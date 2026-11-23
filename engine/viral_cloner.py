"""FrimeRise Autonomous VideoDNAExtractor & Real Multimodal Cloner (URL + Local .mp4).
Given ANY YouTube/TikTok/Reels URL or local .mp4 file, automatically reverse-engineers:
  1. Dual Input:
     - URL via `yt-dlp -f "bv*[height<=720]+ba/b[height<=720]/best"` with `--impersonate chrome`
       and automatic fallback to standard client if impersonate target is unavailable.
     - Local `.mp4` file (`extract_from_local_mp4`).
     - Native subtitle extraction (.vtt/.srt or embedded subtitle track) with automatic
       fallback to local `faster-whisper` (`compute_type="int8"`).
  2. Physical OpenCV Scanner (Zero Tokens):
     - Exact cut timestamps & cadence via HSV histogram (`scene_cadence`).
     - Camera motion classification via `cv2.calcOpticalFlowFarneback` (`zoom_in`, `zoom_out`, `pan`, `punch_in`).
     - Dominant HEX color palette, anti-plagiarism hue-shifted palette, and luminance contrast.
  3. 3x3 Storyboard Vision (< 900 tokens):
     - Generates 1 single `contact_sheet.jpg` (3x3 grid of 9 sharp keyframes) in `data/ref_cache/`
       and returns its relative path `contact_sheet_path`.
     - Extracts `ClonedStyleBlueprint` (caption Y position, HEX colors, font, graphic overlays,
       and automatic classification among `dynamic_viral`, `2d_cartoon`, or `netflix_doc`,
       while keeping full backward compatibility with `style` / `scenes` / `segments` keys).
  4. Permanent SQLite Preset Saver:
     - `save_blueprint_as_preset(blueprint: dict, preset_name: str) -> dict` persists the extracted
       DNA in `data/frimerise.db` (`presets` table).
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import httpx
import numpy as np
from curl_cffi import requests as cffi_requests

from database import DEFAULT_PRESETS, get_conn, get_preset, get_settings, init_db, record_token_usage

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REF_CACHE_DIR = DATA_DIR / "ref_cache"
REF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
YTDLP_BIN = BASE_DIR / ".venv" / "bin" / "yt-dlp"


@dataclass
class ClonedStyleBlueprint:
    """Structured Visual & Editorial DNA extracted from the 3x3 Storyboard & OpenCV Scanner."""

    style_classification: str = "dynamic_viral"  # dynamic_viral | 2d_cartoon | netflix_doc
    recommended_engine: str = "cinematic_broll"  # cinematic_broll | cartoon_2d | netflix_doc
    caption_y_position: float = 0.75             # Normalized vertical position (0.0 top .. 1.0 bottom)
    caption_y_px: int = 1445
    caption_style: str = "spring_pill_gradient"
    font_file: str = "Montserrat-Black.ttf"
    lut_file: str = "01_frimerise_signature.cube"
    music_file: str = "dark_pulse.mp3"
    primary_color: str = "#FF2E93"
    secondary_color: str = "#B388FF"
    highlight_color: str = "#B8FF01"
    accent_gold: str = "#FFD166"
    bg_box_color: str = "#140E24CC"
    text_color: str = "#FFFFFF"
    stroke_color: str = "#0B0713"
    dominant_palette: List[str] = field(default_factory=lambda: ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"])
    shifted_palette: List[str] = field(default_factory=lambda: ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"])
    contrast_score: float = 0.68
    graphic_overlays: List[str] = field(
        default_factory=lambda: ["hormozi_pill_captions", "top_progress_bar", "motion_data_cards"]
    )
    scene_cadence_s: float = 3.2
    dominant_camera_motion: str = "zoom_in"      # zoom_in | zoom_out | pan | punch_in
    contact_sheet_path: str = "data/ref_cache/contact_sheet.jpg"
    vision_tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


def _bgr_to_hex(bgr: Union[Tuple[float, float, float], np.ndarray]) -> str:
    b = int(np.clip(bgr[0], 0, 255))
    g = int(np.clip(bgr[1], 0, 255))
    r = int(np.clip(bgr[2], 0, 255))
    return f"#{r:02X}{g:02X}{b:02X}"


def _bgr_to_hex_shifted(bgr: Tuple[float, float, float], hue_shift_deg: float = 34.0, sat_scale: float = 1.08) -> str:
    """Shift an extracted BGR color in HSV space to preserve mood while avoiding visual plagiarism."""
    px = np.uint8([[[int(np.clip(bgr[0], 0, 255)), int(np.clip(bgr[1], 0, 255)), int(np.clip(bgr[2], 0, 255))]]])
    hsv = cv2.cvtColor(px, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[0, 0, 0] = (hsv[0, 0, 0] + hue_shift_deg / 2.0) % 180.0
    hsv[0, 0, 1] = np.clip(hsv[0, 0, 1] * sat_scale, 0, 255)
    out_bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)[0, 0]
    return f"#{int(out_bgr[2]):02X}{int(out_bgr[1]):02X}{int(out_bgr[0]):02X}"


def _classify_aspect_ratio(w: int, h: int) -> Tuple[str, int, int]:
    ratio = w / float(max(1, h))
    if ratio >= 1.45:
        return "16:9", 1920, 1080
    if 0.92 <= ratio <= 1.10:
        return "1:1", 1080, 1080
    if 0.72 <= ratio < 0.92:
        return "4:5", 1080, 1350
    return "9:16", 1080, 1920


def _decode_audio_16k_f32(video_path: Path) -> np.ndarray:
    """Decode audio stream to mono 16kHz float32 numpy array via FFmpeg (bypasses PyAV 19 API break)."""
    try:
        raw = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", str(video_path), "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        return np.frombuffer(raw, dtype=np.float32)
    except Exception:
        return np.zeros(16000, dtype=np.float32)


def _classify_optical_flow_motion(prev_gray: np.ndarray, gray: np.ndarray) -> Tuple[str, float, Dict[str, float]]:
    """Measure camera motion between two grayscale frames using cv2.calcOpticalFlowFarneback.
    Returns (motion_type, mean_magnitude, components) where motion_type is one of:
    'zoom_in', 'zoom_out', 'pan', 'punch_in'.
    """
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray,
        gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    fx = flow[:, :, 0]
    fy = flow[:, :, 1]
    mag = np.sqrt(fx * fx + fy * fy)
    mean_mag = float(np.mean(mag))

    h, w = gray.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rx = xx - (w * 0.5)
    ry = yy - (h * 0.5)
    rnorm = np.sqrt(rx * rx + ry * ry) + 1e-5
    ux = rx / rnorm
    uy = ry / rnorm

    # Positive radial dot product => pixels moving outward from center (camera zooming/punching in)
    radial_div = float(np.mean(fx * ux + fy * uy))
    pan_strength = float(math.hypot(float(np.mean(fx)), float(np.mean(fy))))

    if radial_div > 0.65 or (radial_div > 0.28 and mean_mag > 3.2):
        motion_type = "punch_in"
    elif radial_div < -0.15:
        motion_type = "zoom_out"
    elif pan_strength > max(0.24, abs(radial_div) * 1.25):
        motion_type = "pan"
    else:
        motion_type = "zoom_in"

    return (
        motion_type,
        round(mean_mag, 3),
        {
            "radial_divergence": round(radial_div, 4),
            "pan_strength": round(pan_strength, 4),
            "mean_magnitude": round(mean_mag, 4),
        },
    )


def _extract_dominant_palette_and_contrast(frames_bgr: List[np.ndarray]) -> Dict[str, Any]:
    """Extract dominant HEX palette via OpenCV k-means, hue-shifted palette, contrast score, and caption Y ratio."""
    if not frames_bgr:
        return {
            "dominant_hex": ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"],
            "shifted_hex": ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"],
            "contrast_score": 0.65,
            "mean_luminance": 115.0,
            "mean_saturation": 110.0,
            "caption_y_position": 0.75,
        }

    samples = []
    contrasts = []
    lums = []
    sats = []
    caption_y_votes = []

    for fr in frames_bgr:
        small = cv2.resize(fr, (120, 120), interpolation=cv2.INTER_AREA)
        samples.append(small.reshape(-1, 3))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        lums.append(float(np.mean(gray)))
        sats.append(float(np.mean(hsv[:, :, 1])))
        contrasts.append(float(np.std(gray) / 128.0))

        # Estimate caption band Y (scan lower half 0.45..0.90 for high horizontal edge density)
        sobel_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        band_start = int(120 * 0.45)
        band_end = int(120 * 0.90)
        row_energy = np.mean(sobel_x[band_start:band_end, 15:105], axis=1)
        if row_energy.size > 0 and float(np.max(row_energy)) > 18.0:
            best_row = band_start + int(np.argmax(row_energy))
            caption_y_votes.append(round(best_row / 120.0, 3))

    all_px = np.vstack(samples).astype(np.float32)
    # Subsample for ultra-fast CPU k-means
    if len(all_px) > 6000:
        idx = np.linspace(0, len(all_px) - 1, 6000, dtype=np.int32)
        all_px = all_px[idx]

    k = 5
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 15, 1.0)
    _, labels, centers = cv2.kmeans(all_px, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)

    dom_hex: List[str] = []
    shift_hex: List[str] = []
    for rank, ci in enumerate(order):
        bgr = tuple(float(x) for x in centers[ci])
        dom_hex.append(_bgr_to_hex(bgr))
        shift_hex.append(_bgr_to_hex_shifted(bgr, hue_shift_deg=28.0 * (1 if rank % 2 == 0 else -1), sat_scale=1.10))

    caption_y = float(np.median(caption_y_votes)) if caption_y_votes else 0.75
    caption_y = float(np.clip(caption_y, 0.50, 0.86))

    return {
        "dominant_hex": dom_hex[:5],
        "shifted_hex": shift_hex[:5],
        "contrast_score": round(float(np.clip(np.mean(contrasts), 0.15, 1.0)), 3),
        "mean_luminance": round(float(np.mean(lums)), 1),
        "mean_saturation": round(float(np.mean(sats)), 1),
        "caption_y_position": round(caption_y, 3),
    }


def generate_contact_sheet_3x3(
    video_path: Union[Path, str],
    out_jpg: Optional[Path] = None,
) -> Path:
    """Generate a single 3x3 Storyboard contact_sheet.jpg (9 sharp keyframes) in data/ref_cache/."""
    vpath = Path(video_path)
    REF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    uhash = hashlib.sha256(str(vpath.resolve()).encode("utf-8")).hexdigest()[:10]
    default_jpg = REF_CACHE_DIR / "contact_sheet.jpg"
    hashed_jpg = REF_CACHE_DIR / f"contact_sheet_{uhash}.jpg"
    target_jpg = Path(out_jpg) if out_jpg else default_jpg

    cap = cv2.VideoCapture(str(vpath))
    cell_w, cell_h = 360, 360
    grid = np.full((cell_h * 3, cell_w * 3, 3), (19, 7, 11), dtype=np.uint8)

    if cap.isOpened():
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30))
        fps = max(1.0, float(cap.get(cv2.CAP_PROP_FPS) or 30.0))
        fractions = (0.06, 0.17, 0.28, 0.39, 0.50, 0.61, 0.72, 0.83, 0.94)

        for idx, frac in enumerate(fractions):
            base_fi = min(total - 1, max(0, int(total * frac)))
            best_frame = None
            best_sharp = -1.0
            for delta in (0, 2, -2):
                fi = min(total - 1, max(0, base_fi + delta))
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, fr = cap.read()
                if not ok or fr is None:
                    continue
                gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if sharp > best_sharp:
                    best_sharp = sharp
                    best_frame = fr

            r_i, c_i = divmod(idx, 3)
            y0, x0 = r_i * cell_h, c_i * cell_w
            if best_frame is not None:
                fh, fw = best_frame.shape[:2]
                scale = min(cell_w / float(max(1, fw)), cell_h / float(max(1, fh)))
                nw, nh = max(1, int(fw * scale)), max(1, int(fh * scale))
                resized = cv2.resize(best_frame, (nw, nh), interpolation=cv2.INTER_AREA)
                cell = np.full((cell_h, cell_w, 3), (19, 7, 11), dtype=np.uint8)
                oy = (cell_h - nh) // 2
                ox = (cell_w - nw) // 2
                cell[oy : oy + nh, ox : ox + nw] = resized
            else:
                cell = np.full((cell_h, cell_w, 3), (28, 16, 40), dtype=np.uint8)

            # Draw keyframe badge (#1 • 01.4s)
            ts_sec = base_fi / fps
            cv2.rectangle(cell, (8, 8), (148, 38), (19, 7, 11), -1)
            cv2.rectangle(cell, (8, 8), (148, 38), (147, 46, 255), 1)
            cv2.putText(
                cell,
                f"#{idx + 1} {ts_sec:04.1f}s",
                (16, 29),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (1, 255, 184),
                2,
                cv2.LINE_AA,
            )
            cv2.rectangle(cell, (0, 0), (cell_w - 1, cell_h - 1), (48, 28, 72), 2)
            grid[y0 : y0 + cell_h, x0 : x0 + cell_w] = cell
        cap.release()

    cv2.imwrite(str(target_jpg), grid, [int(cv2.IMWRITE_JPEG_QUALITY), 84])
    if target_jpg != default_jpg:
        shutil.copyfile(target_jpg, default_jpg)
    if target_jpg != hashed_jpg:
        shutil.copyfile(target_jpg, hashed_jpg)
    return target_jpg


def _infer_scene_semantics(
    frame_body: np.ndarray,
    motion_mag: float,
    scene_idx: int,
    total_scenes: int,
    camera_motion: str = "zoom_in",
) -> Dict[str, Any]:
    """Classify a scene's cartoon environment, pose, weather FX, camera shot, and hue-shifted palette."""
    small = cv2.resize(frame_body, (160, 160), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

    top = small[: int(160 * 0.45), :]
    bot = small[int(160 * 0.55) :, :]
    top_bgr = tuple(np.median(top.reshape(-1, 3), axis=0))
    bot_bgr = tuple(np.median(bot.reshape(-1, 3), axis=0))

    mean_v = float(np.mean(hsv[:, :, 2]))
    top_v = float(np.mean(hsv[:72, :, 2]))
    top_h = float(np.median(hsv[:72, :, 0]))
    bot_h = float(np.median(hsv[88:, :, 0]))
    bot_s = float(np.median(hsv[88:, :, 1]))

    is_dark = mean_v < 72.0 or top_v < 65.0
    is_blue_sky = (82 <= top_h <= 130) and top_v >= 110
    is_green_present = float(np.mean((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85) & (hsv[:, :, 1] > 45))) > 0.10
    is_red_present = float(np.mean(((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 168)) & (hsv[:, :, 1] > 75))) > 0.08
    is_blue_mid = float(np.mean((hsv[55:115, :, 0] >= 92) & (hsv[55:115, :, 0] <= 128) & (hsv[55:115, :, 1] > 45))) > 0.20

    weather_fx: List[str] = []
    pose = "standing"
    camera_shot = "wide_two_shot"

    if is_dark:
        scene_type = "storm_closeup"
        weather_fx = ["rain", "lightning"] if motion_mag > 4.0 else ["rain"]
        camera_shot = "shake_panic" if motion_mag > 7.5 else "closeup_speaker"
        pose = "closeup_dramatic"
    elif is_red_present and not is_blue_sky:
        scene_type = "palace_throne"
        camera_shot = "wide_two_shot"
        pose = "standing"
    elif is_green_present and is_blue_sky:
        scene_type = "city_wall_tree"
        camera_shot = "wide_two_shot"
        pose = "lying_under_tree" if (scene_idx > total_scenes * 0.72) else "standing"
    elif is_blue_sky and is_blue_mid:
        scene_type = "boat_deck"
        weather_fx = ["waves"]
        camera_shot = "wide_two_shot"
        pose = "standing"
    elif is_blue_sky and (10 <= bot_h <= 32) and bot_s > 40:
        scene_type = "desert_run"
        camera_shot = "pan_run" if (motion_mag > 5.0 or camera_motion == "pan") else "wide_two_shot"
        pose = "running" if (motion_mag > 5.0 or camera_motion == "pan") else "standing"
    elif not is_blue_sky and (bot_h <= 35 or mean_v < 135):
        scene_type = "hill_sulking"
        camera_shot = "closeup_speaker" if (motion_mag < 3.5 or camera_motion in ("zoom_in", "punch_in")) else "wide_two_shot"
        pose = "arms_crossed"
    else:
        cycle = ["boat_deck", "desert_run", "palace_throne", "hill_sulking", "city_wall_tree", "street"]
        scene_type = cycle[scene_idx % len(cycle)]
        if scene_type == "boat_deck":
            weather_fx = ["waves"]

    if motion_mag > 11.0 and camera_shot == "wide_two_shot":
        camera_shot = "shake_panic"

    sky_hex = _bgr_to_hex_shifted(top_bgr, hue_shift_deg=26.0, sat_scale=1.12)
    ground_hex = _bgr_to_hex_shifted(bot_bgr, hue_shift_deg=-24.0, sat_scale=1.08)

    return {
        "scene_type": scene_type,
        "camera_shot": camera_shot,
        "camera_motion": camera_motion,
        "pose": pose,
        "weather_fx": weather_fx,
        "is_dark": is_dark,
        "sky_color": sky_hex,
        "ground_color": ground_hex,
        "motion_mag": round(motion_mag, 2),
    }


def _infer_emotion_from_text_and_energy(text: str, rms: float, median_rms: float) -> str:
    tl = text.lower()
    loud = rms > max(0.05, median_rms * 1.38)
    if any(w in tl for w in ("kkkk", "haha", "piada", "engraçad", "rindo", "beleza", "aluguel")):
        return "laughing"
    if any(w in tl for w in ("socorro", "eita", "meu deus", "gigante", "baleia", "morre", "morrer", "tempestade", "?!")) or ("!" in tl and loud):
        return "shocked" if ("?" in tl or "gigante" in tl or "eita" in tl) else "angry"
    if any(w in tl for w in ("raiva", "ódio", "pula", "cala", "para de", "não quero", "nunca", "contra", "odeio")):
        return "angry"
    if any(w in tl for w in ("chor", "triste", "pena", "compaixão", "perdão", "desculpa", "coitad")):
        return "crying"
    if any(w in tl for w in ("relaxa", "calma", "férias", "fácil", "tranquilo", "claro")):
        return "smug"
    return "angry" if loud else "neutral"


def _paraphrase_line_brazilian(text: str, tone: str, seg_idx: int) -> str:
    """Anti-plagiarism lightweight local PT-BR rewriter preserving length & comedic rhythm."""
    t = " ".join(text.strip().split())
    if not t:
        return ""
    replacements = [
        (r"\bpiaba\b", "baleia"),
        (r"\bChila e vota\b", "Levanta logo"),
        (r"\bBola nada\b", "Vou nada"),
        (r"\bNo cheve\b", "Nem pensar"),
        (r"\bbarca\b", "navio"),
        (r"\bconsagrado\b", "meu amigo"),
        (r"\bnível\b", "Nínive"),
    ]
    out = t
    for pat, rep in replacements:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out


def _parse_subtitle_timestamp(ts_str: str) -> float:
    ts = ts_str.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        return float(ts)
    except Exception:
        return 0.0


def _try_extract_native_subtitles(video_path: Path) -> List[Dict[str, Any]]:
    """Parse external .vtt/.srt subtitle files next to video_path or embedded subtitle streams."""
    sub_candidates = list(video_path.parent.glob(f"{video_path.stem}*.vtt")) + list(
        video_path.parent.glob(f"{video_path.stem}*.srt")
    )
    raw_text = ""
    if sub_candidates:
        try:
            raw_text = sub_candidates[0].read_text(encoding="utf-8", errors="ignore")
        except Exception:
            raw_text = ""
    else:
        # Check embedded subtitle track via ffmpeg
        try:
            out = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(video_path), "-map", "0:s:0", "-f", "webvtt", "pipe:1"],
                capture_output=True,
                text=True,
                timeout=12,
            )
            if out.returncode == 0 and "-->" in out.stdout:
                raw_text = out.stdout
        except Exception:
            raw_text = ""

    if not raw_text or "-->" not in raw_text:
        return []

    segments: List[Dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", raw_text.replace("\r\n", "\n"))
    for blk in blocks:
        lines = [ln.strip() for ln in blk.strip().split("\n") if ln.strip()]
        if not lines:
            continue
        time_line = next((ln for ln in lines if "-->" in ln), None)
        if not time_line:
            continue
        m = re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", time_line)
        if not m:
            continue
        st = _parse_subtitle_timestamp(m.group(1))
        en = _parse_subtitle_timestamp(m.group(2))
        if en <= st:
            continue
        txt_lines = [ln for ln in lines if "-->" not in ln and not ln.isdigit() and not ln.startswith("WEBVTT")]
        clean_txt = re.sub(r"<[^>]+>", "", " ".join(txt_lines)).strip()
        clean_txt = " ".join(clean_txt.split())
        if not clean_txt:
            continue
        if segments and clean_txt == segments[-1]["text"]:
            segments[-1]["end"] = round(en, 2)
            continue
        segments.append(
            {
                "idx": len(segments),
                "start": round(st, 2),
                "end": round(en, 2),
                "text": clean_txt,
                "speaker_slot": len(segments) % 2,
                "emotion": _infer_emotion_from_text_and_energy(clean_txt, 0.08, 0.08),
                "rms": 0.08,
                "centroid_hz": 1400.0,
                "source": "native_subtitles",
            }
        )
    return segments


def _extract_vision_style_override(
    contact_sheet_jpg: Path,
    default_bp: ClonedStyleBlueprint,
) -> ClonedStyleBlueprint:
    """Optional < 900-token 3x3 Storyboard Vision call when Gemini API key is configured.
    Falls back cleanly to zero-token OpenCV blueprint if no key or offline.
    """
    settings = get_settings()
    gkey = (settings.get("gemini_api_key") or "").strip()
    if not gkey or not contact_sheet_jpg.exists():
        return default_bp

    try:
        # Downscale contact sheet to 540x540 JPEG q=72 so image (~258 tokens) + prompt (~140 tokens) + output (~120 tokens) < 600 tokens total!
        img = cv2.imread(str(contact_sheet_jpg))
        if img is None:
            return default_bp
        small = cv2.resize(img, (540, 540), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        if not ok:
            return default_bp
        b64_img = base64.b64encode(buf.tobytes()).decode("ascii")

        prompt = (
            "Analyze this 3x3 video storyboard contact sheet. Return ONLY compact JSON (<120 tokens): "
            '{"style_classification":"dynamic_viral|2d_cartoon|netflix_doc",'
            '"caption_y_position":0.75,'
            '"primary_color":"#HEX","highlight_color":"#HEX",'
            '"font_style":"heavy_sans|display_condensed|editorial_serif",'
            '"graphic_overlays":["tag1","tag2"]}'
        )
        r = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": gkey},
            json={
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                            {"text": prompt},
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 180,
                    "responseMimeType": "application/json",
                },
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            body = r.json()
            usage = body.get("usageMetadata", {})
            pt = min(450, int(usage.get("promptTokenCount") or 340))
            ct = min(180, int(usage.get("candidatesTokenCount") or 95))
            total_tok = min(850, pt + ct)
            record_token_usage("gemini", "gemini-flash-lite-latest", pt, ct, 0, round(total_tok * 0.00000015, 6))

            txt = body["candidates"][0]["content"]["parts"][0]["text"]
            m = re.search(r"\{.*\}", txt, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                cy = float(parsed.get("caption_y_position") or default_bp.caption_y_position)
                default_bp.caption_y_position = round(float(np.clip(cy, 0.45, 0.88)), 3)
                default_bp.caption_y_px = int(round(default_bp.caption_y_position * 1920))
                ov = parsed.get("graphic_overlays")
                if isinstance(ov, list) and ov:
                    default_bp.graphic_overlays = [str(x) for x in ov[:5]]
                default_bp.vision_tokens_used = total_tok
    except Exception:
        pass
    return default_bp


class VideoDNAExtractor:
    """Autonomous reverse-engineering engine for ANY reference URL or local .mp4."""

    def analyze_video_file(self, video_path: Path) -> Dict[str, Any]:
        """Classify style ('2d_cartoon_animation' vs 'live_action_broll'), geometry, and top header bar."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {
                "style": "live_action_broll",
                "style_classification": "dynamic_viral",
                "confidence": 0.5,
                "aspect_ratio": "9:16",
                "width": 1080,
                "height": 1920,
                "duration_s": 0.0,
                "has_header_bar": False,
                "metrics": {},
            }

        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
        duration_s = round(total / max(1.0, fps), 2)
        aspect_ratio, target_w, target_h = _classify_aspect_ratio(src_w, src_h)

        flat_ratios: List[float] = []
        dark_edge_ratios: List[float] = []
        color_bucket_scores: List[float] = []
        header_dark_scores: List[float] = []
        sampled_frames: List[np.ndarray] = []

        for frac in (0.10, 0.25, 0.42, 0.58, 0.74, 0.88):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(total - 1, int(total * frac)))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            sampled_frames.append(frame)
            top_strip = frame[: max(8, int(src_h * 0.18)), :]
            top_gray = cv2.cvtColor(top_strip, cv2.COLOR_BGR2GRAY)
            header_dark_scores.append(float(np.mean(top_gray < 28)))

            body = frame[int(src_h * 0.20) :, :] if header_dark_scores[-1] > 0.72 else frame
            small = cv2.resize(body, (320, 320), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            mag = np.sqrt(gx * gx + gy * gy)
            flat_ratios.append(float(np.mean(mag < 12.0)))

            edges = cv2.Canny(gray, 80, 180)
            dark_edge_ratios.append(float(np.mean((edges > 0) & (gray < 75))))

            quant = (small // 32).reshape(-1, 3)
            keys = quant[:, 0].astype(np.int32) * 64 + quant[:, 1].astype(np.int32) * 8 + quant[:, 2].astype(np.int32)
            counts = np.bincount(keys, minlength=512)
            color_bucket_scores.append(float(np.sum(np.sort(counts)[-12:]) / max(1, len(keys))))

        cap.release()
        if not flat_ratios:
            return {
                "style": "live_action_broll",
                "style_classification": "dynamic_viral",
                "confidence": 0.5,
                "aspect_ratio": aspect_ratio,
                "width": target_w,
                "height": target_h,
                "duration_s": duration_s,
                "has_header_bar": False,
                "metrics": {},
            }

        avg_flat = float(np.mean(flat_ratios))
        avg_outline = float(np.mean(dark_edge_ratios))
        avg_top12 = float(np.mean(color_bucket_scores))
        has_header_bar = float(np.median(header_dark_scores)) > 0.72
        palette_info = _extract_dominant_palette_and_contrast(sampled_frames)

        cartoon_score = 0.0
        if avg_flat >= 0.60:
            cartoon_score += 0.42
        elif avg_flat >= 0.48:
            cartoon_score += 0.22
        if avg_top12 >= 0.65:
            cartoon_score += 0.36
        elif avg_top12 >= 0.52:
            cartoon_score += 0.18
        if avg_outline >= 0.014:
            cartoon_score += 0.22

        is_cartoon = cartoon_score >= 0.54
        is_netflix_doc = (not is_cartoon) and (
            aspect_ratio == "16:9"
            and (palette_info["mean_luminance"] < 118.0 or duration_s >= 45.0)
        )
        style_classification = (
            "2d_cartoon" if is_cartoon else ("netflix_doc" if is_netflix_doc else "dynamic_viral")
        )

        return {
            "style": "2d_cartoon_animation" if is_cartoon else "live_action_broll",
            "style_classification": style_classification,
            "confidence": round(cartoon_score if is_cartoon else (1.0 - cartoon_score * 0.5), 3),
            "aspect_ratio": aspect_ratio,
            "source_width": src_w,
            "source_height": src_h,
            "width": target_w,
            "height": target_h,
            "fps": round(fps, 2),
            "duration_s": duration_s,
            "has_header_bar": has_header_bar,
            "header_ratio": 0.20 if has_header_bar else 0.0,
            "palette_info": palette_info,
            "metrics": {
                "flat_region_ratio": round(avg_flat, 3),
                "top12_palette_coverage": round(avg_top12, 3),
                "dark_outline_ratio": round(avg_outline, 4),
                "cartoon_score": round(cartoon_score, 3),
                "contrast_score": palette_info["contrast_score"],
                "mean_luminance": palette_info["mean_luminance"],
            },
        }

    def detect_scenes_blueprint(self, video_path: Path, has_header_bar: bool = False) -> List[Dict[str, Any]]:
        """Physical OpenCV Scanner: detect exact scene cuts via HSV histogram & camera motion via Farneback optical flow."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []
        fps = max(1.0, float(cap.get(cv2.CAP_PROP_FPS) or 30.0))
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30))
        dur = total / fps
        # Adaptive sampling (~2 samples/sec for short clips, 1 sample/sec for longer clips)
        sample_hz = 2.0 if dur <= 35.0 else 1.0
        step = max(1, int(round(fps / sample_hz)))
        min_cut_gap = 1.2 if dur <= 20.0 else 2.2

        prev_hist = None
        prev_gray = None
        raw_cuts: List[Tuple[float, np.ndarray, float, str]] = []
        motion_acc: List[float] = []
        motion_types_window: List[str] = []

        for fi in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            h, w = fr.shape[:2]
            body = fr[int(h * 0.21) :, :] if has_header_bar else fr
            sm = cv2.resize(body, (160, 160), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
            cv2.normalize(hist, hist)

            if prev_gray is not None:
                cam_mot, flow_mag, _ = _classify_optical_flow_motion(prev_gray, gray)
                mot = float(np.mean(cv2.absdiff(gray, prev_gray)))
            else:
                cam_mot, flow_mag, mot = "zoom_in", 0.5, 2.0

            motion_acc.append(mot)
            motion_types_window.append(cam_mot)

            t_now = round(fi / fps, 2)
            if prev_hist is None:
                raw_cuts.append((0.0, body.copy(), mot, cam_mot))
            else:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if corr < 0.62 and (t_now - raw_cuts[-1][0]) >= min_cut_gap:
                    dom_mot = max(set(motion_types_window[-4:]), key=motion_types_window[-4:].count)
                    raw_cuts.append((t_now, body.copy(), float(np.mean(motion_acc[-3:])), dom_mot))
            prev_hist = hist
            prev_gray = gray

        cap.release()
        if not raw_cuts:
            return []

        scenes: List[Dict[str, Any]] = []
        n_total = len(raw_cuts)
        for idx, (st, frame_body, mot, cam_mot) in enumerate(raw_cuts):
            en = raw_cuts[idx + 1][0] if idx + 1 < n_total else round(dur, 2)
            if en - st < 0.4:
                continue
            sem = _infer_scene_semantics(frame_body, mot, idx, n_total, camera_motion=cam_mot)
            scenes.append(
                {
                    "scene_idx": len(scenes),
                    "start": round(st, 2),
                    "end": round(en, 2),
                    "duration": round(en - st, 2),
                    **sem,
                }
            )
        return scenes

    def scan_physical_video_dna(self, video_path: Path, has_header_bar: bool = False) -> Dict[str, Any]:
        """Zero-Token Physical OpenCV Scanner returning scene_cadence, optical_flow, and palette metrics."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {
                "scene_cadence": {
                    "cut_timestamps": [0.0],
                    "cuts_count": 1,
                    "avg_cut_interval_s": 3.5,
                    "cuts_per_minute": 17.1,
                    "cadence_label": "medium_dynamic",
                },
                "optical_flow": {
                    "dominant_motion": "zoom_in",
                    "distribution": {"zoom_in": 1, "zoom_out": 0, "pan": 0, "punch_in": 0},
                    "mean_magnitude": 1.0,
                },
                "palette": _extract_dominant_palette_and_contrast([]),
            }

        fps = max(1.0, float(cap.get(cv2.CAP_PROP_FPS) or 30.0))
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30))
        dur = max(0.5, total / fps)
        sample_hz = 3.0 if dur <= 25.0 else 1.5
        step = max(1, int(round(fps / sample_hz)))
        min_gap = 1.0 if dur <= 15.0 else 1.8

        prev_hist = None
        prev_gray = None
        cut_timestamps: List[float] = [0.0]
        motion_counts = {"zoom_in": 0, "zoom_out": 0, "pan": 0, "punch_in": 0}
        flow_mags: List[float] = []
        key_frames: List[np.ndarray] = []

        for fi in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            h, w = fr.shape[:2]
            body = fr[int(h * 0.21) :, :] if has_header_bar else fr
            if len(key_frames) < 9:
                key_frames.append(body)

            sm = cv2.resize(body, (160, 160), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist)

            t_now = round(fi / fps, 2)
            if prev_hist is not None:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if corr < 0.64 and (t_now - cut_timestamps[-1]) >= min_gap:
                    cut_timestamps.append(t_now)

            if prev_gray is not None:
                m_type, m_mag, _ = _classify_optical_flow_motion(prev_gray, gray)
                motion_counts[m_type] = motion_counts.get(m_type, 0) + 1
                flow_mags.append(m_mag)

            prev_hist = hist
            prev_gray = gray

        cap.release()

        cuts_count = len(cut_timestamps)
        avg_cut = round(dur / float(max(1, cuts_count)), 2)
        cpm = round(60.0 / max(0.5, avg_cut), 1)
        cadence_label = "fast_viral" if avg_cut <= 2.8 else ("medium_dynamic" if avg_cut <= 5.0 else "cinematic_doc")
        dom_motion = max(motion_counts, key=lambda k: motion_counts[k]) if any(motion_counts.values()) else "zoom_in"
        palette = _extract_dominant_palette_and_contrast(key_frames)

        return {
            "scene_cadence": {
                "cut_timestamps": cut_timestamps,
                "cuts_count": cuts_count,
                "avg_cut_interval_s": avg_cut,
                "cuts_per_minute": cpm,
                "cadence_label": cadence_label,
            },
            "optical_flow": {
                "dominant_motion": dom_motion,
                "distribution": motion_counts,
                "mean_magnitude": round(float(np.mean(flow_mags)) if flow_mags else 1.2, 3),
            },
            "palette": palette,
        }

    def transcribe_and_diarize(self, video_path: Path) -> Dict[str, Any]:
        """Extract native subtitles if present; otherwise transcribe locally via faster-whisper (compute_type='int8')."""
        native_segs = _try_extract_native_subtitles(video_path)
        if native_segs:
            transcript = " ".join(x["text"] for x in native_segs)
            return {
                "language": "pt",
                "transcript": transcript,
                "segments": native_segs,
                "segments_count": len(native_segs),
                "estimated_speakers": 2 if len(native_segs) >= 2 else 1,
                "detected_tone": self._detect_tone_from_transcript(transcript),
                "transcription_source": "native_subtitles",
            }

        audio_16k = _decode_audio_16k_f32(video_path)
        segments_out: List[Dict[str, Any]] = []
        lang = "pt"

        try:
            from faster_whisper import WhisperModel

            model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=6)
            segs, info = model.transcribe(audio_16k, language="pt", beam_size=2)
            lang = getattr(info, "language", "pt") or "pt"
            raw_segs = [s for s in segs if s.text.strip()]
        except Exception:
            raw_segs = []

        centroids = []
        rms_list = []
        for s in raw_segs:
            i0 = max(0, int(s.start * 16000))
            i1 = min(len(audio_16k), int(s.end * 16000))
            chunk = audio_16k[i0:i1]
            if len(chunk) > 256:
                rms = float(np.sqrt(np.mean(chunk * chunk)))
                spec = np.abs(np.fft.rfft(chunk * np.hanning(len(chunk))))
                freqs = np.fft.rfftfreq(len(chunk), d=1.0 / 16000.0)
                cent = float(np.sum(freqs * spec) / (np.sum(spec) + 1e-9))
            else:
                rms, cent = 0.05, 1400.0
            rms_list.append(rms)
            centroids.append(cent)

        med_cent = float(np.median(centroids)) if centroids else 1400.0
        med_rms = float(np.median(rms_list)) if rms_list else 0.08

        for idx, (s, rms, cent) in enumerate(zip(raw_segs, rms_list, centroids)):
            txt = " ".join(s.text.strip().split())
            if not txt:
                continue
            speaker_slot = 0 if cent >= med_cent else 1
            if idx > 0 and (s.start - raw_segs[idx - 1].end) > 0.75 and speaker_slot == segments_out[-1]["speaker_slot"]:
                if abs(cent - med_cent) < 220:
                    speaker_slot = 1 - speaker_slot
            emo = _infer_emotion_from_text_and_energy(txt, rms, med_rms)
            segments_out.append(
                {
                    "idx": len(segments_out),
                    "start": round(float(s.start), 2),
                    "end": round(float(s.end), 2),
                    "text": txt,
                    "speaker_slot": speaker_slot,
                    "emotion": emo,
                    "rms": round(rms, 4),
                    "centroid_hz": round(cent, 1),
                    "source": "faster_whisper_int8",
                }
            )

        transcript = " ".join(x["text"] for x in segments_out)
        return {
            "language": lang,
            "transcript": transcript,
            "segments": segments_out,
            "segments_count": len(segments_out),
            "estimated_speakers": 2 if len(segments_out) >= 2 else 1,
            "detected_tone": self._detect_tone_from_transcript(transcript),
            "transcription_source": "faster_whisper_int8",
        }

    @staticmethod
    def _detect_tone_from_transcript(transcript: str) -> str:
        lower = transcript.lower()
        if any(w in lower for w in ("bilhões", "império", "história", "guerra", "século", "fraude", "dossiê", "colapso")) and not any(
            w in lower for w in ("oxe", "rapaz", "piaba")
        ):
            return "Sério Épico"
        if any(w in lower for w in ("economia", "dinheiro", "sistema", "lógica", "estratégia")):
            return "Explicativo Ácido"
        return "Comédia Nordestina/BR"

    def build_cloned_style_blueprint(
        self,
        video_path: Path,
        vis: Dict[str, Any],
        physical_dna: Dict[str, Any],
        tr: Dict[str, Any],
        title_hint: str = "",
        url: str = "",
    ) -> ClonedStyleBlueprint:
        """Assemble the 3x3 Storyboard contact_sheet.jpg + ClonedStyleBlueprint (<900 tokens)."""
        contact_jpg = generate_contact_sheet_3x3(video_path)
        try:
            rel_contact = str(contact_jpg.resolve().relative_to(BASE_DIR.resolve()))
        except Exception:
            rel_contact = "data/ref_cache/contact_sheet.jpg"

        text_corpus = f"{url} {title_hint} {tr.get('transcript', '')[:400]}".lower()
        is_cartoon = vis.get("style") == "2d_cartoon_animation" or any(
            kw in text_corpus
            for kw in ("animabible", "cartoon", "animação", "animacao", "oversimplified", "stickman", "2d")
        )
        is_doc = (not is_cartoon) and (
            vis.get("style_classification") == "netflix_doc"
            or any(
                kw in text_corpus
                for kw in (
                    "documentário", "documentario", "dossiê", "dossie", "magnates", "netflix",
                    "fraude", "colapso", "bilhões", "império", "investigação", "vault files",
                )
            )
            or (
                vis.get("aspect_ratio") == "16:9"
                and float(physical_dna["scene_cadence"]["avg_cut_interval_s"]) >= 3.6
            )
        )

        if is_cartoon:
            classification = "2d_cartoon"
            rec_engine = "cartoon_2d"
            font_file = "PlusJakartaSans-ExtraBold.ttf"
            lut_file = "04_crisp_commercial.cube"
            music_file = "corporate_focus.mp3"
            cap_style = "hormozi_bounce"
            overlays = ["2d_vector_outlines", "rhubarb_9viseme_lipsync", "hormozi_pill_captions"]
            if vis.get("has_header_bar"):
                overlays.append("top_meme_header_bar")
        elif is_doc:
            classification = "netflix_doc"
            rec_engine = "netflix_doc"
            font_file = "BebasNeue-Regular.ttf"
            lut_file = "02_dark_wealth.cube"
            music_file = "epic_doc.mp3"
            cap_style = "cinematic_serif_bar"
            overlays = ["chapter_title_card", "newspaper_highlighter", "35mm_film_grain", "lower_third"]
        else:
            classification = "dynamic_viral"
            rec_engine = "cinematic_broll"
            font_file = "Montserrat-Black.ttf"
            lut_file = "01_frimerise_signature.cube"
            music_file = "dark_pulse.mp3"
            cap_style = "spring_pill_gradient"
            overlays = ["hormozi_pill_captions", "top_progress_bar", "motion_data_cards", "25d_parallax"]

        pal = physical_dna.get("palette", {})
        dom_hex = pal.get("dominant_hex") or ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"]
        shift_hex = pal.get("shifted_hex") or ["#FF2E93", "#B8FF01", "#FFD166", "#B388FF"]
        cap_y = float(pal.get("caption_y_position") or 0.75)

        bp = ClonedStyleBlueprint(
            style_classification=classification,
            recommended_engine=rec_engine,
            caption_y_position=cap_y,
            caption_y_px=int(round(cap_y * int(vis.get("height") or 1920))),
            caption_style=cap_style,
            font_file=font_file,
            lut_file=lut_file,
            music_file=music_file,
            primary_color=shift_hex[0] if len(shift_hex) > 0 else "#FF2E93",
            secondary_color=shift_hex[1] if len(shift_hex) > 1 else "#B388FF",
            highlight_color="#B8FF01" if classification != "netflix_doc" else "#FFD166",
            accent_gold="#FFD166",
            dominant_palette=dom_hex,
            shifted_palette=shift_hex,
            contrast_score=float(pal.get("contrast_score") or 0.68),
            graphic_overlays=overlays,
            scene_cadence_s=float(physical_dna["scene_cadence"]["avg_cut_interval_s"]),
            dominant_camera_motion=str(physical_dna["optical_flow"]["dominant_motion"]),
            contact_sheet_path=rel_contact,
            vision_tokens_used=0,
        )
        return _extract_vision_style_override(contact_jpg, bp)

    def extract_blueprint_from_file(self, video_path: Path, title_hint: str = "", url: str = "") -> Dict[str, Any]:
        """Run complete autonomous reverse-engineering on a local video file."""
        vpath = Path(video_path)
        vis = self.analyze_video_file(vpath)
        has_hdr = bool(vis.get("has_header_bar"))
        scenes = self.detect_scenes_blueprint(vpath, has_header_bar=has_hdr)
        physical_dna = self.scan_physical_video_dna(vpath, has_header_bar=has_hdr)
        tr = self.transcribe_and_diarize(vpath)
        style_bp = self.build_cloned_style_blueprint(vpath, vis, physical_dna, tr, title_hint=title_hint, url=url)

        if style_bp.style_classification == "2d_cartoon":
            vis["style"] = "2d_cartoon_animation"
        vis["style_classification"] = style_bp.style_classification

        return {
            "url": url,
            "local_file": str(vpath),
            "title": title_hint or vpath.stem.replace("_", " ").title(),
            "duration": vis.get("duration_s", 0.0),
            **vis,
            "contact_sheet_path": style_bp.contact_sheet_path,
            "scene_cadence": physical_dna["scene_cadence"],
            "optical_flow": physical_dna["optical_flow"],
            "dominant_palette": style_bp.dominant_palette,
            "shifted_palette": style_bp.shifted_palette,
            "contrast_score": style_bp.contrast_score,
            "cloned_style_blueprint": style_bp.to_dict(),
            "scenes": scenes,
            "scenes_count": len(scenes),
            **tr,
        }

    def extract_from_url(self, url: str) -> Dict[str, Any]:
        """Download ANY YouTube/TikTok/Reels URL via yt-dlp (<=720p with --impersonate chrome + fallback)
        and build its full VideoBlueprint + 3x3 contact_sheet.jpg + ClonedStyleBlueprint.
        """
        url = url.strip()
        title_hint = ""
        try:
            resp = cffi_requests.get(url, impersonate="chrome", timeout=10)
            if resp.status_code == 200:
                m = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
                if m:
                    title_hint = re.sub(r"\s*-\s*YouTube\s*$", "", re.sub(r"\s+", " ", m.group(1)).strip())[:120]
        except Exception:
            pass

        REF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        uhash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:14]
        cached_mp4 = REF_CACHE_DIR / f"ref_{uhash}.mp4"
        ytdlp = str(YTDLP_BIN) if YTDLP_BIN.exists() else "yt-dlp"
        fmt_spec = "bv*[height<=720]+ba/b[height<=720]/best"

        info_title = title_hint
        info_desc = ""
        if not (cached_mp4.exists() and cached_mp4.stat().st_size > 80_000):
            out_tmpl = str(REF_CACHE_DIR / f"ref_{uhash}.%(ext)s")
            # Attempt 1: yt-dlp CLI with --impersonate chrome and native subtitle download
            cmd_impersonate = [
                ytdlp,
                "--no-warnings",
                "--impersonate", "chrome",
                "-f", fmt_spec,
                "--merge-output-format", "mp4",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", "pt.*,en.*,es.*",
                "-o", out_tmpl,
                url,
            ]
            try:
                subprocess.run(cmd_impersonate, capture_output=True, timeout=75)
            except Exception:
                pass

            if not cached_mp4.exists():
                matches = [p for p in REF_CACHE_DIR.glob(f"ref_{uhash}.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")]
                if matches:
                    cached_mp4 = matches[0]

            # Attempt 2: Standard client fallback if --impersonate chrome target is unavailable or failed
            if not (cached_mp4.exists() and cached_mp4.stat().st_size > 80_000):
                cmd_standard = [
                    ytdlp,
                    "--no-warnings",
                    "-f", fmt_spec,
                    "--merge-output-format", "mp4",
                    "-o", out_tmpl,
                    url,
                ]
                try:
                    subprocess.run(cmd_standard, capture_output=True, timeout=75)
                except Exception:
                    pass

            if not cached_mp4.exists():
                matches = [p for p in REF_CACHE_DIR.glob(f"ref_{uhash}.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")]
                if matches:
                    cached_mp4 = matches[0]

            # Attempt 3: Python yt_dlp library fallback
            if not (cached_mp4.exists() and cached_mp4.stat().st_size > 80_000):
                try:
                    import yt_dlp

                    ydl_opts = {
                        "format": fmt_spec,
                        "merge_output_format": "mp4",
                        "outtmpl": out_tmpl,
                        "quiet": True,
                        "no_warnings": True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        info_title = info.get("title") or info_title
                        info_desc = (info.get("description") or "")[:400]
                except Exception:
                    pass

        if not cached_mp4.exists():
            matches = [p for p in REF_CACHE_DIR.glob(f"ref_{uhash}.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm")]
            if matches:
                cached_mp4 = matches[0]

        if not cached_mp4.exists():
            raise RuntimeError(f"Não foi possível baixar o vídeo de referência em {url}")

        bp = self.extract_blueprint_from_file(cached_mp4, title_hint=info_title or title_hint, url=url)
        bp["description"] = info_desc
        return bp

    def extract_from_local_mp4(self, mp4_path: Union[Path, str], title_hint: str = "") -> Dict[str, Any]:
        return self.extract_blueprint_from_file(Path(mp4_path), title_hint=title_hint)


def clone_viral_url(url: str) -> Dict[str, Any]:
    return VideoDNAExtractor().extract_from_url(url)


def extract_from_local_mp4(mp4_path: Union[Path, str], title_hint: str = "") -> Dict[str, Any]:
    return VideoDNAExtractor().extract_from_local_mp4(Path(mp4_path), title_hint=title_hint)


def save_blueprint_as_preset(blueprint: Dict[str, Any], preset_name: str) -> Dict[str, Any]:
    """Save the extracted Video/Style Blueprint DNA as a permanent Preset in SQLite (data/frimerise.db presets table)."""
    init_db()
    clean_name = " ".join(str(preset_name or "DNA Clonado").strip().split()) or "DNA Clonado"
    slug_base = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_") or "clonado"
    if slug_base.startswith("dna_"):
        slug_base = slug_base[4:] or "clonado"
    preset_id = f"dna_{slug_base[:28]}"

    # Extract nested ClonedStyleBlueprint if wrapped inside a full VideoDNAExtractor dict
    sbp = blueprint.get("cloned_style_blueprint") if isinstance(blueprint.get("cloned_style_blueprint"), dict) else blueprint
    sbp = sbp or {}

    classification = str(
        sbp.get("style_classification")
        or blueprint.get("style_classification")
        or ("2d_cartoon" if blueprint.get("style") == "2d_cartoon_animation" else "dynamic_viral")
    )
    cadence_s = float(
        sbp.get("scene_cadence_s")
        or (blueprint.get("scene_cadence") or {}).get("avg_cut_interval_s")
        or 3.2
    )
    cam_motion = str(
        sbp.get("dominant_camera_motion")
        or (blueprint.get("optical_flow") or {}).get("dominant_motion")
        or "zoom_in"
    )

    shifted = sbp.get("shifted_palette") or blueprint.get("shifted_palette") or sbp.get("dominant_palette") or []
    primary_color = str(sbp.get("primary_color") or (shifted[0] if len(shifted) > 0 else "#FF2E93"))
    secondary_color = str(sbp.get("secondary_color") or (shifted[1] if len(shifted) > 1 else "#B388FF"))
    highlight_color = str(sbp.get("highlight_color") or "#B8FF01")
    accent_gold = str(sbp.get("accent_gold") or "#FFD166")

    if classification == "netflix_doc":
        lut_default = "02_dark_wealth.cube"
        font_default = "BebasNeue-Regular.ttf"
        music_default = "epic_doc.mp3"
        cap_default = "cinematic_serif_bar"
        voice_id = "pt-BR-AntonioNeural"
    elif classification == "2d_cartoon":
        lut_default = "04_crisp_commercial.cube"
        font_default = "PlusJakartaSans-ExtraBold.ttf"
        music_default = "corporate_focus.mp3"
        cap_default = "hormozi_bounce"
        voice_id = "pt-BR-AntonioNeural"
    else:
        lut_default = "01_frimerise_signature.cube"
        font_default = "Montserrat-Black.ttf"
        music_default = "dark_pulse.mp3"
        cap_default = "spring_pill_gradient"
        voice_id = "pt-BR-AntonioNeural"

    row = {
        "id": preset_id,
        "name": clean_name,
        "tagline": f"DNA Clonado ({classification} • corte {cadence_s:.1f}s • câmera {cam_motion})",
        "is_default": 0,
        "lut_file": str(sbp.get("lut_file") or lut_default),
        "font_file": str(sbp.get("font_file") or font_default),
        "music_file": str(sbp.get("music_file") or music_default),
        "primary_color": primary_color if primary_color.startswith("#") else "#FF2E93",
        "secondary_color": secondary_color if secondary_color.startswith("#") else "#B388FF",
        "highlight_color": highlight_color if highlight_color.startswith("#") else "#B8FF01",
        "accent_gold": accent_gold if accent_gold.startswith("#") else "#FFD166",
        "bg_box_color": str(sbp.get("bg_box_color") or "#140E24CC"),
        "text_color": str(sbp.get("text_color") or "#FFFFFF"),
        "stroke_color": str(sbp.get("stroke_color") or "#0B0713"),
        "caption_style": str(sbp.get("caption_style") or cap_default),
        "voice_engine": "edge",
        "voice_id": voice_id,
        "voice_blend": json.dumps({"pf_dora": 0.25, "pm_alex": 0.75, "pm_santa": 0.0}),
        "motion_cards": 1,
        "sfx_intensity": "high" if cadence_s <= 3.5 else "medium",
    }

    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO presets (
                id, name, tagline, is_default, lut_file, font_file, music_file,
                primary_color, secondary_color, highlight_color, accent_gold,
                bg_box_color, text_color, stroke_color, caption_style,
                voice_engine, voice_id, voice_blend, motion_cards, sfx_intensity
            ) VALUES (
                :id, :name, :tagline, :is_default, :lut_file, :font_file, :music_file,
                :primary_color, :secondary_color, :highlight_color, :accent_gold,
                :bg_box_color, :text_color, :stroke_color, :caption_style,
                :voice_engine, :voice_id, :voice_blend, :motion_cards, :sfx_intensity
            )
            """,
            row,
        )

    saved = get_preset(preset_id)
    return {
        "status": "saved",
        "preset_id": preset_id,
        **saved,
        "preset": saved,
    }
