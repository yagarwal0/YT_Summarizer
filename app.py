import streamlit as st
from dotenv import load_dotenv
import os
from urllib.parse import urlparse, parse_qs
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Load environment variables
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Prompt template
prompt = """You are a YouTube video summarizer. 
You will be taking the transcript text and summarizing the entire video. 
Provide the important summary in bullet points (around 250 words). 
Here is the transcript: 
"""

# Function to extract video ID from various YouTube URL formats
def get_video_id(url: str):
    parsed_url = urlparse(url)

    if parsed_url.hostname == "youtu.be":
        return parsed_url.path[1:]
    if parsed_url.hostname in ["www.youtube.com", "youtube.com"]:
        if parsed_url.path == "/watch":
            return parse_qs(parsed_url.query).get("v", [None])[0]
        if parsed_url.path.startswith("/shorts/"):
            return parsed_url.path.split("/")[2]
    return None

# Function to fetch transcript
def extract_transcript_details(youtube_video_url):
    try:
        video_id = get_video_id(youtube_video_url)
        if not video_id:
            st.error("Invalid YouTube URL. Please enter a valid link.")
            return None

        transcript_text = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = " ".join([i["text"] for i in transcript_text])
        return transcript

    except (TranscriptsDisabled, NoTranscriptFound):
        st.warning("Transcript not available for this video.")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None

# Function to generate summary using Gemini
def generate_gemini_content(transcript_text, prompt):
    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content([
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript_text}
        ])
        return response.text
    except Exception as e:
        st.error(f"Error while generating summary: {e}")
        return None

# Streamlit UI
st.title("🎬 YouTube Transcript to Detailed Notes Converter")

youtube_link = st.text_input("Enter YouTube video URL")

if youtube_link:
    video_id = get_video_id(youtube_link)
    if video_id:
        st.image(f"http://img.youtube.com/vi/{video_id}/0.jpg", use_column_width=True)

if st.button("Get Detailed Notes"):
    with st.spinner("Fetching transcript and generating summary..."):
        transcript_text = extract_transcript_details(youtube_link)

        if transcript_text:
            summary = generate_gemini_content(transcript_text, prompt)
            if summary:
                st.markdown("## 📝 Detailed Notes")
                st.write(summary)
