#!/usr/bin/env python3
"""
YouTube Language-Safety Checker
================================
Checks the 3 latest videos of a YouTube channel for coarse/naughty language
in their spoken-word transcripts, and produces an HTML safety report.

Setup (one time):
    pip3 install yt-dlp youtube-transcript-api

Usage:
    python3 yt_language_check.py @ChannelHandle
    python3 yt_language_check.py https://www.youtube.com/@ChannelHandle
    python3 yt_language_check.py https://www.youtube.com/watch?v=VIDEO_ID
    python3 yt_language_check.py @ChannelHandle --limit 3 --out report.html

The lexicon (lexicon.json, next to this script) is editable: add/remove
terms and change severity weights to tune what gets flagged.
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import tempfile

# ---------------------------------------------------------------- lexicon

def load_lexicon(path):
    with open(path, "r", encoding="utf-8") as f:
        lex = json.load(f)
    compiled = []
    for tier in lex["tiers"]:
        for term in tier["terms"]:
            pat = r"\b" + re.escape(term).replace(r"\ ", " ").replace(" ", r"\s+") + r"\b"
            compiled.append({
                "term": term,
                "tier": tier["name"],
                "severity": tier["severity"],
                "re": re.compile(pat, re.IGNORECASE),
            })
    return lex, compiled

BLEEP_RE = re.compile(r"\[\s*_+\s*\]")            # auto-caption bleeps: [ __ ]
CENSORED_RE = re.compile(r"\b\w+\*+\w*\b")         # self-censored: f*ck, s***

# ---------------------------------------------------------------- fetching

def get_channel_videos(url, limit):
    """Return list of {id, title} for the channel's latest `limit` videos."""
    try:
        import yt_dlp
    except ImportError:
        sys.exit("Missing dependency. Run: pip3 install yt-dlp youtube-transcript-api")

    url = normalize_url(url)
    opts = {
        "extract_flat": True,
        "playlist_items": f"1:{limit}",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("entries") is not None:
        entries = list(info["entries"])[:limit]
        return [{"id": e["id"], "title": e.get("title") or e["id"]} for e in entries if e]
    # single video
    return [{"id": info["id"], "title": info.get("title") or info["id"]}]


def normalize_url(url):
    url = url.strip()
    if "watch?v=" in url or "youtu.be/" in url:
        return url
    if url.startswith("@"):
        url = "https://www.youtube.com/" + url
    if not url.startswith("http"):
        url = "https://www.youtube.com/@" + url
    if not url.rstrip("/").endswith(("/videos", "/shorts", "/streams")):
        url = url.rstrip("/") + "/videos"
    return url


def fetch_transcript(video_id):
    """Return list of {text, start} snippets, or None if unavailable.
    Tries youtube-transcript-api first, then yt-dlp auto-captions."""
    snippets = _transcript_via_api(video_id)
    if snippets is None:
        snippets = _transcript_via_ytdlp(video_id)
    return snippets


def _transcript_via_api(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    langs = ["en", "en-US", "en-GB", "en-CA", "en-AU"]
    try:
        try:  # new API (>= 1.0)
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=langs)
            return [{"text": s.text, "start": s.start} for s in fetched]
        except AttributeError:  # old API
            data = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
            return [{"text": d["text"], "start": d["start"]} for d in data]
    except Exception as e:
        print(f"    transcript API failed ({type(e).__name__}), trying yt-dlp captions...")
        return None


def _transcript_via_ytdlp(video_id):
    try:
        import yt_dlp
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*", "en"],
            "subtitlesformat": "vtt",
            "outtmpl": os.path.join(tmp, "%(id)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception:
            return None
        for name in os.listdir(tmp):
            if name.endswith(".vtt"):
                with open(os.path.join(tmp, name), encoding="utf-8") as f:
                    return parse_vtt(f.read())
    return None


TIME_RE = re.compile(r"(\d+):(\d\d):(\d\d)\.(\d\d\d)\s*-->")

def parse_vtt(vtt_text):
    """Parse WebVTT into {text, start} snippets, dropping repeated lines
    (YouTube auto-captions repeat text across cues)."""
    snippets, last_text = [], None
    start = 0.0
    for line in vtt_text.splitlines():
        m = TIME_RE.match(line.strip())
        if m:
            h, mi, s, ms = map(int, m.groups())
            start = h * 3600 + mi * 60 + s + ms / 1000
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or "-->" in text or text.isdigit() or text == "WEBVTT":
            continue
        if text != last_text:
            snippets.append({"text": text, "start": start})
            last_text = text
    return snippets

# ---------------------------------------------------------------- analysis

def analyze_snippets(snippets, lex, compiled):
    """Return (hits, word_count). Each hit: term, label, severity, start, excerpt."""
    hits, words = [], 0
    special = lex.get("special", {})
    for sn in snippets:
        text = sn["text"]
        words += len(text.split())
        for c in compiled:
            for _ in c["re"].finditer(text):
                hits.append({
                    "term": c["term"], "label": c["term"], "tier": c["tier"],
                    "severity": c["severity"], "start": sn["start"], "excerpt": text,
                })
        if "bleeped_caption" in special:
            for _ in BLEEP_RE.finditer(text):
                sp = special["bleeped_caption"]
                hits.append({
                    "term": "[ __ ]", "label": sp["label"], "tier": "Bleeped",
                    "severity": sp["severity"], "start": sn["start"], "excerpt": text,
                })
        if "censored_word" in special:
            for m in CENSORED_RE.finditer(text):
                sp = special["censored_word"]
                hits.append({
                    "term": m.group(0), "label": sp["label"], "tier": "Censored",
                    "severity": sp["severity"], "start": sn["start"], "excerpt": text,
                })
    return hits, words


def grade(hits, words, lex):
    """Return (letter, weighted_score_per_1000_words)."""
    thresholds = lex.get("grading", {}).get("thresholds", {"A": 1, "B": 3, "C": 8, "D": 15})
    score = sum(h["severity"] for h in hits) / max(words, 1) * 1000
    severe = sum(1 for h in hits if h["severity"] >= 12)
    if score < thresholds["A"]:
        letter = "A"
    elif score < thresholds["B"]:
        letter = "B"
    elif score < thresholds["C"]:
        letter = "C"
    elif score < thresholds["D"]:
        letter = "D"
    else:
        letter = "F"
    if severe >= 3:
        letter = "F"
    elif severe >= 1 and letter in ("A", "B", "C"):
        letter = "D"
    return letter, round(score, 2)

# ---------------------------------------------------------------- report

GRADE_COLORS = {"A": "#2e7d32", "B": "#7cb342", "C": "#f9a825", "D": "#ef6c00", "F": "#c62828"}
SEV_COLORS = {1: "#f9a825", 3: "#ef6c00", 6: "#c62828", 12: "#6a1b9a"}

def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_report(channel, videos, out_path):
    """videos: list of {id, title, grade, score, words, hits, error}"""
    all_hits = [h for v in videos for h in v.get("hits", [])]
    all_words = sum(v.get("words", 0) for v in videos)
    parts = [f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Language Safety Report — {html.escape(channel)}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;margin:2em auto;padding:0 1em;color:#222}}
 .badge{{display:inline-block;color:#fff;font-size:2.2em;font-weight:700;padding:.2em .6em;border-radius:.25em}}
 .sev{{color:#fff;padding:.1em .5em;border-radius:.25em;font-size:.85em;white-space:nowrap}}
 table{{border-collapse:collapse;width:100%;margin:.8em 0}}
 td,th{{border:1px solid #ddd;padding:.45em .6em;text-align:left;vertical-align:top;font-size:.95em}}
 th{{background:#f5f5f5}} .muted{{color:#777}} h2{{margin-top:1.6em}}
 .excerpt{{color:#555;font-style:italic}}
</style></head><body>
<h1>Language Safety Report</h1>
<p><b>Channel / input:</b> {html.escape(channel)}<br>
<b>Videos checked:</b> {len(videos)} &nbsp;|&nbsp; <b>Words analyzed:</b> {all_words:,}<br>
<b>Generated:</b> {datetime.date.today().isoformat()}</p>"""]

    if all_words:
        from_hits = grade_from(all_hits, all_words, videos)
        letter, score = from_hits
        parts.append(
            f'<p><span class="badge" style="background:{GRADE_COLORS[letter]}">{letter}</span> '
            f'&nbsp;overall — {score} weighted hits per 1,000 words, {len(all_hits)} total flags</p>')

    parts.append("<h2>Videos</h2><table><tr><th>Video</th><th>Grade</th><th>Flags</th><th>Words</th></tr>")
    for v in videos:
        if v.get("error"):
            parts.append(f"<tr><td>{html.escape(v['title'])}</td>"
                         f"<td colspan=3 class=muted>{html.escape(v['error'])}</td></tr>")
        else:
            g = v["grade"]
            parts.append(
                f'<tr><td><a href="https://youtu.be/{v["id"]}">{html.escape(v["title"])}</a></td>'
                f'<td><b style="color:{GRADE_COLORS[g]}">{g}</b></td>'
                f'<td>{len(v["hits"])}</td><td>{v["words"]:,}</td></tr>')
    parts.append("</table>")

    for v in videos:
        if v.get("error") or not v.get("hits"):
            continue
        parts.append(f'<h2>{html.escape(v["title"])}</h2>'
                     "<table><tr><th>Time</th><th>Term</th><th>Severity</th><th>Context</th></tr>")
        for h in sorted(v["hits"], key=lambda x: x["start"]):
            color = SEV_COLORS.get(h["severity"], "#555")
            link = f'https://youtu.be/{v["id"]}?t={int(h["start"])}'
            parts.append(
                f'<tr><td><a href="{link}">{fmt_time(h["start"])}</a></td>'
                f'<td><b>{html.escape(h["term"])}</b></td>'
                f'<td><span class="sev" style="background:{color}">{h["severity"]} — {html.escape(h["tier"])}</span></td>'
                f'<td class="excerpt">…{html.escape(h["excerpt"])}…</td></tr>')
        parts.append("</table>")

    parts.append('<p class="muted">Severity weights: 1 mild insult / trash-talk · 3 moderate profanity · '
                 '6 strong profanity or bleeped word · 12 slur / harmful trolling. '
                 'Edit lexicon.json to tune.</p></body></html>')
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def grade_from(all_hits, all_words, videos):
    lex_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lexicon.json")
    with open(lex_path, encoding="utf-8") as f:
        lex = json.load(f)
    return grade(all_hits, all_words, lex)

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Check a YouTube channel's latest videos for coarse language.")
    ap.add_argument("channel", help="Channel handle (@name), channel URL, or a single video URL")
    ap.add_argument("--limit", type=int, default=3, help="Number of latest videos to check (default 3)")
    ap.add_argument("--out", default=None, help="Output HTML report path")
    ap.add_argument("--lexicon", default=None, help="Path to lexicon.json")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    lex_path = args.lexicon or os.path.join(here, "lexicon.json")
    lex, compiled = load_lexicon(lex_path)

    print(f"Fetching latest {args.limit} videos for {args.channel} ...")
    videos = get_channel_videos(args.channel, args.limit)
    results = []
    for v in videos:
        print(f"  • {v['title']}")
        snippets = fetch_transcript(v["id"])
        if not snippets:
            results.append({**v, "error": "No English transcript/captions available"})
            print("    no transcript available, skipped")
            continue
        hits, words = analyze_snippets(snippets, lex, compiled)
        letter, score = grade(hits, words, lex)
        results.append({**v, "hits": hits, "words": words, "grade": letter, "score": score})
        print(f"    {words:,} words, {len(hits)} flags → grade {letter}")

    safe = re.sub(r"[^\w@-]+", "_", args.channel)[:40]
    out = args.out or os.path.join(os.getcwd(), f"report_{safe}_{datetime.date.today()}.html")
    build_report(args.channel, results, out)
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
