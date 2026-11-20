"""FrimeRise C++ Skia-Python Ultra-Fast Vector Compositor (Hormozi / CapCut Edition).
- Explicit heavy typography loading (Montserrat-Black 900 / Anton / PlusJakartaSans-ExtraBold 800)
  via skia.Typeface.MakeFromFile with startup weight verification log.
- Hormozi / CapCut floating captions: ZERO fixed black box behind the line; 2-3 UPPERCASE words
  at 84px with StrokeWidth=12 + DropShadow, real inter-word spacing (measureText(' ') * 1.35),
  and custom-fitted active-word rounded pill (padding_x=28, padding_y=14) alternating
  Verde Lima (#B8FF01 / #0B0713), Rosa (#FF2E93 / #FFFFFF), and Dourado (#FFD166 / #0B0713)
  with 1.12x spring pop.
- ZERO debug/internal labels and ZERO watermark on Master MP4.
- Auto-wrapping, auto-fitting Motion Graphics Cards (2.5s-3.5s) composited over real footage
  with dynamic FFmpeg boxblur depth-of-field during card windows.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import skia

from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    thermal_guard_wait,
)

BASE_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"
EMOJI_FONT_PATH = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")

# Strictly forbidden internal/debug strings that must NEVER appear on a client video
FORBIDDEN_DEBUG_RE = re.compile(
    r"(TESTE\s*A/B|FRIMERISE\s*ENGINE|VARIAÇÃO\s*ALTERNATIVA|NICHO:|PRESET:|GANCHO\s*[AB]\b|DEBUG)",
    re.IGNORECASE,
)

# 3-color active-word pill rotation: (pill_bg_hex, text_hex, glow_rgba)
ACTIVE_PILL_PALETTE = [
    ("#B8FF01", "#0B0713", (184, 255, 1, 185)),   # Verde Lima + texto escuro ultra-legível
    ("#FF2E93", "#FFFFFF", (255, 46, 147, 195)),  # Rosa Frime + texto branco
    ("#FFD166", "#0B0713", (255, 209, 102, 190)), # Dourado + texto escuro ultra-legível
]


def hex_to_skia(hex_color: str, alpha: Optional[int] = None) -> int:
    s = hex_color.strip().lstrip("#")
    if len(s) == 8:
        r, g, b, a = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
    else:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        a = 255
    if alpha is not None:
        a = alpha
    return skia.ColorSetARGB(a, r, g, b)


def _load_verified_typeface(font_filename: str, role: str = "caption") -> Tuple[skia.Typeface, str]:
    """Explicitly load heavy TTF via skia.Typeface.MakeFromFile and verify it isn't DejaVu Sans."""
    candidates = [
        font_filename,
        "Montserrat-Black.ttf",
        "Anton-Regular.ttf",
        "Montserrat-ExtraBold.ttf",
        "PlusJakartaSans-ExtraBold.ttf",
    ]
    for name in candidates:
        fpath = FONTS_DIR / name
        if fpath.exists() and fpath.stat().st_size > 20_000:
            tf = skia.Typeface.MakeFromFile(str(fpath))
            if tf is not None:
                fam = tf.getFamilyName()
                wt = tf.fontStyle().weight()
                # Reject thin variable fallback (<500) unless it's Anton / Bebas Neue display face
                if wt >= 700 or fam.lower() in ("anton", "bebas neue"):
                    info = f"{name} (family='{fam}', weight={wt}, isBold={tf.isBold()})"
                    print(f"[Skia:{role}] Fonte pesada verificada: {info}", flush=True)
                    return tf, info
    raise RuntimeError(f"Nenhuma fonte pesada válida encontrada em {FONTS_DIR}")


def _load_emoji_typeface() -> Optional[skia.Typeface]:
    if EMOJI_FONT_PATH.exists():
        return skia.Typeface.MakeFromFile(str(EMOJI_FONT_PATH))
    return None


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return 0x1F300 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x1F1E6 <= cp <= 0x1F1FF


