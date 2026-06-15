"""
Page discovery: Shopify sitemap parsing + homepage link crawl.
No external search API required.
"""
import re
import xml.etree.ElementTree as ET
from typing import List, Dict
from urllib.parse import urlparse, urljoin

import httpx


PAGE_TYPE_PATTERNS = {
    "product":    [r"/products/[^/?#]+$", r"/p/\d+"],
    "collection": [r"/collections/[^/?#]+$", r"/shop/", r"/category/"],
    "cart":       [r"/cart$", r"/basket$"],
    "checkout":   [r"/checkout"],
    "search":     [r"/search"],
    "blog":       [r"/blogs/", r"/articles/"],
    "policy":     [r"/policies/"],
    "account":    [r"/account", r"/login", r"/register"],
}


def classify(url: str) -> str:
    path = urlparse(url).path.lower()
    for page_type, patterns in PAGE_TYPE_PATTERNS.items():
        if any(re.search(p, path) for p in patterns):
            return page_type
    if path in ("/", ""):
        return "homepage"
    return "other"


class PageDiscoverer:
    def __init__(self, base_url: str):
        parsed = urlparse(base_url)
        self.scheme = parsed.scheme or "https"
        self.domain = parsed.netloc
        self.base_url = f"{self.scheme}://{self.domain}"

    async def discover(self, max_pages: int = 10) -> List[Dict]:
        discovered: Dict[str, Dict] = {}

        # Always include homepage
        discovered[self.base_url] = {"url": self.base_url, "page_type": "homepage"}

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CROBot/1.0)"},
        ) as client:
            # 1. Shopify sitemap
            sitemap_urls = await self._shopify_sitemaps(client)
            for url in sitemap_urls:
                if url not in discovered:
                    discovered[url] = {"url": url, "page_type": classify(url)}

            # 2. Probe key Shopify paths
            for probe_path in ["/cart", "/search?q=shoes", "/collections/all"]:
                url = self.base_url + probe_path
                if url not in discovered and await self._is_reachable(client, url):
                    discovered[url] = {"url": url, "page_type": classify(url)}

            # 3. Fetch product URLs from the collections JSON API (no scraping needed)
            # Try available-online first — Pep's curated online collection
            # Fall back to /collections/all if it doesn't exist
            product_urls = await self._fetch_collection_products(client, "/collections/available-online")
            if not product_urls:
                product_urls = await self._fetch_collection_products(client, "/collections/all")
            for url in product_urls:
                if url not in discovered:
                    discovered[url] = {"url": url, "page_type": "product"}

            # 4. Crawl homepage links if we still need pages
            if len(discovered) < max_pages + 3:
                homepage_links = await self._homepage_links(client)
                for url in homepage_links:
                    if url not in discovered:
                        discovered[url] = {"url": url, "page_type": classify(url)}

        return self._select_sample(list(discovered.values()), max_pages)

    async def _shopify_sitemaps(self, client: httpx.AsyncClient) -> List[str]:
        """Parse Shopify's sitemap_index.xml and sample each type."""
        urls = []
        index_url = f"{self.base_url}/sitemap.xml"
        try:
            r = await client.get(index_url)
            if r.status_code != 200:
                return urls
            root = ET.fromstring(r.text)
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # Sitemap index → sub-sitemaps
            sub_sitemaps = [loc.text.strip() for loc in root.findall("s:sitemap/s:loc", ns)]
            if not sub_sitemaps:
                # Direct URL set
                sub_sitemaps = []
                urls = [loc.text.strip() for loc in root.findall("s:url/s:loc", ns)]

            for sub_url in sub_sitemaps[:6]:
                try:
                    r2 = await client.get(sub_url)
                    if r2.status_code == 200:
                        sub_root = ET.fromstring(r2.text)
                        sub_urls = [loc.text.strip() for loc in sub_root.findall("s:url/s:loc", ns)]
                        # Sample up to 5 from each sub-sitemap
                        urls.extend(sub_urls[:5])
                except Exception:
                    pass
        except Exception:
            pass
        return [u for u in urls if urlparse(u).netloc == self.domain]

    async def _homepage_links(self, client: httpx.AsyncClient) -> List[str]:
        """Extract internal links from homepage."""
        try:
            from bs4 import BeautifulSoup
            r = await client.get(self.base_url)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "lxml")
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].split("#")[0].split("?")[0]
                if href.startswith("/"):
                    full = self.base_url + href
                elif href.startswith(self.base_url):
                    full = href
                else:
                    continue
                if full not in (self.base_url, self.base_url + "/") and full not in links:
                    links.append(full)
            return links[:40]
        except Exception:
            return []

    async def _is_reachable(self, client: httpx.AsyncClient, url: str) -> bool:
        try:
            r = await client.head(url)
            return r.status_code < 400
        except Exception:
            return False

    async def _fetch_collection_products(self, client: httpx.AsyncClient, collection_path: str) -> List[str]:
        """Fetch product URLs from Shopify's storefront collection JSON endpoint."""
        try:
            r = await client.get(f"{self.base_url}{collection_path}/products.json?limit=8")
            if r.status_code != 200:
                return []
            products = r.json().get("products", [])
            return [
                f"{self.base_url}/products/{p['handle']}"
                for p in products
                if p.get("handle") and any(v.get("available") for v in p.get("variants", []))
            ][:6]  # Only online-available products; cap at 6
        except Exception:
            return []

    def _select_sample(self, pages: List[Dict], max_pages: int) -> List[Dict]:
        """Pick a representative sample prioritising conversion-critical page types."""
        priority = ["homepage", "product", "collection", "cart", "checkout", "search", "other"]
        type_limits = {"homepage": 1, "product": 4, "collection": 3, "cart": 1, "checkout": 1, "search": 1}

        pages.sort(key=lambda p: priority.index(p["page_type"]) if p["page_type"] in priority else len(priority))

        selected = []
        counts: Dict[str, int] = {}
        for page in pages:
            pt = page["page_type"]
            limit = type_limits.get(pt, 1)
            if counts.get(pt, 0) < limit and len(selected) < max_pages:
                selected.append(page)
                counts[pt] = counts.get(pt, 0) + 1

        # Fill remaining slots with anything not yet selected
        for page in pages:
            if len(selected) >= max_pages:
                break
            if page not in selected:
                selected.append(page)

        return selected[:max_pages]
