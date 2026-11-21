"""FrimeRise Documentary Real Media Engine (Photos, 2.5D u2netp Cutouts, HD B-Roll & VideoLayerReader).

100% permissive licenses & Acer Aspire 5 (Core i5) CPU-friendly:
  1. Multi-Source Real Archival / Editorial Photo Fetcher (`fetch_doc_real_photo`):
     - Persistent query/URL cache in `data/doc_photo_cache/`
     - Priority order:
       a) Pixabay Photo API (using live `pixabay_api_key` from `database.get_settings()`)
       b) Wikimedia Commons Search API (historical & editorial photography)
       c) Pollinations Flux fallback (`https://image.pollinations.ai/prompt/...`)
       d) Curated real documentary query fallback + local validated photo cache
     - Every image validated via `cv2.imread` (non-None, width >= 320, height >= 200,
       non-blank variance, and not chroma-key green).
  2. Skia Image Helpers:
     - `load_skia_image_cover(img_path, target_w, target_h) -> Optional[skia.Image]`
       Center-crops (aspect-cover, zero distortion) and converts BGR -> BGRA `skia.Image`.
     - `separate_photo_25d_u2netp(img_path, target_w, target_h) -> (bg_inpainted, fg_cutout)`
       Genuine 2.5D foreground/background separation via `~/.u2net/u2netp.onnx` (ONNXRuntime)
       + sharp background hole-filling via `cv2.inpaint` (TELEA).
  3. Real HD Video B-Roll Fetcher (`fetch_doc_broll_clip`):
     - Fast HD-sized Pixabay landscape/portrait video selection + full multi-source fallback via
       `engine.smart_vision.fetch_unique_real_clip` (Pixabay -> Pexels -> yt-dlp -> Wikimedia ->
       Internet Archive) with OpenCV >30% chroma-key green & Laplacian blur quality gates.
     - Automatically retries curated cinematic documentary queries if a niche query misses.
  4. Lightweight Sequential Frame Streamer (`VideoLayerReader`):
     - Pre-opens `cv2.VideoCapture` with `cv2.setNumThreads(1)`
     - Seamless EOF looping, precomputed aspect-cover center-crop, fast uint8 LUT darkening,
       and zero-copy-ready `skia.Image` (`kBGRA_8888_ColorType`) output.
     - Designed to stream BOTH full-HD 1920x1080 background video AND simultaneous
       Video-over-Video (PiP) windows with minimal CPU/RAM overhead.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import quote

import cv2
import httpx
import numpy as np
import skia

from database import get_settings, record_token_usage
from engine.smart_vision import (
    BAD_TAG_WORDS,
    CACHE_DIR as SMART_VISION_CACHE_DIR,
    build_clean_search_query,
    evaluate_clip_quality,
    fetch_unique_real_clip,
    has_chroma_key_green,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOC_PHOTO_CACHE_DIR = DATA_DIR / "doc_photo_cache"
DOC_BROLL_CACHE_DIR = DATA_DIR / "doc_broll_cache"
DOC_PHOTO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DOC_BROLL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

WIKIMEDIA_USER_AGENT = "FrimeRiseDocEngine/2.0 (https://frimerise.local; documentary-media)"

PHOTO_BAD_WORDS = (
    "greenscreen",
    "green screen",
    "chroma key",
    "chroma",
    "template",
    "mockup",
    "mock-up",
    "transparent background",
    "clipart",
    "vector",
    "icon",
    "logo",
    "coat_of_arms",
    "flag_of",
    "signature",
    "blank_map",
    "diagram",
    "svg",
)

STOP_WORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "with",
    "by", "and", "or", "as", "is", "was", "were", "into", "over", "under",
    "de", "da", "do", "dos", "das", "em", "no", "na", "e", "o", "os", "as",
}

CURATED_DOC_BROLL_QUERIES: List[str] = [
    "city skyline night aerial",
    "stock market trading screen",
    "modern skyscraper architecture",
    "money bills dark finance",
    "office executive business",
    "newspaper printing press",
]

CURATED_DOC_PHOTO_QUERIES: List[str] = [
    "london financial district skyline",
    "stock market trading floor",
    "modern skyscraper architecture night",
    "historic bank building architecture",
    "corporate boardroom office",
    "money bills finance dark",
]

MOOD_DOC_BROLL_QUERIES: Dict[str, List[str]] = {
    "dark_horror": [
        "snow forest night",
        "candle flame dark",
        "medieval castle fog",
        "gothic cathedral dark",
        "fireplace burning dark",
        "winter snow village",
    ],
    "investigative_crime": [
        "rainy city street night",
        "dark alley fog night",
        "police lights night",
        "courthouse building architecture",
        "old library archive dark",
        "newspaper printing press",
    ],
    "epic_history": [
        "ancient roman ruins",
        "medieval castle fog",
        "gothic cathedral dark",
        "candle flame dark",
        "historic european village",
        "old book library candle",
    ],
    "corporate_thriller": list(CURATED_DOC_BROLL_QUERIES),
}

MOOD_DOC_PHOTO_QUERIES: Dict[str, List[str]] = {
    "dark_horror": [
        "dark snowy pine forest winter night",
        "burning candle dark shadow",
        "gothic cathedral candle",
        "medieval winter village snow night",
        "old parchment leather book candle",
        "foggy forest winter dark",
    ],
    "investigative_crime": [
        "rainy city street night noir",
        "historic courthouse building",
        "old archive files library",
        "dark foggy alley night",
        "vintage detective desk lamp",
        "newspaper archive vintage",
    ],
    "epic_history": [
        "ancient roman ruins colosseum",
        "medieval stone castle europe",
        "gothic cathedral interior candle",
        "old parchment manuscript book",
        "ancient marble statue museum",
        "historic european architecture",
    ],
    "corporate_thriller": list(CURATED_DOC_PHOTO_QUERIES),
}

GEMINI_IMAGE_MODELS: Tuple[str, ...] = (
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
)

_BESPOKE_HISTORY_FOLKLORE_RE = re.compile(
    r"\b("
    r"krampus|saturnalia|pagan|ritual|folklore|demon|devil|witch|macabre|"
    r"solstice|yule|inquisition|plague|pharaoh|viking|sacrifice|occult|"
    r"monster|haunted|ghost|cursed|gryla|perchta|vampire|nosferatu|"
    r"exorcism|catacomb|alchemist|myth|ancient\s+rome|medieval\s+demon|"
    r"dark\s+christmas|winter\s+demon|horned\s+creature|secret\s+society"
    r")\b",
    re.IGNORECASE,
)

_DARK_HORROR_HINT_RE = re.compile(
    r"\b("
    r"krampus|saturnalia|christmas|natal|horror|macabre|macabr|dark|snow|winter|"
    r"candle|gothic|cathedral|fog|ghost|witch|demon|ritual|pagan|folklore|"
    r"creepy|haunted|skull|cemetery|fireplace|shadow|curse|vampire|nightmare|"
    r"medieval|forest|dungeon|crypt|tomb"
    r")\b",
    re.IGNORECASE,
)

_HISTORY_HINT_RE = re.compile(
    r"\b("
    r"ancient|roman|rome|egypt|greek|medieval|castle|empire|war|battle|"
    r"century|parchment|manuscript|temple|ruins|historic|museum|painting|"
    r"engraving|artifact|viking|samurai|pharaoh"
    r")\b",
    re.IGNORECASE,
)

_CRIME_HINT_RE = re.compile(
    r"\b("
    r"crime|murder|killer|detective|police|fbi|prison|trial|courthouse|"
    r"forensic|mystery|conspiracy|mafia|cartel|heist|suspect|evidence"
    r")\b",
    re.IGNORECASE,
)

_GEMINI_IMAGE_QUOTA_EXHAUSTED: bool = False
_U2NETP_SESSION = None


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------
def _safe_tag(tag: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tag or "media")).strip("_")
    return (cleaned or "media")[:32]


def _normalize_query(query: str, default: str) -> str:
    q = " ".join(str(query or "").strip().split())
    return q if q else default


def _shorten_query(query: str, max_words: int = 3) -> str:
    words = [
        re.sub(r"[^a-zA-Z0-9-]", "", w)
        for w in query.split()
    ]
    informative = [w for w in words if len(w) >= 3 and w.lower() not in STOP_WORDS]
    if not informative:
        informative = [w for w in words if w]
    return " ".join(informative[:max_words]).strip()


def _infer_media_mood(query: str, explicit_mood: str = "") -> str:
    m = str(explicit_mood or "").strip().lower()
    if m in MOOD_DOC_PHOTO_QUERIES:
        return m
    q = str(query or "")
    if _DARK_HORROR_HINT_RE.search(q):
        return "dark_horror"
    if _CRIME_HINT_RE.search(q):
        return "investigative_crime"
    if _HISTORY_HINT_RE.search(q):
        return "epic_history"
    return "corporate_thriller"


def _read_api_keys() -> Tuple[str, str]:
    try:
        settings = get_settings() or {}
        return (
            str(settings.get("pixabay_api_key") or "").strip(),
            str(settings.get("pexels_api_key") or "").strip(),
        )
    except Exception:
        return "", ""


def _read_gemini_api_key() -> str:
    try:
        settings = get_settings() or {}
        return str(settings.get("gemini_api_key") or "").strip()
    except Exception:
        return ""


def _center_crop_resize_bgr(
    bgr: np.ndarray,
    target_w: int,
    target_h: int,
    high_quality: bool = True,
) -> np.ndarray:
    """Aspect-cover center-crop and resize BGR image to exact (target_w, target_h) with zero distortion."""
    src_h, src_w = bgr.shape[:2]
    tw = max(1, int(target_w))
    th = max(1, int(target_h))

    src_ar = src_w / max(1.0, float(src_h))
    dst_ar = tw / max(1.0, float(th))

    if src_ar > dst_ar:
        crop_w = max(1, min(src_w, int(round(src_h * dst_ar))))
        x0 = (src_w - crop_w) // 2
        cropped = bgr[:, x0 : x0 + crop_w]
    elif src_ar < dst_ar:
        crop_h = max(1, min(src_h, int(round(src_w / dst_ar))))
        y0 = (src_h - crop_h) // 2
        cropped = bgr[y0 : y0 + crop_h, :]
    else:
        cropped = bgr

    ch, cw = cropped.shape[:2]
    if cw == tw and ch == th:
        return np.ascontiguousarray(cropped)

    if cw > tw or ch > th:
        interp = cv2.INTER_AREA if (high_quality or cw > tw * 2.0 or ch > th * 2.0) else cv2.INTER_LINEAR
    else:
        interp = cv2.INTER_LANCZOS4 if high_quality else cv2.INTER_LINEAR
    return cv2.resize(cropped, (tw, th), interpolation=interp)


def _validate_photo_bgr(bgr: Optional[np.ndarray], min_width: int = 320, min_height: int = 200) -> bool:
    """Validate decoded photo: non-None, min dimensions, non-blank, not chroma-key green."""
    if bgr is None or bgr.size == 0 or bgr.ndim < 3:
        return False
    h, w = bgr.shape[:2]
    if w < max(320, int(min_width)) or h < max(200, int(min_height)):
        return False
    if has_chroma_key_green(bgr):
        return False
    # Reject completely flat / corrupt single-color images
    if float(np.std(bgr)) < 8.0:
        return False
    return True


def _validate_photo_file(path: Path, min_width: int = 320, min_height: int = 200) -> Tuple[bool, int, int]:
    """Validate an image file on disk using cv2.imread."""
    if not path.exists() or path.stat().st_size < 4_000:
        return False, 0, 0
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if not _validate_photo_bgr(bgr, min_width=min_width, min_height=min_height):
        return False, 0, 0
    h, w = bgr.shape[:2]
    return True, w, h


def _materialize_photo_in_work_dir(cached_path: Path, work_dir: Optional[Union[Path, str]], tag: str, hsh: str) -> Path:
    if work_dir is None:
        return cached_path
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    ext = cached_path.suffix.lower() if cached_path.suffix else ".jpg"
    dest = wd / f"photo_{_safe_tag(tag)}_{hsh}{ext}"
    if dest.resolve() == cached_path.resolve():
        return cached_path
    try:
        shutil.copy2(cached_path, dest)
        return dest
    except Exception:
        return cached_path


def _materialize_video_in_work_dir(cached_path: Path, work_dir: Optional[Union[Path, str]], tag: str, hsh: str) -> Path:
    """Expose a clean .mp4 path inside work_dir (zero-copy symlink for .mp4, fast transcode only if .webm)."""
    if work_dir is None:
        return cached_path
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)

    source_mp4 = cached_path
    if cached_path.suffix.lower() != ".mp4":
        converted = DOC_BROLL_CACHE_DIR / f"{cached_path.stem}.mp4"
        if not converted.exists() or converted.stat().st_size < 50_000:
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-v", "error",
                        "-i", str(cached_path),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                        "-pix_fmt", "yuv420p", "-an",
                        str(converted),
                    ],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
            except Exception:
                converted.unlink(missing_ok=True)
        if converted.exists() and converted.stat().st_size > 50_000:
            source_mp4 = converted

    dest = wd / f"broll_{_safe_tag(tag)}_{hsh}.mp4"
    if dest.exists() or dest.is_symlink():
        try:
            if dest.resolve() == source_mp4.resolve():
                return dest
            dest.unlink(missing_ok=True)
        except Exception:
            pass
    try:
        os.symlink(source_mp4.resolve(), dest)
        return dest
    except Exception:
        try:
            shutil.copy2(source_mp4, dest)
            return dest
        except Exception:
            return source_mp4


# ---------------------------------------------------------------------------
# 1. Real Multi-Source Archival / Editorial Photo Fetcher
# ---------------------------------------------------------------------------
def _load_photo_query_index(q_hash: str) -> List[Dict[str, Any]]:
    idx_path = DOC_PHOTO_CACHE_DIR / f"idx_{q_hash}.json"
    if not idx_path.exists():
        return []
    try:
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_photo_query_index(q_hash: str, entries: List[Dict[str, Any]]) -> None:
    idx_path = DOC_PHOTO_CACHE_DIR / f"idx_{q_hash}.json"
    try:
        idx_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _search_pixabay_photos(
    client: httpx.Client,
    query: str,
    api_key: str,
    min_width: int = 640,
) -> List[Dict[str, str]]:
    if not api_key:
        return []
    results: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()

    queries_to_try = [query]
    short_q = _shorten_query(query, max_words=3)
    if short_q and short_q.lower() != query.lower():
        queries_to_try.append(short_q)

    for q in queries_to_try:
        try:
            r = client.get(
                "https://pixabay.com/api/",
                params={
                    "key": api_key,
                    "q": q,
                    "image_type": "photo",
                    "orientation": "horizontal",
                    "per_page": 8,
                    "safesearch": "true",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                continue
            for hit in r.json().get("hits", []):
                tags = str(hit.get("tags") or "").lower()
                if any(bad in tags for bad in PHOTO_BAD_WORDS):
                    continue
                img_w = int(hit.get("imageWidth") or hit.get("webformatWidth") or 0)
                img_h = int(hit.get("imageHeight") or hit.get("webformatHeight") or 0)
                if img_w and img_w < max(320, min_width):
                    continue
                if img_h and img_h < 200:
                    continue
                url = str(hit.get("largeImageURL") or hit.get("webformatURL") or "").strip()
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({"source": "pixabay_photo", "url": url})
            if results:
                break
        except Exception:
            continue
    return results


def _search_wikimedia_photos(
    client: httpx.Client,
    query: str,
    min_width: int = 640,
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()

    queries_to_try = [query]
    short_q = _shorten_query(query, max_words=3)
    if short_q and short_q.lower() != query.lower():
        queries_to_try.append(short_q)

    allowed_mimes = {"image/jpeg", "image/png", "image/webp"}
    for q in queries_to_try:
        try:
            r = client.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrsearch": q,
                    "gsrlimit": 6,
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime",
                    "iiurlwidth": 1280,
                    "format": "json",
                },
                headers={"User-Agent": WIKIMEDIA_USER_AGENT},
                timeout=10.0,
            )
            if r.status_code != 200:
                continue
            pages = r.json().get("query", {}).get("pages", {})
            for page in pages.values():
                title_l = str(page.get("title") or "").lower()
                if any(bad in title_l for bad in PHOTO_BAD_WORDS):
                    continue
                ii = (page.get("imageinfo") or [{}])[0]
                mime = str(ii.get("mime") or "").lower()
                if mime not in allowed_mimes:
                    continue
                w = int(ii.get("thumbwidth") or ii.get("width") or 0)
                h = int(ii.get("thumbheight") or ii.get("height") or 0)
                size = int(ii.get("size") or 0)
                if w < 320 or h < 200:
                    continue
                ar = w / max(1.0, float(h))
                if ar < 0.45 or ar > 3.2:
                    continue
                # Prefer Wikimedia's pre-scaled 1280px thumburl to keep bandwidth & CPU low
                url = str(ii.get("thumburl") or "").strip()
                if not url and size < 12_000_000:
                    url = str(ii.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                # Sort high-res candidates ahead of narrow archival scans
                priority = 0 if w >= min_width else 1
                seen_urls.add(url)
                results.append({"source": "wikimedia_photo", "url": url, "priority": str(priority)})
            if results:
                break
        except Exception:
            continue

    results.sort(key=lambda item: int(item.get("priority", "0")))
    return results


def _download_and_validate_photo(
    client: httpx.Client,
    url: str,
    source: str,
    q_hash: str,
    min_width: int = 320,
    timeout: float = 16.0,
) -> Optional[Tuple[Path, int, int]]:
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    cached_jpg = DOC_PHOTO_CACHE_DIR / f"photo_{q_hash}_{url_hash}.jpg"

    if cached_jpg.exists():
        ok, w, h = _validate_photo_file(cached_jpg, min_width=min_width)
        if ok:
            return cached_jpg, w, h
        cached_jpg.unlink(missing_ok=True)

    headers = {"User-Agent": WIKIMEDIA_USER_AGENT} if "wikimedia" in url.lower() else {}
    try:
        resp = client.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 4_000:
            return None
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "text/html" in ctype or "application/json" in ctype or "svg" in ctype:
            return None

        arr = np.frombuffer(resp.content, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if not _validate_photo_bgr(bgr, min_width=min_width, min_height=200):
            return None

        # Normalize to clean high-quality JPEG so cv2.imread & Skia always decode reliably
        if bgr.shape[1] > 1920:
            scale = 1920.0 / float(bgr.shape[1])
            bgr = cv2.resize(
                bgr,
                (1920, max(200, int(round(bgr.shape[0] * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        cv2.imwrite(str(cached_jpg), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        ok, w, h = _validate_photo_file(cached_jpg, min_width=min_width)
        if not ok:
            cached_jpg.unlink(missing_ok=True)
            return None
        return cached_jpg, w, h
    except Exception:
        cached_jpg.unlink(missing_ok=True)
        return None


def _build_gemini_cinema_prompt(prompt_en: str, mood: str = "dark_horror") -> str:
    """Wrap a documentary scene prompt in strict zero-text photographic dark-cinema art direction."""
    mood_style = {
        "dark_horror": (
            "dark cinematic documentary film still, moody chiaroscuro candlelight and cold moonlight, "
            "atmospheric winter mist, photorealistic 35mm cinema photography, shallow depth of field, "
            "A24 and Netflix dark history documentary aesthetic"
        ),
        "investigative_crime": (
            "gritty investigative documentary film still, nocturnal noir lighting, rainy reflections, "
            "photorealistic 35mm editorial photography, tense true-crime cinema mood"
        ),
        "epic_history": (
            "authentic historical documentary archival photograph or museum-grade dramatic chiaroscuro scene, "
            "35mm cinema lens, rich natural textures, historical realism"
        ),
        "corporate_thriller": (
            "sleek high-contrast financial thriller documentary still, obsidian architectural lighting, "
            "35mm cinema lens, sharp editorial photorealism"
        ),
    }.get(mood, "photorealistic 35mm dark cinema documentary still, dramatic chiaroscuro lighting")
    return (
        f"{prompt_en.strip()}. {mood_style}. "
        "CRITICAL: Absolutely ZERO text, ZERO words, ZERO letters, ZERO captions, ZERO watermarks, "
        "ZERO logos, ZERO borders or picture frames. Full-bleed edge-to-edge photographic frame."
    )


def generate_doc_gemini_image(
    prompt_en: str,
    work_dir: Optional[Union[Path, str]] = None,
    tag: str = "gemini_doc",
    mood: str = "dark_horror",
    aspect_ratio: str = "16:9",
    min_width: int = 640,
    used_urls: Optional[Set[str]] = None,
) -> Optional[Path]:
    """Generate a bespoke, zero-text dark-cinema documentary photograph via Google Gemini Native Image API.

    Uses the user's LIVE `gemini_api_key` (`AQ.` or `AIza...` via `headers={"x-goog-api-key": key}`)
    targeting `gemini-2.5-flash-image` / `gemini-3.1-flash-image` with persistent disk caching in
    `data/doc_photo_cache/`. Returns None cleanly (without crashing) if key is missing or quota-limited.
    """
    global _GEMINI_IMAGE_QUOTA_EXHAUSTED
    clean_prompt = _normalize_query(prompt_en, "")
    if not clean_prompt:
        return None

    resolved_mood = _infer_media_mood(clean_prompt, mood)
    ar_clean = "9:16" if str(aspect_ratio or "16:9").strip() == "9:16" else "16:9"
    p_key = f"gemini://{resolved_mood}/{ar_clean}/{clean_prompt.lower()}"
    p_hash = hashlib.sha256(p_key.encode("utf-8")).hexdigest()[:16]
    cached_jpg = DOC_PHOTO_CACHE_DIR / f"gemini_{p_hash}.jpg"
    used = used_urls if used_urls is not None else set()

    # 1. Persistent cache hit (zero API calls, works even if quota is temporarily throttled!)
    if cached_jpg.exists() and p_key not in used:
        ok, _, _ = _validate_photo_file(cached_jpg, min_width=min(min_width, 320))
        if ok:
            used.add(p_key)
            return _materialize_photo_in_work_dir(cached_jpg, work_dir, tag, p_hash)
        cached_jpg.unlink(missing_ok=True)

    if _GEMINI_IMAGE_QUOTA_EXHAUSTED:
        return None

    gkey = _read_gemini_api_key()
    if not gkey:
        return None

    full_prompt = _build_gemini_cinema_prompt(clean_prompt, mood=resolved_mood)
    headers = {"Content-Type": "application/json", "x-goog-api-key": gkey}
    quota_hits = 0

    with httpx.Client(follow_redirects=True, timeout=36.0) as client:
        for model_id in GEMINI_IMAGE_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
            payloads = [
                {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": ar_clean},
                    },
                },
                {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"responseModalities": ["IMAGE"]},
                },
            ]
            for p_idx, payload in enumerate(payloads):
                try:
                    resp = client.post(url, json=payload, headers=headers, timeout=36.0)
                    if resp.status_code == 429:
                        quota_hits += 1
                        break
                    if resp.status_code == 400 and p_idx == 0:
                        continue
                    if resp.status_code != 200:
                        break

                    j = resp.json()
                    parts = j.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    img_b64 = ""
                    for part in parts:
                        idata = part.get("inlineData") or part.get("inline_data")
                        if idata and idata.get("data"):
                            img_b64 = str(idata["data"])
                            break
                    if not img_b64:
                        break

                    raw_bytes = base64.b64decode(img_b64)
                    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
                    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if not _validate_photo_bgr(bgr, min_width=min(min_width, 320), min_height=200):
                        break

                    if bgr.shape[1] > 1920:
                        scale = 1920.0 / float(bgr.shape[1])
                        bgr = cv2.resize(
                            bgr,
                            (1920, max(200, int(round(bgr.shape[0] * scale)))),
                            interpolation=cv2.INTER_AREA,
                        )
                    cv2.imwrite(str(cached_jpg), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                    ok, w, h = _validate_photo_file(cached_jpg, min_width=min(min_width, 320))
                    if not ok:
                        cached_jpg.unlink(missing_ok=True)
                        break

                    try:
                        meta = j.get("usageMetadata", {})
                        pt = int(meta.get("promptTokenCount", 80))
                        ct = int(meta.get("candidatesTokenCount", 256))
                        record_token_usage("gemini-image", model_id, pt, ct, 0, 0.002)
                    except Exception:
                        pass

                    used.add(p_key)
                    q_hash = hashlib.sha256(clean_prompt.lower().encode("utf-8")).hexdigest()[:16]
                    entries = _load_photo_query_index(q_hash)
                    if not any(e.get("url") == p_key for e in entries):
                        entries.insert(0, {
                            "url": p_key,
                            "file": cached_jpg.name,
                            "source": f"gemini_image:{model_id}",
                            "width": w,
                            "height": h,
                            "query": clean_prompt,
                            "mood": resolved_mood,
                        })
                        _save_photo_query_index(q_hash, entries)

                    print(
                        f"[DocMedia] Bespoke Gemini photo ready ({model_id}): {cached_jpg.name} ({w}x{h}) | q='{clean_prompt[:55]}'",
                        flush=True,
                    )
                    return _materialize_photo_in_work_dir(cached_jpg, work_dir, tag, p_hash)
                except Exception:
                    break

    if quota_hits >= len(GEMINI_IMAGE_MODELS):
        _GEMINI_IMAGE_QUOTA_EXHAUSTED = True
        print("[DocMedia] Gemini Image API quota currently throttled (429) — seamlessly blending Pixabay & Wikimedia archival photos.", flush=True)
    return None


def _fetch_pollinations_photo(
    client: httpx.Client,
    query: str,
    q_hash: str,
    used_urls: Set[str],
    min_width: int = 640,
    mood: str = "",
) -> Optional[Tuple[Path, str, int, int]]:
    seed = int(q_hash[:8], 16) % 99999
    if used_urls:
        seed = (seed + len(used_urls) * 37) % 99999
    style_hint = {
        "dark_horror": "dark atmospheric 35mm cinema still, chiaroscuro candlelight, moody horror history documentary, no text",
        "epic_history": "authentic historical documentary photograph, archival 35mm film grain, museum lighting, no text",
        "investigative_crime": "gritty nocturnal investigative documentary photograph, 35mm noir cinema lighting, no text",
    }.get(mood, "editorial documentary photograph, 35mm film photography, realistic natural lighting, sharp focus, no text")
    prompt = f"{query}, {style_hint}"
    url = (
        f"https://image.pollinations.ai/prompt/{quote(prompt)}"
        f"?width=1280&height=720&model=flux&nologo=true&seed={seed}"
    )
    if url in used_urls:
        return None
    dl = _download_and_validate_photo(
        client,
        url,
        source="pollinations_flux",
        q_hash=q_hash,
        min_width=min(min_width, 640),
        timeout=18.0,
    )
    if dl is None:
        return None
    path, w, h = dl
    return path, url, w, h


def fetch_doc_hero_or_archival_photo(
    query: str,
    work_dir: Path,
    tag: str,
    min_width: int = 640,
    used_urls: Optional[Set[str]] = None,
    mood: str = "",
    prefer_gemini: bool = False,
    aspect_ratio: str = "16:9",
    bespoke_prompt_en: str = "",
) -> Optional[Path]:
    """Fetch a bespoke Gemini dark-cinema hero photo OR real archival Pixabay / Wikimedia photograph.

    Designed for open-topic documentaries (macabre folklore, ancient history, true crime, finance):
      - When `prefer_gemini=True` or historical/folklore/macabre cues are present (e.g. Krampus,
        Saturnalia, ancient winter rituals), tries the LIVE Gemini Native Image API first (cached in
        `data/doc_photo_cache/`), then seamlessly blends real Wikimedia Commons archival artworks/photos
        and Pixabay HD photography!
      - Never falls back to unrelated financial stock photos when mood is `dark_horror`, `epic_history`,
        or `investigative_crime`.
    """
    return fetch_doc_real_photo(
        query=query,
        work_dir=work_dir,
        tag=tag,
        min_width=min_width,
        used_urls=used_urls,
        mood=mood,
        prefer_gemini=prefer_gemini,
        aspect_ratio=aspect_ratio,
        bespoke_prompt_en=bespoke_prompt_en,
    )


def fetch_doc_real_photo(
    query: str,
    work_dir: Path,
    tag: str,
    min_width: int = 640,
    used_urls: Optional[Set[str]] = None,
    mood: str = "",
    prefer_gemini: bool = False,
    aspect_ratio: str = "16:9",
    bespoke_prompt_en: str = "",
) -> Optional[Path]:
    """Fetch a REAL documentary / editorial photograph (or bespoke Gemini dark-cinema plate) with disk caching.

    Priority order:
      - If `prefer_gemini` or folklore/macabre/ancient-ritual cues detected:
          Gemini Native Image (`gemini-2.5-flash-image` / `gemini-3.1-flash-image`) ->
          Wikimedia Commons Archival / Pixabay HD Photo -> Pollinations Flux -> Mood-curated stock
      - Standard real-world photography:
          Pixabay Photo API -> Wikimedia Commons Search API -> Gemini Native Image (on stock miss) ->
          Pollinations Flux -> Mood-curated real documentary query fallback + validated local cache

    Every image is validated via `cv2.imread` (non-None, width >= 320, height >= 200,
    not chroma-key green) and cached in `data/doc_photo_cache/`.
    """
    resolved_mood = _infer_media_mood(f"{query} {bespoke_prompt_en}", mood)
    mood_defaults = MOOD_DOC_PHOTO_QUERIES.get(resolved_mood, CURATED_DOC_PHOTO_QUERIES)
    norm_q = _normalize_query(query, mood_defaults[0])
    used = used_urls if used_urls is not None else set()
    q_hash = hashlib.sha256(norm_q.lower().encode("utf-8")).hexdigest()[:16]
    eff_min_w = max(320, int(min_width))
    is_bespoke_folklore = bool(
        prefer_gemini
        or _BESPOKE_HISTORY_FOLKLORE_RE.search(norm_q)
        or (bespoke_prompt_en and _BESPOKE_HISTORY_FOLKLORE_RE.search(bespoke_prompt_en))
    )

    # 0. Fast persistent cache lookup by query hash (respecting used_urls uniqueness)
    cached_entries = _load_photo_query_index(q_hash)
    for entry in cached_entries:
        c_url = str(entry.get("url") or "")
        c_file = DOC_PHOTO_CACHE_DIR / str(entry.get("file") or "")
        if not c_url or c_url in used:
            continue
        ok, _, _ = _validate_photo_file(c_file, min_width=min(eff_min_w, 320))
        if ok:
            used.add(c_url)
            url_hash = hashlib.sha256(c_url.encode("utf-8")).hexdigest()[:16]
            return _materialize_photo_in_work_dir(c_file, work_dir, tag, url_hash)

    # 1. Bespoke Gemini Native Image Generation for folklore / ancient / macabre hero plates
    gemini_tried = False
    if is_bespoke_folklore:
        gemini_tried = True
        gem_prompt = bespoke_prompt_en.strip() if bespoke_prompt_en.strip() else norm_q
        gem_path = generate_doc_gemini_image(
            prompt_en=gem_prompt,
            work_dir=work_dir,
            tag=tag,
            mood=resolved_mood,
            aspect_ratio=aspect_ratio,
            min_width=eff_min_w,
            used_urls=used,
        )
        if gem_path is not None:
            return gem_path

    pixabay_key, _ = _read_api_keys()

    def _record_and_return(cached_path: Path, src_url: str, src_name: str, w: int, h: int) -> Path:
        used.add(src_url)
        entries = _load_photo_query_index(q_hash)
        if not any(e.get("url") == src_url for e in entries):
            entries.append({
                "url": src_url,
                "file": cached_path.name,
                "source": src_name,
                "width": w,
                "height": h,
                "query": norm_q,
                "mood": resolved_mood,
            })
            _save_photo_query_index(q_hash, entries)
        url_hash = hashlib.sha256(src_url.encode("utf-8")).hexdigest()[:16]
        print(
            f"[DocMedia] Real photo ready ({src_name}): {cached_path.name} ({w}x{h}) | q='{norm_q}'",
            flush=True,
        )
        return _materialize_photo_in_work_dir(cached_path, work_dir, tag, url_hash)

    # For specific museum/historical terms (e.g. Saturnalia, medieval engraving), prefer Wikimedia archival plates first
    prefer_wiki_first = bool(
        re.search(r"\b(saturnalia|painting|engraving|manuscript|roman|medieval|victorian|historical|museum|myth|pagan|ritual|folklore)\b", norm_q, re.IGNORECASE)
    )

    with httpx.Client(follow_redirects=True, timeout=16.0) as client:
        def _try_pixabay() -> Optional[Path]:
            if not pixabay_key:
                return None
            for item in _search_pixabay_photos(client, norm_q, pixabay_key, min_width=eff_min_w):
                url = item["url"]
                if url in used:
                    continue
                dl = _download_and_validate_photo(client, url, item["source"], q_hash, min_width=eff_min_w)
                if dl is not None:
                    p, w, h = dl
                    return _record_and_return(p, url, item["source"], w, h)
            return None

        def _try_wikimedia() -> Optional[Path]:
            wiki_candidates = _search_wikimedia_photos(client, norm_q, min_width=eff_min_w)
            for req_w in (eff_min_w, 320):
                for item in wiki_candidates:
                    url = item["url"]
                    if url in used:
                        continue
                    dl = _download_and_validate_photo(client, url, item["source"], q_hash, min_width=req_w)
                    if dl is not None:
                        p, w, h = dl
                        return _record_and_return(p, url, item["source"], w, h)
                if req_w == 320:
                    break
            return None

        # a/b) Pixabay & Wikimedia Commons real archival photography
        if prefer_wiki_first:
            hit = _try_wikimedia() or _try_pixabay()
        else:
            hit = _try_pixabay() or _try_wikimedia()
        if hit is not None:
            return hit

        # c) Bespoke Gemini Native Image Generation if real stock missed
        if not gemini_tried:
            gem_prompt = bespoke_prompt_en.strip() if bespoke_prompt_en.strip() else norm_q
            gem_path = generate_doc_gemini_image(
                prompt_en=gem_prompt,
                work_dir=work_dir,
                tag=tag,
                mood=resolved_mood,
                aspect_ratio=aspect_ratio,
                min_width=eff_min_w,
                used_urls=used,
            )
            if gem_path is not None:
                return gem_path

        # d) Mood-curated real documentary photo queries fallback (NEVER financial banks for dark_horror/history!)
        fb_pool = list(mood_defaults)
        start_idx = int(q_hash[:4], 16) % len(fb_pool)
        for offset in range(len(fb_pool)):
            fb_q = fb_pool[(start_idx + offset) % len(fb_pool)]
            fb_candidates: List[Dict[str, str]] = []
            if pixabay_key:
                fb_candidates.extend(_search_pixabay_photos(client, fb_q, pixabay_key, min_width=eff_min_w))
            if not fb_candidates:
                fb_candidates.extend(_search_wikimedia_photos(client, fb_q, min_width=320))
            for item in fb_candidates:
                url = item["url"]
                if url in used:
                    continue
                dl = _download_and_validate_photo(client, url, item["source"], q_hash, min_width=320)
                if dl is not None:
                    p, w, h = dl
                    return _record_and_return(p, url, f"{item['source']}_fallback", w, h)

        # e) Pollinations Flux fallback (only if Pixabay, Wikimedia & Gemini all missed)
        pol = _fetch_pollinations_photo(client, norm_q, q_hash, used, min_width=eff_min_w, mood=resolved_mood)
        if pol is not None:
            p, url, w, h = pol
            return _record_and_return(p, url, "pollinations_flux", w, h)

    # f) Offline safety net: prefer cached photos matching the same mood first!
    mood_matched_files: List[Path] = []
    for idx_file in DOC_PHOTO_CACHE_DIR.glob("idx_*.json"):
        try:
            items = json.loads(idx_file.read_text(encoding="utf-8"))
            if isinstance(items, list):
                for it in items:
                    if str(it.get("mood") or "") == resolved_mood and it.get("file"):
                        cp = DOC_PHOTO_CACHE_DIR / str(it["file"])
                        if cp.exists() and cp not in mood_matched_files:
                            mood_matched_files.append(cp)
        except Exception:
            continue

    all_cached = sorted(
        [p for p in DOC_PHOTO_CACHE_DIR.glob("*.jpg") if p.is_file() and (p.name.startswith("photo_") or p.name.startswith("gemini_"))],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    ordered_cache = mood_matched_files + [p for p in all_cached if p not in mood_matched_files]

    for p in ordered_cache:
        key = f"cache://{p.name}"
        if key in used:
            continue
        ok, _, _ = _validate_photo_file(p, min_width=320)
        if ok:
            used.add(key)
            return _materialize_photo_in_work_dir(p, work_dir, tag, p.stem[-8:])
    for p in ordered_cache:
        ok, _, _ = _validate_photo_file(p, min_width=320)
        if ok:
            return _materialize_photo_in_work_dir(p, work_dir, tag, p.stem[-8:])
    return None


# ---------------------------------------------------------------------------
# 2. Skia Image Cover Loader & 2.5D u2netp Foreground/Background Separator
# ---------------------------------------------------------------------------
def load_skia_image_cover(img_path: Path, target_w: int, target_h: int) -> Optional[skia.Image]:
    """Load an image file, aspect-cover center-crop & resize cleanly to (target_w, target_h)
    with zero aspect distortion, and return a native `kBGRA_8888_ColorType` `skia.Image`.
    """
    if img_path is None:
        return None
    p = Path(img_path)
    if not p.exists():
        return None
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None
    covered = _center_crop_resize_bgr(bgr, target_w, target_h, high_quality=True)
    bgra = cv2.cvtColor(covered, cv2.COLOR_BGR2BGRA)
    return skia.Image.fromarray(
        np.ascontiguousarray(bgra),
        colorType=skia.ColorType.kBGRA_8888_ColorType,
    )


def _get_u2netp_session():
    """Load ~/.u2net/u2netp.onnx via ONNXRuntime (2 CPU threads, Core i5 friendly)."""
    global _U2NETP_SESSION
    if _U2NETP_SESSION is None:
        import onnxruntime as ort

        u2_path = Path.home() / ".u2net" / "u2netp.onnx"
        rembg_path = Path.home() / ".rembg" / "models" / "u2netp" / "u2netp.onnx"
        model_file = u2_path if u2_path.exists() else (rembg_path if rembg_path.exists() else None)
        if model_file is None:
            return None
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        _U2NETP_SESSION = ort.InferenceSession(
            str(model_file),
            sess_options=so,
            providers=["CPUExecutionProvider"],
        )
    return _U2NETP_SESSION


def separate_photo_25d_u2netp(
    img_path: Path,
    target_w: int,
    target_h: int,
) -> Tuple[Optional[skia.Image], Optional[skia.Image]]:
    """Separate a photo into `(bg_inpainted_skia_img, fg_cutout_skia_img)` at `(target_w, target_h)`
    using `~/.u2net/u2netp.onnx` via `onnxruntime` + `cv2.inpaint` (TELEA).

    Both returned `skia.Image` objects use `kBGRA_8888_ColorType` (unpremultiplied alpha)
    so `parallax_25d_photo` can pan/zoom foreground 2.2x faster than the inpainted background!
    """
    if img_path is None:
        return None, None
    p = Path(img_path)
    if not p.exists():
        return None, None
    bgr_raw = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr_raw is None or bgr_raw.size == 0:
        return None, None

    tw = max(32, int(target_w))
    th = max(32, int(target_h))
    bgr = _center_crop_resize_bgr(bgr_raw, tw, th, high_quality=True)

    alpha = np.zeros((th, tw), dtype=np.uint8)
    sess = _get_u2netp_session()
    if sess is not None:
        try:
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
            alpha = (cv2.resize(mask_320, (tw, th), interpolation=cv2.INTER_LINEAR) * 255.0).astype(np.uint8)
        except Exception:
            alpha = np.zeros((th, tw), dtype=np.uint8)

    solid_cov = float(np.mean(alpha > 128))
    if 0.06 <= solid_cov <= 0.85:
        # Mild contrast stretch keeps genuine u2netp subjects crisp while feathering edges smoothly
        alpha_f = np.clip((alpha.astype(np.float32) / 255.0 - 0.12) / 0.76, 0.0, 1.0)
        alpha = (alpha_f * 255.0).astype(np.uint8)
    else:
        # Smooth architectural/subject focal ellipse fallback for uniform landscapes/skylines
        yy, xx = np.ogrid[:th, :tw]
        dist = ((xx - tw * 0.50) / max(1.0, tw * 0.30)) ** 2 + ((yy - th * 0.54) / max(1.0, th * 0.36)) ** 2
        alpha = np.clip((1.08 - dist) * 255.0, 0, 255).astype(np.uint8)

    # Clean anti-aliased alpha edge for foreground cutout
    alpha_feathered = cv2.GaussianBlur(alpha, (9, 9), 0)
    fg_bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    fg_bgra[:, :, 3] = alpha_feathered

    # Fast CPU background hole-filling at ~1/3 scale, composited ONLY over the dilated mask
    # so untouched background pixels keep 100% original crisp resolution!
    small_w = max(160, min(480, tw // 3))
    small_h = max(120, min(360, th // 3))
    bgr_small = cv2.resize(bgr, (small_w, small_h), interpolation=cv2.INTER_AREA)
    mask_small = cv2.resize(
        (alpha > 42).astype(np.uint8) * 255,
        (small_w, small_h),
        interpolation=cv2.INTER_NEAREST,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    dilated_small = cv2.dilate(mask_small, kernel, iterations=1)
    inpainted_small = cv2.inpaint(bgr_small, dilated_small, inpaintRadius=6, flags=cv2.INPAINT_TELEA)
    inpainted_up = cv2.resize(inpainted_small, (tw, th), interpolation=cv2.INTER_LINEAR)

    # Blend inpainted hole smoothly into crisp full-res background
    hole_mask_full = cv2.resize(dilated_small, (tw, th), interpolation=cv2.INTER_LINEAR)
    hole_mask_soft = cv2.GaussianBlur(hole_mask_full, (15, 15), 0).astype(np.float32) / 255.0
    hole_mask_3 = hole_mask_soft[:, :, np.newaxis]
    bg_inpainted = np.clip(
        inpainted_up.astype(np.float32) * hole_mask_3 + bgr.astype(np.float32) * (1.0 - hole_mask_3),
        0,
        255,
    ).astype(np.uint8)
    bg_bgra = cv2.cvtColor(bg_inpainted, cv2.COLOR_BGR2BGRA)

    bg_skia = skia.Image.fromarray(
        np.ascontiguousarray(bg_bgra),
        colorType=skia.ColorType.kBGRA_8888_ColorType,
    )
    fg_skia = skia.Image.fromarray(
        np.ascontiguousarray(fg_bgra),
        colorType=skia.ColorType.kBGRA_8888_ColorType,
    )
    return bg_skia, fg_skia


# ---------------------------------------------------------------------------
# 3. Real HD Video B-Roll Fetcher
# ---------------------------------------------------------------------------
def _validate_video_file(video_path: Path) -> bool:
    """Confirm clip opens in OpenCV, yields a real frame >=320x200, and passes chroma-key check."""
    if not video_path.exists() or video_path.stat().st_size < 60_000:
        return False
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        ok, frame = cap.read()
        if not ok or frame is None or frame.ndim < 3:
            return False
        h, w = frame.shape[:2]
        if w < 320 or h < 200 or (0 < frame_count < 5):
            return False
    finally:
        cap.release()
    if has_chroma_key_green(video_path):
        return False
    return True


def _pick_cpu_friendly_pixabay_video_variant(
    vids: Dict[str, Any],
    want_landscape: bool = True,
) -> Optional[Dict[str, Any]]:
    """Select a crisp 720p-1080p Pixabay MP4 variant (avoids heavy 4K 60-150MB streams on Core i5)."""
    candidates: List[Dict[str, Any]] = []
    for tier in ("small", "medium", "large", "tiny"):
        v = vids.get(tier)
        if not isinstance(v, dict) or not v.get("url"):
            continue
        w = int(v.get("width") or 0)
        h = int(v.get("height") or 0)
        size = int(v.get("size") or 0)
        if w < 640 or h < 360:
            continue
        is_landscape = w >= h
        orient_penalty = 0 if (is_landscape == want_landscape) else 2_000
        # Target ~1280..1920 wide and <= 24MB for fast download & silky 30fps CPU decoding
        if 1200 <= max(w, h) <= 2048 and size <= 24_000_000:
            res_score = abs(max(w, h) - 1920) // 4 + (size // 200_000)
        elif max(w, h) > 2048:
            res_score = 1_000 + (size // 100_000)
        else:
            res_score = 400 + abs(max(w, h) - 1280)
        candidates.append({
            "score": orient_penalty + res_score,
            "url": str(v["url"]),
            "width": w,
            "height": h,
            "size": size,
            "tier": tier,
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["score"])
    return candidates[0]


def _fetch_pixabay_doc_broll(
    client: httpx.Client,
    query: str,
    api_key: str,
    used_hashes: Set[str],
    want_landscape: bool = True,
) -> Optional[Tuple[Path, str]]:
    """Fast Pixabay HD B-roll search preferring 1080p/720p MP4s & caching in data/doc_broll_cache/."""
    if not api_key:
        return None
    queries_to_try = [query]
    short_q = _shorten_query(query, max_words=3)
    if short_q and short_q.lower() != query.lower():
        queries_to_try.append(short_q)

    for q in queries_to_try:
        try:
            clean_q = build_clean_search_query(q)
            r = client.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": api_key,
                    "q": clean_q,
                    "per_page": 8,
                    "safesearch": "true",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                continue
            hits = r.json().get("hits", [])
        except Exception:
            continue

        for hit in hits:
            tags = str(hit.get("tags") or "").lower()
            if any(bad in tags for bad in BAD_TAG_WORDS):
                continue
            picked = _pick_cpu_friendly_pixabay_video_variant(
                hit.get("videos") or {},
                want_landscape=want_landscape,
            )
            if not picked:
                continue
            url = picked["url"]
            hsh = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            if hsh in used_hashes:
                continue
            local_path = DOC_BROLL_CACHE_DIR / f"doc_pix_{hsh}.mp4"
            try:
                if not local_path.exists() or local_path.stat().st_size < 60_000:
                    resp = client.get(url, timeout=25.0)
                    if resp.status_code != 200 or len(resp.content) < 60_000:
                        continue
                    local_path.write_bytes(resp.content)
                qrep = evaluate_clip_quality(local_path, min_blur=18.0)
                if not qrep["passed"] or not _validate_video_file(local_path):
                    local_path.unlink(missing_ok=True)
                    continue
                used_hashes.add(hsh)
                print(
                    f"[DocMedia] Real HD B-roll ready (pixabay {picked['width']}x{picked['height']}): "
                    f"{local_path.name} | blur={qrep['blur_score']} | green={qrep['green_pixel_ratio']:.1%}",
                    flush=True,
                )
                return local_path, hsh
            except Exception:
                local_path.unlink(missing_ok=True)
                continue
    return None


def fetch_doc_broll_clip(
    query: str,
    work_dir: Path,
    tag: str,
    used_hashes: Set[str],
    aspect_ratio: str = "16:9",
    mood: str = "",
) -> Optional[Path]:
    """Fetch a REAL, valid, non-chroma-key HD `.mp4` B-roll clip for documentary compositing.

    Uses fast HD-optimized Pixabay search + `engine.smart_vision.fetch_unique_real_clip`
    (Pixabay -> Pexels -> yt-dlp -> Wikimedia -> Internet Archive + >30% chroma-key green filter).
    Automatically retries mood-matched cinematic documentary queries on miss so EVERY scene
    receives genuine moving HD video footage matching the documentary's atmosphere!
    """
    resolved_mood = _infer_media_mood(query, mood)
    curated_pool = MOOD_DOC_BROLL_QUERIES.get(resolved_mood, CURATED_DOC_BROLL_QUERIES)
    norm_q = _normalize_query(query, curated_pool[0])
    used = used_hashes if used_hashes is not None else set()
    pixabay_key, pexels_key = _read_api_keys()
    want_landscape = str(aspect_ratio or "16:9").strip() != "9:16"

    # Build ordered query cascade: specific query -> shortened 3-word core -> mood-matched curated queries
    tag_seed = int(hashlib.sha256(f"{tag}:{norm_q}".encode("utf-8")).hexdigest()[:6], 16)
    rotated_curated = [
        curated_pool[(tag_seed + i) % len(curated_pool)]
        for i in range(len(curated_pool))
    ]
    all_queries: List[str] = [norm_q]
    short_q = _shorten_query(norm_q, max_words=3)
    if short_q and short_q.lower() != norm_q.lower():
        all_queries.append(short_q)
    for q in rotated_curated:
        if q.lower() not in {x.lower() for x in all_queries}:
            all_queries.append(q)

    # 1. Fast HD 1080p/720p Pixabay B-roll pass (avoids downloading 100MB 4K clips on Core i5)
    if pixabay_key:
        with httpx.Client(follow_redirects=True, timeout=22.0) as client:
            for q in all_queries[:5]:
                res = _fetch_pixabay_doc_broll(
                    client,
                    q,
                    api_key=pixabay_key,
                    used_hashes=used,
                    want_landscape=want_landscape,
                )
                if res is not None:
                    clip_path, hsh = res
                    return _materialize_video_in_work_dir(clip_path, work_dir, tag, hsh)

    # 2. Multi-source fallback via engine.smart_vision.fetch_unique_real_clip
    #    (Pixabay Video -> Pexels -> yt-dlp -> Wikimedia Commons -> Internet Archive -> cache)
    for idx, q in enumerate(all_queries):
        try:
            clip = fetch_unique_real_clip(
                q,
                pixabay_key=pixabay_key,
                pexels_key=pexels_key,
                exclude_hashes=used,
                scene_index=(tag_seed + idx) % len(curated_pool),
            )
            if clip and _validate_video_file(clip):
                hsh = clip.stem.split("_")[-1][:16]
                used.add(hsh)
                print(
                    f"[DocMedia] Real HD B-roll ready (smart_vision): {clip.name} | q='{q}'",
                    flush=True,
                )
                return _materialize_video_in_work_dir(clip, work_dir, tag, hsh)
        except Exception:
            continue

    # 3. Last-resort reuse of any validated cached real MP4 clip on disk (doc_broll_cache or media_cache)
    cached_clips = []
    for cache_dir in (DOC_BROLL_CACHE_DIR, SMART_VISION_CACHE_DIR):
        if cache_dir.exists():
            cached_clips.extend(
                p for p in cache_dir.glob("*")
                if p.suffix.lower() in (".mp4", ".webm") and p.stat().st_size > 80_000
            )
    cached_clips.sort(key=lambda p: p.stat().st_size)  # prefer lighter HD clips first for CPU speed

    for clip in cached_clips:
        hsh = clip.stem.split("_")[-1][:16]
        if hsh in used:
            continue
        if _validate_video_file(clip):
            used.add(hsh)
            return _materialize_video_in_work_dir(clip, work_dir, tag, hsh)
    for clip in cached_clips:
        if _validate_video_file(clip):
            hsh = clip.stem.split("_")[-1][:16]
            return _materialize_video_in_work_dir(clip, work_dir, tag, hsh)
    return None


# ---------------------------------------------------------------------------
# 4. Lightweight Sequential Skia Video Frame Streamer (Main + PiP Simultaneous)
# ---------------------------------------------------------------------------
class VideoLayerReader:
    """Lightweight sequential OpenCV -> Skia frame reader for full-HD and PiP video layers.

    - Single-threaded OpenCV (`cv2.setNumThreads(1)`) for predictable Core i5 CPU usage
    - Seamless EOF looping back to frame 0
    - Aspect-cover center-crop & resize to exact `(target_w, target_h)` (zero aspect distortion)
    - Fast uint8 LUT darkening (`darken_alpha` in `[0.0, 1.0]`) without float32 allocations
    - Native `skia.Image` (`kBGRA_8888_ColorType`) output for instant zero-copy Skia drawing
    """

    def __init__(self, mp4_path: Path, target_w: int, target_h: int, fps: int = 30) -> None:
        cv2.setNumThreads(1)
        self.mp4_path = Path(mp4_path)
        self.target_w = max(16, int(target_w))
        self.target_h = max(16, int(target_h))
        self.fps = max(1, int(fps))

        self._cap: Optional[cv2.VideoCapture] = None
        self._closed: bool = False
        self._src_fps: float = float(self.fps)
        self._frame_step: float = 1.0
        self._src_pos_accum: float = 0.0
        self._decoded_src_idx: int = -1
        self._crop_rect: Optional[Tuple[int, int, int, int]] = None
        self._interp: int = cv2.INTER_LINEAR
        self._bgra_buf = np.empty((self.target_h, self.target_w, 4), dtype=np.uint8)
        self._darken_lut_cache: Dict[int, np.ndarray] = {}
        self._last_bgr: Optional[np.ndarray] = None
        self._last_skia_key: Optional[Tuple[int, int]] = None
        self._last_skia_img: Optional[skia.Image] = None

        self._open_capture()

    def _open_capture(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if not self.mp4_path.exists():
            return
        cap = cv2.VideoCapture(str(self.mp4_path))
        if not cap.isOpened():
            return
        self._cap = cap
        raw_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if 5.0 <= raw_fps <= 120.0:
            self._src_fps = raw_fps
        else:
            self._src_fps = float(self.fps)
        self._frame_step = self._src_fps / float(self.fps)
        # Keep natural smooth cadence: 24/25/30fps -> 1:1 sequential, 60fps -> grab-skip every other frame
        if 0.72 <= self._frame_step <= 1.35:
            self._frame_step = 1.0

    def _ensure_crop_geometry(self, src_w: int, src_h: int) -> None:
        if self._crop_rect is not None:
            return
        src_ar = src_w / max(1.0, float(src_h))
        dst_ar = self.target_w / max(1.0, float(self.target_h))
        if src_ar > dst_ar:
            crop_w = max(1, min(src_w, int(round(src_h * dst_ar))))
            x0 = (src_w - crop_w) // 2
            self._crop_rect = (x0, 0, x0 + crop_w, src_h)
            cw, ch = crop_w, src_h
        elif src_ar < dst_ar:
            crop_h = max(1, min(src_h, int(round(src_w / dst_ar))))
            y0 = (src_h - crop_h) // 2
            self._crop_rect = (0, y0, src_w, y0 + crop_h)
            cw, ch = src_w, crop_h
        else:
            self._crop_rect = (0, 0, src_w, src_h)
            cw, ch = src_w, src_h
        # Use INTER_AREA when downscaling strongly (prevents PiP aliasing/shimmer); INTER_LINEAR otherwise for speed
        self._interp = cv2.INTER_AREA if (cw > self.target_w * 2.0 or ch > self.target_h * 2.0) else cv2.INTER_LINEAR

    def _read_next_raw_frame(self) -> Optional[np.ndarray]:
        if self._closed or self._cap is None:
            return None
        ok, frame = self._cap.read()
        if ok and frame is not None:
            return frame

        # Seamless EOF loop back to frame 0
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = self._cap.read()
        if ok and frame is not None:
            return frame

        # Container seek fallback: reopen VideoCapture cleanly
        self._open_capture()
        if self._cap is not None:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return frame
        return None

    def _get_darken_lut(self, alpha_key: int) -> np.ndarray:
        lut = self._darken_lut_cache.get(alpha_key)
        if lut is None:
            scale = max(0.0, min(1.0, 1.0 - (alpha_key / 255.0)))
            lut = np.clip(np.rint(np.arange(256, dtype=np.float32) * scale), 0, 255).astype(np.uint8)
            self._darken_lut_cache[alpha_key] = lut
        return lut

    def read_skia_frame(self, darken_alpha: float = 0.0) -> Optional[skia.Image]:
        """Read the next frame sequentially (looping seamlessly on EOF), aspect-cover crop/resize
        to `(target_w, target_h)`, apply optional `darken_alpha` (0.0..1.0), and return a
        `skia.Image` (`kBGRA_8888_ColorType`).
        """
        if self._closed:
            return None

        alpha_clamped = max(0.0, min(1.0, float(darken_alpha or 0.0)))
        alpha_key = int(round(alpha_clamped * 255.0))

        target_src_idx = int(self._src_pos_accum)
        self._src_pos_accum += self._frame_step

        need_decode = (self._last_bgr is None) or (target_src_idx > self._decoded_src_idx)
        if need_decode and self._cap is not None:
            # Skip intermediate frames cheaply with grab() if source FPS >> target FPS (e.g. 60fps -> 30fps)
            skips = max(0, target_src_idx - self._decoded_src_idx - 1) if self._decoded_src_idx >= 0 else 0
            for _ in range(min(skips, 4)):
                if not self._cap.grab():
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    break
            raw = self._read_next_raw_frame()
            if raw is not None:
                h, w = raw.shape[:2]
                self._ensure_crop_geometry(w, h)
                x0, y0, x1, y1 = self._crop_rect  # type: ignore[misc]
                cropped = raw[y0:y1, x0:x1]
                if cropped.shape[1] == self.target_w and cropped.shape[0] == self.target_h:
                    self._last_bgr = cropped
                else:
                    self._last_bgr = cv2.resize(
                        cropped,
                        (self.target_w, self.target_h),
                        interpolation=self._interp,
                    )
                self._decoded_src_idx = target_src_idx
                self._last_skia_key = None

        if self._last_bgr is None:
            return None

        # Fast-path reuse when duplicating a low-FPS source frame with identical darken_alpha
        cache_key = (self._decoded_src_idx, alpha_key)
        if self._last_skia_key == cache_key and self._last_skia_img is not None:
            return self._last_skia_img

        bgr = self._last_bgr
        if alpha_key > 0:
            bgr = cv2.LUT(bgr, self._get_darken_lut(alpha_key))

        cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA, dst=self._bgra_buf)
        img = skia.Image.fromarray(
            self._bgra_buf,
            colorType=skia.ColorType.kBGRA_8888_ColorType,
        )
        self._last_skia_key = cache_key
        self._last_skia_img = img
        return img

    def close(self) -> None:
        self._closed = True
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._last_bgr = None
        self._last_skia_img = None

    def __enter__(self) -> "VideoLayerReader":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


__all__ = [
    "CURATED_DOC_BROLL_QUERIES",
    "CURATED_DOC_PHOTO_QUERIES",
    "DOC_BROLL_CACHE_DIR",
    "DOC_PHOTO_CACHE_DIR",
    "GEMINI_IMAGE_MODELS",
    "MOOD_DOC_BROLL_QUERIES",
    "MOOD_DOC_PHOTO_QUERIES",
    "VideoLayerReader",
    "fetch_doc_broll_clip",
    "fetch_doc_hero_or_archival_photo",
    "fetch_doc_real_photo",
    "generate_doc_gemini_image",
    "load_skia_image_cover",
    "separate_photo_25d_u2netp",
]
