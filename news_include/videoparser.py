from youtube_transcript_api import YouTubeTranscriptApi
from re import match, sub
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
            transcript_list = api.fetch(video_id, languages=['ru', 'kz', 'en'])

            formatted_transcript = ""

            for snippet in transcript_list:

                start_seconds_float = snippet.start

                timestamp = int(start_seconds_float)

                formatted_transcript += f"t={timestamp} {snippet.text}\n"

            return formatted_transcript

        except Exception as e:
            print(f"Не удалось получить транскрипт для video_id '{video_id}': {e}")
            return None

    @staticmethod
    def postprocess(text, url):
        pattern = r"\[t=(\d+)\]"
        replacement = fr"[Таймкод]({url}&t=\1)"
        result = sub(pattern, replacement, text)

        return result
