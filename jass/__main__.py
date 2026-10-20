# ==========================================================
# JassMusic
# Copyright (c) 2026 Jass
# Proprietary Software. Unauthorized copying, modification, distribution, or resale of this source code is strictly prohibited.
# Developed by Jass (Jaskaran Singh)
# © 2026 All Rights Reserved.
# ==========================================================

import asyncio
from pyrogram import idle

from . import app, assistant, call, logger
from .database.mongo import connect_db
from .plugins import load_plugins
from .core.logger import startup_log
from .ptb_app import build_ptb_app


async def start_bot():
    await connect_db()

    load_plugins()
    logger.info("Pyrogram plugins loaded")

    ptb = build_ptb_app(app, call)

    await ptb.initialize()
    await ptb.start()
    await ptb.updater.start_polling()
    logger.info("PTB premium UI started")

    await app.start()
    logger.info("Bot client started")

    await assistant.start()
    logger.info("Assistant client started")

    await call.start()
    logger.info("PyTgCalls started")

    await startup_log()

    logger.info("JassMusic is running...")

        try:
        await idle()
    finally:
        logger.info("Stopping JassMusic...")

        # Stop Telegram UI polling safely
        try:
            if ptb.updater and ptb.updater.running:
                await ptb.updater.stop()
        except Exception as exc:
            logger.warning("PTB updater shutdown issue: %s", exc)

        try:
            await ptb.stop()
        except Exception as exc:
            logger.warning("PTB stop issue: %s", exc)

        try:
            await ptb.shutdown()
        except Exception as exc:
            logger.warning("PTB shutdown issue: %s", exc)

        # Stop PyTgCalls only if this installed version supports it
        try:
            stop_call = getattr(call, "stop", None)
            if callable(stop_call):
                result = stop_call()
                if asyncio.iscoroutine(result):
                    await result
            else:
                logger.warning(
                    "This PyTgCalls version has no stop() method; "
                    "skipping that shutdown step."
                )
        except Exception as exc:
            logger.warning("PyTgCalls shutdown issue: %s", exc)

        for name, client in (
            ("assistant", assistant),
            ("main bot", app),
        ):
            try:
                if getattr(client, "is_connected", False):
                    await client.stop()
            except Exception as exc:
                logger.warning("%s shutdown issue: %s", name, exc)

        logger.info("JassMusic shutdown completed.")


loop = asyncio.get_event_loop()
loop.run_until_complete(start_bot())
