# Liège House Search — Project Context

## Overview
Web app to find rental apartments within 10 min walk of **Liège-Guillemins station** (max €1300/mese, ≥2 camere). Built with Flask + SQLite/Turso + Leaflet + Bootstrap 5 dark theme.

## Current Status — Complete ✅ (Deploy in Progress 🚀)

### Core Features
- [x] Flask server with SQLite DB (dev) / Turso (prod)
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
- [x] Git repository (GitHub: `GiovanniChiarion/liege-house-search`)
- [x] **Database abstraction layer** (`db.py`) — auto-switch SQLite ↔ Turso via env vars
- [x] **Turso cloud DB** — dati persistenti, schema e dati migrati
- [x] **Production-ready** — `create_app()` factory, env var secret key, waitress
- [x] **User accounts**: Giovanni (`chiarion.giovanni@gmail.com`), Maria Luisa (`maria.luisa.ratto@gmail.com`)

### Known Issues
- OSM.de foot routing ~20-30% different from Google Maps (use GMaps link to verify)
- Immoweb CAPTCHA only blocks Playwright, not `requests`
- Some listings have only generic meta descriptions (no rich description available)
- Render free tier goes to sleep after 15 min inactivity (wakes on request)
- Render free tier has ephemeral filesystem — non ci affida dati (Turso risolve)

### Station Coordinates (main entrance)
`50.624433, 5.566708`

### Tech Stack
- **Backend**: Flask (Python 3), SQLite/Turso (libsql), Werkzeug auth, Waitress
- **Frontend**: Bootstrap 5, Leaflet.js, markercluster
- **Scraper**: `requests` + Playwright for Immoweb
- **Routing**: OSM.de routed-foot API
- **Filters**: localStorage + URL params
- **Cloud DB**: Turso (libsql, free tier, 9GB, AWS eu-west-1)

### Database
- **Dev**: `data/listings.db` — SQLite with WAL mode
- **Prod**: Turso cloud (`liege-house-search-gchiarion.aws-eu-west-1.turso.io`)
- **Tables**: `listings` (all listing data), `users` (auth)
- `listings` columns: id, external_id, title, description, price, bedrooms, surface_area, address, latitude, longitude, url, source, image_url, date_posted, date_discovered, distance_to_station, is_rented, is_viewed, is_unavailable, walking_distance, walking_route, notes (TEXT), available_date, excluded, exclusion_reason, features (JSON), last_checked
- Auto-switch: se `TURSO_URL` e `TURSO_AUTH_TOKEN` sono impostati → usa Turso, altrimenti SQLite locale

### Users
| Email | Name | Created |
|-------|------|---------|
| chiarion.giovanni@gmail.com | Giovanni | 2026-06-20 |
| maria.luisa.ratto@gmail.com | Maria Luisa | 2026-06-20 |

### Key Files
- `app.py` — Flask routes, API, auth, `create_app()` factory
- `models.py` — DB schema, queries, user auth
- `db.py` — Database abstraction (SQLite locale ↔ Turso cloud)
- `config.py` — Configuration, station coords, search params
- `migrate_to_turso.py` — Migrate local SQLite → Turso
- `add_user.py` — CLI tool per gestire utenti (add/list/delete/changepw)
- `requirements.txt` — Dipendenze Python
- `templates/index.html` — Main app UI (all JS inline)
- `templates/login.html` — Login page
- `scrape_map_area.py` — Immoweb scraper via Playwright
- `routing.py` — Walking route calculation
- `CLAUDE.md` — This file

### API Endpoints
| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | / | Yes | Main app page |
| GET | /login | No | Login page |
| POST | /login | No | Login action |
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
| GET | /api/config | Yes | App configuration |

### Running (Development)
```bash
cd /home/giovanni/Documents/LiegeHouseSearch
source venv/bin/activate
python app.py
# → http://localhost:5000 (usa SQLite locale)
```

### Running (Production / Turso)
```bash
cd /home/giovanni/Documents/LiegeHouseSearch
export TURSO_URL="libsql://liege-house-search-gchiarion.aws-eu-west-1.turso.io"
export TURSO_AUTH_TOKEN="<token>"
export SECRET_KEY="<random string>"
source venv/bin/activate
waitress-serve --port=5000 --call 'app:create_app'
# → http://localhost:5000 (usa Turso cloud)
```

### Deploy
**Render** (https://dashboard.render.com):
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `waitress-serve --port=$PORT --call 'app:create_app'`
- **Plan**: Free (sleep dopo 15 min inattività)
- **Env vars**: `TURSO_URL`, `TURSO_AUTH_TOKEN`, `SECRET_KEY`

**Turso setup**:
```bash
# Installa CLI
curl -sSfL https://get.tur.so/install.sh | bash

# Crea DB
turso auth login
turso db create liege-house-search

# Ottieni credenziali
turso db show liege-house-search --url
turso db tokens create liege-house-search

# Migra dati locali → Turso
TURSO_URL="..." TURSO_AUTH_TOKEN="..." python migrate_to_turso.py
```

### CLI Tool — Gestione Utenti
```bash
source venv/bin/activate
python add_user.py add <email> <password> [nome]
python add_user.py list
python add_user.py delete <email>
python add_user.py changepw <email> <new_password>
```

### Future Ideas
- [ ] Per-user notes/statuses
- [ ] Isochrone visualization on map
- [ ] CSV/JSON export
- [ ] Email notifications for new listings
- [ ] Mobile responsive improvements
- [ ] GraphHopper/OpenRouteService for better walking routes
- [ ] Scheduled auto-scrape
