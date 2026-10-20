# ==========================================================

# JassMusic

# Copyright (c) 2026 Jass

# Proprietary Software. Unauthorized copying, modification, distribution, or resale of this source code is strictly prohibited.

# Developed by Jass (Jaskaran Singh)

# © 2026 All Rights Reserved.

# ==========================================================

import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    SESSION_STRING = os.getenv("SESSION_STRING", "")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://ChatSphereDB:RadheyMaa@chatspheredb.shxwz5d.mongodb.net/?retryWrites=true&w=majority")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "JassCore")
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    LOGGER_CHAT_ID = int(os.getenv("LOGGER_CHAT_ID", "0"))
    START_IMG = os.getenv("START_IMG", "https://i.pinimg.com/736x/59/90/3a/59903a0d021a27d55a86b507ec329f17.jpg")
    SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/XenoraChatz")
    NETWORK_URL = os.getenv("NETWORK_URL", "https://t.me/xenoraorg")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "")
    ASSISTANT_USERNAME = os.getenv("ASSISTANT_USERNAME", "")
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SAAVN_API_URL = os.getenv("SAAVN_API_URL", "https://saavn.sumit.co/api")
    ARC_API_URL = os.getenv("ARC_API_URL", "https://portal.arcmusic.fun")
    ARC_API_KEY = os.getenv("ARC_API_KEY", "ARC43de7f48ae9b163eb72787")
config = Config()
