"""Debug: Inspect listing elements structure"""
from playwright.sync_api import sync_playwright
import os, json

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

    # Inspect article elements
    articles = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('article')).slice(0, 3).map(a => {
            const info = {};
            info.id = a.id || '';
            info.className = (typeof a.className === 'string' ? a.className : '') || '';
            info.dataAttrs = Object.keys(a.dataset).join(', ');
            info.childCount = a.children.length;
            info.firstChild = a.children[0] ? a.children[0].tagName : '';
            info.html = a.innerHTML.substring(0, 2000);
            return info;
        });
    }""")
    
    print('=== Article elements ===')
    for a in articles:
        for k, v in a.items():
            print(f'  {k}: {str(v)[:200]}')
        print()

    # Look for search-result elements
    print('=== search-result elements ===')
    srs = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('[class*=\"search-result\"]')).slice(0, 2).map(el => {
            const info = {};
            info.tag = el.tagName;
            info.className = (typeof el.className === 'string' ? el.className : '') || '';
            info.dataAttrs = Object.keys(el.dataset).join(', ');
            info.html = el.innerHTML.substring(0, 1500);
            return info;
        });
    }""")
    for sr in srs:
        for k, v in sr.items():
            print(f'  {k}: {str(v)[:300]}')
        print()

    # Look for any JSON data
    print('=== JSON scripts ===')
    json_scripts = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('script[type=\"application/json\"], script[type=\"application/ld+json\"], script#__NEXT_DATA__'))
            .map(s => ({
                id: s.id || '',
                type: s.type || '',
                textLength: (s.textContent || '').length,
                preview: (s.textContent || '').substring(0, 500),
            }));
    }""")
    for js in json_scripts:
        print(f'  ID: {js["id"]}, Type: {js["type"]}, Length: {js["textLength"]}')
        print(f'  Preview: {js["preview"][:300]}')
        print()

    # Check the main page structure
    print('=== Page structure (first 5000 chars of body) ===')
    body_html = page.evaluate("""() => {
        return document.body.innerHTML.substring(0, 5000);
    }""")
    print(body_html)
    
    browser.close()
