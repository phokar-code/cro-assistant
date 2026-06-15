"""Regenerate HTML report + AI narrative from last_audit.json without re-crawling."""
import json
from pathlib import Path
from datetime import datetime

STATE    = Path("state/last_audit.json")
OUTPUT   = Path("report.html")
ROADMAP  = Path("roadmap.md")

data = json.loads(STATE.read_text(encoding="utf-8"))
pages = data["pages"]

from analyzer.ai_analyst import run_ai_analysis
from analyzer.reporter   import generate_html_report, generate_roadmap, bucket_issues, compute_site_score

print("[1/2] Running Claude AI analysis …")
ai_result = run_ai_analysis({"site_url": data.get("site_url", "pepstores.com"), "pages": pages})
if ai_result:
    print("      AI analysis complete")
else:
    print("      AI analysis returned nothing — check claude CLI")

print("[2/2] Generating report …")
diff = data.get("diff")
generate_html_report(
    pages=pages,
    site_url=data.get("site_url", "https://pepstores.com"),
    ai_narrative=ai_result,
    diff=diff,
    output_path=str(OUTPUT),
)
generate_roadmap(pages, str(ROADMAP))

site_score = compute_site_score(pages)
buckets    = bucket_issues(pages)
print(f"\nDone.  Score: {site_score}/100  |  Critical: {len(buckets['critical'])}  |  Warnings: {len(buckets['warning'])}")
print(f"Report: {OUTPUT.resolve()}")
