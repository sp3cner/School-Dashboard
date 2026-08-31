"""
School Dashboard
Pulls assignments/files from Canvas and dated items from uploaded syllabi,
and shows everything in one due-date timeline.

Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

from canvas_client import (
    CanvasClient,
    flatten_assignments,
    flatten_files,
    attach_assignment_materials,
)
from syllabus_parser import parse_syllabus_file
import storage

st.set_page_config(page_title="School Dashboard", page_icon="🎓", layout="wide")

# Canvas timestamps are tz-aware UTC; syllabus dates are tz-naive. Convert Canvas
# times to naive local time everywhere so the two can be sorted/compared together.
LOCAL_TZ = datetime.now().astimezone().tzinfo

# Labels for the derived "turned in" column. Manual overrides always win, since
# they're how Gradescope (and any other externally-graded work) gets marked.
_STATUS_LABEL = {
    "Graded": "✅ Graded",
    "Submitted": "✅ Submitted",
    "Missing": "⚠️ Missing",
    "Not submitted": "— Not yet",
}


def turned_in_label(row, overrides: dict) -> str:
    if overrides.get(str(row.get("assignment_id"))):
        return "✅ Turned in"
    return _STATUS_LABEL.get(row.get("canvas_status"), row.get("canvas_status") or "—")

# ---------------------------------------------------------------------------
# Session state setup
# ---------------------------------------------------------------------------
if "canvas_client" not in st.session_state:
    st.session_state.canvas_client = None
if "courses" not in st.session_state:
    st.session_state.courses = []
# Canvas data and syllabus rows are reloaded from disk on startup, so a restart
# doesn't require re-pulling the API or re-uploading syllabi.
if "canvas_assignments" not in st.session_state:
    st.session_state.canvas_assignments = storage.load_df("canvas_assignments")
if "canvas_files" not in st.session_state:
    st.session_state.canvas_files = storage.load_df("canvas_files")
if "syllabus_items" not in st.session_state:
    st.session_state.syllabus_items = storage.load_df("syllabus_items")
if "submission_overrides" not in st.session_state:
    # {"<assignment_id>": true} — manual "turned in" marks, mainly for Gradescope
    st.session_state.submission_overrides = storage.load_json("overrides", {})

# ---------------------------------------------------------------------------
# Sidebar: Canvas connection
# ---------------------------------------------------------------------------
st.sidebar.header("Canvas connection")
base_url = st.sidebar.text_input(
    "Canvas URL", placeholder="https://myschool.instructure.com",
    help="Your school's Canvas homepage URL, no trailing slash needed.",
)
api_token = st.sidebar.text_input(
    "API token", type="password",
    help="Canvas → Account → Settings → '+ New Access Token'",
)
request_timeout = st.sidebar.slider(
    "Request timeout (seconds)", min_value=15, max_value=90, value=30,
    help="Raise this if you get 'Read timed out' errors — some Canvas instances are slow to respond.",
)

col_a, col_b = st.sidebar.columns(2)
connect_clicked = col_a.button("Connect", use_container_width=True)
refresh_clicked = col_b.button("Refresh", use_container_width=True)

if connect_clicked or refresh_clicked:
    if not base_url or not api_token:
        st.sidebar.error("Enter both the Canvas URL and an API token.")
    else:
        try:
            client = CanvasClient(base_url, api_token, timeout=request_timeout)
            profile = client.test_connection()
            st.session_state.canvas_client = client
            courses = client.get_courses()
            st.session_state.courses = courses

            with st.sidebar.status("Fetching assignments and files per course...", expanded=False):
                assignment_rows = flatten_assignments(client, courses)
                file_rows = flatten_files(client, courses)
                # Link each assignment to files referenced in its description.
                # Reuses file_rows above — no extra Canvas API calls.
                assignment_rows = attach_assignment_materials(
                    assignment_rows, file_rows, client.base_url
                )

            for a in assignment_rows:
                a.pop("description", None)  # raw HTML, only needed for the linking step
            st.session_state.canvas_assignments = pd.DataFrame(assignment_rows)
            st.session_state.canvas_files = pd.DataFrame(file_rows)

            # Persist so the next launch doesn't need the API.
            storage.save_df("canvas_assignments", st.session_state.canvas_assignments)
            storage.save_df("canvas_files", st.session_state.canvas_files)
            storage.touch_meta(canvas_synced_at=datetime.now().isoformat(timespec="seconds"),
                               canvas_url=base_url)

            fetched_courses = set(
                st.session_state.canvas_assignments["course"].unique()
            ) if not st.session_state.canvas_assignments.empty else set()
            all_course_names = {c.get("name") or c.get("course_code") for c in courses}
            skipped = all_course_names - fetched_courses

            st.sidebar.success(f"Connected as {profile.get('name', 'unknown user')} — "
                                f"{len(courses)} active course(s).")
            if skipped:
                st.sidebar.warning(
                    "Some courses timed out and were skipped: " + ", ".join(sorted(skipped)) +
                    ". Try raising the timeout slider and hitting Refresh."
                )
        except requests.exceptions.Timeout:
            st.sidebar.error(
                "Canvas didn't respond in time. Try raising the 'Request timeout' slider above "
                "and click Connect again — some Canvas instances are just slow."
            )
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                st.sidebar.error(
                    "Canvas rejected the API token (401 Unauthorized). Generate a fresh token at "
                    "canvas.its.virginia.edu → Account → Settings → '+ New Access Token', and paste "
                    "it with no leading/trailing spaces. If there's no such button, your school has "
                    "disabled self-service tokens."
                )
            else:
                st.sidebar.error(f"Canvas returned an error: {e}")
        except requests.exceptions.ConnectionError:
            st.sidebar.error(
                "Couldn't reach that Canvas URL. Double-check it's correct and that you have "
                "internet access (some schools require being on-campus or on a VPN)."
            )
        except Exception as e:
            st.sidebar.error(f"Couldn't connect: {e}")

_meta = storage.load_json("meta", {})
if _meta.get("canvas_synced_at"):
    _synced = _meta["canvas_synced_at"].replace("T", " ")
    st.sidebar.caption(
        f"📦 Showing saved data — last Canvas sync {_synced}. "
        "Re-enter your token and click Refresh to update."
    )

st.sidebar.divider()

# ---------------------------------------------------------------------------
# Sidebar: syllabus upload
# ---------------------------------------------------------------------------
st.sidebar.header("Syllabus upload")
uploaded_files = st.sidebar.file_uploader(
    "Upload syllabus files (PDF or DOCX)", type=["pdf", "docx"], accept_multiple_files=True
)
syllabus_year = st.sidebar.number_input(
    "Default year for dates without one", min_value=2020, max_value=2035,
    value=datetime.now().year,
)

if st.sidebar.button("Parse uploaded syllabi", use_container_width=True):
    if not uploaded_files:
        st.sidebar.error("Upload at least one file first.")
    else:
        all_rows = []
        for f in uploaded_files:
            try:
                rows = parse_syllabus_file(f.getvalue(), f.name, default_year=syllabus_year)
                all_rows.extend(rows)
            except Exception as e:
                st.sidebar.error(f"{f.name}: {e}")
        st.session_state.syllabus_items = pd.DataFrame(all_rows)
        storage.save_df("syllabus_items", st.session_state.syllabus_items)
        st.sidebar.success(
            f"Extracted {len(all_rows)} dated item(s) from {len(uploaded_files)} file(s). "
            "Saved — you won't need to re-upload on restart."
        )

st.sidebar.divider()

# ---------------------------------------------------------------------------
# Sidebar: saved data
# ---------------------------------------------------------------------------
with st.sidebar.expander("Saved data"):
    st.caption(
        "Canvas data, syllabus rows, and your 'turned in' marks are saved "
        "locally in `data/` (never committed). No API token is stored."
    )
    if st.button("Clear all saved data", use_container_width=True):
        storage.clear_all()
        for _k in ("canvas_assignments", "canvas_files", "syllabus_items"):
            st.session_state[_k] = pd.DataFrame()
        st.session_state.submission_overrides = {}
        st.rerun()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🎓 School Dashboard")

tab_timeline, tab_canvas, tab_syllabus, tab_files = st.tabs(
    ["📅 Timeline", "🖥️ Canvas Assignments", "📄 Syllabus Items", "📁 Files"]
)

# --- Combined timeline ------------------------------------------------------
with tab_timeline:
    st.subheader("Everything, sorted by due date")

    combined_rows = []

    if not st.session_state.canvas_assignments.empty:
        ca = st.session_state.canvas_assignments.copy()
        ca["date"] = (
            pd.to_datetime(ca["due_at"], errors="coerce", utc=True)
            .dt.tz_convert(LOCAL_TZ)
            .dt.tz_localize(None)
        )
        for _, r in ca.iterrows():
            if pd.isna(r["date"]):
                continue
            combined_rows.append({
                "date": r["date"],
                "time": r["date"].strftime("%I:%M %p").lstrip("0"),
                "turned_in": turned_in_label(r, st.session_state.submission_overrides),
                "source": "Canvas",
                "course": r["course"],
                "item": r["title"],
                "link": r["html_url"],
                "materials": r.get("materials", ""),
                "materials_url": r.get("materials_url", ""),
            })

    if not st.session_state.syllabus_items.empty:
        si = st.session_state.syllabus_items.copy()
        si["date"] = pd.to_datetime(si["date"], errors="coerce")
        for _, r in si.iterrows():
            if pd.isna(r["date"]):
                continue
            combined_rows.append({
                "date": r["date"],
                "time": "",  # syllabus text scans rarely include a due time
                "turned_in": "",
                "source": f"Syllabus ({r['source_file']})",
                "course": "",
                "item": f"[{r['category']}] {r['item']}",
                "link": "",
                "materials": "",
                "materials_url": "",
            })

    if not combined_rows:
        st.info("Connect Canvas and/or upload + parse a syllabus to see the timeline.")
    else:
        timeline_df = pd.DataFrame(combined_rows).sort_values("date")

        colf1, colf2 = st.columns(2)
        with colf1:
            only_upcoming = st.checkbox("Only show today and later", value=True)
        with colf2:
            days_ahead = st.slider("Look ahead (days)", 7, 180, 60)

        if only_upcoming:
            today = pd.Timestamp(datetime.now().date())
            cutoff = today + timedelta(days=days_ahead)
            timeline_df = timeline_df[(timeline_df["date"] >= today) & (timeline_df["date"] <= cutoff)]

        st.dataframe(
            timeline_df.assign(date=timeline_df["date"].dt.strftime("%a, %b %d %Y")),
            use_container_width=True,
            hide_index=True,
            column_config={
                "date": st.column_config.TextColumn("Date"),
                "time": st.column_config.TextColumn("Time due"),
                "turned_in": st.column_config.TextColumn("Turned in"),
                "link": st.column_config.LinkColumn("Link", display_text="Open"),
                "materials": st.column_config.TextColumn("Materials"),
                "materials_url": st.column_config.LinkColumn("Files", display_text="📎 Open"),
            },
        )

# --- Canvas assignments tab -------------------------------------------------
with tab_canvas:
    st.subheader("Canvas assignments by course")
    if st.session_state.canvas_assignments.empty:
        st.info("Connect to Canvas from the sidebar to load assignments.")
    else:
        overrides = st.session_state.submission_overrides
        df = st.session_state.canvas_assignments.copy()
        for _col in ("assignment_id", "canvas_status", "grade"):
            if _col not in df.columns:
                df[_col] = None  # tolerate data saved before these columns existed

        course_options = ["All courses"] + sorted(df["course"].dropna().unique().tolist())
        selected_course = st.selectbox("Filter by course", course_options)
        if selected_course != "All courses":
            df = df[df["course"] == selected_course]

        df["due_at"] = (
            pd.to_datetime(df["due_at"], errors="coerce", utc=True)
            .dt.tz_convert(LOCAL_TZ)
            .dt.tz_localize(None)
        )
        df = df.sort_values("due_at")
        df["turned_in"] = df.apply(lambda r: turned_in_label(r, overrides), axis=1)
        df["mark_turned_in"] = df["assignment_id"].map(
            lambda a: bool(overrides.get(str(a), False))
        )
        if "grade" in df.columns:  # null grades otherwise render as the text "None"
            df["grade"] = df["grade"].where(df["grade"].notna(), "")

        st.caption(
            "Tick **Mark turned in** for anything Canvas can't see on its own — e.g. a "
            "Gradescope assignment you've submitted but that isn't graded yet. "
            "Marks are saved and persist across restarts."
        )

        view_cols = [c for c in [
            "mark_turned_in", "turned_in", "course", "title", "due_at",
            "grade", "points_possible", "submission_types",
            "materials", "materials_url", "html_url", "assignment_id",
        ] if c in df.columns]

        edited = st.data_editor(
            df[view_cols],
            use_container_width=True,
            hide_index=True,
            disabled=[c for c in view_cols if c != "mark_turned_in"],
            column_order=[c for c in view_cols if c != "assignment_id"],
            column_config={
                "mark_turned_in": st.column_config.CheckboxColumn("Mark turned in"),
                "turned_in": st.column_config.TextColumn("Status"),
                "course": st.column_config.TextColumn("Course"),
                "title": st.column_config.TextColumn("Assignment"),
                "due_at": st.column_config.DatetimeColumn("Due", format="ddd, MMM D YYYY h:mm A"),
                "grade": st.column_config.TextColumn("Grade"),
                "points_possible": st.column_config.NumberColumn("Points"),
                "submission_types": st.column_config.TextColumn("Type"),
                "html_url": st.column_config.LinkColumn("Link", display_text="Open in Canvas"),
                "materials": st.column_config.TextColumn("Materials"),
                "materials_url": st.column_config.LinkColumn("Files", display_text="📎 Open"),
            },
            key=f"canvas_editor_{selected_course}",
        )

        new_overrides = dict(overrides)
        dirty = False
        for _, er in edited.iterrows():
            aid = str(er["assignment_id"])
            want = bool(er["mark_turned_in"])
            if want == bool(new_overrides.get(aid, False)):
                continue
            if want:
                new_overrides[aid] = True
            else:
                new_overrides.pop(aid, None)
            dirty = True
        if dirty:
            st.session_state.submission_overrides = new_overrides
            storage.save_json("overrides", new_overrides)
            st.rerun()

# --- Syllabus items tab -----------------------------------------------------
with tab_syllabus:
    st.subheader("Dates extracted from uploaded syllabi")
    st.caption(
        "This is a best-effort text scan — review the rows below. "
        "You can re-upload a cleaned-up file if a lot of dates were missed."
    )
    if st.session_state.syllabus_items.empty:
        st.info("Upload a syllabus PDF/DOCX from the sidebar and click 'Parse uploaded syllabi'.")
    else:
        edited = st.data_editor(
            st.session_state.syllabus_items,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="syllabus_editor",
        )
        if not edited.equals(st.session_state.syllabus_items):
            st.session_state.syllabus_items = edited
            storage.save_df("syllabus_items", edited)
        else:
            st.session_state.syllabus_items = edited

# --- Files tab ---------------------------------------------------------------
with tab_files:
    st.subheader("Files by course")
    if st.session_state.canvas_files.empty:
        st.info("Connect to Canvas from the sidebar to load files.")
    else:
        df = st.session_state.canvas_files.copy()
        course_options = ["All courses"] + sorted(df["course"].dropna().unique().tolist())
        selected_course = st.selectbox("Filter by course", course_options, key="files_course_filter")
        if selected_course != "All courses":
            df = df[df["course"] == selected_course]
        st.dataframe(
            df.sort_values("updated_at", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("Link", display_text="Open file"),
            },
        )
