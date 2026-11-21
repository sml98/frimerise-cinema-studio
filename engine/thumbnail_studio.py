"""FrimeRise Cinema 16:9 A/B/C Thumbnail Studio (1280x720 Netflix / MagnatesMedia / Dark History Covers).

Generates 3 genuine movie-poster / editorial documentary 1280x720 thumbnails for any topic:
  1. thumb_A_mystery.jpg  — Dark Cinema / Editorial Mystery (full-bleed hero artwork on right 65%,
                            sweeping obsidian mist from left, subtle crimson/amber light leak,
                            35mm film grain, 3D gradient movie-poster typography + thin hairline accent)
  2. thumb_B_contrast.jpg — High-Drama Split Lighting / Subject Rim Glow (cold-teal vs. warm-amber/crimson
                            atmospheric split backdrop, u2netp soft-feathered foreground subject cutout
                            with volumetric shoulder/head rim-light halo, shallow DOF lens bokeh,
                            metallic-gold & ice-white cinema headline)
  3. thumb_C_zoom.jpg     — Intense Close-Up Chiaroscuro + Editorial Vignette (tight 1.32x focal close-up,
                            deep moody vignette, subtle glowing spotlight flare, delicate 1.5px cinema-glass
                            corner viewfinder marks, bold lower-left/mid-left movie title lockup)

Hero Artwork Pipeline:
  1. Bespoke zero-text 16:9 hero artwork via user's LIVE Gemini Image API (`gemini-2.5-flash-image`,
     fallback `gemini-3.1-flash-image`, header `x-goog-api-key`) with persistent disk caching.
  2. Fallback (a): High-resolution editorial photography via `engine.doc_media_engine.fetch_doc_real_photo`
     driven by universal topic art direction (fast Gemini text planner + deterministic offline fallback).
  3. Fallback (b): Sharpest, cleanest video frame extracted from `video_path`.

Zero flat colored text pills/boxes, zero MS-Paint arrows/circles, zero jagged cutouts, zero edge clipping.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import cv2
import httpx
import numpy as np
import skia

from database import get_settings
from engine.skia_compositor import FORBIDDEN_DEBUG_RE, _load_verified_typeface, hex_to_skia

BASE_DIR = Path(__file__).resolve().parent.parent
THUMB_HERO_CACHE_DIR = BASE_DIR / "data" / "thumb_hero_cache"
THUMB_HERO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_IMAGE_MODELS: Tuple[str, ...] = (
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
)
GEMINI_TEXT_PLANNER_MODELS: Tuple[str, ...] = (
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
)

_REMBG_SESSION = None
_GEMINI_IMAGE_QUOTA_EXHAUSTED = False


# ---------------------------------------------------------------------------
# Color Gradient Presets (3D Movie-Poster Typography)
# ---------------------------------------------------------------------------
TYPO_GRADIENTS: Dict[str, Dict[str, Any]] = {
    "ice_white": {
        "stops": ["#FFFFFF", "#F1F5F9", "#CBD5E1", "#94A3B8"],
        "positions": [0.0, 0.48, 0.80, 1.0],
        "extrude": "#06080E",
        "glow": None,
    },
    "gold": {
        "stops": ["#FFF6C4", "#FFD166", "#DC941C", "#A45B09"],
        "positions": [0.0, 0.42, 0.76, 1.0],
        "extrude": "#1C0F02",
        "glow": "#FFB703",
    },
    "crimson": {
        "stops": ["#FF758F", "#E11D48", "#B91C1C", "#7F1D1D"],
        "positions": [0.0, 0.42, 0.76, 1.0],
        "extrude": "#1E0309",
        "glow": "#E11D48",
    },
    "amber_flame": {
        "stops": ["#FFF2B2", "#FBBF24", "#E85D04", "#9D2B0B"],
        "positions": [0.0, 0.42, 0.78, 1.0],
        "extrude": "#1F0902",
        "glow": "#F59E0B",
    },
}

MOOD_PALETTES: Dict[str, Dict[str, Any]] = {
    "dark_horror": {
        "a_accent_grad": "crimson",
        "a_bar_hex": "#E11D48",
        "a_leak_rgb": (225, 29, 72),
        "a_leak_warm_rgb": (234, 88, 12),
        "b_cold_rgb": (10, 44, 58),
        "b_warm_rgb": (158, 22, 42),
        "b_rim_warm_rgb": (255, 130, 56),
        "b_rim_outer_rgb": (225, 29, 72),
        "b_rim_cold_rgb": (56, 189, 248),
        "b_accent_grad": "gold",
        "b_bar_hex": "#FFD166",
        "c_accent_grad": "crimson",
        "c_flare_rgb": (255, 168, 76),
        "c_bar_hex": "#E11D48",
    },
    "mystery_crime": {
        "a_accent_grad": "crimson",
        "a_bar_hex": "#E11D48",
        "a_leak_rgb": (220, 38, 38),
        "a_leak_warm_rgb": (245, 158, 11),
        "b_cold_rgb": (12, 48, 66),
        "b_warm_rgb": (150, 26, 48),
        "b_rim_warm_rgb": (255, 160, 64),
        "b_rim_outer_rgb": (225, 29, 72),
        "b_rim_cold_rgb": (56, 189, 248),
        "b_accent_grad": "gold",
        "b_bar_hex": "#FFD166",
        "c_accent_grad": "gold",
        "c_flare_rgb": (255, 200, 96),
        "c_bar_hex": "#FFD166",
    },
    "wealth_power": {
        "a_accent_grad": "gold",
        "a_bar_hex": "#FFD166",
        "a_leak_rgb": (217, 119, 6),
        "a_leak_warm_rgb": (255, 209, 102),
        "b_cold_rgb": (8, 42, 56),
        "b_warm_rgb": (146, 56, 14),
        "b_rim_warm_rgb": (255, 198, 84),
        "b_rim_outer_rgb": (217, 119, 6),
        "b_rim_cold_rgb": (56, 189, 248),
        "b_accent_grad": "gold",
        "b_bar_hex": "#FFD166",
        "c_accent_grad": "gold",
        "c_flare_rgb": (255, 209, 102),
        "c_bar_hex": "#FFD166",
    },
    "epic_history": {
        "a_accent_grad": "gold",
        "a_bar_hex": "#FFD166",
        "a_leak_rgb": (217, 70, 24),
        "a_leak_warm_rgb": (251, 191, 36),
        "b_cold_rgb": (12, 44, 62),
        "b_warm_rgb": (154, 48, 18),
        "b_rim_warm_rgb": (255, 184, 76),
        "b_rim_outer_rgb": (220, 62, 32),
        "b_rim_cold_rgb": (56, 189, 248),
        "b_accent_grad": "gold",
        "b_bar_hex": "#FFD166",
        "c_accent_grad": "amber_flame",
        "c_flare_rgb": (255, 190, 88),
        "c_bar_hex": "#FFD166",
    },
    "sci_tech": {
        "a_accent_grad": "gold",
        "a_bar_hex": "#F59E0B",
        "a_leak_rgb": (234, 88, 12),
        "a_leak_warm_rgb": (56, 189, 248),
        "b_cold_rgb": (8, 48, 68),
        "b_warm_rgb": (154, 44, 24),
        "b_rim_warm_rgb": (255, 166, 68),
        "b_rim_outer_rgb": (234, 88, 12),
        "b_rim_cold_rgb": (56, 189, 248),
        "b_accent_grad": "gold",
        "b_bar_hex": "#FFD166",
        "c_accent_grad": "gold",
        "c_flare_rgb": (255, 196, 92),
        "c_bar_hex": "#FFD166",
    },
}


# ---------------------------------------------------------------------------
# ONNX u2netp Foreground Session
# ---------------------------------------------------------------------------
def _get_u2netp_session():
    """Load ~/.u2net/u2netp.onnx directly via ONNXRuntime (Core i5 CPU friendly, 2 threads)."""
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


def _predict_u2netp_mask(bgr: np.ndarray) -> Optional[np.ndarray]:
    """Return a float32 [0..1] foreground probability map at bgr's exact (H, W) resolution."""
    if bgr is None or bgr.size == 0:
        return None
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
        if p_max - p_min < 1e-4:
            return None
        mask_320 = (pred - p_min) / (p_max - p_min)
        mask_full = cv2.resize(mask_320.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        return np.clip(mask_full, 0.0, 1.0)
    except Exception:
        return None


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / max(1e-6, edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _refine_soft_alpha_matte(raw_mask: np.ndarray) -> np.ndarray:
    """Clean u2netp speckles, smooth silhouette edges with Gaussian feathering, ZERO jagged halos."""
    h, w = raw_mask.shape[:2]
    # Soft S-curve ramp pushes background haze cleanly to 0 while keeping soft hair/fur transitions
    ramped = _smoothstep(0.18, 0.76, raw_mask)

    # Remove tiny isolated background specks using connected components on binary core
    core = (ramped > 0.30).astype(np.uint8)
    k_morph = max(3, int(round(min(h, w) * 0.008)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_morph, k_morph))
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, kernel)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    if num_labels > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        max_area = int(np.max(areas)) if len(areas) > 0 else 0
        keep = np.zeros_like(core, dtype=np.float32)
        for lbl in range(1, num_labels):
            if stats[lbl, cv2.CC_STAT_AREA] >= max(250, int(max_area * 0.08)):
                keep[labels == lbl] = 1.0
        # Dilate keep region slightly so soft hair tendrils around the main subject stay intact
        k_dil = max(7, int(round(min(h, w) * 0.022)) | 1)
        keep_soft = cv2.GaussianBlur(
            cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_dil, k_dil))),
            (0, 0),
            sigmaX=max(2.0, min(h, w) * 0.006),
        )
        ramped = ramped * np.clip(keep_soft, 0.0, 1.0)

    # Silky Gaussian edge feathering so cutout boundaries never look jagged
    sigma = max(2.0, min(h, w) * 0.0042)
    feathered = cv2.GaussianBlur(ramped.astype(np.float32), (0, 0), sigmaX=sigma, sigmaY=sigma)
    # Slight gamma tightening preserves core opacity while keeping edges velvety smooth
    feathered = np.clip(np.power(np.clip(feathered, 0.0, 1.0), 0.92), 0.0, 1.0)
    return feathered


