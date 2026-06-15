"""
pepstores.com CRO Dashboard
Reads audit data from a private GitHub data repo via API.
Team feedback is written back to the same private repo.

Streamlit secrets required (App settings → Secrets):
  GITHUB_TOKEN  =  "ghp_xxxx"            # PAT with repo scope on DATA_REPO
  DATA_REPO     =  "owner/cro-data"      # private data repository
"""
import base64
import json
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analyzer.reporter import bucket_issues, compute_site_score
from analyzer.feedback import STATUSES

STATE_DIR   = Path("state")        # local dev fallback
REPORT_PATH = Path("report.html")  # local dev fallback

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
DATA_REPO    = st.secrets.get("DATA_REPO", "")
_API         = f"https://api.github.com/repos/{DATA_REPO}/contents"
_AUTH        = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
USE_API      = bool(GITHUB_TOKEN and DATA_REPO)

st.set_page_config(page_title="Pep CRO Dashboard", page_icon="📊", layout="wide")


# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.block-container { padding-top: 0.75rem !important; }

.pep-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 0 14px 0; border-bottom: 2px solid #1a5fb4; margin-bottom: 18px;
}
.pep-logo     { display: flex; align-items: center; gap: 12px; }
.pep-logo-box {
    background: #1a5fb4; color: #fff; font-weight: 800; font-size: 17px;
    letter-spacing: 2px; padding: 6px 11px; border-radius: 4px;
}
.pep-title { font-size: 17px; font-weight: 600; color: #1a1a2e; }
.pep-meta  { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #6b7280; }
.pep-badge { padding: 3px 11px; border-radius: 20px; font-size: 12px; font-weight: 600; }
.badge-ok   { background: #d1fae5; color: #065f46; }
.badge-warn { background: #fef3c7; color: #92400e; }
.badge-crit { background: #fee2e2; color: #991b1b; }

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
.delta-up     { color: #065f46; }
.delta-down   { color: #991b1b; }
.delta-flat   { color: #9ca3af; }

.metric-card {
    border-radius: 10px; background: #f9fafb;
    border: 1px solid #e5e7eb; padding: 14px 18px;
}
.metric-value { font-size: 28px; font-weight: 700; }
.metric-label { font-size: 12px; color: #6b7280; font-weight: 500; margin-top: 2px; }
.mc-crit    { color: #dc2626; }
.mc-warn    { color: #d97706; }
.mc-neutral { color: #1a1a2e; }

.fb-existing {
    background: #f0f9ff; border-left: 3px solid #0ea5e9;
    padding: 8px 12px; border-radius: 4px; font-size: 13px; margin-bottom: 8px;
}
.fb-team {
    background: #f5f3ff; border-left: 3px solid #7c3aed;
    padding: 8px 12px; border-radius: 4px; font-size: 13px; margin-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)


# ── GitHub API helpers ────────────────────────────────────────────────────────

def _gh_fetch_json(path: str):
    r = httpx.get(
        f"{_API}/{path}",
        headers={**_AUTH, "Accept": "application/vnd.github.v3.raw"},
        timeout=15,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _gh_get_sha(path: str):
    r = httpx.get(f"{_API}/{path}", headers=_AUTH, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("sha")


def _gh_put_json(path: str, data: dict, message: str) -> bool:
    sha     = _gh_get_sha(path)
    payload = {"message": message, "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode()}
    if sha:
        payload["sha"] = sha
    r = httpx.put(f"{_API}/{path}", json=payload, headers=_AUTH, timeout=15)
    return r.status_code in (200, 201)


# ── Data loading (cached) ─────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def load_all():
    if USE_API:
        audit    = _gh_fetch_json("state/last_audit.json")
        history  = _gh_fetch_json("state/history.json")  or {}
        baseline = _gh_fetch_json("state/baseline.json") or {}
        feedback = _gh_fetch_json("state/feedback.json") or {}
    else:
        def _r(p):
            fp = Path(p)
            return json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
        audit    = _r("state/last_audit.json") or None
        history  = _r("state/history.json")
        baseline = _r("state/baseline.json")
        feedback = _r("state/feedback.json")
    return audit, history, baseline, feedback


# ── Write helpers ─────────────────────────────────────────────────────────────

def _write_feedback(updated: dict, message: str) -> bool:
    if USE_API:
        ok = _gh_put_json("state/feedback.json", updated, message)
        if ok:
            st.cache_data.clear()
        return ok
    else:
        from analyzer.feedback import save_feedback as _save
        _save(updated)
        return True


def submit_issue_feedback(feedback: dict, issue_id: str, status: str, note: str, by: str) -> bool:
    updated = {**feedback, issue_id: {"status": status, "note": note, "by": by, "date": str(date.today())}}
    return _write_feedback(updated, f"feedback: {issue_id} → {status} ({by})")


def submit_manual_issue(feedback: dict, title: str, severity: str, description: str, by: str) -> bool:
    manual = list(feedback.get("_manual", []))
    manual.append({
        "id":          f"manual_{date.today().strftime('%Y%m%d')}_{len(manual)+1:03d}",
        "title":       title,
        "severity":    severity,
        "description": description,
        "by":          by,
        "date":        str(date.today()),
    })
    updated = {**feedback, "_manual": manual}
    return _write_feedback(updated, f"feedback: manual issue by {by}")


# ── Load data ─────────────────────────────────────────────────────────────────

audit, history, baseline, feedback = load_all()

if audit is None:
    st.error("No audit data found. Trigger the GitHub Actions workflow to seed the first run.")
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

longest  = f"{max(ages)}d" if ages else "—"
crit_col = "mc-crit" if n_critical > 0 else "mc-neutral"
warn_col = "mc-warn"  if n_warnings > 0 else "mc-neutral"

c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
with c1:
    st.markdown(f"""<div class="score-card {score_cls}">
        <div class="score-number">{score}/100</div>
        <div class="score-label">CRO Score</div>
        <div class="score-delta">{delta_html}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value {crit_col}">{n_critical}</div>
        <div class="metric-label">Critical issues</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value {warn_col}">{n_warnings}</div>
        <div class="metric-label">Warnings</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value mc-neutral">{longest}</div>
        <div class="metric-label">Longest open</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Filters")
    sev_filter = st.radio("Severity", ["All", "Critical", "Warning", "Info"])

    st.markdown("---")
    st.markdown("### Report an issue")
    st.caption("Found something the tool missed?")
    with st.form("manual_issue", clear_on_submit=True):
        m_title = st.text_input("Issue title *")
        m_sev   = st.selectbox("Severity", ["warning", "critical", "info"])
        m_desc  = st.text_area("What you found", height=80)
        m_name  = st.text_input("Your name *")
        if st.form_submit_button("Submit"):
            if m_title and m_name:
                ok = submit_manual_issue(feedback, m_title, m_sev, m_desc, m_name)
                if ok:
                    st.success("Added! Refresh to see it.")
                    st.rerun()
                else:
                    st.error("Save failed — check GITHUB_TOKEN secret.")
            else:
                st.warning("Title and name are required.")

    st.markdown("---")
    st.caption(f"**Last audit:** {saved_at}  \n**Schedule:** Mon 07:00 UTC")


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_issues, tab_pages, tab_report = st.tabs(["🔍 Issues", "📄 Page breakdown", "📥 Full report"])


# ─── Issues ───────────────────────────────────────────────────────────────────

with tab_issues:
    all_flat = issues["critical"] + issues["warning"] + issues["info"]

    # Inject team-reported manual issues
    for m in feedback.get("_manual", []):
        all_flat.append({
            "id":        m.get("id", "manual"),
            "severity":  m.get("severity", "warning"),
            "title":     m.get("title", ""),
            "impact":    m.get("description", ""),
            "page_type": "team",
            "_manual":   True,
            "feedback_by":   m.get("by", ""),
            "feedback_date": m.get("date", ""),
        })

    filtered = (
        all_flat if sev_filter == "All"
        else [i for i in all_flat if i["severity"] == sev_filter.lower()]
    )

    dismissed = [i for i in filtered if feedback.get(i["id"], {}).get("status") == "false_positive"]
    active    = [i for i in filtered if i not in dismissed]

    st.caption(f"{len(active)} active · {len(dismissed)} dismissed · filter: {sev_filter}")

    for issue in active:
        iid       = issue["id"]
        fb        = feedback.get(iid, {})
        is_manual = issue.get("_manual", False)

        first_seen = history.get(iid, "")
        if first_seen:
            days    = (today - date.fromisoformat(first_seen)).days
            age_str = "New" if days == 0 else (f"{days}d" if days < 14 else f"{days // 7}w")
        else:
            age_str = "New"

        if is_manual:
            scope = "👤 Team"
        elif issue.get("page_count", 1) > 1:
            scope = f"×{issue['page_count']} pages"
        else:
            scope = issue.get("page_type", "")

        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(issue["severity"], "")
        fb_label = f" · {STATUSES[fb['status']]}" if fb.get("status") else ""
        label    = f"{sev_icon} **{issue['title']}**  `{scope}` · {age_str}{fb_label}"

        with st.expander(label, expanded=False):
            if issue.get("impact"):
                st.markdown(f"**Impact:** {issue['impact']}")

            if is_manual:
                st.markdown(f"""<div class="fb-team">
                    👤 Reported by <strong>{issue['feedback_by']}</strong> · {issue['feedback_date']}
                </div>""", unsafe_allow_html=True)
            elif fb:
                st.markdown(f"""<div class="fb-existing">
                    💬 <strong>{STATUSES.get(fb['status'], fb['status'])}</strong>
                    {f'&nbsp;—&nbsp;"{fb["note"]}"' if fb.get("note") else ""}
                    <span style="color:#6b7280"> · {fb.get("by","?")} · {fb.get("date","")}</span>
                </div>""", unsafe_allow_html=True)

            if not is_manual:
                status_opts = list(STATUSES.keys())
                default_idx = status_opts.index(fb["status"]) if fb.get("status") in status_opts else 0

                with st.form(f"fb_{iid}", clear_on_submit=True):
                    fc1, fc2, fc3 = st.columns([2, 3, 2])
                    new_status = fc1.selectbox(
                        "Status", status_opts, index=default_idx,
                        format_func=lambda k: STATUSES[k],
                    )
                    new_note = fc2.text_input("Note (optional)", value=fb.get("note", ""))
                    new_name = fc3.text_input("Your name", value=fb.get("by", ""))

                    if st.form_submit_button("Save feedback"):
                        if new_name:
                            ok = submit_issue_feedback(feedback, iid, new_status, new_note, new_name)
                            if ok:
                                st.rerun()
                            else:
                                st.error("Save failed — check GITHUB_TOKEN secret.")
                        else:
                            st.warning("Your name is required.")

    if dismissed:
        with st.expander(f"🚫 Dismissed as false positives ({len(dismissed)})", expanded=False):
            for issue in dismissed:
                fb = feedback.get(issue["id"], {})
                st.markdown(
                    f"~~{issue['title']}~~ "
                    f"— {fb.get('note','no note')} *(by {fb.get('by','?')}, {fb.get('date','')})*"
                )


# ─── Page breakdown ───────────────────────────────────────────────────────────

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
        pd.DataFrame(page_rows), use_container_width=True, hide_index=True,
        column_config={
            "URL":      st.column_config.LinkColumn(),
            "Score":    st.column_config.NumberColumn(format="%d"),
            "Critical": st.column_config.NumberColumn(width="small"),
            "Warnings": st.column_config.NumberColumn(width="small"),
        },
    )

    scores_data = [
        {"Page": p["url"].split("/")[-1] or "home", "Category": cat, "Score": val}
        for p in pages for cat, val in p.get("scores", {}).items()
    ]
    if scores_data:
        st.subheader("Scores by category")
        st.bar_chart(pd.DataFrame(scores_data).pivot(index="Page", columns="Category", values="Score"))


# ─── Full report ──────────────────────────────────────────────────────────────

with tab_report:
    st.info("Includes per-page filmstrips, journey data, and the detailed roadmap.")

    if USE_API:
        if st.button("Fetch & download full HTML report"):
            with st.spinner("Fetching from data repo…"):
                try:
                    r = httpx.get(
                        f"{_API}/report.html",
                        headers={**_AUTH, "Accept": "application/vnd.github.v3.raw"},
                        timeout=30,
                    )
                    if r.status_code == 200:
                        st.download_button(
                            "⬇ Save report.html",
                            data=r.content,
                            file_name="pepstores_cro_report.html",
                            mime="text/html",
                        )
                    else:
                        st.warning("report.html not found in data repo yet.")
                except Exception as e:
                    st.error(f"Fetch failed: {e}")
    elif REPORT_PATH.exists():
        st.download_button(
            "⬇ Download full HTML report",
            data=REPORT_PATH.read_bytes(),
            file_name="pepstores_cro_report.html",
            mime="text/html",
        )
    else:
        st.warning("report.html not found.")
