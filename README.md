# Smart Learning and Personalized Academic Support System

> study assistent — Generate notes, quiz yourself, re-quiz weak spots, flashcards,send email regarding less score and track confidence per topic. Powered by Gemini

---

## Features

| Tab | What it does |
|-----|-------------|
| 📝 Notes Generator | Enter subject + topics (or upload a PDF syllabus to auto-extract topics), set depth, generate editable notes, download PDF |
| 🧠 Auto Quiz (MCQ) | Builds 10 multiple-choice questions from your notes, grades instantly, flags weak topics |
| 🎯 Weak Spot Re-Quiz | Generates 6 harder targeted questions only on topics you scored below threshold |
| 🃏 Flashcards | Write-answer cards, AI evaluates your answer 0-100 with feedback |
| 📊 Confidence Meter | Per-topic score history across all sessions with trend arrows |
| 🕓 History | Full log of every generation session |

---

## Setup

### 1. Get a Gemini API key
Go to https://aistudio.google.com/app/apikey and create a free key.

### 2. Add your key
Open `.env` and replace the placeholder:
```
GEMINI_API_KEY=your_actual_key_here
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run
```bash
python app.py
```

Then open http://localhost:7860 in your browser.

---

## Flow

```
Open app
    |
Notes Generator  ←─── Upload PDF syllabus (auto-extract topics)
Edit notes freely (trim deep content)
Press Generate
    |
    ├─── Saved to History (history.json)
    |
Auto Quiz (10 MCQs built from your notes)
    |
Weak topics flagged
    |
Targeted Re-Quiz (6 deeper questions on weak topics)
    |
Flashcards (type answers → AI scores 0-100)
    |
Confidence Meter (per-topic trend across sessions)
```

---

## Files

```
smartnotes/
├── app.py              ← main app
├── requirements.txt    ← dependencies
├── .env                ← your Gemini API key
├── history.json        ← auto-created, stores all sessions
├── confidence.json     ← auto-created, per-topic score history
└── generated_notes/    ← auto-created, PDF downloads stored here
```

---

## Notes

- All data is stored locally (JSON files) — no database needed
- The confidence meter persists across app restarts
- You can edit notes before quizzing — trim deep content to focus on exam topics
- PDF syllabus upload uses `pypdf` to extract text, then Gemini identifies the topics
