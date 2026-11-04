"""Gemini image models (Nano Banana) through AvalAI's native Gemini endpoint.

The same models google_imagen reaches through Google, usable from Iran
without a Google account. image_selector tries google_imagen first and
retries the same request here when Google refuses it (MIRROR_ORDER).
"""

from __future__ import annotations

import base64
import io
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import ToolResult, ToolStatus
from tools.graphics.google_imagen import GoogleImagen

# USD per output image by imageSize, from AvalAI's live catalog
# (https://api.avalai.ir/public/models, output_cost_per_image*, 2026-11-04).
# The docs say gemini-2.5-flash-image shut down on 2026-10-02 and that
# flash-lite is 1K only; the catalog still lists both as below.
PRICES = {
    "gemini-3.1-flash-image": {"1K": 0.0672, "2K": 0.101, "4K": 0.151},
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-3.1-flash-lite-image": {"1K": 0.0336, "2K": 0.0672, "4K": 0.1344},
    "gemini-2.5-flash-image": {"1K": 0.04},
}
DEFAULT_MODEL = "gemini-3.1-flash-image"


class AvalAIGeminiImage(GoogleImagen):
    name = "avalai_gemini_image"
    provider = "avalai"
    install_instructions = (
        "Set AVALAI_API_KEY (AvalAI console). AVALAI_BASE_URL overrides "
        "https://api.avalai.ir."
    )
    agent_skills = []
    best_for = [
        "Gemini image models (Nano Banana) when Google's API is not reachable",
        "editing and compositing with up to 14 local reference images",
    ]
    not_good_for = [
        "Imagen models (Google only)",
        "negative prompt control (not supported)",
        "offline generation",
    ]
    input_schema = {
        **GoogleImagen.input_schema,
        "properties": {
            **GoogleImagen.input_schema["properties"],
            "model": {
                "type": "string",
                "enum": list(PRICES),
                "default": DEFAULT_MODEL,
                "description": "Gemini image model served by AvalAI.",
            },
        },
    }
    side_effects = [
        "writes image file to output_path",
        "calls AvalAI API",
    ]

    def get_status(self) -> ToolStatus:
        if os.environ.get("AVALAI_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        prices = PRICES.get(inputs.get("model") or DEFAULT_MODEL, PRICES[DEFAULT_MODEL])
        price = prices.get(inputs.get("resolution") or "1K", max(prices.values()))
        return round(price * inputs.get("number_of_images", 1), 4)

    def build_request(self, inputs: dict[str, Any]) -> dict[str, Any]:
        model = inputs.get("model") or DEFAULT_MODEL
        if model not in PRICES:
            raise ValueError(f"Unsupported AvalAI image model: {model}")
        if inputs.get("image_url") or inputs.get("image_urls") or inputs.get("mask_url"):
            raise ValueError(
                "AvalAI image adapter accepts local image_path/image_paths, not image URLs or masks"
            )
        paths = list(inputs.get("image_paths") or [])
        if inputs.get("image_path"):
            paths.insert(0, inputs["image_path"])
        if len(paths) > 14:
            raise ValueError("At most 14 reference images")
        if inputs.get("generation_mode") == "edit" and not paths:
            raise ValueError("Edit requires source images")
        if inputs.get("generation_mode") == "generate" and paths:
            raise ValueError("Use edit for source images")

        image_config = {"aspectRatio": self._resolve_aspect_ratio(inputs)}
        if inputs.get("resolution"):
            if inputs["resolution"] not in PRICES[model]:
                raise ValueError(f"{model} does not offer {inputs['resolution']} output")
            image_config["imageSize"] = inputs["resolution"]

        parts: list[dict[str, Any]] = [{"text": inputs["prompt"]}]
        parts.extend(
            {
                "inlineData": {
                    "mimeType": mimetypes.guess_type(p)[0] or "image/png",
                    "data": base64.b64encode(Path(p).read_bytes()).decode(),
                }
            }
            for p in paths
        )
        return {
            "model": model,
            "body": {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    # The only combination AvalAI documents; text parts are skipped.
                    "responseModalities": ["TEXT", "IMAGE"],
                    "imageConfig": image_config,
                },
            },
        }

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            key = os.environ.get("AVALAI_API_KEY")
            if not key:
                raise ValueError("No AvalAI API key. " + self.install_instructions)
            request = self.build_request(inputs)

            import requests

            base_url = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir")
            url = f"{base_url.rstrip('/')}/v1beta/models/{request['model']}:generateContent"
            images: list[tuple[bytes, str]] = []
            for _ in range(inputs.get("number_of_images", 1)):
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    json=request["body"],
                    timeout=300,
                )
                if response.status_code != 200:
                    raise ValueError(
                        f"AvalAI returned HTTP {response.status_code}: {response.text[:300]}"
                    )
                image = next(
                    (
                        part["inlineData"]
                        for candidate in response.json().get("candidates", [])
                        for part in candidate.get("content", {}).get("parts", [])
                        if part.get("inlineData", {}).get("data")
                    ),
                    None,
                )
                if not image:
                    raise ValueError(
                        f"No image data returned by {request['model']} (text-only response)."
                    )
                images.append((base64.b64decode(image["data"]), image.get("mimeType", "")))

            outputs: list[str] = []
            for (data, mime), path in zip(
                images, self._output_paths(inputs.get("output_path"), len(images))
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                self._write_image(data, mime, path)
                outputs.append(str(path))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": request["model"],
                "prompt": inputs["prompt"],
                "aspect_ratio": request["body"]["generationConfig"]["imageConfig"]["aspectRatio"],
                "output": outputs[0],
                "outputs": outputs,
                "images_generated": len(outputs),
                "cost_status": "estimated",
            },
            artifacts=outputs,
            cost_usd=self.estimate_cost({**inputs, "number_of_images": len(outputs)}),
            duration_seconds=round(time.time() - start, 2),
            model=request["model"],
        )

    @staticmethod
    def _write_image(data: bytes, mime: str, path: Path) -> None:
        """Write the bytes, re-encoding when the file extension asks for another format."""
        wanted = mimetypes.guess_type(path.name)[0]
        if not wanted or wanted == mime.split(";")[0].strip().lower():
            path.write_bytes(data)
            return
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            if wanted == "image/jpeg" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(path)
