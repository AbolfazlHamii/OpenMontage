"""Hook lab: the hook types from narration-craft, backward compatible. No network."""

import jsonschema

from lib import fa_editorial as ed


def _hooks(types):
    return {"hooks": [{"text": f"هوک شماره‌ی {i} برای تست", "type": types[i % len(types)]} for i in range(12)]}


def test_schema_accepts_old_and_new_types():
    jsonschema.validate(_hooks(ed.ORIGINAL_HOOK_TYPES), ed.HOOKS_SCHEMA)
    data = _hooks(list(ed.HOOK_TYPES))
    data["hooks"][0]["open_loop"] = "چرا ماهی؟"
    jsonschema.validate(data, ed.HOOKS_SCHEMA)
    assert set(ed.ORIGINAL_HOOK_TYPES) < set(ed.HOOK_TYPES) and len(ed.HOOK_TYPES) == 12


def test_prompt_mix():
    full = ed.hooks_prompt("سامسونگ", "فکت‌ها")
    assert "1 of each" in full and all(f"- {t}:" in full for t in ed.HOOK_TYPES)
    assert "open_loop" in full and "no invented numbers" in full and "12" in full
    old = ed.hooks_prompt("x", types=ed.ORIGINAL_HOOK_TYPES)
    assert "2 of each" in old and "- cold_open:" not in old


def test_annotate_hooks_times_the_first_hook():
    hooks = [{"text": "احتمالاً گوشیِ توی دستت سامسونگه.", "type": "you"},
             {"text": "این شرکت در یک مغازه‌ی کوچیک توی شهر تگو کارش رو شروع کرد و همین‌طور ادامه داد.",
              "type": "story"}]
    out = ed.annotate_hooks(hooks, cps=9.0)
    assert out[0]["first_hook_kind"] == "you" and out[0]["first_hook_seconds"] < 3
    assert out[1]["first_hook_seconds"] is None  # no «تو», number, question or «ولی»
    assert out[0]["text"] == hooks[0]["text"] and "first_hook_seconds" not in hooks[0]
