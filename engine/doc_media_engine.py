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
import time
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

# Strict semantic off-topic blocklist so random stock junk (tile floors, butterflies, flowers,
# bathrooms, pets, disco parties, abstract wallpapers) NEVER slips into serious documentaries!
OFFTOPIC_MEDIA_TAGS = (
    "floor",
    "floors",
    "flooring",
    "tile",
    "tiles",
    "tiling",
    "ceramic",
    "pavement",
    "sidewalk",
    "carpet",
    "rug",
    "linoleum",
    "parquet",
    "butterfly",
    "butterflies",
    "insect",
    "insects",
    "moth",
    "ladybug",
    "bee",
    "beetle",
    "dragonfly",
    "flower",
    "flowers",
    "petal",
    "blossom",
    "tulip",
    "daisy",
    "sunflower",
    "bouquet",
    "bathroom",
    "toilet",
    "shower",
    "kitchen",
    "bedroom",
    "living room",
    "sofa",
    "couch",
    "furniture",
    "interior design",
    "beach",
    "tropical",
    "palm tree",
    "surf",
    "swimming pool",
    "bikini",
    "yoga",
    "fitness",
    "gym",
    "workout",
    "selfie",
    "makeup",
    "cosmetics",
    "fashion model",
    "pizza",
    "burger",
    "coffee cup",
    "cupcake",
    "smoothie",
    "puppy",
    "kitten",
    "cat",
    "dog",
    "hamster",
    "aquarium",
    "disco",
    "confetti",
    "balloon",
    "balloons",
    "birthday",
    "wedding dress",
    "baby",
    "toddler",
    "toy",
    "toys",
    "figurine",
    "miniature",
    "statuette",
    "doll",
    "action figure",
    "collectible",
    "toy soldier",
    "plush",
    "mannequin",
    "wax figure",
    "wallpaper",
    "seamless",
    "texture",
    "abstract",
    "glitter",
    "sparkle",
    "emoji",
    "cartoon",
    "anime",
    "cosplay",
    "facepaint",
    "face paint",
    "costume",
    "parade",
    "krampuslauf",
    "perchtenlauf",
    "reenactment",
    "tourist",
    "gemstone",
    "emerald",
    "jade",
    "mineral",
    "crystal",
    "quartz",
    "specimen",
    "artifact_fragment",
    "shard",
    "coin",
    "postage",
    "stamp",
    "paraglider",
    "paragliding",
    "hang glider",
    "skydiving",
    "skiing",
    "snowboard",
    "snowboarding",
    "steampunk",
    "ai generated",
    "3d render",
    "cgi",
    "waterfront",
    "resort",
    "vacation",
    "tourism",
    "cruise",
    "yacht",
    "speedboat",
    "ferry",
    "canal boat",
    "gondola",
)

DARK_HISTORY_EXTRA_BAD_TAGS = (
    "office",
    "laptop",
    "smartphone",
    "typing",
    "skyscraper",
    "traffic",
    "highway",
    "freeway",
    "motorway",
    "neon",
    "cyberpunk",
    "business",
    "corporate",
    "meeting",
    "smiling",
    "happy family",
    "gift box",
    "shopping mall",
    "bus",
    "car",
    "automobile",
    "truck",
    "police van",
    "cargo van",
    "delivery van",
    "camper van",
    "minivan",
    "motorcycle",
    "airplane",
    "aircraft",
    "helicopter",
    "drone",
    "aerial city",
    "train",
    "subway",
    "modern city",
    "downtown",
    "apartment",
    "hotel",
    "parking",
    "asphalt",
    "swimming",
    "sunbathing",
    "palm",
    "island",
    "colorful houses",
    "fairy lights",
    "string lights",
    "christmas lights",
    "led lights",
    "electric lights",
    "riot police",
    "police",
    "kevlar",
    "hoodie",
    "jeans",
    "sneakers",
    "rice terrace",
    "pagoda",
)

# Global perceptual dHash registry for cross-call Wikimedia Commons & archival photo deduplication
_SEEN_PHOTO_DHASHES: Set[int] = set()

_HISTORICAL_ERA_NEGATIVE_LOCK = (
    "authentic period-accurate historical clothing and architecture, dark chiaroscuro oil painting "
    "or archival realism, NO modern police, NO Kevlar helmets, NO modern cars or vans, "
    "NO electric LED lights, NO modern hoodies or jeans"
)

# Explicit modern / contemporary / Act-4 epilogue indicators that must NEVER be falsely
# era-locked to Ancient Rome or Pre-Christian Solstice (e.g. S25 'O ETERNO SOLSTÍCIO').
_MODERN_META_ERA_RE = re.compile(
    r"\b(?:"
    r"act_4(?:_abrupt_ending)?|"
    r"ep[ií]logo|epilogue|"
    r"hoje|today|presente|present[\s-]day|"
    r"modern[ao]s?|modern[\s-]day|"
    r"contempor[aâ]ne[ao]s?|contemporary|"
    r"s[eé]c(?:ulo|\.)\s*(?:xxi|21)|21st[\s-]+century|"
    r"o\s+eterno\s+solst[ií]cio|eternal\s+solstice|"
    r"sala\s+escura|sala\s+de\s+estar|"
    r"20(?:0\d|1\d|2\d)"
    r")\b",
    re.IGNORECASE,
)

_MODERN_PROMPT_ERA_RE = re.compile(
    r"\b(?:"
    r"act_4(?:_abrupt_ending)?|"
    r"ep[ií]logo|epilogue|"
    r"s[eé]c(?:ulo|\.)\s*(?:xxi|21)|21st[\s-]+century|"
    r"modern\s+living\s+room|dark\s+living\s+room|living\s+room|"
    r"modern[\s-]day|contemporary|contempor[aâ]ne[ao]s?|"
    r"festa\s+moderna|seres\s+humanos\s+modernos|natal\s+moderno|hoje\s+em\s+dia|"
    r"sala\s+escura|sala\s+de\s+estar|"
    r"20(?:0\d|1\d|2\d)"
    r")\b",
    re.IGNORECASE,
)

# Multi-millennium forensic synthesis spans (e.g. '217 A.C. A 1931', '2.000 ANOS') should NOT
# blindly lock an overview / epilogue scene to the earliest year in the span.
_MULTI_ERA_SPAN_RE = re.compile(
    r"(?:\b\d{1,4}\s*(?:a\.?c\.?|bc)\s*(?:a|to|[-–—])\s*(?:19\d\d|20\d\d|hoje|presente)\b|"
    r"s[ií]ntese\s+forense|dossi[eê]\s+forense|2\.?000\s+anos)",
    re.IGNORECASE,
)

# High-specificity era rules checked with destination / later-century priority BEFORE secondary words
_HISTORICAL_ERA_RULES: Tuple[Tuple[re.Pattern[str], str, bool], ...] = (
    # Destination / century-range priority: S09 'MIRA A AMSTERDÃ • SÉC. XI–XVII' MUST beat '\bmira\b'!
    (
        re.compile(
            r"s[eé]c(?:ulo|\.)\s*xi\s*[-–—]\s*xvii\b|"
            r"17th[\s-]+century\s+dutch|dutch\s+golden\s+age|amsterd[aã]|new\s+amsterdam|"
            r"sinterklaas|holand[aê]|pa[ií]ses\s+baixos|\b1600s\b",
            re.IGNORECASE,
        ),
        "17th-century Dutch Golden Age Amsterdam and Northern Europe",
        True,
    ),
    (re.compile(r"\b1931\b|sundblom|coca[\s-]*cola", re.IGNORECASE), "1931 Great Depression era early 20th-century America", True),
    (re.compile(r"\b18(?:6[3-9]|7[0-9]|8[01])\b|thomas\s+nast|harper'?s\s+weekly", re.IGNORECASE), "1870s Late 19th-century Victorian New York wood engraving era", True),
    (re.compile(r"\b182[23]\b|clement\s+clarke\s+moore|nova\s+york\s*•?\s*182", re.IGNORECASE), "1820s Early 19th-century Regency New York", True),
    (re.compile(r"\b184[38]\b|dickens|scrooge|vit[oó]ria|victoria|windsor|victorian|s[eé]c(?:ulo|\.)\s*(?:xix|19)\b", re.IGNORECASE), "1840s Victorian London 19th century", True),
    (re.compile(r"\b1660\b|carlos\s+ii|charles\s+ii|restaura[cç][aã]o", re.IGNORECASE), "1660 Restoration England King Charles II", True),
    (re.compile(r"\b165[0-9]\b|massachusetts|boston\s*•?\s*165", re.IGNORECASE), "1659 17th-century Colonial Puritan Massachusetts and Cromwellian England", True),
    (re.compile(r"\b164[4-9]\b|canterbury|plum\s+pudding|pudim\s+de\s+ameixa|puritan", re.IGNORECASE), "1647 17th-century English Civil War Puritan England", True),
    (re.compile(r"s[eé]c(?:ulo|\.)\s*(?:xiv|xv|xvi|14|15|16)\b|tudor|abade\s+da\s+desordem|twelfth\s+night", re.IGNORECASE), "15th-century Late Medieval and Tudor Europe", True),
    (re.compile(r"krampus|alpes\s+austr", re.IGNORECASE), "11th century Medieval Austrian Alps", True),
    (re.compile(r"bari\s+harbor|\b1087\b", re.IGNORECASE), "11th-century Medieval Italy and Europe", True),
    (re.compile(r"s[eé]c(?:ulo|\.)\s*(?:xi|11|onze)\b", re.IGNORECASE), "11th century Medieval Europe", True),
    (re.compile(r"\byule\b|\bodin\b|escandin[aá]v|ca[cç]ada\s+selvagem|s[eé]c(?:ulo|\.)\s*(?:viii|ix|8|9)\b", re.IGNORECASE), "9th century Early Medieval Scandinavian and Germanic winter", True),
    (re.compile(r"s[eé]c(?:ulo|\.)\s*(?:iv|4|quarto)\b|fourth[\s-]+century|4th[\s-]+century|l[ií]cia\s+romana|nicolau\s+de\s+mira|\bmyra\b|\bmira\b", re.IGNORECASE), "4th century AD Byzantine Anatolia, Ancient Myra Lycia", True),
    (re.compile(r"\b336\s*(?:d\.?c\.?|ad)\b|\b354\b|\b325\b|constantin|sol\s+invictus", re.IGNORECASE), "Late Roman Empire 336 AD, Constantinian Rome", True),
    (re.compile(r"\b274\s*(?:d\.?c\.?|ad)\b|aurelian", re.IGNORECASE), "Late Roman Empire 274 AD, Emperor Aurelian era", True),
    (re.compile(r"\b217\s*(?:a\.?c\.?|bc)\b|saturn[aá]lia|templo\s+de\s+saturno", re.IGNORECASE), "Ancient Rome 217 BC, Roman Republic", True),
    (re.compile(r"pr[eé][\s-]*crist[aã]|mediterr[aâ]neo|antiguidade|ancient\s+winter|solst[ií]cio\s+de\s+inverno", re.IGNORECASE), "Pre-Christian Ancient Mediterranean and Northern Europe winter solstice", True),
)


def _match_explicit_era_in_text(text: str) -> Optional[Tuple[str, bool]]:
    """Match an explicit historical era, century range, or pre-1940 date inside a single text span."""
    if not text or not text.strip():
        return None
    clean = text.strip()
    is_multi_span = bool(_MULTI_ERA_SPAN_RE.search(clean))

    # 1. Explicit century ranges (e.g. 'SÉC. XI–XVII') — prioritize destination/end century unless matched by named rule
    for rx, era_label, is_pre_modern in _HISTORICAL_ERA_RULES:
        if is_multi_span and ("217" in era_label or "1931" in era_label):
            continue
        if rx.search(clean):
            return era_label, is_pre_modern

    if is_multi_span:
        return None

    # 2. Generic century range ('SÉC. XI–XVII', 'SÉCULO XV A XVII') -> use destination century
    m_sec_rng = re.search(
        r"\bs[eé]c(?:ulo|\.)\s*(?:[ivxl]+|\d{1,2})\s*(?:[-–—]|a|to)\s*([ivxl]+|\d{1,2})\b",
        clean,
        re.IGNORECASE,
    )
    if m_sec_rng:
        sec_end = m_sec_rng.group(1).upper()
        if sec_end in ("XXI", "21"):
            return "", False
        return f"Historical {sec_end} Century Europe", True

    # 3. Generic English ordinal century ('17th century', '15th-century', '4th century AD')
    m_en_cent = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)[\s-]+century\b", clean, re.IGNORECASE)
    if m_en_cent:
        c_num = int(m_en_cent.group(1))
        if c_num >= 21:
            return "", False
        if 1 <= c_num <= 20:
            return f"Historical {c_num}th-century Era", c_num <= 20

    # 4. Generic BC/AD year ('48 a.C.', '79 AD')
    m_bc = re.search(r"\b(\d{1,4})\s*(a\.?c\.?|bc|d\.?c\.?|ad)\b", clean, re.IGNORECASE)
    if m_bc:
        yr = m_bc.group(1)
        suf = "BC" if m_bc.group(2).lower().startswith(("a", "b")) else "AD"
        return f"Ancient Historical Era {yr} {suf}", True

    # 5. Generic calendar year (1000..1939)
    m_yr = re.search(r"\b(1[0-8]\d{2}|19[0-3]\d)\b", clean)
    if m_yr:
        yr_int = int(m_yr.group(1))
        return f"Historical Era {yr_int}", yr_int <= 1940

    # 6. Generic Portuguese century ('SÉC. XVII', 'SÉCULO IV')
    m_sec = re.search(r"\bs[eé]c(?:ulo|\.)\s*([ivxl]+|\d{1,2})\b", clean, re.IGNORECASE)
    if m_sec:
        sec_tok = m_sec.group(1).upper()
        if sec_tok in ("XXI", "21"):
            return "", False
        return f"Historical {sec_tok} Century Europe", True

    return None


