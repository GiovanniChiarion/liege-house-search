"""Test Playwright scraping of Immoweb"""
from playwright.sync_api import sync_playwright
import os
import json

chromium_path = os.path.expanduser(
    '~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=chromium_path,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-dev-shm-usage',
        ],
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
    page.wait_for_timeout(5000)

    # Extract data using JavaScript evaluation
    results = page.evaluate("""() => {
        const info = [];

        // Check script tags
        const scripts = document.querySelectorAll('script');
        for (const script of scripts) {
            const text = script.textContent || '';
            if (text.includes('__INITIAL_STATE__')) {
                info.push({ source: 'INITIAL_STATE', has: true });
            }
            if (script.type === 'application/ld+json') {
                try {
                    info.push({ source: 'ld+json', data: JSON.parse(text) });
                } catch(e) {}
            }
        }

        // Check window
        info.push({ source: 'windowKeys', data: Object.keys(window).filter(k =>
            k.toLowerCase().includes('search') ||
            k.toLowerCase().includes('result') ||
            k.toLowerCase().includes('classified') ||
            k.toLowerCase().includes('listing') ||
            k.toLowerCase().includes('property')
        ) });

        // Find listing cards
        const listingCards = document.querySelectorAll('[data-classified-id], [id*=\"classified\"], [class*=\"classified\"]');
        info.push({ source: 'classifiedElements', count: listingCards.length });

        // Get all text to understand structure
        const main = document.querySelector('main, [role=\"main\"], #main-content');
        if (main) {
            const text = main.innerText;
            info.push({ source: 'mainText', preview: text.substring(0, 2000) });
        }

        // Check data layers
        if (window.dataLayer) {
            info.push({ source: 'dataLayer', data: window.dataLayer.slice(0, 5) });
        }

        return info;
    }""")

    for r in results:
        source = r.get('source', '?')
        if 'data' in r:
            data = r['data']
            if isinstance(data, str):
                print(f'{source}: {data[:200]}')
            elif isinstance(data, list):
                print(f'{source}: list ({len(data)} items)')
                if data and isinstance(data[0], dict):
                    print(f'  First: {json.dumps(data[0], indent=2)[:300]}')
                else:
                    print(f'  Items: {data[:5]}')
            elif isinstance(data, dict):
                print(f'{source}: dict ({json.dumps(data, indent=2)[:300]})')
        elif 'count' in r:
            print(f'{source}: count={r["count"]}')
        elif 'has' in r:
            print(f'{source}: {r["has"]}')
        else:
            print(f'{source}: {r}')

    browser.close()
