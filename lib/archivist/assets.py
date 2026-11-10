"""Stills for the Archivist character: one base frame and edits of it.

Every animation state is built from these stills (see ``lib/archivist/rig.py``),
so the edits must keep the framing of the base. Each edit is asked to change
one thing only; the rig pastes small patches (mouth, eyes) or cross-fades
whole frames (page turn, shelf pull).
"""

from __future__ import annotations

from pathlib import Path

STYLE = (
    "Flat 2D hand-drawn cartoon illustration for an animated history documentary: "
    "clean dark ink outlines, flat fills with soft painted shading, muted sepia and "
    "cream palette, cold grey-blue night tones, and British racing green (#1F4D3A) "
    "accents on the lamp shade, the cardigan and the file folders. "
    "No text, no letters, no numbers and no words anywhere in the image."
)

BASE_PROMPT = (
    STYLE + " Interior of a Cold War secret archive at night. Tall dark wooden "
    "shelves full of grey file boxes and green folders fill the left side and the "
    "back wall. On the right a tall window with rain streaking down the glass and "
    "a dim blue city at night outside. A green banker's desk lamp throws a warm "
    "pool of light on a heavy wooden desk in the middle of the room. Behind the "
    "desk sits an old archivist, about seventy, facing the viewer, upper body "
    "visible, centered in the frame: round wire glasses, neat white hair, short "
    "white beard, kind tired eyes, dark green knitted cardigan over a white shirt "
    "and a brown tie. Both hands rest on an open manila file of typed pages on "
    "the desk. Also on the desk: a stack of folders, a black rotary phone, a "
    "tea mug and a rubber stamp. His mouth is closed, a faint calm smile, eyes "
    "looking at the viewer. Medium-wide shot, eye level, the archivist takes the "
    "middle third of the frame, quiet empty floor and shelves on the left, the "
    "window on the right."
)

KEEP = (
    "Edit this image. Keep everything exactly the same: same framing and camera, "
    "same room, same lighting, same character, same pose, same objects in the "
    "same places, same drawing style. "
)

EDITS = {
    "mouth_open": KEEP + "Change only his mouth: open as if saying a long 'aah' "
    "while talking, showing a little of the upper teeth and a dark mouth inside. "
    "Nothing else changes.",
    "mouth_mid": KEEP + "Change only his mouth: slightly open, mid-word, lips "
    "parted a little. Nothing else changes.",
    "blink": KEEP + "Change only his eyes: fully closed in a blink behind the "
    "glasses. Nothing else changes.",
    "page_turn": KEEP + "Change only his right hand and the file: his right hand "
    "lifts the top page of the open manila file halfway, turning it, and he "
    "glances down at the page. Nothing else changes.",
    "shelf_reach": KEEP + "Change the archivist's pose only: he has stood up "
    "from the chair and turned to the shelves on the left, reaching up with one "
    "hand to pull a green file box from a high shelf, seen from the side. The "
    "chair is empty behind the desk. The room, the desk and the window are "
    "unchanged.",
    "file_hold": KEEP + "Change only his hands and what they hold: seated as "
    "before, he holds up an old green cardboard file folder, opened toward "
    "himself in both hands at chest height, a red string tie hanging from it, "
    "and he looks at the viewer over the top of his glasses. Nothing else "
    "changes.",
}

# Edits of another edit (source still, prompt): mouth shapes for reading a file.
SECOND_EDITS = {
    "file_mouth_open": ("file_hold", EDITS["mouth_open"]),
    "file_mouth_mid": ("file_hold", EDITS["mouth_mid"]),
}


def generate(out_dir: Path, names: list[str] | None = None, resolution: str = "2K") -> dict:
    """Make the base still and every edit missing from ``out_dir``."""
    from lib.env_loader import load_env
    from tools.graphics.avalai_gemini_image import AvalAIGeminiImage

    load_env()
    tool = AvalAIGeminiImage()
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"images": {}, "cost_usd": 0.0}
    jobs = [("base", None, BASE_PROMPT)] + [(n, "base", p) for n, p in EDITS.items()]
    jobs += [(n, src, p) for n, (src, p) in SECOND_EDITS.items()]
    for name, source, prompt in jobs:
        if names and name not in names:
            continue
        path = out_dir / f"{name}.png"
        if path.exists():
            continue
        inputs = {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "resolution": resolution,
            "output_path": str(path),
        }
        if source:
            inputs.update(generation_mode="edit", image_path=str(out_dir / f"{source}.png"))
        result = tool.execute(inputs)
        if not result.success:
            report["images"][name] = {"error": result.error}
            continue
        report["images"][name] = result.data["output"]
        report["cost_usd"] += result.cost_usd or 0.0
    return report
