#!/usr/bin/env python3
"""
Prep lat-am-periodicals CSVs for volume-level manifest generation.

For each periodical in BATCH:
  - Pages CSV:
    - Rename 'Parent ARK' → 'Issue ARK'
    - Add new 'Parent ARK' = work ARK (from issues CSV Parent ARK)
    - Add 'Range.1' = year (from Date.normalized on the page row)
    - Add 'Range.2' = issue label (from issues CSV via Issue ARK)

lat-multi-works.csv:
  - Clear 'IIIF Object Type' for batch periodicals
  - Change 'viewingHint' from 'multi-part' to 'paged' for batch periodicals
"""

import csv
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
MULTI_WORKS_CSV = os.path.join(BASE, "lat-multi-works.csv")

BATCH = {
    "CTC", "accion", "adelante", "america-deportiva", "azucar",
    "carta-semanal", "cayohueso", "chaveta", "claridad", "cuba-urss",
    "cubanolibre", "cubayamerica", "dialectica", "discusion", "discusion2",
    "elcomunista", "elfortin", "elsocialista", "elsocialista2", "elsocialista3",
    "fundamentos", "ideas-libres", "kwongwahpo", "libertad", "manana",
    "mansenyatpo", "mediodia", "mudo", "palabra", "progresso", "razon",
    "respuestas", "rumbosnuevos", "sierramaestra", "social", "tipografo",
    "ultimahora", "uniondelmarino", "vanguardia", "vanguardiaobrera",
    "vialibre", "vialibre2", "villareno",
}


def find_csv(folder, suffix):
    """Find the single CSV ending with suffix in folder."""
    matches = [f for f in os.listdir(folder) if f.endswith(suffix)]
    if len(matches) == 1:
        return os.path.join(folder, matches[0])
    elif len(matches) == 0:
        return None
    else:
        raise ValueError(f"Multiple {suffix} files in {folder}: {matches}")


def parse_year(date_normalized):
    """Extract 4-digit year from Date.normalized (handles ISO dates, |~| separators, etc.)"""
    # Prefer ISO date format YYYY-MM-DD anywhere in the string
    m = re.search(r"\b(\d{4})-\d{2}", str(date_normalized or ""))
    if m:
        return m.group(1)
    # Fall back to any 4-digit number
    m = re.search(r"\b(\d{4})\b", str(date_normalized or ""))
    return m.group(1) if m else ""


