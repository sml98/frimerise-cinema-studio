"""FrimeRise Smart Vision & Zero-Key Real Footage Curator (Core i5 Optimized).
Fetches REAL HD video clips with zero API keys required:
  1. Pixabay Video API (instant free key at https://pixabay.com, primary when configured)
  2. Pexels Video API (optional secondary when configured)
  3. yt-dlp Smart Stock Search (ytsearch4:{query} vertical HD creative commons no copyright, --max-filesize 25M)
  4. Wikimedia Commons Open API (filetype:video)
  5. Internet Archive Open API (mediatype:movies, MPEG4)

Every clip is:
  - Deduplicated via SQLite (media_history) & per-video scene set
  - Quality-checked via OpenCV Laplacian variance (blur filter)
  - Smart-cropped to 9:16 (1080x1920) with face centering (MediaPipe / OpenCV)
  - Smoothly animated with jitter-free subpixel zoom + 3D LUT (.cube) + safe_scrim + xfade
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import cv2
import httpx
import numpy as np

from database import is_media_used, mark_media_used
from engine.intel_vaapi import (
    build_video_encode_args,
    run_ffmpeg_safe,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
LUTS_DIR = ASSETS_DIR / "luts"
OVERLAYS_DIR = ASSETS_DIR / "overlays"
CACHE_DIR = BASE_DIR / "data" / "media_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
YTDLP_BIN = BASE_DIR / ".venv" / "bin" / "yt-dlp"

# Negative query terms applied across Pixabay, Wikimedia Commons, and yt-dlp
NEGATIVE_STOCK_TERMS = '-greenscreen -"green screen" -"chroma key" -template -intro'

# Words that usually indicate talking-head/text-heavy/chroma-key videos we should skip
BAD_YT_TITLE_WORDS = (
    "podcast", "interview", "tutorial", "review", "reaction", "lyrics",
    "karaoke", "meme", "news", "commentary", "explains", "subscribe", "shorts compilation",
    "greenscreen", "green screen", "chroma key", "chroma", "template", "intro", "overlay",
)

BAD_TAG_WORDS = (
    "greenscreen", "green screen", "chroma key", "chroma", "template", "intro", "overlay",
)

# Clean fallback stock queries guaranteed to return crisp real HD footage
FALLBACK_STOCK_QUERIES = [
    "city night aerial drone stock footage",
    "modern business office laptop stock footage",
    "neon street night traffic timelapse stock footage",
    "luxury skyscrapers sunset aerial stock footage",
    "technology data center abstract lights stock footage",
    "coffee desk workspace productivity stock footage",
    "ocean waves aerial sunset cinematic stock footage",
    "futuristic city skyline night stock footage",
]


# ---------------------------------------------------------------------------
# 1. Quality & Face Framing Analysis (OpenCV + MediaPipe)
# ---------------------------------------------------------------------------
def compute_blur_score(video_path: Path) -> float:
    """Return median Laplacian variance across sampled frames. Low (<30) = blurry."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30)
    if total < 10:
        cap.release()
        return 0.0
    scores = []
    for frac in (0.15, 0.4, 0.65, 0.85):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * frac))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
    cap.release()
    return float(np.median(scores)) if scores else 0.0


