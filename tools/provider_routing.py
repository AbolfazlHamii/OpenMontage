"""Explicit tool/host/model constraints shared by capability selectors."""

from __future__ import annotations

import html
import re


def short_error(error, limit: int = 300) -> str:
    """One readable line from a provider error, for fallback reports.

    Some gateways answer a refused region with a full HTML page (Google's 403
    page is ~1.5 KB of markup and CSS); keep only its text. SDK errors that
    repr() a payload carry escaped newlines, which go too.
    """
    text = str(error)
    if re.search(r"<!doctype html|<html", text, re.IGNORECASE):
        text = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = " ".join(text.replace("\\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def filter_explicit_route(inputs, candidates):
    tool_name = inputs.get("preferred_tool")
    host = inputs.get("hosting_provider")
    model = inputs.get("model") or inputs.get("model_id") or inputs.get("model_name")
    selected = []
    for tool in candidates:
        if tool_name and tool.name != tool_name:
            continue
        if host and getattr(tool, "hosting_provider", tool.provider) != host:
            continue
        if model:
            props = tool.input_schema.get("properties", {})
            models = set()
            for field in ("model", "model_id", "model_name"):
                models.update(props.get(field, {}).get("enum", []))
            models.update(getattr(tool, "_MODELS", {}))
            models.update(getattr(tool, "_MODEL_ALIASES", {}))
            models.update(tool.get_info().get("model_catalog", {}))
            if model not in models:
                continue
        operation = inputs.get("generation_mode") or inputs.get("operation")
        routes = getattr(tool, "routes", None) or getattr(tool, "models", None)
        if isinstance(routes, dict) and operation and operation != "rank":
            model_routes = (
                routes.get(model, {}) if model else next(iter(routes.values()), {})
            )
            normalized = (
                "text_to_video"
                if operation == "generate" and tool.capability == "video_generation"
                else operation
            )
            if normalized not in model_routes:
                continue
        if tool.capability == "image_generation":
            props = tool.input_schema.get("properties", {})
            if any(inputs.get(k) and k not in props for k in ("mask_path", "mask_url")):
                continue
            if any(
                inputs.get(k) and k not in props and "images" not in props
                for k in ("image_path", "image_paths", "image_url", "image_urls")
            ):
                continue
            if operation == "precise_edit" and not (
                getattr(tool, "supports", {}).get("precise_edit")
                or isinstance(routes, dict)
                and any("precise_edit" in r for r in routes.values())
            ):
                continue
        selected.append(tool)
    return selected