def load_issues(issues_path):
    """
    Load issues CSV.
    Returns:
      - issue_labels: dict of Item ARK → Title
      - issue_order: dict of Item ARK → int position (for sorting pages)
      - work_ark: the Parent ARK from issues CSV (same for all rows)
    """
    issue_labels = {}
    issue_order = {}
    work_ark = None
    with open(issues_path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            ark = row.get("Item ARK", "").strip()
            title = row.get("Title", "").strip()
            parent = row.get("Parent ARK", "").strip()
            if ark and title:
                issue_labels[ark] = title
                issue_order[ark] = i
            if parent and not work_ark:
                work_ark = parent
    return issue_labels, issue_order, work_ark


def process_pages(pages_path, work_ark, issue_labels, issue_order):
    """
    Read pages CSV, add/rename columns, write updated CSV in place.
    Returns count of processed rows and any warnings.
    """
    warnings = []
    with open(pages_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        orig_fields = reader.fieldnames
        rows = list(reader)

    # Build new fieldnames — handle both fresh and already-processed CSVs
    new_fields = []
    for col in orig_fields:
        if col == "Parent ARK" and "Issue ARK" not in orig_fields:
            new_fields.append("Parent ARK")
            new_fields.append("Issue ARK")
        elif col == "Item Sequence" and "Issue Sequence" not in orig_fields:
            new_fields.append("Item Sequence")
            new_fields.append("Issue Sequence")
        else:
            new_fields.append(col)
    if "Range.1" not in new_fields:
        new_fields.append("Range.1")
    if "Range.2" not in new_fields:
        new_fields.append("Range.2")

    # Sort rows by issue order then by existing Item Sequence within each issue
    def sort_key(row):
        issue_ark = (row.get("Issue ARK") or row.get("Parent ARK", "")).strip()
        issue_pos = issue_order.get(issue_ark, 9999)
        seq_col = "Issue Sequence" if "Issue Sequence" in row else "Item Sequence"
        try:
            page_seq = int(row.get(seq_col, 0) or 0)
        except ValueError:
            page_seq = 0
        return (issue_pos, page_seq)

    rows.sort(key=sort_key)

    # If Issue ARK column already exists (script was run before), use it directly
    already_processed = "Issue ARK" in orig_fields

    new_rows = []
    for seq_num, row in enumerate(rows, 1):
        issue_ark = (row.get("Issue ARK") or row.get("Parent ARK", "")).strip()
        new_row = {}

        for col in orig_fields:
            if col == "Parent ARK" and not already_processed:
                new_row["Parent ARK"] = work_ark or ""
                new_row["Issue ARK"] = issue_ark
            elif col == "Item Sequence" and "Issue Sequence" not in orig_fields:
                new_row["Item Sequence"] = seq_num
                new_row["Issue Sequence"] = row.get("Item Sequence", "")
            elif col == "Item Sequence":
                new_row["Item Sequence"] = seq_num  # re-assign continuous sequence
            else:
                new_row[col] = row.get(col, "")

        # Range.2 — issue title from issues CSV
        issue_label = issue_labels.get(issue_ark, "")
        if not issue_label:
            warnings.append(f"  WARNING: no issue label found for Issue ARK: {issue_ark}")

        # Range.1 — year parsed from issue title (most reliable source)
        new_row["Range.1"] = parse_year(issue_label)
        new_row["Range.2"] = issue_label

        new_rows.append(new_row)

    with open(pages_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fields)
        writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows), warnings


def update_multiworks(work_arks):
    """
    Update lat-multi-works.csv: clear IIIF Object Type and set viewingHint=paged
    for all rows whose Item ARK is in work_arks.
    """
    with open(MULTI_WORKS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    updated = 0
    for row in rows:
        if row.get("Item ARK", "").strip() in work_arks:
            row["IIIF Object Type"] = ""
            row["viewingHint"] = "paged"
            updated += 1

    with open(MULTI_WORKS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nUpdated {updated} rows in lat-multi-works.csv")


def main():
    work_arks_processed = set()

    for dirname in sorted(BATCH):
        folder = os.path.join(BASE, dirname)
        if not os.path.isdir(folder):
            print(f"WARNING: directory not found: {dirname}")
            continue

        issues_path = find_csv(folder, "-issues.csv")
        pages_path = find_csv(folder, "-pages.csv")

        if not issues_path:
            print(f"WARNING: no issues CSV found for {dirname}, skipping")
            continue
        if not pages_path:
            print(f"WARNING: no pages CSV found for {dirname}, skipping")
            continue

        issue_labels, issue_order, work_ark = load_issues(issues_path)

        if not work_ark:
            print(f"WARNING: could not determine work ARK for {dirname}, skipping")
            continue

        count, warnings = process_pages(pages_path, work_ark, issue_labels, issue_order)
        print(f"{dirname}: {count} pages updated (work ARK: {work_ark})")
        for w in warnings:
            print(w)

        work_arks_processed.add(work_ark)

    # Post-process: for single-year collections, move Range.2 → Range.1 and drop Range.2
    for dirname in sorted(BATCH):
        folder = os.path.join(BASE, dirname)
        if not os.path.isdir(folder):
            continue
        pages_path = find_csv(folder, "-pages.csv")
        if not pages_path:
            continue
        with open(pages_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            rows = list(reader)
        if "Range.2" not in fields:
            continue
        years = set(row.get("Range.1", "") for row in rows)
        if len(years) == 1:
            new_fields = [c for c in fields if c != "Range.2"]
            for row in rows:
                row["Range.1"] = row.get("Range.2", "") or row.get("Range.1", "")
            rows = [{k: v for k, v in row.items() if k != "Range.2"} for row in rows]
            with open(pages_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=new_fields)
                writer.writeheader()
                writer.writerows(rows)
            print(f"{dirname}: single year — Range.2 → Range.1, Range.2 column removed")

    update_multiworks(work_arks_processed)


if __name__ == "__main__":
    main()