def detect_chroma_key(video_path: Path, green_ratio_limit: float = 0.35) -> Tuple[bool, float]:
    """Sample 3 frames via OpenCV and reject clips where >35% of pixels are pure green
    (G > 200, R < 80, B < 80 in BGR). Returns (is_chroma_key, max_green_ratio).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False, 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30)
    max_ratio = 0.0
    for frac in (0.20, 0.50, 0.80):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * frac))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        # OpenCV uses BGR channel order
        b = frame[:, :, 0]
        g = frame[:, :, 1]
        r = frame[:, :, 2]
        green_mask = (g > 200) & (r < 80) & (b < 80)
        ratio = float(np.mean(green_mask))
        if ratio > max_ratio:
            max_ratio = ratio
    cap.release()
    return (max_ratio > green_ratio_limit), round(max_ratio, 4)


def evaluate_clip_quality(video_path: Path, min_blur: float = 25.0, green_ratio_limit: float = 0.35) -> Dict[str, object]:
    """Run full visual quality gate (Laplacian blur + 3-frame OpenCV chroma-key detector)."""
    blur = round(compute_blur_score(video_path), 1)
    is_chroma, green_ratio = detect_chroma_key(video_path, green_ratio_limit=green_ratio_limit)
    passed = (blur >= min_blur) and (not is_chroma)
    return {
        "passed": passed,
        "blur_score": blur,
        "chroma_key_filter": "active",
        "chroma_key_detected": is_chroma,
        "green_pixel_ratio": green_ratio,
        "reason": "chroma_key_rejected" if is_chroma else ("blur_rejected" if blur < min_blur else "ok"),
    }


def detect_face_center_x(video_path: Path) -> float:
    """Detect dominant horizontal face center (0.0 .. 1.0) using MediaPipe / OpenCV."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.5
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30)
    xs: List[float] = []

    mp_detector = None
    try:
        import mediapipe as mp
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
            mp_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.45
            )
    except Exception:
        mp_detector = None

    cascade = None
    if mp_detector is None:
        xml = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if xml.exists():
            cascade = cv2.CascadeClassifier(str(xml))

    for frac in (0.2, 0.5, 0.8):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * frac))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        h, w = frame.shape[:2]
        if mp_detector is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = mp_detector.process(rgb)
            if res and res.detections:
                box = res.detections[0].location_data.relative_bounding_box
                xs.append(float(np.clip(box.xmin + box.width * 0.5, 0.15, 0.85)))
        elif cascade is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.2, 4)
            if len(faces) > 0:
                fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                xs.append(float(np.clip((fx + fw * 0.5) / max(1, w), 0.15, 0.85)))

    cap.release()
    if mp_detector is not None:
        try:
            mp_detector.close()
        except Exception:
            pass
    return float(np.median(xs)) if xs else 0.5


# ---------------------------------------------------------------------------
# 2. Multi-Source Real Video Searchers
# ---------------------------------------------------------------------------
def _search_pixabay(client: httpx.Client, query: str, api_key: str) -> List[Dict[str, str]]:
    if not api_key:
        return []
    try:
        full_q = f"{query} {NEGATIVE_STOCK_TERMS}"
        r = client.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": full_q, "per_page": 8, "safesearch": "true"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return []
        results = []
        for h in r.json().get("hits", []):
            tags = str(h.get("tags", "")).lower()
            if any(bad in tags for bad in BAD_TAG_WORDS):
                continue
            vids = h.get("videos", {})
            chosen = vids.get("large") or vids.get("medium")
            if chosen and chosen.get("url"):
                results.append({"source": "pixabay", "url": chosen["url"]})
        return results
    except Exception:
        return []


def _search_pexels(client: httpx.Client, query: str, api_key: str) -> List[Dict[str, str]]:
    if not api_key:
        return []
    try:
        r = client.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait", "per_page": 6},
            headers={"Authorization": api_key},
            timeout=10.0,
        )
        if r.status_code != 200:
            return []
        results = []
        for v in r.json().get("videos", []):
            files = sorted(
                [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 720],
                key=lambda x: abs((x.get("height") or 0) - 1920),
            )
            if files:
                results.append({"source": "pexels", "url": files[0]["link"]})
        return results
    except Exception:
        return []


def _search_wikimedia_cc0(client: httpx.Client, query: str) -> List[Dict[str, str]]:
    """Query Wikimedia Commons open video library (zero API key) excluding green screen/templates."""
    try:
        r = client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f"filetype:video {query} {NEGATIVE_STOCK_TERMS}",
                "gsrnamespace": 6,
                "gsrlimit": 6,
                "prop": "videoinfo",
                "viprop": "url|mime|size|width|height",
                "format": "json",
            },
            headers={"User-Agent": "FrimeRiseStudio/2.0 (https://localhost:8000)"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return []
        pages = r.json().get("query", {}).get("pages", {})
        results = []
        for p in pages.values():
            title_l = str(p.get("title", "")).lower()
            if any(bad in title_l for bad in BAD_TAG_WORDS):
                continue
            vinfo = (p.get("videoinfo") or [{}])[0]
            url = vinfo.get("url", "")
            size = int(vinfo.get("size") or 0)
            w = int(vinfo.get("width") or 0)
            h = int(vinfo.get("height") or 0)
            if url and (url.lower().endswith(".webm") or url.lower().endswith(".mp4")) and 200_000 < size < 25_000_000 and max(w, h) >= 640:
                results.append({"source": "wikimedia", "url": url})
        return results
    except Exception:
        return []


def _search_internet_archive(client: httpx.Client, query: str) -> List[Dict[str, str]]:
    """Query Internet Archive open MPEG4 movies (zero API key)."""
    try:
        safe_q = " ".join(w for w in query.split()[:3] if w.isalnum())
        if not safe_q:
            safe_q = "city timelapse"
        r = client.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"mediatype:(movies) AND format:(MPEG4) AND ({safe_q})",
                "fl[]": ["identifier", "title"],
                "rows": 4,
                "output": "json",
            },
            timeout=10.0,
        )
        if r.status_code != 200:
            return []
        docs = r.json().get("response", {}).get("docs", [])
        results = []
        for d in docs[:3]:
            ident = d.get("identifier")
            if not ident:
                continue
            mr = client.get(f"https://archive.org/metadata/{ident}/files", timeout=8.0)
            if mr.status_code != 200:
                continue
            for f in mr.json().get("result", []):
                name = str(f.get("name", ""))
                size = int(f.get("size") or 0)
                if name.lower().endswith(".mp4") and 300_000 < size < 24_000_000:
                    results.append({
                        "source": "archive",
                        "url": f"https://archive.org/download/{ident}/{name}",
                    })
                    break
        return results
    except Exception:
        return []


