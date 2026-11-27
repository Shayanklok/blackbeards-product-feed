# Blackbeard's Crafts product feed

Keeps `blackbeards-products.jsonl` in step with the products on
[blackbeardscrafts.com](https://www.blackbeardscrafts.com), so ChatGPT's Business Hub
can re-read it on a schedule.

- `build_feed.py` reads the online store's public product listing and writes the feed.
- `.github/workflows/update-feed.yml` runs it every 6 hours and commits any changes.
- `feed-report.txt` summarises the last run (counts, anything left out).

Feed link for ChatGPT:
`https://shayanklok.github.io/blackbeards-product-feed/blackbeards-products.jsonl.gz`

To rebuild by hand: open the repository's **Actions** tab, choose **Update product feed**,
and press **Run workflow**.
