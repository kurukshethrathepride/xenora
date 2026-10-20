<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=200&section=header&text=Xenora&fontSize=80&fontColor=fff&animation=twinkling&fontAlignY=36&desc=Premium%20Telegram%20Voice%20Chat%20Music%20Bot&descAlignY=62&descAlign=50" width="100%"/>

<br>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-Latest-1D9BF0?style=for-the-badge&logo=telegram&logoColor=white)](https://pyrogram.org)
[![PyTgCalls](https://img.shields.io/badge/PyTgCalls-Latest-00BFFF?style=for-the-badge&logo=telegram&logoColor=white)](https://pytgcalls.github.io)
[![MongoDB](https://img.shields.io/badge/MongoDB-Powered-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](https://mongodb.com)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge)](LICENSE)

<br>

> **High-quality audio & video streaming for Telegram voice chats — built for performance, reliability, and scale.**

<br>

[Features](#-features) · [Tech Stack](#-tech-stack) · [Project Structure](#-project-structure) · [Requirements](#-requirements) · [Configuration](#-configuration) · [Deployment](#-deployment) · [License](#-license)

</div>

---

## ✨ Features

### 🎵 Playback
- High-quality **audio streaming** from YouTube, Spotify, and more
- **Video streaming** support via `/vplay`
- **Loop & Shuffle** playback modes
- **Progress tracking** with real-time player UI

### 📋 Queue Management
- Full **queue system** with add, skip, remove, and clear
- **Auto-queue handling** — next track plays automatically
- Interactive **music player controls** (play/pause/skip/stop)

### 🤖 Automation
- **Auto Assistant Management** — handles assistant accounts seamlessly
- **Broadcast System** — send announcements to all active chats
- **Global Admin Tools** — manage the bot across all groups

### ⚙️ Administration
- **Group Configuration System** — per-group settings and permissions
- **MongoDB-powered storage** — fast, persistent, and scalable
- **Multi-platform media support** — YouTube, SoundCloud, Spotify, and more
- **Modern Telegram UI** — inline buttons, styled messages, clean UX

---

## 🛠 Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Telegram Framework | Pyrogram |
| Voice/Video Calls | PyTgCalls |
| Database | MongoDB |
| Media Downloader | yt-dlp |
| Async Runtime | AsyncIO |

---
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7?style=for-the-badge&logo=render&logoColor=black)](https://render.com/deploy?repo=https://github.com/kurukshethrathepride/xenora)


## 📁 Project Structure

```
JASS/
├── jass/
│   ├── core/               # Core engine (call manager, bot client, etc.)
│   ├── database/           # MongoDB models and CRUD helpers
│   ├── downloads/          # Temporary media download cache
│   ├── helpers/            # Utility functions and decorators
│   ├── locales/            # Language/locale strings
│   ├── logs/               # Runtime log files
│   ├── platforms/          # Platform integrations (YouTube, Spotify, etc.)
│   ├── plugins/            # Command handlers and features
│   ├── __init__.py
│   ├── __main__.py         # Entry point
│   ├── config.py           # Configuration loader
│   └── logger.py           # Logging setup
├── logs/                   # Top-level log output
├── .env                    # Environment variables (not committed)
├── .env.example            # Example environment file
├── .gitignore
├── docker-compose.yml      # Docker Compose config
├── Dockerfile              # Docker image definition
├── LICENSE
├── Procfile                # Heroku/Railway process definition
├── requirements.txt
└── runtime.txt             # Python runtime pin (for Heroku/Railway)
```

---

## 📋 Requirements

Before deploying, ensure you have:

- Python **3.11+**
- A running **MongoDB** instance (local or Atlas)
- A **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)
- **Telegram API ID & API Hash** from [my.telegram.org](https://my.telegram.org)
- A **Pyrogram Session String** for the assistant account

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
```

```env
# Bot Credentials
BOT_TOKEN=your_bot_token_here
API_ID=your_api_id_here
API_HASH=your_api_hash_here

# Assistant Account
STRING_SESSION=your_pyrogram_session_string

# Database
MONGO_DB_URI=mongodb+srv://user:password@cluster.mongodb.net/jass

# Owner
OWNER_ID=your_telegram_user_id
```

> All variables must be set before starting the bot. See `.env.example` for the full list.

---

## 🚀 Deployment

### Local / VPS

```bash
# 1. Clone the repository
git clone https://github.com/jaskrninlove/xenora.git
cd jass

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
nano .env   # Fill in your credentials

# 4. Run the bot
python -m jass
```

---

### 🐳 Docker

```bash
# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the bot
docker-compose down
```

---

### ☁️ Heroku

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

```bash
# Or manually via CLI
heroku create your-app-name
heroku config:set BOT_TOKEN=xxx API_ID=xxx API_HASH=xxx ...
git push heroku main
```

> The `Procfile` and `runtime.txt` are already configured for Heroku.

---

### 🚂 Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

1. Fork this repository
2. Create a new Railway project and link your fork
3. Add all environment variables from `.env.example` in the Railway dashboard
4. Railway auto-detects the `Procfile` and deploys automatically

---

### 🌊 Render / Koyeb / Fly.io

For other platforms, ensure:
- Python 3.11+ runtime is selected
- All `.env` variables are set as environment/config vars
- Start command is set to: `python -m jass`

---

## 📄 License

This project is **proprietary software**.

Unauthorized copying, modification, redistribution, resale, sublicensing, or commercial use of this software or any portion of it is **strictly prohibited** without prior written permission from the copyright holder.

See the [LICENSE](LICENSE) file for full terms.

---

<div align="center">

**Developed & maintained by [Jass](https://github.com/jaskrninlove)**

© 2026 Jass · All Rights Reserved

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=100&section=footer" width="100%"/>

</div>
