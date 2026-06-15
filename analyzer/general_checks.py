"""
Developer-focused CRO checks: security, mobile rendering, schema, conversion signals, performance.
SEO content checks (title, meta description, H1, alt text) are intentionally excluded —
those belong to a content/SEO audit, not a developer bug-detection tool.
"""
import re
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from .shopify_checks import CheckResult, Issue, Severity


# ── Technical / security checks (developer responsibility) ───────────────────

def run_technical_checks(page_data: Dict) -> CheckResult:
    dom       = page_data.get("dom", {})
    page_type = page_data.get("page_type", "other")
    issues: List[Issue] = []
    data: Dict = {}

    # HTTPS — dev must configure and enforce
    data["is_https"] = dom.get("is_https", True)
    if not data["is_https"]:
        issues.append(Issue(
            id="TECH_NO_HTTPS",
            title="Site served over HTTP — SSL not enforced",
            description="All traffic should be forced to HTTPS. Shopify provides SSL by default but redirect may not be enabled.",
            severity=Severity.CRITICAL,
            category="Security",
            recommendation="Enable 'Redirect all HTTP traffic to HTTPS' in Shopify Admin > Online Store > Domains.",
            impact="Browsers flag HTTP as 'Not Secure'. 85% of shoppers abandon non-HTTPS stores.",
        ))

    # Viewport meta — without this, mobile layout breaks entirely
    data["has_viewport"] = dom.get("has_viewport", True)
    if not data["has_viewport"]:
        issues.append(Issue(
            id="TECH_NO_VIEWPORT",
            title="Viewport meta tag missing — mobile layout will break",
            description="No <meta name='viewport'> found. The page will not scale correctly on mobile devices.",
            severity=Severity.CRITICAL,
            category="Mobile Rendering",
            recommendation="Add <meta name='viewport' content='width=device-width, initial-scale=1'> to the theme <head>.",
            impact="Without viewport meta, mobile users see a zoomed-out desktop layout. Unusable on phones.",
        ))

    # Schema markup — dev-implemented structured data
    data["schema_types"] = dom.get("schema_types", [])
    if page_type == "product" and "Product" not in data["schema_types"]:
        issues.append(Issue(
            id="TECH_NO_PRODUCT_SCHEMA",
            title="Product page missing Product schema (JSON-LD)",
            description=(
                f"No Product structured data found. Schema types present: {data['schema_types'] or 'none'}."
            ),
            severity=Severity.WARNING,
            category="Structured Data",
            recommendation=(
                "Add Product JSON-LD with 'offers' (price, availability) and 'aggregateRating'. "
                "Shopify themes should include this via theme.liquid or product.liquid."
            ),
            impact="Misses rich results in Google (star ratings, price, in-stock) — 20–30% CTR uplift when present.",
        ))

    if not data["schema_types"] and page_type not in ("cart", "checkout", "search"):
        issues.append(Issue(
            id="TECH_NO_SCHEMA",
            title="No JSON-LD structured data on page",
            description="No application/ld+json script tags found.",
            severity=Severity.INFO,
            category="Structured Data",
            recommendation="Implement schema appropriate to page type (Organization, WebSite, BreadcrumbList, Product).",
        ))

    # Cookie / consent banner potentially blocking JS or CTAs
    data["has_cookie_banner"] = dom.get("has_cookie_banner", False)
    if data["has_cookie_banner"]:
        issues.append(Issue(
            id="TECH_COOKIE_BANNER",
            title="Cookie consent banner detected — verify it doesn't block CTAs",
            description="A cookie/GDPR consent overlay is present on the page.",
            severity=Severity.INFO,
            category="UX / JS",
            recommendation=(
                "Verify the banner can be dismissed on mobile and does not overlap Add to Cart or Checkout buttons. "
                "Test z-index stacking on small viewports."
            ),
        ))

    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning  = sum(1 for i in issues if i.severity == Severity.WARNING)
    score    = max(0, 100 - critical * 25 - warning * 10)
    return CheckResult(category="Technical", score=score, issues=issues, data=data)


# ── Trust & UX signals (affects developer-controlled UI) ─────────────────────