def _spring_pop_112(age_s: float) -> float:
    """Snappy Hormozi/CapCut pop settling cleanly at 1.12x."""
    if age_s < 0.0:
        return 1.0
    if age_s > 0.28:
        return 1.12
    # Quick overshoot from 0.94 -> 1.18 -> 1.12
    return 1.12 - 0.18 * math.exp(-15.0 * age_s) * math.cos(22.0 * age_s)


def _ease_out_cubic(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def _wrap_text_to_width(text: str, typeface: skia.Typeface, start_size: float, min_size: float, max_w: float, max_lines: int) -> Tuple[skia.Font, List[str]]:
    """Auto-wrap text into <= max_lines and shrink font size if needed so text NEVER clips."""
    clean = " ".join(str(text).strip().split())
    if not clean:
        return skia.Font(typeface, start_size), []

    size = float(start_size)
    while size >= min_size:
        font = skia.Font(typeface, size)
        words = clean.split(" ")
        lines: List[str] = []
        cur = ""
        fits = True
        for wd in words:
            cand = f"{cur} {wd}".strip()
            if font.measureText(cand) <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                if font.measureText(wd) > max_w:
                    fits = False
                    break
                cur = wd
        if cur:
            lines.append(cur)
        if fits and len(lines) <= max_lines:
            return font, lines
        size -= 3.0

    # At min_size, clamp to max_lines with ellipsis if extremely long
    font = skia.Font(typeface, min_size)
    words = clean.split(" ")
    lines = []
    cur = ""
    for wd in words:
        cand = f"{cur} {wd}".strip()
        if font.measureText(cand) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while len(lines[-1]) > 4 and font.measureText(lines[-1] + "...") > max_w:
            lines[-1] = lines[-1][:-1].rstrip()
        lines[-1] = lines[-1] + "..."
    return font, lines


def _sanitize_card_text(txt: str) -> str:
    cleaned = FORBIDDEN_DEBUG_RE.sub("", str(txt or "")).strip(" •-:|")
    return " ".join(cleaned.split())


def group_words_into_chunks(words: List[Dict[str, Any]], max_words: int = 3) -> List[Dict[str, Any]]:
    """Split any multi-word tokens and group into crisp 2-3 word Hormozi subtitle chunks."""
    # First normalize: guarantee every entry is a single clean word with no glued spaces
    clean_words: List[Dict[str, Any]] = []
    global_idx = 0
    for w in words:
        raw = str(w.get("word", "")).strip()
        parts = [p for p in re.split(r"\s+", raw) if p]
        if not parts:
            continue
        st = float(w["start"])
        en = float(w["end"])
        step = max(0.06, (en - st) / float(len(parts)))
        for j, part in enumerate(parts):
            clean_words.append(
                {
                    "word": part,
                    "start": round(st + j * step, 3),
                    "end": round(st + (j + 1) * step, 3),
                    "g_idx": global_idx,
                }
            )
            global_idx += 1

    chunks: List[Dict[str, Any]] = []
    buf: List[Dict[str, Any]] = []
    for w in clean_words:
        buf.append(w)
        txt = w["word"]
        end_punct = txt.endswith((".", "!", "?", ";", ":"))
        char_len = sum(len(x["word"]) for x in buf) + max(0, len(buf) - 1)
        if len(buf) >= max_words or end_punct or char_len >= 16:
            chunks.append(
                {
                    "start": buf[0]["start"],
                    "end": buf[-1]["end"],
                    "words": list(buf),
                }
            )
            buf = []
    if buf:
        chunks.append({"start": buf[0]["start"], "end": buf[-1]["end"], "words": buf})

    for i in range(len(chunks) - 1):
        gap = chunks[i + 1]["start"] - chunks[i]["end"]
        if 0 < gap <= 0.30:
            chunks[i]["end"] = chunks[i + 1]["start"]
    return chunks


class SkiaMotionCompositor:
    """Renders 1080x1920 RGBA overlay frames (Hormozi Captions + Wrapped Motion Cards + Progress Bar)."""

    def __init__(
        self,
        preset: Dict[str, Any],
        width: int = 1080,
        height: int = 1920,
    ) -> None:
        self.w = width
        self.h = height
        self.preset = preset

        self.typeface, self.font_info = _load_verified_typeface(
            preset.get("font_file", "Montserrat-Black.ttf"), role="caption"
        )
        self.ui_typeface, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="card_ui")
        self.emoji_typeface = _load_emoji_typeface()

        self.c_primary = hex_to_skia(preset.get("primary_color", "#FF2E93"))
        self.c_secondary = hex_to_skia(preset.get("secondary_color", "#B388FF"))
        self.c_highlight = hex_to_skia(preset.get("highlight_color", "#B8FF01"))
        self.c_gold = hex_to_skia(preset.get("accent_gold", "#FFD166"))
        self.c_text = hex_to_skia(preset.get("text_color", "#FFFFFF"))
        self.c_stroke = skia.ColorSetARGB(255, 5, 3, 10)

        self.surface = skia.Surface(self.w, self.h)

    def _draw_top_progress_bar(self, canvas: skia.Canvas, progress: float) -> None:
        bar_h = 10
        fill_w = max(6.0, self.w * max(0.0, min(1.0, progress)))
        bar_paint = skia.Paint(AntiAlias=True)
        bar_paint.setShader(
            skia.GradientShader.MakeLinear(
                points=[(0, 0), (self.w, 0)],
                colors=[self.c_primary, self.c_secondary, self.c_highlight],
                positions=[0.0, 0.55, 1.0],
            )
        )
        canvas.drawRoundRect(skia.Rect.MakeXYWH(0, 0, fill_w, bar_h), 5, 5, bar_paint)

    def _draw_motion_card(self, canvas: skia.Canvas, card: Dict[str, Any], t: float) -> None:
        start = float(card.get("start", 0.0))
        end = float(card.get("end", 0.0))
        if not (start <= t <= end):
            return

        age = t - start
        rem = end - t
        enter = _ease_out_cubic(age / 0.28)
        exit_a = _ease_out_cubic(rem / 0.24) if rem < 0.24 else 1.0
        alpha = int(255 * min(enter, exit_a))
        if alpha <= 8:
            return

        ctype = card.get("type", "bar_chart")
        card_w = 880.0
        card_x = (self.w - card_w) / 2.0
        slide_y = (1.0 - enter) * -36.0

        canvas.save()
        canvas.translate(0, slide_y)

        if ctype == "bar_chart":
            card_y, card_h = 310.0, 440.0
            rect = skia.Rect.MakeXYWH(card_x, card_y, card_w, card_h)
            bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.84), 16, 11, 30))
            bg.setImageFilter(skia.ImageFilters.DropShadow(0, 16, 28, 28, skia.ColorSetARGB(int(alpha * 0.65), 0, 0, 0)))
            canvas.drawRoundRect(rect, 34, 34, bg)

            border = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.5)
            border.setShader(
                skia.GradientShader.MakeLinear(
                    points=[(card_x, card_y), (card_x + card_w, card_y + card_h)],
                    colors=[self.c_primary, self.c_secondary, self.c_highlight],
                )
            )
            canvas.drawRoundRect(rect, 34, 34, border)

            # Auto-wrapped, auto-fitted title (NEVER clips)
            raw_title = _sanitize_card_text(card.get("title", "COMPARATIVO DE RESULTADOS")).upper()
            t_font, t_lines = _wrap_text_to_width(raw_title, self.typeface, 38.0, 24.0, card_w - 88.0, max_lines=2)
            tp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
            ty = card_y + 62.0
            for ln in t_lines:
                lw = t_font.measureText(ln)
                canvas.drawString(ln, card_x + (card_w - lw) / 2.0, ty, t_font, tp)
                ty += t_font.getSize() * 1.18

            bars = card.get("bars", [{"label": "Comum", "value": 24}, {"label": "Editado", "value": 58}, {"label": "Otimizado", "value": 95}])[:4]
            max_val = max(float(b.get("value", 1)) for b in bars) or 1.0
            grow = _ease_out_cubic(age / 0.75)

            bar_area_top = ty + 32.0
            bar_area_bottom = card_y + card_h - 74.0
            bar_area_h = max(90.0, bar_area_bottom - bar_area_top)
            inner_w = card_w - 110.0
            slot_w = inner_w / max(1, len(bars))

            for idx, b in enumerate(bars):
                val = float(b.get("value", 50))
                bh = max(18.0, (val / max_val) * bar_area_h * grow)
                bw = min(140.0, slot_w * 0.62)
                bx = card_x + 55.0 + idx * slot_w + (slot_w - bw) / 2.0
                by = bar_area_bottom - bh

                bp = skia.Paint(AntiAlias=True)
                if idx == len(bars) - 1:
                    bp.setShader(
                        skia.GradientShader.MakeLinear(
                            points=[(bx, by), (bx, bar_area_bottom)],
                            colors=[self.c_highlight, self.c_primary],
                        )
                    )
                else:
                    bp.setShader(
                        skia.GradientShader.MakeLinear(
                            points=[(bx, by), (bx, bar_area_bottom)],
                            colors=[self.c_secondary, skia.ColorSetARGB(alpha, 55, 38, 102)],
                        )
                    )
                canvas.drawRoundRect(skia.Rect.MakeXYWH(bx, by, bw, bh), 16, 16, bp)

                # Value centered above bar
                vtxt = f"{int(round(val * grow))}%"
                v_font, _ = _wrap_text_to_width(vtxt, self.typeface, 32.0, 22.0, slot_w - 8.0, 1)
                vw = v_font.measureText(vtxt)
                vp = skia.Paint(AntiAlias=True, Color=self.c_highlight if idx == len(bars) - 1 else skia.ColorSetARGB(alpha, 255, 255, 255))
                canvas.drawString(vtxt, bx + (bw - vw) / 2.0, by - 12.0, v_font, vp)

                # Label centered below bar (auto-fitted to slot_w)
                ltxt = _sanitize_card_text(b.get("label", ""))
                l_font, l_lines = _wrap_text_to_width(ltxt, self.ui_typeface, 24.0, 16.0, slot_w - 10.0, 1)
                lbl_s = l_lines[0] if l_lines else ""
                lw = l_font.measureText(lbl_s)
                lp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 232, 224, 252))
                canvas.drawString(lbl_s, bx + (bw - lw) / 2.0, bar_area_bottom + 40.0, l_font, lp)

        elif ctype == "counter":
            card_y, card_h = 340.0, 290.0
            c_w = 780.0
            c_x = (self.w - c_w) / 2.0
            rect = skia.Rect.MakeXYWH(c_x, card_y, c_w, card_h)
            bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.86), 16, 11, 30))
            bg.setImageFilter(skia.ImageFilters.DropShadow(0, 14, 26, 26, skia.ColorSetARGB(int(alpha * 0.6), 0, 0, 0)))
            canvas.drawRoundRect(rect, 36, 36, bg)

            border = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0, Color=self.c_gold)
            canvas.drawRoundRect(rect, 36, 36, border)

            target_num = float(card.get("target", 340))
            prefix = str(card.get("prefix", "+"))
            suffix = str(card.get("suffix", "%"))
            cur_val = int(round(target_num * _ease_out_cubic(age / 0.85)))
            big_txt = f"{prefix}{cur_val:,}{suffix}".replace(",", ".")

            num_font, _ = _wrap_text_to_width(big_txt, self.typeface, 108.0, 56.0, c_w - 90.0, 1)
            npaint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
            npaint.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 18, 18, skia.ColorSetARGB(int(alpha * 0.7), 255, 209, 102)))
            tw = num_font.measureText(big_txt)
            canvas.drawString(big_txt, (self.w - tw) / 2.0, card_y + 148.0, num_font, npaint)

            sub_txt = _sanitize_card_text(card.get("label", "IMPACTO COMPROVADO")).upper()
            sub_font, sub_lines = _wrap_text_to_width(sub_txt, self.ui_typeface, 30.0, 20.0, c_w - 90.0, 2)
            sp = skia.Paint(AntiAlias=True, Color=self.c_highlight)
            sy = card_y + 216.0
            for sln in sub_lines:
                sw = sub_font.measureText(sln)
                canvas.drawString(sln, (self.w - sw) / 2.0, sy, sub_font, sp)
                sy += sub_font.getSize() * 1.18

        else:  # "headline" — clean editorial callout with auto-wrap & zero debug labels
            raw_title = _sanitize_card_text(card.get("title", "")).upper()
            raw_sub = _sanitize_card_text(card.get("subtitle", ""))
            if not raw_title:
                canvas.restore()
                return

            h_font, h_lines = _wrap_text_to_width(raw_title, self.typeface, 44.0, 28.0, card_w - 110.0, max_lines=2)
            s_font, s_lines = _wrap_text_to_width(raw_sub, self.ui_typeface, 26.0, 19.0, card_w - 110.0, max_lines=2) if raw_sub else (skia.Font(self.ui_typeface, 24), [])

            line_h = h_font.getSize() * 1.24
            card_h = 74.0 + len(h_lines) * line_h + (len(s_lines) * 34.0 + 18.0 if s_lines else 0.0)
            card_y = 320.0
            rect = skia.Rect.MakeXYWH(card_x, card_y, card_w, card_h)

            bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.86), 16, 11, 30))
            bg.setImageFilter(skia.ImageFilters.DropShadow(0, 14, 26, 26, skia.ColorSetARGB(int(alpha * 0.6), 0, 0, 0)))
            canvas.drawRoundRect(rect, 30, 30, bg)

            border = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.5)
            border.setShader(skia.GradientShader.MakeLinear([(card_x, card_y), (card_x + card_w, card_y)], [self.c_primary, self.c_highlight]))
            canvas.drawRoundRect(rect, 30, 30, border)

            hl_prog = _ease_out_cubic(age / 0.45)
            cy = card_y + 72.0
            for idx, ln in enumerate(h_lines):
                lw = h_font.measureText(ln)
                lx = card_x + (card_w - lw) / 2.0
                if idx == 0:
                    hl_w = (lw + 36.0) * hl_prog
                    canvas.drawRoundRect(
                        skia.Rect.MakeXYWH(lx - 18.0, cy - h_font.getSize() * 0.86, hl_w, h_font.getSize() * 1.15),
                        14, 14,
                        skia.Paint(AntiAlias=True, Color=self.c_highlight),
                    )
                    canvas.drawString(ln, lx, cy, h_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 11, 7, 19)))
                else:
                    canvas.drawString(ln, lx, cy, h_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 255, 255)))
                cy += line_h

            for sln in s_lines:
                sw = s_font.measureText(sln)
                canvas.drawString(sln, card_x + (card_w - sw) / 2.0, cy + 8.0, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 232, 224, 252)))
                cy += 34.0

        canvas.restore()

    def _draw_caption_chunk(self, canvas: skia.Canvas, chunk: Dict[str, Any], t: float) -> None:
        """Hormozi / CapCut style floating captions:
        - ZERO black backdrop bar behind the whole line
        - 2-3 UPPERCASE words at 84px, StrokeWidth=12 + DropShadow
        - Real inter-word space = measureText(' ') * 1.35 (NEVER glues words)
        - Custom-fitted rounded pill ONLY on the actively spoken word (padding_x=28, padding_y=14)
          rotating Verde Lima (#B8FF01), Rosa (#FF2E93), Dourado (#FFD166) with 1.12x pop.
        """
        words = chunk["words"]
        if not words:
            return

        base_size = 84.0
        font = skia.Font(self.typeface, base_size)
        emoji_font = skia.Font(self.emoji_typeface, base_size * 0.90) if self.emoji_typeface else font

        # Real calculated space width between words (generous spacing so words & active pill NEVER touch)
        space_w = max(30.0, float(font.measureText(" ")) * 1.45)
        pad_x = 28.0
        pad_y = 14.0

        tokens = []
        total_w = 0.0
        for idx, w in enumerate(words):
            raw = str(w["word"]).strip().upper()
            if not raw:
                continue
            is_active = w["start"] <= t <= (w["end"] + 0.05)
            age = t - w["start"] if is_active else -1.0
            sc = _spring_pop_112(age) if is_active else 1.0
            has_emoji = any(_is_emoji(ch) for ch in raw)
            f_use = emoji_font if (has_emoji and len(raw) <= 2) else font
            tw = float(f_use.measureText(raw))
            # Reserve full expanded horizontal footprint for the popped active pill so neighbors NEVER overlap!
            slot_w = (tw + pad_x * 2.0) * sc if is_active else tw
            tokens.append(
                {
                    "text": raw,
                    "w": tw,
                    "slot_w": slot_w,
                    "active": is_active,
                    "scale": sc,
                    "g_idx": int(w.get("g_idx", idx)),
                    "font": f_use,
                }
            )
            total_w += slot_w

        if not tokens:
            return
        total_w += space_w * (len(tokens) - 1)

        # Safe width check: keep at least 70px margin on left & right (max 940px)
        line_scale = min(1.0, 920.0 / max(1.0, total_w))
        cy = 1445.0

        fm = font.getMetrics()
        ascent = abs(float(fm.fAscent))
        descent = abs(float(fm.fDescent))

        canvas.save()
        canvas.translate(self.w / 2.0, cy)
        canvas.scale(line_scale, line_scale)

        cursor_x = -total_w / 2.0

        # Compute exact non-overlapping center X for each word slot
        draw_order = [tok for tok in tokens if not tok["active"]] + [tok for tok in tokens if tok["active"]]
        positions = {}
        cx_iter = cursor_x
        for tok in tokens:
            positions[id(tok)] = cx_iter + tok["slot_w"] / 2.0
            cx_iter += tok["slot_w"] + space_w

        for tok in draw_order:
            w_cx = positions[id(tok)]
            canvas.save()
            canvas.translate(w_cx, 0.0)

            if tok["active"]:
                canvas.scale(tok["scale"], tok["scale"])
                pill_bg_hex, pill_txt_hex, (gr, gg, gb, ga) = ACTIVE_PILL_PALETTE[tok["g_idx"] % len(ACTIVE_PILL_PALETTE)]

                # Tightly fitted rounded pill around ONLY this spoken word
                pill_rect = skia.Rect.MakeXYWH(
                    -tok["w"] / 2.0 - pad_x,
                    -ascent - pad_y,
                    tok["w"] + pad_x * 2.0,
                    ascent + descent + pad_y * 2.0,
                )
                pill_paint = skia.Paint(AntiAlias=True, Color=hex_to_skia(pill_bg_hex))
                pill_paint.setImageFilter(
                    skia.ImageFilters.DropShadow(0, 6, 18, 18, skia.ColorSetARGB(ga, gr, gg, gb))
                )
                canvas.drawRoundRect(pill_rect, 22, 22, pill_paint)

                # Crisp text inside active pill
                txt_paint = skia.Paint(AntiAlias=True, Color=hex_to_skia(pill_txt_hex))
                if pill_txt_hex == "#FFFFFF":
                    # Add subtle dark outline for white text on pink pill
                    st_p = skia.Paint(
                        AntiAlias=True,
                        Style=skia.Paint.kStroke_Style,
                        StrokeWidth=5.0,
                        StrokeJoin=skia.Paint.kRound_Join,
                        StrokeCap=skia.Paint.kRound_Cap,
                        Color=skia.ColorSetARGB(200, 11, 7, 19),
                    )
                    canvas.drawString(tok["text"], -tok["w"] / 2.0, 0.0, tok["font"], st_p)
                canvas.drawString(tok["text"], -tok["w"] / 2.0, 0.0, tok["font"], txt_paint)
            else:
                # Floating white/gold bold word with thick black StrokeWidth=12 + DropShadow
                shadow_p = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=12.0,
                    StrokeJoin=skia.Paint.kRound_Join,
                    StrokeCap=skia.Paint.kRound_Cap,
                    Color=self.c_stroke,
                )
                shadow_p.setImageFilter(
                    skia.ImageFilters.DropShadow(0, 8, 14, 14, skia.ColorSetARGB(220, 0, 0, 0))
                )
                canvas.drawString(tok["text"], -tok["w"] / 2.0, 0.0, tok["font"], shadow_p)

                fill_color = self.c_gold if any(ch.isdigit() for ch in tok["text"]) else self.c_text
                fill_p = skia.Paint(AntiAlias=True, Color=fill_color)
                canvas.drawString(tok["text"], -tok["w"] / 2.0, 0.0, tok["font"], fill_p)

            canvas.restore()

        canvas.restore()

    def render_frame_rgba(
        self,
        t: float,
        duration_s: float,
        chunks: List[Dict[str, Any]],
        motion_cards: List[Dict[str, Any]],
        show_motion_cards: bool = True,
    ) -> bytes:
        canvas = self.surface.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 0))

        self._draw_top_progress_bar(canvas, t / max(0.01, duration_s))

        if show_motion_cards:
            for card in motion_cards:
                self._draw_motion_card(canvas, card, t)

        for ch in chunks:
            if ch["start"] <= t <= ch["end"]:
                self._draw_caption_chunk(canvas, ch, t)
                break

        return self.surface.makeImageSnapshot().tobytes()

    def composite_onto_video(
        self,
        bg_video: Path,
        audio_m4a: Path,
        output_mp4: Path,
        duration_s: float,
        words: List[Dict[str, Any]],
        motion_cards: List[Dict[str, Any]],
        fps: int = 30,
        show_motion_cards: bool = True,
        thermal_limit_c: float = 85.0,
    ) -> Path:
        """Stream RGBA Skia frames via stdin pipe directly into FFmpeg + Intel QuickSync VAAPI.
        Applies subtle depth-of-field boxblur on background video ONLY during the 2.5s-3.5s
        windows when a Motion Card is displayed.
        """
        thermal_guard_wait(limit_c=thermal_limit_c)
        chunks = group_words_into_chunks(words, max_words=3)
        total_frames = max(1, int(math.ceil(duration_s * fps)))

        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)

        # Build dynamic boxblur enable expression for Motion Card windows
        blur_terms = []
        if show_motion_cards and motion_cards:
            for mc in motion_cards:
                st = float(mc.get("start", 0.0))
                en = float(mc.get("end", 0.0))
                if en > st:
                    blur_terms.append(f"between(t,{st:.2f},{en:.2f})")

        if blur_terms:
            en_expr = "+".join(blur_terms)
            bg_chain = f"[0:v]boxblur=10:2:enable='{en_expr}'[bg_dof]"
        else:
            bg_chain = "[0:v]null[bg_dof]"

        filter_complex = f"{bg_chain};[bg_dof][1:v]overlay=0:0:shortest=1,{hw_suffix}[vout]"

        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            *pre_args,
            "-i",
            str(bg_video),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{self.w}x{self.h}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-i",
            str(audio_m4a),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "2:a",
            "-t",
            f"{duration_s:.3f}",
            *enc_args,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=get_vaapi_env(),
            preexec_fn=nice_preexec,
        )
        assert proc.stdin is not None
        try:
            for f_idx in range(total_frames):
                t = f_idx / float(fps)
                raw = self.render_frame_rgba(
                    t=t,
                    duration_s=duration_s,
                    chunks=chunks,
                    motion_cards=motion_cards,
                    show_motion_cards=show_motion_cards,
                )
                proc.stdin.write(raw)
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

        stderr = proc.stderr.read() if proc.stderr else b""
        proc.wait(timeout=240)
        if proc.returncode != 0:
            raise RuntimeError(f"Skia/FFmpeg composite failed: {stderr.decode(errors='ignore')}")
        return output_mp4


