"""Team feedback on audit issues — load, apply, save."""
import json
from datetime import date
from pathlib import Path

FEEDBACK_PATH = Path(__file__).parent.parent / "state" / "feedback.json"

STATUSES = {
    "confirmed":      "Confirmed",
    "fixed":          "Fixed — verify next run",
    "false_positive": "False positive",
    "watching":       "Watching",
}


def load_feedback(path=None) -> dict:
    p = Path(path) if path else FEEDBACK_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_feedback(feedback: dict, path=None) -> None:
    p = Path(path) if path else FEEDBACK_PATH
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(feedback, indent=2), encoding="utf-8")


def apply_feedback(results: list, feedback: dict) -> list:
    """Annotate detected issues with team feedback status and notes."""
    for page in results:
        for issue in page.get("all_issues", []):
            fb = feedback.get(issue["id"])
            if fb:
                issue["feedback_status"] = fb.get("status")
                issue["feedback_note"]   = fb.get("note", "")
                issue["feedback_by"]     = fb.get("by", "")
                issue["feedback_date"]   = fb.get("date", "")
    return results


def team_regressions(results: list, feedback: dict) -> list:
    """
    Returns IDs of issues the team marked 'fixed' that the tool still detects.
    The reporter promotes these to regressions in the HTML report.
    """
    detected = {
        issue["id"]
        for page in results
        for issue in page.get("all_issues", [])
    }
    return [
        iid for iid, fb in feedback.items()
        if not iid.startswith("_") and fb.get("status") == "fixed" and iid in detected
    ]
