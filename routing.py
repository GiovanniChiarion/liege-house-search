"""
Walking distance & route visualization using OSRM (Open Source Routing Machine).
Free, no API key required. Uses the foot/walking profile.
"""
import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

# Use routing.openstreetmap.de which has dedicated foot/bike routing profiles
OSRM_BASE = "https://routing.openstreetmap.de/routed-foot"

# Cache for routes to avoid hitting the API too often
_route_cache = {}


def get_walking_route(start_lat, start_lon, end_lat, end_lon, retries=3):
    """
    Get walking route between two points using OSRM.
    
    Returns dict with:
      - distance: meters (float)
      - duration: seconds (float)
      - geometry: GeoJSON LineString coordinates [[lon,lat], ...]
      - steps: list of turn-by-turn instructions
    
    Returns None on error.
    """
    # Cache key
    cache_key = f"{start_lat:.5f},{start_lon:.5f};{end_lat:.5f},{end_lon:.5f}"
    if cache_key in _route_cache:
        logger.debug(f"Route cache hit: {cache_key}")
        return _route_cache[cache_key]

    url = (
        f"{OSRM_BASE}/route/v1/foot/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        f"?overview=full&geometries=geojson&steps=true&alternatives=false"
    )

    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                # Rate limited, wait and retry
                wait = 2 ** attempt
                logger.warning(f"OSRM rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok" or not data.get("routes"):
                logger.warning(f"OSRM returned no route: {data.get('message', 'unknown')}")
                return None

            route = data["routes"][0]
            result = {
                "distance": route["distance"],      # meters
                "duration": route["duration"],      # seconds
                "geometry": route["geometry"],       # GeoJSON
                "steps": route.get("legs", [{}])[0].get("steps", []),
            }

            # Cache
            _route_cache[cache_key] = result
            logger.info(f"Walking route: {result['distance']:.0f}m, {result['duration']/60:.1f}min")
            return result

        except requests.exceptions.Timeout:
            logger.warning(f"OSRM timeout (attempt {attempt+1}/{retries})")
            if attempt < retries - 1:
                time.sleep(1)
        except requests.exceptions.RequestException as e:
            logger.warning(f"OSRM error: {e}")
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return None

    return None


def update_listing_walking_distance(listing_id):
    """
    Compute walking distance from Guillemins station to a listing,
    update the DB, and return the result.
    """
    from models import get_listing, get_db
    from config import GUILLEMINS_LAT, GUILLEMINS_LON

    listing = get_listing(listing_id)
    if not listing:
        return None

    lat, lon = listing.get("latitude"), listing.get("longitude")
    if not lat or not lon:
        return None

    route = get_walking_route(GUILLEMINS_LAT, GUILLEMINS_LON, lat, lon)
    if not route:
        return None

    # Save to DB
    db = get_db()
    db.execute(
        "UPDATE listings SET walking_distance = ?, walking_route = ?, last_checked = datetime('now') WHERE id = ?",
        (int(round(route["distance"])), json.dumps(route["geometry"]), listing_id)
    )
    db.commit()
    db.close()

    route["listing_id"] = listing_id
    return route


def batch_update_walking_distances(limit=None):
    """
    Update walking distances for all listings that don't have one yet.
    Returns (updated_count, total_count).
    """
    from models import get_db
    from config import GUILLEMINS_LAT, GUILLEMINS_LON

    db = get_db()
    if limit:
        rows = db.execute(
            "SELECT id, latitude, longitude FROM listings WHERE (walking_distance IS NULL OR walking_distance = 0) AND latitude IS NOT NULL AND longitude IS NOT NULL LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, latitude, longitude FROM listings WHERE (walking_distance IS NULL OR walking_distance = 0) AND latitude IS NOT NULL AND longitude IS NOT NULL"
        ).fetchall()
    db.close()

    total = len(rows)
    updated = 0
    for i, row in enumerate(rows):
        logger.info(f"[{i+1}/{total}] Getting walking distance for listing {row['id']}...")
        route = get_walking_route(GUILLEMINS_LAT, GUILLEMINS_LON, row["latitude"], row["longitude"])
        if route:
            db = get_db()
            db.execute(
                "UPDATE listings SET walking_distance = ?, walking_route = ? WHERE id = ?",
                (int(round(route["distance"])), json.dumps(route["geometry"]), row["id"])
            )
            db.commit()
            db.close()
            updated += 1
            logger.info(f"  → {route['distance']:.0f}m walk")
        time.sleep(0.5)  # Be nice to the API

    return updated, total
