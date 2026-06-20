# Configuration for Liege House Search app

# Coordinates of Liège-Guillemins station (main entrance / Google Maps pin)
GUILLEMINS_LAT = 50.624433
GUILLEMINS_LON = 5.566708

# Radius for "walking distance" (10 minutes ≈ 800m)
MAX_WALK_DISTANCE_METERS = 800

# Search parameters (from user's Immoweb map filter)
MAX_PRICE = 1200
MIN_BEDROOMS = 2
MIN_SURFACE = 80
CITY = "Liège"
COUNTRY = "BE"

# Map area filter (polygon drawn by user around Guillemins)
GEO_SEARCH_AREAS = "y}_tHsf|`@?cfCtiA??bfC"

# Immoweb search URL with map area
IMMOWEB_MAP_SEARCH_URL = (
    "https://www.immoweb.be/en/search?"
    "propertyTypes=HOUSE,APARTMENT"
    "&transactionTypes=FOR_RENT"
    "&priceType=MONTHLY_RENTAL_PRICE"
    "&minBedroomCount={min_bedrooms}"
    "&maxPrice={max_price}"
    "&minPrice=800"
    "&minSurface=80"
    "&countries=BE"
    "&geoSearchAreas={geo_areas}"
    "&orderBy=newest"
)

# Request headers to mimic a real browser (used only for testing)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,nl;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


# Database path
DATABASE_PATH = "data/listings.db"