def _fetch_ytdlp_stock_clip(query: str, exclude_hashes: Set[str]) -> Optional[Path]:
    """Zero-key HD stock footage search via yt-dlp excluding greenscreen/chroma-key/templates.
    Downloads only a clean 5-second middle slice (skipping intros) under 25MB.
    """
    ytdlp = str(YTDLP_BIN) if YTDLP_BIN.exists() else "yt-dlp"
    search_str = f"ytsearch4:{query} vertical HD creative commons no copyright {NEGATIVE_STOCK_TERMS}"
    try:
        probe = subprocess.run(
            [ytdlp, "--flat-playlist", "-J", "--no-warnings", search_str],
            capture_output=True,
            text=True,
            timeout=18,
        )
        if probe.returncode != 0:
            return None
        entries = json.loads(probe.stdout).get("entries") or []
    except Exception:
        return None

    for entry in entries:
        vid_id = entry.get("id")
        title = (entry.get("title") or "").lower()
        dur = float(entry.get("duration") or 0)
        if not vid_id:
            continue
        if any(bad in title for bad in BAD_YT_TITLE_WORDS):
            continue
        if dur and (dur < 4.0 or dur > 240.0):
            continue

        url = f"https://www.youtube.com/watch?v={vid_id}"
        hsh = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        if hsh in exclude_hashes or is_media_used(hsh):
            continue

        out_path = CACHE_DIR / f"ytstock_{hsh}.mp4"
        if out_path.exists() and out_path.stat().st_size > 100_000:
            qrep = evaluate_clip_quality(out_path, min_blur=22.0)
            if qrep["passed"]:
                exclude_hashes.add(hsh)
                mark_media_used(hsh, "yt_stock", query, str(out_path))
                return out_path
            out_path.unlink(missing_ok=True)
            continue

        # Pick a clean 5-second segment starting slightly into the clip (avoids intro logos/fades)
        start_sec = 2 if (not dur or dur >= 8.0) else 0
        end_sec = start_sec + 5
        section = f"*0:{start_sec:02d}-0:{end_sec:02d}"

        try:
            dl_cmd = [
                ytdlp,
                "--no-warnings",
                "--quiet",
                "--max-filesize", "25M",
                "-f", "bestvideo[ext=mp4][height<=1920][height>=480]/best[ext=mp4][height<=1920]/best[height<=1920]",
                "--download-sections", section,
                "--force-keyframes-at-cuts",
                "--merge-output-format", "mp4",
                "-o", str(out_path),
                url,
            ]
            subprocess.run(dl_cmd, capture_output=True, timeout=35)
            # yt-dlp sometimes appends extension
            if not out_path.exists():
                matches = list(CACHE_DIR.glob(f"ytstock_{hsh}.*"))
                if matches:
                    out_path = matches[0]
            if out_path.exists() and out_path.stat().st_size > 80_000:
                qrep = evaluate_clip_quality(out_path, min_blur=22.0)
                if qrep["passed"]:
                    exclude_hashes.add(hsh)
                    mark_media_used(hsh, "yt_stock", query, str(out_path))
                    print(
                        f"[SmartVision] Clipe real aprovado (yt-dlp): {out_path.name} | "
                        f"blur={qrep['blur_score']} | green={qrep['green_pixel_ratio']:.1%} | "
                        f"chroma_key_filter={qrep['chroma_key_filter']}",
                        flush=True,
                    )
                    return out_path
                print(f"[SmartVision] Descartado ({qrep['reason']}, green={qrep['green_pixel_ratio']:.1%}): {out_path.name}", flush=True)
                out_path.unlink(missing_ok=True)
        except Exception:
            out_path.unlink(missing_ok=True)
            continue
    return None


