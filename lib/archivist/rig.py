"""2.5D rig for the Archivist built from a few generated stills.

- Edits are aligned to their source still (ORB + similarity transform), so
  small patches can be pasted without a visible jump.
- Mouth and eye patches come from the difference between an edit and its
  source, limited to a window around the face, with a feathered mask.
- Breathing and a small head nod are a smooth displacement field (no seams).
- Rain is drawn over the window; the lamp glow breathes a little.

Three loopable states use it (see ``show.py``): idle (breathing, blinks, page
turns), talking (mouth shape from TTS loudness) and pulling a file from the
shelf (cross-fades through the shelf and file stills).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

WORK_W, WORK_H = 2304, 1286  # 1.2x the 1920x1080 output, room for a slow push-in


def _load(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.resize(img, (WORK_W, WORK_H), interpolation=cv2.INTER_AREA)


def align(src: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Warp ``src`` onto ``ref`` with a similarity transform from ORB matches."""
    orb = cv2.ORB_create(4000)
    g1, g2 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY), cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is None or d2 is None:
        return src
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2),
                     key=lambda m: m.distance)[:800]
    if len(matches) < 20:
        return src
    p1 = np.float32([k1[m.queryIdx].pt for m in matches])
    p2 = np.float32([k2[m.trainIdx].pt for m in matches])
    m, _ = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None:
        return src
    return cv2.warpAffine(src, m, (ref.shape[1], ref.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def face_transform(src: np.ndarray, ref: np.ndarray, center: tuple[int, int],
                   radius: int = 260) -> np.ndarray | None:
    """Similarity transform mapping the face in ``src`` onto the face in ``ref``,
    from ORB matches inside a box around ``center`` only."""
    cx, cy = center
    box = np.zeros(src.shape[:2], np.uint8)
    box[max(cy - radius, 0):cy + radius, max(cx - radius, 0):cx + radius] = 255
    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(src, cv2.COLOR_BGR2GRAY), box)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), box)
    if d1 is None or d2 is None:
        return None
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2),
                     key=lambda m: m.distance)[:300]
    if len(matches) < 12:
        return None
    p1 = np.float32([k1[m.queryIdx].pt for m in matches])
    p2 = np.float32([k2[m.trainIdx].pt for m in matches])
    m, inliers = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=2.5)
    return m if m is not None and inliers.sum() >= 10 else None


def diff_mask(edit: np.ndarray, ref: np.ndarray, window: tuple[int, int, int, int],
              grow: int = 9, feather: int = 15) -> np.ndarray:
    """Soft float mask (0..1) of where ``edit`` differs from ``ref`` inside ``window``."""
    x0, y0, x1, y1 = window
    d = cv2.absdiff(edit, ref).max(axis=2).astype(np.float32)
    d = cv2.GaussianBlur(d, (0, 0), 2)
    hard = np.zeros(d.shape, np.uint8)
    sub = (d[y0:y1, x0:x1] > 28).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(sub)
    keep = np.zeros_like(sub)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > 40:
            keep[labels == i] = 1
    hard[y0:y1, x0:x1] = keep
    if hard.any():
        ys, xs = np.nonzero(hard)
        # Fill the hull of the changed area so lips and teeth come as one patch.
        hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
        cv2.fillConvexPoly(hard, hull, 1)
    hard = cv2.dilate(hard, np.ones((grow, grow), np.uint8))
    soft = cv2.GaussianBlur(hard.astype(np.float32), (0, 0), feather)
    return np.clip(soft * 1.6, 0, 1)[..., None]


def _bbox(mask: np.ndarray, floor: float = 0.004, pad: int = 4) -> tuple[slice, slice]:
    ys, xs = np.nonzero(mask[..., 0] > floor if mask.ndim == 3 else mask > floor)
    if not len(ys):
        return slice(0, 0), slice(0, 0)
    return (slice(max(ys.min() - pad, 0), ys.max() + pad + 1),
            slice(max(xs.min() - pad, 0), xs.max() + pad + 1))


def _blend(img: np.ndarray, patch: np.ndarray, mask: np.ndarray, box) -> np.ndarray:
    out = img.copy()
    ys, xs = box
    m = mask[ys, xs]
    out[ys, xs] = (img[ys, xs] * (1 - m) + patch[ys, xs] * m).astype(np.uint8)
    return out


