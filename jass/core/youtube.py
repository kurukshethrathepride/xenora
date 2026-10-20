import asyncio
import os
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import aiohttp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import VideosSearch, Playlist

API_URL = os.environ.get("ARC_API_URL", "https://api.arcmusic.fun").rstrip("/")
API_KEY = os.environ.get("ARC_API_KEY", "ARC713d225dfd9efa60c8dca4")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

_in_progress: dict = {}


def time_to_seconds(time):
    stringt = str(time)
    return sum(int(x) * 60 ** i for i, x in enumerate(reversed(stringt.split(":"))))


def find_file(video_id: str, video: bool = False) -> str:
    exts = [".mp4", ".webm", ".mkv"] if video else [".mp3", ".webm", ".m4a", ".opus"]
    for ext in exts:
        path = DOWNLOAD_DIR / f"{video_id}{ext}"
        if path.exists() and path.stat().st_size > 0:
            return str(path)
    return None


async def _arc_download(video_id: str, video: bool = False) -> str:
    ext = "mp4" if video else "mp3"
    file_path = DOWNLOAD_DIR / f"{video_id}.{ext}"

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_URL}/youtube/v2/download",
                    params={"api_key": API_KEY, "query": video_id, "isVideo": str(video).lower()},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"ARC API HTTP {resp.status}")
                    data = await resp.json()
                    break
        except Exception as e:
            if attempt == 2:
                raise Exception(f"ARC API queue failed: {e}")
            await asyncio.sleep(3)

    job_id = data.get("job_id")
    if not job_id:
        raise Exception("ARC API did not return job_id")

    pub_url = ""
    async with aiohttp.ClientSession() as session:
        for i in range(30):
            await asyncio.sleep(3)
            try:
                async with session.get(
                    f"{API_URL}/youtube/jobStatus",
                    params={"api_key": API_KEY, "job_id": job_id},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        continue
                    d = await resp.json()
                    job = d.get("job", {})
                    if job.get("status") == "done":
                        pub_url = job.get("result", {}).get("public_url", "")
                        break
                    elif job.get("status") == "failed":
                        raise Exception(f"ARC job failed: {job.get('error')}")
            except Exception as e:
                if "ARC job failed" in str(e):
                    raise
                continue

    if not pub_url:
        raise Exception("ARC API polling timed out")

    if not pub_url.startswith("http"):
        pub_url = API_URL + ("" if pub_url.startswith("/") else "/") + pub_url

    async with aiohttp.ClientSession() as session:
        async with session.get(pub_url, timeout=aiohttp.ClientTimeout(total=600 if video else 300)) as resp:
            if resp.status != 200:
                raise Exception(f"File stream HTTP {resp.status}")
            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(131072):
                    f.write(chunk)

    if file_path.exists() and file_path.stat().st_size > 0:
        return str(file_path)
    raise Exception("Downloaded file empty")


async def _dedup_download(video_id: str, video: bool) -> str:
    cached = find_file(video_id, video)
    if cached:
        return cached

    key = f"{video_id}:{'video' if video else 'audio'}"

    if key in _in_progress:
        try:
            return await asyncio.shield(_in_progress[key])
        except Exception as e:
            raise Exception(f"Download failed: {e}") from e

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    _in_progress[key] = future

    try:
        result = await _arc_download(video_id, video)
        future.set_result(result)
        return result
    except Exception as e:
        if not future.done():
            future.set_exception(e)
        raise Exception(f"Download failed: {e}") from e
    finally:
        _in_progress.pop(key, None)

async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None
    return await _dedup_download(video_id, False)


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None
    return await _dedup_download(video_id, True)


@dataclass
class Track:
    title: str
    url: str
    webpage_url: str = ""
    duration: int = 0
    thumbnail: str = ""
    is_video: bool = False
    source: str = "YouTube"


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        return text[entity.offset: entity.offset + entity.length]
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["title"]

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["duration"]

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["thumbnails"][0]["url"].split("?")[0]

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
            return 0, "Video download failed"
        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            plist = await Playlist.get(link)
        except Exception:
            return []
        videos = plist.get("videos") or []
        ids = []
        for data in videos[:limit]:
            if not data:
                continue
            vid = data.get("id")
            if not vid:
                continue
            ids.append(vid)
        return ids

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        import yt_dlp
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    if "dash" not in str(format["format"]).lower():
                        formats_available.append({
                            "format": format["format"],
                            "filesize": format.get("filesize"),
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        })
                except Exception:
                    continue
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        try:
            if video:
                downloaded_file = await download_video(link)
            else:
                downloaded_file = await download_song(link)
            if downloaded_file:
                return downloaded_file, True
            return None, False
        except Exception:
            return None, False


async def get_track(query: str, video: bool = False) -> Track:
    results = VideosSearch(query, limit=1)

    try:
        data = (await asyncio.wait_for(results.next(), timeout=20))["result"][0]
    except Exception as e:
        raise Exception(f"Search failed: {e}") from e

    video_id = data.get("id")
    if not video_id:
        raise Exception("No video ID found")

    try:
        cached = await _dedup_download(video_id, video)
    except Exception as e:
        raise Exception(f"Download failed for {video_id}: {e}") from e

    if not cached:
        raise Exception(f"Download failed for {video_id}")

    return Track(
        title=data.get("title", "Unknown Track"),
        url=cached,
        webpage_url=data.get("link") or f"https://www.youtube.com/watch?v={video_id}",
        duration=int(time_to_seconds(data.get("duration") or "0")),
        thumbnail=(data.get("thumbnails") or [{}])[0].get("url", "").split("?")[0],
        is_video=video,
        source="YouTube",
    )

YouTube = YouTubeAPI()
