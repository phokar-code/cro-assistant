"""
pepstores.com CRO Analyser
--------------------------
Usage:
  python main.py audit               # Full audit, saves baseline + report.html
  python main.py diff                # Compare current state to baseline
  python main.py tickets             # Generate markdown tickets from last audit
  python main.py journeys            # Run funnel journey runner (report_journeys.html)
  python main.py audit --no-ai       # Skip Claude AI analysis (faster)
  python main.py audit --pages 5     # Limit pages crawled
  python main.py journeys --j J1,J2  # Run specific journey IDs
  python main.py journeys --mobile   # Mobile only
  python main.py journeys --product  https://pepstores.com/products/...
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from analyzer.discovery    import PageDiscoverer
from analyzer.crawler      import PageCrawler
from analyzer.shopify_checks import run_shopify_checks
from analyzer.general_checks import (
    run_technical_checks,
    run_trust_checks,
    run_conversion_checks,
    run_performance_checks,
)
from analyzer.ai_analyst   import run_ai_analysis, generate_ticket
from analyzer.reporter     import (
    assemble_results,
    save_baseline,
    load_baseline,
    compute_diff,
    compute_site_score,
    generate_html_report,
    generate_markdown_tickets,
    generate_roadmap,
    bucket_issues,
    load_history,
    update_history,
    save_history,
)
from analyzer.journeys         import JourneyRunner, analyse_journeys
from analyzer.reporter_journey import generate_journey_report

TARGET_URL  = "https://pepstores.com"
TICKETS_DIR = Path(__file__).parent / "tickets"
STATE_DIR   = Path(__file__).parent / "state"
LAST_RESULTS_PATH = STATE_DIR / "last_audit.json"


# ── Core audit pipeline ───────────────────────────────────────────────────────

async def run_audit(max_pages: int = 8, use_ai: bool = True) -> list:
    print(f"\n{'='*60}")
    print(f"  pepstores.com CRO Audit")
    print(f"  {datetime.now().strftime('%d %B %Y %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Discover pages
    print("[1/5] Discovering pages …")
    discoverer = PageDiscoverer(TARGET_URL)
    pages      = await discoverer.discover(max_pages=max_pages)
    print(f"      {len(pages)} pages queued\n")
    for p in pages:
        print(f"      {p['page_type']:12}  {p['url']}")
    print()

    # 2. Crawl + functional tests
    print("[2/5] Crawling pages & running functional tests …")
    crawler       = PageCrawler(headless=True)
    crawled_pages = await crawler.crawl_pages(pages)
    print(f"{len(crawled_pages)} pages crawled successfully\n")

    min_pages = max(2, len(pages) // 2)
    if len(crawled_pages) < min_pages:
        print(f"[!] Only {len(crawled_pages)}/{len(pages)} pages returned — site is rate-limiting.")
        print(f"    Aborting to preserve the last good report. Try again in 30+ minutes.\n")
        return []

    # 3. Deterministic checks
    print("[3/5] Running checks …")
    for page in crawled_pages:
        page["shopify_check"]     = run_shopify_checks(page)
        page["technical_check"]   = run_technical_checks(page)
        page["trust_check"]       = run_trust_checks(page)
        page["conversion_check"]  = run_conversion_checks(page)
    print("Shopify, technical, trust, conversion checks done")

    print("Fetching PageSpeed Insights …")
    for page in crawled_pages:
        page["performance_check"] = await run_performance_checks(page["url"])
    print("Performance checks done\n")

    # 4. Assemble results
    results = assemble_results(crawled_pages)

    # 5. AI analysis
    if use_ai:
        print("[4/5] Running Claude AI analysis …")
        findings = {
            "site_url": TARGET_URL,
            "pages": results,
        }
        ai_text = run_ai_analysis(findings)
        if ai_text:
            print("AI analysis complete\n")
        else:
            print("AI analysis skipped (claude CLI not available)\n")
            ai_text = None
    else:
        print("[4/5] AI analysis skipped (--no-ai)\n")
        ai_text = None

    # 6. Save baseline + generate report
    print("[5/5] Saving baseline & generating report …")

    # Auto-diff against previous baseline (load BEFORE overwriting)
    old_baseline = load_baseline()
    auto_diff  = compute_diff(results, old_baseline) if old_baseline else None
    prev_score = old_baseline.get("site_score") if old_baseline else None
    if auto_diff:
        n_reg = len(auto_diff["regressions"])
        n_fix = len(auto_diff["fixed"])
        n_new = len(auto_diff["new_issues"])
        if n_reg or n_fix or n_new:
            print(f"  vs last run: {n_fix} fixed, {n_reg} regressions, {n_new} new")

    save_baseline(results, TARGET_URL)

    # History: record first-seen date for any issue we haven't seen before
    history = load_history()
    history = update_history(history, results)
    save_history(history)

    STATE_DIR.mkdir(exist_ok=True)
    LAST_RESULTS_PATH.write_text(
        json.dumps({"site_url": TARGET_URL, "pages": results, "ai_narrative": ai_text}, indent=2, default=list),
        encoding="utf-8",
    )

    report_path  = Path("report.html")
    roadmap_path = Path("roadmap.md")
    # Include journey data if it exists from a previous run
    journey_data_path = STATE_DIR / "last_journeys.json"
    journey_report = None
    if journey_data_path.exists():
        try:
            journey_report = json.loads(journey_data_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    generate_html_report(results, TARGET_URL, ai_text, diff=auto_diff, output_path=str(report_path),
                         journey_report=journey_report, history=history, prev_score=prev_score)
    generate_roadmap(results, str(roadmap_path))

    # Summary
    all_issues = bucket_issues(results)
    site_score = compute_site_score(results)

    print(f"\n{'='*60}")
    print(f"  AUDIT COMPLETE")
    print(f"  Overall Score:  {site_score}/100")
    print(f"  Critical:       {len(all_issues['critical'])}")
    print(f"  Warnings:       {len(all_issues['warning'])}")
    print(f"  Info:           {len(all_issues['info'])}")
    print(f"{'='*60}")
    print(f"\n  Report:   {report_path.resolve()}")
    print(f"  Roadmap:  {roadmap_path.resolve()}")
    print(f"  Baseline: {(STATE_DIR / 'baseline.json').resolve()}\n")

    return results


# ── Diff command ──────────────────────────────────────────────────────────────

async def run_diff(max_pages: int = 8, use_ai: bool = True) -> None:
    baseline = load_baseline()
    if not baseline:
        print("\n[!] No baseline found. Run 'python main.py audit' first.\n")
        sys.exit(1)

    print(f"\nBaseline from: {baseline['saved_at'][:10]}")
    print("Re-running audit to compare …\n")

    # Re-crawl current state
    discoverer = PageDiscoverer(TARGET_URL)
    pages      = await discoverer.discover(max_pages=max_pages)
    crawler    = PageCrawler(headless=True)
    crawled    = await crawler.crawl_pages(pages)

    for page in crawled:
        page["shopify_check"]    = run_shopify_checks(page)
        page["technical_check"]  = run_technical_checks(page)
        page["trust_check"]      = run_trust_checks(page)
        page["conversion_check"] = run_conversion_checks(page)
        page["performance_check"] = await run_performance_checks(page["url"])

    results = assemble_results(crawled)
    diff    = compute_diff(results, baseline)

    ai_text = None
    if use_ai and (diff["regressions"] or diff["new_issues"]):
        print("Running AI analysis on regressions …")
        findings = {"site_url": TARGET_URL, "pages": results}
        ai_text  = run_ai_analysis(findings)

    report_path = Path("report_diff.html")
    generate_html_report(results, TARGET_URL, ai_text, diff=diff, output_path=str(report_path))

    print(f"\n{'='*60}")
    print(f"  DIFF RESULTS")
    print(f"  Regressions:  {len(diff['regressions'])}")
    print(f"  Fixed:        {len(diff['fixed'])}")
    print(f"  New issues:   {len(diff['new_issues'])}")
    print(f"{'='*60}")

    if diff["regressions"]:
        print("\n  ⚠ REGRESSIONS (were passing, now failing):")
        for r in diff["regressions"]:
            print(f"    • [{r['severity'].upper()}] {r['title']}")
            print(f"      {r['url']}")

    if diff["fixed"]:
        print("\n  ✓ FIXED since baseline:")
        for f in diff["fixed"]:
            print(f"    • {f['title']}")

    print(f"\n  Diff report: {report_path.resolve()}\n")


# ── Tickets command ───────────────────────────────────────────────────────────

async def run_tickets(use_ai: bool = True) -> None:
    if not LAST_RESULTS_PATH.exists():
        print("\n[!] No audit results found. Run 'python main.py audit' first.\n")
        sys.exit(1)

    data    = json.loads(LAST_RESULTS_PATH.read_text(encoding="utf-8"))
    results = data["pages"]
    issues  = bucket_issues(results)
    critical_and_warnings = issues["critical"] + issues["warning"]

    print(f"\nGenerating tickets for {len(critical_and_warnings)} issues …")
    TICKETS_DIR.mkdir(exist_ok=True)

    ai_tickets: dict = {}
    if use_ai:
        for i, issue in enumerate(critical_and_warnings, 1):
            print(f"  [{i}/{len(critical_and_warnings)}] {issue['title'][:60]} …")
            ticket = generate_ticket(issue, issue["url"], issue["page_type"])
            if ticket:
                ai_tickets[issue["id"]] = ticket

    written = generate_markdown_tickets(results, TICKETS_DIR, ai_tickets)

    print(f"\n  Generated {len(written)} tickets in {TICKETS_DIR.resolve()}")
    for f in written:
        print(f"    {f.name}")
    print()


# ── Journeys command ──────────────────────────────────────────────────────────

async def run_journeys(args) -> None:
    journey_ids = [j.strip() for j in args.j.split(",")] if args.j else None

    if args.mobile and not args.desktop:
        devices = ["mobile"]
    elif args.desktop and not args.mobile:
        devices = ["desktop"]
    else:
        devices = ["desktop", "mobile"]

    print(f"\n{'='*60}")
    print(f"  pepstores.com Journey Runner")
    print(f"  {datetime.now().strftime('%d %B %Y %H:%M')}")
    print(f"  Devices:  {', '.join(devices)}")
    if journey_ids:
        print(f"  Journeys: {', '.join(journey_ids)}")
    print(f"{'='*60}\n")

    runner  = JourneyRunner(TARGET_URL)
    results = await runner.run_all(
        product_url=args.product,
        search_term=args.search,
        journey_ids=journey_ids,
        devices=devices,
    )

    report      = analyse_journeys(results)
    report_path = Path("report_journeys.html")
    generate_journey_report(report, TARGET_URL, str(report_path))

    # Persist raw journey data for follow-up diff / ticket generation
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "last_journeys.json").write_text(
        json.dumps(report, indent=2, default=list), encoding="utf-8"
    )

    summary = report["summary"]
    print(f"\n{'='*60}")
    print(f"  JOURNEYS COMPLETE")
    print(f"  Avg friction score:  {summary.get('avg_friction_score', 0)}/100")
    print(f"  Passed / Failed:     {summary.get('successful', 0)} / {summary.get('failed', 0)}")
    print(f"  Desktop friction:    {summary.get('desktop_friction', '—')}/100")
    print(f"  Mobile friction:     {summary.get('mobile_friction', '—')}/100")
    print(f"  Avg click depth:     {summary.get('avg_click_depth', '—')}")
    print(f"  Overlay interruptions: {summary.get('total_overlay_interruptions', 0)}")

    signals = report.get("signals", [])
    if signals:
        print(f"\n  Friction signals:")
        for s in signals:
            icon = "[X]" if s["severity"] == "critical" else "[!]"
            print(f"  {icon} [{s['severity'].upper()}] {s['title']}")

    print(f"\n{'='*60}")
    print(f"\n  Report: {report_path.resolve()}\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="pepstores.com CRO Analyser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    audit_p = sub.add_parser("audit", help="Full audit - baseline + report")
    audit_p.add_argument("--pages",  type=int, default=8, help="Max pages to crawl (default: 8)")
    audit_p.add_argument("--no-ai",  action="store_true", help="Skip Claude AI analysis")

    diff_p  = sub.add_parser("diff", help="Compare to baseline - regression report")
    diff_p.add_argument("--pages",  type=int, default=8)
    diff_p.add_argument("--no-ai",  action="store_true")

    tick_p  = sub.add_parser("tickets", help="Generate markdown tickets from last audit")
    tick_p.add_argument("--no-ai", action="store_true", help="Use template tickets only")

    jour_p  = sub.add_parser("journeys", help="Run funnel journey runner — produces report_journeys.html")
    jour_p.add_argument("--j",        default=None,    help="Comma-separated journey IDs, e.g. J1,J2")
    jour_p.add_argument("--mobile",   action="store_true", help="Run on mobile viewport only")
    jour_p.add_argument("--desktop",  action="store_true", help="Run on desktop viewport only")
    jour_p.add_argument("--product",  default=None,    help="Override product URL for direct-landing journeys")
    jour_p.add_argument("--search",   default="shirt", help="Search term for J5 (default: shirt)")

    args = parser.parse_args()

    if args.command == "audit":
        asyncio.run(run_audit(max_pages=args.pages, use_ai=not args.no_ai))
    elif args.command == "diff":
        asyncio.run(run_diff(max_pages=args.pages, use_ai=not args.no_ai))
    elif args.command == "tickets":
        asyncio.run(run_tickets(use_ai=not args.no_ai))
    elif args.command == "journeys":
        asyncio.run(run_journeys(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
