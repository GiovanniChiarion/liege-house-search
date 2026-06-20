"""
Immoweb scraper for rental listings in Liège, Belgium.

This module fetches listings from Immoweb's search results and parses
the listing data from the HTML or embedded JSON data.
"""
import json
import logging
import re
import time
import math
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    IMMOWEB_SEARCH_URL,
    HEADERS,
    GUILLEMINS_LAT,
    GUILLEMINS_LON,
    MAX_WALK_DISTANCE_METERS,
)

logger = logging.getLogger(__name__)


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def extract_listing_id(url):
    """Extract listing ID from an Immoweb URL."""
    # URL pattern: https://www.immoweb.be/en/classified/...
    # or https://www.immoweb.be/en/classified/<id>
    match = re.search(r'/classified/([^/?]+)', url)
    if match:
        return match.group(1)
    # Try to find numeric ID
    match = re.search(r'/(\d{7,})', url)
    if match:
        return match.group(1)
    return None


def parse_listing_card(card):
    """Parse a single listing card from the search results page."""
    try:
        listing = {}

        # URL and external ID
        link = card.select_one('a.card__title-link')
        if not link:
            # Try alternative selectors
            link = card.select_one('a[href*="/classified/"]')
        if link:
            url = urljoin('https://www.immoweb.be', link.get('href', ''))
            listing['url'] = url
            listing['external_id'] = extract_listing_id(url)
        else:
            # Try to find the listing from data attributes
            data_id = card.get('data-id') or card.get('id')
            if data_id:
                listing['external_id'] = str(data_id)
                listing['url'] = f"https://www.immoweb.be/en/classified/{data_id}"

        # Title
        title_elem = card.select_one('.card__title')
        if title_elem:
            listing['title'] = title_elem.get_text(strip=True)
        elif link:
            listing['title'] = link.get_text(strip=True)

        if not listing.get('title'):
            listing['title'] = 'Appartement à louer'

        # Price
        price_elem = card.select_one('.card__price')
        if not price_elem:
            price_elem = card.select_one('[class*="price"]')
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_match = re.search(r'(\d[\d.]*)', price_text.replace(' ', ''))
            if price_match:
                listing['price'] = int(price_match.group(1).replace('.', ''))

        # Bedrooms
        bedrooms_elem = card.select_one('[class*="bedroom"]')
        if not bedrooms_elem:
            bedrooms_elem = card.select_one('[class*="bed"]')
        if bedrooms_elem:
            bed_text = bedrooms_elem.get_text(strip=True)
            bed_match = re.search(r'(\d+)', bed_text)
            if bed_match:
                listing['bedrooms'] = int(bed_match.group(1))
        else:
            # Try from the title
            title = listing.get('title', '')
            bed_match = re.search(r'(\d+)\s*(bedroom|chambre|slaapkamer)', title, re.IGNORECASE)
            if bed_match:
                listing['bedrooms'] = int(bed_match.group(1))

        # Surface area
        surface_elem = card.select_one('[class*="surface"]')
        if surface_elem:
            surface_text = surface_elem.get_text(strip=True)
            surface_match = re.search(r'(\d+)', surface_text)
            if surface_match:
                listing['surface_area'] = float(surface_match.group(1))

        # Address / location
        location_elem = card.select_one('.card__location')
        if location_elem:
            listing['address'] = location_elem.get_text(strip=True)

        # Image
        img_elem = card.select_one('img.card__image')
        if img_elem:
            listing['image_url'] = img_elem.get('src') or img_elem.get('data-src')

        # Date posted - often in a data attribute
        date_elem = card.select_one('[class*="date"]')
        if date_elem:
            listing['date_posted'] = date_elem.get_text(strip=True)

        # Try to find JSON-LD data in the card
        json_script = card.select_one('script[type="application/ld+json"]')
        if json_script:
            try:
                data = json.loads(json_script.string)
                if isinstance(data, dict):
                    if not listing.get('latitude') and 'geo' in data:
                        geo = data['geo']
                        listing['latitude'] = float(geo.get('latitude', 0))
                        listing['longitude'] = float(geo.get('longitude', 0))
                    if not listing.get('price') and 'offers' in data:
                        offers = data['offers']
                        if isinstance(offers, dict) and 'price' in offers:
                            listing['price'] = int(float(offers['price']))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # Try to extract coordinates from data attributes
        for attr in ['data-lat', 'data-latitude', 'data-lat', 'latitude']:
            val = card.get(attr)
            if val:
                try:
                    listing['latitude'] = float(val)
                except (ValueError, TypeError):
                    pass
                break

        for attr in ['data-lon', 'data-longitude', 'data-lng', 'longitude']:
            val = card.get(attr)
            if val:
                try:
                    listing['longitude'] = float(val)
                except (ValueError, TypeError):
                    pass
                break

        # If no external_id but we have a URL, generate one from URL
        if not listing.get('external_id') and listing.get('url'):
            listing['external_id'] = extract_listing_id(listing['url'])

        # Calculate distance to Guillemins station
        if listing.get('latitude') and listing.get('longitude'):
            listing['distance_to_station'] = haversine_distance(
                GUILLEMINS_LAT, GUILLEMINS_LON,
                listing['latitude'], listing['longitude']
            )

        listing['source'] = 'immoweb'

        return listing

    except Exception as e:
        logger.warning(f"Error parsing listing card: {e}")
        return None


