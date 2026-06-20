# Deploy: Liège House Search su Render + Turso

## Obiettivo
Rendere l'app Flask accessibile da Internet su HTTPS, gratis, con dati persistenti.

## Architettura
- **Render** (free tier): Flask + Waitress, Python nativo
- **Turso**: SQLite cloud persistente (HTTP API, fino a 500 DB/9GB gratis)
- Dev locale continua a funzionare con SQLite file

## Modifiche ai file

### Nuovo: `db.py`
Layer astratto: se `TURSO_URL` e `TURSO_AUTH_TOKEN` sono impostati → usa `libsql_client`, altrimenti usa `sqlite3` locale.

### Modificato: `models.py`
Ogni funzione importa `get_connection()` da `db.py` invece di chiamare `sqlite3.connect()` direttamente. Adattamento per differenze API.

### Modificato: `config.py`
- `SECRET_KEY` da `os.environ.get('SECRET_KEY', ...)`
- `DATABASE_PATH` rimane per dev locale
- Turso URL/token da env vars

### Modificato: `app.py`
- `app.secret_key` da env var
- Refactor: `create_app()` factory function per waitress
- Schema SQL gestito centralmente

### Nuovo: `requirements.txt`
flask, flask-cors, werkzeug, requests, beautifulsoup4, lxml, waitress, libsql-client

### Nuovo: `migrate_to_turso.py`
Legge da `data/listings.db` locale, scrive su Turso via libsql-client. Copia listings e users.

### Rimosso: file debug
`debug_scraper*.py`, `test_*.py`, `debug_article.py`, `extract_listings.py`

### Aggiornato: `.gitignore`
Non ignora più `data/*.db` (il DB Turso è remoto, il locale serve per dev)

## Configurazione Render (dashboard)
- **Build**: `pip install -r requirements.txt`
- **Start**: `waitress-serve --port=$PORT --call 'app:create_app'`
- **Env vars**: `TURSO_URL`, `TURSO_AUTH_TOKEN`, `SECRET_KEY`
- **Plan**: Free

## Setup Turso
1. `turso db create liege-house-search`
2. `turso db show liege-house-search --url` → `TURSO_URL`
3. `turso db tokens create liege-house-search` → `TURSO_AUTH_TOKEN`

## Utenti
Dopo il deploy, creo i due utenti con `add_user.py`.

## Testing
1. Test locale con Turso
2. Deploy su Render, verificare login + listings + route
3. Test da cellulare fuori LAN
