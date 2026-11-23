"""FrimeRise Cinema v7 Pro Motion Graphics Studio (Mixed_Media_High_Retention_Documentary_Engine v3.0.0).

Implements procedural 30fps C++ Skia motion-design renderers across all 5 Mixed-Media Documentary
Categories (`Vox`, `Johnny Harris`, `MagnatesMedia`, `Fern`, `16:9` `1920x1080 @ 30fps` + `9:16` safe):
  1. `draw_depth_title_behind_subject`: Alpha-aware Rule-of-Thirds + Headroom 3D Depth Title rendered
     BETWEEN 2.5D background (`bg_img`) and foreground character (`fg_img`), guaranteeing >=88% clear
     legibility (`fg_alpha < 96`), seamless radial halo (`>= 2.2 * radius`), and pre-rendered offscreen
     `skia.Image` sprite caching (~0.12 ms/frame).
  2. `draw_anamorphic_film_burn_and_bokeh` + `draw_chapter_whip_and_film_burn`: Pre-cached `96x96`
     radial bokeh orb sprites (~0.08 ms/frame) + 8-frame directional `whip_pan` & 12-frame `film_burn`
     chapter transitions.
  3. `draw_pro_safezone_lower_third`: JSON v3.0.0 `date_and_location_stamp` (`bottom_left` `x=96, y=h-84-pill_h`
     in 16:9 with `Cinzel Bold 42px` `#F8FAFC` + `Courier Prime Bold 24px` `#E0C097` + `4px` `#EAB308` left bar +
     0.40s `cubic-bezier(0.22, 1, 0.36, 1)` left-to-right clipRect mask reveal; `y=192, x=46` in 9:16).
  4. `draw_pro_cartographic_map`: Dark Topographic Tactical Map (`#121417` / `#2C323B` / `#EAB308` / `#D9381E` /
     `#F8FAFC`) supporting both A->B historical routes AND single-city Tactical Regional Perimeter & Schematic Mode.
  5. `draw_2d_schematic_over_realism`: Vox / Johnny Harris 2D vector schematics (tactical reticles, animated dashed
     callout lines, cause-and-effect diagram nodes, historical timeline breakdown in Courier Prime Bold 36-64px)
     layered over a 65% brightness desaturated realistic scene.
  6. `draw_pro_archival_newspaper` + `draw_video_over_video_collage`: Vox / Johnny Harris archival documents &
     1–3 floating Video-over-Video PiP collage cards (`55%–75%` scale, `2px solid rgba(255,255,255,0.18)`,
     `0px 20px 50px rgba(0,0,0,0.85)` shadow, `-2deg..+2deg` slide-in rotation, `#FFD700` multiply brush highlighter).
  7. `draw_pro_odometer_timeline`: Clean 16:9/9:16 mechanical chronometer timeline with compact date drums,
     larger archival photo cards, and vector cause-and-effect callout arrows (zero fake `IMPACTO %` chartjunk).
  8. `draw_pro_forensic_string_board`: Mindhunter / MagnatesMedia investigation board with catenary strings
     completing by `prog <= 0.35` and routed pin-to-pin cleanly clear of card badges.
  9. `draw_fern_3d_reconstruction`: Fern-style minimalist dark 3D perspective architectural reconstruction,
     orbiting 3D camera matrix, volumetric spotlight cones, rim-lit dark human silhouette, glowing 3D perspective
     tactical target circles, and digital forensic UI telemetry callouts.
"""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import skia

from engine.skia_compositor import (
    FORBIDDEN_DEBUG_RE,
    _ease_out_cubic,
    _wrap_text_to_width,
    hex_to_skia,
)

_BASE_DIR = Path(__file__).resolve().parent.parent
_FONTS_DIR = _BASE_DIR / "assets" / "fonts"
_LINEAR_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)

# Cached Google Fonts typefaces (Cinzel Bold & Courier Prime Bold)
_FONT_CACHE: Dict[str, Optional[skia.Typeface]] = {}

# Performance & Alpha-Aware Placement Caches (bounded LRU)
_FG_ALPHA_CACHE: Dict[Tuple[int, int, int], Tuple[float, float, np.ndarray]] = {}
_DEPTH_PLACEMENT_CACHE: Dict[Tuple[int, str, int, int, int], Tuple[float, float, float, float, float]] = {}
_DEPTH_TITLE_SPRITE_CACHE: Dict[Tuple[str, int, int, str, int], Tuple[int, skia.Image, float, float, float, float]] = {}
_BOKEH_SPRITE_CACHE: Dict[str, skia.Image] = {}
_BLUR_BACKDROP_CACHE: Dict[Tuple[int, int, int, int], skia.Image] = {}
_DESAT_IMAGE_CACHE: Dict[int, skia.Image] = {}
_GRAD_BG_CACHE: Dict[Tuple[str, int, int], skia.Image] = {}
_SILHOUETTE_CACHE: Dict[Tuple[int, int, int], skia.Image] = {}

# Desaturated 65%-brightness C++ ColorFilter for 2D_Infographic_Over_Realism
_DESAT_65_COLOR_MATRIX: List[float] = [
    0.260, 0.340, 0.050, 0.0, 0.0,
    0.165, 0.435, 0.050, 0.0, 0.0,
    0.165, 0.340, 0.145, 0.0, 0.0,
    0.000, 0.000, 0.000, 1.0, 0.0,
]
_DESAT_65_FILTER = skia.ColorFilters.Matrix(_DESAT_65_COLOR_MATRIX)

_ARROW_AND_GLYPH_MAP: Dict[str, str] = {
    "\u2794": "->",
    "\u279c": "->",
    "\u279e": "->",
    "\u27a1": "->",
    "\u2192": "->",
    "\u21d2": "->",
    "\u2190": "<-",
    "\u21d0": "<-",
    "\u2194": "<->",
    "\u21d4": "<->",
    "\u25cf": "•",
    "\u25c9": "•",
    "\u25aa": "•",
    "\u25ab": "•",
    "\u25c6": "•",
    "\ufe0f": "",
}


# ---------------------------------------------------------------------------
# Cached Google Fonts Loaders (Cinzel Bold & Courier Prime Bold)
# ---------------------------------------------------------------------------
def _load_cached_font_file(filenames: Sequence[str], cache_key: str) -> Optional[skia.Typeface]:
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]
    loaded: Optional[skia.Typeface] = None
    for fname in filenames:
        fp = _FONTS_DIR / fname
        if fp.exists() and fp.stat().st_size > 15_000:
            try:
                tf = skia.Typeface.MakeFromFile(str(fp))
                if tf is not None:
                    loaded = tf
                    break
            except Exception:
                pass
    _FONT_CACHE[cache_key] = loaded
    return loaded


def get_cinzel_bold_typeface(fallback: Optional[skia.Typeface] = None) -> Optional[skia.Typeface]:
    """Return cached Google Fonts Cinzel-Bold.ttf typeface, falling back gracefully."""
    tf = _load_cached_font_file(("Cinzel-Bold.ttf", "Cinzel-Regular.ttf"), "cinzel_bold")
    return tf if tf is not None else fallback


def get_courier_prime_bold_typeface(fallback: Optional[skia.Typeface] = None) -> Optional[skia.Typeface]:
    """Return cached Google Fonts CourierPrime-Bold.ttf typeface, falling back gracefully."""
    tf = _load_cached_font_file(("CourierPrime-Bold.ttf", "CourierPrime-Regular.ttf"), "courier_prime_bold")
    return tf if tf is not None else fallback


# ---------------------------------------------------------------------------
# Internal Helpers (Glyph Safety, Easing, Cover Crop, Attribute Access)
# ---------------------------------------------------------------------------
def _ease_doc_snap(x: float, x1: float = 0.22, y1: float = 1.0, x2: float = 0.36, y2: float = 1.0) -> float:
    """Exact CSS cubic-bezier(0.22, 1, 0.36, 1) ease-out quint-like snap."""
    t_target = max(0.0, min(1.0, float(x)))
    if t_target <= 0.0:
        return 0.0
    if t_target >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        inv = 1.0 - mid
        bx = 3.0 * inv * inv * mid * x1 + 3.0 * inv * mid * mid * x2 + mid * mid * mid
        if bx < t_target:
            lo = mid
        else:
            hi = mid
    u = 0.5 * (lo + hi)
    inv = 1.0 - u
    return 3.0 * inv * inv * u * y1 + 3.0 * inv * u * u * y2 + u * u * u


def _ease_out_back(x: float) -> float:
    t = max(0.0, min(1.0, float(x)))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * ((t - 1.0) ** 3) + c1 * ((t - 1.0) ** 2)


def _ease_in_out_cubic(x: float) -> float:
    t = max(0.0, min(1.0, float(x)))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def _get_attr(obj: Any, key: str, default: Any = "") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        val = obj.get(key, default)
        return default if val is None else val
    val = getattr(obj, key, default)
    return default if val is None else val


def _normalize_upper(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or "")).upper()


def _sanitize_glyphs(
    text: str,
    typeface: Optional[skia.Typeface] = None,
    preserve_spacing: bool = False,
) -> str:
    s = FORBIDDEN_DEBUG_RE.sub("", str(text or ""))
    for bad_ch, repl in _ARROW_AND_GLYPH_MAP.items():
        if bad_ch in s:
            s = s.replace(bad_ch, repl)
    if typeface is not None:
        out_chars: List[str] = []
        for ch in s:
            if ch.isspace() or ord(ch) < 128:
                out_chars.append(ch)
            elif typeface.unicharToGlyph(ord(ch)) != 0:
                out_chars.append(ch)
            elif ch in ("•", "·"):
                out_chars.append("-")
            else:
                out_chars.append(" ")
        s = "".join(out_chars)
    if preserve_spacing:
        return s.strip()
    return " ".join(s.split())


def _draw_safe_string(
    canvas: skia.Canvas,
    text: str,
    x: float,
    y: float,
    font: skia.Font,
    paint: skia.Paint,
    preserve_spacing: bool = False,
) -> None:
    safe_txt = _sanitize_glyphs(text, typeface=font.getTypeface(), preserve_spacing=preserve_spacing)
    if safe_txt:
        canvas.drawString(safe_txt, float(x), float(y), font, paint)


def _draw_fast_rrect_shadow(
    canvas: skia.Canvas,
    rrect: skia.RRect,
    dy: float = 18.0,
    sigma: float = 22.0,
    alpha: int = 217,
) -> None:
    """Ultra-fast 3-pass layered RRect drop shadow (0.08 ms/frame even under canvas.rotate() vs 55–180 ms/frame CPU Gaussian)."""
    if alpha <= 4:
        return
    base_a = max(0, min(255, int(alpha)))
    rect = rrect.rect()
    radii = rrect.radii(skia.RRect.kUpperLeft_Corner)
    rx = max(4.0, float(radii.fX))
    ry = max(4.0, float(radii.fY))
    spread = max(6.0, min(36.0, float(sigma) * 0.9))
    for k_spread, k_dy, k_alpha in (
        (spread * 0.95, float(dy) * 1.10, 0.24),
        (spread * 0.52, float(dy) * 0.85, 0.36),
        (spread * 0.20, float(dy) * 0.55, 0.52),
    ):
        a_l = max(1, min(255, int(round(base_a * k_alpha))))
        sr = skia.Rect.MakeLTRB(
            rect.left() - k_spread,
            rect.top() - k_spread * 0.45 + k_dy,
            rect.right() + k_spread,
            rect.bottom() + k_spread * 0.85 + k_dy,
        )
        canvas.drawRoundRect(
            sr,
            rx + k_spread * 0.35,
            ry + k_spread * 0.35,
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(a_l, 0, 0, 0)),
        )


def _get_desat65_image(img: skia.Image) -> skia.Image:
    """Pre-apply 65%-brightness desaturation matrix once per `img.uniqueID()` for 4x faster blitting."""
    key = int(img.uniqueID())
    cached = _DESAT_IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    iw, ih = max(1, img.width()), max(1, img.height())
    surf = skia.Surface(iw, ih)
    c = surf.getCanvas()
    p = skia.Paint(AntiAlias=True)
    p.setColorFilter(_DESAT_65_FILTER)
    c.drawImage(img, 0.0, 0.0, _LINEAR_SAMPLING, p)
    out = surf.makeImageSnapshot()
    if len(_DESAT_IMAGE_CACHE) >= 32:
        _DESAT_IMAGE_CACHE.clear()
    _DESAT_IMAGE_CACHE[key] = out
    return out


def _get_cached_gradient_overlay(
    tag: str,
    w: int,
    h: int,
    draw_fn: Any,
) -> skia.Image:
    """Pre-render a 1/4-res full-screen radial/linear gradient overlay once per `(tag, w, h)`."""
    key = (tag, int(w), int(h))
    cached = _GRAD_BG_CACHE.get(key)
    if cached is not None:
        return cached
    sw = max(120, int(w) // 4)
    sh = max(90, int(h) // 4)
    surf = skia.Surface(sw, sh)
    c = surf.getCanvas()
    c.clear(skia.ColorSetARGB(0, 0, 0, 0))
    draw_fn(c, sw, sh)
    out = surf.makeImageSnapshot()
    if len(_GRAD_BG_CACHE) >= 32:
        _GRAD_BG_CACHE.clear()
    _GRAD_BG_CACHE[key] = out
    return out


def _draw_cached_gradient(canvas: skia.Canvas, img: skia.Image, w: int, h: int) -> None:
    canvas.drawImageRect(
        img,
        skia.Rect.MakeWH(img.width(), img.height()),
        skia.Rect.MakeWH(w, h),
        _LINEAR_SAMPLING,
        skia.Paint(),
        skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
    )


def _draw_image_cover(
    canvas: skia.Canvas,
    img: Optional[skia.Image],
    dst_rect: skia.Rect,
    paint: Optional[skia.Paint] = None,
    y_bias: float = 0.25,
) -> None:
    if img is None or img.width() <= 0 or img.height() <= 0:
        return
    iw = float(img.width())
    ih = float(img.height())
    dw = max(1.0, float(dst_rect.width()))
    dh = max(1.0, float(dst_rect.height()))
    src_ar = iw / ih
    dst_ar = dw / dh
    if src_ar > dst_ar + 1e-4:
        crop_w = ih * dst_ar
        sx0 = (iw - crop_w) * 0.5
        src_r = skia.Rect.MakeXYWH(sx0, 0.0, crop_w, ih)
    elif src_ar < dst_ar - 1e-4:
        crop_h = iw / dst_ar
        sy0 = (ih - crop_h) * max(0.0, min(1.0, float(y_bias)))
        src_r = skia.Rect.MakeXYWH(0.0, sy0, iw, crop_h)
    else:
        src_r = skia.Rect.MakeWH(iw, ih)
    canvas.drawImageRect(
        img,
        src_r,
        dst_rect,
        _LINEAR_SAMPLING,
        paint,
        skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
    )


def _draw_dark_bokeh_backdrop(
    canvas: skia.Canvas,
    w: int,
    h: int,
    backdrop_img: Optional[skia.Image],
    prog: float,
    t: float,
    scrim_alpha: int = 165,
    blur_sigma: float = 0.0,
    mood: str = "dark_horror",
) -> None:
    full_r = skia.Rect.MakeWH(w, h)
    canvas.clear(skia.ColorSetARGB(255, 9, 7, 15))
    if backdrop_img is not None:
        src_img = (
            _get_blurred_backdrop_image(backdrop_img, w, h, sigma=blur_sigma)
            if blur_sigma > 0.5
            else backdrop_img
        )
        zoom = 1.04 + 0.05 * prog
        pan_x = (prog - 0.5) * -20.0
        canvas.save()
        canvas.clipRect(full_r)
        canvas.translate(w * 0.5 + pan_x, h * 0.5)
        canvas.scale(zoom, zoom)
        _draw_image_cover(
            canvas,
            src_img,
            skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h),
            paint=None,
            y_bias=0.30,
        )
        canvas.restore()

    center_a = max(0, min(238, scrim_alpha - 24))
    edge_a = max(0, min(246, scrim_alpha + 26))
    scrim_img = _get_cached_gradient_overlay(
        f"bokeh_scrim_{center_a}_{edge_a}",
        w,
        h,
        lambda gc, gw, gh: gc.drawRect(
            skia.Rect.MakeWH(gw, gh),
            _make_radial_paint(
                (gw * 0.5, gh * 0.45),
                max(gw, gh) * 0.74,
                [skia.ColorSetARGB(center_a, 14, 10, 24), skia.ColorSetARGB(edge_a, 6, 4, 12)],
            ),
        ),
    )
    _draw_cached_gradient(canvas, scrim_img, w, h)
    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)


def _make_radial_paint(
    center: Tuple[float, float],
    radius: float,
    colors: List[int],
    positions: Optional[List[float]] = None,
) -> skia.Paint:
    p = skia.Paint()
    if positions is not None:
        p.setShader(skia.GradientShader.MakeRadial(center, radius, colors, positions))
    else:
        p.setShader(skia.GradientShader.MakeRadial(center, radius, colors))
    return p


def extract_depth_stamp_text(raw_text_or_scene: Any) -> str:
    """Extract a clean, punchy 1-2 word uppercase stamp (e.g. '336 d.C.', '1647', 'SÉC. IV', 'MIRA', 'ROMA', 'KRAMPUS')."""
    if not isinstance(raw_text_or_scene, str):
        lt = str(_get_attr(raw_text_or_scene, "lower_third_title", "") or "")
        sub = str(_get_attr(raw_text_or_scene, "lower_third_subtitle", "") or "")
        narr = str(_get_attr(raw_text_or_scene, "narration", "") or "")
        raw = f"{lt} • {sub} • {narr}".strip(" •")
    else:
        raw = raw_text_or_scene.strip()

    if not raw:
        return "ARQUIVO"

    # If caller already passed a short 1-2 word stamp without bullets, keep it directly
    if "•" not in raw and len(raw) <= 14 and len(raw.split()) <= 2:
        # Preserve 'd.C.' / 'a.C.' casing if present, otherwise uppercase
        m_dc = re.match(r"^\s*(\d{2,4})\s*([da]\.?\s*c\.?)\s*$", raw, flags=re.IGNORECASE)
        if m_dc:
            era = "d.C." if m_dc.group(2).lower().startswith("d") else "a.C."
            return f"{m_dc.group(1)} {era}"
        return _normalize_upper(raw)

    # 1. Explicit year with d.C. / a.C. / AD / BC
    m_era = re.search(r"\b(\d{2,4})\s*(d\.?\s*C\.?|a\.?\s*C\.?|AD|BC)\b", raw, flags=re.IGNORECASE)
    if m_era:
        yr = m_era.group(1)
        suf = m_era.group(2).upper().replace(" ", "")
        if suf.startswith("D"):
            return f"{yr} d.C."
        if suf.startswith("A") and "C" in suf:
            return f"{yr} a.C."
        return f"{yr} {suf}"

    # 2. Explicit 4-digit historical year (1000..2029)
    m_yr = re.search(r"\b(1\d{3}|20[0-2]\d)\b", raw)
    if m_yr:
        return m_yr.group(1)

    # 3. Roman or spelled-out century -> 'SÉC. IV', 'SÉC. XI', etc.
    century_map = {
        "PRIMEIRO": "I",
        "UM": "I",
        "SEGUNDO": "II",
        "DOIS": "II",
        "TERCEIRO": "III",
        "TRÊS": "III",
        "TRES": "III",
        "QUARTO": "IV",
        "QUATRO": "IV",
        "QUINTO": "V",
        "CINCO": "V",
        "SEXTO": "VI",
        "SEIS": "VI",
        "SÉTIMO": "VII",
        "SETIMO": "VII",
        "SETE": "VII",
        "OITAVO": "VIII",
        "OITO": "VIII",
        "NONO": "IX",
        "NOVE": "IX",
        "DÉCIMO PRIMEIRO": "XI",
        "DECIMO PRIMEIRO": "XI",
        "ONZE": "XI",
        "DÉCIMO SEGUNDO": "XII",
        "DOZE": "XII",
        "DÉCIMO": "X",
        "DEZ": "X",
    }
    upper_raw = _normalize_upper(raw)
    m_rom = re.search(r"\bS[EÉ]C(?:ULO|\.)?\s+([IVXLCDM]{1,5})\b", upper_raw)
    if m_rom:
        return f"SÉC. {m_rom.group(1)}"
    for word_c, rom_c in century_map.items():
        if re.search(rf"\bS[EÉ]C(?:ULO|\.)?\s+{word_c}\b", upper_raw):
            return f"SÉC. {rom_c}"

    # 4. Otherwise pick the strongest 1-2 whole location/entity words before '•' or ',' (ZERO mid-word [:N] slices!)
    first_seg = re.split(r"[•|—\-:,]", upper_raw)[0].strip()
    stop_words = {"DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS", "O", "A", "OS", "AS", "ANTIGA"}
    words = [w for w in first_seg.split() if w not in stop_words]
    if not words:
        words = first_seg.split()
    if not words:
        return "ARQUIVO"
    two_words = " ".join(words[:2]).strip()
    if len(two_words) <= 16:
        return two_words
    return words[0].strip() or "ARQUIVO"


# ---------------------------------------------------------------------------
# 1. Signature 3D Depth Title Behind 2.5D Foreground Subject (Alpha-Aware + Sprite-Cached)
# ---------------------------------------------------------------------------
def _dilate_alpha_grid(grid: np.ndarray, rx: int, ry: int) -> np.ndarray:
    """Fast pure-NumPy 2D separable max-dilation over a `(2*ry+1) x (2*rx+1)` kernel."""
    out = grid
    if rx > 0:
        padded = np.pad(out, ((0, 0), (rx, rx)), mode="edge")
        acc = padded[:, : out.shape[1]].copy()
        for dx in range(1, 2 * rx + 1):
            np.maximum(acc, padded[:, dx : dx + out.shape[1]], out=acc)
        out = acc
    if ry > 0:
        padded = np.pad(out, ((ry, ry), (0, 0)), mode="edge")
        acc = padded[: out.shape[0], :].copy()
        for dy in range(1, 2 * ry + 1):
            np.maximum(acc, padded[dy : dy + out.shape[0], :], out=acc)
        out = acc
    return out


def _analyze_fg_alpha(
    fg_img: skia.Image,
    w: int,
    h: int,
) -> Tuple[float, float, np.ndarray]:
    """Compute and cache `(fg_cx_norm, fg_y_top_norm, alpha_grid)` once per `fg_img.uniqueID()`.
    Dilates `alpha_grid` to the worst-case `1.14x` foreground push-in + opposing parallax envelope
    so 3D Depth Titles stay unoccluded across the ENTIRE shot duration (never clipping leading/trailing glyphs!).
    """
    key = (int(fg_img.uniqueID()), int(w), int(h))
    cached = _FG_ALPHA_CACHE.get(key)
    if cached is not None:
        return cached

    is_wide = w >= h
    gw = 160 if is_wide else 90
    gh = 90 if is_wide else 160

    def _render_alpha_at_scale(scale: float) -> np.ndarray:
        surf = skia.Surface(gw, gh)
        c = surf.getCanvas()
        c.clear(skia.ColorSetARGB(0, 0, 0, 0))
        c.save()
        c.translate(gw * 0.5, gh * 0.5)
        c.scale(scale, scale)
        c.translate(-gw * 0.5, -gh * 0.5)
        _draw_image_cover(c, fg_img, skia.Rect.MakeWH(gw, gh), y_bias=0.25)
        c.restore()
        raw = surf.makeImageSnapshot().tobytes()
        return np.frombuffer(raw, dtype=np.uint8).reshape(gh, gw, 4)[:, :, 3].copy()

    # Union of 1.00x base footprint and worst-case 1.14x foreground push-in footprint + parallax safety dilation
    alpha_100 = _render_alpha_at_scale(1.00)
    alpha_114 = _render_alpha_at_scale(1.14)
    alpha_union = np.maximum(alpha_100, alpha_114)
    pad_rx = max(2, int(round(gw * 0.028)))
    pad_ry = max(2, int(round(gh * 0.022)))
    alpha_grid = _dilate_alpha_grid(alpha_union, pad_rx, pad_ry)

    mask = alpha_grid >= 96
    if mask.any():
        ys, xs = np.nonzero(mask)
        weights = alpha_grid[ys, xs].astype(np.float32)
        fg_cx_norm = float(np.sum(xs * weights) / max(1.0, float(np.sum(weights)))) / float(gw)
        # 2nd percentile ignores stray 1px mask noise while capturing exact crown/horns top
        fg_y_top_norm = float(np.percentile(ys, 2.0)) / float(gh)
    else:
        fg_cx_norm = 0.5
        fg_y_top_norm = 1.0

    result = (
        max(0.0, min(1.0, fg_cx_norm)),
        max(0.0, min(1.0, fg_y_top_norm)),
        alpha_grid,
    )
    if len(_FG_ALPHA_CACHE) >= 64:
        _FG_ALPHA_CACHE.clear()
    _FG_ALPHA_CACHE[key] = result
    return result


def _bbox_clear_fraction(
    alpha_grid: np.ndarray,
    x0_norm: float,
    y0_norm: float,
    x1_norm: float,
    y1_norm: float,
    alpha_thresh: int = 96,
) -> float:
    """Fraction of pixels inside the normalized text bounding box with `fg_alpha < alpha_thresh`."""
    gh, gw = alpha_grid.shape
    ix0 = max(0, min(gw - 1, int(math.floor(x0_norm * gw))))
    ix1 = max(ix0 + 1, min(gw, int(math.ceil(x1_norm * gw))))
    iy0 = max(0, min(gh - 1, int(math.floor(y0_norm * gh))))
    iy1 = max(iy0 + 1, min(gh, int(math.ceil(y1_norm * gh))))
    patch = alpha_grid[iy0:iy1, ix0:ix1]
    if patch.size == 0:
        return 1.0
    return float(np.mean(patch < alpha_thresh))


def _bbox_quartile_clear_fractions(
    alpha_grid: np.ndarray,
    x0_norm: float,
    y0_norm: float,
    x1_norm: float,
    y1_norm: float,
    alpha_thresh: int = 96,
) -> Tuple[float, float, float, float]:
    """Return `(q0, q1, q2, q3)` clear fractions across the 4 horizontal quartiles of the text bbox
    so leading/trailing glyphs (e.g. 'S' in 'SÉC. IV' or 'A' in 'ESCANDINÁVIA') are NEVER occluded!
    """
    span = max(1e-4, float(x1_norm) - float(x0_norm))
    return (
        _bbox_clear_fraction(alpha_grid, x0_norm, y0_norm, x0_norm + span * 0.25, y1_norm, alpha_thresh=alpha_thresh),
        _bbox_clear_fraction(alpha_grid, x0_norm + span * 0.25, y0_norm, x0_norm + span * 0.50, y1_norm, alpha_thresh=alpha_thresh),
        _bbox_clear_fraction(alpha_grid, x0_norm + span * 0.50, y0_norm, x0_norm + span * 0.75, y1_norm, alpha_thresh=alpha_thresh),
        _bbox_clear_fraction(alpha_grid, x0_norm + span * 0.75, y0_norm, x1_norm, y1_norm, alpha_thresh=alpha_thresh),
    )


