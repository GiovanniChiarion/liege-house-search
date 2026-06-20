# Liège House Search — Project Context

## Overview
Web app to find rental apartments within 10 min walk of **Liège-Guillemins station** (max €1300/mese, ≥2 camere). Built with Flask + SQLite + Leaflet + Bootstrap 5 dark theme.

## Current Status — Complete ✅

### Core Features
- [x] Flask server with SQLite DB
- [x] 20 Immoweb listings imported with coords
- [x] Walking routes via OSM.de foot API (routed-foot)
- [x] Walking distances and route GeoJSON saved in DB
- [x] Leaflet map with CartoDB dark tiles + marker clustering
- [x] Detail modal with listing info, notes, statuses
- [x] Google Maps verification button for walking directions
- [x] Sort: distance, price ↑/↓, date, bedrooms
- [x] "A piedi max" numeric input (minutes → meters: 1 min = 80m)
- [x] Status toggles: Visto / Non disponibile / Nascondi
- [x] Exclusion with optional reason
- [x] Per-user notes (shared for now)
- [x] "Mostra visti / Mostra non disp. / Mostra esclusi" toggles
- [x] Filter persistence via localStorage
- [x] Reset filters button
- [x] **Full Immoweb descriptions** (extracted via requests, alternativeDescriptions.fr)
- [x] **Riassunto in italiano** generato automaticamente nel modale
- [x] **Caratteristiche immobile** (piano, ascensore, classe energetica, ecc.)
- [x] **Login/Registrazione** con email e password
- [x] Session-based authentication
- [x] Git repository

### Known Issues
- OSM.de foot routing ~20-30% different from Google Maps (use GMaps link to verify)
- Immoweb CAPTCHA only blocks Playwright, not `requests`
- Some listings have only generic meta descriptions (no rich description available)
- Flask dev server not suitable for production

### Station Coordinates (main entrance)
`50.624433, 5.566708`

### Tech Stack
- **Backend**: Flask (Python 3), SQLite, Werkzeug auth
- **Frontend**: Bootstrap 5, Leaflet.js, markercluster
- **Scraper**: `requests` + Playwright for Immoweb
- **Routing**: OSM.de routed-foot API
- **Filters**: localStorage + URL params

### Database
- `data/listings.db` — SQLite with WAL mode
- **Tables**: `listings` (all listing data), `users` (auth)
- `listings` columns: id, external_id, title, description, price, bedrooms, surface_area, address, latitude, longitude, url, source, image_url, date_posted, date_discovered, distance_to_station, is_rented, is_viewed, is_unavailable, walking_distance, walking_route, notes (TEXT), available_date, excluded, exclusion_reason, features (JSON), last_checked

### Key Files
- `app.py` — Flask routes, API, auth
- `models.py` — DB schema, queries, user auth
- `config.py` — Configuration
- `templates/index.html` — Main app UI (all JS inline)
- `templates/login.html` — Login page
- `templates/register.html` — Registration page
- `scrape_map_area.py` — Immoweb scraper via Playwright
- `routing.py` — Walking route calculation
- `CLAUDE.md` — This file

### API Endpoints
| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | / | Yes | Main app page |
| GET | /login | No | Login page |
| POST | /login | No | Login action |
| GET | /register | No | Register page |
| POST | /register | No | Register action |
| GET | /logout | No | Logout |
| GET | /api/listings | Yes | List all (filters via query params) |
| GET | /api/listings/<id> | Yes | Get single listing |
| POST | /api/listings | Yes | Add manual listing |
| PATCH | /api/listings/<id>/status | Yes | Update status field |
| PATCH | /api/listings/<id>/notes | Yes | Update notes |
| DELETE | /api/listings/<id> | Yes | Delete listing |
| GET | /api/listings/<id>/route | Yes | Get walking route |
| GET | /api/stats | Yes | DB statistics |
| POST | /api/scrape | Yes | Trigger Immoweb scrape |
| POST | /api/listings/import | Yes | Import listings |

### Running
```bash
cd /home/giovanni/Documents/LiegeHouseSearch
source venv/bin/activate
python app.py
# → http://localhost:5000
```

### Deploy
Accessible on LAN at `http://10.176.248.244:5000`. For internet deployment:
- Use waitress/gunicorn instead of Flask dev server
- Set a permanent `app.secret_key`
- Use a reverse proxy (nginx/caddy)
- Consider adding HTTPS

### Future Ideas
- [ ] Per-user notes/statuses
- [ ] Isochrone visualization on map
- [ ] CSV/JSON export
- [ ] Email notifications for new listings
- [ ] Mobile responsive improvements
- [ ] GraphHopper/OpenRouteService for better walking routes
- [ ] Scheduled auto-scrape
