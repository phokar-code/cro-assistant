"""
pepstores.com CRO Dashboard — Streamlit app
Reads from state/ directory committed by the weekly GitHub Actions audit.
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analyzer.reporter import bucket_issues, compute_site_score

STATE_DIR   = Path("state")
REPORT_PATH = Path("report.html")

st.set_page_config(
    page_title="Pep CRO Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── Global CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Tighten Streamlit's default top padding */
.block-container { padding-top: 0.75rem !important; }

/* ── Header strip ── */
.pep-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0 14px 0;
    border-bottom: 2px solid #1a5fb4;
    margin-bottom: 18px;
}
.pep-logo      { display: flex; align-items: center; gap: 12px; }
.pep-logo-box  {
    background: #1a5fb4; color: #fff;
    font-weight: 800; font-size: 17px; letter-spacing: 2px;
    padding: 6px 11px; border-radius: 4px;
}
.pep-title { font-size: 17px; font-weight: 600; color: #1a1a2e; }
.pep-meta  { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #6b7280; }
.pep-badge { padding: 3px 11px; border-radius: 20px; font-size: 12px; font-weight: 600; }
.badge-ok   { background: #d1fae5; color: #065f46; }
.badge-warn { background: #fef3c7; color: #92400e; }
.badge-crit { background: #fee2e2; color: #991b1b; }

/* ── Score card ── */
.score-card {
    border-radius: 10px; padding: 16px 20px;
    display: flex; flex-direction: column; gap: 3px;
}
.score-good { background: #d1fae5; }
.score-warn { background: #fef3c7; }
.score-crit { background: #fee2e2; }
.score-number { font-size: 32px; font-weight: 800; line-height: 1; color: #1a1a2e; }
.score-label  { font-size: 12px; color: #6b7280; font-weight: 500; }
.score-delta  { font-size: 13px; font-weight: 600; margin-top: 2px; }
.delta-up   { color: #065f46; }
.delta-down { color: #991b1b; }
.delta-flat { color: #9ca3af; }

/* ── Metric cards ── */
.metric-card {
    border-radius: 10px; background: #f9fafb;
    border: 1px solid #e5e7eb; padding: 14px 18px; height: 100%;
}
.metric-value   { font-size: 28px; font-weight: 700; }
.metric-label   { font-size: 12px; color: #6b7280; font-weight: 500; margin-top: 2px; }
.mc-crit    { color: #dc2626; }
.mc-warn    { color: #d97706; }
.mc-neutral { color: #1a1a2e; }
</style>
""", unsafe_allow_html=True)


# ── Data ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data():
    if not (STATE_DIR / "last_audit.json").exists():
        return None, {}, {}
    audit    = json.loads((STATE_DIR / "last_audit.json").read_text(encoding="utf-8"))
    history  = json.loads((STATE_DIR / "history.json").read_text(encoding="utf-8"))  if (STATE_DIR / "history.json").exists()  else {}
    baseline = json.loads((STATE_DIR / "baseline.json").read_text(encoding="utf-8")) if (STATE_DIR / "baseline.json").exists() else {}
    return audit, history, baseline


audit, history, baseline = load_data()

if audit is None:
    st.error("No audit data found. Trigger the GitHub Actions workflow to run the first audit.")
    st.stop()

pages      = audit["pages"]
issues     = bucket_issues(pages)
score      = compute_site_score(pages)
prev_score = baseline.get("site_score")
saved_at   = baseline.get("saved_at", "")[:10] or "—"
today      = date.today()

ages = []
for first_seen in history.values():
    try:
        ages.append((today - date.fromisoformat(first_seen)).days)
    except ValueError:
        pass

n_critical = len(issues["critical"])
n_warnings = len(issues["warning"])
delta      = (score - prev_score) if prev_score is not None else None


# ── Compact header ────────────────────────────────────────────────────────────

if n_critical > 0:
    badge_cls, badge_txt = "badge-crit", f"⚠ {n_critical} critical"
elif n_warnings > 0:
    badge_cls, badge_txt = "badge-warn", f"! {n_warnings} warnings"
else:
    badge_cls, badge_txt = "badge-ok",   "✓ No critical issues"

page_word = "page" if len(pages) == 1 else "pages"