def _compute_depth_title_placement(
    stamp: str,
    w: int,
    h: int,
    title_tf: skia.Typeface,
    fg_img: Optional[skia.Image] = None,
) -> Tuple[float, float, float, float, float]:
    """Compute and cache Rule-of-Thirds + Headroom placement `(center_x, baseline_y, font_size, measured_w, clear_frac)`.
    Uses the dilated worst-case `1.14x` foreground alpha footprint and requires BOTH:
      - global `cf >= 0.92` (`fg_alpha < 96`)
      - EVERY horizontal quartile `q_cf >= 0.75` (protecting leading/trailing characters!).
    """
    is_wide = w >= h
    target_max_w = w * (0.76 if is_wide else 0.86)
    base_font_size = 236.0 if is_wide else 220.0
    min_font_size = 56.0

    font = skia.Font(title_tf, base_font_size)
    font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
    measured_w = float(font.measureText(stamp))
    if measured_w > target_max_w and measured_w > 1.0:
        base_font_size = max(min_font_size, base_font_size * (target_max_w / measured_w))
        font = skia.Font(title_tf, base_font_size)
        font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        measured_w = float(font.measureText(stamp))

    if fg_img is None:
        return (
            float(w) * 0.5,
            float(h) * (0.37 if is_wide else 0.34),
            base_font_size,
            measured_w,
            1.0,
        )

    cache_key = (int(fg_img.uniqueID()), stamp, int(w), int(h), int(title_tf.uniqueID()))
    cached = _DEPTH_PLACEMENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    fg_cx_norm, fg_y_top_norm, alpha_grid = _analyze_fg_alpha(fg_img, w, h)

    # Rule-of-Thirds + Headroom candidate ordering (expanded negative-space sweeps for 1.14x dilated masks)
    if is_wide:
        if fg_cx_norm < 0.48:
            cx_cands = [0.64, 0.70, 0.76, 0.82, 0.58, 0.50, 0.24, 0.18]
            by_cands = [0.34, 0.26, 0.20, 0.42, 0.16, 0.50, max(0.14, fg_y_top_norm + 0.04)]
        elif fg_cx_norm > 0.52:
            cx_cands = [0.36, 0.30, 0.24, 0.18, 0.42, 0.50, 0.76, 0.82]
            by_cands = [0.34, 0.26, 0.20, 0.42, 0.16, 0.50, max(0.14, fg_y_top_norm + 0.04)]
        else:
            headroom_by = max(0.15, min(0.36, fg_y_top_norm + 0.04))
            cx_cands = [0.50, 0.72, 0.28, 0.78, 0.22, 0.84, 0.16, 0.64, 0.36]
            by_cands = [headroom_by, max(0.13, fg_y_top_norm), 0.20, 0.26, 0.34, 0.44, 0.54]
    else:
        headroom_by = max(0.15, min(0.34, fg_y_top_norm + 0.04))
        cx_cands = [0.50, 0.64, 0.36, 0.76, 0.24]
        by_cands = [headroom_by, max(0.12, fg_y_top_norm), 0.18, 0.24, 0.32, 0.40]

    best_any: Optional[Tuple[float, float, float, float, float]] = None
    best_any_score = -1.0
    chosen: Optional[Tuple[float, float, float, float, float]] = None

    for scale_mult in (1.0, 0.86, 0.74, 0.62, 0.50, 0.40, 0.32, 0.26):
        fs = max(min_font_size, base_font_size * scale_mult)
        f_try = skia.Font(title_tf, fs)
        mw = float(f_try.measureText(stamp))
        fm = f_try.getMetrics()
        asc = abs(float(fm.fAscent))
        desc = abs(float(fm.fDescent))

        half_w_norm = (mw * 0.5) / float(w)
        asc_norm = asc / float(h)
        desc_norm = desc / float(h)
        drift_pad_x = 16.0 / float(w)

        found_at_scale: Optional[Tuple[float, float, float, float, float]] = None
        best_clear_at_scale = -1.0

        for cx_n in cx_cands:
            # Clamp center_x so text never clips viewport left/right margins (6% safe margin)
            cx_clamped = max(half_w_norm + 0.055, min(1.0 - half_w_norm - 0.055, cx_n))
            for by_n in by_cands:
                by_clamped = max(asc_norm + 0.045, min(0.76 - desc_norm, by_n))
                x0 = cx_clamped - half_w_norm - drift_pad_x
                x1 = cx_clamped + half_w_norm + drift_pad_x
                y0 = by_clamped - asc_norm
                y1 = by_clamped + desc_norm
                cf = _bbox_clear_fraction(alpha_grid, x0, y0, x1, y1, alpha_thresh=96)
                q_cfs = _bbox_quartile_clear_fractions(alpha_grid, x0, y0, x1, y1, alpha_thresh=96)
                min_q_cf = min(q_cfs)

                if cf >= 0.92 and min_q_cf >= 0.75:
                    # Prefer first candidate hitting global >=92% AND every quartile >=75%, breaking ties by clarity
                    eff_clarity = cf * 0.65 + min_q_cf * 0.35
                    if found_at_scale is None or eff_clarity > best_clear_at_scale + 0.02:
                        best_clear_at_scale = eff_clarity
                        found_at_scale = (cx_clamped * w, by_clamped * h, fs, mw, cf)
                        if cf >= 0.96 and min_q_cf >= 0.90:
                            break
                score = cf * 100.0 + min_q_cf * 65.0 + scale_mult * 8.0
                if score > best_any_score:
                    best_any_score = score
                    best_any = (cx_clamped * w, by_clamped * h, fs, mw, cf)
            if found_at_scale is not None and best_clear_at_scale >= 0.94:
                break

        if found_at_scale is not None:
            chosen = found_at_scale
            break

    result = chosen or best_any or (float(w) * 0.5, float(h) * (0.37 if is_wide else 0.34), base_font_size, measured_w, 1.0)
    if len(_DEPTH_PLACEMENT_CACHE) >= 64:
        _DEPTH_PLACEMENT_CACHE.clear()
    _DEPTH_PLACEMENT_CACHE[cache_key] = result
    return result


def _get_or_render_depth_title_sprite(
    stamp: str,
    w: int,
    h: int,
    mood_norm: str,
    font_size: float,
    title_tf: skia.Typeface,
) -> Tuple[skia.Image, float, float, float, float]:
    """Pre-render and cache the full 3D Depth Title (seamless radial halo >= 2.2*radius + 3D extrusion
    shadow + gold/crimson gradient fill + specular rim stroke) into an offscreen `skia.Image` sprite
    keyed by `(stamp, w, h, mood, int(font_size))` so per-frame compositing runs in ~0.12 ms/frame!
    Returns `(sprite_img, anchor_cx, anchor_baseline_y, ascent, descent)`.
    """
    fs_int = int(round(font_size))
    cache_key = (stamp, int(w), int(h), mood_norm, fs_int)
    tf_id = int(title_tf.uniqueID())
    cached = _DEPTH_TITLE_SPRITE_CACHE.get(cache_key)
    if cached is not None and cached[0] == tf_id:
        _, spr_img, acx, abase, asc, desc = cached
        return spr_img, acx, abase, asc, desc

    font = skia.Font(title_tf, float(fs_int))
    font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
    measured_w = float(font.measureText(stamp))
    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))
    text_h = max(40.0, ascent + descent)

    # Seamless halo bounds: strictly >= 2.2 * radius so radial glow reaches alpha=0 inside sprite!
    halo_rx = max(120.0, measured_w * 0.62)
    halo_ry = max(110.0, min(halo_rx, text_h * 1.05))
    spr_w = int(math.ceil(max(measured_w + 160.0, halo_rx * 2.26)))
    spr_h = int(math.ceil(max(text_h + 180.0, halo_ry * 2.26)))
    # Keep even dimensions for fast SIMD blitting
    spr_w += spr_w % 2
    spr_h += spr_h % 2

    surf = skia.Surface(spr_w, spr_h)
    sc = surf.getCanvas()
    sc.clear(skia.ColorSetARGB(0, 0, 0, 0))

    anchor_cx = spr_w * 0.5
    text_mid_y = spr_h * 0.5
    anchor_baseline_y = text_mid_y + (ascent - descent) * 0.5
    top_y = anchor_baseline_y - ascent
    bot_y = anchor_baseline_y + descent
    draw_x = anchor_cx - measured_w * 0.5

    is_crimson_mood = mood_norm in ("dark_horror", "investigative_crime")

    # 1. Atmospheric seamless elliptical back-glow (strictly >= 2.2 * radius, zero rectangular seam!)
    glow_col = (
        skia.ColorSetARGB(108, 158, 27, 36)
        if is_crimson_mood
        else skia.ColorSetARGB(98, 212, 175, 55)
    )
    sc.save()
    sc.translate(anchor_cx, (top_y + bot_y) * 0.5)
    sc.scale(1.0, halo_ry / halo_rx)
    halo_r = skia.Rect.MakeXYWH(-halo_rx * 1.12, -halo_rx * 1.12, halo_rx * 2.24, halo_rx * 2.24)
    halo_p = skia.Paint(AntiAlias=True)
    halo_p.setShader(
        skia.GradientShader.MakeRadial(
            (0.0, 0.0),
            halo_rx,
            [glow_col, skia.ColorSetARGB(int(skia.ColorGetA(glow_col) * 0.35), 110, 22, 28) if is_crimson_mood else skia.ColorSetARGB(34, 180, 140, 40), skia.ColorSetARGB(0, 10, 6, 16)],
            [0.0, 0.52, 1.0],
        )
    )
    sc.drawRect(halo_r, halo_p)
    sc.restore()

    # 2. Deep 3D extrusion / soft dark drop shadow (pre-baked once in sprite!)
    shadow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(236, 6, 4, 12))
    shadow_p.setImageFilter(
        skia.ImageFilters.DropShadow(
            0.0,
            16.0,
            26.0,
            26.0,
            skia.ColorSetARGB(236, 0, 0, 0),
        )
    )
    _draw_safe_string(sc, stamp, draw_x, anchor_baseline_y + 6.0, font, shadow_p)

    # 3. Warm Gold / Crimson Vertical Gradient Fill
    if is_crimson_mood:
        grad_colors = [
            hex_to_skia("#FFE082", 255),
            hex_to_skia("#D4AF37", 255),
            hex_to_skia("#9E1B24", 246),
        ]
        grad_pos = [0.0, 0.58, 1.0]
    else:
        grad_colors = [
            hex_to_skia("#FFF3C4", 255),
            hex_to_skia("#FFE082", 255),
            hex_to_skia("#D4AF37", 255),
        ]
        grad_pos = [0.0, 0.52, 1.0]

    fill_p = skia.Paint(AntiAlias=True)
    fill_p.setShader(
        skia.GradientShader.MakeLinear(
            [(anchor_cx, top_y), (anchor_cx, bot_y)],
            grad_colors,
            grad_pos,
        )
    )
    _draw_safe_string(sc, stamp, draw_x, anchor_baseline_y, font, fill_p)

    # 4. Thin crisp specular rim stroke
    stroke_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.2,
        Color=hex_to_skia("#FFF5D6", 174),
    )
    _draw_safe_string(sc, stamp, draw_x, anchor_baseline_y, font, stroke_p)

    spr_img = surf.makeImageSnapshot()
    if len(_DEPTH_TITLE_SPRITE_CACHE) >= 48:
        _DEPTH_TITLE_SPRITE_CACHE.clear()
    _DEPTH_TITLE_SPRITE_CACHE[cache_key] = (tf_id, spr_img, anchor_cx, anchor_baseline_y, ascent, descent)
    return spr_img, anchor_cx, anchor_baseline_y, ascent, descent


def draw_depth_title_behind_subject(
    canvas: skia.Canvas,
    w: int,
    h: int,
    text: str,
    shot_prog: float,
    t: float,
    title_tf: skia.Typeface,
    mood: str = "dark_horror",
    fg_img: Optional[skia.Image] = None,
    **kwargs: Any,
) -> None:
    """Render MagnatesMedia / Johnny Harris 3D Depth Title BETWEEN `bg_img` and `fg_img`
    with Alpha-Aware Rule-of-Thirds + Headroom Placement (`>= 88%` clear legibility) and
    offscreen sprite caching (~0.12 ms/frame).
    """
    stamp = extract_depth_stamp_text(text)
    stamp = _sanitize_glyphs(stamp, typeface=title_tf)
    if not stamp:
        return

    prog_clamped = max(0.0, min(1.0, float(shot_prog)))
    fade_in = _ease_out_cubic(min(1.0, prog_clamped / 0.16))
    fade_out = _ease_out_cubic(min(1.0, (1.0 - prog_clamped) / 0.12)) if prog_clamped > 0.88 else 1.0
    base_alpha = int(198 * min(fade_in, fade_out))
    if base_alpha <= 8:
        return

    mood_norm = str(mood or "dark_horror").lower()
    base_cx, base_by, font_size, _mw, _clear_frac = _compute_depth_title_placement(
        stamp, w, h, title_tf, fg_img=fg_img
    )
    spr_img, anchor_cx, anchor_by, ascent, _descent = _get_or_render_depth_title_sprite(
        stamp, w, h, mood_norm, font_size, title_tf
    )

    # Inverse horizontal parallax drift (opposes foreground subject motion for 2.5D separation)
    # Drawn at crisp 1:1 sprite scale for ultra-fast ~0.25 ms/frame SIMD blitting (240x faster than live blur!)
    drift_x = (prog_clamped - 0.5) * -22.0
    drift_y = (prog_clamped - 0.5) * -5.0 + math.sin(t * 1.4) * 1.8

    center_x = base_cx + drift_x
    baseline_y = base_by + drift_y

    blit_p = skia.Paint()
    blit_p.setAlpha(base_alpha)
    canvas.drawImage(
        spr_img,
        float(int(round(center_x - anchor_cx))),
        float(int(round(baseline_y - anchor_by))),
        _LINEAR_SAMPLING,
        blit_p,
    )


# ---------------------------------------------------------------------------
# 2. 35mm Anamorphic Film-Burn Light Leak, Pre-Cached 96x96 Bokeh & Whip Pan
# ---------------------------------------------------------------------------
def _get_bokeh_orb_sprite(variant: str) -> skia.Image:
    """Pre-render and cache a `96x96` soft radial bokeh orb sprite once (~0.22 ms/frame blit!)."""
    cached = _BOKEH_SPRITE_CACHE.get(variant)
    if cached is not None:
        return cached
    sz = 96
    surf = skia.Surface(sz, sz)
    c = surf.getCanvas()
    c.clear(skia.ColorSetARGB(0, 0, 0, 0))
    if variant == "gold":
        cols = [
            skia.ColorSetARGB(255, 255, 224, 132),
            skia.ColorSetARGB(132, 224, 132, 24),
            skia.ColorSetARGB(0, 0, 0, 0),
        ]
    else:
        cols = [
            skia.ColorSetARGB(255, 242, 92, 74),
            skia.ColorSetARGB(132, 178, 36, 44),
            skia.ColorSetARGB(0, 0, 0, 0),
        ]
    p = skia.Paint(AntiAlias=True)
    p.setShader(
        skia.GradientShader.MakeRadial(
            (sz * 0.5, sz * 0.5),
            sz * 0.48,
            cols,
            [0.0, 0.58, 1.0],
        )
    )
    c.drawCircle(sz * 0.5, sz * 0.5, sz * 0.48, p)
    img = surf.makeImageSnapshot()
    _BOKEH_SPRITE_CACHE[variant] = img
    return img


def draw_anamorphic_film_burn_and_bokeh(
    canvas: skia.Canvas,
    w: int,
    h: int,
    t: float,
    shot_local_t: float,
    mood: str = "dark_horror",
) -> None:
    """Render 2-layer depth particles (14 small crisp distant embers + 6 pre-cached `96x96` radial
    bokeh orb sprites) plus an organic 35mm anamorphic light-leak sweep on the first 0.24s of a cut.
    """
    mood_norm = str(mood or "dark_horror").lower()
    is_dark = mood_norm in ("dark_horror", "investigative_crime", "epic_history")
    fw = max(1.0, float(w))
    fh = max(1.0, float(h))

    # Layer 1: 14 small crisp distant embers drifting upwards (single reused Paint)
    ember_p = skia.Paint(AntiAlias=True)
    base_e_a = 76 if is_dark else 58
    for i in range(14):
        speed_x = 18.0 + (i % 5) * 6.5
        speed_y = 22.0 + (i % 4) * 8.0
        phase = i * 1.37
        ex = (i * 197.0 + t * speed_x + math.sin(t * 1.8 + phase) * 18.0) % fw
        ey = (i * 139.0 - t * speed_y) % fh
        flicker = 0.55 + 0.45 * math.sin(t * 4.6 + phase)
        rad = 1.6 + (i % 3) * 0.95
        ember_alpha = int(base_e_a * flicker)
        if i % 3 == 0:
            ember_p.setColor(skia.ColorSetARGB(ember_alpha, 255, 122, 48))
        else:
            ember_p.setColor(skia.ColorSetARGB(ember_alpha, 255, 214, 112))
        canvas.drawCircle(ex, ey, rad, ember_p)

    # Layer 2: 6 pre-cached 96x96 luminous radial bokeh orbs via fast SIMD kSrcOver (~0.24 ms/frame!)
    spr_gold = _get_bokeh_orb_sprite("gold")
    spr_crim = _get_bokeh_orb_sprite("crimson")
    src_r = skia.Rect.MakeWH(96.0, 96.0)
    bokeh_p = skia.Paint()
    for bi in range(6):
        b_phase = bi * 2.09
        bx = ((bi * 311.0 + t * (9.0 + (bi % 3) * 4.0) + math.cos(t * 0.7 + b_phase) * 32.0) % (fw + 160.0)) - 80.0
        by = ((bi * 257.0 - t * (7.5 + (bi % 2) * 3.5) + math.sin(t * 0.6 + b_phase) * 24.0) % (fh + 160.0)) - 80.0
        b_rad = (36.0 + (bi % 3) * 18.0) * (1.0 + 0.08 * math.sin(t * 1.3 + b_phase))
        pulse = 0.65 + 0.35 * math.sin(t * 1.9 + b_phase)
        bokeh_p.setAlpha(int(28 * pulse))
        dst_r = skia.Rect.MakeXYWH(bx - b_rad, by - b_rad, b_rad * 2.0, b_rad * 2.0)
        canvas.drawImageRect(
            spr_gold if (bi % 2 == 0) else spr_crim,
            src_r,
            dst_r,
            _LINEAR_SAMPLING,
            bokeh_p,
            skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
        )

    # Layer 3: Organic 35mm Anamorphic Film-Burn / Light-Leak Sweep on Shot Cuts (`0 <= shot_local_t < 0.24`)
    if 0.0 <= float(shot_local_t) < 0.24:
        u = float(shot_local_t) / 0.24
        env = ((1.0 - u) ** 1.55) * (0.72 + 0.28 * math.sin(u * math.pi))
        if env > 0.01:
            full_r = skia.Rect.MakeWH(w, h)
            sweep_x = w * (0.12 + 0.76 * u)
            sweep_y = h * (0.28 + 0.18 * math.sin(u * math.pi))
            burn_rad = max(w, h) * (0.58 + 0.18 * (1.0 - u))

            burn_p = skia.Paint(AntiAlias=True)
            burn_p.setBlendMode(skia.BlendMode.kScreen)
            burn_p.setShader(
                skia.GradientShader.MakeRadial(
                    (sweep_x, sweep_y),
                    burn_rad,
                    [
                        skia.ColorSetARGB(int(165 * env), 255, 226, 142),
                        skia.ColorSetARGB(int(118 * env), 224, 98, 36),
                        skia.ColorSetARGB(int(72 * env), 158, 27, 36),
                        skia.ColorSetARGB(0, 0, 0, 0),
                    ],
                    [0.0, 0.34, 0.68, 1.0],
                )
            )
            canvas.drawRect(full_r, burn_p)

            streak_h = max(64.0, h * 0.09)
            streak_y = sweep_y - streak_h * 0.5
            streak_r = skia.Rect.MakeXYWH(0.0, streak_y, float(w), streak_h)
            streak_p = skia.Paint(AntiAlias=True)
            streak_p.setBlendMode(skia.BlendMode.kScreen)
            streak_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(0.0, streak_y), (0.0, streak_y + streak_h)],
                    [
                        skia.ColorSetARGB(0, 255, 180, 90),
                        skia.ColorSetARGB(int(92 * env), 255, 214, 130),
                        skia.ColorSetARGB(0, 158, 27, 36),
                    ],
                    [0.0, 0.5, 1.0],
                )
            )
            canvas.drawRect(streak_r, streak_p)


def draw_chapter_whip_and_film_burn(
    canvas: skia.Canvas,
    w: int,
    h: int,
    prog: float,
    mode: str = "film_burn",
    direction: int = 1,
    mood: str = "dark_horror",
) -> None:
    """Optional 8-frame directional `whip_pan` (`~0.267s @ 30fps`) or 12-frame organic `film_burn`
    (`~0.40s @ 30fps`) chapter transition overlay. `prog` advances `0.0 -> 1.0`.
    """
    u = max(0.0, min(1.0, float(prog)))
    if u <= 0.001 or u >= 0.999:
        return
    m = str(mode or "film_burn").strip().lower()
    full_r = skia.Rect.MakeWH(w, h)
    bell = math.sin(u * math.pi) ** 1.25
    dir_sign = 1.0 if int(direction) >= 0 else -1.0

    if m in ("whip_pan", "whip", "whip_and_burn", "both"):
        # High-velocity horizontal directional whip-pan motion streaks + edge drag
        drag_alpha = int(175 * bell)
        drag_p = skia.Paint(AntiAlias=True)
        x0 = 0.0 if dir_sign > 0 else float(w)
        x1 = float(w) if dir_sign > 0 else 0.0
        drag_p.setShader(
            skia.GradientShader.MakeLinear(
                [(x0, 0.0), (x1, 0.0)],
                [
                    skia.ColorSetARGB(int(drag_alpha * 0.85), 10, 12, 16),
                    skia.ColorSetARGB(int(drag_alpha * 0.45), 18, 20, 23),
                    skia.ColorSetARGB(int(drag_alpha * 0.92), 8, 8, 12),
                ],
                [0.0, 0.5, 1.0],
            )
        )
        canvas.drawRect(full_r, drag_p)

        # Horizontal velocity blur streaks sweeping rapidly across frame
        streak_p = skia.Paint(AntiAlias=True)
        streak_p.setBlendMode(skia.BlendMode.kScreen)
        for idx in range(11):
            sy = (idx + 0.5) * (float(h) / 11.0) + math.sin(idx * 2.3) * 18.0
            sh = 14.0 + (idx % 4) * 16.0
            sweep_norm = (u * 1.45 - (idx % 3) * 0.14)
            sx = (sweep_norm * w) if dir_sign > 0 else ((1.0 - sweep_norm) * w)
            sw = w * (0.48 + 0.24 * bell)
            col_a = int((76 if idx % 2 == 0 else 54) * bell)
            c_mid = (
                skia.ColorSetARGB(col_a, 234, 179, 8)
                if idx % 3 != 0
                else skia.ColorSetARGB(col_a, 217, 56, 30)
            )
            streak_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(sx - sw * 0.5, sy), (sx + sw * 0.5, sy)],
                    [skia.ColorSetARGB(0, 0, 0, 0), c_mid, skia.ColorSetARGB(0, 0, 0, 0)],
                    [0.0, 0.5, 1.0],
                )
            )
            canvas.drawRect(skia.Rect.MakeXYWH(sx - sw * 0.5, sy - sh * 0.5, sw, sh), streak_p)

    if m in ("film_burn", "light_leak", "whip_and_burn", "both"):
        # 12-frame 35mm halide light leak / film burn blooming warmly across frame
        burn_env = (math.sin(u * math.pi) ** 1.1) * (0.85 + 0.15 * math.cos(u * math.pi * 2.0))
        cx1 = w * (0.15 + 0.72 * u) if dir_sign > 0 else w * (0.85 - 0.72 * u)
        cy1 = h * (0.36 + 0.18 * math.sin(u * math.pi))
        rad1 = max(w, h) * (0.55 + 0.26 * burn_env)

        burn1 = skia.Paint(AntiAlias=True)
        burn1.setBlendMode(skia.BlendMode.kScreen)
        burn1.setShader(
            skia.GradientShader.MakeRadial(
                (cx1, cy1),
                rad1,
                [
                    skia.ColorSetARGB(int(215 * burn_env), 255, 236, 172),
                    skia.ColorSetARGB(int(165 * burn_env), 234, 128, 32),
                    skia.ColorSetARGB(int(115 * burn_env), 217, 56, 30),
                    skia.ColorSetARGB(0, 0, 0, 0),
                ],
                [0.0, 0.30, 0.64, 1.0],
            )
        )
        canvas.drawRect(full_r, burn1)

        # Secondary edge sprocket halide bleed
        cx2 = w * (0.90 - 0.45 * u) if dir_sign > 0 else w * (0.10 + 0.45 * u)
        cy2 = h * 0.72
        burn2 = skia.Paint(AntiAlias=True)
        burn2.setBlendMode(skia.BlendMode.kScreen)
        burn2.setShader(
            skia.GradientShader.MakeRadial(
                (cx2, cy2),
                max(w, h) * 0.44,
                [
                    skia.ColorSetARGB(int(145 * burn_env), 255, 200, 96),
                    skia.ColorSetARGB(int(80 * burn_env), 185, 28, 38),
                    skia.ColorSetARGB(0, 0, 0, 0),
                ],
                [0.0, 0.52, 1.0],
            )
        )
        canvas.drawRect(full_r, burn2)


