import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# エロ専用に使う別 Telegram チャットID（非公開スーパーグループ等）。未設定なら 1 対 1 でも従来どおり。
_erotic_raw = os.getenv("TELEGRAM_EROTIC_CHAT_ID", "").strip()
TELEGRAM_EROTIC_CHAT_ID: int | None
try:
    TELEGRAM_EROTIC_CHAT_ID = int(_erotic_raw) if _erotic_raw else None
except ValueError:
    TELEGRAM_EROTIC_CHAT_ID = None

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FAL_API_KEY        = os.getenv("FAL_API_KEY")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY     = os.getenv("TAVILY_API_KEY")

DIARY_DIR = Path.home() / "lena_diary"

OPENROUTER_BASE_URL  = "https://openrouter.ai/api/v1"
ANTHROPIC_BASE_URL   = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION    = "2023-06-01"

# Model routing — override any via .env
MODEL_NSFW = os.getenv("MODEL_NSFW", "gryphe/mythomax-l2-13b")
MODEL_CHAT = os.getenv("MODEL_CHAT", "claude-sonnet-4-6")

MAX_HISTORY_MESSAGES = 12

IMAGE_SIZE = "landscape_4_3"
IMAGE_STEPS = 28
# fal.ai のモデルエンドポイント。通常用と NSFW 用を分けられる。
# realistic-vision は enable_safety_checker=false で安定して NSFW 生成可能。
IMAGE_MODEL_SFW = os.getenv("IMAGE_MODEL_SFW", "fal-ai/flux/dev")
IMAGE_MODEL_NSFW = os.getenv("IMAGE_MODEL_NSFW", "fal-ai/realistic-vision")

# Naoya's context files (Google Drive local sync)
GDRIVE_BASE = Path.home() / "My Drive"
PROFILE_PATH = GDRIVE_BASE / "02_Personal" / "profile.md"
ENGLISH_CONTEXT_PATH = GDRIVE_BASE / "03_Learning" / "English_Learning" / "AI_context.md"
ENGLISH_SESSIONS_DIR = GDRIVE_BASE / "03_Learning" / "English_Learning" / "sessions"


def validate():
    missing = [k for k, v in {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "FAL_API_KEY":        FAL_API_KEY,
        "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
        "TAVILY_API_KEY":     TAVILY_API_KEY,
    }.items() if not v]
    if missing:
        print(f"[ERROR] Missing required env vars: {', '.join(missing)}")
        print("        Copy .env.example to .env and fill in your API keys.")
        sys.exit(1)
