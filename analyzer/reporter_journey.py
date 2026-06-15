"""Journey filmstrip HTML report — generates report_journeys.html from journey results."""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def generate_journey_report(
    report: Dict,
    site_url: str,
    output_path: str = "report_journeys.html",
) -> None:
    summary  = report.get("summary", {})
    journeys = report.get("journeys", [])
    signals  = report.get("signals", [])

    avg_friction = summary.get("avg_friction_score", 0)
    friction_color = _friction_color(avg_friction)

    html = _PAGE_TEMPLATE.format(
        site_url=site_url,
        report_date=datetime.now().strftime("%d %B %Y, %H:%M"),
        avg_friction=avg_friction,
        friction_color=friction_color,
        friction_label=_friction_label(avg_friction),
        total_journeys=summary.get("total_journeys", 0),
        successful=summary.get("successful", 0),
        failed=summary.get("failed", 0),
        desktop_friction=summary.get("desktop_friction", "—"),
        mobile_friction=summary.get("mobile_friction", "—"),
        avg_click_depth=summary.get("avg_click_depth", "—"),
        total_overlays=summary.get("total_overlay_interruptions", 0),
        signals_html=_render_signals(signals),
        journeys_html=_render_journeys(journeys),
    )

    Path(output_path).write_text(html, encoding="utf-8")


def generate_journey_section_html(report: Dict) -> str:
    """Return a self-contained HTML fragment for embedding in the main audit report.

    Uses the light-theme CSS that matches report.html rather than the dark-theme
    standalone page style.
    """
    if not report:
        return ""
    summary  = report.get("summary", {})
    journeys = report.get("journeys", [])
    signals  = report.get("signals", [])

    avg_friction = summary.get("avg_friction_score", 0)
    fc = _friction_color(avg_friction)

    run_date = report.get("run_date", "")

    return _SECTION_TEMPLATE.format(
        avg_friction=avg_friction,
        friction_color=fc,
        friction_label=_friction_label(avg_friction),
        total_journeys=summary.get("total_journeys", 0),
        successful=summary.get("successful", 0),
        failed=summary.get("failed", 0),
        desktop_friction=summary.get("desktop_friction", "—"),
        mobile_friction=summary.get("mobile_friction", "—"),
        avg_click_depth=summary.get("avg_click_depth", "—"),
        total_overlays=summary.get("total_overlay_interruptions", 0),
        run_date=run_date,
        signals_html=_render_signals_light(signals),
        journeys_html=_render_journeys_light(journeys),
    )


# ── Rendering helpers ──────────────────────────────────────────────────────────

def _render_signals(signals: List[Dict]) -> str:
    if not signals:
        return "<p style='color:#6b7280'>No friction signals detected.</p>"
    items = []
    for s in signals:
        color = "#ef4444" if s["severity"] == "critical" else "#f59e0b"
        badge = "critical" if s["severity"] == "critical" else "warning"
        items.append(f"""
        <div class="signal-card signal-{badge}">
          <div class="signal-header">
            <span class="badge badge-{badge}">{badge.upper()}</span>
            <strong>{_esc(s['title'])}</strong>
          </div>
          <p class="signal-detail">{_esc(s['detail'])}</p>
        </div>""")
    return "\n".join(items)


def _render_journeys(journeys: List[Dict]) -> str:
    sections = []
    for j in journeys:
        steps_html = _render_filmstrip(j["steps"], j["device"])
        success = j.get("success", False)
        fs = j.get("friction_score", 0)
        status_class = "journey-ok" if success else "journey-fail"
        status_text = "PASSED" if success else f"FAILED at {j.get('failed_at', '?')}"

        sections.append(f"""
        <section class="journey-card {status_class}">
          <div class="journey-header">
            <div class="journey-title">
              <span class="journey-id">{_esc(j['journey_id'])}</span>
              <span class="journey-name">{_esc(j['journey_name'])}</span>
              <span class="device-badge device-{j['device']}">{j['device'].upper()}</span>
            </div>
            <div class="journey-meta">
              <span class="status-pill {'pill-ok' if success else 'pill-fail'}">{status_text}</span>
              <span class="meta-item">Friction <strong style="color:{_friction_color(fs)}">{fs}/100</strong></span>
              <span class="meta-item">Clicks <strong>{j.get('click_depth', '?')}</strong></span>
              <span class="meta-item">Time <strong>{j.get('total_time_ms', 0)/1000:.1f}s</strong></span>
              <span class="meta-item">Steps <strong>{j.get('successful_steps', 0)}/{j.get('total_steps', 0)}</strong></span>
            </div>
          </div>
          <div class="filmstrip-wrapper">
            <div class="filmstrip">
              {steps_html}
            </div>
          </div>
        </section>""")

    return "\n".join(sections)


