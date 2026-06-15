"""
Report generation, baseline management, and diff engine.
"""
import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .shopify_checks import Severity, Issue


STATE_DIR    = Path(__file__).parent.parent / "state"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
HISTORY_PATH = STATE_DIR / "history.json"


# ── Issue history (first-seen tracking) ──────────────────────────────────────

def load_history() -> Dict[str, str]:
    """Load {issue_id: first_seen_date} map. Returns {} if no file yet."""
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_history(history: Dict[str, str], pages: List[Dict]) -> Dict[str, str]:
    """Add first-seen date for any issue ID not already in history. Never overwrites."""
    today = datetime.now().strftime("%Y-%m-%d")
    for page in pages:
        for issue in page.get("all_issues", []):
            iid = issue["id"]
            if iid not in history:
                history[iid] = today
    return history


def save_history(history: Dict[str, str]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


def annotate_with_history(buckets: Dict[str, List], history: Dict[str, str]) -> Dict[str, List]:
    """Attach first_seen and days_open to each issue in the bucketed lists."""
    today = date.today()
    for bucket in buckets.values():
        for issue in bucket:
            first_seen = history.get(issue["id"])
            if first_seen:
                try:
                    fs = datetime.strptime(first_seen, "%Y-%m-%d").date()
                    issue["first_seen"] = first_seen
                    issue["days_open"] = (today - fs).days
                except ValueError:
                    pass
    return buckets


# ── Baseline management ───────────────────────────────────────────────────────

def save_baseline(results: List[Dict], site_url: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    baseline = {
        "site_url":   site_url,
        "saved_at":   datetime.now().isoformat(),
        "site_score": compute_site_score(results),
        "pages":      [],
    }
    for page in results:
        issues_snapshot = [
            {"id": i["id"], "severity": i["severity"], "title": i["title"]}
            for i in page.get("all_issues", [])
        ]
        baseline["pages"].append({
            "url":       page["url"],
            "page_type": page["page_type"],
            "scores":    page.get("scores", {}),
            "issue_ids": {i["id"] for i in issues_snapshot},
            "issues":    issues_snapshot,
        })

    path = STATE_DIR / "baseline.json"
    path.write_text(json.dumps(baseline, indent=2, default=list), encoding="utf-8")
    return path


def load_baseline() -> Optional[Dict]:
    path = STATE_DIR / "baseline.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compute_diff(current: List[Dict], baseline: Dict) -> Dict:
    """
    Returns:
      regressions:  issues passing in baseline, now failing
      fixed:        issues failing in baseline, now passing
      new_issues:   issues not seen in baseline at all
    """
    baseline_by_url: Dict[str, set] = {
        p["url"]: set(p["issue_ids"]) for p in baseline.get("pages", [])
    }

    regressions = []
    fixed       = []
    new_issues  = []

    for page in current:
        url        = page["url"]
        cur_ids    = {i["id"] for i in page.get("all_issues", [])}
        base_ids   = baseline_by_url.get(url, set())

        for issue in page.get("all_issues", []):
            iid = issue["id"]
            if iid not in base_ids:
                # Either page is new OR issue is new
                if url in baseline_by_url:
                    regressions.append({**issue, "url": url, "page_type": page.get("page_type")})
                else:
                    new_issues.append({**issue, "url": url, "page_type": page.get("page_type")})

        for base_issue in next(
            (p["issues"] for p in baseline.get("pages", []) if p["url"] == url), []
        ):
            if base_issue["id"] not in cur_ids:
                fixed.append({**base_issue, "url": url})

    return {
        "regressions": regressions,
        "fixed":       fixed,
        "new_issues":  new_issues,
        "baseline_date": baseline.get("saved_at", ""),
    }


# ── Results assembly ──────────────────────────────────────────────────────────

def assemble_results(crawled_pages: List[Dict]) -> List[Dict]:
    """Flatten check results into a list of page dicts for the report."""
    pages = []
    for page in crawled_pages:
        all_issues = []
        scores     = {}
        for check_key in ("shopify", "technical", "trust", "conversion", "performance"):
            check = page.get(f"{check_key}_check")
            if not check:
                continue
            scores[check_key] = check.score
            for issue in check.issues:
                all_issues.append({
                    "id":             issue.id,
                    "title":          issue.title,
                    "description":    issue.description,
                    "severity":       issue.severity.value,
                    "category":       issue.category,
                    "recommendation": issue.recommendation,
                    "impact":         getattr(issue, "impact", ""),
                })

        overall = int(sum(scores.values()) / len(scores)) if scores else 0

        pages.append({
            "url":        page["url"],
            "page_type":  page["page_type"],
            "screenshot": page.get("screenshot"),
            "scores":     scores,
            "overall_score": overall,
            "all_issues": all_issues,
            "shopify_env":  page.get("shopify_env", {}),
            "functional":   page.get("functional", {}),
        })
    return pages


# Issues that indicate a purchase is completely blocked — hard cap on site score
_P0_ISSUE_IDS = {
    "SHOP_NO_ATC_BUTTON",
    "SHOP_ATC_NO_RESPONSE",
    "SHOP_NO_CHECKOUT_BTN",
    "SHOP_CHECKOUT_BTN_DISABLED",
    "TECH_NO_HTTPS",
}


def compute_site_score(pages: List[Dict]) -> int:
    if not pages:
        return 0

    raw = int(sum(p["overall_score"] for p in pages) / len(pages))

    all_issue_ids = {i["id"] for p in pages for i in p.get("all_issues", [])}
    # Count unique critical issue types — a site-wide problem repeated on 8 pages
    # is 1 fixable issue, not 8 independent blockers.
    critical_count = len({
        i["id"] for p in pages for i in p.get("all_issues", [])
        if i.get("severity") == "critical"
    })

    score = raw
    # A purchase blocker (broken ATC or checkout) makes the score meaningless above 50
    if _P0_ISSUE_IDS & all_issue_ids:
        score = min(score, 50)
    # Many distinct critical issue types still cap the score
    if critical_count >= 10:
        score = min(score, 45)
    elif critical_count >= 5:
        score = min(score, 65)

    return score


def bucket_issues(pages: List[Dict]) -> Dict[str, List]:
    # Group all instances of each issue ID across pages
    by_id: Dict[str, List[Dict]] = {}
    for page in pages:
        for issue in page.get("all_issues", []):
            iid = issue["id"]
            by_id.setdefault(iid, []).append(
                {**issue, "url": page["url"], "page_type": page["page_type"]}
            )

    buckets: Dict[str, List] = {"critical": [], "warning": [], "info": []}
    emitted: set = set()

    for page in pages:
        for issue in page.get("all_issues", []):
            iid = issue["id"]
            instances = by_id[iid]

            if len(instances) > 1:
                # Site-wide issue: emit once, annotated with all affected pages
                if iid in emitted:
                    continue
                emitted.add(iid)
                item = {
                    **instances[0],
                    "affected_pages": [inst["url"] for inst in instances],
                    "page_count": len(instances),
                }
            else:
                # Page-specific: emit once per URL
                key = iid + page["url"]
                if key in emitted:
                    continue
                emitted.add(key)
                item = {**issue, "url": page["url"], "page_type": page["page_type"]}

            sev = issue["severity"]
            if sev == "critical":
                buckets["critical"].append(item)
            elif sev == "warning":
                buckets["warning"].append(item)
            else:
                buckets["info"].append(item)

    return buckets


# ── HTML report ───────────────────────────────────────────────────────────────

def generate_html_report(
    pages: List[Dict],
    site_url: str,
    ai_narrative: Optional[str],
    diff: Optional[Dict],
    output_path: str,
    journey_report: Optional[Dict] = None,
    history: Optional[Dict[str, str]] = None,
    prev_score: Optional[int] = None,
) -> None:
    from .reporter_journey import generate_journey_section_html

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")

    site_score  = compute_site_score(pages)
    all_issues  = bucket_issues(pages)
    if history:
        all_issues = annotate_with_history(all_issues, history)
    score_color = _score_color(site_score)
    score_label = _score_label(site_score)

    # Exec summary data
    score_delta = (site_score - prev_score) if prev_score is not None else None
    all_flat = all_issues["critical"] + all_issues["warning"] + all_issues["info"]
    longest_open = max(
        (i for i in all_flat if i.get("days_open", 0) > 0),
        key=lambda i: i["days_open"],
        default=None,
    )
    top_finding = (all_issues["critical"] or all_issues["warning"] or [None])[0]

    journey_html = generate_journey_section_html(journey_report) if journey_report else None

    html = template.render(
        site_url=site_url,
        report_date=datetime.now().strftime("%d %B %Y, %H:%M"),
        site_score=site_score,
        score_color=score_color,
        score_label=score_label,
        pages=pages,
        all_issues=all_issues,
        critical_count=len(all_issues["critical"]),
        warning_count=len(all_issues["warning"]),
        info_count=len(all_issues["info"]),
        ai_narrative=_markdown_to_html(ai_narrative) if ai_narrative else None,
        diff=diff,
        total_pages=len(pages),
        journey_html=journey_html,
        prev_score=prev_score,
        score_delta=score_delta,
        longest_open=longest_open,
        top_finding=top_finding,
    )

    Path(output_path).write_text(html, encoding="utf-8")


# ── Markdown ticket generation ────────────────────────────────────────────────

def generate_markdown_tickets(pages: List[Dict], tickets_dir: Path, ai_tickets: Dict[str, str]) -> List[Path]:
    tickets_dir.mkdir(exist_ok=True)
    written = []

    all_issues = bucket_issues(pages)
    # Only generate tickets for critical + warning
    for issue in all_issues["critical"] + all_issues["warning"]:
        iid       = re.sub(r"[^\w]", "_", issue["id"]).lower()
        slug      = re.sub(r"[^\w\s-]", "", issue["title"].lower()).strip()
        slug      = re.sub(r"[\s]+", "-", slug)[:50]
        filename  = f"{issue['severity']}_{iid}_{slug}.md"
        filepath  = tickets_dir / filename

        # Use AI-generated ticket if available, else template
        if issue["id"] in ai_tickets and ai_tickets[issue["id"]]:
            content = ai_tickets[issue["id"]]
        else:
            content = _default_ticket(issue)

        filepath.write_text(content, encoding="utf-8")
        written.append(filepath)

    return written


def _default_ticket(issue: Dict) -> str:
    return f"""# {issue['title']}

## Summary
{issue.get('impact') or issue['description']}

## Observed Behaviour
{issue['description']}

## Expected Behaviour
This issue should not occur. {issue['recommendation']}

## Steps to Reproduce
1. Visit {issue['url']}
2. Observe the issue described above.

## Business Impact
- Severity: {issue['severity'].upper()}
- Category: {issue['category']}
- Impact: {issue.get('impact', 'See description.')}

## Acceptance Criteria
- [ ] Issue no longer present on {issue['url']}
- [ ] Verified on desktop and mobile

## Technical Notes
{issue['recommendation']}

## Priority
{'P0' if issue['severity'] == 'critical' else 'P1'} — {issue['severity'].capitalize()} severity CRO issue
"""


def generate_roadmap(pages: List[Dict], output_path: str) -> None:
    all_issues = bucket_issues(pages)
    lines = [
        f"# pepstores.com — CRO Roadmap\n",
        f"Generated: {datetime.now().strftime('%d %B %Y')}\n\n",
        "## P0 — Fix Today (Conversion Blockers)\n",
        "| Issue | Page | Category | Impact |\n",
        "|---|---|---|---|\n",
    ]
    for i in all_issues["critical"]:
        lines.append(f"| {i['title']} | {i['url']} | {i['category']} | {i.get('impact','—')} |\n")

    lines += [
        "\n## P1 — This Sprint (High Impact)\n",
        "| Issue | Page | Category | Recommendation |\n",
        "|---|---|---|---|\n",
    ]
    for i in all_issues["warning"]:
        lines.append(f"| {i['title']} | {i['url']} | {i['category']} | {i.get('recommendation','—')[:80]} |\n")

    lines += [
        "\n## P2 — This Month (Optimisation)\n",
        "| Issue | Page | Category |\n",
        "|---|---|---|\n",
    ]
    for i in all_issues["info"]:
        lines.append(f"| {i['title']} | {i['url']} | {i['category']} |\n")

    Path(output_path).write_text("".join(lines), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _score_color(score: int) -> str:
    if score >= 80:
        return "#22c55e"
    if score >= 60:
        return "#f59e0b"
    if score >= 40:
        return "#f97316"
    return "#ef4444"


def _score_label(score: int) -> str:
    if score >= 80:
        return "Good"
    if score >= 60:
        return "Needs Work"
    if score >= 40:
        return "Poor"
    return "Critical"


def _markdown_to_html(text: str) -> str:
    """Convert markdown to HTML — handles headers, bold, tables, lists, HR."""
    if not text:
        return ""

    lines   = text.split("\n")
    output  = []
    in_list = False
    in_table = False
    table_rows: list = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return
        html = ['<table class="ai-table">']
        for ri, row in enumerate(table_rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            if ri == 0:
                html.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead><tbody>")
            elif re.match(r"^[\|\-\s:]+$", row):
                continue  # separator row
            else:
                html.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
        html.append("</tbody></table>")
        output.append("\n".join(html))
        table_rows = []
        in_table = False

    def flush_list():
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    def _inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         s)
        s = re.sub(r"`(.+?)`",       r"<code>\1</code>",     s)
        return s

    for line in lines:
        stripped = line.strip()

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            in_table = True
            table_rows.append(stripped)
            continue
        else:
            if in_table:
                flush_table()

        # Horizontal rule
        if re.match(r"^---+$", stripped):
            flush_list()
            output.append("<hr>")
            continue

        # Headers
        m = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if m:
            flush_list()
            level = len(m.group(1))
            output.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        # List item
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Numbered list
        m = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m:
            if in_list:
                output.append("</ul>")
                in_list = False
                output.append("<ol>")
                in_list = True  # reuse flag
            output.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Blank line
        if not stripped:
            flush_list()
            continue

        # Paragraph
        flush_list()
        output.append(f"<p>{_inline(stripped)}</p>")

    flush_list()
    if in_table:
        flush_table()

    return "\n".join(output)