TRUST_SIGNALS = {
    "payment_badges": [r"visa", r"mastercard", r"paypal", r"amex", r"apple pay", r"google pay", r"eft", r"instant eft"],
    "return_policy":  [r"return policy", r"refund", r"money.?back", r"free return", r"exchange"],
    "reviews":        [r"review", r"rating", r"star", r"verified.?purchas", r"customer.?feedback"],
    "shipping_info":  [r"free shipping", r"fast delivery", r"delivery", r"ships in", r"collect in.?store"],
    "privacy_policy": [r"privacy policy", r"privacy notice", r"popia"],
    "trust_badges":   [r"norton", r"mcafee", r"trustpilot", r"secure.?checkout"],
}


def run_trust_checks(page_data: Dict) -> CheckResult:
    html      = page_data.get("html", "")
    dom       = page_data.get("dom", {})
    page_type = page_data.get("page_type", "other")
    issues: List[Issue] = []
    data: Dict = {}

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ", strip=True).lower()

    found = {
        key: any(re.search(p, text, re.IGNORECASE) for p in patterns)
        for key, patterns in TRUST_SIGNALS.items()
    }
    data["trust_signals"] = found

    # Also check DOM for payment icon images/SVGs (text search misses image-only icons)
    if not found["payment_badges"]:
        dom_payment = (
            bool(soup.find_all("img", alt=re.compile(r"visa|mastercard|paypal|amex|eft|payflex|payjustnow", re.I)))
            or bool(soup.find_all(class_=re.compile(r"payment.?icon|shopify.?payment", re.I)))
            or bool(soup.find("ul", class_=re.compile(r"payment", re.I)))
            or "payment-icons" in html.lower()
            or "shopify-payment-icon" in html.lower()
            or bool(soup.find_all(attrs={"data-payment-methods": True}))
        )
        found["payment_badges"] = dom_payment

    # Payment badges — dev renders these in theme footer / cart template
    if not found["payment_badges"]:
        issues.append(Issue(
            id="TRUST_NO_PAYMENT_ICONS",
            title="No payment method icons rendered on page",
            description=(
                "No Visa / Mastercard / PayPal / EFT icons detected in the DOM. "
                "These should be rendered by the theme footer or cart template."
            ),
            severity=Severity.WARNING,
            category="Trust UI",
            recommendation=(
                "Add payment icons to footer.liquid and cart template. "
                "Shopify provides payment icons via {{ shop.enabled_payment_types }}."
            ),
            impact="Missing payment icons increase checkout abandonment — shoppers need to see payment options before committing.",
        ))

    # Return policy — should appear on product/cart pages (dev controls placement)
    if not found["return_policy"] and page_type in ("product", "cart", "checkout"):
        issues.append(Issue(
            id="TRUST_NO_RETURN_POLICY",
            title="No return/refund policy text visible on this page",
            description="No return policy content detected. This should appear near the Add to Cart button or in cart.",
            severity=Severity.WARNING,
            category="Trust UI",
            recommendation=(
                "Add a short returns snippet (1–2 lines) to product.liquid above or below the ATC button. "
                "Link to the full /policies/refund-policy page."
            ),
            impact="Purchase anxiety is the #2 reason for cart abandonment.",
        ))

    # Shipping info on product/cart — dev controls template content
    if not found["shipping_info"] and page_type in ("product", "cart"):
        issues.append(Issue(
            id="TRUST_NO_SHIPPING_INFO",
            title="No shipping/delivery information visible",
            description="No delivery estimate, free shipping mention, or collect-in-store option detected.",
            severity=Severity.INFO,
            category="Trust UI",
            recommendation="Add delivery estimate block to product.liquid. Can be driven by a metafield for flexibility.",
        ))

    # Privacy policy link — POPIA compliance check, reported once (homepage only).
    # The fix lives in footer.liquid — no value in flagging every page separately.
    if not found["privacy_policy"] and page_type == "homepage":
        # Also check DOM for href-based privacy links (text check misses "Privacy" without "policy")
        dom_privacy = bool(
            soup.find("a", href=re.compile(r"privacy|popia", re.I))
            or soup.find("a", string=re.compile(r"privacy|popia", re.I))
        )
        if not dom_privacy:
            issues.append(Issue(
                id="TRUST_NO_PRIVACY_LINK",
                title="No privacy policy link in site footer",
                description=(
                    "No privacy policy or POPIA notice link detected anywhere on the homepage. "
                    "This is reported once — the fix is a single change to footer.liquid."
                ),
                severity=Severity.WARNING,
                category="Legal Compliance",
                recommendation=(
                    "Add a privacy policy link to footer.liquid. "
                    "Shopify auto-generates /policies/privacy-policy — link to it from the footer nav."
                ),
                impact="POPIA (South African law) requires visible privacy notice. Legal exposure if absent.",
            ))

    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning  = sum(1 for i in issues if i.severity == Severity.WARNING)
    bonus    = sum(1 for v in found.values() if v) * 2
    score    = max(0, min(100, 100 - critical * 25 - warning * 10 + bonus))
    return CheckResult(category="Trust", score=score, issues=issues, data=data)


