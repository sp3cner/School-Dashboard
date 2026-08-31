"""
Thin wrapper around the Canvas LMS REST API.

Docs: https://canvas.instructure.com/doc/api/

You need:
  - base_url: your school's Canvas URL, e.g. "https://myschool.instructure.com"
  - api_token: a personal access token
      Canvas -> Account -> Settings -> "+ New Access Token"
"""

from __future__ import annotations
import requests
from datetime import datetime
from typing import Optional


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
        return self._get_all(
            f"courses/{course_id}/assignments",
            params={"per_page": 100, "order_by": "due_at"},
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
            rows.append({
                "source": "Canvas",
                "course": course_name,
                "title": a.get("name"),
                "due_at": a.get("due_at"),
                "points_possible": a.get("points_possible"),
                "html_url": a.get("html_url"),
                "submission_types": ", ".join(a.get("submission_types") or []),
            })
    return rows


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
                "filename": f.get("display_name"),
                "url": f.get("url"),
                "updated_at": f.get("updated_at"),
                "size_kb": round((f.get("size") or 0) / 1024, 1),
            })
    return rows
