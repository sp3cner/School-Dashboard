# School Dashboard

A local Streamlit dashboard that pulls assignments and files from Canvas
and important dates from your uploaded syllabi, and shows them all in one
sorted timeline.

## Setup

1. Make sure you have Python 3.9+ installed.
2. In this folder, install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   streamlit run app.py
   ```

   This opens the dashboard in your browser (usually at `http://localhost:8501`).

## Getting a Canvas API token

1. Log in to Canvas.
2. Go to **Account → Settings**.
3. Scroll to **Approved Integrations** and click **+ New Access Token**.
4. Give it a purpose (e.g. "school dashboard") and generate it.
5. Copy the token immediately — Canvas only shows it once. If you lose it, just
   generate a new one.
6. In the dashboard sidebar, paste your Canvas URL (e.g.
   `https://myschool.instructure.com`, no trailing slash) and the token, then
   click **Connect**.

Your token is only kept in memory for the current browser session — it is
never written to disk by this app. Treat it like a password: don't share it,
and revoke it from Canvas settings if you ever think it leaked.

## Using it

- **Timeline tab** — every Canvas assignment with a due date, plus every
  dated item pulled from your uploaded syllabi, merged and sorted. Filter to
  "today and later" and a lookahead window.
- **Canvas Assignments tab** — raw assignment list per course, with a link
  straight to each assignment in Canvas.
- **Syllabus Items tab** — the dates the parser found in your uploaded
  syllabus files. Syllabus formats vary a lot, so this is a best-effort text
  scan, not perfect extraction — the table is editable, so fix, delete, or
  add rows as needed. Edits here feed the Timeline tab live.
- **Files tab** — every file Canvas has for each course, with a direct link.

## Notes on syllabus parsing

The parser looks for lines containing something that looks like a date
(`Sept 5`, `9/5`, `9/5/26`, etc.) and keeps the surrounding line of text as
the description, tagging it with a rough category (exam, quiz, paper,
project, assignment, reading, other) based on keywords. It works well for
syllabi with a dated schedule table or a list of "Week X — date — topic"
lines. It will miss things in unusual formats — that's what the editable
table is for.

## Extending this

Some natural next steps if you want to take this further:
- Add `.ics` calendar export so due dates show up in your phone's calendar.
- Cache Canvas responses to disk so you don't re-fetch on every refresh.
- Add email/text reminders for items due soon.
- Support multiple syllabus formats more robustly with an LLM-based extractor
  instead of regex, for messier syllabi.
