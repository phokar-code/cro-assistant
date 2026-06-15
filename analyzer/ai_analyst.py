"""
AI analysis layer — calls the local `claude` CLI using the user's logged-in session.
No separate API key required.
Loads skills.md as the CRO knowledge base and produces:
  - Executive summary
  - Prioritised recommendations
  - Ticket content
  - Roadmap
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


SKILLS_PATH = Path(__file__).parent.parent / "skills.md"

SYSTEM_PROMPT = """You are a senior Conversion Rate Optimisation (CRO) specialist with deep Shopify expertise.
You are analysing pepstores.com — a South African discount retailer on Shopify with custom theme code.
Your audience is a non-technical e-commerce manager. Be specific, business-focused, and actionable.
Always lead with revenue/conversion impact before the technical detail.
Use South African English spelling (e.g. "optimise", "analyse", "colour")."""

ANALYSIS_PROMPT_TEMPLATE = """
## CRO Knowledge Base
{skills}

---

## Audit Findings for {url}
Run date: {date}
Pages analysed: {page_count}

### Issue Summary
- Critical issues (blockers): {critical_count}
- Warnings (high impact): {warning_count}
- Info items: {info_count}

### Detailed Findings (JSON)
```json
{findings_json}
```

---

## Your Tasks

### 1. Executive Summary
Write 3–4 sentences summarising the overall conversion health of the site.
Lead with the most important finding. Quantify impact where possible.

### 2. Top Issues (business impact focus)
For each critical and warning issue, write a brief business-impact paragraph (2–3 sentences).
Format: **[Issue Title]** — impact paragraph.

### 3. Quick Wins
List 3–5 issues that can be fixed in under a day with high conversion impact.
Format: - **Fix**: description | **Impact**: what improves | **Effort**: hours estimate

### 4. Roadmap
Create a prioritised roadmap table with columns: Priority | Issue | Business Impact | Estimated Effort
P0 = fix today, P1 = this sprint, P2 = this month, P3 = backlog

### 5. Key Insight
One paragraph: the single most important pattern or root cause you see across these findings.
What does it tell us about how development changes are affecting conversions?

Keep the tone professional but clear. Avoid jargon a manager won't understand.
"""

TICKET_PROMPT_TEMPLATE = """
## CRO Knowledge Base
{skills}

---

## Issue to Document
```json
{issue_json}
```

Site: pepstores.com
Page: {url} ({page_type})

---

Write a development ticket in this exact markdown format:

# [TICKET TITLE — concise, action-oriented]

## Summary
One sentence describing the problem and its business impact.

## Observed Behaviour
What is currently happening on the site.

## Expected Behaviour
What should happen instead.

## Steps to Reproduce
1. Go to [URL]
2. [Action]
3. [Observe]

## Business Impact
- Conversion impact: [specific %, or qualitative]
- Affected users: [which users/devices/journeys]
- Revenue risk: [low/medium/high] — [brief reason]

## Acceptance Criteria
- [ ] [Testable criterion 1]
- [ ] [Testable criterion 2]

## Technical Notes
[Any Shopify-specific context, selectors, or investigation tips]

## Priority
[P0 / P1 / P2 / P3] — [one-line justification]
"""


def _load_skills() -> str:
    if SKILLS_PATH.exists():
        return SKILLS_PATH.read_text(encoding="utf-8")
    return ""


_CLAUDE_FALLBACK_PATHS = [
    r"C:\Users\prabo\.local\bin\claude.exe",
    r"C:\Users\prabo\AppData\Local\Programs\claude\claude.exe",
]

def _find_claude() -> Optional[str]:
    found = shutil.which("claude")
    if found:
        return found
    for p in _CLAUDE_FALLBACK_PATHS:
        if Path(p).exists():
            return p
    return None


def _call_claude(prompt: str, timeout: int = 180) -> Optional[str]:
    """Call claude CLI via stdin to avoid Windows 32K command-line limit."""
    import tempfile
    claude_bin = _find_claude()
    if not claude_bin:
        print("  [AI] 'claude' command not found. Is Claude Code installed?", file=sys.stderr)
        return None

    # Write prompt to temp file, then pass the short file path as the -p argument.
    # This avoids the Windows 32,767-char CreateProcess limit on command lines.
    tmp_path = None
    try:
        import tempfile as _tf
        with _tf.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            tmp_path = f.name

        # claude -p "$(type file)" won't work cross-platform; use --print with stdin instead
        result = subprocess.run(
            [claude_bin, "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if result.stdout.strip():
            return result.stdout.strip()
        err = result.stderr.strip()
        print(f"  [AI] claude CLI error: {err[:300]}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("  [AI] claude CLI timed out", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(f"  [AI] Could not execute: {claude_bin}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [AI] Unexpected error: {e}", file=sys.stderr)
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def run_ai_analysis(findings: Dict) -> Optional[str]:
    """Run full site analysis via Claude CLI."""
    skills = _load_skills()

    # Flatten issues for Claude — trim HTML/screenshot from the payload
    slim_findings = []
    for page in findings.get("pages", []):
        slim_page = {
            "url":       page.get("url"),
            "page_type": page.get("page_type"),
            "issues":    page.get("all_issues", []),
            "scores":    page.get("scores", {}),
            "functional_tests": page.get("functional", {}),
            "shopify_env": {
                k: v for k, v in page.get("shopify_env", {}).items()
                if k in ("hasShopify", "theme_name", "currency", "scriptCount", "appScripts")
            },
        }
        slim_findings.append(slim_page)

    critical = sum(i["severity"] == "critical" for p in slim_findings for i in p.get("issues", []))
    warning  = sum(i["severity"] == "warning"  for p in slim_findings for i in p.get("issues", []))
    info     = sum(i["severity"] == "info"      for p in slim_findings for i in p.get("issues", []))

    from datetime import datetime
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        skills=skills,
        url=findings.get("site_url", "pepstores.com"),
        date=datetime.now().strftime("%d %B %Y"),
        page_count=len(slim_findings),
        critical_count=critical,
        warning_count=warning,
        info_count=info,
        findings_json=json.dumps(slim_findings, indent=2),
    )

    full_prompt = SYSTEM_PROMPT + "\n\n" + prompt
    return _call_claude(full_prompt, timeout=240)


def generate_ticket(issue: Dict, url: str, page_type: str) -> Optional[str]:
    """Generate a single development ticket for one issue."""
    skills = _load_skills()
    prompt = SYSTEM_PROMPT + "\n\n" + TICKET_PROMPT_TEMPLATE.format(
        skills=skills,
        issue_json=json.dumps(issue, indent=2),
        url=url,
        page_type=page_type,
    )
    return _call_claude(prompt, timeout=120)