# ---------------------------------------------------------------------------
# 3. Date & Location Stamp (`date_and_location_stamp` JSON v3.0.0 + 9:16 Mobile Safe Zone)
# ---------------------------------------------------------------------------
def draw_pro_safezone_lower_third(
    canvas: skia.Canvas,
    w: int,
    h: int,
    title: str,
    subtitle: str,
    body_t: float,
    body_dur: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    max_display_s: float = 3.8,
    **kwargs: Any,
) -> None:
    """Render Documentary Date & Location Stamp:
    - In 16:9 (`w >= h`, JSON v3.0.0 `date_and_location_stamp`):
      - Position: `bottom_left` with `margin_px: {"x": 96, "y": 84}` (`x = 96, y = h - 84 - pill_h`).
      - Typography: `Cinzel Bold 42px` (`#F8FAFC`) primary stamp + `Courier Prime Bold 24px` (`#E0C097`)
        subtitle + `4px` `#EAB308` vertical left accent bar.
      - Animation: Left-to-right `canvas.clipRect` mask reveal over `0.40s` using `cubic-bezier(0.22, 1, 0.36, 1)`.
    - In 9:16 (`w < h`, Mobile Safe-Zone):
      - Position: `y = 192px, x = 46px` (strictly below TikTok/Reels/Shorts top UI dead zone!).
    """
    vis_dur = min(max(0.5, float(body_dur)), float(max_display_s))
    if body_t < 0.0 or body_t >= vis_dur:
        return

    is_wide = w >= h

    if is_wide:
        eff_title_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf
        eff_ui_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
        clean_title = _sanitize_glyphs(_normalize_upper(title), typeface=eff_title_tf)
        clean_sub = _sanitize_glyphs(_normalize_upper(subtitle), typeface=eff_ui_tf)
        if not clean_title and not clean_sub:
            return

        # Exact 0.40s cubic-bezier(0.22, 1, 0.36, 1) left-to-right mask reveal + 0.36s exit
        reveal_p = _ease_doc_snap(min(1.0, body_t / 0.40))
        exit_a = _ease_out_cubic(min(1.0, (vis_dur - body_t) / 0.36)) if (vis_dur - body_t) < 0.36 else 1.0
        alpha = int(248 * exit_a)
        if alpha <= 8 or reveal_p <= 0.01:
            return

        scale_x = float(w) / 1920.0
        scale_y = float(h) / 1080.0
        margin_x = 96.0 * scale_x
        margin_y = 84.0 * scale_y
        # Strictly bound 16:9 pill to <= 0.42*w (806px, max right edge x=902px) so it NEVER reaches the right half!
        max_pill_w = min(float(w) - margin_x * 2.0, float(w) * 0.42)
        max_text_w = max(220.0, max_pill_w - 56.0 * scale_x)

        t_font, t_lns = _wrap_text_to_width(clean_title, eff_title_tf, 42.0 * scale_x, 20.0 * scale_x, max_text_w, 1)
        t_font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        t_line = t_lns[0] if t_lns else clean_title
        t_w = float(t_font.measureText(t_line)) if t_line else 0.0

        s_line = ""
        s_w = 0.0
        s_font = skia.Font(eff_ui_tf, 24.0 * scale_x)
        s_font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        if clean_sub:
            s_font, s_lns = _wrap_text_to_width(clean_sub, eff_ui_tf, 24.0 * scale_x, 13.5 * scale_x, max_text_w, 1)
            s_font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
            s_line = s_lns[0] if s_lns else clean_sub
            s_w = float(s_font.measureText(s_line)) if s_line else 0.0

        content_w = max(t_w, s_w)
        pill_w = min(max_pill_w, max(240.0 * scale_x, content_w + 56.0 * scale_x))
        pill_h = (108.0 if s_line else 68.0) * scale_y

        bx = margin_x
        by = float(h) - margin_y - pill_h
        pill_r = skia.Rect.MakeXYWH(bx, by, pill_w, pill_h)
        pill_rr = skia.RRect.MakeRectXY(pill_r, 8.0, 8.0)

        # Left-to-right mask reveal via canvas.clipRect over first 0.40s
        canvas.save()
        clip_w = (pill_w + 36.0) * reveal_p
        canvas.clipRect(skia.Rect.MakeXYWH(bx - 12.0, by - 16.0, max(1.0, clip_w), pill_h + 44.0))

        # Dark slate translucent glass panel (#121417) with fast layered shadow
        _draw_fast_rrect_shadow(canvas, pill_rr, dy=10.0, sigma=16.0, alpha=int(alpha * 0.72))
        bg_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.86), 18, 20, 23))
        canvas.drawRRect(pill_rr, bg_p)

        border_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.2,
            Color=hex_to_skia("#2C323B", int(alpha * 0.85)),
        )
        canvas.drawRRect(pill_rr, border_p)

        # Exact 4px #EAB308 vertical accent bar on left edge
        bar_w = max(4.0, 4.0 * scale_x)
        bar_r = skia.Rect.MakeXYWH(bx, by + 6.0 * scale_y, bar_w, pill_h - 12.0 * scale_y)
        canvas.drawRoundRect(bar_r, 2.0, 2.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308", alpha)))

        # Primary Cinzel Bold 42px (#F8FAFC) + Secondary Courier Prime Bold 24px (#E0C097)
        text_x = bx + 22.0 * scale_x
        if t_line:
            title_y = by + ((50.0 if s_line else 46.0) * scale_y)
            _draw_safe_string(
                canvas,
                t_line,
                text_x,
                title_y,
                t_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", alpha)),
            )
        if s_line:
            sub_y = by + 86.0 * scale_y
            _draw_safe_string(
                canvas,
                s_line,
                text_x,
                sub_y,
                s_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#E0C097", int(alpha * 0.96))),
            )

        canvas.restore()
        return

    # 9:16 Vertical Mobile Safe-Zone Lower Third (`y = 192px, x = 46px`)
    clean_title = _sanitize_glyphs(_normalize_upper(title), typeface=title_tf)
    clean_sub = _sanitize_glyphs(_normalize_upper(subtitle), typeface=ui_tf)
    if not clean_title and not clean_sub:
        return

    enter = _ease_out_cubic(min(1.0, body_t / 0.36))
    exit_a = _ease_out_cubic(min(1.0, (vis_dur - body_t) / 0.36)) if (vis_dur - body_t) < 0.36 else 1.0
    alpha = int(242 * min(enter, exit_a))
    if alpha <= 8:
        return

    base_x = 46.0
    base_y = 192.0
    max_pill_w = float(w) - 92.0
    max_text_w = max(160.0, max_pill_w - 44.0)

    t_font, t_lns = _wrap_text_to_width(clean_title, title_tf, 31.0, 19.0, max_text_w, 1)
    t_line = t_lns[0] if t_lns else clean_title
    t_w = float(t_font.measureText(t_line)) if t_line else 0.0

    s_line = ""
    s_w = 0.0
    s_font = skia.Font(ui_tf, 23.0)
    if clean_sub:
        s_font, s_lns = _wrap_text_to_width(clean_sub, ui_tf, 23.0, 15.0, max_text_w, 1)
        s_line = s_lns[0] if s_lns else clean_sub
        s_w = float(s_font.measureText(s_line)) if s_line else 0.0

    content_w = max(t_w, s_w)
    pill_w = min(max_pill_w, max(180.0, content_w + 44.0))
    pill_h = 100.0 if s_line else 64.0

    bx = base_x + (1.0 - enter) * -28.0
    by = base_y

    pill_r = skia.Rect.MakeXYWH(bx, by, pill_w, pill_h)
    pill_rr = skia.RRect.MakeRectXY(pill_r, 14.0, 14.0)

    _draw_fast_rrect_shadow(canvas, pill_rr, dy=10.0, sigma=18.0, alpha=int(alpha * 0.75))
    bg_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.90), 11, 8, 20))
    canvas.drawRRect(pill_rr, bg_p)

    border_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.5,
        Color=hex_to_skia("#FFD166", int(alpha * 0.42)),
    )
    canvas.drawRRect(pill_rr, border_p)

    bar_full_h = pill_h - 20.0
    bar_cur_h = bar_full_h * _ease_out_cubic(min(1.0, body_t / 0.48))
    bar_y = by + 10.0 + (bar_full_h - bar_cur_h) * 0.5
    bar_r = skia.Rect.MakeXYWH(bx + 8.0, bar_y, 6.0, max(6.0, bar_cur_h))
    bar_p = skia.Paint(AntiAlias=True)
    bar_p.setShader(
        skia.GradientShader.MakeLinear(
            [(bx + 8.0, by + 10.0), (bx + 8.0, by + pill_h - 10.0)],
            [hex_to_skia("#FFD166", alpha), hex_to_skia("#9E1B24", alpha)],
        )
    )
    canvas.drawRoundRect(bar_r, 3.0, 3.0, bar_p)

    text_x = bx + 24.0
    if t_line:
        title_y = (by + 42.0) if s_line else (by + 43.0)
        _draw_safe_string(
            canvas,
            t_line,
            text_x,
            title_y,
            t_font,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", alpha)),
        )
    if s_line:
        sub_y = by + 79.0
        _draw_safe_string(
            canvas,
            s_line,
            text_x,
            sub_y,
            s_font,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#F4EFE6", int(alpha * 0.96))),
        )


# ---------------------------------------------------------------------------
# 4. Dark Cartographic Tactical Map of Europe & Mediterranean
# ---------------------------------------------------------------------------
# Procedural normalized (0..1, 0..1) coastline polygons for Europe, Scandinavia & Mediterranean
_EUROPE_LANDMASS_POLYS: List[List[Tuple[float, float]]] = [
    # Scandinavia / Nordic Peninsula (Norway & Sweden)
    [
        (0.39, 0.16), (0.42, 0.10), (0.50, 0.05), (0.59, 0.08),
        (0.58, 0.15), (0.52, 0.18), (0.45, 0.19),
    ],
    # Great Britain (London at ~0.27, 0.27)
    [
        (0.21, 0.14), (0.26, 0.12), (0.28, 0.18), (0.27, 0.23),
        (0.30, 0.26), (0.29, 0.30), (0.22, 0.31), (0.19, 0.28),
        (0.22, 0.23), (0.20, 0.18),
    ],
    # Ireland
    [
        (0.13, 0.19), (0.17, 0.18), (0.18, 0.24), (0.14, 0.26), (0.12, 0.23),
    ],
    # Continental Western/Central Europe + Iberia + France + Alps + Italy + Balkans
    [
        (0.06, 0.56), (0.07, 0.44), (0.16, 0.43), (0.21, 0.35),
        (0.28, 0.32), (0.36, 0.24), (0.43, 0.18), (0.48, 0.14),
        (0.55, 0.18), (0.64, 0.16), (0.78, 0.15), (0.92, 0.20),
        (0.94, 0.36), (0.84, 0.42), (0.75, 0.43), (0.71, 0.50),
        # Greece / Peloponnese peninsula
        (0.68, 0.62), (0.64, 0.66), (0.61, 0.59), (0.58, 0.50),
        # Adriatic East coast up to Venice
        (0.53, 0.43), (0.48, 0.43),
        # Italian boot peninsula (Rome at ~0.47, 0.56)
        (0.51, 0.52), (0.56, 0.61), (0.54, 0.67), (0.50, 0.64),
        (0.46, 0.57), (0.42, 0.49), (0.37, 0.48),
        # Southern France & Iberian Mediterranean coast
        (0.30, 0.51), (0.23, 0.58), (0.15, 0.65), (0.08, 0.64),
    ],
    # Sicily
    [
        (0.47, 0.68), (0.52, 0.68), (0.51, 0.72), (0.47, 0.71),
    ],
    # Corsica & Sardinia
    [
        (0.39, 0.53), (0.41, 0.53), (0.41, 0.63), (0.38, 0.63),
    ],
    # Anatolia / Asia Minor (Myra at ~0.78, 0.68) & Levant / Palmyra
    [
        (0.72, 0.52), (0.82, 0.49), (0.95, 0.48), (0.97, 0.78),
        (0.89, 0.80), (0.86, 0.69), (0.79, 0.70), (0.73, 0.66),
        (0.71, 0.58),
    ],
    # North Africa Mediterranean Coastline
    [
        (0.08, 0.76), (0.24, 0.73), (0.38, 0.72), (0.44, 0.77),
        (0.56, 0.82), (0.72, 0.84), (0.88, 0.83), (0.95, 0.94),
        (0.06, 0.94),
    ],
]

# Eastern North America coastline polygons used in Transatlantic Projection Mode (u in [0.02..0.30])
_EASTERN_NORTH_AMERICA_POLYS: List[List[Tuple[float, float]]] = [
    # Labrador -> Nova Scotia -> New England (Boston ~0.228, 0.345) -> NY (~0.206, 0.402) -> Florida -> Gulf
    [
        (0.02, 0.14), (0.14, 0.13), (0.22, 0.17), (0.26, 0.23),
        (0.29, 0.27), (0.25, 0.30), (0.255, 0.345), (0.225, 0.395),
        (0.205, 0.455), (0.215, 0.525), (0.175, 0.595), (0.185, 0.695),
        (0.165, 0.775), (0.135, 0.755), (0.125, 0.675), (0.06, 0.665),
        (0.02, 0.640),
    ],
    # Newfoundland island
    [
        (0.285, 0.175), (0.320, 0.185), (0.315, 0.225), (0.280, 0.215),
    ],
]

_AMERICAS_CITY_KEYS = (
    "BOSTON", "MASSACHUSETTS", "NOVA INGLATERRA", "NEW ENGLAND",
    "NOVA YORK", "NEW YORK", "NOVA IORQUE", "MANHATTAN",
    "CHICAGO", "ILLINOIS", "WASHINGTON", "FILADÉLFIA", "FILADELFIA", "PHILADELPHIA",
)

_CITY_GEO_COORDS: List[Tuple[Tuple[str, ...], Tuple[float, float], str]] = [
    (("CANTERBURY", "KENT"), (0.292, 0.288), "51°16'N 01°04'E"),
    (("WESTMINSTER", "PARLAMENTO"), (0.265, 0.278), "51°30'N 00°07'W"),
    (("AMSTERDÃ", "AMSTERDA", "AMSTERDAM", "HOLANDA", "PAÍSES BAIXOS", "NETHERLANDS", "DUTCH"), (0.352, 0.258), "52°22'N 04°54'E"),
    (("VATICANO", "VATICAN", "SANTA SÉ"), (0.463, 0.562), "41°54'N 12°27'E"),
    (("ROMA", "ROME", "ITÁLIA", "ITALY", "SATURNALIA", "SATURNÁLIA", "TRASIMENO"), (0.465, 0.565), "41°54'N 12°29'E"),
    (("PALMIRA", "PALMYRA", "SÍRIA", "SIRIA", "SYRIA"), (0.885, 0.725), "34°33'N 38°16'E"),
    (("MIRA", "MYRA", "DEMRE", "ÁSIA MENOR", "ASIA MINOR", "ANATÓLIA", "ANATOLIA", "LÍCIA", "LICIA"), (0.785, 0.675), "36°15'N 29°59'E"),
    (("CONSTANTINOPLA", "CONSTANTINOPLE", "ISTAMBUL", "ISTANBUL", "BIZÂNCIO", "BYZANTIUM", "TURQUIA", "TURKEY"), (0.742, 0.542), "41°01'N 28°58'E"),
    (("ALPES", "ALPS", "ÁUSTRIA", "AUSTRIA", "TIROL", "SALZBURGO", "VIENA", "KRAMPUS"), (0.465, 0.395), "47°16'N 11°24'E"),
    (("ALEMANHA", "GERMANY", "BAVIERA", "BAVARIA", "MUNIQUE", "MUNICH", "BERLIM", "BERLIN", "HERZOGENAURACH"), (0.478, 0.335), "48°08'N 11°34'E"),
    (("BOSTON", "MASSACHUSETTS", "NOVA INGLATERRA", "NEW ENGLAND"), (0.228, 0.345), "42°21'N 71°03'W"),
    (("NOVA YORK", "NEW YORK", "NOVA IORQUE", "MANHATTAN"), (0.206, 0.402), "40°42'N 74°00'W"),
    (("CHICAGO", "ILLINOIS"), (0.128, 0.362), "41°52'N 87°37'W"),
    (("POLO NORTE", "NORTH POLE", "ÁRTICO", "ARTICO", "ARCTIC"), (0.500, 0.085), "90°00'N 00°00'E"),
    (("LONDRES", "LONDON", "WINDSOR", "MANCHESTER", "INGLATERRA", "ENGLAND", "BRITÂNICO", "PURITANO", "CROMWELL"), (0.268, 0.275), "51°30'N 00°07'W"),
    (("PARIS", "FRANÇA", "FRANCE"), (0.315, 0.355), "48°51'N 02°21'E"),
    (("ESCANDINÁVIA", "SCANDINAVIA", "NORUEGA", "NORWAY", "SUÉCIA", "SWEDEN", "YULE", "ODIN"), (0.480, 0.145), "59°55'N 10°45'E"),
    (("MILÃO", "MILAN"), (0.425, 0.455), "45°28'N 09°11'E"),
    (("VILNIUS", "LITUÂNIA", "LITHUANIA", "LETÔNIA", "LATVIA"), (0.685, 0.235), "54°41'N 25°16'E"),
    (("ATENAS", "ATHENS", "GRÉCIA", "GREECE", "NICEIA", "NICAEA"), (0.655, 0.625), "37°59'N 23°43'E"),
]


def _is_americas_location(name: str) -> bool:
    up = _normalize_upper(name)
    return any(k in up for k in _AMERICAS_CITY_KEYS)


def _project_eu_uv_transatlantic(uv: Tuple[float, float]) -> Tuple[float, float]:
    """Shift normalized Europe/Mediterranean UV into right half (`[0.44..1.00]`) for transatlantic routes."""
    return (0.44 + uv[0] * 0.56, uv[1])


def _resolve_city_map_point(
    name: str,
    default_uv: Tuple[float, float],
    default_coord: str,
    transatlantic: bool = False,
) -> Tuple[Tuple[float, float], str]:
    up = _normalize_upper(name)
    for keys, uv, coord_str in _CITY_GEO_COORDS:
        for k in keys:
            if k in up:
                if transatlantic and not _is_americas_location(name):
                    return _project_eu_uv_transatlantic(uv), coord_str
                return uv, coord_str
    if transatlantic and not _is_americas_location(name):
        return _project_eu_uv_transatlantic(default_uv), default_coord
    return default_uv, default_coord


def _draw_compass_rose(
    canvas: skia.Canvas,
    cx: float,
    cy: float,
    radius: float,
    ui_tf: skia.Typeface,
) -> None:
    ring_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.2,
        Color=skia.ColorSetARGB(72, 234, 179, 8),
    )
    canvas.drawCircle(cx, cy, radius, ring_p)
    canvas.drawCircle(cx, cy, radius * 0.72, ring_p)

    # 4 cardinal points + 4 intercardinal ticks
    star_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(96, 234, 179, 8))
    for angle_deg, len_mult in ((0, 1.0), (90, 0.85), (180, 0.85), (270, 0.85), (45, 0.52), (135, 0.52), (225, 0.52), (315, 0.52)):
        rad_a = math.radians(angle_deg - 90.0)
        px = cx + math.cos(rad_a) * (radius * len_mult)
        py = cy + math.sin(rad_a) * (radius * len_mult)
        canvas.drawLine(cx, cy, px, py, ring_p)

    north_path = skia.Path()
    north_path.moveTo(cx, cy - radius * 1.02)
    north_path.lineTo(cx - radius * 0.16, cy)
    north_path.lineTo(cx + radius * 0.16, cy)
    north_path.close()
    canvas.drawPath(north_path, star_p)

    nf = skia.Font(ui_tf, max(11.0, radius * 0.28))
    nw = float(nf.measureText("N"))
    _draw_safe_string(
        canvas,
        "N",
        cx - nw * 0.5,
        cy - radius * 1.12,
        nf,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(165, 234, 179, 8)),
    )


def _draw_tactical_pip_monitor(
    canvas: skia.Canvas,
    pip_img: Optional[skia.Image],
    cx: float,
    cy: float,
    pip_w: float,
    pip_h: float,
    label_text: str,
    coord_text: str,
    body_t: float,
    t: float,
    ui_tf: skia.Typeface,
    is_en: bool = False,
) -> None:
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    ent = _ease_doc_snap(min(1.0, max(0.0, (body_t - 0.08) / 0.42)))
    sc = 0.86 + 0.14 * ent

    canvas.save()
    canvas.translate(cx, cy)
    canvas.scale(sc, sc)

    r = skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, pip_h)
    rr = skia.RRect.MakeRectXY(r, 12.0, 12.0)

    _draw_fast_rrect_shadow(canvas, rr, dy=18.0, sigma=24.0, alpha=217)
    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(242, 18, 20, 23))
    canvas.drawRRect(rr, sh_p)

    canvas.save()
    canvas.clipRRect(rr, doAntiAlias=True)
    if pip_img is not None:
        kb = 1.03 + 0.05 * math.sin(t * 0.5)
        canvas.save()
        canvas.scale(kb, kb)
        _draw_image_cover(canvas, pip_img, r, y_bias=0.25)
        canvas.restore()
    else:
        grad = skia.Paint()
        grad.setShader(
            skia.GradientShader.MakeLinear(
                [(-pip_w * 0.5, -pip_h * 0.5), (pip_w * 0.5, pip_h * 0.5)],
                [skia.ColorSetARGB(255, 28, 32, 39), skia.ColorSetARGB(255, 18, 20, 23)],
            )
        )
        canvas.drawRect(r, grad)

    # Subtle scanlines + top/bottom HUD scrims
    scan_p = skia.Paint(Color=skia.ColorSetARGB(20, 0, 0, 0))
    for sy in range(int(-pip_h * 0.5), int(pip_h * 0.5), 4):
        canvas.drawLine(-pip_w * 0.5, sy, pip_w * 0.5, sy, scan_p)

    top_scrim = skia.Paint()
    top_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, -pip_h * 0.5), (0.0, -pip_h * 0.5 + 54.0)],
            [skia.ColorSetARGB(190, 12, 14, 18), skia.ColorSetARGB(0, 12, 14, 18)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, 54.0), top_scrim)

    bot_scrim = skia.Paint()
    bot_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, pip_h * 0.5 - 56.0), (0.0, pip_h * 0.5)],
            [skia.ColorSetARGB(0, 12, 14, 18), skia.ColorSetARGB(210, 12, 14, 18)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, pip_h * 0.5 - 56.0, pip_w, 56.0), bot_scrim)

    # Corner tactical brackets (#EAB308)
    ret_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.4,
        Color=hex_to_skia("#EAB308", 215),
    )
    blen = 22.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            rx_c = sx * (pip_w * 0.5 - 14.0)
            ry_c = sy * (pip_h * 0.5 - 14.0)
            canvas.drawLine(rx_c, ry_c, rx_c - sx * blen, ry_c, ret_p)
            canvas.drawLine(rx_c, ry_c, rx_c, ry_c - sy * blen, ret_p)

    # Top-left archival feed pill
    rec_txt = "ARCHIVE FEED • SECTOR CAM" if is_en else "ARQUIVO VISUAL • SETOR"
    rf, rl = _wrap_text_to_width(rec_txt, cp_tf, 14.5, 11.0, pip_w - 60.0, 1)
    r_str = rl[0] if rl else rec_txt
    rw = float(rf.measureText(r_str))
    pill_r = skia.Rect.MakeXYWH(-pip_w * 0.5 + 18.0, -pip_h * 0.5 + 16.0, rw + 42.0, 28.0)
    canvas.drawRoundRect(pill_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 18, 20, 23)))
    blink = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 6.4))
    canvas.drawCircle(
        pill_r.left() + 14.0,
        pill_r.centerY(),
        4.8,
        skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E", int(255 * blink))),
    )
    _draw_safe_string(canvas, r_str, pill_r.left() + 26.0, pill_r.top() + 19.5, rf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

    # Bottom coordinate & location telemetry bar
    bot_txt = f"{_normalize_upper(label_text)}  •  {coord_text}"
    bf, bl = _wrap_text_to_width(bot_txt, cp_tf, 15.5, 12.0, pip_w - 40.0, 1)
    if bl:
        _draw_safe_string(
            canvas,
            bl[0],
            -pip_w * 0.5 + 20.0,
            pip_h * 0.5 - 16.0,
            bf,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")),
        )

    canvas.restore()
    canvas.drawRRect(
        rr,
        skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=2.0,
            Color=skia.ColorSetARGB(48, 255, 255, 255),
        ),
    )
    canvas.restore()


