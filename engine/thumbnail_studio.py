"""FrimeRise Magnetic 16:9 A/B Thumbnail Studio (1280x720 High-CTR YouTube Covers).
Uses C++ Skia + rembg (u2netp ONNX) + heavy verified typography (Anton-Regular.ttf & Montserrat-Black.ttf)
to automatically generate 3 distinct A/B/C 1280x720 thumbnails for every 16:9 video:
  1. thumb_A_mystery.jpg  — True Crime / Mystery Curiosity Gap (isolated subject + censor eye-bar + gold/pink arrow + dark crimson glow)
  2. thumb_B_contrast.jpg — High-Voltage Neon Split Contrast (isolated subject + lime/pink neon rim-light + 3-word stacked impact headline)
  3. thumb_C_zoom.jpg     — Extreme Focal Zoom + Pink Target Circle & Lime Curved Arrow + Gold/White 3-Word Headline
Accepts `custom_3words: Optional[str] = None` so pre-seeded channel episodes (e.g. "ESCONDEU $1.4 BILHÃO" or "HID $1.4 BILLION")
render verbatim with zero edge clipping. Runs 100% on Intel Core i5 CPU with zero LLM tokens.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import skia

from engine.skia_compositor import FORBIDDEN_DEBUG_RE, _load_verified_typeface, hex_to_skia

BASE_DIR = Path(__file__).resolve().parent.parent
_REMBG_SESSION = None


def _get_u2netp_session():
    """Load u2netp.onnx directly via ONNXRuntime (avoids numba/TBB thread-fork deadlocks in asyncio!)."""
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        import onnxruntime as ort

        u2_path = Path.home() / ".u2net" / "u2netp.onnx"
        if not u2_path.exists():
            from rembg import new_session

            new_session("u2netp")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        _REMBG_SESSION = ort.InferenceSession(str(u2_path), sess_options=so, providers=["CPUExecutionProvider"])
    return _REMBG_SESSION


def _group_into_max_three_lines(tokens: List[str]) -> List[str]:
    """Group a token list into at most 3 stacked lines while keeping every token verbatim."""
    if len(tokens) <= 3:
        return tokens
    if len(tokens) == 4:
        # Merge the shortest adjacent pair so 4-word hooks like "ELE JUNTOU OS PONTOS" stay verbatim in 3 lines
        pairs = [
            ([f"{tokens[0]} {tokens[1]}", tokens[2], tokens[3]], len(tokens[0]) + len(tokens[1])),
            ([tokens[0], f"{tokens[1]} {tokens[2]}", tokens[3]], len(tokens[1]) + len(tokens[2])),
            ([tokens[0], tokens[1], f"{tokens[2]} {tokens[3]}"], len(tokens[2]) + len(tokens[3])),
        ]
        pairs.sort(key=lambda item: item[1])
        return pairs[0][0]
    # For >4 tokens, group into 3 balanced lines
    n = len(tokens)
    c1 = max(1, round(n / 3))
    c2 = max(c1 + 1, round(2 * n / 3))
    return [
        " ".join(tokens[:c1]),
        " ".join(tokens[c1:c2]),
        " ".join(tokens[c2:]),
    ]


def _extract_three_impact_words(title: str, custom_3words: Optional[str] = None) -> List[str]:
    """Distill any video title/topic into at most 3 ultra-punchy uppercase thumbnail lines,
    or render `custom_3words` verbatim (preserving $, %, ., digits, and accents).
    """
    if custom_3words and str(custom_3words).strip():
        clean_custom = FORBIDDEN_DEBUG_RE.sub("", str(custom_3words)).upper().strip()
        clean_custom = re.sub(r"[^A-ZÀ-Ú0-9$%.,+!?\s-]", " ", clean_custom)
        custom_tokens = [w.strip() for w in clean_custom.split() if w.strip()]
        if custom_tokens:
            return _group_into_max_three_lines(custom_tokens)

    clean = FORBIDDEN_DEBUG_RE.sub("", str(title or "")).upper().strip()
    clean = re.sub(r"[^A-ZÀ-Ú0-9$%.,+!?\s-]", " ", clean)
    raw_tokens = [w.strip(".,") if not any(c.isdigit() for c in w) else w.strip() for w in clean.split() if w.strip()]
    raw_tokens = [w for w in raw_tokens if w]

    # If the provided title is already a short 1-4 word hook (e.g. "ESCONDEU $1.4 BILHÃO" or "TUDO É DELES"), keep verbatim
    if 1 <= len(raw_tokens) <= 4:
        return _group_into_max_three_lines(raw_tokens)

    stopwords = {
        "DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS", "UM", "UMA",
        "COM", "POR", "PARA", "QUE", "COMO", "SOBRE", "ENTRE", "MAIS", "PELO", "PELA",
        "THE", "AND", "FOR", "WITH", "CON", "DEL", "LOS", "LAS", "A", "O", "E",
    }
    tokens = [w for w in raw_tokens if (len(w) >= 2 or any(c.isdigit() for c in w)) and w not in stopwords]
    if not tokens:
        tokens = ["SEGREDO", "REVELADO", "AGORA!"]
    picked = tokens[:3]
    if len(picked) == 1:
        picked = [picked[0], "REVELADO!"]
    return picked[:3]


def _pick_best_video_frames(video_path: Path, work_dir: Path) -> List[Path]:
    """Sample 3 sharp, visually distinct frames (22%, 52%, 78%) from the video (or use image directly)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if video_path.exists() and video_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return [video_path, video_path, video_path]

    dur_s = 12.0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video_path)],
            text=True,
        ).strip()
        dur_s = max(1.0, float(out))
    except Exception:
        pass

    frames: List[Path] = []
    for idx, frac in enumerate((0.22, 0.52, 0.78), start=1):
        ts = max(0.1, min(max(0.2, dur_s - 0.2), dur_s * frac))
        fp = work_dir / f"_thumb_src_{idx}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video_path), "-frames:v", "1", str(fp)],
            check=False,
        )
        if fp.exists() and fp.stat().st_size > 200:
            frames.append(fp)

    # Fallback: create a dark obsidian synthetic frame if video has 0 extractable frames
    if not frames:
        fallback_png = work_dir / "_thumb_src_fallback.png"
        canvas_np = np.zeros((720, 1280, 3), dtype=np.uint8)
        canvas_np[:, :] = (19, 7, 11)
        cv2.circle(canvas_np, (900, 360), 220, (80, 30, 140), -1)
        cv2.imwrite(str(fallback_png), canvas_np)
        frames = [fallback_png]
    return frames


