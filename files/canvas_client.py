"""
Thin wrapper around the Canvas LMS REST API.

Docs: https://canvas.instructure.com/doc/api/

You need:
  - base_url: your school's Canvas URL, e.g. "https://myschool.instructure.com"
  - api_token: a personal access token
      Canvas -> Account -> Settings -> "+ New Access Token"
"""

from __future__ import annotations
import re
import requests
from datetime import datetime
from typing import Optional

from categorize import classify

# Matches "/files/12345" anywhere in a chunk of Canvas HTML (download links,
# preview links, data-api attributes all contain this).
_FILE_REF_RE = re.compile(r"/files/(\d+)")


class CanvasClient:
    def __init__(self, base_url: str, api_token: str, timeout: int = 30):
        self.base_url = base_url.strip().rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token.strip()}"}
        self.timeout = timeout

    def _get_all(self, endpoint: str, params: Optional[dict] = None) -> list:
        """Follows Canvas's Link-header pagination and returns all results."""
        url = f"{self.base_url}/api/v1/{endpoint}"
        results = []
        while url:
            resp = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
            url = resp.links.get("next", {}).get("url")
            params = None  # params are baked into the "next" url already
        return results

    def test_connection(self) -> dict:
        """Raises if the token/url is bad; returns the user's profile on success."""
        url = f"{self.base_url}/api/v1/users/self"
        resp = requests.get(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_courses(self, active_only: bool = True) -> list[dict]:
        params = {"per_page": 100, "include[]": "term"}
        if active_only:
            params["enrollment_state"] = "active"
        return self._get_all("courses", params=params)

    def get_assignments(self, course_id: int) -> list[dict]:
        # include[]=submission attaches the current user's submission object
        # (workflow_state, submitted_at, score, grade, missing/late flags) so
        # we can show whether each assignment has been turned in.
        return self._get_all(
            f"courses/{course_id}/assignments",
            params={"per_page": 100, "order_by": "due_at", "include[]": "submission"},
        )

    def get_files(self, course_id: int) -> list[dict]:
        return self._get_all(
            f"courses/{course_id}/files",
            params={"per_page": 100, "sort": "updated_at", "order": "desc"},
        )

    def get_planner_items(self, start_date: Optional[str] = None) -> list[dict]:
        """Unified upcoming items (assignments, quizzes, discussions, calendar events)
        across all courses. start_date is an ISO date string, defaults to today."""
        params = {"per_page": 100}
        if start_date:
            params["start_date"] = start_date
        return self._get_all("planner/items", params=params)

    def get_syllabus_body(self, course_id: int) -> str:
        """Canvas's own HTML syllabus field for a course, if the instructor filled it in."""
        data = self._get_all(
            f"courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )
        if data and isinstance(data[0], dict):
            return data[0].get("syllabus_body") or ""
        return ""


def flatten_assignments(client: CanvasClient, courses: list[dict]) -> list[dict]:
    """Fetch assignments for every course and flatten into one list of rows,
    each tagged with the course name, ready for a dataframe."""
    rows = []
    for course in courses:
        course_id = course.get("id")
        course_name = course.get("name") or course.get("course_code") or str(course_id)
        try:
            assignments = client.get_assignments(course_id)
        except requests.RequestException:
            continue
        for a in assignments:
            sub = _submission_summary(a)
            ext_url = (a.get("external_tool_tag_attributes") or {}).get("url") or ""
            sub_types = a.get("submission_types") or []
            rows.append({
                "source": "Canvas",
                "course": course_name,
                "course_id": course_id,
                "assignment_id": a.get("id"),
                "title": a.get("name"),
                "category": classify(a.get("name"), sub_types),
                "due_at": a.get("due_at"),
                "points_possible": a.get("points_possible"),
                "html_url": a.get("html_url"),
                "submission_types": ", ".join(sub_types),
                "canvas_status": sub["status"],
                "submitted_at": sub["submitted_at"],
                "grade": sub["grade"],
                "score": sub["score"],
                # True when Canvas hands grading off to an external tool
                # (Gradescope, etc.) — Canvas can't see the submission until a
                # grade is passed back, so these rely on the manual override.
                "external_tool": "external_tool" in sub_types,
                "is_gradescope": "gradescope" in ext_url.lower()
                or "gradescope" in (a.get("name") or "").lower(),
                # raw description HTML — used to find attached files, then dropped
                # before display (see attach_assignment_materials / app.py).
                "description": a.get("description") or "",
            })
    return rows


def _submission_summary(assignment: dict) -> dict:
    """Condense the Canvas ``submission`` sub-object into a status string plus
    the raw bits worth showing. Requires the assignments call to have used
    ``include[]=submission``; degrades gracefully if it didn't."""
    sub = assignment.get("submission") or {}
    state = sub.get("workflow_state")
    submitted_at = sub.get("submitted_at")
    score = sub.get("score")

    if state == "graded" or score is not None:
        status = "Graded"
    elif submitted_at or state in ("submitted", "pending_review"):
        status = "Submitted"
    elif sub.get("missing"):
        status = "Missing"
    else:
        status = "Not submitted"

    return {
        "status": status,
        "submitted_at": submitted_at,
        "score": score,
        "grade": sub.get("grade"),
    }


def extract_file_ids(html: str) -> list[int]:
    """Return the Canvas file IDs referenced in a chunk of HTML, in order,
    de-duplicated. Used to link an assignment to its attached materials."""
    seen: list[int] = []
    for match in _FILE_REF_RE.finditer(html or ""):
        fid = int(match.group(1))
        if fid not in seen:
            seen.append(fid)
    return seen


def attach_assignment_materials(
    assignment_rows: list[dict], file_rows: list[dict], base_url: str
) -> list[dict]:
    """For each assignment, find files referenced in its description HTML and
    attach browser-facing links to them.

    Reuses the already-fetched ``file_rows`` to resolve filenames, so this adds
    no extra API calls. Sets two fields on each row:
      - ``materials``: comma-separated filenames ("" if none)
      - ``materials_url``: a stable Canvas page URL — the file's own page when
        exactly one is attached, otherwise the assignment page listing them all
    """
    base_url = base_url.rstrip("/")
    names_by_id = {
        f["file_id"]: f.get("filename")
        for f in file_rows
        if f.get("file_id") is not None
    }
    for a in assignment_rows:
        ids = extract_file_ids(a.get("description", ""))
        names = [names_by_id.get(fid) or f"file {fid}" for fid in ids]
        a["materials"] = ", ".join(names)
        if len(ids) == 1:
            a["materials_url"] = f"{base_url}/courses/{a['course_id']}/files/{ids[0]}"
        elif len(ids) > 1:
            a["materials_url"] = a.get("html_url") or ""
        else:
            a["materials_url"] = ""
    return assignment_rows


def flatten_files(client: CanvasClient, courses: list[dict]) -> list[dict]:
    rows = []
    for course in courses:
        course_id = course.get("id")
        course_name = course.get("name") or course.get("course_code") or str(course_id)
        try:
            files = client.get_files(course_id)
        except requests.RequestException:
            continue
        for f in files:
            rows.append({
                "course": course_name,
                "file_id": f.get("id"),
                "filename": f.get("display_name"),
                "url": f.get("url"),
                "updated_at": f.get("updated_at"),
                "size_kb": round((f.get("size") or 0) / 1024, 1),
            })
    return rows