def _render_filmstrip(steps: List[Dict], device: str) -> str:
    cells = []
    for i, s in enumerate(steps):
        ok = s.get("success", False)
        cell_class = "step-ok" if ok else "step-fail"
        timing = s.get("timing_ms", 0)
        timing_str = f"{timing/1000:.1f}s" if timing >= 1000 else f"{timing}ms"
        timing_class = "timing-slow" if timing > (4000 if device == "mobile" else 6000) else "timing-ok"

        # Thumbnail
        img_tag = ""
        if s.get("screenshot_b64"):
            img_tag = (
                f'<img src="data:image/jpeg;base64,{s["screenshot_b64"]}" '
                f'class="step-thumb" alt="{_esc(s.get("step_label",""))}" '
                f'onclick="openLightbox(this)">'
            )
        else:
            img_tag = '<div class="step-thumb-placeholder">No screenshot</div>'

        # CTA info
        cta_html = ""
        pct = s.get("cta_viewport_pct")
        if pct is not None:
            zone_color = "#22c55e" if pct >= 65 else ("#f59e0b" if pct >= 40 else "#ef4444")
            cta_html = f'<span class="cta-pos" style="color:{zone_color}" title="CTA position from top of viewport">CTA {pct:.0f}%</span>'

        scroll_px = s.get("scroll_to_cta_px")
        if scroll_px and scroll_px > 0:
            cta_html += f' <span class="scroll-hint">↓{scroll_px}px</span>'

        # Overlay indicator
        overlay_html = '<span class="overlay-dot" title="Overlay detected">⚠</span>' if s.get("overlay_detected") else ""

        # Console errors
        console_html = ""
        if s.get("console_errors"):
            n = len(s["console_errors"])
            errs = "\n".join(_esc(e) for e in s["console_errors"][:3])
            console_html = f'<span class="console-err" title="{errs}">{n} JS error{"s" if n>1 else ""}</span>'

        # Notes
        notes_html = ""
        if s.get("notes"):
            notes_html = "<br>".join(_esc(n) for n in s["notes"][:2])
            notes_html = f'<div class="step-notes">{notes_html}</div>'

        # Error message
        err_html = ""
        if s.get("error"):
            err_html = f'<div class="step-error" title="{_esc(s["error"])}">{_esc(s["error"][:80])}…</div>'

        cells.append(f"""
          <div class="filmstrip-cell {cell_class}">
            <div class="step-num">{i+1}</div>
            {img_tag}
            <div class="step-info">
              <div class="step-label">{_esc(s.get('step_label',''))}</div>
              <div class="step-timing {timing_class}">{timing_str}</div>
              {cta_html}
              {overlay_html}
              {console_html}
              {notes_html}
              {err_html}
            </div>
          </div>""")

    return "".join(cells)


def _esc(text: str) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _friction_color(score: int) -> str:
    if score >= 80:
        return "#22c55e"
    if score >= 60:
        return "#f59e0b"
    if score >= 40:
        return "#f97316"
    return "#ef4444"


def _friction_label(score: int) -> str:
    if score >= 80:
        return "Low Friction"
    if score >= 60:
        return "Moderate Friction"
    if score >= 40:
        return "High Friction"
    return "Severe Friction"


