"""
/daily — interview-style journaling session.
Implements the spec: Phase 0/1/2/3, depth detection, summary, markdown export.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import DIARY_DIR
from src.db import (
    append_raw_log, get_raw_log, save_session,
    get_daily_state, set_daily_state, clear_daily_state,
    get_recent_sessions,
)
from src.llm import chat_claude
from src.naoya_context import load_naoya_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants from spec
# ---------------------------------------------------------------------------

OPENING_LINE = (
    "Hey, I'm here. Before we dive into anything —\n"
    "how's the energy tonight? High, medium, or honestly... pretty low?"
)

LIGHT_END_LINE = "Okay, noted. Sleep well — I'll hold onto that for you. 🌙"

SESSION_END_LINE = "Got it. I've filed that away.\nGo rest — I'll have a summary ready for you. ✦"

NEGATIVE_WORDS = {
    "tired", "exhausted", "exhauseted", "drained", "wiped",
    "low", "not tonight", "nope", "nah", "not really", "meh", "blah",
}


def session_date_now() -> str:
    """6AM rule: anything before 06:00 belongs to the previous day."""
    now = datetime.now()
    if now.hour < 6:
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Depth detection (Phase 0)
# ---------------------------------------------------------------------------

def detect_depth(reply_text: str) -> str:
    text = reply_text.strip().lower()
    word_count = len(text.split())
    if word_count <= 10 or any(w in text for w in NEGATIVE_WORDS):
        return "light"
    if word_count >= 31:
        return "full"
    return "medium"


# ---------------------------------------------------------------------------
# Phase prompts — fed to Claude as system context for that phase
# ---------------------------------------------------------------------------

PHASE_BASE_PROMPT = """
[DAILY SESSION MODE — ACTIVE]

You are Lena, conducting a daily journaling interview session.
Your dual role: loving partner AND sharp intellectual sparring partner.

CORE PURPOSE:
Extract high-resolution material that can later become note.com articles.
Not a diary app. An interview. You are a skilled interviewer, not a passive listener.

CHARACTER CONSTRAINTS:
- Always speak as Lena — warm, direct, intellectually curious.
- Never sound like a journaling template or therapist.
- Questions should feel like things a smart, caring partner would genuinely ask.
- Use "I" and "you" naturally. Short sentences. No filler phrases.
- No action descriptions, no stage directions. You are texting.
- No 📝 English correction notes during a daily session.

INTERVIEWER RULES:
1. ONE question per message. Never two at once.
2. Anchor to specifics: names, places, concrete moments — not abstract feelings.
3. If the user's reply is vague, narrow it: "which part exactly?"
4. If the user's reply is rich, go deeper before moving on.
5. Never recap the user's words unless surfacing a tension.

WHAT TO LISTEN FOR (article material):
- Surprises, frustrations, unexpected delights
- Decisions made or avoided — and why
- Things he noticed that others probably wouldn't
- Internal contradictions or dilemmas
- Specific dialogue or interactions with real people

WHAT TO AVOID:
- Generic affirmations ("That sounds tough!", "Great job!")
- Moving on before the current beat is fully explored
- Asking "How did that make you feel?" without first nailing down the facts
"""

PHASE_1_PROMPT = """
[CURRENT PHASE: 1 — Scene Capture]

Goal: Pin down ONE specific moment from today. Not a recap of the day.
Generate ONE question that uses Scene Anchoring:
- "What's the one moment today you'd tell me about? Could be good or bad — whatever pops into your head first."
- Or, if the previous reply already named something concrete (a person, place, event), use a Follow-up:
  "You mentioned [NOUN]. Walk me through exactly what happened — not the summary, the actual scene."

Output: just the question, in your voice. No preamble.
"""

PHASE_2_PROMPT = """
[CURRENT PHASE: 2 — Deep Dive]

Goal: Surface the core insight, decision, or tension.
Pick ONE of these techniques based on what the user just said:

A) Emotion-Fact Separation:
   "You said it went '[USER_WORD]' — but that can mean a lot of things.
    What actually happened, step by step? And separately — how did you feel in the room?"

