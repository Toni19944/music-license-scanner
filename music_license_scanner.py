#!/usr/bin/env python3
"""
Music Library License Scanner
==============================
Scans a music folder and attempts to determine the license of each track.

HOW IT WORKS:
  1. Reads existing metadata (tags) from each audio file
  2. Checks artist name, file path, and URL tags against known free music sources
  3. Fingerprints each track via AcousticID / Chromaprint to identify unknown songs
  4. Looks up the identified track on MusicBrainz for label / license info
  5. Optionally queries the Jamendo API for CC license data
  6. Outputs an incremental CSV report (saved as it goes, never loses progress)

SETUP (run once):
  pip install pyacoustid mutagen musicbrainzngs requests

  You also need the fpcalc binary for audio fingerprinting:
    Windows : Download from https://acoustid.org/chromaprint, extract fpcalc.exe,
              add its folder to your system PATH
    macOS   : brew install chromaprint
    Linux   : sudo apt install libchromaprint-tools

API KEYS (both free):
  AcousticID  : https://acoustid.org/applications  -> New Application -> copy API key
  Jamendo     : https://devportal.jamendo.com       -> New App -> copy Client ID (optional)

USAGE:
  python music_license_scanner.py <folder> [--exclude Folder1,Folder2]

EXAMPLES:
  python music_license_scanner.py "F:\\Music"
  python music_license_scanner.py "F:\\Music" --exclude "Podcasts,Audiobooks,SFX"
"""

import os
import sys
import csv
import time
import threading
import requests
import musicbrainzngs
import acoustid


