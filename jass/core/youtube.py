
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from py_yt import VideosSearch, Playlist


LOGGER = logging.getLogger(__name__)

# =========================================================
# CONFIGURATION
# =========================================================

ARC_API_URL = os.getenv(
    "ARC_API_URL",
    "https://api.arcmusic.fun",
).rstrip("/")

ARC_API_KEY = os.getenv("ARC_API_KEY", "").strip()

DOWNLOAD_DIR = Path(
    os.getenv("DOWNLOAD_DIR", "downloads")
)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=90)
MAX_API_RETRIES = 3
MAX_JOB_POLLS = 30
JOB_POLL_INTERVAL = 3

# Register your running Kurigram assistant client at startup.
_telegram_media_client = None

# Prevent simultaneous downloads of the same item.
_in_progress: dict[str, asyncio.Task] = {}
_in_progress_lock = asyncio.Lock()


def set_telegram_media_client(client):
    """
    Register the already-started Kurigram/Pyrogram-compatible
    client that can access the ARC Telegram media channel.
    """
    global _telegram_media_client
    _telegram_media_client = client
    LOGGER.info("Telegram media client registered for ARC downloads.")


# =========================================================
# YOUTUBE HELPERS
# =========================================================

def extract_video_id(value: str) -> Optional[str]:
    """Extract a YouTube video ID from a URL or plain ID."""
    if not value:
        return None

    value = str(value).strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        parts = [part for part in parsed.path.split("/") if part]

        if host in {
            "youtu.be",
            "www.youtu.be",
        }:
            return parts[0] if parts else None

        if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            if parsed.path == "/watch":
                from urllib.parse import parse_qs
                return parse_qs(parsed.query).get("v", [None])[0]

            if len(parts) >= 2 and parts[0] in {
                "shorts",
                "embed",
                "live",
                "v",
            }:
                return parts[1]

    except Exception:
        LOGGER.debug("Could not parse YouTube URL: %s", value)

    return None


def _media_path(video_id: str, video: bool = False) -> Path:
    extension = ".mp4" if video else ".mp3"
    return DOWNLOAD_DIR / f"{video_id}{extension}"


def find_file(video_id: str, video: bool = False) -> Optional[str]:
    """Return a valid cached file, if available."""
    expected = _media_path(video_id, video)

    if expected.is_file() and expected.stat().st_size > 0:
        return str(expected)

    # Also accept a previously cached media file with another extension.
    for path in DOWNLOAD_DIR.glob(f"{video_id}.*"):
        if path.is_file() and path.stat().st_size > 0:
            return str(path)

    return None


# =========================================================
# ARC API REQUESTS
# =========================================================

async def _request_json(
    session: aiohttp.ClientSession,
    url: str,
    params: dict,
) -> dict:
    """Request JSON with bounded retries and useful errors."""
    last_error = "Unknown ARC API error"

    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            async with session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                body = await response.text()

                if response.status == 403:
                    raise RuntimeError(
                        "ARC API returned HTTP 403. Check ARC_API_KEY "
                        "and confirm the key is valid."
                    )

                if response.status in (401, 404):
                    raise RuntimeError(
                        f"ARC API returned HTTP {response.status}: "
                        f"{body[:500]}"
                    )

                if response.status == 429 or response.status >= 500:
                    last_error = (
                        f"ARC API HTTP {response.status}: {body[:500]}"
                    )
                    if attempt < MAX_API_RETRIES:
                        await asyncio.sleep(attempt * 2)
                        continue
                    break

                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(
                        f"ARC API HTTP {response.status}: {body[:500]}"
                    )

                try:
                    data = await response.json(content_type=None)
                except Exception as exc:
                    raise RuntimeError(
                        f"ARC API returned invalid JSON: {body[:500]}"
                    ) from exc

                if not isinstance(data, dict):
                    raise RuntimeError("ARC API returned an unexpected response.")

                return data

        except RuntimeError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            LOGGER.warning(
                "ARC request attempt %s/%s failed: %s",
                attempt,
                MAX_API_RETRIES,
                last_error,
            )
            if attempt < MAX_API_RETRIES:
                await asyncio.sleep(attempt * 2)

    raise RuntimeError(
        f"ARC API request failed after {MAX_API_RETRIES} attempts: "
        f"{last_error}"
    )


# =========================================================
# ARC CACHED TELEGRAM MEDIA
# =========================================================