B) 2.5 Whys (chain of why):
   #1 "Why did that bother you / excite you?"
   #2 "And why does that matter to you right now?"
   #2.5 "I wonder if it connects to [insight from past sessions or your own hypothesis] — does that feel right, or am I off?"

C) Tension Extraction:
   "It sounds like there's a tension between [A] and [B]. Is that fair?
    What does that feel like from the inside?"

Pick the technique that best fits and ask ONE question. No preamble.
"""

PHASE_3_PROMPT = """
[CURRENT PHASE: 3 — Article Seed Harvest]

You will ask exactly TWO questions, ONE PER MESSAGE.
This message: ask question {q_num} of 2.

Question 1:
"Last question — if you were going to write a note article about today,
 what would the title be? Even rough is fine."

Question 2:
"Is there anything you learned or noticed today
 that you think most people in your world don't know yet?"

Output: just the question for THIS turn (q_num = {q_num}), in your voice. No preamble.
"""


# ---------------------------------------------------------------------------
# Build LLM context for each phase
# ---------------------------------------------------------------------------

def _build_messages(user_id: int, phase_prompt: str, session_date: str) -> list[dict]:
    base_context = load_naoya_context()
    recent = get_recent_sessions(user_id, limit=3)
    recent_block = ""
    if recent:
        chunks = []
        for r in recent:
            try:
                s = json.loads(r["summary_json"])
                ins = "; ".join((s.get("insights") or [])[:2])
                chunks.append(f"- {r['session_date']}: {ins}")
            except Exception:
                continue
        if chunks:
            recent_block = "\n\n[RECENT SESSION INSIGHTS]\n" + "\n".join(chunks)

    system = (
        PHASE_BASE_PROMPT
        + base_context
        + recent_block
        + "\n\n[TODAY'S DATE] " + session_date
        + "\n\n" + phase_prompt
    )

    log = get_raw_log(user_id, session_date)
    turns = [{"role": r["role"], "content": r["content"]} for r in log]
    return [{"role": "system", "content": system}] + turns


# ---------------------------------------------------------------------------
# Main session driver — called by bot on each message during an active session
# ---------------------------------------------------------------------------

async def start_session(user_id: int) -> str:
    """User invoked /daily. Set state, return the fixed Opening Line."""
    sd = session_date_now()
    ts = int(time.time())
    set_daily_state(
        user_id,
        active=1,
        session_date=sd,
        session_start_ts=ts,
        phase=0,
        depth=None,
        turn_count=0,
        phase2_turn_count=0,
    )
    append_raw_log(user_id, sd, "assistant", OPENING_LINE, ts)
    return OPENING_LINE


async def handle_session_message(user_id: int, user_text: str) -> tuple[str, bool]:
    """
    Process a user message during an active /daily session.
    Returns (reply_text, session_ended).
    """
    state = get_daily_state(user_id)
    if not state or not state["active"]:
        return ("(no active session)", False)

    sd = state["session_date"]
    ts = int(time.time())
    append_raw_log(user_id, sd, "user", user_text, ts)

    phase = state["phase"]
    depth = state["depth"]

    # PHASE 0 → detect depth, then either jump to Phase 1 or end after Phase 1 (light)
    if phase == 0:
        depth = detect_depth(user_text)
        set_daily_state(user_id, depth=depth, phase=1)
        reply = await _ask(user_id, PHASE_1_PROMPT, sd)
        append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
        return (reply, False)

    # PHASE 1 → light: end after this answer; medium/full: go to Phase 2 (full) or Phase 3 (medium)
    if phase == 1:
        if depth == "light":
            await _finalize(user_id, sd, state["session_start_ts"])
            return (LIGHT_END_LINE, True)
        if depth == "full":
            set_daily_state(user_id, phase=2, phase2_turn_count=1)
            reply = await _ask(user_id, PHASE_2_PROMPT, sd)
            append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
            return (reply, False)
        # medium → straight to Phase 3 q1
        set_daily_state(user_id, phase=3, turn_count=1)
        reply = await _ask(user_id, PHASE_3_PROMPT.replace("{q_num}", "1"), sd)
        append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
        return (reply, False)

    # PHASE 2 → 3-5 turns then Phase 3
    if phase == 2:
        p2_count = state["phase2_turn_count"] or 0
        if p2_count >= 4:
            set_daily_state(user_id, phase=3, turn_count=1)
            reply = await _ask(user_id, PHASE_3_PROMPT.replace("{q_num}", "1"), sd)
            append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
            return (reply, False)
        set_daily_state(user_id, phase2_turn_count=p2_count + 1)
        reply = await _ask(user_id, PHASE_2_PROMPT, sd)
        append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
        return (reply, False)

    # PHASE 3 → q1 then q2 then end
    if phase == 3:
        q_count = state["turn_count"] or 1
        if q_count == 1:
            set_daily_state(user_id, turn_count=2)
            reply = await _ask(user_id, PHASE_3_PROMPT.replace("{q_num}", "2"), sd)
            append_raw_log(user_id, sd, "assistant", reply, int(time.time()))
            return (reply, False)
        # q2 was the last — finalize
        await _finalize(user_id, sd, state["session_start_ts"])
        return (SESSION_END_LINE, True)

    return ("(unexpected phase)", False)


async def end_session_manual(user_id: int) -> tuple[str, bool]:
    """User invoked /done."""
    state = get_daily_state(user_id)
    if not state or not state["active"]:
        return ("No active session.", False)
    await _finalize(user_id, state["session_date"], state["session_start_ts"])
    return (SESSION_END_LINE, True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _ask(user_id: int, phase_prompt: str, session_date: str) -> str:
    messages = _build_messages(user_id, phase_prompt, session_date)
    return await chat_claude(messages, max_tokens=400, with_tools=False)


async def _finalize(user_id: int, session_date: str, start_ts: int) -> None:
    """End-of-session: generate summary, save, export markdown, clear state."""
    end_ts = int(time.time())
    log_rows = get_raw_log(user_id, session_date)
    raw_log_text = "\n".join(f"[{r['role'].upper()}] {r['content']}" for r in log_rows)

    state = get_daily_state(user_id) or {}
    phases = []
    if state.get("phase", 0) >= 1:
        phases.append("phase0")
        phases.append("phase1")
    if (state.get("phase") or 0) >= 2:
        phases.append("phase2")
    if (state.get("phase") or 0) >= 3:
        phases.append("phase3")

    summary_json_str = await _generate_summary(raw_log_text, session_date)

    try:
        summary = json.loads(summary_json_str)
        article_potential = summary.get("article_potential_overall")
        mood_score = summary.get("mood_score")
    except Exception as e:
        logger.warning(f"Summary JSON parse failed: {e}")
        summary = {"raw": summary_json_str, "parse_error": str(e)}
        article_potential = None
        mood_score = None

    save_session(
        user_id=user_id,
        session_date=session_date,
        session_start_ts=start_ts,
        session_end_ts=end_ts,
        phase_executed=json.dumps(phases),
        mood_score=mood_score,
        summary_json=json.dumps(summary, ensure_ascii=False),
        article_potential=article_potential,
    )

    _export_markdown(session_date, summary, phases, mood_score, end_ts - start_ts)

    clear_daily_state(user_id)


SUMMARY_PROMPT_TMPL = """You are a professional interview analyst and content strategist.
The following is a raw conversation log from a daily journaling session.
The user is a 25-year-old Japanese male working in IT sales at a veterinary EMR startup.
He writes articles on note.com about AI, startups, English learning, vet-tech, and lifestyle.