def _cutout_subject_u2netp(frame_png: Path, out_cutout_png: Path) -> Tuple[Optional[skia.Image], Tuple[int, int, int, int]]:
    """Run u2netp ONNX model directly on frame_png to isolate the foreground subject and return (skia.Image, bbox)."""
    bgr = cv2.imread(str(frame_png), cv2.IMREAD_COLOR)
    if bgr is None:
        return None, (0, 0, 400, 600)
    h, w = bgr.shape[:2]

    try:
        sess = _get_u2netp_session()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        norm = (resized - mean) / std
        inp = np.transpose(norm, (2, 0, 1))[np.newaxis, :, :, :].astype(np.float32)
        in_name = sess.get_inputs()[0].name
        pred = sess.run(None, {in_name: inp})[0][0, 0]
        p_min, p_max = float(np.min(pred)), float(np.max(pred))
        mask_320 = (pred - p_min) / max(1e-5, p_max - p_min)
        alpha = (cv2.resize(mask_320, (w, h), interpolation=cv2.INTER_LINEAR) * 255.0).astype(np.uint8)

        ys, xs = np.where(alpha > 45)
        cov = len(xs) / float(max(1, h * w))
        if len(xs) > 400 and 0.03 <= cov <= 0.90:
            rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = alpha
            pad = 16
            x0, x1 = max(0, int(np.min(xs)) - pad), min(w, int(np.max(xs)) + pad)
            y0, y1 = max(0, int(np.min(ys)) - pad), min(h, int(np.max(ys)) + pad)
            cropped = rgba[y0:y1, x0:x1]
            ok, enc = cv2.imencode(".png", cropped)
            if ok:
                out_cutout_png.write_bytes(enc.tobytes())
                return skia.Image.open(str(out_cutout_png)), (x0, y0, x1 - x0, y1 - y0)
    except Exception:
        pass

    # Fallback: rounded oval alpha mask around the primary right/center character or subject
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    cx, cy = int(w * 0.62), int(h * 0.52)
    rx, ry = int(w * 0.26), int(h * 0.42)
    x0, x1 = max(0, cx - rx), min(w, cx + rx)
    y0, y1 = max(0, cy - ry), min(h, cy + ry)
    crop = rgba[y0:y1, x0:x1].copy()
    ch, cw = crop.shape[:2]
    yy, xx = np.ogrid[:ch, :cw]
    dist = ((xx - cw * 0.5) / max(1.0, cw * 0.47)) ** 2 + ((yy - ch * 0.5) / max(1.0, ch * 0.48)) ** 2
    mask = np.clip((1.05 - dist) * 255.0, 0, 255).astype(np.uint8)
    crop[:, :, 3] = mask
    ok, enc = cv2.imencode(".png", crop)
    if ok:
        out_cutout_png.write_bytes(enc.tobytes())
        return skia.Image.open(str(out_cutout_png)), (x0, y0, cw, ch)
    return None, (0, 0, 400, 600)


