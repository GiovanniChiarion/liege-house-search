"""Extract structured listing data from Immoweb using Playwright"""
from playwright.sync_api import sync_playwright
import os
import json
import re
import math

CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
)
GUILLEMINS_LAT = 50.6243
GUILLEMINS_LON = 5.5665


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def extract_listings(max_pages=5):
    """Scrape Immoweb listings and return structured data."""
    all_listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=CHROMIUM_PATH,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        context = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1920, 'height': 1080},
        )

        for page_num in range(1, max_pages + 1):
            page = context.new_page()
            page.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}',
                      lambda route: route.abort())

            url = (
                'https://www.immoweb.be/en/search/house-and-apartment/for-rent/'
                f'liege/district?countries=BE&page={page_num}'
                '&orderBy=relevance&minBedroomCount=2&maxPrice=1300'
            )

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(5000)

                listings = page.evaluate("""() => {
                    const results = [];
                    const cards = document.querySelectorAll('[data-classified-id]');

                    for (const card of cards) {
                        try {
                            const item = {
                                external_id: card.getAttribute('data-classified-id') || '',
                                title: '',
                                price: 0,
                                bedrooms: 0,
                                surface_area: null,
                                address: '',
                                url: '',
                                image_url: '',
                                latitude: null,
                                longitude: null,
                                date_posted: '',
                                description: '',
                            };

                            // URL
                            const link = card.querySelector('a[href*=\"/classified/\"]');
                            if (link) {
                                item.url = link.href;
                                const titleEl = link.querySelector('[class*=\"title\"]');
                                if (titleEl) item.title = titleEl.innerText.trim();
                            }

                            // Price
                            const priceEl = card.querySelector('[class*=\"price\"], [class*=\"Price\"]');
                            if (priceEl) {
                                const text = priceEl.innerText.trim();
                                const match = text.match(/([0-9]+[0-9.,]*)/);
                                if (match) item.price = parseInt(match[1].replace(/[.,]/g, ''));
                            }

                            // Bedrooms
                            const bedEl = card.querySelector('[class*=\"bedroom\"], [class*=\"Bedroom\"], [class*=\"bed\"]');
                            if (bedEl) {
                                const text = bedEl.innerText.trim();
                                const match = text.match(/(\\d+)/);
                                if (match) item.bedrooms = parseInt(match[1]);
                            }

                            // Surface
                            const surfEl = card.querySelector('[class*=\"surface\"], [class*=\"Surface\"]');
                            if (surfEl) {
                                const text = surfEl.innerText.trim();
                                const match = text.match(/(\\d+)/);
                                if (match) item.surface_area = parseFloat(match[1]);
                            }

                            // Address / location
                            const locEl = card.querySelector('[class*=\"location\"], [class*=\"Location\"]');
                            if (locEl) {
                                item.address = locEl.innerText.trim();
                            }

                            // Image
                            const img = card.querySelector('img[class*=\"image\"], img[class*=\"Image\"]');
                            if (img) {
                                item.image_url = img.getAttribute('src') || img.getAttribute('data-src') || '';
                            }

                            // Date
                            const dateEl = card.querySelector('[class*=\"date\"], [class*=\"Date\"], time');
                            if (dateEl) {
                                item.date_posted = dateEl.getAttribute('datetime') || dateEl.innerText.trim();
                            }

                            // Coordinates from data attributes
                            const lat = card.getAttribute('data-lat') || card.getAttribute('data-latitude');
                            const lng = card.getAttribute('data-lng') || card.getAttribute('data-longitude') || card.getAttribute('data-lon');
                            if (lat && lng) {
                                item.latitude = parseFloat(lat);
                                item.longitude = parseFloat(lng);
                            }

                            // Description
                            const descEl = card.querySelector('[class*=\"description\"], [class*=\"Description\"]');
                            if (descEl) {
                                item.description = descEl.innerText.trim();
                            }

                            // Title fallback
                            if (!item.title) {
                                const allText = card.innerText;
                                const lines = allText.split('\\n').filter(l => l.trim());
                                if (lines.length > 2) item.title = lines[2].trim();
                            }

                            results.push(item);
                        } catch(e) {
                            console.error('Error parsing card:', e);
                        }
                    }

                    return results;
                }""")

                print(f'Page {page_num}: Found {len(listings)} listings')

                for listing in listings:
                    if listing.get('price', 0) <= 1300 and listing.get('bedrooms', 0) >= 1:
                        all_listings.append(listing)

            except Exception as e:
                print(f'Error on page {page_num}: {e}')

            page.close()

        browser.close()

    # Calculate distances to Guillemins
    for listing in all_listings:
        if listing.get('latitude') and listing.get('longitude'):
            listing['distance_to_station'] = haversine_distance(
                GUILLEMINS_LAT, GUILLEMINS_LON,
                listing['latitude'], listing['longitude']
            )
        listing['source'] = 'immoweb'

    return all_listings


if __name__ == '__main__':
    listings = extract_listings(max_pages=2)
    print(f'\nTotal listings: {len(listings)}')
    print(f'Listings near Guillemins (<800m): {sum(1 for l in listings if l.get("distance_to_station") and l["distance_to_station"] < 800)}')
    for l in listings[:5]:
        dist = l.get('distance_to_station', '?')
        if dist and dist < 1000:
            print(f'  {l["title"]}: €{l["price"]} ({l["bedrooms"]} beds, {l["address"]}, {dist:.0f}m)')