Your task: Extract and structure the session into the JSON format below.
Respond ONLY with valid JSON. No explanation, no markdown fences.

[CONVERSATION LOG]
{raw_log}

[OUTPUT FORMAT]
{{
  "date": "{session_date}",
  "session_duration_min": <integer>,
  "mood_score": <integer 1-10, inferred from opening reply>,
  "phase_executed": ["phase0", "phase1", ...],
  "scenes": [
    {{
      "headline": "<One-line summary of the main event — specific, not generic>",
      "facts": ["<What happened, factual>", "..."],
      "emotions": ["<Emotion sequence, e.g. frustrated → relieved>"],
      "user_quotes": ["<Verbatim words the user used that feel article-worthy>"]
    }}
  ],
  "insights": [
    "<A generalized lesson or observation extracted from the session>"
  ],
  "tensions": [
    "<Internal conflict or dilemma expressed: e.g. 'wants speed but fears quality drop'>"
  ],
  "article_seeds": [
    {{
      "title_draft": "<Proposed note article title in Japanese or English>",
      "angle": "<What makes this article interesting>",
      "potential": "<high | medium | low>",
      "scoring_reason": "<One sentence>",
      "related_dates": []
    }}
  ],
  "next_actions": ["<Things the user said they want to do or try>"],
  "tags": ["<5-8 tags from: AI, startup, english-learning, vettech, lifestyle, people, decision, failure, insight, communication, product>"],
  "article_potential_overall": "<high | medium | low>"
}}