# ── Conversion element checks (dev-controlled UI) ─────────────────────────────

def run_conversion_checks(page_data: Dict) -> CheckResult:
    dom       = page_data.get("dom", {})
    page_type = page_data.get("page_type", "other")
    issues: List[Issue] = []
    data: Dict = {}

    # Price — rendered by Liquid, should always be present on product pages
    price_els = dom.get("price_elements", [])
    data["prices_found"] = price_els
    if page_type == "product" and not price_els:
        issues.append(Issue(
            id="CONV_NO_PRICE",
            title="Price element not rendered on product page",
            description=(
                "No .price or .money element found in the DOM. "
                "The Liquid price variable may not be rendering, or the element has an unexpected class."
            ),
            severity=Severity.CRITICAL,
            category="Product Template",
            recommendation=(
                "Verify {{ product.price | money }} is outputting in product.liquid. "
                "Check for CSS that may be hiding the price element (display:none, visibility:hidden)."
            ),
            impact="Price is the primary purchase decision factor. Invisible price = zero conversions.",
        ))

    # Search bar — dev implements this in the theme header
    data["has_search"] = dom.get("has_search", False)
    if page_type in ("homepage", "collection") and not data["has_search"]:
        issues.append(Issue(
            id="CONV_NO_SEARCH",
            title="Search input not rendered in header",
            description="No search input (type='search' or placeholder containing 'search') found.",
            severity=Severity.WARNING,
            category="Navigation",
            recommendation=(
                "Ensure search form is included in header.liquid or a section. "
                "Shopify's Predictive Search API should be wired to the input."
            ),
            impact="43% of ecommerce visitors use site search. Search users convert 2–3× more.",
        ))

    # Checkout form fields — only on checkout-type pages
    if page_type == "checkout":
        forms    = dom.get("forms", [])
        n_fields = sum(f.get("fields", 0) for f in forms)
        data["checkout_field_count"] = n_fields
        if n_fields > 12:
            issues.append(Issue(
                id="CONV_CHECKOUT_FRICTION",
                title=f"Checkout renders ~{n_fields} visible form fields",
                description=(
                    f"Counted approximately {n_fields} non-hidden form fields on checkout. "
                    "Shopify's native checkout is limited, but custom checkout modifications may be adding unnecessary fields."
                ),
                severity=Severity.WARNING,
                category="Checkout UX",
                recommendation="Audit checkout.liquid (Shopify Plus) or checkout scripts for added fields. Remove any non-essential inputs.",
            ))

    # Reviews widget — single authoritative check (DOM-based, replaces text-based trust check)
    data["has_reviews"] = dom.get("has_reviews", False)
    if page_type == "product" and not data["has_reviews"]:
        issues.append(Issue(
            id="CONV_NO_REVIEWS_DOM",
            title="No reviews widget found on product page",
            description=(
                "No review/rating elements detected (.yotpo, .okendo, .stamped, .reviews, [class*='rating']). "
                "Either no reviews app is installed, or the embed snippet is missing from the product template."
            ),
            severity=Severity.WARNING,
            category="Trust / Product Template",
            recommendation=(
                "Ensure the reviews app embed snippet is in product.liquid. "
                "For Shopify 2.0 themes, verify the app block is enabled in the theme editor."
            ),
            impact="Products with reviews convert 3.5× better. Missing widget = invisible social proof.",
        ))

    # BNPL visibility — Payflex / PayJustNow are the dominant SA instalment options
    html = page_data.get("html", "")
    if page_type in ("product", "cart"):
        soup_conv = BeautifulSoup(html, "lxml")
        text_conv = soup_conv.get_text(separator=" ", strip=True).lower()
        bnpl_text = any(re.search(p, text_conv, re.IGNORECASE) for p in [
            r"payflex", r"payjustnow", r"pay just now",
            r"buy now.{0,5}pay later", r"pay in 4", r"4 x payments?",
        ])
        bnpl_dom = bool(
            soup_conv.find_all("img", alt=re.compile(r"payflex|payjustnow", re.I))
            or soup_conv.find_all(class_=re.compile(r"payflex|payjustnow|bnpl", re.I))
            or "payflex" in html.lower()
            or "payjustnow" in html.lower()
        )
        data["has_bnpl"] = bnpl_text or bnpl_dom
        if not data["has_bnpl"]:
            issues.append(Issue(
                id="CONV_NO_BNPL",
                title="No BNPL option visible (Payflex / PayJustNow)",
                description=(
                    "No buy-now-pay-later widget detected. "
                    "Payflex and PayJustNow are the dominant SA BNPL providers and show instalment "
                    "prices directly on product and cart pages when configured."
                ),
                severity=Severity.WARNING,
                category="Checkout / Payment",
                recommendation=(
                    "Install the Payflex or PayJustNow Shopify app and enable their product-page widget. "
                    "Both integrate with Shopify and display '4 × R X' instalment callouts near the ATC button."
                ),
                impact="BNPL options increase conversion 20–30% for orders over R500. SA shoppers expect these options.",
            ))

    # Product image count — single image listings convert significantly worse
    if page_type == "product":
        img_count = dom.get("product_image_count", 0)
        data["product_image_count"] = img_count
        if 0 < img_count < 3:
            issues.append(Issue(
                id="CONV_FEW_PRODUCT_IMAGES",
                title=f"Product has only {img_count} image(s) — 3+ recommended",
                description=(
                    f"Only {img_count} product image(s) detected in the gallery. "
                    "Shoppers expect multiple angles, lifestyle shots, and a size reference."
                ),
                severity=Severity.WARNING,
                category="Product Template",
                recommendation=(
                    "Upload 3–6 images per product: front, back, detail, lifestyle, size comparison. "
                    "Enable Shopify image zoom in theme settings."
                ),
                impact="Products with 3+ images convert 50% better than single-image listings.",
            ))

    # Sticky ATC bar — check via DOM whether a sticky/fixed ATC element is configured
    if page_type == "product":
        sticky_present = dom.get("sticky_atc_present", False)
        data["sticky_atc_present"] = sticky_present
        if not sticky_present and dom.get("has_atc_button"):
            issues.append(Issue(
                id="CONV_NO_STICKY_ATC",
                title="No sticky Add to Cart bar on product page",
                description=(
                    "No sticky or fixed-position ATC element detected. "
                    "Customers who scroll past the fold on mobile lose access to the buy action."
                ),
                severity=Severity.WARNING,
                category="Mobile / UX",
                recommendation=(
                    "Enable the Minimog theme's sticky 'Buy Bar' / 'Sticky Add to Cart' in theme settings. "
                    "This pins a compact ATC strip to the bottom of the mobile viewport when the user scrolls."
                ),
                impact="30%+ of mobile product-page scrollers abandon without finding the CTA again.",
            ))

    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning  = sum(1 for i in issues if i.severity == Severity.WARNING)
    score    = max(0, 100 - critical * 20 - warning * 10)
    return CheckResult(category="Conversion", score=score, issues=issues, data=data)


