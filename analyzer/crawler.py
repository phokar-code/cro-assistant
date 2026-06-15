"""
Playwright-based crawler.
Takes screenshots, extracts DOM data, and runs functional tests
(add-to-cart click, checkout reachability, cart drawer, mobile cart).
"""
import asyncio
import base64
import re
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PWTimeout


# Common Shopify selectors — works across themes including custom-coded stores
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
]

CHECKOUT_BTN_SELECTORS = [
    '[name="checkout"]',
    '.checkout_btn',
    '.checkout-button',
    '#checkout',
    'button[data-checkout]',
    'a:has-text("Checkout")',
    'button:has-text("Checkout")',
    'button:has-text("CHECKOUT")',
    'button:has-text("PROCEED TO CHECKOUT")',
    'input[value="Checkout"]',
]

CART_COUNT_SELECTORS = [
    '.cart-count',
    '[data-cart-count]',
    '.cart__count',
    '#CartCount',
    '.header__cart-count',
    '[aria-label*="cart"] .count',
    '.cart-icon__bubble',
    # Minimog theme
    '.m-cart-icon-bubble',
    '[class*="cart-count"]',
    '[class*="cart-quantity"]',
]

CART_DRAWER_SELECTORS = [
    '.cart-drawer',
    '.cart-notification',
    '.side-cart',
    '[data-cart-drawer]',
    '.cart-popup',
    '.mini-cart',
    '.cart-notification-wrapper',
]

VARIANT_SELECTORS = [
    'select[name="id"]',
    '.single-option-selector',
    '[data-option-index]',
    '.product-form__option select',
    'input[name="id"]',
]


