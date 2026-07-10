# YouTube Language-Safety Checker

Check the latest videos of a YouTube channel for coarse or harmful language in
their spoken-word transcripts, and get a self-contained HTML safety report with
per-video grades and timestamped, clickable flags.

It fetches auto-generated (or human) captions, scans them against an editable,
tiered lexicon, and grades each video **A–F** based on weighted "hits per 1,000
spoken words."

## Features

- **Channel or single video** — pass a handle, channel URL, or a `watch?v=` link.
- **Robust transcript fetching** — tries [`youtube-transcript-api`](https://pypi.org/project/youtube-transcript-api/)
  first, then falls back to [`yt-dlp`](https://pypi.org/project/yt-dlp/) auto-captions.
- **Editable lexicon** — `lexicon.json` holds tiered terms and severity weights; tune it without touching code.
- **Special detectors** — catches caption bleeps (`[ __ ]`) and self-censored words (`f*ck`, `s***`).
- **Timestamped report** — every flag links straight to that moment in the video.
- **Weighted grading** — configurable thresholds; any severe (slur/harmful) hit caps the grade.

## Installation

Requires Python 3.8+.

```bash
pip3 install -r requirements.txt
```

or install the two dependencies directly:

```bash
pip3 install yt-dlp youtube-transcript-api
```

## Web app (phone-friendly)

Prefer a tap-and-check experience — for example, a parent on a phone? Run the
Streamlit app:

```bash
pip3 install -r requirements.txt
streamlit run app.py
```

Open the URL it prints, paste a channel or video link, tap **Check**, and read
the grade. You can also download the full HTML report from the app.

### Check from a phone

- **Same Wi-Fi:** run the command above, then on your phone open
  `http://<your-computer-ip>:8501`. Find the IP with `ipconfig getifaddr en0`
  (macOS) or `hostname -I` (Linux).
- **From anywhere:** deploy free to [Streamlit Community Cloud](https://share.streamlit.io) —
  push this repo to GitHub, create an app pointing at `app.py`, and you get a
  public `https` URL to open or bookmark on any phone. No install needed.

## Command-line usage

```bash
# Latest 3 videos of a channel (default)
python3 yt_language_check.py @ChannelHandle

# A full channel URL
python3 yt_language_check.py https://www.youtube.com/@ChannelHandle

# A single video
python3 yt_language_check.py https://www.youtube.com/watch?v=VIDEO_ID

# Check more videos and choose the output file
python3 yt_language_check.py @ChannelHandle --limit 5 --out report.html
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `channel` | *(required)* | Channel handle (`@name`), channel URL, or a single video URL |
| `--limit` | `3` | Number of latest videos to check (1–10) |
| `--out` | `report_<channel>_<date>.html` | Output HTML report path |
| `--lexicon` | `lexicon.json` next to the script | Path to a custom lexicon file |

The report is written to the current directory by default and can be opened in
any browser.

## How it works

1. **Fetch** the channel's latest `--limit` videos with `yt-dlp` (flat extraction, no downloads).
2. **Retrieve captions** for each video via `youtube-transcript-api`, falling back to `yt-dlp` WebVTT auto-captions.
3. **Scan** each caption snippet against the compiled lexicon (whole-word, case-insensitive) plus the bleep/self-censor detectors.
4. **Grade** by summing severity weights, normalizing per 1,000 words, and applying the thresholds in `lexicon.json`.
5. **Render** a single HTML file with an overall grade, a per-video summary table, and per-video flag tables linking to timestamps.

## Customizing the lexicon

`lexicon.json` is plain, editable JSON. Each tier has a `name`, a `severity`
weight, and a list of `terms` (multi-word phrases allowed). Matching is
case-insensitive and whole-word.

```json
{
  "tiers": [
    { "name": "Moderate profanity", "severity": 3, "terms": ["damn", "hell", "..."] }
  ],
  "grading": {
    "thresholds": { "A": 1, "B": 3, "C": 8, "D": 15 },
    "labels": {
      "A": "Clean — family-friendly",
      "B": "Mild — occasional light language",
      "C": "Moderate — some coarse language",
      "D": "Strong — frequent coarse language",
      "F": "Explicit — heavy or harmful language"
    }
  }
}
```

**Severity weights** (defaults):

| Weight | Meaning |
|--------|---------|
| 1 | Mild insult / gamer trash-talk |
| 3 | Moderate profanity |
| 6 | Strong profanity, sexual, or a bleeped word |
| 12 | Slur / harmful trolling |

**Grading:** the score is `sum(severity) / words * 1000`. Grades follow the
`thresholds` map. Any single severity-12 hit caps the grade at **D**; three or
more force an **F**. Each grade carries a descriptive label (shown in the
console and report) that you can reword via `grading.labels`:

| Grade | Default description |
|:-----:|---------------------|
| A | Clean — family-friendly |
| B | Mild — occasional light language |
| C | Moderate — some coarse language |
| D | Strong — frequent coarse language |
| F | Explicit — heavy or harmful language |

## Notes & limitations

- Only English captions are checked (`en`, `en-US`, `en-GB`, `en-CA`, `en-AU`).
- Videos without available captions are listed as skipped in the report.
- Auto-caption transcription is imperfect, so flags reflect what YouTube heard,
  not necessarily what was said.

## License

Released under the [MIT License](LICENSE).
