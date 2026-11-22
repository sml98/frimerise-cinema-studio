"""FrimeRise Cinema v6 Pro Motion Graphics Studio (After-Effects / DaVinci-Resolve Grade Skia C++ Renderers).

Implements 7 procedural 30fps C++ Skia motion-design renderers:
  1. `draw_depth_title_behind_subject`: MagnatesMedia / Johnny Harris 3D Depth Title rendered BETWEEN
     2.5D background (`bg_img`) and foreground character (`fg_img`).
  2. `draw_anamorphic_film_burn_and_bokeh`: 2-layer depth particles (14 crisp distant embers + 6 soft radial
     bokeh orbs) + organic 35mm anamorphic light-leak / film-burn sweep on shot cuts (`shot_local_t < 0.24`).
  3. `draw_pro_safezone_lower_third`: Mobile Safe-Zone Lower Third (`y = 192px, x = 46px` in 9:16;
     `y = 74px, x = 68px` in 16:9) with 31px bold gold title, 23px warm bone subtitle, and tight auto-fitted
     obsidian glass pill width (`text_w + 44px`, clamped `<= w - 92px`).
  4. `draw_pro_cartographic_map`: True Dark Cartographic Tactical Map of Europe & Mediterranean with procedural
     vector coastlines, lat/lon graticule ticks (`41°54'N`, `47°16'N`, `51°30'N`), compass rose watermark,
     animated 2.5D camera push-in (`1.00 -> 1.14x`), glowing cubic Bézier route arc with traveling ember head,
     pulsing radar rings, telemetry HUD badge, and tactical PiP video monitor.
  5. `draw_pro_archival_newspaper`: Vox / Johnny Harris archival document card over darkened bokeh backdrop
     with 2.5D camera push-in (`1.00 -> 1.08x`), perspective tilt (`-1.1 deg -> +0.3 deg`), paper fiber grain,
     vintage double-rule masthead (`ARQUIVO HISTÓRICO CONFIDENCIAL`), `1.38:1` top-weighted sepia photo plate
     with corner photo-mount tabs, circular crimson verification seal stamp, and animated highlighter sweep.
  6. `draw_pro_odometer_timeline`: Mechanical Odometer Year Counter that rolls digits vertically between active
     milestone eras + sliding 35mm millimeter ruler tick bar + 4 milestone cards where the active milestone
     (`int(prog * n_pts)`) is illuminated by a radial golden spotlight, scaled up (`1.04x`), and fills an
     animated 0 -> 100% data-impact bar.
  7. `draw_pro_forensic_string_board`: Mindhunter / MagnatesMedia investigation board with 4 Polaroid/dossier
     evidence cards, 3D metallic push-pins + cast shadows, curved catenary Bézier red strings with gravity sag
     and board shadows, and a moving flashlight spotlight (`RadialGradient`) tracking the active evidence card.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

import skia

from engine.skia_compositor import (
     FORBIDDEN_DEBUG_RE,
    _ease_out_cubic,
    _wrap_text_to_width,
    hex_to_skia,
)

_LINEAR_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)

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
# Internal Helpers (Glyph Safety, Easing, Cover Crop, Attribute Access)
# ---------------------------------------------------------------------------
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
        zoom = 1.04 + 0.05 * prog
        pan_x = (prog - 0.5) * -20.0
        canvas.save()
        canvas.clipRect(full_r)
        canvas.translate(w * 0.5 + pan_x, h * 0.5)
        canvas.scale(zoom, zoom)
        img_p = skia.Paint(AntiAlias=True)
        if blur_sigma > 0.5:
            img_p.setImageFilter(skia.ImageFilters.Blur(blur_sigma, blur_sigma))
        _draw_image_cover(
            canvas,
            backdrop_img,
            skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h),
            paint=img_p,
            y_bias=0.30,
        )
        canvas.restore()

    center_a = max(0, min(238, scrim_alpha - 24))
    edge_a = max(0, min(246, scrim_alpha + 26))
    scrim = skia.Paint()
    scrim.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.5, h * 0.45),
            max(w, h) * 0.74,
            [skia.ColorSetARGB(center_a, 14, 10, 24), skia.ColorSetARGB(edge_a, 6, 4, 12)],
        )
    )
    canvas.drawRect(full_r, scrim)
    draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t=1.0, mood=mood)


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

    # 4. Otherwise pick the strongest 1-2 word location/entity token before '•' or ','
    first_seg = re.split(r"[•|—\-:,]", upper_raw)[0].strip()
    stop_words = {"DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS", "O", "A", "OS", "AS", "ANTIGA"}
    words = [w for w in first_seg.split() if w not in stop_words]
    if not words:
        words = first_seg.split()
    stamp = " ".join(words[:2]).strip()
    return stamp[:14] if stamp else "ARQUIVO"


# ---------------------------------------------------------------------------
# 1. Signature 3D Depth Title Behind 2.5D Foreground Subject
# ---------------------------------------------------------------------------
def draw_depth_title_behind_subject(
    canvas: skia.Canvas,
    w: int,
    h: int,
    text: str,
    shot_prog: float,
    t: float,
    title_tf: skia.Typeface,
    mood: str = "dark_horror",
) -> None:
    """Render MagnatesMedia / Johnny Harris 3D Depth Title BETWEEN `bg_img` and `fg_img`
    so the 2.5D foreground subject cutout stands IN FRONT OF the giant typography.
    """
    stamp = extract_depth_stamp_text(text)
    stamp = _sanitize_glyphs(stamp, typeface=title_tf)
    if not stamp:
        return

    prog_clamped = max(0.0, min(1.0, float(shot_prog)))
    # Smooth fade-in and organic depth blend (peak alpha ~198 so it sits naturally in the 3D scene depth)
    fade_in = _ease_out_cubic(min(1.0, prog_clamped / 0.16))
    fade_out = _ease_out_cubic(min(1.0, (1.0 - prog_clamped) / 0.12)) if prog_clamped > 0.88 else 1.0
    base_alpha = int(198 * min(fade_in, fade_out))
    if base_alpha <= 8:
        return

    is_wide = w >= h
    target_max_w = w * (0.78 if is_wide else 0.86)
    font_size = 240.0 if is_wide else 225.0
    min_font_size = 96.0
    font = skia.Font(title_tf, font_size)
    font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)

    measured_w = float(font.measureText(stamp))
    if measured_w > target_max_w and measured_w > 1.0:
        font_size = max(min_font_size, font_size * (target_max_w / measured_w))
        font = skia.Font(title_tf, font_size)
        font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        measured_w = float(font.measureText(stamp))

    # Inverse horizontal parallax drift (opposes foreground subject motion for strong 2.5D depth separation)
    drift_x = (prog_clamped - 0.5) * -22.0
    drift_y = (prog_clamped - 0.5) * -5.0 + math.sin(t * 1.4) * 2.0
    depth_scale = 0.96 + 0.05 * prog_clamped

    center_x = w * 0.5 + drift_x
    baseline_y = h * (0.37 if is_wide else 0.34) + drift_y

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))
    top_y = baseline_y - ascent
    bot_y = baseline_y + descent

    canvas.save()
    canvas.translate(center_x, baseline_y - ascent * 0.45)
    canvas.scale(depth_scale, depth_scale)
    canvas.translate(-center_x, -(baseline_y - ascent * 0.45))

    draw_x = center_x - measured_w * 0.5

    # 1. Atmospheric back-glow behind the giant letters to separate them from dark backgrounds
    mood_norm = str(mood or "dark_horror").lower()
    is_crimson_mood = mood_norm in ("dark_horror", "investigative_crime")
    glow_col = (
        skia.ColorSetARGB(int(base_alpha * 0.42), 158, 27, 36)
        if is_crimson_mood
        else skia.ColorSetARGB(int(base_alpha * 0.38), 212, 175, 55)
    )
    halo_r = skia.Rect.MakeXYWH(
        center_x - measured_w * 0.58,
        top_y - 36.0,
        measured_w * 1.16,
        (bot_y - top_y) + 72.0,
    )
    halo_p = skia.Paint(AntiAlias=True)
    halo_p.setShader(
        skia.GradientShader.MakeRadial(
            (center_x, (top_y + bot_y) * 0.5),
            max(120.0, measured_w * 0.62),
            [glow_col, skia.ColorSetARGB(0, 10, 6, 16)],
        )
    )
    canvas.drawRect(halo_r, halo_p)

    # 2. Deep 3D extrusion / soft dark drop shadow
    shadow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(base_alpha * 0.92), 6, 4, 12))
    shadow_p.setImageFilter(
        skia.ImageFilters.DropShadow(
            0.0,
            16.0,
            28.0,
            28.0,
            skia.ColorSetARGB(int(base_alpha * 0.92), 0, 0, 0),
        )
    )
    _draw_safe_string(canvas, stamp, draw_x, baseline_y + 6.0, font, shadow_p)

    # 3. Warm Gold / Crimson Vertical Gradient Fill (#FFE082 -> #D4AF37 or #FFE082 -> #D4AF37 -> #9E1B24)
    if is_crimson_mood:
        grad_colors = [
            hex_to_skia("#FFE082", base_alpha),
            hex_to_skia("#D4AF37", base_alpha),
            hex_to_skia("#9E1B24", int(base_alpha * 0.96)),
        ]
        grad_pos = [0.0, 0.58, 1.0]
    else:
        grad_colors = [
            hex_to_skia("#FFF3C4", base_alpha),
            hex_to_skia("#FFE082", base_alpha),
            hex_to_skia("#D4AF37", base_alpha),
        ]
        grad_pos = [0.0, 0.52, 1.0]

    fill_p = skia.Paint(AntiAlias=True)
    fill_p.setShader(
        skia.GradientShader.MakeLinear(
            [(center_x, top_y), (center_x, bot_y)],
            grad_colors,
            grad_pos,
        )
    )
    _draw_safe_string(canvas, stamp, draw_x, baseline_y, font, fill_p)

    # 4. Thin crisp specular rim stroke
    stroke_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.2,
        Color=hex_to_skia("#FFF5D6", int(base_alpha * 0.68)),
    )
    _draw_safe_string(canvas, stamp, draw_x, baseline_y, font, stroke_p)

    canvas.restore()


# ---------------------------------------------------------------------------
# 2. 35mm Anamorphic Film-Burn Light Leak & 2-Layer Bokeh / Embers
# ---------------------------------------------------------------------------
def draw_anamorphic_film_burn_and_bokeh(
    canvas: skia.Canvas,
    w: int,
    h: int,
    t: float,
    shot_local_t: float,
    mood: str = "dark_horror",
) -> None:
    """Render 2-layer depth particles (14 small crisp distant embers + 6 larger soft radial bokeh orbs)
    plus an organic 35mm anamorphic light-leak / film-burn sweep on the first 0.24s of a shot cut.
    """
    mood_norm = str(mood or "dark_horror").lower()
    is_dark = mood_norm in ("dark_horror", "investigative_crime", "epic_history")

    # Layer 1: 14 small crisp distant embers drifting upwards
    for i in range(14):
        speed_x = 18.0 + (i % 5) * 6.5
        speed_y = 22.0 + (i % 4) * 8.0
        phase = i * 1.37
        ex = ((i * 197.0 + t * speed_x + math.sin(t * 1.8 + phase) * 18.0) % max(1.0, float(w)))
        ey = ((i * 139.0 - t * speed_y) % max(1.0, float(h)))
        flicker = 0.55 + 0.45 * math.sin(t * 4.6 + phase)
        rad = 1.6 + (i % 3) * 0.95
        ember_alpha = int((76 if is_dark else 58) * flicker)
        if i % 3 == 0:
            col = skia.ColorSetARGB(ember_alpha, 255, 122, 48)  # Torch ember orange-crimson
        else:
            col = skia.ColorSetARGB(ember_alpha, 255, 214, 112)  # Candlelight gold
        canvas.drawCircle(ex, ey, rad, skia.Paint(AntiAlias=True, Color=col))

    # Layer 2: 6 larger soft radial-gradient out-of-focus bokeh orbs drifting slowly across the lens
    for bi in range(6):
        b_phase = bi * 2.09
        bx = ((bi * 311.0 + t * (9.0 + (bi % 3) * 4.0) + math.cos(t * 0.7 + b_phase) * 32.0) % (w + 160.0)) - 80.0
        by = ((bi * 257.0 - t * (7.5 + (bi % 2) * 3.5) + math.sin(t * 0.6 + b_phase) * 24.0) % (h + 160.0)) - 80.0
        b_rad = (36.0 + (bi % 3) * 18.0) * (1.0 + 0.08 * math.sin(t * 1.3 + b_phase))
        pulse = 0.65 + 0.35 * math.sin(t * 1.9 + b_phase)
        core_a = int(30 * pulse)
        mid_a = int(16 * pulse)
        if bi % 2 == 0:
            c0 = skia.ColorSetARGB(core_a, 255, 209, 102)
            c1 = skia.ColorSetARGB(mid_a, 217, 119, 6)
        else:
            c0 = skia.ColorSetARGB(core_a, 225, 75, 62)
            c1 = skia.ColorSetARGB(mid_a, 158, 27, 36)
        bokeh_p = skia.Paint(AntiAlias=True)
        bokeh_p.setBlendMode(skia.BlendMode.kScreen)
        bokeh_p.setShader(
            skia.GradientShader.MakeRadial(
                (bx, by),
                b_rad,
                [c0, c1, skia.ColorSetARGB(0, 0, 0, 0)],
                [0.0, 0.58, 1.0],
            )
        )
        canvas.drawCircle(bx, by, b_rad, bokeh_p)

    # Layer 3: Organic 35mm Anamorphic Film-Burn / Light-Leak Sweep on Shot Cuts (`0 <= shot_local_t < 0.24`)
    if 0.0 <= float(shot_local_t) < 0.24:
        u = float(shot_local_t) / 0.24
        # Smooth organic flash envelope: fast attack + warm film decay
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
                        skia.ColorSetARGB(int(165 * env), 255, 226, 142),  # Hot amber-gold filament core
                        skia.ColorSetARGB(int(118 * env), 224, 98, 36),    # 35mm halide orange burn
                        skia.ColorSetARGB(int(72 * env), 158, 27, 36),     # Deep crimson edge halation
                        skia.ColorSetARGB(0, 0, 0, 0),
                    ],
                    [0.0, 0.34, 0.68, 1.0],
                )
            )
            canvas.drawRect(full_r, burn_p)

            # Secondary anamorphic horizontal lens flare streak
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


# ---------------------------------------------------------------------------
# 3. Mobile Safe-Zone Auto-Fitted Lower Third Badge (Fixes #98 Finding #1)
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
    """Render sleek Mobile Safe-Zone Lower Third:
    - In 9:16 (`w < h`): `y = 192px, x = 46px` (well below TikTok/Reels/Shorts top UI dead zone!).
    - In 16:9 (`w >= h`): `y = 74px, x = 68px`.
    - Crisp 31px bold gold title (`#FFD166`) + 23px warm bone subtitle (`#F4EFE6`).
    - Tightly auto-fitted dark obsidian glass pill width (`measured_text_w + 44px`, clamped `<= w - 92px`).
    """
    vis_dur = min(max(0.5, float(body_dur)), float(max_display_s))
    if body_t < 0.0 or body_t >= vis_dur:
        return

    clean_title = _sanitize_glyphs(_normalize_upper(title), typeface=title_tf)
    clean_sub = _sanitize_glyphs(_normalize_upper(subtitle), typeface=ui_tf)
    if not clean_title and not clean_sub:
        return

    enter = _ease_out_cubic(min(1.0, body_t / 0.36))
    exit_a = _ease_out_cubic(min(1.0, (vis_dur - body_t) / 0.36)) if (vis_dur - body_t) < 0.36 else 1.0
    alpha = int(242 * min(enter, exit_a))
    if alpha <= 8:
        return

    is_wide = w >= h
    base_x = 68.0 if is_wide else 46.0
    base_y = 74.0 if is_wide else 192.0
    max_pill_w = float(w) - 92.0
    max_text_w = max(160.0, max_pill_w - 44.0)

    # Measure & auto-fit 31px title and 23px subtitle
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

    # 1. Deep obsidian glass pill with drop shadow
    bg_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.90), 11, 8, 20))
    bg_p.setImageFilter(
        skia.ImageFilters.DropShadow(0.0, 10.0, 22.0, 22.0, skia.ColorSetARGB(int(alpha * 0.75), 0, 0, 0))
    )
    canvas.drawRRect(pill_rr, bg_p)

    # Subtle obsidian-gold specular glass border
    border_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.5,
        Color=hex_to_skia("#FFD166", int(alpha * 0.42)),
    )
    canvas.drawRRect(pill_rr, border_p)

    # 2. Animated 6px vertical crimson-gold accent bar on left edge
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

    # 3. Crisp 31px Gold Title (#FFD166) & 23px Warm Bone Subtitle (#F4EFE6)
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
# Procedural normalized (0..1, 0..1) coastline polygons for Europe & Mediterranean
_EUROPE_LANDMASS_POLYS: List[List[Tuple[float, float]]] = [
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
    # Anatolia / Asia Minor (Myra at ~0.78, 0.68) & Levant
    [
        (0.72, 0.52), (0.82, 0.49), (0.95, 0.48), (0.97, 0.76),
        (0.89, 0.78), (0.86, 0.69), (0.79, 0.70), (0.73, 0.66),
        (0.71, 0.58),
    ],
    # North Africa Mediterranean Coastline
    [
        (0.08, 0.76), (0.24, 0.73), (0.38, 0.72), (0.44, 0.77),
        (0.56, 0.82), (0.72, 0.84), (0.88, 0.83), (0.95, 0.94),
        (0.06, 0.94),
    ],
]

_CITY_GEO_COORDS: List[Tuple[Tuple[str, ...], Tuple[float, float], str]] = [
    (("ROMA", "ROME", "ITÁLIA", "ITALY", "VATICANO", "SATURNALIA"), (0.465, 0.565), "41°54'N 12°29'E"),
    (("MIRA", "MYRA", "ÁSIA MENOR", "ASIA MINOR", "ANATÓLIA", "ANATOLIA", "LICIA", "TURQUIA"), (0.785, 0.675), "36°15'N 29°59'E"),
    (("ALPES", "ALPS", "ÁUSTRIA", "AUSTRIA", "TIROL", "BAVIERA", "KRAMPUS"), (0.465, 0.395), "47°16'N 11°24'E"),
    (("LONDRES", "LONDON", "INGLATERRA", "ENGLAND", "BRITÂNICO", "PURITANO", "CROMWELL"), (0.268, 0.275), "51°30'N 00°07'W"),
    (("MILÃO", "MILAN"), (0.425, 0.455), "45°28'N 09°11'E"),
    (("PARIS", "FRANÇA", "FRANCE"), (0.315, 0.355), "48°51'N 02°21'E"),
    (("HERZOGENAURACH", "ALEMANHA", "GERMANY", "BERLIM", "BERLIN"), (0.485, 0.315), "49°34'N 10°53'E"),
    (("VILNIUS", "LITUÂNIA", "LITHUANIA", "LETÔNIA", "LATVIA"), (0.685, 0.235), "54°41'N 25°16'E"),
    (("ATENAS", "ATHENS", "GRÉCIA", "GREECE", "NICEIA"), (0.655, 0.625), "37°59'N 23°43'E"),
]


def _resolve_city_map_point(
    name: str,
    default_uv: Tuple[float, float],
    default_coord: str,
) -> Tuple[Tuple[float, float], str]:
    up = _normalize_upper(name)
    for keys, uv, coord_str in _CITY_GEO_COORDS:
        for k in keys:
            if k in up:
                return uv, coord_str
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
        Color=skia.ColorSetARGB(72, 212, 175, 55),
    )
    canvas.drawCircle(cx, cy, radius, ring_p)
    canvas.drawCircle(cx, cy, radius * 0.72, ring_p)

    # 4 cardinal points + 4 intercardinal ticks
    star_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(88, 212, 175, 55))
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
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(140, 255, 209, 102)),
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
    ent = _ease_out_back(min(1.0, max(0.0, (body_t - 0.08) / 0.44)))
    sc = 0.84 + 0.16 * ent

    canvas.save()
    canvas.translate(cx, cy)
    canvas.scale(sc, sc)

    r = skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, pip_h)
    rr = skia.RRect.MakeRectXY(r, 16.0, 16.0)

    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(242, 8, 7, 15))
    sh_p.setImageFilter(skia.ImageFilters.DropShadow(0.0, 18.0, 36.0, 36.0, skia.ColorSetARGB(220, 0, 0, 0)))
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
                [skia.ColorSetARGB(255, 24, 20, 38), skia.ColorSetARGB(255, 10, 8, 18)],
            )
        )
        canvas.drawRect(r, grad)

    # Scanlines + top/bottom HUD scrims
    scan_p = skia.Paint(Color=skia.ColorSetARGB(24, 0, 0, 0))
    for sy in range(int(-pip_h * 0.5), int(pip_h * 0.5), 4):
        canvas.drawLine(-pip_w * 0.5, sy, pip_w * 0.5, sy, scan_p)

    top_scrim = skia.Paint()
    top_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, -pip_h * 0.5), (0.0, -pip_h * 0.5 + 56.0)],
            [skia.ColorSetARGB(185, 8, 6, 15), skia.ColorSetARGB(0, 8, 6, 15)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, 56.0), top_scrim)

    bot_scrim = skia.Paint()
    bot_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, pip_h * 0.5 - 56.0), (0.0, pip_h * 0.5)],
            [skia.ColorSetARGB(0, 8, 6, 15), skia.ColorSetARGB(200, 8, 6, 15)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, pip_h * 0.5 - 56.0, pip_w, 56.0), bot_scrim)

    # Corner target reticles
    ret_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.4,
        Color=hex_to_skia("#FFD166", 210),
    )
    blen = 22.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            rx_c = sx * (pip_w * 0.5 - 14.0)
            ry_c = sy * (pip_h * 0.5 - 14.0)
            canvas.drawLine(rx_c, ry_c, rx_c - sx * blen, ry_c, ret_p)
            canvas.drawLine(rx_c, ry_c, rx_c, ry_c - sy * blen, ret_p)

    # Center subtle target crosshair reticle
    ch_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.2,
        Color=skia.ColorSetARGB(72, 255, 209, 102),
    )
    canvas.drawCircle(0.0, 0.0, 24.0, ch_p)
    canvas.drawLine(-34.0, 0.0, -12.0, 0.0, ch_p)
    canvas.drawLine(12.0, 0.0, 34.0, 0.0, ch_p)
    canvas.drawLine(0.0, -34.0, 0.0, -12.0, ch_p)
    canvas.drawLine(0.0, 12.0, 0.0, 34.0, ch_p)

    # Top-left blinking REC telemetry pill
    rec_txt = "REC • TACTICAL FEED" if is_en else "REC • MONITOR TÁTICO"
    rf, rl = _wrap_text_to_width(rec_txt, ui_tf, 15.0, 11.0, pip_w - 60.0, 1)
    r_str = rl[0] if rl else rec_txt
    rw = float(rf.measureText(r_str))
    pill_r = skia.Rect.MakeXYWH(-pip_w * 0.5 + 18.0, -pip_h * 0.5 + 16.0, rw + 42.0, 28.0)
    canvas.drawRoundRect(pill_r, 7.0, 7.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(210, 11, 8, 18)))
    blink = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 7.2))
    canvas.drawCircle(
        pill_r.left() + 14.0,
        pill_r.centerY(),
        5.0,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(255 * blink), 220, 38, 56)),
    )
    _draw_safe_string(canvas, r_str, pill_r.left() + 26.0, pill_r.top() + 19.5, rf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

    # Bottom coordinate & location telemetry bar
    bot_txt = f"{_normalize_upper(label_text)}  •  {coord_text}"
    bf, bl = _wrap_text_to_width(bot_txt, ui_tf, 16.0, 12.0, pip_w - 40.0, 1)
    if bl:
        _draw_safe_string(
            canvas,
            bl[0],
            -pip_w * 0.5 + 20.0,
            pip_h * 0.5 - 16.0,
            bf,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")),
        )

    canvas.restore()
    canvas.drawRRect(
        rr,
        skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=2.5,
            Color=hex_to_skia("#D4AF37", 215),
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
    """Render Dark Cartographic Tactical Map of Europe & Mediterranean with procedural coastlines,
    degree graticules ('41°54'N', '47°16'N', '51°30'N'), compass rose watermark, animated 2.5D camera
    push-in (1.0 -> 1.14x), glowing cubic Bézier route arc with traveling ember head, pulsing radar
    rings, sleek coordinate telemetry badge, and tactical PiP video monitor.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    _draw_dark_bokeh_backdrop(canvas, w, h, backdrop_img, prog, t, scrim_alpha=172, blur_sigma=4.0, mood=mood)

    is_wide = w >= h
    if is_wide:
        map_w = w * 0.90
        map_h = 668.0
        mx = (w - map_w) * 0.5
        my = 190.0
        pip_w, pip_h = 470.0, 266.0
        pip_cx = mx + map_w - pip_w * 0.5 - 24.0
        pip_cy = my + map_h - pip_h * 0.5 - 24.0
        # Map geographic space leaves clear top margin for HUD and clear right margin for PiP monitor
        geo_x0 = mx + 28.0
        geo_w = map_w - pip_w - 64.0
        geo_y0 = my + 104.0
        geo_h = map_h - 132.0
    else:
        # 9:16 Safe Zone: starts at y=308px (below lower-third badge at y=192..292) and leaves room for PiP below
        map_w = w - 92.0
        map_h = 684.0
        mx = 46.0
        my = 308.0
        pip_w = w - 124.0
        pip_h = 406.0
        pip_cx = w * 0.5
        pip_cy = my + map_h + 24.0 + pip_h * 0.5
        # Map geographic space sits cleanly below the top telemetry HUD banner (my + 108..map_h - 24)
        geo_x0 = mx + 18.0
        geo_w = map_w - 36.0
        geo_y0 = my + 108.0
        geo_h = map_h - 134.0

    map_r = skia.Rect.MakeXYWH(mx, my, map_w, map_h)
    map_rr = skia.RRect.MakeRectXY(map_r, 20.0, 20.0)

    # Outer dark obsidian cartographic frame + shadow
    frame_shadow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(242, 9, 12, 22))
    frame_shadow.setImageFilter(skia.ImageFilters.DropShadow(0.0, 20.0, 40.0, 40.0, skia.ColorSetARGB(225, 0, 0, 0)))
    canvas.drawRRect(map_rr, frame_shadow)

    orig_name = str(_get_attr(scene, "map_origin", "ROMA") or "ROMA")
    dest_name = str(_get_attr(scene, "map_destination", "LONDRES") or "LONDRES")
    metric_txt = str(_get_attr(scene, "map_metric", "ROTA HISTÓRICA") or "ROTA HISTÓRICA")

    uv_orig, coord_orig = _resolve_city_map_point(orig_name, (0.465, 0.565), "41°54'N 12°29'E")
    uv_dest, coord_dest = _resolve_city_map_point(dest_name, (0.268, 0.275), "51°30'N 00°07'W")
    if math.hypot(uv_orig[0] - uv_dest[0], uv_orig[1] - uv_dest[1]) < 0.08:
        uv_orig = (0.465, 0.565)
        uv_dest = (0.268, 0.275)

    p_orig = (geo_x0 + geo_w * uv_orig[0], geo_y0 + geo_h * uv_orig[1])
    p_dest = (geo_x0 + geo_w * uv_dest[0], geo_y0 + geo_h * uv_dest[1])

    # Cubic Bézier control points arching smoothly over Europe (clamped inside map geo zone)
    mid_x = (p_orig[0] + p_dest[0]) * 0.5
    mid_y = (p_orig[1] + p_dest[1]) * 0.5
    dist = math.hypot(p_dest[0] - p_orig[0], p_dest[1] - p_orig[1])
    arc_lift = max(55.0, min(145.0, dist * 0.30))
    min_ctrl_y = geo_y0 + 18.0
    c1 = (p_orig[0] + (mid_x - p_orig[0]) * 0.55, max(min_ctrl_y, min(p_orig[1], mid_y) - arc_lift * 0.85))
    c2 = (p_dest[0] + (mid_x - p_dest[0]) * 0.55, max(min_ctrl_y, min(p_dest[1], mid_y) - arc_lift * 0.95))

    route_prog = _ease_in_out_cubic(min(1.0, max(0.08, prog * 1.18)))

    # Evaluate current cubic Bézier tip `(tip_x, tip_y)`
    u = route_prog
    iu = 1.0 - u
    tip_x = (iu ** 3) * p_orig[0] + 3 * (iu ** 2) * u * c1[0] + 3 * iu * (u ** 2) * c2[0] + (u ** 3) * p_dest[0]
    tip_y = (iu ** 3) * p_orig[1] + 3 * (iu ** 2) * u * c1[1] + 3 * iu * (u ** 2) * c2[1] + (u ** 3) * p_dest[1]

    # Animated 2.5D camera push-in (scale 1.00 -> 1.14) tracking along the route
    cam_scale = 1.00 + 0.14 * _ease_in_out_cubic(prog)
    cam_focus_x = p_orig[0] + (p_dest[0] - p_orig[0]) * (0.25 + 0.50 * route_prog)
    cam_focus_y = p_orig[1] + (p_dest[1] - p_orig[1]) * (0.25 + 0.50 * route_prog)
    map_cx = geo_x0 + geo_w * 0.5
    map_cy = geo_y0 + geo_h * 0.5
    pan_x = (map_cx - cam_focus_x) * 0.18 * prog
    pan_y = (map_cy - cam_focus_y) * 0.18 * prog

    canvas.save()
    canvas.clipRRect(map_rr, doAntiAlias=True)

    # Dark parchment / obsidian sea canvas
    sea_p = skia.Paint()
    sea_p.setShader(
        skia.GradientShader.MakeRadial(
            (mx + map_w * 0.5, my + map_h * 0.5),
            max(map_w, map_h) * 0.75,
            [skia.ColorSetARGB(255, 18, 24, 42), skia.ColorSetARGB(255, 8, 11, 20)],
        )
    )
    canvas.drawRect(map_r, sea_p)

    # Apply 2.5D camera push-in transform for map geometry & route
    canvas.save()
    canvas.translate(map_cx + pan_x, map_cy + pan_y)
    canvas.scale(cam_scale, cam_scale)
    canvas.translate(-map_cx, -map_cy)

    # 1. Procedural Europe & Mediterranean Coastline Vector Silhouettes
    land_fill = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235, 29, 36, 56))
    coast_glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=5.5,
        Color=skia.ColorSetARGB(52, 212, 175, 55),
    )
    coast_stroke = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.7,
        Color=skia.ColorSetARGB(175, 188, 162, 106),
    )

    for poly in _EUROPE_LANDMASS_POLYS:
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

    # 2. Compass Rose Watermark
    _draw_compass_rose(
        canvas,
        mx + map_w * (0.88 if is_wide else 0.86),
        my + map_h * (0.22 if is_wide else 0.25),
        44.0 if is_wide else 40.0,
        ui_tf,
    )

    # 3. Pulsing Concentric Radar Rings at Origin & Destination Pins
    for pin_xy, ring_hex in ((p_orig, "#D4AF37"), (p_dest, "#E63946")):
        for r_base in (22.0, 46.0, 74.0):
            r_cur = r_base + ((t * 26.0) % 24.0)
            fade_r = max(0.0, 1.0 - (r_cur / 98.0))
            rp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=1.8,
                Color=hex_to_skia(ring_hex, int(155 * fade_r)),
            )
            canvas.drawCircle(pin_xy[0], pin_xy[1], r_cur, rp)

    # 4. Glowing Cubic Bézier Route Arc + Animated Traveling Ember Head
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

    outer_glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=12.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(130, 185, 28, 38),
    )
    outer_glow.setImageFilter(skia.ImageFilters.Blur(6.0, 6.0))
    canvas.drawPath(route_path, outer_glow)

    core_arc = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4.5,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#FFD166"),
    )
    core_arc.setPathEffect(skia.DashPathEffect.Make([16.0, 10.0], -t * 64.0))
    canvas.drawPath(route_path, core_arc)

    # Traveling Ember Head along the Cubic Bézier tip
    ember_halo = skia.Paint(AntiAlias=True)
    ember_halo.setShader(
        skia.GradientShader.MakeRadial(
            (tip_x, tip_y),
            24.0,
            [
                skia.ColorSetARGB(235, 255, 230, 140),
                skia.ColorSetARGB(160, 230, 57, 70),
                skia.ColorSetARGB(0, 158, 27, 36),
            ],
            [0.0, 0.45, 1.0],
        )
    )
    canvas.drawCircle(tip_x, tip_y, 24.0, ember_halo)
    canvas.drawCircle(tip_x, tip_y, 6.5, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

    coord_font = skia.Font(ui_tf, 12.5)
    # Origin & Destination Pins + Crisp Callout Badges
    for is_dest, pin_pt, city_lbl, city_coord in (
        (False, p_orig, orig_name, coord_orig),
        (True, p_dest, dest_name, coord_dest),
    ):
        pin_col = "#E63946" if is_dest else "#D4AF37"
        canvas.drawCircle(pin_pt[0], pin_pt[1], 11.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(pin_col)))
        canvas.drawCircle(pin_pt[0], pin_pt[1], 4.8, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

        c_clean = _sanitize_glyphs(_normalize_upper(city_lbl), typeface=title_tf)
        cf, cl = _wrap_text_to_width(c_clean, title_tf, 22.0, 15.0, 240.0, 1)
        c_str = cl[0] if cl else c_clean
        cw = float(cf.measureText(c_str))
        tag_w = max(136.0, cw + 28.0)
        tag_h = 46.0
        tx = max(geo_x0 + 12.0, min(geo_x0 + geo_w - tag_w - 12.0, pin_pt[0] - tag_w * 0.5))
        ty = pin_pt[1] + 18.0 if pin_pt[1] < (geo_y0 + geo_h * 0.72) else (pin_pt[1] - tag_h - 18.0)

        tag_r = skia.Rect.MakeXYWH(tx, ty, tag_w, tag_h)
        canvas.drawRoundRect(tag_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(226, 10, 12, 22)))
        canvas.drawRoundRect(
            tag_r,
            8.0,
            8.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.6, Color=hex_to_skia(pin_col, 210)),
        )
        _draw_safe_string(canvas, c_str, tx + 14.0, ty + 22.0, cf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166" if is_dest else "#F4EFE6")))
        _draw_safe_string(canvas, city_coord, tx + 14.0, ty + 39.0, coord_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 212, 175, 55)))

    canvas.restore()  # End 2.5D camera push-in

    # 5. Latitude / Longitude Graticule Lines + Degree Coordinate Ticks (drawn in viewport space so ticks never clip!)
    grat_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.0,
        Color=skia.ColorSetARGB(42, 212, 175, 55),
    )
    coord_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(170, 214, 195, 150))

    lat_ticks = [
        (0.27, "51°30'N"),
        (0.41, "47°16'N"),
        (0.57, "41°54'N"),
        (0.71, "36°15'N"),
    ]
    for ry_norm, lat_lbl in lat_ticks:
        gy = geo_y0 + geo_h * ry_norm
        canvas.drawLine(mx, gy, mx + map_w, gy, grat_p)
        _draw_safe_string(canvas, lat_lbl, mx + 14.0, gy - 6.0, coord_font, coord_paint)

    lon_ticks = [
        (0.26, "00°07'W"),
        (0.47, "12°29'E"),
        (0.65, "23°43'E"),
        (0.81, "29°59'E"),
    ]
    for rx_norm, lon_lbl in lon_ticks:
        gx = geo_x0 + geo_w * rx_norm
        canvas.drawLine(gx, my, gx, my + map_h, grat_p)
        _draw_safe_string(canvas, lon_lbl, gx + 6.0, my + map_h - 12.0, coord_font, coord_paint)

    # 6. Top-Left Coordinate Telemetry Callout Badge (`scene.map_metric`)
    hud_w = min(map_w - 44.0, 520.0 if is_wide else (map_w - 44.0))
    hud_h = 84.0
    hud_r = skia.Rect.MakeXYWH(mx + 22.0, my + 20.0, hud_w, hud_h)
    canvas.drawRoundRect(hud_r, 12.0, 12.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(226, 10, 12, 22)))
    canvas.drawRoundRect(
        hud_r,
        12.0,
        12.0,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#D4AF37", 220)),
    )
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(mx + 30.0, my + 30.0, 5.0, hud_h - 20.0),
        2.5,
        2.5,
        skia.Paint(AntiAlias=True, Color=hex_to_skia("#9E1B24")),
    )

    tele_hdr = f"CARTOGRAPHIC TELEMETRY • {coord_orig} -> {coord_dest}" if is_en else f"TELEMETRIA CARTOGRÁFICA • {coord_orig} -> {coord_dest}"
    th_f, th_l = _wrap_text_to_width(tele_hdr, ui_tf, 14.5, 11.0, hud_w - 44.0, 1)
    if th_l:
        _draw_safe_string(canvas, th_l[0], mx + 44.0, my + 44.0, th_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F4EFE6", 210)))

    mf, ml = _wrap_text_to_width(_normalize_upper(metric_txt), title_tf, 28.0, 18.0, hud_w - 44.0, 1)
    if ml:
        _draw_safe_string(canvas, ml[0], mx + 44.0, my + 76.0, mf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

    canvas.restore()  # End map clipRRect

    # Crisp antique gold outer border around tactical map
    canvas.drawRRect(
        map_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#D4AF37", 195)),
    )

    # 7. Tactical PiP Video Monitor with Corner Target Reticles
    _draw_tactical_pip_monitor(
        canvas=canvas,
        pip_img=pip_img or backdrop_img,
        cx=pip_cx,
        cy=pip_cy,
        pip_w=pip_w,
        pip_h=pip_h,
        label_text=f"{orig_name} -> {dest_name}",
        coord_text=coord_dest,
        body_t=body_t,
        t=t,
        ui_tf=ui_tf,
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
        paper_h = 656.0
        py = 194.0
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
        bottom_pad = 32.0
        max_paper_h = 1140.0
        raw_paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        if raw_paper_h > max_paper_h:
            v_photo_h = max(round(inner_w / 1.44), v_photo_h - (raw_paper_h - max_paper_h))
        paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        # Place below mobile safe-zone lower third (y=192..292) and above bottom captions (y~1520)
        py = max(302.0, min(340.0, (1480.0 - 302.0 - paper_h) * 0.5 + 302.0))

    # 2.5D camera push-in (1.00 -> 1.08x) and gentle perspective tilt (-1.1 deg -> +0.3 deg)
    ent = _ease_out_cubic(min(1.0, body_t / 0.38))
    cam_scale = (0.94 + 0.06 * ent) * (1.00 + 0.08 * prog)
    tilt_deg = -1.1 + 1.4 * prog

    canvas.save()
    canvas.translate(w * 0.5, py + paper_h * 0.5)
    canvas.scale(cam_scale, cam_scale)
    canvas.rotate(tilt_deg)

    p_rect = skia.Rect.MakeXYWH(-paper_w * 0.5, -paper_h * 0.5, paper_w, paper_h)
    p_rr = skia.RRect.MakeRectXY(p_rect, 12.0, 12.0)

    # 1. Floating aged parchment card with deep cinema drop shadow
    shadow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 242, 234, 217))
    shadow_p.setImageFilter(skia.ImageFilters.DropShadow(0.0, 26.0, 48.0, 48.0, skia.ColorSetARGB(230, 0, 0, 0)))
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
    for fx_i in range(int(-paper_w * 0.5), int(paper_w * 0.5), 29):
        canvas.drawLine(fx_i, -paper_h * 0.5, fx_i, paper_h * 0.5, skia.Paint(Color=skia.ColorSetARGB(9, 70, 52, 34)))

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
    mast_font, mast_lns = _wrap_text_to_width(mast_txt, ui_tf, 21.0, 14.0, inner_w, 1)
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

    sweep_total = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.05) / 0.66)))

    if is_wide:
        photo_col_w = inner_w * 0.43
        gap_col = inner_w * 0.03
        quote_col_x = left_x + photo_col_w + gap_col
        quote_col_w = inner_w - photo_col_w - gap_col

        photo_h = min(content_h - 30.0, round(photo_col_w / 1.38))
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, photo_col_w, photo_h)
        _draw_archival_sepia_plate_with_mounts(canvas, photo_img or backdrop_img, photo_rect)

        cap_str = f"EXHIBIT • {lt_title}" if is_en else f"PRANCHA DE ARQUIVO • {lt_title}"
        cf, cl = _wrap_text_to_width(cap_str, ui_tf, 15.0, 11.5, photo_col_w, 1)
        if cl:
            _draw_safe_string(canvas, cl[0], left_x, content_top + photo_h + 22.0, cf, ink_muted)

        q_font, q_lines = _wrap_text_to_width(quote_txt, ui_tf, 29.0, 18.0, quote_col_w - 44.0, 4)
        line_step = q_font.getSize() * 1.40
        q_box_h = min(content_h - 14.0, max(1, len(q_lines)) * line_step + 46.0)
        q_box_y = content_top + max(4.0, (content_h - q_box_h) * 0.35)

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
                    (lw + 16.0) * line_prog,
                    q_font.getSize() * 1.18,
                )
                hl_p = skia.Paint(AntiAlias=True)
                hl_p.setBlendMode(skia.BlendMode.kMultiply)
                hl_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(hl_rect.left(), hl_rect.top()), (hl_rect.right(), hl_rect.top())],
                        [skia.ColorSetARGB(215, 255, 209, 102), skia.ColorSetARGB(195, 224, 118, 72)],
                    )
                )
                canvas.drawRoundRect(hl_rect, 7.0, 7.0, hl_p)
            _draw_safe_string(canvas, qln, quote_col_x + 22.0, qy, q_font, ink_dark)
            qy += line_step

        _draw_wax_verification_seal(
            canvas,
            right_x - 68.0,
            content_bottom - 52.0,
            48.0,
            title_tf,
            ui_tf,
            is_en=is_en,
        )
    else:
        # 9:16 Vertical Broadsheet: 1.38:1 top-weighted sepia plate with corner mounts + quote + wax seal
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, inner_w, v_photo_h)
        _draw_archival_sepia_plate_with_mounts(canvas, photo_img or backdrop_img, photo_rect)

        cap_str = f"ARCHIVAL PLATE • {lt_title}" if is_en else f"PRANCHA FOTOGRÁFICA • {lt_title}"
        cf, cl = _wrap_text_to_width(cap_str, ui_tf, 15.5, 11.5, inner_w - 120.0, 1)
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
                    (lw + 16.0) * line_prog,
                    q_font_v.getSize() * 1.18,
                )
                hl_p = skia.Paint(AntiAlias=True)
                hl_p.setBlendMode(skia.BlendMode.kMultiply)
                hl_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(hl_rect.left(), hl_rect.top()), (hl_rect.right(), hl_rect.top())],
                        [skia.ColorSetARGB(215, 255, 209, 102), skia.ColorSetARGB(195, 224, 118, 72)],
                    )
                )
                canvas.drawRoundRect(hl_rect, 7.0, 7.0, hl_p)
            _draw_safe_string(canvas, qln, left_x + 22.0, qy, q_font_v, ink_dark)
            qy += line_step

        # Wax verification seal overlapping bottom-right of photo plate
        _draw_wax_verification_seal(
            canvas,
            right_x - 62.0,
            content_top + v_photo_h - 14.0,
            52.0,
            title_tf,
            ui_tf,
            is_en=is_en,
        )

    canvas.restore()  # End paper clipRRect
    canvas.drawRRect(p_rr, rule_thick)
    canvas.restore()