def _cutout_subject_u2netp(
    frame_or_bgr: Union[Path, np.ndarray],
    out_cutout_png: Optional[Path] = None,
) -> Tuple[Optional[np.ndarray], float, Dict[str, Any]]:
    """Isolate foreground subject with u2netp + soft-feathered matte, edge decontamination,
    and organic border dissolves so it composites like a studio movie poster (ZERO jagged artifacts).
    Returns `(bgra_cropped_uint8, coverage_ratio, meta_dict)`.
    """
    if isinstance(frame_or_bgr, np.ndarray):
        bgr = frame_or_bgr.copy()
    else:
        bgr = cv2.imread(str(frame_or_bgr), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None, 0.0, {}

    h, w = bgr.shape[:2]
    raw_mask = _predict_u2netp_mask(bgr)
    if raw_mask is None:
        return None, 0.0, {}

    alpha_f = _refine_soft_alpha_matte(raw_mask)
    ys, xs = np.where(alpha_f > 0.25)
    cov = float(len(xs)) / float(max(1, h * w))
    if len(xs) < 600 or cov < 0.04 or cov > 0.92:
        return None, cov, {}

    pad = max(14, int(round(min(h, w) * 0.02)))
    x0 = max(0, int(np.min(xs)) - pad)
    x1 = min(w, int(np.max(xs)) + pad)
    y0 = max(0, int(np.min(ys)) - pad)
    y1 = min(h, int(np.max(ys)) + pad)

    crop_bgr = bgr[y0:y1, x0:x1].astype(np.float32)
    crop_alpha = alpha_f[y0:y1, x0:x1].copy()
    ch, cw = crop_bgr.shape[:2]

    # Edge color decontamination: pull translucent fringe pixels slightly darker/inward
    # to eliminate bright background halo rings around hair/shoulders.
    eroded_core = cv2.erode((crop_alpha > 0.85).astype(np.uint8), np.ones((5, 5), np.uint8))
    fringe = (crop_alpha > 0.02) & (eroded_core == 0)
    if np.any(fringe):
        # Smooth inward color bleed + gentle shadow pull on outer translucent edge
        blur_bgr = cv2.GaussianBlur(crop_bgr, (0, 0), sigmaX=3.0)
        edge_strength = np.clip(1.0 - crop_alpha, 0.0, 1.0)[:, :, np.newaxis]
        # Darken outer fringe gently toward deep cinema shadow so bright halos vanish
        decontam = crop_bgr * (1.0 - 0.35 * edge_strength) + blur_bgr * (0.20 * edge_strength)
        crop_bgr = np.where(fringe[:, :, np.newaxis], decontam, crop_bgr)

    touches_left = x0 <= 4
    touches_right = x1 >= w - 4
    touches_top = y0 <= 4
    touches_bottom = y1 >= h - 4

    # Smooth horizontal feather if subject extends off original left edge (no hard rectangular chop!)
    if touches_left and cw > 40:
        fade_w = max(24, int(cw * 0.16))
        ramp_x = _smoothstep(0.0, float(fade_w), np.arange(cw, dtype=np.float32))[np.newaxis, :]
        crop_alpha *= ramp_x

    # Smooth top feather if hair/subject touched top edge of source frame
    if touches_top and ch > 40:
        fade_t = max(14, int(ch * 0.07))
        ramp_t = _smoothstep(0.0, float(fade_t), np.arange(ch, dtype=np.float32))[:, np.newaxis]
        crop_alpha *= ramp_t

    # Organic bottom mist dissolve so torso/base melts cleanly into dark lower foreground
    if ch > 60:
        fade_b = max(24, int(ch * 0.12))
        dist_from_bottom = (ch - 1 - np.arange(ch, dtype=np.float32))[:, np.newaxis]
        ramp_b = _smoothstep(0.0, float(fade_b), dist_from_bottom)
        crop_alpha *= ramp_b

    bgra = np.zeros((ch, cw, 4), dtype=np.uint8)
    bgra[:, :, :3] = np.clip(crop_bgr, 0, 255).astype(np.uint8)
    bgra[:, :, 3] = np.clip(crop_alpha * 255.0, 0, 255).astype(np.uint8)

    if out_cutout_png is not None:
        ok, enc = cv2.imencode(".png", bgra)
        if ok:
            out_cutout_png.write_bytes(enc.tobytes())

    meta = {
        "bbox": (x0, y0, cw, ch),
        "touches_left": touches_left,
        "touches_right": touches_right,
        "touches_top": touches_top,
        "touches_bottom": touches_bottom,
        "coverage": cov,
    }
    return bgra, cov, meta


def _fallback_feathered_vignette_cutout(bgr: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Graceful ultra-soft elliptical feathered cutout when no crisp separable silhouette exists."""
    h, w = bgr.shape[:2]
    cx, cy = int(w * 0.54), int(h * 0.46)
    rx, ry = int(w * 0.34), int(h * 0.44)
    x0, x1 = max(0, cx - rx), min(w, cx + rx)
    y0, y1 = max(0, cy - ry), min(h, cy + ry)
    crop = bgr[y0:y1, x0:x1].copy()
    ch, cw = crop.shape[:2]
    yy, xx = np.ogrid[:ch, :cw]
    nx = (xx - cw * 0.5) / max(1.0, cw * 0.46)
    ny = (yy - ch * 0.48) / max(1.0, ch * 0.46)
    r2 = nx * nx + ny * ny
    alpha = (1.0 - _smoothstep(0.45, 1.02, r2)).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=max(8.0, min(ch, cw) * 0.04))
    bgra = np.zeros((ch, cw, 4), dtype=np.uint8)
    bgra[:, :, :3] = crop
    bgra[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return bgra, {
        "bbox": (x0, y0, cw, ch),
        "touches_left": False,
        "touches_right": False,
        "touches_top": False,
        "touches_bottom": True,
        "coverage": 0.35,
    }


# ---------------------------------------------------------------------------
# Smart Universal Topic Art Director & Headline Distillation
# ---------------------------------------------------------------------------
def _group_into_max_three_lines(tokens: List[str]) -> List[str]:
    """Group a token list into at most 3 stacked lines while keeping every token verbatim."""
    if len(tokens) <= 3:
        return tokens
    if len(tokens) == 4:
        pairs = [
            ([f"{tokens[0]} {tokens[1]}", tokens[2], tokens[3]], len(tokens[0]) + len(tokens[1])),
            ([tokens[0], f"{tokens[1]} {tokens[2]}", tokens[3]], len(tokens[1]) + len(tokens[2])),
            ([tokens[0], tokens[1], f"{tokens[2]} {tokens[3]}"], len(tokens[2]) + len(tokens[3])),
        ]
        pairs.sort(key=lambda item: item[1])
        return pairs[0][0]
    n = len(tokens)
    c1 = max(1, round(n / 3))
    c2 = max(c1 + 1, round(2 * n / 3))
    return [
        " ".join(tokens[:c1]),
        " ".join(tokens[c1:c2]),
        " ".join(tokens[c2:]),
    ]


def _sanitize_headline_tokens(raw_text: str) -> List[str]:
    clean = FORBIDDEN_DEBUG_RE.sub("", str(raw_text or "")).upper().strip()
    clean = re.sub(r"[^A-ZÀ-Ú0-9$%.,+!?\s-]", " ", clean)
    tokens = [w.strip(".,") if not any(c.isdigit() for c in w) else w.strip() for w in clean.split() if w.strip()]
    return [w for w in tokens if w]


def _extract_three_impact_words(
    title: str,
    custom_3words: Optional[str] = None,
    llm_headline_words: Optional[List[str]] = None,
) -> List[str]:
    """Distill any video title/topic into 2-3 ultra-punchy uppercase movie-poster lines,
    or render `custom_3words` 100% verbatim (preserving $, %, ., digits, and accents).
    """
    if custom_3words and str(custom_3words).strip():
        custom_tokens = _sanitize_headline_tokens(str(custom_3words))
        if custom_tokens:
            return _group_into_max_three_lines(custom_tokens)

    raw_tokens = _sanitize_headline_tokens(title)
    if 1 <= len(raw_tokens) <= 3:
        return _group_into_max_three_lines(raw_tokens)

    if llm_headline_words:
        cleaned_llm: List[str] = []
        for item in llm_headline_words[:3]:
            toks = _sanitize_headline_tokens(item)
            if toks:
                cleaned_llm.append(" ".join(toks[:2]))
        if 1 <= len(cleaned_llm) <= 3:
            if len(cleaned_llm) == 1 and " " in cleaned_llm[0]:
                return _group_into_max_three_lines(cleaned_llm[0].split())
            return cleaned_llm

    # Smart offline distillation: filter both grammatical stopwords AND generic documentary fillers
    stopwords = {
        "DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS", "UM", "UMA",
        "COM", "POR", "PARA", "QUE", "COMO", "SOBRE", "ENTRE", "MAIS", "PELO", "PELA",
        "THE", "AND", "FOR", "WITH", "CON", "DEL", "LOS", "LAS", "A", "O", "E", "OS", "AS",
        "OF", "IN", "ON", "TO", "FROM", "IS", "WAS", "ARE", "THIS", "THAT", "WHO", "WHY",
    }
    generic_fillers = {
        "REAL", "HISTÓRIA", "HISTORIA", "VERDADEIRA", "TRÁS", "TRAS", "PORTRÁS", "TUDO",
        "VOCÊ", "VOCE", "PRECISA", "SABER", "STORY", "TRUE", "HISTORY", "BEHIND", "ABOUT",
        "REALMENTE", "ACONTECEU", "EPISÓDIO", "DOCUMENTÁRIO", "VIDEO", "VÍDEO",
    }
    content_tokens = [
        w for w in raw_tokens
        if (len(w) >= 2 or any(c.isdigit() for c in w)) and w not in stopwords
    ]
    sharp_tokens = [w for w in content_tokens if w not in generic_fillers]

    if len(sharp_tokens) >= 2:
        # Prefer putting the topic anchor (often near the end, e.g., NATAL) paired with the strongest modifier
        if len(sharp_tokens) == 2:
            # In Portuguese/Spanish "MACABRA NATAL" reads far better as "NATAL MACABRO" if adjective came first
            w0, w1 = sharp_tokens[0], sharp_tokens[1]
            if w0 in ("MACABRA", "SOMBRIA", "OCULTA", "SECRETA", "PROIBIDA", "OBSCURA", "TERRÍVEL") and len(w1) >= 4:
                masc = w0[:-1] + "O" if w0.endswith("A") and w1.endswith(("L", "O", "R", "S")) else w0
                return [w1, masc]
            return [w0, w1]
        # Pick the first sharp hook + final topic anchor (up to 3 words)
        picked = [sharp_tokens[0], sharp_tokens[-1]] if len(sharp_tokens) > 3 else sharp_tokens[:3]
        return picked

    picked = (sharp_tokens or content_tokens)[:3]
    if not picked:
        return ["SEGREDO", "OCULTO"]
    if len(picked) == 1:
        return [picked[0], "OCULTO"]
    return picked[:3]


def _offline_art_direction(title: str) -> Dict[str, Any]:
    """Deterministic multilingual topic analyzer when LLM text planner is unavailable."""
    t = str(title or "").lower()

    if any(k in t for k in ("natal", "christmas", "krampus", "papai noel", "santa", "saturnalia", "noel")):
        return {
            "mood": "dark_horror",
            "gemini_prompts": [
                (
                    "Sinister ancient European winter folklore horned figure Krampus standing in a swirling "
                    "midnight snowstorm illuminated by a single flickering medieval oil lantern, dramatic "
                    "photorealistic cinema chiaroscuro lighting, 85mm lens, shallow depth of field, "
                    "subject framed on right two-thirds, dark atmospheric mist on left, ZERO text"
                ),
                (
                    "Haunting dramatic dark studio portrait of an ancient carved horned winter demon mask "
                    "with glowing amber eyes emerging from cold shadow and crimson ember rim light, "
                    "photorealistic dark fantasy cinema, 85mm lens, isolated foreground subject, ZERO text"
                ),
                (
                    "Extreme tight chiaroscuro close-up of a sinister weathered winter folklore figure in "
                    "falling snow illuminated by warm candlelight against pitch-black gothic night, "
                    "ultra-sharp photorealistic cinema still, shallow depth of field, ZERO text"
                ),
            ],
            "photo_queries": [
                "krampus devil mask dark",
                "winter gothic castle snow night",
                "dark snowy forest fog night",
                "gothic cathedral winter snow night",
            ],
            "auto_headline": ["NATAL", "MACABRO"],
        }

    if any(k in t for k in ("macabr", "terror", "assombr", "demôn", "demon", "brux", "witch", "ocult", "horror", "maldiç", "cursed", "ritual", "halloween", "vampir")):
        return {
            "mood": "dark_horror",
            "gemini_prompts": [
                f"Atmospheric dark horror cinema scene inspired by '{title}', eerie gothic candlelight shadows, mist and dramatic chiaroscuro, 85mm lens, subject on right, dark space on left, ZERO text",
                f"Dramatic shadowed dark-cinema portrait of a mysterious hooded figure holding an ancient lantern related to '{title}', stark rim lighting, photorealistic, ZERO text",
                f"Intense chiaroscuro close-up of eerie candlelit ancient gothic architecture and shadow for '{title}', 85mm shallow DOF, ZERO text",
            ],
            "photo_queries": [
                "hooded figure dark lantern fog",
                "gothic cathedral dark night fog",
                "creepy dark forest mist night",
                "ancient skull candle dark shadow",
            ],
            "auto_headline": [],
        }

    if any(k in t for k in ("bilhã", "bilha", "billion", "milhã", "million", "banco", "bank", "fraude", "fraud", "bolsa", "wall street", "trader", "dinheiro", "money", "império", "empire", "falência", "crash", "barings", "enron")):
        return {
            "mood": "wealth_power",
            "gemini_prompts": [
                f"MagnatesMedia style cinematic dark thriller scene for '{title}', lone silhouetted financier overlooking rain-streaked glass skyscraper skyline at midnight, cold steel blue and warm gold lighting, 85mm lens, subject on right, ZERO text",
                f"Dramatic studio chiaroscuro portrait of a shadowed dark-suited corporate executive silhouette with golden rim lighting for '{title}', photorealistic thriller cinema, ZERO text",
                f"Intense cinematic close-up of gold bullion, dark marble bank vault, and rain-drenched financial district lights at night for '{title}', chiaroscuro, ZERO text",
            ],
            "photo_queries": [
                "silhouette businessman dark window night",
                "london financial district skyscrapers night",
                "dark luxury bank vault gold",
                "stock market dark trading screen night",
            ],
            "auto_headline": [],
        }

    if any(k in t for k in ("crime", "assass", "murder", "serial", "prisão", "prison", "máfia", "mafia", "cartel", "desaparec", "fbi", "cia", "espião", "spy", "dossiê", "investig")):
        return {
            "mood": "mystery_crime",
            "gemini_prompts": [
                f"Netflix true-crime documentary cinema key art for '{title}', shadowy detective silhouette in rain-soaked nocturnal alleyway lit by crimson neon and cold streetlights, 85mm lens, subject on right, ZERO text",
                f"Dramatic silhouetted mystery figure in dark trenchcoat with harsh crimson-amber and cold-blue split rim lighting for '{title}', photorealistic cinema, ZERO text",
                f"Intense close-up of rain-streaked nocturnal city noir window and eerie red glow for '{title}', chiaroscuro documentary film still, ZERO text",
            ],
            "photo_queries": [
                "silhouette man dark alley fog night",
                "noir rain street night dark",
                "abandoned dark corridor mystery",
                "shadowy figure dark coat night",
            ],
            "auto_headline": [],
        }

    if any(k in t for k in ("ia ", "ai ", "inteligência artificial", "robô", "robot", "hacker", "cyber", "espaço", "space", "nasa", "alien", "ovni", "ufo", "futuro")):
        return {
            "mood": "sci_tech",
            "gemini_prompts": [
                f"Cinematic sci-fi documentary film still for '{title}', dramatic shadowed futuristic silhouette illuminated by cold cyan and amber volumetric light, 85mm lens, subject on right, ZERO text",
                f"Dramatic high-contrast dark studio portrait of an illuminated cybernetic silhouette with rim lighting for '{title}', photorealistic cinema, ZERO text",
                f"Intense macro chiaroscuro close-up of glowing dark futuristic monolith and moody mist for '{title}', 85mm cinema lens, ZERO text",
            ],
            "photo_queries": [
                "futuristic silhouette dark neon fog",
                "dark server room glowing lights",
                "deep space nebula dark cosmos",
                "cyberpunk dark city rain night",
            ],
            "auto_headline": [],
        }

    # Universal epic dark history / documentary default
    ascii_words = [
        w for w in re.findall(r"[a-zA-Z]{4,}", title)
        if w.lower() not in {"como", "sobre", "historia", "real", "verdade", "porque", "para", "tras", "story", "history", "behind", "about", "true"}
    ]
    base_q = " ".join(ascii_words[:3]) if ascii_words else "ancient dark mystery"
    return {
        "mood": "epic_history",
        "gemini_prompts": [
            f"Netflix dark history documentary cinema key art depicting '{title}', dramatic photorealistic historical scene with moody chiaroscuro candlelight and deep atmospheric mist, 85mm cinema lens, subject framed on right two-thirds, ZERO text",
            f"High-drama shadowed historical figure portrait emerging from atmospheric mist with warm amber and cold slate rim lighting for '{title}', photorealistic 85mm lens, ZERO text",
            f"Intense chiaroscuro cinematic close-up of dramatic historic artifact and shadowy lighting representing '{title}', shallow depth of field, ZERO text",
        ],
        "photo_queries": [
            f"{base_q} dark dramatic night",
            "ancient statue dark shadow dramatic",
            "historic cathedral dark fog night",
            "mysterious silhouette fog dramatic night",
        ],
        "auto_headline": [],
    }


def _plan_thumbnail_art_direction(title: str, custom_3words: Optional[str] = None) -> Dict[str, Any]:
    """Use fast Gemini text planner to generate topic-authentic English photography queries,
    bespoke Gemini image prompts, cinema mood, and smart 2-3 word headline (when custom_3words is None).
    Falls back seamlessly to deterministic multilingual heuristics if offline or rate-limited.
    """
    fallback = _offline_art_direction(title)
    try:
        settings = get_settings()
    except Exception:
        settings = {}
    api_key = str(settings.get("gemini_api_key") or "").strip()
    if not api_key:
        return fallback

    prompt = (
        "You are a 10M-view Netflix / MagnatesMedia / Dark History YouTube Thumbnail Art Director.\n"
        f"Video title: {title!r}\n"
        f"Custom headline (if provided): {custom_3words!r}\n\n"
        "Return STRICT JSON with exactly these keys:\n"
        '{\n'
        '  "mood": "dark_horror" | "mystery_crime" | "wealth_power" | "epic_history" | "sci_tech",\n'
        '  "gemini_prompts": [\n'
        '     "Prompt 1 (Variant A): ultra-sharp photorealistic 16:9 dark cinema scene, focal subject on RIGHT side, moody negative space on LEFT, chiaroscuro 85mm lens, STRICTLY NO TEXT",\n'
        '     "Prompt 2 (Variant B): dramatic isolated foreground hero figure/portrait/object against dark studio haze for rim-light compositing, photorealistic, NO TEXT",\n'
        '     "Prompt 3 (Variant C): intense tight close-up dramatic detail/face/artifact in chiaroscuro spotlight, shallow DOF, NO TEXT"\n'
        '  ],\n'
        "  \"photo_queries\": [\n"
        "     \"2-4 word English Pixabay query #1 for the PRIMARY iconic dark portrait/figure/creature/person of this exact topic (e.g. 'krampus devil mask dark', 'stressed businessman dark office')\",\n"
        "     \"2-4 word English Pixabay query #2 for a moody dark nocturnal architecture/landmark/setting of this topic (e.g. 'winter gothic castle snow night', 'london financial district night')\",\n"
        "     \"2-4 word English Pixabay query #3 for an eerie moody night scene or dramatic shadow portrait of this topic (MUST include 'dark' or 'night', NEVER bright daylight props or clipart)\",\n"
        "     \"2-4 word English Pixabay query #4 backup dark cinematic visual for this topic\"\n"
        "  ],\n"
        "  \"auto_headline\": [\"WORD1\", \"WORD2\"]\n"
        "}\n"
        "Rules:\n"
        "- `photo_queries` MUST be crisp 2-4 word English visual nouns/adjectives that return real dramatic DARK photographs on Pixabay (e.g. 'krampus devil mask dark', 'winter gothic castle snow night', 'silhouette businessman skyscraper night'). NEVER use abstract words like 'truth' or 'history', and NEVER suggest bright sunlit toys/dolls or clipart!\n"
        "- `auto_headline`: 2 to 3 ULTRA-PUNCHY uppercase words in the SAME LANGUAGE as the video title (e.g. for 'A real história macabra por trás do Natal' -> ['NATAL', 'MACABRO']).\n"
        "- Output valid JSON ONLY, no markdown fences."
    )

    for model in GEMINI_TEXT_PLANNER_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            resp = httpx.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.25,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=12.0,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            raw_txt = "".join(str(p.get("text") or "") for p in parts).strip()
            if not raw_txt:
                continue
            raw_txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt, flags=re.IGNORECASE | re.DOTALL).strip()
            parsed = json.loads(raw_txt)
            if not isinstance(parsed, dict):
                continue

            mood = str(parsed.get("mood") or fallback["mood"]).strip().lower()
            if mood not in MOOD_PALETTES:
                mood = fallback["mood"]

            g_prompts = [str(x).strip() for x in (parsed.get("gemini_prompts") or []) if str(x).strip()]
            if len(g_prompts) < 3:
                g_prompts = (g_prompts + fallback["gemini_prompts"])[:3]

            p_queries = [str(x).strip() for x in (parsed.get("photo_queries") or []) if str(x).strip()]
            if len(p_queries) < 3:
                p_queries = (p_queries + fallback["photo_queries"])[:4]

            auto_hl = [str(x).strip() for x in (parsed.get("auto_headline") or []) if str(x).strip()][:3]
            return {
                "mood": mood,
                "gemini_prompts": g_prompts[:3],
                "photo_queries": p_queries[:4],
                "auto_headline": auto_hl or fallback.get("auto_headline", []),
            }
        except Exception:
            continue

    return fallback


# ---------------------------------------------------------------------------
# 1. Bespoke Hero Artwork via LIVE Gemini Image API + Disk Cache
# ---------------------------------------------------------------------------
def _validate_decoded_bgr(bgr: Optional[np.ndarray], min_w: int = 400, min_h: int = 220) -> bool:
    if bgr is None or bgr.size == 0 or bgr.ndim != 3:
        return False
    h, w = bgr.shape[:2]
    if w < min_w or h < min_h:
        return False
    # Reject flat blank images
    if float(np.std(bgr)) < 10.0:
        return False
    # Reject chroma-key green screens
    b, g, r = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    chroma_ratio = float(np.mean((g > 195) & (r < 85) & (b < 85)))
    if chroma_ratio > 0.25:
        return False
    return True


def _generate_gemini_hero_image(
    topic: str,
    style_prompt: str,
    out_path: Path,
) -> Optional[Path]:
    """Generate a bespoke, moody, ultra-sharp photographic/cinematic 16:9 hero scene with ZERO text
    via the user's LIVE Gemini Image API (`gemini-2.5-flash-image`, fallback `gemini-3.1-flash-image`)
    using header `x-goog-api-key`.
    """
    global _GEMINI_IMAGE_QUOTA_EXHAUSTED
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    full_prompt = (
        f"Topic context: {str(topic).strip()}. "
        f"{str(style_prompt).strip()}. "
        "16:9 widescreen cinematic documentary film still, ultra-sharp 85mm cinema lens, dramatic chiaroscuro "
        "lighting, rich deep shadows, shallow depth of field, movie poster photography. "
        "STRICT REQUIREMENT: ZERO text, ZERO letters, ZERO words, ZERO numbers, ZERO typography, "
        "ZERO watermarks, ZERO logos anywhere in the image."
    )

    cache_key = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()[:20]
    cache_file = THUMB_HERO_CACHE_DIR / f"gemini_hero_{cache_key}.jpg"
    if cache_file.exists() and cache_file.stat().st_size > 12_000:
        bgr_c = cv2.imread(str(cache_file), cv2.IMREAD_COLOR)
        if _validate_decoded_bgr(bgr_c):
            shutil.copy2(cache_file, out_path)
            print(f"[ThumbStudio] Bespoke Gemini hero cache hit: {cache_file.name}", flush=True)
            return out_path

    if _GEMINI_IMAGE_QUOTA_EXHAUSTED:
        return None

    try:
        api_key = str(get_settings().get("gemini_api_key") or "").strip()
    except Exception:
        api_key = ""
    if not api_key:
        return None

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    quota_hits = 0
    with httpx.Client(timeout=40.0) as client:
        for model in GEMINI_IMAGE_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            # Try with explicit 16:9 imageConfig first, then clean responseModalities-only payload if 400
            payload_variants = [
                {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": "16:9"},
                    },
                },
                {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                    },
                },
            ]
            for p_idx, payload in enumerate(payload_variants):
                try:
                    resp = client.post(url, headers=headers, json=payload)
                except Exception as exc:
                    print(f"[ThumbStudio] Gemini image request error ({model}): {exc}", flush=True)
                    break

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        candidates = data.get("candidates") or []
                        for cand in candidates:
                            parts = (cand.get("content") or {}).get("parts") or []
                            for part in parts:
                                inline = part.get("inlineData") or part.get("inline_data")
                                if not inline or not inline.get("data"):
                                    continue
                                raw_bytes = base64.b64decode(inline["data"])
                                arr = np.frombuffer(raw_bytes, dtype=np.uint8)
                                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                                if _validate_decoded_bgr(bgr):
                                    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                                    if ok:
                                        cache_file.write_bytes(enc.tobytes())
                                        out_path.write_bytes(enc.tobytes())
                                        print(
                                            f"[ThumbStudio] Bespoke Gemini hero generated ({model}): "
                                            f"{bgr.shape[1]}x{bgr.shape[0]} -> {out_path.name}",
                                            flush=True,
                                        )
                                        return out_path
                    except Exception as exc:
                        print(f"[ThumbStudio] Gemini image decode error ({model}): {exc}", flush=True)
                    break

                if resp.status_code == 400 and p_idx == 0:
                    # Retry without imageConfig on older endpoint variants
                    continue

                if resp.status_code == 429:
                    quota_hits += 1
                    txt = resp.text or ""
                    print(f"[ThumbStudio] Gemini image {model} rate-limited (429), falling back cleanly.", flush=True)
                    if "limit: 0" in txt or quota_hits >= len(GEMINI_IMAGE_MODELS):
                        _GEMINI_IMAGE_QUOTA_EXHAUSTED = True
                    break

                print(f"[ThumbStudio] Gemini image {model} HTTP {resp.status_code}, trying fallback.", flush=True)
                break

    return None


# ---------------------------------------------------------------------------
# Video Frame Fallback & Hero Candidate Scoring
# ---------------------------------------------------------------------------
def _score_cinema_drama_bgr(bgr: np.ndarray) -> float:
    """Score how visually sharp, dramatic, and thumbnail-worthy an image is."""
    if not _validate_decoded_bgr(bgr, min_w=320, min_h=200):
        return -1.0
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (320, 180), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    sharpness = min(500.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()))
    contrast = float(np.std(gray))
    mean_luma = float(np.mean(gray))
    # Dark cinema prefers moody-to-balanced exposure (penalize harsh bright daytime glare)
    exposure_bonus = 1.0 - min(1.0, abs(mean_luma - 72.0) / 135.0)
    overexposed_frac = float(np.mean(gray > 225))
    glare_penalty = 0.72 if overexposed_frac > 0.08 else 1.0
    # Penalize pure-white flat stock backgrounds (corners all > 235)
    corners = np.concatenate([gray[:14, :14].ravel(), gray[:14, -14:].ravel(), gray[-14:, :14].ravel(), gray[-14:, -14:].ravel()])
    white_bg_penalty = 0.45 if float(np.mean(corners > 232)) > 0.65 else 1.0
    res_bonus = min(1.3, math.sqrt((w * h) / (1280.0 * 720.0)))
    return (sharpness * 0.22 + contrast * 1.45 + exposure_bonus * 40.0) * glare_penalty * white_bg_penalty * res_bonus


def _pick_best_video_frames(video_path: Path, work_dir: Path) -> List[Path]:
    """Sample sharp, clean frames from video_path (or direct image input), avoiding burned-in captions."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if video_path.exists() and video_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return [video_path]

    if not video_path.exists():
        return []

    dur_s = 12.0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video_path)],
            text=True,
            timeout=10,
        ).strip()
        dur_s = max(1.0, float(out))
    except Exception:
        pass

    scored: List[Tuple[float, Path]] = []
    for idx, frac in enumerate((0.12, 0.24, 0.38, 0.52, 0.66, 0.78, 0.88), start=1):
        ts = max(0.15, min(max(0.25, dur_s - 0.25), dur_s * frac))
        fp = work_dir / f"_thumb_vframe_{idx}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(fp)],
            check=False,
        )
        if fp.exists() and fp.stat().st_size > 1000:
            bgr = cv2.imread(str(fp), cv2.IMREAD_COLOR)
            if _validate_decoded_bgr(bgr, min_w=320, min_h=200):
                # Crop out bottom 18% if it looks like a rendered video with captions, saving clean crop
                h, w = bgr.shape[:2]
                clean_bgr = bgr[: int(h * 0.82), :]
                cv2.imwrite(str(fp), clean_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
                scored.append((_score_cinema_drama_bgr(clean_bgr), fp))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [p for _, p in scored[:3]]


def _acquire_hero_assets(
    title: str,
    video_path: Path,
    work_dir: Path,
    art_dir: Dict[str, Any],
) -> Tuple[List[Tuple[Path, np.ndarray, str]], str]:
    """Acquire up to 3 high-resolution cinematic hero images using the required priority chain:
      1. Bespoke Gemini Image API (`gemini-2.5-flash-image` -> `gemini-3.1-flash-image`)
      2. Pixabay / Wikimedia HD editorial photos via `engine.doc_media_engine.fetch_doc_real_photo`
      3. Best crisp video frames from `video_path`
    """
    assets: List[Tuple[Path, np.ndarray, str]] = []
    sources_used: List[str] = []

    # 1. Try LIVE Gemini Image API for bespoke zero-text hero artwork
    gemini_prompts = art_dir.get("gemini_prompts") or []
    for idx, g_prompt in enumerate(gemini_prompts[:3], start=1):
        out_p = work_dir / f"_gemini_hero_{idx}.jpg"
        got = _generate_gemini_hero_image(title, g_prompt, out_p)
        if got is not None and got.exists():
            bgr = cv2.imread(str(got), cv2.IMREAD_COLOR)
            if _validate_decoded_bgr(bgr):
                assets.append((got, bgr, "gemini_image"))
                if "gemini_image" not in sources_used:
                    sources_used.append("gemini_image")
        else:
            # If the first Gemini call failed/429'd, immediately drop to Fallback (a)
            if idx == 1:
                break

    # 2. Fallback (a): High-Resolution Editorial Photography via engine.doc_media_engine.fetch_doc_real_photo
    if len(assets) < 3:
        try:
            from engine.doc_media_engine import fetch_doc_real_photo

            used_urls: Set[str] = set()
            queries = list(art_dir.get("photo_queries") or [])
            for q_idx, query in enumerate(queries, start=1):
                if len(assets) >= 3:
                    break
                p = fetch_doc_real_photo(
                    query=query,
                    work_dir=work_dir,
                    tag=f"thumb_hero_{q_idx}",
                    min_width=900,
                    used_urls=used_urls,
                )
                if p is not None and Path(p).exists():
                    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
                    if _validate_decoded_bgr(bgr, min_w=600, min_h=340):
                        # Avoid duplicate identical image bytes
                        h_sig = hashlib.md5(cv2.resize(bgr, (32, 18)).tobytes()).hexdigest()
                        if not any(
                            hashlib.md5(cv2.resize(existing_bgr, (32, 18)).tobytes()).hexdigest() == h_sig
                            for _, existing_bgr, _ in assets
                        ):
                            assets.append((Path(p), bgr, f"editorial_photo:{query}"))
                            if "doc_media_photo" not in sources_used:
                                sources_used.append("doc_media_photo")
        except Exception as exc:
            print(f"[ThumbStudio] Editorial photo fallback notice: {exc}", flush=True)

    # 3. Fallback (b): Sharpest clean video frame from video_path
    if len(assets) < 1:
        v_frames = _pick_best_video_frames(video_path, work_dir)
        for vf in v_frames:
            bgr = cv2.imread(str(vf), cv2.IMREAD_COLOR)
            if _validate_decoded_bgr(bgr, min_w=320, min_h=200):
                assets.append((vf, bgr, "video_frame"))
                if "video_frame" not in sources_used:
                    sources_used.append("video_frame")

    # Emergency obsidian cinematic atmospheric fallback (never crashes even on missing video + offline)
    if not assets:
        fb_path = work_dir / "_thumb_emergency_bg.jpg"
        yy, xx = np.mgrid[0:720, 0:1280].astype(np.float32)
        dist = np.sqrt(((xx - 920.0) / 560.0) ** 2 + ((yy - 340.0) / 420.0) ** 2)
        glow = np.clip(1.0 - dist, 0.0, 1.0) ** 2.0
        fb = np.zeros((720, 1280, 3), dtype=np.uint8)
        fb[:, :, 0] = np.clip(14 + glow * 32, 0, 255).astype(np.uint8)
        fb[:, :, 1] = np.clip(10 + glow * 28, 0, 255).astype(np.uint8)
        fb[:, :, 2] = np.clip(16 + glow * 92, 0, 255).astype(np.uint8)
        cv2.imwrite(str(fb_path), fb, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
        assets.append((fb_path, fb, "synthetic_obsidian"))
        sources_used.append("synthetic_obsidian")

    return assets, "+".join(sources_used)


# ---------------------------------------------------------------------------
# Cinema Color Grading, Saliency Framing & Film Grain
# ---------------------------------------------------------------------------
def _cinema_grade_bgr(
    bgr: np.ndarray,
    style: str = "mystery",
    mood: str = "dark_horror",
) -> np.ndarray:
    """Apply Hollywood cinema color grading: chiaroscuro S-curve, split shadows/highlights,
    and micro-contrast sharpening so raw stock looks like a Netflix key-art still.
    """
    img = bgr.astype(np.float32) / 255.0

    # 1. Chiaroscuro S-curve contrast
    if style == "closeup":
        contrast, gamma, sat = 1.24, 1.08, 0.88
    elif style == "split_subject":
        contrast, gamma, sat = 1.18, 0.98, 0.94
    else:
        contrast, gamma, sat = 1.20, 1.06, 0.90

    img = np.power(np.clip(img, 1e-4, 1.0), gamma)
    # Smooth S-curve anchored at 0.44 midtone
    img = 0.44 + (img - 0.44) * contrast
    img = np.clip(img, 0.0, 1.0)
    # Deep cinema obsidian floor (lifted slightly from dead-clipped 0 to 0.025)
    img = 0.022 + img * 0.968

    # 2. Controlled cinema saturation (prevents cheap oversaturated stock look)
    luma = (0.114 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.299 * img[:, :, 2])[:, :, np.newaxis]
    img = np.clip(luma + (img - luma) * sat, 0.0, 1.0)

    # 3. Mood-aware split toning (cool obsidian/teal shadows + warm amber/crimson highlights)
    shadow_w = np.clip(1.0 - luma * 1.9, 0.0, 1.0)
    high_w = np.clip((luma - 0.42) * 1.7, 0.0, 1.0)

    if mood in ("dark_horror", "mystery_crime"):
        # Cool slate-obsidian shadows, subtle crimson/amber warm highlights
        img[:, :, 0] += shadow_w[:, :, 0] * 0.032 - high_w[:, :, 0] * 0.038  # B
        img[:, :, 1] += shadow_w[:, :, 0] * 0.010 - high_w[:, :, 0] * 0.010  # G
        img[:, :, 2] -= shadow_w[:, :, 0] * 0.012 - high_w[:, :, 0] * 0.048  # R
    else:
        # Classic teal-and-amber blockbuster split tone
        img[:, :, 0] += shadow_w[:, :, 0] * 0.042 - high_w[:, :, 0] * 0.044  # B
        img[:, :, 1] += shadow_w[:, :, 0] * 0.020 + high_w[:, :, 0] * 0.010  # G
        img[:, :, 2] -= shadow_w[:, :, 0] * 0.016 - high_w[:, :, 0] * 0.046  # R

    out_u8 = np.clip(img * 255.0, 0, 255).astype(np.uint8)

    # 4. Crisp 85mm cinema micro-contrast sharpening (unsharp mask)
    blur = cv2.GaussianBlur(out_u8, (0, 0), sigmaX=1.8)
    sharp_amt = 0.50 if style == "closeup" else 0.38
    sharpened = cv2.addWeighted(out_u8, 1.0 + sharp_amt, blur, -sharp_amt, 0)
    return sharpened


def _relight_cutout_bgra(
    bgra: np.ndarray,
    mood: str = "dark_horror",
) -> np.ndarray:
    """Subtly grade and relight the isolated foreground subject so its left edge catches cold-teal
    studio fill and its right edge catches warm amber/crimson rim light.
    """
    out = bgra.copy()
    bgr_graded = _cinema_grade_bgr(out[:, :, :3], style="split_subject", mood=mood).astype(np.float32)
    h, w = bgr_graded.shape[:2]
    pal = MOOD_PALETTES.get(mood, MOOD_PALETTES["dark_horror"])

    # Horizontal directional light gradient across the subject's edges
    x_norm = np.linspace(0.0, 1.0, w, dtype=np.float32)[np.newaxis, :, np.newaxis]
    left_kiss = np.power(np.clip(1.0 - x_norm * 2.2, 0.0, 1.0), 1.8)
    right_kiss = np.power(np.clip((x_norm - 0.55) * 2.2, 0.0, 1.0), 1.7)

    cold_bgr = np.array([pal["b_rim_cold_rgb"][2], pal["b_rim_cold_rgb"][1], pal["b_rim_cold_rgb"][0]], dtype=np.float32)
    warm_bgr = np.array([pal["b_rim_warm_rgb"][2], pal["b_rim_warm_rgb"][1], pal["b_rim_warm_rgb"][0]], dtype=np.float32)

    # Subtle edge tint (screen-like gentle addition weighted by luminance)
    bgr_graded = bgr_graded + left_kiss * cold_bgr * 0.14 + right_kiss * warm_bgr * 0.16
    out[:, :, :3] = np.clip(bgr_graded, 0, 255).astype(np.uint8)
    return out


def _detect_focal_point(bgr: np.ndarray, mask: Optional[np.ndarray] = None) -> Tuple[float, float]:
    """Return normalized (fx, fy) focal point of the main subject (weighted slightly toward upper-third
    where faces/eyes sit on portraits, falling back to OpenCV edge-saliency centroid).
    """
    h, w = bgr.shape[:2]
    if mask is None:
        mask = _predict_u2netp_mask(bgr)
    if mask is not None:
        strong = np.clip(mask - 0.35, 0.0, 1.0)
        total = float(np.sum(strong))
        if total > (h * w * 0.015):
            yy, xx = np.mgrid[0:h, 0:w]
            cx = float(np.sum(xx * strong) / total) / max(1.0, float(w))
            cy = float(np.sum(yy * strong) / total) / max(1.0, float(h))
            # Bias slightly upward toward eyes/head of portraits inside the foreground bbox
            ys = np.where(strong > 0.2)[0]
            if len(ys) > 20:
                y_top = float(np.min(ys)) / max(1.0, float(h))
                y_bot = float(np.max(ys)) / max(1.0, float(h))
                eye_y = y_top + (y_bot - y_top) * 0.36
                cy = cy * 0.45 + eye_y * 0.55
            return (max(0.15, min(0.85, cx)), max(0.18, min(0.75, cy)))

    # Edge-energy saliency fallback
    small = cv2.resize(bgr, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    s = float(np.sum(mag))
    if s > 1e-3:
        yy, xx = np.mgrid[0:90, 0:160]
        return (
            max(0.20, min(0.80, float(np.sum(xx * mag) / s) / 160.0)),
            max(0.22, min(0.72, float(np.sum(yy * mag) / s) / 90.0)),
        )
    return (0.55, 0.44)


def _compose_focal_canvas_bgr(
    bgr: np.ndarray,
    target_w: int,
    target_h: int,
    src_focal: Tuple[float, float],
    dst_focal: Tuple[float, float],
    zoom: float = 1.08,
    allow_left_mist_extend: bool = True,
) -> np.ndarray:
    """Aspect-cover scale + zoom `bgr` and intelligently frame `src_focal` onto `dst_focal`
    with zero aspect distortion. If shifting the hero right exposes left space, smoothly mirror-blur
    and darken the far-left strip (which sits seamlessly beneath the left atmospheric mist scrim).
    """
    sh, sw = bgr.shape[:2]
    base_scale = max(target_w / max(1.0, float(sw)), target_h / max(1.0, float(sh)))
    scale = base_scale * max(1.0, float(zoom))
    rw = max(target_w, int(round(sw * scale)))
    rh = max(target_h, int(round(sh * scale)))
    resized = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_LANCZOS4)

    fx_px = src_focal[0] * rw
    fy_px = src_focal[1] * rh
    desired_left = int(round(fx_px - dst_focal[0] * target_w))
    desired_top = int(round(fy_px - dst_focal[1] * target_h))

    # Clamp vertically inside valid bounds
    top = max(0, min(rh - target_h, desired_top))

    if desired_left >= 0 and desired_left + target_w <= rw:
        return resized[top : top + target_h, desired_left : desired_left + target_w].copy()

    if not allow_left_mist_extend:
        left = max(0, min(rw - target_w, desired_left))
        return resized[top : top + target_h, left : left + target_w].copy()

    # If desired_left < 0, we want to push the image right so the hero sits in the right 65% spotlight!
    max_shift = int(target_w * 0.30)
    if desired_left < 0:
        pad_l = min(max_shift, -desired_left)
        # Create darkened mirror-blurred left atmospheric extension
        pad_src = resized[top : top + target_h, : min(rw, pad_l + 64)]
        mirrored = cv2.flip(pad_src, 1)
        if mirrored.shape[1] < pad_l:
            mirrored = cv2.resize(mirrored, (pad_l, target_h), interpolation=cv2.INTER_LINEAR)
        else:
            mirrored = mirrored[:, -pad_l:]
        mirrored = cv2.GaussianBlur(mirrored, (0, 0), sigmaX=18.0, sigmaY=18.0)
        mirrored = (mirrored.astype(np.float32) * 0.45).astype(np.uint8)

        right_take = target_w - pad_l
        main_crop = resized[top : top + target_h, :right_take]
        canvas = np.concatenate([mirrored, main_crop], axis=1)
        # Soft feather across the join seam (completely hidden beneath left mist gradient anyway)
        seam_w = min(44, pad_l, right_take)
        if seam_w > 8:
            seam_slice = canvas[:, pad_l - seam_w // 2 : pad_l + seam_w // 2].copy()
            canvas[:, pad_l - seam_w // 2 : pad_l + seam_w // 2] = cv2.GaussianBlur(seam_slice, (0, 0), sigmaX=7.0)
        return canvas

    left = max(0, min(rw - target_w, desired_left))
    return resized[top : top + target_h, left : left + target_w].copy()


def _bgr_to_skia_image(bgr: np.ndarray) -> skia.Image:
    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    return skia.Image.fromarray(
        np.ascontiguousarray(bgra),
        colorType=skia.ColorType.kBGRA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
        copy=True,
    )


def _bgra_to_skia_image(bgra: np.ndarray) -> skia.Image:
    return skia.Image.fromarray(
        np.ascontiguousarray(bgra),
        colorType=skia.ColorType.kBGRA_8888_ColorType,
        alphaType=skia.AlphaType.kUnpremul_AlphaType,
        copy=True,
    )


def _make_colored_silhouette_skia(bgra: np.ndarray, rgb: Tuple[int, int, int]) -> skia.Image:
    """Create a solid-colored silhouette image using the exact feathered alpha matte of `bgra`
    for physically-grounded studio rim-light halos behind hair/shoulders.
    """
    h, w = bgra.shape[:2]
    sil = np.zeros((h, w, 4), dtype=np.uint8)
    sil[:, :, 0] = rgb[2]  # B
    sil[:, :, 1] = rgb[1]  # G
    sil[:, :, 2] = rgb[0]  # R
    sil[:, :, 3] = bgra[:, :, 3]
    return _bgra_to_skia_image(sil)


def _draw_film_grain(canvas: skia.Canvas, w: int, h: int, alpha: int = 26, seed: int = 42) -> None:
    """Apply fine monochrome 35mm cinema film grain (eliminates banding & unifies photography + type)."""
    rng = np.random.default_rng(seed)
    # Generate at half-res then scale smoothly for authentic 35mm organic grain clump
    gh, gw = h // 2, w // 2
    noise = rng.normal(128.0, 34.0, size=(gh, gw)).astype(np.float32)
    noise_u8 = np.clip(noise, 0, 255).astype(np.uint8)
    grain_bgra = np.zeros((gh, gw, 4), dtype=np.uint8)
    grain_bgra[:, :, 0] = noise_u8
    grain_bgra[:, :, 1] = noise_u8
    grain_bgra[:, :, 2] = noise_u8
    grain_bgra[:, :, 3] = alpha
    grain_img = _bgra_to_skia_image(grain_bgra)
    p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kSoftLight)
    canvas.drawImageRect(grain_img, skia.Rect.MakeWH(w, h), skia.SamplingOptions(skia.FilterMode.kLinear), p)


# ---------------------------------------------------------------------------
# Cinema Atmospheric Lighting & Delicate Editorial Elements
# ---------------------------------------------------------------------------
def _draw_cinema_light_leak(
    canvas: skia.Canvas,
    w: float,
    h: float,
    primary_rgb: Tuple[int, int, int],
    warm_rgb: Tuple[int, int, int],
) -> None:
    """Subtle 35mm warm crimson/amber anamorphic edge light leak (never loud or neon)."""
    # Upper-right / far-right warm cinema bloom
    p1 = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    p1.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.96, h * 0.16),
            w * 0.44,
            [
                skia.ColorSetARGB(82, primary_rgb[0], primary_rgb[1], primary_rgb[2]),
                skia.ColorSetARGB(34, warm_rgb[0], warm_rgb[1], warm_rgb[2]),
                skia.ColorSetARGB(0, primary_rgb[0], primary_rgb[1], primary_rgb[2]),
            ],
            [0.0, 0.48, 1.0],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), p1)

    # Soft bottom-left ember kiss (adds depth behind lower text without reducing legibility)
    p2 = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    p2.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.08, h * 0.96),
            w * 0.34,
            [
                skia.ColorSetARGB(46, warm_rgb[0], warm_rgb[1], warm_rgb[2]),
                skia.ColorSetARGB(0, warm_rgb[0], warm_rgb[1], warm_rgb[2]),
            ],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), p2)


