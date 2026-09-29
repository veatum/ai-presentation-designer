"""Optional text-to-image enrichment for the star task.

Uses Hugging Face Inference Providers through InferenceClient when HF_TOKEN is
configured. The default application mode remains open-license image retrieval,
so generation does not unexpectedly add a paid external dependency.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from PIL import Image

DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"


def is_enabled(mode: str | None = None) -> bool:
    mode = (mode or os.getenv("IMAGE_MODE", "retrieve")).strip().lower()
    return mode in {"text_to_image", "t2i", "generate", "generated"} and bool(os.getenv("HF_TOKEN"))


def generate_image(prompt: str, output: str | Path, *, model: str | None = None, timeout: int = 45) -> dict:
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise ValueError("HF_TOKEN не задан: text-to-image режим отключён.")
    model = model or os.getenv("IMAGE_MODEL", DEFAULT_MODEL)
    provider = os.getenv("IMAGE_PROVIDER", "auto").strip() or "auto"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    try:
        from huggingface_hub import InferenceClient
    except ImportError as exc:
        raise RuntimeError("Не установлен huggingface_hub для text-to-image.") from exc

    client_kwargs = {"api_key": token, "timeout": timeout}
    if provider.lower() != "auto":
        client_kwargs["provider"] = provider
    client = InferenceClient(**client_kwargs)
    image = client.text_to_image(
        prompt=prompt[:1400],
        model=model,
        width=1344,
        height=756,
        num_inference_steps=4,
        guidance_scale=0.0,
    )
    if not isinstance(image, Image.Image):
        raise RuntimeError("Inference Providers не вернул изображение PIL.Image.")
    image = image.convert("RGB")
    image.thumbnail((2200, 1400), Image.Resampling.LANCZOS)
    image.save(output, "JPEG", quality=92, optimize=True)
    return {
        "path": str(output),
        "source": "Hugging Face Inference Providers",
        "model": model,
        "provider": provider,
        "prompt": prompt[:1400],
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "landing_url": f"https://huggingface.co/{model}",
        "license": "Apache-2.0 (model card)",
    }
