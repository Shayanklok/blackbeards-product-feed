"""Build a ChatGPT product feed (JSONL) from the Blackbeard's Crafts online store.

Reads the store's public product listing (the same data the website shows)
and writes one JSON line per product in OpenAI's product feed format.

Run:  python build_feed.py
Output: blackbeards-products.jsonl (+ .gz), feed-report.txt
"""
import gzip
import html
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = ("https://cdn5.editmysite.com/app/store/api/v28/editor/users/131373534"
        "/sites/595993652281475416")
SELLER = "Blackbeard's Crafts"
HERE = Path(__file__).parent
OUT = HERE / "blackbeards-products.jsonl"
REPORT = HERE / "feed-report.txt"
CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else None  # optional raw-data cache dir


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def get_all(path):
    rows, page = [], 1
    while True:
        d = get(f"{BASE}/{path}?page={page}&per_page=100")
        rows += d["data"]
        pg = d["meta"]["pagination"]
        if page >= pg["total_pages"]:
            if len(rows) != pg["total"]:
                print(f"WARNING {path}: got {len(rows)} of {pg['total']}")
            return rows
        page += 1


def clean(text):
    """HTML -> plain text."""
    text = html.unescape(html.unescape(text or "")).replace("\xa0", " ")
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li)\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?[a-z][^>]*>", "", text)
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l).strip()


def main():
    products = get_all("products")
    cats = {c["site_category_id"] if "site_category_id" in c else c["id"]: c
            for c in get_all("categories")}
    if CACHE:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "products.json").write_text(json.dumps(products), encoding="utf-8")
        (CACHE / "categories.json").write_text(json.dumps(list(cats.values())), encoding="utf-8")

    skipped, rows, seen = Counter(), [], set()
    no_brand = []
    for p in products:
        name = (p.get("name") or "").strip()
        if p.get("visibility") != "visible":
            skipped["hidden on the website"] += 1; continue
        if p.get("product_type") != "physical":
            skipped[f"not a physical product ({p.get('product_type')})"] += 1; continue
        price = (p.get("price") or {}).get("low_subunits")
        if not price or price <= 0:
            skipped["no price"] += 1; continue
        img = ((p.get("thumbnail") or {}).get("data") or {}).get("absolute_url")
        if not img:
            skipped["no photo"] += 1; continue
        url = p.get("absolute_site_link")
        if not url or not name:
            skipped["no product page or name"] += 1; continue
        item_id = str(p["site_product_id"])
        if item_id in seen:
            skipped["duplicate"] += 1; continue
        seen.add(item_id)

        # Names are written "Maker - Product"; the maker is the brand.
        if " - " in name:
            brand = name.split(" - ", 1)[0].strip()
        else:
            brand = SELLER
            no_brand.append(name)

        desc = clean(p.get("short_description")) or name
        badges = p.get("badges") or {}
        inv = p.get("inventory") or {}
        sold_out = badges.get("out_of_stock") or inv.get("all_variations_sold_out")
        row = {
            "item_id": item_id,
            "title": name[:150],
            "description": desc[:5000],
            "url": url,
            "brand": brand,
            "seller_name": SELLER,
            "image_url": img,
            "price": f"{price / 100:.2f} USD",
            "availability": "out_of_stock" if sold_out else "in_stock",
            "target_countries": ["US"],
            "store_country": "US",
            "condition": "new",
            "seller_url": "https://www.blackbeardscrafts.com",
        }
        # Use the most specific category, written as "Parent > Child".
        own = [cats[c] for c in (p.get("categoryIds") or []) if c in cats]
        if own:
            def root_name(c):
                return (cats.get(c.get("root_parent_category_id") or "") or c)["name"]
            # Prefer the shop's own categories over the delivery-app menu copies.
            c = max(own, key=lambda c: (root_name(c).strip().lower() != "doordash menu",
                                        c.get("depth") or 0))
            path, hops = [], 0
            while c and hops < 6:
                path.insert(0, c["name"].strip())
                c = cats.get(c.get("parent") or "")
                hops += 1
            return_path = [n for n in path if n.lower() != "doordash menu"]
            if return_path:
                row["product_category"] = " > ".join(return_path)
        rows.append(row)

    # Safety: never replace a good file with an empty or badly shrunken one.
    previous = sum(1 for _ in OUT.open(encoding="utf-8")) if OUT.exists() else 0
    if not rows or len(rows) < previous * 0.5:
        sys.exit(f"Refusing to publish: only {len(rows)} products (was {previous}).")

    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # ChatGPT's hosted-URL option wants JSONL compressed (.jsonl.gz).
    # mtime=0 keeps the file byte-identical when the products haven't changed.
    with open(str(OUT) + ".gz", "wb") as raw, \
            gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(OUT.read_bytes())

    avail = Counter(r["availability"] for r in rows)
    lines = [
        f"Products on the website: {len(products)}",
        f"Products written to the file: {len(rows)}",
        f"  in stock: {avail['in_stock']}, out of stock: {avail['out_of_stock']}",
        f"  with a category: {sum('product_category' in r for r in rows)}",
        f"  description missing on the site (title used instead): "
        f"{sum(r['description'] == r['title'] for r in rows)}",
        "Left out:",
        *[f"  {n}: {why}" for why, n in skipped.most_common()],
        f"No maker in the name, brand set to the store ({len(no_brand)}):",
        *[f"  {n}" for n in no_brand],
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8 + len(skipped)]))


if __name__ == "__main__":
    main()
