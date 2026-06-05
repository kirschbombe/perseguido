#!/usr/bin/env python3
"""Build volume-level IIIF manifests for El Perseguido by grouping issues by Año."""

import csv
import json
import re
import os

BASE_URL = "https://raw.githubusercontent.com/kirschbombe/perseguido/main/output"
MANIFESTS_DIR = "manifests"
OUTPUT_DIR = "output"
CSV_FILE = "perseguido_issues.csv"

YEAR_MAP = {
    1: 1890, 2: 1891, 3: 1892, 4: 1893,
    5: 1894, 6: 1895, 7: 1896, 8: 1897,
}


def ark_to_filename(ark):
    return ark.replace("ark:/21198/", "") + ".json"


def volume_manifest_id(ano):
    return f"{BASE_URL}/volume-ano-{ano}.json"


def parse_numero(title):
    m = re.search(r"número (\d+)", title)
    return m.group(1) if m else "?"


def build_volume(ano, issues_data):
    vol_id = volume_manifest_id(ano)
    year = YEAR_MAP.get(ano, "")

    all_canvases = []
    all_issue_ranges = []

    for issue in issues_data:
        manifest_path = os.path.join(MANIFESTS_DIR, ark_to_filename(issue["ark"]))
        with open(manifest_path) as f:
            manifest = json.load(f)

        old_base = manifest["id"]
        numero = parse_numero(issue["title"])
        date_str = issue["date_creation"]

        page_ranges = []
        for page_num, canvas in enumerate(manifest.get("items", []), 1):
            canvas["label"] = {"none": [f"número {numero}, p. {page_num}"]}

            canvas_json = json.dumps(canvas).replace(old_base, vol_id)
            canvas = json.loads(canvas_json)
            all_canvases.append(canvas)

            page_range = {
                "id": f"{vol_id}/range/range-ano-{ano}/range-issue-{numero}/range-page-{page_num}",
                "type": "Range",
                "label": {"en": [f"p. {page_num}"]},
                "items": [{"id": canvas["id"], "type": "Canvas"}],
            }
            page_ranges.append(page_range)

        issue_range = {
            "id": f"{vol_id}/range/range-ano-{ano}/range-issue-{numero}",
            "type": "Range",
            "label": {"en": [f"número {numero}, {date_str}"]},
            "metadata": [
                {"label": {"en": ["Date"]}, "value": {"en": [issue["date_normalized"]]}},
                {"label": {"en": ["Issue number"]}, "value": {"en": [numero]}},
            ],
            "items": page_ranges,
        }
        all_issue_ranges.append(issue_range)

    top_range = {
        "id": f"{vol_id}/range/range-ano-{ano}",
        "type": "Range",
        "label": {"en": [f"Año {ano} ({year})"]},
        "items": all_issue_ranges,
    }

    first_date = issues_data[0]["date_normalized"]
    last_date = issues_data[-1]["date_normalized"]
    metadata = [
        {"label": {"en": ["Date range"]}, "value": {"en": [f"{first_date} / {last_date}"]}},
        {"label": {"en": ["Genre"]}, "value": {"en": ["newspapers"]}},
        {"label": {"en": ["Rights"]}, "value": {"en": ["Public domain"]}},
        {
            "label": {"en": ["Note"]},
            "value": {"en": [
                "This is a test note. Issue dates are derived from publication records "
                "and may be approximate where original issues lack explicit date information."
            ]},
        },
    ]

    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": vol_id,
        "type": "Manifest",
        "label": {"none": [f"El Perseguido, Año {ano} ({year})"]},
        "behavior": ["paged"],
        "metadata": metadata,
        "items": all_canvases,
        "structures": [top_range],
    }


def build_collection(volumes):
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{BASE_URL}/collection.json",
        "type": "Collection",
        "label": {"none": ["El Perseguido (El): Voz de los explotados — Volumes"]},
        "items": [
            {"id": vol["id"], "type": "Manifest", "label": vol["label"]}
            for _, vol in volumes
        ],
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    groups = {}
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row["Title"]
            m = re.match(r"Año (\d+),", title)
            if not m:
                print(f"WARNING: could not parse Año from: {title}")
                continue
            ano = int(m.group(1))
            groups.setdefault(ano, []).append({
                "ark": row["Item ARK"],
                "title": title,
                "date_normalized": row["Date.normalized"],
                "date_creation": row["Date.creation"],
            })

    for ano in groups:
        groups[ano].sort(key=lambda x: x["date_normalized"])

    volumes = []
    for ano in sorted(groups):
        issues = groups[ano]
        print(f"Building Año {ano} ({YEAR_MAP.get(ano, '?')}) — {len(issues)} issues...")
        vol = build_volume(ano, issues)
        out_path = os.path.join(OUTPUT_DIR, f"volume-ano-{ano}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vol, f, ensure_ascii=False, indent=2)
        print(f"  → {out_path} ({len(vol['items'])} canvases, {len(issues)} issue ranges)")
        volumes.append((ano, vol))

    collection = build_collection(volumes)
    coll_path = os.path.join(OUTPUT_DIR, "collection.json")
    with open(coll_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, ensure_ascii=False, indent=2)
    print(f"→ {coll_path} ({len(volumes)} volumes)")


if __name__ == "__main__":
    main()
