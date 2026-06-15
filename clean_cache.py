import json
from pathlib import Path

REMOVE_IDS = {
    "TECH_NO_TITLE", "TECH_TITLE_LONG",
    "TECH_NO_META_DESC",
    "TECH_NO_H1", "TECH_MULTI_H1",
    "TECH_NO_BREADCRUMB",
    "TECH_IMG_NO_ALT",
    "TECH_NO_CANONICAL",
    "TECH_NO_OG",
}

path = Path("state/last_audit.json")
data = json.loads(path.read_text(encoding="utf-8"))

total_removed = 0
for page in data["pages"]:
    before = len(page.get("all_issues", []))
    page["all_issues"] = [i for i in page.get("all_issues", []) if i.get("id") not in REMOVE_IDS]
    removed = before - len(page["all_issues"])
    total_removed += removed
    if removed:
        print(page["page_type"], "—", removed, "SEO issues removed")

path.write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"\nTotal removed: {total_removed}. Cache updated.")