def scrape_immoweb_page(page=1):
    """Scrape a single page of Immoweb search results."""
    url = IMMOWEB_SEARCH_URL.format(
        page=page,
        min_bedrooms=2,
        max_price=1300,
    )

    logger.info(f"Fetching page {page}: {url}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error fetching page {page}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'lxml')
    listings = []

    # Try multiple selectors for listing cards
    cards = soup.select('.card, [class*="listing"], [class*="result"], article, .search-results__item')

    if not cards:
        # Try to find any element with listing data
        cards = soup.select('[data-id], [class*="classified"]')

    if not cards:
        # Look for JSON data embedded in the page
        json_data = extract_json_from_page(soup)
        if json_data:
            return parse_json_listings(json_data)

    for card in cards:
        listing = parse_listing_card(card)
        if listing and listing.get('price'):
            if listing.get('price') <= 1300:
                listings.append(listing)

    logger.info(f"Found {len(listings)} listings on page {page}")
    return listings


def extract_json_from_page(soup):
    """Try to extract listing data from JSON embedded in the page."""
    # Look for window.__INITIAL_STATE__ or similar
    scripts = soup.select('script')
    for script in scripts:
        if not script.string:
            continue
        text = script.string

        # Try __INITIAL_STATE__
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Try __NEXT_DATA__ (Next.js)
        if 'id="__NEXT_DATA__"' in str(script) or '__NEXT_DATA__' in text:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass

        # Try dataLayer
        match = re.search(r'dataLayer\.push\(({.*?})\)', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

    # Try JSON-LD scripts
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                return data
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def parse_json_listings(data):
    """Parse listing data from embedded JSON."""
    listings = []

    # Try to find listings array in various possible paths
    def find_listings(obj, depth=0):
        if depth > 5:
            return []
        results = []
        if isinstance(obj, dict):
            # Check if this object looks like a listing
            if obj.get('price') and (obj.get('url') or obj.get('id')):
                results.append(obj)
            # Search recursively
            for value in obj.values():
                results.extend(find_listings(value, depth + 1))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(find_listings(item, depth + 1))
        return results

    found = find_listings(data)
    for item in found:
        try:
            listing = {
                'external_id': str(item.get('id', item.get('externalId', ''))),
                'title': item.get('title', 'Appartement à louer'),
                'price': int(float(item.get('price', item.get('mainPrice', 0)))),
                'bedrooms': item.get('bedroomCount', item.get('bedrooms')),
                'surface_area': item.get('livingArea', item.get('surface', item.get('netSurface'))),
                'address': item.get('location', item.get('address', item.get('street'))),
                'latitude': item.get('latitude', item.get('lat')),
                'longitude': item.get('longitude', item.get('lng', item.get('lon'))),
                'url': item.get('url', f"https://www.immoweb.be/en/classified/{item.get('id')}"),
                'image_url': item.get('picture', item.get('image', item.get('mainPicture'))),
                'date_posted': item.get('publicationDate', item.get('date', item.get('creationDate'))),
                'source': 'immoweb',
            }

            # Clean up
            if isinstance(listing['image_url'], dict):
                listing['image_url'] = listing['image_url'].get('url', listing['image_url'].get('src'))

            # Calculate distance
            if listing.get('latitude') and listing.get('longitude'):
                listing['distance_to_station'] = haversine_distance(
                    GUILLEMINS_LAT, GUILLEMINS_LON,
                    float(listing['latitude']), float(listing['longitude'])
                )

            if listing.get('price') and listing['price'] <= 1300:
                listings.append(listing)

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Error parsing JSON listing: {e}")
            continue

    return listings


def get_listing_details(url):
    """Fetch detailed information for a single listing."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error fetching listing details: {e}")
        return {}

    soup = BeautifulSoup(response.text, 'lxml')
    details = {}

    # Try to find JSON-LD
    json_script = soup.select_one('script[type="application/ld+json"]')
    if json_script:
        try:
            data = json.loads(json_script.string)
            if isinstance(data, dict):
                geo = data.get('geo', {})
                if geo:
                    details['latitude'] = float(geo.get('latitude', 0))
                    details['longitude'] = float(geo.get('longitude', 0))
                offers = data.get('offers', {})
                if isinstance(offers, dict) and offers.get('price'):
                    details['price'] = int(float(offers['price']))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Find description
    desc_elem = soup.select_one('.description, [class*="description"]')
    if desc_elem:
        details['description'] = desc_elem.get_text(strip=True)

    # Find date posted
    date_elem = soup.select_one('[class*="date"], [class*="publication"], time')
    if date_elem:
        details['date_posted'] = date_elem.get_text(strip=True)
        # Also check datetime attribute
        if date_elem.get('datetime'):
            details['date_posted'] = date_elem['datetime']

    # Calculate distance if we have coordinates
    if details.get('latitude') and details.get('longitude'):
        details['distance_to_station'] = haversine_distance(
            GUILLEMINS_LAT, GUILLEMINS_LON,
            details['latitude'], details['longitude']
        )

    return details


def scrape_all_pages(max_pages=5):
    """Scrape multiple pages of listings."""
    all_listings = []

    for page in range(1, max_pages + 1):
        listings = scrape_immoweb_page(page)
        if not listings:
            logger.info(f"No more listings found after page {page - 1}")
            break
        all_listings.extend(listings)
        time.sleep(1.5)  # Be respectful to the server

    logger.info(f"Total listings scraped: {len(all_listings)}")
    return all_listings


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    listings = scrape_all_pages(max_pages=3)
    print(f"Found {len(listings)} listings")
    for l in listings[:5]:
        print(f"  - {l.get('title')}: €{l.get('price')} ({l.get('bedrooms')} beds)")