def _draw_cinema_bokeh_lights(
    canvas: skia.Canvas,
    w: float,
    h: float,
    warm_rgb: Tuple[int, int, int],
    cold_rgb: Tuple[int, int, int],
    seed: int = 108,
) -> None:
    """Shallow depth-of-field 85mm f/1.4 optical bokeh orbs (soft, defocused, translucent)."""
    rng = np.random.default_rng(seed)
    # Place gentle warm bokeh lights predominantly in mid-right & cold bokeh softly on left
    specs = [
        (0.56, 0.18, 42, warm_rgb, 44),
        (0.64, 0.10, 26, (255, 224, 148), 52),
        (0.92, 0.22, 54, warm_rgb, 40),
        (0.88, 0.78, 48, warm_rgb, 36),
        (0.52, 0.82, 34, (255, 209, 102), 38),
        (0.74, 0.14, 18, (255, 236, 179), 58),
        (0.46, 0.30, 22, cold_rgb, 34),
        (0.14, 0.16, 46, cold_rgb, 28),
        (0.38, 0.86, 56, cold_rgb, 24),
        (0.62, 0.64, 16, (255, 220, 140), 46),
        (0.95, 0.56, 30, (255, 160, 80), 42),
    ]
    for fx, fy, radius, rgb, alpha in specs:
        jx = float(rng.uniform(-0.015, 0.015))
        jy = float(rng.uniform(-0.015, 0.015))
        cx = (fx + jx) * w
        cy = (fy + jy) * h
        r = float(radius)
        paint = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
        paint.setShader(
            skia.GradientShader.MakeRadial(
                (cx, cy),
                r,
                [
                    skia.ColorSetARGB(int(alpha * 0.55), rgb[0], rgb[1], rgb[2]),
                    skia.ColorSetARGB(int(alpha * 0.90), rgb[0], rgb[1], rgb[2]),
                    skia.ColorSetARGB(0, rgb[0], rgb[1], rgb[2]),
                ],
                [0.0, 0.72, 1.0],
            )
        )
        paint.setImageFilter(skia.ImageFilters.Blur(3.5, 3.5))
        canvas.drawCircle(cx, cy, r, paint)


