"""
Immoweb scraper using Playwright — v2 with window.classified extraction.

Extracts rental listings from Immoweb search results, opens detail pages
to get exact coordinates (lat/lng), full address, and publication date,
then calculates walking distance to Liège-Guillemins station.
"""
import json
import logging
import math
import os
import re
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from config import GUILLEMINS_LAT, GUILLEMINS_LON, MAX_WALK_DISTANCE_METERS

logger = logging.getLogger(__name__)

CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
)

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_distance(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters between two lat/lon points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _browser_context(p):
    """Create a Playwright browser + context."""
    browser = p.chromium.launch(
        headless=True,
        executable_path=CHROMIUM_PATH,
        args=['--no-sandbox', '--disable-gpu'],
    )
    context = browser.new_context(
        user_agent=(
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        viewport={'width': 1920, 'height': 1080},
    )
    return browser, context


def _abort_assets(route):
    """Abort loading of non-essential resources."""
    if route.request.resource_type in ('image', 'stylesheet', 'font', 'media'):
        route.abort()
    else:
        route.continue_()


# ---------------------------------------------------------------------------
# Search-page extraction
# ---------------------------------------------------------------------------

def _extract_listings_from_search(page):
    """
    Extract listing cards from a search results page.
    Returns list of dicts with: external_id, url, price, bedrooms,
    surface_area, address, title, image_url, is_new.
    """
    return page.evaluate("""() => {
        const articles = document.querySelectorAll('article.card--result');
        return Array.from(articles).map(a => {
            const id = (a.id || '').replace('classified_', '');
            const link = a.querySelector('a');
            const url = link ? link.href : '';
            const text = a.textContent || '';

            let price = 0;
            const pm = text.match(/[€]\\s*([0-9,.]+)/);
            if (pm) price = parseInt(pm[1].replace(/,/g, ''));

            let bedrooms = 0;
            const bm = text.match(/(\\d+)\\s*bdr/);
            if (bm) bedrooms = parseInt(bm[1]);

            let surface = null;
            const sm = text.match(/(\\d+)\\s*m²/);
            if (sm) surface = parseFloat(sm[1]);

            let address = '';
            const am = text.match(/(\\d{4})\\s+([A-Za-zÀ-ÿ \\-]+)/);
            if (am) address = am[0].trim();

            let title = '';
            const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
            for (const line of lines) {
                if (line.length > 10
                    && !line.includes('€')
                    && !line.includes('bdr')
                    && !line.includes('m²')
                    && !line.match(/^\\d{4}/)) {
                    title = line;
                    break;
                }
            }
            if (!title) title = text.includes('House') ? 'House' : 'Apartment';

            const img = a.querySelector('img.card__media-picture--loaded');
            const imageUrl = img ? (img.getAttribute('src') || '') : '';
            const isNew = !!a.querySelector('.flag-list__item--new');

            return {
                external_id: id,
                url: url,
                price: price,
                bedrooms: bedrooms,
                surface_area: surface,
                address: address,
                title: title.substring(0, 150),
                image_url: imageUrl,
                is_new: isNew,
            };
        });
    }""")


# ---------------------------------------------------------------------------
# Detail-page extraction (window.classified)
# ---------------------------------------------------------------------------

def _extract_listing_detail(page, url):
    """
    Open a listing detail page and extract full data from window.classified.
    Returns a dict with all fields, or None on failure.
    """
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(4000)

        data = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                const t = s.textContent || '';
                if (t.includes('window.classified')) {
                    try {
                        const match = t.match(/window\\.classified\\s*=\\s*(\\{[^;]+\\})/);
                        if (!match) return null;
                        const c = JSON.parse(match[1]);
                        const prop = c.property || {};
                        const loc = prop.location || {};
                        const pub = c.publication || {};
                        const media = c.media || [];

                        return {
                            id: c.id,
                            title: prop.title || prop.name || '',
                            description: (prop.description && prop.description.en) || '',
                            price: (c.price && c.price.mainValue) || 0,
                            bedrooms: prop.bedroomCount || prop.bedrooms || 0,
                            surface: prop.netHabitableSurface || null,
                            street: loc.street || '',
                            number: loc.number || '',
                            box: loc.box || '',
                            postalCode: loc.postalCode || '',
                            locality: loc.locality || '',
                            latitude: loc.latitude || null,
                            longitude: loc.longitude || null,
                            date_posted: pub.date || pub.creationDate || '',
                            image: media.length > 0 ? (media[0].url || media[0].src || '') : '',
                            is_new: c.flags ? !!c.flags.isNewClassified : false,
                        };
                    } catch(e) {
                        return { error: e.message };
                    }
                }
            }
            return null;
        }""")

        if data and data.get('latitude') and data.get('longitude'):
            return data
        return None

    except Exception as e:
        logger.debug(f"Error opening detail page {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main scraping functions
# ---------------------------------------------------------------------------

def scrape_search_pages(max_pages=5):
    """
    Scrape listing cards from Immoweb search result pages.
    Returns raw listings (no coordinates or dates yet).
    """
    all_listings = []

    with sync_playwright() as p:
        browser, context = _browser_context(p)

        for page_num in range(1, max_pages + 1):
            page = context.new_page()
            page.route('**/*', _abort_assets)

            url = (
                'https://www.immoweb.be/en/search/house-and-apartment/for-rent/'
                f'liege/district?countries=BE&page={page_num}'
                '&orderBy=relevance&minBedroomCount=2&maxPrice=1300'
            )

            try:
                logger.info(f"Fetching search page {page_num}...")
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(5000)

                listings = _extract_listings_from_search(page)
                logger.info(f"Page {page_num}: {len(listings)} listings")

                for l in listings:
                    if 200 <= l['price'] <= 1300 and l['bedrooms'] >= 1:
                        l['source'] = 'immoweb'
                        all_listings.append(l)

                if not listings:
                    logger.info(f"No listings on page {page_num}, stopping.")
                    page.close()
                    break

            except Exception as e:
                logger.error(f"Error on page {page_num}: {e}")

            page.close()
            time.sleep(1.5)

        browser.close()

    logger.info(f"Total raw listings: {len(all_listings)}")
    return all_listings


def enrich_with_detail_pages(listings, max_listings=None):
    """
    Open each listing's detail page to get coordinates, full address, and date.
    Updates listings in place with: latitude, longitude, distance_to_station,
    date_posted, full_address, description, image_url.

    This is the SLOW step (~8-15s per listing for page load).
    Use max_listings to limit for testing.
    """
    if max_listings:
        listings = listings[:max_listings]

    with sync_playwright() as p:
        browser, context = _browser_context(p)

        for i, listing in enumerate(listings):
            url = listing.get('url')
            if not url:
                logger.warning(f"[{i+1}/{len(listings)}] No URL for {listing.get('external_id', '?')}")
                continue

            logger.info(f"[{i+1}/{len(listings)}] Fetching {url.split('/')[-1]}...")

            page = context.new_page()
            page.route('**/*', _abort_assets)

            detail = _extract_listing_detail(page, url)
            if detail:
                listing['full_address'] = (
                    f"{detail.get('street', '')} {detail.get('number', '')}"
                    f"{' ' + detail.get('box', '') if detail.get('box') else ''}"
                    f", {detail.get('postalCode', '')} {detail.get('locality', '')}"
                ).strip().strip(',')

                if detail.get('latitude') and detail.get('longitude'):
                    listing['latitude'] = detail['latitude']
                    listing['longitude'] = detail['longitude']
                    listing['distance_to_station'] = haversine_distance(
                        GUILLEMINS_LAT, GUILLEMINS_LON,
                        detail['latitude'], detail['longitude']
                    )

                if detail.get('date_posted'):
                    listing['date_posted'] = detail['date_posted']

                if detail.get('description'):
                    listing['description'] = detail['description']

                if detail.get('image') and not listing.get('image_url'):
                    listing['image_url'] = detail['image']

                if detail.get('surface') and not listing.get('surface_area'):
                    listing['surface_area'] = detail['surface']

                logger.info(f"  → ({detail['latitude']:.4f}, {detail['longitude']:.4f}) "
                           f"dist={listing.get('distance_to_station', 0):.0f}m "
                           f"date={detail.get('date_posted', '?')[:10]}")
            else:
                logger.warning(f"  → Could not extract details")

            page.close()
            time.sleep(1)  # Polite delay

        browser.close()


def scrape_all_pages(max_pages=3, detail_pages=True, max_details=None):
    """
    Full scrape: search pages + detail pages for coordinates/dates.

    Args:
        max_pages: Number of search result pages to scrape
        detail_pages: Whether to open detail pages (slow but gives coordinates)
        max_details: Max listings to enrich with details (None = all)

    Returns:
        List of listings within MAX_WALK_DISTANCE_METERS of Guillemins
    """
    listings = scrape_search_pages(max_pages=max_pages)

    if not listings:
        logger.warning("No listings found.")
        return []

    if detail_pages:
        enrich_with_detail_pages(listings, max_listings=max_details)

    # Filter by walking distance (only those with coordinates)
    nearby = [
        l for l in listings
        if l.get('distance_to_station') is not None
        and l['distance_to_station'] <= MAX_WALK_DISTANCE_METERS
    ]

    far = [l for l in listings if l.get('distance_to_station') is not None
           and l['distance_to_station'] > MAX_WALK_DISTANCE_METERS]
    no_coords = [l for l in listings if l.get('distance_to_station') is None]

    logger.info(f"Within {MAX_WALK_DISTANCE_METERS}m: {len(nearby)}")
    logger.info(f"Too far: {len(far)}")
    logger.info(f"No coords (detail pages not fetched?): {len(no_coords)}")

    return nearby


def get_listing_details(url):
    """Fetch detailed info for a single listing URL."""
    with sync_playwright() as p:
        browser, context = _browser_context(p)
        page = context.new_page()
        detail = _extract_listing_detail(page, url)
        page.close()
        browser.close()

    if detail and detail.get('latitude'):
        detail['distance_to_station'] = haversine_distance(
            GUILLEMINS_LAT, GUILLEMINS_LON,
            detail['latitude'], detail['longitude']
        )
    return detail or {}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
    )

    nearby = scrape_all_pages(max_pages=3, detail_pages=True, max_details=5)

    print(f"\n=== Listings within {MAX_WALK_DISTANCE_METERS}m of Guillemins ===")
    for l in nearby:
        addr = l.get('full_address') or l.get('address', '?')
        dist = l.get('distance_to_station', 0)
        print(f"  €{l['price']}/m · {l['bedrooms']}cam · {l.get('surface_area', '?')}m² · {dist:.0f}m")
        print(f"    {addr}")
        print(f"    {l.get('url', '')}")
        print()