# ── Performance checks (PageSpeed Insights — free, no key required) ───────────

async def run_performance_checks(url: str, api_key: str = "") -> CheckResult:
    issues: List[Issue] = []
    data:   Dict        = {}

    try:
        params: Dict = {"url": url, "strategy": "mobile", "category": "performance"}
        if api_key:
            params["key"] = api_key

        async with httpx.AsyncClient(timeout=35) as client:
            r = await client.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
            )
        if r.status_code != 200:
            raise RuntimeError(f"PageSpeed API returned {r.status_code}")

        psi    = r.json()
        lhr    = psi.get("lighthouseResult", {})
        cats   = lhr.get("categories", {})
        audits = lhr.get("audits", {})

        perf_score = int((cats.get("performance", {}).get("score") or 0.5) * 100)
        data["performance_score"] = perf_score

        cwv_map = {
            "largest-contentful-paint":  ("LCP",  2500, 4000, "ms"),
            "cumulative-layout-shift":   ("CLS",  0.1,  0.25, ""),
            "interaction-to-next-paint": ("INP",  200,  500,  "ms"),
            "first-contentful-paint":    ("FCP",  1800, 3000, "ms"),
            "server-response-time":      ("TTFB", 800,  1800, "ms"),
        }

        for audit_key, (label, good, poor, unit) in cwv_map.items():
            audit = audits.get(audit_key, {})
            val   = audit.get("numericValue")
            if val is None:
                continue
            data[label] = round(val, 3)
            display = f"{val:.0f}{unit}" if unit else f"{val:.3f}"

            if val > poor:
                issues.append(Issue(
                    id=f"PERF_{label}_POOR",
                    title=f"Poor {label}: {display} (threshold: {poor}{unit})",
                    description=(
                        f"{label} measured at {display} on mobile. "
                        f"Google classifies this as 'Poor' (above {poor}{unit})."
                    ),
                    severity=Severity.CRITICAL,
                    category="Core Web Vitals",
                    recommendation=_cwv_tip(label),
                    impact=f"Poor {label} directly reduces mobile conversion rate and hurts Google ranking.",
                ))
            elif val > good:
                issues.append(Issue(
                    id=f"PERF_{label}_WARN",
                    title=f"{label} needs improvement: {display}",
                    description=f"{label} is {display} — in 'needs improvement' range ({good}–{poor}{unit}).",
                    severity=Severity.WARNING,
                    category="Core Web Vitals",
                    recommendation=_cwv_tip(label),
                ))

        # Developer-actionable opportunities
        for audit_key, title, tip in [
            ("render-blocking-resources", "Render-blocking scripts in <head>",
             "Move non-critical scripts to async/defer. Audit app scripts added to theme.liquid."),
            ("unused-javascript", "Large unused JavaScript bundles",
             "Identify and remove unused app scripts. Use Chrome DevTools Coverage tab to find dead code."),
            ("uses-optimized-images", "Unoptimised images being served",
             "Use Shopify's CDN image transforms: append ?width=800&format=webp to image URLs in Liquid."),
        ]:
            a = audits.get(audit_key, {})
            score_val = a.get("score")
            if score_val is not None and score_val < 0.9:
                savings = a.get("details", {}).get("overallSavingsMs", 0)
                if savings and savings > 300:
                    issues.append(Issue(
                        id=f"PERF_{audit_key.upper().replace('-','_')}",
                        title=f"{title} (~{savings:.0f}ms saving potential)",
                        description=a.get("description", "")[:150],
                        severity=Severity.WARNING,
                        category="Performance",
                        recommendation=tip,
                    ))

    except Exception as e:
        data["error"] = str(e)
        issues.append(Issue(
            id="PERF_UNAVAILABLE",
            title="PageSpeed data unavailable",
            description=str(e)[:150],
            severity=Severity.INFO,
            category="Performance",
            recommendation="Run manually at https://pagespeed.web.dev",
        ))

    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning  = sum(1 for i in issues if i.severity == Severity.WARNING)
    score    = data.get("performance_score", max(0, 100 - critical * 20 - warning * 10))
    return CheckResult(category="Performance", score=score, issues=issues, data=data)


def _cwv_tip(label: str) -> str:
    tips = {
        "LCP":  "Preload the hero/product image. Defer non-critical scripts. Check TTFB first — slow server = slow LCP.",
        "CLS":  "Set explicit width and height on all <img> tags. Avoid injecting content above existing DOM nodes.",
        "INP":  "Break up long JavaScript tasks (>50ms). Defer third-party scripts. Audit app JS for blocking code.",
        "FCP":  "Inline critical CSS. Remove render-blocking <script> tags from <head>. Reduce server response time.",
        "TTFB": "Enable Shopify CDN. Reduce liquid render complexity. Check for slow app API calls during page render.",
    }
    return tips.get(label, "Review Google PageSpeed Insights for specific recommendations.")