# ── Page template ──────────────────────────────────────────────────────────────

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Journey Report — {site_url}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background: #0f172a; color: #e2e8f0; font-size: 14px; }}
  a {{ color: #60a5fa; }}

  /* ── Header ── */
  .page-header {{ background: #1e293b; border-bottom: 1px solid #334155;
                  padding: 24px 32px; display: flex; align-items: center;
                  justify-content: space-between; flex-wrap: wrap; gap: 16px; }}
  .site-url {{ font-size: 18px; font-weight: 700; color: #f1f5f9; }}
  .report-date {{ font-size: 12px; color: #94a3b8; }}

  /* ── Score bar ── */
  .score-bar {{ background: #1e293b; border-bottom: 1px solid #334155;
               padding: 20px 32px; display: flex; gap: 32px; flex-wrap: wrap; }}
  .score-item {{ display: flex; flex-direction: column; gap: 4px; }}
  .score-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase;
                  letter-spacing: .05em; }}
  .score-value {{ font-size: 28px; font-weight: 700; }}
  .score-sub {{ font-size: 12px; color: #94a3b8; }}

  /* ── Layout ── */
  main {{ max-width: 1600px; margin: 0 auto; padding: 24px 32px; }}

  /* ── Signals ── */
  .signals-section {{ margin-bottom: 32px; }}
  .section-title {{ font-size: 16px; font-weight: 600; color: #f1f5f9;
                    margin-bottom: 12px; }}
  .signal-card {{ background: #1e293b; border-radius: 8px; padding: 14px 18px;
                  margin-bottom: 10px; border-left: 4px solid; }}
  .signal-critical {{ border-color: #ef4444; }}
  .signal-warning  {{ border-color: #f59e0b; }}
  .signal-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
  .signal-detail {{ font-size: 13px; color: #94a3b8; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
            font-size: 10px; font-weight: 700; letter-spacing: .05em; }}
  .badge-critical {{ background: #ef4444; color: #fff; }}
  .badge-warning   {{ background: #f59e0b; color: #000; }}

  /* ── Journey cards ── */
  .journey-card {{ background: #1e293b; border-radius: 12px; margin-bottom: 28px;
                   overflow: hidden; border: 1px solid #334155; }}
  .journey-ok   {{ border-top: 3px solid #22c55e; }}
  .journey-fail {{ border-top: 3px solid #ef4444; }}
  .journey-header {{ padding: 16px 20px; display: flex; align-items: flex-start;
                     justify-content: space-between; flex-wrap: wrap; gap: 12px;
                     border-bottom: 1px solid #334155; }}
  .journey-title {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .journey-id {{ font-size: 20px; font-weight: 700; color: #f1f5f9; }}
  .journey-name {{ font-size: 14px; color: #94a3b8; }}
  .device-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px;
                   font-weight: 600; }}
  .device-mobile  {{ background: #7c3aed; color: #fff; }}
  .device-desktop {{ background: #0284c7; color: #fff; }}
  .journey-meta {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
  .status-pill {{ padding: 4px 12px; border-radius: 20px; font-size: 12px;
                  font-weight: 700; }}
  .pill-ok   {{ background: #14532d; color: #4ade80; }}
  .pill-fail {{ background: #450a0a; color: #f87171; }}
  .meta-item {{ font-size: 13px; color: #94a3b8; }}

  /* ── Filmstrip ── */
  .filmstrip-wrapper {{ overflow-x: auto; padding: 16px 20px; }}
  .filmstrip {{ display: flex; gap: 12px; min-width: max-content; }}
  .filmstrip-cell {{ width: 200px; background: #0f172a; border-radius: 8px;
                     border: 2px solid; overflow: hidden; flex-shrink: 0; }}
  .step-ok   {{ border-color: #22c55e33; }}
  .step-fail {{ border-color: #ef444488; }}
  .step-num {{ position: relative; background: #1e293b; padding: 4px 10px;
               font-size: 11px; color: #64748b; }}
  .step-thumb {{ width: 100%; height: 140px; object-fit: cover; object-position: top;
                 display: block; cursor: pointer; transition: opacity .2s; }}
  .step-thumb:hover {{ opacity: .85; }}
  .step-thumb-placeholder {{ width: 100%; height: 140px; background: #1e293b;
                              display: flex; align-items: center; justify-content: center;
                              color: #475569; font-size: 12px; }}
  .step-info {{ padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }}
  .step-label {{ font-size: 12px; font-weight: 600; color: #f1f5f9;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .step-timing {{ font-size: 11px; }}
  .timing-ok   {{ color: #6b7280; }}
  .timing-slow {{ color: #f59e0b; font-weight: 600; }}
  .cta-pos {{ font-size: 11px; font-weight: 600; }}
  .scroll-hint {{ font-size: 11px; color: #94a3b8; }}
  .overlay-dot {{ font-size: 13px; color: #f59e0b; }}
  .console-err {{ font-size: 11px; color: #ef4444; cursor: help; }}
  .step-notes {{ font-size: 11px; color: #4ade80; margin-top: 2px; }}
  .step-error {{ font-size: 11px; color: #f87171; margin-top: 2px;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                 cursor: help; }}

  /* ── Lightbox ── */
  #lightbox {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,.85);
               z-index: 9999; align-items: center; justify-content: center; cursor: zoom-out; }}
  #lightbox.open {{ display: flex; }}
  #lightbox img {{ max-width: 90vw; max-height: 90vh; border-radius: 8px;
                   box-shadow: 0 20px 60px #000; }}
</style>
</head>
<body>

<div class="page-header">
  <div>
    <div class="site-url">{site_url} — Journey Report</div>
    <div class="report-date">Generated {report_date}</div>
  </div>
</div>

<div class="score-bar">
  <div class="score-item">
    <span class="score-label">Avg Friction Score</span>
    <span class="score-value" style="color:{friction_color}">{avg_friction}/100</span>
    <span class="score-sub">{friction_label}</span>
  </div>
  <div class="score-item">
    <span class="score-label">Journeys Run</span>
    <span class="score-value">{total_journeys}</span>
    <span class="score-sub">{successful} passed · {failed} failed</span>
  </div>
  <div class="score-item">
    <span class="score-label">Desktop Friction</span>
    <span class="score-value" style="color:{friction_color}">{desktop_friction}/100</span>
  </div>
  <div class="score-item">
    <span class="score-label">Mobile Friction</span>
    <span class="score-value" style="color:{friction_color}">{mobile_friction}/100</span>
  </div>
  <div class="score-item">
    <span class="score-label">Avg Click Depth</span>
    <span class="score-value">{avg_click_depth}</span>
    <span class="score-sub">taps to checkout</span>
  </div>
  <div class="score-item">
    <span class="score-label">Overlay Interruptions</span>
    <span class="score-value">{total_overlays}</span>
  </div>
</div>

<main>

<section class="signals-section">
  <h2 class="section-title">Friction Signals</h2>
  {signals_html}
</section>

<section>
  <h2 class="section-title">Journey Filmstrips</h2>
  {journeys_html}
</section>

</main>

<div id="lightbox" onclick="closeLightbox()">
  <img id="lightbox-img" src="" alt="">
</div>

<script>
function openLightbox(img) {{
  document.getElementById('lightbox-img').src = img.src;
  document.getElementById('lightbox').classList.add('open');
}}
function closeLightbox() {{
  document.getElementById('lightbox').classList.remove('open');
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLightbox(); }});
</script>
</body>
</html>"""


# ── Light-theme section helpers (for embedding in main report.html) ────────────

def _render_signals_light(signals: List[Dict]) -> str:
    if not signals:
        return "<p style='color:#6b7280;font-size:13px'>No friction signals detected.</p>"
    items = []
    for s in signals:
        is_crit = s["severity"] == "critical"
        bg   = "#FEF3F2" if is_crit else "#FFFAEB"
        bdr  = "#FCA5A5" if is_crit else "#FCD34D"
        clr  = "#D92D20" if is_crit else "#B54708"
        badge_bg = clr
        items.append(f"""
<div style="border:1px solid {bdr};border-left:4px solid {clr};border-radius:6px;
            padding:12px 16px;margin-bottom:8px;background:{bg}">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
    <span style="background:{badge_bg};color:#fff;font-size:10px;font-weight:700;
                 padding:2px 7px;border-radius:4px;letter-spacing:.05em">
      {_esc(s['severity'].upper())}
    </span>
    <strong style="font-size:13px;color:#111827">{_esc(s['title'])}</strong>
  </div>
  <p style="font-size:12px;color:#6b7280;margin:0">{_esc(s['detail'])}</p>
</div>""")
    return "\n".join(items)


def _render_journeys_light(journeys: List[Dict]) -> str:
    sections = []
    for j in journeys:
        success = j.get("success", False)
        fs = j.get("friction_score", 0)
        fc = _friction_color(fs)
        status_bg = "#ECFDF3" if success else "#FEF3F2"
        status_clr = "#027A48" if success else "#D92D20"
        status_bdr = "#6CE9A6" if success else "#FCA5A5"
        status_text = "PASSED" if success else f"FAILED at '{j.get('failed_at', '?')}'"
        device = j.get("device", "")
        device_bg = "#7c3aed" if device == "mobile" else "#0284c7"

        steps_html = _render_filmstrip_light(j.get("steps", []), device)

        sections.append(f"""
<div style="border:1px solid #e5e7eb;border-radius:8px;margin-bottom:20px;overflow:hidden;
            {'border-top:3px solid #D92D20' if not success else 'border-top:3px solid #027A48'}">
  <div style="padding:14px 18px;background:#f9fafb;border-bottom:1px solid #e5e7eb;
              display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:10px">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-size:18px;font-weight:700;color:#111827">{_esc(j['journey_id'])}</span>
      <span style="font-size:13px;color:#6b7280">{_esc(j.get('journey_name',''))}</span>
      <span style="background:{device_bg};color:#fff;font-size:11px;font-weight:600;
                   padding:2px 8px;border-radius:4px">{device.upper()}</span>
    </div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span style="background:{status_bg};color:{status_clr};border:1px solid {status_bdr};
                   padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700">
        {_esc(status_text)}
      </span>
      <span style="font-size:12px;color:#6b7280">Friction <strong style="color:{fc}">{fs}/100</strong></span>
      <span style="font-size:12px;color:#6b7280">Clicks <strong>{j.get('click_depth','?')}</strong></span>
      <span style="font-size:12px;color:#6b7280">Time <strong>{j.get('total_time_ms',0)/1000:.1f}s</strong></span>
      <span style="font-size:12px;color:#6b7280">Steps <strong>{j.get('successful_steps',0)}/{j.get('total_steps',0)}</strong></span>
    </div>
  </div>
  <div style="overflow-x:auto;padding:14px 16px;background:#fff">
    <div style="display:flex;gap:10px;min-width:max-content">
      {steps_html}
    </div>
  </div>
</div>""")
    return "\n".join(sections)


def _render_filmstrip_light(steps: List[Dict], device: str) -> str:
    cells = []
    for i, s in enumerate(steps):
        ok = s.get("success", False)
        timing = s.get("timing_ms", 0)
        timing_str = f"{timing/1000:.1f}s" if timing >= 1000 else f"{timing}ms"
        slow = timing > (4000 if device == "mobile" else 6000)
        timing_clr = "#B54708" if slow else "#6b7280"
        border_clr = "#6CE9A6" if ok else "#FCA5A5"
        bg_clr = "#ECFDF3" if ok else "#FEF3F2"

        img_tag = ""
        if s.get("screenshot_b64"):
            uid = f"jss_{i}_{hash(s.get('url',''))}"
            img_tag = (
                f'<img src="data:image/jpeg;base64,{s["screenshot_b64"]}" '
                f'style="width:170px;height:120px;object-fit:cover;object-position:top;'
                f'display:block;cursor:pointer;border-bottom:1px solid #e5e7eb" '
                f'alt="{_esc(s.get("step_label",""))}" '
                f'onclick="lbxJourneyOpen(this)">'
            )
        else:
            img_tag = ('<div style="width:170px;height:120px;background:#f3f4f6;'
                       'display:flex;align-items:center;justify-content:center;'
                       'font-size:11px;color:#9ca3af">No screenshot</div>')

        # CTA info
        cta_html = ""
        pct = s.get("cta_viewport_pct")
        if pct is not None:
            zone_clr = "#027A48" if pct >= 65 else ("#B54708" if pct >= 40 else "#D92D20")
            cta_html = f'<span style="font-size:10px;color:{zone_clr};font-weight:600">CTA {pct:.0f}%</span> '

        # Overlay
        overlay_html = '<span style="font-size:11px;color:#B54708" title="Overlay detected">&#9888;</span> ' if s.get("overlay_detected") else ""

        # Console errors
        console_html = ""
        if s.get("console_errors"):
            n = len(s["console_errors"])
            console_html = f'<span style="font-size:10px;color:#D92D20">{n} JS err</span>'

        # Notes
        notes_html = ""
        if s.get("notes"):
            note = s["notes"][0] if s["notes"] else ""
            notes_html = f'<div style="font-size:10px;color:#027A48;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:165px" title="{_esc(note)}">{_esc(note[:35])}</div>'

        # Error
        err_html = ""
        if s.get("error"):
            err_text = s.get("error", "")
            err_html = f'<div style="font-size:10px;color:#D92D20;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:165px" title="{_esc(err_text)}">{_esc(err_text[:40])}&hellip;</div>'

        cells.append(f"""
<div style="width:172px;border:2px solid {border_clr};border-radius:6px;overflow:hidden;flex-shrink:0;background:{bg_clr}">
  <div style="background:#f3f4f6;padding:3px 8px;font-size:10px;color:#6b7280;display:flex;justify-content:space-between">
    <span>{i+1}. {_esc(s.get('step_name',''))}</span>
    <span style="color:{'#D92D20' if not ok else '#027A48'}">{'' if ok else '&#x2717;'}</span>
  </div>
  {img_tag}
  <div style="padding:6px 8px">
    <div style="font-size:11px;font-weight:600;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{_esc(s.get('step_label',''))}</div>
    <div style="font-size:11px;color:{timing_clr};{'font-weight:600' if slow else ''}">{timing_str}</div>
    <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap">{cta_html}{overlay_html}{console_html}</div>
    {notes_html}
    {err_html}
  </div>
</div>""")
    return "".join(cells)


# ── Light-theme section template ───────────────────────────────────────────────

_SECTION_TEMPLATE = """\
<style>
/* journey section — scoped styles */
.j-lbx{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:9999;
        align-items:center;justify-content:center;cursor:zoom-out}}
.j-lbx.open{{display:flex}}
.j-lbx img{{max-width:90vw;max-height:90vh;border-radius:6px;box-shadow:0 20px 60px #000}}
</style>
<div class="j-lbx" id="j-lbx" onclick="jlbxClose()">
  <img id="j-lbx-img" src="" alt="">
</div>
<script>
function lbxJourneyOpen(img){{document.getElementById('j-lbx-img').src=img.src;document.getElementById('j-lbx').classList.add('open');}}
function jlbxClose(){{document.getElementById('j-lbx').classList.remove('open');}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')jlbxClose();}});
</script>

<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
  <div style="flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Avg Friction</div>
    <div style="font-size:32px;font-weight:700;color:{friction_color}">{avg_friction}/100</div>
    <div style="font-size:12px;color:#6b7280">{friction_label}</div>
  </div>
  <div style="flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Journeys</div>
    <div style="font-size:32px;font-weight:700;color:#111827">{total_journeys}</div>
    <div style="font-size:12px;color:#6b7280">{successful} passed &middot; {failed} failed</div>
  </div>
  <div style="flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Desktop Friction</div>
    <div style="font-size:32px;font-weight:700;color:{friction_color}">{desktop_friction}/100</div>
  </div>
  <div style="flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Mobile Friction</div>
    <div style="font-size:32px;font-weight:700;color:{friction_color}">{mobile_friction}/100</div>
  </div>
  <div style="flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Avg Click Depth</div>
    <div style="font-size:32px;font-weight:700;color:#111827">{avg_click_depth}</div>
    <div style="font-size:12px;color:#6b7280">taps to checkout</div>
  </div>
</div>

<h3 style="font-size:14px;font-weight:700;color:#111827;margin:20px 0 10px">Friction Signals</h3>
{signals_html}

<h3 style="font-size:14px;font-weight:700;color:#111827;margin:20px 0 10px">Journey Filmstrips</h3>
{journeys_html}"""
