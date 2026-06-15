"""Friction signal analysis — aggregates journey results into actionable CRO findings."""
from typing import Dict, List, Any

from .runner import JourneyResult, StepResult


def analyse_journeys(results: List[JourneyResult]) -> Dict[str, Any]:
    """Return a structured friction report usable by the HTML reporter."""
    if not results:
        return {"summary": {}, "journeys": [], "signals": [], "issues": []}

    desktop = [r for r in results if r.device == "desktop"]
    mobile  = [r for r in results if r.device == "mobile"]

    def avg_friction(group: List[JourneyResult]) -> int:
        return int(sum(r.friction_score for r in group) / len(group)) if group else 0

    summary = {
        "total_journeys":        len(results),
        "successful":            sum(1 for r in results if r.success),
        "failed":                sum(1 for r in results if not r.success),
        "avg_friction_score":    avg_friction(results),
        "desktop_friction":      avg_friction(desktop),
        "mobile_friction":       avg_friction(mobile),
        "avg_click_depth":       round(sum(r.click_depth for r in results) / len(results), 1),
        "total_overlay_interruptions": sum(r.overlay_interruptions for r in results),
    }

    return {
        "summary":  summary,
        "journeys": [r.to_dict() for r in results],
        "signals":  _extract_signals(results),
        "issues":   _extract_issues(results),
    }


def _extract_signals(results: List[JourneyResult]) -> List[Dict]:
    signals: List[Dict] = []

    # ── Failed journeys ────────────────────────────────────────────────────
    failed = [r for r in results if not r.success]
    if failed:
        names = ", ".join(f"{r.journey_id}" for r in failed[:4])
        signals.append({
            "type":     "journey_failure",
            "severity": "critical",
            "title":    f"{len(failed)} journey(s) could not complete the purchase",
            "detail":   (
                f"Journeys {names} failed — customers hitting this path cannot convert. "
                "Check the failed step and its error message."
            ),
        })

    # ── Overlay interruptions ─────────────────────────────────────────────
    total_overlays = sum(r.overlay_interruptions for r in results)
    if total_overlays > 0:
        signals.append({
            "type":     "overlay_interruption",
            "severity": "warning",
            "title":    f"Overlays interrupted the journey {total_overlays} time(s)",
            "detail":   (
                "Consent banners, chat widgets, or newsletter pop-ups blocked "
                "the primary funnel path. Each interruption increases abandonment."
            ),
        })

    # ── Mobile thumb zone failures ─────────────────────────────────────────
    mobile_results = [r for r in results if r.device == "mobile"]
    thumb_fails = [
        (r.journey_id, s.step_name)
        for r in mobile_results
        for s in r.steps
        if s.cta_viewport_pct is not None and s.cta_viewport_pct < 40
    ]
    if thumb_fails:
        signals.append({
            "type":     "thumb_zone_fail",
            "severity": "warning",
            "title":    f"Primary CTA in hard-to-reach zone on {len(thumb_fails)} mobile step(s)",
            "detail":   (
                "CTA was in the top 40% of the mobile screen — difficult to tap one-handed. "
                "Move ATC and checkout buttons into the lower half of the viewport."
            ),
        })

    # ── Slow steps ────────────────────────────────────────────────────────
    slow = [
        (r.journey_id, s.step_name, s.timing_ms)
        for r in results
        for s in r.steps
        if s.timing_ms > (4000 if r.device == "mobile" else 6000)
    ]
    if slow:
        worst_ms = max(ms for _, _, ms in slow)
        signals.append({
            "type":     "slow_steps",
            "severity": "warning",
            "title":    f"{len(slow)} journey step(s) exceeded acceptable load time",
            "detail":   (
                f"Slowest step: {worst_ms / 1000:.1f}s. "
                "Delays > 3s increase abandonment by 32% (Google research)."
            ),
        })

    # ── Console errors during journeys ─────────────────────────────────────
    error_steps = [
        (r.journey_id, s.step_name, s.console_errors)
        for r in results
        for s in r.steps
        if s.console_errors
    ]
    if error_steps:
        total_errors = sum(len(e) for _, _, e in error_steps)
        signals.append({
            "type":     "console_errors",
            "severity": "critical",
            "title":    f"{total_errors} JS error(s) across {len(error_steps)} journey step(s)",
            "detail":   (
                "JavaScript errors during navigation can break cart/checkout functionality "
                "silently. Review the console errors per step."
            ),
        })

    # ── ATC button disabled (in-store-only products) ───────────────────────
    atc_disabled = [
        r for r in results
        if any(
            s.action == "click_atc" and not s.success
            and s.error and "disabled" in s.error.lower()
            for s in r.steps
        )
    ]
    if atc_disabled:
        signals.append({
            "type":     "atc_disabled",
            "severity": "critical",
            "title":    f"ATC button disabled on {len(atc_disabled)} journey(s)",
            "detail":   (
                "Online-available product collection contains products where the ATC "
                "button is disabled or missing. Customers who land on these pages cannot "
                "add to cart, causing direct conversion loss."
            ),
        })

    # ── High click depth ──────────────────────────────────────────────────
    deep = [r for r in results if r.success and r.click_depth > 8]
    if deep:
        max_depth = max(r.click_depth for r in deep)
        signals.append({
            "type":     "high_click_depth",
            "severity": "warning",
            "title":    f"{len(deep)} successful journey(s) require > 8 clicks to checkout",
            "detail":   (
                f"Maximum click depth observed: {max_depth}. "
                "Best practice for mobile purchase: ≤ 6 taps. "
                "Reduce navigation layers or surface the product / ATC earlier."
            ),
        })

    return signals


def _extract_issues(results: List[JourneyResult]) -> List[Dict]:
    """Convert fatal journey failures to structured Issue dicts for the ticket system."""
    issues = []
    for r in results:
        if not r.success:
            failed_step = next((s for s in r.steps if not s.success), None)
            err_msg = failed_step.error if failed_step else "unknown error"
            issues.append({
                "id":          f"JOURNEY_{r.journey_id.upper()}_FAILED",
                "title":       f"Journey {r.journey_id} failed — {r.failed_at}",
                "description": (
                    f"{r.journey_name} on {r.device} failed at step '{r.failed_at}': {err_msg}"
                ),
                "severity":    "critical",
                "category":    "Journey / Funnel",
                "recommendation": (
                    f"Investigate step '{r.failed_at}' on {r.device}. "
                    "See journey report screenshot for visual context."
                ),
                "impact":      (
                    "Customers following this path cannot complete a purchase. "
                    "Direct conversion loss."
                ),
                "journey_id":  r.journey_id,
                "failed_step": r.failed_at,
                "device":      r.device,
            })
    return issues
