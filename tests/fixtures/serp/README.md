# tests/fixtures/serp — Raw Google SERP HTML Fixtures

5-10 raw Google SERP HTML files captured by `scripts/spike/03_pws_consent_probe.py` (and initially by `scripts/spike/02_cloak_smoke.py`).

## Filename Pattern

`{NN}-{query_slug}.html`

Example: `01-pelota_playera_quico.html`, `02-filtro_aceite_ford_focus.html`

## Manifest

Each fixture is documented in `tests/fixtures/serp/MANIFEST.md` (appended by the capture script on each run).
The manifest records the query, capture date, byte count, and whether any INTERSTITIAL_MARKERS were detected.

## Security Notes

- These HTML files may contain Google SERP content. They are **never rendered in a browser context** during testing — only parsed via selectolax (text extraction, no JS execution). See T-01-01-07 in the threat register.
- Fixtures are committed to git as regression inputs for Phase 2's SERP parser. They contain no personal data (cold ephemeral Cloak context, no user account cookies).

## Expected Size Range

Normal Google SERP HTML: **200-800 KB**. If a fixture is smaller than ~35 KB, it is likely a consent interstitial page, not a real SERP — the capture script flags these with a warning.
