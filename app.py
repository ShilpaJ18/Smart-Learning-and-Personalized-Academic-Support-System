import gradio as gr
import google.generativeai as genai
import json
import os
import re
import datetime
from fpdf import FPDF
import pypdf

# ── CONFIG ────────────────────────────────────────────────────────────────────
HISTORY_FILE = "history.json"
NOTES_DIR    = "generated_notes"
os.makedirs(NOTES_DIR, exist_ok=True)

def get_model():
    API_KEY = "your gemnini api key"  # 👈 paste your Gemini API key here
    genai.configure(api_key=API_KEY)
    return genai.GenerativeModel("gemini-2.5-flash")

# ── HISTORY ───────────────────────────────────────────────────────────────────
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_history(record: dict):
    data = load_history()
    data.append(record)
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def update_history_score(subject: str, score_str: str):
    data = load_history()
    for rec in reversed(data):
        if rec.get("subject", "") == subject and rec.get("score", "") == "—":
            rec["score"] = score_str
            break
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

# FIX 1: New function to update flashcard score specifically
def update_history_fc_score(subject: str, score_str: str):
    """Update history score only for records that have '—' or a previous flashcard score (not quiz scores)."""
    data = load_history()
    for rec in reversed(data):
        if rec.get("subject", "") == subject:
            current = rec.get("score", "—")
            # Only update if score is '—' or already a flashcard score (not a quiz score)
            if current == "—" or current.startswith("Flashcards:"):
                rec["score"] = score_str
                break
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_history_table():
    rows = load_history()
    if not rows:
        return [["No history yet", "—", "—", "—"]]
    return [[r.get("timestamp",""), r.get("subject",""),
             r.get("topics",""), r.get("score","—")] for r in reversed(rows)]

# ── CONFIDENCE ────────────────────────────────────────────────────────────────
CONF_FILE = "confidence.json"

def load_conf():
    if not os.path.exists(CONF_FILE):
        return {}
    try:
        with open(CONF_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_conf(data):
    with open(CONF_FILE, "w") as f:
        json.dump(data, f, indent=2)

def update_conf(topic: str, score_pct: float):
    d = load_conf()
    if topic not in d:
        d[topic] = []
    d[topic].append(round(score_pct, 1))
    save_conf(d)

# FIX 2: Removed Trend and Sessions columns
def get_conf_table():
    d = load_conf()
    if not d:
        return [["No data yet", "—", "—"]]
    rows = []
    for topic, scores in d.items():
        avg    = round(sum(scores) / len(scores), 1)
        status = "Strong" if avg >= 75 else ("OK" if avg >= 50 else "Weak")
        rows.append([topic, f"{avg}%", status])
    rows.sort(key=lambda x: float(x[1].replace("%", "")))
    return rows

# ── PDF SAFE ENCODING ─────────────────────────────────────────────────────────
REPLACEMENTS = {
    "\u2014": "-",  "\u2013": "-",  "\u2018": "'",  "\u2019": "'",
    "\u201c": '"',  "\u201d": '"',  "\u2022": "-",  "\u2192": "->",
    "\u2190": "<-", "\u2191": "^",  "\u2193": "v",  "\u2264": "<=",
    "\u2265": ">=", "\u00b0": "deg","\u03b1": "alpha","\u03b2": "beta",
    "\u03c0": "pi", "\u2026": "...","\u2260": "!=", "\u00b1": "+/-",
    "\u00d7": "x",  "\u00f7": "/",  "\u221a": "sqrt","\u03c3": "sigma",
    "\u03bb": "lambda", "\u00e9": "e", "\u00e8": "e", "\u00ea": "e",
    "\u00e0": "a",  "\u00e2": "a",  "\u00f4": "o",  "\u00fb": "u",
    "\u00f9": "u",  "\u00ee": "i",  "\u00ef": "i",  "\u00e7": "c",
    "\u00fc": "u",  "\u00e4": "a",  "\u00f6": "o",  "\u00df": "ss",
    "\u25b8": ">",
}

def safe_str(text):
    for ch, rep in REPLACEMENTS.items():
        text = text.replace(ch, rep)
    return text.encode("latin-1", "replace").decode("latin-1")

# ── CLEAN PLAIN TEXT ─────────────────────────────────────────────────────────
def clean_notes_text(raw: str) -> str:
    lines = raw.split("\n")
    out   = []
    for line in lines:
        stripped = line.strip()
        indent   = len(line) - len(line.lstrip())
        if not stripped:
            out.append("")
            continue
        stripped = re.sub(r'\*\*(.*?)\*\*', r'\1', stripped)
        stripped = re.sub(r'\*(.*?)\*',     r'\1', stripped)
        stripped = re.sub(r'^#+\s*', '',            stripped)
        if re.match(r'^\*\s+', stripped):
            stripped = "  • " + stripped[2:]
        elif re.match(r'^-\s+', stripped) and not re.match(r'^\d', stripped):
            stripped = "  • " + stripped[2:]
        if indent >= 8:
            stripped = "      " + stripped
        elif indent >= 4:
            stripped = "    " + stripped
        out.append(stripped)
    return "\n".join(out)

# ── PDF GENERATOR ─────────────────────────────────────────────────────────────
def make_pdf(clean_content: str, filename: str, title: str) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, safe_str(title.upper()), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)
    for line in clean_content.split("\n"):
        s = line.strip()
        if not s:
            pdf.ln(3); continue
        if re.match(r'^\d+\.', s):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(26, 26, 46)
            pdf.multi_cell(0, 8, safe_str(s), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0); continue
        if "EXAM SUMMARY" in s.upper():
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_fill_color(91, 79, 255)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(0, 9, safe_str(s), new_x="LMARGIN", new_y="NEXT", fill=True)
            pdf.set_text_color(0, 0, 0); pdf.ln(2); continue
        if s.isupper() and len(s) < 60:
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 7, safe_str(s), new_x="LMARGIN", new_y="NEXT"); continue
        if s.startswith("  •") or s.startswith("•"):
            pdf.set_font("Helvetica", size=11)
            pdf.multi_cell(0, 6, safe_str(s), new_x="LMARGIN", new_y="NEXT"); continue
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 7, safe_str(line), new_x="LMARGIN", new_y="NEXT")
    path = os.path.join(NOTES_DIR, filename)
    pdf.output(path)
    return path

