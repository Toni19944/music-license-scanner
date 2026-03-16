# Music License Scanner

A Python tool that scans your local music library and attempts to determine the license of each track — so you know what's safe to use in YouTube videos or other content.

It reads file tags, checks artist names against known free music rosters (like NCS), fingerprints audio via AcousticID, cross-references MusicBrainz for label and license data, and optionally queries the Jamendo API. Results are saved to a CSV you can filter in Excel or Google Sheets.

---

## What it detects

| Result | Meaning |
|---|---|
| `YES - monetization OK` | CC0, CC BY, Public Domain — fully free to use |
| `CAUTION - non-commercial only` | CC BY-NC variants — free but no ads/monetization |
| `NO - all rights reserved` | Commercial release — do not use |
| `UNKNOWN - verify manually` | Could not determine — check manually |

---

## Requirements

- Python 3.8+
- `fpcalc` binary (Chromaprint) — for audio fingerprinting
- A free AcousticID API key
- (Optional) A free Jamendo Client ID

---

## Installation

**1. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**2. Install fpcalc (Chromaprint)**

| OS | Command |
|---|---|
| Windows | Download from [acoustid.org/chromaprint](https://acoustid.org/chromaprint), extract `fpcalc.exe`, add its folder to your system PATH |
| macOS | `brew install chromaprint` |
| Linux | `sudo apt install libchromaprint-tools` |

To verify it's working, open a terminal and run:
```bash
fpcalc
```
If it prints `ERROR: No input files` — that's correct and means it's installed and found. If it says `command not found` or similar, it's not in your PATH yet.

**3. Get a free AcousticID API key**

1. Sign up at [acoustid.org](https://acoustid.org/login)
2. Go to [acoustid.org/applications](https://acoustid.org/applications)
3. Click **New Application**, give it any name
4. Copy the API key

> Note: there are two keys on AcousticID — make sure you use the **Application API key**, not the "user API key for submitting fingerprints".

**4. (Optional) Get a free Jamendo Client ID**

1. Sign up at [devportal.jamendo.com](https://devportal.jamendo.com)
2. Create a new app, copy the Client ID

**5. Add your keys to the script**

Open `music_license_scanner.py` and fill in:

```python
ACOUSTID_API_KEY  = "your_key_here"
JAMENDO_CLIENT_ID = "your_client_id_here"  # optional
```

---

## Usage

**Windows — double-click runner:**

Edit `scan_music.bat` in Notepad, set your music folder path, and double-click to run.

**Command line:**

```bash
python music_license_scanner.py "F:\Music"
```

**With folder exclusions:**

```bash
python music_license_scanner.py "F:\Music" --exclude "Podcasts,Audiobooks,SFX"
```

Folder names with spaces work fine — just separate multiple folders with a comma.

---

## Output

The scan produces `music_license_report.csv` in the same folder as the script. It is written **incrementally** — one row per file as it goes — so results are never lost if the scan is interrupted.

### CSV columns

| Column | Description |
|---|---|
| `file` | Relative path to the audio file |
| `title` | Track title (from tags or AcousticID) |
| `artist` | Artist name |
| `album` | Album name |
| `license` | Detected license (e.g. `cc by`, `all rights reserved`, `unknown`) |
| `source` | Where the license info came from (e.g. `ncs`, `jamendo`, `musicbrainz`) |
| `safe_to_use` | Plain-English verdict for easy filtering |
| `youtube_verdict` | Detailed verdict with monetization guidance |
| `acoustid_match` | Artist and title identified by AcousticID fingerprinting |
| `confidence` | AcousticID match confidence score (0–1) |
| `notes` | How the license was determined, or any warnings |

### Filtering in Excel

1. Open the CSV → click any cell → **Data → Filter**
2. Click the dropdown arrow on the `safe_to_use` column
3. Select only `YES - monetization OK` (or include `CAUTION` if your video is non-monetized)

---

## How it works (step by step)

For each audio file, the scanner runs these steps in order and stops as soon as a license is found:

1. **Read file tags** — checks `license`, `comment`, `copyright`, and URL fields for embedded license text
2. **URL tag check** — if a tag links to jamendo.com, incompetech.com, ncs.io etc., the license is inferred from that
3. **NCS artist check** — if the tagged artist matches the NCS roster, it's marked as CC BY
4. **File path check** — folder names like `NCS` or `incompetech` are also detected
5. **AcousticID fingerprint** — audio is fingerprinted and matched against the AcousticID database
6. **MusicBrainz lookup** — the identified recording is looked up for label and license data; commercial label = all rights reserved
7. **Jamendo API** — searches Jamendo by artist + title for CC license info

---

## Performance

- Expect roughly **1–3 seconds per file** when fingerprinting is enabled (fpcalc + API calls)
- A library of 3000 songs will take **1–2 hours** to fully scan
- The `SLEEP_BETWEEN_REQUESTS` setting (default 0.5s) keeps API usage polite — don't set it to 0

---

## Limitations

- **Results are best-effort, not legal advice.** Always verify manually before using a track in commercial or monetized content.
- AcousticID and MusicBrainz coverage varies — obscure or poorly tagged tracks may not be identified.
- The NCS artist list is manually maintained and may not be fully up to date.
- Tracks with no tags, no AcousticID match, and no Jamendo match will remain `UNKNOWN`.

---

## License

MIT — free to use, modify, and share.