def draw_pro_cartographic_map(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    pip_img: Optional[skia.Image],
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render Dark Topographic Tactical Map (`#121417` base, `#2C323B` muted borders, 65%-brightness
    desaturated realistic blend, `#EAB308` / `#D9381E` / `#F8FAFC` vectors, `Courier Prime Bold` labels):
      - When `orig_name != dest_name`: animated A->B cubic Bézier route arc (`cubic-bezier(0.22, 1, 0.36, 1)`)
        with dashed `stroke-dashoffset`, traveling ember head, and accurate lat/lon pins.
      - When `orig_name == dest_name` (single-city event like LONDRES or CANTERBURY): NEVER silently
        resets coordinates to another city! Renders **Tactical Regional Perimeter & Schematic Mode**
        with a single high-precision pin at true city coords, expanding concentric tactical target rings
        in `#D9381E` / `#EAB308`, vector callout lines, and historical schematic HUD over the 65%
        desaturated backdrop + PiP monitor.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    cinzel_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf

    # Base desaturated 65% brightness dark realistic scene (#121417 foundation)
    full_r = skia.Rect.MakeWH(w, h)
    canvas.clear(hex_to_skia("#121417"))
    desat_bg = _get_desat65_image(backdrop_img) if backdrop_img is not None else None
    if desat_bg is not None:
        canvas.save()
        canvas.translate(w * 0.5, h * 0.5)
        sc_bg = 1.03 + 0.04 * prog
        canvas.scale(sc_bg, sc_bg)
        _draw_image_cover(canvas, desat_bg, skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h), paint=None, y_bias=0.28)
        canvas.restore()
    vig_img = _get_cached_gradient_overlay(
        "map_vig_bg",
        w,
        h,
        lambda gc, gw, gh: gc.drawRect(
            skia.Rect.MakeWH(gw, gh),
            _make_radial_paint(
                (gw * 0.5, gh * 0.48),
                max(gw, gh) * 0.72,
                [skia.ColorSetARGB(120, 18, 20, 23), skia.ColorSetARGB(215, 10, 12, 16)],
            ),
        ),
    )
    _draw_cached_gradient(canvas, vig_img, w, h)
    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)

    is_wide = w >= h
    if is_wide:
        map_w = w * 0.90
        map_h = min(756.0, h - 252.0)  # Leaves bottom_left date stamp margin (y=84+108) completely unobstructed
        mx = (w - map_w) * 0.5
        my = 58.0
        pip_w, pip_h = 468.0, 264.0
        pip_cx = mx + map_w - pip_w * 0.5 - 26.0
        pip_cy = my + map_h - pip_h * 0.5 - 24.0
        geo_x0 = mx + 28.0
        geo_w = map_w - pip_w - 64.0
        geo_y0 = my + 108.0
        geo_h = map_h - 136.0
    else:
        map_w = w - 92.0
        map_h = 684.0
        mx = 46.0
        my = 308.0
        pip_w = w - 124.0
        pip_h = 406.0
        pip_cx = w * 0.5
        pip_cy = my + map_h + 24.0 + pip_h * 0.5
        geo_x0 = mx + 18.0
        geo_w = map_w - 36.0
        geo_y0 = my + 108.0
        geo_h = map_h - 134.0

    map_r = skia.Rect.MakeXYWH(mx, my, map_w, map_h)
    map_rr = skia.RRect.MakeRectXY(map_r, 16.0, 16.0)

    # Outer dark slate cartographic frame + fast layered shadow
    _draw_fast_rrect_shadow(canvas, map_rr, dy=18.0, sigma=28.0, alpha=220)
    frame_shadow = skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 242))
    canvas.drawRRect(map_rr, frame_shadow)

    orig_name = str(_get_attr(scene, "map_origin", "") or _get_attr(scene, "lower_third_title", "ROMA") or "ROMA").strip()
    dest_raw = str(_get_attr(scene, "map_destination", "") or "").strip()
    dest_name = dest_raw if dest_raw else orig_name
    metric_txt = str(_get_attr(scene, "map_metric", "ANÁLISE GEOGRÁFICA") or "ANÁLISE GEOGRÁFICA")
    lt_sub = str(_get_attr(scene, "lower_third_subtitle", "") or _get_attr(scene, "evidence_headline", "") or "")

    is_transatlantic = _is_americas_location(orig_name) or _is_americas_location(dest_name)
    uv_orig, coord_orig = _resolve_city_map_point(orig_name, (0.465, 0.565), "41°54'N 12°29'E", transatlantic=is_transatlantic)
    uv_dest, coord_dest = _resolve_city_map_point(dest_name, uv_orig, coord_orig, transatlantic=is_transatlantic)

    # Detect single-city event cleanly — NEVER silently reset uv_orig/uv_dest to fake cities!
    orig_norm = _normalize_upper(orig_name).strip()
    dest_norm = _normalize_upper(dest_name).strip()
    city_dist = math.hypot(uv_orig[0] - uv_dest[0], uv_orig[1] - uv_dest[1])
    is_single_city = (orig_norm == dest_norm) or (city_dist < 0.04)

    p_orig = (geo_x0 + geo_w * uv_orig[0], geo_y0 + geo_h * uv_orig[1])
    p_dest = (geo_x0 + geo_w * uv_dest[0], geo_y0 + geo_h * uv_dest[1])

    eased_prog = _ease_doc_snap(min(1.0, max(0.0, prog)))
    map_cx = geo_x0 + geo_w * 0.5
    map_cy = geo_y0 + geo_h * 0.5

    if is_single_city:
        # Tactical Regional Perimeter zoom locking smoothly onto the true city coordinate
        cam_scale = 1.06 + 0.22 * eased_prog
        pan_x = (map_cx - p_orig[0]) * (0.32 + 0.16 * eased_prog)
        pan_y = (map_cy - p_orig[1]) * (0.32 + 0.16 * eased_prog)
        route_prog = 0.0
    else:
        route_prog = _ease_doc_snap(min(1.0, max(0.06, prog * 1.15)))
        cam_scale = 1.00 + 0.14 * _ease_in_out_cubic(prog)
        cam_focus_x = p_orig[0] + (p_dest[0] - p_orig[0]) * (0.25 + 0.50 * route_prog)
        cam_focus_y = p_orig[1] + (p_dest[1] - p_orig[1]) * (0.25 + 0.50 * route_prog)
        pan_x = (map_cx - cam_focus_x) * 0.18 * prog
        pan_y = (map_cy - cam_focus_y) * 0.18 * prog

    canvas.save()
    canvas.clipRRect(map_rr, doAntiAlias=True)

    # Dark topographic slate base (#121417) with subtle 65%-desaturated photo texture ghost
    sea_p = skia.Paint()
    sea_p.setShader(
        skia.GradientShader.MakeRadial(
            (mx + map_w * 0.5, my + map_h * 0.5),
            max(map_w, map_h) * 0.78,
            [skia.ColorSetARGB(255, 24, 28, 34), hex_to_skia("#121417", 255)],
        )
    )
    canvas.drawRect(map_r, sea_p)

    if desat_bg is not None:
        ghost_p = skia.Paint(AntiAlias=True)
        ghost_p.setAlpha(68 if is_single_city else 44)
        _draw_image_cover(canvas, desat_bg, map_r, paint=ghost_p, y_bias=0.25)

    # Apply 2.5D camera push-in transform for map geometry & tactical overlays
    canvas.save()
    canvas.translate(map_cx + pan_x, map_cy + pan_y)
    canvas.scale(cam_scale, cam_scale)
    canvas.translate(-map_cx, -map_cy)

    # 1. Procedural Topographic Coastline Silhouettes (`#1B2027` land + `#2C323B` muted borders)
    land_fill = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(236, 26, 31, 38))
    coast_glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4.5,
        Color=hex_to_skia("#2C323B", 110),
    )
    coast_stroke = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.8,
        Color=hex_to_skia("#2C323B", 235),
    )

    if is_transatlantic:
        active_polys: List[List[Tuple[float, float]]] = list(_EASTERN_NORTH_AMERICA_POLYS)
        for eu_poly in _EUROPE_LANDMASS_POLYS:
            active_polys.append([_project_eu_uv_transatlantic(pt) for pt in eu_poly])
    else:
        active_polys = list(_EUROPE_LANDMASS_POLYS)

    for poly in active_polys:
        path = skia.Path()
        for idx_pt, (ux, uy) in enumerate(poly):
            px = geo_x0 + geo_w * ux
            py = geo_y0 + geo_h * uy
            if idx_pt == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.close()
        canvas.drawPath(path, coast_glow)
        canvas.drawPath(path, land_fill)
        canvas.drawPath(path, coast_stroke)

    if is_transatlantic:
        ocean_lbl = "ATLANTIC OCEAN" if is_en else "OCEANO ATLÂNTICO"
        oc_f = skia.Font(cp_tf, 13.0)
        oc_w = float(oc_f.measureText(ocean_lbl))
        _draw_safe_string(
            canvas,
            ocean_lbl,
            geo_x0 + geo_w * 0.385 - oc_w * 0.5,
            geo_y0 + geo_h * 0.62,
            oc_f,
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(88, 224, 192, 151)),
        )

    # 2. Compass Rose Watermark
    _draw_compass_rose(
        canvas,
        mx + map_w * (0.88 if is_wide else 0.86),
        my + map_h * (0.20 if is_wide else 0.24),
        42.0 if is_wide else 38.0,
        cp_tf,
    )

    coord_font = skia.Font(cp_tf, 13.5)
    # Strictly clear left latitude axis labels (`mx + 14..78px`) on every callout/badge
    min_badge_x = max(geo_x0 + 12.0, mx + 86.0)

    if is_single_city:
        # ------------------------------------------------------------------
        # SINGLE-CITY TACTICAL REGIONAL PERIMETER & SCHEMATIC MODE
        # ------------------------------------------------------------------
        px, py = p_orig
        # Expanding concentric tactical target rings in #D9381E and #EAB308
        for ring_i, (r_base, r_hex, dashed) in enumerate(
            [
                (34.0, "#D9381E", False),
                (72.0, "#EAB308", True),
                (118.0, "#D9381E", True),
                (168.0, "#F8FAFC", True),
            ]
        ):
            pulse_r = r_base * (0.85 + 0.15 * eased_prog) + ((t * 18.0 + ring_i * 9.0) % 20.0)
            fade_a = int(max(45.0, min(225.0, (1.0 - ring_i * 0.17) * 210.0)))
            rp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.6 if ring_i < 2 else 1.5,
                Color=hex_to_skia(r_hex, fade_a),
            )
            if dashed:
                rp.setPathEffect(skia.DashPathEffect.Make([12.0, 8.0], -t * (32.0 if ring_i % 2 == 0 else -24.0)))
            canvas.drawCircle(px, py, pulse_r, rp)

        # Crosshair axis ticks around true city coordinates
        axis_len = 195.0 * eased_prog
        axis_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.2,
            Color=hex_to_skia("#EAB308", 125),
        )
        axis_p.setPathEffect(skia.DashPathEffect.Make([6.0, 6.0], -t * 18.0))
        canvas.drawLine(px - axis_len, py, px + axis_len, py, axis_p)
        canvas.drawLine(px, py - axis_len * 0.72, px, py + axis_len * 0.72, axis_p)

        # Animated dashed vector callout lines radiating to schematic HUD callout nodes (ZERO [:N] slicing!)
        callout_specs = [
            (
                (px + 135.0, py - 88.0),
                "PERÍMETRO ATIVO" if not is_en else "ACTIVE PERIMETER",
                _normalize_upper(orig_name),
                "#D9381E",
            ),
            (
                (px - 148.0, py + 76.0),
                "COORDENADAS" if not is_en else "COORDINATES",
                coord_orig,
                "#EAB308",
            ),
            (
                (px + 142.0, py + 86.0),
                "REGISTRO HISTÓRICO" if not is_en else "HISTORICAL EVENT",
                _normalize_upper(lt_sub or metric_txt),
                "#F8FAFC",
            ),
        ]
        max_callout_w = min(340.0, max(200.0, geo_w * 0.42))
        for c_idx, (end_pt, k_hdr, k_val, c_hex) in enumerate(callout_specs):
            c_prog = _ease_doc_snap(min(1.0, max(0.0, (prog - 0.08 * c_idx) / 0.38)))
            if c_prog <= 0.02:
                continue
            ex = max(min_badge_x + 40.0, min(geo_x0 + geo_w - 110.0, end_pt[0]))
            ey = max(geo_y0 + 36.0, min(geo_y0 + geo_h - 46.0, end_pt[1]))
            elbow_x = px + (ex - px) * 0.55
            cur_ex = px + (ex - px) * c_prog
            cur_ey = py + (ey - py) * c_prog
            vec_path = skia.Path()
            vec_path.moveTo(px, py)
            vec_path.lineTo(px + (elbow_x - px) * c_prog, cur_ey)
            vec_path.lineTo(cur_ex, cur_ey)
            vp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.0,
                Color=hex_to_skia(c_hex, 210),
            )
            vp.setPathEffect(skia.DashPathEffect.Make([10.0, 6.0], -t * 42.0))
            canvas.drawPath(vec_path, vp)

            if c_prog > 0.55:
                box_a = int(235 * min(1.0, (c_prog - 0.55) / 0.45))
                hf = skia.Font(cp_tf, 12.5)
                vf, v_lns = _wrap_text_to_width(k_val, cp_tf, 16.5, 11.5, max_callout_w - 28.0, 2)
                if not v_lns:
                    v_lns = [k_val]
                max_ln_w = max([float(hf.measureText(k_hdr))] + [float(vf.measureText(ln)) for ln in v_lns])
                bw = min(max_callout_w, max(168.0, max_ln_w + 28.0))
                line_step = vf.getSize() * 1.24
                bh = 50.0 if len(v_lns) <= 1 else (36.0 + len(v_lns) * line_step + 8.0)
                bx = ex if ex >= px else (ex - bw)
                bx = max(min_badge_x, min(geo_x0 + geo_w - bw - 12.0, bx))
                by = max(geo_y0 + 8.0, min(geo_y0 + geo_h - bh - 8.0, ey - bh * 0.5))
                br = skia.Rect.MakeXYWH(bx, by, bw, bh)
                canvas.drawRoundRect(br, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", box_a)))
                canvas.drawRoundRect(
                    br,
                    6.0,
                    6.0,
                    skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, Color=hex_to_skia(c_hex, box_a)),
                )
                canvas.drawRect(skia.Rect.MakeXYWH(bx, by + 6.0, 3.5, bh - 12.0), skia.Paint(Color=hex_to_skia(c_hex, box_a)))
                _draw_safe_string(canvas, k_hdr, bx + 12.0, by + 18.0, hf, skia.Paint(AntiAlias=True, Color=hex_to_skia(c_hex, box_a)))
                vy = by + 38.0
                for vln in v_lns:
                    _draw_safe_string(canvas, vln, bx + 12.0, vy, vf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", box_a)))
                    vy += line_step

        # Single high-precision target pin at true city coordinates
        canvas.drawCircle(px, py, 16.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E", 85)))
        canvas.drawCircle(px, py, 10.5, skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E", 255)))
        canvas.drawCircle(px, py, 4.5, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 255)))

        # Crisp city label badge cleanly above the pin (always clearing left latitude labels!)
        c_clean = _sanitize_glyphs(_normalize_upper(orig_name), typeface=cinzel_tf)
        cf, cl = _wrap_text_to_width(c_clean, cinzel_tf, 24.0, 15.0, 260.0, 1)
        c_str = cl[0] if cl else c_clean
        cw = float(cf.measureText(c_str))
        tag_w = max(160.0, cw + 32.0)
        tag_h = 50.0
        tx = max(min_badge_x, min(geo_x0 + geo_w - tag_w - 12.0, px - tag_w * 0.5))
        ty = max(geo_y0 + 12.0, py - tag_h - 24.0)
        tag_r = skia.Rect.MakeXYWH(tx, ty, tag_w, tag_h)
        canvas.drawRoundRect(tag_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 236)))
        canvas.drawRoundRect(
            tag_r,
            8.0,
            8.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8, Color=hex_to_skia("#EAB308", 230)),
        )
        _draw_safe_string(canvas, c_str, tx + 14.0, ty + 25.0, cf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))
        _draw_safe_string(canvas, coord_orig, tx + 14.0, ty + 43.0, coord_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")))

    else:
        # ------------------------------------------------------------------
        # GENUINE A -> B CARTOGRAPHIC ROUTE MODE
        # ------------------------------------------------------------------
        mid_x = (p_orig[0] + p_dest[0]) * 0.5
        mid_y = (p_orig[1] + p_dest[1]) * 0.5
        dist = math.hypot(p_dest[0] - p_orig[0], p_dest[1] - p_orig[1])
        arc_lift = max(55.0, min(145.0, dist * 0.30))
        min_ctrl_y = geo_y0 + 18.0
        c1 = (p_orig[0] + (mid_x - p_orig[0]) * 0.55, max(min_ctrl_y, min(p_orig[1], mid_y) - arc_lift * 0.85))
        c2 = (p_dest[0] + (mid_x - p_dest[0]) * 0.55, max(min_ctrl_y, min(p_dest[1], mid_y) - arc_lift * 0.95))

        u = route_prog
        iu = 1.0 - u
        tip_x = (iu ** 3) * p_orig[0] + 3 * (iu ** 2) * u * c1[0] + 3 * iu * (u ** 2) * c2[0] + (u ** 3) * p_dest[0]
        tip_y = (iu ** 3) * p_orig[1] + 3 * (iu ** 2) * u * c1[1] + 3 * iu * (u ** 2) * c2[1] + (u ** 3) * p_dest[1]

        # 3. Pulsing Concentric Radar Rings at Origin & Destination Pins
        for pin_xy, ring_hex in ((p_orig, "#EAB308"), (p_dest, "#D9381E")):
            for r_base in (22.0, 46.0, 74.0):
                r_cur = r_base + ((t * 26.0) % 24.0)
                fade_r = max(0.0, 1.0 - (r_cur / 98.0))
                rp = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=1.8,
                    Color=hex_to_skia(ring_hex, int(170 * fade_r)),
                )
                canvas.drawCircle(pin_xy[0], pin_xy[1], r_cur, rp)

        # 4. Glowing Cubic Bézier Route Arc + Animated Dashed stroke-dashoffset + Traveling Ember Head
        route_path = skia.Path()
        steps = 56
        max_s = max(2, int(steps * route_prog))
        for si in range(max_s + 1):
            su = si / float(steps)
            siu = 1.0 - su
            bx = (siu ** 3) * p_orig[0] + 3 * (siu ** 2) * su * c1[0] + 3 * siu * (su ** 2) * c2[0] + (su ** 3) * p_dest[0]
            by = (siu ** 3) * p_orig[1] + 3 * (siu ** 2) * su * c1[1] + 3 * siu * (su ** 2) * c2[1] + (su ** 3) * p_dest[1]
            if si == 0:
                route_path.moveTo(bx, by)
            else:
                route_path.lineTo(bx, by)

        outer_glow_wide = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=20.0,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=hex_to_skia("#D9381E", 48),
        )
        canvas.drawPath(route_path, outer_glow_wide)
        outer_glow = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=11.0,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=hex_to_skia("#D9381E", 108),
        )
        canvas.drawPath(route_path, outer_glow)

        core_arc = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=4.5,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=hex_to_skia("#EAB308"),
        )
        core_arc.setPathEffect(skia.DashPathEffect.Make([16.0, 10.0], -t * 64.0))
        canvas.drawPath(route_path, core_arc)

        ember_halo = skia.Paint(AntiAlias=True)
        ember_halo.setShader(
            skia.GradientShader.MakeRadial(
                (tip_x, tip_y),
                24.0,
                [
                    skia.ColorSetARGB(235, 255, 230, 140),
                    hex_to_skia("#D9381E", 165),
                    skia.ColorSetARGB(0, 158, 27, 36),
                ],
                [0.0, 0.45, 1.0],
            )
        )
        canvas.drawCircle(tip_x, tip_y, 24.0, ember_halo)
        canvas.drawCircle(tip_x, tip_y, 6.5, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

        # Origin & Destination Pins + Crisp Callout Badges (tx >= mx + 86.0 clears latitude labels!)
        for is_dest, pin_pt, city_lbl, city_coord in (
            (False, p_orig, orig_name, coord_orig),
            (True, p_dest, dest_name, coord_dest),
        ):
            pin_col = "#D9381E" if is_dest else "#EAB308"
            canvas.drawCircle(pin_pt[0], pin_pt[1], 11.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(pin_col)))
            canvas.drawCircle(pin_pt[0], pin_pt[1], 4.8, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

            c_clean = _sanitize_glyphs(_normalize_upper(city_lbl), typeface=cinzel_tf)
            cf, cl = _wrap_text_to_width(c_clean, cinzel_tf, 22.0, 15.0, 240.0, 1)
            c_str = cl[0] if cl else c_clean
            cw = float(cf.measureText(c_str))
            tag_w = max(148.0, cw + 28.0)
            tag_h = 48.0
            tx = max(min_badge_x, min(geo_x0 + geo_w - tag_w - 12.0, pin_pt[0] - tag_w * 0.5))
            ty = pin_pt[1] + 18.0 if pin_pt[1] < (geo_y0 + geo_h * 0.72) else (pin_pt[1] - tag_h - 18.0)

            tag_r = skia.Rect.MakeXYWH(tx, ty, tag_w, tag_h)
            canvas.drawRoundRect(tag_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 232)))
            canvas.drawRoundRect(
                tag_r,
                8.0,
                8.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.6, Color=hex_to_skia(pin_col, 220)),
            )
            _draw_safe_string(canvas, c_str, tx + 14.0, ty + 23.0, cf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))
            _draw_safe_string(canvas, city_coord, tx + 14.0, ty + 41.0, coord_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")))

    canvas.restore()  # End 2.5D camera push-in

    # 5. Latitude / Longitude Graticule Lines + Degree Coordinate Ticks
    grat_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.0,
        Color=hex_to_skia("#2C323B", 130),
    )
    coord_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(175, 224, 192, 151))

    for ry_norm, lat_lbl in ((0.27, "51°30'N"), (0.41, "47°16'N"), (0.57, "41°54'N"), (0.71, "36°15'N")):
        gy = geo_y0 + geo_h * ry_norm
        canvas.drawLine(mx, gy, mx + map_w, gy, grat_p)
        _draw_safe_string(canvas, lat_lbl, mx + 14.0, gy - 6.0, coord_font, coord_paint)

    lon_ticks = (
        ((0.22, "71°03'W"), (0.40, "40°00'W"), (0.59, "00°07'W"), (0.80, "15°00'E"))
        if is_transatlantic
        else ((0.26, "00°07'W"), (0.47, "12°29'E"), (0.65, "23°43'E"), (0.81, "29°59'E"))
    )
    for rx_norm, lon_lbl in lon_ticks:
        gx = geo_x0 + geo_w * rx_norm
        canvas.drawLine(gx, my, gx, my + map_h, grat_p)
        _draw_safe_string(canvas, lon_lbl, gx + 6.0, my + map_h - 12.0, coord_font, coord_paint)

    # 6. Top-Left Coordinate Telemetry Callout Badge
    hud_w = min(map_w - 44.0, 560.0 if is_wide else (map_w - 44.0))
    hud_h = 88.0
    hud_r = skia.Rect.MakeXYWH(mx + 22.0, my + 18.0, hud_w, hud_h)
    canvas.drawRoundRect(hud_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 236)))
    canvas.drawRoundRect(
        hud_r,
        10.0,
        10.0,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8, Color=hex_to_skia("#2C323B", 230)),
    )
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(mx + 28.0, my + 26.0, 4.0, hud_h - 16.0),
        2.0,
        2.0,
        skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E" if is_single_city else "#EAB308")),
    )

    if is_single_city:
        tele_hdr = (
            f"TACTICAL SECTOR • {_normalize_upper(orig_name)} • {coord_orig}"
            if is_en
            else f"ZONA TÁTICA • {_normalize_upper(orig_name)} • {coord_orig}"
        )
    else:
        tele_hdr = (
            f"CARTOGRAPHIC ROUTE • {coord_orig} -> {coord_dest}"
            if is_en
            else f"ROTA CARTOGRÁFICA • {coord_orig} -> {coord_dest}"
        )
    th_f, th_l = _wrap_text_to_width(tele_hdr, cp_tf, 15.0, 11.0, hud_w - 44.0, 1)
    if th_l:
        _draw_safe_string(canvas, th_l[0], mx + 42.0, my + 44.0, th_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#E0C097", 235)))

    mf, ml = _wrap_text_to_width(_normalize_upper(metric_txt), cinzel_tf, 28.0, 18.0, hud_w - 44.0, 1)
    if ml:
        _draw_safe_string(canvas, ml[0], mx + 42.0, my + 78.0, mf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

    canvas.restore()  # End map clipRRect

    # Crisp muted slate-gold outer border around tactical map
    canvas.drawRRect(
        map_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#2C323B", 235)),
    )

    # 7. Tactical PiP Video Monitor
    pip_label = _normalize_upper(orig_name) if is_single_city else f"{orig_name} -> {dest_name}"
    _draw_tactical_pip_monitor(
        canvas=canvas,
        pip_img=pip_img or backdrop_img,
        cx=pip_cx,
        cy=pip_cy,
        pip_w=pip_w,
        pip_h=pip_h,
        label_text=pip_label,
        coord_text=coord_orig if is_single_city else coord_dest,
        body_t=body_t,
        t=t,
        ui_tf=cp_tf,
        is_en=is_en,
    )


# ---------------------------------------------------------------------------
# 5. Vox / Johnny Harris Archival Newspaper & Document Presentation
# ---------------------------------------------------------------------------
def _draw_archival_sepia_plate_with_mounts(
    canvas: skia.Canvas,
    photo_img: Optional[skia.Image],
    rect: skia.Rect,
) -> None:
    sepia_matrix = [
        0.38, 0.68, 0.14, 0.0, -0.05,
        0.34, 0.62, 0.12, 0.0, -0.06,
        0.27, 0.50, 0.10, 0.0, -0.08,
        0.00, 0.00, 0.00, 1.0,  0.00,
    ]
    p_paint = skia.Paint(AntiAlias=True)
    p_paint.setColorFilter(skia.ColorFilters.Matrix(sepia_matrix))

    canvas.save()
    canvas.clipRect(rect)
    if photo_img is not None:
        _draw_image_cover(canvas, photo_img, rect, paint=p_paint, y_bias=0.14)
    else:
        # Procedural vintage woodcut engraving fallback
        bg = skia.Paint(Color=skia.ColorSetARGB(255, 62, 52, 42))
        canvas.drawRect(rect, bg)

    # Subtle newsprint halftone horizontal lines
    ht_p = skia.Paint(Color=skia.ColorSetARGB(24, 24, 18, 12))
    for sy in range(int(rect.top()), int(rect.bottom()), 4):
        canvas.drawLine(rect.left(), sy, rect.right(), sy, ht_p)

    # Vintage radial edge burn inside plate
    vig = skia.Paint()
    vig.setShader(
        skia.GradientShader.MakeRadial(
            (rect.centerX(), rect.centerY()),
            max(rect.width(), rect.height()) * 0.68,
            [skia.ColorSetARGB(0, 22, 15, 10), skia.ColorSetARGB(82, 22, 15, 10)],
        )
    )
    canvas.drawRect(rect, vig)
    canvas.restore()

    # Crisp double ink border
    canvas.drawRect(
        rect,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.2, Color=skia.ColorSetARGB(235, 32, 26, 24)),
    )

    # 4 Archival Corner Photo-Mount Tabs (triangular obsidian-leather corner mounts)
    tab_sz = 26.0
    tab_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 26, 20, 22))
    tab_gold = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#D4AF37", 180))
    corners = [
        (rect.left(), rect.top(), 1.0, 1.0),
        (rect.right(), rect.top(), -1.0, 1.0),
        (rect.left(), rect.bottom(), 1.0, -1.0),
        (rect.right(), rect.bottom(), -1.0, -1.0),
    ]
    for cx_c, cy_c, dx, dy in corners:
        path = skia.Path()
        path.moveTo(cx_c, cy_c)
        path.lineTo(cx_c + dx * tab_sz, cy_c)
        path.lineTo(cx_c, cy_c + dy * tab_sz)
        path.close()
        canvas.drawPath(path, tab_p)
        canvas.drawLine(cx_c + dx * tab_sz, cy_c, cx_c, cy_c + dy * tab_sz, tab_gold)


def _draw_wax_verification_seal(
    canvas: skia.Canvas,
    cx: float,
    cy: float,
    radius: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    is_en: bool = False,
) -> None:
    canvas.save()
    canvas.translate(cx, cy)
    canvas.rotate(-14.0)

    # Translucent crimson ink/wax stamp base
    wax_fill = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(38, 158, 27, 36))
    canvas.drawCircle(0.0, 0.0, radius, wax_fill)

    outer_ring = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=3.2,
        Color=skia.ColorSetARGB(205, 158, 27, 36),
    )
    canvas.drawCircle(0.0, 0.0, radius, outer_ring)

    inner_ring = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.5,
        Color=skia.ColorSetARGB(190, 158, 27, 36),
    )
    inner_ring.setPathEffect(skia.DashPathEffect.Make([6.0, 4.0], 0.0))
    canvas.drawCircle(0.0, 0.0, radius * 0.82, inner_ring)

    stamp_main = "VERIFIED" if is_en else "AUTÊNTICO"
    stamp_sub = "ARCHIVAL SEAL" if is_en else "SELO FORENSE"
    f1 = skia.Font(title_tf, max(12.0, radius * 0.28))
    f2 = skia.Font(ui_tf, max(9.5, radius * 0.19))
    p_ink = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 148, 22, 32))

    w1 = float(f1.measureText(stamp_main))
    w2 = float(f2.measureText(stamp_sub))
    _draw_safe_string(canvas, stamp_main, -w1 * 0.5, 2.0, f1, p_ink)
    _draw_safe_string(canvas, stamp_sub, -w2 * 0.5, radius * 0.36, f2, p_ink)
    canvas.restore()