# ── HTML FORMATTER ────────────────────────────────────────────────────────────
def format_notes_html(raw: str) -> str:
    if not raw:
        return ""
    lines = raw.split("\n")
    out   = []
    for line in lines:
        s      = line.strip()
        indent = len(line) - len(line.lstrip())
        if not s:
            out.append("<div style='height:6px'></div>"); continue
        if "EXAM SUMMARY" in s.upper():
            clean = re.sub(r'\*\*|\*|##', '', s).strip()
            out.append(
                f"<div style='font-family:Syne,sans-serif;font-size:13px;font-weight:800;"
                f"color:#fff;background:#5b4fff;border-radius:8px;padding:9px 14px;"
                f"margin:22px 0 10px;letter-spacing:.04em'>{clean}</div>"
            ); continue
        if re.match(r'^\d+\.', s):
            clean = re.sub(r'\*\*(.*?)\*\*', r'\1', s)
            clean = re.sub(r'\*(.*?)\*',     r'\1', clean)
            out.append(
                f"<div style='font-family:Syne,sans-serif;font-size:16px;font-weight:800;"
                f"color:#1a1a2e;margin:22px 0 8px;padding-left:14px;"
                f"border-left:4px solid #5b4fff;line-height:1.4'>{clean}</div>"
            ); continue
        if (s.startswith("**") and s.endswith("**") and len(s) > 4) or s.startswith("##"):
            inner = re.sub(r'\*\*|##', '', s).strip()
            out.append(
                f"<div style='font-family:Syne,sans-serif;font-size:13px;font-weight:700;"
                f"color:#1a1a2e;background:rgba(91,79,255,.06);border-radius:6px;"
                f"padding:5px 10px;margin:12px 0 5px;display:inline-block'>{inner}</div>"
            ); continue
        if indent >= 8 and re.match(r'^\*\s|^-\s', s):
            content = re.sub(r'^[\*\-]\s+', '', s)
            content = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#1a1a2e">\1</b>', content)
            content = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', content)
            out.append(
                f"<div style='font-size:12px;color:#5f5e5a;padding:2px 0 2px 40px;"
                f"position:relative;line-height:1.65'>"
                f"<span style='position:absolute;left:26px;color:#aaa9ec'>–</span>{content}</div>"
            ); continue
        if re.match(r'^\*\s|^-\s|^•\s', s):
            content = re.sub(r'^[\*\-•]\s+', '', s)
            content = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#1a1a2e">\1</b>', content)
            content = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', content)
            out.append(
                f"<div style='font-size:13px;color:#3a3a42;padding:3px 0 3px 22px;"
                f"position:relative;line-height:1.65'>"
                f"<span style='position:absolute;left:6px;color:#5b4fff;font-weight:700'>▸</span>"
                f"{content}</div>"
            ); continue
        s2 = re.sub(r'\*\*(.*?)\*\*', r'<b style="color:#1a1a2e">\1</b>', s)
        s2 = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', s2)
        out.append(
            f"<div style='font-size:13px;color:#3a3a42;line-height:1.75;padding:2px 0'>{s2}</div>"
        )
    return "".join(out)

# ── PDF SYLLABUS PARSER ───────────────────────────────────────────────────────
def parse_syllabus_pdf(pdf_file):
    if pdf_file is None:
        return "", "No PDF uploaded."
    try:
        text = ""
        reader = pypdf.PdfReader(pdf_file)
        for page in reader.pages:
            text += page.extract_text() or ""
        if not text.strip():
            return "", "PDF appears empty."
        resp   = get_model().generate_content(
            "Extract the main study topics from this syllabus. "
            "Return ONLY a comma-separated list of topic names, nothing else.\n\n"
            + text[:6000]
        )
        topics = resp.text.strip()
        return topics, f"Extracted {len(topics.split(','))} topics from PDF."
    except Exception as e:
        return "", f"Error: {e}"

# ── JSON EXTRACTOR ────────────────────────────────────────────────────────────
def extract_json_array(raw: str):
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return None

# ── NOTES GENERATOR ───────────────────────────────────────────────────────────
def generate_notes(subject, topics, depth):
    if not subject.strip() or not topics.strip():
        return "", "", None, "Please enter subject and topics."
    try:
        depth_inst = {
            "Brief (exam summary)": "Keep each topic concise — 3-5 bullet points max.",
            "Standard":             "Cover definitions, key concepts, and one example per topic.",
            "Deep (full detail)":   "Provide thorough explanations, sub-topics, examples, and edge cases.",
        }.get(depth, "Standard coverage.")
        prompt = (
            f"Generate structured study notes for subject: '{subject}'.\n"
            f"Topics to cover: {topics}\n"
            f"Depth: {depth_inst}\n\n"
            "Format rules:\n"
            "- Numbered sections per topic (e.g. 1. Topic Name)\n"
            "- Use ** for sub-headings\n"
            "- Use * for bullet points\n"
            "- Include definitions, concepts, examples\n"
            "- End with EXAM SUMMARY section\n"
            "Output only the notes content, nothing else."
        )
        raw_notes   = get_model().generate_content(prompt).text.strip()
        html_notes  = format_notes_html(raw_notes)
        clean_notes = clean_notes_text(raw_notes)
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{subject.replace(' ', '_')}_{ts}.pdf"
        path  = make_pdf(clean_notes, fname, f"{subject} Study Notes")
        save_history({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "subject":   subject, "topics": topics,
            "notes":     clean_notes, "pdf": path, "score": "—",
        })
        return html_notes, clean_notes, path, f"Notes ready for: {subject}"
    except Exception as e:
        return "", "", None, f"Error generating notes: {e}"

# ── QUIZ BUILDER ──────────────────────────────────────────────────────────────
def build_quiz(notes, subject):
    if not notes or not notes.strip():
        return [], "No notes found. Generate notes first."
    try:
        prompt = (
            f"Create exactly 10 multiple-choice questions based ONLY on these notes for '{subject}'.\n\n"
            f"NOTES:\n{notes[:5000]}\n\n"
            "Rules:\n"
            "- First 5 must be SCENARIO-BASED: begin with 'Scenario: '\n"
            "- Last 5 must be NORMAL direct concept/fact questions\n"
            "- Each question has exactly 4 options\n\n"
            "Return ONLY a valid JSON array, no markdown, no extra text:\n"
            '[{"q":"...","options":["A) ...","B) ...","C) ...","D) ..."],"answer":0,"topic":"...","type":"scenario"}]\n'
            "type='scenario' for Q1-5, 'normal' for Q6-10. 'answer' is 0-based index."
        )
        raw = get_model().generate_content(prompt).text.strip()
        qs  = extract_json_array(raw)
        if not qs:
            return [], "Could not parse quiz JSON. Try again."
        return qs, f"{len(qs)} questions ready."
    except Exception as e:
        return [], f"Quiz error: {e}"

# ── RE-QUIZ ───────────────────────────────────────────────────────────────────
def build_requiz(weak_topics, notes, subject):
    if not weak_topics:
        return [], "No weak topics detected."
    try:
        prompt = (
            f"Create 6 harder multiple-choice questions targeting ONLY these weak topics: {', '.join(weak_topics)}\n"
            f"Subject: {subject}\nNotes:\n{notes[:3000]}\n\n"
            "Return ONLY valid JSON array, no markdown:\n"
            '[{"q":"...","options":["A) ...","B) ...","C) ...","D) ..."],"answer":0,"topic":"..."}]'
        )
        raw = get_model().generate_content(prompt).text.strip()
        qs  = extract_json_array(raw)
        if not qs:
            return [], "Could not parse re-quiz. Try again."
        return qs, f"{len(qs)} targeted questions ready."
    except Exception as e:
        return [], f"Re-quiz error: {e}"

# ── FLASHCARDS ────────────────────────────────────────────────────────────────
def build_flashcards(notes, subject):
    if not notes or not notes.strip():
        return None, "No notes found."
    try:
        prompt = (
            f"Create 8 flashcard questions from these notes for '{subject}'.\n"
            "Each needs a short written answer (1-3 sentences).\n"
            f"Notes:\n{notes[:3000]}\n\n"
            "Return ONLY valid JSON array, no markdown:\n"
            '[{"question":"...","answer":"...","topic":"..."}]'
        )
        raw   = get_model().generate_content(prompt).text.strip()
        cards = extract_json_array(raw)
        if not cards:
            return None, "Could not parse flashcards. Try again."
        return cards, f"{len(cards)} flashcards ready."
    except Exception as e:
        return None, f"Flashcard error: {e}"