def _draw_subtle_spotlight_flare(
    canvas: skia.Canvas,
    fx: float,
    fy: float,
    flare_rgb: Tuple[int, int, int],
) -> None:
    """Delicate cinema spotlight glow + subtle horizontal anamorphic lens streak around focal point."""
    # Soft atmospheric spotlight bloom
    bloom = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    bloom.setShader(
        skia.GradientShader.MakeRadial(
            (fx, fy),
            280.0,
            [
                skia.ColorSetARGB(62, flare_rgb[0], flare_rgb[1], flare_rgb[2]),
                skia.ColorSetARGB(24, flare_rgb[0], flare_rgb[1], flare_rgb[2]),
                skia.ColorSetARGB(0, flare_rgb[0], flare_rgb[1], flare_rgb[2]),
            ],
            [0.0, 0.45, 1.0],
        )
    )
    canvas.drawCircle(fx, fy, 280.0, bloom)

    # Whisper-thin horizontal anamorphic cinema streak
    streak_w = 420.0
    streak_h = 8.0
    streak_rect = skia.Rect.MakeXYWH(fx - streak_w * 0.5, fy - streak_h * 0.5, streak_w, streak_h)
    streak_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    streak_p.setShader(
        skia.GradientShader.MakeLinear(
            [(fx - streak_w * 0.5, fy), (fx + streak_w * 0.5, fy)],
            [
                skia.ColorSetARGB(0, flare_rgb[0], flare_rgb[1], flare_rgb[2]),
                skia.ColorSetARGB(58, 255, 244, 214),
                skia.ColorSetARGB(0, flare_rgb[0], flare_rgb[1], flare_rgb[2]),
            ],
            [0.0, 0.5, 1.0],
        )
    )
    streak_p.setImageFilter(skia.ImageFilters.Blur(6.0, 2.5))
    canvas.drawRect(streak_rect, streak_p)