st.markdown(f"""
<div class="pep-header">
    <div class="pep-logo">
        <div class="pep-logo-box">PEP</div>
        <span class="pep-title">CRO Dashboard</span>
    </div>
    <div class="pep-meta">
        <span>Last audit: <strong>{saved_at}</strong></span>
        <span>&nbsp;·&nbsp;</span>
        <span>{len(pages)} {page_word} crawled</span>
        <span class="pep-badge {badge_cls}">{badge_txt}</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Metrics row ───────────────────────────────────────────────────────────────

score_cls = "score-good" if score >= 80 else "score-warn" if score >= 60 else "score-crit"

if delta is None or delta == 0:
    delta_html = '<span class="delta-flat">no change vs last run</span>'
elif delta > 0:
    delta_html = f'<span class="delta-up">↑ +{delta} pts vs last run</span>'
else:
    delta_html = f'<span class="delta-down">↓ {delta} pts vs last run</span>'

longest   = f"{max(ages)}d" if ages else "—"
crit_col  = "mc-crit" if n_critical > 0 else "mc-neutral"
warn_col  = "mc-warn"  if n_warnings > 0 else "mc-neutral"

col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

with col1:
    st.markdown(f"""
    <div class="score-card {score_cls}">
        <div class="score-number">{score}/100</div>
        <div class="score-label">CRO Score</div>
        <div class="score-delta">{delta_html}</div>
    </div>""", unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {crit_col}">{n_critical}</div>
        <div class="metric-label">Critical issues</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {warn_col}">{n_warnings}</div>
        <div class="metric-label">Warnings</div>
    </div>""", unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value mc-neutral">{longest}</div>
        <div class="metric-label">Longest open</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Filters")
    sev_filter = st.radio("Severity", ["All", "Critical", "Warning", "Info"], index=0)

    st.markdown("---")
    st.markdown("### Audit info")
    st.markdown(f"**Site:** pepstores.com")
    st.markdown(f"**Last run:** {saved_at}")
    st.markdown("**Schedule:** Every Monday 07:00 UTC")

    if REPORT_PATH.exists():
        st.markdown("---")
        st.download_button(
            "⬇ Download full report",
            data=REPORT_PATH.read_bytes(),
            file_name="pepstores_cro_report.html",
            mime="text/html",
        )


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_issues, tab_pages, tab_report = st.tabs(["🔍 Issues", "📄 Page breakdown", "📥 Full report"])


# Issues ──────────────────────────────────────────────────────────────────────

with tab_issues:
    all_issues_flat = issues["critical"] + issues["warning"] + issues["info"]
    filtered = (
        all_issues_flat if sev_filter == "All"
        else [i for i in all_issues_flat if i["severity"] == sev_filter.lower()]
    )

    rows = []
    for issue in filtered:
        first_seen = history.get(issue["id"], "")
        if first_seen:
            days    = (today - date.fromisoformat(first_seen)).days
            age_str = "New" if days == 0 else (f"{days}d" if days < 14 else f"{days // 7}w")
        else:
            age_str = "New"

        scope = (
            f"×{issue['page_count']} pages"
            if issue.get("page_count", 1) > 1
            else issue.get("page_type", "")
        )
        rows.append({
            "Severity":   issue["severity"].upper(),
            "Title":      issue["title"],
            "Impact":     issue.get("impact", ""),
            "Scope":      scope,
            "Open since": age_str,
        })

    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Severity":   st.column_config.TextColumn(width="small"),
                "Scope":      st.column_config.TextColumn(width="small"),
                "Open since": st.column_config.TextColumn(width="small"),
            },
        )
        st.caption(f"{len(rows)} issue(s) · filter: {sev_filter}")
    else:
        st.success("No issues at this severity level.")


# Page breakdown ──────────────────────────────────────────────────────────────

with tab_pages:
    page_rows = []
    for page in pages:
        ps = page.get("scores", {})
        pi = page.get("all_issues", page.get("issues", []))
        page_rows.append({
            "URL":      page["url"],
            "Type":     page["page_type"],
            "Score":    round(sum(ps.values()) / len(ps)) if ps else None,
            "Critical": sum(1 for i in pi if i.get("severity") == "critical"),
            "Warnings": sum(1 for i in pi if i.get("severity") == "warning"),
        })

    st.dataframe(
        pd.DataFrame(page_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL":      st.column_config.LinkColumn(),
            "Score":    st.column_config.NumberColumn(format="%d"),
            "Critical": st.column_config.NumberColumn(width="small"),
            "Warnings": st.column_config.NumberColumn(width="small"),
        },
    )

    scores_data = [
        {"Page": p["url"].split("/")[-1] or "home", "Category": cat, "Score": val}
        for p in pages
        for cat, val in p.get("scores", {}).items()
    ]
    if scores_data:
        st.subheader("Scores by category")
        df_pivot = pd.DataFrame(scores_data).pivot(index="Page", columns="Category", values="Score")
        st.bar_chart(df_pivot)


# Full report ─────────────────────────────────────────────────────────────────

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
            st.info("Includes per-page filmstrips, journey data, and the detailed roadmap.")
        components.html(REPORT_PATH.read_text(encoding="utf-8"), height=900, scrolling=True)
    else:
        st.warning("report.html not found — the CI workflow commits it after each audit run.")