def eval_flashcard(user_ans, ideal_ans, question):
    """Returns (score 0-100, grade 'correct'|'partial'|'wrong', feedback)"""
    if not user_ans.strip():
        return 0, "wrong", "No answer provided."
    try:
        prompt = (
            f"Evaluate this student answer strictly.\n"
            f"Question: {question}\n"
            f"Ideal answer: {ideal_ans}\n"
            f"Student answer: {user_ans}\n\n"
            "Grading rules:\n"
            "- Score 75-100 = Correct (student got the key concept right)\n"
            "- Score 40-74  = Partial (student got some but missed key parts)\n"
            "- Score 0-39   = Wrong (incorrect or too vague)\n\n"
            "Return ONLY JSON, no markdown:\n"
            '{"score":80,"grade":"correct","feedback":"brief feedback max 1 sentence"}'
        )
        raw  = get_model().generate_content(prompt).text.strip()
        raw  = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        score = int(data.get("score", 0))
        grade = data.get("grade", "wrong")
        if grade not in ("correct", "partial", "wrong"):
            grade = "correct" if score >= 75 else ("partial" if score >= 40 else "wrong")
        return score, grade, data.get("feedback", "Evaluated.")
    except Exception as e:
        return 0, "wrong", f"Error: {e}"

# ── FLASHCARD SCORE CALCULATOR ────────────────────────────────────────────────
def calc_fc_score(scores_list):
    total  = len(scores_list)
    weight = 0.0
    correct = partial = wrong = attempted = 0
    for s in scores_list:
        if s is None:
            continue
        attempted += 1
        g = s.get("grade", "wrong")
        if g == "correct":
            weight  += 1.0
            correct += 1
        elif g == "partial":
            weight  += 0.5
            partial += 1
        else:
            wrong += 1
    pct = round(weight / total * 100) if total > 0 else 0
    return pct, correct, partial, wrong, attempted

# ── FC QUESTION HTML ──────────────────────────────────────────────────────────
def fc_question_html(card, idx, total, scores_list):
    answered = len([s for s in scores_list if s is not None])
    return (
        f"<div style='background:#ffffff;border:2px solid #5b4fff;border-radius:14px;"
        f"padding:20px 24px;box-shadow:0 2px 12px rgba(91,79,255,.1)'>"
        f"<div style='font-size:16px;font-weight:700;color:#1a1a2e;line-height:1.6'>"
        f"{card['question']}</div>"
        f"<div style='margin-top:10px;display:flex;align-items:center;gap:10px'>"
        f"<span style='font-size:11px;color:#5b4fff;font-weight:700;background:rgba(91,79,255,.1);"
        f"padding:3px 10px;border-radius:20px'>{card.get('topic','')}</span>"
        f"<span style='font-size:11px;color:#7a7a8a;font-weight:500'>"
        f"Card {idx+1} of {total} &nbsp;·&nbsp; {answered} answered</span>"
        f"</div></div>"
    )

