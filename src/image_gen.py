import asyncio
import httpx
import logging
from config.settings import (
    FAL_API_KEY, IMAGE_SIZE, IMAGE_STEPS,
    IMAGE_MODEL_SFW, IMAGE_MODEL_NSFW,
    NOVITA_API_KEY, NOVITA_MODEL,
)
from config.character import IMAGE_PROMPT_BASE
from src.db import log_usage
from src.pricing import fal_cost

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "blurry, low quality, deformed, ugly, bad anatomy, watermark, text, "
    "cartoon, anime, extra limbs, mutated, censored, mosaic, pixelated genitals"
)

NEGATIVE_PROMPT_NSFW = (
    "blurry, low quality, deformed, ugly, bad anatomy, watermark, signature, text, "
    "cartoon, anime, extra limbs, mutated hands, extra fingers, bad hands, "
    "censored, mosaic, pixelated, black box, black rectangle, "
    "(worst quality:2), (low quality:2), amateur, sketch"
)

NSFW_KEYWORDS = ["sex", "naked", "nude", "undress", "underwear", "erotic", "porn",
                 "裸", "セックス", "エロ", "下着", "ヌード", "脱い"]

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
        + "explicit nudity, uncensored, NSFW, detailed body, "
        + "masterpiece, best quality, ultra-detailed, 8k"
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


# ---------------------------------------------------------------------------
# NovitaAI — async txt2img (NSFW 特化)
# ---------------------------------------------------------------------------

_NOVITA_TXT2IMG = "https://api.novita.ai/v3/async/txt2img"
_NOVITA_RESULT  = "https://api.novita.ai/v3/async/task-result"


async def _generate_novita(prompt: str) -> bytes:
    """Submit → poll → download via NovitaAI."""
    headers = {
        "Authorization": f"Bearer {NOVITA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "extra": {
            "enable_nsfw_detection": False,
            "response_image_type": "jpeg",
        },
        "request": {
            "model_name": NOVITA_MODEL,
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT_NSFW,
            "width": 512,
            "height": 768,
            "steps": 30,
            "image_num": 1,
            "guidance_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
            "seed": -1,
        },
    }

    async with httpx.AsyncClient(timeout=120) as client:
        # 1. Submit
        resp = await client.post(_NOVITA_TXT2IMG, headers=headers, json=payload)
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        logger.info(f"[NovitaAI] task submitted: {task_id}")

        # 2. Poll until finished (max 90s)
        for attempt in range(18):
            await asyncio.sleep(5)
            result = await client.get(
                _NOVITA_RESULT,
                headers=headers,
                params={"task_id": task_id},
            )
            result.raise_for_status()
            data = result.json()
            status = data.get("task", {}).get("status")
            logger.info(f"[NovitaAI] poll #{attempt + 1} status={status}")

            if status == "TASK_STATUS_SUCCEED":
                image_url = data["images"][0]["image_url"]
                img = await client.get(image_url)
                img.raise_for_status()
                log_usage(service="novita", model=NOVITA_MODEL, count=1, cost_usd=0.004)
                return img.content

            if status in ("TASK_STATUS_FAILED", "TASK_STATUS_CANCELED"):
                raise RuntimeError(f"NovitaAI task failed: {data}")

        raise TimeoutError("NovitaAI generation timed out after 90s")


# ---------------------------------------------------------------------------
# fal.ai fallback (SFW / NovitaAI 未設定時)
# ---------------------------------------------------------------------------

async def _generate_fal(prompt: str, erotic: bool) -> bytes:
    model = IMAGE_MODEL_NSFW if erotic else IMAGE_MODEL_SFW
    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json",
    }
    if erotic:
        payload = {
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT_NSFW,
            "image_size": IMAGE_SIZE,
            "num_inference_steps": 35,
            "num_images": 1,
            "enable_safety_checker": False,
            "guidance_scale": 5.0,
            "format": "jpeg",
        }
    else:
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
        resp = await client.post(f"https://fal.run/{model}", headers=headers, json=payload)
        resp.raise_for_status()
        image_url = resp.json()["images"][0]["url"]
        img = await client.get(image_url)
        img.raise_for_status()
        log_usage(service="fal", model=model, count=1, cost_usd=fal_cost(1))
        return img.content


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_image(context: str = "", erotic: bool = False) -> bytes | None:
    prompt = _build_erotic_prompt(context) if erotic else _build_contextual_prompt(context)
    use_novita = erotic and bool(NOVITA_API_KEY)

    logger.info(
        f"Generating image (erotic={erotic}, backend={'novita' if use_novita else 'fal'}) "
        f"prompt: {prompt[:100]}..."
    )

    try:
        if use_novita:
            return await _generate_novita(prompt)
        else:
            return await _generate_fal(prompt, erotic)
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None