def _gauss(cx: float, cy: float, sx: float, sy: float) -> np.ndarray:
    y, x = np.mgrid[0:WORK_H, 0:WORK_W].astype(np.float32)
    return np.exp(-(((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2) / 2)


@dataclass
class Pose:
    """A still plus its mouth and eye patches (if any)."""
    image: np.ndarray
    mouths: list  # [(image, mask)] for mid, open
    eyes: tuple | None = None


class Rig:
    # Face and window positions as fractions of the frame (from base.png).
    FACE = (0.505, 0.395)
    CHEST = (0.505, 0.60)
    WINDOW = (0.80, 0.03, 0.995, 0.66)
    LAMP = (0.79, 0.53)

    def __init__(self, stills: Path, seed: int = 7):
        load = lambda n: _load(stills / f"{n}.png")  # noqa: E731
        base = load("base")
        fx, fy = int(self.FACE[0] * WORK_W), int(self.FACE[1] * WORK_H)
        mouth_win = (fx - 110, fy + 10, fx + 110, fy + 150)
        eye_win = (fx - 130, fy - 90, fx + 130, fy + 10)

        def patches(ref, names, win):
            out = []
            for n in names:
                if not (stills / f"{n}.png").exists():
                    continue
                img = align(load(n), ref)
                out.append((img, diff_mask(img, ref, win)))
            return out

        self.poses = {"desk": Pose(base, patches(base, ["mouth_mid", "mouth_open"], mouth_win))}
        blink = patches(base, ["blink"], eye_win)
        self.poses["desk"].eyes = blink[0] if blink else None
        self.stills = {"page_turn": align(load("page_turn"), base),
                       "shelf_reach": align(load("shelf_reach"), base)}
        if (stills / "file_hold.png").exists():
            hold = align(load("file_hold"), base)
            fwin = (fx - 130, fy - 10, fx + 130, fy + 170)
            mouths = patches(hold, ["file_mouth_mid", "file_mouth_open"], fwin)
            if not mouths:
                # No mouth edits of this pose: carry the desk mouths over to
                # where the face sits in the file still.
                m = face_transform(base, hold, (fx, fy))
                if m is not None:
                    size = (WORK_W, WORK_H)
                    # Keep only where the moved closed face matches the file
                    # still, so the patch stops at the folder's edge.
                    moved = cv2.warpAffine(base, m, size, borderMode=cv2.BORDER_REPLICATE)
                    same = (cv2.absdiff(moved, hold).max(axis=2) < 45).astype(np.uint8)
                    same = cv2.morphologyEx(same, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
                    same = cv2.erode(same, np.ones((7, 7), np.uint8))
                    # Fill small holes (the open mouth differs from the closed one).
                    same = cv2.morphologyEx(same, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8))
                    keep = cv2.GaussianBlur(same.astype(np.float32), (0, 0), 4)[..., None]
                    for img, mask in self.poses["desk"].mouths:
                        w_img = cv2.warpAffine(img, m, size, borderMode=cv2.BORDER_REPLICATE)
                        w_mask = cv2.warpAffine(mask[..., 0], m, size)[..., None] * keep
                        mouths.append((w_img, w_mask))
            self.poses["file"] = Pose(hold, mouths)
        self.breath = _gauss(self.CHEST[0] * WORK_W, self.CHEST[1] * WORK_H - 120, 260, 300)
        self.nod = _gauss(fx, fy, 170, 190)
        self.grid_y, self.grid_x = np.mgrid[0:WORK_H, 0:WORK_W].astype(np.float32)
        self.lamp_glow = _gauss(self.LAMP[0] * WORK_W, self.LAMP[1] * WORK_H, 380, 260)[..., None]
        self._boxes: dict = {}
        self.warp_box = _bbox(np.maximum(self.breath, self.nod), floor=0.01)
        self.lamp_box = _bbox(self.lamp_glow, floor=0.01)
        ly, lx = self.lamp_box
        self.lamp_light = (base[ly, lx] * self.lamp_glow[ly, lx]).astype(np.uint8)
        self.rng = np.random.default_rng(seed)
        wx0, wy0, wx1, wy1 = self.WINDOW
        self.win = (int(wx0 * WORK_W), int(wy0 * WORK_H), int(wx1 * WORK_W), int(wy1 * WORK_H))
        n = 260
        self.drops = np.stack([
            self.rng.uniform(self.win[0], self.win[2], n),
            self.rng.uniform(self.win[1], self.win[3], n),
            self.rng.uniform(900, 1500, n),     # speed px/s
            self.rng.uniform(18, 46, n),        # length
            self.rng.uniform(0.25, 0.7, n),     # alpha
        ], 1)

    # -- pieces ----------------------------------------------------------

    def pose_image(self, pose: str, mouth: int, blink: bool) -> np.ndarray:
        p = self.poses[pose]
        img = p.image
        if mouth and p.mouths:
            m_img, m_mask = p.mouths[min(mouth, len(p.mouths)) - 1]
            img = _blend(img, m_img, m_mask, self._box(m_mask))
        if blink and p.eyes is not None:
            e_img, e_mask = p.eyes
            img = _blend(img, e_img, e_mask, self._box(e_mask))
        return img

    def _box(self, mask: np.ndarray):
        key = id(mask)
        if key not in self._boxes:
            self._boxes[key] = _bbox(mask)
        return self._boxes[key]

    def warp(self, img: np.ndarray, t: float, nod: float = 0.0, breath: float = 1.0) -> np.ndarray:
        ys, xs = self.warp_box
        dy = breath * (3.2 * math.sin(2 * math.pi * t / 4.6) * self.breath[ys, xs]
                       + nod * self.nod[ys, xs])
        out = img.copy()
        # Remap the field's box only; the field is ~0 at the box edge.
        sub = cv2.remap(img, self.grid_x[ys, xs], self.grid_y[ys, xs] + dy, cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
        out[ys, xs] = sub
        return out

    def rain(self, img: np.ndarray, t: float) -> np.ndarray:
        x0, y0, x1, y1 = self.win
        layer = img[y0:y1, x0:x1].copy()
        h = y1 - y0
        for x, y, v, ln, a in self.drops:
            yy = (y - y0 + v * t) % (h + ln) - ln
            px = int(x - x0 - 0.12 * yy * 0.15)
            p0 = (px, int(yy))
            p1 = (px - 3, int(yy + ln))
            col = (int(205 * a + 40), int(190 * a + 40), int(170 * a + 40))
            cv2.line(layer, p0, p1, col, 1, cv2.LINE_AA)
        out = img.copy()
        out[y0:y1, x0:x1] = cv2.addWeighted(img[y0:y1, x0:x1], 0.55, layer, 0.45, 0)
        return out

    def lamp(self, img: np.ndarray, t: float) -> np.ndarray:
        flick = 0.035 * math.sin(t * 1.7) + 0.02 * math.sin(t * 5.3 + 1)
        ys, xs = self.lamp_box
        out = img.copy()
        # Additive light from a fixed "lit" layer: a few percent either way.
        out[ys, xs] = cv2.addWeighted(img[ys, xs], 1.0, self.lamp_light, flick, 0)
        return out

    # -- one frame -------------------------------------------------------

    def frame(self, t: float, *, pose: str = "desk", mouth: int = 0, blink: bool = False,
              still: str | None = None, mix: float = 0.0, nod: float = 0.0) -> np.ndarray:
        """``still``/``mix`` cross-fade the pose toward a whole other still."""
        img = self.pose_image(pose, mouth, blink)
        breath = 1.0
        if still and mix > 0:
            other = self.stills[still] if still in self.stills else self.poses[still].image
            img = cv2.addWeighted(img, 1 - mix, other, mix, 0)
            if still in self.stills:  # he is out of the chair: no breathing field there
                breath = 1 - mix
        img = self.warp(img, t, nod, breath)
        img = self.rain(img, t)
        return self.lamp(img, t)


def camera(img: np.ndarray, zoom: float, cx: float = 0.5, cy: float = 0.45,
           size: tuple[int, int] = (1920, 1080)) -> np.ndarray:
    """Crop a window ``1/zoom`` of the frame around (cx, cy) and scale to ``size``."""
    h, w = img.shape[:2]
    cw, ch = w / zoom, h / zoom
    x0 = min(max(cx * w - cw / 2, 0), w - cw)
    y0 = min(max(cy * h - ch / 2, 0), h - ch)
    m = np.float32([[size[0] / cw, 0, -x0 * size[0] / cw], [0, size[1] / ch, -y0 * size[1] / ch]])
    return cv2.warpAffine(img, m, size, flags=cv2.INTER_AREA)