class PageCrawler:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def crawl_pages(self, pages: List[Dict]) -> List[Dict]:
        results = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)

            # Desktop context
            desktop_ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            # Mobile context (for mobile-specific tests)
            mobile_ctx = await browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                is_mobile=True,
                has_touch=True,
            )

            for i, page_info in enumerate(pages):
                if i > 0:
                    await asyncio.sleep(2)  # polite delay between requests
                print(f"    Crawling [{page_info['page_type']:12}] {page_info['url'][:70]}")
                crawled = await self._crawl_page(desktop_ctx, mobile_ctx, page_info)
                if crawled:
                    results.append(crawled)

            await desktop_ctx.close()
            await mobile_ctx.close()
            await browser.close()

        return results

    async def _crawl_page(
        self,
        desktop_ctx: BrowserContext,
        mobile_ctx: BrowserContext,
        page_info: Dict,
    ) -> Optional[Dict]:
        url = page_info["url"]
        page_type = page_info["page_type"]

        # --- Desktop crawl ---
        page = await desktop_ctx.new_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else 0
            if status >= 400:
                print(f"      [!] HTTP {status} for {url} — skipping")
                await page.close()
                return None

            await page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass  # Continue with whatever loaded

        try:
            screenshot_b64 = base64.b64encode(
                await page.screenshot(full_page=False, type="jpeg", quality=72)
            ).decode()

            html = await page.content()
            dom_data = await self._extract_dom_data(page)

            # Shopify environment
            shopify_env = await page.evaluate("""() => ({
                hasShopify: typeof window.Shopify !== 'undefined',
                theme: window.Shopify?.theme?.name || null,
                currency: window.Shopify?.currency?.active || null,
                hasPaymentButton: typeof window.Shopify?.PaymentButton !== 'undefined',
                scriptCount: document.querySelectorAll('script[src]').length,
                appScripts: Array.from(document.querySelectorAll('script[src]'))
                    .map(s => s.src)
                    .filter(s => s.includes('cdn.shopify') || s.includes('apps.shopifycdn') || s.includes('shopifyapps'))
                    .length,
            })""")

            # For product pages: check online availability via Shopify JSON endpoint
            # before running any functional tests (avoids false positives on in-store-only products)
            product_available = None
            if page_type == "product":
                handle = url.rstrip("/").split("/products/")[-1].split("?")[0].split("#")[0]
                product_available = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('/products/{handle}.json');
                            if (!r.ok) return null;
                            const d = await r.json();
                            return d.product.variants.some(v => v.available);
                        }} catch(e) {{ return null; }}
                    }}
                """)

            # Wait for async-rendered elements before capturing DOM
            # Dynamic checkout buttons (PayPal, Apple Pay) load after networkidle
            if page_type == "product":
                try:
                    await page.wait_for_function(
                        "() => { const el = document.querySelector('.shopify-payment-button, [data-shopify=\"payment-button\"]'); return !el || el.children.length > 0; }",
                        timeout=3000,
                    )
                except Exception:
                    pass

            # Functional tests (only on relevant page types)
            functional = {}
            if page_type == "product":
                functional["atc"] = await self._test_add_to_cart(page, url)
            if page_type == "cart":
                functional["checkout_btn"] = await self._test_checkout_button(page)
            if page_type in ("product", "collection", "homepage"):
                functional["mobile_cart"] = await self._test_mobile_cart(mobile_ctx, url)

            await page.close()

            return {
                "url": url,
                "page_type": page_type,
                "status_code": status,
                "html": html,
                "screenshot": screenshot_b64,
                "dom": dom_data,
                "shopify_env": shopify_env,
                "functional": functional,
                "product_available": product_available,
            }

        except Exception as e:
            print(f"      [!] Error crawling {url}: {e}")
            try:
                await page.close()
            except Exception:
                pass
            return None

    async def _extract_dom_data(self, page: Page) -> Dict:
        return await page.evaluate("""() => {
            const getText = sel => document.querySelector(sel)?.textContent?.trim() || '';
            const getAttr = (sel, attr) => document.querySelector(sel)?.getAttribute(attr) || '';
            const count = sel => document.querySelectorAll(sel).length;
            const exists = sel => !!document.querySelector(sel);

            return {
                title: document.title,
                h1s: Array.from(document.querySelectorAll('h1')).map(h => h.textContent.trim()).slice(0, 3),
                meta_description: getAttr('meta[name="description"]', 'content'),
                canonical: getAttr('link[rel="canonical"]', 'href'),
                has_viewport: exists('meta[name="viewport"]'),
                is_https: location.protocol === 'https:',
                images_total: count('img'),
                images_no_alt: count('img:not([alt])'),
                has_schema: exists('script[type="application/ld+json"]'),
                schema_types: Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                    .map(s => { try { return JSON.parse(s.textContent)['@type']; } catch(e) { return null; } })
                    .filter(Boolean),
                has_breadcrumb: exists('[aria-label*="breadcrumb" i], .breadcrumb, #breadcrumb, nav[class*="breadcrumb" i]'),
                has_search: exists('input[type="search"], input[placeholder*="search" i]'),
                has_reviews: exists('.reviews, .product-reviews, [class*="review"], [class*="rating"], .yotpo, .okendo, .stamped'),
                form_count: count('form'),
                forms: Array.from(document.querySelectorAll('form')).map(f => ({
                    action: f.action,
                    fields: f.querySelectorAll('input:not([type="hidden"]), select, textarea').length,
                })),
                has_announcement_bar: exists('.announcement-bar, .announcement, [class*="announcement"]'),
                has_cookie_banner: exists('[class*="cookie"], [id*="cookie"], [class*="consent"], [id*="gdpr"]'),
                links_internal: Array.from(document.querySelectorAll('a[href^="/"], a[href^="' + location.origin + '"]')).length,
                price_elements: Array.from(document.querySelectorAll(
                    '.price, [class*="price"], .money, .m-price, .m-price__regular, .m-price--main, [data-price], .product__price'
                )).map(el => el.textContent.trim()).filter(t => t && /[0-9]/.test(t)).slice(0, 3),
                product_image_count: (() => {
                    const gallery = document.querySelector(
                        '.product-media-list, .product__media-gallery, .product-gallery, ' +
                        '[class*="product-images"], [class*="product__gallery"], .m-product-media'
                    );
                    if (gallery) return gallery.querySelectorAll('img, video, [class*="media"]').length;
                    return document.querySelectorAll(
                        '.product-media-container, .media--product, [class*="product-media"]'
                    ).length;
                })(),
                sticky_atc_present: (() => {
                    const knownSelectors = [
                        '.m-product-sticky-atc', '[class*="sticky-atc"]', '[class*="sticky_atc"]',
                        '.sticky-add-to-cart', '.product-sticky-bar', '[data-sticky-atc]',
                        '.m-sticky-atc', '[class*="m-sticky"]'
                    ];
                    for (const sel of knownSelectors) {
                        if (document.querySelector(sel)) return true;
                    }
                    const atcBtn = document.querySelector(
                        'button[name="add"], [data-add-to-cart], #AddToCart, .product-form__cart-submit'
                    );
                    if (!atcBtn) return false;
                    let el = atcBtn.parentElement;
                    while (el && el !== document.body) {
                        const pos = window.getComputedStyle(el).position;
                        if (pos === 'sticky' || pos === 'fixed') return true;
                        el = el.parentElement;
                    }
                    return false;
                })(),
                has_atc_button: !!document.querySelector(
                    'button[name="add"], [data-add-to-cart], #AddToCart, .product-form__cart-submit'
                ),
                atc_disabled: !!document.querySelector(
                    'button[name="add"][disabled], [data-add-to-cart][disabled], #AddToCart[disabled]'
                ),
                has_dynamic_checkout: !!document.querySelector('.shopify-payment-button, [data-shopify="payment-button"]'),
                dynamic_checkout_empty: (() => {
                    const el = document.querySelector('.shopify-payment-button, [data-shopify="payment-button"]');
                    return el ? el.children.length === 0 : null;
                })(),
                variant_selectors: Array.from(document.querySelectorAll('select[name="id"], .single-option-selector'))
                    .map(s => ({ name: s.name, options: s.options?.length || 0 })),
            };
        }""")

    async def _test_add_to_cart(self, page: Page, url: str) -> Dict:
        """Actually click Add to Cart and verify the cart responds."""
        result = {
            "button_found": False,
            "button_enabled": False,
            "variant_required": False,
            "cart_responded": False,
            "console_errors": [],
            "error": None,
        }
        try:
            # Capture JS console errors during the ATC interaction
            console_errors: list = []
            page.on("console", lambda msg: console_errors.append(msg.text[:200]) if msg.type == "error" else None)

            # Try to select first available variant
            for sel in VARIANT_SELECTORS:
                variant_el = await page.query_selector(sel)
                if variant_el:
                    result["variant_required"] = True
                    options = await variant_el.query_selector_all("option:not([disabled])")
                    if options:
                        await variant_el.select_option(index=1 if len(options) > 1 else 0)
                    break

            await page.wait_for_timeout(500)

            # Find ATC button
            atc_btn = None
            for sel in ATC_SELECTORS:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    atc_btn = btn
                    result["button_found"] = True
                    result["button_enabled"] = not await btn.get_attribute("disabled")
                    break

            if not atc_btn or not result["button_enabled"]:
                return result

            # Primary check: Shopify cart API — reliable across all themes
            _cart_js = """async () => {
                try {
                    const r = await fetch('/cart.js', {cache: 'no-store'});
                    const d = await r.json();
                    return d.item_count;
                } catch(e) { return null; }
            }"""
            api_before = await page.evaluate(_cart_js)

            await atc_btn.click()
            await page.wait_for_timeout(3000)

            api_after = await page.evaluate(_cart_js)
            api_responded = (
                api_before is not None and api_after is not None
                and api_after > api_before
            )

            # Fallback: DOM observation (drawer, notification, count bubble)
            cart_before = await self._get_cart_count(page)
            cart_after  = await self._get_cart_count(page)
            drawer_open = await self._cart_drawer_visible(page)
            notification = await page.query_selector(
                '.cart-notification, .cart-popup, [class*="added-to-cart"], '
                '.m-cart-notification, [class*="cart-notification"], '
                '.m-cart-drawer, [class*="cart-drawer"], [class*="cart-open"]'
            )

            result["cart_responded"] = api_responded or (
                (cart_after is not None and cart_before is not None and cart_after > cart_before)
                or drawer_open
                or notification is not None
            )
            result["console_errors"] = console_errors[:5]

        except Exception as e:
            result["error"] = str(e)[:200]

        return result

    async def _test_checkout_button(self, page: Page) -> Dict:
        """Check the cart page has a functional checkout button.

        Cart may be empty during the crawl, so the button can exist in the DOM
        but be hidden (0x0). We check DOM presence first; only flag as missing
        if the element doesn't exist at all.
        """
        result = {"button_found": False, "button_enabled": False, "cart_empty": False}

        # Detect empty cart state so we don't false-positive a missing checkout btn
        empty_signals = await page.query_selector(
            '[class*="empty-cart" i], [class*="cart-empty" i], '
            '[id*="empty-cart" i], [id*="cart-empty" i]'
        )
        body_text = await page.evaluate("() => document.body.innerText.slice(0, 1000).toLowerCase()")
        if empty_signals or "your cart is empty" in body_text or "cart is empty" in body_text:
            result["cart_empty"] = True

        for sel in CHECKOUT_BTN_SELECTORS:
            btn = await page.query_selector(sel)
            if btn:
                # Element exists — consider the button present even if invisible on empty cart
                result["button_found"] = True
                disabled = await btn.get_attribute("disabled")
                result["button_enabled"] = disabled is None
                break
        return result

    async def _test_mobile_cart(self, mobile_ctx: BrowserContext, url: str) -> Dict:
        """Test cart icon tap on mobile viewport."""
        result = {"cart_icon_found": False, "cart_icon_tappable": False, "error": None}
        page = await mobile_ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # href*="/cart" matches both relative (/cart) and absolute (https://pepstores.com/cart) URLs
            cart_icon = await page.query_selector(
                'a[href*="/cart"]:not([href*="/cart/"]):not([href*="articles"]), '
                '.m-cart-icon-bubble, [data-cart-toggle], '
                '.cart-icon, .header__cart, [class*="cart-icon" i], '
                '[aria-label*="cart" i]'
            )
            if cart_icon and await cart_icon.is_visible():
                result["cart_icon_found"] = True
                box = await cart_icon.bounding_box()
                result["cart_icon_tappable"] = box is not None and box["width"] >= 44 and box["height"] >= 44
        except Exception as e:
            result["error"] = str(e)[:200]
        finally:
            await page.close()
        return result

    async def _get_cart_count(self, page: Page) -> Optional[int]:
        for sel in CART_COUNT_SELECTORS:
            el = await page.query_selector(sel)
            if el:
                text = await el.text_content()
                try:
                    return int(re.sub(r"[^\d]", "", text or "0") or "0")
                except ValueError:
                    pass
        return None

    async def _cart_drawer_visible(self, page: Page) -> bool:
        for sel in CART_DRAWER_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True
        return False