def _telegram_message_link(value: str) -> Optional[tuple[str, int]]:
    """Parse a public t.me/channel/message link."""
    if not value:
        return None

    try:
        parsed = urlparse(value.strip())
        if parsed.hostname not in {"t.me", "www.t.me"}:
            return None

        parts = [part for part in parsed.path.split("/") if part]

        # Supports links such as t.me/ArcAPI_1/838.
        if len(parts) >= 2 and parts[0] != "c":
            if parts[1].isdigit():
                return parts[0], int(parts[1])

        # Private channel links use /c/<channel_id>/<message_id>.
        # Convert to the -100... form used by Telegram clients.
        if len(parts) >= 3 and parts[0] == "c":
            if parts[1].isdigit() and parts[2].isdigit():
                return f"-100{parts[1]}", int(parts[2])

    except Exception:
        LOGGER.debug("Could not parse Telegram media link.")

    return None


async def _download_cached_telegram_media(
    message_link: str,
    video_id: str,
    video: bool = False,
) -> str:
    """
    Download media from the Telegram message returned by ARC.
    The registered client must have access to that message.
    """
    client = _telegram_media_client

    if client is None:
        raise RuntimeError(
            "ARC returned cached Telegram media, but no Telegram media "
            "client is registered. Register the assistant client using "
            "set_telegram_media_client(assistant) during startup."
        )

    parsed = _telegram_message_link(message_link)
    if not parsed:
        raise RuntimeError(
            f"ARC returned an unsupported Telegram media link: {message_link}"
        )

    chat_id, message_id = parsed

    try:
        message = await client.get_messages(chat_id, message_id)
    except Exception as exc:
        raise RuntimeError(
            "Could not retrieve ARC's cached Telegram message. Make sure "
            "the registered assistant account can access the ARC channel. "
            f"Telegram error: {exc}"
        ) from exc

    if not message or getattr(message, "empty", False):
        raise RuntimeError(
            "ARC's Telegram message was empty or inaccessible."
        )

    media = (
        getattr(message, "audio", None)
        or getattr(message, "voice", None)
        or getattr(message, "video", None)
        or getattr(message, "document", None)
        or getattr(message, "video_note", None)
        or getattr(message, "animation", None)
    )

    if media is None:
        raise RuntimeError(
            "ARC's Telegram message does not contain a supported media file."
        )

    # Preserve the actual media extension where possible.
    file_name = getattr(media, "file_name", None)
    mime_type = getattr(media, "mime_type", None) or ""

    if file_name:
        extension = Path(file_name).suffix.lower()
    elif video or mime_type.startswith("video/"):
        extension = ".mp4"
    elif mime_type == "audio/mpeg":
        extension = ".mp3"
    elif mime_type == "audio/ogg":
        extension = ".ogg"
    elif mime_type == "audio/mp4":
        extension = ".m4a"
    else:
        extension = ".mp4" if video else ".audio"

    destination = DOWNLOAD_DIR / f"{video_id}{extension}"

    try:
        downloaded = await client.download_media(
            message,
            file_name=str(destination),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Telegram media download failed: {exc}"
        ) from exc

    if not downloaded:
        raise RuntimeError("Telegram client did not return a downloaded file path.")

    downloaded_path = Path(str(downloaded))

    if not downloaded_path.is_file() or downloaded_path.stat().st_size <= 0:
        raise RuntimeError(
            "Telegram download finished without producing a valid media file."
        )

    LOGGER.info(
        "Downloaded ARC cached media for %s to %s",
        video_id,
        downloaded_path,
    )

    return str(downloaded_path)


# =========================================================
# ARC DOWNLOAD JOB
# =========================================================

