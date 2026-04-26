import asyncio
import logging
import random
import re
from html import escape
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from config.settings import TELEGRAM_BOT_TOKEN, MODEL_NSFW, TELEGRAM_EROTIC_CHAT_ID
from src.conversation import build_messages, append_assistant_reply
from src.llm import chat_claude, chat_openrouter
from src.image_gen import generate_image
from src.naoya_context import log_correction
from src.mode import (
    get_mode, set_mode, bump_erotic_count,
    get_channel, set_channel,
    CHAT, IN_PERSON, EROTIC,
    GENERAL, DIARY, EROTIC_CH, VALID_CHANNELS,
)
from src.db import get_daily_state, usage_summary
from src.daily import start_session, handle_session_message, end_session_manual
from src.pricing import (
    JPY_PER_USD, TAVILY_FREE_MONTHLY, TAVILY_OVER_PRICE,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
<b>Commands</b>

💬 /chat — テキストモード
📍 /meet — 一緒にいるモード
🔥 /sex  — エロモード（エロチャンネルへ自動切替）
📷 /photo — 画像を生成
📓 /daily — 今日の振り返りインタビュー
✅ /done  — 振り返り終了
📊 /usage — トークン・コスト確認
❓ /mode  — 現在のモード・チャンネル確認

<b>チャンネル切替</b>
🗂 /ch general — 普段の対話チャンネル
🗂 /ch diary   — 日記チャンネル
🗂 /ch erotic  — エロチャンネル

🔄 /help  — このメッセージ
""".strip()

EROTIC_USE_DEDICATED_TELEGRAM = (
    "🔥 エロ会話は、あなたが用意した「エロ専用の別 Telegram チャット」"
    "（非公開のスーパーグループ推奨。Botを管理者として追加）で行ってください。\n"
    "そのスーパーグループのチャットIDを <code>TELEGRAM_EROTIC_CHAT_ID</code> に設定していますか？"
    " この1対1チャットでエロを使うには、その行を <code>.env</code> から削除（空）にしてください。"
)


def _is_dedicated_erotic_telegram_chat(update: Update) -> bool:
    if TELEGRAM_EROTIC_CHAT_ID is None or update.effective_chat is None:
        return False
    return update.effective_chat.id == TELEGRAM_EROTIC_CHAT_ID


def _is_private_1o1_bot_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def _sync_telegram_chat_with_mode(user_id: int, update: Update) -> None:
    """Erotic split: 専用群では常に erotic+erotic_ch。1対1 では必ず非エロ扱いに戻す。"""
    if TELEGRAM_EROTIC_CHAT_ID is None:
        return
    if _is_dedicated_erotic_telegram_chat(update):
        set_mode(user_id, EROTIC)
        set_channel(user_id, EROTIC_CH)
    elif _is_private_1o1_bot_chat(update):
        if get_mode(user_id) == EROTIC:
            set_mode(user_id, CHAT)
        if get_channel(user_id) == EROTIC_CH:
            set_channel(user_id, GENERAL)


def _help_text() -> str:
    t = HELP_TEXT
    if TELEGRAM_EROTIC_CHAT_ID is not None:
        t += "\n\n<i>🔐 エロ専用の別Telegram（スーパーグループ）を .env の TELEGRAM_EROTIC_CHAT_ID で有効中。"
        " エロ会話はそちらでのみ行えます。</i>"
    return t


def _clean(text: str) -> str:
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


EROTIC_SOFT_LIMIT_CHARS = 150
EROTIC_WORD_CAP = 12


def _trim_erotic(text: str) -> str:
    text = text.strip()
    text = re.split(r'\n*📝', text, maxsplit=1)[0].strip()

    if len(text) <= EROTIC_SOFT_LIMIT_CHARS:
        return text

    m = re.match(r'\s*(\*[^*\n]+\*)\s*(.*)', text, re.DOTALL)
    if not m:
        first = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)[0]
        words = first.split()
        return ' '.join(words[:EROTIC_WORD_CAP]) + ('...' if len(words) > EROTIC_WORD_CAP else '')

    action, rest = m.group(1), m.group(2).strip()
    if not rest:
        return action

    first = re.split(r'(?<=[.!?])\s+|\*', rest, maxsplit=1)[0].strip()
    qm = re.match(r'("[^"]+")', first)
    if qm:
        first = qm.group(1)
    words = first.split()
    if len(words) > EROTIC_WORD_CAP:
        first = ' '.join(words[:EROTIC_WORD_CAP]) + '...'
    return f"{action} {first}".strip()


_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')


def _render_inline(text: str) -> str:
    placeholders = []

    def stash(m):
        placeholders.append((m.group(1), m.group(2)))
        return f"\x00LINK{len(placeholders)-1}\x00"

    masked = _MD_LINK_RE.sub(stash, text)
    masked = re.sub(r'"([^"]+)"', r'\1', masked)
    safe = escape(masked)
    for i, (label, url) in enumerate(placeholders):
        safe = safe.replace(
            f"\x00LINK{i}\x00",
            f'<a href="{escape(url, quote=True)}">{escape(label)}</a>',
        )
    return safe


def _format_reply(reply: str) -> str:
    reply = _clean(reply)
    parts = re.split(r'(\*[^*\n]+\*)', reply)
    lines = []
    for part in parts:
        if not part.strip():
            continue
        if part.startswith('*') and part.endswith('*') and len(part) > 2:
            lines.append(f'<b>{escape(part[1:-1].strip())}</b>')
        else:
            text = part.strip()
            if not text:
                continue
            lines.append(_render_inline(text))
    return '\n'.join(lines)


def _strip_emojis(text: str) -> str:
    return re.sub(r'[💕❤️]', '', text).rstrip()


def _reply_delay(reply: str) -> float:
    chars = len(reply)
    base = 1.0 + min(chars / 80, 5.0)
    return base + random.uniform(-0.3, 0.5)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_help_text(), parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_help_text(), parse_mode="HTML")


async def cmd_meet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    _sync_telegram_chat_with_mode(uid, update)
    if TELEGRAM_EROTIC_CHAT_ID and _is_dedicated_erotic_telegram_chat(update):
        await update.message.reply_text(
            "📍 一緒にいるモードは、Bot への 1対1 チャットで /meet を使ってください。"
        )
        return
    set_mode(uid, IN_PERSON)
    set_channel(uid, GENERAL)
    await update.message.reply_text("📍 In-person mode  |  🗂 general channel")


async def cmd_sex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    _sync_telegram_chat_with_mode(uid, update)
    if TELEGRAM_EROTIC_CHAT_ID and _is_private_1o1_bot_chat(update):
        await update.message.reply_text(EROTIC_USE_DEDICATED_TELEGRAM, parse_mode="HTML")
        return
    set_mode(uid, EROTIC)
    set_channel(uid, EROTIC_CH)
    await update.message.reply_text("🔥 Erotic mode  |  🗂 erotic channel")


async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    _sync_telegram_chat_with_mode(uid, update)
    if TELEGRAM_EROTIC_CHAT_ID and _is_dedicated_erotic_telegram_chat(update):
        await update.message.reply_text(
            "💬 普段の会話は Bot への 1対1 で /chat してください。ここはエロ専用の Telegram です。"
        )
        return
    set_mode(uid, CHAT)
    set_channel(uid, GENERAL)
    await update.message.reply_text("💬 Chat mode  |  🗂 general channel")


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _sync_telegram_chat_with_mode(user_id, update)
    mode = get_mode(user_id)
    channel = get_channel(user_id)
    mode_labels = {CHAT: "💬 Chat", IN_PERSON: "📍 In-person", EROTIC: "🔥 Erotic"}
    ch_labels = {GENERAL: "🗂 general", DIARY: "🗂 diary", EROTIC_CH: "🗂 erotic"}
    await update.message.reply_text(
        f"Mode: {mode_labels.get(mode, mode)}\n"
        f"Channel: {ch_labels.get(channel, channel)}"
    )


async def cmd_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    _sync_telegram_chat_with_mode(uid, update)
    if not context.args:
        channel = get_channel(uid)
        ch_labels = {GENERAL: "🗂 general", DIARY: "🗂 diary", EROTIC_CH: "🗂 erotic"}
        await update.message.reply_text(f"現在のチャンネル: {ch_labels.get(channel, channel)}")
        return

    requested = context.args[0].lower()
    if requested not in VALID_CHANNELS:
        await update.message.reply_text(
            f"チャンネルは general / diary / erotic のいずれかを指定してください。"
        )
        return

    if (
        TELEGRAM_EROTIC_CHAT_ID
        and _is_dedicated_erotic_telegram_chat(update)
        and requested != EROTIC_CH
    ):
        await update.message.reply_text(
            "ここはエロ専用の Telegram です。/ch general や /ch diary は 1対1 チャットで行ってください。"
        )
        return
    if requested == EROTIC_CH and TELEGRAM_EROTIC_CHAT_ID and _is_private_1o1_bot_chat(update):
        await update.message.reply_text(EROTIC_USE_DEDICATED_TELEGRAM, parse_mode="HTML")
        return

    set_channel(uid, requested)
    # erotic チャンネルに切り替えたらモードも連動
    if requested == EROTIC_CH:
        set_mode(uid, EROTIC)
        await update.message.reply_text("🗂 erotic channel  |  🔥 Erotic mode")
    elif requested == GENERAL:
        # general に戻したときはモードを chat にリセット
        if get_mode(uid) == EROTIC:
            set_mode(uid, CHAT)
        await update.message.reply_text("🗂 general channel  |  💬 Chat mode")
    else:
        await update.message.reply_text(f"🗂 {requested} channel")


async def cmd_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    _sync_telegram_chat_with_mode(user_id, update)
    mode = get_mode(user_id)
    args_text = " ".join(context.args) if context.args else ""

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="upload_photo"
    )

    # Erotic: pull scene cues from recent assistant action; non-erotic: use args or generic
    if mode == EROTIC:
        from src.db import get_history
        channel = get_channel(user_id)
        history = get_history(user_id, channel=channel)
        recent_actions = [m["content"] for m in history if m["role"] == "assistant"][-3:]
        scene_context = " ".join(recent_actions) + " " + args_text
    else:
        scene_context = args_text or "casual everyday outfit"

    try:
        image_bytes = await generate_image(context=scene_context, erotic=(mode == EROTIC))
        if image_bytes:
            await update.message.reply_photo(photo=image_bytes)
        else:
            await update.message.reply_text("画像生成に失敗しました")
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await update.message.reply_text(f"<code>{escape(str(e))}</code>", parse_mode="HTML")


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if TELEGRAM_EROTIC_CHAT_ID and _is_dedicated_erotic_telegram_chat(update):
        await update.message.reply_text("📓 /daily は Bot への 1対1 チャットで使ってください。")
        return
    state = get_daily_state(user_id)
    if state and state.get("active"):
        await update.message.reply_text(
            "セッション継続中です。終わるには /done を打ってください。"
        )
        return
    opening = await start_session(user_id)
    await update.message.reply_text(opening)


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import time as _time
    from datetime import datetime, timedelta

    now      = datetime.now()
    today_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    month_ts = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    days_in_month   = (now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)).day if now.month != 12 else 31
    day_of_month    = now.day

    today = {r["service"]: r for r in usage_summary(today_ts)}
    month = {r["service"]: r for r in usage_summary(month_ts)}

    def fmt_block(stats: dict, label: str) -> str:
        lines = [f"<b>【{label}】</b>"]
        total_usd = 0.0
        for svc in ("claude", "openrouter", "fal", "tavily"):
            r = stats.get(svc)
            if not r:
                continue
            cost = r["cost_usd"]
            total_usd += cost
            jpy = cost * JPY_PER_USD
            if svc == "claude":
                lines.append(
                    f"• Claude: {r['input_tokens']:,} in / {r['output_tokens']:,} out "
                    f"(¥{jpy:.1f})"
                )
            elif svc == "openrouter":
                lines.append(
                    f"• Mythomax: {r['input_tokens']:,} in / {r['output_tokens']:,} out "
                    f"(¥{jpy:.1f})"
                )
            elif svc == "fal":
                lines.append(f"• Images: {r['count']} 枚 (¥{jpy:.1f})")
            elif svc == "tavily":
                free_left = max(TAVILY_FREE_MONTHLY - r['count'], 0)
                if label.startswith("今月"):
                    lines.append(
                        f"• Tavily: {r['count']}/{TAVILY_FREE_MONTHLY} 検索 "
                        f"(無料枠 {free_left} 残, ¥{jpy:.1f})"
                    )
                else:
                    lines.append(f"• Tavily: {r['count']} 検索")
        lines.append(f"<b>合計: 約 ¥{total_usd * JPY_PER_USD:.1f}</b>")
        return "\n".join(lines)

    today_block = fmt_block(today, "今日")
    month_block = fmt_block(month, "今月")

    # Projection
    month_total_usd = sum(r["cost_usd"] for r in month.values())
    projected_jpy = (month_total_usd / max(day_of_month, 1)) * days_in_month * JPY_PER_USD

    msg = "📊 <b>Usage Report</b>\n\n" + today_block + "\n\n" + month_block
    msg += f"\n\n<b>【月予測】</b>\n約 ¥{projected_jpy:.0f} / 月"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if TELEGRAM_EROTIC_CHAT_ID and _is_dedicated_erotic_telegram_chat(update):
        await update.message.reply_text("✅ /done も 1対1 チャットで行ってください。")
        return
    state = get_daily_state(user_id)
    if not state or not state.get("active"):
        await update.message.reply_text("アクティブな /daily セッションはありません。")
        return
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )
    closing, _ = await end_session_manual(user_id)
    await update.message.reply_text(closing)


# ---------------------------------------------------------------------------
# Main message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text
    _sync_telegram_chat_with_mode(user_id, update)

    # If a /daily session is active, route there
    state = get_daily_state(user_id)
    if state and state.get("active"):
        if TELEGRAM_EROTIC_CHAT_ID and _is_dedicated_erotic_telegram_chat(update):
            await update.message.reply_text(
                "振り返り /daily の続きは、Bot への 1対1 チャットでお願いします。"
            )
            return
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
        try:
            reply, ended = await handle_session_message(user_id, user_text)
            await update.message.reply_text(reply)
        except Exception as e:
            import traceback
            logger.error(f"/daily error: {e}\n{traceback.format_exc()}")
            await update.message.reply_text(
                f"<code>ERROR: {escape(str(e))}</code>", parse_mode="HTML"
            )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        mode = get_mode(user_id)
        messages = build_messages(user_id, user_text)

        if mode == EROTIC:
            reply = await chat_openrouter(
                messages,
                model=MODEL_NSFW,
                max_tokens=80,
                stop=["\n\n", "📝", "I want to please", "Tell me if", "Keep going, don"],
            )
            reply = _trim_erotic(reply)
            count = bump_erotic_count(user_id)
            if count % 3 != 0:
                reply = _strip_emojis(reply)
        else:
            # /chat and /meet — Claude Sonnet with web search tool enabled
            reply = await chat_claude(messages, with_tools=True)

        # Skip persistence for erotic mode (per user request)
        if mode != EROTIC:
            append_assistant_reply(user_id, user_text, reply, mode)
            await asyncio.sleep(_reply_delay(reply))
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action="typing"
            )

        await update.message.reply_text(_format_reply(reply), parse_mode="HTML")

        if mode != EROTIC:
            log_correction(user_id, user_text, reply)

    except Exception as e:
        import traceback
        logger.error(f"Error: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(
            f"<code>ERROR: {escape(str(e))}</code>", parse_mode="HTML"
        )


def run_bot() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("meet", cmd_meet))
    app.add_handler(CommandHandler("sex", cmd_sex))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("ch", cmd_channel))
    app.add_handler(CommandHandler("photo", cmd_photo))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")
    app.run_polling()
