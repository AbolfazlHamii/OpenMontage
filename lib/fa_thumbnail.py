"""Persian YouTube thumbnails: one background still + short text -> A/B variants.

The still carries no text. Every Persian word is HTML set in Vazirmatn over
it (templates in styles/thumbnails/fa/), rendered to 1280x720 by a headless
Chrome. The page shrinks each text group to its box and writes its layout
(font sizes, boxes, overlap with the duration badge) into the DOM, so the
checks below run on what was actually drawn, not on what was asked for.

Checks per variant: readable at phone size (font px scaled to a 160 px wide
thumbnail), text/backing contrast (WCAG ratio), word count, nothing under
the duration badge, no overflow, JPG under YouTube's 2 MB limit. A phone
preview sheet (every variant at feed sizes, light and dark) is rendered for
the eye check that no number replaces.

See skills/creative/youtube-packaging.md for the design rules.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Callable, Optional

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "styles" / "thumbnails" / "fa"

WIDTH, HEIGHT = 1280, 720
PHONE_WIDTH = 160  # smallest common size: the Up Next list
PREVIEW_WIDTHS = (360, 246, 160)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
# The duration badge covers roughly this share of the bottom-right corner.
BADGE_ZONE = (0.20, 0.14)
MIN_CONTRAST = 4.5
MAX_WORDS = 4
WINDOW_MARGIN = (200, 240)

# Smallest acceptable height, in px, of each text role on a 160 px thumbnail.
MIN_PHONE_PX = {"headline": 12.0, "year": 10.0, "kicker": 7.5}

# Channel palette, from the Samsung sample (hyperframes-sample/index.html).
PALETTE = {
    "ink": "#ffffff",
    "outline": "#16100b",
    "accent": "#1428a0",
    "paper": "#fff8ec",
    "dark": "#16100b",
    "fire": "#ff8a2a",
}

# Per template: the text roles it shows, the box each may fill (px), the
# starting and minimum font size, the colour pairs that must contrast, and
# the default grade of the still.
TEMPLATES: dict[str, dict[str, Any]] = {
    "punch": {
        "roles": {
            "headline": {"max_w": 660, "px": 170, "min_px": 96},
            "kicker": {"max_w": 600, "px": 84, "min_px": 60},
        },
        "pairs": [("headline", "ink", "outline"), ("kicker", "ink", "accent")],
        "grade": "saturate(1.15) contrast(1.06)",
    },
    "era": {
        "roles": {
            "year": {"max_w": 520, "px": 150, "min_px": 90},
            "headline": {"max_w": 640, "px": 124, "min_px": 90},
            "kicker": {"max_w": 600, "px": 70, "min_px": 56},
        },
        "pairs": [("year", "paper", "accent"), ("headline", "ink", "outline"),
                  ("kicker", "paper", "outline")],
        "grade": "sepia(0.22) saturate(1.08) contrast(1.05)",
    },
    "question": {
        "roles": {
            "headline": {"max_w": 600, "px": 180, "min_px": 96},
            "kicker": {"max_w": 560, "px": 72, "min_px": 56},
        },
        "pairs": [("headline", "ink", "outline"), ("kicker", "ink", "outline")],
        "grade": "saturate(1.12) contrast(1.05)",
    },
}

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
_TO_FA_DIGITS = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹" * 2)
_LAYOUT_RE = re.compile(r'<script type="application/json" id="om-layout">(.*?)</script>', re.S)


@dataclass
class Variant:
    id: str
    template: str
    headline: str
    kicker: str = ""
    year: str = ""
    focus: tuple[float, float] = (0.5, 0.5)  # point of the still kept in view, 0-1
    zoom: float = 1.0
    ring: Optional[tuple[float, float, float]] = None  # x, y, radius as frame fractions
    subject: Optional[tuple[float, float]] = None  # face/object in the still that text must not cover; default focus
    grade: Optional[str] = None  # CSS filter for the still
    side: str = "right"  # text block at the right (RTL reading start) or left edge
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: Optional[dict[str, Any]] = None) -> "Variant":
        merged = {**(defaults or {}), **data}
        if merged.get("template") not in TEMPLATES:
            raise ValueError(f"unknown template {merged.get('template')!r}; "
                             f"choose from {sorted(TEMPLATES)}")
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in merged.items() if k in known}
        for key in ("focus", "ring", "subject"):
            if kwargs.get(key) is not None:
                kwargs[key] = tuple(float(v) for v in kwargs[key])
        return cls(**kwargs)


@dataclass
class Fonts:
    black: Optional[Path] = None
    bold: Optional[Path] = None
    searched: list[str] = field(default_factory=list)

    def css_src(self, weight: str) -> str:
        path = self.black if weight == "black" else self.bold
        local = "Vazirmatn Black" if weight == "black" else "Vazirmatn ExtraBold"
        if path:
            return f'url("{path.as_uri()}")'
        return f'local("{local}")'


# ---- text ----------------------------------------------------------------

def clean_text(text: str) -> str:
    """Persian letters and digits, single spaces; ZWNJ is kept."""
    text = (text or "").translate(_ARABIC_TO_PERSIAN).translate(_TO_FA_DIGITS)
    return re.sub(r"[ \t]+", " ", text).strip()


def split_lines(text: str) -> list[str]:
    """A headline may be given on two lines with '|' or a newline."""
    return [line.strip() for line in re.split(r"\s*(?:\||\n)\s*", clean_text(text)) if line.strip()]


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s|]+", clean_text(text)) if re.search(r"\w", w)]


_STOP = {"در", "از", "به", "با", "که", "و", "را", "رو", "این", "یه", "یک", "تا", "برای", "کل"}


def repeats_title(thumb_text: str, title: str) -> float:
    """Share of the thumbnail's content words that the title already says."""
    def strip(w: str) -> str:
        return re.sub(r"[^\w\u200c]", "", w)

    thumb = [strip(w) for w in words(thumb_text) if strip(w) not in _STOP]
    title_words = {strip(w) for w in words(title)}
    thumb = [w for w in thumb if w]
    if not thumb:
        return 0.0
    return sum(1 for w in thumb if w in title_words) / len(thumb)