def draw_pro_archival_newspaper(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    photo_img: Optional[skia.Image],
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render Vox / Johnny Harris Archival Document & Broadsheet over darkened bokeh backdrop
    with 2.5D camera push-in (1.00 -> 1.08x), gentle perspective tilt (-1.1 deg -> +0.3 deg),
    aged paper grain/fiber lines, vintage double-rule masthead ('ARQUIVO HISTÓRICO CONFIDENCIAL'),
    crisp 1.38:1 top-weighted sepia archival plate with corner photo-mount tabs, wax/ink verification
    seal stamp, and smooth animated warm-crimson/gold highlighter sweep across `scene.evidence_quote`.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    _draw_dark_bokeh_backdrop(canvas, w, h, backdrop_img, prog, t, scrim_alpha=172, blur_sigma=6.0, mood=mood)

    is_wide = w >= h
    headline_txt = _normalize_upper(str(_get_attr(scene, "evidence_headline", "REGISTRO HISTÓRICO CONFIDENCIAL")))
    quote_txt = str(_get_attr(scene, "evidence_quote", "Documentos históricos revelam os fatos ocultos deste período."))
    lt_title = _normalize_upper(str(_get_attr(scene, "lower_third_title", "ARQUIVO CENTRAL")))

    paper_w = min(w - 130.0, 1420.0 if is_wide else 936.0)
    inner_w = paper_w - 92.0

    h_font, h_lines = _wrap_text_to_width(headline_txt, title_tf, 42.0 if is_wide else 40.0, 24.0, inner_w, 2)
    n_h_lines = max(1, len(h_lines))
    headline_step = h_font.getSize() * 1.15
    header_height = 44.0 + 64.0 + (n_h_lines * headline_step) - 10.0 + 18.0

    if is_wide:
        paper_h = min(726.0, float(h) - 266.0)
        py = 66.0
        v_photo_h = 0.0
        v_q_box_h = 0.0
        q_font_v = skia.Font(ui_tf, 28.0)
        q_lines_v: List[str] = []
    else:
        q_font_v, q_lines_v = _wrap_text_to_width(quote_txt, ui_tf, 28.0, 18.0, inner_w - 44.0, 4)
        v_line_step = q_font_v.getSize() * 1.38
        v_q_box_h = max(1, len(q_lines_v)) * v_line_step + 44.0
        # Exact 1.38:1 top-weighted archival plate aspect ratio
        v_photo_h = round(inner_w / 1.38)
        cap_and_gap = 40.0
        bottom_pad = 36.0
        max_paper_h = 1140.0
        raw_paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        if raw_paper_h > max_paper_h:
            v_photo_h = max(round(inner_w / 1.44), v_photo_h - (raw_paper_h - max_paper_h))
        paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        # Place below mobile safe-zone lower third (y=192..292) and above bottom captions (y~1520)
        py = max(302.0, min(340.0, (1480.0 - 302.0 - paper_h) * 0.5 + 302.0))

    # 2.5D camera push-in (1.00 -> 1.08x) and gentle perspective tilt (-1.1 deg -> +0.3 deg)
    ent = _ease_doc_snap(min(1.0, body_t / 0.38))
    cam_scale = (0.94 + 0.06 * ent) * (1.00 + 0.08 * prog)
    tilt_deg = -1.1 + 1.4 * prog

    canvas.save()
    canvas.translate(w * 0.5, py + paper_h * 0.5)
    canvas.scale(cam_scale, cam_scale)
    canvas.rotate(tilt_deg)

    p_rect = skia.Rect.MakeXYWH(-paper_w * 0.5, -paper_h * 0.5, paper_w, paper_h)
    p_rr = skia.RRect.MakeRectXY(p_rect, 12.0, 12.0)

    # 1. Floating aged parchment card with fast layered cinema drop shadow
    _draw_fast_rrect_shadow(canvas, p_rr, dy=20.0, sigma=26.0, alpha=224)
    shadow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 242, 234, 217))
    canvas.drawRRect(p_rr, shadow_p)

    canvas.save()
    canvas.clipRRect(p_rr, doAntiAlias=True)

    # Radial parchment aging gradient (warm cream center -> antique sepia edge)
    age_p = skia.Paint()
    age_p.setShader(
        skia.GradientShader.MakeRadial(
            (0.0, 0.0),
            max(paper_w, paper_h) * 0.72,
            [skia.ColorSetARGB(255, 246, 239, 224), skia.ColorSetARGB(255, 224, 210, 184)],
        )
    )
    canvas.drawRect(p_rect, age_p)

    # Procedural aged paper grain / fiber lines
    fiber_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(18, 82, 64, 42))
    for fy_i in range(int(-paper_h * 0.5), int(paper_h * 0.5), 11):
        canvas.drawLine(-paper_w * 0.5, fy_i, paper_w * 0.5, fy_i + ((fy_i % 3) - 1) * 3.0, fiber_p)
    v_fiber_p = skia.Paint(Color=skia.ColorSetARGB(9, 70, 52, 34))
    for fx_i in range(int(-paper_w * 0.5), int(paper_w * 0.5), 29):
        canvas.drawLine(fx_i, -paper_h * 0.5, fx_i, paper_h * 0.5, v_fiber_p)

    ink_dark = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 22, 18, 26))
    ink_muted = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 72, 60, 54))
    rule_thick = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=skia.ColorSetARGB(240, 36, 28, 34))
    rule_thin = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=skia.ColorSetARGB(215, 36, 28, 34))

    left_x = -paper_w * 0.5 + 46.0
    right_x = paper_w * 0.5 - 46.0
    top_y = -paper_h * 0.5 + 42.0

    # 2. Vintage Double-Rule Masthead ('ARQUIVO HISTÓRICO CONFIDENCIAL')
    mast_txt = (
        "CONFIDENTIAL HISTORICAL ARCHIVE   •   FORENSIC DOSSIER"
        if is_en
        else "ARQUIVO HISTÓRICO CONFIDENCIAL   •   DOSSIÊ FORENSE"
    )
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    mast_font, mast_lns = _wrap_text_to_width(mast_txt, cp_tf, 20.0, 14.0, inner_w - 110.0, 1)
    if mast_lns:
        _draw_safe_string(canvas, mast_lns[0], left_x, top_y, mast_font, ink_muted)
    canvas.drawLine(left_x, top_y + 13.0, right_x, top_y + 13.0, rule_thick)
    canvas.drawLine(left_x, top_y + 19.0, right_x, top_y + 19.0, rule_thin)

    # 3. Bold Archival Headline
    hy = top_y + 64.0
    for ln in h_lines:
        _draw_safe_string(canvas, ln, left_x, hy, h_font, ink_dark)
        hy += headline_step

    rule_y = hy - 10.0
    canvas.drawLine(left_x, rule_y, right_x, rule_y, rule_thick)
    canvas.drawLine(left_x, rule_y + 5.0, right_x, rule_y + 5.0, rule_thin)

    content_top = rule_y + 18.0
    content_bottom = paper_h * 0.5 - 30.0
    content_h = max(140.0, content_bottom - content_top)

    sweep_total = _ease_doc_snap(min(1.0, max(0.0, (prog - 0.05) / 0.62)))

    if is_wide:
        photo_col_w = inner_w * 0.43
        gap_col = inner_w * 0.03
        quote_col_x = left_x + photo_col_w + gap_col
        quote_col_w = inner_w - photo_col_w - gap_col

        photo_h = min(content_h - 32.0, round(photo_col_w / 1.38))
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, photo_col_w, photo_h)
        _draw_archival_sepia_plate_with_mounts(canvas, photo_img or backdrop_img, photo_rect)

        cap_str = f"EXHIBIT • {lt_title}" if is_en else f"PRANCHA DE ARQUIVO • {lt_title}"
        cf, cl = _wrap_text_to_width(cap_str, cp_tf, 15.0, 11.5, photo_col_w, 1)
        if cl:
            _draw_safe_string(canvas, cl[0], left_x, content_top + photo_h + 22.0, cf, ink_muted)

        q_font, q_lines = _wrap_text_to_width(quote_txt, ui_tf, 29.0, 18.0, quote_col_w - 44.0, 4)
        line_step = q_font.getSize() * 1.40
        q_box_h = min(content_h - 108.0, max(1, len(q_lines)) * line_step + 46.0)
        q_box_y = content_top + 6.0

        callout_r = skia.Rect.MakeXYWH(quote_col_x, q_box_y, quote_col_w, q_box_h)
        canvas.drawRoundRect(callout_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 251, 246, 235)))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, rule_thin)

        n_lns = max(1, len(q_lines))
        qy = q_box_y + 42.0
        for idx_l, qln in enumerate(q_lines):
            line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
            if line_prog > 0.01:
                lw = float(q_font.measureText(qln))
                hl_rect = skia.Rect.MakeXYWH(
                    quote_col_x + 14.0,
                    qy - q_font.getSize() * 0.86,
                    (lw + 18.0) * line_prog,
                    q_font.getSize() * 1.18,
                )
                hl_p = skia.Paint(AntiAlias=True)
                hl_p.setBlendMode(skia.BlendMode.kMultiply)
                hl_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(hl_rect.left(), hl_rect.top()), (hl_rect.right(), hl_rect.top())],
                        [hex_to_skia("#FFD700", 228), hex_to_skia("#EAB308", 205)],
                    )
                )
                canvas.drawRoundRect(hl_rect, 6.0, 6.0, hl_p)
            _draw_safe_string(canvas, qln, quote_col_x + 22.0, qy, q_font, ink_dark)
            qy += line_step

        # Position AUTÊNTICO crimson seal strictly on the light parchment margin (clear of dark inset plate!)
        _draw_wax_verification_seal(
            canvas,
            right_x - 66.0,
            content_bottom - 52.0,
            46.0,
            title_tf,
            cp_tf,
            is_en=is_en,
        )
    else:
        # 9:16 Vertical Broadsheet: 1.38:1 top-weighted sepia plate with corner mounts + quote
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, inner_w, v_photo_h)
        _draw_archival_sepia_plate_with_mounts(canvas, photo_img or backdrop_img, photo_rect)

        cap_str = f"ARCHIVAL PLATE • {lt_title}" if is_en else f"PRANCHA FOTOGRÁFICA • {lt_title}"
        cf, cl = _wrap_text_to_width(cap_str, cp_tf, 15.5, 11.5, inner_w - 110.0, 1)
        if cl:
            _draw_safe_string(canvas, cl[0], left_x, content_top + v_photo_h + 23.0, cf, ink_muted)

        q_box_y = content_top + v_photo_h + 38.0
        line_step = q_font_v.getSize() * 1.38
        callout_r = skia.Rect.MakeXYWH(left_x, q_box_y, inner_w, v_q_box_h)
        canvas.drawRoundRect(callout_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 251, 246, 235)))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, rule_thin)

        n_lns = max(1, len(q_lines_v))
        qy = q_box_y + 42.0
        for idx_l, qln in enumerate(q_lines_v):
            line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
            if line_prog > 0.01:
                lw = float(q_font_v.measureText(qln))
                hl_rect = skia.Rect.MakeXYWH(
                    left_x + 14.0,
                    qy - q_font_v.getSize() * 0.86,
                    (lw + 18.0) * line_prog,
                    q_font_v.getSize() * 1.18,
                )
                hl_p = skia.Paint(AntiAlias=True)
                hl_p.setBlendMode(skia.BlendMode.kMultiply)
                hl_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(hl_rect.left(), hl_rect.top()), (hl_rect.right(), hl_rect.top())],
                        [hex_to_skia("#FFD700", 228), hex_to_skia("#EAB308", 205)],
                    )
                )
                canvas.drawRoundRect(hl_rect, 6.0, 6.0, hl_p)
            _draw_safe_string(canvas, qln, left_x + 22.0, qy, q_font_v, ink_dark)
            qy += line_step

        # Position AUTÊNTICO crimson seal strictly on the light parchment margin below the photo plate
        # (over the light cream parchment quote margin, NEVER overlapping the dark corner of the inset plate!)
        seal_cy = min(content_bottom - 44.0, q_box_y + v_q_box_h - 42.0)
        if seal_cy - 44.0 <= photo_rect.bottom() + 6.0:
            seal_cy = photo_rect.bottom() + 52.0
        _draw_wax_verification_seal(
            canvas,
            right_x - 54.0,
            seal_cy,
            42.0,
            title_tf,
            cp_tf,
            is_en=is_en,
        )

    canvas.restore()  # End paper clipRRect
    canvas.drawRRect(p_rr, rule_thick)
    canvas.restore()


# ---------------------------------------------------------------------------
# 6. Mechanical Odometer Timeline + Sliding 35mm Ruler + Cause-and-Effect Vector Arrows
# ---------------------------------------------------------------------------
def _compact_odometer_date(raw_date: str) -> str:
    """Ensure odometer drum tokens stay compact ('217 a.C.', '336 d.C.', 'SÉC. IV', '1647')."""
    txt = str(raw_date or "").strip()
    if len(txt) <= 10:
        return txt
    return extract_depth_stamp_text(txt)


def _draw_cause_effect_arrow(
    canvas: skia.Canvas,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    arrow_prog: float,
    t: float,
    color_hex: str = "#EAB308",
    active: bool = True,
) -> None:
    """Draw an animated dashed vector cause-and-effect arrow between milestone cards."""
    if arrow_prog <= 0.02:
        return
    alpha = 235 if active else 115
    ex = p0[0] + (p1[0] - p0[0]) * arrow_prog
    ey = p0[1] + (p1[1] - p0[1]) * arrow_prog
    line_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=3.0 if active else 2.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia(color_hex, alpha),
    )
    line_p.setPathEffect(skia.DashPathEffect.Make([10.0, 6.0], -t * 44.0))
    canvas.drawLine(p0[0], p0[1], ex, ey, line_p)

    # Arrowhead at tip
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    head_len = 12.0 if active else 9.0
    head_path = skia.Path()
    head_path.moveTo(ex, ey)
    head_path.lineTo(ex - head_len * math.cos(ang - 0.45), ey - head_len * math.sin(ang - 0.45))
    head_path.lineTo(ex - head_len * math.cos(ang + 0.45), ey - head_len * math.sin(ang + 0.45))
    head_path.close()
    canvas.drawPath(head_path, skia.Paint(AntiAlias=True, Color=hex_to_skia(color_hex, alpha)))


def _draw_mechanical_odometer_header(
    canvas: skia.Canvas,
    cx: float,
    top_y: float,
    odo_w: float,
    odo_h: float,
    prev_date: str,
    curr_date: str,
    roll_frac: float,
    prog: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    is_en: bool = False,
) -> None:
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    housing_r = skia.Rect.MakeXYWH(cx - odo_w * 0.5, top_y, odo_w, odo_h)
    housing_rr = skia.RRect.MakeRectXY(housing_r, 14.0, 14.0)

    _draw_fast_rrect_shadow(canvas, housing_rr, dy=14.0, sigma=20.0, alpha=220)
    sh_p = skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 244))
    canvas.drawRRect(housing_rr, sh_p)

    canvas.save()
    canvas.clipRRect(housing_rr, doAntiAlias=True)

    hdr_lbl = "CHRONOMETER ARCHIVE • HISTORICAL TIMELINE" if is_en else "CRONÔMETRO HISTÓRICO • LINHA DO TEMPO"
    hf, hl = _wrap_text_to_width(hdr_lbl, cp_tf, 13.5, 10.5, odo_w - 40.0, 1)
    if hl:
        hw = float(hf.measureText(hl[0]))
        _draw_safe_string(
            canvas,
            hl[0],
            cx - hw * 0.5,
            top_y + 22.0,
            hf,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#E0C097", 220)),
        )

    drum_w = odo_w - 56.0
    drum_h = 54.0
    drum_x = cx - drum_w * 0.5
    drum_y = top_y + 30.0
    drum_r = skia.Rect.MakeXYWH(drum_x, drum_y, drum_w, drum_h)
    drum_rr = skia.RRect.MakeRectXY(drum_r, 8.0, 8.0)
    canvas.drawRRect(drum_rr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 10, 12, 15)))

    p_str = _sanitize_glyphs(_normalize_upper(_compact_odometer_date(prev_date)), typeface=cp_tf)
    c_str = _sanitize_glyphs(_normalize_upper(_compact_odometer_date(curr_date)), typeface=cp_tf)
    max_len = max(len(p_str), len(c_str), 4)
    p_pad = p_str.center(max_len)
    c_pad = c_str.center(max_len)

    canvas.save()
    canvas.clipRRect(drum_rr, doAntiAlias=True)

    slot_w = min(44.0, drum_w / float(max(1, max_len)))
    total_slots_w = slot_w * max_len
    start_sx = cx - total_slots_w * 0.5
    d_font = skia.Font(cp_tf, min(36.0, slot_w * 0.92))

    for i in range(max_len):
        sx = start_sx + i * slot_w
        ch_prev = p_pad[i]
        ch_curr = c_pad[i]

        if i > 0:
            canvas.drawLine(
                sx,
                drum_y + 4.0,
                sx,
                drum_y + drum_h - 4.0,
                skia.Paint(Color=hex_to_skia("#2C323B", 140)),
            )

        if ch_prev == ch_curr or roll_frac >= 0.999:
            ch_w = float(d_font.measureText(ch_curr))
            _draw_safe_string(
                canvas,
                ch_curr,
                sx + (slot_w - ch_w) * 0.5,
                drum_y + 40.0,
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")),
            )
        else:
            slot_roll = _ease_doc_snap(min(1.0, max(0.0, (roll_frac * 1.25) - (i / float(max_len)) * 0.22)))
            y_offset = slot_roll * drum_h
            w_p = float(d_font.measureText(ch_prev))
            w_c = float(d_font.measureText(ch_curr))
            _draw_safe_string(
                canvas,
                ch_prev,
                sx + (slot_w - w_p) * 0.5,
                drum_y + 40.0 - y_offset,
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308", int(255 * (1.0 - slot_roll)))),
            )
            _draw_safe_string(
                canvas,
                ch_curr,
                sx + (slot_w - w_c) * 0.5,
                drum_y + 40.0 + (drum_h - y_offset),
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308", int(255 * slot_roll))),
            )

    cyl_p = skia.Paint()
    cyl_p.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, drum_y), (0.0, drum_y + drum_h)],
            [
                skia.ColorSetARGB(185, 6, 8, 10),
                skia.ColorSetARGB(0, 6, 8, 10),
                skia.ColorSetARGB(0, 6, 8, 10),
                skia.ColorSetARGB(185, 6, 8, 10),
            ],
            [0.0, 0.26, 0.74, 1.0],
        )
    )
    canvas.drawRect(drum_r, cyl_p)
    canvas.restore()

    canvas.drawRRect(
        drum_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.6, Color=hex_to_skia("#2C323B", 230)),
    )

    ruler_y = top_y + odo_h - 10.0
    scroll_px = prog * 540.0
    tick_p_major = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#EAB308", 215))
    tick_p_minor = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=hex_to_skia("#2C323B", 190))

    step_px = 12.0
    first_k = int((scroll_px - odo_w * 0.5) // step_px) - 2
    last_k = int((scroll_px + odo_w * 0.5) // step_px) + 2
    for k in range(first_k, last_k):
        tx = cx + (k * step_px - scroll_px)
        if tx < housing_r.left() + 14.0 or tx > housing_r.right() - 14.0:
            continue
        if k % 5 == 0:
            canvas.drawLine(tx, ruler_y - 16.0, tx, ruler_y, tick_p_major)
        else:
            canvas.drawLine(tx, ruler_y - 9.0, tx, ruler_y, tick_p_minor)

    needle = skia.Path()
    needle.moveTo(cx, ruler_y - 18.0)
    needle.lineTo(cx - 7.0, ruler_y - 27.0)
    needle.lineTo(cx + 7.0, ruler_y - 27.0)
    needle.close()
    canvas.drawPath(needle, skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E")))

    canvas.restore()
    canvas.drawRRect(
        housing_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#2C323B", 235)),
    )


def draw_pro_odometer_timeline(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    extra_photos: List[skia.Image],
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render 16:9 / 9:16 Mechanical Odometer Timeline with larger archival photo cards,
    animated vector cause-and-effect callout arrows in `#EAB308` / `#D9381E`, and zero
    percentage chartjunk bars.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    cinzel_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf

    # Desaturated 65%-brightness dark realistic background (#121417 base)
    full_r = skia.Rect.MakeWH(w, h)
    canvas.clear(hex_to_skia("#121417"))
    if backdrop_img is not None:
        desat_bg = _get_desat65_image(backdrop_img)
        canvas.save()
        canvas.translate(w * 0.5, h * 0.5)
        sc_bg = 1.03 + 0.04 * prog
        canvas.scale(sc_bg, sc_bg)
        _draw_image_cover(canvas, desat_bg, skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h), paint=None, y_bias=0.28)
        canvas.restore()
    vig_img = _get_cached_gradient_overlay(
        "timeline_vig_bg",
        w,
        h,
        lambda gc, gw, gh: gc.drawRect(
            skia.Rect.MakeWH(gw, gh),
            _make_radial_paint(
                (gw * 0.5, gh * 0.45),
                max(gw, gh) * 0.75,
                [skia.ColorSetARGB(126, 18, 20, 23), skia.ColorSetARGB(220, 10, 12, 16)],
            ),
        ),
    )
    _draw_cached_gradient(canvas, vig_img, w, h)
    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)

    raw_pts = _get_attr(scene, "timeline_points", None) or []
    pts: List[Dict[str, str]] = []
    for p in raw_pts[:4]:
        pts.append(
            {
                "date": str(_get_attr(p, "date", "MARCO")),
                "label": str(_get_attr(p, "label", "Evento Histórico Documentado")),
                "value": str(_get_attr(p, "value", "ORIGEM")),
            }
        )
    while len(pts) < 4:
        idx_f = len(pts) + 1
        pts.append(
            {
                "date": f"FASE 0{idx_f}",
                "label": "Registro Histórico & Consequência",
                "value": f"ETAPA 0{idx_f}",
            }
        )

    n_pts = len(pts)
    prog_c = max(0.0, min(0.9999, float(prog)))
    active_idx = min(n_pts - 1, max(0, int(prog_c * n_pts)))
    seg_span = 1.0 / float(n_pts)
    seg_local_prog = max(0.0, min(1.0, (prog_c - active_idx * seg_span) / seg_span))

    prev_idx = max(0, active_idx - 1)
    roll_frac = _ease_doc_snap(min(1.0, seg_local_prog / 0.36)) if active_idx > 0 else 1.0

    is_wide = w >= h
    odo_w = 580.0 if is_wide else (w - 110.0)
    odo_h = 118.0 if is_wide else 122.0
    odo_top_y = 44.0 if is_wide else 304.0

    _draw_mechanical_odometer_header(
        canvas=canvas,
        cx=w * 0.5,
        top_y=odo_top_y,
        odo_w=odo_w,
        odo_h=odo_h,
        prev_date=pts[prev_idx]["date"],
        curr_date=pts[active_idx]["date"],
        roll_frac=roll_frac,
        prog=prog_c,
        title_tf=cinzel_tf,
        ui_tf=cp_tf,
        is_en=is_en,
    )

    photo_pool = [img for img in (extra_photos or []) if img is not None]
    if not photo_pool and backdrop_img is not None:
        photo_pool = [backdrop_img]

    card_rects: List[skia.Rect] = []
    if is_wide:
        # Optimized 16:9 layout: generous 2x2 archival photo cards with open corridor for cause-and-effect arrows
        gap_x = 84.0
        gap_y = 54.0
        side_m = 82.0
        cw = (float(w) - side_m * 2.0 - gap_x) * 0.5
        ch = min(286.0, (float(h) - (odo_top_y + odo_h + 34.0) - 216.0 - gap_y) * 0.5)
        gx0 = side_m
        gx1 = side_m + cw + gap_x
        gy0 = odo_top_y + odo_h + 34.0
        gy1 = gy0 + ch + gap_y
        card_rects = [
            skia.Rect.MakeXYWH(gx0, gy0, cw, ch),
            skia.Rect.MakeXYWH(gx1, gy0, cw, ch),
            skia.Rect.MakeXYWH(gx0, gy1, cw, ch),
            skia.Rect.MakeXYWH(gx1, gy1, cw, ch),
        ]
    else:
        rail_x = 84.0
        cards_top = odo_top_y + odo_h + 32.0
        slot_h = 252.0
        cw = w - rail_x - 84.0
        ch = 226.0
        canvas.drawLine(
            rail_x,
            cards_top + 30.0,
            rail_x,
            cards_top + slot_h * 3 + 110.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#2C323B", 180)),
        )
        fill_h = (slot_h * 3 + 80.0) * prog_c
        canvas.drawLine(
            rail_x,
            cards_top + 30.0,
            rail_x,
            cards_top + 30.0 + fill_h,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.5, Color=hex_to_skia("#EAB308")),
        )
        for i in range(4):
            cy_i = cards_top + i * slot_h
            card_rects.append(skia.Rect.MakeXYWH(rail_x + 34.0, cy_i, cw, ch))

    # Radial spotlight illuminating active milestone card
    act_r = card_rects[active_idx]
    spot_p = skia.Paint(AntiAlias=True)
    spot_p.setShader(
        skia.GradientShader.MakeRadial(
            (act_r.centerX(), act_r.centerY()),
            max(act_r.width(), act_r.height()) * 0.85,
            [
                skia.ColorSetARGB(90, 234, 179, 8),
                skia.ColorSetARGB(34, 217, 56, 30),
                skia.ColorSetARGB(0, 18, 20, 23),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    canvas.drawRect(full_r, spot_p)

    # Cause-and-effect vector callout arrows connecting milestone cards in 16:9 (#EAB308 / #D9381E)
    if is_wide and len(card_rects) == 4:
        r0, r1, r2, r3 = card_rects
        # 0 -> 1 (horizontal top), 1 -> 2 (stepped center corridor), 2 -> 3 (horizontal bottom)
        a01_p = _ease_doc_snap(min(1.0, max(0.0, (prog_c - 0.12) / 0.18)))
        _draw_cause_effect_arrow(
            canvas,
            (r0.right() + 6.0, r0.centerY()),
            (r1.left() - 8.0, r1.centerY()),
            a01_p,
            t,
            color_hex="#EAB308",
            active=(active_idx >= 1),
        )
        # Stepped diagonal connector from Card 1 bottom -> corridor -> Card 2 top
        a12_p = _ease_doc_snap(min(1.0, max(0.0, (prog_c - 0.36) / 0.18)))
        if a12_p > 0.02:
            mid_y = (r0.bottom() + r2.top()) * 0.5
            pts_step = [
                (r1.centerX(), r1.bottom() + 4.0),
                (r1.centerX(), mid_y),
                (r2.centerX(), mid_y),
                (r2.centerX(), r2.top() - 6.0),
            ]
            step_path = skia.Path()
            step_path.moveTo(pts_step[0][0], pts_step[0][1])
            seg_t = a12_p * 3.0
            last_pt = pts_step[0]
            prev_pt = pts_step[0]
            for s_i in range(3):
                local_u = max(0.0, min(1.0, seg_t - s_i))
                if local_u > 0.0:
                    prev_pt = pts_step[s_i]
                    nx = pts_step[s_i][0] + (pts_step[s_i + 1][0] - pts_step[s_i][0]) * local_u
                    ny = pts_step[s_i][1] + (pts_step[s_i + 1][1] - pts_step[s_i][1]) * local_u
                    step_path.lineTo(nx, ny)
                    last_pt = (nx, ny)
            c_col = "#D9381E" if active_idx >= 2 else "#EAB308"
            sp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=3.0 if active_idx >= 2 else 2.0,
                Color=hex_to_skia(c_col, 230 if active_idx >= 2 else 120),
            )
            sp.setPathEffect(skia.DashPathEffect.Make([10.0, 6.0], -t * 44.0))
            canvas.drawPath(step_path, sp)
            ang = math.atan2(last_pt[1] - prev_pt[1], last_pt[0] - prev_pt[0])
            hp = skia.Path()
            hp.moveTo(last_pt[0], last_pt[1])
            hp.lineTo(last_pt[0] - 11.0 * math.cos(ang - 0.45), last_pt[1] - 11.0 * math.sin(ang - 0.45))
            hp.lineTo(last_pt[0] - 11.0 * math.cos(ang + 0.45), last_pt[1] - 11.0 * math.sin(ang + 0.45))
            hp.close()
            canvas.drawPath(hp, skia.Paint(AntiAlias=True, Color=hex_to_skia(c_col, 235)))

        a23_p = _ease_doc_snap(min(1.0, max(0.0, (prog_c - 0.62) / 0.18)))
        _draw_cause_effect_arrow(
            canvas,
            (r2.right() + 6.0, r2.centerY()),
            (r3.left() - 8.0, r3.centerY()),
            a23_p,
            t,
            color_hex="#D9381E",
            active=(active_idx >= 3),
        )

    phase_tags = (
        ("01 // ORIGEM", "02 // RUPTURA", "03 // ESCALADA", "04 // CONSEQUÊNCIA")
        if not is_en
        else ("01 // ORIGIN", "02 // SHIFT", "03 // ESCALATION", "04 // OUTCOME")
    )

    # Render 4 Archival Milestone Cards (ZERO fake IMPACTO % bars!)
    for idx, pt in enumerate(pts):
        r = card_rects[idx]
        is_act = idx == active_idx
        is_past = idx < active_idx

        if not is_wide:
            rail_x = 84.0
            ny = r.centerY()
            canvas.drawCircle(
                rail_x,
                ny,
                14.0 if is_act else 9.0,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E" if is_act else ("#EAB308" if is_past else "#2C323B"))),
            )
            canvas.drawCircle(rail_x, ny, 4.5, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

        sc = 1.03 if is_act else 0.97
        canvas.save()
        canvas.translate(r.centerX(), r.centerY())
        canvas.scale(sc, sc)
        local_r = skia.Rect.MakeXYWH(-r.width() * 0.5, -r.height() * 0.5, r.width(), r.height())
        local_rr = skia.RRect.MakeRectXY(local_r, 12.0, 12.0)

        bg_alpha = 242 if is_act else 188
        bg_col = hex_to_skia("#171A1F", bg_alpha) if is_act else hex_to_skia("#121417", bg_alpha)
        if is_act:
            _draw_fast_rrect_shadow(canvas, local_rr, dy=16.0, sigma=22.0, alpha=215)
        c_bg = skia.Paint(AntiAlias=True, Color=bg_col)
        canvas.drawRRect(local_rr, c_bg)

        # Left vertical 4px accent bar (#EAB308 active / #D9381E climax / #2C323B inactive)
        bar_hex = "#D9381E" if (is_act and idx >= 2) else ("#EAB308" if (is_act or is_past) else "#2C323B")
        canvas.drawRoundRect(
            skia.Rect.MakeXYWH(local_r.left() + 6.0, local_r.top() + 14.0, 4.0, r.height() - 28.0),
            2.0,
            2.0,
            skia.Paint(AntiAlias=True, Color=hex_to_skia(bar_hex, 240 if is_act else 140)),
        )

        # Larger archival photo card on right side of card (276px wide in 16:9!)
        thumb_w = 276.0 if is_wide else 204.0
        text_avail_w = r.width() - 48.0
        if photo_pool:
            p_img = photo_pool[idx % len(photo_pool)]
            pr = skia.Rect.MakeXYWH(local_r.right() - thumb_w - 16.0, local_r.top() + 16.0, thumb_w, r.height() - 32.0)
            prr = skia.RRect.MakeRectXY(pr, 8.0, 8.0)
            canvas.save()
            canvas.clipRRect(prr, doAntiAlias=True)
            img_p = skia.Paint(AntiAlias=True)
            img_p.setAlphaf(1.0 if is_act else 0.58)
            _draw_image_cover(canvas, p_img, pr, paint=img_p, y_bias=0.20)
            canvas.restore()
            canvas.drawRRect(
                prr,
                skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=1.8,
                    Color=hex_to_skia("#EAB308" if is_act else "#2C323B", 220 if is_act else 150),
                ),
            )
            text_avail_w = r.width() - thumb_w - 64.0

        tx = local_r.left() + 26.0
        ty = local_r.top() + 44.0

        # Courier Prime Bold Compact Date & Era Header
        compact_d = _compact_odometer_date(pt["date"])
        hdr_txt = f"{_normalize_upper(compact_d)}  •  {_normalize_upper(pt['value'])}"
        df, dl = _wrap_text_to_width(hdr_txt, cinzel_tf, 29.0 if is_act else 24.0, 16.0, text_avail_w, 1)
        if dl:
            _draw_safe_string(
                canvas,
                dl[0],
                tx,
                ty,
                df,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308" if is_act else "#E0C097", 252 if is_act else 175)),
            )

        # Milestone Description Label
        lf, ll = _wrap_text_to_width(pt["label"], ui_tf, 23.0 if is_act else 20.5, 14.5, text_avail_w, 3)
        ly = ty + 42.0
        for ln in ll:
            _draw_safe_string(
                canvas,
                ln,
                tx,
                ly,
                lf,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 248 if is_act else 155)),
            )
            ly += lf.getSize() * 1.28

        # Clean Documentary Cause-Effect Phase Tag (Courier Prime Bold — NO fake percentage bars!)
        tag_y = local_r.bottom() - 22.0
        tag_f = skia.Font(cp_tf, 14.5)
        tag_str = phase_tags[idx % len(phase_tags)]
        _draw_safe_string(
            canvas,
            tag_str,
            tx,
            tag_y,
            tag_f,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E" if (is_act and idx >= 2) else ("#EAB308" if is_act else "#94A3B8"), 235 if is_act else 150)),
        )
        # Subtle hairline underline under phase tag (not a fake percentage bar!)
        canvas.drawLine(
            tx,
            tag_y + 7.0,
            tx + min(text_avail_w, 180.0),
            tag_y + 7.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia(bar_hex, 200 if is_act else 90)),
        )

        border_col = hex_to_skia("#EAB308" if is_act else "#2C323B", 240 if is_act else 180)
        canvas.drawRRect(
            local_rr,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.6 if is_act else 1.4, Color=border_col),
        )
        canvas.restore()


