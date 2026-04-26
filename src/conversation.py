from config.settings import MAX_HISTORY_MESSAGES
from config.character import SYSTEM_PROMPT
from src.naoya_context import load_naoya_context
from src.db import get_history, add_message
from src.mode import (
    get_mode, get_channel,
    IN_PERSON, EROTIC,
    IN_PERSON_PROMPT, EROTIC_PROMPT, CHAT_PROMPT, EROTIC_FEW_SHOT,
)

_BASE_PROMPT = SYSTEM_PROMPT + load_naoya_context()


def build_messages(user_id: int, new_message: str) -> list[dict]:
    channel = get_channel(user_id)
    history = get_history(user_id, channel=channel)
    history.append({"role": "user", "content": new_message})

    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]

    mode = get_mode(user_id)
    if mode == EROTIC:
        mode_prompt = EROTIC_PROMPT
    elif mode == IN_PERSON:
        mode_prompt = IN_PERSON_PROMPT
    else:
        mode_prompt = CHAT_PROMPT
    system = _BASE_PROMPT + mode_prompt

    if mode == EROTIC:
        return [{"role": "system", "content": system}] + EROTIC_FEW_SHOT + history
    return [{"role": "system", "content": system}] + history


def append_assistant_reply(
    user_id: int, user_message: str, assistant_reply: str, mode: str | None = None
) -> None:
    channel = get_channel(user_id)
    add_message(user_id, "user", user_message, mode, channel)
    add_message(user_id, "assistant", assistant_reply, mode, channel)