# ==============================================================================
#  CONFIGURATION — edit these before running
# ==============================================================================
ACOUSTID_API_KEY  = "YOUR_ACOUSTID_API_KEY_HERE"   # https://acoustid.org/applications
JAMENDO_CLIENT_ID = "YOUR_JAMENDO_CLIENT_ID_HERE"  # https://devportal.jamendo.com (optional)
OUTPUT_FILE       = "music_license_report.csv"
SUPPORTED_EXTS    = {".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".opus", ".wma"}
SLEEP_BETWEEN_REQUESTS = 0.5  # seconds between API calls — be polite to free services

# Subfolders to exclude by name (case-sensitive). Can also be set via --exclude flag.
# Example: EXCLUDE_FOLDERS = {"Podcasts", "Audiobooks", "SFX"}
EXCLUDE_FOLDERS = set()
# ==============================================================================


# Known NCS (No Copyright Sounds) artists.
# All NCS releases are free for YouTube use with attribution (CC BY).
NCS_ARTISTS = {
    "alan walker", "elektronomia", "different heaven", "ncs", "nocopyrightsounds",
    "jim yosef", "tobu", "itro", "aero chord", "cartoon", "syn cole", "lensko",
    "disfigure", "marshmello", "unknown brain", "ship wrek", "distrion",
    "alex skrindo", "t-mass", "rival", "ash o'connor", "cmc$", "lost sky",
    "chris linton", "laszlo", "inukshuk", "janji", "culture code", "kovan",
    "electro-light", "subtact", "glude", "warptech", "killercats", "ash",
    "evan king", "jensation", "waysons", "phantom sage", "clarx", "harddope",
    "mike luczo", "stahl!", "mendum", "levianth", "fredji",
}

# Keywords found in tags that suggest a known free music source
FREE_MUSIC_SOURCES = [
    "freemusicarchive", "fma", "incompetech", "ccmixter", "jamendo",
    "bensound", "musopen", "ncs", "nocopyrightsounds", "pixabay",
    "youtube audio library",
]

# License sets used for the safe_to_use verdict column
SAFE_FOR_MONETIZED    = {"cc0", "cc by", "cc by-sa", "public domain"}
SAFE_FOR_NONMONETIZED = {"cc0", "cc by", "cc by-sa", "cc by-nd",
                         "cc by-nc", "cc by-nc-sa", "cc by-nc-nd", "public domain"}

YOUTUBE_SAFE_NOTE = {
    "cc0":               "FREE - monetization OK",
    "public domain":     "FREE - monetization OK",
    "cc by":             "FREE with credit - monetization OK",
    "cc by-sa":          "FREE with credit (share-alike) - monetization OK",
    "cc by-nd":          "FREE with credit (no derivatives) - monetization OK",
    "cc by-nc":          "CAUTION - non-commercial only, no monetization",
    "cc by-nc-sa":       "CAUTION - non-commercial only, no monetization",
    "cc by-nc-nd":       "CAUTION - non-commercial only, no monetization",
    "all rights reserved": "DO NOT USE - all rights reserved",
    "unknown":           "UNKNOWN - verify manually",
}

musicbrainzngs.set_useragent("MusicLicenseScanner", "1.0",
                             "https://github.com/user/music-license-scanner")


# ==============================================================================
#  FILE DISCOVERY
# ==============================================================================

def get_audio_files(folder):
    """Recursively yield audio file paths, skipping excluded subfolders."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_FOLDERS]
        for f in files:
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS:
                yield os.path.join(root, f)


# ==============================================================================
#  TAG READING
# ==============================================================================

def read_tags(filepath):
    """
    Read audio file tags using mutagen.
    Runs in a thread with a 5-second timeout to handle corrupt/malformed files.
    Always returns plain strings for all values.
    """
    result = {}
    errors = []

    def _read():
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(filepath, easy=True)
            if not audio or not audio.tags:
                return
            result.update({
                k: str(v[0]) if isinstance(v, list) else str(v)
                for k, v in audio.tags.items()
            })
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=5)

    if t.is_alive():
        print("  WARNING: tag reading timed out (corrupt file?) — skipping tags")
        return {}
    if errors:
        return {}
    return result


# ==============================================================================
#  LICENSE DETECTION FROM TAGS AND FILE PATH
# ==============================================================================

def parse_license_from_url(url):
    """Detect a CC license type from a Creative Commons URL."""
    if not url:
        return None
    url = url.lower()
    if "publicdomain/zero" in url or "/cc0" in url:
        return "cc0"
    if "by-nc-nd" in url: return "cc by-nc-nd"
    if "by-nc-sa" in url: return "cc by-nc-sa"
    if "by-nc"    in url: return "cc by-nc"
    if "by-nd"    in url: return "cc by-nd"
    if "by-sa"    in url: return "cc by-sa"
    if "by" in url and "creativecommons" in url:
        return "cc by"
    return None


def guess_license_from_tags(tags):
    """Scan common tag fields for embedded license text."""
    fields = ["license", "comment", "copyright", "description", "organization", "url"]
    combined = " ".join(str(tags.get(f, "")) for f in fields).lower()

    if "cc0" in combined or "creative commons zero" in combined:
        return "cc0"
    if "public domain" in combined:
        return "public domain"
    if "cc by-nc-nd" in combined: return "cc by-nc-nd"
    if "cc by-nc-sa" in combined: return "cc by-nc-sa"
    if "cc by-nc"    in combined: return "cc by-nc"
    if "cc by-nd"    in combined: return "cc by-nd"
    if "cc by-sa"    in combined: return "cc by-sa"
    if "cc by" in combined or "creative commons" in combined:
        return "cc by"
    if "all rights reserved" in combined:
        return "all rights reserved"
    return None


def guess_source_from_tags(tags):
    """Check tag values for mentions of known free music platforms."""
    combined = " ".join(str(v) for v in tags.values()).lower()
    for source in FREE_MUSIC_SOURCES:
        if source in combined:
            return source
    return None


def guess_from_url_tags(tags):
    """
    Check URL-type tags for links to known licensing platforms.
    Returns (license_or_None, source_or_None).
    """
    url_fields = ["website", "url", "www", "woas", "woaf", "wors", "wpub", "comment"]
    for field in url_fields:
        val = str(tags.get(field, "")).lower()
        if not val:
            continue
        if "nocopyrightsounds.com" in val or "ncs.io" in val:
            return "cc by", "ncs"
        if "incompetech.com" in val:
            return "cc by", "incompetech"
        if "musopen.org" in val:
            return "public domain", "musopen"
        if "ccmixter.org" in val:
            return "cc by-nc", "ccmixter"
        if "jamendo.com" in val:
            return None, "jamendo"
        if "freemusicarchive.org" in val:
            return None, "freemusicarchive"
        if "creativecommons.org/licenses" in val:
            return parse_license_from_url(val), "cc url in tags"
    return None, None


def guess_from_filepath(filepath):
    """
    Check the file path and folder names for hints about known free music sources.
    Returns (license_or_None, source_or_None, note).
    """
    path_lower = filepath.lower()
    if "nocopyrightsounds" in path_lower or "\\ncs\\" in path_lower or "/ncs/" in path_lower:
        return "cc by", "ncs", "NCS found in file path"
    if "incompetech" in path_lower:
        return "cc by", "incompetech", "Incompetech found in file path"
    if "freemusicarchive" in path_lower or "\\fma\\" in path_lower or "/fma/" in path_lower:
        return None, "freemusicarchive", "FMA found in file path — verify license"
    if "jamendo" in path_lower:
        return None, "jamendo", "Jamendo found in file path — verify license"
    if "musopen" in path_lower:
        return "public domain", "musopen", "Musopen found in file path"
    return None, None, ""


def check_ncs_artist(artist):
    """Return True if the artist name matches a known NCS roster artist."""
    if not artist:
        return False
    return artist.lower().strip() in NCS_ARTISTS


# ==============================================================================
#  EXTERNAL API LOOKUPS
# ==============================================================================

def fingerprint_and_lookup(filepath):
    """
    Fingerprint the audio file using fpcalc (Chromaprint) and look it up via AcousticID.
    Returns a list of match dicts with keys: score, recording_id, title, artist.
    """
    if ACOUSTID_API_KEY == "YOUR_ACOUSTID_API_KEY_HERE":
        return []
    try:
        raw = acoustid.match(ACOUSTID_API_KEY, filepath)
        matches = []
        for score, rid, title, artist in raw:
            matches.append({
                "score":        round(score, 2),
                "recording_id": rid,
                "title":        title or "",
                "artist":       artist or "",
            })
        return matches
    except Exception as e:
        print(f"  WARNING: AcousticID error — {e}")
        return []


def lookup_musicbrainz(recording_id):
    """
    Look up a MusicBrainz recording by ID.
    Returns (license_or_None, note_string).
    Infers "all rights reserved" if a commercial label is found with no CC tags.
    """
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id,
            includes=["releases", "release-groups", "artist-credits",
                      "tags", "user-tags", "labels"]
        )
        rec  = result.get("recording", {})
        tags = [t["name"].lower() for t in rec.get("tag-list", [])]

        # Explicit CC license in MusicBrainz tags
        for tag in tags:
            for lic in YOUTUBE_SAFE_NOTE:
                if lic in tag:
                    return lic, f"CC tag in MusicBrainz: {tag}"

        # Label present = commercial release
        for release in rec.get("release-list", []):
            for li in release.get("label-info-list", []):
                label_name = li.get("label", {}).get("name", "")
                if label_name:
                    return "all rights reserved", f"Label: {label_name}"

        # In MusicBrainz but no label info — still likely commercial
        if rec.get("release-list"):
            return "all rights reserved", "Found in MusicBrainz (no CC tags, no label)"

        return None, ""
    except Exception:
        return None, ""


def lookup_jamendo(title, artist):
    """
    Search Jamendo for a track by title + artist and return its CC license.
    Returns (license_or_None, source_or_None).
    """
    if JAMENDO_CLIENT_ID == "YOUR_JAMENDO_CLIENT_ID_HERE":
        return None, None
    try:
        params = {
            "client_id": JAMENDO_CLIENT_ID,
            "format":    "json",
            "limit":     3,
            "search":    f"{artist} {title}".strip(),
            "include":   "licenses",
        }
        resp    = requests.get("https://api.jamendo.com/v3.0/tracks/",
                               params=params, timeout=5)
        results = resp.json().get("results", [])
        title_l = title.lower()
        for track in results:
            if title_l in track.get("name", "").lower():
                lic_url = track.get("license_ccurl", "") or track.get("licenseurl", "")
                lic     = parse_license_from_url(lic_url)
                if lic:
                    return lic, "jamendo"
        return None, None
    except Exception:
        return None, None


# ==============================================================================
#  MAIN SCAN LOOP
# ==============================================================================

def scan_library(folder):
    """
    Scan all audio files in folder, determine licenses, and write results to CSV.
    The CSV is written incrementally — results are never lost if the scan is interrupted.
    """
    files = list(get_audio_files(folder))
    total = len(files)
    print(f"\n  Found {total} audio files. Starting scan...\n")

    fieldnames = [
        "file", "title", "artist", "album",
        "license", "source", "safe_to_use", "youtube_verdict",
        "acoustid_match", "confidence", "notes",
    ]

    csvfile = open(OUTPUT_FILE, "w", newline="", encoding="utf-8")
    writer  = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    csvfile.flush()

    results = []

    for i, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        rel_path = os.path.relpath(filepath, folder)
        print(f"[{i}/{total}] {filename}")

        row = {
            "file":           rel_path,
            "title":          "",
            "artist":         "",
            "album":          "",
            "license":        "unknown",
            "source":         "",
            "safe_to_use":    "",
            "youtube_verdict": YOUTUBE_SAFE_NOTE["unknown"],
            "acoustid_match": "",
            "confidence":     "",
            "notes":          "",
        }

        try:
            # --- Step 1: Read file tags ---
            tags         = read_tags(filepath)
            row["title"]  = tags.get("title",  tags.get("TIT2", ""))
            row["artist"] = tags.get("artist", tags.get("TPE1", ""))
            row["album"]  = tags.get("album",  tags.get("TALB", ""))

            # --- Step 2: License from tag text ---
            lic_tags = guess_license_from_tags(tags)
            src_tags = guess_source_from_tags(tags)
            if lic_tags:
                row["license"] = lic_tags
                row["notes"]   = "License text found in file tags"
            if src_tags and not row["source"]:
                row["source"] = src_tags

            # --- Step 3: License from URL-type tags ---
            if row["license"] == "unknown":
                lic_url, src_url = guess_from_url_tags(tags)
                if lic_url:
                    row["license"] = lic_url
                    row["notes"]   = "License from URL tag"
                if src_url and not row["source"]:
                    row["source"] = src_url

            # --- Step 4: NCS artist check from tags ---
            if row["license"] == "unknown" and check_ncs_artist(row["artist"]):
                row["license"] = "cc by"
                row["source"]  = "ncs"
                row["notes"]   = "Artist matches NCS roster — CC BY (credit required)"

            # --- Step 5: File path / folder name hints ---
            if row["license"] == "unknown":
                lic_path, src_path, note_path = guess_from_filepath(filepath)
                if lic_path:
                    row["license"] = lic_path
                    row["notes"]   = note_path
                if src_path and not row["source"]:
                    row["source"] = src_path
                    if not row["notes"]:
                        row["notes"] = note_path

            # --- Step 6: AcousticID fingerprint ---
            if ACOUSTID_API_KEY != "YOUR_ACOUSTID_API_KEY_HERE":
                matches = fingerprint_and_lookup(filepath)
                if matches:
                    best = matches[0]
                    row["acoustid_match"] = (
                        f"{best['artist']} - {best['title']}"
                        if best["artist"] or best["title"] else "?"
                    )
                    row["confidence"] = best["score"]
                    print(f"  -> AcousticID: {row['acoustid_match']} "
                          f"(confidence: {row['confidence']})")

                    # Fill in title/artist if missing from tags
                    if not row["title"]  and best["title"]:  row["title"]  = best["title"]
                    if not row["artist"] and best["artist"]: row["artist"] = best["artist"]

                    # --- Step 7: MusicBrainz license lookup ---
                    if best["recording_id"] and row["license"] == "unknown":
                        mb_lic, mb_note = lookup_musicbrainz(best["recording_id"])
                        if mb_lic:
                            row["license"] = mb_lic
                            row["notes"]   = mb_note

                    # --- Step 8: NCS check on AcousticID artist ---
                    if row["license"] == "unknown" and check_ncs_artist(best["artist"]):
                        row["license"] = "cc by"
                        row["source"]  = "ncs"
                        row["notes"]   = "AcousticID artist matches NCS roster — CC BY"

                    # --- Step 9: Jamendo lookup ---
                    if row["license"] == "unknown" and (row["title"] or row["artist"]):
                        j_lic, j_src = lookup_jamendo(row["title"], row["artist"])
                        if j_lic:
                            row["license"] = j_lic
                            row["source"]  = j_src or "jamendo"
                            row["notes"]   = "License found on Jamendo"

                time.sleep(SLEEP_BETWEEN_REQUESTS)

            # --- Step 10: Final verdict ---
            lic = row["license"].lower().strip()
            row["youtube_verdict"] = YOUTUBE_SAFE_NOTE.get(lic, YOUTUBE_SAFE_NOTE["unknown"])

            if lic in SAFE_FOR_MONETIZED:
                row["safe_to_use"] = "YES - monetization OK"
            elif lic in SAFE_FOR_NONMONETIZED:
                row["safe_to_use"] = "CAUTION - non-commercial only"
            elif lic == "all rights reserved":
                row["safe_to_use"] = "NO - all rights reserved"
            else:
                row["safe_to_use"] = "UNKNOWN - verify manually"

        except Exception as e:
            row["notes"] = f"Error processing file: {e}"
            print(f"  WARNING: error on this file — {e}")

        writer.writerow(row)
        csvfile.flush()
        results.append(row)

    csvfile.close()
    return results


# ==============================================================================
#  SUMMARY
# ==============================================================================

def print_summary(results):
    from collections import Counter
    licenses = Counter(r["license"] for r in results)
    print("\n" + "=" * 56)
    print("  SUMMARY")
    print("=" * 56)
    for lic, count in licenses.most_common():
        verdict = YOUTUBE_SAFE_NOTE.get(lic, YOUTUBE_SAFE_NOTE["unknown"])
        print(f"  {lic:25s}  x{count:<5d}  {verdict}")
    print("=" * 56)
    unknown = sum(1 for r in results if r["license"] == "unknown")
    if unknown:
        print(f"\n  {unknown} tracks could not be identified — verify these manually.")


# ==============================================================================
#  ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    music_folder = sys.argv[1]
    if not os.path.isdir(music_folder):
        print(f"Error: '{music_folder}' is not a valid directory.")
        sys.exit(1)

    if "--exclude" in sys.argv:
        idx = sys.argv.index("--exclude")
        if idx + 1 < len(sys.argv):
            for name in sys.argv[idx + 1].split(","):
                name = name.strip()
                if name:
                    EXCLUDE_FOLDERS.add(name)
            print(f"  Excluding folders: {', '.join(EXCLUDE_FOLDERS)}")

    results = scan_library(music_folder)
    print(f"\n  Report saved to: {OUTPUT_FILE}")
    print_summary(results)