async def _arc_download(
    video_id: str,
    video: bool = False,
) -> str:
    """
    Request an ARC download. Handles either:
      1. A normal asynchronous job with a public download URL.
      2. A cached-media response containing a Telegram message link.
    """
    if not ARC_API_KEY:
        raise RuntimeError(
            "ARC_API_KEY is missing. Set it in the Render environment variables."
        )

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"Accept": "application/json"}
    params = {
        "api_key": ARC_API_KEY,
        "video_id": video_id,
        "isVideo": str(video).lower(),
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        data = await _request_json(
            session,
            f"{ARC_API_URL}/youtube/v2/download",
            params,
        )

        result = data.get("result")
        if not isinstance(result, dict):
            result = {}

        # Cached response: ARC has already stored the media in Telegram.
        if result.get("cached") is True:
            message_link = (
                result.get("cdn")
                or result.get("message_link")
                or result.get("telegram_link")
                or result.get("url")
            )

            if not message_link:
                raise RuntimeError(
                    "ARC reported cached media but did not return a Telegram link."
                )

            if str(message_link).startswith(("https://t.me/", "http://t.me/")):
                return await _download_cached_telegram_media(
                    message_link=str(message_link),
                    video_id=video_id,
                    video=video,
                )

            raise RuntimeError(
                "ARC marked the media as cached, but its returned link was "
                "not a supported Telegram message link."
            )

        # Support job IDs found at the top level or inside result.
        job_id = (
            data.get("job_id")
            or result.get("job_id")
            or data.get("id")
            or result.get("id")
        )

        if not job_id:
            raise RuntimeError(
                "ARC response contained neither cached media nor a download "
                f"job ID. Response: {str(data)[:700]}"
            )

        status_params = {
            "api_key": ARC_API_KEY,
            "job_id": str(job_id),
        }

        for poll_number in range(1, MAX_JOB_POLLS + 1):
            await asyncio.sleep(JOB_POLL_INTERVAL)

            status_data = await _request_json(
                session,
                f"{ARC_API_URL}/youtube/jobStatus",
                status_params,
            )

            status_result = status_data.get("result")
            if not isinstance(status_result, dict):
                status_result = {}

            status = str(
                status_data.get("status")
                or status_result.get("status")
                or ""
            ).lower()

            if status in {"failed", "error", "cancelled", "canceled"}:
                detail = (
                    status_data.get("error")
                    or status_result.get("error")
                    or status_data.get("message")
                    or status_result.get("message")
                    or "No error details returned"
                )
                raise RuntimeError(f"ARC download job failed: {detail}")

            public_url = (
                status_result.get("public_url")
                or status_result.get("download_url")
                or status_data.get("public_url")
                or status_data.get("download_url")
            )

            # Some API responses only provide the URL once status is complete.
            if public_url and (
                status in {"success", "completed", "complete", "done"}
                or not status
            ):
                return await _download_public_url(
                    session,
                    str(public_url),
                    video_id,
                    video,
                )

            if status in {"success", "completed", "complete", "done"}:
                raise RuntimeError(
                    "ARC job completed but did not include a public download URL."
                )

        raise RuntimeError(
            f"ARC download job timed out after "
            f"{MAX_JOB_POLLS * JOB_POLL_INTERVAL} seconds."
        )


async def _download_public_url(
    session: aiohttp.ClientSession,
    url: str,
    video_id: str,
    video: bool = False,
) -> str:
    """Download a media file returned by ARC."""
    if urlparse(url).scheme not in {"http", "https"}:
        raise RuntimeError("ARC returned an invalid public download URL.")

    destination = _media_path(video_id, video)

    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
            if response.status < 200 or response.status >= 300:
                body = await response.text()
                raise RuntimeError(
                    f"ARC media download returned HTTP {response.status}: "
                    f"{body[:300]}"
                )

            temporary = destination.with_suffix(
                destination.suffix + ".part"
            )

            try:
                with temporary.open("wb") as file:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        if chunk:
                            file.write(chunk)

                if not temporary.is_file() or temporary.stat().st_size <= 0:
                    raise RuntimeError("ARC returned an empty media file.")

                temporary.replace(destination)

            finally:
                if temporary.exists():
                    temporary.unlink(missing_ok=True)

    except Exception:
        LOGGER.exception("ARC media download failed for %s", video_id)
        raise

    return str(destination)


# =========================================================
# DOWNLOAD DEDUPLICATION
# =========================================================

async def _dedup_download(
    video_id: str,
    video: bool = False,
) -> str:
    """Reuse a cached file or an existing in-progress download."""
    cached = find_file(video_id, video)
    if cached:
        return cached

    key = f"{video_id}:{int(video)}"

    async with _in_progress_lock:
        task = _in_progress.get(key)

        if task is None or task.done():
            task = asyncio.create_task(
                _arc_download(video_id, video=video)
            )
            _in_progress[key] = task

    try:
        return await task
    finally:
        async with _in_progress_lock:
            if _in_progress.get(key) is task:
                _in_progress.pop(key, None)


async def download_song(value: str) -> str:
    video_id = extract_video_id(value)
    if not video_id:
        raise ValueError("Could not extract a valid YouTube video ID.")
    return await _dedup_download(video_id, video=False)


async def download_video(value: str) -> str:
    video_id = extract_video_id(value)
    if not video_id:
        raise ValueError("Could not extract a valid YouTube video ID.")
    return await _dedup_download(video_id, video=True)


# =========================================================
# SEARCH AND TRACK DETAILS
# =========================================================

@dataclass
class Track:
    title: str
    url: str
    duration: str = "Unknown"
    thumbnail: str = ""
    video_id: str = ""
    file_path: str = ""


async def _search_videos(query: str, limit: int = 1) -> list:
    """Search YouTube using py-yt-search."""
    try:
        search = VideosSearch(query, limit=limit)
        response = await asyncio.to_thread(search.result)
        if asyncio.iscoroutine(response):
            response = await response

        if isinstance(response, dict):
            return response.get("result", []) or []

    except Exception:
        LOGGER.exception("YouTube search failed for query: %s", query)

    return []


async def get_track(
    query: str,
    video: bool = False,
) -> Track:
    """
    Search for a track or accept a YouTube URL, then download it
    through ARC and return a Track object.
    """
    query = str(query or "").strip()
    if not query:
        raise ValueError("Please provide a YouTube URL or search query.")

    video_id = extract_video_id(query)
    item = {}

    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        item = {
            "id": video_id,
            "title": url,
            "link": url,
            "duration": "Unknown",
            "thumbnails": [],
        }
    else:
        results = await _search_videos(query, limit=1)
        if not results:
            raise RuntimeError(f"No YouTube results found for: {query}")

        item = results[0]
        video_id = (
            item.get("id")
            or extract_video_id(item.get("link", ""))
            or extract_video_id(item.get("url", ""))
        )

        if not video_id:
            raise RuntimeError("YouTube search result did not contain a valid video ID.")

        url = (
            item.get("link")
            or item.get("url")
            or f"https://www.youtube.com/watch?v={video_id}"
        )

    title = item.get("title") or "Unknown title"
    duration = item.get("duration") or item.get("duration_string") or "Unknown"

    thumbnails = item.get("thumbnails") or []
    thumbnail = item.get("thumbnail") or ""

    if not thumbnail and thumbnails:
        last_thumbnail = thumbnails[-1]
        if isinstance(last_thumbnail, dict):
            thumbnail = last_thumbnail.get("url", "")

    file_path = await _dedup_download(video_id, video=video)

    return Track(
        title=title,
        url=url,
        duration=str(duration),
        thumbnail=thumbnail,
        video_id=video_id,
        file_path=file_path,
    )


# =========================================================
# COMPATIBILITY WRAPPER
# =========================================================

class YouTubeAPI:
    """Convenience wrapper for search, metadata and download methods."""

    async def exists(self, query: str) -> bool:
        return extract_video_id(query) is not None or bool(
            await _search_videos(query, limit=1)
        )

    async def details(self, query: str) -> Optional[dict]:
        video_id = extract_video_id(query)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            return {
                "id": video_id,
                "title": url,
                "link": url,
                "url": url,
                "duration": "Unknown",
                "thumbnail": "",
                "thumbnails": [],
            }

        results = await _search_videos(query, limit=1)
        return results[0] if results else None

    async def title(self, query: str) -> str:
        data = await self.details(query)
        return str(data.get("title", "Unknown title")) if data else "Unknown title"

    async def duration(self, query: str) -> str:
        data = await self.details(query)
        if not data:
            return "Unknown"
        return str(data.get("duration") or data.get("duration_string") or "Unknown")

    async def thumbnail(self, query: str) -> str:
        data = await self.details(query)
        if not data:
            return ""
        if data.get("thumbnail"):
            return str(data["thumbnail"])
        thumbnails = data.get("thumbnails") or []
        if thumbnails and isinstance(thumbnails[-1], dict):
            return str(thumbnails[-1].get("url", ""))
        return ""

    async def video(self, query: str) -> str:
        return await download_video(query)

    async def playlist(self, query: str):
        try:
            playlist = Playlist(query)
            result = await asyncio.to_thread(playlist.result)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, dict):
                return result.get("result", result.get("videos", [])) or []
            return result or []
        except Exception:
            LOGGER.exception("YouTube playlist lookup failed.")
            return []

    async def track(self, query: str, video: bool = False) -> Track:
        return await get_track(query, video=video)

    async def formats(self, query: str):
        # ARC handles the actual media retrieval and format selection.
        data = await self.details(query)
        return data or {}

    async def slider(self, query: str):
        return await self.details(query)

    async def download(self, query: str, video: bool = False) -> str:
        return (
            await download_video(query)
            if video
            else await download_song(query)
        )


YouTube = YouTubeAPI()