def fc_final_html(pct, correct, partial, wrong, attempted, total):
    col = "#00a688" if pct >= 75 else ("#f59e0b" if pct >= 50 else "#d43a4a")
    unattempted = total - attempted
    return (
        f"<div style='background:#ffffff;border:2px solid {col};border-radius:16px;"
        f"padding:28px 32px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.08)'>"
        f"<div style='font-family:Syne,sans-serif;font-size:14px;font-weight:700;"
        f"color:#7a7a8a;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px'>"
        f"Final Score</div>"
        f"<div style='font-family:Syne,sans-serif;font-size:48px;font-weight:800;color:{col}'>"
        f"{pct}%</div>"
        f"<div style='font-size:13px;color:#3a3a42;margin-top:8px'>"
        f"Based on {total} questions</div>"
        f"<div style='display:flex;justify-content:center;gap:16px;margin-top:16px;flex-wrap:wrap'>"
        f"<div style='background:#EAF3DE;border-radius:10px;padding:10px 18px;min-width:80px'>"
        f"<div style='font-size:22px;font-weight:800;color:#27500A'>{correct}</div>"
        f"<div style='font-size:11px;color:#3B6D11;font-weight:600'>Correct (+1)</div></div>"
        f"<div style='background:#FAEEDA;border-radius:10px;padding:10px 18px;min-width:80px'>"
        f"<div style='font-size:22px;font-weight:800;color:#633806'>{partial}</div>"
        f"<div style='font-size:11px;color:#854F0B;font-weight:600'>Partial (+0.5)</div></div>"
        f"<div style='background:#FCEBEB;border-radius:10px;padding:10px 18px;min-width:80px'>"
        f"<div style='font-size:22px;font-weight:800;color:#501313'>{wrong}</div>"
        f"<div style='font-size:11px;color:#A32D2D;font-weight:600'>Wrong (+0)</div></div>"
        f"<div style='background:#F1EFE8;border-radius:10px;padding:10px 18px;min-width:80px'>"
        f"<div style='font-size:22px;font-weight:800;color:#444441'>{unattempted}</div>"
        f"<div style='font-size:11px;color:#5F5E5A;font-weight:600'>Skipped (+0)</div></div>"
        f"</div>"
        f"<div style='font-size:12px;color:#7a7a8a;margin-top:14px'>"
        f"Formula: (Correct × 1 + Partial × 0.5) ÷ {total} × 100</div>"
        f"</div>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap');

:root {
    --ink: #0d0d0f; --ink2: #3a3a42; --ink3: #7a7a8a;
    --paper: #f7f6f2; --surface: #ffffff;
    --accent: #5b4fff;
}
body, .gradio-container {
    font-family: 'DM Sans', sans-serif !important;
    background: var(--paper) !important;
    color: var(--ink) !important;
}
.app-header {
    background: var(--ink); border-radius: 18px;
    padding: 28px 32px 24px; margin-bottom: 20px;
    position: relative; overflow: hidden;
}
.app-header::before {
    content: ''; position: absolute;
    top: -50px; right: -50px; width: 180px; height: 180px;
    background: var(--accent); border-radius: 50%; opacity: .15;
}
.app-title {
    font-family: 'Syne', sans-serif !important;
    font-size: 2rem; font-weight: 800; color: #fff;
    letter-spacing: -.03em; margin-bottom: 4px;
}
.app-sub { color: rgba(255,255,255,.5); font-size: .85rem; }
.step-pill {
    display: inline-block; font-family: 'Syne', sans-serif;
    font-size: 10px; font-weight: 700; letter-spacing: .1em;
    text-transform: uppercase; padding: 3px 10px;
    border-radius: 20px; margin-bottom: 10px;
}
.pill-1 { background: rgba(91,79,255,.12); color: #3c3489; }
.pill-2 { background: rgba(0,201,167,.12); color: #007a63; }
.pill-3 { background: rgba(255,91,107,.12); color: #a0222f; }
.pill-4 { background: rgba(245,158,11,.12); color: #8a5e00; }

.block > label > span:first-child {
    font-family: 'Syne', sans-serif !important;
    font-size: 11px !important; font-weight: 700 !important;
    text-transform: uppercase !important; letter-spacing: .06em !important;
    color: var(--ink2) !important;
}

/* ── FLASHCARD SECTION — force white background everywhere ── */
.flashcard-wrap {
    background: #f7f6f2 !important;
    border-radius: 16px !important;
    padding: 16px !important;
}
.flashcard-wrap * {
    --bg: #ffffff;
}

/* ── RADIO — white cards ── */
[role="radiogroup"] {
    background: transparent !important;
    gap: 5px !important; display: flex !important;
    flex-direction: column !important;
}
[role="radiogroup"] label {
    background: #ffffff !important;
    border: 1.5px solid rgba(0,0,0,.1) !important;
    border-radius: 9px !important;
    padding: 10px 16px !important; margin: 0 0 4px 0 !important;
    cursor: pointer !important;
    transition: border-color .15s, background .15s !important;
    display: flex !important; align-items: center !important; gap: 10px !important;
}
[role="radiogroup"] label:hover {
    border-color: var(--accent) !important;
    background: rgba(91,79,255,.04) !important;
}
[role="radiogroup"] label:has(input:checked) {
    border-color: var(--accent) !important;
    background: rgba(91,79,255,.08) !important;
}
[role="radiogroup"] label span,
[role="radiogroup"] label p,
[role="radiogroup"] span {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 13px !important; font-weight: 400 !important;
    text-transform: none !important; letter-spacing: 0 !important;
    color: #0d0d0f !important;
}

input[type=text], textarea, select {
    font-family: 'DM Sans', sans-serif !important;
    border-radius: 10px !important;
    border: 1.5px solid rgba(0,0,0,.1) !important;
    background: var(--paper) !important; color: var(--ink) !important;
    font-size: 13px !important;
    transition: border-color .2s, box-shadow .2s !important;
}
input:focus, textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(91,79,255,.12) !important;
    outline: none !important;
}
button.primary, .gr-button-primary {
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important; font-size: 13px !important;
    background: var(--accent) !important; color: #fff !important;
    border: none !important; border-radius: 10px !important;
    cursor: pointer !important;
    transition: all .22s cubic-bezier(.34,1.56,.64,1) !important;
    box-shadow: 0 4px 14px rgba(91,79,255,.28) !important;
}
button.primary:hover {
    transform: translateY(-3px) scale(1.02) !important;
    box-shadow: 0 8px 24px rgba(91,79,255,.42) !important;
    background: #4a3dee !important;
}
button.primary:active { transform: translateY(0) scale(.98) !important; }
button.secondary, .gr-button-secondary {
    font-family: 'Syne', sans-serif !important;
    font-weight: 600 !important; font-size: 13px !important;
    background: var(--surface) !important; color: var(--ink) !important;
    border: 1.5px solid rgba(0,0,0,.12) !important;
    border-radius: 10px !important; cursor: pointer !important;
    transition: all .2s ease !important;
}
button.secondary:hover {
    border-color: var(--accent) !important; color: var(--accent) !important;
    background: rgba(91,79,255,.05) !important;
    transform: translateY(-2px) !important;
}
.tab-nav {
    background: var(--surface) !important; border-radius: 12px !important;
    padding: 4px !important; border: 1px solid rgba(0,0,0,.06) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,.06) !important;
}
.tab-nav button {
    font-family: 'DM Sans', sans-serif !important; font-size: 13px !important;
    font-weight: 500 !important; border-radius: 9px !important;
    border: none !important; background: transparent !important;
    color: var(--ink3) !important; transition: all .2s ease !important;
    white-space: nowrap !important;
}
.tab-nav button:hover {
    background: rgba(91,79,255,.08) !important;
    color: var(--accent) !important; transform: translateY(-1px);
}
.tab-nav button.selected {
    background: var(--accent) !important; color: #fff !important;
    box-shadow: 0 4px 14px rgba(91,79,255,.35) !important;
}
.gr-dataframe table { font-size: 13px !important; font-family: 'DM Sans', sans-serif !important; }
.gr-dataframe thead tr { background: var(--ink) !important; color: #fff !important; }
.gr-dataframe thead th {
    font-family: 'Syne', sans-serif !important; font-size: 11px !important;
    font-weight: 700 !important; text-transform: uppercase !important;
    letter-spacing: .06em !important; padding: 10px 14px !important;
}
.gr-dataframe tbody tr:nth-child(even) { background: var(--paper) !important; }
.gr-dataframe tbody tr:hover { background: rgba(91,79,255,.06) !important; }
.gr-file-upload {
    border: 2px dashed rgba(91,79,255,.3) !important;
    border-radius: 12px !important; background: rgba(91,79,255,.02) !important;
    transition: all .2s ease !important;
}
.gr-file-upload:hover {
    border-color: var(--accent) !important;
    background: rgba(91,79,255,.06) !important;
}
@keyframes pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(91,79,255,.4); }
    50%      { box-shadow: 0 0 0 8px rgba(91,79,255,0); }
}
.pulsing { animation: pulse 2s infinite; }
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-thumb { background: rgba(0,0,0,.15); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }
"""


# ══════════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════════
with gr.Blocks(css=CSS, title="SmartNotes AI") as demo:

    st_notes   = gr.State("")
    st_subject = gr.State("")
    st_topics  = gr.State("")
    st_quiz    = gr.State([])
    st_weak    = gr.State([])
    st_requiz  = gr.State([])
    st_cards   = gr.State([])
    st_card_i  = gr.State(0)
    st_fc_sc   = gr.State([])

    gr.HTML("""
    <div class="app-header">
      <div class="app-title">SmartNotes AI</div>
      <div class="app-sub">Generate notes · Auto quiz · Weak spot re-quiz · Flashcards · Confidence tracker</div>
    </div>
    """)

    with gr.Tabs(elem_classes="tab-nav"):

        # ══════════════════════════════════════════════════════════════════════
        # TAB 1 — NOTES + QUIZ
        # ══════════════════════════════════════════════════════════════════════
        with gr.Tab("📝 Notes + Quiz"):

            gr.HTML('<span class="step-pill pill-1">Step 1 — Generate Notes</span>')

            with gr.Row():
                with gr.Column(scale=1):
                    pdf_upload = gr.File(label="Upload syllabus PDF (optional)",
                                         file_types=[".pdf"], type="filepath")
                    parse_btn  = gr.Button("Extract topics from PDF", variant="secondary", size="sm")
                    parse_msg  = gr.Textbox(label="", show_label=False, interactive=False,
                                            lines=1, placeholder="PDF status…")
                    subj_in    = gr.Textbox(label="Subject", placeholder="e.g. Operating Systems")
                    topic_in   = gr.Textbox(label="Topics (comma-separated)", lines=3,
                                            placeholder="e.g. Process Management, Deadlocks, Memory")
                    depth_in   = gr.Dropdown(
                        ["Brief (exam summary)", "Standard", "Deep (full detail)"],
                        value="Standard", label="Note depth")
                    gen_btn    = gr.Button("Generate Notes", variant="primary", elem_classes="pulsing")
                    gen_status = gr.Textbox(label="", show_label=False, interactive=False,
                                            lines=1, placeholder="Status…")

                with gr.Column(scale=2):
                    gr.HTML(
                        "<div style='font-family:Syne;font-size:11px;font-weight:700;"
                        "text-transform:uppercase;letter-spacing:.06em;color:#7a7a8a;"
                        "margin-bottom:8px'>Generated Notes</div>"
                    )
                    notes_display = gr.HTML(
                        value="<div style='color:#7a7a8a;font-size:13px;padding:12px 0;"
                              "min-height:200px'>Notes will appear here after generation.</div>"
                    )
                    notes_edit = gr.Textbox(
                        label="Edit notes before quiz",
                        lines=5, interactive=True,
                        placeholder="Clean notes appear here for editing after generation…"
                    )
                    pdf_dl = gr.DownloadButton("Download PDF", visible=False,
                                               variant="secondary", size="sm")

            gr.HTML("<hr style='border:none;border-top:1px solid rgba(0,0,0,.07);margin:24px 0'>")
            gr.HTML('<span class="step-pill pill-2">Step 2 — Auto Quiz (5 Scenario + 5 Normal)</span>')
            gr.HTML("""
            <div style='background:rgba(0,201,167,.07);border:1px solid rgba(0,201,167,.2);
                border-radius:8px;padding:10px 14px;font-size:13px;color:#006b59;margin-bottom:14px'>
              Generate notes first, then click <b>Build Quiz</b>.
            </div>
            """)

            build_quiz_btn = gr.Button("Build Quiz from Notes", variant="primary")
            quiz_status    = gr.Textbox(label="", show_label=False, interactive=False,
                                        lines=1, placeholder="Quiz status…")

            scenario_header = gr.HTML("")
            q_groups = []
            q_radios = []
            q_fbs    = []
            for i in range(5):
                with gr.Group(visible=False) as grp:
                    r = gr.Radio(choices=[], label=f"Q{i+1}", interactive=False)
                    f = gr.HTML("")
                q_groups.append(grp)
                q_radios.append(r)
                q_fbs.append(f)

            normal_header = gr.HTML("")
            for i in range(5, 10):
                with gr.Group(visible=False) as grp:
                    r = gr.Radio(choices=[], label=f"Q{i+1}", interactive=False)
                    f = gr.HTML("")
                q_groups.append(grp)
                q_radios.append(r)
                q_fbs.append(f)

            with gr.Row(visible=False) as submit_quiz_row:
                submit_quiz_btn = gr.Button("Submit Quiz", variant="primary")
            quiz_result = gr.HTML("")

            gr.HTML("<hr style='border:none;border-top:1px solid rgba(0,0,0,.07);margin:24px 0'>")
            gr.HTML('<span class="step-pill pill-3">Step 3 — Weak Spot Re-Quiz</span>')

            weak_info    = gr.HTML("")
            build_rq_btn = gr.Button("Build Targeted Re-Quiz", variant="primary", visible=False)
            rq_status    = gr.Textbox(label="", show_label=False, interactive=False,
                                      lines=1, placeholder="Re-quiz status…", visible=False)

            rq_groups = []
            rq_radios = []
            rq_fbs    = []
            for i in range(6):
                with gr.Group(visible=False) as grp:
                    r = gr.Radio(choices=[], label=f"RQ{i+1}", interactive=False)
                    f = gr.HTML("")
                rq_groups.append(grp)
                rq_radios.append(r)
                rq_fbs.append(f)

            with gr.Row(visible=False) as submit_rq_row:
                submit_rq_btn = gr.Button("Submit Re-Quiz", variant="primary")
            rq_result = gr.HTML("")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 2 — FLASHCARDS
        # ══════════════════════════════════════════════════════════════════════
        with gr.Tab("🃏 Flashcards"):
            gr.HTML('<span class="step-pill pill-2">Write-answer flashcards · Correct=1pt · Partial=0.5pt · Wrong=0pt</span>')

            with gr.Row():
                fc_notes = gr.Textbox(label="Notes (auto-filled from Notes tab)",
                                      lines=4, placeholder="Notes auto-fill here after generation…")
                fc_subj  = gr.Textbox(label="Subject", placeholder="Subject name…")

            build_fc_btn = gr.Button("Build Flashcards", variant="primary")
            fc_status    = gr.Textbox(label="", show_label=False, interactive=False, lines=1)

            with gr.Column(visible=False) as fc_col:
                fc_q = gr.HTML(
                    "<div style='background:#ffffff;border:2px solid #5b4fff;border-radius:14px;"
                    "padding:20px 24px'><div style='font-size:16px;font-weight:700;color:#1a1a2e'>"
                    "Question will appear here</div></div>"
                )
                fc_ans = gr.Textbox(
                    label="Your answer",
                    lines=3, interactive=True,
                    placeholder="Type your answer here…"
                )
                with gr.Row():
                    fc_eval_btn = gr.Button("Evaluate Answer", variant="primary")
                    fc_next_btn = gr.Button("Next Card →",     variant="secondary")
                fc_fb    = gr.HTML("")
                fc_final = gr.HTML("")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 3 — CONFIDENCE + HISTORY
        # ══════════════════════════════════════════════════════════════════════
        with gr.Tab("📊 Confidence & History"):
            gr.HTML('<span class="step-pill pill-4">Per-topic confidence tracked across all sessions</span>')
            with gr.Row():
                ref_conf = gr.Button("Refresh Confidence", variant="secondary", size="sm")
                ref_hist = gr.Button("Refresh History",    variant="secondary", size="sm")

            # FIX 3: Darker, bolder section headings
            gr.HTML('<div style="font-weight:800;font-size:15px;color:#1a1a2e;margin:10px 0 6px;font-family:Syne,sans-serif;">Confidence meter</div>')
            # FIX 2: Only Topic, Avg Score, Status columns
            conf_df = gr.Dataframe(
                headers=["Topic", "Avg Score", "Status"],
                value=get_conf_table(), interactive=False, wrap=True)

            gr.HTML('<div style="font-weight:800;font-size:15px;color:#1a1a2e;margin:16px 0 6px;font-family:Syne,sans-serif;">Generation history</div>')
            hist_df = gr.Dataframe(
                headers=["Timestamp", "Subject", "Topics", "Score"],
                value=get_history_table(), interactive=False, wrap=True)

    gr.HTML("""
    <div style='text-align:center;padding:16px 0 6px;font-size:11px;color:#7a7a8a'>
      SmartNotes AI · Gemini 2.5 Flash
    </div>
    """)

    # ══════════════════════════════════════════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════════════════════════════════════════

    parse_btn.click(parse_syllabus_pdf, inputs=[pdf_upload],
                    outputs=[topic_in, parse_msg])

    def _gen(subject, topics, depth):
        html, clean, path, msg = generate_notes(subject, topics, depth)
        pdf_upd = gr.update(visible=bool(path), value=path) if path else gr.update(visible=False)
        return html, clean, clean, subject, topics, pdf_upd, msg

    gen_btn.click(
        _gen,
        inputs=[subj_in, topic_in, depth_in],
        outputs=[notes_display, notes_edit, st_notes, st_subject, st_topics, pdf_dl, gen_status]
    )

    notes_edit.change(lambda x: x, inputs=notes_edit, outputs=st_notes)

    # ── Build quiz ────────────────────────────────────────────────────────────
    def _build_quiz(notes, subject):
        qs, msg = build_quiz(notes, subject)
        empty_fbs     = [gr.update(value="") for _ in range(10)]
        hidden_groups = [gr.update(visible=False)] * 10
        blank_radios  = [gr.update(choices=[], label=f"Q{i+1}", value=None, interactive=False)
                         for i in range(10)]
        if not qs:
            return ([], msg, gr.update(value=""), gr.update(value=""),
                    *hidden_groups, *blank_radios, *empty_fbs, gr.update(visible=False))
        s_hdr = (
            "<div style='font-family:Syne;font-size:12px;font-weight:700;color:#3c3489;"
            "text-transform:uppercase;letter-spacing:.06em;margin:12px 0 6px;"
            "padding:6px 12px;background:rgba(91,79,255,.08);border-radius:6px'>"
            "Scenario-based questions (1–5)</div>"
        )
        n_hdr = (
            "<div style='font-family:Syne;font-size:12px;font-weight:700;color:#007a63;"
            "text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px;"
            "padding:6px 12px;background:rgba(0,201,167,.08);border-radius:6px'>"
            "Normal questions (6–10)</div>"
        )
        grp_upd = [gr.update(visible=True)] * min(len(qs), 10)
        while len(grp_upd) < 10:
            grp_upd.append(gr.update(visible=False))
        rad_upd = []
        for i in range(10):
            if i < len(qs):
                q = qs[i]
                rad_upd.append(gr.update(choices=q["options"], label=f"Q{i+1}: {q['q']}",
                                          value=None, interactive=True))
            else:
                rad_upd.append(gr.update(choices=[], label=f"Q{i+1}", value=None, interactive=False))
        return (qs, msg, gr.update(value=s_hdr), gr.update(value=n_hdr),
                *grp_upd, *rad_upd, *empty_fbs, gr.update(visible=True))

    build_quiz_btn.click(
        _build_quiz,
        inputs=[notes_edit, subj_in],
        outputs=([st_quiz, quiz_status, scenario_header, normal_header]
                 + q_groups + q_radios + q_fbs + [submit_quiz_row])
    )

    # ── Submit quiz ───────────────────────────────────────────────────────────
    def _submit_quiz(qs, subject, *radio_vals):
        pad_fbs = [gr.update(value="") for _ in range(10)]
        if not qs:
            return ([], "<p style='color:red'>Build the quiz first.</p>",
                    gr.update(value="", visible=False),
                    gr.update(visible=False), gr.update(visible=False), *pad_fbs)

        correct = 0
        weak    = []
        fb_list = []

        for i, q in enumerate(qs):
            chosen = radio_vals[i] if i < len(radio_vals) else None
            if chosen is None:
                fb_list.append(gr.update(
                    value="<div style='color:#f59e0b;font-size:12px;padding:4px 0'>⚠ Not answered</div>"))
                weak.append(q.get("topic", f"Topic {i+1}"))
                continue
            idx   = q["options"].index(chosen) if chosen in q["options"] else -1
            right = (idx == q["answer"])
            if right:
                correct += 1
                fb_list.append(gr.update(
                    value="<div style='color:#00a688;font-size:12px;padding:4px 0'>✓ Correct!</div>"))
            else:
                fb_list.append(gr.update(
                    value=f"<div style='color:#d43a4a;font-size:12px;padding:4px 0'>"
                          f"✗ Wrong. Correct: <b>{q['options'][q['answer']]}</b></div>"))
                weak.append(q.get("topic", f"Topic {i+1}"))

        while len(fb_list) < 10:
            fb_list.append(gr.update(value=""))

        weak = list(dict.fromkeys(weak))
        pct  = round(correct / len(qs) * 100)
        col  = "#00a688" if pct >= 75 else ("#f59e0b" if pct >= 50 else "#d43a4a")

        if subject:
            update_history_score(subject, f"Quiz: {correct}/{len(qs)} ({pct}%)")

        result_html = (
            f"<div style='background:{col}1a;border:1px solid {col}44;"
            f"border-radius:12px;padding:18px 22px;margin-top:14px'>"
            f"<div style='font-family:Syne;font-size:28px;font-weight:800;color:{col}'>{pct}%</div>"
            f"<div style='font-size:13px;color:#3a3a42;margin-top:4px'>"
            f"{correct}/{len(qs)} correct &nbsp;·&nbsp; "
            f"{'Great job!' if pct>=75 else ('Keep studying' if pct>=50 else 'Needs more work')}</div>"
            + (f"<div style='font-size:12px;color:#d43a4a;margin-top:8px'>"
               f"Weak topics: <b>{', '.join(weak)}</b></div>" if weak else "")
            + "</div>"
        )

        for t in set(q.get("topic", "General") for q in qs):
            t_qs = [q for q in qs if q.get("topic") == t]
            t_correct = 0
            for q in t_qs:
                idx_q = qs.index(q)
                r = radio_vals[idx_q] if idx_q < len(radio_vals) else None
                if r is not None and r in q["options"] and q["options"].index(r) == q["answer"]:
                    t_correct += 1
            update_conf(t, t_correct / len(t_qs) * 100)

        weak_html = ""
        if weak:
            weak_html = (
                f"<div style='background:rgba(255,91,107,.08);border:1px solid rgba(255,91,107,.25);"
                f"border-radius:8px;padding:10px 14px;font-size:13px;color:#a0222f;margin-bottom:8px'>"
                f"Weak topics: <b>{', '.join(weak)}</b>. Build the re-quiz below.</div>"
            )

        return (weak, result_html,
                gr.update(visible=bool(weak), value=weak_html),
                gr.update(visible=bool(weak)),
                gr.update(visible=bool(weak)),
                *fb_list)

    submit_quiz_btn.click(
        _submit_quiz,
        inputs=[st_quiz, st_subject] + q_radios,
        outputs=[st_weak, quiz_result, weak_info, build_rq_btn, rq_status] + q_fbs
    )

    # ── Build re-quiz ─────────────────────────────────────────────────────────
    def _build_rq(weak, notes, subject):
        hidden = [gr.update(visible=False)] * 6
        blank  = [gr.update(choices=[], label=f"RQ{i+1}", value=None, interactive=False)
                  for i in range(6)]
        if not weak:
            return [], "No weak topics.", *hidden, *blank, gr.update(visible=False)
        qs, msg = build_requiz(weak, notes, subject)
        if not qs:
            return [], msg, *hidden, *blank, gr.update(visible=False)
        grp_upd = [gr.update(visible=True)] * min(len(qs), 6)
        while len(grp_upd) < 6:
            grp_upd.append(gr.update(visible=False))
        rad_upd = []
        for i in range(6):
            if i < len(qs):
                q = qs[i]
                rad_upd.append(gr.update(choices=q["options"], label=f"RQ{i+1}: {q['q']}",
                                          value=None, interactive=True))
            else:
                rad_upd.append(gr.update(choices=[], label=f"RQ{i+1}",
                                          value=None, interactive=False))
        return qs, msg, *grp_upd, *rad_upd, gr.update(visible=True)

    build_rq_btn.click(
        _build_rq,
        inputs=[st_weak, notes_edit, subj_in],
        outputs=[st_requiz, rq_status] + rq_groups + rq_radios + [submit_rq_row]
    )

    # ── Submit re-quiz ────────────────────────────────────────────────────────
    def _submit_rq(qs, *radio_vals):
        pad = [gr.update(value="") for _ in range(6)]
        if not qs:
            return "<p style='color:red'>Build re-quiz first.</p>", *pad
        correct = 0
        fb_list = []
        for i, q in enumerate(qs):
            chosen = radio_vals[i] if i < len(radio_vals) else None
            if chosen is None:
                fb_list.append(gr.update(
                    value="<div style='color:#f59e0b;font-size:12px;padding:4px 0'>⚠ Not answered</div>"))
                continue
            idx = q["options"].index(chosen) if chosen in q["options"] else -1
            if idx == q["answer"]:
                correct += 1
                fb_list.append(gr.update(
                    value="<div style='color:#00a688;font-size:12px;padding:4px 0'>✓ Correct!</div>"))
            else:
                fb_list.append(gr.update(
                    value=f"<div style='color:#d43a4a;font-size:12px;padding:4px 0'>"
                          f"✗ Wrong. Answer: <b>{q['options'][q['answer']]}</b></div>"))
        while len(fb_list) < 6:
            fb_list.append(gr.update(value=""))
        pct = round(correct / len(qs) * 100)
        col = "#00a688" if pct >= 75 else ("#f59e0b" if pct >= 50 else "#d43a4a")
        html = (
            f"<div style='background:{col}1a;border:1px solid {col}44;"
            f"border-radius:12px;padding:18px 22px;margin-top:14px'>"
            f"<div style='font-family:Syne;font-size:28px;font-weight:800;color:{col}'>{pct}%</div>"
            f"<div style='font-size:13px;color:#3a3a42;margin-top:4px'>"
            f"{correct}/{len(qs)} correct on re-quiz</div></div>"
        )
        for q in qs:
            update_conf(q.get("topic", "General"), pct)
        return html, *fb_list

    submit_rq_btn.click(
        _submit_rq,
        inputs=[st_requiz] + rq_radios,
        outputs=[rq_result] + rq_fbs
    )

    # ── Flashcards — build ────────────────────────────────────────────────────
    def _build_fc(notes, subject):
        cards, msg = build_flashcards(notes, subject)
        blank_q = (
            "<div style='background:#ffffff;border:2px solid #5b4fff;border-radius:14px;"
            "padding:20px 24px'><div style='font-size:16px;font-weight:700;color:#1a1a2e'>"
            "Question will appear here</div></div>"
        )
        if cards is None:
            return [], 0, [], msg, gr.update(visible=False), blank_q, "", ""
        scores = [None] * len(cards)
        q_html = fc_question_html(cards[0], 0, len(cards), scores)
        return cards, 0, scores, msg, gr.update(visible=True), q_html, "", ""

    build_fc_btn.click(
        _build_fc,
        inputs=[fc_notes, fc_subj],
        outputs=[st_cards, st_card_i, st_fc_sc, fc_status, fc_col, fc_q, fc_fb, fc_final]
    )

    # ── Flashcards — evaluate ─────────────────────────────────────────────────
    def _eval_fc(user_ans, cards, idx, scores, subject):
        if not cards or idx >= len(cards):
            return "", scores

        card               = cards[idx]
        score, grade, fb   = eval_flashcard(user_ans, card["answer"], card["question"])

        scores = list(scores) if scores else [None] * len(cards)
        while len(scores) < len(cards):
            scores.append(None)
        scores[idx] = {"score": score, "grade": grade}

        pct, correct, partial, wrong, attempted = calc_fc_score(scores)
        total = len(cards)

        grade_color = {"correct": "#00a688", "partial": "#f59e0b", "wrong": "#d43a4a"}.get(grade, "#d43a4a")
        grade_label = {"correct": "✓ Correct (+1 pt)", "partial": "~ Partial (+0.5 pt)", "wrong": "✗ Wrong (+0 pt)"}.get(grade, "✗ Wrong")
        grade_bg    = {"correct": "#EAF3DE", "partial": "#FAEEDA", "wrong": "#FCEBEB"}.get(grade, "#FCEBEB")

        fb_html = (
            f"<div style='background:#ffffff;border:1.5px solid {grade_color}44;"
            f"border-radius:12px;padding:16px 20px;margin-top:10px'>"
            f"<div style='display:inline-block;background:{grade_bg};color:{grade_color};"
            f"font-family:Syne,sans-serif;font-size:13px;font-weight:700;"
            f"padding:4px 14px;border-radius:20px;margin-bottom:8px'>{grade_label}</div>"
            f"<div style='font-size:13px;color:#1a1a2e;font-weight:500;margin-bottom:6px'>{fb}</div>"
            f"<div style='font-size:12px;color:#5f5e5a;font-style:italic'>"
            f"Ideal: {card['answer']}</div>"
            f"<div style='margin-top:10px;padding:8px 12px;background:#f7f6f2;"
            f"border-radius:8px;font-size:12px;color:#3c3489;font-weight:600'>"
            f"Running: {attempted}/{total} answered · "
            f"Score so far: {pct}% &nbsp;({correct} correct, {partial} partial, {wrong} wrong)</div>"
            f"</div>"
        )

        update_conf(card.get("topic", "General"), score)

        # FIX 1: Save flashcard score to history using dedicated function
        if subject:
            update_history_fc_score(subject, f"Flashcards: {pct}% ({attempted}/{total} done)")

        return fb_html, scores

    fc_eval_btn.click(
        _eval_fc,
        inputs=[fc_ans, st_cards, st_card_i, st_fc_sc, st_subject],
        outputs=[fc_fb, st_fc_sc]
    )

    # ── Flashcards — next card ────────────────────────────────────────────────
    def _next_fc(cards, idx, scores, subject):
        if not cards:
            return idx, "", "", ""
        nxt   = idx + 1
        total = len(cards)

        if nxt >= total:
            pct, correct, partial, wrong, attempted = calc_fc_score(scores)
            final_html = fc_final_html(pct, correct, partial, wrong, attempted, total)
            done_q = (
                f"<div style='background:#ffffff;border:2px solid #00c9a7;border-radius:14px;"
                f"padding:20px 24px;text-align:center'>"
                f"<div style='font-size:18px;font-weight:700;color:#007a63'>"
                f"All {total} flashcards completed!</div></div>"
            )
            # FIX 1: Save final flashcard score using dedicated function
            if subject:
                update_history_fc_score(subject, f"Flashcards: {pct}% ({attempted}/{total} answered)")
            return nxt, done_q, "", final_html

        card  = cards[nxt]
        q_html = fc_question_html(card, nxt, total, scores)
        return nxt, q_html, "", ""

    fc_next_btn.click(
        _next_fc,
        inputs=[st_cards, st_card_i, st_fc_sc, st_subject],
        outputs=[st_card_i, fc_q, fc_fb, fc_final]
    )

    st_notes.change(lambda n, s: (n, s), inputs=[st_notes, st_subject],
                    outputs=[fc_notes, fc_subj])

    ref_conf.click(get_conf_table, outputs=conf_df)
    ref_hist.click(get_history_table, outputs=hist_df)
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText

# ── CONFIG ── fill these in ───────────────────────────────────────────────────
EMAIL_SENDER       = "shilpaj4418@gmail.com"      # Gmail address you send FROM
EMAIL_APP_PASSWORD = "gcdm ujjz uaqi ccwd"       # 16-char Gmail App Password
EMAIL_RECIPIENT    = "shilpaj4418@gmail.com"     # Address to send the report TO
# ─────────────────────────────────────────────────────────────────────────────


def _get_performance_summary() -> dict:
    """Pull the latest record from history.json."""
    rows = load_history()          # reuses existing function — no modification needed
    if not rows:
        return None
    latest = rows[-1]
    return {
        "subject":   latest.get("subject", "N/A"),
        "topics":    latest.get("topics",  "N/A"),
        "score":     latest.get("score",   "—"),
        "timestamp": latest.get("timestamp", "N/A"),
    }


def _get_weak_topics(top_n: int = 3) -> list[dict]:
    """Return the bottom-N topics by average score from confidence.json."""
    d = load_conf()                # reuses existing function — no modification needed
    if not d:
        return []
    scored = []
    for topic, scores in d.items():
        avg = round(sum(scores) / len(scores), 1)
        scored.append({"topic": topic, "avg": avg})
    scored.sort(key=lambda x: x["avg"])
    return scored[:top_n]


def _generate_ai_advice(subject: str, score: str, weak_topics: list[dict]) -> str:
    """Ask Gemini to write 2-3 short improvement tips."""
    if not subject or subject == "N/A":
        return "No study data available yet — generate some notes and take a quiz first!"

    weak_str = (
        ", ".join(f"{w['topic']} ({w['avg']}%)" for w in weak_topics)
        if weak_topics else "none identified"
    )

    prompt = (
        f"A student is studying '{subject}'.\n"
        f"Their latest quiz/flashcard score: {score}\n"
        f"Their weakest topics (with average scores): {weak_str}\n\n"
        "Write EXACTLY 3 short, actionable improvement tips (1-2 sentences each). "
        "Be encouraging but specific. Number them 1, 2, 3. No markdown, no preamble."
    )

    try:
        advice = get_model().generate_content(prompt).text.strip()
        return advice
    except Exception as e:
        return f"Could not generate AI advice: {e}"


def _build_study_plan(weak_topics: list[dict]) -> list[str]:
    """Compose a simple 4-step study plan based on weak topics."""
    topic_names = [w["topic"] for w in weak_topics] if weak_topics else ["your recent topics"]
    topics_str  = ", ".join(topic_names)

    return [
        f"📖  Revise notes on weak topics: {topics_str}",
        "📝  Re-take the quiz focusing on those sections",
        "🃏  Run through the flashcard deck — aim for 80%+ correct",
        "📊  Check the Confidence tab to track improvement over time",
    ]


def _render_email_html(summary: dict | None,
                       weak:    list[dict],
                       advice:  str,
                       plan:    list[str]) -> str:
    """Build a clean, readable HTML email body."""

    # ── performance block ──────────────────────────────────────────────────
    if summary:
        perf_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:6px 0;color:#6b7280;font-size:13px;width:110px">Subject</td>
            <td style="padding:6px 0;color:#111827;font-size:13px;font-weight:600">{summary['subject']}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#6b7280;font-size:13px">Topics</td>
            <td style="padding:6px 0;color:#111827;font-size:13px">{summary['topics']}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#6b7280;font-size:13px">Latest Score</td>
            <td style="padding:6px 0;color:#4f46e5;font-size:14px;font-weight:700">{summary['score']}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#6b7280;font-size:13px">Session</td>
            <td style="padding:6px 0;color:#6b7280;font-size:12px">{summary['timestamp']}</td>
          </tr>
        </table>
        """
    else:
        perf_html = "<p style='color:#9ca3af;font-size:13px;margin:0'>No study sessions recorded yet.</p>"

    # ── weak topics block ──────────────────────────────────────────────────
    if weak:
        weak_rows = "".join(
            f"""<tr>
                  <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;
                             color:#374151;font-size:13px">{w['topic']}</td>
                  <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;
                             color:#ef4444;font-size:13px;font-weight:600;
                             text-align:right">{w['avg']}%</td>
                </tr>"""
            for w in weak
        )
        weak_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #fee2e2;border-radius:8px;overflow:hidden">
          <thead>
            <tr style="background:#fef2f2">
              <th style="padding:8px 12px;text-align:left;color:#b91c1c;
                         font-size:11px;text-transform:uppercase;letter-spacing:.05em">Topic</th>
              <th style="padding:8px 12px;text-align:right;color:#b91c1c;
                         font-size:11px;text-transform:uppercase;letter-spacing:.05em">Avg Score</th>
            </tr>
          </thead>
          <tbody>{weak_rows}</tbody>
        </table>
        """
    else:
        weak_html = "<p style='color:#9ca3af;font-size:13px;margin:0'>No weak topics detected yet — keep studying!</p>"

    # ── advice block ───────────────────────────────────────────────────────
    advice_lines = advice.strip().split("\n")
    advice_html  = "".join(
        f"<p style='margin:0 0 10px 0;color:#374151;font-size:13px;line-height:1.6'>{line}</p>"
        for line in advice_lines if line.strip()
    )

    # ── study plan block ───────────────────────────────────────────────────
    plan_html = "".join(
        f"<li style='margin:0 0 10px 0;color:#374151;font-size:13px;line-height:1.6'>{step}</li>"
        for step in plan
    )

    # ── assemble full email ────────────────────────────────────────────────
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background:#f9fafb;font-family:'Segoe UI',Arial,sans-serif">

      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:32px 16px">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0"
                 style="max-width:600px;width:100%;background:#ffffff;
                        border-radius:16px;overflow:hidden;
                        box-shadow:0 4px 24px rgba(0,0,0,.07)">

            <!-- HEADER -->
            <tr>
              <td style="background:#1a1a2e;padding:28px 32px 24px">
                <div style="font-size:22px;font-weight:800;color:#ffffff;
                            letter-spacing:-.02em;margin-bottom:4px">
                  📚 SmartNotes AI
                </div>
                <div style="font-size:13px;color:rgba(255,255,255,.5)">
                  Your automated study report · {datetime.datetime.now().strftime("%A, %d %B %Y")}
                </div>
              </td>
            </tr>

            <!-- BODY -->
            <tr>
              <td style="padding:28px 32px">

                <!-- Section 1: Performance -->
                <div style="margin-bottom:28px">
                  <div style="font-size:11px;font-weight:700;color:#5b4fff;
                              text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">
                    📊 Performance Summary
                  </div>
                  {perf_html}
                </div>

                <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 28px 0">

                <!-- Section 2: Weak Topics -->
                <div style="margin-bottom:28px">
                  <div style="font-size:11px;font-weight:700;color:#ef4444;
                              text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">
                    🎯 Weak Topics (Bottom 3)
                  </div>
                  {weak_html}
                </div>

                <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 28px 0">

                <!-- Section 3: AI Advice -->
                <div style="margin-bottom:28px">
                  <div style="font-size:11px;font-weight:700;color:#059669;
                              text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">
                    🧠 AI Improvement Advice
                  </div>
                  <div style="background:#f0fdf4;border-left:3px solid #059669;
                              border-radius:0 8px 8px 0;padding:14px 16px">
                    {advice_html}
                  </div>
                </div>

                <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 28px 0">

                <!-- Section 4: Study Plan -->
                <div style="margin-bottom:8px">
                  <div style="font-size:11px;font-weight:700;color:#d97706;
                              text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">
                    📅 Suggested Study Plan
                  </div>
                  <ol style="margin:0;padding-left:20px">
                    {plan_html}
                  </ol>
                </div>

              </td>
            </tr>

            <!-- FOOTER -->
            <tr>
              <td style="background:#f9fafb;padding:16px 32px;text-align:center;
                         border-top:1px solid #f3f4f6">
                <div style="font-size:11px;color:#9ca3af">
                  Sent automatically by SmartNotes AI · Gemini 2.5 Flash
                </div>
              </td>
            </tr>

          </table>
        </td></tr>
      </table>

    </body>
    </html>
    """


def send_smart_email() -> None:
    """
    Assemble and dispatch the Smart AI Study Report via Gmail SMTP.
    Designed to be called in a background thread — never raises to the caller.
    """
    try:
        # 1. Gather data ──────────────────────────────────────────────────────
        summary     = _get_performance_summary()
        weak        = _get_weak_topics(top_n=3)
        subject_str = summary["subject"] if summary else "N/A"
        score_str   = summary["score"]   if summary else "—"

        # 2. Generate AI advice ───────────────────────────────────────────────
        advice = _generate_ai_advice(subject_str, score_str, weak)

        # 3. Build study plan ─────────────────────────────────────────────────
        plan = _build_study_plan(weak)

        # 4. Render email HTML ────────────────────────────────────────────────
        html_body = _render_email_html(summary, weak, advice, plan)

        # 5. Build MIME message ───────────────────────────────────────────────
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"📚 SmartNotes AI Study Report — "
            f"{datetime.datetime.now().strftime('%d %b %Y')}"
        )
        msg["From"] = EMAIL_SENDER
        msg["To"]   = EMAIL_RECIPIENT

        # Plain-text fallback (brief)
        plain = (
            f"SmartNotes AI — Study Report\n"
            f"{'='*40}\n"
            f"Subject : {subject_str}\n"
            f"Score   : {score_str}\n\n"
            f"Weak Topics:\n"
            + "\n".join(f"  • {w['topic']} — {w['avg']}%" for w in weak)
            + f"\n\nAI Advice:\n{advice}\n\n"
            f"Study Plan:\n"
            + "\n".join(f"  {i+1}. {step}" for i, step in enumerate(plan))
        )
        msg.attach(MIMEText(plain,     "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # 6. Send via Gmail SMTP ──────────────────────────────────────────────
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

        print("[SmartNotes AI] ✅ Study report email sent successfully.")

    except smtplib.SMTPAuthenticationError:
        print("[SmartNotes AI] ❌ Email failed: authentication error. "
              "Check EMAIL_SENDER and EMAIL_APP_PASSWORD.")
    except smtplib.SMTPException as e:
        print(f"[SmartNotes AI] ❌ Email SMTP error: {e}")
    except Exception as e:
        print(f"[SmartNotes AI] ❌ Email unexpected error: {e}")


def _launch_email_thread() -> None:
    """Spawn a daemon thread so the email send never blocks the Gradio UI."""
    t = threading.Thread(target=send_smart_email, daemon=True, name="SmartEmailReport")
    t.start()
    print("[SmartNotes AI] 📧 Email report thread started.")


# ── FIRE ON STARTUP ───────────────────────────────────────────────────────────
_launch_email_thread()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