def _draw_editorial_viewfinder_marks(canvas: skia.Canvas, w: float, h: float) -> None:
    """Delicate 1.5px cinema-glass L-bracket corner marks (editorial documentary look, NEVER cartoonish)."""
    inset = 32.0
    arm = 30.0
    corners = [
        [(inset, inset + arm), (inset, inset), (inset + arm, inset)],
        [(w - inset - arm, inset), (w - inset, inset), (w - inset, inset + arm)],
        [(inset, h - inset - arm), (inset, h - inset), (inset + arm, h - inset)],
        [(w - inset - arm, h - inset), (w - inset, h - inset), (w - inset, h - inset - arm)],
    ]

    shadow_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=3.0,
        StrokeCap=skia.Paint.kSquare_Cap,
        Color=skia.ColorSetARGB(120, 0, 0, 0),
    )
    glass_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.5,
        StrokeCap=skia.Paint.kSquare_Cap,
        Color=skia.ColorSetARGB(128, 241, 245, 249),
    )
    for pts in corners:
        path = skia.Path()
        path.moveTo(pts[0][0], pts[0][1])
        path.lineTo(pts[1][0], pts[1][1])
        path.lineTo(pts[2][0], pts[2][1])
        canvas.drawPath(path, shadow_p)
        canvas.drawPath(path, glass_p)