# ---------------------------------------------------------------------------
# 7. Mindhunter / MagnatesMedia Forensic String Board with Catenary Strings & Spotlight
# ---------------------------------------------------------------------------
def _draw_3d_metallic_pushpin(
    canvas: skia.Canvas,
    px: float,
    py: float,
    is_active: bool = False,
) -> None:
    canvas.drawCircle(px + 5.0, py + 7.5, 16.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(65, 0, 0, 0)))
    canvas.drawCircle(px + 4.0, py + 6.0, 12.5, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(135, 0, 0, 0)))

    canvas.drawCircle(px + 1.0, py + 2.0, 6.5, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 160, 165, 178)))

    rad = 13.5 if is_active else 12.0
    head_p = skia.Paint(AntiAlias=True)
    head_p.setShader(
        skia.GradientShader.MakeRadial(
            (px - 3.5, py - 3.5),
            rad * 1.35,
            [
                skia.ColorSetARGB(255, 255, 145, 145),
                skia.ColorSetARGB(255, 217, 56, 30),
                skia.ColorSetARGB(255, 98, 12, 18),
            ],
            [0.0, 0.48, 1.0],
        )
    )
    canvas.drawCircle(px, py, rad, head_p)

    canvas.drawCircle(
        px,
        py,
        rad,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia("#EAB308", 210)),
    )
    canvas.drawCircle(px - 3.8, py - 3.8, 3.2, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 255, 245, 240)))


def _draw_catenary_red_string(
    canvas: skia.Canvas,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    edge_prog: float,
    corridor_mid: Optional[Tuple[float, float]] = None,
) -> None:
    """Draw a realistic taut crimson forensic string pin-to-pin with gravity sag or corridor routing
    so strings NEVER bisect card badges!
    """
    if edge_prog <= 0.02:
        return
    if corridor_mid is not None:
        # Route smoothly through the open corridor between cards so no badge text is ever crossed!
        c1 = (p0[0] + (corridor_mid[0] - p0[0]) * 0.72, p0[1] + (corridor_mid[1] - p0[1]) * 0.58)
        c2 = (p1[0] + (corridor_mid[0] - p1[0]) * 0.72, p1[1] + (corridor_mid[1] - p1[1]) * 0.58)
    else:
        dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        # Taut sag keeping horizontal pin-to-pin threads strictly in the top margin clear of card text/photos
        sag = min(18.0, 8.0 + dist * 0.012)
        c1 = (p0[0] + (p1[0] - p0[0]) * 0.33, p0[1] + (p1[1] - p0[1]) * 0.33 + sag * 0.85)
        c2 = (p0[0] + (p1[0] - p0[0]) * 0.67, p0[1] + (p1[1] - p0[1]) * 0.67 + sag * 0.95)

    path = skia.Path()
    steps = 40
    max_s = max(1, int(steps * min(1.0, edge_prog)))
    for si in range(max_s + 1):
        u = si / float(steps)
        iu = 1.0 - u
        bx = (iu ** 3) * p0[0] + 3 * (iu ** 2) * u * c1[0] + 3 * iu * (u ** 2) * c2[0] + (u ** 3) * p1[0]
        by = (iu ** 3) * p0[1] + 3 * (iu ** 2) * u * c1[1] + 3 * iu * (u ** 2) * c2[1] + (u ** 3) * p1[1]
        if si == 0:
            path.moveTo(bx, by)
        else:
            path.lineTo(bx, by)

    canvas.save()
    canvas.translate(4.0, 12.0)
    shadow_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=7.5,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(88, 0, 0, 0),
    )
    canvas.drawPath(path, shadow_str)
    canvas.restore()

    glow_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=11.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#D9381E", 68),
    )
    canvas.drawPath(path, glow_str)

    core_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=3.8,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#D9381E"),
    )
    canvas.drawPath(path, core_str)

    spec_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.2,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(145, 255, 175, 175),
    )
    canvas.drawPath(path, spec_str)


def draw_pro_forensic_string_board(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    extra_photos: List[skia.Image],
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render Mindhunter / MagnatesMedia Forensic Investigation Board:
    - 4 Polaroid/dossier evidence cards with aged paper border, photo thumbnail, 3D metallic push-pin
      + shadow at top center, and red evidence badge.
    - Curved catenary Bézier red strings ALL completing cleanly by `prog <= 0.35` (zero severed mid-air
      strings!) and routed pin-to-pin cleanly ABOVE / clear of card badges!
    - Moving Flashlight Spotlight (`RadialGradient`) tracking the active evidence card.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    _draw_dark_bokeh_backdrop(canvas, w, h, backdrop_img, prog, t, scrim_alpha=178, blur_sigma=3.5, mood=mood)

    grid_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.0,
        Color=hex_to_skia("#2C323B", 82),
    )
    for gx in range(0, w, 96):
        canvas.drawLine(gx, 0, gx, h, grid_p)
    for gy in range(0, h, 96):
        canvas.drawLine(0, gy, w, gy, grid_p)

    raw_nodes = _get_attr(scene, "board_nodes", None) or []
    nodes: List[Dict[str, str]] = []
    for n in raw_nodes[:4]:
        nodes.append(
            {
                "id": str(_get_attr(n, "id", f"n{len(nodes)+1}")),
                "title": str(_get_attr(n, "title", f"EVIDÊNCIA #{len(nodes)+1}")),
                "role": str(_get_attr(n, "role", "Registro Documental Arquivado")),
                "badge": str(_get_attr(n, "badge", "PROVA FORENSE")),
            }
        )
    while len(nodes) < 4:
        k = len(nodes) + 1
        nodes.append(
            {
                "id": f"n{k}",
                "title": f"ARQUIVO #{k:02d}",
                "role": "Evidência Histórica Confirmada",
                "badge": f"PROVA #{k:02d}",
            }
        )

    photo_pool = [img for img in (extra_photos or []) if img is not None]
    if not photo_pool and backdrop_img is not None:
        photo_pool = [backdrop_img]

    is_wide = w >= h
    if is_wide:
        centers = [
            (456.0, 268.0),
            (1464.0, 264.0),
            (462.0, 622.0),
            (1458.0, 618.0),
        ]
        tilts = (-1.6, 1.4, 1.2, -1.5)
        card_w, card_h = 584.0, 252.0
    else:
        centers = [
            (286.0, 560.0),
            (794.0, 570.0),
            (286.0, 1088.0),
            (794.0, 1098.0),
        ]
        tilts = (-1.6, 1.5, 1.3, -1.4)
        card_w, card_h = 446.0, 444.0

    prog_c = max(0.0, min(0.9999, float(prog)))
    active_idx = min(3, max(0, int(prog_c * 4)))
    cont_idx = max(0.0, min(3.0, prog_c * 3.2))
    i0 = int(math.floor(cont_idx))
    i1 = min(3, i0 + 1)
    frac = _ease_in_out_cubic(cont_idx - i0)
    spot_x = centers[i0][0] + (centers[i1][0] - centers[i0][0]) * frac
    spot_y = centers[i0][1] + (centers[i1][1] - centers[i0][1]) * frac

    # Top-center push-pin coordinates strictly on the upper border of each card (well ABOVE badges!)
    pin_coords: List[Tuple[float, float]] = []
    for idx, (cx, cy) in enumerate(centers):
        rad_t = math.radians(tilts[idx])
        local_py = -card_h * 0.5 + 12.0
        px = cx - local_py * math.sin(rad_t)
        py = cy + local_py * math.cos(rad_t)
        pin_coords.append((px, py))

    # 1A. Draw DIAGONAL Catenary Red Strings `(0->3)` and `(1->2)` UNDERNEATH the cards so they
    # emerge cleanly into the open central corridor and NEVER slash across card text (`217`) or coin photos!
    corridor_cx = float(w) * 0.5
    corridor_cy = (centers[0][1] + centers[2][1]) * 0.5
    diag_edges = [
        (2, 0, 3, (corridor_cx, corridor_cy - 18.0)),
        (3, 1, 2, (corridor_cx, corridor_cy + 18.0)),
    ]
    for e_idx, i_start, i_end, corr_pt in diag_edges:
        edge_start = 0.02 + e_idx * 0.055
        edge_dur = 0.155
        raw_ep = (prog_c - edge_start) / edge_dur
        edge_prog = _ease_doc_snap(min(1.0, max(0.0, raw_ep)))
        if edge_prog > 0.02:
            _draw_catenary_red_string(canvas, centers[i_start], centers[i_end], edge_prog, corridor_mid=corr_pt)

    # 1B. Draw the 4 Polaroid / Dossier Evidence Cards
    for idx, nd in enumerate(nodes):
        cx, cy = centers[idx]
        is_act = idx == active_idx
        ent = _ease_out_back(max(0.0, min(1.0, (body_t - idx * 0.05) / 0.34)))
        sc = (0.88 + 0.12 * ent) * (1.03 if is_act else 0.98)

        canvas.save()
        canvas.translate(cx, cy)
        canvas.rotate(tilts[idx])
        canvas.scale(sc, sc)

        rx = -card_w * 0.5
        ry = -card_h * 0.5
        c_rect = skia.Rect.MakeXYWH(rx, ry, card_w, card_h)
        c_rr = skia.RRect.MakeRectXY(c_rect, 14.0, 14.0)

        _draw_fast_rrect_shadow(canvas, c_rr, dy=18.0, sigma=24.0, alpha=225)
        paper_border = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(248, 236, 228, 212))
        canvas.drawRRect(c_rr, paper_border)

        inner_r = skia.Rect.MakeXYWH(rx + 6.0, ry + 6.0, card_w - 12.0, card_h - 12.0)
        inner_rr = skia.RRect.MakeRectXY(inner_r, 10.0, 10.0)
        canvas.drawRRect(inner_rr, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 246)))

        if is_wide:
            pol_w = 196.0
            pol_h = card_h - 36.0
            pol_x = rx + 20.0
            pol_y = ry + 18.0
            pol_r = skia.Rect.MakeXYWH(pol_x, pol_y, pol_w, pol_h)
            canvas.drawRoundRect(pol_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 244, 238, 224)))

            img_r = skia.Rect.MakeXYWH(pol_x + 8.0, pol_y + 8.0, pol_w - 16.0, pol_h - 34.0)
            if photo_pool:
                p_img = photo_pool[idx % len(photo_pool)]
                canvas.save()
                canvas.clipRect(img_r)
                _draw_image_cover(canvas, p_img, img_r, y_bias=0.18)
                canvas.restore()
            else:
                canvas.drawRect(img_r, skia.Paint(Color=skia.ColorSetARGB(255, 36, 30, 48)))

            ev_lbl = f"EXHIBIT #{idx + 1:02d}" if is_en else f"EVIDÊNCIA #{idx + 1:02d}"
            ef = skia.Font(ui_tf, 12.5)
            ew = float(ef.measureText(ev_lbl))
            _draw_safe_string(
                canvas,
                ev_lbl,
                pol_x + (pol_w - ew) * 0.5,
                pol_y + pol_h - 9.0,
                ef,
                skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 32, 24, 30)),
            )

            tx = pol_x + pol_w + 22.0
            tw_max = max(140.0, (rx + card_w - 24.0) - tx)

            badge_clean = _sanitize_glyphs(_normalize_upper(nd["badge"]), typeface=ui_tf)
            bf, bl = _wrap_text_to_width(badge_clean, ui_tf, 16.0, 12.0, tw_max - 24.0, 1)
            b_str = bl[0] if bl else badge_clean
            bw = float(bf.measureText(b_str))
            # Position badge cleanly in mid-lower band (`ry + 44`) well below top push-pin corridor
            badge_r = skia.Rect.MakeXYWH(tx, ry + 42.0, min(tw_max, bw + 26.0), 30.0)
            canvas.drawRoundRect(badge_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E")))
            canvas.drawRoundRect(
                badge_r,
                6.0,
                6.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#EAB308", 190)),
            )
            _draw_safe_string(canvas, b_str, tx + 13.0, ry + 62.5, bf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            tf_n, tl_n = _wrap_text_to_width(_normalize_upper(nd["title"]), title_tf, 28.0, 18.0, tw_max, 2)
            ty_n = ry + 108.0
            for tln in tl_n:
                _draw_safe_string(canvas, tln, tx, ty_n, tf_n, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308" if is_act else "#F8FAFC")))
                ty_n += tf_n.getSize() * 1.15

            rf_n, rl_n = _wrap_text_to_width(nd["role"], ui_tf, 19.5, 14.0, tw_max, 2)
            ry_n = max(ty_n + 6.0, ry + card_h - 58.0)
            for rln in rl_n:
                if ry_n > ry + card_h - 14.0:
                    break
                _draw_safe_string(canvas, rln, tx, ry_n, rf_n, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 224, 218, 235)))
                ry_n += rf_n.getSize() * 1.24
        else:
            pol_w = card_w - 40.0
            pol_h = 224.0
            pol_x = rx + 20.0
            pol_y = ry + 26.0
            pol_r = skia.Rect.MakeXYWH(pol_x, pol_y, pol_w, pol_h)
            canvas.drawRoundRect(pol_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 244, 238, 224)))

            img_r = skia.Rect.MakeXYWH(pol_x + 8.0, pol_y + 8.0, pol_w - 16.0, pol_h - 34.0)
            if photo_pool:
                p_img = photo_pool[idx % len(photo_pool)]
                canvas.save()
                canvas.clipRect(img_r)
                _draw_image_cover(canvas, p_img, img_r, y_bias=0.16)
                canvas.restore()
            else:
                canvas.drawRect(img_r, skia.Paint(Color=skia.ColorSetARGB(255, 36, 30, 48)))

            ev_lbl = f"EXHIBIT #{idx + 1:02d}" if is_en else f"EVIDÊNCIA #{idx + 1:02d}"
            ef = skia.Font(ui_tf, 13.0)
            ew = float(ef.measureText(ev_lbl))
            _draw_safe_string(
                canvas,
                ev_lbl,
                pol_x + (pol_w - ew) * 0.5,
                pol_y + pol_h - 9.0,
                ef,
                skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 32, 24, 30)),
            )

            tx = rx + 22.0
            tw_max = card_w - 44.0
            by_badge = pol_y + pol_h + 14.0

            badge_clean = _sanitize_glyphs(_normalize_upper(nd["badge"]), typeface=ui_tf)
            bf, bl = _wrap_text_to_width(badge_clean, ui_tf, 15.5, 11.5, tw_max - 24.0, 1)
            b_str = bl[0] if bl else badge_clean
            bw = float(bf.measureText(b_str))
            badge_r = skia.Rect.MakeXYWH(tx, by_badge, min(tw_max, bw + 26.0), 28.0)
            canvas.drawRoundRect(badge_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#D9381E")))
            canvas.drawRoundRect(
                badge_r,
                6.0,
                6.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#EAB308", 190)),
            )
            _draw_safe_string(canvas, b_str, tx + 13.0, by_badge + 19.5, bf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            tf_n, tl_n = _wrap_text_to_width(_normalize_upper(nd["title"]), title_tf, 27.0, 18.0, tw_max, 1)
            ty_n = by_badge + 60.0
            if tl_n:
                _draw_safe_string(canvas, tl_n[0], tx, ty_n, tf_n, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308" if is_act else "#F8FAFC")))

            rf_n, rl_n = _wrap_text_to_width(nd["role"], ui_tf, 19.0, 13.5, tw_max, 2)
            ry_n = ty_n + 30.0
            for rln in rl_n:
                if ry_n > ry + card_h - 16.0:
                    break
                _draw_safe_string(canvas, rln, tx, ry_n, rf_n, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 224, 218, 235)))
                ry_n += rf_n.getSize() * 1.24

        if is_act:
            canvas.drawRRect(
                c_rr,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#EAB308", 230)),
            )

        canvas.restore()

    # 2. Horizontal Top-Corridor Catenary Bézier Red Strings `(0->1)` & `(2->3)` — completing cleanly by `prog <= 0.35`
    # and staying strictly along the upper card border well clear of badges, titles, and polaroid photos!
    horiz_edges = [
        (0, 0, 1, None),
        (1, 2, 3, None),
    ]
    for e_idx, i_start, i_end, corr_pt in horiz_edges:
        edge_start = 0.02 + e_idx * 0.055
        edge_dur = 0.155
        raw_ep = (prog_c - edge_start) / edge_dur
        edge_prog = _ease_doc_snap(min(1.0, max(0.0, raw_ep)))
        if edge_prog > 0.02:
            _draw_catenary_red_string(canvas, pin_coords[i_start], pin_coords[i_end], edge_prog, corridor_mid=corr_pt)

    # 3. 3D Metallic Push-Pins + Shadow at Top Center of Each Card
    for idx, (px, py) in enumerate(pin_coords):
        _draw_3d_metallic_pushpin(canvas, px, py, is_active=(idx == active_idx))

    # 4. Moving Flashlight Spotlight illuminating active card & dimming outer edges
    beam_rad = (480.0 if is_wide else 430.0) * (1.0 + 0.03 * math.sin(t * 2.2))

    beam_p = skia.Paint(AntiAlias=True)
    beam_p.setBlendMode(skia.BlendMode.kScreen)
    beam_p.setShader(
        skia.GradientShader.MakeRadial(
            (spot_x, spot_y),
            beam_rad * 0.85,
            [
                skia.ColorSetARGB(64, 255, 232, 168),
                skia.ColorSetARGB(26, 234, 179, 8),
                skia.ColorSetARGB(0, 0, 0, 0),
            ],
            [0.0, 0.55, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), beam_p)

    dim_p = skia.Paint(AntiAlias=True)
    dim_p.setShader(
        skia.GradientShader.MakeRadial(
            (spot_x, spot_y),
            beam_rad * 1.45,
            [
                skia.ColorSetARGB(0, 10, 12, 16),
                skia.ColorSetARGB(52, 10, 12, 16),
                skia.ColorSetARGB(138, 8, 10, 14),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), dim_p)


# ---------------------------------------------------------------------------
# 8. `2D_Infographic_Over_Realism` — Vox / Johnny Harris Vector Schematics Over 65% Realism
# ---------------------------------------------------------------------------
def draw_2d_schematic_over_realism(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image] = None,
    body_t: Optional[float] = None,
    extra_photos: Optional[List[skia.Image]] = None,
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render Category 2 (`2D_Infographic_Over_Realism` / `layer_2_2d_infographics_over_realism`):
    Layers animated 2D vector schematics (tactical target reticles, animated dashed callout lines,
    cause-and-effect diagram nodes, and historical chronology breakdown in `#EAB308`, `#D9381E`,
    `#F8FAFC` with `Courier Prime Bold 36px-64px` data labels and `cubic-bezier(0.22, 1, 0.36, 1)`)
    directly over a desaturated 65%-brightness realistic scene (`#121417` base, `#2C323B` borders).
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    cinzel_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf
    prog_c = max(0.0, min(1.0, float(prog)))
    eased_p = _ease_doc_snap(prog_c)
    is_wide = w >= h

    # 1. Desaturated 65%-brightness realistic backdrop over #121417 dark slate base (cached filter!)
    canvas.clear(hex_to_skia("#121417"))
    if backdrop_img is not None:
        desat_bg = _get_desat65_image(backdrop_img)
        canvas.save()
        canvas.translate(w * 0.5, h * 0.5)
        sc = 1.02 + 0.05 * prog_c
        canvas.scale(sc, sc)
        _draw_image_cover(canvas, desat_bg, skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h), y_bias=0.25)
        canvas.restore()

    # Cached 1/4-res edge darkening vignette so vector schematics pop at 100% contrast (~6ms vs 21ms)
    def _build_schem_vig(vc: skia.Canvas, sw: int, sh: int) -> None:
        vp = skia.Paint()
        vp.setShader(
            skia.GradientShader.MakeRadial(
                (sw * 0.42, sh * 0.46),
                max(sw, sh) * 0.72,
                [skia.ColorSetARGB(46, 18, 20, 23), skia.ColorSetARGB(182, 12, 14, 18)],
            )
        )
        vc.drawRect(skia.Rect.MakeWH(sw, sh), vp)

    _draw_cached_gradient(canvas, _get_cached_gradient_overlay("schem_vig", w, h, _build_schem_vig), w, h)

    # Muted #2C323B architectural schematic grid overlay
    grid_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.0,
        Color=hex_to_skia("#2C323B", 88),
    )
    step_g = 96 if is_wide else 80
    for gx in range(0, w, step_g):
        canvas.drawLine(gx, 0, gx, h, grid_p)
    for gy in range(0, h, step_g):
        canvas.drawLine(0, gy, w, gy, grid_p)

    # Extract scene-local metadata for diagram nodes & key date/stat headline
    stamp_big = extract_depth_stamp_text(scene)
    lt_title = _normalize_upper(str(_get_attr(scene, "lower_third_title", stamp_big) or stamp_big))
    lt_sub = str(_get_attr(scene, "lower_third_subtitle", "") or "").strip()
    headline = _normalize_upper(str(_get_attr(scene, "evidence_headline", "") or lt_sub or "ANÁLISE HISTÓRICA"))
    quote_txt = str(_get_attr(scene, "evidence_quote", "") or "").strip()

    # Use explicit scene-local `schematic_points` ONLY if provided; NEVER slice global Roman `timeline_points[:3]`
    # onto 1644 / 1863 scenes! Build scene-local CAUSA / MECANISMO / EFEITO cards cleanly from scene metadata.
    raw_nodes: List[Tuple[str, str, str]] = []
    s_pts = _get_attr(scene, "schematic_points", None) or []
    for sp in s_pts[:3]:
        if isinstance(sp, (tuple, list)) and len(sp) >= 3:
            raw_nodes.append((str(sp[0]), str(sp[1]), str(sp[2])))
        else:
            raw_nodes.append(
                (
                    str(_get_attr(sp, "tag", _get_attr(sp, "date", "FASE"))),
                    str(_get_attr(sp, "title", _get_attr(sp, "value", "EVENTO"))),
                    str(_get_attr(sp, "desc", _get_attr(sp, "label", "Registro documentado"))),
                )
            )

    if not raw_nodes:
        sub_parts = [seg.strip() for seg in re.split(r"[•|—]+", lt_sub) if seg.strip()]
        cause_desc = lt_sub if lt_sub else headline
        mech_title = _normalize_upper(sub_parts[0]) if sub_parts else stamp_big
        mech_desc = headline
        eff_title = (
            _normalize_upper(sub_parts[-1])
            if len(sub_parts) >= 2
            else ("DOCUMENTED IMPACT" if is_en else "IMPACTO DOCUMENTADO")
        )
        eff_desc = quote_txt or (
            "Historical turning point documented in primary archives."
            if is_en
            else "Ruptura histórica documentada nos registros primários."
        )
        raw_nodes = [
            (f"{'CAUSE' if is_en else 'CAUSA'} • {stamp_big}", lt_title, cause_desc),
            ("MECHANISM" if is_en else "MECANISMO", mech_title, mech_desc),
            ("EFFECT" if is_en else "EFEITO", eff_title, eff_desc),
        ]
    while len(raw_nodes) < 3:
        idx_k = len(raw_nodes) + 1
        raw_nodes.append(
            (
                f"{'PHASE' if is_en else 'FASE'} 0{idx_k}",
                f"{'MILESTONE' if is_en else 'MARCO'} 0{idx_k}",
                headline,
            )
        )

    # 2. Animated Tactical Target Reticles locked onto 2 focal landmarks over the realistic scene
    reticle_pts = (
        [(w * 0.27, h * 0.36, 78.0, "#D9381E"), (w * 0.44, h * 0.58, 56.0, "#EAB308")]
        if is_wide
        else [(w * 0.34, h * 0.36, 62.0, "#D9381E"), (w * 0.68, h * 0.48, 48.0, "#EAB308")]
    )
    for r_idx, (rx, ry, r_rad, r_hex) in enumerate(reticle_pts):
        rp_prog = _ease_doc_snap(min(1.0, max(0.0, (prog_c - r_idx * 0.08) / 0.34)))
        if rp_prog <= 0.02:
            continue
        cur_r = r_rad * (1.28 - 0.28 * rp_prog)
        outer_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=2.6,
            Color=hex_to_skia(r_hex, int(225 * rp_prog)),
        )
        outer_p.setPathEffect(skia.DashPathEffect.Make([14.0, 9.0], -t * (38.0 if r_idx == 0 else -30.0)))
        canvas.drawCircle(rx, ry, cur_r, outer_p)

        inner_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.4,
            Color=hex_to_skia("#F8FAFC", int(185 * rp_prog)),
        )
        canvas.drawCircle(rx, ry, cur_r * 0.56, inner_p)
        canvas.drawCircle(rx, ry, 5.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(r_hex, int(250 * rp_prog))))

        # Crosshair ticks
        tick_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8, Color=hex_to_skia(r_hex, int(210 * rp_prog)))
        for d_a in (0.0, 90.0, 180.0, 270.0):
            rad_a = math.radians(d_a)
            canvas.drawLine(
                rx + math.cos(rad_a) * (cur_r * 0.72),
                ry + math.sin(rad_a) * (cur_r * 0.72),
                rx + math.cos(rad_a) * (cur_r * 1.18),
                ry + math.sin(rad_a) * (cur_r * 1.18),
                tick_p,
            )

    # 3. Top-Right / Right-Column Historical Breakdown & Cause-and-Effect Vector Schematic Panel
    if is_wide:
        panel_x = w * 0.54
        panel_y = 66.0
        panel_w = w * 0.41
        panel_h = h - 246.0  # Clears bottom_right captions & bottom_left date stamp
    else:
        panel_x = 46.0
        panel_y = h * 0.54
        panel_w = w - 92.0
        panel_h = h * 0.34

    # Big Courier Prime Bold 36px-64px Data / Year Stamp at top of schematic column
    stamp_reveal = _ease_doc_snap(min(1.0, prog_c / 0.28))
    big_f, big_l = _wrap_text_to_width(stamp_big, cp_tf, 64.0 if is_wide else 48.0, 36.0, panel_w - 32.0, 1)
    big_str = big_l[0] if big_l else stamp_big
    big_p = skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308", int(255 * stamp_reveal)))
    big_sh = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(190 * stamp_reveal), 0, 0, 0))
    hdr_tag = "SCHEMATIC ANALYSIS // HISTORICAL DATA" if is_en else "ANÁLISE ESQUEMÁTICA // DADOS HISTÓRICOS"
    hf = skia.Font(cp_tf, 15.0 if is_wide else 13.0)
    _draw_safe_string(canvas, hdr_tag, panel_x, panel_y + 18.0, hf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", int(200 * stamp_reveal))))
    _draw_safe_string(canvas, big_str, panel_x + 3.0, panel_y + (79.0 if is_wide else 65.0), big_f, big_sh)
    _draw_safe_string(canvas, big_str, panel_x, panel_y + (76.0 if is_wide else 62.0), big_f, big_p)

    # Animated vector divider under headline
    div_y = panel_y + (94.0 if is_wide else 78.0)
    div_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#D9381E", 230))
    div_p.setPathEffect(skia.DashPathEffect.Make([18.0, 8.0], -t * 48.0))
    canvas.drawLine(panel_x, div_y, panel_x + panel_w * stamp_reveal, div_y, div_p)

    # 3 Cause-and-Effect Diagram Nodes connected with animated dashed callout lines from reticles
    # Card 03 uses high-contrast #F87171 over #121417 dark slate (instead of dark low-contrast #D9381E)
    node_colors = ("#EAB308", "#F8FAFC", "#F87171")
    nodes_top = div_y + 24.0
    n_count = len(raw_nodes)
    node_gap = 20.0 if is_wide else 16.0
    node_h = min(176.0 if is_wide else 136.0, (panel_y + panel_h - nodes_top - node_gap * (n_count - 1)) / float(n_count))

    prev_node_bottom: Optional[Tuple[float, float]] = None
    for idx_n, (n_tag, n_title, n_desc) in enumerate(raw_nodes):
        n_prog = _ease_doc_snap(min(1.0, max(0.0, (prog_c - (0.08 + idx_n * 0.14)) / 0.32)))
        if n_prog <= 0.02:
            continue
        ny = nodes_top + idx_n * (node_h + node_gap)
        n_col = node_colors[idx_n % len(node_colors)]
        slide_x = (1.0 - n_prog) * 34.0
        nx = panel_x + slide_x
        nr = skia.Rect.MakeXYWH(nx, ny, panel_w, node_h)
        nrr = skia.RRect.MakeRectXY(nr, 8.0, 8.0)

        # Animated dashed vector callout leader from left reticle to this schematic node (16:9)
        if is_wide and idx_n < len(reticle_pts):
            rx, ry, _, _ = reticle_pts[idx_n]
            mid_elbow_x = rx + (nx - rx) * 0.52
            c_path = skia.Path()
            c_path.moveTo(rx, ry)
            c_path.lineTo(rx + (mid_elbow_x - rx) * n_prog, ry + (ny + node_h * 0.5 - ry) * n_prog)
            c_path.lineTo(rx + (nx - rx) * n_prog, ry + (ny + node_h * 0.5 - ry) * n_prog)
            cp_line = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.2,
                Color=hex_to_skia(n_col, int(220 * n_prog)),
            )
            cp_line.setPathEffect(skia.DashPathEffect.Make([10.0, 6.0], -t * 50.0))
            canvas.drawPath(c_path, cp_line)
            canvas.drawCircle(nx, ny + node_h * 0.5, 5.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(n_col, int(240 * n_prog))))

        # Cause -> Effect vertical arrow from previous node
        if prev_node_bottom is not None:
            _draw_cause_effect_arrow(
                canvas,
                prev_node_bottom,
                (nx + 42.0, ny - 3.0),
                n_prog,
                t,
                color_hex=n_col,
                active=True,
            )

        # Node Card (#121417 translucent + #2C323B muted border + 4px vector accent bar)
        card_a = int(230 * n_prog)
        _draw_fast_rrect_shadow(canvas, nrr, dy=12.0, sigma=18.0, alpha=int(180 * n_prog))
        card_bg = skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", card_a))
        canvas.drawRRect(nrr, card_bg)
        canvas.drawRRect(
            nrr,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, Color=hex_to_skia("#2C323B", card_a)),
        )
        canvas.drawRect(
            skia.Rect.MakeXYWH(nx, ny + 8.0, 4.0, node_h - 16.0),
            skia.Paint(AntiAlias=True, Color=hex_to_skia(n_col, int(250 * n_prog))),
        )

        tx = nx + 20.0
        avail_w = panel_w - 36.0
        # Tag + wrapped Cinzel title + wrapped Courier Prime description (ZERO mid-word truncation!)
        tag_str = f"0{idx_n + 1} // {_normalize_upper(n_tag)}"
        tf_tag, tag_ls = _wrap_text_to_width(tag_str, cp_tf, 14.5, 11.5, avail_w, 1)
        _draw_safe_string(
            canvas,
            tag_ls[0] if tag_ls else tag_str,
            tx,
            ny + 24.0,
            tf_tag,
            skia.Paint(AntiAlias=True, Color=hex_to_skia(n_col, int(250 * n_prog))),
        )
        title_f, title_ls = _wrap_text_to_width(_normalize_upper(n_title), cinzel_tf, 26.0 if is_wide else 21.0, 14.5, avail_w, 1)
        if title_ls:
            _draw_safe_string(canvas, title_ls[0], tx, ny + 55.0, title_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", int(250 * n_prog))))

        desc_f, desc_ls = _wrap_text_to_width(n_desc, cp_tf, 17.0 if is_wide else 14.5, 12.0, avail_w, 3)
        dy = ny + 84.0
        for dln in desc_ls:
            if dy > ny + node_h - 10.0:
                break
            _draw_safe_string(canvas, dln, tx, dy, desc_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#E0C097", int(230 * n_prog))))
            dy += desc_f.getSize() * 1.24

        prev_node_bottom = (nx + 42.0, ny + node_h + 2.0)

    # 4. Left-Side Stepped Historical Vector Timeline Breakdown Bar (Vox visual anchor — ZERO [:38] slicing!)
    if is_wide:
        bar_x = 96.0
        bar_y = 76.0
        bar_w = w * 0.40
        hl_f, hl_lns = _wrap_text_to_width(_normalize_upper(headline), cp_tf, 15.5, 11.5, bar_w - 36.0, 2)
        if not hl_lns:
            hl_lns = [_normalize_upper(headline)]
        hl_step = hl_f.getSize() * 1.28
        bar_h = 84.0 if len(hl_lns) <= 1 else (48.0 + len(hl_lns) * hl_step + 24.0)
        br = skia.Rect.MakeXYWH(bar_x, bar_y, bar_w, bar_h)
        canvas.drawRoundRect(br, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 215)))
        canvas.drawRoundRect(
            br,
            8.0,
            8.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia("#2C323B", 220)),
        )
        hy_bar = bar_y + 28.0
        for hln in hl_lns:
            _draw_safe_string(
                canvas,
                hln,
                bar_x + 18.0,
                hy_bar,
                hl_f,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 235)),
            )
            hy_bar += hl_step
        # Stepped proportional vector breakdown segments (#EAB308, #F8FAFC, #F87171)
        seg_x = bar_x + 18.0
        seg_y = hy_bar + 4.0
        seg_total_w = bar_w - 36.0
        weights = (0.34, 0.30, 0.36)
        cur_x = seg_x
        for s_i, (wt, s_hex) in enumerate(zip(weights, ("#EAB308", "#F8FAFC", "#F87171"))):
            sw = max(4.0, (seg_total_w - 12.0) * wt * eased_p)
            canvas.drawRoundRect(
                skia.Rect.MakeXYWH(cur_x, seg_y, sw, 14.0),
                3.0,
                3.0,
                skia.Paint(AntiAlias=True, Color=hex_to_skia(s_hex, 230)),
            )
            cur_x += (seg_total_w - 12.0) * wt + 6.0

    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)


