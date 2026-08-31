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

st.set_page_config(page_title="School Dashboard", page_icon="🎓", layout="wide")

# ---------------------------------------------------------------------------
# Session state setup
# ---------------------------------------------------------------------------
if "canvas_client" not in st.session_state:
    st.session_state.canvas_client = None
if "courses" not in st.session_state:
    st.session_state.courses = []
if "canvas_assignments" not in st.session_state:
    st.session_state.canvas_assignments = pd.DataFrame()
if "canvas_files" not in st.session_state:
    st.session_state.canvas_files = pd.DataFrame()
if "syllabus_items" not in st.session_state:
    st.session_state.syllabus_items = pd.DataFrame()

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
        st.sidebar.success(f"Extracted {len(all_rows)} dated item(s) from {len(uploaded_files)} file(s).")

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

    # Canvas due_at is timezone-aware UTC; syllabus dates are timezone-naive.
    # Convert Canvas timestamps to naive local time so the two can be combined
    # and sorted together without "Cannot compare tz-naive and tz-aware" errors.
    local_tz = datetime.now().astimezone().tzinfo

    if not st.session_state.canvas_assignments.empty:
        ca = st.session_state.canvas_assignments.copy()
        ca["date"] = (
            pd.to_datetime(ca["due_at"], errors="coerce", utc=True)
            .dt.tz_convert(local_tz)
            .dt.tz_localize(None)
        )
        for _, r in ca.iterrows():
            if pd.isna(r["date"]):
                continue
            combined_rows.append({
                "date": r["date"],
                "time": r["date"].strftime("%I:%M %p").lstrip("0"),
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
        df = st.session_state.canvas_assignments.copy()
        course_options = ["All courses"] + sorted(df["course"].dropna().unique().tolist())
        selected_course = st.selectbox("Filter by course", course_options)
        if selected_course != "All courses":
            df = df[df["course"] == selected_course]
        df["due_at"] = pd.to_datetime(df["due_at"], errors="coerce")
        df = df.sort_values("due_at").drop(columns=["course_id"], errors="ignore")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "html_url": st.column_config.LinkColumn("Link", display_text="Open in Canvas"),
                "materials": st.column_config.TextColumn("Materials"),
                "materials_url": st.column_config.LinkColumn("Files", display_text="📎 Open"),
            },
        )

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
        )
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