# ---------------------------------------------------------------------------
# 6. Mechanical Odometer Timeline + Sliding 35mm Ruler + Data-Impact Bars
# ---------------------------------------------------------------------------
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
    housing_r = skia.Rect.MakeXYWH(cx - odo_w * 0.5, top_y, odo_w, odo_h)
    housing_rr = skia.RRect.MakeRectXY(housing_r, 16.0, 16.0)

    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(244, 11, 9, 18))
    sh_p.setImageFilter(skia.ImageFilters.DropShadow(0.0, 14.0, 28.0, 28.0, skia.ColorSetARGB(220, 0, 0, 0)))
    canvas.drawRRect(housing_rr, sh_p)

    canvas.save()
    canvas.clipRRect(housing_rr, doAntiAlias=True)

    # Top micro-label
    hdr_lbl = "CHRONOMETER ARCHIVE • ERA COUNTER" if is_en else "CRONÔMETRO MECÂNICO • MARCO TEMPORAL"
    hf, hl = _wrap_text_to_width(hdr_lbl, ui_tf, 13.5, 10.5, odo_w - 40.0, 1)
    if hl:
        hw = float(hf.measureText(hl[0]))
        _draw_safe_string(
            canvas,
            hl[0],
            cx - hw * 0.5,
            top_y + 22.0,
            hf,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#D4AF37", 205)),
        )

    # Mechanical Odometer Drum Window
    drum_w = odo_w - 56.0
    drum_h = 56.0
    drum_x = cx - drum_w * 0.5
    drum_y = top_y + 30.0
    drum_r = skia.Rect.MakeXYWH(drum_x, drum_y, drum_w, drum_h)
    drum_rr = skia.RRect.MakeRectXY(drum_r, 10.0, 10.0)
    canvas.drawRRect(drum_rr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 6, 5, 11)))

    # Character-by-character vertical rolling drum inside clipped odometer window
    p_str = _sanitize_glyphs(_normalize_upper(prev_date), typeface=title_tf)
    c_str = _sanitize_glyphs(_normalize_upper(curr_date), typeface=title_tf)
    max_len = max(len(p_str), len(c_str), 4)
    p_pad = p_str.center(max_len)
    c_pad = c_str.center(max_len)

    canvas.save()
    canvas.clipRRect(drum_rr, doAntiAlias=True)

    slot_w = min(46.0, drum_w / float(max(1, max_len)))
    total_slots_w = slot_w * max_len
    start_sx = cx - total_slots_w * 0.5
    d_font = skia.Font(title_tf, 36.0)

    for i in range(max_len):
        sx = start_sx + i * slot_w
        ch_prev = p_pad[i]
        ch_curr = c_pad[i]

        # Subtle drum wheel separator line
        if i > 0:
            canvas.drawLine(
                sx,
                drum_y + 4.0,
                sx,
                drum_y + drum_h - 4.0,
                skia.Paint(Color=skia.ColorSetARGB(55, 212, 175, 55)),
            )

        if ch_prev == ch_curr or roll_frac >= 0.999:
            ch_w = float(d_font.measureText(ch_curr))
            _draw_safe_string(
                canvas,
                ch_curr,
                sx + (slot_w - ch_w) * 0.5,
                drum_y + 41.0,
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")),
            )
        else:
            # Staggered mechanical wheel roll per digit slot
            slot_roll = _ease_in_out_cubic(min(1.0, max(0.0, (roll_frac * 1.25) - (i / float(max_len)) * 0.22)))
            y_offset = slot_roll * drum_h
            w_p = float(d_font.measureText(ch_prev))
            w_c = float(d_font.measureText(ch_curr))
            _draw_safe_string(
                canvas,
                ch_prev,
                sx + (slot_w - w_p) * 0.5,
                drum_y + 41.0 - y_offset,
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", int(255 * (1.0 - slot_roll)))),
            )
            _draw_safe_string(
                canvas,
                ch_curr,
                sx + (slot_w - w_c) * 0.5,
                drum_y + 41.0 + (drum_h - y_offset),
                d_font,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", int(255 * slot_roll))),
            )

    # Cylindrical top/bottom drum shadow overlay
    cyl_p = skia.Paint()
    cyl_p.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, drum_y), (0.0, drum_y + drum_h)],
            [
                skia.ColorSetARGB(185, 4, 3, 8),
                skia.ColorSetARGB(0, 4, 3, 8),
                skia.ColorSetARGB(0, 4, 3, 8),
                skia.ColorSetARGB(185, 4, 3, 8),
            ],
            [0.0, 0.26, 0.74, 1.0],
        )
    )
    canvas.drawRect(drum_r, cyl_p)
    canvas.restore()

    canvas.drawRRect(
        drum_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.6, Color=hex_to_skia("#D4AF37", 190)),
    )

    # Sliding 35mm Millimeter Ruler Tick Bar at bottom of odometer housing
    ruler_y = top_y + odo_h - 10.0
    scroll_px = prog * 540.0
    tick_p_major = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#FFD166", 210))
    tick_p_minor = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=skia.ColorSetARGB(120, 212, 175, 55))

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

    # Center crimson-gold needle pointer above ruler
    needle = skia.Path()
    needle.moveTo(cx, ruler_y - 19.0)
    needle.lineTo(cx - 7.0, ruler_y - 28.0)
    needle.lineTo(cx + 7.0, ruler_y - 28.0)
    needle.close()
    canvas.drawPath(needle, skia.Paint(AntiAlias=True, Color=hex_to_skia("#E63946")))

    canvas.restore()
    canvas.drawRRect(
        housing_rr,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.2, Color=hex_to_skia("#D4AF37", 215)),
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
    """Render Mechanical Odometer Year Counter + sliding 35mm millimeter ruler tick bar + 4 milestone
    cards where the active milestone (`int(prog * n_pts)`) is illuminated by a radial golden spotlight,
    scaled up (`1.04x`), and shows an animated data-impact bar filling from 0 -> 100%.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    _draw_dark_bokeh_backdrop(canvas, w, h, backdrop_img, prog, t, scrim_alpha=174, blur_sigma=4.0, mood=mood)

    raw_pts = _get_attr(scene, "timeline_points", None) or []
    pts: List[Dict[str, str]] = []
    for p in raw_pts[:4]:
        pts.append(
            {
                "date": str(_get_attr(p, "date", "MARCO")),
                "label": str(_get_attr(p, "label", "Evento Histórico Documentado")),
                "value": str(_get_attr(p, "value", "IMPACTO")),
            }
        )
    while len(pts) < 4:
        idx_f = len(pts) + 1
        pts.append(
            {
                "date": f"FASE 0{idx_f}",
                "label": "Registro Histórico & Consequência",
                "value": f"MARCO #{idx_f}",
            }
        )

    n_pts = len(pts)
    prog_c = max(0.0, min(0.9999, float(prog)))
    active_idx = min(n_pts - 1, max(0, int(prog_c * n_pts)))
    seg_span = 1.0 / float(n_pts)
    seg_local_prog = max(0.0, min(1.0, (prog_c - active_idx * seg_span) / seg_span))

    prev_idx = max(0, active_idx - 1)
    roll_frac = _ease_out_cubic(min(1.0, seg_local_prog / 0.38)) if active_idx > 0 else 1.0

    is_wide = w >= h
    odo_w = 560.0 if is_wide else (w - 110.0)
    odo_h = 122.0
    odo_top_y = 66.0 if is_wide else 304.0

    # 1. Top Mechanical Odometer Year Counter + Sliding 35mm Millimeter Ruler
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
        title_tf=title_tf,
        ui_tf=ui_tf,
        is_en=is_en,
    )

    photo_pool = [img for img in (extra_photos or []) if img is not None]
    if not photo_pool and backdrop_img is not None:
        photo_pool = [backdrop_img]

    # Compute card positions for 16:9 (2x2 grid) or 9:16 (4 stacked cards with central timeline rail)
    card_rects: List[skia.Rect] = []
    if is_wide:
        cw = (w - 180.0) * 0.5
        ch = 240.0
        gx0 = 72.0
        gx1 = 72.0 + cw + 36.0
        gy0 = odo_top_y + odo_h + 34.0
        gy1 = gy0 + ch + 28.0
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
        # Vertical timeline rail on left
        canvas.drawLine(
            rail_x,
            cards_top + 30.0,
            rail_x,
            cards_top + slot_h * 3 + 110.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=skia.ColorSetARGB(90, 212, 175, 55)),
        )
        fill_h = (slot_h * 3 + 80.0) * prog_c
        canvas.drawLine(
            rail_x,
            cards_top + 30.0,
            rail_x,
            cards_top + 30.0 + fill_h,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5.0, Color=hex_to_skia("#FFD166")),
        )
        for i in range(4):
            cy_i = cards_top + i * slot_h
            card_rects.append(skia.Rect.MakeXYWH(rail_x + 34.0, cy_i, cw, ch))

    # 2. Radial Golden Spotlight illuminating the active milestone card
    act_r = card_rects[active_idx]
    spot_p = skia.Paint(AntiAlias=True)
    spot_p.setShader(
        skia.GradientShader.MakeRadial(
            (act_r.centerX(), act_r.centerY()),
            max(act_r.width(), act_r.height()) * 0.85,
            [
                skia.ColorSetARGB(108, 255, 209, 102),
                skia.ColorSetARGB(42, 217, 119, 6),
                skia.ColorSetARGB(0, 10, 8, 18),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), spot_p)

    # 3. Render 4 Milestone Cards (active scaled 1.04x with 0->100% impact bar; inactive recessed in shadow)
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
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#E63946" if is_act else ("#D4AF37" if is_past else "#4A4458"))),
            )
            canvas.drawCircle(rail_x, ny, 5.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

        sc = 1.04 if is_act else 0.96
        canvas.save()
        canvas.translate(r.centerX(), r.centerY())
        canvas.scale(sc, sc)
        local_r = skia.Rect.MakeXYWH(-r.width() * 0.5, -r.height() * 0.5, r.width(), r.height())
        local_rr = skia.RRect.MakeRectXY(local_r, 16.0, 16.0)

        bg_alpha = 242 if is_act else 172
        bg_col = skia.ColorSetARGB(bg_alpha, 18, 14, 28) if is_act else skia.ColorSetARGB(bg_alpha, 10, 8, 16)
        c_bg = skia.Paint(AntiAlias=True, Color=bg_col)
        if is_act:
            c_bg.setImageFilter(skia.ImageFilters.DropShadow(0.0, 16.0, 32.0, 32.0, skia.ColorSetARGB(220, 0, 0, 0)))
        canvas.drawRRect(local_rr, c_bg)

        # Optional photo thumbnail on right side of card
        thumb_w = 188.0 if is_wide else 196.0
        text_avail_w = r.width() - 48.0
        if photo_pool:
            p_img = photo_pool[idx % len(photo_pool)]
            pr = skia.Rect.MakeXYWH(local_r.right() - thumb_w - 16.0, local_r.top() + 16.0, thumb_w, r.height() - 32.0)
            prr = skia.RRect.MakeRectXY(pr, 10.0, 10.0)
            canvas.save()
            canvas.clipRRect(prr, doAntiAlias=True)
            img_p = skia.Paint(AntiAlias=True)
            img_p.setAlphaf(1.0 if is_act else 0.45)
            _draw_image_cover(canvas, p_img, pr, paint=img_p, y_bias=0.20)
            canvas.restore()
            canvas.drawRRect(
                prr,
                skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=1.5,
                    Color=hex_to_skia("#FFD166" if is_act else "#5A5268", 200 if is_act else 110),
                ),
            )
            text_avail_w = r.width() - thumb_w - 62.0

        tx = local_r.left() + 24.0
        ty = local_r.top() + 42.0

        # Era / Date + Metric Header
        hdr_txt = f"{_normalize_upper(pt['date'])}  •  {_normalize_upper(pt['value'])}"
        df, dl = _wrap_text_to_width(hdr_txt, title_tf, 28.0 if is_act else 24.0, 16.0, text_avail_w, 1)
        if dl:
            _draw_safe_string(
                canvas,
                dl[0],
                tx,
                ty,
                df,
                skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166" if is_act else "#9E94AF", 250 if is_act else 155)),
            )

        # Milestone Description Label
        lf, ll = _wrap_text_to_width(pt["label"], ui_tf, 22.0 if is_act else 20.0, 14.5, text_avail_w, 2)
        ly = ty + 38.0
        for ln in ll:
            _draw_safe_string(
                canvas,
                ln,
                tx,
                ly,
                lf,
                skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(245 if is_act else 140, 244, 239, 230)),
            )
            ly += 27.0

        # Animated Data-Impact Bar (0 -> 100% fill on active milestone!)
        bar_y = local_r.bottom() - 34.0
        bar_h = 12.0
        bar_w = text_avail_w
        track_r = skia.Rect.MakeXYWH(tx, bar_y, bar_w, bar_h)
        canvas.drawRoundRect(track_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(160, 28, 24, 42)))

        if is_act:
            fill_frac = _ease_out_cubic(min(1.0, max(0.08, seg_local_prog * 1.25)))
        elif is_past:
            fill_frac = 1.0
        else:
            fill_frac = 0.12

        fill_r = skia.Rect.MakeXYWH(tx, bar_y, max(12.0, bar_w * fill_frac), bar_h)
        fill_p = skia.Paint(AntiAlias=True)
        if is_act:
            fill_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(fill_r.left(), bar_y), (fill_r.right(), bar_y)],
                    [hex_to_skia("#9E1B24"), hex_to_skia("#D97706"), hex_to_skia("#FFD166")],
                    [0.0, 0.55, 1.0],
                )
            )
        else:
            fill_p.setColor(hex_to_skia("#6C637A", 140 if is_past else 80))
        canvas.drawRoundRect(fill_r, 6.0, 6.0, fill_p)

        if is_act:
            pct_str = f"IMPACTO • {int(round(fill_frac * 100))}%" if not is_en else f"IMPACT • {int(round(fill_frac * 100))}%"
            pf = skia.Font(ui_tf, 13.0)
            _draw_safe_string(canvas, pct_str, tx, bar_y - 7.0, pf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

        border_col = hex_to_skia("#FFD166" if is_act else "#4E465E", 245 if is_act else 115)
        canvas.drawRRect(
            local_rr,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.2 if is_act else 1.6, Color=border_col),
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
    # Cast shadow on board/card below and to the right of the push-pin
    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(165, 0, 0, 0))
    sh_p.setImageFilter(skia.ImageFilters.Blur(3.5, 3.5))
    canvas.drawCircle(px + 4.5, py + 6.5, 12.5, sh_p)

    # Metallic needle collar
    canvas.drawCircle(px + 1.0, py + 2.0, 6.5, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 160, 165, 178)))

    # 3D Spherical Crimson/Brass Pin Head with radial specular gradient
    rad = 13.5 if is_active else 12.0
    head_p = skia.Paint(AntiAlias=True)
    head_p.setShader(
        skia.GradientShader.MakeRadial(
            (px - 3.5, py - 3.5),
            rad * 1.35,
            [
                skia.ColorSetARGB(255, 255, 145, 145),
                skia.ColorSetARGB(255, 210, 32, 44),
                skia.ColorSetARGB(255, 98, 12, 18),
            ],
            [0.0, 0.48, 1.0],
        )
    )
    canvas.drawCircle(px, py, rad, head_p)

    # Brass rim & crisp specular highlight dot
    canvas.drawCircle(
        px,
        py,
        rad,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia("#FFD166", 200)),
    )
    canvas.drawCircle(px - 3.8, py - 3.8, 3.2, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 255, 245, 240)))


def _draw_catenary_red_string(
    canvas: skia.Canvas,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    edge_prog: float,
) -> None:
    if edge_prog <= 0.02:
        return
    dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    # Realistic physical gravity sag proportional to span distance
    sag = min(92.0, 28.0 + dist * 0.11)
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

    # 1. Realistic offset drop shadow cast by the hanging string onto the board below
    canvas.save()
    canvas.translate(5.0, 15.0)
    shadow_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=5.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(135, 0, 0, 0),
    )
    shadow_str.setImageFilter(skia.ImageFilters.Blur(4.5, 4.5))
    canvas.drawPath(path, shadow_str)
    canvas.restore()

    # 2. Outer crimson yarn halo
    glow_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=8.5,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(105, 185, 24, 36),
    )
    glow_str.setImageFilter(skia.ImageFilters.Blur(4.0, 4.0))
    canvas.drawPath(path, glow_str)

    # 3. Taut crimson forensic thread core + specular fiber highlight
    core_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#D62839"),
    )
    canvas.drawPath(path, core_str)

    spec_str = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.3,
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
    - Curved catenary Bézier red strings (with realistic gravity sag and cast shadow) progressively
      drawn pin-to-pin as `prog` advances.
    - Moving Flashlight Spotlight (`RadialGradient`) that travels across the board to illuminate whichever
      evidence card is currently active while dimming the surrounding board edges.
    """
    mood = str(_get_attr(scene, "mood", "dark_horror") or "dark_horror")
    _draw_dark_bokeh_backdrop(canvas, w, h, backdrop_img, prog, t, scrim_alpha=178, blur_sigma=3.5, mood=mood)

    # Subtle forensic evidence board grid
    grid_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.0,
        Color=skia.ColorSetARGB(22, 212, 175, 55),
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
            (480.0, 326.0),
            (1440.0, 322.0),
            (490.0, 648.0),
            (1430.0, 644.0),
        ]
        tilts = (-1.8, 1.5, 1.3, -1.6)
        card_w, card_h = 560.0, 248.0
    else:
        # 2x2 Polaroid Dossier Investigation Board in 9:16 (below y=306px safe zone & above y=1480px captions)
        centers = [
            (286.0, 560.0),
            (794.0, 570.0),
            (286.0, 1088.0),
            (794.0, 1098.0),
        ]
        tilts = (-1.8, 1.6, 1.4, -1.5)
        card_w, card_h = 446.0, 444.0

    # Compute smooth continuous active card index & moving flashlight center `(spot_x, spot_y)`
    prog_c = max(0.0, min(0.9999, float(prog)))
    active_idx = min(3, max(0, int(prog_c * 4)))
    cont_idx = max(0.0, min(3.0, prog_c * 3.2))
    i0 = int(math.floor(cont_idx))
    i1 = min(3, i0 + 1)
    frac = _ease_in_out_cubic(cont_idx - i0)
    spot_x = centers[i0][0] + (centers[i1][0] - centers[i0][0]) * frac
    spot_y = centers[i0][1] + (centers[i1][1] - centers[i0][1]) * frac

    # Top-center push-pin coordinates for each card
    pin_coords: List[Tuple[float, float]] = []
    for idx, (cx, cy) in enumerate(centers):
        rad_t = math.radians(tilts[idx])
        local_py = -card_h * 0.5 + 14.0
        px = cx - local_py * math.sin(rad_t)
        py = cy + local_py * math.cos(rad_t)
        pin_coords.append((px, py))

    # 1. Draw the 4 Polaroid / Dossier Evidence Cards
    for idx, nd in enumerate(nodes):
        cx, cy = centers[idx]
        is_act = idx == active_idx
        ent = _ease_out_back(max(0.0, min(1.0, (body_t - idx * 0.06) / 0.38)))
        sc = (0.86 + 0.14 * ent) * (1.03 if is_act else 0.98)

        canvas.save()
        canvas.translate(cx, cy)
        canvas.rotate(tilts[idx])
        canvas.scale(sc, sc)

        rx = -card_w * 0.5
        ry = -card_h * 0.5
        c_rect = skia.Rect.MakeXYWH(rx, ry, card_w, card_h)
        c_rr = skia.RRect.MakeRectXY(c_rect, 14.0, 14.0)

        # Aged paper outer border around obsidian dossier card
        paper_border = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(248, 236, 228, 212))
        paper_border.setImageFilter(skia.ImageFilters.DropShadow(0.0, 18.0, 34.0, 34.0, skia.ColorSetARGB(225, 0, 0, 0)))
        canvas.drawRRect(c_rr, paper_border)

        inner_r = skia.Rect.MakeXYWH(rx + 6.0, ry + 6.0, card_w - 12.0, card_h - 12.0)
        inner_rr = skia.RRect.MakeRectXY(inner_r, 10.0, 10.0)
        canvas.drawRRect(inner_rr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(246, 16, 13, 24)))

        if is_wide:
            # 16:9 Horizontal Polaroid + Dossier layout
            pol_w = 186.0
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
            badge_r = skia.Rect.MakeXYWH(tx, ry + 32.0, min(tw_max, bw + 26.0), 30.0)
            canvas.drawRoundRect(badge_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#9E1B24")))
            canvas.drawRoundRect(
                badge_r,
                6.0,
                6.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#FFD166", 190)),
            )
            _draw_safe_string(canvas, b_str, tx + 13.0, ry + 52.5, bf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            tf_n, tl_n = _wrap_text_to_width(_normalize_upper(nd["title"]), title_tf, 28.0, 18.0, tw_max, 2)
            ty_n = ry + 98.0
            for tln in tl_n:
                _draw_safe_string(canvas, tln, tx, ty_n, tf_n, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166" if is_act else "#F4EFE6")))
                ty_n += tf_n.getSize() * 1.15

            rf_n, rl_n = _wrap_text_to_width(nd["role"], ui_tf, 19.5, 14.0, tw_max, 2)
            ry_n = max(ty_n + 6.0, ry + card_h - 62.0)
            for rln in rl_n:
                if ry_n > ry + card_h - 16.0:
                    break
                _draw_safe_string(canvas, rln, tx, ry_n, rf_n, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 224, 218, 235)))
                ry_n += rf_n.getSize() * 1.24
        else:
            # 9:16 Vertical Polaroid / Dossier Card (2x2 Grid)
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
            canvas.drawRoundRect(badge_r, 6.0, 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#9E1B24")))
            canvas.drawRoundRect(
                badge_r,
                6.0,
                6.0,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=hex_to_skia("#FFD166", 190)),
            )
            _draw_safe_string(canvas, b_str, tx + 13.0, by_badge + 19.5, bf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            tf_n, tl_n = _wrap_text_to_width(_normalize_upper(nd["title"]), title_tf, 27.0, 18.0, tw_max, 1)
            ty_n = by_badge + 60.0
            if tl_n:
                _draw_safe_string(canvas, tl_n[0], tx, ty_n, tf_n, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166" if is_act else "#F4EFE6")))

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
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166", 230)),
            )

        canvas.restore()

    # 2. Curved Catenary Bézier Red Strings with Gravity Sag & Shadow (spanning across the open corridors!)
    edges = [(0, 1), (1, 2), (2, 3), (0, 3)]
    for e_idx, (i_start, i_end) in enumerate(edges):
        edge_prog = _ease_out_cubic(min(1.0, max(0.0, (prog_c * 1.75) - e_idx * 0.18)))
        if edge_prog > 0.02:
            _draw_catenary_red_string(canvas, pin_coords[i_start], pin_coords[i_end], edge_prog)

    # 3. 3D Metallic Push-Pins + Shadow at Top Center of Each Card
    for idx, (px, py) in enumerate(pin_coords):
        _draw_3d_metallic_pushpin(canvas, px, py, is_active=(idx == active_idx))

    # 4. Moving Flashlight Spotlight (`RadialGradient`) illuminating active card & dimming outer edges
    beam_rad = (480.0 if is_wide else 430.0) * (1.0 + 0.03 * math.sin(t * 2.2))

    # Warm tungsten flashlight beam overlay (kScreen) on the active evidence card
    beam_p = skia.Paint(AntiAlias=True)
    beam_p.setBlendMode(skia.BlendMode.kScreen)
    beam_p.setShader(
        skia.GradientShader.MakeRadial(
            (spot_x, spot_y),
            beam_rad * 0.85,
            [
                skia.ColorSetARGB(68, 255, 232, 168),
                skia.ColorSetARGB(28, 212, 175, 55),
                skia.ColorSetARGB(0, 0, 0, 0),
            ],
            [0.0, 0.55, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), beam_p)

    # Surrounding board edge dimming mask outside the flashlight cone
    dim_p = skia.Paint(AntiAlias=True)
    dim_p.setShader(
        skia.GradientShader.MakeRadial(
            (spot_x, spot_y),
            beam_rad * 1.45,
            [
                skia.ColorSetARGB(0, 6, 4, 12),
                skia.ColorSetARGB(54, 6, 4, 12),
                skia.ColorSetARGB(142, 5, 3, 10),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), dim_p)