def _draw_curved_pointer_arrow(
    canvas: skia.Canvas,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color_hex: str = "#FF2E93",
) -> None:
    """Draw a high-CTR YouTube thumbnail arrow with thick black outline and neon glow."""
    path = skia.Path()
    ctrl_x = (x0 + x1) * 0.5 + 36.0
    ctrl_y = min(y0, y1) - 65.0
    path.moveTo(x0, y0)
    path.quadTo(ctrl_x, ctrl_y, x1, y1)

    glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=22.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia(color_hex),
    )
    glow.setImageFilter(skia.ImageFilters.DropShadow(0, 6, 18, 18, skia.ColorSetARGB(220, 0, 0, 0)))
    outline = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=30.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorBLACK,
    )
    canvas.drawPath(path, outline)
    canvas.drawPath(path, glow)

    # Arrowhead at (x1, y1)
    ang = math.atan2(y1 - ctrl_y, x1 - ctrl_x)
    head = skia.Path()
    head.moveTo(x1, y1)
    head.lineTo(x1 - 44 * math.cos(ang - 0.55), y1 - 44 * math.sin(ang - 0.55))
    head.lineTo(x1 - 44 * math.cos(ang + 0.55), y1 - 44 * math.sin(ang + 0.55))
    head.close()
    canvas.drawPath(
        head,
        skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=12.0,
            StrokeJoin=skia.Paint.kRound_Join,
            Color=skia.ColorBLACK,
        ),
    )
    canvas.drawPath(head, skia.Paint(AntiAlias=True, Color=hex_to_skia(color_hex)))


def _measure_text_safe(font: skia.Font, text: str) -> Tuple[float, float]:
    """Return (visual_width, left_overhang_shift) accounting for glyph bounding box."""
    bounds = skia.Rect()
    adv = float(font.measureText(text, skia.TextEncoding.kUTF8, bounds))
    left_shift = max(0.0, -float(bounds.fLeft))
    vis_w = max(adv, float(bounds.fRight) + left_shift)
    return vis_w, left_shift


