"""Persian thumbnail builder. No Chrome and no network: a fake runner stands in
for the browser, writing the screenshot and returning the DOM with a layout report."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from lib import fa_thumbnail as ft
from lib.fa_thumbnail import Variant

TITLE = "کل تاریخ سامسونگ در ۹۰ ثانیه"


@pytest.fixture
def still(tmp_path) -> Path:
    path = tmp_path / "still.png"
    Image.new("RGB", (1376, 768), (120, 90, 60)).save(path)
    return path


def text_item(role="headline", px=170, box=(600, 40, 1228, 250), **flags):
    return {"role": role, "text": "x", "px": px, "box": list(box),
            "too_wide": False, "outside": False, "badge_overlap": False, **flags}


def layout(*items, fonts_loaded=True):
    return {"fonts_loaded": fonts_loaded, "texts": list(items or [text_item()])}


class FakeChrome:
    """Writes a window-sized PNG to --screenshot and returns a DOM with a layout report."""

    def __init__(self, thumb_layout=None, sheet_size=(1200, 900)):
        self.thumb_layout = thumb_layout or layout()
        self.sheet_size = sheet_size
        self.calls = []

    def __call__(self, cmd, capture_output, timeout):
        self.calls.append(cmd)
        shot = Path(next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1])
        w, h = (int(v) for v in next(a for a in cmd if a.startswith("--window-size=")).split("=")[1].split(","))
        Image.new("RGB", (w, h), (30, 30, 30)).save(shot)
        if "preview_phone" in cmd[-1]:
            report = {"width": self.sheet_size[0], "height": self.sheet_size[1]}
        else:
            report = self.thumb_layout
        dom = f'<html><body><script type="application/json" id="om-layout">{json.dumps(report, ensure_ascii=False)}</script></body></html>'
        return SimpleNamespace(returncode=0, stdout=dom.encode("utf-8"), stderr=b"")


# ---- text ------------------------------------------------------------------

def test_clean_text_persian_letters_and_digits_keep_zwnj():
    assert ft.clean_text("  تاريخ  ك 1938 ") == "تاریخ ک ۱۹۳۸"
    assert ft.clean_text("ماهی‌فروشی") == "ماهی‌فروشی"


def test_split_lines_and_words():
    assert ft.split_lines("گوشی‌هاشو|سوزوند!") == ["گوشی‌هاشو", "سوزوند!"]
    assert ft.split_lines("با ماهی\nشروع شد") == ["با ماهی", "شروع شد"]
    # A half-space joins one word; a lone "؟!" is not a word.
    assert len(ft.words("گوشی‌هاشو سوزوند ؟!")) == 2


def test_repeats_title():
    assert ft.repeats_title("تاریخ سامسونگ", TITLE) == 1.0
    assert ft.repeats_title("گوشی‌هاشو سوزوند!", TITLE) == 0.0


def test_contrast_ratio():
    assert ft.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert ft.contrast_ratio("#1428a0", "#1428a0") == pytest.approx(1.0)
    for template in ft.TEMPLATES.values():
        for _, fg, bg in template["pairs"]:
            assert ft.contrast_ratio(ft.PALETTE[fg], ft.PALETTE[bg]) >= ft.MIN_CONTRAST


# ---- layout ----------------------------------------------------------------

def test_cover_box_covers_the_frame_and_clamps_focus():
    left, top, w, h = ft.cover_box(1376, 768)
    assert w >= ft.WIDTH and h >= ft.HEIGHT and left <= 0 and top <= 0
    assert left + w >= ft.WIDTH and top + h >= ft.HEIGHT
    # A focus at the far edge cannot pull the still off the frame.
    left, top, w, h = ft.cover_box(1376, 768, focus=(1.0, 1.0), zoom=1.5)
    assert left + w == ft.WIDTH and top + h == ft.HEIGHT
    left, top, *_ = ft.cover_box(1376, 768, focus=(0.0, 0.0), zoom=1.5)
    assert (left, top) == (0, 0)


def test_subject_in_frame_follows_zoom_and_focus():
    v = Variant("A", "punch", "x", focus=(0.5, 0.5), zoom=1.0, subject=(0.5, 0.5))
    assert ft.subject_in_frame(v, (1280, 720)) == (640, 360)


def test_variant_from_dict_validates_and_merges_defaults():
    v = Variant.from_dict({"id": "C", "template": "question", "headline": "ماهی؟!", "ring": [0.7, 0.5, 0.1]},
                          defaults={"focus": [0.6, 0.4]})
    assert v.focus == (0.6, 0.4) and v.ring == (0.7, 0.5, 0.1)
    with pytest.raises(ValueError):
        Variant.from_dict({"id": "X", "template": "nope", "headline": "x"})


@pytest.mark.parametrize("template", sorted(ft.TEMPLATES))
def test_build_html_fills_every_placeholder(template, still, tmp_path):
    font = tmp_path / "Vazirmatn-Black.ttf"
    font.write_bytes(b"")
    v = Variant("A", template, "گوشی‌هاشو|سوزوند <!>", kicker="۱۵۰ هزار", year="1995",
                ring=(0.5, 0.5, 0.1), side="left")
    page = ft.build_html(v, still, ft.Fonts(black=font, bold=font))
    assert not re.search(r"\$[a-z_{]", page)
    assert "سوزوند &lt;!&gt;" in page  # escaped, never raw HTML
    assert font.as_uri() in page and still.resolve().as_uri() in page
    assert 'class="frame side-left"' in page
    if template == "era":
        assert "۱۹۹۵" in page


def test_default_variants_cover_three_templates():
    a, b, c = ft.default_variants("با ماهی شروع شد", year="1938")
    assert [a.template, b.template, c.template] == ["punch", "era", "question"]
    assert c.headline.endswith("؟")


def test_find_fonts_uses_env_dir(tmp_path, monkeypatch):
    for name in ("Vazirmatn-Black.ttf", "Vazirmatn-ExtraBold.ttf"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setenv("FA_FONTS_DIR", str(tmp_path))
    fonts = ft.find_fonts()
    assert fonts.black == tmp_path / "Vazirmatn-Black.ttf"
    assert fonts.bold == tmp_path / "Vazirmatn-ExtraBold.ttf"
    assert ft.Fonts().css_src("black") == 'local("Vazirmatn Black")'


def test_find_chrome_prefers_env(tmp_path, monkeypatch):
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("CHROME_PATH", str(exe))
    assert ft.find_chrome() == str(exe)


def test_chrome_command(tmp_path):
    cmd = ft.chrome_command("chrome", tmp_path / "a b.html", tmp_path / "out.png", (1480, 960))
    assert "--headless=new" in cmd and "--dump-dom" in cmd and "--window-size=1480,960" in cmd
    assert cmd[-1].startswith("file:") and "%20" in cmd[-1]


def test_parse_layout_needs_the_report():
    assert ft.parse_layout('<script type="application/json" id="om-layout">{"texts": []}</script>') == {"texts": []}
    with pytest.raises(RuntimeError):
        ft.parse_layout("<html></html>")


# ---- checks ----------------------------------------------------------------

def test_check_variant_passes_a_clean_layout():
    v = Variant("A", "punch", "گوشی‌هاشو|سوزوند!")
    result = ft.check_variant(v, layout(), TITLE, subject_xy=(400, 500))
    assert result["passed"], result["problems"]
    assert result["phone_px"]["headline"] == pytest.approx(170 * 160 / 1280, abs=0.1)


def test_check_variant_problems():
    v = Variant("A", "punch", "یک دو سه چهار پنج شش هفت")
    items = [text_item(px=80), text_item(role="kicker", px=84, box=(1100, 650, 1250, 710), badge_overlap=True)]
    result = ft.check_variant(v, layout(*items, fonts_loaded=False), TITLE, subject_xy=(700, 100))
    text = " ".join(result["problems"])
    assert not result["passed"]
    assert "Vazirmatn" in text
    assert "headline is 10.0 px" in text
    assert "duration badge" in text
    assert "covers the subject" in text
    assert "7 words" in text


def test_check_variant_warns_on_title_repeat_and_low_contrast():
    v = Variant("A", "punch", "تاریخ سامسونگ")
    result = ft.check_variant(v, layout(), TITLE, palette={"ink": "#333333", "outline": "#222222"})
    assert any("repeats the title" in w for w in result["warnings"])
    assert any("contrast" in p for p in result["problems"])


# ---- files -----------------------------------------------------------------

def test_save_jpeg_steps_quality_down(tmp_path):
    png = tmp_path / "noise.png"
    Image.effect_noise((1280, 720), 90).convert("RGB").save(png)
    jpg = tmp_path / "noise.jpg"
    big = ft.save_jpeg(png, jpg)
    small = ft.save_jpeg(png, jpg, max_bytes=big // 2)
    assert small < big


def test_crop_png(tmp_path):
    png = tmp_path / "a.png"
    Image.new("RGB", (1480, 960)).save(png)
    ft.crop_png(png, (1280, 720))
    assert Image.open(png).size == (1280, 720)
    with pytest.raises(RuntimeError):
        ft.crop_png(png, (2000, 2000))


def test_make_thumbnails_end_to_end_with_fake_chrome(still, tmp_path):
    chrome = FakeChrome(layout(text_item(box=(800, 40, 1228, 250))))
    out = tmp_path / "out dir"
    report = ft.make_thumbnails(still, ft.default_variants("با ماهی|شروع شد", year="1938"), out,
                                title=TITLE, chrome="chrome", runner=chrome)
    assert len(chrome.calls) == 4  # three variants + the phone sheet
    assert report["all_passed"], [v["problems"] for v in report["variants"]]
    for v in report["variants"]:
        assert Image.open(v["png"]).size == (1280, 720)
        assert Path(v["jpg"]).stat().st_size <= ft.MAX_UPLOAD_BYTES
    assert Image.open(out / "preview_phone.png").size == (1200, 900)
    saved = json.loads((out / "thumbnails.json").read_text(encoding="utf-8"))
    assert saved["title"] == TITLE
    assert (out / "html" / "thumb_A.html").read_text(encoding="utf-8").count("شروع شد") == 1


def test_render_raises_on_chrome_failure(tmp_path):
    def broken(cmd, capture_output, timeout):
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"line one\nGPU process crashed")
    with pytest.raises(RuntimeError, match="GPU process crashed"):
        ft.render(tmp_path / "a.html", tmp_path / "a.png", "chrome", runner=broken)


def test_cli_quick_mode(still, tmp_path, monkeypatch):
    from scripts import fa_thumbnail as cli

    calls = {}

    def fake_make(background, variants, out_dir, title, chrome, palette):
        calls["templates"] = [v.template for v in variants]
        calls["ring"] = variants[2].ring
        return {"all_passed": True, "preview": "p.png", "variants": []}

    monkeypatch.setattr(cli, "make_thumbnails", fake_make)
    code = cli.main(["--background", str(still), "--text", "ماهی", "--ring", "0.7,0.5,0.1",
                     "--out", str(tmp_path)])
    assert code == 0
    assert calls == {"templates": ["punch", "era", "question"], "ring": (0.7, 0.5, 0.1)}
