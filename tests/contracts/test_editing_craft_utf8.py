"""The editing-craft tools read and write Persian text: every text open must name its encoding."""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FILES = [
    "lib/fa_edit_qa.py",
    "lib/sfx_synth.py",
    "scripts/fa_edit_pass.py",
    "scripts/fa_sfx_library.py",
    "scripts/fa_render_qa.py",
    "tools/audio/beat_detect.py",
    "tools/audio/music_duck.py",
    "tools/audio/sfx_placer.py",
    "tools/subtitle/word_captions.py",
]


@pytest.mark.parametrize("relative_path", FILES)
def test_text_io_names_utf8(relative_path: str) -> None:
    path = REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bare = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name not in {"open", "read_text", "write_text"}:
            continue
        if name == "open" and isinstance(func, ast.Attribute):
            continue  # wave.open / Path.open in binary mode
        if not any(k.arg == "encoding" for k in node.keywords):
            bare.append(node.lineno)
    assert bare == [], f"text I/O without encoding= at lines {bare}"