def _draw_hairline_accent_bar(
    canvas: skia.Canvas,
    x: float,
    y: float,
    width: float,
    color_hex: str,
    thickness: float = 4.0,
) -> None:
    """Thin metallic gradient cinema hairline rule (pure Netflix / MagnatesMedia polish, zero boxes)."""
    base_col = hex_to_skia(color_hex, alpha=245)
    r = skia.ColorGetR(base_col)
    g = skia.ColorGetG(base_col)
    b = skia.ColorGetB(base_col)
    rect = skia.Rect.MakeXYWH(x, y, width, thickness)

    # Subtle shadow lift
    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(165, 0, 0, 0))
    sh_p.setImageFilter(skia.ImageFilters.Blur(4.0, 4.0))
    canvas.drawRoundRect(skia.Rect.MakeXYWH(x, y + 2.0, width, thickness), 2.0, 2.0, sh_p)

    # Metallic horizontal fade bar
    bar_p = skia.Paint(AntiAlias=True)
    bar_p.setShader(
        skia.GradientShader.MakeLinear(
            [(x, y), (x + width, y)],
            [
                skia.ColorSetARGB(255, min(255, r + 45), min(255, g + 45), min(255, b + 45)),
                skia.ColorSetARGB(235, r, g, b),
                skia.ColorSetARGB(0, r, g, b),
            ],
            [0.0, 0.58, 1.0],
        )
    )
    canvas.drawRoundRect(rect, 2.0, 2.0, bar_p)


# ---------------------------------------------------------------------------
# 2. Magazine / Movie-Poster Grade 3D Gradient Typography (ZERO Pills, ZERO Clipping!)
# ---------------------------------------------------------------------------
def _measure_glyph_box(font: skia.Font, text: str) -> Tuple[float, float, float, float]:
    """Return `(visual_width, left_shift, ascent_up, descent_down)` using exact Skia glyph bounds,
    explicitly accounting for Portuguese diacritics (Ã, Á, É, Ó, Ç) so ZERO edges ever clip.
    """
    bounds = skia.Rect()
    adv = float(font.measureText(text, skia.TextEncoding.kUTF8, bounds))
    left_shift = max(0.0, -float(bounds.fLeft))
    vis_w = max(adv, float(bounds.fRight) + left_shift)
    ascent_up = max(font.getSize() * 0.72, -float(bounds.fTop))
    descent_down = max(0.0, float(bounds.fBottom))
    return vis_w, left_shift, ascent_up, descent_down


def _draw_cinema_poster_headline(
    canvas: skia.Canvas,
    words: List[str],
    x_left: float,
    max_w: float,
    anton_tf: skia.Typeface,
    mont_tf: skia.Typeface,
    line_gradients: List[str],
    accent_bar_hex: Optional[str] = None,
    vertical_anchor: str = "center",  # "center" or "lower_left"
    bar_position: str = "top",        # "top" or "bottom"
    canvas_w: float = 1280.0,
    canvas_h: float = 720.0,
) -> Tuple[float, float, float]:
    """Render 1-3 massive movie-poster uppercase lines with:
      - Rich 3D vertical linear gradient fill (Brushed Gold / Blood Crimson / Ice White)
      - Subtle 3D dark extrusion (+4px, +6px stepped cleanly)
      - Multi-pass deep soft feathered drop shadow
      - Ultra-clean thin dark contour (StrokeWidth 4.0..5.5, NEVER cartoon 15px borders!)
      - Guaranteed strict safe-margin auto-fitting (ZERO clipping on any edge or diacritic!)
    Returns `(block_top_y, block_bottom_y, block_max_w)`.
    """
    lines = [str(w).strip() for w in words[:3] if str(w).strip()]
    if not lines:
        return (200.0, 400.0, 300.0)

    safe_margin_x = 64.0
    safe_margin_y = 68.0
    safe_x = max(safe_margin_x, float(x_left))
    avail_w = min(float(max_w), canvas_w - safe_x - safe_margin_x)
    avail_h = canvas_h - 2.0 * safe_margin_y - 34.0  # reserve breathing room for hairline bar

    n_lines = len(lines)
    # Theatrical movie-poster font sizing: 2-line headlines go HUGE; 3-line headlines balance cleanly
    if n_lines == 1:
        max_start_size = 176.0
        gap_ratio = 0.0
    elif n_lines == 2:
        max_start_size = 166.0
        gap_ratio = 0.14
    else:
        max_start_size = 142.0
        gap_ratio = 0.13

    def _fit_lines(scale_mult: float = 1.0) -> Tuple[List[Dict[str, Any]], float]:
        prepared: List[Dict[str, Any]] = []
        total_h = 0.0
        for idx, word in enumerate(lines):
            # Anton-Regular gives iconic tall condensed Netflix/movie-poster presence;
            # Montserrat-Black for numeric/short punchy lead-ins when pairing 3 lines adds editorial contrast
            use_mont = (n_lines == 3 and idx == 1 and any(c.isdigit() or c in "$%" for c in word))
            tf = mont_tf if use_mont else anton_tf

            # Give the accent/hero line slightly higher target ceiling for optical drama
            is_accent = line_gradients[idx % len(line_gradients)] != "ice_white"
            target_size = (max_start_size * (1.04 if is_accent and n_lines == 2 else 0.98)) * scale_mult
            size = max(40.0, target_size)
            font = skia.Font(tf, size)
            vis_w, left_shift, asc_up, desc_dn = _measure_glyph_box(font, word)
            # Leave +12px margin for subtle 3D extrusion (+5px) + thin stroke (+5px)
            while size > 36.0 and (vis_w + 14.0) > avail_w:
                size -= 2.0
                font = skia.Font(tf, size)
                vis_w, left_shift, asc_up, desc_dn = _measure_glyph_box(font, word)

            prepared.append({
                "idx": idx,
                "word": word,
                "font": font,
                "size": size,
                "vis_w": vis_w,
                "left_shift": left_shift,
                "ascent": asc_up,
                "descent": desc_dn,
                "grad_key": line_gradients[idx % len(line_gradients)],
            })

        # Keep optical harmony: prevent a short word (like "O" or "A") from dwarfing or looking awkward,
        # while capping huge size discrepancies across stacked lines (> 1.48x ratio looks messy)
        if len(prepared) >= 2:
            min_sz = min(item["size"] for item in prepared)
            cap_sz = min_sz * 1.42
            for item in prepared:
                if item["size"] > cap_sz:
                    item["size"] = cap_sz
                    item["font"] = skia.Font(item["font"].getTypeface(), cap_sz)
                    vis_w, left_shift, asc_up, desc_dn = _measure_glyph_box(item["font"], item["word"])
                    item["vis_w"], item["left_shift"], item["ascent"], item["descent"] = (
                        vis_w,
                        left_shift,
                        asc_up,
                        desc_dn,
                    )

        for i, item in enumerate(prepared):
            total_h += item["ascent"] + item["descent"]
            if i < len(prepared) - 1:
                total_h += max(12.0, min(26.0, item["size"] * gap_ratio))
        return prepared, total_h

    prepared, total_h = _fit_lines(1.0)
    # If total height exceeds safe vertical budget, shrink uniformly cleanly
    if total_h > avail_h and total_h > 1.0:
        prepared, total_h = _fit_lines(avail_h / total_h * 0.96)

    if vertical_anchor == "lower_left":
        # Anchor cleanly in lower-left / mid-left editorial poster zone
        desired_bottom = canvas_h - 86.0
        start_top = max(safe_margin_y + 18.0, desired_bottom - total_h)
    else:
        # Optical vertical center slightly above true geometric center (48%)
        start_top = max(
            safe_margin_y + 18.0,
            min(canvas_h - safe_margin_y - total_h - 14.0, (canvas_h - total_h) * 0.48),
        )

    block_top = start_top
    block_max_w = max(item["vis_w"] for item in prepared)

    # Optional thin metallic hairline accent bar ABOVE the title lockup
    if accent_bar_hex and bar_position == "top":
        bar_w = max(108.0, min(176.0, block_max_w * 0.36))
        _draw_hairline_accent_bar(canvas, safe_x, max(44.0, block_top - 24.0), bar_w, accent_bar_hex, thickness=4.0)

    cursor_y = start_top
    for i, item in enumerate(prepared):
        word = item["word"]
        font = item["font"]
        size = item["size"]
        asc = item["ascent"]
        desc = item["descent"]
        draw_x = safe_x + item["left_shift"]
        baseline_y = cursor_y + asc

        grad_spec = TYPO_GRADIENTS.get(item["grad_key"], TYPO_GRADIENTS["ice_white"])

        # Pass 1: Deep ambient soft feathered cinema drop shadow
        ambient_shadow = skia.Paint(AntiAlias=True, Color=skia.ColorBLACK)
        ambient_shadow.setImageFilter(
            skia.ImageFilters.DropShadowOnly(0.0, 14.0, 26.0, 26.0, skia.ColorSetARGB(235, 0, 0, 0))
        )
        canvas.drawString(word, draw_x, baseline_y, font, ambient_shadow)

        # Pass 2: Tighter crisp lift shadow directly beneath letters
        tight_shadow = skia.Paint(AntiAlias=True, Color=skia.ColorBLACK)
        tight_shadow.setImageFilter(
            skia.ImageFilters.DropShadowOnly(0.0, 6.0, 11.0, 11.0, skia.ColorSetARGB(210, 0, 0, 0))
        )
        canvas.drawString(word, draw_x, baseline_y, font, tight_shadow)

        # Pass 3: Subtle cinema colored luminescence ONLY for hero accent words (Crimson / Gold)
        if grad_spec.get("glow"):
            glow_col = hex_to_skia(grad_spec["glow"], alpha=78)
            glow_p = skia.Paint(AntiAlias=True, Color=glow_col, BlendMode=skia.BlendMode.kScreen)
            glow_p.setImageFilter(skia.ImageFilters.Blur(18.0, 18.0))
            canvas.drawString(word, draw_x, baseline_y, font, glow_p)

        # Pass 4: Subtle 3D dark metallic extrusion (+4px, +6px stepped smoothly for cinema thickness)
        ext_col = hex_to_skia(grad_spec["extrude"], alpha=235)
        ext_paint = skia.Paint(AntiAlias=True, Color=ext_col)
        for dx, dy in ((1.5, 2.0), (3.0, 4.0), (4.5, 6.0)):
            canvas.drawString(word, draw_x + dx, baseline_y + dy, font, ext_paint)

        # Pass 5: Ultra-clean thin dark contour (4.0..5.5px — NEVER chunky cartoon 15px border!)
        stroke_w = max(4.0, min(5.5, size * 0.036))
        contour_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=stroke_w,
            StrokeJoin=skia.Paint.kRound_Join,
            Color=skia.ColorSetARGB(225, 7, 6, 11),
        )
        canvas.drawString(word, draw_x, baseline_y, font, contour_p)

        # Pass 6: Rich 3D vertical linear gradient fill across the exact glyph height
        grad_top = baseline_y - asc
        grad_bot = baseline_y + max(2.0, desc * 0.4)
        fill_p = skia.Paint(AntiAlias=True)
        fill_p.setShader(
            skia.GradientShader.MakeLinear(
                [(draw_x, grad_top), (draw_x, grad_bot)],
                [hex_to_skia(c) for c in grad_spec["stops"]],
                grad_spec["positions"],
            )
        )
        canvas.drawString(word, draw_x, baseline_y, font, fill_p)

        # Advance cleanly to next stacked line
        line_gap = max(12.0, min(26.0, size * gap_ratio)) if i < len(prepared) - 1 else 0.0
        cursor_y = baseline_y + desc + line_gap

    block_bottom = cursor_y

    # Optional thin metallic hairline accent bar BELOW the title lockup
    if accent_bar_hex and bar_position == "bottom":
        bar_w = max(116.0, min(190.0, block_max_w * 0.42))
        _draw_hairline_accent_bar(
            canvas,
            safe_x,
            min(canvas_h - 46.0, block_bottom + 18.0),
            bar_w,
            accent_bar_hex,
            thickness=4.0,
        )

    return (block_top, block_bottom, block_max_w)


