"""Test extraction of Immoweb listings with Playwright"""
import os, json, re, math
from playwright.sync_api import sync_playwright

CHROMIUM_PATH = os.path.expanduser('~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')
GUILLEMINS_LAT = 50.6243
GUILLEMINS_LON = 5.5665

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def extract_coords_from_page(page, url):
    """Extract coordinates from a listing detail page."""
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(3000)
        
        coords = page.evaluate("""() => {
            // Try JSON-LD
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const data = JSON.parse(s.textContent);
                    if (data.geo) {
                        return { lat: parseFloat(data.geo.latitude), lng: parseFloat(data.geo.longitude) };
                    }
                } catch(e) {}
            }
            // Try meta tags
            const metaLat = document.querySelector('meta[property="place:location:latitude"]');
            const metaLng = document.querySelector('meta[property="place:location:longitude"]');
            if (metaLat && metaLng) {
                return { lat: parseFloat(metaLat.content), lng: parseFloat(metaLng.content) };
            }
            // Try window.__NUXT__
            try {
                const nuxt = window.__NUXT__;
                if (nuxt && nuxt.state && nuxt.state.classified) {
                    const c = nuxt.state.classified;
                    if (c.property && c.property.location) {
                        return { lat: c.property.location.latitude, lng: c.property.location.longitude };
                    }
                }
            } catch(e) {}
            return null;
        }""")
        return coords
    except Exception as e:
        print(f"  Error getting coords: {e}")
        return None

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=CHROMIUM_PATH,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'],
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
    )
    
    # First get listing URLs from search pages
    all_listings = []
    
    for page_num in range(1, 4):  # First 3 pages
        page = context.new_page()
        page.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}', lambda route: route.abort())
        
        search_url = (
            'https://www.immoweb.be/en/search/house-and-apartment/for-rent/liege/district?'
            f'countries=BE&page={page_num}&orderBy=relevance&minBedroomCount=2&maxPrice=1300'
        )
        
        try:
            page.goto(search_url, wait_until='networkidle', timeout=20000)
            page.wait_for_timeout(3000)
            
            listings = page.evaluate("""() => {
                const articles = document.querySelectorAll('article.card--result');
                return Array.from(articles).map(a => {
                    const id = (a.id || '').replace('classified_', '');
                    const link = a.querySelector('a');
                    const url = link ? link.href : '';
                    const text = a.textContent || '';
                    
                    // Price: take the first number after €
                    let price = 0;
                    const m = text.match(/[€]\\s*([0-9,.]+)/);
                    if (m) price = parseInt(m[1].replace(/,/g, ''));
                    
                    // Bedrooms
                    let bedrooms = 0;
                    const bm = text.match(/(\\d+)\\s*bdr/);
                    if (bm) bedrooms = parseInt(bm[1]);
                    
                    // Surface
                    let surface = null;
                    const sm = text.match(/(\\d+)\\s*m²/);
                    if (sm) surface = parseFloat(sm[1]);
                    
                    // Address (postal code + city)
                    let address = '';
                    const am = text.match(/(\\d{4})\\s+([A-Za-zÀ-ÿ \\-]+)/);
                    if (am) address = am[0].trim();
                    
                    // Title - find the longest non-empty meaningful line
                    let title = '';
                    const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    for (const line of lines) {
                        if (line.length > 10 && !line.includes('€') && !line.includes('bdr') && !line.includes('m²') && !line.match(/^\\d{4}/)) {
                            title = line;
                            break;
                        }
                    }
                    if (!title) {
                        if (text.includes('House')) title = 'House';
                        else if (text.includes('Apartment')) title = 'Apartment';
                        else title = 'Property';
                    }
                    
                    // Date posted - check for "new" flag
                    const isNew = !!a.querySelector('.flag-list__item--new');
                    
                    return {
                        external_id: id,
                        url: url,
                        price: price,
                        bedrooms: bedrooms,
                        surface_area: surface,
                        address: address,
                        title: title.substring(0, 100),
                        is_new: isNew,
                    };
                });
            }""")
            
            print(f"Page {page_num}: Found {len(listings)} listings")
            for l in listings:
                print(f"  {l['external_id']}: €{l['price']} {l['bedrooms']}bdr {l['surface_area']}m² {l['address']} new={l['is_new']}")
            
            all_listings.extend(listings)
            
        except Exception as e:
            print(f"Error on page {page_num}: {e}")
        
        page.close()
    
    print(f"\nTotal listings from search: {len(all_listings)}")
    
    # Now get coordinates for each listing
    print("\n=== Getting coordinates ===")
    for i, listing in enumerate(all_listings):
        if not listing['url']:
            continue
        
        print(f"[{i+1}/{len(all_listings)}] {listing['external_id']}: {listing['title'][:40]}")
        page = context.new_page()
        page.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}', lambda route: route.abort())
        
        coords = extract_coords_from_page(page, listing['url'])
        if coords:
            listing['latitude'] = coords['lat']
            listing['longitude'] = coords['lng']
            dist = haversine(GUILLEMINS_LAT, GUILLEMINS_LON, coords['lat'], coords['lng'])
            listing['distance_to_station'] = round(dist, 1)
            print(f"    Lat={coords['lat']:.4f} Lng={coords['lng']:.4f} Dist={dist:.0f}m {'✓' if dist <= 800 else '✗'}")
        else:
            print(f"    No coordinates found")
        
        page.close()
    
    # Results
    print("\n=== Results ===")
    near = [l for l in all_listings if l.get('distance_to_station') and l['distance_to_station'] <= 800]
    print(f"Listings within 800m of Guillemins: {len(near)}")
    for l in near:
        print(f"  €{l['price']} - {l['bedrooms']}bdr - {l['address']} - {l['distance_to_station']:.0f}m - {l['url']}")
    
    # Save to JSON
    with open('data/scraped_listings.json', 'w') as f:
        json.dump(all_listings, f, indent=2, default=str)
    print(f"\nSaved {len(all_listings)} listings to data/scraped_listings.json")
    
    browser.close()