def _download_http_candidates(
    client: httpx.Client,
    candidates: List[Dict[str, str]],
    query: str,
    exclude_hashes: Set[str],
) -> Optional[Path]:
    for item in candidates:
        url = item["url"]
        hsh = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        if hsh in exclude_hashes or is_media_used(hsh):
            continue
        ext = ".webm" if ".webm" in url.lower() else ".mp4"
        local_path = CACHE_DIR / f"{item['source']}_{hsh}{ext}"
        try:
            if not local_path.exists():
                resp = client.get(url, timeout=22.0)
                if resp.status_code != 200 or len(resp.content) < 80_000:
                    continue
                local_path.write_bytes(resp.content)
            qrep = evaluate_clip_quality(local_path, min_blur=25.0)
            if not qrep["passed"]:
                print(
                    f"[SmartVision] Descartado ({qrep['reason']}, blur={qrep['blur_score']}, "
                    f"green={qrep['green_pixel_ratio']:.1%}): {local_path.name}",
                    flush=True,
                )
                local_path.unlink(missing_ok=True)
                continue
            exclude_hashes.add(hsh)
            mark_media_used(hsh, item["source"], query, str(local_path))
            print(
                f"[SmartVision] Clipe real aprovado ({item['source']}): {local_path.name} | "
                f"blur={qrep['blur_score']} | green={qrep['green_pixel_ratio']:.1%} | "
                f"chroma_key_filter={qrep['chroma_key_filter']}",
                flush=True,
            )
            return local_path
        except Exception:
            local_path.unlink(missing_ok=True)
            continue
    return None


