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

    # Simple debug: dump key parts of the page
    # 1. Count elements by tag
    tag_counts = page.evaluate("""() => {
        const tags = {};
        document.querySelectorAll('*').forEach(el => {
            const tag = el.tagName;
            tags[tag] = (tags[tag] || 0) + 1;
        });
        return tags;
    }""")
    print('Tag counts:')
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:30]:
        print(f'  {tag}: {count}')

    # 2. Look for listing-related elements
    listing_selectors = [
        'article', '[class*=classified]', '[class*=search-result]', 
        '[class*=result]', '[class*=card]', '[class*=property]',
        '[class*=listing]', '[data-id]', '[data-classified]',
        'li[class*=result]', 'div[class*=result]', 'a[href*="/classified/"]',
        'section[class*=result]', '[role=listitem]', '[role=article]',
    ]
    print('\nSelector counts:')
    for sel in listing_selectors:
        count = page.evaluate(f'document.querySelectorAll("{sel}").length')
        if count > 0:
            print(f'  {sel}: {count}')

    # 3. Get all links to classifieds
    links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href*="/classified/"]'))
            .slice(0, 5)
            .map(a => ({
                href: a.href,
                text: a.innerText.trim().substring(0, 80),
                parentTag: a.parentElement.tagName,
                parentClass: (a.parentElement.className || '').toString().substring(0, 80),
            }));
    }""")
    print('\nFirst 5 classified links:')
    for l in links:
        print(f'  {l["href"]}')
        print(f'  text: {l["text"]}')
        print(f'  parent: {l["parentTag"]}.{l["parentClass"]}')
        print()

    browser.close()
