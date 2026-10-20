
import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import aiohttp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import VideosSearch, Playlist


API_URL = os.environ.get(
    "ARC_API_URL", "https://api.arcmusic.fun"
).rstrip("/")
API_KEY = os.environ.get("ARC_API_KEY", "")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

_in_progress: dict[str, asyncio.Task] = {}


def time_to_seconds(value) -> int:
    try:
        parts = str(value).split(":")
        return sum(
            int(part) * 60 ** index
            for index, part in enumerate(reversed(parts))
        )
    except (ValueError, TypeError):
        return 0


def find_file(video_id: str, video: bool = False) -> Optional[str]:
    extensions = (
        [".mp4", ".webm", ".mkv"]
        if video
        else [".mp3", ".webm", ".m4a", ".opus"]
    )

    for extension in extensions:
        path = DOWNLOAD_DIR / f"{video_id}{extension}"
        if path.is_file() and path.stat().st_size > 0:
            return str(path)

    return None


async def _arc_download(video_id: str, video: bool = False) -> str:
    extension = "mp4" if video else "mp3"
    file_path = DOWNLOAD_DIR / f"{video_id}.{extension}"

    # Submit the download request.
    data = None
    timeout = aiohttp.ClientTimeout(total=30)

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_URL}/youtube/v2/download",
                    params={
                        "api_key": API_KEY,
                        "query": video_id,
                        "isVideo": str(video).lower(),
                    },
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"ARC API HTTP {resp.status}: {body[:300]}"
                        )

                    try:
                        data = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as exc:
                        raise RuntimeError(
                            f"ARC API returned invalid JSON: {exc}"
                        ) from exc

                    if not isinstance(data, dict):
                        raise RuntimeError(
                            "ARC API returned an unexpected response type"
                        )

                    result = data.get("result") or {}

                    # Cached Telegram media is not a queued job.
                    if (
                        data.get("status") == "success"
                        and isinstance(result, dict)
                        and result.get("success") is True
                        and result.get("cached") is True
                    ):
                        cdn = result.get("cdn", "")

                        raise RuntimeError(
                            "ARC API returned cached media instead of a "
                            "download job. CDN/message link: "
                            f"{cdn or 'not provided'}. "
                            "A Telegram media retrieval handler is required."
                        )

                    # A normal response must contain a job ID.
                    job_id = data.get("job_id")

                    if not job_id:
                        safe_data = dict(data)

                        for key in (
                            "api_key",
                            "key",
                            "token",
                            "authorization",
                        ):
                            if key in safe_data:
                                safe_data[key] = "[REDACTED]"

                        raise RuntimeError(
                            "ARC API response missing job_id: "
                            f"{safe_data!r}"
                        )

                    break

        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"ARC API request failed after 3 attempts: {exc}"
                ) from exc

            await asyncio.sleep(3)

    if not data or not data.get("job_id"):
        raise RuntimeError("ARC API did not provide a download job")

    job_id = data["job_id"]
    public_url = ""

    # Poll the download job.
    async with aiohttp.ClientSession() as session:
        for _ in range(30):
            await asyncio.sleep(3)

            try:
                async with session.get(
                    f"{API_URL}/youtube/jobStatus",
                    params={
                        "api_key": API_KEY,
                        "job_id": job_id,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        continue

                    try:
                        status_data = await resp.json(
                            content_type=None
                        )
                    except (ValueError, aiohttp.ContentTypeError):
                        continue

                    if not isinstance(status_data, dict):
                        continue

                    job = status_data.get("job") or {}
                    if not isinstance(job, dict):
                        continue

                    status = job.get("status")

                    if status == "done":
                        result = job.get("result") or {}
                        if isinstance(result, dict):
                            public_url = result.get("public_url", "")
                        break

                    if status == "failed":
                        raise RuntimeError(
                            f"ARC job failed: "
                            f"{job.get('error', 'Unknown error')}"
                        )

            except RuntimeError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue

    if not public_url:
        raise RuntimeError(
            "ARC download job timed out or returned no public_url"
        )

    if not public_url.startswith(("http://", "https://")):
        public_url = (
            API_URL
            + ("" if public_url.startswith("/") else "/")
            + public_url
        )

    # Download the actual media file.
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                public_url,
                timeout=aiohttp.ClientTimeout(
                    total=600 if video else 300
                ),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"Media download HTTP {resp.status}"
                    )

                with open(file_path, "wb") as output:
                    async for chunk in resp.content.iter_chunked(131072):
                        output.write(chunk)

    except Exception:
        if file_path.exists():
            file_path.unlink()
        raise

    if file_path.is_file() and file_path.stat().st_size > 0:
        return str(file_path)

    raise RuntimeError("Downloaded media file is empty")


async def _dedup_download(
    video_id: str, video: bool = False
) -> Optional[str]:
    cached = find_file(video_id, video)
    if cached:
        return cached

    key = f"{video_id}:{'video' if video else 'audio'}"
    task = _in_progress.get(key)

    if task is None:
        task = asyncio.create_task(_arc_download(video_id, video))
        _in_progress[key] = task

    try:
        return await asyncio.shield(task)
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc
    finally:
        if task.done() and _in_progress.get(key) is task:
            _in_progress.pop(key, None)


def extract_video_id(link: str) -> Optional[str]:
    link = (link or "").strip()

    if not link:
        return None

    if "youtu.be/" in link:
        video_id = (
            link.split("youtu.be/", 1)[1]
            .split("?", 1)[0]
            .split("/", 1)[0]
        )
    elif "v=" in link:
        video_id = link.split("v=", 1)[1].split("&", 1)[0]
    else:
        video_id = link

    return video_id or None


async def download_song(link: str) -> Optional[str]:
    video_id = extract_video_id(link)
    if not video_id or len(video_id) < 3:
        return None

    return await _dedup_download(video_id, False)


async def download_video(link: str) -> Optional[str]:
    video_id = extract_video_id(link)
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
        self.reg = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

    async def exists(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)
        return bool(re.search(self.regex, link or ""))

    async def url(self, message_1: Message) -> Optional[str]:
        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            entities = message.entities or []
            text_value = message.text or message.caption or ""

            for entity in entities:
                if entity.type == MessageEntityType.URL:
                    return text_value[
                        entity.offset:entity.offset + entity.length
                    ]

                if entity.type == MessageEntityType.TEXT_LINK:
                    return entity.url

            for entity in message.caption_entities or []:
                if entity.type == MessageEntityType.TEXT_LINK:
                    return entity.url

        return None

    async def details(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        results = VideosSearch(link, limit=1)
        response = await results.next()
        items = response.get("result", [])

        if not items:
            raise RuntimeError("No YouTube search results found")

        result = items[0]
        title = result.get("title", "Unknown Track")
        duration_min = result.get("duration") or ""
        thumbnail = (
            (result.get("thumbnails") or [{}])[0].get("url", "")
            .split("?", 1)[0]
        )
        video_id = result.get("id", "")
        duration_sec = (
            time_to_seconds(duration_min) if duration_min else 0
        )

        return title, duration_min, duration_sec, thumbnail, video_id

    async def title(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (await self.details(link, videoid))[0]

    async def duration(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (await self.details(link, videoid))[1]

    async def thumbnail(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (await self.details(link, videoid))[3]

    async def video(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
            return 0, "Video download failed"
        except Exception as exc:
            return 0, f"Video download error: {exc}"

    async def playlist(
        self,
        link,
        limit,
        user_id,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.listbase + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            playlist_data = await Playlist.get(link)
        except Exception:
            return []

        videos = playlist_data.get("videos") or []
        ids = []

        for item in videos[:limit]:
            if not item:
                continue

            video_id = item.get("id")
            if video_id:
                ids.append(video_id)

        return ids

    async def track(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        results = VideosSearch(link, limit=1)
        response = await results.next()
        items = response.get("result", [])

        if not items:
            raise RuntimeError("No YouTube search results found")

        result = items[0]
        title = result.get("title", "Unknown Track")
        duration_min = result.get("duration") or ""
        video_id = result.get("id", "")
        youtube_url = result.get("link") or (
            self.base + video_id if video_id else ""
        )
        thumbnail = (
            (result.get("thumbnails") or [{}])[0].get("url", "")
            .split("?", 1)[0]
        )

        track_details = {
            "title": title,
            "link": youtube_url,
            "vidid": video_id,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }

        return track_details, video_id

    async def formats(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        import yt_dlp

        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        options = {"quiet": True, "no_warnings": True}

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(link, download=False)
            available = []

            for item in info.get("formats", []):
                try:
                    if "dash" not in str(
                        item.get("format", "")
                    ).lower():
                        available.append({
                            "format": item.get("format", ""),
                            "filesize": item.get("filesize"),
                            "format_id": item.get("format_id", ""),
                            "ext": item.get("ext", ""),
                            "format_note": item.get("format_note", ""),
                            "yturl": link,
                        })
                except (KeyError, TypeError):
                    continue

        return available, link

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)

        if "&" in link:
            link = link.split("&", 1)[0]

        search = VideosSearch(link, limit=10)
        response = await search.next()
        items = response.get("result", [])

        if query_type < 0 or query_type >= len(items):
            raise IndexError(
                "Requested YouTube search result does not exist"
            )

        result = items[query_type]
        title = result.get("title", "Unknown Track")
        duration_min = result.get("duration") or ""
        video_id = result.get("id", "")
        thumbnail = (
            (result.get("thumbnails") or [{}])[0].get("url", "")
            .split("?", 1)[0]
        )

        return title, duration_min, thumbnail, video_id

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
    ):
        if videoid:
            link = self.base + str(link)

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
        response = await asyncio.wait_for(
            results.next(), timeout=20
        )
        items = response.get("result", [])

        if not items:
            raise RuntimeError("No YouTube search results found")

        data = items[0]

    except Exception as exc:
        raise RuntimeError(f"Search failed: {exc}") from exc

    video_id = data.get("id")
    if not video_id:
        raise RuntimeError(
            "YouTube search result did not contain a video ID"
        )

    try:
        downloaded_file = await _dedup_download(video_id, video)
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {video_id}: {exc}"
        ) from exc

    if not downloaded_file:
        raise RuntimeError(
            f"Download failed for {video_id}: no file returned"
        )

    thumbnails = data.get("thumbnails") or [{}]

    return Track(
        title=data.get("title", "Unknown Track"),
        url=downloaded_file,
        webpage_url=data.get("link") or (
            f"https://www.youtube.com/watch?v={video_id}"
        ),
        duration=time_to_seconds(data.get("duration") or "0"),
        thumbnail=thumbnails[0].get("url", "").split("?", 1)[0],
        is_video=video,
        source="YouTube",
    )


YouTube = YouTubeAPI()
