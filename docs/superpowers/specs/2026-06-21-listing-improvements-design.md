# Listing Improvements — Design Spec

## Overview
Refine the listing management experience: separate `is_new` from `is_viewed`, add stable sequential titles, enable bulk selection and actions, and fix the marker-click → sidebar sync.

## DB Changes

### New columns on `listings`
- `is_new` (BOOLEAN, DEFAULT 1) — separate from `is_viewed`. Persists until manually cleared.
- `listing_number` (INTEGER) — sequential stable number assigned at creation, never changes.

### Migration
```sql
ALTER TABLE listings ADD COLUMN is_new BOOLEAN DEFAULT 1;
ALTER TABLE listings ADD COLUMN listing_number INTEGER;
```

After adding columns, assign listing numbers and backfill `is_new`:
```sql
UPDATE listings SET listing_number = id WHERE listing_number IS NULL;
UPDATE listings SET is_new = 0 WHERE is_new IS NULL;
```

## Backend

### `add_listing()` — auto-assign listing_number
When inserting a new listing, compute:
```sql
SELECT COALESCE(MAX(listing_number), 0) + 1 FROM listings;
```
Set the result as `listing_number`. Never updated after creation.

### `update_listing_status()` — add `is_new` to allowed fields
Add `"is_new"` to the `allowed_fields` list. Also auto-clear `is_new` when `is_viewed` or `is_unavailable` is set to `true`.

### New endpoint: `POST /api/listings/bulk-status`
Accepts:
```json
{ "ids": [1, 2, 3], "field": "is_new", "value": false }
```
Applies the same status update to all IDs in a single transaction.

### API endpoint: auto-clear logic
When `api_update_status` sets `is_viewed=true` or `is_unavailable=true`, also set `is_new=false` in the same transaction to keep state consistent even if frontend has a bug.

## Frontend — Marker Logic

Replace `isNew = !is_viewed` with `isNew = listing.is_new`:

| `is_new` | `is_viewed` | `is_unavailable` | Marker color | Radius | Tooltip icon |
|---|---|---|---|---|---|
| true | any | false | amber `#ff9100` | 10 | 🆕 |
| false | true | false | green `#00c853` | 8 | 👁️ |
| false | false | false | default | 8 | — |
| any | any | true | red `#ff1744` | 6 | ❌ |

Click handler: PATCH `is_viewed=true`, then call `loadListings()` to update sidebar.

## Frontend — Card Rendering

- **Title**: always `"Annuncio #${listing.listing_number}"`
- **Badges**: amber "Nuovo" if `is_new`; gray "Visto" if viewed; red "Non disponibile" if unavailable
- **CSS class**: `.new` if `is_new`, `.viewed` if `!is_new && is_viewed`
- **Checkbox**: each card gets a checkbox (always visible, left of image)
- **"Non Nuovo" button**: new action in card actions row (star icon)

## Frontend — Bulk Selection

- **Checkbox**: each card has `<input type="checkbox">`, always visible
- **Selected count**: counter shown when selections > 0
- **Bulk toolbar**: fixed at bottom of listings panel, shown when selections > 0
  - "Segna come visto" → PATCH `is_viewed=true` + auto `is_new=false`
  - "Non nuovo" → PATCH `is_new=false`
  - "Non disp." → PATCH `is_unavailable=true` + auto `is_new=false`
  - "Deseleziona tutto" → clears selection
- After bulk operation, reload listings

### CSS
```css
.listing-card.selected { border-color: var(--accent); box-shadow: ... }
.bulk-toolbar { position: fixed; bottom: 0; ... }
```

## Files to Modify

| File | Changes |
|---|---|
| `models.py` | Add `is_new` to allowed fields; `add_listing()`: auto-assign `listing_number`; add `bulk_update_status()` |
| `app.py` | Add `POST /api/listings/bulk-status`; auto-clear `is_new` in status handler |
| `templates/index.html` | Marker logic, card rendering, bulk UI, `clearNew()`, `toggleViewed()` clears `is_new`, marker click → `loadListings()` |

## Edge Cases
- Existing listings get `is_new = 0` after migration — they're not "new"
- Deleting a listing: listing_number is not reused (gaps are fine)
- Manual `add_listing()` via API: `listing_number` auto-assigned, `is_new` defaults to 1
- Listings without `listing_number` (old ones) fall back to `id` as display number
