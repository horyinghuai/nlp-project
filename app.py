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
    Extracts skills individually.
    Splits by delimiters (comma, fullstop, etc) and newlines.
    CRITICAL: Does NOT split if text is inside parentheses e.g., "Microsoft (Excel, Word)".
    """
    # 1. Join lines with newline to treat as one block
    text = "\n".join(lines)
    
    found_skills = []
    current_skill = ""
    paren_depth = 0
    
    # Delimiters that separate skills
    delimiters = [',', '.', ';', ':', '|', '/', '•', '·', '\n']
    
    for char in text:
        if char == '(':
            paren_depth += 1
            current_skill += char
        elif char == ')':
            if paren_depth > 0:
                paren_depth -= 1
            current_skill += char
        elif char in delimiters and paren_depth == 0:
            # Only split if we are NOT inside parentheses
            clean_skill = current_skill.strip()
            if clean_skill:
                found_skills.append(clean_skill)
            current_skill = ""
        else:
            current_skill += char
            
    # Append the last skill if exists
    if current_skill.strip():
        found_skills.append(current_skill.strip())

    # 2. Filter and Cleanup
    stop_words = ["skills", "technologies", "include", "following", "proficient", "knowledge", "frameworks", "tools", "competencies", "experienced", "with", "ability", "to", "and", "the"]
    final_skills = []
    
    for s in list(set(found_skills)):
        s_clean = s.strip()
        # Filter: length > 1, not just digits, and not a stop word
        if len(s_clean) > 1 and not s_clean.isdigit() and s_clean.lower() not in stop_words:
            final_skills.append(s_clean)
    
    return final_skills

def parse_experience(lines):
    """
    Parses experience into the format:
    Heading: Job Title
    Subheading: Location
    Subheading: Duration
    Normal: Content
    
    Includes checks for "Inc." and other company suffixes.
    """
    jobs = []
    current_job = {
        "title": "", 
        "location": "", 
        "duration": "", 
        "content": [],
        "company": "" 
    }
    
    # Keywords to help identify Job Titles
    job_keywords = [
        "manager", "engineer", "developer", "consultant", "analyst", "intern", "director", 
        "executive", "assistant", "specialist", "officer", "architect", "admin", 
        "head", "vice", "president", "representative", "coordinator", "clerk", "founder", 
        "co-founder", "recruiter", "associate", "lead",
        "trainee", "receptionist", "staff", "crew", "member"
    ]
    
    # Blacklist words: If a line starts with these, it is CONTENT, not a header.
    action_verbs = [
        "leading", "collaborated", "supported", "assisted", "oversaw", "managed", 
        "used", "introduced", "helping", "ensuring", "refined", "created", 
        "developed", "leveraged", "facilitated", "administered", "reducing", "smooth",
        "helped", "held", "organized", "monitored", "handled", "analyzed", 
        "implemented", "optimized", "conducted", "generated", "stored"
    ]
    
    # Whitelist suffixes that end with a period but are allowed in headers
    company_suffixes = ["inc.", "corp.", "ltd.", "co.", "llc.", "p.c.", "pvt.", "dept."]

    # Regex for Durations
    date_pattern = r'\b(19|20)\d{2}\b|present|current|ongoing|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b'

    for i, line in enumerate(lines):
        line_clean = line.strip()
        if not line_clean: continue
        line_lower = line_clean.lower()
        
        # --- Context Checks ---
        is_short_line = len(line_clean) < 100 
        ends_with_period = line_clean.endswith('.') 
        
        # NEW: Check if it's a valid company abbreviation ending in dot
        is_company_suffix = any(line_lower.endswith(s) for s in company_suffixes)

        # Check if the PREVIOUS line looks like it runs into this one
        is_continuation = False
        if i > 0:
            prev_line = lines[i-1].strip().lower()
            if prev_line and (prev_line.endswith(',') or prev_line.endswith('and') or not prev_line[-1] in ['.', '!', '?', ':']):
                 if current_job["content"]:
                     is_continuation = True

        # Check for keywords
        has_job_keyword = False
        for k in job_keywords:
            if re.search(r'\b' + re.escape(k) + r's?\b', line_lower): 
                has_job_keyword = True
                break
        
        has_date = re.search(date_pattern, line_lower)
        starts_with_action = any(line_lower.startswith(v) for v in action_verbs)

        # 1. Job Title Logic
        if (is_short_line and has_job_keyword and not starts_with_action 
            and not is_continuation and not ends_with_period):
            
            if current_job["title"]: 
                current_job["content"] = "\n".join(current_job["content"])
                if not current_job["company"] and current_job["location"]:
                    current_job["company"] = current_job["location"]
                jobs.append(current_job)
                current_job = {"title": "", "location": "", "duration": "", "content": [], "company": ""}
            
            current_job["title"] = line_clean
            continue

        # 2. Duration Logic
        if (is_short_line and has_date and current_job["title"] 
            and not starts_with_action and not is_continuation and not ends_with_period):
            
            if not current_job["duration"]:
                current_job["duration"] = line_clean
            else:
                current_job["duration"] += " | " + line_clean
            continue

        # 3. Location / Company Logic
        # CHANGED: Allow lines ending in period IF they are in the company_suffixes whitelist
        if (is_short_line and not has_date and current_job["title"] 
            and not starts_with_action and not is_continuation 
            and (not ends_with_period or is_company_suffix)):
            
            if not current_job["company"]:
                current_job["company"] = line_clean
            elif not current_job["location"]:
                current_job["location"] = line_clean
            continue
            
        # 4. Content Logic
        current_job["content"].append(line_clean)
            
    # Save the last job entry
    if current_job["title"] or current_job["content"]:
        current_job["content"] = "\n".join(current_job["content"])
        if not current_job["company"] and current_job["location"]:
            current_job["company"] = current_job["location"]
        jobs.append(current_job)
        
    return jobs

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
        "experience": "I separate Job Titles, Locations, Durations and Content.",
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