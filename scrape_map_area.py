"""
Scrape listings from Immoweb using the map area filter around Guillemins.
Then open detail pages to get coordinates and calculate walking distance.
"""
import json
import logging
import os
import time
import urllib.parse

from playwright.sync_api import sync_playwright
from models import init_db, add_listing, get_all_listings, update_listing_status
from config import GUILLEMINS_LAT, GUILLEMINS_LON, MAX_WALK_DISTANCE_METERS

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
)


def haversine_distance(lat1, lon1, lat2, lon2):
    import math
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def make_browser(p):
    return p.chromium.launch(
        headless=True,
        executable_path=CHROMIUM_PATH,
        args=['--no-sandbox', '--disable-gpu'],
    )


# --- Step 1: Extract listings from map search ---

def scrape_map_search():
    """
    Use Immoweb's map area search to find listings near Guillemins.
    Returns list of basic listing info (no coordinates yet).
    """
    PARAMS = {
        'propertyTypes': 'HOUSE,APARTMENT',
        'transactionTypes': 'FOR_RENT',
        'priceType': 'MONTHLY_RENTAL_PRICE',
        'minBedroomCount': '2',
        'maxPrice': '1200',
        'minPrice': '800',
        'minSurface': '80',
        'countries': 'BE',
        'geoSearchAreas': 'y}_tHsf|`@?cfCtiA??bfC',  # User-drawn area around Guillemins
        'orderBy': 'newest',
    }

    search_url = 'https://www.immoweb.be/en/search?' + urllib.parse.urlencode(PARAMS, safe='%')
    logger.info(f"Map search URL: {search_url}")

    all_listings = []

    with sync_playwright() as p:
        browser = make_browser(p)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )

        for page_num in range(1, 6):  # Up to 5 pages
            page = context.new_page()
            url = search_url + f'&page={page_num}' if page_num > 1 else search_url

            try:
                logger.info(f"Fetching page {page_num}...")
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(5000)

                listings = page.evaluate("""() => {
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
                        const img = a.querySelector('img.card__media-picture--loaded');
                        const imageUrl = img ? (img.getAttribute('src') || '') : '';
                        const isNew = !!a.querySelector('.flag-list__item--new');
                        let title = '';
                        const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                        for (const line of lines) {
                            if (line.length > 10 && !line.includes('€') && !line.includes('bdr') && !line.includes('m²') && !line.match(/^\\d{4}/)) {
                                title = line; break;
                            }
                        }
                        if (!title) title = text.includes('House') ? 'House' : 'Apartment';
                        return { id, url, price, bedrooms, surface, address, imageUrl, isNew, title: title.substring(0, 150) };
                    });
                }""")

                logger.info(f"  Found {len(listings)} listings")
                for l in listings:
                    if 200 <= l['price'] <= 1300 and l['bedrooms'] >= 1:
                        l['source'] = 'immoweb'
                        all_listings.append(l)

                if not listings:
                    page.close()
                    break

            except Exception as e:
                logger.error(f"  Error: {e}")

            page.close()
            time.sleep(1.5)

        browser.close()

    logger.info(f"Total listings from map search: {len(all_listings)}")
    return all_listings


# --- Step 2: Get coordinates from detail pages ---