def _extract_historical_era_lock(
    lower_third_title: str = "",
    lower_third_subtitle: str = "",
    prompt_en: str = "",
) -> Tuple[str, bool]:
    """Extract a canonical English historical period lock and whether the scene is pre-modern.

    Priority order:
      1. Modern / Contemporary / Act-4 Epilogue override (`ACT_4`, `HOJE`, `MODERNA`,
         `CONTEMPORÂNEO`, `SÉC. XXI`, `O ETERNO SOLSTÍCIO`, `living room`, `sala escura`) -> `("", False)`.
      2. Explicit century / year / destination in `prompt_en` (e.g. `17th century Dutch Golden Age`,
         `eleventh-century Bari`).
      3. Explicit century / year / destination in `lower_third_title` (e.g. `MIRA A AMSTERDÃ • SÉC. XI–XVII`
         overrides secondary `\\bmira\\b`!).
      4. Combined metadata (`lower_third_title` + `lower_third_subtitle`), then full text.
    """
    lt_title = str(lower_third_title or "").strip()
    lt_sub = str(lower_third_subtitle or "").strip()
    p_en = str(prompt_en or "").strip()
    combined_meta = f"{lt_title} {lt_sub}".strip()
    combined_all = f"{combined_meta} {p_en}".strip()

    # Check if prompt_en explicitly specifies a pre-1940 historical era
    prompt_match = _match_explicit_era_in_text(p_en) if p_en else None
    meta_has_modern = bool(combined_meta and _MODERN_META_ERA_RE.search(combined_meta))
    prompt_has_modern = bool(p_en and _MODERN_PROMPT_ERA_RE.search(p_en))

    # 1. Contemporary / Modern / Act-4 Epilogue override (prevents S25 'O ETERNO SOLSTÍCIO' false ancient lock!)
    if meta_has_modern:
        if prompt_match is not None and prompt_match[1] and not prompt_has_modern:
            return prompt_match
        return "", False

    if prompt_has_modern and (prompt_match is None or not prompt_match[1]):
        # If the prompt/narration explicitly describes a modern/Act-4 scene (e.g. modern living room,
        # 'festa moderna', 'ACT_4', 'SÉC. XXI') and lower_third_title has no specific single pre-1940 date,
        # treat as contemporary (is_pre_modern=False).
        title_match_chk = _match_explicit_era_in_text(lt_title) if lt_title else None
        if title_match_chk is None or _MULTI_ERA_SPAN_RE.search(combined_meta):
            return "", False

    # 2. Prioritize explicit century/year/destination in prompt_en over secondary words in metadata
    if prompt_match is not None:
        return prompt_match

    # 3. Prioritize explicit century/year/destination in lower_third_title
    if lt_title:
        title_match = _match_explicit_era_in_text(lt_title)
        if title_match is not None:
            return title_match

    # 4. Combined lower_third_title + lower_third_subtitle
    if combined_meta:
        meta_match = _match_explicit_era_in_text(combined_meta)
        if meta_match is not None:
            return meta_match

    # 5. Full combined context fallback
    if combined_all:
        all_match = _match_explicit_era_in_text(combined_all)
        if all_match is not None:
            return all_match

    return "", False


def _enforce_historical_era_prompt_lock(
    prompt_en: str,
    lower_third_title: str = "",
    lower_third_subtitle: str = "",
) -> str:
    """Prepend an explicit historical era lock extracted from scene metadata and append strict
    anti-anachronism negative directives to pre-modern visual prompts before Google Flow generation.
    Idempotent: never duplicates an existing era prefix or negative-lock tail.
    """
    base = " ".join(str(prompt_en or "").strip().split())
    if not base:
        return base

    era_label, is_pre_modern = _extract_historical_era_lock(lower_third_title, lower_third_subtitle, base)
    out = base
    if not is_pre_modern:
        return re.sub(r"\s{2,}", " ", out).strip()

    if era_label:
        # Prepend period lock ONLY if not already explicitly prefixed or containing a historical scene lock
        out_low = out.lower()
        if (era_label.lower() not in out_low) and ("historical scene:" not in out_low):
            out = f"{era_label} historical scene: {out}"

    if ("NO Kevlar helmets" not in out) and ("authentic period-accurate historical clothing" not in out.lower()):
        out = f"{out.rstrip(' .,;')}, {_HISTORICAL_ERA_NEGATIVE_LOCK}"
    return re.sub(r"\s{2,}", " ", out).strip()


# Modern currency & numismatic coin patterns that MUST ALWAYS be blocked even when 'coins' is in query
_MODERN_CURRENCY_COIN_RE = re.compile(
    r"\b(?:"
    r"\d+\s*kr\b|kronor|kroner|shillings?|farthings?|sixpence|halfpenny|"
    r"pence|penny|cents?|centavos?|euro\s+coins?|dollar\s+coins?|quarter\s+dollar|"
    r"krugerrand|commemorative\s+coins?|numismat\w*|coinage\s+of\s+(?:19|20)|"
    r"(?:19\d\d|20[0-2]\d)\s+(?:gold\s+|silver\s+|bronze\s+|copper\s+)?(?:coins?|shillings?|kr|kronor|penny|cent|dollar|franc|mark)|"
    r"(?:coins?|shillings?|kronor)\s+(?:19\d\d|20[0-2]\d)|"
    r"george\s+v\b|elizabeth\s+ii\b"
    r")",
    re.IGNORECASE,
)

_ANCIENT_COIN_ALLOW_TERMS = (
    " roman ", " ancient ", " byzantine ", " medieval ", " aureus ",
    " denarius ", " solidus ", " sestertius ", " drachma ", " antoninianus ",
)


def _is_offtopic_media_tags(tags_text: str, query: str = "", mood: str = "") -> bool:
    """Reject off-topic stock hits (tile floors, butterflies, modern currency coins, modern offices)."""
    t_norm = re.sub(r"[^a-z0-9]+", " ", (tags_text or "").lower()).strip()
    q_norm = re.sub(r"[^a-z0-9]+", " ", (query or "").lower()).strip()
    if not t_norm:
        return False

    # ALWAYS block modern currency coins (20kr, kronor, 1933 shilling, etc.) — NEVER unblock just
    # because 'coin' or 'coins' appears in a historical query!
    if _MODERN_CURRENCY_COIN_RE.search(t_norm):
        return True

    t_pad = f" {t_norm} "
    q_pad = f" {q_norm} "

    def _matches_tag(tag_str: str, padded_haystack: str) -> bool:
        b_norm = re.sub(r"[^a-z0-9]+", " ", tag_str.lower()).strip()
        if not b_norm:
            return False
        if f" {b_norm} " in padded_haystack:
            return True
        if len(b_norm) >= 4 and not b_norm.endswith("s") and f" {b_norm}s " in padded_haystack:
            return True
        return False

    for bad in OFFTOPIC_MEDIA_TAGS:
        if _matches_tag(bad, t_pad):
            if bad == "coin":
                # Only allow genuinely ancient/roman/byzantine/medieval coins when query asks for coins
                if _matches_tag("coin", q_pad) and any(aw in t_pad for aw in _ANCIENT_COIN_ALLOW_TERMS):
                    continue
                return True
            if not _matches_tag(bad, q_pad):
                return True

    if mood in ("dark_horror", "epic_history"):
        for bad in DARK_HISTORY_EXTRA_BAD_TAGS:
            if _matches_tag(bad, t_pad) and not _matches_tag(bad, q_pad):
                return True
    return False


def _score_media_relevance(query: str, tags_text: str, mood: str = "") -> int:
    """Score how well a candidate's tags/title actually match the requested query."""
    if _is_offtopic_media_tags(tags_text, query=query, mood=mood):
        return -100
    t_low = (tags_text or "").lower()
    q_tokens = [
        tok for tok in re.findall(r"[a-z]{3,}", (query or "").lower())
        if tok not in STOP_WORDS and tok not in ("dark", "night", "old", "vintage", "photo", "image", "cinema", "cinematic")
    ]
    if not q_tokens:
        return 1
    score = 0
    for tok in q_tokens:
        if tok in t_low:
            score += 3
        elif len(tok) >= 5 and tok[:5] in t_low:
            score += 2
    return score

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
        "ancient roman marble sculpture chiaroscuro",
        "historic european architecture",
    ],
    "corporate_thriller": list(CURATED_DOC_PHOTO_QUERIES),
}

GEMINI_IMAGE_MODELS: Tuple[str, ...] = (
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
)

