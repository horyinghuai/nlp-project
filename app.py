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
    
    # Comprehensive list of headers to define boundaries
    headers = {
        "education": ["education", "academic background", "academic history", "qualifications", "education & qualifications"],
        "experience": ["experience", "work history", "employment", "work experience", "professional experience", "career history", "career summary"],
        "skills": ["skills", "technologies", "technical skills", "core competencies", "technical proficiency", "software", "expertise"],
        "projects": ["projects", "personal projects", "academic projects"],
        "references": ["references", "referees"],
        "languages": ["languages"],
        "summary": ["summary", "profile", "objective", "about me"]
    }

    # 1. Find the start of the section
    start_index = -1
    target_keywords = headers.get(section_name, [])
    
    for keyword in target_keywords:
        # We search for the keyword followed by a newline or colon for accuracy
        pattern = r'\b' + re.escape(keyword) + r'[:\n]'
        match = re.search(pattern, text_lower)
        if match:
            start_index = match.start()
            break
            
    if start_index == -1:
        # Fallback: lenient search
        for keyword in target_keywords:
            idx = text_lower.find(keyword)
            if idx != -1:
                start_index = idx
                break
    
    if start_index == -1:
        return []

    # 2. Find the END of the section (the nearest NEXT header)
    end_index = len(text)
    
    for key, keywords in headers.items():
        if key == section_name: continue # Don't stop at own header
        for keyword in keywords:
            # Look for other headers AFTER the start_index
            # We add a buffer of 20 chars to skip the current header itself
            pattern = r'\n\s*' + re.escape(keyword) # Look for headers at start of lines
            match = re.search(pattern, text_lower[start_index+20:])
            if match:
                real_idx = start_index + 20 + match.start()
                if real_idx < end_index:
                    end_index = real_idx

    # 3. Extract and Clean
    raw_section = text[start_index:end_index].strip()
    lines = [line.strip() for line in raw_section.split('\n') if line.strip()]
    
    # Remove the header itself from the extracted lines
    if lines and any(h in lines[0].lower() for h in target_keywords):
        lines.pop(0)
            
    return lines

def parse_skills(lines):
    """
    Extracts skills, keeping text inside () together.
    """
    text = " ".join(lines)
    found_skills = []
    
    # Custom splitter: split by commas/bullets BUT NOT inside parentheses
    current_word = []
    paren_depth = 0
    
    for char in text:
        if char == '(': paren_depth += 1
        if char == ')': paren_depth -= 1
        
        # Split on comma or bullet points if we are NOT inside parens
        if (char in [',', '•', '·', '|'] or (char == '\n')) and paren_depth == 0:
            word = "".join(current_word).strip()
            if word and len(word) > 1: # Filter empty/single chars
                found_skills.append(word)
            current_word = []
        else:
            current_word.append(char)
            
    # Add last word
    if current_word:
        word = "".join(current_word).strip()
        if word and len(word) > 1:
            found_skills.append(word)

    # Clean up: remove generic words if they sneaked in
    stop_words = ["skills", "technologies", "include", "following"]
    final_skills = [s for s in found_skills if s.lower() not in stop_words]
    
    return list(set(final_skills))

def parse_education(lines):
    """
    Extracts Course, Uni, Location, Period from Education lines.
    """
    educations = []
    current_edu = {}
    
    # Heuristics
    degree_keywords = ["bachelor", "master", "bsc", "msc", "phd", "diploma", "degree", "certificate", "foundation"]
    uni_keywords = ["university", "college", "institute", "polytechnic", "school", "academy"]
    
    for line in lines:
        line_lower = line.lower()
        
        # Check if line looks like a Degree/Course
        is_degree = any(k in line_lower for k in degree_keywords)
        
        # If we hit a new degree, save previous and start new
        if is_degree:
            if current_edu:
                educations.append(current_edu)
            current_edu = {"course": line, "university": "", "location": "", "period": ""}
        
        elif current_edu:
            # Try to identify other fields based on current_edu context
            
            # University?
            if any(k in line_lower for k in uni_keywords) and not current_edu["university"]:
                current_edu["university"] = line
                
            # Period? (Look for years like 2018 - 2022)
            elif re.search(r'\d{4}', line) and not current_edu["period"]:
                current_edu["period"] = line
                
            # Location? (Usually short, contains comma, not a date/uni/degree)
            elif "," in line and not re.search(r'\d', line) and not current_edu["location"]:
                 current_edu["location"] = line
                 
    if current_edu:
        educations.append(current_edu)
        
    return educations

def parse_experience(lines):
    """
    Extracts Job Title, Company, and Merged Content.
    Structure: Job Title (Heading), Company (Subheading), Content (Paragraph).
    """
    jobs = []
    current_job = {"title": "", "company": "", "content": []}
    
    # Common job titles to help identify headers
    job_titles = ["manager", "engineer", "developer", "consultant", "analyst", "intern", "director", "executive", "assistant", "lead", "specialist", "officer"]
    
    for line in lines:
        line_lower = line.lower()
        
        # Check if line is a Date line (often separates jobs)
        is_date = re.search(r'20\d\d|19\d\d|present', line_lower)
        # Check if line is a likely Job Title
        is_title = any(t in line_lower for t in job_titles)
        
        # If it looks like a Start of a new block (Date or Title) AND we have content
        if (is_title or is_date) and len(current_job["content"]) > 2:
            # Save previous
            current_job["content"] = " ".join(current_job["content"]) # Merge lines
            jobs.append(current_job)
            current_job = {"title": "", "company": "", "content": []}

        # Heuristic to fill fields
        if not current_job["title"] and is_title:
            current_job["title"] = line
        elif not current_job["company"] and ("company" in line_lower or "sdn bhd" in line_lower or "ltd" in line_lower):
            current_job["company"] = line
        elif not current_job["title"] and not current_job["company"]:
            # If we don't have title/company yet, first lines are usually them
            if is_date: 
                 # Often date is on same line or near title, ignore for now or add to content?
                 # Let's add to content to be safe, or try to extract title.
                 pass 
            else:
                 # Guess: First line is Title
                 current_job["title"] = line
        else:
            # Everything else is content
            current_job["content"].append(line)
            
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

    # 1. Extract Email
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = list(set(re.findall(email_pattern, text)))
    if emails:
        data["email"] = emails[0] # Just take the first one

    # 2. Extract Name
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        if "resume" not in lines[0].lower():
            data["name"] = lines[0]
        else:
            data["name"] = lines[1] if len(lines) > 1 else "Unknown"

    # 3. Extract Skills (Parsed from field only, keeping () together)
    raw_skills = extract_section(text, "skills")
    data["skills"] = parse_skills(raw_skills)

    # 4. Extract Education (Structured)
    raw_edu = extract_section(text, "education")
    data["education"] = parse_education(raw_edu)
    
    # 5. Extract Experience (Structured & Neat)
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
        "upload": "Click 'Choose PDF' to select a file. You can see the filename and cancel if needed before analyzing.",
        "format": "We only support PDF files.",
        "experience": "I separate Job Titles and Companies, and merge the descriptions into neat paragraphs.",
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