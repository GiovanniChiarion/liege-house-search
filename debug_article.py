"""Debug: Get full HTML of one article element"""
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
        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
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

    # Get the full outer HTML of the first article
    html = page.evaluate("""() => {
        const article = document.querySelector('article.card--result');
        return article ? article.outerHTML : 'No article found';
    }""")
    print(html)
    
    browser.close()