def fetch_unique_real_clip(
    query: str,
    pixabay_key: str = "",
    pexels_key: str = "",
    exclude_hashes: Optional[Set[str]] = None,
    scene_index: int = 0,
) -> Path:
    """Guarantee a REAL, unique, crisp HD video clip using Pixabay -> Pexels -> yt-dlp -> Wikimedia -> Internet Archive."""
    used = exclude_hashes if exclude_hashes is not None else set()
    queries_to_try = [query, FALLBACK_STOCK_QUERIES[scene_index % len(FALLBACK_STOCK_QUERIES)]]

    with httpx.Client(follow_redirects=True, timeout=18.0) as client:
        for q in queries_to_try:
            # 1. Pixabay (instant-approval API key)
            if pixabay_key:
                clip = _download_http_candidates(client, _search_pixabay(client, q, pixabay_key), q, used)
                if clip:
                    return clip

            # 2. Pexels (optional secondary API key)
            if pexels_key:
                clip = _download_http_candidates(client, _search_pexels(client, q, pexels_key), q, used)
                if clip:
                    return clip

            # 3. Zero-key yt-dlp stock footage (fast, clean 5s HD Creative Commons / No Copyright clips)
            clip = _fetch_ytdlp_stock_clip(q, used)
            if clip:
                return clip

            # 4. Zero-key Wikimedia Commons open video API
            clip = _download_http_candidates(client, _search_wikimedia_cc0(client, q), q, used)
            if clip:
                return clip

            # 5. Zero-key Internet Archive open MPEG4 API
            clip = _download_http_candidates(client, _search_internet_archive(client, q), q, used)
            if clip:
                return clip

    # Last-resort reuse of an already-cached REAL downloaded video clip (distinct from scenes already used)
    cached_reals = sorted(
        [p for p in CACHE_DIR.glob("*") if p.suffix.lower() in (".mp4", ".webm") and p.stat().st_size > 100_000],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in cached_reals:
        tag = p.stem.split("_")[-1]
        if tag not in used:
            if evaluate_clip_quality(p, min_blur=20.0)["passed"]:
                used.add(tag)
                return p
            p.unlink(missing_ok=True)
    if cached_reals:
        for p in cached_reals:
            if p.exists() and evaluate_clip_quality(p, min_blur=20.0)["passed"]:
                return p

    raise RuntimeError(f"Não foi possível baixar filmagem real para '{query}' (verifique conexão com a internet).")


# ---------------------------------------------------------------------------
# 3. Smart Crop 9:16 + Subpixel Zoom + 3D LUT + Safe Scrim + xfade Assembly
# ---------------------------------------------------------------------------
def prepare_styled_scene(
    raw_clip: Path,
    out_mp4: Path,
    duration_s: float,
    lut_file: str,
    scene_index: int = 0,
    fps: int = 30,
) -> Path:
    """Apply face-centered 9:16 Smart Crop + jitter-free subpixel Ken Burns zoom
    (1.25x supersampled 1350x2400 -> smooth floating crop -> lanczos 1080x1920)
    + 3D LUT (.cube) + subtle vignette + lower-third safe_scrim.
    """
    face_x = detect_face_center_x(raw_clip)
    lut_path = LUTS_DIR / lut_file
    vignette_path = OVERLAYS_DIR / "vignette_9x16.png"
    scrim_path = OVERLAYS_DIR / "safe_scrim.png"

    # Supersample to 1350x2400 (fast on Core i5, zero zoompan jitter), smoothly pan/zoom into 1188x2112 -> lanczos 1080x1920
    direction = 1 if scene_index % 2 == 0 else -1
    safe_dur = max(1.0, float(duration_s))
    cx_expr = f"clip((iw-1350)*{face_x:.3f},0,max(0,iw-1350))"
    drift_x = f"(1350-1188)/2+({direction})*38*(t/{safe_dur:.2f})"
    drift_y = f"(2400-2112)/2+44*(t/{safe_dur:.2f})"

    vf_chain = [
        f"fps={fps}",
        "scale=1350:2400:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop=w=1350:h=2400:x='{cx_expr}':y='(ih-2400)/2'",
        f"crop=w=1188:h=2112:x='{drift_x}':y='{drift_y}'",
        "scale=1080:1920:flags=lanczos",
    ]
    if lut_path.exists():
        esc_lut = str(lut_path).replace("\\", "/").replace(":", "\\:")
        vf_chain.append(f"lut3d=file='{esc_lut}'")

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    inputs = ["-stream_loop", "-1", "-i", str(raw_clip)]
    filter_parts = [f"[0:v]{','.join(vf_chain)}[base]"]
    cur = "[base]"
    idx = 1
    if vignette_path.exists():
        inputs.extend(["-i", str(vignette_path)])
        filter_parts.append(f"{cur}[{idx}:v]overlay=0:0[v1]")
        cur = "[v1]"
        idx += 1
    if scrim_path.exists():
        inputs.extend(["-i", str(scrim_path)])
        filter_parts.append(f"{cur}[{idx}:v]overlay=0:0[v2]")
        cur = "[v2]"
        idx += 1

    filter_parts.append(f"{cur}{hw_suffix}[vout]")

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
        "-t",
        f"{duration_s:.3f}",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd)
    return out_mp4


def assemble_scenes_with_xfade(
    scene_paths: List[Path],
    scene_durations: List[float],
    out_mp4: Path,
    xfade_dur: float = 0.30,
) -> Tuple[Path, List[float]]:
    """Stitch prepared 1080x1920 real footage scenes with smooth FFmpeg xfade transitions."""
    if len(scene_paths) == 1:
        if scene_paths[0] != out_mp4:
            run_ffmpeg_safe(["ffmpeg", "-y", "-v", "error", "-i", str(scene_paths[0]), "-c", "copy", str(out_mp4)])
        return out_mp4, []

    transitions = ["fade", "wipeleft", "smoothup", "slideright", "smoothleft", "dissolve"]
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)

    inputs = []
    for p in scene_paths:
        inputs.extend(["-i", str(p)])

    filter_parts = []
    transition_times: List[float] = []
    prev_label = "[0:v]"
    offset = scene_durations[0] - xfade_dur

    for i in range(1, len(scene_paths)):
        tr = transitions[(i - 1) % len(transitions)]
        out_lbl = f"[xf{i}]"
        safe_offset = max(0.2, offset)
        transition_times.append(round(safe_offset, 3))
        filter_parts.append(
            f"{prev_label}[{i}:v]xfade=transition={tr}:duration={xfade_dur:.2f}:offset={safe_offset:.3f}{out_lbl}"
        )
        prev_label = out_lbl
        offset = safe_offset + scene_durations[i] - xfade_dur

    filter_parts.append(f"{prev_label}{hw_suffix}[vout]")

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd)
    return out_mp4, transition_times
