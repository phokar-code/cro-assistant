"""
Shopify-specific conversion checks.
Uses DOM data + functional test results from the crawler.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"
    PASS     = "pass"


@dataclass
class Issue:
    id: str
    title: str
    description: str
    severity: Severity
    category: str
    recommendation: str = ""
    impact: str = ""


@dataclass
class CheckResult:
    category: str
    score: int
    issues: List[Issue] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)


def run_shopify_checks(page_data: Dict) -> CheckResult:
    dom      = page_data.get("dom", {})
    env      = page_data.get("shopify_env", {})
    func     = page_data.get("functional", {})
    page_type = page_data.get("page_type", "other")
    url      = page_data.get("url", "")

    issues: List[Issue] = []
    data: Dict = {}

    # ── Shopify store detection ──────────────────────────────────────────────
    data["is_shopify"] = env.get("hasShopify", False)
    data["theme_name"] = env.get("theme")
    data["currency"]   = env.get("currency")

    # ── App script bloat ─────────────────────────────────────────────────────
    script_count = env.get("scriptCount", 0)
    app_scripts  = env.get("appScripts", 0)
    data["script_count"] = script_count
    data["app_scripts"]  = app_scripts

    if script_count > 25:
        issues.append(Issue(
            id="SHOP_SCRIPT_BLOAT",
            title=f"Excessive scripts detected ({script_count} total, {app_scripts} app scripts)",
            description=(
                f"The page loads {script_count} external scripts. "
                "Each Shopify app installed adds scripts that accumulate and slow the store."
            ),
            severity=Severity.WARNING if script_count < 40 else Severity.CRITICAL,
            category="Performance / Apps",
            recommendation="Audit installed apps in Shopify admin. Remove unused apps. Each unused app slows load time.",
            impact="1 second delay = 7% conversion drop. Slow stores drive 40%+ bounce rate increase.",
        ))

    # ── Add to Cart functional test ──────────────────────────────────────────
    if page_type == "product":
        atc = func.get("atc", {})
        data["atc_test"] = atc

        if not atc.get("button_found"):
            if page_data.get("product_available") is False:
                # In-store only — no ATC button is expected, not a bug
                issues.append(Issue(
                    id="SHOP_PRODUCT_INSTORE_ONLY",
                    title="Product not available online — ATC button not expected",
                    description=(
                        "This product has no online-purchasable variants (confirmed via /products/[handle].json). "
                        "It is in-store only. The missing ATC button is intentional."
                    ),
                    severity=Severity.INFO,
                    category="Shopify Functional",
                    recommendation=(
                        "No fix needed for the ATC button. Consider adding an online-availability filter "
                        "to collection pages so customers can self-sort before clicking through."
                    ),
                    impact="Customers finding this product via search or collection hit a dead end. "
                           "Consider surfacing 'In-Store Only' prominently before they click through.",
                ))
            else:
                issues.append(Issue(
                    id="SHOP_NO_ATC_BUTTON",
                    title="Add to Cart button not found on product page",
                    description="No recognisable Add to Cart button was detected in the DOM.",
                    severity=Severity.CRITICAL,
                    category="Shopify Functional",
                    recommendation="Ensure form[action='/cart/add'] with a submit button exists. Check for JS rendering issues.",
                    impact="100% of product page visitors cannot add items to cart.",
                ))
        elif not atc.get("button_enabled"):
            issues.append(Issue(
                id="SHOP_ATC_DISABLED",
                title="Add to Cart button is disabled on page load",
                description=(
                    "The ATC button is present but disabled. "
                    + ("Likely requires variant selection first." if atc.get("variant_required") else "Unknown cause.")
                ),
                severity=Severity.WARNING,
                category="Shopify Functional",
                recommendation="Auto-select the first available variant on page load to enable the ATC button immediately.",
                impact="Users unfamiliar with Shopify may assume product is unavailable and leave.",
            ))
        elif not atc.get("cart_responded"):
            issues.append(Issue(
                id="SHOP_ATC_NO_RESPONSE",
                title="Add to Cart click did not update cart",
                description=(
                    "Clicked the ATC button but the cart count did not change and no drawer/notification appeared. "
                    + (f"Error: {atc['error']}" if atc.get("error") else "Possible JS conflict.")
                ),
                severity=Severity.CRITICAL,
                category="Shopify Functional",
                recommendation=(
                    "Open browser DevTools > Console while clicking ATC. Look for JS errors. "
                    "Test /cart/add.js endpoint directly. Check for app conflicts."
                ),
                impact="Visitors cannot purchase. This is the highest-priority fix possible.",
            ))

    # ── Dynamic checkout buttons ─────────────────────────────────────────────
    if page_type == "product":
        has_dyn   = dom.get("has_dynamic_checkout", False)
        dyn_empty = dom.get("dynamic_checkout_empty")
        data["dynamic_checkout"] = {"present": has_dyn, "empty": dyn_empty}

        if has_dyn and dyn_empty:
            issues.append(Issue(
                id="SHOP_DYN_CHECKOUT_EMPTY",
                title="Dynamic checkout container is empty (Buy Now / PayPal not rendering)",
                description=(
                    "A .shopify-payment-button container exists but has no children. "
                    "Payment provider buttons (Buy Now, PayPal, Apple Pay) are not rendering."
                ),
                severity=Severity.WARNING,
                category="Shopify Functional",
                recommendation=(
                    "Check Shopify admin > Settings > Payments. "
                    "Verify no CSP header is blocking pay.shopify.com. "
                    "Test in multiple browsers."
                ),
                impact="Removes the highest-converting one-click purchase path for returning customers.",
            ))

    # ── Variant selector state ───────────────────────────────────────────────
    if page_type == "product":
        atc_disabled = dom.get("atc_disabled", False)
        variants     = dom.get("variant_selectors", [])
        data["variant_info"] = {"selectors": len(variants), "atc_disabled_on_load": atc_disabled}

        if atc_disabled and variants:
            issues.append(Issue(
                id="SHOP_VARIANT_NO_PRESELECT",
                title="ATC button disabled — no variant pre-selected on page load",
                description=(
                    f"Found {len(variants)} variant selector(s). "
                    "The ATC button starts disabled because no variant is pre-selected."
                ),
                severity=Severity.WARNING,
                category="UX / Conversion",
                recommendation="Add JS to auto-select the first in-stock variant on DOMContentLoaded.",
                impact="Creates unnecessary friction. Users may abandon thinking the product is unavailable.",
            ))

    # ── Cart page checkout button ────────────────────────────────────────────
    if page_type == "cart":
        co_btn = func.get("checkout_btn", {})
        data["checkout_btn_test"] = co_btn

        if not co_btn.get("button_found"):
            if co_btn.get("cart_empty"):
                # Empty cart hides the checkout button on many themes — not a real fault
                issues.append(Issue(
                    id="SHOP_CHECKOUT_BTN_UNTESTED",
                    title="Checkout button untested — cart was empty during audit",
                    description=(
                        "The cart page was empty when audited. The checkout button may not render "
                        "until items are in the cart. Manual verification recommended."
                    ),
                    severity=Severity.INFO,
                    category="Shopify Functional",
                    recommendation="Add a product to cart before running the audit to properly test the checkout flow.",
                    impact="Checkout flow could not be verified automatically.",
                ))
            else:
                issues.append(Issue(
                    id="SHOP_NO_CHECKOUT_BTN",
                    title="Checkout button not found on cart page",
                    description="No checkout button was detected on the cart page.",
                    severity=Severity.CRITICAL,
                    category="Shopify Functional",
                    recommendation="Check cart.liquid / cart template. Ensure checkout button has name='checkout' or standard class.",
                    impact="Users with items in cart cannot proceed to purchase.",
                ))
        elif not co_btn.get("button_enabled"):
            issues.append(Issue(
                id="SHOP_CHECKOUT_BTN_DISABLED",
                title="Checkout button is disabled on cart page",
                description="Cart page checkout button exists but is disabled.",
                severity=Severity.CRITICAL,
                category="Shopify Functional",
                recommendation="Investigate JS disabling the checkout button. Check for cart validation errors.",
                impact="Users cannot proceed to checkout.",
            ))

    # ── Mobile cart icon ─────────────────────────────────────────────────────
    if page_type in ("product", "collection", "homepage"):
        mobile = func.get("mobile_cart", {})
        data["mobile_cart_test"] = mobile

        if mobile and not mobile.get("cart_icon_found"):
            issues.append(Issue(
                id="SHOP_NO_MOBILE_CART",
                title="Cart icon not found on mobile viewport",
                description="No cart icon detected on mobile. Users on mobile cannot access cart.",
                severity=Severity.CRITICAL,
                category="Mobile",
                recommendation="Ensure cart icon is visible in mobile header. Check responsive CSS.",
                impact="60%+ of ecommerce traffic is mobile. Missing cart icon blocks all mobile purchases.",
            ))
        elif mobile and mobile.get("cart_icon_found") and not mobile.get("cart_icon_tappable"):
            issues.append(Issue(
                id="SHOP_MOBILE_CART_SMALL",
                title="Cart icon touch target is too small on mobile",
                description="Cart icon found but bounding box is < 44×44px — below WCAG AA and Apple HIG minimum.",
                severity=Severity.WARNING,
                category="Mobile",
                recommendation="Ensure cart icon touch target is at least 44×44px (WCAG AA / Apple HIG). Add padding if needed.",
                impact="Small touch targets cause missed taps and cart abandonment on mobile.",
            ))

    # ── Score ────────────────────────────────────────────────────────────────
    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning  = sum(1 for i in issues if i.severity == Severity.WARNING)
    score    = max(0, 100 - critical * 30 - warning * 10)

    return CheckResult(category="Shopify", score=score, issues=issues, data=data)