def render_cover_9x16(
    title: str,
    subtitle: str,
    preset: Dict[str, Any],
    out_png: Path,
    bg_frame_path: Optional[Path] = None,
) -> Path:
    """Render a clean, editorial 1080x1920 HD Thumbnail Cover in Skia C++ (zero debug labels)."""
    w, h = 1080, 1920
    surf = skia.Surface(w, h)
    c = surf.getCanvas()

    if bg_frame_path and bg_frame_path.exists():
        img = skia.Image.open(str(bg_frame_path))
        c.drawImageRect(img, skia.Rect.MakeWH(w, h))
        scrim = skia.Paint()
        scrim.setShader(
            skia.GradientShader.MakeLinear(
                [(0, 0), (0, h)],
                [
                    skia.ColorSetARGB(120, 11, 7, 19),
                    skia.ColorSetARGB(175, 11, 7, 19),
                    skia.ColorSetARGB(220, 11, 7, 19),
                ],
                [0.0, 0.55, 1.0],
            )
        )
        c.drawRect(skia.Rect.MakeWH(w, h), scrim)
    else:
        bgp = skia.Paint()
        bgp.setShader(
            skia.GradientShader.MakeLinear(
                points=[(0, 0), (w, h)],
                colors=[skia.ColorSetARGB(255, 24, 14, 46), skia.ColorSetARGB(255, 11, 7, 19)],
            )
        )
        c.drawRect(skia.Rect.MakeWH(w, h), bgp)

    c_highlight = hex_to_skia(preset.get("highlight_color", "#B8FF01"))
    c_gold = hex_to_skia(preset.get("accent_gold", "#FFD166"))
    main_tf, _ = _load_verified_typeface(preset.get("font_file", "Montserrat-Black.ttf"), role="cover")
    ui_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="cover_sub")

    clean_title = _sanitize_card_text(title).upper() or "VÍDEO EM ALTA"
    title_font, lines = _wrap_text_to_width(clean_title, main_tf, 96.0, 56.0, w - 160.0, max_lines=4)
    line_step = title_font.getSize() * 1.24
    y0 = 920.0 - ((len(lines) - 1) * line_step) / 2.0

    for idx, line in enumerate(lines):
        tw = title_font.measureText(line)
        lx = (w - tw) / 2.0
        ly = y0 + idx * line_step
        if idx == len(lines) - 1:
            c.drawRoundRect(
                skia.Rect.MakeXYWH(lx - 28, ly - title_font.getSize() * 0.88, tw + 56, title_font.getSize() * 1.18),
                22, 22,
                skia.Paint(AntiAlias=True, Color=c_highlight),
            )
            c.drawString(line, lx, ly, title_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 11, 7, 19)))
        else:
            sp = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=12,
                StrokeJoin=skia.Paint.kRound_Join,
                Color=skia.ColorSetARGB(255, 5, 3, 10),
            )
            c.drawString(line, lx, ly, title_font, sp)
            fp = skia.Paint(AntiAlias=True, Color=c_gold if idx == 0 else skia.ColorWHITE)
            fp.setImageFilter(skia.ImageFilters.DropShadow(0, 8, 18, 18, skia.ColorSetARGB(200, 0, 0, 0)))
            c.drawString(line, lx, ly, title_font, fp)

    clean_sub = _sanitize_card_text(subtitle)
    if clean_sub:
        sub_font, sub_lines = _wrap_text_to_width(clean_sub, ui_tf, 36.0, 24.0, w - 180.0, max_lines=2)
        sy = 1560.0
        for sln in sub_lines:
            sw = sub_font.measureText(sln)
            c.drawString(sln, (w - sw) / 2.0, sy, sub_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 240, 235, 255)))
            sy += sub_font.getSize() * 1.25

    surf.makeImageSnapshot().save(str(out_png), skia.kPNG)
    return out_png