def _save_surface_jpeg(surface: skia.Surface, out_path: Path, quality: int = 94) -> None:
    snap = surface.makeImageSnapshot()
    encoded = snap.encodeToData(skia.kJPEG, int(quality))
    if encoded is not None:
        out_path.write_bytes(bytes(encoded))
    else:
        snap.save(str(out_path), skia.kJPEG)


# ---------------------------------------------------------------------------
# Role Selector Across Acquired Hero Candidates
# ---------------------------------------------------------------------------
def _select_hero_roles(
    assets: List[Tuple[Path, np.ndarray, str]],
    work_dir: Path,
) -> Dict[str, Any]:
    """Evaluate all acquired hero candidates with u2netp + drama scoring and pick the strongest
    visual for each of the 3 A/B/C variants so every cover looks bespoke and cohesive.
    """
    analyzed: List[Dict[str, Any]] = []
    for idx, (path, bgr, src) in enumerate(assets):
        mask = _predict_u2netp_mask(bgr)
        drama_score = _score_cinema_drama_bgr(bgr)
        focal = _detect_focal_point(bgr, mask=mask)

        # Evaluate cutout suitability (clean prominent foreground silhouette covering 10%..74% of frame)
        cutout_bgra, cov, cut_meta = _cutout_subject_u2netp(
            bgr,
            out_cutout_png=work_dir / f"_thumb_cutout_cand_{idx}.png",
        )
        cutout_score = -1.0
        if cutout_bgra is not None and 0.08 <= cov <= 0.78:
            # Ideal foreground coverage sits around 0.30..0.55
            cov_fit = 1.0 - min(1.0, abs(cov - 0.40) / 0.42)
            # Prefer portraits/figures not heavily chopped on all 4 sides
            edge_touches = sum(
                1 for k in ("touches_left", "touches_right", "touches_top", "touches_bottom") if cut_meta.get(k)
            )
            edge_bonus = 1.0 if edge_touches <= 2 else (0.78 if edge_touches == 3 else 0.55)
            cutout_score = drama_score * (0.65 + 0.55 * cov_fit) * edge_bonus

        analyzed.append({
            "idx": idx,
            "path": path,
            "bgr": bgr,
            "src": src,
            "drama_score": drama_score,
            "focal": focal,
            "cutout_bgra": cutout_bgra,
            "cutout_meta": cut_meta,
            "cutout_cov": cov,
            "cutout_score": cutout_score,
        })

    # Variant A (Dark Cinema / Editorial Mystery): strongly prefer idx=0 (our primary art-directed iconic
    # portrait/hero subject for the topic) whenever it meets cinema quality, avoiding random side-props.
    best_a = max(
        analyzed,
        key=lambda x: x["drama_score"] + (95.0 if x["idx"] == 0 and x["drama_score"] >= 45.0 else 0.0),
    )

    # Variant B Cutout Subject: cleanest prominent u2netp foreground silhouette, strongly preferring
    # the primary iconic figure/portrait (idx=0) over secondary inanimate objects when it cuts cleanly.
    cutout_candidates = [x for x in analyzed if x["cutout_bgra"] is not None]
    if cutout_candidates:
        best_b_subj = max(
            cutout_candidates,
            key=lambda x: x["cutout_score"] + (85.0 if x["idx"] == 0 and x["cutout_score"] > 0 else 0.0),
        )
    else:
        best_b_subj = best_a

    # Variant B Atmospheric Defocused Backdrop: prefer a distinct environment scene if available
    distinct_for_b_bg = [x for x in analyzed if x["idx"] != best_b_subj["idx"]]
    best_b_bg = max(distinct_for_b_bg, key=lambda x: x["drama_score"]) if distinct_for_b_bg else best_a

    # Variant C (Intense 1.32x Close-Up Chiaroscuro): prefer a distinct dramatic scene if available and sharp,
    # otherwise use best_a zoomed dramatically into its focal eyes/detail!
    distinct_for_c = [x for x in analyzed if x["idx"] != best_a["idx"] and x["drama_score"] >= best_a["drama_score"] * 0.65]
    if distinct_for_c:
        # Prefer the atmospheric setting or 3rd distinct shot for genuine A/B/C visual diversity
        unused_c = [x for x in distinct_for_c if x["idx"] != best_b_bg["idx"]]
        best_c = max(unused_c or distinct_for_c, key=lambda x: x["drama_score"])
    else:
        best_c = best_a

    return {
        "a": best_a,
        "b_subject": best_b_subj,
        "b_bg": best_b_bg,
        "c": best_c,
    }


def _build_line_gradient_sequence(n_lines: int, accent_grad: str, lead_accent: bool = False) -> List[str]:
    """Build luxury movie-poster gradient assignment across 1-3 stacked lines.
    Rule of luxury editorial typography: highlight ONE electric accent line so the eye locks instantly.
    """
    if n_lines <= 1:
        return [accent_grad]
    if n_lines == 2:
        return [accent_grad, "ice_white"] if lead_accent else ["ice_white", accent_grad]
    # 3 lines: highlight the punchy center focal hook (or top/bottom) against crisp Ice Platinum White
    return ["ice_white", accent_grad, "ice_white"] if not lead_accent else [accent_grad, "ice_white", "ice_white"]