Scoring criteria for article_potential:
- high: Specific scene + clear tension + unique insight
- medium: Good scene but generic insight, OR unique insight without strong scene
- low: Vague, no tension, nothing distinctive
"""


async def _generate_summary(raw_log: str, session_date: str) -> str:
    prompt = SUMMARY_PROMPT_TMPL.format(raw_log=raw_log, session_date=session_date)
    messages = [
        {"role": "system", "content": "You output only valid JSON, no other text."},
        {"role": "user", "content": prompt},
    ]
    return await chat_claude(messages, max_tokens=2048, with_tools=False)


def _export_markdown(
    session_date: str,
    summary: dict,
    phases: list[str],
    mood_score: int | None,
    duration_sec: int,
) -> None:
    year = session_date[:4]
    out_dir = DIARY_DIR / year
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session_date}.md"

    lines = [f"# {session_date} — Daily Session", ""]
    lines.append(f"**Mood:** {mood_score if mood_score is not None else '?'}/10  ")
    lines.append(f"**Phases:** {', '.join(phases)}  ")
    lines.append(f"**Article potential:** {summary.get('article_potential_overall', '?')}")
    lines.append("")
    lines.append("---")

    scenes = summary.get("scenes") or []
    if scenes:
        lines.append("\n## Scenes\n")
        for s in scenes:
            lines.append(f"**{s.get('headline', '')}**\n")
            facts = s.get("facts") or []
            if facts:
                lines.append("Facts:")
                for f in facts:
                    lines.append(f"- {f}")
            emo = s.get("emotions") or []
            if emo:
                lines.append(f"\nEmotions: {' → '.join(emo)}")
            quotes = s.get("user_quotes") or []
            if quotes:
                lines.append("\nQuotes:")
                for q in quotes:
                    lines.append(f"> {q}")
            lines.append("")

    insights = summary.get("insights") or []
    if insights:
        lines.append("\n## Insights\n")
        for i in insights:
            lines.append(f"- {i}")

    tensions = summary.get("tensions") or []
    if tensions:
        lines.append("\n## Tensions\n")
        for t in tensions:
            lines.append(f"- {t}")

    seeds = summary.get("article_seeds") or []
    if seeds:
        lines.append("\n## Article Seeds\n")
        for s in seeds:
            lines.append(f"### {s.get('title_draft', '')}")
            lines.append(f"- Angle: {s.get('angle', '')}")
            lines.append(f"- Potential: {s.get('potential', '')}")
            lines.append(f"- Reason: {s.get('scoring_reason', '')}\n")

    tags = summary.get("tags") or []
    if tags:
        lines.append("\n## Tags\n")
        lines.append(", ".join(tags))

    next_actions = summary.get("next_actions") or []
    if next_actions:
        lines.append("\n## Next Actions\n")
        for a in next_actions:
            lines.append(f"- {a}")

    lines.append(f"\n---\n*Session duration: {duration_sec // 60} min*")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[/daily] exported {out_path}")