# ---- colour --------------------------------------------------------------

def _channel(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---- layout --------------------------------------------------------------

def cover_box(img_w: int, img_h: int, focus: tuple[float, float] = (0.5, 0.5),
              zoom: float = 1.0, frame: tuple[int, int] = (WIDTH, HEIGHT)) -> tuple[int, int, int, int]:
    """Left, top, width, height of the still so it covers the frame, zoomed,
    with the focus point as close to the centre as the edges allow."""
    fw, fh = frame
    scale = max(fw / img_w, fh / img_h) * max(zoom, 1.0)
    w, h = round(img_w * scale), round(img_h * scale)
    left = fw / 2 - focus[0] * w
    top = fh / 2 - focus[1] * h
    left = min(0, max(fw - w, left))
    top = min(0, max(fh - h, top))
    return round(left), round(top), w, h


def subject_in_frame(variant: Variant, img_size: tuple[int, int]) -> tuple[int, int]:
    left, top, w, h = cover_box(img_size[0], img_size[1], variant.focus, variant.zoom)
    sx, sy = variant.subject or variant.focus
    return round(left + sx * w), round(top + sy * h)


def _span(role: str, text: str, spec: dict[str, Any], css_class: str) -> str:
    return (f'<span class="fit {css_class}" data-role="{role}" data-fit="{role}" '
            f'data-max-w="{spec["max_w"]}" data-min-px="{spec["min_px"]}" '
            f'style="font-size:{spec["px"]}px">{html.escape(text)}</span>')


def text_html(variant: Variant) -> dict[str, str]:
    roles = TEMPLATES[variant.template]["roles"]
    out = {"headline_html": "", "kicker_html": "", "year_html": ""}
    if "headline" in roles:
        out["headline_html"] = "\n".join(
            _span("headline", line, roles["headline"], "headline stroke")
            for line in split_lines(variant.headline))
    if variant.kicker and "kicker" in roles:
        css = "kicker" if variant.template == "punch" else "kicker stroke"
        out["kicker_html"] = _span("kicker", clean_text(variant.kicker), roles["kicker"], css)
    if variant.year and "year" in roles:
        out["year_html"] = _span("year", clean_text(variant.year), roles["year"], "year")
    return out


def find_fonts(extra_dirs: Optional[list[Path]] = None) -> Fonts:
    dirs: list[Path] = list(extra_dirs or [])
    for env in ("FA_FONTS_DIR", "SUBTITLE_FONTS_DIR"):
        if os.environ.get(env):
            dirs.append(Path(os.environ[env]))
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path(r"C:\Windows\Fonts"), Path.home() / ".fonts", Path("/usr/share/fonts")]
    fonts = Fonts(searched=[str(d) for d in dirs])
    for d in dirs:
        if not d.is_dir():
            continue
        fonts.black = fonts.black or next(iter(d.glob("Vazirmatn-Black.ttf")), None)
        fonts.bold = fonts.bold or next(iter(d.glob("Vazirmatn-ExtraBold.ttf")), None)
    fonts.bold = fonts.bold or fonts.black
    return fonts


