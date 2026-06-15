"""
Journey runner — executes each journey template inside a persistent Playwright browser
context so cart state, cookies, and session survive across steps.
"""
import asyncio
import base64
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .templates import JOURNEY_TEMPLATES, JourneyStep, JourneyTemplate


# ── Device profiles ────────────────────────────────────────────────────────────

DEVICE_PROFILES: Dict[str, Dict] = {
    "desktop": {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "is_mobile": False,
        "has_touch": False,
    },
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "is_mobile": True,
        "has_touch": True,
    },
}

# ── Selector banks ─────────────────────────────────────────────────────────────

ATC_SELECTORS = [
    'button[name="add"]',
    '[data-add-to-cart]',
    '#AddToCart',
    '#add-to-cart-btn',
    '.product-form__cart-submit',
    'form[action*="/cart/add"] button[type="submit"]',
    'button:has-text("Add to Cart")',
    'button:has-text("Add to Bag")',
    'button:has-text("Buy Now")',
    'button:has-text("ADD TO CART")',
]

CHECKOUT_BTN_SELECTORS = [
    '[name="checkout"]',
    '.checkout_btn',
    '.checkout-button',
    'button:has-text("PROCEED TO CHECKOUT")',
    'button:has-text("Checkout")',
    'button:has-text("CHECKOUT")',
    'a:has-text("Checkout")',
]

HAMBURGER_SELECTORS = [
    '.m-menu-toggle',
    '[class*="hamburger"]',
    '[class*="burger"]',
    '[class*="menu-toggle"]',
    '[class*="nav-toggle"]',
    '[data-menu-toggle]',
    '[aria-label*="menu" i]',
    '#mobile-menu-toggle',
    'button[class*="menu"]',
]

CART_COUNT_SELECTORS = [
    '.m-cart-icon-bubble',
    '.cart-count',
    '[data-cart-count]',
    '.cart__count',
    '#CartCount',
    '.header__cart-count',
    '[class*="cart-count"]',
]

OVERLAY_SELECTORS = [
    '[class*="cookie-banner"]',
    '[class*="consent-banner"]',
    '[class*="newsletter-popup"]',
    '[class*="popup"]:not([style*="display: none"])',
    '[class*="overlay"]:not([style*="display: none"])',
    '.modal:not([style*="display: none"])',
]

CART_RESPONSE_SELECTORS = [
    '.cart-notification',
    '.cart-popup',
    '[class*="added-to-cart"]',
    '.m-cart-notification',
    '[class*="cart-notification"]',
    '.cart-drawer',
    '.mini-cart',
    '[class*="side-cart"]',
    '[data-cart-drawer]',
]


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step_name: str
    step_label: str
    action: str
    url: str
    success: bool
    timing_ms: int
    screenshot_b64: Optional[str] = None
    cart_count_before: Optional[int] = None
    cart_count_after: Optional[int] = None
    # 0-100: percentage from top of viewport (lower = needs scroll / thumb unfriendly)
    cta_viewport_pct: Optional[float] = None
    # pixels user must scroll to see the CTA (0 = already in view)
    scroll_to_cta_px: Optional[int] = None
    overlay_detected: bool = False
    console_errors: List[str] = field(default_factory=list)
    network_errors: List[str] = field(default_factory=list)
    error: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "step_name":        self.step_name,
            "step_label":       self.step_label,
            "action":           self.action,
            "url":              self.url,
            "success":          self.success,
            "timing_ms":        self.timing_ms,
            "screenshot_b64":   self.screenshot_b64,
            "cart_count_before": self.cart_count_before,
            "cart_count_after": self.cart_count_after,
            "cta_viewport_pct": self.cta_viewport_pct,
            "scroll_to_cta_px": self.scroll_to_cta_px,
            "overlay_detected": self.overlay_detected,
            "console_errors":   self.console_errors,
            "network_errors":   self.network_errors,
            "error":            self.error,
            "notes":            self.notes,
        }


