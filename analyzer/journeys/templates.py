"""Journey template definitions — 5 scenarios × 2 devices = 10 journeys per audit."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class JourneyStep:
    name: str       # machine key, used in failed_at
    action: str     # one of the action strings in runner.py
    label: str      # human-readable label for the report
    kwargs: dict = field(default_factory=dict)


@dataclass
class JourneyTemplate:
    id: str
    name: str
    description: str
    steps: List[JourneyStep]
    # If True, only run on mobile viewport
    mobile_only: bool = False


# ── Step actions (implemented in runner._execute_step) ───────────────────────
#
#  navigate            Go to URL (kwargs: url)
#  click_collection    Click first collection link found on current page
#  click_online_product  Click first product with "Available Online" badge (or first product link)
#  click_atc           Click Add to Cart button; measures CTA position
#  wait_cart_response  Wait 4 s and verify cart updated (drawer / count / notification)
#  click_checkout      Click checkout button; measures CTA position
#  click_hamburger     Click mobile menu toggle
#  click_menu_collection  Click first collection link inside the open mobile menu
#  click_sort          Open sort dropdown and select price-ascending
#  click_search        Click search input or open search overlay
#  type_search         Fill search input with kwargs["query"] and submit
#  click_search_result Click first product link in search results


JOURNEY_TEMPLATES: List[JourneyTemplate] = [
    JourneyTemplate(
        id="J1",
        name="Full Browse Funnel",
        description="Homepage → Collection → Online Product → Cart → Checkout",
        steps=[
            JourneyStep("homepage",        "navigate",             "Land on homepage",              {"url": "/"}),
            JourneyStep("collection",      "click_collection",     "Click first collection link"),
            JourneyStep("product",         "click_online_product", "Click online-available product"),
            JourneyStep("atc",             "click_atc",            "Click Add to Cart"),
            JourneyStep("cart_response",   "wait_cart_response",   "Confirm cart updated"),
            JourneyStep("cart",            "navigate",             "Navigate to cart",              {"url": "/cart"}),
            JourneyStep("checkout",        "click_checkout",       "Tap Proceed to Checkout"),
        ],
    ),
    JourneyTemplate(
        id="J2",
        name="Direct Product Landing",
        description="Product (direct URL) → Cart → Checkout",
        steps=[
            JourneyStep("product",         "navigate",             "Land on product page",          {"url": "{product_url}"}),
            JourneyStep("atc",             "click_atc",            "Click Add to Cart"),
            JourneyStep("cart_response",   "wait_cart_response",   "Confirm cart updated"),
            JourneyStep("cart",            "navigate",             "Navigate to cart",              {"url": "/cart"}),
            JourneyStep("checkout",        "click_checkout",       "Tap Proceed to Checkout"),
        ],
    ),
    JourneyTemplate(
        id="J3",
        name="Mobile Navigation Flow",
        description="Homepage → Hamburger → Collection → Product → Cart → Checkout",
        mobile_only=True,
        steps=[
            JourneyStep("homepage",        "navigate",             "Land on homepage",              {"url": "/"}),
            JourneyStep("hamburger",       "click_hamburger",      "Open hamburger menu"),
            JourneyStep("menu_collection", "click_menu_collection","Pick collection from menu"),
            JourneyStep("product",         "click_online_product", "Click online-available product"),
            JourneyStep("atc",             "click_atc",            "Click Add to Cart"),
            JourneyStep("cart_response",   "wait_cart_response",   "Confirm cart updated"),
            JourneyStep("cart",            "navigate",             "Navigate to cart",              {"url": "/cart"}),
            JourneyStep("checkout",        "click_checkout",       "Tap Proceed to Checkout"),
        ],
    ),
    JourneyTemplate(
        id="J4",
        name="Collection Sort & Buy",
        description="Collection → Sort Price Low→High → Product → Cart → Checkout",
        steps=[
            JourneyStep("collection",      "navigate",             "Land on Available Online",      {"url": "/collections/available-online"}),
            JourneyStep("sort",            "click_sort",           "Sort by price low-high"),
            JourneyStep("product",         "click_online_product", "Click first product after sort"),
            JourneyStep("atc",             "click_atc",            "Click Add to Cart"),
            JourneyStep("cart_response",   "wait_cart_response",   "Confirm cart updated"),
            JourneyStep("cart",            "navigate",             "Navigate to cart",              {"url": "/cart"}),
            JourneyStep("checkout",        "click_checkout",       "Tap Proceed to Checkout"),
        ],
    ),
    JourneyTemplate(
        id="J5",
        name="Search-Driven Purchase",
        description="Homepage → Search → Results → Product → Cart → Checkout",
        steps=[
            JourneyStep("homepage",        "navigate",             "Land on homepage",              {"url": "/"}),
            JourneyStep("search_open",     "click_search",         "Open search"),
            JourneyStep("search_type",     "type_search",          "Search for product",            {"query": "{search_term}"}),
            JourneyStep("result",          "click_search_result",  "Click first search result"),
            JourneyStep("atc",             "click_atc",            "Click Add to Cart"),
            JourneyStep("cart_response",   "wait_cart_response",   "Confirm cart updated"),
            JourneyStep("cart",            "navigate",             "Navigate to cart",              {"url": "/cart"}),
            JourneyStep("checkout",        "click_checkout",       "Tap Proceed to Checkout"),
        ],
    ),
]
