#!/usr/bin/env python3
"""
YouTube Language-Safety Checker — Streamlit web app
===================================================
A phone-friendly front-end for yt_language_check.py. Paste a channel or video
link and get an at-a-glance safety grade with timestamped flags — designed so a
parent can check a channel from a phone.

Run:
    pip3 install -r requirements.txt
    streamlit run app.py
"""
import html
import os
import sys
import tempfile

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:  # ensure the sibling module imports under any launcher
    sys.path.insert(0, HERE)

import yt_language_check as yt  # noqa: E402  (import after sys.path bootstrap)

st.set_page_config(page_title="YouTube Language Check", page_icon="🎬", layout="centered")

# ----------------------------------------------------------------- cached helpers

@st.cache_resource
def get_lexicon():
    """Load and compile the lexicon once (compiled regexes aren't serializable)."""
    return yt.load_lexicon(os.path.join(HERE, "lexicon.json"))


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_videos(channel, limit):
    return yt.get_channel_videos(channel, limit)


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_transcript(video_id):
    return yt.fetch_transcript(video_id)


def grade_badge(letter, size="2em"):
    color = yt.GRADE_COLORS.get(letter, "#555")
    return (f'<span style="display:inline-block;background:{color};color:#fff;'
            f'font-weight:700;font-size:{size};line-height:1;padding:.12em .5em;'
            f'border-radius:.2em">{html.escape(letter)}</span>')

# ----------------------------------------------------------------- analysis

def run_check(channel, limit):
    """Fetch + analyze videos, returning CLI-compatible result dicts."""
    lex, compiled = get_lexicon()
    with st.spinner("Finding the channel’s latest videos…"):
        videos = fetch_videos(channel, limit)  # raises yt.NotFoundError on a bad handle/link
    results = []
    with st.status("Checking videos…", expanded=True) as status:
        for v in videos:
            st.write(f"• {v['title']}")
            snippets = fetch_transcript(v["id"])
            if not snippets:
                results.append({**v, "error": "No English transcript/captions available"})
                continue
            hits, words = yt.analyze_snippets(snippets, lex, compiled)
            letter, score = yt.grade(hits, words, lex)
            results.append({**v, "hits": hits, "words": words, "grade": letter, "score": score})
        status.update(label=f"Checked {len(videos)} video(s)", state="complete", expanded=False)
    return results

# ----------------------------------------------------------------- rendering

def render_overall(channel, results):
    lex, _ = get_lexicon()
    all_hits = [h for v in results for h in v.get("hits", [])]
    all_words = sum(v.get("words", 0) for v in results)
    if not all_words:
        st.warning("No transcripts were available for these videos, so no grade could be computed.")
        return
    letter, score = yt.grade(all_hits, all_words, lex)
    label = yt.grade_label(letter, lex)
    st.markdown(
        f'<div style="text-align:center;margin:.5em 0 1em">'
        f'{grade_badge(letter, "3.6em")}'
        f'<div style="font-size:1.25em;font-weight:600;margin-top:.35em">{html.escape(label)}</div>'
        f'<div style="color:#888;font-size:.9em">{score} weighted hits per 1,000 words · '
        f'{len(all_hits)} flags · {len(results)} videos</div></div>',
        unsafe_allow_html=True)


def render_videos(results):
    lex, _ = get_lexicon()
    for v in results:
        st.divider()
        if v.get("error"):
            st.markdown(f"**{html.escape(v['title'])}**")
            st.caption(f"⚠️ {v['error']}")
            continue
        g = v["grade"]
        label = yt.grade_label(g, lex)
        c1, c2 = st.columns([1, 4])
        with c1:
            st.markdown(grade_badge(g, "1.9em"), unsafe_allow_html=True)
        with c2:
            st.markdown(f"**[{html.escape(v['title'])}](https://youtu.be/{v['id']})**")
            st.caption(f"{label} · {len(v['hits'])} flags · {v['words']:,} words")
        if v["hits"]:
            with st.expander(f"Show {len(v['hits'])} flagged moments"):
                rows = ["| Time | Term | Severity | Context |", "|:--|:--|:--|:--|"]
                for h in sorted(v["hits"], key=lambda x: x["start"]):
                    t = yt.fmt_time(h["start"])
                    link = f'https://youtu.be/{v["id"]}?t={int(h["start"])}'
                    term = h["term"].replace("`", "")
                    ctx = (h["excerpt"].replace("|", "\\|").replace("*", "\\*")
                           .replace("\n", " ").strip())
                    rows.append(f'| [{t}]({link}) | `{term}` | {h["severity"]} — '
                                f'{html.escape(h["tier"])} | …{html.escape(ctx)}… |')
                st.markdown("\n".join(rows))


def offer_download(channel, results):
    lex, _ = get_lexicon()
    tmp = os.path.join(tempfile.gettempdir(), "language_report.html")
    yt.build_report(channel, results, tmp, lex)
    with open(tmp, "rb") as f:
        data = f.read()
    safe = "".join(ch if ch.isalnum() or ch in "@-_" else "_" for ch in channel)[:40]
    st.download_button("⬇️ Download full HTML report", data,
                       file_name=f"report_{safe}.html", mime="text/html",
                       use_container_width=True)

# ----------------------------------------------------------------- UI

st.title("🎬 YouTube Language Check")
st.write("Check a channel's latest videos for coarse or harmful language. "
         "Paste a channel handle, a channel link, or a single video link.")

with st.form("check"):
    channel = st.text_input(
        "YouTube channel or video",
        placeholder="@ChannelHandle · youtube.com/@Handle · youtu.be/VIDEO_ID")
    limit = st.slider("How many recent videos to check", 1, 10, 3)
    submitted = st.form_submit_button("Check", type="primary", use_container_width=True)

if submitted:
    channel = (channel or "").strip()
    if not channel:
        st.warning("Please enter a channel handle or video link first.")
    else:
        try:
            st.session_state["results"] = run_check(channel, limit)
            st.session_state["channel"] = channel
        except yt.NotFoundError as e:
            st.session_state.pop("results", None)
            st.error(f"🔎 {e}")
        except Exception as e:  # network / no yt-dlp / unexpected
            st.session_state.pop("results", None)
            st.error(f"Something went wrong while checking that input: {e}")

if st.session_state.get("results"):
    channel = st.session_state["channel"]
    results = st.session_state["results"]
    render_overall(channel, results)
    render_videos(results)
    if any("grade" in v for v in results):
        st.divider()
        offer_download(channel, results)

with st.expander("How grades work"):
    lex, _ = get_lexicon()
    labels = lex.get("grading", {}).get("labels", yt.GRADE_LABELS)
    st.markdown("**Grades** are tuned for kids under 10 — words not okay in class "
                "pull the grade down fast. They start from weighted flags per 1,000 "
                "spoken words, then a single slur / harmful word forces an **F** and "
                "any strong-profanity word caps the grade at **D**.")
    st.markdown("\n".join(f"- **{g}** — {labels.get(g, '')}" for g in ["A", "B", "C", "D", "F"]))
    st.markdown("**Severity weights:** 1 mild insult · 3 moderate profanity · "
                "6 strong profanity or bleeped word · 12 slur / harmful. "
                "Edit `lexicon.json` to tune what gets flagged.")

st.caption("Auto-captions are imperfect — flags reflect what YouTube transcribed, "
           "not always what was said.")
