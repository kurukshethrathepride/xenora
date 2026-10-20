# ==========================================================
# JassMusic
# Copyright (c) 2026 Jass
# Proprietary Software. Unauthorized copying, modification, distribution, or resale of this source code is strictly prohibited.
# Developed by Jass (Jaskaran Singh)
# © 2026 All Rights Reserved.
# ==========================================================

import asyncio
import html
import time

from pyrogram.errors import UserAlreadyParticipant
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
from pyrogram.enums import ParseMode
from jass import assistant
from .queue import queue
from .youtube import get_track, set_telegram_media_client
from .logger import error_log
from ..helpers.buttons import player_buttons_ptb, player_close_button_ptb, player_close_button
from ..helpers.premium import render as render_pyro
from ..helpers.premium_ptb import render as render_ptb
from telegram import Bot
from jass.config import config

ptb_bot = Bot(config.BOT_TOKEN)
START_TIME = time.time()
# Register the existing assistant for ARC cached Telegram media.
set_telegram_media_client(assistant)

loop_enabled = {}
active = {}
player_messages = {}
progress_tasks = {}
end_tasks = {}
track_tokens = {}


def format_duration(seconds: int):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def progress_bar(current: int, total: int):
    total = int(total or 0)
    current = int(current or 0)

    if total <= 0:
        return "00:00 ◉────── 00:00"

    size = 6
    current = min(current, total)
    filled = int(size * current / total)

    bar = "━" * filled + "◉" + "─" * max(0, size - filled)
    return f"{format_duration(current)} {bar} {format_duration(total)}"


def stream(track):
    if getattr(track, "is_video", False):
        return MediaStream(
            track.url,
            audio_parameters=AudioQuality.HIGH,
            video_parameters=VideoQuality.HD_720p,
        )

    return MediaStream(
        track.url,
        audio_parameters=AudioQuality.HIGH,
    )


async def safe_play(call, chat_id: int, media):
    """Join/play with self-healing: if PyTgCalls' cached call state is stale
    (e.g. the voice chat was ended/restarted outside the bot, or the bot's
    own leave_call failed silently), force a clean leave and retry once
    before giving up."""
    try:
        await call.play(chat_id, media)
    except Exception as e:
        err = str(e)

        if "GROUPCALL_INVALID" in err or "GroupcallInvalid" in err:
            try:
                await call.leave_call(chat_id)
            except Exception:
                pass

            await asyncio.sleep(1)
            await call.play(chat_id, media)
        else:
            raise


async def premium_reply(message, text: str, **kwargs):
    kwargs.pop("parse_mode", None)
    return await message.reply_text(
        render_pyro(text),
        parse_mode=ParseMode.HTML,
        **kwargs,
    )


async def premium_edit(message, text: str, **kwargs):
    kwargs.pop("parse_mode", None)
    return await message.edit_text(
        render_pyro(text),
        parse_mode=ParseMode.HTML,
        **kwargs,
    )


async def ensure_assistant_joined(client, message):
    chat_id = message.chat.id

    try:
        await assistant.get_chat(chat_id)
        return True
    except Exception:
        pass

    try:
        invite = await client.export_chat_invite_link(chat_id)

        try:
            await assistant.join_chat(invite)
        except UserAlreadyParticipant:
            pass

        return True

    except Exception as e:
        await premium_reply(
            message,
            f":warning: <b>Assistant Required</b>\n\n"
            f"<blockquote>"
            f":bot: I tried to invite the assistant automatically, but it could not join.\n\n"
            f":settings: <b>Required Bot Permissions:</b>\n"
            f"Invite Users and Manage Video Chats\n\n"
            f":warning: <b>Error:</b> <code>{html.escape(str(e))}</code>"
            f"</blockquote>",
        )
        return False


def short_title(title: str, limit: int = 38):
    if not title:
        return "Unknown Track"

    if len(title) > limit:
        title = title[:limit] + "..."

    return html.escape(title)


