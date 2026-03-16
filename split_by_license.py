#!/usr/bin/env python3
"""
License CSV Splitter
=====================
Reads music_license_report.csv and splits it into separate CSVs by category.

Output files:
  free_monetization_ok.csv     — CC0, CC BY, CC BY-SA, Public Domain
  free_noncommercial_only.csv  — CC BY-NC, CC BY-NC-SA, CC BY-NC-ND, CC BY-ND
  not_free.csv                 — All rights reserved
  unknown.csv                  — Could not determine

USAGE:
  python split_by_license.py
  python split_by_license.py my_report.csv
"""

import csv
import sys
import os

INPUT_FILE = "music_license_report.csv"

CATEGORIES = {
    "free_monetization_ok": {
        "licenses": {"cc0", "cc by", "cc by-sa", "public domain"},
        "filename": "free_monetization_ok.csv",
        "label":    "Free — monetization OK",
    },
    "free_noncommercial": {
        "licenses": {"cc by-nc", "cc by-nc-sa", "cc by-nc-nd", "cc by-nd"},
        "filename": "free_noncommercial_only.csv",
        "label":    "Free — non-commercial only",
    },
    "not_free_confirmed": {
        "licenses": {"all rights reserved"},
        "filename": "not_free_confirmed.csv",
        "label":    "All rights reserved (confirmed by label/MusicBrainz)",
    },
    "not_free_assumed": {
        "licenses": {"assumed commercial"},
        "filename": "not_free_assumed.csv",
        "label":    "Assumed commercial (AcousticID match, no CC found)",
    },
    "unknown": {
        "licenses": {"unknown"},
        "filename": "unknown.csv",
        "label":    "Unknown — verify manually",
    },
}


def split_csv(input_file):
    if not os.path.isfile(input_file):
        print(f"Error: '{input_file}' not found.")
        sys.exit(1)

    # Read all rows
    with open(input_file, newline="", encoding="utf-8") as f:
        reader    = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows       = list(reader)

    print(f"\n  Read {len(rows)} rows from {input_file}\n")

    # Sort rows into buckets
    buckets = {key: [] for key in CATEGORIES}
    unmatched = []

    for row in rows:
        lic = row.get("license", "").lower().strip()
        matched = False
        for key, cat in CATEGORIES.items():
            if lic in cat["licenses"]:
                buckets[key].append(row)
                matched = True
                break
        if not matched:
            unmatched.append(row)

    # Write each bucket to its own CSV
    for key, cat in CATEGORIES.items():
        bucket = buckets[key]
        out    = cat["filename"]
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(bucket)
        print(f"  {cat['label']:35s} x{len(bucket):<5d} -> {out}")

    # Any licenses not in the categories above
    if unmatched:
        with open("other.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(unmatched)
        print(f"  {'Other (uncategorized)':35s} x{len(unmatched):<5d} -> other.csv")

    print(f"\n  Done! {len(rows)} rows split into {len(CATEGORIES)} files.")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    split_csv(input_file)
