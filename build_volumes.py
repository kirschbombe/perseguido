#!/usr/bin/env python3
"""Build volume-level IIIF manifests for a periodical collection.

Usage:
  python3 build_volumes.py perseguido
  python3 build_volumes.py elfigaro
"""

import sys
import csv
import json
import re
import os

BASE_GITHUB = "https://raw.githubusercontent.com/kirschbombe/perseguido/main"
MANIFESTS_DIR = "manifests"

# ── Collection configs ────────────────────────────────────────────────────────

PERSEGUIDO_YEAR_MAP = {
    1: 1890, 2: 1891, 3: 1892, 4: 1893,
    5: 1894, 6: 1895, 7: 1896, 8: 1897,
}

CONFIGS = {
    "perseguido": {
        "issues_csv": "perseguido_issues.csv",
        "date_field": "Date.creation",
        "sort_issues": True,      # sort by date within each volume
        "output_dir": "output",
        "github_path": "output",
        "manifest_label": "El Perseguido (El): Voz de los explotados",
        "collection_label": "El Perseguido (El): Voz de los explotados — Volumes",
    },
    "elfigaro": {
        "issues_csv": "elfigaro-issues.csv",
        "date_field": "Date.created",
        "sort_issues": False,     # preserve CSV order
        "output_dir": "output/elfigaro",
        "github_path": "output/elfigaro",
        "manifest_label": "El Fígaro",
        "collection_label": "El Fígaro — Volumes",
    },
}

# ── Issue parsing ─────────────────────────────────────────────────────────────

def parse_issue(row, collection):
    """Return dict with volume_key (int), volume_label, issue_label, is_index.
    Returns None if the row can't be parsed."""
    title = row["Title"]

    if collection == "perseguido":
        m = re.match(r"Año (\d+), número (\d+)\. (.+)", title)
        if not m:
            return None
        ano = int(m.group(1))
        return {
            "volume_key": ano,
            "volume_label": f"Año {ano} ({PERSEGUIDO_YEAR_MAP.get(ano, '')})",
            "issue_label": f"número {m.group(2)}, {m.group(3)}",
            "is_index": False,
        }

    if collection == "elfigaro":
        # Index volumes: "1885 to 1899 (Indices, vol. 01)"
        if re.search(r"Indices", title, re.I):
            return {
                "volume_key": None,
                "volume_label": None,
                "issue_label": title,
                "is_index": True,
            }
        # Group by year from Date.normalized
        year_m = re.match(r"(\d{4})", row.get("Date.normalized", ""))
        if not year_m:
            return None
        year = int(year_m.group(1))
        return {
            "volume_key": year,
            "volume_label": str(year),
            "issue_label": title,
            "is_index": False,
        }

    return None

# ── Core build functions ──────────────────────────────────────────────────────

def ark_to_filename(ark):
    return ark.replace("ark:/21198/", "") + ".json"


def build_ranges_for_issues(issues, vol_id, vol_key_str):
    """Build issue ranges (with page sub-ranges) for a list of issues."""
    issue_ranges = []
    for issue in issues:
        manifest_path = os.path.join(MANIFESTS_DIR, ark_to_filename(issue["ark"]))
        if not os.path.exists(manifest_path):
            print(f"  WARNING: manifest not found, skipping: {manifest_path}")
            continue
        with open(manifest_path) as f:
            manifest = json.load(f)

        old_base = manifest["id"]
        issue_label = issue["issue_label"]
        # Derive a slug for range IDs from the issue label
        slug = re.sub(r"[^\w]+", "-", issue_label).strip("-").lower()[:40]

        page_ranges = []
        canvases = []
        for page_num, canvas in enumerate(manifest.get("items", []), 1):
            canvas["label"] = {"none": [f"{issue_label}, p. {page_num}"]}
            canvas = json.loads(json.dumps(canvas).replace(old_base, vol_id))
            canvases.append(canvas)

            page_range = {
                "id": f"{vol_id}/range/{vol_key_str}/{slug}/p{page_num}",
                "type": "Range",
                "label": {"en": [f"p. {page_num}"]},
                "items": [{"id": canvas["id"], "type": "Canvas"}],
            }
            page_ranges.append(page_range)

        issue_range = {
            "id": f"{vol_id}/range/{vol_key_str}/{slug}",
            "type": "Range",
            "label": {"en": [issue_label]},
            "metadata": [
                {"label": {"en": ["Date"]}, "value": {"en": [issue["date_normalized"]]}},
            ],
            "items": page_ranges,
        }
        issue_ranges.append((issue_range, canvases))

    return issue_ranges


