#!/usr/bin/env python3
"""
Liege House Search - Flask web application for finding rental houses
near Liège-Guillemins station.
"""
import json
import logging
import threading
from datetime import datetime

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from functools import wraps, Response
from flask_cors import CORS

from config import GUILLEMINS_LAT, GUILLEMINS_LON, MAX_WALK_DISTANCE_METERS
from models import init_db, get_all_listings, get_listing, \
    add_listing, update_listing_status, delete_listing, get_stats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize database
init_db()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        name = request.form.get('name', '').strip()
        if not email or not password:
            flash('Email e password obbligatori', 'error')
            return render_template('register.html')
        if len(password) < 4:
            flash('Password troppo corta (min 4 caratteri)', 'error')
            return render_template('register.html')
        user_id = register_user(email, password, name)
        if user_id:
            session['user_id'] = user_id
            session['user_name'] = name or email.split('@')[0]
            flash('Registrazione completata!', 'success')
            return redirect(url_for('index'))
        flash('Email già registrata', 'error')
        return render_template('register.html')
    return render_template('register.html')


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
def api_get_listing(listing_id):
    """Get a single listing."""
    listing = get_listing(listing_id)
    if listing is None:
        return jsonify({'error': 'Listing not found'}), 404
    return jsonify(listing)


@app.route('/api/listings', methods=['POST'])
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


@app.route('/api/listings/<int:listing_id>/notes', methods=['PATCH'])
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
def api_delete_listing(listing_id):
    """Delete a listing."""
    try:
        delete_listing(listing_id)
        return jsonify({'message': 'Listing deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting listing: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/listings/<int:listing_id>/route')
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
def api_stats():
    """Get database statistics."""
    return jsonify(get_stats())


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    """Trigger scraping of Immoweb listings.
    Uses the map area filter around Guillemins.
    """
    from scrape_map_area import scrape_map_search, enrich_with_details

    data = request.get_json() or {}
    max_listings = data.get('max_listings', 50)

    def run_scrape():
        try:
            listings = scrape_map_search()
            if listings:
                enrich_with_details(listings, max_listings=max_listings)
                count = 0
                for listing in listings:
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
                logger.info(f"Scrape complete: {count} new/updated listings")
            else:
                logger.warning("No listings found from map search")
        except Exception as e:
            logger.error(f"Scrape failed: {e}")

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()

    return jsonify({'message': f'Ricerca Immoweb avviata nell\'area mappa Guillemins'}), 202


@app.route('/api/listings/import', methods=['POST'])
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


@app.route('/api/config')
def api_config():
    """Get application configuration."""
    return jsonify({
        'guillemins_lat': GUILLEMINS_LAT,
        'guillemins_lon': GUILLEMINS_LON,
        'max_walk_distance': MAX_WALK_DISTANCE_METERS,
        'default_max_price': 1300,
        'default_min_bedrooms': 2,
    })


if __name__ == '__main__':
    logger.info("Starting Liege House Search server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