def _draw_stacked_3word_headline(
    canvas: skia.Canvas,
    words: List[str],
    x_left: float,
    y_top: float,
    max_w: float,
    anton_tf: skia.Typeface,
    mont_tf: skia.Typeface,
    palette: List[Tuple[str, Optional[str]]],  # (text_hex, optional_pill_bg_hex)
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
) -> None:
    """Render up to 3 massive stacked thumbnail lines with guaranteed safe bounds (zero edge clipping)."""
    lines = [str(w).strip() for w in words[:3] if str(w).strip()]
    if not lines:
        return

    safe_x_left = max(74.0, x_left)
    avail_w = min(max_w - 48.0, canvas_w - safe_x_left - 80.0)

    prepared = []
    total_block_h = 0.0
    gap_y = 38.0
    for idx, word in enumerate(lines):
        tf = anton_tf if idx % 2 == 0 else mont_tf
        size = 104.0
        font = skia.Font(tf, size)
        vis_w, left_shift = _measure_text_safe(font, word)
        while size > 36.0 and vis_w > avail_w:
            size -= 2.0
            font = skia.Font(tf, size)
            vis_w, left_shift = _measure_text_safe(font, word)
        prepared.append((idx, word, font, size, vis_w, left_shift))
        total_block_h += size * 0.98
    total_block_h += gap_y * max(0, len(prepared) - 1)

    # Vertically center the stacked headline inside safe vertical zone [82 .. canvas_h - 82]
    start_top = max(82.0, min(canvas_h - 82.0 - total_block_h, (canvas_h - total_block_h) * 0.48))
    cursor_y = start_top

    for idx, word, font, size, vis_w, left_shift in prepared:
        txt_hex, pill_hex = palette[idx % len(palette)]
        cursor_y += size * 0.94
        draw_x = safe_x_left + left_shift

        if pill_hex:
            pill_x = max(36.0, safe_x_left - 20.0)
            pill_w = min(canvas_w - pill_x - 36.0, vis_w + 46.0)
            pr = skia.Rect.MakeXYWH(pill_x, cursor_y - size * 1.04, pill_w, size * 1.22)
            pp = skia.Paint(AntiAlias=True, Color=hex_to_skia(pill_hex))
            pp.setImageFilter(skia.ImageFilters.DropShadow(0, 8, 18, 18, skia.ColorSetARGB(210, 0, 0, 0)))
            canvas.drawRoundRect(pr, 20, 20, pp)
            canvas.drawRoundRect(
                pr,
                20,
                20,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6.0, Color=skia.ColorBLACK),
            )

        stroke_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=14.0,
            StrokeJoin=skia.Paint.kRound_Join,
            Color=skia.ColorBLACK,
        )
        stroke_p.setImageFilter(skia.ImageFilters.DropShadow(0, 8, 16, 16, skia.ColorSetARGB(235, 0, 0, 0)))
        if not pill_hex:
            canvas.drawString(word, draw_x, cursor_y, font, stroke_p)
        canvas.drawString(word, draw_x, cursor_y, font, skia.Paint(AntiAlias=True, Color=hex_to_skia(txt_hex)))
        cursor_y += gap_y


