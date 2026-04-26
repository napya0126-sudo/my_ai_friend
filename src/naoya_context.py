"""
Loads Naoya's profile and English learning context from Google Drive,
and logs English corrections to both SQLite and Google Drive sessions.
"""
import re
from datetime import date
from pathlib import Path
from config.settings import PROFILE_PATH, ENGLISH_CONTEXT_PATH, ENGLISH_SESSIONS_DIR


def load_naoya_context() -> str:
    sections = []

    if PROFILE_PATH.exists():
        profile = PROFILE_PATH.read_text(encoding="utf-8")
        sections.append(f"## Naoya's Profile\n{_trim(profile, 1200)}")

    if ENGLISH_CONTEXT_PATH.exists():
        eng = ENGLISH_CONTEXT_PATH.read_text(encoding="utf-8")
        sections.append(f"## Naoya's English Learning Status\n{_trim(eng, 800)}")

    if not sections:
        return ""

    return (
        "\n\n---\n## Context about Naoya (read silently, use naturally)\n\n"
        + "\n\n".join(sections)
    )


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(truncated)"


# ---------------------------------------------------------------------------
# English correction tracking
# ---------------------------------------------------------------------------

# Matches Claude's format: 📝 Quick note: "original" → "corrected"
CORRECTION_PATTERN = re.compile(
    r'📝\s*Quick note:\s*["“]([^"”]+)["”]\s*→\s*["“]([^"”]+)["”]',
    re.IGNORECASE,
)

CATEGORY_PATTERNS = {
    "article":     re.compile(r"\b(a|an|the)\b", re.IGNORECASE),
    "tense":       re.compile(r"\b(was|were|has|have|had|will|would|did)\b", re.IGNORECASE),
    "preposition": re.compile(r"\b(in|on|at|by|for|with|about|to|from)\b", re.IGNORECASE),
}


def _categorize(original: str, corrected: str) -> str:
    diff = set(corrected.lower().split()) - set(original.lower().split())
    diff_str = " ".join(diff)
    for cat, pat in CATEGORY_PATTERNS.items():
        if pat.search(diff_str):
            return cat
    return "word_choice"


def log_correction(user_id: int, user_message: str, assistant_reply: str) -> None:
    """Parse Lena's reply for 📝 corrections; save to DB and Google Drive."""
    matches = CORRECTION_PATTERN.findall(assistant_reply)
    if not matches:
        return

    from src.db import add_correction

    today = date.today().isoformat()
    log_path = ENGLISH_SESSIONS_DIR / f"{today}-lena.md"
    ENGLISH_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as f:
        if not log_path.exists() or log_path.stat().st_size == 0:
            f.write(f"# Lena English Corrections — {today}\n\n")
        for original, corrected in matches:
            original  = original.strip()
            corrected = corrected.strip()
            category  = _categorize(original, corrected)

            # DB
            add_correction(user_id, original, corrected, category)

            # Google Drive markdown
            f.write(
                f"- **Original**: {original}\n"
                f"  **Corrected**: {corrected}\n"
                f"  **Category**: `{category}`\n\n"
            )