def build_full_run(collection, groups, indices, config):
    run_id = f"{BASE_GITHUB}/{config['github_path']}/full-run.json"
    all_canvases = []
    all_vol_ranges = []

    for vol_key in sorted(groups):
        issues = groups[vol_key]
        vol_label = issues[0]["volume_label"]
        vol_key_str = f"vol-{vol_key}"
        vol_range_id = f"{run_id}/range/{vol_key_str}"

        issue_range_data = build_ranges_for_issues(issues, run_id, vol_key_str)
        issue_ranges = []
        for ir, canvases in issue_range_data:
            all_canvases.extend(canvases)
            issue_ranges.append(ir)

        all_vol_ranges.append({
            "id": vol_range_id,
            "type": "Range",
            "label": {"en": [vol_label]},
            "items": issue_ranges,
        })

    # Indices as first top-level range (matching source collection order)
    if indices:
        idx_range_data = build_ranges_for_issues(indices, run_id, "indices")
        idx_issue_ranges = []
        idx_canvases = []
        for ir, canvases in idx_range_data:
            idx_canvases.extend(canvases)
            idx_issue_ranges.append(ir)
        all_canvases = idx_canvases + all_canvases
        all_vol_ranges.insert(0, {
            "id": f"{run_id}/range/indices",
            "type": "Range",
            "label": {"en": ["Indices"]},
            "items": idx_issue_ranges,
        })

    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": run_id,
        "type": "Manifest",
        "label": {"none": [config["manifest_label"]]},
        "behavior": ["paged"],
        "items": all_canvases,
        "structures": all_vol_ranges,
    }


def build_volume_manifests(collection, groups, config):
    """Build one manifest per volume (for the multi-part collection approach)."""
    volumes = []
    for vol_key in sorted(groups):
        issues = groups[vol_key]
        vol_label = issues[0]["volume_label"]
        vol_id = f"{BASE_GITHUB}/{config['github_path']}/volume-{vol_key}.json"
        vol_key_str = f"vol-{vol_key}"

        issue_range_data = build_ranges_for_issues(issues, vol_id, vol_key_str)
        all_canvases = []
        issue_ranges = []
        for ir, canvases in issue_range_data:
            all_canvases.extend(canvases)
            issue_ranges.append(ir)

        manifest = {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": vol_id,
            "type": "Manifest",
            "label": {"none": [f"{config['manifest_label']}, {vol_label}"]},
            "behavior": ["paged"],
            "items": all_canvases,
            "structures": issue_ranges,
        }
        volumes.append((vol_key, manifest))
    return volumes


def build_collection(volumes, indices, config):
    coll_id = f"{BASE_GITHUB}/{config['github_path']}/collection.json"
    items = [{"id": v["id"], "type": "Manifest", "label": v["label"]} for _, v in volumes]
    # Index manifests could be added here too if built separately
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": coll_id,
        "type": "Collection",
        "label": {"none": [config["collection_label"]]},
        "items": items,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    collection = sys.argv[1] if len(sys.argv) > 1 else "perseguido"
    if collection not in CONFIGS:
        print(f"Unknown collection '{collection}'. Choose: {list(CONFIGS)}")
        sys.exit(1)

    config = CONFIGS[collection]
    os.makedirs(config["output_dir"], exist_ok=True)

    # Read and group issues
    groups = {}   # vol_key (int) → [issue dicts]
    indices = []  # index items

    date_field = config["date_field"]
    with open(config["issues_csv"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_issue(row, collection)
            if parsed is None:
                print(f"  WARNING: could not parse title: {row['Title']!r}")
                continue
            issue = {
                "ark": row["Item ARK"],
                "title": row["Title"],
                "date_normalized": row["Date.normalized"],
                "date_created": row.get(date_field, ""),
                "manifest_url": row["IIIF Manifest URL"],
                "volume_label": parsed["volume_label"],
                "issue_label": parsed["issue_label"],
            }
            if parsed["is_index"]:
                indices.append(issue)
            else:
                groups.setdefault(parsed["volume_key"], []).append(issue)

    if config["sort_issues"]:
        for key in groups:
            groups[key].sort(key=lambda x: x["date_normalized"])

    print(f"Collection: {collection} | {sum(len(v) for v in groups.values())} issues across {len(groups)} volumes | {len(indices)} index items")

    # Build full-run manifest
    print("Building full-run manifest...")
    full_run = build_full_run(collection, groups, indices, config)
    run_path = os.path.join(config["output_dir"], "full-run.json")
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(full_run, f, ensure_ascii=False, indent=2)
    print(f"  → {run_path} ({len(full_run['items'])} canvases, {len(full_run['structures'])} top-level ranges)")

    # Build per-volume manifests + collection
    print("Building volume manifests...")
    volumes = build_volume_manifests(collection, groups, config)
    for vol_key, manifest in volumes:
        out_path = os.path.join(config["output_dir"], f"volume-{vol_key}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"  → {out_path} ({len(manifest['items'])} canvases)")

    collection_json = build_collection(volumes, indices, config)
    coll_path = os.path.join(config["output_dir"], "collection.json")
    with open(coll_path, "w", encoding="utf-8") as f:
        json.dump(collection_json, f, ensure_ascii=False, indent=2)
    print(f"  → {coll_path} ({len(volumes)} volumes)")


if __name__ == "__main__":
    main()