def safe_mention(user):
    if not user:
        return "Unknown"

    name = html.escape(user.first_name or user.username or "User")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def track_title_link(track):
    title = short_title(getattr(track, "title", "Unknown Track"))
    url = getattr(track, "webpage_url", None)

    if url:
        return f'<a href="{html.escape(url, quote=True)}">{title}</a>'

    return title


def play_caption(track, requested_by):
    title = track_title_link(track)
    mode = ":video:" if getattr(track, "is_video", False) else ":music:"

    return (
        f":play: <b>Started Streaming</b>\n\n"
        f"<blockquote>"
        f"{mode} <b>Title:</b> {title}\n"
        f":time: <b>Duration:</b> <code>{format_duration(track.duration)}</code>\n"
        f":profile: <b>Requested By:</b> {requested_by}\n\n"
        f":active: The stage is live. Enjoy the music."
        f"</blockquote>"
    )


def queue_caption(track, requested_by, pos: int):
    title = track_title_link(track)
    mode = ":video:" if getattr(track, "is_video", False) else ":music:"

    return (
        f":queue: <b>Added To Queue</b>\n\n"
        f"<blockquote>"
        f":queue: <b>Position:</b> <code>#{pos}</code>\n"
        f"{mode} <b>Title:</b> {title}\n"
        f":time: <b>Duration:</b> <code>{format_duration(track.duration)}</code>\n"
        f":profile: <b>Requested By:</b> {requested_by}\n\n"
        f":success: This track will play after the current stream."
        f"</blockquote>"
    )

async def stop_progress(chat_id: int):
    task = progress_tasks.pop(chat_id, None)
    if task:
        task.cancel()


async def stop_end_timer(chat_id: int):
    task = end_tasks.pop(chat_id, None)
    if task:
        task.cancel()


async def progress_worker(chat_id: int, track, token: float):
    start = time.time()

    while chat_id in active and track_tokens.get(chat_id) == token:
        try:
            current = int(time.time() - start)

            if current >= int(track.duration or 0):
                break

            msg = player_messages.get(chat_id)
            if msg:
                await msg.edit_reply_markup(
                    reply_markup=player_buttons_ptb(progress_bar(current, track.duration))
                )

            await asyncio.sleep(20)

        except asyncio.CancelledError:
            break

        except Exception:
            await asyncio.sleep(20)


async def auto_next_worker(client, call, chat_id: int, track, token: float):
    try:
        duration = int(track.duration or 0)

        if duration <= 0:
            duration = 300

        await asyncio.sleep(duration + 8)

        if track_tokens.get(chat_id) != token:
            return

        if chat_id not in active:
            return

        await play_next_from_queue(client, call, chat_id, None)

    except asyncio.CancelledError:
        pass

    except Exception as e:
        await error_log("Auto Next Worker", e)