# ---------------------------------------------------------------------------
# Main Public Entry Point
# ---------------------------------------------------------------------------
def generate_ab_thumbnails_16x9(
    video_path: Union[str, Path],
    title: str,
    output_dir: Union[str, Path],
    custom_3words: Optional[str] = None,
) -> Dict[str, str]:
    """Generate 3 genuine 10M-view Netflix / MagnatesMedia / Dark History 1280x720 thumbnails:
      - thumb_A_mystery.jpg  (Dark Cinema / Editorial Mystery)
      - thumb_B_contrast.jpg (High-Drama Split Lighting / Subject Rim Glow)
      - thumb_C_zoom.jpg     (Intense Close-Up Chiaroscuro + Editorial Vignette)

    Accepts `custom_3words` to render pre-seeded or user-defined hooks verbatim with zero edge clipping.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    W, H = 1280, 720
    anton_tf, _ = _load_verified_typeface("Anton-Regular.ttf", role="thumb_anton")
    mont_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="thumb_montserrat")

    # Universal topic art direction (mood + Gemini hero prompts + Pixabay queries + smart auto-headline)
    art_dir = _plan_thumbnail_art_direction(title, custom_3words=custom_3words)
    mood = str(art_dir.get("mood") or "dark_horror")
    pal = MOOD_PALETTES.get(mood, MOOD_PALETTES["dark_horror"])

    words = _extract_three_impact_words(
        title,
        custom_3words=custom_3words,
        llm_headline_words=art_dir.get("auto_headline"),
    )

    assets, hero_source_summary = _acquire_hero_assets(title, video_path, work_dir, art_dir)
    roles = _select_hero_roles(assets, work_dir)
    seed_base = int(hashlib.md5(f"{title}|{words}".encode("utf-8")).hexdigest()[:8], 16)

    # =========================================================================
    # THUMB A: DARK CINEMA / EDITORIAL MYSTERY (thumb_A_mystery.jpg)
    # =========================================================================
    surf_a = skia.Surface(W, H)
    ca = surf_a.getCanvas()
    ca.clear(hex_to_skia("#07060B"))

    hero_a = roles["a"]
    graded_a = _cinema_grade_bgr(hero_a["bgr"], style="mystery", mood=mood)
    composed_a = _compose_focal_canvas_bgr(
        graded_a,
        target_w=W,
        target_h=H,
        src_focal=hero_a["focal"],
        dst_focal=(0.68, 0.45),
        zoom=1.08,
        allow_left_mist_extend=True,
    )
    img_a = _bgr_to_skia_image(composed_a)
    ca.drawImageRect(img_a, skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kLinear))

    # Sweeping atmospheric dark mist from left (alpha 245 -> 160 -> 0) leaving right 65% hero luminous
    left_mist = skia.Paint(AntiAlias=True)
    left_mist.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, 0.0), (W * 0.72, 0.0)],
            [
                skia.ColorSetARGB(248, 7, 6, 11),
                skia.ColorSetARGB(232, 9, 7, 14),
                skia.ColorSetARGB(162, 10, 8, 15),
                skia.ColorSetARGB(48, 10, 8, 15),
                skia.ColorSetARGB(0, 7, 6, 11),
            ],
            [0.0, 0.28, 0.52, 0.78, 1.0],
        )
    )
    ca.drawRect(skia.Rect.MakeWH(W, H), left_mist)

    # Subtle vertical cinema vignette (top & bottom frame grounding)
    vert_vig_a = skia.Paint(AntiAlias=True)
    vert_vig_a.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, 0.0), (0.0, H)],
            [
                skia.ColorSetARGB(128, 5, 5, 9),
                skia.ColorSetARGB(0, 5, 5, 9),
                skia.ColorSetARGB(0, 5, 5, 9),
                skia.ColorSetARGB(156, 5, 5, 9),
            ],
            [0.0, 0.20, 0.78, 1.0],
        )
    )
    ca.drawRect(skia.Rect.MakeWH(W, H), vert_vig_a)

    # Subtle red/amber cinema light leak
    _draw_cinema_light_leak(ca, W, H, pal["a_leak_rgb"], pal["a_leak_warm_rgb"])

    # Clean massive stacked 2-3 word movie-poster typography on left + thin hairline accent bar
    grads_a = _build_line_gradient_sequence(len(words), pal["a_accent_grad"], lead_accent=False)
    _draw_cinema_poster_headline(
        ca,
        words=words,
        x_left=68.0,
        max_w=W * 0.48,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        line_gradients=grads_a,
        accent_bar_hex=pal["a_bar_hex"],
        vertical_anchor="center",
        bar_position="top",
        canvas_w=W,
        canvas_h=H,
    )
    _draw_film_grain(ca, W, H, alpha=26, seed=seed_base + 1)

    thumb_a_path = output_dir / "thumb_A_mystery.jpg"
    _save_surface_jpeg(surf_a, thumb_a_path, quality=94)

    # =========================================================================
    # THUMB B: HIGH-DRAMA SPLIT LIGHTING / SUBJECT RIM GLOW (thumb_B_contrast.jpg)
    # =========================================================================
    surf_b = skia.Surface(W, H)
    cb = surf_b.getCanvas()
    cb.clear(hex_to_skia("#061017"))

    # 1. Deeply blurred atmospheric photographic texture layer for rich studio backdrop depth
    bg_b_src = roles["b_bg"]
    bg_b_graded = _cinema_grade_bgr(bg_b_src["bgr"], style="mystery", mood=mood)
    bg_b_cover = _compose_focal_canvas_bgr(
        bg_b_graded,
        target_w=W,
        target_h=H,
        src_focal=(0.5, 0.5),
        dst_focal=(0.5, 0.5),
        zoom=1.10,
        allow_left_mist_extend=False,
    )
    bg_b_blur = cv2.GaussianBlur(bg_b_cover, (0, 0), sigmaX=20.0, sigmaY=20.0)
    bg_b_dark = (bg_b_blur.astype(np.float32) * 0.42).astype(np.uint8)
    cb.drawImageRect(_bgr_to_skia_image(bg_b_dark), skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kLinear))

    # 2. Cold-teal (left) vs. Warm-amber/crimson (right) split studio atmospheric lighting
    cold_r, cold_g, cold_b = pal["b_cold_rgb"]
    warm_r, warm_g, warm_b = pal["b_warm_rgb"]
    split_base = skia.Paint(AntiAlias=True)
    split_base.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, H * 0.15), (W, H * 0.85)],
            [
                skia.ColorSetARGB(215, cold_r, cold_g, cold_b),
                skia.ColorSetARGB(195, 7, 13, 20),
                skia.ColorSetARGB(198, warm_r, warm_g, warm_b),
            ],
            [0.0, 0.48, 1.0],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), split_base)

    # Volumetric studio radial washes (cool cyan-teal mist left + fiery crimson/amber backlight right)
    cool_wash = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    cool_wash.setShader(
        skia.GradientShader.MakeRadial(
            (W * 0.16, H * 0.34),
            W * 0.48,
            [
                skia.ColorSetARGB(95, pal["b_rim_cold_rgb"][0], pal["b_rim_cold_rgb"][1], pal["b_rim_cold_rgb"][2]),
                skia.ColorSetARGB(0, pal["b_rim_cold_rgb"][0], pal["b_rim_cold_rgb"][1], pal["b_rim_cold_rgb"][2]),
            ],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), cool_wash)

    warm_wash = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    warm_wash.setShader(
        skia.GradientShader.MakeRadial(
            (W * 0.78, H * 0.48),
            W * 0.46,
            [
                skia.ColorSetARGB(135, pal["b_rim_outer_rgb"][0], pal["b_rim_outer_rgb"][1], pal["b_rim_outer_rgb"][2]),
                skia.ColorSetARGB(65, pal["b_rim_warm_rgb"][0], pal["b_rim_warm_rgb"][1], pal["b_rim_warm_rgb"][2]),
                skia.ColorSetARGB(0, pal["b_rim_outer_rgb"][0], pal["b_rim_outer_rgb"][1], pal["b_rim_outer_rgb"][2]),
            ],
            [0.0, 0.48, 1.0],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), warm_wash)

    # 3. Shallow depth-of-field bokeh lights behind the subject
    _draw_cinema_bokeh_lights(cb, W, H, pal["b_rim_warm_rgb"], pal["b_rim_cold_rgb"], seed=seed_base + 2)

    # 4. u2netp isolated foreground hero subject with soft feathered rim-light halo
    subj_info = roles["b_subject"]
    cutout_bgra = subj_info["cutout_bgra"]
    cut_meta = subj_info["cutout_meta"]
    if cutout_bgra is None:
        cutout_bgra, cut_meta = _fallback_feathered_vignette_cutout(subj_info["bgr"])

    relit_bgra = _relight_cutout_bgra(cutout_bgra, mood=mood)
    ch, cw = relit_bgra.shape[:2]
    aspect = cw / max(1.0, float(ch))

    # Scale hero subject generously for strong Netflix poster presence while preserving a clean
    # breathing channel from the left headline. Wide horned/landscape subjects bleed subtly off
    # the right frame edge so their head/eyes stay tall and commanding.
    target_h = H * 0.92 if cut_meta.get("touches_bottom") else H * 0.86
    target_w = target_h * aspect
    max_subj_w = W * (0.58 if aspect > 1.18 else 0.50)
    if target_w > max_subj_w:
        target_w = max_subj_w
        target_h = target_w / max(0.2, aspect)
    elif target_w < W * 0.36:
        target_w = min(W * 0.46, target_w * 1.15)
        target_h = min(H * 0.94, target_w / max(0.2, aspect))

    # Anchor cleanly to right & bottom borders for seamless grounded movie-poster presence
    if cut_meta.get("touches_right") or aspect > 1.18:
        sx = max(W * 0.47, W - target_w + 34.0)
    else:
        sx = max(W * 0.50, W - target_w - 22.0)
    sy = (H - target_h + 10.0) if cut_meta.get("touches_bottom") else max(28.0, (H - target_h) * 0.68)
    dst_rect = skia.Rect.MakeXYWH(sx, sy, target_w, target_h)

    # Multi-layered soft feathered rim-light halo BEHIND the shoulders/head
    sil_outer = _make_colored_silhouette_skia(relit_bgra, pal["b_rim_outer_rgb"])
    sil_warm = _make_colored_silhouette_skia(relit_bgra, pal["b_rim_warm_rgb"])
    sil_cold = _make_colored_silhouette_skia(relit_bgra, pal["b_rim_cold_rgb"])

    # Outer volumetric crimson/amber aura
    rim_outer_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    rim_outer_p.setAlphaf(0.72)
    rim_outer_p.setImageFilter(skia.ImageFilters.Blur(44.0, 44.0))
    cb.drawImageRect(
        sil_outer,
        skia.Rect.MakeXYWH(sx + 10.0, sy - 6.0, target_w, target_h),
        skia.SamplingOptions(skia.FilterMode.kLinear),
        rim_outer_p,
    )

    # Sculpted warm rim-light halo kissing right contour of hair/shoulders
    rim_warm_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    rim_warm_p.setAlphaf(0.78)
    rim_warm_p.setImageFilter(skia.ImageFilters.Blur(14.0, 14.0))
    cb.drawImageRect(
        sil_warm,
        skia.Rect.MakeXYWH(sx + 8.0, sy - 3.0, target_w, target_h),
        skia.SamplingOptions(skia.FilterMode.kLinear),
        rim_warm_p,
    )

    # Subtle cold-teal studio rim kiss on left edge of subject
    rim_cold_p = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kScreen)
    rim_cold_p.setAlphaf(0.42)
    rim_cold_p.setImageFilter(skia.ImageFilters.Blur(12.0, 12.0))
    cb.drawImageRect(
        sil_cold,
        skia.Rect.MakeXYWH(sx - 7.0, sy - 2.0, target_w, target_h),
        skia.SamplingOptions(skia.FilterMode.kLinear),
        rim_cold_p,
    )

    # Grounding dark shadow behind subject + crisp feathered subject on top
    subj_img = _bgra_to_skia_image(relit_bgra)
    cb.drawImageRect(subj_img, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear))

    # Subtle left-side dark contrast scrim + bottom atmospheric mist ground so subject & headline merge
    b_scrim = skia.Paint(AntiAlias=True)
    b_scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, 0.0), (W * 0.56, 0.0)],
            [
                skia.ColorSetARGB(185, 5, 11, 16),
                skia.ColorSetARGB(105, 5, 11, 16),
                skia.ColorSetARGB(0, 5, 11, 16),
            ],
            [0.0, 0.62, 1.0],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), b_scrim)

    b_bottom_mist = skia.Paint(AntiAlias=True)
    b_bottom_mist.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, H * 0.72), (0.0, H)],
            [skia.ColorSetARGB(0, 5, 7, 11), skia.ColorSetARGB(205, 5, 7, 11)],
        )
    )
    cb.drawRect(skia.Rect.MakeWH(W, H), b_bottom_mist)

    # 5. Bold Metallic-Gold & Crisp Ice-White Cinema Headline on Left
    grads_b = _build_line_gradient_sequence(len(words), pal["b_accent_grad"], lead_accent=(len(words) == 2))
    _draw_cinema_poster_headline(
        cb,
        words=words,
        x_left=64.0,
        max_w=W * 0.43,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        line_gradients=grads_b,
        accent_bar_hex=pal["b_bar_hex"],
        vertical_anchor="center",
        bar_position="bottom",
        canvas_w=W,
        canvas_h=H,
    )
    _draw_film_grain(cb, W, H, alpha=24, seed=seed_base + 2)

    thumb_b_path = output_dir / "thumb_B_contrast.jpg"
    _save_surface_jpeg(surf_b, thumb_b_path, quality=94)

    # =========================================================================
    # THUMB C: INTENSE CLOSE-UP CHIAROSCURO + EDITORIAL VIGNETTE (thumb_C_zoom.jpg)
    # =========================================================================
    surf_c = skia.Surface(W, H)
    cc = surf_c.getCanvas()
    cc.clear(hex_to_skia("#050508"))

    hero_c = roles["c"]
    graded_c = _cinema_grade_bgr(hero_c["bgr"], style="closeup", mood=mood)
    # Tight 1.32x cinematic focal close-up using 100% genuine edge-to-edge pixels (zero left seam)
    # with gentle upper-right framing so heads/eyes stay cleanly inside the cinema frame.
    focal_dst_c = (0.60, 0.48)
    composed_c = _compose_focal_canvas_bgr(
        graded_c,
        target_w=W,
        target_h=H,
        src_focal=(hero_c["focal"][0], max(0.32, hero_c["focal"][1])),
        dst_focal=focal_dst_c,
        zoom=1.32,
        allow_left_mist_extend=False,
    )
    cc.drawImageRect(_bgr_to_skia_image(composed_c), skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kLinear))

    # Deep moody radial chiaroscuro vignette centered around the focal subject
    fx_c, fy_c = W * focal_dst_c[0], H * focal_dst_c[1]
    rad_vig_c = skia.Paint(AntiAlias=True)
    rad_vig_c.setShader(
        skia.GradientShader.MakeRadial(
            (fx_c, fy_c),
            W * 0.74,
            [
                skia.ColorSetARGB(0, 6, 5, 10),
                skia.ColorSetARGB(62, 6, 5, 10),
                skia.ColorSetARGB(185, 6, 5, 10),
                skia.ColorSetARGB(242, 4, 4, 8),
            ],
            [0.0, 0.36, 0.74, 1.0],
        )
    )
    cc.drawRect(skia.Rect.MakeWH(W, H), rad_vig_c)

    # Smooth horizontal left-to-center chiaroscuro mist + lower-left reading scrim
    left_scrim_c = skia.Paint(AntiAlias=True)
    left_scrim_c.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, 0.0), (W * 0.56, 0.0)],
            [
                skia.ColorSetARGB(218, 6, 5, 10),
                skia.ColorSetARGB(120, 6, 5, 10),
                skia.ColorSetARGB(0, 6, 5, 10),
            ],
            [0.0, 0.52, 1.0],
        )
    )
    cc.drawRect(skia.Rect.MakeWH(W, H), left_scrim_c)

    lower_left_scrim = skia.Paint(AntiAlias=True)
    lower_left_scrim.setShader(
        skia.GradientShader.MakeRadial(
            (W * 0.18, H * 0.80),
            W * 0.58,
            [
                skia.ColorSetARGB(225, 6, 5, 10),
                skia.ColorSetARGB(145, 6, 5, 10),
                skia.ColorSetARGB(0, 6, 5, 10),
            ],
            [0.0, 0.55, 1.0],
        )
    )
    cc.drawRect(skia.Rect.MakeWH(W, H), lower_left_scrim)

    # Subtle glowing spotlight flare around focal point
    _draw_subtle_spotlight_flare(cc, fx_c, fy_c, pal["c_flare_rgb"])

    # Delicate 1.5px editorial cinema-glass corner viewfinder marks (ZERO chunky cartoons!)
    _draw_editorial_viewfinder_marks(cc, W, H)

    # Dramatic bold lower-left / mid-left movie title lockup
    grads_c = _build_line_gradient_sequence(len(words), pal["c_accent_grad"], lead_accent=False)
    _draw_cinema_poster_headline(
        cc,
        words=words,
        x_left=68.0,
        max_w=W * 0.52,
        anton_tf=anton_tf,
        mont_tf=mont_tf,
        line_gradients=grads_c,
        accent_bar_hex=pal["c_bar_hex"],
        vertical_anchor="lower_left",
        bar_position="top",
        canvas_w=W,
        canvas_h=H,
    )
    _draw_film_grain(cc, W, H, alpha=28, seed=seed_base + 3)

    thumb_c_path = output_dir / "thumb_C_zoom.jpg"
    _save_surface_jpeg(surf_c, thumb_c_path, quality=94)

    print(
        f"[ThumbStudio] Generated 3 cinema 1280x720 thumbnails ({hero_source_summary}, mood={mood}, words={words}) -> {output_dir}",
        flush=True,
    )
    return {
        "thumb_a": str(thumb_a_path),
        "thumb_b": str(thumb_b_path),
        "thumb_c": str(thumb_c_path),
        "headline_words": " ".join(words),
        "lines": words,
        "hero_source": hero_source_summary,
    }