def build_html(variant: Variant, background: Path, fonts: Fonts,
               palette: Optional[dict[str, str]] = None) -> str:
    palette = {**PALETTE, **(palette or {})}
    tpl = TEMPLATES[variant.template]
    with Image.open(background) as im:
        img_w, img_h = im.size
    left, top, w, h = cover_box(img_w, img_h, variant.focus, variant.zoom)

    ring = variant.ring or (0.0, 0.0, 0.0)
    ring_d = round(ring[2] * 2 * HEIGHT)
    fragment = Template((TEMPLATES_DIR / f"{variant.template}.html").read_text(encoding="utf-8"))
    body = fragment.substitute(
        **text_html(variant),
        width=WIDTH, height=HEIGHT,
        ring_left=round(ring[0] * WIDTH - ring_d / 2),
        ring_top=round(ring[1] * HEIGHT - ring_d / 2),
        ring_d=ring_d,
        ring_hidden="" if variant.ring else " hidden",
    )
    base = Template((TEMPLATES_DIR / "base.html").read_text(encoding="utf-8"))
    return base.substitute(
        **palette,
        width=WIDTH, height=HEIGHT,
        font_black=fonts.css_src("black"), font_bold=fonts.css_src("bold"),
        bg_src=background.resolve().as_uri(),
        bg_left=left, bg_top=top, bg_w=w, bg_h=h,
        bg_filter=variant.grade or tpl["grade"],
        side="left" if variant.side == "left" else "right",
        badge_x=round(WIDTH * (1 - BADGE_ZONE[0])),
        badge_y=round(HEIGHT * (1 - BADGE_ZONE[1])),
        variant_body=body,
    )


# ---- rendering -----------------------------------------------------------

def find_chrome() -> Optional[str]:
    for env in ("CHROME_PATH", "HYPERFRAMES_BROWSER_PATH"):
        if os.environ.get(env) and Path(os.environ[env]).is_file():
            return os.environ[env]
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def chrome_command(chrome: str, html_path: Path, png_path: Path, size: tuple[int, int]) -> list[str]:
    return [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--disable-extensions", "--force-device-scale-factor=1",
        f"--window-size={size[0]},{size[1]}", "--virtual-time-budget=4000",
        f"--screenshot={png_path.resolve()}", "--dump-dom", html_path.resolve().as_uri(),
    ]


def parse_layout(dom: str) -> dict[str, Any]:
    match = _LAYOUT_RE.search(dom or "")
    if not match:
        raise RuntimeError("the page wrote no layout report (fonts or script failed to load)")
    return json.loads(match.group(1))


def render(html_path: Path, png_path: Path, chrome: str, size: tuple[int, int] = (WIDTH, HEIGHT),
           runner: Callable[..., Any] = subprocess.run, timeout: int = 90) -> str:
    """Screenshot the page and return the DOM after its scripts ran.

    Headless Chrome's viewport is smaller than --window-size (the bottom ~90 px
    come out blank), so the window gets a margin and the PNG is cropped to
    `size` afterwards (crop_png)."""
    window = (size[0] + WINDOW_MARGIN[0], size[1] + WINDOW_MARGIN[1])
    proc = runner(chrome_command(chrome, html_path, png_path, window),
                  capture_output=True, timeout=timeout)
    if proc.returncode != 0 or not png_path.is_file():
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
        raise RuntimeError(f"chrome failed ({proc.returncode}): {' '.join(err)}")
    return (proc.stdout or b"").decode("utf-8", "replace")


