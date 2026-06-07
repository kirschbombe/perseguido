#!/usr/bin/env python3
"""
Inject IIIF structures (ranges) into jpv3-generated manifests in output/.

For each manifest, finds the matching pages CSV in ready-for-fester/ by Parent ARK,
then builds a range hierarchy based on what columns are present:

  3-level (Range.2 present): Range.1 → Range.2 → page ranges
  2-level (no Range.2):      Range.1 → page ranges

Mixed cases within a single Range.1 group are also handled: rows with a Range.2
value get wrapped in an issue sub-range; rows without one attach directly.

Canvases are matched to CSV rows positionally (manifest item order == CSV row order).
"""

import csv
import json
import os
from collections import OrderedDict
from urllib.parse import unquote

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
FESTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ready-for-fester")


def load_pages_csvs():
    """Return dict: parent_ark -> list of rows (in CSV order)."""
    lookup = {}
    for name in sorted(os.listdir(FESTER_DIR)):
        folder = os.path.join(FESTER_DIR, name)
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            if not fname.endswith("-pages.csv"):
                continue
            path = os.path.join(folder, fname)
            rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
            if not rows:
                continue
            parent_ark = rows[0].get("Parent ARK", "").strip()
            if parent_ark:
                lookup[parent_ark] = rows
    return lookup


def build_structures(manifest_id, canvases, rows):
    """
    Build IIIF Presentation 3 structures array.

    Handles two layouts depending on whether Range.2 values are present:
      - Range.2 present:  Range.1 → Range.2 → page ranges  (3-level)
      - Range.2 absent:   Range.1 → page ranges             (2-level)

    Mixed cases are handled per Range.1 group — if some rows within a group
    have Range.2 and others don't, the Range.2-less pages are added directly
    as page ranges alongside any issue sub-ranges.
    """
    structures = []
    range_counter = [0]

    def next_range_id():
        range_counter[0] += 1
        return f"{manifest_id}/range/{range_counter[0]}"

    def make_page_range(title, canvas_id):
        return {
            "id": next_range_id(),
            "type": "Range",
            "label": {"none": [title]},
            "items": [{"id": canvas_id, "type": "Canvas"}],
        }

    # Group by Range.1 preserving order.
    # Each group is an OrderedDict of r2_label → [(title, canvas_id)].
    # Empty-string r2 means "no sub-range — attach directly to Range.1".
    vol_groups = OrderedDict()
    for row, canvas in zip(rows, canvases):
        r1 = row.get("Range.1", "").strip()
        r2 = row.get("Range.2", "").strip()
        title = row.get("Title", "").strip()
        canvas_id = canvas["id"]

        if r1 not in vol_groups:
            vol_groups[r1] = OrderedDict()
        if r2 not in vol_groups[r1]:
            vol_groups[r1][r2] = []
        vol_groups[r1][r2].append((title, canvas_id))

    for r1_label, sub_groups in vol_groups.items():
        items = []
        for r2_label, pages in sub_groups.items():
            page_ranges = [make_page_range(t, c) for t, c in pages]
            if r2_label:
                # Range.2 present — wrap pages in an issue-level range
                items.append({
                    "id": next_range_id(),
                    "type": "Range",
                    "label": {"none": [r2_label]},
                    "items": page_ranges,
                })
            else:
                # No Range.2 — attach page ranges directly to Range.1
                items.extend(page_ranges)

        structures.append({
            "id": next_range_id(),
            "type": "Range",
            "label": {"none": [r1_label]},
            "items": items,
        })

    return structures


def main():
    print("Loading pages CSVs...")
    pages_lookup = load_pages_csvs()
    print(f"  Found CSVs for {len(pages_lookup)} works\n")

    manifest_files = sorted(
        f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json")
    )

    matched = 0
    skipped = 0

    for fname in manifest_files:
        path = os.path.join(OUTPUT_DIR, fname)
        manifest = json.load(open(path, encoding="utf-8"))

        manifest_ark = unquote(fname.replace(".json", ""))
        manifest_id = manifest.get("id", "")
        canvases = manifest.get("items", [])

        rows = pages_lookup.get(manifest_ark)
        if rows is None:
            print(f"SKIP {manifest_ark}: no matching pages CSV")
            skipped += 1
            continue

        if len(rows) != len(canvases):
            print(
                f"WARN {manifest_ark}: {len(rows)} CSV rows but {len(canvases)} canvases — skipping"
            )
            skipped += 1
            continue

        structures = build_structures(manifest_id, canvases, rows)
        manifest["structures"] = structures

        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        label = manifest.get("label", {}).get("none", ["?"])[0]
        n_vols = len(structures)
        n_issues = sum(len(v["items"]) for v in structures)
        print(
            f"OK  {label}: {n_vols} volume range(s), {n_issues} issue range(s), {len(canvases)} pages"
        )
        matched += 1

    print(f"\nDone: {matched} manifests updated, {skipped} skipped.")


if __name__ == "__main__":
    main()
