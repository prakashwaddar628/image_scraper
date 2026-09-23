"""
Central configuration for the product image scraper.
Edit these values to match your environment before running main.py.
"""

# Path to the source spreadsheet (categorized item list)
INPUT_XLSX = "Item_List_Categorized.xlsx"

# The combined "all items" sheet — skipped automatically since every item
# also appears in its individual category sheet. Change if your sheet names differ.
SKIP_SHEETS = ["All Items - Categorized"]

# Where category folders + images get written
OUTPUT_DIR = "output"

# Seconds to wait between requests (per item, per source tried).
# Keep this reasonably high (1.5-3s) to avoid triggering bot-detection / IP bans.
REQUEST_DELAY = 2.0

# HTTP request timeout (seconds)
TIMEOUT = 15

# How many times to retry a single source before giving up on it for that item
MAX_RETRIES = 2

# Rotated per-request to look less like a single bot
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# Order in which sources are tried for each item. Comment one out to disable it.
# "bing" is the most reliable/least likely to block; amazon/flipkart are best-effort.
SOURCES_ORDER = ["flipkart", "amazon", "bing"]

# Minimum acceptable downloaded image size in bytes (filters out 1x1 tracking pixels / broken icons)
MIN_IMAGE_BYTES = 2000

# Minimum keyword-overlap score (see scrapers/matching.py) a candidate image's
# title/alt-text must reach — against the item name — before it's downloaded.
# Raise this (e.g. 0.5) for stricter matching / more skipped items; lower it
# (e.g. 0.2) to accept more images at the cost of more mismatches.
MIN_MATCH_SCORE = 0.3

# How many top-ranked, already-validated candidates to attempt downloading
# (in score order) per source before giving up on that source. This covers
# dead links / hotlink-blocked images without falling back to a worse source.
MAX_DOWNLOAD_ATTEMPTS_PER_SOURCE = 3

# Sent as the "Referer" header when downloading each source's images — many
# CDNs reject image requests with no Referer (hotlink protection), which is
# a common cause of "found a match but the image never downloaded".
REFERERS = {
    "flipkart": "https://www.flipkart.com/",
    "amazon": "https://www.amazon.in/",
    "bing": "https://www.bing.com/",
    "google": "https://www.google.com/",
    "bigbasket": "https://www.bigbasket.com/",
    "jiomart": "https://www.jiomart.com/",
    "blinkit": "https://www.blinkit.com/",
    "swiggy": "https://www.swiggy.com/",
    "zeptonow": "https://www.zepto.com/",
    "dunzo": "https://www.dunzo.com/",
}
