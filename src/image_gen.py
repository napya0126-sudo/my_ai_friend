import httpx
import logging
from config.settings import FAL_API_KEY, IMAGE_SIZE, IMAGE_STEPS
from config.character import IMAGE_PROMPT_BASE
from src.db import log_usage
from src.pricing import fal_cost

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "blurry, low quality, deformed, ugly, bad anatomy, watermark, text, "
    "cartoon, anime, extra limbs, mutated, clothed, censored, underwear visible"
)

NSFW_KEYWORDS = ["sex", "naked", "nude", "undress", "underwear", "erotic", "porn",
                 "裸", "セックス", "エロ", "下着", "ヌード", "脱い"]

# Map action keywords → explicit image prompt fragments.
# Order matters: more specific patterns first.
EROTIC_ACTION_MAP = [
    (("mouth", "suck", "lick him", "tongue", "kneel", "throat", "blowjob", "deepthroat"),
     "fully nude woman kneeling between his legs, oral sex, explicit blowjob, bare breasts visible, intimate pov, close-up of her face"),
    (("rides", "riding", "cowgirl", "on top of him", "straddl", "bouncing"),
     "fully nude woman in cowgirl position, riding him, bare breasts exposed, explicit sex, view from below"),
    (("from behind", "doggy", "ass up", "bent over", "all fours"),
     "fully nude woman on all fours, doggy style position, explicit sex from behind, bare ass and back exposed"),
    (("missionary", "legs around", "underneath him", "on her back"),
     "fully nude woman lying on her back, legs spread, missionary sex position, bare body fully exposed"),
    (("fingers", "fingering", "rubs her", "touches herself", "clit"),
     "fully nude woman touching herself, fingers between her legs, bare body, explicit solo"),
    (("kiss", "lips", "tongues"),
     "nude woman in passionate kiss, bare body close-up, intimate"),
    (("breast", "nipple", "chest", "topless"),
     "topless woman, bare breasts fully exposed, nipples visible, sensual"),
    (("undress", "strip", "unbutton", "bra", "panties", "lingerie"),
     "woman removing lingerie, half-nude, bra falling off, bare breasts being revealed"),
]


def _erotic_scene_modifiers(context: str) -> str:
    text = context.lower()
    for keywords, fragment in EROTIC_ACTION_MAP:
        if any(kw in text for kw in keywords):
            return fragment
    return "fully nude woman, completely naked, bare body exposed, sensual intimate pose"


def _build_erotic_prompt(context: str) -> str:
    scene = _erotic_scene_modifiers(context)
    return (
        IMAGE_PROMPT_BASE
        + f", {scene}, bedroom setting, soft warm lighting, "
        + "natural skin texture, photorealistic, shallow depth of field, "
        + "explicit nudity, uncensored, NSFW, detailed body"
    )


def _build_contextual_prompt(context: str) -> str:
    context_lower = context.lower()

    if any(w in context_lower for w in NSFW_KEYWORDS):
        return IMAGE_PROMPT_BASE + ", intimate setting, bedroom, sensual, tasteful nudity"
    elif any(w in context_lower for w in ["gym", "sport", "exercise", "workout"]):
        return IMAGE_PROMPT_BASE + ", wearing sportswear, gym background"
    elif any(w in context_lower for w in ["office", "work", "meeting", "ceo"]):
        return IMAGE_PROMPT_BASE + ", wearing business attire, modern office background"
    elif any(w in context_lower for w in ["cafe", "coffee", "morning"]):
        return IMAGE_PROMPT_BASE + ", casual outfit, cozy cafe background"
    elif any(w in context_lower for w in ["outdoor", "park", "walk", "nature"]):
        return IMAGE_PROMPT_BASE + ", casual outfit, outdoor nature background"
    elif any(w in context_lower for w in ["beach", "swim", "summer", "海"]):
        return IMAGE_PROMPT_BASE + ", wearing swimsuit, beach background, sunny day"
    else:
        return IMAGE_PROMPT_BASE + ", casual everyday outfit, natural lighting"


async def generate_image(context: str = "", erotic: bool = False) -> bytes | None:
    prompt = _build_erotic_prompt(context) if erotic else _build_contextual_prompt(context)
    logger.info(f"Generating image (erotic={erotic}) with prompt: {prompt[:120]}...")

    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "image_size": IMAGE_SIZE,
        "num_inference_steps": IMAGE_STEPS,
        "num_images": 1,
        "enable_safety_checker": False,
        "guidance_scale": 3.5,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://fal.run/fal-ai/flux/dev",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        image_url = data["images"][0]["url"]
        img_response = await client.get(image_url)
        img_response.raise_for_status()
        log_usage(service="fal", model="flux-dev", count=1, cost_usd=fal_cost(1))
        return img_response.content
