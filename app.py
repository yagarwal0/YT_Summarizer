import os
import re
from urllib.parse import urlparse, parse_qs

import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

# youtube-transcript-api imports (handle various exception types gracefully)
from youtube_transcript_api import YouTubeTranscriptApi
try:
    # These may not exist in very old versions, so import defensively
    from youtube_transcript_api._errors import (
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
        TooManyRequests,
    )
except Exception:
    # Fallbacks if running on an older version
    class TranscriptsDisabled(Exception): ...
    class NoTranscriptFound(Exception): ...
    class VideoUnavailable(Exception): ...
    class TooManyRequests(Exception): ...

# ---------------------------
# Setup
# ---------------------------
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

st.set_page_config(page_title="YouTube Transcript → Notes", page_icon="📝")
st.title("🎬 YouTube Transcript to Detailed Notes Converter")

if not API_KEY:
    st.error("Missing GOOGLE_API_KEY in your environment (.env). Please set it and restart.")
    st.stop()

genai.configure(api_key=API_KEY)

PROMPT = (
    "You are a YouTube video summarizer. "
    "Summarize the entire transcript into clear bullet points (~250 words). "
    "Focus on key ideas, steps, definitions, and any takeaways.\n\n"
    "Transcript:\n"
)

# ---------------------------
# Helpers
# ---------------------------
def get_video_id(url: str):
    """
    Extract a YouTube video ID from many common URL formats.
    Works for:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - plus query params like &t=123s etc.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        # youtu.be/<id>
        if host in ("youtu.be", "www.youtu.be"):
            vid = parsed.path.lstrip("/").split("/")[0]
            if len(vid) == 11:
                return vid

        # youtube.com variants
        if "youtube" in host:
            # /watch?v=<id>
            if parsed.path == "/watch":
                vid = parse_qs(parsed.query).get("v", [None])[0]
                if vid and len(vid) == 11:
                    return vid
            # /shorts/<id>
            if parsed.path.startswith("/shorts/"):
                parts = parsed.path.split("/")
                if len(parts) >= 3 and len(parts[2]) == 11:
                    return parts[2]
            # /embed/<id>
            if parsed.path.startswith("/embed/"):
                parts = parsed.path.split("/")
                if len(parts) >= 3 and len(parts[2]) == 11:
                    return parts[2]

        # Regex fallback (last resort)
        m = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


@st.cache_data(show_spinner=False, ttl=3600)
def extract_transcript_text(youtube_url: str) -> str | None:
    """
    Fetch transcript text using whatever API the installed library supports.
    Tries:
      1) YouTubeTranscriptApi.get_transcript (if available)
      2) YouTubeTranscriptApi.list_transcripts + find/translate to English
    Returns a single string or None on failure.
    """
    video_id = get_video_id(youtube_url)
    if not video_id:
        st.error("Invalid YouTube URL. Please enter a valid video link.")
        return None

    languages = ["en", "en-US", "en-GB"]

    try:
        # Path A: get_transcript available
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            try:
                items = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
                return " ".join(chunk.get("text", "") for chunk in items)
            except (NoTranscriptFound, TranscriptsDisabled):
                # fall through to try list_transcripts approach
                pass

        # Path B: list_transcripts available
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            tl = YouTubeTranscriptApi.list_transcripts(video_id)

            # Prefer direct English transcript
            try:
                tr = tl.find_transcript(languages)
                return " ".join(chunk.get("text", "") for chunk in tr.fetch())
            except Exception:
                # Try translating first available transcript to English
                for tr in tl:
                    try:
                        tr_en = tr.translate("en")
                        return " ".join(chunk.get("text", "") for chunk in tr_en.fetch())
                    except Exception:
                        # Fall back to whatever transcript exists if translation fails
                        try:
                            return " ".join(chunk.get("text", "") for chunk in tr.fetch())
                        except Exception:
                            continue

            # If we reach here, nothing worked
            raise NoTranscriptFound(video_id)

        # Neither method exists (very old/odd install)
        st.error(
            "Your installed `youtube-transcript-api` does not expose "
            "`get_transcript` or `list_transcripts`.\n\n"
            "Please update it:\n"
            "  pip install -U youtube-transcript-api"
        )
        return None

    except (NoTranscriptFound, TranscriptsDisabled):
        st.warning("Transcript is not available for this video.")
        return None
    except (VideoUnavailable, TooManyRequests) as e:
        st.error(f"{type(e).__name__}: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error while fetching transcript: {e}")
        return None


def generate_summary_with_gemini(transcript_text: str) -> str | None:
    """
    Generate a ~250-word bullet summary using Gemini.
    Uses a simple string input for maximum SDK compatibility.
    Tries a couple of model names for broader support.
    """
    if not transcript_text:
        return None

    for model_name in ["gemini-1.5-flash", "gemini-pro"]:
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(PROMPT + transcript_text)
            if hasattr(resp, "text") and resp.text:
                return resp.text
            # Some SDK versions return candidates; try a safe fallback:
            if getattr(resp, "candidates", None):
                parts = []
                for c in resp.candidates:
                    try:
                        for p in c.content.parts:
                            if getattr(p, "text", None):
                                parts.append(p.text)
                    except Exception:
                        continue
                if parts:
                    return "\n".join(parts)
        except Exception as e:
            # Try next model name
            last_err = e
            continue

    st.error("Gemini summarization failed. Please check your API key and model access.")
    return None


# ---------------------------
# UI
# ---------------------------
youtube_link = st.text_input("Enter YouTube video URL")

if youtube_link:
    vid = get_video_id(youtube_link)
    if vid:
        st.image(f"http://img.youtube.com/vi/{vid}/0.jpg", use_container_width=True)

if st.button("Get Detailed Notes"):
    with st.spinner("Fetching transcript and generating summary..."):
        transcript_text = extract_transcript_text(youtube_link)
        if transcript_text:
            summary = generate_summary_with_gemini(transcript_text)
            if summary:
                st.markdown("## 📝 Detailed Notes")
                st.write(summary)
            else:
                st.error("Failed to generate summary from the transcript.")