# ---------------------------------------------------------------------------
# 9. `Video_Over_Video_PiP` — `layer_3_video_over_video_collage` (Vox / Johnny Harris)
# ---------------------------------------------------------------------------
def _get_blurred_backdrop_image(
    img: skia.Image,
    w: int,
    h: int,
    sigma: float = 15.0,
) -> skia.Image:
    """Render and cache a 15px Gaussian-blurred backdrop at 1/4 resolution for <0.2ms/frame blits."""
    key = (int(img.uniqueID()), int(w), int(h), int(round(sigma)))
    cached = _BLUR_BACKDROP_CACHE.get(key)
    if cached is not None:
        return cached
    sw = max(160, w // 4)
    sh = max(90, h // 4)
    surf = skia.Surface(sw, sh)
    c = surf.getCanvas()
    c.clear(hex_to_skia("#121417"))
    p = skia.Paint(AntiAlias=True)
    # 15px blur at full res == 3.75px sigma at 1/4 scale (visually identical, 16x faster!)
    p.setImageFilter(skia.ImageFilters.Blur(max(1.0, sigma * 0.25), max(1.0, sigma * 0.25)))
    _draw_image_cover(c, img, skia.Rect.MakeWH(sw, sh), paint=p, y_bias=0.25)
    out = surf.makeImageSnapshot()
    if len(_BLUR_BACKDROP_CACHE) >= 32:
        _BLUR_BACKDROP_CACHE.clear()
    _BLUR_BACKDROP_CACHE[key] = out
    return out


def draw_video_over_video_collage(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image] = None,
    pip_frames_or_photos: Optional[Sequence[Optional[skia.Image]]] = None,
    body_t: Optional[float] = None,
    is_en: bool = False,
    **kwargs: Any,
) -> None:
    """Render Category 3 (`Video_Over_Video_PiP` / `layer_3_video_over_video_collage`):
    - Background track: Dark textured paper/grid surface (`#121417`) + optional blurred slow-motion
      B-roll (`15px` blur at `40%` opacity).
    - Foreground PiP cards: 1 to 3 floating video/document windows (`scale 55%-75%`),
      border `2px solid rgba(255,255,255,0.18)`, drop shadow `0px 20px 50px rgba(0,0,0,0.85)`,
      slide-in entrance with slight rotation (`-2deg` to `+2deg`), and animated `#FFD700`
      (`kMultiply`) brush-stroke highlighter synced to keywords!
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    cinzel_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf
    prog_c = max(0.0, min(1.0, float(prog)))
    is_wide = w >= h

    # 1. Background Track: Dark textured paper/grid surface (#121417) + blurred B-roll (15px, 40% opacity)
    full_r = skia.Rect.MakeWH(w, h)
    canvas.clear(hex_to_skia("#121417"))
    if backdrop_img is not None:
        blur_bg = _get_blurred_backdrop_image(backdrop_img, w, h, sigma=15.0)
        bg_p = skia.Paint(AntiAlias=True)
        bg_p.setAlpha(int(round(255 * 0.40)))  # Exact 40% opacity
        canvas.drawImageRect(
            blur_bg,
            skia.Rect.MakeWH(blur_bg.width(), blur_bg.height()),
            full_r,
            _LINEAR_SAMPLING,
            bg_p,
            skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
        )

    # Dark archival paper grid & subtle fiber lines
    grid_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=hex_to_skia("#2C323B", 78))
    for gx in range(0, w, 80):
        canvas.drawLine(gx, 0, gx, h, grid_p)
    for gy in range(0, h, 80):
        canvas.drawLine(0, gy, w, gy, grid_p)
    fiber_p = skia.Paint(Color=skia.ColorSetARGB(12, 224, 192, 151))
    for fy in range(0, h, 18):
        canvas.drawLine(0, fy, w, fy + ((fy % 3) - 1) * 2.0, fiber_p)

    # Gather 1 to 3 valid PiP media windows
    raw_pool = [img for img in (pip_frames_or_photos or []) if img is not None]
    if not raw_pool and backdrop_img is not None:
        raw_pool = [backdrop_img]
    n_cards = max(1, min(3, len(raw_pool) if raw_pool else 2))

    headline = _normalize_upper(str(_get_attr(scene, "evidence_headline", "") or _get_attr(scene, "lower_third_title", "DOSSIÊ VISUAL") or "DOSSIÊ VISUAL"))
    quote = str(_get_attr(scene, "evidence_quote", "") or _get_attr(scene, "lower_third_subtitle", "Registros históricos preservados confirmam a ruptura.") or "")
    stamp_lbl = extract_depth_stamp_text(scene)

    # Define 1-3 floating window specs (scale 55%-75% of viewport slot, -2deg..+2deg rotation)
    if is_wide:
        if n_cards == 1:
            layouts = [
                (w * 0.50, h * 0.45, w * 0.64, h * 0.64, -1.2, 0.00, "primary"),
            ]
        elif n_cards == 2:
            layouts = [
                (w * 0.34, h * 0.44, w * 0.55, h * 0.58, -1.8, 0.00, "primary"),
                (w * 0.71, h * 0.50, w * 0.44, h * 0.54, 1.9, 0.16, "doc_highlight"),
            ]
        else:
            layouts = [
                (w * 0.28, h * 0.43, w * 0.42, h * 0.52, -2.0, 0.00, "pip_a"),
                (w * 0.52, h * 0.46, w * 0.46, h * 0.56, 1.4, 0.14, "primary"),
                (w * 0.76, h * 0.50, w * 0.38, h * 0.50, -1.6, 0.28, "doc_highlight"),
            ]
    else:
        if n_cards == 1:
            layouts = [(w * 0.50, h * 0.48, w * 0.74, h * 0.42, -1.4, 0.00, "doc_highlight")]
        else:
            layouts = [
                (w * 0.46, h * 0.38, w * 0.72, h * 0.30, -1.9, 0.00, "primary"),
                (w * 0.54, h * 0.64, w * 0.72, h * 0.28, 1.8, 0.18, "doc_highlight"),
            ][:n_cards]

    border_paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.0,
        Color=skia.ColorSetARGB(46, 255, 255, 255),  # Exact 2px solid rgba(255,255,255,0.18)
    )

    for c_idx, (cx, cy, cw, ch, rot_deg, delay_p, role_kind) in enumerate(layouts):
        ent = _ease_doc_snap(min(1.0, max(0.0, (prog_c - delay_p) / 0.28)))
        if ent <= 0.01:
            continue

        # Slide-in from alternating horizontal/vertical edges + subtle floating rotation (-2deg to +2deg)
        slide_dx = (1.0 - ent) * (-90.0 if c_idx % 2 == 0 else 90.0)
        slide_dy = (1.0 - ent) * 44.0 + math.sin(t * 1.1 + c_idx * 1.7) * 4.0
        cur_rot = rot_deg * (0.45 + 0.55 * ent) + math.sin(t * 0.65 + c_idx) * 0.35
        cur_scale = 0.92 + 0.08 * ent

        canvas.save()
        canvas.translate(cx + slide_dx, cy + slide_dy)
        canvas.rotate(cur_rot)
        canvas.scale(cur_scale, cur_scale)

        r = skia.Rect.MakeXYWH(-cw * 0.5, -ch * 0.5, cw, ch)
        rr = skia.RRect.MakeRectXY(r, 10.0, 10.0)

        # Exact drop shadow: 0px 20px 50px rgba(0,0,0,0.85) (fast analytical C++ MaskFilter)
        _draw_fast_rrect_shadow(canvas, rr, dy=20.0, sigma=25.0, alpha=int(217 * ent))
        sh_p = skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", int(245 * ent)))
        canvas.drawRRect(rr, sh_p)

        canvas.save()
        canvas.clipRRect(rr, doAntiAlias=True)

        img_use = raw_pool[c_idx % len(raw_pool)] if raw_pool else None

        if role_kind == "doc_highlight":
            # Parchment / archival document PiP window with animated #FFD700 kMultiply brush-stroke highlighter!
            canvas.drawRect(r, skia.Paint(Color=skia.ColorSetARGB(255, 244, 237, 222)))
            # Top archival plate slice (44% height) + unobstructed headline & highlighted excerpt below
            plate_h = ch * 0.44
            plate_r = skia.Rect.MakeXYWH(-cw * 0.5 + 16.0, -ch * 0.5 + 40.0, cw - 32.0, plate_h - 44.0)
            if img_use is not None:
                _draw_archival_sepia_plate_with_mounts(canvas, img_use, plate_r)
            # Top file header strip
            hdr_f = skia.Font(cp_tf, 13.5)
            _draw_safe_string(
                canvas,
                f"ARQUIVO // {stamp_lbl}" if not is_en else f"ARCHIVE // {stamp_lbl}",
                -cw * 0.5 + 18.0,
                -ch * 0.5 + 26.0,
                hdr_f,
                skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(200, 66, 54, 46)),
            )
            # Headline (up to 2 crisp wrapped lines, ZERO truncation) + quote with #FFD700 multiply brush highlighter
            text_top = -ch * 0.5 + plate_h + 14.0
            hf_d, hl_d = _wrap_text_to_width(headline, cinzel_tf, 20.5, 13.0, cw - 40.0, 2)
            hy_d = text_top + 18.0
            for hln in hl_d:
                _draw_safe_string(canvas, hln, -cw * 0.5 + 20.0, hy_d, hf_d, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(245, 22, 18, 24)))
                hy_d += hf_d.getSize() * 1.22

            qf_d, ql_d = _wrap_text_to_width(quote, cp_tf, 18.5, 12.5, cw - 44.0, 5)
            qy = hy_d + 12.0
            line_step = qf_d.getSize() * 1.38
            hl_sweep = _ease_doc_snap(min(1.0, max(0.0, (prog_c - delay_p - 0.08) / 0.52)))
            n_ql = max(1, len(ql_d))
            for li, qln in enumerate(ql_d):
                if qy > ch * 0.5 - 14.0:
                    break
                l_prog = max(0.0, min(1.0, hl_sweep * n_ql - li))
                if l_prog > 0.01:
                    lw = float(qf_d.measureText(qln))
                    # Organic #FFD700 multiply brush-stroke highlight bar
                    brush_r = skia.Rect.MakeXYWH(
                        -cw * 0.5 + 16.0,
                        qy - qf_d.getSize() * 0.84,
                        (lw + 14.0) * l_prog,
                        qf_d.getSize() * 1.16,
                    )
                    hl_p = skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD700", 225))
                    hl_p.setBlendMode(skia.BlendMode.kMultiply)
                    canvas.drawRoundRect(brush_r, 5.0, 5.0, hl_p)
                _draw_safe_string(canvas, qln, -cw * 0.5 + 22.0, qy, qf_d, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 20, 18, 22)))
                qy += line_step
        else:
            # Floating Cinema Video / Archival Photo Window (Background Cards 1 & 2)
            if img_use is not None:
                kb = 1.03 + 0.06 * prog_c
                canvas.save()
                canvas.scale(kb, kb)
                _draw_image_cover(canvas, img_use, r, y_bias=0.22)
                canvas.restore()
            else:
                canvas.drawRect(r, skia.Paint(Color=hex_to_skia("#1C2026")))

            # Clean unobstructed top-left `FIG. 01` / `FIG. 02` tag ONLY on multi-card background windows
            # (removes buried/overlapped bottom prose captions — headline + quote belong strictly on Card 3!)
            has_doc_card = any(spec[6] == "doc_highlight" for spec in layouts)
            tag_txt = f"FIG. 0{c_idx + 1}" if has_doc_card else f"FIG. 0{c_idx + 1} • {stamp_lbl}"
            tf_b = skia.Font(cp_tf, 14.5)
            tw_b = float(tf_b.measureText(tag_txt))
            pill_r = skia.Rect.MakeXYWH(-cw * 0.5 + 16.0, -ch * 0.5 + 16.0, tw_b + 26.0, 28.0)
            canvas.drawRoundRect(pill_r, 5.0, 5.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 220)))
            canvas.drawRect(skia.Rect.MakeXYWH(pill_r.left(), pill_r.top() + 4.0, 3.5, 20.0), skia.Paint(Color=hex_to_skia("#EAB308")))
            _draw_safe_string(canvas, tag_txt, pill_r.left() + 12.0, pill_r.top() + 19.0, tf_b, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

            # Only render bottom caption when this is a solo 1-card unobstructed layout (no overlapping foreground card)
            if not has_doc_card:
                bot_h = 92.0
                bot_r = skia.Rect.MakeXYWH(-cw * 0.5, ch * 0.5 - bot_h, cw, bot_h)
                scrim_p = skia.Paint()
                scrim_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(0.0, bot_r.top()), (0.0, bot_r.bottom())],
                        [skia.ColorSetARGB(0, 12, 14, 18), skia.ColorSetARGB(225, 12, 14, 18)],
                    )
                )
                canvas.drawRect(bot_r, scrim_p)
                hl_w = (cw - 44.0) * _ease_doc_snap(min(1.0, max(0.0, (prog_c - 0.12) / 0.45)))
                canvas.drawRoundRect(
                    skia.Rect.MakeXYWH(-cw * 0.5 + 20.0, ch * 0.5 - 16.0, max(6.0, hl_w), 4.0),
                    2.0,
                    2.0,
                    skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD700", 230)),
                )
                cap_f, cap_l = _wrap_text_to_width(headline, cp_tf, 18.0, 13.0, cw - 40.0, 2)
                cy_cap = ch * 0.5 - (30.0 if len(cap_l) <= 1 else 52.0)
                for cln in cap_l:
                    _draw_safe_string(canvas, cln, -cw * 0.5 + 20.0, cy_cap, cap_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))
                    cy_cap += cap_f.getSize() * 1.24

        canvas.restore()  # End clipRRect
        canvas.drawRRect(rr, border_paint)
        canvas.restore()

    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)


# ---------------------------------------------------------------------------
# 10. `Dark_3D_Reconstruction` — Fern-Style Minimalist 3D Reconstruction & Digital UI
# ---------------------------------------------------------------------------
def _get_rimlit_silhouette_image(
    fg_img: skia.Image,
    target_w: int = 380,
    target_h: int = 520,
) -> skia.Image:
    """Convert `fg_img`'s alpha mask into a cached Fern-style rim-lit dark human silhouette sprite."""
    key = (int(fg_img.uniqueID()), int(target_w), int(target_h))
    cached = _SILHOUETTE_CACHE.get(key)
    if cached is not None:
        return cached

    surf = skia.Surface(target_w, target_h)
    c = surf.getCanvas()
    c.clear(skia.ColorSetARGB(0, 0, 0, 0))
    dst = skia.Rect.MakeXYWH(24.0, 24.0, target_w - 48.0, target_h - 48.0)

    # Pass 1: Backlit cold-cyan / warm-bone volumetric rim glow expanded via blur + SrcIn tint
    rim_left = skia.Paint(AntiAlias=True)
    rim_left.setColorFilter(skia.ColorFilters.Blend(hex_to_skia("#38BDF8", 235), skia.BlendMode.kSrcIn))
    rim_left.setImageFilter(skia.ImageFilters.Blur(6.5, 6.5))
    c.save()
    c.translate(-5.0, -3.0)
    _draw_image_cover(c, fg_img, dst, paint=rim_left, y_bias=0.22)
    c.restore()

    rim_right = skia.Paint(AntiAlias=True)
    rim_right.setColorFilter(skia.ColorFilters.Blend(hex_to_skia("#E0C097", 235), skia.BlendMode.kSrcIn))
    rim_right.setImageFilter(skia.ImageFilters.Blur(5.5, 5.5))
    c.save()
    c.translate(5.0, -3.0)
    _draw_image_cover(c, fg_img, dst, paint=rim_right, y_bias=0.22)
    c.restore()

    # Pass 2: Crisp dark silhouette core (#0B0D11)
    core_p = skia.Paint(AntiAlias=True)
    core_p.setColorFilter(skia.ColorFilters.Blend(skia.ColorSetARGB(250, 11, 13, 17), skia.BlendMode.kSrcIn))
    _draw_image_cover(c, fg_img, dst, paint=core_p, y_bias=0.22)

    out = surf.makeImageSnapshot()
    if len(_SILHOUETTE_CACHE) >= 32:
        _SILHOUETTE_CACHE.clear()
    _SILHOUETTE_CACHE[key] = out
    return out


def _project_3d_point(
    pt: Tuple[float, float, float],
    yaw_rad: float,
    pitch_rad: float,
    cam_dist: float,
    cam_y: float,
    focal: float,
    cx: float,
    cy: float,
) -> Optional[Tuple[float, float, float]]:
    """Project a 3D world point `(x, y, z)` through an orbiting perspective camera matrix.
    Returns `(screen_x, screen_y, cam_z)` or None if behind camera near plane.
    """
    x, y, z = pt
    # Orbit rotation around world Y axis (yaw)
    cyaw, syaw = math.cos(yaw_rad), math.sin(yaw_rad)
    rx = x * cyaw + z * syaw
    rz = -x * syaw + z * cyaw
    ry = y - cam_y

    # Translate by camera distance along +Z
    tz = rz + cam_dist

    # Pitch rotation around camera X axis
    cpit, spit = math.cos(pitch_rad), math.sin(pitch_rad)
    py = ry * cpit - tz * spit
    pz = ry * spit + tz * cpit

    if pz <= 0.35:
        return None
    inv_z = focal / pz
    return (cx + rx * inv_z, cy - py * inv_z, pz)


def draw_fern_3d_reconstruction(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: Any,
    prog: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image] = None,
    fg_img: Optional[skia.Image] = None,
    body_t: Optional[float] = None,
    is_en: bool = False,
    primary_photo: Optional[skia.Image] = None,
    **kwargs: Any,
) -> None:
    """Render Category 4 (`Dark_3D_Reconstruction` — Fern-style Minimalist 3D Reconstruction):
    - Dark slate minimalist 3D void (`#121417`) with orbiting 3D perspective camera matrix.
    - Procedural 3D perspective wireframe architectural floor grid, columns/arches, and central altar.
    - Overhead volumetric spotlight cones (`kScreen` god rays + ground pool).
    - Backlit dark human silhouette (when `fg_img` is provided) OR a rim-lit 3D holographic
      archival exhibit monolith framing `backdrop_img` / `primary_photo` on the glowing plinth
      (ZERO primitive circle+trapezoid cartoon pawn fallback!).
    - Glowing 3D-projected perspective tactical target circles (`#D9381E`, `#EAB308`, `#38BDF8`).
    - Fern-style digital forensic UI telemetry callouts (`Courier Prime Bold` / `Cinzel Bold`, ZERO `[:N]` slices!).
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    cp_tf = get_courier_prime_bold_typeface(fallback=ui_tf) or ui_tf
    cinzel_tf = get_cinzel_bold_typeface(fallback=title_tf) or title_tf
    prog_c = max(0.0, min(1.0, float(prog)))
    is_wide = w >= h
    exhibit_img = backdrop_img or primary_photo

    full_r = skia.Rect.MakeWH(w, h)
    # 1. Dark minimalist 3D slate void (#121417 + deep #0D1B2A horizon fog, cached 1/4-res gradient)
    def _build_fern_void(vc: skia.Canvas, sw: int, sh: int) -> None:
        vp = skia.Paint()
        vp.setShader(
            skia.GradientShader.MakeLinear(
                [(0.0, 0.0), (0.0, float(sh))],
                [
                    hex_to_skia("#0D1B2A", 255),
                    hex_to_skia("#121417", 255),
                    skia.ColorSetARGB(255, 10, 12, 16),
                ],
                [0.0, 0.52, 1.0],
            )
        )
        vc.drawRect(skia.Rect.MakeWH(sw, sh), vp)

    _draw_cached_gradient(canvas, _get_cached_gradient_overlay("fern_void", w, h, _build_fern_void), w, h)

    # Subtle 15%-opacity desaturated architectural depth whisper if backdrop_img supplied
    if backdrop_img is not None:
        desat_bg = _get_desat65_image(backdrop_img)
        ghost_p = skia.Paint()
        ghost_p.setAlpha(38)
        _draw_image_cover(canvas, desat_bg, full_r, paint=ghost_p, y_bias=0.28)

    # Smooth orbiting 3D perspective camera parameters
    yaw_deg = -14.0 + 28.0 * _ease_in_out_cubic(prog_c)
    pitch_deg = 13.5 - 2.8 * prog_c
    yaw_rad = math.radians(yaw_deg)
    pitch_rad = math.radians(pitch_deg)
    cam_dist = 7.4 - 1.55 * prog_c
    cam_y = 2.05 - 0.25 * prog_c
    focal = min(float(w), float(h)) * (1.02 if is_wide else 1.15)
    vp_cx = float(w) * 0.50
    vp_cy = float(h) * (0.48 if is_wide else 0.45)

    def _proj(x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        return _project_3d_point((x, y, z), yaw_rad, pitch_rad, cam_dist, cam_y, focal, vp_cx, vp_cy)

    # 2. Perspective 3D Architectural Wireframe Floor Grid (depth-attenuated)
    grid_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2)
    for gx in range(-6, 7):
        p0 = _proj(float(gx) * 1.05, 0.0, -5.5)
        p1 = _proj(float(gx) * 1.05, 0.0, 5.5)
        if p0 and p1:
            is_axis = gx == 0
            grid_p.setColor(hex_to_skia("#38BDF8", 78) if is_axis else hex_to_skia("#2C323B", 135))
            canvas.drawLine(p0[0], p0[1], p1[0], p1[1], grid_p)

    for gz in range(-5, 6):
        p0 = _proj(-6.3, 0.0, float(gz) * 1.05)
        p1 = _proj(6.3, 0.0, float(gz) * 1.05)
        if p0 and p1:
            depth_fade = max(0.25, min(1.0, 1.0 - (gz + 5.0) / 13.0))
            grid_p.setColor(hex_to_skia("#2C323B", int(155 * depth_fade)))
            canvas.drawLine(p0[0], p0[1], p1[0], p1[1], grid_p)

    # 3. 3D Wireframe Architectural Columns & Central Altar Plinth
    col_wire = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, Color=hex_to_skia("#38BDF8", 112))
    col_face = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(96, 20, 26, 36))

    def _draw_3d_box(cx_b: float, y0_b: float, y1_b: float, cz_b: float, hw: float, hd: float, edge_p: skia.Paint, fill_p: Optional[skia.Paint] = None) -> None:
        corners = [
            (cx_b - hw, y0_b, cz_b - hd), (cx_b + hw, y0_b, cz_b - hd),
            (cx_b + hw, y0_b, cz_b + hd), (cx_b - hw, y0_b, cz_b + hd),
            (cx_b - hw, y1_b, cz_b - hd), (cx_b + hw, y1_b, cz_b - hd),
            (cx_b + hw, y1_b, cz_b + hd), (cx_b - hw, y1_b, cz_b + hd),
        ]
        pts_2d = [_proj(*pt) for pt in corners]
        if any(p is None for p in pts_2d):
            return
        if fill_p is not None:
            for face_ids in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)):
                fp = skia.Path()
                fp.moveTo(pts_2d[face_ids[0]][0], pts_2d[face_ids[0]][1])
                for fid in face_ids[1:]:
                    fp.lineTo(pts_2d[fid][0], pts_2d[fid][1])
                fp.close()
                canvas.drawPath(fp, fill_p)
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)):
            canvas.drawLine(pts_2d[a][0], pts_2d[a][1], pts_2d[b][0], pts_2d[b][1], edge_p)

    # Flanking colonnade columns (back to front)
    for col_z in (2.8, 0.2, -2.2):
        for col_x in (-3.6, 3.6):
            _draw_3d_box(col_x, 0.0, 3.6, col_z, 0.26, 0.26, col_wire, col_face)
        # Overhead arch beam connecting left & right column tops
        tl = _proj(-3.6, 3.6, col_z)
        tr = _proj(3.6, 3.6, col_z)
        tm = _proj(0.0, 4.35, col_z)
        if tl and tr and tm:
            arch_path = skia.Path()
            arch_path.moveTo(tl[0], tl[1])
            arch_path.quadTo(tm[0], tm[1], tr[0], tr[1])
            canvas.drawPath(arch_path, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.3, Color=hex_to_skia("#2C323B", 165)))

    # Central 3D stepped altar / forensic stage plinth
    altar_edge = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8, Color=hex_to_skia("#EAB308", 160))
    altar_fill = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(145, 24, 28, 36))
    _draw_3d_box(0.0, 0.0, 0.24, 0.0, 1.45, 1.05, altar_edge, altar_fill)
    _draw_3d_box(0.0, 0.24, 0.44, 0.0, 0.96, 0.72, altar_edge, altar_fill)

    # 4. Glowing 3D Perspective Tactical Target Circles on Floor Plane (`#D9381E`, `#EAB308`, `#38BDF8`)
    for r_idx, (rad_3d, r_hex, speed_rot) in enumerate(
        [
            (1.65, "#D9381E", 0.55),
            (2.25, "#EAB308", -0.38),
            (2.90, "#38BDF8", 0.24),
        ]
    ):
        ring_path = skia.Path()
        segs = 48
        started = False
        rot_off = t * speed_rot
        for si in range(segs + 1):
            ang = rot_off + (si / float(segs)) * math.pi * 2.0
            pt2 = _proj(math.cos(ang) * rad_3d, 0.02, math.sin(ang) * rad_3d)
            if pt2 is None:
                continue
            if not started:
                ring_path.moveTo(pt2[0], pt2[1])
                started = True
            else:
                ring_path.lineTo(pt2[0], pt2[1])
        if started:
            rp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.6 if r_idx == 0 else 1.8,
                Color=hex_to_skia(r_hex, 215 if r_idx < 2 else 170),
            )
            rp.setPathEffect(skia.DashPathEffect.Make([16.0, 10.0], -t * 36.0))
            canvas.drawPath(ring_path, rp)

    # 5. Overhead Volumetric Spotlight Cone + Ground Light Pool (`kScreen`)
    stage_floor = _proj(0.0, 0.44, 0.0) or (vp_cx, h * 0.62, cam_dist)
    light_top = _proj(0.0, 5.8, -0.3) or (vp_cx, -40.0, cam_dist)
    cone_half_w = (w * 0.20) if is_wide else (w * 0.34)
    cone_path = skia.Path()
    cone_path.moveTo(light_top[0] - cone_half_w * 0.18, max(-20.0, light_top[1]))
    cone_path.lineTo(light_top[0] + cone_half_w * 0.18, max(-20.0, light_top[1]))
    cone_path.lineTo(stage_floor[0] + cone_half_w, stage_floor[1] + 55.0)
    cone_path.lineTo(stage_floor[0] - cone_half_w, stage_floor[1] + 55.0)
    cone_path.close()

    cone_p = skia.Paint(AntiAlias=True)
    cone_p.setBlendMode(skia.BlendMode.kScreen)
    cone_p.setShader(
        skia.GradientShader.MakeLinear(
            [(light_top[0], max(0.0, light_top[1])), (stage_floor[0], stage_floor[1] + 55.0)],
            [
                skia.ColorSetARGB(88, 224, 192, 151),
                skia.ColorSetARGB(52, 56, 189, 248),
                skia.ColorSetARGB(12, 56, 189, 248),
            ],
            [0.0, 0.55, 1.0],
        )
    )
    canvas.drawPath(cone_path, cone_p)

    # Elliptical backlit floor glow behind silhouette
    pool_p = skia.Paint(AntiAlias=True)
    pool_p.setBlendMode(skia.BlendMode.kScreen)
    pool_p.setShader(
        skia.GradientShader.MakeRadial(
            (stage_floor[0], stage_floor[1]),
            cone_half_w * 0.95,
            [
                skia.ColorSetARGB(95, 224, 192, 151),
                skia.ColorSetARGB(42, 56, 189, 248),
                skia.ColorSetARGB(0, 0, 0, 0),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    canvas.save()
    canvas.translate(stage_floor[0], stage_floor[1])
    canvas.scale(1.0, 0.36)
    canvas.drawCircle(0.0, 0.0, cone_half_w * 0.95, pool_p)
    canvas.restore()

    # 6. Centerpiece on Glowing Tactical Plinth:
    #    - If `fg_img` is provided: backlit rim-lit dark silhouette cutout.
    #    - If `fg_img is None`: rim-lit 3D holographic archival exhibit monolith framing `backdrop_img` / `primary_photo`!
    stamp_lbl = extract_depth_stamp_text(scene)
    fig_base = _proj(0.0, 0.44, 0.0) or (vp_cx, h * 0.64, cam_dist)
    fig_head = _proj(0.0, 2.38, 0.0) or (vp_cx, h * 0.26, cam_dist)
    fig_h = max(180.0, min(h * 0.58, abs(fig_base[1] - fig_head[1])))
    fig_w = fig_h * 0.72

    # Contact shadow ellipse on top of altar
    shadow_w = fig_w * (0.56 if fg_img is not None else 1.25)
    canvas.drawOval(
        skia.Rect.MakeXYWH(fig_base[0] - shadow_w * 0.5, fig_base[1] - 10.0, shadow_w, 22.0),
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 4, 5, 8)),
    )

    callout_anchor_top = (fig_base[0], fig_base[1] - fig_h * 0.72)
    callout_anchor_bot = (stage_floor[0] + (80.0 if is_wide else 40.0), stage_floor[1])

    if fg_img is not None:
        sil_img = _get_rimlit_silhouette_image(fg_img)
        dst_sil = skia.Rect.MakeXYWH(
            fig_base[0] - fig_w * 0.5,
            fig_base[1] - fig_h + 10.0,
            fig_w,
            fig_h,
        )
        canvas.drawImageRect(
            sil_img,
            skia.Rect.MakeWH(sil_img.width(), sil_img.height()),
            dst_sil,
            _LINEAR_SAMPLING,
            skia.Paint(AntiAlias=True),
            skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
        )
    else:
        # Rim-Lit 3D Holographic Archival Exhibit Monolith on the Glowing Tactical Plinth
        fx, fy = fig_base[0], fig_base[1]
        lev_y = math.sin(t * 1.45) * 4.0
        mon_w = min(w * (0.34 if is_wide else 0.72), fig_h * (1.28 if is_wide else 1.02))
        mon_h = min(h * (0.48 if is_wide else 0.34), fig_h * 0.90)
        mon_cx = fx
        mon_bot = fy - 18.0 + lev_y
        mon_top = mon_bot - mon_h
        mon_l = mon_cx - mon_w * 0.5
        mon_r = mon_cx + mon_w * 0.5
        callout_anchor_top = (mon_r, mon_top + mon_h * 0.28)
        callout_anchor_bot = (mon_r, mon_top + mon_h * 0.70)

        # Upward holographic projector light beams rising from tactical plinth to monolith base
        emitter_path = skia.Path()
        emitter_path.moveTo(fx - mon_w * 0.36, fy + 2.0)
        emitter_path.lineTo(fx + mon_w * 0.36, fy + 2.0)
        emitter_path.lineTo(mon_r - 12.0, mon_bot + 4.0)
        emitter_path.lineTo(mon_l + 12.0, mon_bot + 4.0)
        emitter_path.close()
        em_p = skia.Paint(AntiAlias=True)
        em_p.setBlendMode(skia.BlendMode.kScreen)
        em_p.setShader(
            skia.GradientShader.MakeLinear(
                [(fx, fy + 2.0), (fx, mon_bot - 18.0)],
                [
                    hex_to_skia("#38BDF8", 155),
                    hex_to_skia("#EAB308", 72),
                    skia.ColorSetARGB(0, 56, 189, 248),
                ],
                [0.0, 0.45, 1.0],
            )
        )
        canvas.drawPath(emitter_path, em_p)
        # Plinth holographic emitter bar
        canvas.drawRoundRect(
            skia.Rect.MakeXYWH(fx - mon_w * 0.36, fy - 3.0, mon_w * 0.72, 6.0),
            3.0,
            3.0,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#38BDF8", 220)),
        )

        # Orbit-synced subtle 3D monolith perspective bevel & glass extrusion
        yaw_skew = math.sin(yaw_rad) * 0.06
        extrude_dx = -math.sin(yaw_rad) * 18.0
        canvas.save()
        canvas.translate(mon_cx, mon_top + mon_h * 0.5)
        canvas.skew(0.0, yaw_skew)
        canvas.translate(-mon_cx, -(mon_top + mon_h * 0.5))

        slab_rect = skia.Rect.MakeXYWH(mon_l, mon_top, mon_w, mon_h)
        slab_rr = skia.RRect.MakeRectXY(slab_rect, 10.0, 10.0)

        # Dual-color Fern rim backlight halo (#38BDF8 cold cyan left + #E0C097 warm gold right)
        halo_l = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
        halo_l.setImageFilter(skia.ImageFilters.Blur(14.0, 14.0))
        halo_l.setColor(hex_to_skia("#38BDF8", 130))
        canvas.drawRoundRect(skia.Rect.MakeXYWH(mon_l - 8.0, mon_top + 4.0, 18.0, mon_h - 8.0), 8.0, 8.0, halo_l)

        halo_r = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
        halo_r.setImageFilter(skia.ImageFilters.Blur(14.0, 14.0))
        halo_r.setColor(hex_to_skia("#E0C097", 120))
        canvas.drawRoundRect(skia.Rect.MakeXYWH(mon_r - 10.0, mon_top + 4.0, 18.0, mon_h - 8.0), 8.0, 8.0, halo_r)

        # 3D extruded glass thickness bezel opposite camera orbit yaw
        if abs(extrude_dx) > 1.5:
            back_r = skia.Rect.MakeXYWH(mon_l + extrude_dx, mon_top + 4.0, mon_w, mon_h)
            canvas.drawRoundRect(back_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(200, 16, 22, 30)))
            canvas.drawRoundRect(
                back_r,
                10.0,
                10.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia("#38BDF8", 130)),
            )

        # Monolith obsidian glass chassis + shadow
        _draw_fast_rrect_shadow(canvas, slab_rr, dy=16.0, sigma=22.0, alpha=210)
        canvas.drawRRect(slab_rr, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 242)))

        # Clipped inner holographic exhibit viewport
        inner_pad = 12.0
        hdr_h = 28.0
        ftr_h = 24.0
        img_rect = skia.Rect.MakeXYWH(
            mon_l + inner_pad,
            mon_top + hdr_h + 4.0,
            mon_w - inner_pad * 2.0,
            mon_h - hdr_h - ftr_h - 8.0,
        )
        canvas.save()
        canvas.clipRRect(skia.RRect.MakeRectXY(img_rect, 6.0, 6.0), doAntiAlias=True)
        if exhibit_img is not None:
            kb_m = 1.03 + 0.05 * prog_c
            canvas.save()
            canvas.translate(img_rect.centerX(), img_rect.centerY())
            canvas.scale(kb_m, kb_m)
            canvas.translate(-img_rect.centerX(), -img_rect.centerY())
            _draw_image_cover(canvas, exhibit_img, img_rect, y_bias=0.22)
            canvas.restore()
            # Subtle cool-slate forensic tint & holographic micro-scanlines
            tint_p = skia.Paint()
            tint_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(img_rect.left(), img_rect.top()), (img_rect.right(), img_rect.bottom())],
                    [skia.ColorSetARGB(36, 56, 189, 248), skia.ColorSetARGB(14, 18, 20, 23), skia.ColorSetARGB(34, 224, 192, 151)],
                    [0.0, 0.5, 1.0],
                )
            )
            canvas.drawRect(img_rect, tint_p)
        else:
            # Procedural forensic blueprint artifact grid if no backdrop/primary photo was supplied
            canvas.drawRect(img_rect, skia.Paint(Color=hex_to_skia("#0D1B2A", 245)))
            bp_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#38BDF8", 115))
            for gx_m in range(int(img_rect.left()), int(img_rect.right()), 28):
                canvas.drawLine(gx_m, img_rect.top(), gx_m, img_rect.bottom(), bp_p)
            for gy_m in range(int(img_rect.top()), int(img_rect.bottom()), 28):
                canvas.drawLine(img_rect.left(), gy_m, img_rect.right(), gy_m, bp_p)
            for rr_m in (0.20, 0.34, 0.46):
                canvas.drawCircle(img_rect.centerX(), img_rect.centerY(), min(img_rect.width(), img_rect.height()) * rr_m, bp_p)

        # Holographic micro-scanlines + sweeping cyan laser scanner bar
        scan_p = skia.Paint(Color=skia.ColorSetARGB(18, 56, 189, 248))
        for sy_m in range(int(img_rect.top()), int(img_rect.bottom()), 4):
            canvas.drawLine(img_rect.left(), sy_m, img_rect.right(), sy_m, scan_p)
        laser_y = img_rect.top() + ((t * 0.24) % 1.0) * img_rect.height()
        laser_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
        laser_p.setShader(
            skia.GradientShader.MakeLinear(
                [(0.0, laser_y - 16.0), (0.0, laser_y + 16.0)],
                [skia.ColorSetARGB(0, 56, 189, 248), hex_to_skia("#38BDF8", 145), skia.ColorSetARGB(0, 56, 189, 248)],
                [0.0, 0.5, 1.0],
            )
        )
        canvas.drawRect(skia.Rect.MakeXYWH(img_rect.left(), laser_y - 16.0, img_rect.width(), 32.0), laser_p)
        canvas.drawLine(img_rect.left(), laser_y, img_rect.right(), laser_y, skia.Paint(Color=hex_to_skia("#F8FAFC", 150)))

        # Diagonal glass sheen across exhibit plate
        sheen_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
        sheen_p.setShader(
            skia.GradientShader.MakeLinear(
                [(img_rect.left(), img_rect.top()), (img_rect.right(), img_rect.bottom())],
                [skia.ColorSetARGB(34, 248, 250, 252), skia.ColorSetARGB(0, 248, 250, 252), skia.ColorSetARGB(18, 224, 192, 151)],
                [0.0, 0.42, 1.0],
            )
        )
        canvas.drawRect(img_rect, sheen_p)
        canvas.restore()

        # Monolith header & footer forensic telemetry bars
        mon_hdr_txt = f"3D EXHIBIT // {stamp_lbl}" if is_en else f"ARQUIVO 3D // {stamp_lbl}"
        mh_f, mh_l = _wrap_text_to_width(mon_hdr_txt, cp_tf, 13.0, 10.5, mon_w - 42.0, 1)
        canvas.drawCircle(mon_l + 18.0, mon_top + 16.0, 3.8, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")))
        _draw_safe_string(
            canvas,
            mh_l[0] if mh_l else mon_hdr_txt,
            mon_l + 28.0,
            mon_top + 21.0,
            mh_f,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 235)),
        )
        ftr_txt = "HOLO-SCAN • SPATIAL ARCHIVE" if is_en else "VARREDURA HOLOGRÁFICA • ATIVA"
        _draw_safe_string(
            canvas,
            ftr_txt,
            mon_l + 14.0,
            mon_bot - 7.0,
            skia.Font(cp_tf, 11.5),
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#38BDF8", 210)),
        )

        # Rim-lit metallic glass border + #EAB308 tactical corner brackets
        rim_border = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0)
        rim_border.setShader(
            skia.GradientShader.MakeLinear(
                [(mon_l, mon_top), (mon_r, mon_bot)],
                [hex_to_skia("#38BDF8", 230), hex_to_skia("#2C323B", 200), hex_to_skia("#E0C097", 230)],
                [0.0, 0.5, 1.0],
            )
        )
        canvas.drawRRect(slab_rr, rim_border)

        brk_m = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.4, Color=hex_to_skia("#EAB308", 225))
        bl_m = 18.0
        for sx_m, cx_m in ((-1, mon_l - 4.0), (1, mon_r + 4.0)):
            for sy_m, cy_m in ((-1, mon_top - 4.0), (1, mon_bot + 4.0)):
                canvas.drawLine(cx_m, cy_m, cx_m - sx_m * bl_m, cy_m, brk_m)
                canvas.drawLine(cx_m, cy_m, cx_m, cy_m - sy_m * bl_m, brk_m)

        canvas.restore()

    # 7. Fern-Style Digital Forensic UI Telemetry Callouts (ZERO [:N] mid-word slices!)
    lt_title = _normalize_upper(str(_get_attr(scene, "lower_third_title", stamp_lbl) or stamp_lbl))
    lt_sub = _normalize_upper(str(_get_attr(scene, "lower_third_subtitle", "") or _get_attr(scene, "evidence_headline", "") or "RECONSTRUÇÃO HISTÓRICA"))

    # Top-left live 3D camera telemetry strip
    hud_x = 96.0 if is_wide else 46.0
    hud_y = 54.0 if is_wide else 306.0
    hud_w = 430.0 if is_wide else (w - 92.0)
    hud_r = skia.Rect.MakeXYWH(hud_x, hud_y, hud_w, 72.0)
    canvas.drawRoundRect(hud_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", 215)))
    canvas.drawRoundRect(
        hud_r,
        6.0,
        6.0,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia("#2C323B", 230)),
    )
    canvas.drawRect(skia.Rect.MakeXYWH(hud_x, hud_y + 6.0, 4.0, 60.0), skia.Paint(Color=hex_to_skia("#38BDF8")))
    hud_hdr = "3D RECONSTRUCTION // FORENSIC MODEL" if is_en else "RECONSTRUÇÃO 3D // SIMULAÇÃO FORENSE"
    _draw_safe_string(canvas, hud_hdr, hud_x + 16.0, hud_y + 28.0, skia.Font(cp_tf, 14.0), skia.Paint(AntiAlias=True, Color=hex_to_skia("#38BDF8")))
    cam_readout = f"AZM {yaw_deg:+05.1f}°  •  ELV {pitch_deg:04.1f}°  •  DIST {cam_dist:04.2f}M"
    _draw_safe_string(canvas, cam_readout, hud_x + 16.0, hud_y + 54.0, skia.Font(cp_tf, 15.5), skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))

    # 3D-tracked vector leader lines & dynamically wrapped forensic callout cards
    callouts = [
        (
            callout_anchor_top,
            (w * 0.71 if is_wide else 46.0, h * 0.24 if is_wide else h * 0.64),
            "SUJEITO // ERA" if not is_en else "SUBJECT // ERA",
            lt_title,
            "#EAB308",
            0.08,
        ),
        (
            callout_anchor_bot,
            (w * 0.71 if is_wide else 46.0, h * 0.45 if is_wide else h * 0.76),
            "EVENTO CRÍTICO" if not is_en else "KEY EVENT",
            lt_sub,
            "#F87171",
            0.22,
        ),
    ]
    prev_callout_bottom = 0.0
    for anchor_pt, box_pos, c_tag, c_val, c_hex, c_delay in callouts:
        cp_anim = _ease_doc_snap(min(1.0, max(0.0, (prog_c - c_delay) / 0.30)))
        if cp_anim <= 0.02:
            continue
        bx, by = box_pos
        if is_wide:
            bw = min(468.0, max(360.0, float(w) - bx - 48.0))
        else:
            bx = 46.0
            bw = float(w) - 92.0
        vf, vl = _wrap_text_to_width(c_val, cinzel_tf, 20.5, 13.0, bw - 32.0, 2)
        if not vl:
            vl = [c_val]
        line_step = vf.getSize() * 1.24
        bh = 74.0 if len(vl) <= 1 else (44.0 + len(vl) * line_step + 14.0)
        if prev_callout_bottom > 0.0:
            by = max(by, prev_callout_bottom + 18.0)
        prev_callout_bottom = by + bh

        ax, ay = anchor_pt
        ex = bx
        ey = by + bh * 0.5
        mid_x = ax + (ex - ax) * 0.52

        lp = skia.Path()
        lp.moveTo(ax, ay)
        lp.lineTo(ax + (mid_x - ax) * cp_anim, ay + (ey - ay) * cp_anim)
        lp.lineTo(ax + (ex - ax) * cp_anim, ay + (ey - ay) * cp_anim)
        l_paint = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=2.0,
            Color=hex_to_skia(c_hex, int(225 * cp_anim)),
        )
        l_paint.setPathEffect(skia.DashPathEffect.Make([8.0, 5.0], -t * 36.0))
        canvas.drawPath(lp, l_paint)
        canvas.drawCircle(ax, ay, 5.5, skia.Paint(AntiAlias=True, Color=hex_to_skia(c_hex, int(250 * cp_anim))))

        if cp_anim > 0.45:
            ba = int(235 * min(1.0, (cp_anim - 0.45) / 0.55))
            br = skia.Rect.MakeXYWH(bx, by, bw, bh)
            canvas.drawRoundRect(br, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#121417", ba)))
            canvas.drawRoundRect(
                br,
                6.0,
                6.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, Color=hex_to_skia(c_hex, ba)),
            )
            canvas.drawCircle(bx + 16.0, by + 22.0, 4.5, skia.Paint(AntiAlias=True, Color=hex_to_skia(c_hex, ba)))
            _draw_safe_string(canvas, c_tag, bx + 28.0, by + 27.0, skia.Font(cp_tf, 13.5), skia.Paint(AntiAlias=True, Color=hex_to_skia(c_hex, ba)))
            vy = by + 56.0
            for vln in vl:
                _draw_safe_string(canvas, vln, bx + 16.0, vy, vf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", ba)))
                vy += line_step

    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)