async def send_card(message, caption, track, buttons=True):
    reply_markup = player_buttons_ptb(progress_bar(0, track.duration)) if buttons else None
    thumb = getattr(track, "thumbnail", None) or getattr(track, "thumb", None)

    if thumb:
        try:
            return await ptb_bot.send_photo(
                chat_id=message.chat.id,
                photo=thumb,
                caption=render_ptb(caption),
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception:
            pass

    return await ptb_bot.send_message(
        chat_id=message.chat.id,
        text=render_ptb(caption),
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

async def start_track_tasks(client, call, chat_id: int, track):
    token = time.time()
    track_tokens[chat_id] = token

    await stop_progress(chat_id)
    await stop_end_timer(chat_id)

    progress_tasks[chat_id] = asyncio.create_task(
        progress_worker(chat_id, track, token)
    )
    end_tasks[chat_id] = asyncio.create_task(
        auto_next_worker(client, call, chat_id, track, token)
    )


async def send_player_ui(message, track):
    requested_by = safe_mention(message.from_user) if message else "Unknown"
    caption = play_caption(track, requested_by)

    msg = await send_card(message, caption, track, buttons=True)
    player_messages[message.chat.id] = msg
    return msg


async def send_queue_ui(message, track, pos: int):
    requested_by = safe_mention(message.from_user)
    caption = queue_caption(track, requested_by, pos)
    return await send_card(message, caption, track, buttons=True)


def stream_ended_caption(user: str):
    return (
        ":stop: <b>Stream Ended</b>\n\n"
        "<blockquote>"
        f":profile: <b>By:</b> {user}\n\n"
        ":queue: No more queued tracks are available.\n"
        ":active: Assistant has left the voice chat."
        "</blockquote>"
    )


def no_voice_chat_caption():
    return (
        ":warning: <b>The Stage Is Empty</b>\n\n"
        "<blockquote>"
        "The music is ready, but no voice chat is currently active in this group.\n\n"
        ":active: Start a voice chat first.\n"
        ":play: Then send /play again.\n\n"
        "The moment the stage opens, the melody will begin."
        "</blockquote>"
    )

async def play_query(client, call, message, query: str, video: bool = False):
    if not await ensure_assistant_joined(client, message):
        return

    chat_id = message.chat.id
    track = await get_track(query, video=video)
    track.is_video = video

    if chat_id in active:
        pos = queue.add(chat_id, track)
        return await send_queue_ui(message, track, pos)

    try:
        await safe_play(call, chat_id, stream(track))

    except Exception as e:
        err = str(e)

        if (
            "CHAT_ADMIN_REQUIRED" in err
            or "CreateGroupCall" in err
            or "phone.CreateGroupCall" in err
            or "GROUPCALL_INVALID" in err
            or "GroupcallInvalid" in err
        ):
            return await premium_reply(
                message,
                no_voice_chat_caption(),
            )

        raise

    active[chat_id] = track
    await send_player_ui(message, track)
    await start_track_tasks(client, call, chat_id, track)


async def play_next_from_queue(client, call, chat_id: int, message=None):
    if loop_enabled.get(chat_id):
        current_track = active.get(chat_id)

        if current_track:
            await safe_play(call, chat_id, stream(current_track))
            await start_track_tasks(client, call, chat_id, current_track)
            return

    next_track = queue.pop(chat_id)

    if not next_track:
        await stop_track(call, chat_id)

        if message:
            user = safe_mention(message.from_user)
            await premium_reply(
                message,
                stream_ended_caption(user),
                reply_markup=player_close_button(),
            )

        return

    await safe_play(call, chat_id, stream(next_track))
    active[chat_id] = next_track

    if message:
        await send_player_ui(message, next_track)
    else:
        old_msg = player_messages.get(chat_id)

        if old_msg:
            caption = play_caption(next_track, "Auto Player")
            new_msg = await send_card(old_msg, caption, next_track, buttons=True)
            player_messages[chat_id] = new_msg

    await start_track_tasks(client, call, chat_id, next_track)


async def skip_track(client, call, chat_id: int, message=None):
    await play_next_from_queue(client, call, chat_id, message)


async def stop_track(call, chat_id: int):
    queue.clear(chat_id)
    active.pop(chat_id, None)
    player_messages.pop(chat_id, None)
    track_tokens.pop(chat_id, None)

    await stop_progress(chat_id)
    await stop_end_timer(chat_id)

    try:
        await call.leave_call(chat_id)
    except Exception:
        pass

def register_end_handler(app, call):
    from pytgcalls.types import StreamEnded, ChatUpdate

    @call.on_update()
    async def on_stream_end(client, update):
        if isinstance(update, StreamEnded):
            chat_id = update.chat_id
            await stop_end_timer(chat_id)

            if chat_id not in active:
                return

            try:
                await play_next_from_queue(app, call, chat_id, message=None)
            except Exception as e:
                await error_log("StreamEnd Handler", e)

        elif isinstance(update, ChatUpdate):
            if update.status in (
                ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ChatUpdate.Status.KICKED,
                ChatUpdate.Status.LEFT_GROUP,
            ):
                chat_id = update.chat_id

                queue.clear(chat_id)
                active.pop(chat_id, None)
                player_messages.pop(chat_id, None)
                track_tokens.pop(chat_id, None)

                await stop_progress(chat_id)
                await stop_end_timer(chat_id)