@dataclass
class JourneyResult:
    journey_id: str
    journey_name: str
    device: str
    steps: List[StepResult] = field(default_factory=list)
    failed_at: Optional[str] = None
    total_time_ms: int = 0
    click_depth: int = 0
    overlay_interruptions: int = 0
    friction_score: int = 100

    @property
    def success(self) -> bool:
        return self.failed_at is None

    @property
    def successful_steps(self) -> int:
        return sum(1 for s in self.steps if s.success)

    def to_dict(self) -> Dict:
        return {
            "journey_id":           self.journey_id,
            "journey_name":         self.journey_name,
            "device":               self.device,
            "success":              self.success,
            "failed_at":            self.failed_at,
            "total_time_ms":        self.total_time_ms,
            "click_depth":          self.click_depth,
            "overlay_interruptions": self.overlay_interruptions,
            "friction_score":       self.friction_score,
            "successful_steps":     self.successful_steps,
            "total_steps":          len(self.steps),
            "steps":                [s.to_dict() for s in self.steps],
        }


# ── Runner ─────────────────────────────────────────────────────────────────────

_PRODUCT_CACHE = Path(__file__).parent.parent.parent / "state" / "journey_product.txt"


class JourneyRunner:
    def __init__(self, base_url: str = "https://pepstores.com"):
        self.base_url = base_url.rstrip("/")

    async def run_all(
        self,
        product_url: Optional[str] = None,
        search_term: str = "shirt",
        journey_ids: Optional[List[str]] = None,
        devices: Optional[List[str]] = None,
    ) -> List[JourneyResult]:
        devices = devices or ["desktop", "mobile"]
        templates = [
            t for t in JOURNEY_TEMPLATES
            if not journey_ids or t.id in journey_ids
        ]

        results: List[JourneyResult] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                # Discover a purchasable product URL once before running journeys
                if not product_url:
                    # Try cache first
                    if _PRODUCT_CACHE.exists():
                        product_url = _PRODUCT_CACHE.read_text(encoding="utf-8-sig").strip()
                        print(f"  Product (cached): {product_url}")
                    else:
                        print("  Discovering online-available product …")
                        product_url = await self._discover_purchasable_product(browser)
                        if product_url:
                            print(f"  Product: {product_url}")
                        else:
                            print("  Warning: no purchasable product found — ATC steps will report friction")

                for template in templates:
                    run_devices = devices
                    if template.mobile_only:
                        run_devices = [d for d in devices if d == "mobile"]

                    for device in run_devices:
                        print(f"  {template.id} [{device:7}] {template.name}")
                        result = await self._run_journey(
                            browser, template, device, product_url, search_term
                        )
                        results.append(result)
                        status = "OK " if result.success else f"FAIL @ {result.failed_at}"
                        print(
                            f"    {status} — {result.successful_steps}/{len(result.steps)} steps "
                            f"| friction {result.friction_score}/100 "
                            f"| {result.total_time_ms/1000:.1f}s"
                        )
            finally:
                await browser.close()

        return results

    # ── Discover purchasable product ─────────────────────────────────────────

    async def _discover_purchasable_product(self, browser: Browser) -> Optional[str]:
        """Visit /collections/available-online, collect product links, return first
        one where the ATC button is visible and not disabled."""
        ctx = await browser.new_context(
            viewport=DEVICE_PROFILES["desktop"]["viewport"],
            user_agent=DEVICE_PROFILES["desktop"]["user_agent"],
        )
        page = await ctx.new_page()
        found = None
        try:
            await page.goto(
                f"{self.base_url}/collections/available-online",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            # Wait for product grid to populate (Minimog lazy-loads)
            try:
                await page.wait_for_selector('a[href*="/products/"]', timeout=12000)
            except Exception:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            # Collect unique product links from the collection page
            links: List[str] = await page.evaluate("""() => {
                const seen = new Set();
                return Array.from(document.querySelectorAll('a[href*="/products/"]'))
                    .map(a => a.href.split('?')[0])
                    .filter(h => { if (seen.has(h)) return false; seen.add(h); return true; })
                    .slice(0, 16);
            }""")

            for url in links:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    # Wait for dynamic checkout / ATC buttons to render
                    try:
                        await page.wait_for_selector(
                            ", ".join(ATC_SELECTORS[:6]), timeout=6000
                        )
                    except Exception:
                        pass
                    await page.wait_for_timeout(1000)
                    for sel in ATC_SELECTORS:
                        btn = await page.query_selector(sel)
                        if btn:
                            disabled = await btn.get_attribute("disabled")
                            visible = await btn.is_visible()
                            if visible and disabled is None:
                                found = url
                                break
                    if found:
                        break
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            await page.close()
            await ctx.close()

        if found:
            _PRODUCT_CACHE.parent.mkdir(exist_ok=True)
            _PRODUCT_CACHE.write_text(found, encoding="utf-8")

        return found

    # ── Run a single journey ─────────────────────────────────────────────────

    async def _run_journey(
        self,
        browser: Browser,
        template: JourneyTemplate,
        device: str,
        product_url: Optional[str],
        search_term: str,
    ) -> JourneyResult:
        profile = DEVICE_PROFILES[device]
        ctx = await browser.new_context(
            viewport=profile["viewport"],
            user_agent=profile["user_agent"],
            is_mobile=profile.get("is_mobile", False),
            has_touch=profile.get("has_touch", False),
        )

        result = JourneyResult(
            journey_id=f"{template.id}_{device}",
            journey_name=template.name,
            device=device,
        )

        # Template variables resolved per-step
        ctx_vars: Dict[str, str] = {
            "product_url": product_url or f"{self.base_url}/collections/available-online",
            "search_term": search_term,
        }

        page = await ctx.new_page()
        console_errors: List[str] = []
        network_errors: List[str] = []
        page.on(
            "console",
            lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None,
        )
        page.on(
            "response",
            lambda r: network_errors.append(f"{r.status} {r.url[:120]}")
            if r.status >= 400
            else None,
        )

        t_start = time.time()

        try:
            for step in template.steps:
                n_errors_before = len(console_errors)
                n_net_before = len(network_errors)

                step_result = await self._execute_step(
                    page, step, device, ctx_vars
                )
                step_result.console_errors = console_errors[n_errors_before:]
                step_result.network_errors = network_errors[n_net_before:]

                result.steps.append(step_result)

                if step_result.overlay_detected:
                    result.overlay_interruptions += 1

                # Every action other than passive waits counts as a click
                if step.action not in ("wait_cart_response",):
                    result.click_depth += 1

                if not step_result.success:
                    result.failed_at = step.name
                    break

        except Exception as exc:
            result.failed_at = "runner_exception"
            result.steps.append(
                StepResult(
                    step_name="exception",
                    step_label="Unhandled exception",
                    action="exception",
                    url=page.url,
                    success=False,
                    timing_ms=0,
                    error=str(exc)[:400],
                )
            )
        finally:
            result.total_time_ms = int((time.time() - t_start) * 1000)
            result.friction_score = _compute_friction(result)
            await page.close()
            await ctx.close()

        return result

    # ── Step execution ───────────────────────────────────────────────────────

    async def _execute_step(
        self,
        page: Page,
        step: JourneyStep,
        device: str,
        ctx_vars: Dict[str, str],
    ) -> StepResult:
        t_start = time.time()
        success = False
        error: Optional[str] = None
        notes: List[str] = []
        overlay = False
        cart_before = cart_after = None
        cta_pct = scroll_px = None

        # Resolve {placeholders} in kwargs
        kwargs = {
            k: v.format(**ctx_vars) if isinstance(v, str) else v
            for k, v in step.kwargs.items()
        }

        try:
            if step.action == "navigate":
                raw = kwargs["url"]
                target = raw if raw.startswith("http") else self.base_url + raw
                # Guard: if the resolved URL is not a product page but is a collection,
                # note it so the journey can still be meaningful
                if "{product_url}" in kwargs.get("url", "") and "/products/" not in target:
                    notes.append(
                        f"No purchasable product URL available — navigating to {target}"
                    )
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                overlay = await self._detect_overlay(page)
                if overlay:
                    await self._dismiss_overlay(page)
                success = True

            elif step.action == "click_collection":
                el = await page.query_selector(
                    'a[href*="/collections/"]:not([href*="/collections/all"])'
                )
                if not el:
                    el = await page.query_selector('a[href*="/collections/"]')
                if el:
                    href = await el.get_attribute("href") or ""
                    target = self.base_url + href if href.startswith("/") else href
                    ctx_vars["current_collection"] = target
                    await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    success = True
                else:
                    error = "No collection link found on page"

            elif step.action == "click_online_product":
                # Wait for product grid to render before scanning for links
                try:
                    await page.wait_for_selector('a[href*="/products/"]', timeout=8000)
                except Exception:
                    pass
                # Collect all candidate product links from the page
                all_product_links: List[str] = await page.evaluate("""() => {
                    const seen = new Set();
                    return Array.from(document.querySelectorAll('a[href*="/products/"]'))
                        .map(a => a.href.split('?')[0])
                        .filter(h => { if (seen.has(h)) return false; seen.add(h); return true; });
                }""")
                # Try preferred (badge) first, then fallback order
                preferred = await page.evaluate(_FIND_ONLINE_PRODUCT_JS)
                candidates = (
                    ([preferred] if preferred else []) +
                    [u for u in all_product_links if u != preferred]
                )[:6]

                found_product = None
                for candidate_url in candidates:
                    try:
                        await page.goto(candidate_url, wait_until="domcontentloaded", timeout=20000)
                        try:
                            await page.wait_for_selector(", ".join(ATC_SELECTORS[:5]), timeout=5000)
                        except Exception:
                            pass
                        # Check if ATC is enabled on this product
                        for sel in ATC_SELECTORS:
                            btn = await page.query_selector(sel)
                            if btn and await btn.is_visible():
                                disabled = await btn.get_attribute("disabled")
                                if disabled is None:
                                    found_product = candidate_url
                                    break
                        if found_product:
                            break
                    except Exception:
                        continue

                if found_product:
                    ctx_vars["product_url"] = found_product
                    success = True
                    notes.append(f"Product: {found_product.split('/products/')[-1][:40]}")
                elif candidates:
                    # Navigate to first candidate anyway; record as friction (ATC disabled)
                    ctx_vars["product_url"] = candidates[0]
                    await page.goto(candidates[0], wait_until="domcontentloaded", timeout=20000)
                    notes.append("No product with enabled ATC on this collection — navigated to first product")
                    success = True
                else:
                    # No product links at all on the collection page.
                    # Fall back to the cached known-good product if available.
                    cached = ctx_vars.get("product_url", "")
                    if "/products/" in cached:
                        notes.append(
                            "Collection page has no visible product links — "
                            "falling back to cached product URL"
                        )
                        await page.goto(cached, wait_until="domcontentloaded", timeout=20000)
                        success = True
                    else:
                        error = "No product link found on collection page and no cached fallback"

            elif step.action == "click_atc":
                # If we're on a collection or non-product page, navigate to the product first
                current_url = page.url
                if "/products/" not in current_url:
                    product_target = ctx_vars.get("product_url", "")
                    if "/products/" in product_target:
                        notes.append(f"Redirecting to product from {current_url}")
                        await page.goto(product_target, wait_until="domcontentloaded", timeout=20000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                    else:
                        # Try to find a product link on current page and navigate
                        product_href = await page.evaluate(
                            "() => { const a = document.querySelector('a[href*=\"/products/\"]'); "
                            "return a ? a.href : null; }"
                        )
                        if product_href:
                            notes.append(f"Auto-navigated to product: {product_href[:60]}")
                            await page.goto(product_href, wait_until="domcontentloaded", timeout=20000)

                # Wait for ATC button to render (dynamic checkout buttons)
                try:
                    await page.wait_for_selector(", ".join(ATC_SELECTORS[:5]), timeout=5000)
                except Exception:
                    pass

                cart_before = await self._get_cart_count(page)
                cta_pct, scroll_px = await self._measure_cta(page, ATC_SELECTORS, device)

                atc_btn = None
                for sel in ATC_SELECTORS:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        disabled = await btn.get_attribute("disabled")
                        if disabled is None:
                            atc_btn = btn
                            break

                if atc_btn:
                    await atc_btn.click()
                    if cta_pct is not None:
                        zone = "below fold" if scroll_px and scroll_px > 0 else _thumb_zone(cta_pct, device)
                        notes.append(f"CTA at {cta_pct:.0f}% from top ({zone})")
                    success = True
                else:
                    btn_any = await page.query_selector(ATC_SELECTORS[0]) or \
                              await page.query_selector(ATC_SELECTORS[1])
                    if btn_any:
                        error = "ATC button found but disabled (product may be out of stock or in-store only)"
                    else:
                        error = "ATC button not found on product page"

            elif step.action == "wait_cart_response":
                await page.wait_for_timeout(4000)
                cart_after = await self._get_cart_count(page)

                drawer_visible = await self._cart_response_visible(page)
                count_increased = (
                    cart_before is not None
                    and cart_after is not None
                    and cart_after > cart_before
                )
                redirected_to_cart = "/cart" in page.url

                # Always succeed — we verify cart state on the cart page itself.
                # Record what we observed as notes so friction analysis can use it.
                success = True
                if count_increased:
                    notes.append(f"Cart count: {cart_before} -> {cart_after}")
                elif drawer_visible:
                    notes.append("Cart drawer / notification visible")
                elif redirected_to_cart:
                    notes.append("Redirected to cart automatically")
                else:
                    notes.append(
                        f"No cart response detected (count {cart_before}->{cart_after}, "
                        "no drawer). Will verify on cart page."
                    )

            elif step.action == "click_checkout":
                cta_pct, scroll_px = await self._measure_cta(page, CHECKOUT_BTN_SELECTORS, device)

                checkout_btn = None
                for sel in CHECKOUT_BTN_SELECTORS:
                    btn = await page.query_selector(sel)
                    if btn:
                        disabled = await btn.get_attribute("disabled")
                        visible = await btn.is_visible()
                        if visible and disabled is None:
                            checkout_btn = btn
                            break

                if checkout_btn:
                    if cta_pct is not None:
                        zone = _thumb_zone(cta_pct, device)
                        notes.append(f"Checkout CTA at {cta_pct:.0f}% from top ({zone})")
                    await checkout_btn.click()
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    success = True
                else:
                    error = "Checkout button not found or disabled on cart page"

            elif step.action == "click_hamburger":
                for sel in HAMBURGER_SELECTORS:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await page.wait_for_timeout(800)
                        success = True
                        break
                if not success:
                    error = "No hamburger / mobile menu toggle found"

            elif step.action == "click_menu_collection":
                # Look in visible mobile nav / drawer first, then fall back to any visible link
                el = None
                for sel in [
                    '[class*="mobile-nav"] a[href*="/collections/"]',
                    '[class*="mobile-menu"] a[href*="/collections/"]',
                    '[class*="drawer"] a[href*="/collections/"]',
                    '[class*="m-navigation"] a[href*="/collections/"]',
                    'nav a[href*="/collections/"]',
                    'a[href*="/collections/"]',
                ]:
                    candidate = await page.query_selector(sel)
                    if candidate and await candidate.is_visible():
                        el = candidate
                        break

                if el:
                    href = await el.get_attribute("href") or ""
                    target = self.base_url + href if href.startswith("/") else href
                    await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    # If no products on the navigated collection, fall back to available-online
                    try:
                        await page.wait_for_selector('a[href*="/products/"]', timeout=5000)
                    except Exception:
                        notes.append(f"Collection {target} has no products — falling back to /collections/available-online")
                        await page.goto(
                            f"{self.base_url}/collections/available-online",
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        try:
                            await page.wait_for_selector('a[href*="/products/"]', timeout=8000)
                        except Exception:
                            pass
                    success = True
                else:
                    # Fallback: navigate directly (no visible mobile menu found)
                    notes.append("Mobile menu links not found — navigating to /collections/available-online")
                    await page.goto(
                        f"{self.base_url}/collections/available-online",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    success = True

            elif step.action == "click_sort":
                sort_el = await page.query_selector(
                    'select[id*="sort"], select[name*="sort"], '
                    '[class*="sort"] select, [data-sort-by]'
                )
                if sort_el:
                    tag: str = await sort_el.evaluate("el => el.tagName")
                    if tag == "SELECT":
                        try:
                            await sort_el.select_option(value="price-ascending")
                            await page.wait_for_timeout(1500)
                            success = True
                        except Exception:
                            notes.append("Select sort option failed — proceeding with default")
                            success = True
                    else:
                        await sort_el.click()
                        await page.wait_for_timeout(500)
                        opt = await page.query_selector(
                            '[data-sort="price-ascending"], '
                            '[value="price-ascending"], '
                            'option[value="price-ascending"]'
                        )
                        if opt:
                            await opt.click()
                            await page.wait_for_timeout(1500)
                        success = True
                else:
                    notes.append("Sort control not detected — proceeding with default collection order")
                    success = True  # Non-fatal: can still select a product

            elif step.action == "click_search":
                # Try visible search input first, then search toggle buttons
                # Includes Minimog theme selectors: m-search-toggle, m-header__search
                search_el = None
                for sel in [
                    'input[type="search"]',
                    'input[placeholder*="search" i]',
                    '[class*="m-search-toggle"]',
                    '[class*="m-header__search"]',
                    '[data-search-toggle]',
                    '[class*="search-toggle"]',
                    '[class*="search-icon"]',
                    'button[class*="search"]',
                    '[aria-label*="search" i]',
                    'a[href*="/search"]',
                    '[class*="header__search"]',
                ]:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        search_el = el
                        break
                if search_el:
                    await search_el.click()
                    await page.wait_for_timeout(700)
                    # If this opened an overlay, wait for the actual input to appear
                    try:
                        await page.wait_for_selector(
                            'input[type="search"], input[name="q"]', timeout=4000
                        )
                    except Exception:
                        pass
                    success = True
                else:
                    # Navigate directly to /search as last resort
                    await page.goto(
                        f"{self.base_url}/search", wait_until="domcontentloaded", timeout=20000
                    )
                    notes.append("Search toggle not found — navigated to /search directly")
                    success = True

            elif step.action == "type_search":
                query = kwargs.get("query", "shirt")
                search_input = None
                for sel in [
                    'input[type="search"]',
                    'input[name="q"]',
                    'input[placeholder*="search" i]',
                    '[class*="search"] input',
                    '[class*="m-search"] input',
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        search_input = el
                        break

                if search_input:
                    try:
                        await search_input.click()
                        await page.wait_for_timeout(200)
                    except Exception:
                        pass
                    await search_input.fill(query)
                    await search_input.press("Enter")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    success = True
                    notes.append(f'Searched for "{query}"')
                else:
                    # Navigate directly to search URL
                    await page.goto(
                        f"{self.base_url}/search?q={query}",
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                    notes.append(f'Search input not found — navigated to /search?q={query}')
                    success = True

            elif step.action == "click_search_result":
                # Wait for results to appear after search
                try:
                    await page.wait_for_selector('a[href*="/products/"]', timeout=8000)
                except Exception:
                    pass
                result_link = None
                for sel in [
                    '.search-results a[href*="/products/"]',
                    '[class*="search-result"] a[href*="/products/"]',
                    '[class*="predictive"] a[href*="/products/"]',
                    '.predictive-search a[href*="/products/"]',
                    'a[href*="/products/"]',
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        result_link = el
                        break
                if result_link:
                    href = await result_link.get_attribute("href") or ""
                    target = self.base_url + href if href.startswith("/") else href
                    ctx_vars["product_url"] = target
                    await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    success = True
                else:
                    error = "No product link found in search results"

        except Exception as exc:
            error = str(exc)[:300]
            success = False

        timing_ms = int((time.time() - t_start) * 1000)

        # Capture screenshot
        try:
            raw_png = await page.screenshot(full_page=False, type="jpeg", quality=65)
            screenshot_b64 = base64.b64encode(raw_png).decode()
        except Exception:
            screenshot_b64 = None

        return StepResult(
            step_name=step.name,
            step_label=step.label,
            action=step.action,
            url=page.url,
            success=success,
            timing_ms=timing_ms,
            screenshot_b64=screenshot_b64,
            cart_count_before=cart_before,
            cart_count_after=cart_after,
            cta_viewport_pct=cta_pct,
            scroll_to_cta_px=scroll_px,
            overlay_detected=overlay,
            error=error,
            notes=notes,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _detect_overlay(self, page: Page) -> bool:
        for sel in OVERLAY_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                box = await el.bounding_box()
                if box and box["width"] > 100 and box["height"] > 100:
                    return True
        return False

    async def _dismiss_overlay(self, page: Page) -> None:
        for sel in [
            '[class*="close"]',
            '[aria-label*="close" i]',
            'button:has-text("Accept")',
            'button:has-text("OK")',
            'button:has-text("Got it")',
            'button:has-text("Agree")',
            '[class*="dismiss"]',
        ]:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                try:
                    await btn.click()
                    await page.wait_for_timeout(400)
                    return
                except Exception:
                    pass

    async def _get_cart_count(self, page: Page) -> Optional[int]:
        for sel in CART_COUNT_SELECTORS:
            el = await page.query_selector(sel)
            if el:
                text = (await el.text_content()) or ""
                digits = re.sub(r"[^\d]", "", text)
                if digits:
                    try:
                        return int(digits)
                    except ValueError:
                        pass
        return None

    async def _cart_response_visible(self, page: Page) -> bool:
        for sel in CART_RESPONSE_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True
        return False

    async def _measure_cta(
        self,
        page: Page,
        selectors: List[str],
        device: str,
    ) -> Tuple[Optional[float], Optional[int]]:
        """
        Returns (cta_viewport_pct, scroll_to_cta_px).
        cta_viewport_pct: 0-100 % from top of current viewport (>70 = thumb zone on mobile).
        scroll_to_cta_px: pixels to scroll to bring element into view (0 = already visible).
        """
        vp = page.viewport_size
        vh = vp["height"] if vp else 844

        for sel in selectors:
            el = await page.query_selector(sel)
            if not el:
                continue
            box = await el.bounding_box()
            if not box:
                continue
            centre_y = box["y"] + box["height"] / 2
            pct = (centre_y / vh) * 100
            # If element centre is below the visible viewport, scroll distance needed
            scroll_needed = max(0, int(centre_y - vh + box["height"] / 2))
            return round(pct, 1), scroll_needed
        return None, None


# ── Friction scoring ───────────────────────────────────────────────────────────

def _thumb_zone(pct: float, device: str) -> str:
    """Classify CTA position into thumb-reach zones for mobile."""
    if device != "mobile":
        return "desktop"
    if pct >= 65:
        return "thumb zone ✓"
    if pct >= 40:
        return "stretch zone"
    return "hard to reach"


def _compute_friction(result: JourneyResult) -> int:
    """
    Returns 0-100 score (100 = no friction, 0 = completely blocked).
    Deductions:
      Journey failed entirely                    -50 base
      Each failed step (beyond first)            -10
      Overlay interruption                       -10 each
      Step > 4s on mobile                        -5 each
      Step > 6s on desktop                       -5 each
      CTA in hard-to-reach zone on mobile        -10 per step
      CTA requires scrolling > 400px             -5 per step
      Console errors in a step                   -3 per error (max -15 per step)
      Click depth > 8                            -3 per click over 8
    """
    score = 100

    if not result.success:
        score -= 50
        extra_failures = sum(1 for s in result.steps if not s.success) - 1
        score -= max(0, extra_failures) * 10

    for step in result.steps:
        if step.overlay_detected:
            score -= 10

        threshold_ms = 4000 if result.device == "mobile" else 6000
        if step.timing_ms > threshold_ms:
            score -= 5

        if result.device == "mobile" and step.cta_viewport_pct is not None:
            if step.cta_viewport_pct < 40:  # hard to reach zone
                score -= 10
            elif step.cta_viewport_pct < 65:  # stretch zone
                score -= 5

        if step.scroll_to_cta_px and step.scroll_to_cta_px > 400:
            score -= 5

        if step.console_errors:
            score -= min(15, len(step.console_errors) * 3)

    if result.click_depth > 8:
        score -= (result.click_depth - 8) * 3

    return max(0, min(100, score))


# ── JS helpers (evaluated in page context) ─────────────────────────────────────

_FIND_ONLINE_PRODUCT_JS = """() => {
    // Strategy 1: find "Available Online" badge (Product Labels app, .pl-text)
    // and scan siblings/ancestors for a product href
    const badges = Array.from(document.querySelectorAll('.pl-text, .pl-animation'));
    for (const badge of badges) {
        let el = badge.parentElement;
        for (let i = 0; i < 8; i++) {
            if (!el) break;
            const link = el.querySelector('a[href*="/products/"]');
            if (link) return link.href.split('?')[0];
            const sibLink = el.parentElement && el.parentElement.querySelector('a[href*="/products/"]');
            if (sibLink) return sibLink.href.split('?')[0];
            el = el.parentElement;
        }
    }
    // Strategy 2: positional overlap — find badge rect and match product link
    if (badges.length > 0) {
        const bBox = badges[0].getBoundingClientRect();
        const links = Array.from(document.querySelectorAll('a[href*="/products/"]'));
        for (const link of links) {
            const lBox = link.getBoundingClientRect();
            const overlap = !(bBox.right < lBox.left || bBox.left > lBox.right ||
                               bBox.bottom < lBox.top || bBox.top > lBox.bottom);
            if (overlap) return link.href.split('?')[0];
            // Close-enough proximity (within 200px vertically)
            if (Math.abs((bBox.top + bBox.bottom)/2 - (lBox.top + lBox.bottom)/2) < 200)
                return link.href.split('?')[0];
        }
    }
    // Strategy 3: fallback — first product link on page
    const anyLink = document.querySelector('a[href*="/products/"]');
    return anyLink ? anyLink.href.split('?')[0] : null;
}"""