def enrich_with_details(listings, max_listings=None):
    """Open detail pages to get coordinates, full address, dates."""
    target = listings if max_listings is None else listings[:max_listings]

    with sync_playwright() as p:
        browser = make_browser(p)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )

        for i, listing in enumerate(target):
            url = listing.get('url')
            if not url:
                continue

            logger.info(f"[{i+1}/{len(target)}] {listing['id']}...")

            page = context.new_page()

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(4000)

                detail = page.evaluate("""() => {
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
                                    lat: loc.latitude,
                                    lng: loc.longitude,
                                    street: loc.street || '',
                                    number: loc.number || '',
                                    box: loc.box || '',
                                    postalCode: loc.postalCode || '',
                                    locality: loc.locality || '',
                                    date_posted: pub.date || pub.creationDate || '',
                                    description: (prop.description && prop.description.en) || '',
                                    bedrooms: prop.bedroomCount || prop.bedrooms || 0,
                                    surface: prop.netHabitableSurface || null,
                                    image: media.length > 0 ? (media[0].url || media[0].src || '') : '',
                                    title: prop.title || prop.name || '',
                                };
                            } catch(e) { return null; }
                        }
                    }
                    return null;
                }""")

                if detail and detail.get('lat') and detail.get('lng'):
                    listing['latitude'] = detail['lat']
                    listing['longitude'] = detail['lng']
                    listing['distance_to_station'] = haversine_distance(
                        GUILLEMINS_LAT, GUILLEMINS_LON, detail['lat'], detail['lng']
                    )
                    listing['full_address'] = (
                        f"{detail.get('street', '')} {detail.get('number', '')}"
                        f"{' ' + detail.get('box', '') if detail.get('box') else ''}"
                        f", {detail.get('postalCode', '')} {detail.get('locality', '')}"
                    ).strip().strip(',')
                    if detail.get('date_posted'):
                        listing['date_posted'] = detail['date_posted']
                    if detail.get('description'):
                        listing['description'] = detail['description']
                    if detail.get('image'):
                        listing['image_url'] = detail['image']
                    if detail.get('surface'):
                        listing['surface_area'] = detail['surface']
                    if detail.get('title'):
                        listing['title'] = detail['title']

                    logger.info(f"  → ({detail['lat']:.4f}, {detail['lng']:.4f}) "
                               f"dist={listing['distance_to_station']:.0f}m")
                else:
                    logger.warning(f"  → No coordinates found")

            except Exception as e:
                logger.warning(f"  → Error: {e}")

            page.close()
            time.sleep(1)

        browser.close()


# --- Step 3: Save to database ---

def save_to_db(listings):
    """Save listings to the database."""
    init_db()
    count = 0
    for l in listings:
        if not l.get('latitude') or not l.get('longitude'):
            continue
        data = {
            'external_id': l['id'],
            'title': l.get('title', 'Appartement'),
            'price': l['price'],
            'bedrooms': l['bedrooms'],
            'surface_area': l.get('surface_area'),
            'address': l.get('full_address') or l.get('address', ''),
            'latitude': l['latitude'],
            'longitude': l['longitude'],
            'url': l.get('url', ''),
            'source': 'immoweb',
            'image_url': l.get('image_url', ''),
            'date_posted': l.get('date_posted', ''),
            'distance_to_station': l['distance_to_station'],
        }
        try:
            add_listing(data)
            count += 1
        except Exception as e:
            logger.warning(f"Error saving {l.get('id')}: {e}")
    return count


# --- Main ---

if __name__ == '__main__':
    # Step 1: Get listings from map search
    listings = scrape_map_search()
    print(f"\n=== Found {len(listings)} listings in map area ===")

    # Step 2: Get coordinates
    print("\n=== Getting coordinates from detail pages ===")
    enrich_with_details(listings)

    # Step 3: Save to DB
    print("\n=== Saving to database ===")
    saved = save_to_db(listings)
    print(f"Saved {saved} listings with coordinates")

    # Results
    nearby = [l for l in listings
              if l.get('distance_to_station') and l['distance_to_station'] <= MAX_WALK_DISTANCE_METERS]
    nearby.sort(key=lambda x: x['distance_to_station'])

    print(f"\n=== Listings within {MAX_WALK_DISTANCE_METERS}m of Guillemins ({len(nearby)}) ===")
    for l in nearby:
        addr = l.get('full_address') or l.get('address', '?')
        print(f"  ✅ €{l['price']}/m · {l['bedrooms']}cam · {l.get('surface_area', '?')}m² · {l['distance_to_station']:.0f}m")
        print(f"     {addr}")
        print(f"     Pubblicato: {(l.get('date_posted','')[:10]) if l.get('date_posted') else '?'}")
        print(f"     {l.get('url','')}")
        print()

    # Also show within 1000m
    within_1km = [l for l in listings
                  if l.get('distance_to_station') and l['distance_to_station'] <= 1000]
    if within_1km:
        print(f"\n=== Within 1km ({len(within_1km)}) ===")
        for l in within_1km:
            marker = '✅' if l['distance_to_station'] <= 800 else '🚶'
            print(f"  {marker} €{l['price']}/m · {l['bedrooms']}cam · {l['distance_to_station']:.0f}m · {l.get('address','?')}")
