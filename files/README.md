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

## Saved data (survives restarts)

After you connect once or parse a syllabus, the app writes the results to a
local `data/` folder (gitignored). On the next launch it loads straight from
there, so you don't need to re-pull the API or re-upload syllabi — the
sidebar shows when Canvas was last synced. To pull fresh data, re-enter your
token and click **Refresh**. Your **turned in** marks are saved there too.
"Saved data → Clear all saved data" in the sidebar wipes the folder.

The API token is never part of this — only fetched data and your own edits.

## Using it

- **Timeline tab** — every Canvas assignment with a due date (and due time),
  plus every dated item pulled from your uploaded syllabi, merged and sorted.
  Filter to "today and later" and a lookahead window. The **Materials** /
  **Files** columns link to any files the instructor attached to an
  assignment's description. The **Turned in** column shows submission status.
- **Canvas Assignments tab** — assignment list per course, with links to
  each assignment and its attached files, plus a **Turned in** status.
  Native Canvas assignments report status automatically (submitted / graded /
  missing). For work Canvas can't see directly — **Gradescope** assignments
  you've submitted but that aren't graded yet — tick **Mark turned in**; that
  mark is saved.
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
- Add email/text reminders for items due soon.
- Support multiple syllabus formats more robustly with an LLM-based extractor
  instead of regex, for messier syllabi.
