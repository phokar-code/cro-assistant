"""
pepstores.com CRO Dashboard
---------------------------
Deployed on Streamlit Community Cloud.
Data is populated by the weekly GitHub Actions audit run.

Reads from state/ directory (committed by CI):
  - state/last_audit.json   — full page results
  - state/history.json      — issue first-seen dates
  - state/baseline.json     — site score + saved_at timestamp
  - report.html             — full HTML report (download only)
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analyzer.reporter import bucket_issues, compute_site_score

STATE_DIR = Path("state")
REPORT_PATH = Path("report.html")

st.set_page_config(
    page_title="pepstores.com CRO Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data():
    audit_path    = STATE_DIR / "last_audit.json"
    history_path  = STATE_DIR / "history.json"
    baseline_path = STATE_DIR / "baseline.json"

    if not audit_path.exists():
        return None, {}, {}

    audit    = json.loads(audit_path.read_text(encoding="utf-8"))
    history  = json.loads(history_path.read_text(encoding="utf-8"))  if history_path.exists()  else {}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    return audit, history, baseline


audit, history, baseline = load_data()

if audit is None:
    st.error("No audit data found — the weekly CI hasn't run yet, or state files weren't committed.")
    st.stop()

pages      = audit["pages"]
issues     = bucket_issues(pages)
score      = compute_site_score(pages)
prev_score = baseline.get("site_score")
saved_at   = baseline.get("saved_at", "")[:10] or "unknown"
today      = date.today()

# Age of each tracked issue (days since first seen)
ages = []
for first_seen in history.values():
    try:
        ages.append((today - date.fromisoformat(first_seen)).days)
    except ValueError:
        pass

all_issues_flat = issues["critical"] + issues["warning"] + issues["info"]


# ── Header ────────────────────────────────────────────────────────────────────

st.title("pepstores.com — CRO Dashboard")
st.caption(f"Last audit: **{saved_at}**  ·  {len(pages)} pages crawled  ·  Data refreshes every Monday 07:00 UTC")

# ── Metrics row ───────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)
delta = (score - prev_score) if prev_score is not None else None
col1.metric("CRO Score",       f"{score}/100",                delta=f"{delta:+d} pts" if delta is not None else None)
col2.metric("Critical Issues", len(issues["critical"]),        delta=None)
col3.metric("Warnings",        len(issues["warning"]),         delta=None)
col4.metric("Longest Open",    f"{max(ages)}d" if ages else "—")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_issues, tab_pages, tab_report = st.tabs(["🔍 Issues", "📄 Page breakdown", "📥 Full report"])


# ─── Issues tab ───────────────────────────────────────────────────────────────

with tab_issues:
    col_filter, col_spacer = st.columns([2, 6])
    with col_filter:
        sev_filter = st.radio("Severity", ["All", "Critical", "Warning", "Info"], horizontal=True)

    filtered = all_issues_flat
    if sev_filter != "All":
        filtered = [i for i in all_issues_flat if i["severity"] == sev_filter.lower()]

    rows = []
    for issue in filtered:
        first_seen = history.get(issue["id"], "")
        if first_seen:
            days = (today - date.fromisoformat(first_seen)).days
            age_str = "New" if days == 0 else (f"{days}d" if days < 14 else f"{days // 7}w")
        else:
            age_str = "New"

        # Multi-page issues show page count; single-page shows page type
        if issue.get("page_count", 1) > 1:
            scope = f"×{issue['page_count']} pages"
        else:
            scope = issue.get("page_type", "")

        rows.append({
            "Severity":   issue["severity"].upper(),
            "Title":      issue["title"],
            "Impact":     issue.get("impact", ""),
            "Scope":      scope,
            "Open since": age_str,
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Severity": st.column_config.TextColumn(width="small"),
                "Scope":    st.column_config.TextColumn(width="small"),
                "Open since": st.column_config.TextColumn(width="small"),
            },
        )
        st.caption(f"{len(rows)} issue(s) shown")
    else:
        st.success("No issues at this severity level.")


# ─── Page breakdown tab ───────────────────────────────────────────────────────

with tab_pages:
    page_rows = []
    for page in pages:
        page_scores  = page.get("scores", {})
        page_issues  = page.get("all_issues", page.get("issues", []))
        critical_cnt = sum(1 for i in page_issues if i.get("severity") == "critical")
        warning_cnt  = sum(1 for i in page_issues if i.get("severity") == "warning")
        avg_score    = round(sum(page_scores.values()) / len(page_scores)) if page_scores else None

        page_rows.append({
            "URL":      page["url"],
            "Type":     page["page_type"],
            "Score":    avg_score,
            "Critical": critical_cnt,
            "Warnings": warning_cnt,
        })

    df_pages = pd.DataFrame(page_rows)
    st.dataframe(
        df_pages,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL":      st.column_config.LinkColumn(),
            "Score":    st.column_config.NumberColumn(format="%d"),
            "Critical": st.column_config.NumberColumn(width="small"),
            "Warnings": st.column_config.NumberColumn(width="small"),
        },
    )

    # Per-category bar chart
    if page_rows:
        scores_data = []
        for page in pages:
            for category, val in page.get("scores", {}).items():
                scores_data.append({"Page": page["url"].split("/")[-1] or "home", "Category": category, "Score": val})
        if scores_data:
            st.subheader("Scores by category")
            df_scores = pd.DataFrame(scores_data).pivot(index="Page", columns="Category", values="Score")
            st.bar_chart(df_scores)


# ─── Full report tab ──────────────────────────────────────────────────────────

with tab_report:
    if REPORT_PATH.exists():
        col_dl, col_info = st.columns([2, 6])
        with col_dl:
            st.download_button(
                "⬇ Download full HTML report",
                data=REPORT_PATH.read_bytes(),
                file_name="pepstores_cro_report.html",
                mime="text/html",
            )
        with col_info:
            st.info("The full report includes per-page filmstrips, journey data, and the detailed roadmap.")

        st.subheader("Report preview")
        html_content = REPORT_PATH.read_text(encoding="utf-8")
        components.html(html_content, height=900, scrolling=True)
    else:
        st.warning("report.html not found in the repo root. The CI workflow commits it after each audit run.")
