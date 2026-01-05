import os
import re
from flask import Flask, render_template, request, redirect, url_for, jsonify
from pypdf import PdfReader

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- NLP CORE LOGIC ---
def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_section(text, section_name):
    """
    Extracts text between a specific section header and the next known header.
    """
    text_lower = text.lower()
    
    # Expanded headers to fix overlap issues and include Achievements in Experience
    headers = {
        "education": [
            "education", "academic background", "academic history", 
            "qualifications", "educational qualifications"
        ],
        "experience": [
            "experience", "work history", "employment", "work experience", 
            "professional experience", "career history", "career summary",
            "achievements", "key achievements", "professional background"
        ],
        "skills": [
            "skills", "technologies", "technical skills", "core competencies", 
            "technical proficiency", "skills & expertise", "software skills"
        ],
        "projects": ["projects", "personal projects", "academic projects"],
        "references": ["references"]
    }

    # Find start index of the requested section
    start_index = -1
    for keyword in headers.get(section_name, []):
        # We look for the keyword followed by a newline or colon to be safer
        idx = text_lower.find(keyword)
        if idx != -1:
            start_index = idx
            break
    
    if start_index == -1:
        return []

    # Find the nearest start of ANY other section to determine the end
    end_index = len(text)
    for key, keywords in headers.items():
        # Don't stop at keywords belonging to the SAME section 
        # (e.g., don't let "Achievements" stop "Experience" since we want them merged)
        if key == section_name: 
            continue
            
        for keyword in keywords:
            idx = text_lower.find(keyword, start_index + 20) # +20 buffer to skip the current header
            if idx != -1 and idx < end_index:
                end_index = idx

    # Extract the raw block
    raw_section = text[start_index:end_index].strip()
    
    # Split into lines and clean up
    lines = [line.strip() for line in raw_section.split('\n') if line.strip()]
    
    # Remove the header itself if it appears in the first few lines
    if lines:
        first_line_lower = lines[0].lower()
        if any(h in first_line_lower for h in headers[section_name]):
            lines.pop(0)
            
    return lines

def analyze_resume(text):
    data = {
        "name": "Not Found",
        "emails": [],
        "phones": [],
        "skills": [],
        "education": [],
        "experience": []
    }

    # 1. Extract ALL Emails
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    data["emails"] = list(set(re.findall(email_pattern, text)))

    # 2. Extract ALL Phones
    phone_pattern = r'(\+?6?01)[0-46-9]-*[0-9]{7,8}'
    data["phones"] = list(set(re.findall(phone_pattern, text)))

    # 3. Extract Skills (Hybrid: Keywords + Section Parsing)
    found_skills = []
    
    # A. predefined high-value keywords
    skills_db = ['Python', 'Java', 'C++', 'SQL', 'HTML', 'CSS', 'JavaScript', 
                 'Machine Learning', 'NLP', 'Communication', 'Leadership', 'Excel',
                 'Git', 'Docker', 'Flask', 'React', 'Project Management', 'AWS', 'Azure']
    
    lower_text = text.lower()
    for skill in skills_db:
        if skill.lower() in lower_text:
            found_skills.append(skill)
            
    # B. Extract everything from the "Skills" section
    skills_section_lines = extract_section(text, "skills")
    for line in skills_section_lines:
        # Split line by common delimiters (comma, bullet points, pipe)
        parts = re.split(r'[,|•·\t]', line)
        for part in parts:
            clean_part = part.strip()
            # Filter out junk/empty strings
            if len(clean_part) > 1 and len(clean_part) < 30: 
                found_skills.append(clean_part)

    data["skills"] = list(set(found_skills))

    # 4. Extract Name
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        if "resume" not in lines[0].lower():
            data["name"] = lines[0]
        else:
            data["name"] = lines[1] if len(lines) > 1 else "Unknown"

    # 5. Extract Education
    data["education"] = extract_section(text, "education")
    
    # 6. Extract Experience (Includes Achievements now)
    data["experience"] = extract_section(text, "experience")

    return data

# --- ROUTES ---
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        raw_text = extract_text_from_pdf(filepath)
        extracted_data = analyze_resume(raw_text)
        os.remove(filepath)
        return render_template('result.html', data=extracted_data)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '').lower()
    responses = {
        "upload": "Click 'Choose PDF' to select a file. You can see the filename and cancel if needed before analyzing.",
        "format": "We only support PDF files.",
        "experience": "I group 'Work History' and 'Achievements' into the Experience section.",
        "manual": "Check 'README_System_Manual.txt' in the folder.",
        "hello": "Hi! I'm your Resume Assistant.",
        "default": "I can help with uploading, formats, and explaining how I work."
    }
    
    reply = responses["default"]
    if any(x in user_message for x in ["upload", "start", "file"]): reply = responses["upload"]
    elif "format" in user_message or "pdf" in user_message: reply = responses["format"]
    elif "experience" in user_message or "education" in user_message: reply = responses["experience"]
    elif "hello" in user_message or "hi" in user_message: reply = responses["hello"]
    elif "manual" in user_message: reply = responses["manual"]

    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run(debug=True)