# Product Image Scraper

Reads `Item_List_Categorized.xlsx`, and for every item in every category sheet,
searches Flipkart → Amazon → Bing Images (in that order) for a matching product
photo, then saves it into a category-wise folder as `<Product Name>_<Barcode>.jpg`.

The barcode suffix is intentional: many items share the same name across
sizes/variants (e.g. multiple "Amul Butter" rows at different prices), so the
barcode keeps every file unique while the product name stays human-readable.

## How it avoids saving the wrong/random image

Earlier versions of this kind of scraper just downloaded whatever the first
search result was — which is exactly how you end up with a shoe photo saved
for a bag of rice. This version validates every candidate before saving:

1. Each source (Flipkart, Amazon, Bing) returns **several** candidate images,
   each paired with its own title/alt-text — not just result #1.
2. Every candidate is scored against the item name in `scrapers/matching.py`:
   - **Brand check (hard filter):** up to two of the item's likely brand
     words (many Indian grocery brands are two words, e.g. "Bajaj Almond")
     must appear in the candidate's title/alt-text. If none do, that
     candidate is thrown out completely, however good its other keyword
     overlap looks.
   - **Keyword overlap (score):** what fraction of the item name's
     significant words also show up in the candidate text — combined with a
     **minimum absolute overlap count**, so a coincidental one-word match
     (e.g. both mentioning "green") can't pass just because the ratio looks
     high on a short name. The category name gives a small bonus if present.
   - **No detectable brand → stricter score:** for very generic names with
     no clear brand word, the score requirement is effectively raised
     automatically, since there's less to verify against.
3. Only candidates that pass both checks and clear `config.MIN_MATCH_SCORE`
   (default `0.3`) are attempted. The scraper tries the **top few** ranked
   candidates per source in order — if the best match's image link is dead
   or blocked, it tries the next-best match from the same source before
   giving up and moving to the next source. This is also why some items
   that previously failed to download at all should now succeed: a single
   dead link no longer sinks the whole source.
4. If **no** source produces a confident match that also downloads
   successfully, the item is logged as `failed` in `_progress.csv` with the
   real reason (search failure, no match, or download error) — nothing gets
   saved rather than something wrong getting saved.

Every successful download also logs its `match_score` and the exact
`matched_title` it was validated against in `_progress.csv`, so you can
audit *why* each image was accepted, not just which sources succeeded.

**Downloads that used to silently fail:** many image CDNs reject requests
with no `Referer` header (hotlink protection) or serve an image with a
missing/wrong `Content-Type`. Downloads now send a source-appropriate
`Referer` and verify the file by its actual byte signature rather than
trusting response headers, which should recover a chunk of previously
"failed" items.

**Tuning:** raise `config.MIN_MATCH_SCORE` (e.g. `0.5`) for stricter
matching and more skipped items, or lower it (e.g. `0.2`) to accept more
images at higher risk of mismatches. Since generic item names (brand-only,
no size/variant — e.g. "555 JEERA") give the scorer less to work with,
expect a higher skip rate for those regardless of threshold; those are the
rows worth fixing by hand or enriching with more detail in the spreadsheet.

## Before you run this at full scale, please read

- **9,717 items is a large batch.** At the default 2-second delay and three
  sources tried per item, a full run can take many hours. Start with `--limit`
  and `--categories` to sanity-check match quality before committing to the
  whole file.
- **Amazon and Flipkart actively detect and block scraping.** Expect a rising
  failure rate the longer/faster you run this — CAPTCHAs, 503s, or empty
  results are the sites telling you to slow down or that you've been
  temporarily blocked. The Bing Images fallback exists specifically so the
  pipeline still produces *something* when that happens, though those images
  come from the open web generally, not guaranteed to be from a store listing.
- **This scrapes public search-result HTML, not an official API**, so it will
  need maintenance — these sites change their markup periodically, which is
  why each scraper module documents exactly what pattern it's matching on.
- **Match quality isn't guaranteed.** The scrapers take the *first* plausible
  result for each product name/description as written in your spreadsheet —
  there's no human or barcode-level verification that the image is the exact
  SKU. Expect to spot-check and manually fix a percentage of results,
  especially for generic names (e.g. "555 JEERA" without a size).
- If your organization has (or can get) official product image feeds from
  distributors/brands, or access to Amazon's/Flipkart's affiliate APIs, those
  are far more reliable and ToS-compliant than scraping search results at
  this volume — worth checking before a large run.

## Setup

```bash
pip install -r requirements.txt
```

Place `Item_List_Categorized.xlsx` in this folder (or pass `--input path/to/file.xlsx`).

## Usage

**Always test first** on a couple of categories with a small limit:

```bash
python main.py --limit 10 --categories "Snacks" "Dairy"
```

Check `output/Snacks/` and `output/Dairy/` — open a few images and confirm
they actually match the products before scaling up.

Then run the full batch:

```bash
python main.py
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--limit N` | Only process the first N items per category (testing) |
| `--categories "Dairy" "Snacks"` | Only process specific category sheets |
| `--delay 3.0` | Seconds between requests — raise this if you're getting blocked |
| `--workers 4` | Run items in parallel (keep low; higher = more likely to get IP-banned) |
| `--input path.xlsx` | Use a different spreadsheet |
| `--output path` | Use a different output folder |

### Resuming

The run is safe to stop (Ctrl+C) and restart. Every attempt — success or
failure — is logged to `output/_progress.csv`. On the next run, any barcode
already marked `success` is skipped automatically, so you never re-download
what you already have.

To retry only the items that failed, open `_progress.csv`, filter to
`status == failed`, and re-run `main.py` — completed items are skipped, so it
will naturally retry whatever's left (you can also raise `--delay` or reduce
`--workers` first, since a `failed` result usually means a source was
blocking you).

## Output structure

```
output/
    _progress.csv
    Baby Care/
        AMUL SPRAY INFANT 500G_8901262080033.jpg
        ...
    Bakery/
        ...
    Dairy/
        ...
    ...
```

## Troubleshooting

- **Almost everything fails immediately** → you're likely being blocked at
  the network level already; try a different network, raise `--delay`, or
  reduce to `--workers 1`.
- **Amazon results are always empty** → check `output/_progress.csv`'s
  `error` column; if you see repeated failures right away, Amazon is very
  likely serving a CAPTCHA page instead of search results (see the comment
  in `scrapers/amazon.py`).
- **Flipkart stops returning matches** → their markup/CDN domain may have
  changed; check `scrapers/flipkart.py`'s `IMAGE_CDN_PATTERN` still matches
  what you see in a browser's page source for a manual search.
- **Wrong product image downloaded** → check that item's `match_score` and
  `matched_title` in `_progress.csv` — if the score is right at the
  `MIN_MATCH_SCORE` threshold, raise the threshold in `config.py`. If the
  matched title looks unrelated despite passing the brand check, the item
  name and a same-brand-different-product listing happened to share enough
  generic words (e.g. size only) — worth excluding that item name pattern or
  hand-checking that category.
- **A lot of items end up `failed` / skipped** → this is the validation
  working as intended when sources aren't returning a confident match, not a
  bug. Check a sample of `failed` rows' `error` column — if it's genuinely
  "no confident match" rather than a block/CAPTCHA, either the item names
  are too generic (see above) or `MIN_MATCH_SCORE` is set too strict for
  your catalog.
