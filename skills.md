# Shopify CRO Specialist Knowledge Base
## pepstores.com — Conversion Rate Optimisation

You are acting as a senior CRO specialist with deep Shopify expertise. Use this knowledge base
when analysing audit findings. Always frame issues in terms of business impact (lost revenue,
abandoned carts, drop-off) before explaining the technical cause.

---

## CRITICAL SHOPIFY FAILURE MODES (Conversion-Killers)

### 1. Add to Cart Broken
**Detection:** Button present but click does nothing; no cart count change; no drawer/notification
**Root causes:**
- JS conflict between theme and an installed app (most common on custom-code stores)
- Variant not pre-selected — Shopify disables the ATC button until a variant is chosen
- `form[action="/cart/add"]` missing or malformed
- `fetch('/cart/add.js')` returning 422 (sold out) or 500 (server error)
- Event listener overwritten by custom code
**Business impact:** 100% of affected product page visitors cannot purchase. Highest priority issue.
**Fix:** Check browser console for JS errors on ATC click. Test `/cart/add.js` endpoint directly. Audit app scripts for conflicts.

### 2. Checkout Flow Broken / Inaccessible
**Detection:** Checkout button missing, disabled, or leads to error page
**Root causes:**
- Shopify Payments not activated (store can't accept payments)
- Custom checkout scripts throwing errors
- Cart page missing checkout button
- `checkout.shopify.com` blocked or misconfigured
**Business impact:** Zero sales possible if checkout is unreachable.
**Fix:** Verify Shopify Payments status in admin. Test `/checkout` endpoint. Review cart.liquid for checkout button.

### 3. Dynamic Checkout Buttons Not Rendering (Buy Now / PayPal / Apple Pay)
**Detection:** `.shopify-payment-button` container is empty; buttons should appear but don't
**Root causes:**
- Payment provider not configured in Shopify admin
- CSP (Content Security Policy) blocking Shopify's payment scripts
- Custom JS removing or hiding the container
- Browser/region mismatch (Apple Pay only shows on Apple devices)
**Business impact:** Removes the highest-converting "Buy Now" path for returning customers.
**Fix:** Check Shopify admin > Payments. Inspect CSP headers. Test in multiple browsers.

### 4. Variant Selector Leaves ATC Disabled
**Detection:** Product page loads with "Add to Cart" greyed out; no variant pre-selected
**Root causes:**
- Theme default — Shopify disables ATC until variant selected
- First variant is sold out (Shopify disables for OOS variants)
- Custom JS not triggering variant selection on load
**Business impact:** Creates friction; users unfamiliar with Shopify may think product is unavailable.
**Fix:** Auto-select first available variant on page load. Show clear "Select a size/colour" prompt.

### 5. Mobile Cart Icon / Drawer Not Working
**Detection:** Cart icon click on mobile does nothing or page doesn't respond
**Root causes:**
- z-index conflict with sticky header or popup
- Touch event handler conflicting with scroll
- Cart drawer JS error on mobile viewport
- Fixed positioning issue after orientation change
**Business impact:** Mobile users (often 60%+ of ecommerce traffic) cannot access cart.
**Fix:** Test on real mobile devices. Check z-index stacking. Audit touch event handlers.

### 6. App Script Bloat (Render-Blocking)
**Detection:** 10+ third-party scripts in `<head>`; LCP > 4s; FCP > 3s
**Root causes:**
- Each Shopify app injects scripts — they accumulate over time
- Many load synchronously and block rendering
- Scripts loaded for all pages, not just where needed
**Business impact:** 1 second delay in page load = 7% conversion drop. 3s+ causes 40%+ bounce rate increase.
**Fix:** Audit installed apps — remove unused. Move scripts to async/defer. Use Shopify's Script Editor carefully.

### 7. Product Page Missing Key Elements
**Detection:** No price, no reviews widget, < 2 images, no description, no size guide
**Root causes:** Custom code removing elements; metafield data missing; app widget failed to load
**Business impact:** Reduces purchase confidence. Products with reviews convert 3.5x better.
**Fix:** Audit each product template. Ensure price, reviews, images, and description are mandatory.

### 8. Search Returning No Results (or Broken)
**Detection:** Search query returns 0 results for popular terms; search page errors
**Root causes:**
- Shopify Predictive Search API failing
- Custom search implementation broken
- Search index not including all products
**Business impact:** 43% of visitors go straight to search. Search users convert 2-3x better.
**Fix:** Test with common product terms. Check Shopify Search & Discovery app configuration.

### 9. Collection Page Filters Not Working
**Detection:** Filter selections don't update product grid; URL params change but products don't filter
**Root causes:**
- Shopify storefront API change breaking custom filter implementation
- Theme JS error on filter click
- App conflict with filtering logic
**Business impact:** Users cannot find products. Direct path from browse → purchase is broken.
**Fix:** Test all filter combinations. Check browser console on filter click.

### 10. Cookie Consent / Popup Blocking Checkout
**Detection:** Cookie banner or popup overlay blocks CTA buttons; cannot dismiss on mobile
**Root causes:**
- Popup z-index higher than checkout button
- Cookie consent script timing — fires after page render, covers content
- GDPR popup modal not closable on iOS
**Business impact:** Any friction over the buy button directly reduces conversion.
**Fix:** Ensure consent banners appear below sticky CTAs. Test close button on mobile.

### 11. SSL / HTTPS Issues
**Detection:** Mixed content warnings; HTTP pages; certificate errors
**Business impact:** Chrome shows "Not Secure" — 85% of shoppers will not purchase on non-HTTPS sites.
**Fix:** Force HTTPS redirect in Shopify admin. Check for hard-coded HTTP asset URLs.

### 12. Price Not Prominently Displayed
**Detection:** Price absent, hidden, or below the fold on product pages
**Business impact:** Price clarity is the #1 factor in purchase decisions. Hidden pricing = lost trust.
**Fix:** Price must be in the top visual area, near the ATC button, in a readable font size (18px+).

### 13. No Trust Signals at Checkout
**Detection:** Checkout page lacks payment icons, security seals, or return policy link
**Business impact:** 17% of cart abandonment is due to trust concerns at checkout.
**Fix:** Add "Secure Checkout" badge, payment method icons, and returns link to checkout.

### 14. Slow LCP on Product Pages
**Detection:** LCP > 2.5s; hero product image loading slowly
**Root causes:** Unoptimised images (no WebP); no lazy loading strategy; large JS bundles blocking render
**Business impact:** Pages under 2.4s load time achieve ~1.9% conversion rate. Pages over 5.7s drop to ~0.6% (a 3x difference). On mobile: 1→3s load = +32% bounce rate; 1→5s = +90% bounce rate (Google research). This is the most data-backed conversion lever available.
**Fix:** Use Shopify's image CDN with `?width=` parameters. Enable lazy loading for below-fold images. Target sub-3s mobile load. Do NOT strip trust signals or reviews to chase speed scores — compress assets instead.

### 15. Out-of-Stock Handling
**Detection:** OOS products show ATC button (broken), or no availability message
**Root causes:** Theme not checking Shopify variant availability correctly
**Business impact:** Frustrates users; damages trust. Should show "Notify Me" or "Similar Products" instead.
**Fix:** Handle `available: false` variant state explicitly in product template.

### 16. No Guest Checkout Path
**Detection:** Shopify checkout requires account login; no "Continue as Guest" option
**Business impact:** 23% of users abandon when forced to create an account (Baymard Institute data).
**Fix:** Shopify admin > Settings > Checkout > enable "Accounts are optional".

### 17. Discount Code Field Hidden or Broken
**Detection:** Discount code field missing on cart page or not applying at checkout
**Business impact:** If you run promotions, broken discount codes kill campaign ROI.
**Fix:** Test discount code flow end-to-end. Ensure cart attributes are passed to checkout.

### 18. Broken or Missing Breadcrumbs on Product Pages
**Detection:** No breadcrumb navigation; no schema BreadcrumbList markup
**Business impact:** Users lose navigation context. Also misses rich result opportunity in search.
**Fix:** Add breadcrumb HTML + BreadcrumbList JSON-LD schema.

### 19. Missing Product Schema
**Detection:** No `Product` JSON-LD on product pages; no price/availability in search results
**Business impact:** Misses rich results (star ratings, price, availability in Google SERP) — increases CTR by 20-30%.
**Fix:** Add Product schema with `offers`, `aggregateRating`, and `availability` properties.

### 20. Announcement Bar / Banner Link Broken
**Detection:** Announcement bar CTA links to 404 or wrong URL
**Business impact:** First thing users see on landing — if broken, undermines credibility immediately.
**Fix:** Audit all banner/announcement CTAs. Test links after every deploy.

---

## TRUST SIGNAL PATTERNS (From Industry Research)

### Trust signals must be near the decision point
Burying reviews in a footer or on an "About" page neutralises them. Research shows trust signals **lift conversion 20%+ when placed correctly** (adjacent to CTA or contact form). Placement matters more than presence.

**Sandwich pattern:** Show proof elements both *above* and *below* the primary CTA. The moment a visitor sees the CTA, proof should be in sight.

**What counts as a trust signal:**
- Customer reviews with specific outcomes (not "Great service!" — that's noise)
- Payment method icons (Visa, Mastercard, EFT) visible before checkout
- Security seals ("Secure Checkout", SSL badge)
- Return policy plainly visible on product and cart pages
- Third-party certifications or awards
- Real statistics or measurable results

**Weak trust signals to flag:**
- Vague testimonials with no outcomes ("Amazing!" / "Love it!")
- Trust badges buried in footer
- Payment icons only visible inside checkout — too late
- Generic stock imagery next to trust copy

**Detection logic:**
- Check if reviews widget is above the fold or below ATC button
- Check if payment badges appear on product page (not just checkout)
- Check if return policy is accessible from product page
- Flag if the only trust signals are in the footer

---

## MOBILE CONVERSION (Critical for pepstores.com)

Mobile represents 60%+ of ecommerce traffic. Conversion rates on mobile lag desktop — but the gap is closing and cannot be ignored.

### Mobile load speed thresholds (evidence-based benchmarks)
| Load time | Impact |
|---|---|
| Under 2.4s | Conversion rate ~1.9% |
| Over 5.7s | Conversion rate drops to ~0.6% (3x worse) |
| 1s → 3s (mobile) | Bounce probability +32% (Google research) |
| 1s → 5s (mobile) | Bounce probability +90% (Google research) |

**Implication:** A page loading in 6 seconds on mobile is not "a bit slow" — it has effectively destroyed most of its conversion potential. Mobile load speed is the single most data-backed conversion lever.

### Mobile-specific conversion checks
- Cart icon tap target must be 44×44px minimum (Apple HIG) or 48×48dp (Material)
- ATC button must be visible without scrolling on common mobile viewports (390px wide)
- No horizontal scroll on product or checkout pages
- Checkout form fields must not trigger iOS zoom (font-size ≥ 16px on inputs)
- Sticky "Add to Cart" bar on scroll is a high-impact fix for mobile product pages
- Cookie consent / popups must be dismissable without covering the ATC area

---

## PRODUCT PAGE QUALITY (eCommerce-Specific)

### Product images — multiple angles are non-negotiable
A single product image is not enough. Customers do not trust a product they can only see from one angle. They understand that a "good angle" or specific shot can hide flaws. Women's clothing in particular benefits from multiple model shots and detail close-ups.

**Minimum viable:** 3+ images showing front, back, and detail
**Better:** Lifestyle shot + multiple angles + zoom capability
**Detection:** Count images on product pages; flag if only 1 image is present

### Product description quality
Hastily written or manufacturer-copied descriptions fail to convert. Generic copy forces visitors to compare on price alone — the most damaging competitive position.

**Weak description signals (flag these):**
- Very short description (< 50 words)
- Obvious manufacturer spec dump (model numbers, dimensions only)
- No customer-facing benefit language
- No size guide or fit information for clothing

### Decision paralysis — one page, one goal
When a page has competing CTAs, multiple service options, or too many navigation paths, visitors don't pick the best one — they leave. This is a well-documented psychological phenomenon (decision paralysis / choice overload).

**For pepstores.com:** Each collection/product page should have one dominant action. The ATC button must be the clearest interactive element on the page.

**Detection:** Count primary CTA buttons visible above the fold. If more than one, flag as decision paralysis risk.

---

## CTA CLARITY & PLACEMENT

### No clear CTA above the fold is a conversion killer
Visitors decide in under 5 seconds whether to stay or leave. If the above-fold area does not tell them exactly what to do next, they bounce — wasting all ad spend and SEO equity used to bring them there.

**Vague CTAs that create friction (flag these):**
- "Learn More", "Get Started", "Welcome"
- "Contact Us" without a specific benefit
- No button visible without scrolling

**Strong CTA characteristics:**
- Benefit-driven language ("Add to Cart", "Buy Now", specific offer)
- High contrast — visually impossible to miss
- One dominant action per section (competing CTAs neutralise each other)

### CTAs must match user journey stage
- Early stage (awareness): low-friction actions ("View range", "See all products")
- Mid stage (consideration): clarity actions ("View pricing", "Compare options")  
- Late stage (intent): commitment actions ("Add to Cart", "Checkout now")

Placing a "Buy Now" CTA on a user who is still browsing creates friction. Placing a "Learn More" on a user who is ready to buy loses the sale.

---

## FUNCTIONAL TESTING CHECKLIST (Run After Every Deploy)

Based on industry research: *"A page can look polished and still leak conversions if the functionality is broken underneath."*

Every deploy to pepstores.com should verify:
- [ ] Add to Cart works on desktop (click → cart count increments or drawer opens)
- [ ] Add to Cart works on mobile (tap → same response)
- [ ] Variant selection → ATC button enables correctly
- [ ] Checkout button on cart page is visible and enabled
- [ ] Checkout flow reaches confirmation page
- [ ] Search returns results for top product terms
- [ ] Navigation links reach correct pages (no 404s)
- [ ] Cookie banner can be dismissed on mobile without covering ATC
- [ ] Dynamic checkout buttons (EFT, card) render on product pages
- [ ] Discount code field accepts and applies codes

**Why this matters:** The biggest conversion losses often come from bugs introduced by developers that no one caught because no one tested the full user journey after the change.

---

## PAGE SPEED — BALANCE, DON'T STRIP

Page speed matters, but it is one of the most over-simplified issues in marketing. Slow load times hurt conversions — but so does removing the elements that build trust and help users understand the product.

**The goal is to build the fastest page that still does its job.**

Removing product images, trust signals, or reviews widgets to chase a speed score will improve the score while hurting actual conversion. Conversely, a beautifully designed page that takes 6 seconds to load on mobile will convert at 0.6% regardless of how good the design is.

**Correct fixes (compress, don't remove):**
- Compress images and serve WebP via Shopify CDN (`?format=webp&width=N`)
- Lazy-load below-fold images
- Move non-critical scripts to async/defer
- Remove *unused* app scripts (not all scripts — only unused ones)
- Eliminate render-blocking CSS for above-fold content

---

## SCORING WEIGHTS (Conversion Impact)

| Category | Weight | Rationale |
|---|---|---|
| Functional (ATC, Checkout) | 40% | Zero sales if these break |
| Trust & Security | 25% | Correct placement lifts conversion 20%+; buried trust signals are worthless |
| Performance (Core Web Vitals) | 20% | 2.4s vs 5.7s load time = 3x conversion rate difference |
| Product Page Quality | 10% | Images, copy, and reviews drive purchase confidence |
| Navigation & Discovery | 5% | Getting users to the right page |

---

## ROADMAP PRIORITISATION FRAMEWORK

**P0 — Fix Today (Blocker):** Anything preventing a user from completing a purchase
- Add to Cart broken
- Checkout inaccessible
- Mobile cart not working

**P1 — Fix This Sprint (High Impact):** Losing significant conversion rate
- Trust signals missing or buried (not adjacent to ATC/checkout CTA)
- Performance >3s mobile load time (bounce +32% at 3s, +90% at 5s)
- Dynamic checkout buttons missing
- Variant selector issues
- No clear CTA above the fold
- Single product image (multiple angles required for trust)

**P2 — Fix This Month (Medium Impact):** Meaningful improvement to conversion
- Trust signals present but weak (vague testimonials, footer-only placement)
- Missing reviews/social proof adjacent to ATC button
- Product description quality (manufacturer copy, too short)
- Search functionality
- Filter UX
- Decision paralysis (too many competing CTAs above fold)

**P3 — Roadmap (Low Impact / Quick Wins):** Polish and optimisation
- Schema markup
- Breadcrumbs
- Open Graph tags
- Image alt text

---

## KNOWN SHOPIFY PLATFORM QUIRKS

- Shopify checkout URL is always `checkout.shopify.com` — cannot be custom-themed without Shopify Plus
- `/cart.js` and `/cart/add.js` are reliable AJAX endpoints for testing cart functionality
- `window.Shopify` object indicates Shopify store; `window.Shopify.theme` gives theme name
- `window.ShopifyAnalytics` or `window.__st` indicates analytics scripts loaded
- Shopify CDN serves images from `cdn.shopify.com` — use `?width=` param for responsive sizing
- Shopify's default product handle format: `/products/{handle}`
- Collections: `/collections/{handle}`
- Predictive search API: `/search/suggest.json?q={query}&resources[type]=product`
- Dynamic checkout renders via `Shopify.PaymentButton` — check for this object in console
