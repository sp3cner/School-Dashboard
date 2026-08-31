"""
One shared item classifier for both data sources, so a Canvas assignment
called "Lab 4" and a syllabus line "Lab 4 due" land in the same bucket and
the type filter works across everything.

``classify()`` returns exactly one label from ``CATEGORIES``.
"""

from __future__ import annotations

import re

CATEGORIES = [
    "Exam",
    "Quiz",
    "Lab",
    "Homework",
    "Project",
    "Paper",
    "Presentation",
    "Discussion",
    "Reading",
    "Class event",
    "Other",
]

# Checked in order — the first pattern that matches wins, so more specific
# categories come before the ones they'd otherwise be swallowed by
# (e.g. "final project" is a Project, not an Exam).
_PATTERNS: list[tuple[str, str]] = [
    ("Class event", r"\b(no class|holiday|recess|spring break|fall break|break day|snow day)\b"),
    ("Quiz", r"\b(quiz|quizzes)\b"),
    ("Lab", r"\b(lab|labs|laboratory|pre-?lab|post-?lab|lab report)\b"),
    ("Presentation", r"\b(presentation|present|poster session|demo day|showcase)\b"),
    ("Discussion", r"\b(discussion|forum post|response post|peer review|reflection post)\b"),
    ("Project", r"\b(project|milestone|capstone|deliverable|sprint)\b"),
    ("Exam", r"\b(exam|midterm|final|test|quiz bowl)\b"),
    ("Paper", r"\b(paper|essay|report|write-?up|memo|thesis|literature review)\b"),
    ("Homework",
     r"\b(homework|hw ?\d*|problem set|problem-set|pset|p-set|assignment|exercise|worksheet)\b"),
    ("Reading", r"\b(reading|read|chapter|textbook|pages? \d+)\b"),
]
_COMPILED = [(label, re.compile(pattern, re.IGNORECASE)) for label, pattern in _PATTERNS]

# Canvas submission-type hints — a stronger signal than the title text.
_SUBMISSION_TYPE_CATEGORY = {
    "online_quiz": "Quiz",
    "discussion_topic": "Discussion",
}


def classify(text: str, submission_types=None) -> str:
    """Best-effort category for an assignment/syllabus item.

    ``submission_types`` may be a Canvas list (``["online_quiz"]``) or the
    comma-joined string the dashboard stores; either is accepted.
    """
    if submission_types:
        if isinstance(submission_types, str):
            tokens = re.split(r"[,\s]+", submission_types.lower())
        else:
            tokens = [str(t).lower() for t in submission_types]
        for token in tokens:
            if token in _SUBMISSION_TYPE_CATEGORY:
                return _SUBMISSION_TYPE_CATEGORY[token]

    text = text or ""
    for label, rx in _COMPILED:
        if rx.search(text):
            return label
    return "Other"
