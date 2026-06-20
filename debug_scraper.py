"""Debug: Find how listing data is structured on Immoweb"""
from playwright.sync_api import sync_playwright
import os

CHROMIUM_PATH = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
)

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
    page = context.new_page()
    page.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}', lambda route: route.abort())

    page.goto(
        'https://www.immoweb.be/en/search/house-and-apartment/for-rent/liege/district?'
        'countries=BE&page=1&orderBy=relevance&minBedroomCount=2&maxPrice=1300',
        wait_until='domcontentloaded',
        timeout=15000,
    )
    page.wait_for_timeout(8000)

    # Debug: find all elements and their attributes
    debug_info = page.evaluate("""() => {
        const info = [];

        // Check all elements with data- attributes
        const allElements = document.querySelectorAll('*');
        const dataElements = [];
        for (const el of allElements) {
            if (el.hasAttribute('data-classified-id') || el.hasAttribute('data-id') || el.hasAttribute('data-listing')) {
                dataElements.push({
                    tag: el.tagName,
                    id: el.id,
                    classes: el.className,
                    dataAttrs: Object.keys(el.dataset).join(', '),
                    innerLength: el.innerText.length,
                });
            }
        }
        info.push({source: 'data-elements', data: dataElements.slice(0, 20)});

        // Check what's in the main content area
        const mainAreas = document.querySelectorAll('[class*=\"result\"], [class*=\"search\"], [class*=\"list\"], main, section');
        info.push({source: 'main-areas', count: mainAreas.length, 
                    classes: Array.from(mainAreas).slice(0, 10).map(el => ({
                        tag: el.tagName,
                        id: el.id,
                        classes: el.className.substring(0, 100),
                        childCount: el.children.length,
                    }))
        });

        // Check the full HTML of the body (first 5000 chars)
        const bodyHtml = document.body.innerHTML;
        // Find where listing data might be
        const listingMarkers = ['classified', 'data-id', 'data-classified', 'search-result', 'card'];
        const positions = [];
        for (const marker of listingMarkers) {
            let idx = bodyHtml.indexOf(marker);
            if (idx >= 0) {
                positions.push({
                    marker,
                    index: idx,
                    context: bodyHtml.substring(Math.max(0, idx-50), idx + 150)
                });
            }
        }
        info.push({source: 'marker-positions', data: positions.slice(0, 20)});

        return info;
    }""")

    for r in debug_info:
        source = r.get('source', '?')
        print(f'\n=== {source} ===')
        if 'data' in r:
            data = r['data']
            if isinstance(data, list):
                for item in data[:10]:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            print(f'  {k}: {str(v)[:150]}')
                        print()
                    else:
                        print(f'  {item}')
            elif isinstance(data, str):
                print(data[:1000])
            else:
                print(str(data)[:1000])
        if 'count' in r:
            print(f'  Count: {r["count"]}')

    browser.close()
