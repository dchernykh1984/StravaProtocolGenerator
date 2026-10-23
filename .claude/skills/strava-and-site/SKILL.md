---
name: strava-and-site
description: How StravaProtocolGenerator turns Strava segment leaderboards into competition protocols and publishes them to the cycling site. Use when working on Strava scraping, rider matching, standings, or site publishing. Contains no secrets.
---

# Strava-to-site pipeline

All in `app/`: sign in to Strava -> fetch the competition roster from the cycling site ->
scrape each configured segment leaderboard with Selenium -> match scraped athletes to
registered riders -> compute per-stage standings and an overall cup -> render HTML
protocols -> optionally publish them back to the site.

## Secrets and safety

- Strava credentials and the site upload token are provided at runtime and are SECRETS:
  never hardcode, log, or commit them.
- Selenium drives a real browser (`app/selenium_driver.py`, excluded from coverage). In
  tests never hit Strava live: feed saved leaderboard HTML or fixtures and assert on the
  parser plus the matching and standings logic.

## Rider matching

- Scraped Strava names rarely equal registration names exactly, so matching is fuzzy and
  is the fragile part. Any change to matching needs tests over real-world name variants
  (transliteration, word order, missing or extra parts).

## Site contract

- The roster read and the protocol publish use the same cycling-site REST API as the
  other referee tools (competition id plus token). Re-publishing with the same
  competition overwrites; there is no separate edit call.
- A protocol goes as HTML, as structured data the site draws itself
  (`app/protocol_document.py`, schema copy in `tests/fixtures/protocol-document-v1.json`
  from the site's `protocols/schema/`), or both (`AppConfig.protocol_format`, default
  both). The builders take the HTML renderers' inputs plus `categories` and the
  protocol's own `unregistered_group_name`, and reuse `html_render`'s helpers so the
  data never disagrees with the HTML; `tests/test_protocol_document.py` checks every HTML
  value appears in the data. Strava links stay (`url` on name, result and stage cells).
- A document the site refuses comes back as `document_error` and is shown as an
  output warning; a failing build is a warning too, and the HTML still goes out.
