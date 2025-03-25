from youtube_transcript_api import YouTubeTranscriptApi
from re import match
import os
from dotenv import load_dotenv

load_dotenv()


class VideoParser:

    @staticmethod
    def getytid(text):
        m = match(r'^https?://(?:www\.)?youtube\.com/watch\?v=([^\s&]+)', text)
        if m:
            return m.group(1)
        return False

    @staticmethod
    def parse(video_id):
        api = YouTubeTranscriptApi()
        try:
            transcript = api.fetch(video_id, languages=['ru', 'kz', 'en'])
            text = ""
            for snippet in transcript:
                text += f"{snippet.text}\n"
            return text
        except Exception as e:
            print("Не удалось получить транскрипт:", e)
            return None
