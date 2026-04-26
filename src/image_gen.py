import httpx
import logging
from config.settings import FAL_API_KEY, IMAGE_SIZE, IMAGE_STEPS
from config.character import IMAGE_PROMPT_BASE
from src.db import log_usage
from src.pricing import fal_cost

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "blurry, low quality, deformed, ugly, bad anatomy, watermark, text, "
    "cartoon, anime, extra limbs, mutated, censored, mosaic, pixelated genitals"
)

NSFW_KEYWORDS = ["sex", "naked", "nude", "undress", "underwear", "erotic", "porn",
                 "裸", "セックス", "エロ", "下着", "ヌード", "脱い"]

# NSFWシーン別プロンプトはローカル専用の config/nsfw_scenes.py から読み込む。
# そのファイルは .gitignore 済みで GitHub には存在しない。
# ファイルがない環境では空リストにフォールバックし、汎用プロンプトが使われる。
# シーンを追加・編集したい場合は config/nsfw_scenes.py を直接編集すること。
try:
    from config.nsfw_scenes import NSFW_SCENE_MAP
except ImportError:
    NSFW_SCENE_MAP = []


def _erotic_scene_modifiers(context: str) -> str:
    text = context.lower()
    for keywords, fragment in NSFW_SCENE_MAP:
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
