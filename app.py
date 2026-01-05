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
    Extracts text ONLY from the requested section, stopping strictly at the next header.
    """
    text_lower = text.lower()
    
    headers = {
        "education": ["education", "academic background", "academic history", "qualifications", "education & qualifications"],
        "experience": ["experience", "work history", "employment", "work experience", "professional experience", "career history", "career summary"],
        "skills": ["skills", "technologies", "technical skills", "core competencies", "technical proficiency", "software", "expertise"],
        "projects": ["projects", "personal projects", "academic projects"],
        "references": ["references", "referees"],
        "languages": ["languages"],
        "summary": ["summary", "profile", "objective", "about me"]
    }

    start_index = -1
    target_keywords = headers.get(section_name, [])
    
    # 1. Find Start
    for keyword in target_keywords:
        pattern = r'\b' + re.escape(keyword) + r'[:\n]'
        match = re.search(pattern, text_lower)
        if match:
            start_index = match.start()
            break
            
    if start_index == -1:
        for keyword in target_keywords:
            idx = text_lower.find(keyword)
            if idx != -1:
                start_index = idx
                break
    
    if start_index == -1:
        return []

    # 2. Find End
    end_index = len(text)
    for key, keywords in headers.items():
        if key == section_name: continue
        for keyword in keywords:
            pattern = r'\n\s*' + re.escape(keyword)
            match = re.search(pattern, text_lower[start_index+20:])
            if match:
                real_idx = start_index + 20 + match.start()
                if real_idx < end_index:
                    end_index = real_idx

    # 3. Clean
    raw_section = text[start_index:end_index].strip()
    lines = [line.strip() for line in raw_section.split('\n') if line.strip()]
    
    if lines and any(h in lines[0].lower() for h in target_keywords):
        lines.pop(0)
            
    return lines

def parse_skills(lines):
    """
    Extracts skills individually, splitting by commas/newlines but keeping () together.
    """
    text = " ".join(lines)
    found_skills = []
    
    current_word = []
    paren_depth = 0
    
    # Split by these characters
    delimiters = [',', '•', '·', '|', ';', '/'] 

    for char in text:
        if char == '(': paren_depth += 1
        if char == ')': paren_depth -= 1
        
        # Split ONLY if not inside parentheses
        if (char in delimiters or char == '\n') and paren_depth == 0:
            word = "".join(current_word).strip()
            if word and len(word) > 1:
                found_skills.append(word)
            current_word = []
        else:
            current_word.append(char)
            
    if current_word:
        word = "".join(current_word).strip()
        if word and len(word) > 1:
            found_skills.append(word)

    # Filter out generic words
    stop_words = ["skills", "technologies", "include", "following", "proficient", "knowledge", "frameworks"]
    final_skills = [s for s in found_skills if s.lower() not in stop_words and len(s) < 40]
    
    return list(set(final_skills))

def parse_education(lines):
    educations = []
    current_edu = {}
    
    degree_keywords = ["bachelor", "master", "bsc", "msc", "phd", "diploma", "degree", "certificate", "foundation"]
    uni_keywords = ["university", "college", "institute", "polytechnic", "school", "academy"]
    
    for line in lines:
        line_lower = line.lower()
        is_degree = any(k in line_lower for k in degree_keywords)
        
        if is_degree:
            if current_edu:
                educations.append(current_edu)
            current_edu = {"course": line, "university": "", "location": "", "period": ""}
        
        elif current_edu:
            if any(k in line_lower for k in uni_keywords) and not current_edu["university"]:
                current_edu["university"] = line
            elif re.search(r'\d{4}', line) and not current_edu["period"]:
                current_edu["period"] = line
            elif "," in line and not re.search(r'\d', line) and not current_edu["location"]:
                 current_edu["location"] = line
                 
    if current_edu:
        educations.append(current_edu)
        
    return educations

def parse_experience(lines):
    """
    Strict extraction of Job Titles and Companies to avoid sentences as headers.
    """
    jobs = []
    current_job = {"title": "", "company": "", "content": []}
    
    job_keywords = ["manager", "engineer", "developer", "consultant", "analyst", "intern", "director", "executive", "assistant", "lead", "specialist", "officer", "architect", "admin"]
    company_keywords = ["sdn", "bhd", "inc", "ltd", "corporation", "corp", "company", "solutions", "technologies", "group", "services", "limited"]

    for line in lines:
        line_clean = line.strip()
        line_lower = line_clean.lower()
        
        # Validation checks
        is_date = re.search(r'20\d\d|19\d\d|present', line_lower)
        is_job_keyword = any(k in line_lower for k in job_keywords)
        is_company_keyword = any(k in line_lower for k in company_keywords)
        
        # A line is a "Header Candidate" if it's short, has no period at end, and contains keywords
        is_header_candidate = len(line_clean) < 50 and not line_clean.endswith('.')
        
        # 1. New Job Entry Trigger
        if (is_job_keyword or is_date) and len(current_job["content"]) > 1:
            # Save previous job
            current_job["content"] = " ".join(current_job["content"])
            jobs.append(current_job)
            current_job = {"title": "", "company": "", "content": []}

        # 2. Identify Job Title
        if not current_job["title"]:
            if is_header_candidate and (is_job_keyword or line_clean.isupper() or len(line_clean) < 40):
                # Don't take it if it looks like a date line only
                if not (is_date and len(line_clean) < 15): 
                    current_job["title"] = line_clean
                    continue # Move to next line

        # 3. Identify Company
        if not current_job["company"]:
            if is_header_candidate and (is_company_keyword or " at " in line_lower):
                current_job["company"] = line_clean
                continue

        # 4. Fallback: If still no title/company, check strict "First Line" rule
        # Only treat first lines as headers if they are NOT sentences
        if not current_job["title"] and not current_job["company"] and not current_job["content"]:
            if is_header_candidate and not is_date:
                current_job["title"] = line_clean
                continue

        # 5. Content
        current_job["content"].append(line_clean)
            
    # Save last job
    if current_job["title"] or current_job["content"]:
        current_job["content"] = " ".join(current_job["content"])
        jobs.append(current_job)
        
    return jobs

def analyze_resume(text):
    data = {
        "name": "Not Found",
        "email": "Not Found",
        "skills": [],
        "education": [],
        "experience": []
    }

    # 1. Email
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if email_match:
        data["email"] = email_match.group(0)

    # 2. Name
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        if "resume" not in lines[0].lower():
            data["name"] = lines[0]
        else:
            data["name"] = lines[1] if len(lines) > 1 else "Unknown"

    # 3. Skills
    raw_skills = extract_section(text, "skills")
    data["skills"] = parse_skills(raw_skills)

    # 4. Education
    raw_edu = extract_section(text, "education")
    data["education"] = parse_education(raw_edu)
    
    # 5. Experience
    raw_exp = extract_section(text, "experience")
    data["experience"] = parse_experience(raw_exp)

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
        "upload": "Click 'Choose PDF' to select a file.",
        "format": "We only support PDF files.",
        "experience": "I separate Job Titles and Companies, ensuring sentences stay in the description.",
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