def generate_ab_thumbnails_16x9(
    video_path: Union[str, Path],
    title: str,
    output_dir: Union[str, Path],
    custom_3words: Optional[str] = None,
) -> Dict[str, str]:
    """Generate 3 high-CTR 1280x720 A/B/C YouTube thumbnails in output_dir:
      - thumb_A_mystery.jpg
      - thumb_B_contrast.jpg
      - thumb_C_zoom.jpg
    Accepts `custom_3words` so pre-seeded channel episodes (e.g. "ESCONDEU $1.4 BILHÃO" or "HID $1.4 BILLION")
    render verbatim with zero clipped text at the edges.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    W, H = 1280, 720
    words = _extract_three_impact_words(title, custom_3words=custom_3words)
    anton_tf, _ = _load_verified_typeface("Anton-Regular.ttf", role="thumb_anton")
    mont_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="thumb_montserrat")

    src_frames = _pick_best_video_frames(video_path, work_dir)
    if not src_frames:
        raise RuntimeError(f"Não foi possível extrair frames de {video_path} para gerar thumbnails.")

    cutout_png = work_dir / "_thumb_subject_cutout.png"
    subject_img, _ = _cutout_subject_u2netp(src_frames[min(1, len(src_frames) - 1)], cutout_png)
    bg_img_a = skia.Image.open(str(src_frames[0]))
    bg_img_c = skia.Image.open(str(src_frames[-1]))

    # =========================================================================
    # THUMB A: MYSTERY / TRUE-CRIME CURIOSITY GAP (thumb_A_mystery.jpg)
    # =========================================================================
    surf_a = skia.Surface(W, H)
    ca = surf_a.getCanvas()
    ca.clear(hex_to_skia("#0B0713"))

    # Blurred dark dramatic background + crimson radial spotlight
    if bg_img_a:
        blur_p = skia.Paint(AntiAlias=True)
        blur_p.setImageFilter(skia.ImageFilters.Blur(14.0, 14.0))
        ca.drawImageRect(bg_img_a, skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kLinear), blur_p)
    dark_grad = skia.Paint()
    dark_grad.setShader(
        skia.GradientShader.MakeRadial(
            (W * 0.72, H * 0.50),
            W * 0.65,
            [skia.ColorSetARGB(170, 255, 46, 147), skia.ColorSetARGB(235, 11, 7, 19)],
        )
    )
    ca.drawRect(skia.Rect.MakeWH(W, H), dark_grad)

    # Subject cutout on right with intense Pink (#FF2E93) rim-light & True-Crime Eye Censor Bar!
    bar_x = W * 0.66
    bar_y = H * 0.30
    bar_w = 260.0
    if subject_img:
        sw_i, sh_i = subject_img.width(), subject_img.height()
        target_h = H * 0.86
        raw_tw = target_h * (sw_i / max(1.0, float(sh_i)))
        target_w = max(W * 0.32, min(W * 0.44, raw_tw))
        sx = W - target_w - 48.0
        sy = H - target_h - 12.0
        dst_rect = skia.Rect.MakeXYWH(sx, sy, target_w, target_h)

        rim_p = skia.Paint(AntiAlias=True)
        rim_p.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 24, 24, hex_to_skia("#FF2E93")))
        ca.drawImageRect(subject_img, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear), rim_p)
        ca.drawImageRect(subject_img, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear))

        bar_y = max(110.0, min(H - 160.0, sy + target_h * 0.25))
        bar_w = max(210.0, min(310.0, target_w * 0.72))
        bar_x = max(W * 0.55, min(W - bar_w - 48.0, sx + (target_w - bar_w) * 0.5))

    # True-Crime Eye Censor Bar (guaranteed inside right column with zero edge clipping)
    ca.save()
    ca.translate(bar_x + bar_w * 0.5, bar_y)
    ca.rotate(-4.5)
    bar_r = skia.Rect.MakeXYWH(-bar_w * 0.5, -26, bar_w, 52)
    ca.drawRoundRect(bar_r, 8, 8, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
    ca.drawRoundRect(
        bar_r,
        8,
        8,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0, Color=hex_to_skia("#FFD166")),
    )
    tag_txt = "CENSURADO"
    tag_size = 25.0
    tag_font = skia.Font(mont_tf, tag_size)
    while tag_size > 16.0 and tag_font.measureText(tag_txt) > bar_w - 28.0:
        tag_size -= 1.5
        tag_font = skia.Font(mont_tf, tag_size)
    tw_tag = tag_font.measureText(tag_txt)
    ca.drawString(tag_txt, -tw_tag * 0.5, 9.0, tag_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
    ca.restore()

    # Pointer arrow from headline to mystery eye-bar
    _draw_curved_pointer_arrow(ca, W * 0.45, H * 0.36, bar_x - 16.0, bar_y, "#FFD166")

    _draw_stacked_3word_headline(
        ca,
        words,
        x_left=76.0,
        y_top=120.0,
        max_w=W * 0.49,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        palette=[("#FFFFFF", None), ("#0B0713", "#FFD166"), ("#FF2E93", None)],
        canvas_w=W,
        canvas_h=H,
    )
    thumb_a_path = output_dir / "thumb_A_mystery.jpg"
    surf_a.makeImageSnapshot().save(str(thumb_a_path), skia.kJPEG)

    # =========================================================================
    # THUMB B: HIGH-VOLTAGE NEON SPLIT CONTRAST (thumb_B_contrast.jpg)
    # =========================================================================
    surf_b = skia.Surface(W, H)
    cb = surf_b.getCanvas()
    cb.clear(hex_to_skia("#140E24"))

    # Electric diagonal split background (#0B0713 left, #FF2E93 / #B388FF right)
    bg_split = skia.Paint()
    bg_split.setShader(
        skia.GradientShader.MakeLinear(
            [(0, 0), (W, H)],
            [hex_to_skia("#0B0713"), hex_to_skia("#140E24"), hex_to_skia("#FF2E93")],
            [0.0, 0.55, 1.0],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), bg_split)

    # Diagonal Lime Green (#B8FF01) accent lightning slash
    slash = skia.Path()
    slash.moveTo(W * 0.56, 0)
    slash.lineTo(W * 0.60, 0)
    slash.lineTo(W * 0.48, H)
    slash.lineTo(W * 0.44, H)
    slash.close()
    cb.drawPath(slash, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    if subject_img:
        sw_i, sh_i = subject_img.width(), subject_img.height()
        target_h = H * 0.88
        raw_tw = target_h * (sw_i / max(1.0, float(sh_i)))
        target_w = max(W * 0.32, min(W * 0.44, raw_tw))
        sx = W - target_w - 44.0
        sy = H - target_h - 10.0
        dst_rect = skia.Rect.MakeXYWH(sx, sy, target_w, target_h)

        glow_b = skia.Paint(AntiAlias=True)
        glow_b.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 26, 26, hex_to_skia("#B8FF01")))
        cb.drawImageRect(subject_img, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear), glow_b)
        cb.drawImageRect(subject_img, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear))

    _draw_stacked_3word_headline(
        cb,
        words,
        x_left=76.0,
        y_top=125.0,
        max_w=W * 0.48,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        palette=[("#0B0713", "#B8FF01"), ("#FFFFFF", None), ("#FFD166", "#FF2E93")],
        canvas_w=W,
        canvas_h=H,
    )
    thumb_b_path = output_dir / "thumb_B_contrast.jpg"
    surf_b.makeImageSnapshot().save(str(thumb_b_path), skia.kJPEG)

    # =========================================================================
    # THUMB C: EXTREME FOCAL ZOOM + TARGET CIRCLE & ARROW (thumb_C_zoom.jpg)
    # =========================================================================
    surf_c = skia.Surface(W, H)
    cc = surf_c.getCanvas()
    cc.clear(skia.ColorBLACK)

    if bg_img_c:
        # 1.28x dramatic zoom crop into scene
        cc.save()
        cc.translate(W * 0.56, H * 0.50)
        cc.scale(1.28, 1.28)
        cc.translate(-W * 0.50, -H * 0.50)
        cc.drawImageRect(bg_img_c, skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kLinear))
        cc.restore()

    # Left-side dark gradient scrim so 3-word text pops with 100% legibility
    left_scrim = skia.Paint()
    left_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0, 0), (W * 0.72, 0)],
            [skia.ColorSetARGB(235, 11, 7, 19), skia.ColorSetARGB(165, 20, 14, 36), skia.ColorSetARGB(0, 11, 7, 19)],
            [0.0, 0.58, 1.0],
        )
    )
    cc.drawRect(skia.Rect.MakeWH(W, H), left_scrim)

    # High-CTR Pink (#FF2E93) Focus Target Circle + Lime (#B8FF01) Curved Arrow on right focal point
    focus_x, focus_y = W * 0.75, H * 0.48
    ring_out = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=18.0, Color=skia.ColorBLACK)
    ring_in = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=11.0, Color=hex_to_skia("#FF2E93"))
    ring_in.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 16, 16, hex_to_skia("#FF2E93")))
    cc.drawCircle(focus_x, focus_y, 134.0, ring_out)
    cc.drawCircle(focus_x, focus_y, 134.0, ring_in)
    _draw_curved_pointer_arrow(cc, W * 0.46, H * 0.58, focus_x - 132.0, focus_y + 18.0, "#B8FF01")

    _draw_stacked_3word_headline(
        cc,
        words,
        x_left=76.0,
        y_top=120.0,
        max_w=W * 0.48,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        palette=[("#FFD166", None), ("#FFFFFF", "#FF2E93"), ("#B8FF01", None)],
        canvas_w=W,
        canvas_h=H,
    )
    thumb_c_path = output_dir / "thumb_C_zoom.jpg"
    surf_c.makeImageSnapshot().save(str(thumb_c_path), skia.kJPEG)

    return {
        "thumb_a": str(thumb_a_path),
        "thumb_b": str(thumb_b_path),
        "thumb_c": str(thumb_c_path),
        "headline_words": " ".join(words),
        "lines": words,
    }