GEMINI_VISION_MODELS: Tuple[str, ...] = (
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
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

_GEMINI_IMAGE_QUOTA_COOLDOWN_UNTIL: float = 0.0
_GEMINI_IMAGE_QUOTA_COOLDOWN_S: float = 600.0
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


def _read_pixabay_keys() -> Tuple[str, str]:
    """Return `(pixabay_image_key, pixabay_video_key)`.
    If `pixabay_image_api_key` is set, uses it for images; otherwise falls back to `pixabay_api_key`.
    If `pixabay_api_key` is set, uses it for videos; otherwise falls back to `pixabay_image_api_key`.
    """
    try:
        settings = get_settings() or {}
        global_key = str(settings.get("pixabay_api_key") or "").strip()
        img_key = str(settings.get("pixabay_image_api_key") or "").strip() or global_key
        vid_key = global_key or img_key
        return img_key, vid_key
    except Exception:
        return "", ""


def _read_api_keys() -> Tuple[str, str]:
    try:
        settings = get_settings() or {}
        _, vid_key = _read_pixabay_keys()
        return (
            vid_key,
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


def compute_image_dhash(bgr: np.ndarray, hash_size: int = 8) -> Optional[int]:
    """Compute a fast 64-bit perceptual difference hash (dhash) to catch duplicate/near-duplicate media."""
    try:
        if bgr is None or bgr.size == 0:
            return None
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
        diff = resized[:, 1:] > resized[:, :-1]
        bits = 0
        for val in diff.flatten():
            bits = (bits << 1) | int(bool(val))
        return bits
    except Exception:
        return None


def compute_file_dhash(img_path: Path) -> Optional[int]:
    try:
        bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        return compute_image_dhash(bgr)
    except Exception:
        return None


def compute_video_dhash(video_path: Path) -> Optional[int]:
    """Extract the middle frame of a video clip and compute its 64-bit perceptual hash."""
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        try:
            n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if n_frames > 4:
                cap.set(cv2.CAP_PROP_POS_FRAMES, n_frames // 2)
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            return compute_image_dhash(frame)
        finally:
            cap.release()
    except Exception:
        return None


def is_perceptual_duplicate(
    cand_hash: Optional[int],
    used_dhashes: Optional[Set[int]],
    max_hamming: int = 8,
) -> bool:
    """Return True if `cand_hash` is visually identical or near-duplicate to any hash in `used_dhashes`."""
    if cand_hash is None or not used_dhashes:
        return False
    for existing in used_dhashes:
        if (cand_hash ^ existing).bit_count() <= max_hamming:
            return True
    return False


def _search_openverse_photos(
    client: httpx.Client,
    query: str,
    min_width: int = 640,
    mood: str = "",
) -> List[Dict[str, str]]:
    """Query Openverse (Smithsonian, Wikimedia, Flickr CC, archival collections — commercial CC licenses)."""
    clean_query = _sanitize_search_query(query, mood=mood)
    if not clean_query:
        return []
    results: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()
    try:
        r = client.get(
            "https://api.openverse.org/v1/images/",
            params={
                "q": clean_query,
                "page_size": 10,
                "license_type": "commercial",
            },
            headers={"User-Agent": WIKIMEDIA_USER_AGENT},
            timeout=9.0,
        )
        if r.status_code != 200:
            return []
        for item in r.json().get("results", []):
            title_tags = " ".join([
                str(item.get("title") or ""),
                " ".join(str(t.get("name") or "") for t in (item.get("tags") or []) if isinstance(t, dict)),
            ]).lower()
            if any(bad in title_tags for bad in PHOTO_BAD_WORDS):
                continue
            if _is_offtopic_media_tags(title_tags, query=clean_query, mood=mood):
                continue
            w = int(item.get("width") or 0)
            h = int(item.get("height") or 0)
            if w and w < max(320, min_width):
                continue
            if h and h < 200:
                continue
            url = str(item.get("url") or "").strip()
            thumb = str(item.get("thumbnail") or url).strip()
            if not url or url in seen_urls or url.lower().endswith(".svg"):
                continue
            seen_urls.add(url)
            results.append({
                "source": "openverse_photo",
                "url": url,
                "thumb": thumb,
                "tags": title_tags[:120],
            })
    except Exception:
        pass
    return results


def _download_thumb_bgr(client: httpx.Client, url: str, timeout: float = 6.5) -> Optional[np.ndarray]:
    if not url:
        return None
    headers = {"User-Agent": WIKIMEDIA_USER_AGENT} if ("wikimedia" in url.lower() or "openverse" in url.lower()) else {}
    try:
        r = client.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200 or len(r.content) < 1500:
            return None
        arr = np.frombuffer(r.content, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0 or bgr.shape[0] < 64 or bgr.shape[1] < 64:
            return None
        return bgr
    except Exception:
        return None


def _check_dark_horror_visual_guard(bgr: np.ndarray) -> Tuple[bool, str]:
    """Fast OpenCV HSV brightness / luminance-floor / blue-sky / bright-greenery / neon-LED guard
    for `dark_horror` & historical moods.
    Rejects 92%-black dead clips (`mean_v < 24.0`), sunny daytime skies, sunlit summer ruins/walls,
    bright daytime greenery, and modern electric neon/fairy-light spikes while preserving dark gothic,
    candlelit, misty, and archival visuals.
    """
    try:
        if bgr is None or bgr.size == 0 or bgr.ndim < 3:
            return False, "invalid_frame"
        h0, w0 = bgr.shape[:2]
        if max(h0, w0) > 320:
            scale = 320.0 / float(max(h0, w0))
            sample = cv2.resize(
                bgr,
                (max(16, int(round(w0 * scale))), max(16, int(round(h0 * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            sample = bgr
        hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
        h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

        mean_v = float(np.mean(v_ch))
        p80_v = float(np.percentile(v_ch, 80))
        bright_ratio = float(np.mean(v_ch >= 185))

        # Minimum luminance floor: reject 92%-black dead clips (e.g. f09 pitch-black frame)
        if mean_v < 24.0 or p80_v < 34.0:
            return False, f"too_dark_crushed(v={mean_v:.1f},p80={p80_v:.0f})"

        top_h = h_ch[: max(1, h_ch.shape[0] // 2), :]
        top_s = s_ch[: max(1, s_ch.shape[0] // 2), :]
        top_v = v_ch[: max(1, v_ch.shape[0] // 2), :]
        blue_sky_top = float(
            np.mean((top_h >= 88) & (top_h <= 135) & (top_s >= 35) & (top_v >= 135))
        )
        bright_green = float(
            np.mean((h_ch >= 30) & (h_ch <= 88) & (s_ch >= 45) & (v_ch >= 100))
        )
        # Reject modern electric cyan/blue/magenta LED & fairy lights in historical scenes
        neon_led_ratio = float(
            np.mean((h_ch >= 90) & (h_ch <= 165) & (s_ch >= 150) & (v_ch >= 170))
        )

        if mean_v > 130.0 or (mean_v > 118.0 and p80_v >= 195.0 and bright_ratio >= 0.30):
            return False, f"bright_daytime(v={mean_v:.0f})"
        if (blue_sky_top >= 0.16 and mean_v >= 96.0) or (blue_sky_top >= 0.28 and p80_v >= 150.0):
            return False, f"sunny_blue_sky({blue_sky_top:.0%})"
        if bright_green >= 0.14 and mean_v >= 88.0:
            return False, f"bright_greenery({bright_green:.0%})"
        if neon_led_ratio >= 0.045:
            return False, f"electric_neon_lights({neon_led_ratio:.1%})"
        return True, "ok"
    except Exception:
        return True, "guard_skip"


def _call_gemini_vision_json(
    payload: Dict[str, Any],
    gkey: str,
    timeout: float = 14.0,
    max_attempts_per_model: int = 3,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Resilient Gemini Vision JSON caller with 3-attempt exponential backoff on transient errors
    (HTTP 429/500/502/503/504 and network timeouts) + automatic 3-model failover
    (`gemini-flash-lite-latest` -> `gemini-2.5-flash-lite` -> `gemini-2.5-flash`).
    STRICT FAIL-CLOSED: returns `(None, err_code)` if all retries and failover models fail.
    """
    retryable_codes = {429, 500, 502, 503, 504}
    last_err = "http_0"
    headers = {"Content-Type": "application/json", "x-goog-api-key": gkey}

    for model_id in GEMINI_VISION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        for attempt in range(max(1, int(max_attempts_per_model))):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
                code = int(resp.status_code)
                if code == 200:
                    data = resp.json()
                    cands = data.get("candidates") or []
                    parts = (cands[0].get("content") or {}).get("parts") or [] if cands else []
                    raw_txt = ""
                    for part in parts:
                        if isinstance(part, dict) and part.get("text"):
                            raw_txt = str(part["text"]).strip()
                            break
                    if raw_txt.startswith("```"):
                        raw_txt = re.sub(
                            r"^```(?:json)?\s*|\s*```$",
                            "",
                            raw_txt,
                            flags=re.IGNORECASE | re.DOTALL,
                        ).strip()
                    parsed: Optional[Dict[str, Any]] = None
                    if raw_txt:
                        try:
                            obj = json.loads(raw_txt)
                            if isinstance(obj, dict):
                                parsed = obj
                        except Exception:
                            m_json = re.search(r"\{.*\}", raw_txt, re.DOTALL)
                            if m_json:
                                try:
                                    obj = json.loads(m_json.group(0))
                                    if isinstance(obj, dict):
                                        parsed = obj
                                except Exception:
                                    parsed = None
                    if parsed is not None:
                        return parsed, f"ok:{model_id}"
                    last_err = "json_parse_err"
                    if attempt + 1 < max_attempts_per_model:
                        time.sleep(0.6 * (2 ** attempt))
                        continue
                    break

                last_err = f"http_{code}"
                if code in (401, 403):
                    # Authentication failure will not recover via retry or model failover
                    return None, last_err
                if code in retryable_codes:
                    if attempt + 1 < max_attempts_per_model:
                        time.sleep(0.75 * (2 ** attempt))
                        continue
                    break
                # Non-retryable (e.g. 404 model unavailable / 400): failover immediately to next model
                break
            except httpx.TimeoutException:
                last_err = "timeout"
                if attempt + 1 < max_attempts_per_model:
                    time.sleep(0.75 * (2 ** attempt))
                    continue
                break
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                last_err = f"net_err:{type(exc).__name__}"
                if attempt + 1 < max_attempts_per_model:
                    time.sleep(0.75 * (2 ** attempt))
                    continue
                break
            except Exception as exc:
                last_err = f"vision_err:{str(exc)[:40]}"
                break

    return None, last_err


def vision_select_best_candidate(
    thumb_bgrs: List[np.ndarray],
    query: str,
    scene_context: str = "",
    mood: str = "dark_horror",
    min_score: int = 7,
    strict_vision: bool = True,
) -> Tuple[int, int, str]:
    """Multimodal Gemini Vision Critic (Batch-4 2x2 grid): inspects up to 4 candidate thumbnails
    in ONE call with 3-attempt exponential backoff + 3-model failover, evaluating BOTH:
      (a) Zero modern anachronisms for historical scenes, AND
      (b) Direct semantic relevance to the spoken narration phrase (`scene_context`) and `query`.
    ALWAYS STRICT FAIL-CLOSED: returns `(-1, 0, reason)` on missing API key, guard rejection,
    persistent API/HTTP/timeout error, JSON failure, or when no candidate reaches `min_score`.
    """
    _ = strict_vision  # Parameter retained for caller compatibility; gate is ALWAYS fail-closed.
    if not thumb_bgrs:
        return -1, 0, "no_candidates"
    gkey = _read_gemini_api_key()
    if not gkey:
        return -1, 0, "no_vision_key"

    raw_n = min(4, len(thumb_bgrs))
    kept_indices: List[int] = []
    kept_bgrs: List[np.ndarray] = []
    last_guard_reason = ""
    if mood in ("dark_horror", "epic_history"):
        for idx in range(raw_n):
            ok_g, g_why = _check_dark_horror_visual_guard(thumb_bgrs[idx])
            if ok_g:
                kept_indices.append(idx)
                kept_bgrs.append(thumb_bgrs[idx])
            else:
                last_guard_reason = g_why
        if not kept_indices:
            return -1, 0, f"visual_guard:{last_guard_reason or 'sunny_or_bright'}"
    else:
        kept_indices = list(range(raw_n))
        kept_bgrs = list(thumb_bgrs[:raw_n])

    n_c = len(kept_bgrs)
    cell_w, cell_h = 320, 220
    cols = 2 if n_c > 1 else 1
    rows = 2 if n_c > 2 else 1
    grid = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)

    for idx in range(n_c):
        bgr = kept_bgrs[idx]
        tile = _center_crop_resize_bgr(bgr, cell_w, cell_h, high_quality=False)
        # Draw high-contrast label badge ("1", "2", "3", "4") in top-left corner
        cv2.rectangle(tile, (4, 4), (48, 44), (0, 0, 0), -1)
        cv2.putText(tile, str(idx + 1), (14, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.05, (0, 255, 255), 3, cv2.LINE_AA)
        r_i, c_i = divmod(idx, cols)
        grid[r_i * cell_h : (r_i + 1) * cell_h, c_i * cell_w : (c_i + 1) * cell_w] = tile

    ok_enc, buf = cv2.imencode(".jpg", grid, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok_enc:
        return -1, 0, "encode_failed"
    b64_img = base64.b64encode(buf.tobytes()).decode("ascii")

    era_label, is_pre_modern = _extract_historical_era_lock(scene_context, "", query)
    mood_desc = {
        "dark_horror": (
            "dark gothic historical horror documentary (strictly NO sunny daytime skies, NO blue summer sky, "
            "NO bright sunlit ruins or green meadows, NO pitch-black empty frames, NO modern electric LED or fairy lights, "
            "NO modern night drone aerials of electrified cities/highways, NO modern police/Kevlar/riot vans/cars/race cars, "
            "NO modern wristwatches, NO modern hoodies/jeans/sneakers/tourists/cosplay parades, NO kitchen scales or branded products, "
            "NO modern museum plaques/glass display cases/art gallery walls, NO modern printing presses/film projectors, "
            "NO modern currency coins, NO plastic figurines/miniatures/souvenirs, NO NASA globes, NO cheerful stock photos)"
        ),
        "epic_history": (
            "authentic historical cinema documentary (strictly NO modern cars/race cars/vehicles, wristwatches, police/Kevlar gear, "
            "modern clothing/tourists/parades, modern buildings/townhouses/suburban houses, electric LED/fairy lights, "
            "kitchen scales, modern museum plaques/galleries, modern printing presses/projectors, modern coins, NASA globes, "
            "toys/figurines, or anachronistic modern objects)"
        ),
        "investigative_crime": "gritty noir investigative true-crime documentary (strictly NO cartoons, bright vacation scenes, toys, or stock clip-art)",
        "corporate_thriller": "prestige financial/corporate documentary thriller",
    }.get(mood, "prestige cinematic documentary")

    era_gate_txt = ""
    if mood in ("dark_horror", "epic_history"):
        era_hdr = f"TARGET HISTORICAL ERA: {era_label} (PRE-1920 STRICT ANACHRONISM AUDIT)" if (era_label and is_pre_modern) else "HISTORICAL DOCUMENTARY STRICT GATE"
        era_gate_txt = (
            f"GATE A — ZERO MODERN ANACHRONISMS ({era_hdr}): Immediately REJECT (best=0) ANY image showing "
            "modern cars/race cars/vans/trucks, modern wristwatches/dials, electric LED/fairy/neon lights, "
            "modern tourists/crowds/clothing (hoodies, jeans, sneakers, sleeveless dresses, cosplay/parades), "
            "modern buildings/apartments/townhouses/suburban houses/highways/airports, digital kitchen scales or branded products/logos, "
            "modern museum plaques/glass cases/gallery walls/framed photos, modern offset printing presses or IMAX/film projectors, "
            "modern 20th/21st-century coins, modern book stacks/stage auditoriums, NASA/satellite maps, "
            "sunny blue daytime sky, bright sunlit greenery, pitch-black frames, plastic figurines/souvenirs, or watermarks/text overlays.\n"
        )

    prompt_txt = (
        f"You are the ruthless Visual Director & Historical Continuity Critic for a {mood_desc}.\n"
        f"Target shot query: {query[:220]}\n"
        f"Spoken narration / scene context: {(scene_context or query)[:300]}\n"
        f"{era_gate_txt}"
        "GATE B — DIRECT SEMANTIC RELEVANCE TO SPOKEN NARRATION & TARGET QUERY: "
        "The winning image MUST directly and unmistakably depict the exact historical subject, person, event, place, or object "
        "described in BOTH the Target shot query AND Spoken narration context. "
        "IMMEDIATELY REJECT (best=0) off-topic keyword-pun collisions or unrelated nature/filler shots "
        "(e.g., reject a pine cone or volcano when narrating Bishop Nicholas, reject a Native American mural for oil painting brush, "
        "reject Washington DC or Kansas houses for Victorian London, reject a rusty bucket or generic rock on grass).\n"
        f"Inspect the {n_c} candidate image(s) labeled 1..{n_c} in the grid.\n"
        f"Pick the SINGLE best image ONLY if it passes BOTH Gate A (zero anachronisms) AND Gate B (direct semantic match) "
        f"with score >= {min_score}/10. If NONE passes BOTH gates at >= {min_score}/10, set best=0.\n"
        'Reply STRICT JSON ONLY: {"best": 0, "score": 0, "reason": "short"}'
    )
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}},
                {"text": prompt_txt},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 220,
            "temperature": 0.1,
        },
    }
    parsed, call_status = _call_gemini_vision_json(payload, gkey=gkey, timeout=14.0, max_attempts_per_model=3)
    if parsed is None:
        return -1, 0, call_status
    try:
        best_1 = int(parsed.get("best") or 0)
        score = int(parsed.get("score") or 0)
        reason = str(parsed.get("reason") or "")[:90]
        if 1 <= best_1 <= n_c and score >= min_score:
            return kept_indices[best_1 - 1], score, reason
        return -1, score, reason or "below_threshold"
    except Exception as exc:
        return -1, 0, f"vision_parse_err:{str(exc)[:40]}"


def _gemini_vision_batch_pick_best(
    thumb_bgrs: List[np.ndarray],
    query: str,
    scene_context: str = "",
    mood: str = "dark_horror",
    min_score: int = 7,
    strict_vision: bool = True,
) -> Tuple[int, int, str]:
    """Alias for `vision_select_best_candidate` used by Wikimedia Commons archival curation."""
    return vision_select_best_candidate(
        thumb_bgrs=thumb_bgrs,
        query=query,
        scene_context=scene_context,
        mood=mood,
        min_score=min_score,
        strict_vision=True,
    )


def _verify_single_image_vision(
    img_path_or_bgr: Union[Path, str, np.ndarray],
    query: str,
    scene_context: str = "",
    mood: str = "dark_horror",
    min_score: int = 7,
    strict_vision: bool = True,
) -> Tuple[bool, int, str]:
    """Validate a single image (Path or BGR ndarray) through Gemini Vision Critic (ALWAYS fail-closed)."""
    _ = strict_vision
    try:
        if isinstance(img_path_or_bgr, np.ndarray):
            bgr = img_path_or_bgr
        else:
            bgr = cv2.imread(str(img_path_or_bgr), cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            return False, 0, "unreadable_image"
        idx, score, reason = vision_select_best_candidate(
            [bgr],
            query=query,
            scene_context=scene_context,
            mood=mood,
            min_score=min_score,
            strict_vision=True,
        )
        return (idx == 0), score, reason
    except Exception as exc:
        return False, 0, f"single_vision_err:{str(exc)[:40]}"


def verify_historical_anachronism_vision(
    img_path_or_bgr: Union[Path, str, np.ndarray],
    query: str,
    lower_third_title: str = "",
    lower_third_subtitle: str = "",
    mood: str = "dark_horror",
    strict_vision: bool = True,
) -> Tuple[bool, int, str]:
    """Screen ANY image — including bespoke Google Flow AI plates — for BOTH:
      (a) Historical anachronisms (modern cars/race cars, wristwatches, police/Kevlar gear,
          electric LEDs, modern tourists/clothing, modern buildings, kitchen scales, modern museum
          plaques/galleries, modern printing presses/projectors, modern coins), AND
      (b) Direct semantic relevance to the target prompt and scene context.
    Enforces `_check_dark_horror_visual_guard` on BOTH `dark_horror` AND `epic_history`.
    Uses 3-attempt exponential backoff + 3-model failover and is ALWAYS STRICT FAIL-CLOSED:
    returns `(False, 0, err_code)` on any persistent API/HTTP/timeout failure.
    """
    _ = strict_vision  # Parameter retained for caller compatibility; ALWAYS fail-closed.
    era_label, is_pre_modern = _extract_historical_era_lock(lower_third_title, lower_third_subtitle, query)
    if isinstance(img_path_or_bgr, np.ndarray):
        bgr = img_path_or_bgr
    else:
        bgr = cv2.imread(str(img_path_or_bgr), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return False, 0, "unreadable_image"

    if mood in ("dark_horror", "epic_history"):
        ok_g, g_why = _check_dark_horror_visual_guard(bgr)
        if not ok_g:
            return False, 0, f"visual_guard:{g_why}"

    gkey = _read_gemini_api_key()
    if not gkey:
        return False, 0, "no_vision_key"

    tile = _center_crop_resize_bgr(bgr, 512, 320, high_quality=False)
    ok_enc, buf = cv2.imencode(".jpg", tile, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok_enc:
        return False, 0, "encode_failed"
    b64_img = base64.b64encode(buf.tobytes()).decode("ascii")

    ctx_meta = f"{lower_third_title} {lower_third_subtitle}".strip()
    era_clause = (
        f"TARGET HISTORICAL ERA: {era_label} (PRE-1920 STRICT ANACHRONISM AUDIT!). "
        "You MUST set anachronism=true and pass=false if the image contains ANY: "
        "modern police/riot gear/Kevlar helmets/clear ballistic shields/assault rifles, "
        "modern cars/race cars/vans/trucks/flashing blue-red LED strobes, modern wristwatches/dials, "
        "modern hoodies/puffer jackets/blue jeans/sneakers/sleeveless dresses/tourists/cosplay parades/COVID masks, "
        "modern buildings/apartments/townhouses/suburban houses/asphalt/metal crowd barriers/roll-down shop shutters, "
        "digital kitchen scales or commercial branded products/logos, modern museum plaques/glass display cases/gallery walls, "
        "modern offset printing presses or IMAX/film projectors, modern 20th/21st-century coins, NASA globes, "
        "electric LED/fairy/neon lights, or smartphones/laptops."
        if is_pre_modern
        else f"TARGET ERA/CONTEXT: {era_label or ctx_meta or query}. Reject watermarks, burned-in text overlays, modern tactical police, race cars, commercial logos, or blatantly off-topic stock."
    )
    prompt_txt = (
        "You are a ruthless Historical Continuity, Anachronism & Semantic Relevance Inspector for a prestige Netflix/BBC documentary.\n"
        f"{era_clause}\n"
        f"Scene context / title: {(ctx_meta or query)[:240]}\n"
        f"Target shot prompt: {query[:280]}\n"
        "Verify BOTH requirements:\n"
        "  1. ZERO modern anachronisms, wrong historical century clothing/vehicles/lighting, burned-in text, or watermarks.\n"
        "  2. DIRECT SEMANTIC RELEVANCE: the image must genuinely depict the subject/scene described in the Target shot prompt "
        "and Scene context (set relevant=false and pass=false for off-topic photos like a pine cone for Bishop Nicholas, "
        "a wristwatch for an ancient manuscript, a race car, or unrelated scenery).\n"
        'Reply STRICT JSON ONLY: {"pass": true, "anachronism": false, "relevant": true, "score": 8, "reason": "short"}'
    )
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}},
                {"text": prompt_txt},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 200,
            "temperature": 0.05,
        },
    }
    parsed, call_status = _call_gemini_vision_json(payload, gkey=gkey, timeout=14.0, max_attempts_per_model=3)
    if parsed is None:
        return False, 0, call_status
    try:
        passed = (
            bool(parsed.get("pass", False))
            and not bool(parsed.get("anachronism", False))
            and bool(parsed.get("relevant", True))
        )
        score = int(parsed.get("score") or (8 if passed else 2))
        reason = str(parsed.get("reason") or "")[:90]
        return (passed and score >= 7), score, reason or "rejected"
    except Exception as exc:
        return False, 0, f"anachronism_parse_err:{str(exc)[:40]}"


def _is_permissive_wikimedia_license(extmeta: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that a Wikimedia Commons asset carries a Public Domain or commercial CC license
    (Public domain, CC0, CC-BY, CC-BY-SA) and NOT NC/ND/Fair Use/Non-Free."""
    lic_short = str(((extmeta.get("LicenseShortName") or {}).get("value")) or "").strip()
    lic_name = str(((extmeta.get("License") or {}).get("value")) or "").strip()
    usage = str(((extmeta.get("UsageTerms") or {}).get("value")) or "").strip()
    combined = f"{lic_short} {lic_name} {usage}".lower()
    if not combined.strip():
        return False, "missing_license"
    for forbidden in ("non-free", "fair use", "all rights reserved", "copyrighted", "-nc", "nc-", "by-nd", "-nd"):
        if forbidden in combined:
            return False, lic_short or "restricted_license"
    for allowed in ("public domain", "pd-", "pd ", "cc0", "cc-zero", "cc-by-sa", "cc by-sa", "cc-by", "cc by"):
        if allowed in combined or combined.startswith("pd"):
            return True, lic_short or lic_name or "PD/CC"
    return False, lic_short or "unknown_license"


_WIKI_GENRE_ANCHORS: Set[str] = {
    "painting", "engraving", "woodcut", "illustration", "manuscript",
    "portrait", "fresco", "etching", "drawing", "lithograph", "codex",
    "tapestry", "mosaic", "sculpture", "bust",
}

_WIKI_FILLER_WORDS: Set[str] = {
    # English stopwords (prevent broken fragments like 'Chronograph of')
    "of", "in", "the", "on", "from", "with", "at", "to", "by", "and", "for",
    "a", "an", "as", "or", "is", "was", "were", "into", "over", "under",
    # Atmospheric/stylistic fillers — NEVER strip genre anchors (painting/engraving/woodcut/etc.)!
    "dark", "atmospheric", "cinematic", "moody", "dramatic", "shadow", "shadows",
    "chiaroscuro", "candlelit", "nocturnal", "still", "scene", "frame", "detail",
    "photo", "image", "museum", "museums",
}

_WIKI_ART_BONUS_TERMS: Tuple[str, ...] = (
    "painting", "engraving", "etching", "woodcut", "lithograph", "fresco",
    "manuscript", "codex", "illustration", "mosaic", "miniature", "tapestry",
    "leech", "bruegel", "nast", "durer", "rembrandt", "rubens", "caravaggio",
    "portrait", "broadsheet", "postcard", "184", "186", "188",
    "164", "165", "166", "17th", "18th", "19th",
)

# Boundary-safe HARD REJECT regex for modern snapshot / off-topic Wikimedia filenames & titles
# (careful: 'landscape' != 'dsc', 'climax' != 'imax', 'Caravaggio'/'Carol' != 'car', 'grace' != 'race')
_WIKI_MODERN_SNAP_CAM_RE = re.compile(
    r"(?:^|[^a-z])(?:dsc|img|pxl)(?:[_\-\s]?\d|[_\-])",
    re.IGNORECASE,
)

_WIKI_MODERN_SNAP_TITLE_RE = re.compile(
    r"(?:"
    r"(?<!\d)(?:199\d|20[012]\d)(?!\d)|"
    r"\bdsc\b|\bunsplash\b|\bpxhere\b|\bmodern\b|\bplaques?\b|\beditions?\b|"
    r"\bmuseums?\b|\bexhibits?\b|\bexhibitions?\b|\bdisplays?\b|"
    r"\bcostumes?\b|\bparades?\b|\ble\s+mans\b|\b(?:wrist)?watch(?:es)?\b|"
    r"\bautomatic\b|\bheidelberg\b|\bimax\b|\brac(?:e|es|ing)\b|\bcars?\b|"
    r"\bscales?\b|\bkitchens?\b|\bkronor\b|\bkroner\b|\b\d+\s*kr\b|\bshillings?\b|"
    r"\bnasa\b|\bnara\b|\bairports?\b|\bhighways?\b|"
    r"\bpaperbacks?\b|\bbookshops?\b|\bstorefronts?\b|\bselfies?\b|\bcosplay\b|"
    r"\btourists?\b|\bsouvenirs?\b|\bprojectors?\b|\bkrampuslauf\b|\bperchtenlauf\b|"
    r"\bethanol\b|\bjoop\b|\bwestg\b|\bbookshelf\b"
    r")",
    re.IGNORECASE,
)

_WIKI_HISTORICAL_ART_CATS_RE = re.compile(
    r"\b(?:"
    r"paintings?|engravings?|woodcuts?|manuscripts?|illustrations?|"
    r"historical\s+maps?|sculptures?|etchings?|lithographs?|fresco(?:es)?|"
    r"mosaics?|tapestries|illuminated\s+manuscripts?|byzantine\s+icons?"
    r")\b",
    re.IGNORECASE,
)

_WIKI_MODERN_CAT_REJECT_RE = re.compile(
    r"\b(?:"
    r"unsplash|pxhere|automobiles|race\s+cars?|le\s+mans|wristwatches|"
    r"nasa|nara|coins\s+of\s+sweden|modern\s+architecture|parades|"
    r"krampuslauf|perchtenlauf|cosplay|museum\s+interiors?|commemorative\s+plaques?|"
    r"airports?|highways?|kitchen\s+scales?|imax|film\s+projectors?|offset\s+printing"
    r")\b",
    re.IGNORECASE,
)

_WIKI_MODERN_DESC_REJECT_RE = re.compile(
    r"\b(?:"
    r"unsplash|pxhere|le\s+mans|race\s+car|ford\s+ecoboost|wristwatch|chronograph\s+watch|"
    r"heidelberg|imax|film\s+projector|kitchen\s+scale|digital\s+scale|ethanol\s+burn|"
    r"joop|nasa|nara|airport|highway|kronor|kroner|\d+\s*kr\b|shillings?|"
    r"cosplay|krampuslauf|perchtenlauf|parade|modern\s+printing\s+press|selfie|souvenir|tourist"
    r")\b",
    re.IGNORECASE,
)


def _strip_html_tags(raw: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(raw or ""))).strip()


def _sanitize_search_query(query: str, mood: str = "") -> str:
    """Normalize a search query and strip 'museum'/'museums' so museum-hallway / tourist photos aren't lured."""
    q = _normalize_query(query, "")
    if not q:
        return ""
    if mood in ("dark_horror", "epic_history", ""):
        q = re.sub(r"\bmuseums?\b", "", q, flags=re.IGNORECASE)
        q = re.sub(r"\s{2,}", " ", q).strip()
    return q


def _build_wikimedia_search_queries(query_en: str) -> List[str]:
    """Build meaningful 4-6 token Wikimedia CirrusSearch queries preserving genre anchors
    (painting, engraving, woodcut, illustration, manuscript, portrait, fresco) and NEVER
    blindly truncating to 2-word fragments (`core_2`).
    """
    norm_q = _sanitize_search_query(query_en, mood="dark_horror")
    if not norm_q:
        return []
    queries: List[str] = [norm_q]
    seen_low: Set[str] = {norm_q.lower()}

    core_tokens = [
        tok for tok in re.findall(r"[A-Za-z0-9'-]+", norm_q)
        if tok.lower() not in _WIKI_FILLER_WORDS and len(tok) >= 2
    ]
    if core_tokens:
        # Keep 4-6 core tokens intact (NEVER truncate >=4-token queries to 2 words!)
        if len(core_tokens) >= 4:
            q6 = " ".join(core_tokens[:6]).strip()
            if q6 and q6.lower() not in seen_low:
                queries.append(q6)
                seen_low.add(q6.lower())
            if len(core_tokens) > 4:
                # Preserve any trailing genre anchor (painting/engraving/woodcut/manuscript/etc.)
                tail_anchors = [t for t in core_tokens[4:] if t.lower() in _WIKI_GENRE_ANCHORS]
                q4_tokens = list(core_tokens[:4])
                if tail_anchors and tail_anchors[0].lower() not in {t.lower() for t in q4_tokens}:
                    q4_tokens.append(tail_anchors[0])
                q4 = " ".join(q4_tokens).strip()
                if q4 and q4.lower() not in seen_low:
                    queries.append(q4)
                    seen_low.add(q4.lower())
        else:
            q_all = " ".join(core_tokens).strip()
            if q_all and q_all.lower() not in seen_low:
                queries.append(q_all)
                seen_low.add(q_all.lower())
    return queries


def _check_wikimedia_modern_metadata(
    title_raw: str,
    extmeta: Dict[str, Any],
    mood: str = "",
) -> Tuple[bool, str, bool]:
    """HARD-REJECT modern snapshots, modern objects, and post-1960 non-art photo uploads using
    filename/title + `extmetadata` (`DateTimeOriginal`, `ImageDescription`, `Categories`).
    Returns `(is_rejected, reason, is_historical_art_cat)`.
    """
    _ = mood
    if not isinstance(extmeta, dict):
        extmeta = {}
    clean_title = re.sub(r"^file:", "", str(title_raw or ""), flags=re.IGNORECASE).strip()
    if _WIKI_MODERN_SNAP_CAM_RE.search(clean_title):
        return True, "modern_cam_prefix", False
    title_norm = re.sub(r"[^a-z0-9]+", " ", clean_title.lower()).strip()
    m_title = _WIKI_MODERN_SNAP_TITLE_RE.search(title_norm)
    if m_title:
        return True, f"modern_title:{m_title.group(0)}", False

    cats_raw = _strip_html_tags(((extmeta.get("Categories") or {}).get("value")) or "")
    desc_raw = _strip_html_tags(((extmeta.get("ImageDescription") or {}).get("value")) or "")
    dto_raw = _strip_html_tags(((extmeta.get("DateTimeOriginal") or {}).get("value")) or "")

    is_historical_art_cat = bool(cats_raw and _WIKI_HISTORICAL_ART_CATS_RE.search(cats_raw))

    if cats_raw:
        m_cat = _WIKI_MODERN_CAT_REJECT_RE.search(cats_raw)
        if m_cat:
            return True, f"modern_cat:{m_cat.group(0)}", is_historical_art_cat

    if desc_raw:
        m_desc = _WIKI_MODERN_DESC_REJECT_RE.search(desc_raw)
        if m_desc:
            return True, f"modern_desc:{m_desc.group(0)}", is_historical_art_cat

    # Inspect DateTimeOriginal: hard-reject uploads dated >= 1960 unless Categories clearly contain
    # Paintings, Engravings, Woodcuts, Manuscripts, Illustrations, Historical maps, or Sculptures.
    if dto_raw:
        dto_years = [int(y) for y in re.findall(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", dto_raw)]
        if dto_years and min(dto_years) >= 1960 and not is_historical_art_cat:
            return True, f"dated_{min(dto_years)}_non_art", False

    return False, "", is_historical_art_cat


def fetch_wikimedia_commons_archival_photo(
    query_en: str,
    out_dir: Path,
    prefix: str = "wiki",
    is_wide: bool = True,
    topic_context: str = "",
    mood: str = "dark_horror",
    used_urls: Optional[Set[str]] = None,
    used_dhashes: Optional[Set[int]] = None,
    strict_vision: bool = True,
) -> Optional[Path]:
    """Priority 1 Free Archival Source: Query Wikimedia Commons API (`action=query`, `generator=search`,
    `gsrnamespace=6`, `prop=imageinfo`, `iiprop=url|extmetadata|dimensions`, `iiurlwidth=1920`),
    filtering strictly for:
      - Meaningful 4-6 token queries preserving genre anchors (zero `core_2` truncation)
      - HARD REJECT of modern snapshot filenames & post-1960 non-art `extmetadata`
      - `base_rel >= 3` BEFORE any museum `PD-old`/`PD-Art` bonus (zero bonus for `CC0`!)
      - Bitmap images (`image/jpeg`, `image/png`) with `width >= 900`
      - Aspect ratio matching `16:9` / landscape when `is_wide=True`
      - Valid Public Domain / CC0 / CC-BY / CC-BY-SA license via `extmetadata`
      - MANDATORY Batch-4 Gemini Vision Critic (`min_score=7`, strict fail-closed — ZERO 0ms bypass!)
      - Global perceptual `dhash` deduplication (`_SEEN_PHOTO_DHASHES` + optional `used_dhashes`)
    """
    _ = strict_vision  # 0ms Vision bypass is permanently abolished; Batch-4 Vision Critic ALWAYS runs.
    queries_to_try = _build_wikimedia_search_queries(query_en)
    if not queries_to_try:
        return None
    norm_q = queries_to_try[0]
    out_path_dir = Path(out_dir)
    out_path_dir.mkdir(parents=True, exist_ok=True)
    used = used_urls if used_urls is not None else set()
    dhash_pool: Set[int] = _SEEN_PHOTO_DHASHES | (used_dhashes if used_dhashes is not None else set())
    allowed_mimes = {"image/jpeg", "image/png"}

    candidates: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()
    with httpx.Client(follow_redirects=True, timeout=16.0) as client:
        for q in queries_to_try:
            try:
                resp = client.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={
                        "action": "query",
                        "generator": "search",
                        "gsrnamespace": 6,
                        "gsrsearch": f"{q} filetype:bitmap",
                        "gsrlimit": 16,
                        "prop": "imageinfo",
                        "iiprop": "url|extmetadata|dimensions|mime|size",
                        "iiurlwidth": 1920,
                        "format": "json",
                    },
                    headers={"User-Agent": WIKIMEDIA_USER_AGENT},
                    timeout=12.0,
                )
                if resp.status_code != 200:
                    continue
                pages = (resp.json().get("query") or {}).get("pages") or {}
                for page in pages.values():
                    title_raw = str(page.get("title") or "")
                    title_l = title_raw.lower()
                    if any(bad in title_l for bad in PHOTO_BAD_WORDS):
                        continue
                    if _is_offtopic_media_tags(title_l, query=q, mood=mood):
                        continue
                    ii_list = page.get("imageinfo") or []
                    if not ii_list or not isinstance(ii_list[0], dict):
                        continue
                    ii = ii_list[0]
                    mime = str(ii.get("mime") or "").lower()
                    if mime not in allowed_mimes:
                        continue
                    orig_w = int(ii.get("width") or 0)
                    orig_h = int(ii.get("height") or 0)
                    thumb_w = int(ii.get("thumbwidth") or orig_w)
                    thumb_h = int(ii.get("thumbheight") or orig_h)
                    eff_w = max(orig_w, thumb_w)
                    eff_h = orig_h if orig_w >= thumb_w else thumb_h
                    if eff_w < 900 or eff_h < 400:
                        continue
                    ar = eff_w / max(1.0, float(eff_h))
                    if is_wide:
                        if ar < 0.92 or ar > 2.65:
                            continue
                    else:
                        if ar < 0.42 or ar > 1.45:
                            continue
                    extmeta = ii.get("extmetadata") if isinstance(ii.get("extmetadata"), dict) else {}
                    ok_lic, lic_lbl = _is_permissive_wikimedia_license(extmeta)
                    if not ok_lic:
                        continue

                    # HARD REJECT modern snapshots / post-1960 non-art uploads (NEVER soft -6!)
                    is_modern_rej, _, is_historical_art_cat = _check_wikimedia_modern_metadata(
                        title_raw, extmeta, mood=mood
                    )
                    if is_modern_rej:
                        continue

                    # Require genuine lexical relevance BEFORE any PD/art bonus!
                    base_rel = _score_media_relevance(q, title_l, mood=mood)
                    if base_rel < 3:
                        continue

                    full_url = str(ii.get("thumburl") or ii.get("url") or "").strip()
                    if not full_url or full_url in used or full_url in seen_urls:
                        continue
                    # Build a lighter 480px preview URL if thumburl is 1920px
                    thumb_preview = re.sub(r"/\d+px-", "/480px-", full_url) if "/1920px-" in full_url else full_url

                    # Separate CC0 (ZERO bonus — Unsplash/PxHere!) from genuine museum PD-old / PD-Art
                    lic_short_l = str(((extmeta.get("LicenseShortName") or {}).get("value")) or "").lower()
                    lic_name_l = str(((extmeta.get("License") or {}).get("value")) or "").lower()
                    lic_combined = f"{lic_lbl.lower()} {lic_short_l} {lic_name_l}"
                    is_cc0 = ("cc0" in lic_combined) or ("cc-zero" in lic_combined)
                    is_pd_museum = (
                        (not is_cc0)
                        and (
                            "pd-art" in lic_combined
                            or "pd-old" in lic_combined
                            or "pd-1923" in lic_combined
                            or "pd-us-expired" in lic_combined
                            or (("public domain" in lic_combined or lic_short_l.startswith("pd")) and is_historical_art_cat)
                        )
                    )

                    rel_score = base_rel
                    if is_pd_museum:
                        rel_score += 5
                    if any(term in title_l for term in _WIKI_ART_BONUS_TERMS):
                        rel_score += 4
                    if is_historical_art_cat:
                        rel_score += 2
                    if is_wide and ar >= 1.18:
                        rel_score += 2

                    seen_urls.add(full_url)
                    candidates.append({
                        "url": full_url,
                        "thumb": thumb_preview,
                        "title": title_raw,
                        "license": lic_lbl,
                        "is_pd_museum": is_pd_museum,
                        "base_rel": base_rel,
                        "width": eff_w,
                        "height": eff_h,
                        "ar_dist": abs(ar - (16.0 / 9.0 if is_wide else 9.0 / 16.0)),
                        "rel_score": rel_score,
                    })
                if len(candidates) >= 8:
                    break
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda c: (-int(c["rel_score"]), float(c["ar_dist"])))

        cand_items: List[Dict[str, Any]] = []
        cand_bgrs: List[np.ndarray] = []
        for item in candidates[:12]:
            if len(cand_items) >= 4:
                break
            tbgr = _download_thumb_bgr(client, item["thumb"], timeout=8.0)
            if tbgr is None and item["thumb"] != item["url"]:
                tbgr = _download_thumb_bgr(client, item["url"], timeout=10.0)
            if tbgr is None:
                continue
            if mood in ("dark_horror", "epic_history"):
                ok_g, _ = _check_dark_horror_visual_guard(tbgr)
                if not ok_g:
                    continue
            dh = compute_image_dhash(tbgr)
            if is_perceptual_duplicate(dh, dhash_pool, max_hamming=8):
                continue
            cand_items.append(item)
            cand_bgrs.append(tbgr)

        if not cand_items:
            return None

        ctx_str = (topic_context or norm_q).strip()
        best_i, v_score, v_reason = _gemini_vision_batch_pick_best(
            cand_bgrs,
            query=norm_q,
            scene_context=ctx_str,
            mood=mood,
            min_score=7,
            strict_vision=True,
        )
        if best_i < 0:
            print(
                f"[DocMedia] Wikimedia Vision rejected all {len(cand_items)} plates for '{norm_q}' ({v_score}/10: {v_reason})",
                flush=True,
            )
            return None
        winner = cand_items[best_i]

        q_hash = hashlib.sha256(norm_q.lower().encode("utf-8")).hexdigest()[:12]
        dl = _download_and_validate_photo(
            client,
            winner["url"],
            source="wikimedia_commons_archival",
            q_hash=q_hash,
            min_width=900,
            timeout=18.0,
        )
        if dl is None:
            return None
        cached_path, w_px, h_px = dl
        final_dh = compute_file_dhash(cached_path)
        if is_perceptual_duplicate(final_dh, dhash_pool, max_hamming=8):
            return None
        if final_dh is not None:
            _SEEN_PHOTO_DHASHES.add(final_dh)
            if used_dhashes is not None:
                used_dhashes.add(final_dh)
        used.add(winner["url"])

        url_hash = hashlib.sha256(winner["url"].encode("utf-8")).hexdigest()[:12]
        dest_file = out_path_dir / f"{_safe_tag(prefix)}_{url_hash}.jpg"
        try:
            shutil.copy2(cached_path, dest_file)
        except Exception:
            dest_file = cached_path
        print(
            f"[DocMedia] Wikimedia archival plate APPROVED ({winner['license']} | {w_px}x{h_px} | "
            f"vision={v_score}/10: {v_reason}) -> {dest_file.name}",
            flush=True,
        )
        return dest_file


def verify_video_frame_vision(
    video_path: Path,
    query: str,
    scene_context: str = "",
    mood: str = "dark_horror",
    min_score: int = 7,
    strict_vision: bool = True,
) -> Tuple[bool, int, str]:
    """Extract a representative frame from a downloaded video and verify semantic relevance via Gemini Vision.
    ALWAYS FAIL-CLOSED (`return False, 0, reason`).
    """
    _ = strict_vision
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False, 0, "cannot_open"
        try:
            n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if n_frames > 6:
                cap.set(cv2.CAP_PROP_POS_FRAMES, n_frames // 3)
            ok, frame = cap.read()
            if not ok or frame is None:
                return False, 0, "empty_frame"
        finally:
            cap.release()
        idx, score, reason = vision_select_best_candidate(
            [frame],
            query=query,
            scene_context=scene_context,
            mood=mood,
            min_score=min_score,
            strict_vision=True,
        )
        return (idx == 0), score, reason
    except Exception as exc:
        return False, 0, f"verify_err:{str(exc)[:40]}"


def _search_pixabay_photos(
    client: httpx.Client,
    query: str,
    api_key: str,
    min_width: int = 640,
    mood: str = "",
) -> List[Dict[str, str]]:
    if not api_key:
        return []
    clean_query = _sanitize_search_query(query, mood=mood)
    if not clean_query:
        return []
    scored_results: List[Tuple[int, Dict[str, str]]] = []
    seen_urls: Set[str] = set()

    queries_to_try = [clean_query]
    short_q = _shorten_query(clean_query, max_words=4)
    if short_q and short_q.lower() != clean_query.lower():
        queries_to_try.append(short_q)

    for q in queries_to_try:
        try:
            r = client.get(
                "https://pixabay.com/api/",
                params={
                    "key": api_key,
                    "q": q,
                    "image_type": "photo",
                    "per_page": 12,
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
                rel_score = _score_media_relevance(q, tags, mood=mood)
                if rel_score <= 0:
                    continue
                img_w = int(hit.get("imageWidth") or hit.get("webformatWidth") or 0)
                img_h = int(hit.get("imageHeight") or hit.get("webformatHeight") or 0)
                if img_w and img_w < max(320, min_width):
                    continue
                if img_h and img_h < 200:
                    continue
                url = str(hit.get("largeImageURL") or hit.get("webformatURL") or "").strip()
                thumb = str(hit.get("previewURL") or hit.get("webformatURL") or url).strip()
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    scored_results.append((rel_score, {"source": "pixabay_photo", "url": url, "thumb": thumb}))
            if scored_results:
                break
        except Exception:
            continue
    scored_results.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored_results]


def _search_wikimedia_photos(
    client: httpx.Client,
    query: str,
    min_width: int = 640,
    mood: str = "",
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()

    queries_to_try = _build_wikimedia_search_queries(query)
    if not queries_to_try:
        return []

    allowed_mimes = {"image/jpeg", "image/png", "image/webp"}
    for q in queries_to_try:
        try:
            r = client.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrsearch": f"{q} filetype:bitmap",
                    "gsrlimit": 12,
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata|size|mime",
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
                title_raw = str(page.get("title") or "")
                title_l = title_raw.lower()
                if any(bad in title_l for bad in PHOTO_BAD_WORDS):
                    continue
                if _is_offtopic_media_tags(title_l, query=q, mood=mood):
                    continue
                ii = (page.get("imageinfo") or [{}])[0]
                mime = str(ii.get("mime") or "").lower()
                if mime not in allowed_mimes:
                    continue
                extmeta = ii.get("extmetadata") if isinstance(ii.get("extmetadata"), dict) else {}
                ok_lic, _ = _is_permissive_wikimedia_license(extmeta)
                if not ok_lic:
                    continue
                is_modern_rej, _, is_historical_art_cat = _check_wikimedia_modern_metadata(
                    title_raw, extmeta, mood=mood
                )
                if is_modern_rej:
                    continue
                base_rel = _score_media_relevance(q, title_l, mood=mood)
                if base_rel < 3:
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
                thumb_preview = re.sub(r"/\d+px-", "/480px-", url) if "/1280px-" in url else url
                bonus = 3 if is_historical_art_cat else 0
                priority = (0 if w >= min_width else 10) - (base_rel + bonus)
                seen_urls.add(url)
                results.append({
                    "source": "wikimedia_photo",
                    "url": url,
                    "thumb": thumb_preview,
                    "priority": str(priority),
                })
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
    global _GEMINI_IMAGE_QUOTA_COOLDOWN_UNTIL
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

    if time.monotonic() < _GEMINI_IMAGE_QUOTA_COOLDOWN_UNTIL:
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

                    _GEMINI_IMAGE_QUOTA_COOLDOWN_UNTIL = 0.0
                    print(
                        f"[DocMedia] Bespoke Gemini photo ready ({model_id}): {cached_jpg.name} ({w}x{h}) | q='{clean_prompt[:55]}'",
                        flush=True,
                    )
                    return _materialize_photo_in_work_dir(cached_jpg, work_dir, tag, p_hash)
                except Exception:
                    break

    if quota_hits >= len(GEMINI_IMAGE_MODELS):
        _GEMINI_IMAGE_QUOTA_COOLDOWN_UNTIL = time.monotonic() + _GEMINI_IMAGE_QUOTA_COOLDOWN_S
        print(
            "[DocMedia] Gemini Image API quota currently throttled (429) — cooling down 10 min and seamlessly blending Pixabay & Wikimedia archival photos.",
            flush=True,
        )
    return None


def _fetch_pollinations_photo(
    client: httpx.Client,
    query: str,
    q_hash: str,
    used_urls: Set[str],
    min_width: int = 640,
    mood: str = "",
    aspect_ratio: str = "16:9",
) -> Optional[Tuple[Path, str, int, int]]:
    seed = int(q_hash[:8], 16) % 99999
    if used_urls:
        seed = (seed + len(used_urls) * 37) % 99999
    style_hint = {
        "dark_horror": "dark atmospheric 35mm cinema still, chiaroscuro candlelight, moody horror history documentary, no text",
        "epic_history": "authentic historical documentary photograph, archival 35mm film grain, museum lighting, no text",
        "investigative_crime": "gritty nocturnal investigative documentary photograph, 35mm noir cinema lighting, no text",
    }.get(mood, "editorial documentary photograph, 35mm film photography, realistic natural lighting, sharp focus, no text")
    ar_clean = "9:16" if str(aspect_ratio or "16:9").strip() == "9:16" else "16:9"
    pw, ph = (768, 1344) if ar_clean == "9:16" else (1280, 720)
    prompt = f"{query}, {style_hint}"
    url = (
        f"https://image.pollinations.ai/prompt/{quote(prompt)}"
        f"?width={pw}&height={ph}&model=flux&nologo=true&seed={seed}"
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
    scene_context: str = "",
    used_dhashes: Optional[Set[int]] = None,
    strict_vision: bool = True,
    allow_duplicate: bool = False,
) -> Optional[Path]:
    """Fetch a bespoke hero photo OR Vision-verified real archival Openverse / Wikimedia / Pixabay photograph."""
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
        scene_context=scene_context,
        used_dhashes=used_dhashes,
        strict_vision=strict_vision,
        allow_duplicate=allow_duplicate,
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
    scene_context: str = "",
    used_dhashes: Optional[Set[int]] = None,
    strict_vision: bool = True,
    allow_duplicate: bool = False,
) -> Optional[Path]:
    """Fetch a Vision-verified documentary photograph (Openverse / Wikimedia / Pixabay) OR bespoke
    Google Flow Pro (`Nano Banana 2.1`) / Gemini / Pollinations dark-cinema plate, enforcing:
      1. Multimodal Gemini Vision Critic (score >= 7/10; rejects paragliders, modern buses, tropical
         resorts, cosplayers, watermarks, anachronisms BEFORE accepting!).
      2. 64-bit Perceptual dhash deduplication across the entire video (zero visual repetition!).
    """
    resolved_mood = _infer_media_mood(f"{query} {bespoke_prompt_en}", mood)
    mood_defaults = MOOD_DOC_PHOTO_QUERIES.get(resolved_mood, CURATED_DOC_PHOTO_QUERIES)
    norm_q = _normalize_query(query, mood_defaults[0])
    ar_clean = "9:16" if str(aspect_ratio or "16:9").strip() == "9:16" else "16:9"
    used = used_urls if used_urls is not None else set()
    dhashes = used_dhashes if used_dhashes is not None else set()
    q_hash = hashlib.sha256(norm_q.lower().encode("utf-8")).hexdigest()[:16]
    flow_key_payload = f"{norm_q.lower()}||{str(bespoke_prompt_en or '').strip().lower()}||{ar_clean}"
    flow_hash = hashlib.sha256(flow_key_payload.encode("utf-8")).hexdigest()[:16]
    eff_min_w = max(320, int(min_width))
    ctx_text = (scene_context or bespoke_prompt_en or norm_q).strip()

    def _check_dhash_ok(img_path: Path) -> bool:
        if allow_duplicate:
            return True
        dh = compute_file_dhash(img_path)
        if is_perceptual_duplicate(dh, dhashes, max_hamming=8):
            return False
        if dh is not None:
            dhashes.add(dh)
        return True

    def _orientation_matches_ar(w_px: int, h_px: int) -> bool:
        if ar_clean == "9:16":
            return h_px >= w_px * 1.25
        return w_px >= h_px * 1.25

    # 0. Fast persistent cache lookup by query hash (respecting used_urls, AR, dhash AND Vision check)
    effective_strict = strict_vision or (resolved_mood in ("dark_horror", "epic_history"))
    cached_entries = _load_photo_query_index(q_hash)
    for entry in cached_entries:
        c_url = str(entry.get("url") or "")
        c_file = DOC_PHOTO_CACHE_DIR / str(entry.get("file") or "")
        c_src = str(entry.get("source") or "")
        if not c_url or c_url in used:
            continue
        ok, cw, ch = _validate_photo_file(c_file, min_width=min(eff_min_w, 320))
        if not ok:
            continue
        if c_src in ("google_flow_bespoke", "google_flow_pro_nano_banana_2"):
            c_ar = str(entry.get("aspect_ratio") or "").strip()
            if (c_ar and c_ar != ar_clean) or not _orientation_matches_ar(cw, ch):
                continue
        if effective_strict:
            bgr_c = cv2.imread(str(c_file), cv2.IMREAD_COLOR)
            if bgr_c is not None:
                if c_src in ("google_flow_bespoke", "google_flow_pro_nano_banana_2"):
                    if resolved_mood in ("dark_horror", "epic_history"):
                        ok_a, a_sc, a_why = verify_historical_anachronism_vision(
                            bgr_c,
                            query=bespoke_prompt_en or norm_q,
                            lower_third_title=ctx_text,
                            mood=resolved_mood,
                            strict_vision=True,
                        )
                        if not ok_a:
                            print(f"[DocMedia] Vision rejected anachronistic cached Flow photo ({a_sc}/10: {a_why}) -> {c_file.name}", flush=True)
                            continue
                else:
                    v_idx, v_sc, v_why = vision_select_best_candidate(
                        [bgr_c],
                        query=norm_q,
                        scene_context=ctx_text,
                        mood=resolved_mood,
                        min_score=7,
                        strict_vision=True,
                    )
                    if v_idx != 0:
                        print(f"[DocMedia] Vision rejected cached photo ({v_sc}/10: {v_why}) -> {c_file.name}", flush=True)
                        continue
        if not _check_dhash_ok(c_file):
            continue
        used.add(c_url)
        url_hash = hashlib.sha256(c_url.encode("utf-8")).hexdigest()[:16]
        return _materialize_photo_in_work_dir(c_file, work_dir, tag, url_hash)

    pixabay_key, _ = _read_pixabay_keys()

    def _record_and_return(cached_path: Path, src_url: str, src_name: str, w: int, h: int) -> Optional[Path]:
        if not _check_dhash_ok(cached_path):
            return None
        used.add(src_url)
        entries = _load_photo_query_index(q_hash)
        if not any(e.get("url") == src_url for e in entries):
            entries.append({
                "url": src_url,
                "file": cached_path.name,
                "source": src_name,
                "width": w,
                "height": h,
                "aspect_ratio": ar_clean,
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

    with httpx.Client(follow_redirects=True, timeout=16.0) as client:
        def _try_vision_verified_stock(search_q: str) -> Optional[Path]:
            """Collect up to 4 candidate thumbnails across Wikimedia + Openverse + Pixabay,
            evaluate ALL 4 simultaneously in ONE 1-second Gemini Vision Critic call, and ONLY
            download full-res of the winning candidate if score >= 7/10!
            """
            clean_sq = _sanitize_search_query(search_q, mood=resolved_mood) or search_q
            pool: List[Dict[str, str]] = []
            # Historical subjects prioritize Wikimedia + Openverse ahead of generic Pixabay
            if resolved_mood in ("dark_horror", "epic_history"):
                pool.extend(_search_wikimedia_photos(client, clean_sq, min_width=eff_min_w, mood=resolved_mood)[:4])
                pool.extend(_search_openverse_photos(client, clean_sq, min_width=eff_min_w, mood=resolved_mood)[:4])
                if pixabay_key:
                    pool.extend(_search_pixabay_photos(client, clean_sq, pixabay_key, min_width=eff_min_w, mood=resolved_mood)[:4])
            else:
                if pixabay_key:
                    pool.extend(_search_pixabay_photos(client, clean_sq, pixabay_key, min_width=eff_min_w, mood=resolved_mood)[:4])
                pool.extend(_search_openverse_photos(client, clean_sq, min_width=eff_min_w, mood=resolved_mood)[:4])
                pool.extend(_search_wikimedia_photos(client, clean_sq, min_width=eff_min_w, mood=resolved_mood)[:4])

            fresh: List[Dict[str, str]] = []
            seen_u: Set[str] = set()
            for item in pool:
                u = str(item.get("url") or "")
                if not u or u in used or u in seen_u:
                    continue
                seen_u.add(u)
                fresh.append(item)

            if not fresh:
                return None

            if not effective_strict:
                for item in fresh[:6]:
                    dl = _download_and_validate_photo(client, item["url"], item["source"], q_hash, min_width=min(eff_min_w, 320))
                    if dl is not None:
                        p, w, h = dl
                        res = _record_and_return(p, item["url"], item["source"], w, h)
                        if res is not None:
                            return res
                return None

            # Download up to 4 small thumbnails (fast, ~30KB each) and run Batch-4 Gemini Vision selection!
            cand_items: List[Dict[str, str]] = []
            cand_bgrs: List[np.ndarray] = []
            for item in fresh[:10]:
                if len(cand_items) >= 4:
                    break
                t_url = str(item.get("thumb") or item["url"])
                tbgr = _download_thumb_bgr(client, t_url)
                if tbgr is None:
                    continue
                if resolved_mood in ("dark_horror", "epic_history"):
                    ok_g, _ = _check_dark_horror_visual_guard(tbgr)
                    if not ok_g:
                        continue
                dh = compute_image_dhash(tbgr)
                if not allow_duplicate and is_perceptual_duplicate(dh, dhashes, max_hamming=8):
                    continue
                cand_items.append(item)
                cand_bgrs.append(tbgr)

            if not cand_items:
                return None

            best_i, v_score, v_reason = vision_select_best_candidate(
                cand_bgrs,
                query=clean_sq,
                scene_context=ctx_text,
                mood=resolved_mood,
                min_score=7,
                strict_vision=True,
            )
            if best_i < 0:
                print(
                    f"[DocMedia] Vision rejected all {len(cand_items)} stock hits for '{clean_sq}' ({v_score}/10: {v_reason})",
                    flush=True,
                )
                return None

            winner = cand_items[best_i]
            dl = _download_and_validate_photo(client, winner["url"], winner["source"], q_hash, min_width=min(eff_min_w, 320))
            if dl is not None:
                p, w, h = dl
                print(
                    f"[DocMedia] Vision APPROVED {winner['source']} ({v_score}/10: {v_reason}) | q='{clean_sq}'",
                    flush=True,
                )
                return _record_and_return(p, winner["url"], winner["source"], w, h)
            return None

        def _try_google_flow_bespoke() -> Optional[Path]:
            try:
                from engine.google_flow_bridge import generate_flow_bespoke_photo_sync

                raw_flow_prompt = bespoke_prompt_en.strip() if bespoke_prompt_en.strip() else norm_q
                flow_prompt = (
                    _enforce_historical_era_prompt_lock(raw_flow_prompt, ctx_text, "")
                    if resolved_mood in ("dark_horror", "epic_history")
                    else raw_flow_prompt
                )
                flow_target = DOC_PHOTO_CACHE_DIR / f"flow_{flow_hash}.jpg"
                flow_path = generate_flow_bespoke_photo_sync(
                    prompt_en=flow_prompt,
                    out_path=flow_target,
                    aspect_ratio=ar_clean,
                    mood=resolved_mood,
                    try_browser=True,
                )
                if flow_path is not None and flow_path.exists():
                    ok_v, fw, fh = _validate_photo_file(flow_path, min_width=320, min_height=200)
                    if ok_v and _orientation_matches_ar(fw, fh):
                        if effective_strict and resolved_mood in ("dark_horror", "epic_history"):
                            ok_a, a_sc, a_why = verify_historical_anachronism_vision(
                                flow_path,
                                query=flow_prompt,
                                lower_third_title=ctx_text,
                                mood=resolved_mood,
                                strict_vision=True,
                            )
                            if not ok_a:
                                print(
                                    f"[DocMedia] Vision rejected anachronistic Flow bespoke photo ({a_sc}/10: {a_why}) -> {flow_path.name}",
                                    flush=True,
                                )
                                return None
                        return _record_and_return(flow_path, f"flow://{flow_hash}", "google_flow_bespoke", fw, fh)
            except Exception:
                pass
            return None

        # 0.5 Priority 1 Free Archival Source (Wikimedia Commons API with PD/CC license + Vision + dHash)
        if resolved_mood in ("dark_horror", "epic_history"):
            wiki_hit = fetch_wikimedia_commons_archival_photo(
                query_en=norm_q,
                out_dir=Path(work_dir),
                prefix=f"wiki_{_safe_tag(tag)}",
                is_wide=(ar_clean != "9:16"),
                topic_context=ctx_text,
                mood=resolved_mood,
                used_urls=used,
                used_dhashes=dhashes,
                strict_vision=True,
            )
            if wiki_hit is not None and wiki_hit.exists():
                return wiki_hit

        # 1. Try Vision-verified archival/stock photography FIRST (fast, ~1.5s, 0% junk)
        hit = _try_vision_verified_stock(norm_q)
        if hit is not None:
            return hit

        # 2. If Vision rejected stock (or no stock found), generate era-locked bespoke cinema art via Google Flow Pro!
        flow_hit = _try_google_flow_bespoke()
        if flow_hit is not None:
            return flow_hit

        # 3. Last resort: try mood-matched curated queries ONLY when not historical (never pollute history docs!)
        if resolved_mood not in ("dark_horror", "epic_history") and not effective_strict:
            fb_pool = list(mood_defaults)
            start_idx = int(q_hash[:4], 16) % len(fb_pool)
            for offset in range(min(3, len(fb_pool))):
                fb_q = fb_pool[(start_idx + offset) % len(fb_pool)]
                fb_hit = _try_vision_verified_stock(fb_q)
                if fb_hit is not None:
                    return fb_hit

    if allow_duplicate:
        all_cached = sorted(
            [p for p in DOC_PHOTO_CACHE_DIR.glob("*.jpg") if p.is_file() and (p.name.startswith("flow_") or p.name.startswith("photo_"))],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in all_cached:
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


def _guided_filter_gray(
    guide_f32: np.ndarray,
    src_f32: np.ndarray,
    r: int = 6,
    eps: float = 1e-3,
) -> np.ndarray:
    """Fast OpenCV box-filter Guided Image Filter (He et al.) aligning a low-res mask
    sharply onto full-resolution grayscale edges without needing opencv-contrib.
    """
    ksize = (2 * int(r) + 1, 2 * int(r) + 1)
    mean_i = cv2.boxFilter(guide_f32, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    mean_p = cv2.boxFilter(src_f32, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    mean_ip = cv2.boxFilter(guide_f32 * src_f32, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    cov_ip = mean_ip - mean_i * mean_p
    mean_ii = cv2.boxFilter(guide_f32 * guide_f32, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    var_i = mean_ii - mean_i * mean_i
    a = cov_ip / (var_i + float(eps))
    b = mean_p - a * mean_i
    mean_a = cv2.boxFilter(a, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    mean_b = cv2.boxFilter(b, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    return np.clip(mean_a * guide_f32 + mean_b, 0.0, 1.0)


def separate_photo_25d_u2netp(
    img_path: Path,
    target_w: int,
    target_h: int,
) -> Tuple[Optional[skia.Image], Optional[skia.Image]]:
    """Separate a photo into `(bg_inpainted_skia_img, fg_cutout_skia_img)` at `(target_w, target_h)`
    using `~/.u2net/u2netp.onnx` via `onnxruntime`, OpenCV Guided Filter edge refinement, and
    half-res TELEA background hole-filling.

    Strictly requires ONE clean dominant single subject (`0.10 <= solid_cov <= 0.55`,
    `largest_area / total_area >= 0.80`, `<= 4` small secondary blobs). For landscapes,
    crowds, architecture, fragmented masks, or unavailable `u2netp`, returns
    `(sharp_full_bg_skia, None)` with ZERO fake ellipse cutout or halo blur!
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

    def _sharp_bg_only() -> Tuple[skia.Image, None]:
        sharp_bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
        return (
            skia.Image.fromarray(
                np.ascontiguousarray(sharp_bgra),
                colorType=skia.ColorType.kBGRA_8888_ColorType,
            ),
            None,
        )

    sess = _get_u2netp_session()
    if sess is None:
        return _sharp_bg_only()

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
        if (p_max - p_min) < 1e-4:
            return _sharp_bg_only()
        mask_320 = ((pred - p_min) / max(1e-5, p_max - p_min)).astype(np.float32)
        mask_full_f = cv2.resize(mask_320, (tw, th), interpolation=cv2.INTER_LINEAR)
        alpha_raw = np.clip(mask_full_f * 255.0, 0.0, 255.0).astype(np.uint8)
    except Exception:
        return _sharp_bg_only()

    solid_mask = (alpha_raw > 128).astype(np.uint8)
    solid_cov = float(np.mean(solid_mask))
    if not (0.10 <= solid_cov <= 0.55):
        return _sharp_bg_only()

    # Require ONE clean dominant single subject (reject crowds, multi-subject & fragmented masks)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(solid_mask, connectivity=8)
    if num_labels <= 1:
        return _sharp_bg_only()
    areas = stats[1:, cv2.CC_STAT_AREA]
    total_area = int(np.sum(areas))
    if total_area <= 0:
        return _sharp_bg_only()
    largest_area = int(np.max(areas))
    dominance = largest_area / float(total_area)
    min_blob_px = max(4, min(16, int(tw * th * 0.00005)))
    significant_blobs = int(np.sum(areas >= min_blob_px))
    secondary_blobs = max(0, significant_blobs - 1)
    if dominance < 0.80 or secondary_blobs > 4:
        return _sharp_bg_only()

    # Edge-preserving Guided Filter refinement against full-res grayscale (locks mask onto real HD contours!)
    gray_f = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    refined_f = _guided_filter_gray(gray_f, mask_full_f, r=6, eps=1e-3)
    alpha_f = np.clip((refined_f - 0.15) / 0.70, 0.0, 1.0)
    alpha_u8 = (alpha_f * 255.0).astype(np.uint8)

    # 1px erode + minimal (3, 3) feather (zero muddy halo blur!)
    erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    alpha_eroded = cv2.erode(alpha_u8, erode_kernel, iterations=1)
    alpha_feathered = cv2.GaussianBlur(alpha_eroded, (3, 3), 0)
    fg_bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    fg_bgra[:, :, 3] = alpha_feathered

    # Clean half-res (tw // 2) background hole-filling with thin (5, 5) dilation, inpaintRadius=4 & (7, 7) blend
    half_w = max(32, tw // 2)
    half_h = max(32, th // 2)
    bgr_half = cv2.resize(bgr, (half_w, half_h), interpolation=cv2.INTER_AREA)
    mask_half = cv2.resize(
        (alpha_eroded > 64).astype(np.uint8) * 255,
        (half_w, half_h),
        interpolation=cv2.INTER_NEAREST,
    )
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dilated_half = cv2.dilate(mask_half, dilate_kernel, iterations=1)
    inpainted_half = cv2.inpaint(bgr_half, dilated_half, inpaintRadius=4, flags=cv2.INPAINT_TELEA)
    inpainted_up = cv2.resize(inpainted_half, (tw, th), interpolation=cv2.INTER_LINEAR)

    hole_mask_full = cv2.resize(dilated_half, (tw, th), interpolation=cv2.INTER_LINEAR)
    hole_mask_soft = cv2.GaussianBlur(hole_mask_full, (7, 7), 0).astype(np.float32) / 255.0
    hole_mask_3 = hole_mask_soft[:, :, np.newaxis]
    bg_inpainted = np.clip(
        inpainted_up.astype(np.float32) * hole_mask_3 + bgr.astype(np.float32) * (1.0 - hole_mask_3),
        0,
        255,
    ).astype(np.uint8)
    # Schema v3.0.0 layer_1_photorealistic_2_5d_parallax: subtle 3px Gaussian depth-of-field blur on separated background
    bg_inpainted = cv2.GaussianBlur(bg_inpainted, (7, 7), 2.8)
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
        if max(w, h) < 640 or min(w, h) < 360:
            continue
        is_landscape = w >= h
        orient_match = (is_landscape == want_landscape)
        orient_penalty = 0 if orient_match else 2_000
        # Target ~1280..1920 long-edge and <= 24MB for fast download & silky 30fps CPU decoding
        if 1200 <= max(w, h) <= 2048 and size <= 24_000_000:
            res_score = abs(max(w, h) - 1920) // 4 + (size // 200_000)
        elif max(w, h) > 2048:
            res_score = 1_000 + (size // 100_000)
        else:
            res_score = 400 + abs(max(w, h) - 1280)
        candidates.append({
            "score": orient_penalty + res_score,
            "orient_match": orient_match,
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
    mood: str = "",
    scene_context: str = "",
    used_dhashes: Optional[Set[int]] = None,
    strict_vision: bool = True,
) -> Optional[Tuple[Path, str]]:
    """Fast Pixabay HD B-roll search preferring 1080p/720p MP4s with hit-list-level orientation
    ranking, strict anti-junk filtering, AND Multimodal Gemini Vision thumbnail pre-screening
    (fail-closed when `strict_vision=True`) BEFORE downloading full MP4s!
    """
    if not api_key:
        return None
    dhashes = used_dhashes if used_dhashes is not None else set()
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
                    "per_page": 20,
                    "safesearch": "true",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                continue
            hits = r.json().get("hits", [])
        except Exception:
            continue

        # Rank hits at the HIT-LIST level by orientation match first (portrait clips first for 9:16!),
        # then semantic relevance, then variant quality, while filtering out off-topic junk!
        ranked_hits: List[Tuple[Tuple[int, int, int], Dict[str, Any], Dict[str, Any]]] = []
        for hit in hits:
            tags = str(hit.get("tags") or "").lower()
            if any(bad in tags for bad in BAD_TAG_WORDS):
                continue
            rel_score = _score_media_relevance(q, tags, mood=mood)
            if rel_score <= 0:
                continue
            picked = _pick_cpu_friendly_pixabay_video_variant(
                hit.get("videos") or {},
                want_landscape=want_landscape,
            )
            if not picked:
                continue
            hsh = hashlib.sha256(picked["url"].encode("utf-8")).hexdigest()[:16]
            if hsh in used_hashes:
                continue
            orient_rank = 1 if picked.get("orient_match") else 0
            rank_key = (orient_rank, rel_score, -int(picked["score"]))
            ranked_hits.append((rank_key, hit, picked))
        ranked_hits.sort(key=lambda x: x[0], reverse=True)
        if not ranked_hits:
            continue

        # Pre-screen top candidate video thumbnails in ONE 1-second Gemini Vision call BEFORE downloading!
        ordered_candidates = ranked_hits[:8]
        if strict_vision:
            if not _read_gemini_api_key():
                print(f"[DocMedia] Strict Vision skipped Pixabay video query '{q}' (missing Gemini API key)", flush=True)
                continue
            v_items: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
            v_bgrs: List[np.ndarray] = []
            for _, hit, picked in ordered_candidates:
                if len(v_items) >= 4:
                    break
                vids = hit.get("videos") or {}
                t_url = str(
                    (vids.get("tiny") or {}).get("thumbnail")
                    or (vids.get("small") or {}).get("thumbnail")
                    or (vids.get("medium") or {}).get("thumbnail")
                    or ""
                ).strip()
                tbgr = _download_thumb_bgr(client, t_url) if t_url else None
                if tbgr is None:
                    continue
                if mood in ("dark_horror", "epic_history"):
                    ok_g, _ = _check_dark_horror_visual_guard(tbgr)
                    if not ok_g:
                        continue
                dh = compute_image_dhash(tbgr)
                if is_perceptual_duplicate(dh, dhashes, max_hamming=8):
                    continue
                v_items.append((hit, picked))
                v_bgrs.append(tbgr)

            if not v_items:
                print(
                    f"[DocMedia] Strict Vision skipped Pixabay video query '{q}' (no verifiable/dark-compliant thumbnails)",
                    flush=True,
                )
                continue

            best_i, v_score, v_reason = vision_select_best_candidate(
                v_bgrs,
                query=q,
                scene_context=scene_context or q,
                mood=mood or "dark_horror",
                min_score=7,
                strict_vision=True,
            )
            if best_i < 0:
                print(
                    f"[DocMedia] Vision rejected all {len(v_items)} Pixabay video hits for '{q}' ({v_score}/10: {v_reason})",
                    flush=True,
                )
                continue
            win_hit, win_picked = v_items[best_i]
            print(
                f"[DocMedia] Vision APPROVED Pixabay video ({v_score}/10: {v_reason}) | q='{q}'",
                flush=True,
            )
            ordered_candidates = [((1, 99, 0), win_hit, win_picked)]

        for _, hit, picked in ordered_candidates:
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
                if mood in ("dark_horror", "epic_history"):
                    # Verify decoded middle frame passes luminance floor (mean_v >= 24.0) & neon/daytime guard!
                    cap_chk = cv2.VideoCapture(str(local_path))
                    mid_ok = True
                    try:
                        if cap_chk.isOpened():
                            nf = int(cap_chk.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                            if nf > 6:
                                cap_chk.set(cv2.CAP_PROP_POS_FRAMES, nf // 2)
                            ok_f, mid_fr = cap_chk.read()
                            if ok_f and mid_fr is not None:
                                mid_ok, mid_why = _check_dark_horror_visual_guard(mid_fr)
                                if not mid_ok:
                                    print(f"[DocMedia] Visual guard rejected downloaded B-roll ({mid_why}) -> {local_path.name}", flush=True)
                    finally:
                        cap_chk.release()
                    if not mid_ok:
                        continue
                vdh = compute_video_dhash(local_path)
                if is_perceptual_duplicate(vdh, dhashes, max_hamming=8):
                    continue
                if vdh is not None:
                    dhashes.add(vdh)
                used_hashes.add(hsh)
                print(
                    f"[DocMedia] Real HD B-roll ready (pixabay {picked['width']}x{picked['height']}): "
                    f"{local_path.name} | tags='{str(hit.get('tags') or '')[:45]}' | blur={qrep['blur_score']} | green={qrep['green_pixel_ratio']:.1%}",
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
    scene_context: str = "",
    used_dhashes: Optional[Set[int]] = None,
    strict_vision: bool = True,
) -> Optional[Path]:
    """Fetch a REAL, valid, Vision-verified, non-duplicate HD `.mp4` B-roll clip.
    NEVER falls back blindly to generic `MOOD_DOC_BROLL_QUERIES` when a historical scene's B-roll query
    fails Vision screening! When no period-authentic B-roll clip passes Vision + luminance floor (`mean_v >= 24.0`),
    cleanly returns `None` so the compositor uses the scene's 2.5D parallax plates & 2D schematics instead
    of an anachronistic video!
    """
    resolved_mood = _infer_media_mood(query, mood)
    curated_pool = MOOD_DOC_BROLL_QUERIES.get(resolved_mood, CURATED_DOC_BROLL_QUERIES)
    norm_q = _normalize_query(query, "")
    if not norm_q:
        if strict_vision or resolved_mood in ("dark_horror", "epic_history"):
            return None
        norm_q = curated_pool[0]
    used = used_hashes if used_hashes is not None else set()
    dhashes = used_dhashes if used_dhashes is not None else set()
    pixabay_key, pexels_key = _read_api_keys()
    want_landscape = str(aspect_ratio or "16:9").strip() != "9:16"

    tag_seed = int(hashlib.sha256(f"{tag}:{norm_q}".encode("utf-8")).hexdigest()[:6], 16)
    # Strict Era Gate: NEVER silently fall back to generic MOOD_DOC_BROLL_QUERIES in historical/strict mode!
    all_queries: List[str] = [norm_q]
    short_q = _shorten_query(norm_q, max_words=3)
    if short_q and short_q.lower() != norm_q.lower() and len(short_q.split()) >= 2:
        all_queries.append(short_q)
    if not strict_vision and resolved_mood not in ("dark_horror", "epic_history"):
        rotated_curated = [
            curated_pool[(tag_seed + i) % len(curated_pool)]
            for i in range(len(curated_pool))
        ]
        for q in rotated_curated:
            if q.lower() not in {x.lower() for x in all_queries}:
                all_queries.append(q)

    # 1. Fast HD 1080p/720p Pixabay B-roll pass with Gemini Vision thumbnail pre-screening
    if pixabay_key:
        with httpx.Client(follow_redirects=True, timeout=22.0) as client:
            for q in all_queries[:2 if (strict_vision or resolved_mood in ("dark_horror", "epic_history")) else 4]:
                res = _fetch_pixabay_doc_broll(
                    client,
                    q,
                    api_key=pixabay_key,
                    used_hashes=used,
                    want_landscape=want_landscape,
                    mood=resolved_mood,
                    scene_context=scene_context or norm_q,
                    used_dhashes=dhashes,
                    strict_vision=strict_vision,
                )
                if res is not None:
                    clip_path, hsh = res
                    return _materialize_video_in_work_dir(clip_path, work_dir, tag, hsh)

    # 2. Multi-source fallback via smart_vision ONLY if Vision approves the downloaded frame against the ORIGINAL query!
    for idx, q in enumerate(all_queries[:2]):
        try:
            clip = fetch_unique_real_clip(
                q,
                pixabay_key=pixabay_key,
                pexels_key=pexels_key,
                exclude_hashes=used,
                scene_index=(tag_seed + idx) % len(curated_pool),
            )
            if clip and _validate_video_file(clip):
                vdh = compute_video_dhash(clip)
                if is_perceptual_duplicate(vdh, dhashes, max_hamming=8):
                    continue
                if strict_vision:
                    ok_v, v_sc, v_why = verify_video_frame_vision(
                        clip,
                        query=norm_q,
                        scene_context=scene_context or norm_q,
                        mood=resolved_mood,
                        min_score=7,
                        strict_vision=True,
                    )
                    if not ok_v:
                        print(f"[DocMedia] Vision rejected smart_vision clip ({v_sc}/10: {v_why}) -> {clip.name}", flush=True)
                        continue
                hsh = clip.stem.split("_")[-1][:16]
                used.add(hsh)
                if vdh is not None:
                    dhashes.add(vdh)
                print(
                    f"[DocMedia] Real HD B-roll ready (smart_vision): {clip.name} | q='{q}'",
                    flush=True,
                )
                return _materialize_video_in_work_dir(clip, work_dir, tag, hsh)
        except Exception:
            continue

    # When strict_vision=True or historical mood, cleanly return None so compositor uses 2.5D plates!
    if strict_vision or resolved_mood in ("dark_horror", "epic_history"):
        return None

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

    def __init__(
        self,
        mp4_path: Path,
        target_w: int,
        target_h: int,
        fps: int = 30,
        playback_speed: float = 1.0,
    ) -> None:
        cv2.setNumThreads(1)
        self.mp4_path = Path(mp4_path)
        self.target_w = max(16, int(target_w))
        self.target_h = max(16, int(target_h))
        self.fps = max(1, int(fps))
        self.playback_speed = max(0.25, min(2.0, float(playback_speed or 1.0)))

        self._cap: Optional[cv2.VideoCapture] = None
        self._closed: bool = False
        self._src_fps: float = float(self.fps)
        self._frame_step: float = self.playback_speed
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
        base_step = self._src_fps / float(self.fps)
        if abs(self.playback_speed - 1.0) > 1e-3:
            # Explicit slow-motion / speed-ramp playback (e.g. 0.85x atmospheric slow-motion B-roll)
            self._frame_step = max(0.20, base_step * self.playback_speed)
        else:
            # Keep natural smooth cadence: 24/25/30fps -> 1:1 sequential, 60fps -> grab-skip every other frame
            self._frame_step = 1.0 if (0.72 <= base_step <= 1.35) else base_step

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
    "_SEEN_PHOTO_DHASHES",
    "_enforce_historical_era_prompt_lock",
    "_extract_historical_era_lock",
    "_gemini_vision_batch_pick_best",
    "_verify_single_image_vision",
    "fetch_doc_broll_clip",
    "fetch_doc_hero_or_archival_photo",
    "fetch_doc_real_photo",
    "fetch_wikimedia_commons_archival_photo",
    "generate_doc_gemini_image",
    "load_skia_image_cover",
    "separate_photo_25d_u2netp",
    "verify_historical_anachronism_vision",
]