def crop_png(png_path: Path, size: tuple[int, int]) -> None:
    with Image.open(png_path) as im:
        if im.size == tuple(size):
            return
        if im.width < size[0] or im.height < size[1]:
            raise RuntimeError(f"screenshot {im.size} is smaller than {size}")
        cropped = im.crop((0, 0, size[0], size[1]))
    cropped.save(png_path)


def save_jpeg(png_path: Path, jpg_path: Path, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
    for quality in (92, 88, 84, 80, 75):
        rgb.save(jpg_path, "JPEG", quality=quality, optimize=True, progressive=True)
        if jpg_path.stat().st_size <= max_bytes:
            break
    return jpg_path.stat().st_size


# ---- checks --------------------------------------------------------------

def _inside(point: tuple[int, int], box: list[int], pad: int = 0) -> bool:
    x, y = point
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def check_variant(variant: Variant, layout: dict[str, Any], title: str = "",
                  palette: Optional[dict[str, str]] = None,
                  subject_xy: Optional[tuple[int, int]] = None) -> dict[str, Any]:
    palette = {**PALETTE, **(palette or {})}
    problems: list[str] = []
    warnings: list[str] = []
    scale = PHONE_WIDTH / WIDTH

    if not layout.get("fonts_loaded"):
        problems.append("Vazirmatn did not load; the PNG uses a fallback font")

    phone_px: dict[str, float] = {}
    for item in layout.get("texts", []):
        role = item["role"]
        px = round(item["px"] * scale, 1)
        phone_px[role] = min(px, phone_px.get(role, px))
        if item.get("too_wide"):
            problems.append(f"{role} does not fit its box even at the minimum size")
        if item.get("outside"):
            problems.append(f"{role} runs outside the frame")
        if item.get("badge_overlap"):
            problems.append(f"{role} sits under the duration badge (bottom-right)")
        if subject_xy and _inside(subject_xy, item["box"], pad=12):
            problems.append(f"{role} covers the subject at {subject_xy}; move the focus or the subject")
    for role, px in phone_px.items():
        floor = MIN_PHONE_PX.get(role, 0)
        if px < floor:
            problems.append(f"{role} is {px} px tall at {PHONE_WIDTH} px wide (needs {floor})")

    contrast = {}
    for role, fg, bg in TEMPLATES[variant.template]["pairs"]:
        if role not in phone_px:
            continue
        ratio = round(contrast_ratio(palette[fg], palette[bg]), 2)
        contrast[role] = ratio
        if ratio < MIN_CONTRAST:
            problems.append(f"{role} contrast {ratio} < {MIN_CONTRAST}")

    shown = " ".join(t for t in (variant.year, variant.headline, variant.kicker) if t)
    count = len(words(shown))
    if count > MAX_WORDS + 1:
        problems.append(f"{count} words on the thumbnail (keep it to {MAX_WORDS})")
    elif count > MAX_WORDS:
        warnings.append(f"{count} words; {MAX_WORDS} or fewer reads faster")
    overlap = repeats_title(shown, title) if title else 0.0
    if overlap >= 0.6:
        warnings.append(f"repeats the title ({overlap:.0%} of its words); add something the title does not say")

    return {"passed": not problems, "problems": problems, "warnings": warnings,
            "phone_px": phone_px, "contrast": contrast, "words": count,
            "title_overlap": round(overlap, 2)}


# ---- preview sheet -------------------------------------------------------

def preview_html(results: list[dict[str, Any]], title: str, fonts: Fonts,
                 duration: str = "1:30") -> tuple[str, tuple[int, int]]:
    sections = []
    for theme, label in (("light", "Light theme"), ("dark", "Dark theme")):
        rows = []
        for width in PREVIEW_WIDTHS:
            cards = []
            for res in results:
                caption = (f'<div class="title" style="width:{width}px">{html.escape(clean_text(title))}</div>'
                           if width >= 246 else "")
                cards.append(
                    f'<div class="card" style="width:{width}px">'
                    f'<div class="thumb"><img src="{Path(res["png"]).resolve().as_uri()}" alt="">'
                    f'<span class="badge">{html.escape(duration)}</span></div>'
                    f'{caption}<div class="id">{html.escape(res["id"])} · {html.escape(res["template"])}</div></div>')
            rows.append(f'<div class="row"><div class="label">{width} px</div>{"".join(cards)}</div>')
        sections.append(f'<div class="theme {theme}"><h2>{label}</h2>{"".join(rows)}</div>')

    n = max(len(results), 1)
    width = 28 * 2 + 70 + 26 * n + n * PREVIEW_WIDTHS[0]
    row_heights = sum(round(w * 9 / 16) + (78 if w >= 246 else 30) + 18 for w in PREVIEW_WIDTHS)
    height = 2 * (22 + 36 + row_heights + 26)
    page = Template((TEMPLATES_DIR / "preview.html").read_text(encoding="utf-8")).substitute(
        width=width, sections="\n".join(sections),
        font_black=fonts.css_src("black"), font_bold=fonts.css_src("bold"))
    return page, (width, height)


# ---- one call ------------------------------------------------------------

def default_variants(headline: str, kicker: str = "", year: str = "",
                     focus: tuple[float, float] = (0.5, 0.5),
                     ring: Optional[tuple[float, float, float]] = None) -> list[Variant]:
    """Three variants from one still and one short text: A punch, B era, C question."""
    question = headline if headline.rstrip().endswith(("؟", "?", "!")) else headline.rstrip() + "؟"
    return [
        Variant("A", "punch", headline, kicker=kicker, focus=focus, zoom=1.25),
        Variant("B", "era", headline, kicker=kicker if not year else "", year=year, focus=focus, zoom=1.1),
        Variant("C", "question", question, focus=focus, zoom=1.0, ring=ring),
    ]


def make_thumbnails(background: Path, variants: list[Variant], out_dir: Path, title: str = "",
                    chrome: Optional[str] = None, palette: Optional[dict[str, str]] = None,
                    runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    background = Path(background)
    if not background.is_file():
        raise FileNotFoundError(background)
    chrome = chrome or find_chrome()
    if not chrome:
        raise RuntimeError("no Chrome/Chromium found; set CHROME_PATH")
    out_dir = Path(out_dir)
    html_dir = out_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    fonts = find_fonts()

    results = []
    for variant in variants:
        page = html_dir / f"thumb_{variant.id}.html"
        page.write_text(build_html(variant, background, fonts, palette), encoding="utf-8")
        png = out_dir / f"thumb_{variant.id}.png"
        layout = parse_layout(render(page, png, chrome, runner=runner))
        crop_png(png, (WIDTH, HEIGHT))
        jpg = out_dir / f"thumb_{variant.id}.jpg"
        jpg_bytes = save_jpeg(png, jpg)
        with Image.open(background) as im:
            subject_xy = subject_in_frame(variant, im.size)
        check = check_variant(variant, layout, title, palette, subject_xy)
        if jpg_bytes > MAX_UPLOAD_BYTES:
            check["problems"].append(f"JPG is {jpg_bytes} bytes (YouTube limit {MAX_UPLOAD_BYTES})")
            check["passed"] = False
        with Image.open(png) as im:
            if im.size != (WIDTH, HEIGHT):
                check["problems"].append(f"PNG is {im.size}, expected {(WIDTH, HEIGHT)}")
                check["passed"] = False
        results.append({
            "id": variant.id, "template": variant.template, "headline": variant.headline,
            "kicker": variant.kicker, "year": variant.year, "notes": variant.notes,
            "png": str(png), "jpg": str(jpg), "jpg_bytes": jpg_bytes,
            "layout": layout["texts"], **check,
        })

    sheet_html, size = preview_html(results, title, fonts)
    sheet_page = html_dir / "preview_phone.html"
    sheet_page.write_text(sheet_html, encoding="utf-8")
    sheet = out_dir / "preview_phone.png"
    measured = parse_layout(render(sheet_page, sheet, chrome, size=size, runner=runner))
    # The estimate leaves room; crop to what the page measured (never past the window's
    # visible part, which ends WINDOW_MARGIN[1] - ~90 px below the estimate).
    crop_png(sheet, (min(measured.get("width", size[0]), size[0]),
                     min(measured.get("height", size[1]), size[1] + WINDOW_MARGIN[1] // 2)))

    report = {
        "background": str(background), "title": title, "chrome": chrome,
        "fonts": {"black": str(fonts.black) if fonts.black else None,
                  "bold": str(fonts.bold) if fonts.bold else None},
        "phone_width": PHONE_WIDTH, "preview": str(sheet),
        "all_passed": all(r["passed"] for r in results), "variants": results,
    }
    (out_dir / "thumbnails.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    return report
