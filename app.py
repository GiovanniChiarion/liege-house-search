#!/usr/bin/env python3
"""
Liege House Search - Flask web application for finding rental houses
near Liège-Guillemins station.
"""
import json
import logging
import os
import threading
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from functools import wraps
from flask_cors import CORS

from config import GUILLEMINS_LAT, GUILLEMINS_LON, MAX_WALK_DISTANCE_METERS
from models import init_db, get_all_listings, get_listing, \
    add_listing, update_listing_status, delete_listing, get_stats, \
    bulk_update_status, authenticate_user, get_user

# Scrape state tracker
_scrape_lock = threading.Lock()
_scrape_state = {
    'status': 'idle',
    'found': 0,
    'new': 0,
    'processed': 0,
    'error': None,
    'started_at': None,
    'finished_at': None,
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
CORS(app)

# Initialize database
init_db()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = authenticate_user(email, password)
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name'] or email.split('@')[0]
            flash('Login effettuato!', 'success')
            return redirect(url_for('index'))
        flash('Email o password errati', 'error')
        return render_template('login.html')
    return render_template('login.html')




@app.route('/logout')
def logout():
    session.clear()
    flash('Logout effettuato', 'info')
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """Serve the main application page."""
    return render_template('index.html',
                         guillemins_lat=GUILLEMINS_LAT,
                         guillemins_lon=GUILLEMINS_LON)


@app.route('/api/listings')
@login_required
def api_listings():
    """Get all listings with optional filters."""
    filters = {}
    if request.args.get('max_price'):
        filters['max_price'] = int(request.args['max_price'])
    if request.args.get('min_bedrooms'):
        filters['min_bedrooms'] = int(request.args['min_bedrooms'])
    if request.args.get('max_distance'):
        filters['max_distance'] = float(request.args['max_distance'])

    show_viewed = request.args.get('show_viewed', 'true').lower() == 'true'
    show_unavailable = request.args.get('show_unavailable', 'true').lower() == 'true'
    show_excluded = request.args.get('show_excluded', 'true').lower() == 'true'
    filters['show_viewed'] = show_viewed
    filters['show_unavailable'] = show_unavailable
    filters['show_excluded'] = show_excluded

    # By default hide unavailable
    if 'show_unavailable' not in request.args:
        filters['show_unavailable'] = False

    listings = get_all_listings(filters)

    # Format dates for JSON
    for listing in listings:
        for key in ['date_discovered', 'date_posted', 'last_checked']:
            if listing.get(key):
                try:
                    dt = datetime.fromisoformat(listing[key])
                    listing[key] = dt.isoformat()
                except (ValueError, TypeError):
                    pass

    return jsonify(listings)


@app.route('/api/listings/<int:listing_id>')
@login_required
def api_get_listing(listing_id):
    """Get a single listing."""
    listing = get_listing(listing_id)
    if listing is None:
        return jsonify({'error': 'Listing not found'}), 404
    return jsonify(listing)


@app.route('/api/listings', methods=['POST'])
@login_required
def api_add_listing():
    """Add a new listing manually."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required = ['title', 'price']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        listing_id = add_listing(data)
        return jsonify({'id': listing_id, 'message': 'Listing added successfully'}), 201
    except Exception as e:
        logger.error(f"Error adding listing: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/<int:listing_id>/status', methods=['PATCH'])
@login_required
def api_update_status(listing_id):
    """Update listing status (viewed, unavailable, rented)."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    field = data.get('field')
    value = data.get('value', True)

    if not field:
        return jsonify({'error': 'No field specified'}), 400

    try:
        update_listing_status(listing_id, field, value)
        return jsonify({'message': 'Status updated successfully'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/bulk-status', methods=['POST'])
@login_required
def api_bulk_status():
    """Update a status field on multiple listings."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    ids = data.get('ids', [])
    field = data.get('field')
    value = data.get('value', True)

    if not ids or not isinstance(ids, list):
        return jsonify({'error': 'ids must be a non-empty array'}), 400
    if not field:
        return jsonify({'error': 'No field specified'}), 400

    try:
        bulk_update_status(ids, field, value)
        return jsonify({'message': f'Aggiornati {len(ids)} annunci'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error in bulk status update: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/<int:listing_id>/notes', methods=['PATCH'])
@login_required
def api_update_notes(listing_id):
    """Update notes for a listing."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    notes = data.get('notes', '')
    try:
        from models import get_db
        db = get_db()
        db.execute('UPDATE listings SET notes = ? WHERE id = ?', (notes, listing_id))
        db.commit()
        db.close()
        return jsonify({'message': 'Notes updated successfully'})
    except Exception as e:
        logger.error(f"Error updating notes: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/<int:listing_id>', methods=['DELETE'])
@login_required
def api_delete_listing(listing_id):
    """Delete a listing."""
    try:
        delete_listing(listing_id)
        return jsonify({'message': 'Listing deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting listing: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/<int:listing_id>/route')
@login_required
def api_listing_route(listing_id):
    """Get walking route for a listing.
    Returns GeoJSON route geometry from Guillemins station to the listing.
    """
    from routing import update_listing_walking_distance
    from models import get_listing

    # Check if we already have the route
    listing = get_listing(listing_id)
    if not listing:
        return jsonify({'error': 'Listing not found'}), 404

    if listing.get('walking_route'):
        # Return cached route
        try:
            geometry = json.loads(listing['walking_route'])
            return jsonify({
                'distance': listing['walking_distance'],
                'geometry': geometry,
                'cached': True,
            })
        except (json.JSONDecodeError, TypeError):
            pass

    # Compute new route
    route = update_listing_walking_distance(listing_id)
    if not route:
        return jsonify({'error': 'Could not compute walking route'}), 500

    return jsonify({
        'distance': route['distance'],
        'duration': route['duration'],
        'geometry': route['geometry'],
        'cached': False,
    })


@app.route('/api/routes/batch', methods=['POST'])
@login_required
def api_batch_routes():
    """Batch compute walking distances for listings that don't have one yet."""
    from routing import batch_update_walking_distances

    data = request.get_json() or {}
    limit = data.get('limit')

    def run_batch():
        updated, total = batch_update_walking_distances(limit=limit)
        logger.info(f"Batch routing complete: {updated}/{total} updated")

    thread = threading.Thread(target=run_batch, daemon=True)
    thread.start()

    return jsonify({'message': 'Batch walking distance computation started'}), 202


@app.route('/api/stats')
@login_required
def api_stats():
    """Get database statistics."""
    return jsonify(get_stats())


@app.route('/api/scrape', methods=['POST'])
@login_required
def api_scrape():
    """Trigger scraping of Immoweb listings.
    Only processes new listings not already in the database.
    """
    from scrape_map_area import scrape_map_search, enrich_with_details

    with _scrape_lock:
        if _scrape_state['status'] == 'running':
            return jsonify({'message': 'Scrape già in corso'}), 409
        _scrape_state['status'] = 'running'
        _scrape_state['found'] = 0
        _scrape_state['new'] = 0
        _scrape_state['processed'] = 0
        _scrape_state['error'] = None
        _scrape_state['started_at'] = datetime.now().isoformat()
        _scrape_state['finished_at'] = None

    data = request.get_json() or {}
    max_listings = data.get('max_listings', 50)

    def run_scrape():
        try:
            listings = scrape_map_search()
            with _scrape_lock:
                _scrape_state['found'] = len(listings)

            if listings:
                existing_ids = set()
                for l in get_all_listings():
                    if l.get('external_id'):
                        existing_ids.add(l['external_id'])

                new_listings = [l for l in listings if l['id'] not in existing_ids]

                with _scrape_lock:
                    _scrape_state['new'] = len(new_listings)

                if not new_listings:
                    logger.info("No new listings found")
                    with _scrape_lock:
                        _scrape_state['status'] = 'done'
                        _scrape_state['finished_at'] = datetime.now().isoformat()
                    return

                enrich_with_details(new_listings, max_listings=max_listings)
                count = 0
                for listing in new_listings:
                    if listing.get('latitude') and listing.get('longitude'):
                        data = {
                            'external_id': listing['id'],
                            'title': listing.get('title', 'Appartamento'),
                            'price': listing['price'],
                            'bedrooms': listing['bedrooms'],
                            'surface_area': listing.get('surface_area'),
                            'address': listing.get('full_address') or listing.get('address', ''),
                            'latitude': listing['latitude'],
                            'longitude': listing['longitude'],
                            'url': listing.get('url', ''),
                            'source': 'immoweb',
                            'image_url': listing.get('image_url', ''),
                            'date_posted': listing.get('date_posted', ''),
                            'distance_to_station': listing['distance_to_station'],
                        }
                        try:
                            add_listing(data)
                            count += 1
                        except Exception as e:
                            logger.warning(f"Error saving listing {listing.get('id')}: {e}")
                    with _scrape_lock:
                        _scrape_state['processed'] = count
                logger.info(f"Scrape complete: {count} new listings saved")
            else:
                logger.warning("No listings found from map search")

            with _scrape_lock:
                _scrape_state['status'] = 'done'
                _scrape_state['finished_at'] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            with _scrape_lock:
                _scrape_state['status'] = 'failed'
                _scrape_state['error'] = str(e)
                _scrape_state['finished_at'] = datetime.now().isoformat()

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()

    return jsonify({'message': 'Ricerca nuovi annunci su Immoweb avviata'}), 202


@app.route('/api/scrape/status', methods=['GET'])
@login_required
def api_scrape_status():
    """Get current scrape status for progress polling."""
    with _scrape_lock:
        return jsonify(dict(_scrape_state))


@app.route('/api/listings/import', methods=['POST'])
@login_required
def api_import_listings():
    """Bulk import listings from JSON array."""
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Expected a JSON array of listings'}), 400

    count = 0
    errors = []
    for item in data:
        try:
            add_listing(item)
            count += 1
        except Exception as e:
            errors.append({'listing': item.get('title', 'unknown'), 'error': str(e)})

    return jsonify({
        'message': f'Imported {count} listings',
        'errors': errors,
        'count': count,
    })


@app.route('/api/listings/import-by-url', methods=['POST'])
@login_required
def api_import_by_url():
    """Import a single listing from an Immoweb URL."""
    from playwright.sync_api import sync_playwright
    from scrape_map_area import make_browser, haversine_distance
    from db import get_db
    from config import GUILLEMINS_LAT, GUILLEMINS_LON

    data = request.get_json() or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'URL richiesto'}), 400

    if 'immoweb.be' not in url:
        return jsonify({'error': 'Inserisci un URL valido di Immoweb'}), 400

    import re
    match = re.search(r'/(\d{7,})', url)
    if not match:
        return jsonify({'error': 'ID annuncio non trovato nell\'URL'}), 400

    external_id = match.group(1)

    db = get_db()
    exists = db.execute("SELECT id FROM listings WHERE external_id = ?", (external_id,)).fetchone()
    db.close()
    if exists:
        return jsonify({'message': 'Annuncio già presente nel database'}), 200

    try:
        with sync_playwright() as p:
            browser = make_browser(p)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080},
            )
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(4000)

            detail = page.evaluate("""() => {
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    const t = s.textContent || '';
                    if (t.includes('window.classified')) {
                        try {
                            const match = t.match(/window\\.classified\\s*=\\s*(\\{[^;]+\\})/);
                            if (!match) return null;
                            const c = JSON.parse(match[1]);
                            const prop = c.property || {};
                            const loc = prop.location || {};
                            const pub = c.publication || {};
                            const media = c.media || [];
                            const price = c.price || {};
                            const trans = c.transaction || {};
                            const features = {};
                            if (prop.type) features.type = prop.type;
                            if (prop.subtype) features.subtype = prop.subtype;
                            if (loc.floor != null) features.floor = loc.floor;
                            if (prop.hasLift != null) features.lift = prop.hasLift;
                            if (prop.energy) {
                                features.energy = prop.energy.epcScore || prop.energy.primaryEnergyConsumptionPerSqm || null;
                            }
                            if (prop.hasTerrace != null) features.terrace = prop.hasTerrace;
                            if (prop.terraceSurface) features.terrace_surface = prop.terraceSurface;
                            if (prop.hasGarden != null) features.garden = prop.hasGarden;
                            if (prop.gardenSurface) features.garden_surface = prop.gardenSurface;
                            if (prop.parkingCountIndoor) features.parking_indoor = prop.parkingCountIndoor;
                            if (prop.parkingCountOutdoor) features.parking_outdoor = prop.parkingCountOutdoor;
                            if (prop.parkingCountClosedBox) features.parking_box = prop.parkingCountClosedBox;
                            if (prop.kitchen && prop.kitchen.type) features.kitchen = prop.kitchen.type;
                            if (prop.bathroomCount) features.bathrooms = prop.bathroomCount;
                            if (prop.hasSwimmingPool) features.swimming_pool = prop.hasSwimmingPool;
                            if (prop.hasBalcony != null) features.balcony = prop.hasBalcony;
                            return {
                                lat: loc.latitude,
                                lng: loc.longitude,
                                street: loc.street || '',
                                number: loc.number || '',
                                box: loc.box || '',
                                postalCode: loc.postalCode || '',
                                locality: loc.locality || '',
                                date_posted: pub.date || pub.creationDate || '',
                                description: (prop.description && prop.description.en) || '',
                                bedrooms: prop.bedroomCount || prop.bedrooms || 0,
                                surface: prop.netHabitableSurface || null,
                                image: media.length > 0 ? (media[0].url || media[0].src || '') : '',
                                title: prop.title || prop.name || '',
                                price: price.mainValue || (trans.rental && trans.rental.monthlyRentalPrice) || 0,
                                features: Object.keys(features).length > 0 ? JSON.stringify(features) : '',
                            };
                        } catch(e) { return null; }
                    }
                }
                return null;
            }""")

            page.close()
            browser.close()

        if not detail or not detail.get('lat') or not detail.get('lng'):
            return jsonify({'error': 'Impossibile estrarre i dati dell\'annuncio'}), 500

        distance = haversine_distance(
            GUILLEMINS_LAT, GUILLEMINS_LON, detail['lat'], detail['lng']
        )

        address = (
            f"{detail.get('street', '')} {detail.get('number', '')}"
            f"{' ' + detail.get('box', '') if detail.get('box') else ''}"
            f", {detail.get('postalCode', '')} {detail.get('locality', '')}"
        ).strip().strip(',')

        listing_data = {
            'external_id': external_id,
            'title': detail.get('title') or 'Appartamento',
            'price': int(detail.get('price', 0)),
            'bedrooms': detail.get('bedrooms', 0),
            'surface_area': detail.get('surface'),
            'address': address,
            'latitude': detail['lat'],
            'longitude': detail['lng'],
            'url': url,
            'source': 'immoweb',
            'image_url': detail.get('image', ''),
            'date_posted': detail.get('date_posted', ''),
            'distance_to_station': distance,
        }

        if detail.get('features'):
            listing_data['features'] = detail['features']

        listing_id = add_listing(listing_data)

        return jsonify({
            'id': listing_id,
            'message': f'Annuncio importato: €{listing_data["price"]}, {listing_data["bedrooms"]} cam, {distance:.0f}m dalla stazione',
        }), 201

    except Exception as e:
        logger.error(f"Error importing listing by URL: {e}")
        return jsonify({'error': f'Errore importazione: {str(e)}'}), 500


@app.route('/api/config')
@login_required
def api_config():
    """Get application configuration."""
    return jsonify({
        'guillemins_lat': GUILLEMINS_LAT,
        'guillemins_lon': GUILLEMINS_LON,
        'max_walk_distance': MAX_WALK_DISTANCE_METERS,
        'default_max_price': 1300,
        'default_min_bedrooms': 2,
    })


def create_app():
    """Application factory for production WSGI servers (waitress/gunicorn)."""
    return app


if __name__ == '__main__':
    logger.info("Starting Liege House Search server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
