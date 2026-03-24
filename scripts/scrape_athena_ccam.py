"""
Scrape CCAM vocabulary from Athena OHDSI API and export to CSV.
Usage:
    python scripts/scrape_athena_ccam.py --token "eyJ..." --output ccam_athena.csv

The token is the Athena-Auth-Token from browser DevTools (XHR headers).
The session/token may expire after ~30 min, so run quickly.
"""
import argparse
import csv
import json
import subprocess
import sys
import time

ATHENA_API = "https://athena.ohdsi.org/api/v1/concepts"
PROXY = "http://localhost:3128"
PAGE_SIZE = 500  # max per page


def fetch_page(token: str, cookie: str, page: int, proxy: str | None) -> dict:
    url = f"{ATHENA_API}?vocabulary=CCAM&pageSize={PAGE_SIZE}&page={page}&query="
    cmd = ["curl", "-s", "--compressed", "--max-time", "30"]
    if proxy:
        cmd += ["-x", proxy]
    cmd += [
        "-H", f"Athena-Auth-Token: {token}",
        "-H", f"Cookie: {cookie}",
        "-H", "Accept: application/json",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", "Referer: https://athena.ohdsi.org/search-terms/terms",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"curl exit code: {result.returncode}")
        print(f"stderr: {result.stderr[:500]}")
        print(f"stdout: {result.stdout[:500]}")
        raise RuntimeError(f"curl failed with code {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Not JSON. First 500 chars of response:")
        print(result.stdout[:500])
        raise


def main():
    parser = argparse.ArgumentParser(description="Scrape CCAM from Athena")
    parser.add_argument("--token", required=True, help="Athena-Auth-Token JWT")
    parser.add_argument("--cookie", required=True, help="Full Cookie header from browser")
    parser.add_argument("--output", default="ccam_athena.csv", help="Output CSV path")
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy")
    args = parser.parse_args()

    proxy = None if args.no_proxy else PROXY

    # First page to get total
    print("Fetching page 1...")
    data = fetch_page(args.token, args.cookie, 1, proxy)

    # Detect response structure
    if "content" in data:
        items = data["content"]
        total = data.get("totalElements", 0)
        total_pages = data.get("totalPages", 1)
    elif "items" in data:
        items = data["items"]
        total = data.get("total", len(items))
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    else:
        # Try to find the list in the response
        print("Response keys:", list(data.keys()))
        print("First 500 chars:", json.dumps(data)[:500])
        sys.exit(1)

    print(f"Total CCAM concepts: {total}, pages: {total_pages}")

    if not items:
        print("No items found! Check token validity.")
        sys.exit(1)

    # Show first item structure
    print(f"First item keys: {list(items[0].keys())}")
    print(f"First item: {json.dumps(items[0], indent=2)[:300]}")

    all_items = list(items)

    # Fetch remaining pages
    for page in range(2, total_pages + 1):
        print(f"Fetching page {page}/{total_pages}...")
        try:
            data = fetch_page(args.token, args.cookie, page, proxy)
            page_items = data.get("content", data.get("items", []))
            all_items.extend(page_items)
            time.sleep(0.3)  # be polite
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break

    print(f"Total items fetched: {len(all_items)}")

    # Detect field names for code and name
    sample = all_items[0]
    code_field = None
    name_field = None
    for f in ["conceptCode", "concept_code", "code"]:
        if f in sample:
            code_field = f
            break
    for f in ["conceptName", "concept_name", "name"]:
        if f in sample:
            name_field = f
            break

    if not code_field or not name_field:
        print(f"Cannot detect code/name fields. Keys: {list(sample.keys())}")
        # Write raw JSON as fallback
        with open(args.output.replace(".csv", ".json"), "w") as f:
            json.dump(all_items, f, indent=2)
        print(f"Wrote raw JSON to {args.output.replace('.csv', '.json')}")
        sys.exit(1)

    print(f"Using fields: code={code_field}, name={name_field}")

    # Write CSV
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "description", "concept_id", "vocabulary_id", "domain_id", "standard_concept"])
        for item in all_items:
            writer.writerow([
                item.get(code_field, ""),
                item.get(name_field, ""),
                item.get("conceptId", item.get("concept_id", "")),
                item.get("vocabularyId", item.get("vocabulary_id", "")),
                item.get("domainId", item.get("domain_id", "")),
                item.get("standardConcept", item.get("standard_concept", "")),
            ])

    print(f"Wrote {len(all_items)} concepts to {args.output}")
    print(f"\nTo load into OPAL:")
    print(f'  curl --noproxy \'*\' -s -X POST "http://localhost:8000/api/mapping/reference/upload" \\')
    print(f'    -F "name=CCAM_EN" -F "domain=Procedure" -F "file=@{args.output}"')


if __name__ == "__main__":
    main()
