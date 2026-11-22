"""FrimeRise Netflix / MagnatesMedia Cinema Investigative Documentary Studio v2 (Skia C++ + Real HD Video/PiP + Real Photos + QuickSync iHD).
Features:
  - Supports 16:9 Widescreen (1920x1080, scalable from 25s demos up to 3-15 min high-RPM mid-roll documentaries)
    and 9:16 Vertical Doc (1080x1920).
  - Real Moving HD B-Roll Video Base Layer in EVERY scene via `engine.doc_media_engine.VideoLayerReader`
    (never a flat empty dark grid!).
  - Real Video-over-Video (Picture-in-Picture Forensic Monitor + Split-Screen Video & Dossier) with
    16px rounded tilted frame, glowing #FF2E93/#FFD166 border, scanlines, blinking red REC dot,
    and `_ease_out_back` spring entrance.
  - Real Archival & Editorial Photographs embedded in ALL investigative modes via `fetch_doc_real_photo`,
    `load_skia_image_cover`, and `separate_photo_25d_u2netp` (genuine 2.2x 2.5D foreground/background parallax!).
  - Scene-by-scene disk rendering with os.nice(10) and thermal_guard_wait so RAM stays flat and Core i5 stays cool.
  - Dramatic Act Structure: Cold Open + Wide Letter-Spaced Chapter Cards ('C A P Í T U L O   I', 'C A P Í T U L O   I I')
    with assets/sfx/sub_boom.wav impact + sleek editorial Lower Thirds + LUT assets/luts/02_dark_wealth.cube + 35mm film grain.
  - 7 Investigative C++ Skia Visual Modes @ 30fps:
      1) broll_video_pip: Full-bleed moving HD video + Video-over-Video PiP forensic monitor + cold-open archival dossier
      2) newspaper_highlighter: Moving HD video backdrop + archival broadsheet with real monochrome/sepia photo & Multiply highlighter sweep
      3) dark_map_route: Moving HD video backdrop + translucent tactical route map + live Video-over-Video PiP monitor
      4) parallax_25d_photo: Moving HD video backdrop + real u2netp 2.5D separated photo (2.2x foreground parallax) inside cinema matte
      5) red_string_board: Moving HD video backdrop + 3-4 distinct real Polaroid evidence photos pinned to obsidian nodes with #FF2E93 strings
      6) sliding_timeline: Moving HD video backdrop + camera-tracked sliding timeline with real photo inset header inside active card
      7) video_pip_evidence: Split-Screen Video + Dossier (left 54% crisp moving B-roll + PiP monitor, right 46% glassmorphic card + real photo)
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import subprocess
import unicodedata
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

import edge_tts
import httpx
import numpy as np
from pydantic import BaseModel, Field
import skia

from agents.llm_router import _extract_json
from agents.retention_doctor import OPEN_LOOP_MARKERS_RE, audit_netflix_doc_plan
from database import get_settings, record_token_usage
from engine.audio_dsp import (
    _estimate_word_timestamps,
    _get_wav_duration,
    _synthesize_espeak_fallback,
    align_script_words_to_audio,
    master_broadcast_audio,
    trim_silence_vad,
)
try:
    from engine.audio_dsp import normalize_scene_wav_lufs
except Exception:
    normalize_scene_wav_lufs = None  # type: ignore
from engine.gemini_tts import (
    GEMINI_EXPRESSIVE_VOICES,
    has_valid_gemini_key,
    normalize_narration_for_speech,
    synthesize_gemini_tts_line,
)
try:
    import engine.gemini_tts as _gemini_tts_mod
    build_act_acting_direction = getattr(_gemini_tts_mod, "build_act_acting_direction", None)
except Exception:
    build_act_acting_direction = None  # type: ignore
from engine.doc_media_engine import (
    VideoLayerReader,
    _enforce_historical_era_prompt_lock,
    _extract_historical_era_lock,
    compute_file_dhash,
    fetch_doc_broll_clip,
    fetch_doc_hero_or_archival_photo,
    fetch_doc_real_photo,
    fetch_wikimedia_commons_archival_photo,
    is_perceptual_duplicate,
    load_skia_image_cover,
    separate_photo_25d_u2netp,
    verify_historical_anachronism_vision,
)
from engine.google_flow_bridge import generate_flow_batch_images_sync
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    FORBIDDEN_DEBUG_RE,
    _ease_out_cubic,
    _load_verified_typeface,
    _wrap_text_to_width,
    group_words_into_chunks,
    hex_to_skia,
)

try:
    from engine.kinetic_captions import draw_kinetic_captions, resolve_caption_style
except Exception:
    draw_kinetic_captions = None  # type: ignore
    resolve_caption_style = None  # type: ignore

try:
    from engine.kinetic_captions import draw_kinetic_caption_chunk
except Exception:
    draw_kinetic_caption_chunk = None  # type: ignore

try:
    from engine.kinetic_captions import DARK_CINEMA_PILL_PALETTE
except Exception:
    DARK_CINEMA_PILL_PALETTE = [
        ("#9E1B24", "#FFFFFF", (158, 27, 36, 210)),   # Blood Crimson + Pure White
        ("#FFD166", "#0B0713", (255, 209, 102, 200)), # Antique Gold + Obsidian Ink
        ("#D97706", "#FFFFFF", (217, 119, 6, 205)),   # Torch Amber + Pure White
    ]

try:
    from engine.pro_sfx_studio import ensure_pro_cinema_sfx, select_music_for_mood
except Exception:
    ensure_pro_cinema_sfx = None  # type: ignore
    select_music_for_mood = None  # type: ignore

try:
    from engine.flow_vault import ensure_upgraded_dark_horror_music
except Exception:
    ensure_upgraded_dark_horror_music = None  # type: ignore

try:
    import engine.pro_motion_graphics as _pmg_mod
    from engine.pro_motion_graphics import (
        draw_anamorphic_film_burn_and_bokeh,
        draw_depth_title_behind_subject,
        draw_pro_archival_newspaper,
        draw_pro_cartographic_map,
        draw_pro_forensic_string_board,
        draw_pro_odometer_timeline,
        draw_pro_safezone_lower_third,
    )
    draw_2d_schematic_over_realism = getattr(_pmg_mod, "draw_2d_schematic_over_realism", None)
    draw_video_over_video_collage = getattr(_pmg_mod, "draw_video_over_video_collage", None)
    draw_fern_3d_reconstruction = getattr(_pmg_mod, "draw_fern_3d_reconstruction", None)
    draw_chapter_whip_and_film_burn = getattr(_pmg_mod, "draw_chapter_whip_and_film_burn", None)
except Exception:
    draw_depth_title_behind_subject = None  # type: ignore
    draw_anamorphic_film_burn_and_bokeh = None  # type: ignore
    draw_pro_safezone_lower_third = None  # type: ignore
    draw_pro_cartographic_map = None  # type: ignore
    draw_pro_archival_newspaper = None  # type: ignore
    draw_pro_odometer_timeline = None  # type: ignore
    draw_pro_forensic_string_board = None  # type: ignore
    draw_2d_schematic_over_realism = None  # type: ignore
    draw_video_over_video_collage = None  # type: ignore
    draw_fern_3d_reconstruction = None  # type: ignore
    draw_chapter_whip_and_film_burn = None  # type: ignore

_DEPTH_TITLE_ACCEPTS_FG_IMG: bool = False
if draw_depth_title_behind_subject is not None:
    try:
        _DEPTH_TITLE_ACCEPTS_FG_IMG = "fg_img" in inspect.signature(draw_depth_title_behind_subject).parameters
    except Exception:
        _DEPTH_TITLE_ACCEPTS_FG_IMG = False

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
CONFIG_DIR = BASE_DIR / "config"
SKILLS_DIR = BASE_DIR / "skills"
DOC_BG_CACHE = BASE_DIR / "data" / "doc_bgs"
DOC_BG_CACHE.mkdir(parents=True, exist_ok=True)
HIGH_RETENTION_ENGINE_V3_CONFIG_PATH = CONFIG_DIR / "high_retention_doc_engine_v3.json"
REFERENCE_BENCHMARKS_EDL_V3_PATH = CONFIG_DIR / "reference_benchmarks_edl_v3.json"


def load_high_retention_engine_config() -> Dict[str, Any]:
    """Load the canonical Mixed_Media_High_Retention_Documentary_Engine v3.0.0 schema config."""
    try:
        if HIGH_RETENTION_ENGINE_V3_CONFIG_PATH.exists():
            data = json.loads(HIGH_RETENTION_ENGINE_V3_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {
        "schema_version": "3.0.0",
        "pipeline_name": "Mixed_Media_High_Retention_Documentary_Engine",
    }


VisualModeType = Literal[
    "cinema_multishot",
    "broll_video_pip",
    "newspaper_highlighter",
    "dark_map_route",
    "parallax_25d_photo",
    "red_string_board",
    "sliding_timeline",
    "video_pip_evidence",
    "2d_schematic_over_realism",
    "video_over_video_collage",
    "fern_3d_reconstruction",
]

VisualCategoryType = Literal[
    "2.5D_Parallax",
    "2D_Infographic_Over_Realism",
    "Video_Over_Video_PiP",
    "Dark_3D_Reconstruction",
    "Atmospheric_B_Roll",
]

# Cinema v7 Mixed-Media 5-Category visual rhythm (Vox, Johnny Harris, MagnatesMedia, Fern, Elementar)
VISUAL_MODES: Tuple[VisualModeType, ...] = (
    "parallax_25d_photo",         # Sc 0: Cold Open Hero 2.5D Parallax + 3D Depth Title
    "fern_3d_reconstruction",     # Sc 1: Dark Minimalist 3D Reconstruction
    "cinema_multishot",           # Sc 2: Multi-shot hero 2.5D + slow-mo B-roll
    "2d_schematic_over_realism",  # Sc 3: Vox / Johnny Harris 2D Infographic Over Realism
    "newspaper_highlighter",      # Sc 4: Archival Broadsheet with Highlighter Sweep
    "dark_map_route",             # Sc 5: Pro Cartographic European Map with Camera Zoom & Radar
    "video_over_video_collage",   # Sc 6: Video-over-Video Floating PiP Collage
    "sliding_timeline",           # Sc 7: Mechanical Odometer Timeline (era-matched hero plates)
    "red_string_board",           # Sc 8: Forensic String Board (era-matched hero plates)
    "parallax_25d_photo",         # Sc 9: 2.5D Parallax + Depth Title
)


def _resolve_visual_category(visual_mode: str, is_broll_shot: bool = False) -> VisualCategoryType:
    """Map an internal Skia visual_mode to one of the 5 canonical v3.0.0 EDL visual_category values."""
    if is_broll_shot:
        return "Atmospheric_B_Roll"
    vm = str(visual_mode or "").strip()
    if vm in ("2d_schematic_over_realism", "dark_map_route", "sliding_timeline"):
        return "2D_Infographic_Over_Realism"
    if vm in ("video_over_video_collage", "newspaper_highlighter", "red_string_board", "video_pip_evidence", "broll_video_pip"):
        return "Video_Over_Video_PiP"
    if vm == "fern_3d_reconstruction":
        return "Dark_3D_Reconstruction"
    return "2.5D_Parallax"


def _select_visual_mode_for_scene(idx: int, total_scenes: int = 10) -> VisualModeType:
    """Return the visual mode for scene `idx`, guaranteeing ALL 5 Mixed-Media visual categories
    (2.5D_Parallax, 2D_Infographic_Over_Realism, Video_Over_Video_PiP, Dark_3D_Reconstruction,
    and Atmospheric_B_Roll) appear cleanly across short and 25-scene documentaries.
    """
    if total_scenes == 6:
        six_pack: Tuple[VisualModeType, ...] = (
            "parallax_25d_photo",
            "2d_schematic_over_realism",
            "newspaper_highlighter",
            "fern_3d_reconstruction",
            "dark_map_route",
            "red_string_board",
        )
        return six_pack[idx % len(six_pack)]
    if total_scenes == 7 and idx == 6:
        return "red_string_board"
    return VISUAL_MODES[idx % len(VISUAL_MODES)]

PIP_ENABLED_MODES: Tuple[VisualModeType, ...] = (
    "broll_video_pip",
    "dark_map_route",
    "video_pip_evidence",
    "video_over_video_collage",
)

ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")

_LINEAR_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)

# Unicode glyph normalization table — guarantees ZERO missing-glyph '[]' boxes in Montserrat / PlusJakartaSans
_ARROW_AND_GLYPH_MAP: Dict[str, str] = {
    "\u2794": "->",   # ➔
    "\u279c": "->",   # ➜
    "\u279e": "->",   # ➞
    "\u27a1": "->",   # ➡
    "\u2192": "->",   # →
    "\u21d2": "->",   # ⇒
    "\u2190": "<-",   # ←
    "\u21d0": "<-",   # ⇐
    "\u2194": "<->",  # ↔
    "\u21d4": "<->",  # ⇔
    "\u25cf": "•",    # ● (missing in Montserrat-Black.ttf!)
    "\u25c9": "•",    # ◉
    "\u25aa": "•",    # ▪
    "\u25ab": "•",    # ▫
    "\u25c6": "•",    # ◆
    "\ufe0f": "",     # variation selector
}


DocMoodType = Literal[
    "dark_horror",
    "investigative_crime",
    "epic_history",
    "corporate_thriller",
]

VALID_DOC_MOODS: Tuple[str, ...] = (
    "dark_horror",
    "investigative_crime",
    "epic_history",
    "corporate_thriller",
)

CINEMA_XFADE_DURATION_S: float = 0.40
CINEMA_XFADE_POOL: Tuple[str, ...] = (
    "fadeblack",
    "smoothleft",
    "zoomin",
    "dissolve",
    "wiperight",
)


def _ease_out_back(x: float) -> float:
    """Snappy cinematic overshoot spring easing for PiP monitor & Polaroid entrances."""
    t = max(0.0, min(1.0, float(x)))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * ((t - 1.0) ** 3) + c1 * ((t - 1.0) ** 2)


def _sanitize_glyphs(
    text: str,
    typeface: Optional[skia.Typeface] = None,
    preserve_spacing: bool = False,
) -> str:
    """Replace unsupported Unicode arrows/bullets with clean ASCII/verified glyphs so Skia NEVER renders a '[]' box."""
    s = str(text or "")
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


def _normalize_upper(text: str) -> str:
    """Return clean Unicode NFC uppercase text (e.g. 'ALPES AUSTRÍacos' -> 'ALPES AUSTRÍACOS')."""
    return unicodedata.normalize("NFC", str(text or "")).upper()


def _spaced_chapter_label(roman: str, lang: str = "pt_br") -> str:
    """Return wide letter-spaced cinema chapter title with generous gap before the Roman numeral."""
    r_spaced = " ".join(list(roman.strip()))
    if str(lang).lower().startswith("en"):
        return f"C H A P T E R     {r_spaced}"
    return f"C A P Í T U L O     {r_spaced}"


def _clean_doc_text(text: str, preserve_spacing: bool = False) -> str:
    cleaned = FORBIDDEN_DEBUG_RE.sub("", str(text or "")).strip()
    return _sanitize_glyphs(cleaned, preserve_spacing=preserve_spacing)


def _draw_safe_string(
    canvas: skia.Canvas,
    text: str,
    x: float,
    y: float,
    font: skia.Font,
    paint: skia.Paint,
    preserve_spacing: bool = False,
) -> None:
    """Draw a string after verifying every character has a real glyph in the active typeface."""
    safe_txt = _sanitize_glyphs(text, typeface=font.getTypeface(), preserve_spacing=preserve_spacing)
    if safe_txt:
        canvas.drawString(safe_txt, x, y, font, paint)


# ---------------------------------------------------------------------------
# 1. Pydantic Models & JSON Contract for Netflix / MagnatesMedia Doc Studio
# ---------------------------------------------------------------------------
class TimelinePoint(BaseModel):
    date: str
    label: str
    value: str


class BoardNode(BaseModel):
    id: str
    title: str
    role: str
    badge: str


class NetflixDocScene(BaseModel):
    scene_id: str
    act_id: str = "ACT_1_WORLD_BUILDING"
    act_label: str = "ACT I"
    chapter_card: Optional[str] = None
    chapter_subtitle: Optional[str] = None
    visual_mode: VisualModeType = "broll_video_pip"
    visual_category: Optional[str] = None
    cut_cadence_s: Optional[float] = None
    pattern_interrupt: bool = False
    mood: str = "corporate_thriller"
    narration: str
    lower_third_title: str
    lower_third_subtitle: str
    highlight_color: str = "#EAB308"
    evidence_headline: str = "ARCHIVAL DOCUMENTARY RECORD"
    evidence_quote: str = "Historical records and archival testimonies reveal the hidden story behind these events."
    map_origin: str = "ORIGEM"
    map_destination: str = "DESTINO"
    map_metric: str = "ARQUIVO HISTÓRICO"
    timeline_points: List[TimelinePoint] = Field(default_factory=list)
    board_nodes: List[BoardNode] = Field(default_factory=list)
    image_prompt_en: str = "cinematic dark archival documentary still photograph"
    bespoke_image_prompt_en: str = ""
    prefer_gemini_photo: bool = False
    broll_query_en: str = "dark atmospheric night documentary"
    pip_broll_query_en: str = "historic architecture night fog"
    photo_query_en: str = "historic archive candle dark"
    extra_photo_queries_en: List[str] = Field(default_factory=list)
    shot_prompts_en: List[str] = Field(default_factory=list)
    transition_type: Optional[str] = None


# Backwards/shorthand alias
DocScene = NetflixDocScene


class NetflixDocPlan(BaseModel):
    schema_version: str = "3.0.0"
    pipeline_name: str = "Mixed_Media_High_Retention_Documentary_Engine"
    title: str
    subtitle: str
    channel_name: str = "Dossiê Capital"
    mood: str = "corporate_thriller"
    lang: str = "pt_br"
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    target_minutes: float = 17.0
    lut_file: str = "02_dark_wealth.cube"
    voice_id: str = "Charon"
    caption_style: str = "selective_emphasis"
    thumbnail_hook: str = "A VERDADE OCULTA"
    topic_source: str = "curated"
    tokens_used: int = 0
    cost_usd: float = 0.0
    pattern_interrupt_times: List[float] = Field(default_factory=list)
    scenes: List[NetflixDocScene]
    hashtags: List[str] = Field(default_factory=lambda: ["#documentario", "#historia", "#investigacao", "#cinema"])
    retention_audit: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2. Curated Investigative Dossiers (10 High-RPM Twin-Channel Episodes + Custom)
# ---------------------------------------------------------------------------
_CURATED_DOSSIERS: List[Dict[str, Any]] = [
    {
        "keywords": ("leeson", "barings", "88888", "banco da rainha", "queen's oldest bank"),
        "title_pt": "Nick Leeson: O Operador que Quebrou o Banco da Rainha",
        "title_en": "Nick Leeson: The Rogue Trader Who Collapsed Barings Bank",
        "sub_pt": "Dossiê Forense • Conta Secreta #88888",
        "sub_en": "Forensic File • Secret Error Account #88888",
        "hook_pt": "ESCONDEU $1.4 BILHÃO",
        "hook_en": "HID $1.4 BILLION",
        "origin": "LONDRES",
        "dest": "SINGAPURA",
        "metric_pt": "US$ 1.4 BILHÃO OCULTO",
        "metric_en": "$1.4 BILLION CONCEALED",
        "headline": "BARINGS BANK COLLAPSES OVERNIGHT AFTER $1.4B SECRET LOSS",
        "quote_pt": "A conta de erro 88888 escondeu prejuízos bilionários em contratos futuros do Nikkei por 32 meses sem auditoria.",
        "quote_en": "Error Account 88888 concealed unauthorized Nikkei futures losses for 32 months while London sent more capital.",
        "broll_queries": [
            "london skyline night",
            "stock market trading monitors",
            "singapore skyline night aerial",
            "corporate boardroom executives",
            "bank vault money bills",
            "earthquake rubble city",
        ],
        "pip_queries": [
            "stock market chart",
            "newspaper printing press",
            "gold bars bank vault",
            "singapore skyline night aerial",
            "london skyline night",
            "corporate boardroom executives",
        ],
        "photo_queries": [
            "historic bank building london",
            "stock market trading floor",
            "singapore financial district skyline",
            "businessman suit office portrait",
            "london financial district skyline",
            "money bills finance dark",
        ],
        "timeline": [
            {"date": "1992", "label": "Conta #88888 Aberta", "value": "-US$ 2M"},
            {"date": "1993", "label": "Especulação SIMEX", "value": "-US$ 23M"},
            {"date": "1994", "label": "Auditoria Enganada", "value": "-US$ 208M"},
            {"date": "1995", "label": "Terremoto de Kobe", "value": "-US$ 1.4B"},
        ],
        "nodes": [
            {"id": "n1", "title": "NICK LEESON", "role": "Chefe de Operações SIMEX", "badge": "OPERADOR"},
            {"id": "n2", "title": "CONTA #88888", "role": "Arquivo Oculto de Erros", "badge": "CAIXA PRETA"},
            {"id": "n3", "title": "BARINGS (1762)", "role": "233 Anos de História", "badge": "VENDIDO POR £1"},
            {"id": "n4", "title": "NIKKEI 225", "role": "Aposta Dobrada em Tóquio", "badge": "-US$ 1.4 BILHÃO"},
        ],
        "narr_pt": [
            "Em fevereiro de 1995, um único operador de vinte e oito anos em Singapura derrubou o banco mais antigo da coroa britânica — só que ninguém em Londres desconfiava do número 88888.",
            "Para esconder um pequeno erro de uma funcionária, Nick Leeson abriu a conta secreta cinco vezes oito, mas o que começou com dois milhões virou uma bola de neve fora de controle.",
            "Enquanto a matriz em Londres acreditava que ele gerava lucros recordes, centenas de milhões de dólares cruzavam o planeta para cobrir margens ocultas na bolsa asiática.",
            "Quando o terremoto de Kobe derrubou o índice Nikkei em janeiro de 1995, Leeson dobrou a aposta final e o rombo explodiu para um vírgula quatro bilhão de dólares.",
            "Em quarenta e oito horas, um império financeiro de duzentos e trinta e três anos foi vendido por exatamente uma libra esterlina.",
        ],
        "narr_en": [
            "In February 1995, a single twenty-eight-year-old trader in Singapore brought down Britain's oldest merchant bank — yet nobody in London questioned Account 88888.",
            "To hide a tiny clerical mistake on the trading floor, Nick Leeson opened secret error account five-eights, but a two-million-dollar loss quickly spiraled out of control.",
            "While executives in London praised him as a miracle profit machine, hundreds of millions of dollars were wired across the globe to feed hidden margin calls.",
            "When the Kobe earthquake sent the Nikkei crashing in January 1995, Leeson doubled down one last time and the secret hole exploded to one point four billion dollars.",
            "Within forty-eight hours, a two-hundred-and-thirty-three-year financial empire collapsed and was sold for a single British pound.",
        ],
    },
    {
        "keywords": ("luxottica", "essilorluxottica", "óculos de luxo", "oculos de luxo", "império secreto dos óculos", "eyewear illusion", "eyewear monopoly", "ray-ban", "oakley"),
        "title_pt": "A Ilusão da Escolha: O Império Secreto dos Óculos",
        "title_en": "The Illusion of Choice: Inside the Eyewear Monopoly",
        "sub_pt": "Dossiê Antitruste • Margem de 2.000%",
        "sub_en": "Antitrust File • 2,000% Markup Architecture",
        "hook_pt": "TUDO É DELES",
        "hook_en": "THEY OWN ALL",
        "origin": "MILÃO",
        "dest": "NOVA YORK",
        "metric_pt": "+2.000% DE MARGEM",
        "metric_en": "+2,000% RETAIL MARKUP",
        "headline": "ONE CONGLOMERATE CONTROLS 80% OF GLOBAL EYEWEAR BRANDS",
        "quote_pt": "Quando a Oakley tentou desafiar os preços do grupo, foi retirada das vitrines até suas ações caírem e ser comprada pelo próprio rival.",
        "quote_en": "When Oakley resisted pricing terms, its frames vanished from retail chains until its stock tumbled into a buyout.",
        "broll_queries": [
            "milan italy architecture city",
            "luxury retail store shopping mall",
            "industrial factory production line",
            "new york city skyline night",
            "corporate boardroom executives",
            "money bills dark finance",
        ],
        "pip_queries": [
            "sunglasses fashion luxury store",
            "stock market trading monitors",
            "new york fifth avenue street",
            "industrial workshop machinery",
            "corporate office skyscraper",
        ],
        "photo_queries": [
            "sunglasses fashion luxury",
            "milan architecture italy",
            "eyeglasses optical store",
            "businessman suit office portrait",
            "new york skyscraper skyline",
            "factory production industrial",
        ],
        "timeline": [
            {"date": "1961", "label": "Oficina em Agordo", "value": "US$ 100K"},
            {"date": "1999", "label": "Compra da Ray-Ban", "value": "US$ 640M"},
            {"date": "2007", "label": "Aquisição da Oakley", "value": "US$ 2.1B"},
            {"date": "2018", "label": "Fusão EssilorLuxottica", "value": "US$ 57B"},
        ],
        "nodes": [
            {"id": "n1", "title": "ESSILORLUXOTTICA", "role": "Holding Dominante", "badge": "80% DO MERCADO"},
            {"id": "n2", "title": "RAY-BAN & OAKLEY", "role": "Marcas 'Rivais' Internas", "badge": "MESMO DONO"},
            {"id": "n3", "title": "SUNGLASS HUT", "role": "Rede Global de Varejo", "badge": "CONTROLE DE PREÇO"},
            {"id": "n4", "title": "CUSTO REAL US$ 12", "role": "Vendido por US$ 300+", "badge": "MARGEM 2.000%"},
        ],
        "narr_pt": [
            "Você entra em um shopping, compara dez marcas diferentes de óculos de sol achando que está pesquisando preço — só que quase todas pertencem exatamente à mesma fábrica.",
            "Durante décadas, uma única gigante italiana comprou silenciosamente as fábricas de armações, as maiores marcas de luxo e até as redes de óticas onde você compra.",
            "Quando a Oakley tentou vender mais barato em 2001, ela foi banida das maiores vitrines dos Estados Unidos até perder valor de mercado e ser comprada pelo próprio grupo.",
            "Com a fusão de cinquenta e sete bilhões de dólares entre lentes e armações, uma peça que custa doze dólares na linha de montagem chega à vitrine por trezentos dólares.",
            "No fim das contas, a concorrência que você vê na prateleira foi desenhada no mesmo escritório em Milão.",
        ],
        "narr_en": [
            "You walk into a mall and compare ten competing designer sunglasses brands thinking you have a choice — yet almost every frame comes from the exact same company.",
            "Over four decades, a single Italian giant quietly bought the frame factories, the luxury fashion licenses, and even the retail chains that sell them.",
            "When Oakley tried to fight back on pricing in 2001, its products were pulled from major stores until its stock plunged and it was acquired by the very same rival.",
            "Following a fifty-seven-billion-dollar merger uniting lenses and frames, an acetate piece costing twelve dollars to manufacture sells for over three hundred.",
            "What looks like fierce competition in the display case was engineered in a single boardroom in Milan.",
        ],
    },
    {
        "keywords": ("theranos", "elizabeth holmes", "projeto edison", "sangue falso da theranos", "blood-testing mirage"),
        "title_pt": "Theranos: A Fraude de US$ 9 Bilhões dentro de uma Caixa Vazia",
        "title_en": "Theranos: The $9 Billion Silicon Valley Blood Mirage",
        "sub_pt": "Dossiê Vale do Silício • Projeto Edison",
        "sub_en": "Silicon Valley File • The Edison Black Box",
        "hook_pt": "CAIXA VAZIA",
        "hook_en": "IT WAS EMPTY",
        "origin": "PALO ALTO",
        "dest": "WASHINGTON D.C.",
        "metric_pt": "US$ 9 BILHÕES EVAPORADOS",
        "metric_en": "$9 BILLION VALUATION ZEROED",
        "headline": "SECRET LAB AUDIT EXPOSES COMMERCIAL ANALYZERS BEHIND THERANOS",
        "quote_pt": "Enquanto investidores avaliavam a empresa em US$ 9 bilhões, 94% dos testes reais eram rodados escondidos em máquinas comerciais de terceiros.",
        "quote_en": "While investors valued the startup at $9 billion, over 90% of patient tests were secretly run on diluted samples using third-party machines.",
        "broll_queries": [
            "medical laboratory blood test science",
            "modern tech office silicon valley",
            "laboratory microscope medical equipment",
            "washington dc capitol architecture",
            "corporate glass building night",
            "courthouse justice building",
        ],
        "pip_queries": [
            "medical laboratory blood sample tube",
            "stock market trading monitors",
            "newspaper printing press",
            "scientist working laboratory",
            "corporate boardroom executives",
        ],
        "photo_queries": [
            "medical laboratory blood sample",
            "scientist microscope laboratory",
            "modern corporate office building",
            "federal courthouse architecture",
            "pharmacy medicine laboratory",
            "businessman suit office portrait",
        ],
        "timeline": [
            {"date": "2003", "label": "Fundação em Stanford", "value": "US$ 6M"},
            {"date": "2013", "label": "Acordo Farmácias", "value": "US$ 1.5B"},
            {"date": "2014", "label": "Pico de Valuation", "value": "US$ 9.0B"},
            {"date": "2018", "label": "Colapso & Indiciamento", "value": "US$ 0"},
        ],
        "nodes": [
            {"id": "n1", "title": "ELIZABETH HOLMES", "role": "CEO & Fundadora", "badge": "US$ 9 BILHÕES"},
            {"id": "n2", "title": "MÁQUINA EDISON", "role": "Promessa de 200 Exames", "badge": "FALHA TÉCNICA"},
            {"id": "n3", "title": "LAB SECRETO", "role": "Máquinas Comerciais", "badge": "AMOSTRAS DILUÍDAS"},
            {"id": "n4", "title": "DENÚNCIA WSJ", "role": "Investigação Forense", "badge": "COLAPSO TOTAL"},
        ],
        "narr_pt": [
            "Ela convenceu generais, ex-secretários de Estado e bilionários do Vale do Silício de que uma única gota de sangue faria duzentos exames — mas a máquina não funcionava.",
            "Documentos internos revelaram que quando os executivos visitavam a sede em Palo Alto, o aparelho Edison exibia apenas uma simulação pré-gravada na tela.",
            "Enquanto a empresa captava mais de setecentos milhões de dólares de investidores, as amostras reais eram levadas por uma porta trancada para máquinas comuns de mercado.",
            "Em 2015, um denunciante interno entregou os registros de laboratório à imprensa e aos reguladores federais, expondo resultados imprecisos em milhares de pacientes.",
            "Em poucos meses, o império de nove bilhões de dólares virou pó e entrou para a história como a maior ilusão corporativa do Vale do Silício.",
        ],
        "narr_en": [
            "She convinced four-star generals, former cabinet secretaries, and Silicon Valley billionaires that a single drop of blood could run two hundred tests — except the machine did not work.",
            "Internal records revealed that whenever VIP investors toured the Palo Alto headquarters, the Edison box on the desk was playing a pre-recorded software demo.",
            "While the company raised over seven hundred million dollars across private rounds, real blood samples were quietly routed through a locked basement to commercial analyzers.",
            "In 2015, a courageous lab whistleblower handed forensic logs to investigative reporters and regulators, exposing flawed results sent to real patients.",
            "Within months, a nine-billion-dollar unicorn evaporated into zero and became Silicon Valley's ultimate cautionary tale.",
        ],
    },
    {
        "keywords": ("evaldas", "rimasauskas", "boletos falsos", "fake invoices", "operação quanta"),
        "title_pt": "O Homem que Enviou Boletos Falsos para o Vale do Silício — E Eles Pagaram",
        "title_en": "The Man Who Emailed Fake Invoices to Big Tech — And They Paid $122M",
        "sub_pt": "Dossiê Crimes Cibernéticos • Operação Quanta",
        "sub_en": "Cyber Forensics File • The $122M Invoice Scheme",
        "hook_pt": "ELES PAGARAM TUDO",
        "hook_en": "THEY JUST PAID",
        "origin": "VILNIUS",
        "dest": "VALE DO SILÍCIO",
        "metric_pt": "US$ 122 MILHÕES TRANSFERIDOS",
        "metric_en": "$122 MILLION WIRED",
        "headline": "LITHUANIAN SHELL COMPANY COLLECTS $122M FROM TECH GIANTS VIA EMAIL",
        "quote_pt": "Sem invadir nenhum servidor com código complexo, Rimasauskas registrou uma empresa homônima na Letônia e simplesmente enviou faturas por e-mail.",
        "quote_en": "Without deploying zero-day malware, Rimasauskas registered an identical supplier name in Latvia and emailed payment requests.",
        "broll_queries": [
            "cybersecurity computer screen code dark",
            "data center server room lights",
            "bank vault money bills",
            "european city skyline night aerial",
            "office laptop keyboard typing",
            "hong kong skyline night",
        ],
        "pip_queries": [
            "laptop keyboard typing dark screen",
            "money bills dark finance",
            "server room data center",
            "modern skyscraper architecture",
            "stock market trading monitors",
        ],
        "photo_queries": [
            "data center server room",
            "laptop computer office desk",
            "european historic city architecture",
            "historic bank building architecture",
            "money bills finance dark",
            "corporate boardroom office",
        ],
        "timeline": [
            {"date": "2013", "label": "Empresa Homônima Criada", "value": "US$ 0"},
            {"date": "2014", "label": "Primeira Remessa Paga", "value": "US$ 23M"},
            {"date": "2015", "label": "Segunda Onda de Faturas", "value": "US$ 99M"},
            {"date": "2017", "label": "Rastreio Internacional", "value": "US$ 122M"},
        ],
        "nodes": [
            {"id": "n1", "title": "E. RIMASAUSKAS", "role": "Operador em Vilnius", "badge": "E-MAILS FALSOS"},
            {"id": "n2", "title": "QUANTA FICTÍCIA", "role": "Clone de Fornecedor Real", "badge": "LETÔNIA"},
            {"id": "n3", "title": "SETOR FINANCEIRO", "role": "Aprovação Automática", "badge": "US$ 122 MILHÕES"},
            {"id": "n4", "title": "6 PAÍSES", "role": "Bancos em Chipre e HK", "badge": "CONFISCADO"},
        ],
        "narr_pt": [
            "Ele não usou supercomputadores nem invadiu servidores secretos: ele apenas enviou boletos e faturas por e-mail para duas das maiores empresas de tecnologia do planeta — e elas pagaram cento e vinte e dois milhões de dólares.",
            "De um quarto na Lituânia, Evaldas Rimasauskas descobriu o nome exato de uma fabricante asiática que fornecia peças reais de servidores para o Vale do Silício.",
            "Ele abriu uma empresa com exatamente o mesmo nome na Letônia, falsificou carimbos simples e mandou e-mails cobrando lotes de hardware para o setor de contas a pagar.",
            "Durante dois anos, transferências milionárias saíram da Califórnia direto para contas na Europa Oriental, Chipre e Hong Kong sem ninguém checar o código bancário.",
            "Quando uma auditoria finalmente percebeu o erro de cento e vinte e dois milhões, o dinheiro já havia dado a volta ao mundo em seis jurisdições diferentes.",
        ],
        "narr_en": [
            "He did not write advanced malware or breach a firewall: he simply emailed invoices to two of the richest tech giants on Earth — and they wired him one hundred and twenty-two million dollars.",
            "From a quiet apartment in Lithuania, Evaldas Rimasauskas identified the exact Taiwanese hardware manufacturer supplying server racks to Silicon Valley.",
            "He incorporated a shell company with the exact same name in Latvia, forged basic stamps, and emailed billing requests straight to corporate accounts payable.",
            "For two full years, multi-million-dollar wires flowed from California into bank accounts across Latvia, Cyprus, and Hong Kong without triggering an alarm.",
            "By the time auditors noticed the one-hundred-and-twenty-two-million-dollar discrepancy, the funds had already been split across six international jurisdictions.",
        ],
    },
    {
        "keywords": ("camarão infinito", "camarao infinito", "red lobster", "endless shrimp"),
        "title_pt": "O Dia em que o Camarão Infinito de US$ 20 Afundou uma Rede Bilionária",
        "title_en": "How $20 Endless Shrimp Sank a Billion-Dollar Restaurant Empire",
        "sub_pt": "Dossiê Corporativo • Colapso Red Lobster",
        "sub_en": "Corporate Autopsy • The Endless Shrimp Disaster",
        "hook_pt": "PREJUÍZO INFINITO",
        "hook_en": "INFINITE LOSS",
        "origin": "ORLANDO",
        "dest": "BANGKOK",
        "metric_pt": "-US$ 11 MILHÕES EM 90 DIAS",
        "metric_en": "-$11M OPERATING SHOCK",
        "headline": "PERMANENT $20 ENDLESS SHRIMP PROMOTION TRIGGERS CHAPTER 11 FILING",
        "quote_pt": "A fornecedora controladora transformou a promoção temporária de US$ 20 em item fixo do cardápio para escoar seu próprio estoque de camarão.",
        "quote_en": "Major supplier shareholders pushed to make the $20 promotion permanent while restaurant leases were already inflated.",
        "broll_queries": [
            "restaurant kitchen cooking seafood",
            "busy restaurant dining room night",
            "commercial real estate city skyline",
            "cargo shipping port containers",
            "corporate boardroom executives",
            "money bills dark finance",
        ],
        "pip_queries": [
            "seafood shrimp food cooking",
            "stock market trading monitors",
            "cash register money finance",
            "restaurant dining interior",
            "modern skyscraper architecture",
        ],
        "photo_queries": [
            "seafood shrimp restaurant plate",
            "restaurant interior dining tables",
            "commercial real estate building",
            "restaurant chef kitchen cooking",
            "money bills finance dark",
            "corporate boardroom office",
        ],
        "timeline": [
            {"date": "2014", "label": "Venda dos Imóveis (Leaseback)", "value": "US$ 1.5B"},
            {"date": "2020", "label": "Fornecedor Assume Controle", "value": "US$ 575M"},
            {"date": "2023", "label": "Camarão Infinito Fixo US$ 20", "value": "-US$ 11M"},
            {"date": "2024", "label": "Pedido de Recuperação Cap. 11", "value": "US$ 1B DÍVIDA"},
        ],
        "nodes": [
            {"id": "n1", "title": "PROMOÇÃO US$ 20", "role": "Camarão Sem Limite", "badge": "PREJUÍZO POR MESA"},
            {"id": "n2", "title": "LEASEBACK IMÓVEIS", "role": "Aluguel de US$ 200M/Ano", "badge": "CAIXA DRENADO"},
            {"id": "n3", "title": "FORNECEDOR GLOBAL", "role": "Escoamento de Estoque", "badge": "CONFLITO INTERNO"},
            {"id": "n4", "title": "CHAPTER 11", "role": "Mais de 100 Lojas Fechadas", "badge": "COLAPSO 2024"},
        ],
        "narr_pt": [
            "Parecia a promoção perfeita para atrair clientes: pague vinte dólares e coma camarão à vontade — só que os clientes aceitaram o desafio a sério demais.",
            "Em 2023, a tradicional rede americana Red Lobster decidiu transformar o festival temporário de camarão infinito em um prato fixo do cardápio todos os dias.",
            "Clientes passaram a ficar três horas na mesa e viralizaram no TikTok batendo recordes de mais de cem camarões por pessoa pagando apenas vinte dólares.",
            "Mas o verdadeiro golpe estava nos bastidores: anos antes, os terrenos das lojas haviam sido vendidos, obrigando a rede a pagar duzentos milhões por ano de aluguel.",
            "Somando aluguéis sufocantes com milhões de prejuízo no camarão, o império de setecentos restaurantes entrou em recuperação judicial com um bilhão em dívidas.",
        ],
        "narr_en": [
            "It sounded like the ultimate marketing hook: pay twenty dollars for all-you-can-eat shrimp — except hungry customers took the challenge literally.",
            "In 2023, restaurant giant Red Lobster made its temporary Endless Shrimp event a permanent everyday menu item at twenty dollars.",
            "Diners camped at tables for three hours and went viral on TikTok eating over a hundred shrimp on a single twenty-dollar bill.",
            "Yet the deeper trap lay behind the scenes: a prior sale-leaseback deal had stripped the company of its real estate, locking in two hundred million a year in rent.",
            "Crushed between soaring lease obligations and millions lost at the shrimp buffet, the seven-hundred-location chain filed for Chapter 11 with a billion dollars in debt.",
        ],
    },
    {
        "keywords": ("adidas", "puma", "dassler", "herzogenaurach"),
        "title_pt": "A Cidade Dividida ao Meio: A Guerra Secreta entre os Irmãos Adidas e Puma",
        "title_en": "Blood Rivals: How Two Feuding Brothers Split a Town into Adidas and Puma",
        "sub_pt": "Dossiê Histórico • Herzogenaurach, 1948",
        "sub_en": "Historical File • The Herzogenaurach Split",
        "hook_pt": "IRMÃOS INIMIGOS",
        "hook_en": "BLOOD RIVALS",
        "origin": "MARGEM NORTE",
        "dest": "MARGEM SUL",
        "metric_pt": "US$ 45 BILHÕES EM GUERRA",
        "metric_en": "$45B COMBINED RIVALRY",
        "headline": "TWO BROTHERS SPLIT ONE SHOE FACTORY ACROSS THE AURACH RIVER",
        "quote_pt": "Durante 60 anos, os moradores olhavam primeiro para os pés de um estranho antes de decidir se conversavam com ele.",
        "quote_en": "For six decades, townspeople looked down at a stranger's shoes before speaking a single word.",
        "broll_queries": [
            "running shoes athlete track stadium",
            "germany historic town river aerial",
            "soccer football stadium crowd night",
            "industrial leather workshop craft",
            "european bridge river historic town",
            "corporate headquarters glass building",
        ],
        "pip_queries": [
            "athlete sprinting running track",
            "soccer football stadium field",
            "vintage shoe workshop craft",
            "german town historic streets",
            "crowd stadium sports lights",
        ],
        "photo_queries": [
            "running shoes athletic track",
            "german historic town river",
            "football soccer stadium",
            "leather workshop craft vintage",
            "athlete runner stadium track",
            "historic european factory building",
        ],
        "timeline": [
            {"date": "1924", "label": "Fábrica Irmãos Dassler", "value": "1ª MEDALHA"},
            {"date": "1948", "label": "Ruptura & Rio Aurach", "value": "2 FÁBRICAS"},
            {"date": "1970", "label": "Pacto Pelé na Copa", "value": "QUEBRA DO ACORDO"},
            {"date": "2009", "label": "Primeira Trégua Oficial", "value": "61 ANOS DEPOIS"},
        ],
        "nodes": [
            {"id": "n1", "title": "ADI DASSLER", "role": "O Artesão Inventor", "badge": "FUNDOU A ADIDAS"},
            {"id": "n2", "title": "RUDI DASSLER", "role": "O Vendedor Agressivo", "badge": "FUNDOU A PUMA"},
            {"id": "n3", "title": "RIO AURACH", "role": "Fronteira na Cidade", "badge": "CIDADE DIVIDIDA"},
            {"id": "n4", "title": "COPA DE 1970", "role": "Pelé Amarra a Chuteira", "badge": "GOLPE DE MESTRE"},
        ],
        "narr_pt": [
            "Em uma pequena cidade da Alemanha, as pessoas aprenderam a olhar para os sapatos umas das outras antes de dar bom dia — porque dois irmãos declararam guerra total.",
            "Adi e Rudolf Dassler começaram fabricando calçados esportivos juntos na lavanderia da mãe em 1924, mas desconfianças na Segunda Guerra Mundial destruíram a família.",
            "Em 1948, eles dividiram os funcionários e as máquinas ao meio: Adi ficou de um lado do rio e criou a Adidas; Rudolf atravessou a ponte e fundou a Puma.",
            "A rivalidade explodiu na Copa de 1970, quando a Puma pagou a Pelé para pedir ao juiz alguns segundos antes do apito inicial e amarrar as chuteiras diante de todas as câmeras do mundo.",
            "Mesmo depois da morte dos dois irmãos, eles foram enterrados nas extremidades opostas do mesmo cemitério para nunca mais ficarem lado a lado.",
        ],
        "narr_en": [
            "In one small German town, residents learned to look down at a stranger's shoes before saying hello — because two brothers turned their family business into total war.",
            "Adi and Rudolf Dassler started cobbling track spikes together in their mother's laundry room in 1924, until bitter World War II suspicions tore them apart.",
            "In 1948, they split the factory assets down the middle: Adi stayed north of the river to launch Adidas, while Rudolf crossed the bridge to create Puma.",
            "The feud peaked at the 1970 World Cup, when Puma covertly paid Pelé to pause at kickoff and tie his boots in front of every television camera on Earth.",
            "Even in death, the two brothers were buried at opposite ends of the town cemetery so they would never rest side by side.",
        ],
    },
    {
        "keywords": ("pepsi", "harrier", "john leonard", "7 milhões de pontos", "7 million pepsi"),
        "title_pt": "O Estudante que Juntou 7 Milhões de Pontos e Exigiu o Caça Militar da Pepsi",
        "title_en": "The College Student Who Bought 7 Million Pepsi Points to Claim a Fighter Jet",
        "sub_pt": "Dossiê Jurídico • Leonard v. Pepsico (1996)",
        "sub_en": "Legal File • Leonard v. Pepsico, 7,000,000 Points",
        "hook_pt": "ELE JUNTOU OS PONTOS",
        "hook_en": "HE BOUGHT IT",
        "origin": "SEATTLE",
        "dest": "NOVA YORK",
        "metric_pt": "7.000.000 DE PONTOS",
        "metric_en": "7,000,000 PEPSI POINTS",
        "headline": "STUDENT SENDS $700,000 CHECK TO CLAIM HARRIER JET FROM TV COMMERCIAL",
        "quote_pt": "O regulamento impresso permitia comprar pontos extras por 10 centavos cada — transformando um caça de US$ 33 milhões em uma oferta de US$ 700 mil.",
        "quote_en": "Fine print in the catalog allowed buying extra points at 10 cents each — pricing a $33M Harrier Jet at just $700,000.",
        "broll_queries": [
            "military fighter jet flying sky",
            "television broadcast studio vintage",
            "new york city skyline aerial",
            "courthouse law justice building",
            "money bills bank finance",
            "corporate boardroom executives",
        ],
        "pip_queries": [
            "fighter jet aircraft takeoff",
            "retro television static screen",
            "manhattan skyscrapers aerial",
            "newspaper printing press",
            "law courtroom gavel justice",
        ],
        "photo_queries": [
            "military fighter jet aircraft",
            "new york city skyline",
            "courthouse building architecture",
            "vintage television broadcast",
            "business contract documents desk",
            "businessman suit office portrait",
        ],
        "timeline": [
            {"date": "1996", "label": "Comercial na TV sem Aviso", "value": "7.000.000 PTS"},
            {"date": "MAR/96", "label": "Descoberta da Brecha de US$ 0.10", "value": "US$ 700.000"},
            {"date": "MAI/96", "label": "Cheque Enviado à Pepsi", "value": "RECUSADO"},
            {"date": "1999", "label": "Sentença Federal em NY", "value": "CASO HISTÓRICO"},
        ],
        "nodes": [
            {"id": "n1", "title": "JOHN LEONARD", "role": "Estudante de 21 Anos", "badge": "DESCOBRIU A BRECHA"},
            {"id": "n2", "title": "TODD HOFFMAN", "role": "Investidor Anjo", "badge": "CHEQUE US$ 700K"},
            {"id": "n3", "title": "AV-8 HARRIER II", "role": "Caça de Pouso Vertical", "badge": "VALIA US$ 33M"},
            {"id": "n4", "title": "CATÁLOGO PEPSI", "role": "US$ 0,10 por Ponto Extra", "badge": "SEM LETRA MIÚDA"},
        ],
        "narr_pt": [
            "Em 1996, um comercial de televisão mostrou um caça militar Harrier de trinta e três milhões de dólares por sete milhões de pontos Pepsi sem nenhuma letra miúda na tela.",
            "Para juntar sete milhões de rótulos seria preciso beber dezenove mil latas por dia durante um ano — mas um estudante de vinte e um anos leu o catálogo até a última linha.",
            "No rodapé do formulário estava escrito que qualquer cliente podia ter apenas quinze pontos físicos e comprar o restante por dez centavos de dólar cada ponto.",
            "John Leonard fez a conta: sete milhões de pontos custavam exatamente setecentos mil dólares, então ele convenceu um investidor e enviou o cheque autenticado para a sede da empresa.",
            "A batalha judicial parou nos tribunais federais de Nova York e obrigou a indústria publicitária mundial a reescrever para sempre as regras de letras miúdas na TV.",
        ],
        "narr_en": [
            "In 1996, a television commercial flashed a thirty-three-million-dollar Harrier fighter jet for seven million Pepsi Points without a single disclaimer on screen.",
            "Collecting seven million physical labels meant drinking nineteen thousand sodas a day — until a twenty-one-year-old student read the printed catalog's final paragraph.",
            "Buried in the order rules was a clause allowing anyone with fifteen physical labels to purchase the remaining points for ten cents each.",
            "John Leonard did the math: seven million points cost exactly seven hundred thousand dollars, so he raised the money from an investor and mailed a certified check.",
            "The resulting federal lawsuit in New York became a landmark contract-law ruling that forever changed how television commercials write their disclaimers.",
        ],
    },
    {
        "keywords": ("wirecard", "marsalek", "dinheiro fantasma", "2 bilhões fantasmas", "ghost fortune"),
        "title_pt": "Wirecard: Os US$ 2 Bilhões Fantasmas que Enganaram a Europa Inteira",
        "title_en": "Wirecard: The $2 Billion Ghost Fortune That Fooled Europe",
        "sub_pt": "Dossiê Frankfurt & Manila • O Dinheiro Que Nunca Existiu",
        "sub_en": "Frankfurt & Manila File • The Missing €1.9 Billion",
        "hook_pt": "DINHEIRO FANTASMA",
        "hook_en": "GHOST BILLIONS",
        "origin": "MUNIQUE",
        "dest": "MANILA",
        "metric_pt": "US$ 2.1 BILHÕES INEXISTENTES",
        "metric_en": "$2.1 BILLION MISSING",
        "headline": "PHILIPPINE CENTRAL BANK CONFIRMS $2.1B WIRECARD ESCROW NEVER ENTERED COUNTRY",
        "quote_pt": "Um quarto de todo o lucro declarado pela gigante alemã do índice DAX estava supostamente guardado em duas contas asiáticas que nunca existiram.",
        "quote_en": "A quarter of the DAX-listed fintech's balance sheet sat inside two Philippine escrow accounts that turned out to be total fabrications.",
        "broll_queries": [
            "frankfurt financial skyline night",
            "stock market trading monitors",
            "asia city skyline night aerial",
            "bank vault money bills",
            "private jet airport tarmac night",
            "corporate boardroom executives",
        ],
        "pip_queries": [
            "stock market trading monitors",
            "bank vault money bills",
            "newspaper printing press",
            "private jet flying night",
            "frankfurt skyscraper city",
        ],
        "photo_queries": [
            "frankfurt financial skyline skyscrapers",
            "stock market trading floor",
            "historic bank building architecture",
            "private jet airport tarmac",
            "businessman suit office portrait",
            "money bills finance dark",
        ],
        "timeline": [
            {"date": "2018", "label": "Entrada no Índice DAX-30", "value": "US$ 28B"},
            {"date": "2019", "label": "Reportagens Financial Times", "value": "NEGADO"},
            {"date": "JUN/20", "label": "Bancos nas Filipinas Negam Saldo", "value": "-US$ 2.1B"},
            {"date": "JUL/20", "label": "Fuga de Marsalek & Falência", "value": "COLAPSO DAX"},
        ],
        "nodes": [
            {"id": "n1", "title": "WIRECARD AG", "role": "Estrela do Índice DAX-30", "badge": "VALIA US$ 28B"},
            {"id": "n2", "title": "JAN MARSALEK", "role": "COO & Operador Fantasma", "badge": "FORAGIDO"},
            {"id": "n3", "title": "BANCOS EM MANILA", "role": "Certificados Falsificados", "badge": "SALDO ZERO"},
            {"id": "n4", "title": "US$ 2.1 BILHÕES", "role": "Caixa Fictício Declarado", "badge": "NUNCA EXISTIU"},
        ],
        "narr_pt": [
            "Ela era a joia tecnológica da Alemanha, avaliada em vinte e oito bilhões de dólares no principal índice da bolsa de Frankfurt — até alguém ligar para dois bancos nas Filipinas.",
            "Durante anos, quando jornalistas questionavam a contabilidade da Wirecard, os reguladores protegiam a empresa e investigavam os próprios repórteres.",
            "No balanço oficial constavam dois vírgula um bilhões de dólares em dinheiro vivo guardados em contas fiduciárias na Ásia, representando quase todo o lucro acumulado do grupo.",
            "Em junho de 2020, auditores exigiram confirmação direta e o Banco Central das Filipinas respondeu com uma frase: esse dinheiro nunca entrou no nosso sistema financeiro.",
            "Em setenta e duas horas, o diretor de operações fugiu em um jato particular e a maior fintech da Europa declarou insolvência.",
        ],
        "narr_en": [
            "It was Germany's crown-jewel fintech, valued at twenty-eight billion dollars on Frankfurt's elite DAX index — until auditors finally called two banks in the Philippines.",
            "For years, whenever investigative reporters questioned Wirecard's profit margins, authorities defended the company and even probed the journalists.",
            "On paper, two point one billion dollars in cash sat safely inside Asian escrow accounts, representing nearly the entire historical profit of the enterprise.",
            "In June 2020, electronic verification was demanded and the Philippine Central Bank delivered a stunner: that money had never entered their financial system.",
            "Within seventy-two hours, the chief operating officer vanished on a private flight and Europe's premier tech champion collapsed into insolvency.",
        ],
    },
    {
        "keywords": ("forest city", "estreito de johor", "metrópole futurista de us$ 100", "futuristic mega-city", "ghost archipelago"),
        "title_pt": "Forest City: A Metrópole Futurista de US$ 100 Bilhões que Está 98% Vazia",
        "title_en": "Forest City: Inside the $100 Billion Futuristic Megacity Sitting 98% Empty",
        "sub_pt": "Dossiê Megaprojetos • Estreito de Johor",
        "sub_en": "Megaproject File • The $100B Ghost Archipelago",
        "hook_pt": "98% VAZIA",
        "hook_en": "98% EMPTY",
        "origin": "SHENZHEN",
        "dest": "ESTREITO DE JOHOR",
        "metric_pt": "US$ 100 BILHÕES PROJETADOS",
        "metric_en": "$100B MEGAPROJECT STALLED",
        "headline": "FOUR ARTIFICIAL ISLANDS BUILT FOR 700,000 RESIDENTS STAND 98% UNINHABITED",
        "quote_pt": "Projetada para abrigar 700 mil pessoas em ilhas artificiais ao lado de Singapura, menos de 1% da capacidade foi ocupada após controles de capital.",
        "quote_en": "Engineered on reclaimed islands for 700,000 people across from Singapore, abrupt capital controls froze buyer inflows overnight.",
        "broll_queries": [
            "futuristic skyscrapers aerial city",
            "singapore skyline night aerial",
            "construction skyscraper crane building",
            "empty city highway night",
            "modern luxury highrise apartments",
            "ocean island coast aerial",
        ],
        "pip_queries": [
            "modern skyscraper architecture",
            "empty shopping mall interior",
            "singapore financial district",
            "money bills dark finance",
            "city skyline night aerial",
        ],
        "photo_queries": [
            "modern skyscraper towers architecture",
            "singapore skyline night",
            "empty city boulevard skyscrapers",
            "construction skyscraper crane",
            "luxury condo tower exterior",
            "corporate boardroom office",
        ],
        "timeline": [
            {"date": "2016", "label": "Aterro de 4 Ilhas Artificiais", "value": "US$ 100B PLANO"},
            {"date": "2017", "label": "Limite de Remessas Externas", "value": "-85% VENDAS"},
            {"date": "2020", "label": "Fronteiras Fechadas", "value": "OBRAS PARADAS"},
            {"date": "2024", "label": "Menos de 9.000 Moradores", "value": "98% VAZIA"},
        ],
        "nodes": [
            {"id": "n1", "title": "FOREST CITY", "role": "Meta: 700.000 Habitantes", "badge": "4 ILHAS ARTIFICIAIS"},
            {"id": "n2", "title": "US$ 500K / APTO", "role": "Inacessível ao Mercado Local", "badge": "FOCO EXTERNO"},
            {"id": "n3", "title": "CONTROLE CAMBIAL", "role": "Teto de US$ 50K/Ano", "badge": "COMPRADORES TRAVADOS"},
            {"id": "n4", "title": "TORRES VAZIAS", "role": "Apenas ~2% de Ocupação", "badge": "CIDADE FANTASMA"},
        ],
        "narr_pt": [
            "Imagine construir quatro ilhas artificiais do zero, erguer dezenas de arranha-céus cobertos de florestas verticais por cem bilhões de dólares — e quase ninguém ir morar lá.",
            "Lançada em 2016 no sul da Malásia, a poucos minutos da fronteira com Singapura, Forest City foi planejada para receber setecentos mil moradores de alta renda.",
            "Só que os apartamentos custavam cinco vezes mais do que a classe média local podia pagar, pois todo o projeto dependia de compradores estrangeiros pagando à vista.",
            "Quando novos controles cambiais limitaram o envio de dinheiro para imóveis no exterior em cinquenta mil dólares por ano, as vendas secaram da noite para o dia.",
            "Hoje, avenidas de seis pistas, shoppings inteiros e dezenas de torres continuam com noventa e oito por cento dos apartamentos apagados no meio do oceano.",
        ],
        "narr_en": [
            "Imagine reclaiming four artificial islands from the sea and building dozens of jungle-wrapped skyscrapers under a hundred-billion-dollar masterplan — only for almost nobody to move in.",
            "Launched in 2016 at the southern tip of Malaysia looking straight across at Singapore, Forest City was engineered to house seven hundred thousand residents.",
            "Yet the luxury condos were priced far above local salaries, relying almost entirely on foreign buyers wiring capital from abroad.",
            "When sudden currency rules capped overseas property transfers at fifty thousand dollars a year, the buyer pipeline vanished overnight.",
            "Today, six-lane boulevards, sprawling shopping malls, and towers of luxury apartments sit ninety-eight percent dark above the ocean.",
        ],
    },
    {
        "keywords": ("12.150", "12,150", "david phillips", "pudim", "pudins", "pudding", "milhas aéreas infinitas", "milhas aéreas vitalícias"),
        "title_pt": "O Engenheiro que Comprou 12.150 Pudins de US$ 0,25 e Ganhou Milhas Aéreas Vitalícias",
        "title_en": "The Engineer Who Bought 12,150 Cups of 25-Cent Pudding for Lifetime Frequent-Flyer Miles",
        "sub_pt": "Dossiê Arbitragem • A Brecha de 1,25 Milhão de Milhas",
        "sub_en": "Arbitrage File • The 1.25 Million Mile Loophole",
        "hook_pt": "BRECHA GENIAL",
        "hook_en": "THE PUDDING GLITCH",
        "origin": "DAVIS, CA",
        "dest": "MUNDO INTEIRO",
        "metric_pt": "1.253.000 MILHAS POR US$ 3.140",
        "metric_en": "1,253,000 MILES FOR $3,140",
        "headline": "CIVIL ENGINEER EXPLOITS 25-CENT PUDDING BARCODE PROMOTION FOR 1.25M AIR MILES",
        "quote_pt": "Ao doar os 12.150 potes para o banco de alimentos em troca de ajudar a retirar os códigos de barras, ele ainda abateu US$ 815 no imposto de renda.",
        "quote_en": "By donating all 12,150 pudding cups to charity in exchange for peeling the barcodes, he even earned an $815 tax deduction.",
        "broll_queries": [
            "supermarket grocery store aisle",
            "commercial airplane takeoff runway",
            "airport terminal departure flight",
            "california city skyline aerial",
            "airplane window clouds sky",
            "money bills dark finance",
        ],
        "pip_queries": [
            "airplane flying above clouds",
            "supermarket shopping cart aisle",
            "airport terminal departure board",
            "calculator accounting finance desk",
            "commercial jet landing airport",
        ],
        "photo_queries": [
            "supermarket grocery store shelves",
            "commercial airplane flying sky",
            "airport terminal airplane",
            "chocolate pudding dessert",
            "engineer blueprints desk office",
            "businessman suit office portrait",
        ],
        "timeline": [
            {"date": "MAI/99", "label": "Promoção 1.000 Milhas a Cada 10 Códigos", "value": "US$ 0.25 / POTE"},
            {"date": "JUN/99", "label": "Compra de 12.150 Potes de Pudim", "value": "US$ 3.140"},
            {"date": "JUL/99", "label": "Doação + Abatimento Fiscal", "value": "-US$ 815 IR"},
            {"date": "AGO/99", "label": "Crédito Final na Conta Aérea", "value": "1.253.000 MILHAS"},
        ],
        "nodes": [
            {"id": "n1", "title": "DAVID PHILLIPS", "role": "Engenheiro Civil", "badge": "CALCULOU A BRECHA"},
            {"id": "n2", "title": "12.150 PUDINS", "role": "US$ 0,25 por Unidade", "badge": "CUSTO US$ 3.140"},
            {"id": "n3", "title": "BANCO DE ALIMENTOS", "role": "Destacou os Códigos", "badge": "DEDUÇÃO FISCAL"},
            {"id": "n4", "title": "1,25 MILHÃO MILHAS", "role": "Equivalente a 31 Viagens", "badge": "VALIA US$ 150.000+"},
        ],
        "narr_pt": [
            "Em 1999, um engenheiro civil da Califórnia entrou em um supermercado, olhou para um potinho de pudim de vinte e cinco centavos e descobriu como viajar de primeira classe pelo resto da vida.",
            "Uma promoção da fabricante oferecia mil milhas aéreas para cada dez códigos de barras enviados até o fim do mês, achando que ninguém compraria centenas de caixas.",
            "David Phillips fez a conta na hora: dez potes custavam dois dólares e cinquenta centavos e rendiam mil milhas que valiam mais de vinte e cinco dólares em passagens.",
            "Ele esvaziou dez supermercados comprando doze mil cento e cinquenta pudins por três mil cento e quarenta dólares e doou toda a comida para uma instituição em troca de ajuda para descolar os rótulos.",
            "A empresa cumpriu a regra e depositou um milhão duzentas e cinquenta e três mil milhas na conta dele — uma fortuna em voos internacionais por uma fração do preço.",
        ],
        "narr_en": [
            "In 1999, a California civil engineer walked down a grocery aisle, spotted a twenty-five-cent cup of chocolate pudding, and discovered a mathematical path to lifetime flights.",
            "A promotional campaign offered one thousand frequent-flyer miles for every ten product barcodes mailed in by the end of the month.",
            "David Phillips ran the numbers on the spot: ten pudding cups cost two dollars and fifty cents yet generated one thousand air miles worth over twenty-five dollars.",
            "He swept through ten stores buying twelve thousand one hundred and fifty pudding cups for three thousand one hundred and forty dollars, then donated the food to charity in exchange for help peeling the labels.",
            "The company honored every barcode and deposited one million two hundred and fifty-three thousand air miles into his account — unlocking decades of free global travel.",
        ],
    },
]


_DARK_HORROR_TOPIC_RE = re.compile(
    r"("
    r"macabr|terror|horror|sombri|assustador|maldi[cç]|dem[oô]ni|krampus|saturn[aá]lia|"
    r"brux|witch|fantasm|ghost|ocult|ritual|pag[aã]o|pagan|vampir|dr[aá]cula|exorcis|"
    r"monstr|pesadelo|cemit[eé]ri|catacumb|creepy|haunted|folclore|folklore|lenda|"
    r"sinistr|assombra|sobrenatural|infern|bizarro|satan|natal\s+macabr|lado\s+sombri|"
    r"dark\s+history|dark\s+secret|macabre|cursed|scary|disturbing|nightmare|grim"
    r")",
    re.IGNORECASE,
)

_CRIME_TOPIC_RE = re.compile(
    r"("
    r"crime|assassin|serial\s+killer|mist[eé]ri|desaparec|sequestr|fbi|pol[ií]ci|"
    r"detetive|caso\s+real|true\s+crime|conspira[cç]|m[aá]fia|cartel|espionag|"
    r"murder|unsolved|mystery|heist|roubo|pris[aã]o|fuga|enigma|homic[ií]di|"
    r"investiga[cç][aã]o\s+criminal|cold\s+case"
    r")",
    re.IGNORECASE,
)

_CORPORATE_TOPIC_RE = re.compile(
    r"("
    r"banco|bank|bilh[oõ]es|billion|milh[oõ]es|million|bolsa|stock|fraude|fraud|"
    r"monop[oó]li|empresa|startup|corporate|finan[cç]|wall\s+street|cripto|crypto|"
    r"bitcoin|im[oó]veis|dinheiro|money|capital|mercado|a[cç][oõ]es|fal[eê]ncia|"
    r"investidor|ceo|economia|imposto|offshore|esquema|pir[aâ]mide|golpe\s+financeiro"
    r")",
    re.IGNORECASE,
)

_HISTORY_TOPIC_RE = re.compile(
    r"("
    r"hist[oó]ri|imp[eé]ri|roma|egit|gr[eé]ci|guerra|medieval|s[eé]culo|antiguid|"
    r"civiliza[cç]|batalha|fara[oó]|viking|samurai|revolu[cç]|descobert|ci[eê]nci|"
    r"espa[cç]o|universo|biografi|inventor|rei|rainha|imperador|mitologia|natal|"
    r"history|ancient|empire|war|biography|science|origin|origens|origem"
    r")",
    re.IGNORECASE,
)

_FORBIDDEN_FINANCE_LEFTOVERS_RE = re.compile(
    r"\b(barings|leeson|88888|singapura|singapore|zurique|zurich|londres\s*[•\-]\s*singapura|"
    r"conta\s+secreta|holding\s+offshore|auditoria\s+forense|stock\s+market\s+trading|"
    r"historic\s+bank\s+building\s+london|london\s+financial\s+district|"
    r"dossi[eê]\s+capital|vault\s+files)\b",
    re.IGNORECASE,
)


def _enforce_vertical_prompt_framing(prompt: str) -> str:
    """Replace landscape/wide framing cues with vertical 9:16 portrait cues so Google Flow never flips to landscape."""
    p = str(prompt or "").strip()
    if not p:
        return p
    p = re.sub(
        r"\b(?:dramatic\s+)?wide\s+establishing(?:\s+35mm)?(?:\s+cinema)?(?:\s+still)?(?:\s+shot)?\b",
        "vertical full-bleed 9:16 35mm cinema still",
        p,
        flags=re.IGNORECASE,
    )
    p = re.sub(
        r"\b(?:dramatic\s+)?wide[\s-]+(?:angle|shot|cinematic|establishing|view|vista)\b",
        "intimate vertical 9:16 cinema shot",
        p,
        flags=re.IGNORECASE,
    )
    p = re.sub(r"\b(?:widescreen|panoramic|landscape|16:9)\b", "vertical 9:16", p, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", p).strip()


def _estimate_chapter_count(n_scenes: int) -> int:
    """Return exact number of chapter cards assigned for a documentary of `n_scenes` scenes."""
    if n_scenes <= 1:
        return 0
    chapter_step = max(2, n_scenes // min(4, max(2, n_scenes // 2)))
    count = 0
    for idx in range(1, n_scenes):
        if idx == 1 or (idx >= 3 and (idx - 1) % chapter_step == 0 and count < 4):
            count += 1
    return count

_OPEN_TOPIC_FALLBACK_MEDIA: Dict[str, Dict[str, List[str]]] = {
    "dark_horror": {
        "broll": [
            "snow forest night",
            "candle flame dark",
            "medieval castle fog",
            "gothic cathedral dark",
            "fireplace burning dark",
            "winter snow village",
        ],
        "pip": [
            "candle flame dark",
            "fireplace burning dark",
            "snow forest night",
            "gothic cathedral dark",
            "medieval castle fog",
        ],
        "photos": [
            "dark snowy pine forest winter night",
            "burning candle dark shadow",
            "gothic cathedral candle",
            "medieval european village snow night",
            "old parchment leather book candle",
            "foggy medieval castle night",
        ],
    },
    "investigative_crime": {
        "broll": [
            "rainy city street night",
            "dark alley fog night",
            "police lights night",
            "courthouse building architecture",
            "old library archive dark",
            "newspaper printing press",
        ],
        "pip": [
            "newspaper printing press",
            "police lights night",
            "old library archive dark",
            "rainy city street night",
            "courthouse building architecture",
        ],
        "photos": [
            "rainy city street night noir",
            "historic courthouse building",
            "old archive files library",
            "dark foggy alley night",
            "vintage detective desk lamp",
            "newspaper archive vintage",
        ],
    },
    "epic_history": {
        "broll": [
            "ancient roman ruins",
            "medieval castle fog",
            "gothic cathedral dark",
            "candle flame dark",
            "historic european village",
            "old book library candle",
        ],
        "pip": [
            "candle flame dark",
            "ancient roman ruins",
            "old book library candle",
            "gothic cathedral dark",
            "medieval castle fog",
        ],
        "photos": [
            "ancient roman ruins colosseum",
            "medieval stone castle europe",
            "gothic cathedral interior candle",
            "old parchment manuscript book",
            "ancient marble statue museum",
            "historic european architecture",
        ],
    },
    "corporate_thriller": {
        "broll": [
            "city skyline night aerial",
            "stock market trading screen",
            "modern skyscraper architecture",
            "corporate boardroom executives",
            "money bills dark finance",
            "newspaper printing press",
        ],
        "pip": [
            "stock market trading monitors",
            "newspaper printing press",
            "bank vault money bills",
            "modern skyscraper architecture",
            "corporate boardroom executives",
        ],
        "photos": [
            "modern skyscraper architecture night",
            "stock market trading floor",
            "corporate boardroom office",
            "historic bank building architecture",
            "money bills finance dark",
            "businessman suit office portrait",
        ],
    },
}


def _classify_topic_mood(topic: str) -> str:
    """Classify any arbitrary documentary topic into one of the 4 cinema moods."""
    t = str(topic or "")
    if _DARK_HORROR_TOPIC_RE.search(t):
        return "dark_horror"
    if _CRIME_TOPIC_RE.search(t):
        return "investigative_crime"
    if _CORPORATE_TOPIC_RE.search(t) and not _HISTORY_TOPIC_RE.search(t):
        return "corporate_thriller"
    if _HISTORY_TOPIC_RE.search(t):
        return "epic_history"
    if _CORPORATE_TOPIC_RE.search(t):
        return "corporate_thriller"
    return "epic_history"


def _normalize_mood(raw_mood: Optional[str], topic: str) -> str:
    m = str(raw_mood or "").strip().lower().replace("-", "_").replace(" ", "_")
    if m in VALID_DOC_MOODS:
        # If topic clearly screams dark_horror (e.g. macabra/terror/krampus), never let LLM downgrade it to corporate_thriller
        if _DARK_HORROR_TOPIC_RE.search(topic) and m == "corporate_thriller":
            return "dark_horror"
        return m
    if any(k in m for k in ("horror", "dark", "macabr", "terror", "gothic", "folklore")):
        return "dark_horror"
    if any(k in m for k in ("crime", "mystery", "detective", "forensic", "thriller_crime")):
        return "investigative_crime"
    if any(k in m for k in ("history", "historic", "epic", "ancient", "bio", "science")):
        return "epic_history"
    return _classify_topic_mood(topic)


def _extract_clean_json(raw: str) -> Dict[str, Any]:
    """Parse JSON safely, stripping DeepSeek special tokens (<|...|>) and markdown code fences."""
    cleaned = re.sub(r"<\|[^|>]*\|>", "", str(raw or "")).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    parsed = _extract_json(cleaned)
    return parsed if isinstance(parsed, dict) else {}


def _match_curated_dossier(topic: str) -> Optional[Dict[str, Any]]:
    """Return one of the 10 curated financial dossiers ONLY when the topic clearly matches it."""
    t_low = str(topic or "").lower()
    for d in _CURATED_DOSSIERS:
        if any(k in t_low for k in d["keywords"]):
            return d
    return None


def _default_channel_for_mood(mood: str, is_en: bool) -> str:
    if mood == "dark_horror":
        return "Dark Vault Files" if is_en else "Arquivos Sombrios"
    if mood == "investigative_crime":
        return "Forensic Case Files" if is_en else "Dossiê Investigativo"
    if mood == "epic_history":
        return "Hidden Chronicles" if is_en else "Crônicas Ocultas"
    return "Vault Files" if is_en else "Dossiê Capital"


def _default_chapter_subtitles_for_mood(mood: str, is_en: bool) -> List[str]:
    if mood == "dark_horror":
        return (
            ["FORBIDDEN ORIGINS", "THE WINTER SHADOW", "BURIED IN HISTORY", "THE MASK REMAINS"]
            if is_en
            else ["AS ORIGENS PROIBIDAS", "A SOMBRA NO INVERNO", "O PASSADO APAGADO", "A MÁSCARA MODERNA"]
        )
    if mood == "investigative_crime":
        return (
            ["THE FIRST CLUE", "THE HIDDEN TRAIL", "THE BREAKING POINT", "THE FINAL TRUTH"]
            if is_en
            else ["A PRIMEIRA PISTA", "A ROTA OCULTA", "O PONTO DE RUPTURA", "A VERDADE REVELADA"]
        )
    if mood == "epic_history":
        return (
            ["THE ANCIENT DAWN", "THE HIDDEN TURNING POINT", "THE ERA OF SHADOWS", "THE LASTING LEGACY"]
            if is_en
            else ["A ORIGEM ANTIGA", "A VIRADA ESQUECIDA", "A ERA DAS SOMBRAS", "O LEGADO OCULTO"]
        )
    return (
        ["THE HIDDEN ANOMALY", "THE OFFSHORE MONEY TRAIL", "THE BREAKING POINT", "THE FINAL COLLAPSE"]
        if is_en
        else ["A ANOMALIA NOS ARQUIVOS", "A ROTA DO CAPITAL OCULTO", "O PONTO DE RUPTURA", "O COLAPSO DO IMPÉRIO"]
    )


def _select_transition_for_scene(s_idx: int, visual_mode: str, has_chapter: bool) -> str:
    """Choose a Hollywood cinema xfade transition matching the editorial rhythm of the cut."""
    if has_chapter:
        return "fadeblack"
    mode_map = {
        "newspaper_highlighter": "smoothleft",
        "dark_map_route": "dissolve",
        "parallax_25d_photo": "zoomin",
        "red_string_board": "wiperight",
        "sliding_timeline": "smoothleft",
        "video_pip_evidence": "dissolve",
        "broll_video_pip": "fadeblack",
    }
    return mode_map.get(visual_mode, CINEMA_XFADE_POOL[s_idx % len(CINEMA_XFADE_POOL)])


def _ensure_topic_open_loops(
    scenes: List[NetflixDocScene],
    mood: str,
    clean_lang: str,
) -> None:
    """Ensure gripping topic-authentic open-loop questions exist every ~14s BEFORE Retention Doctor
    runs, so Retention Doctor audits clichés cleanly without ever injecting financial bridges into
    horror/history/crime documentaries!
    """
    is_en = clean_lang == "en_us"
    bridges_by_mood = {
        "dark_horror": (
            [
                "What terrifying truth was buried beneath this tradition?",
                "Yet why did official history try so hard to erase what happened next?",
                "And what ancient ritual still hides behind the celebration today?",
            ]
            if is_en
            else [
                "Mas qual segredo macabro foi enterrado sob essa tradição?",
                "E por que a história oficial tentou apagar o que acontecia naquela noite?",
                "Será que o ritual original nunca desapareceu de verdade?",
            ]
        ),
        "investigative_crime": (
            [
                "What crucial clue did every investigator overlook at first?",
                "Yet who was pulling the strings behind the scenes all along?",
                "And how did one tiny detail finally crack the entire case open?",
            ]
            if is_en
            else [
                "Qual pista crucial passou despercebida por todos os investigadores?",
                "Mas quem realmente controlava cada passo nos bastidores desse mistério?",
                "E como um único detalhe esquecido mudou toda a investigação?",
            ]
        ),
        "epic_history": (
            [
                "What forgotten event changed the course of history overnight?",
                "Yet why was this chapter nearly erased from modern chronicles?",
                "And how does that ancient turning point still echo today?",
            ]
            if is_en
            else [
                "Qual evento esquecido mudou o rumo da história da noite para o dia?",
                "Mas por que esse capítulo quase desapareceu dos livros oficiais?",
                "E como essa virada histórica ainda ecoa até hoje?",
            ]
        ),
        "corporate_thriller": (
            [
                "How did nobody inside the boardroom notice what was happening?",
                "Yet what hidden detail inside the records triggered the collapse?",
                "And why did the warning signs go ignored until it was too late?",
            ]
            if is_en
            else [
                "Como ninguém nos bastidores percebeu o tamanho do risco a tempo?",
                "Mas qual detalhe oculto nos registros acelerou a virada decisiva?",
                "E por que todos os alertas foram ignorados até o último instante?",
            ]
        ),
    }
    pool = bridges_by_mood.get(mood, bridges_by_mood["epic_history"])
    # Skip artificial open-loop injection whenever the plan already has >= 1 natural '?' hook
    existing_q_hooks = sum(1 for sc in scenes if "?" in str(sc.narration or ""))
    if existing_q_hooks >= 1:
        return

    since_loop_s = 0.0
    b_idx = 0
    for idx, sc in enumerate(scenes):
        if existing_q_hooks >= 1:
            break
        txt = sc.narration.strip()
        dur_est = max(2.2, len(txt.split()) / 2.05)
        since_loop_s += dur_est
        if "?" in txt or OPEN_LOOP_MARKERS_RE.search(txt):
            since_loop_s = 0.0
            continue
        # Inject at most 1 '?' hook ONLY when the entire script had zero '?' marks
        if (idx == 0 or (idx < len(scenes) - 1 and since_loop_s >= 24.0)) and b_idx < len(pool):
            q = pool[b_idx]
            b_idx += 1
            base_clean = txt.rstrip(".!?…—- ").strip()
            sc.narration = f"{base_clean}. {q}" if base_clean else q
            existing_q_hooks += 1
            since_loop_s = 0.0


_BANNED_DARK_NEON_RE = re.compile(
    r"\b(?:neon\s+reindeers?|neon\s+signs?|neon\s+lights?|neon\s+outlines?|"
    r"pink[/\s-]*green\s+leds?|hot[\s-]*pink|lime[\s-]*green|electric[\s-]*blue\s+neon|"
    r"cyberpunk|synthwave|bright\s+led\s+snowflakes?)\b",
    re.IGNORECASE,
)

_PT_CARDINAL_TO_ORDINAL_CENTURY: Dict[str, str] = {
    "um": "primeiro",
    "dois": "segundo",
    "três": "terceiro",
    "tres": "terceiro",
    "quatro": "quarto",
    "cinco": "quinto",
    "seis": "sexto",
    "sete": "sétimo",
    "oito": "oitavo",
    "nove": "nono",
    "dez": "décimo",
}

_PT_CENTURY_CARDINAL_RE = re.compile(
    r"\b(s[eé]culo)\s+(um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez)\b",
    re.IGNORECASE,
)


def _normalize_pt_century_ordinals_in_text(text: str, lang: str = "pt_br") -> str:
    """Normalize Portuguese century cardinals I..X ('século quatro') into educated ordinals ('século quarto')."""
    if str(lang).lower().startswith("en"):
        return text

    def _repl(m: re.Match[str]) -> str:
        sec_word = m.group(1)
        num_word = m.group(2).lower()
        ord_word = _PT_CARDINAL_TO_ORDINAL_CENTURY.get(num_word, m.group(2))
        if m.group(2).isupper():
            ord_word = ord_word.upper()
        elif m.group(2)[0].isupper():
            ord_word = ord_word.capitalize()
        return f"{sec_word} {ord_word}"

    return _PT_CENTURY_CARDINAL_RE.sub(_repl, str(text or ""))


def _sanitize_dark_history_prompt(prompt: str, mood: str) -> str:
    """Ban cyberpunk neon / pink-green LED anachronisms in dark_horror and epic_history visual prompts."""
    p = str(prompt or "").strip()
    if not p:
        return p
    if str(mood or "").strip().lower() in ("dark_horror", "epic_history", "investigative_crime"):
        if _BANNED_DARK_NEON_RE.search(p):
            p = _BANNED_DARK_NEON_RE.sub(
                "moody candlelit windows and warm vintage streetlamps casting dark shadows in an obsidian room",
                p,
            )
    return re.sub(r"\s{2,}", " ", p).strip()


def _call_open_topic_director_llm(
    topic: str,
    n_scenes: int,
    clean_lang: str,
    mood_hint: str,
    custom_directives: str = "",
    aspect_ratio: str = "16:9",
    min_scene_words: int = 18,
    max_scene_words: int = 22,
    target_seconds: float = 60.0,
) -> Optional[Tuple[Dict[str, Any], str, int, float]]:
    """Call LIVE DeepSeek (`deepseek-chat`) OR Google Gemini (`gemini-flash-lite-latest` via
    `headers={"x-goog-api-key": gkey}`) with automatic failover to author a 100% original, deeply
    researched, gripping Netflix / Dark History documentary blueprint for ANY arbitrary topic.
    """
    settings = get_settings() or {}
    dkey = str(settings.get("deepseek_api_key") or "").strip()
    gkey = str(settings.get("gemini_api_key") or "").strip()
    default_llm = str(settings.get("default_llm") or "gemini-flash-lite-latest").strip().lower()
    if not dkey and not gkey:
        return None

    is_en = clean_lang == "en_us"
    is_vertical = str(aspect_ratio).strip() == "9:16"
    lang_label = "American English" if is_en else "Brazilian Portuguese (PT-BR)"
    skill_path = SKILLS_DIR / "10_netflix_investigative_doc.md"
    skill_excerpt = skill_path.read_text(encoding="utf-8")[:900] if skill_path.exists() else ""
    if mood_hint != "corporate_thriller" and skill_excerpt:
        skill_excerpt = re.sub(
            r"(?:Canal\s+)?[\"']?(?:Dossi[eê]\s+Capital|Vault\s+Files)[\"']?",
            "",
            skill_excerpt,
            flags=re.IGNORECASE,
        )
        skill_excerpt = re.sub(r"\s*—\s*\)", ")", skill_excerpt)
        skill_excerpt = re.sub(r"[ \t]{2,}", " ", skill_excerpt)

    total_min_w = min_scene_words * n_scenes
    total_max_w = max_scene_words * n_scenes
    if is_vertical:
        framing_rule = (
            "   - `bespoke_image_prompt_en`: vivid 16-26 word English VERTICAL 9:16 full-bleed dark-cinema portrait still prompt depicting THAT scene's opening historical moment, dramatic candlelight/chiaroscuro, 35mm film grain, ZERO text/words/letters. NEVER use 'wide', 'widescreen', 'panoramic', 'landscape', or 'wide establishing'!\n"
            "   - `shot_prompts_en`: array of 4 to 5 DISTINCT chronological English VERTICAL 9:16 35mm cinema still prompts (14-24 words EACH) — ONE bespoke vertical shot for EACH phrase/beat of that scene's narration! Every single prompt MUST depict a DIFFERENT vertical camera angle/subject matching that exact moment (e.g., 'Vertical full-bleed 9:16 35mm cinema still...' -> 'Intimate vertical close-up detail...' -> 'Tall dramatic portrait silhouette...' -> 'Moody vertical low-angle atmospheric frame...'), NEVER 'wide establishing' or 'wide angle', ZERO text/words/letters, ZERO modern anachronisms!\n"
        )
        shot_example_json = (
            '      "bespoke_image_prompt_en": "Vertical full-bleed 9:16 dark cinema photorealistic portrait still, chiaroscuro lighting, no text",\n'
            '      "shot_prompts_en": ["Vertical full-bleed 9:16 35mm cinema still matching phrase 1, no text", "Intimate vertical close-up detail matching phrase 2, no text", "Tall dramatic vertical portrait matching phrase 3, no text", "Moody vertical 9:16 atmospheric still matching phrase 4, no text"],\n'
        )
    else:
        framing_rule = (
            "   - `bespoke_image_prompt_en`: vivid 16-26 word English dark-cinema photographic still prompt depicting THAT scene's opening historical moment, dramatic candlelight/chiaroscuro, 35mm film grain, ZERO text/words/letters.\n"
            "   - `shot_prompts_en`: array of 4 to 5 DISTINCT chronological English 35mm cinema still prompts (14-24 words EACH) — ONE bespoke shot for EACH phrase/beat of that scene's narration! Every single prompt MUST depict a DIFFERENT camera angle/subject matching that exact moment of the story (e.g., wide establishing shot -> tense close-up object -> dramatic character/silhouettes -> eerie symbolic detail), ZERO text/words/letters, ZERO modern anachronisms!\n"
        )
        shot_example_json = (
            '      "bespoke_image_prompt_en": "dark cinema photorealistic scene description, no text",\n'
            '      "shot_prompts_en": ["chronological shot 1 matching phrase 1, 35mm cinema, no text", "shot 2 matching phrase 2, close-up detail, no text", "shot 3 matching phrase 3, dramatic wide angle, no text", "shot 4 matching phrase 4, moody atmospheric still, no text"],\n'
        )

    sys_prompt = (
        f"You are an Emmy-winning Netflix / A24 / Nostalgia / MagnatesMedia Documentary Showrunner & Historian writing in {lang_label}.\n"
        "Create a 100% ORIGINAL, deeply researched, spine-tingling, cinematic documentary script strictly about the user's EXACT TOPIC.\n"
        "ABSOLUTE STORYTELLING & VOICE RULES:\n"
        "1. CONTINUOUS HUMAN NARRATIVE & STRICT FORWARD HISTORICAL CHRONOLOGY: Write like a master human storyteller telling ONE gripping, continuous story from Cold Open to unforgettable ending — NEVER disjointed bullet points, NEVER repeating ideas across scenes, and NEVER pasting the user's raw prompt text inside narration or headlines! Scenes MUST progress STRICTLY FORWARD in historical time from earliest era to modern day (e.g., for dark Christmas history: Act I Roman Saturnalia 217 a.C. & 336 d.C. Sol Invictus decree -> Act II 4th-century Bishop Nicholas of Myra -> Act III 11th/12th-century Alpine fusion with Krampus -> Act IV 1647 Puritan Ban by Oliver Cromwell & Plum Pudding Riots -> Epilogue 19th-century Victorian & modern corporate domestication — NEVER put 11th-c. Krampus before 4th-c. Saint Nicholas!). NEVER jump backwards in time across scenes, and NEVER connect two different centuries with 'Enquanto isso' / 'Meanwhile'! Verify historical geography and climate accurately.\n"
        "2. REAL HISTORICAL DEPTH: Cite real eras, real years (e.g., 217 a.C., 336 d.C., 1647, 4th century, 1890s), real places (Rome, Myra, Austrian Alps, London, Iceland), real historical figures/folklore/edicts, and genuine plot twists!\n"
        f"3. STRICT DURATION & NATURAL SPOKEN RHYTHM (~{int(round(target_seconds))}s TOTAL): Each scene narration MUST be strictly {min_scene_words}-{max_scene_words} crisp, visceral spoken words (total script ~{total_min_w}-{total_max_w} words across all {n_scenes} scenes so final video hits ~{int(round(target_seconds))}s cleanly!). Write spoken Portuguese/English naturally with commas and clean periods — NEVER em-dashes ('—'). Spell out centuries naturally using Portuguese ordinals for I-X and cardinals for XI+ (write 'século quarto' instead of 'SÉC. IV' or 'século quatro', 'século onze' instead of 'SÉC. XI', and 'antes de Cristo' instead of 'a.C.').\n"
        "4. ZERO ROBOTIC AI CLICHÉS & ZERO OFF-TOPIC BRANDING: NEVER write 'Em um mundo onde', 'Vamos mergulhar', 'Em conclusão', 'Por trás da imagem familiar', 'As crônicas históricas conectaram', 'In a world where', or 'Let's dive in'. Invent a topic-authentic `channel_name` matching the mood (NEVER 'Dossiê Capital' or 'Vault Files' unless mood is 'corporate_thriller').\n"
        "5. CRITICAL NARRATIVE RULE: Do NOT end every scene with a rhetorical question! At least 75% of scenes MUST end with a concrete, visceral, mind-blowing historical fact or consequence (e.g. 'Em Mira, o próprio bispo Nicolau demoliu templos pagãos com as próprias mãos.', 'Em Londres, soldados invadiam casas pelo cheiro de carne assada e arrastavam famílias para a prisão.'). Use at most 1 or 2 open-loop transition questions across the entire script — and whenever a scene asks a question, the VERY NEXT SCENE MUST directly answer it in its opening sentence! Only the final scene ends with a haunting second-person question to the viewer ('E você... quando acende as luzes na noite de vinte e quatro de dezembro... ainda sente a sombra do que tentaram apagar?').\n"
        "6. VISUAL PRECISION & BAN CYBERPUNK NEON IN DARK HISTORY (ZERO OFF-TOPIC STOCK!): Every scene needs concrete, atmospheric English visual queries:\n"
        "   - STRICTLY FORBID 'neon signs', 'neon reindeer', 'pink/green LED', or 'cyberpunk' in `shot_prompts_en` and `bespoke_image_prompt_en` for `dark_horror` / `epic_history` (even in modern-era epilogue scenes, use moody candlelit windows, snow falling under warm vintage streetlamps, dark shadows cast by a Christmas tree in an obsidian room!).\n"
        "   - `broll_query_en` and `pip_broll_query_en` (MUST differ from each other): concrete, real atmospheric stock video phrases that exist on Pixabay (e.g., 'snow pine forest night', 'burning candle dark shadow', 'medieval stone castle fog', 'gothic cathedral interior', 'crackling fireplace dark', 'winter snow village night', 'old leather book candle', 'ancient roman stone ruins'). NEVER use abstract words like 'floor', 'butterfly', 'background', 'texture', or 'darkness' alone.\n"
        "   - `photo_query_en` and `extra_photo_queries_en` (3-4 distinct concrete English museum/historical/photographic subjects matching THAT exact scene — e.g., 'Krampus Austrian folklore mask', 'Roman Saturnalia festival painting', 'Saint Nicholas Byzantine icon', 'Puritan Oliver Cromwell 17th century engraving', 'Victorian gothic winter postcard').\n"
        f"{framing_rule}"
        "   - `prefer_gemini_photo`: true for vivid historical/macabre/folklore scenes where custom AI cinema art beats generic stock.\n"
        "7. UNIQUE PER-SCENE UI METADATA & CHAPTER SUBTITLE: Give EVERY scene its OWN specific `chapter_subtitle` (a crisp 2-4 word UPPERCASE thematic chapter title matching THAT EXACT scene's subject/era — e.g. 'O MONSTRO DOS ALPES' for a Krampus scene, 'O NATAL PROIBIDO' for a 1647 London Puritans scene), its OWN `evidence_headline` (<= 48 chars, punchy newspaper headline), `evidence_quote` (1 gripping historical fact for THAT scene), and `lower_third_title` (`LOCATION • ERA`, clean ALL-CAPS).\n"
        "8. Classify `mood` strictly as ONE of: \"dark_horror\", \"investigative_crime\", \"epic_history\", \"corporate_thriller\".\n"
        "Return ONLY valid JSON matching this exact schema:\n"
        "{\n"
        '  "title": "Editorial documentary title",\n'
        '  "subtitle": "Short archival subtitle (e.g. Arquivo Histórico • Roma & Alpes)",\n'
        '  "channel_name": "Topic-authentic cinema channel name",\n'
        '  "mood": "dark_horror | investigative_crime | epic_history | corporate_thriller",\n'
        '  "thumbnail_hook": "2-3 PUNCHY WORDS",\n'
        '  "map_origin": "REAL ORIGIN PLACE",\n'
        '  "map_destination": "REAL DESTINATION PLACE",\n'
        '  "map_metric": "DRAMATIC HISTORICAL METRIC/ERA",\n'
        '  "evidence_headline": "DRAMATIC ARCHIVAL HEADLINE",\n'
        '  "evidence_quote": "1-2 gripping sentences of real documented evidence about the topic.",\n'
        '  "timeline_points": [\n'
        '    {"date": "REAL YEAR/ERA", "label": "Short real milestone", "value": "Concise impact tag"}\n'
        "  ],\n"
        '  "board_nodes": [\n'
        '    {"id": "n1", "title": "ENTITY 1", "role": "Short role", "badge": "SHORT BADGE"}\n'
        "  ],\n"
        '  "scenes": [\n'
        "    {\n"
        '      "chapter_subtitle": "2-4 WORD CHAPTER TITLE FOR THIS EXACT SCENE",\n'
        f'      "narration": "{min_scene_words}-{max_scene_words} gripping spoken words (no em-dashes)...",\n'
        '      "lower_third_title": "SPECIFIC LOCATION • REAL ERA/YEAR",\n'
        '      "lower_third_subtitle": "SPECIFIC ARCHIVAL CONTEXT • DETAIL",\n'
        '      "evidence_headline": "Scene-specific dramatic headline",\n'
        '      "evidence_quote": "Scene-specific documented quote/detail",\n'
        '      "map_origin": "Origin location",\n'
        '      "map_destination": "Destination location",\n'
        '      "map_metric": "Scene dramatic stat/era",\n'
        '      "broll_query_en": "3-4 word concrete English video query",\n'
        '      "pip_broll_query_en": "different 3-4 word English video query",\n'
        '      "photo_query_en": "2-4 word concrete English photo query",\n'
        '      "extra_photo_queries_en": ["photo q1", "photo q2", "photo q3", "photo q4"],\n'
        f"{shot_example_json}"
        '      "prefer_gemini_photo": true\n'
        "    }\n"
        "  ],\n"
        '  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4"]\n'
        "}"
    )

    def _invoke_single_call(usr_p: str, target_count: int) -> Optional[Tuple[Dict[str, Any], str, int, float]]:
        max_out_tokens = min(16384, 2400 + target_count * 480)
        provider_order = ["deepseek", "gemini"] if "deepseek" in default_llm else ["gemini", "deepseek"]
        for prov in provider_order:
            if prov == "deepseek" and dkey:
                try:
                    from openai import OpenAI

                    cli = OpenAI(api_key=dkey, base_url="https://api.deepseek.com", timeout=90.0)
                    resp = cli.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": usr_p},
                        ],
                        temperature=0.72,
                        max_tokens=min(8192, max_out_tokens),
                        response_format={"type": "json_object"},
                    )
                    raw_txt = resp.choices[0].message.content or "{}"
                    data = _extract_clean_json(raw_txt)
                    if isinstance(data.get("scenes"), list) and len(data["scenes"]) >= max(3, int(target_count * 0.6)):
                        u = resp.usage
                        pt = int(getattr(u, "prompt_tokens", 900))
                        ct = int(getattr(u, "completion_tokens", 1600))
                        cost = round((pt * 0.14 + ct * 0.28) / 1_000_000.0, 6)
                        try:
                            record_token_usage("deepseek", "deepseek-chat", pt, ct, 0, cost)
                        except Exception:
                            pass
                        print(
                            f"[NetflixDoc] Open-topic AI Director succeeded via DeepSeek (deepseek-chat) | "
                            f"scenes={len(data['scenes'])}/{target_count} | mood={data.get('mood')}",
                            flush=True,
                        )
                        return data, "llm_deepseek", pt + ct, cost
                except Exception as exc:
                    print(f"[NetflixDoc] DeepSeek open-topic director failed, failing over: {exc}", flush=True)

            if prov == "gemini" and gkey:
                gemini_models = ("gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash")
                headers = {"Content-Type": "application/json", "x-goog-api-key": gkey}
                for gm in gemini_models:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                        payload = {
                            "system_instruction": {"parts": [{"text": sys_prompt}]},
                            "contents": [{"role": "user", "parts": [{"text": usr_p}]}],
                            "generationConfig": {
                                "temperature": 0.72,
                                "maxOutputTokens": max_out_tokens,
                                "responseMimeType": "application/json",
                            },
                        }
                        r = httpx.post(url, json=payload, headers=headers, timeout=95.0)
                        if r.status_code != 200:
                            print(f"[NetflixDoc] Gemini ({gm}) HTTP {r.status_code}, trying next model...", flush=True)
                            continue
                        j = r.json()
                        parts = j.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        txt = "".join(str(p.get("text") or "") for p in parts if not p.get("thought"))
                        if not txt:
                            txt = str(parts[0].get("text") or "") if parts else ""
                        data = _extract_clean_json(txt)
                        if isinstance(data.get("scenes"), list) and len(data["scenes"]) >= max(3, int(target_count * 0.6)):
                            meta = j.get("usageMetadata", {})
                            pt = int(meta.get("promptTokenCount", 900))
                            ct = int(meta.get("candidatesTokenCount", 1800))
                            cost = round((pt * 0.05 + ct * 0.20) / 1_000_000.0, 6)
                            try:
                                record_token_usage("gemini", gm, pt, ct, 0, cost)
                            except Exception:
                                pass
                            print(
                                f"[NetflixDoc] Open-topic AI Director succeeded via Gemini ({gm}) | "
                                f"scenes={len(data['scenes'])}/{target_count} | mood={data.get('mood')}",
                                flush=True,
                            )
                            return data, f"llm_gemini:{gm}", pt + ct, cost
                        else:
                            got_n = len(data.get("scenes", [])) if isinstance(data, dict) else 0
                            print(f"[NetflixDoc] Gemini ({gm}) incomplete JSON ({got_n}/{target_count} scenes), trying next...", flush=True)
                    except Exception as exc:
                        print(f"[NetflixDoc] Gemini ({gm}) open-topic director failed: {exc}", flush=True)
                        continue
        return None

    dir_block = f"\nUSER CREATIVE DIRECTIVES: {custom_directives.strip()}" if custom_directives.strip() else ""
    if n_scenes <= 14:
        user_prompt = (
            f"EXACT DOCUMENTARY TOPIC: {topic}\n"
            f"LANGUAGE: {lang_label}\n"
            f"SUGGESTED MOOD: {mood_hint}\n"
            f"EXACT NUMBER OF SCENES REQUIRED: {n_scenes}\n"
            f"{dir_block}\n"
            f"STYLE REFERENCE:\n{skill_excerpt}"
        )
        return _invoke_single_call(user_prompt, n_scenes)

    part1_n = (n_scenes + 1) // 2
    part2_n = n_scenes - part1_n
    prompt_p1 = (
        f"EXACT DOCUMENTARY TOPIC: {topic}\n"
        f"LANGUAGE: {lang_label}\n"
        f"SUGGESTED MOOD: {mood_hint}\n"
        f"PART 1 OF 2 (Cold Open + Acts I & II — end on a gripping mid-story cliffhanger!)\n"
        f"EXACT NUMBER OF SCENES IN PART 1: {part1_n}\n"
        f"{dir_block}\n"
        f"STYLE REFERENCE:\n{skill_excerpt}"
    )
    res1 = _invoke_single_call(prompt_p1, part1_n)
    if res1 is None:
        return None
    data1, src1, tok1, cost1 = res1
    p1_scenes = [s for s in (data1.get("scenes") or []) if isinstance(s, dict)][:part1_n]
    prev_tail = " ".join(str(s.get("narration") or "") for s in p1_scenes[-2:])
    used_facts = "; ".join(str(s.get("evidence_headline") or "") for s in p1_scenes if s.get("evidence_headline"))

    prompt_p2 = (
        f"EXACT DOCUMENTARY TOPIC: {topic}\n"
        f"LANGUAGE: {lang_label}\n"
        f"SUGGESTED MOOD: {data1.get('mood') or mood_hint}\n"
        f"PART 2 OF 2 (Acts III & IV + Dark Twist + Chilling Finale — continue SEAMLESSLY after Part 1!)\n"
        f"PART 1 ENDED WITH: \"{prev_tail}\"\n"
        f"ALREADY COVERED HEADLINES (DO NOT REPEAT): {used_facts}\n"
        f"EXACT NUMBER OF NEW SCENES IN PART 2: {part2_n}\n"
        f"{dir_block}"
    )
    res2 = _invoke_single_call(prompt_p2, part2_n)
    if res2 is not None:
        data2, _, tok2, cost2 = res2
        p2_scenes = [s for s in (data2.get("scenes") or []) if isinstance(s, dict)][:part2_n]
        data1["scenes"] = p1_scenes + p2_scenes
        return data1, src1, tok1 + tok2, round(cost1 + cost2, 6)
    return data1, src1, tok1, cost1


def _build_open_topic_offline_dossier(topic: str, clean_lang: str, mood: str) -> Dict[str, Any]:
    """Mood-authentic zero-finance fallback dossier ONLY used if BOTH DeepSeek and Gemini are offline."""
    is_en = clean_lang == "en_us"
    clean_t = _clean_doc_text(topic) or ("A História Oculta" if not is_en else "The Hidden History")
    short_upper = clean_t.upper()[:26]
    media_pack = _OPEN_TOPIC_FALLBACK_MEDIA.get(mood, _OPEN_TOPIC_FALLBACK_MEDIA["epic_history"])

    if mood == "dark_horror":
        origin = "ANTIGUIDADE" if not is_en else "ANCIENT ERA"
        dest = "EUROPA MEDIEVAL" if not is_en else "MEDIEVAL EUROPE"
        metric = "ARQUIVO SOMBRIO • ORIGEM OCULTA" if not is_en else "DARK ARCHIVE • HIDDEN ORIGIN"
        sub = "Arquivo Sombrio • História Oculta" if not is_en else "Dark Archive • Hidden History"
        hook = "O LADO SOMBRIO" if not is_en else "THE DARK TRUTH"
        headline = f"ARQUIVOS HISTÓRICOS REVELAM O LADO SOMBRIO DE {short_upper}" if not is_en else f"FORGOTTEN ARCHIVES EXPOSE THE DARK ORIGIN OF {short_upper}"
        quote = (
            f"Crônicas antigas preservam detalhes inquietantes sobre {clean_t} que a versão moderna tentou suavizar."
            if not is_en
            else f"Ancient chronicles preserve unsettling accounts behind {clean_t} that modern retellings quietly erased."
        )
        timeline = [
            {"date": "ORIGEM", "label": "Primeiros Registros Antigos", "value": "RAIZ OCULTA"},
            {"date": "SÉC. IV", "label": "Transformação Cultural", "value": "RITUAL ADAPTADO"},
            {"date": "IDADE MÉDIA", "label": "Folclore & Advertências", "value": "LENDAS SOMBRIAS"},
            {"date": "HOJE", "label": "A Máscara Moderna", "value": "VERDADE EXPOSTA"},
        ]
        nodes = [
            {"id": "n1", "title": short_upper[:18], "role": "Origem Histórica", "badge": "ARQUIVO #01"},
            {"id": "n2", "title": "RITUAIS ANTIGOS", "role": "Tradições Esquecidas", "badge": "FOLCLORE"},
            {"id": "n3", "title": "CRÔNICAS VELADAS", "role": "Relatos Medievais", "badge": "PROVA HISTÓRICA"},
            {"id": "n4", "title": "VERSÃO MODERNA", "role": "O Que Foi Apagado", "badge": "REVELADO"},
        ]
        narr = (
            [
                f"Arquivos antigos de {clean_t} revelam que a tradição nasceu em rituais de inverno repletos de excessos e sacrifícios.",
                f"No século quarto, autoridades religiosas absorveram os antigos festivais pagãos e demoliram templos rivais com as próprias mãos.",
                "Durante a Idade Média, lendas alpinas fundiram o inverno a criaturas sombrias que puniam os culpados na calada da noite.",
                "Em 1647, soldados patrulhavam as ruas pelo cheiro de banquetes proibidos e arrastavam famílias inteiras para a prisão.",
                f"E você, ao revisitar a origem de {clean_t}, ainda sente a sombra do que tentaram apagar?",
            ]
            if not is_en
            else [
                f"Ancient archives of {clean_t} reveal that the tradition began inside winter rituals of excess and blood sacrifice.",
                "In the fourth century, early authorities absorbed pagan solstice feasts while tearing down rival temples with their bare hands.",
                "Across medieval Europe, Alpine folklore fused winter nights with horned figures that punished the wicked in the dark.",
                "By 1647, armed patrols hunted down forbidden feasts by the scent of roasting meat and dragged families to prison.",
                f"And you, when the lights of {clean_t} flicker at midnight, do you still feel the shadow they tried to erase?",
            ]
        )
    else:
        origin = "ARQUIVO ORIGINAL" if not is_en else "PRIMARY ARCHIVE"
        dest = "PRESENTE" if not is_en else "PRESENT DAY"
        metric = "DOSSIÊ HISTÓRICO COMPLETO" if not is_en else "COMPLETE ARCHIVAL FILE"
        sub = "Arquivo Documental • Investigação" if not is_en else "Archival Documentary • Investigation"
        hook = "A VERDADE OCULTA" if not is_en else "THE HIDDEN TRUTH"
        headline = f"DOCUMENTOS REVELAM A HISTÓRIA REAL POR TRÁS DE {short_upper}" if not is_en else f"ARCHIVAL RECORDS REVEAL THE REAL STORY BEHIND {short_upper}"
        quote = (
            f"Registros históricos e evidências preservadas revelam como {clean_t} transformou seu tempo de maneira inesperada."
            if not is_en
            else f"Preserved historical records reveal how {clean_t} reshaped its era in ways rarely told today."
        )
        timeline = [
            {"date": "FASE I", "label": "Origem Documentada", "value": "INÍCIO"},
            {"date": "FASE II", "label": "Virada Decisiva", "value": "RUPTURA"},
            {"date": "FASE III", "label": "Clímax Histórico", "value": "IMPACTO"},
            {"date": "LEGADO", "label": "Repercussão Atual", "value": "REVELADO"},
        ]
        nodes = [
            {"id": "n1", "title": short_upper[:18], "role": "Tema Central", "badge": "ARQUIVO #01"},
            {"id": "n2", "title": "TESTEMUNHOS", "role": "Registros de Época", "badge": "EVIDÊNCIA"},
            {"id": "n3", "title": "PONTO DE VIRADA", "role": "Evento Decisivo", "badge": "CRÍTICO"},
            {"id": "n4", "title": "LEGADO REAL", "role": "Impacto Duradouro", "badge": "HISTÓRIA"},
        ]
        narr = (
            [
                f"A história oficial sobre {clean_t} ocultou durante séculos os registros primários que deram origem a tudo.",
                f"Documentos de época provam que as raízes de {clean_t} surgiram sob decretos implacáveis e disputas de poder.",
                "Cada testemunho preservado conecta lugares distantes e mostra como decisões secretas alteraram o destino de uma geração inteira.",
                "Quando a cronologia completa veio à tona, as provas documentais desmontaram de vez a versão oficial.",
                f"E você, diante das provas reais sobre {clean_t}, ainda acredita na versão que contaram nos livros?",
            ]
            if not is_en
            else [
                f"Official chronicles of {clean_t} concealed for centuries the primary records that sparked the entire affair.",
                f"Period documents prove the roots of {clean_t} emerged under ruthless decrees and high-stakes power struggles.",
                "Each preserved testimony connects distant capitals and exposes how covert decisions reshaped an entire generation.",
                "When the complete chronological archive surfaced, hard forensic evidence dismantled the official myth overnight.",
                f"And you, seeing the primary evidence behind {clean_t}, do you still believe the version told in textbooks?",
            ]
        )

    return {
        "title": clean_t,
        "subtitle": sub,
        "channel_name": _default_channel_for_mood(mood, is_en),
        "mood": mood,
        "thumbnail_hook": hook,
        "chapter_subtitles": _default_chapter_subtitles_for_mood(mood, is_en),
        "map_origin": origin,
        "map_destination": dest,
        "map_metric": metric,
        "evidence_headline": headline,
        "evidence_quote": quote,
        "timeline_points": timeline,
        "board_nodes": nodes,
        "broll_queries": list(media_pack["broll"]),
        "pip_queries": list(media_pack["pip"]),
        "photo_queries": list(media_pack["photos"]),
        "narr": narr,
    }


def _build_universal_dossier(topic: str, lang: str = "pt_br") -> Dict[str, Any]:
    """Backwards-compatible helper: returns curated financial dossier on exact match or mood-adapted open dossier."""
    matched = _match_curated_dossier(topic)
    if matched is not None:
        return matched
    clean_lang = "en_us" if str(lang).lower().startswith("en") else "pt_br"
    mood = _classify_topic_mood(topic)
    off = _build_open_topic_offline_dossier(topic, clean_lang=clean_lang, mood=mood)
    return {
        "keywords": (),
        "mood": mood,
        "title_pt": off["title"],
        "title_en": off["title"],
        "sub_pt": off["subtitle"],
        "sub_en": off["subtitle"],
        "hook_pt": off["thumbnail_hook"],
        "hook_en": off["thumbnail_hook"],
        "origin": off["map_origin"],
        "dest": off["map_destination"],
        "metric_pt": off["map_metric"],
        "metric_en": off["map_metric"],
        "headline": off["evidence_headline"],
        "quote_pt": off["evidence_quote"],
        "quote_en": off["evidence_quote"],
        "broll_queries": off["broll_queries"],
        "pip_queries": off["pip_queries"],
        "photo_queries": off["photo_queries"],
        "timeline": off["timeline_points"],
        "nodes": off["board_nodes"],
        "narr_pt": off["narr"],
        "narr_en": off["narr"],
    }


_CHRISTMAS_MASTERPIECE_RE = re.compile(
    r"\b(natal|christmas|saturn[aá]lia|krampus|papai\s+noel|santa\s+claus|sol\s+invictus|pudim\s+de\s+ameixa)\b",
    re.IGNORECASE,
)


def _is_christmas_dark_history_topic(topic: str) -> bool:
    """Return True when the documentary topic requests the historical dark origins of Christmas."""
    return bool(_CHRISTMAS_MASTERPIECE_RE.search(str(topic or "")))


def _assign_act_metadata_for_index(idx: int, total_scenes: int) -> Tuple[str, float, bool]:
    """Return `(act_id, cut_cadence_s, is_pattern_interrupt)` for scene `idx` in a 5-Act v3.0.0 arc."""
    if total_scenes >= 20:
        if idx <= 1:
            return "ACT_0_COLD_OPEN_HOOK", 2.2, False
        if idx <= 6:
            return "ACT_1_WORLD_BUILDING", 4.0, False
        if idx <= 15:
            return "ACT_2_DEEP_MECHANICS", 3.5, idx in (7, 12)
        if idx <= 21:
            return "ACT_3_CLIMAX_REVELATION", 2.7, idx == 16
        return "ACT_4_ABRUPT_ENDING", 4.5, False
    # Proportional 5-act mapping for shorter documentaries
    ratio = idx / float(max(1, total_scenes - 1))
    if idx == 0:
        return "ACT_0_COLD_OPEN_HOOK", 2.2, False
    if ratio < 0.30:
        return "ACT_1_WORLD_BUILDING", 4.0, False
    if ratio < 0.68:
        return "ACT_2_DEEP_MECHANICS", 3.5, False
    if ratio < 0.88:
        return "ACT_3_CLIMAX_REVELATION", 2.7, False
    return "ACT_4_ABRUPT_ENDING", 4.5, False


def _build_christmas_5act_masterpiece_plan(
    aspect_ratio: Literal["16:9", "9:16"] = "16:9",
    target_minutes: float = 17.0,
    clean_lang: str = "pt_br",
    caption_style: str = "selective_emphasis",
) -> Dict[str, Any]:
    """Build the canonical 25-Scene, 5-Act High-Retention Historical Documentary Blueprint
    ('A Noite em que o Sol Morreu: A Verdadeira História por Trás do Natal', ~2,250-2,450 words,
    ~16m00s-17m30s / 960-1,050s) inspired by Super Histórico / H2 History / Mega Curioso (narrative)
    and Vox / Johnny Harris / MagnatesMedia / Fern / Elementar (5-category Mixed-Media visuals).

    100% BBC/Netflix Standards & Practices fact-checked:
      - Names 'Natal' in the VERY FIRST sentence (zero hook miss).
      - Accurate 217 BC Roman Saturnalia (Lake Trasimene / Temple of Saturn) — zero pop-history distortions.
      - Accurate 274 AD Emperor Aurelian Sol Invictus vs 336 AD Chronograph of 354 under Constantine (no fake edict).
      - Explicitly traces 4th-c. Bishop Nicholas of Myra -> Dutch Sinterklaas -> Santa Claus / Papai Noel.
      - Accurate 1647 Canterbury (Kent) Plum Pudding Riot -> Second English Civil War (NOT London!).
      - Accurate 1660 Restoration of King Charles II repealing the Puritan ban & reviving revelry.
      - Strict forward chronology: 1822-1823 Moore -> 1843 Dickens -> 1848 Victoria/Albert -> 1863-1881 Nast -> 1931 Sundblom.
      - Genuine A->B map routes (Mira -> Amsterdã, Londres -> Boston), era-matched recap timeline & string board.
      - Zero CTA in Act 4, abrupt 0.50s cut after final haunting interrogative sentence.
    """
    is_en = clean_lang == "en_us"
    is_vertical = aspect_ratio == "9:16"
    voice_id = "Charon"

    global_timeline: List[TimelinePoint] = [
        TimelinePoint(date="217 a.C.", label="Saturnália Romana no Templo de Saturno", value="ORIGEM PAGÃ"),
        TimelinePoint(date="336 d.C.", label="Cronógrafo de 354 e Sol Invictus em Roma", value="ABSORÇÃO IMPERIAL"),
        TimelinePoint(date="SÉC. IV & XI", label="Bispo Nicolau de Mira e Krampus nos Alpes", value="DUALISMO FOLCLÓRICO"),
        TimelinePoint(date="1647", label="Motim do Pudim de Ameixa em Canterbury", value="NATAL PROIBIDO"),
        TimelinePoint(date="1843 & 1848", label="Dickens e a Árvore Real de Vitória e Albert", value="DOMESTICAÇÃO"),
        TimelinePoint(date="1931", label="Haddon Sundblom e o Ícone Global Moderno", value="PADRONIZAÇÃO"),
    ]
    global_nodes: List[BoardNode] = [
        BoardNode(id="n1", title="SATURNÁLIA • 217 A.C.", role="Velas, ramos verdes e inversão social em Roma", badge="ORIGEM #01"),
        BoardNode(id="n2", title="SOL INVICTUS • 274-336", role="Solstício de 25 de dezembro absorvido por Roma", badge="CALENDÁRIO #02"),
        BoardNode(id="n3", title="NICOLAU DE MIRA", role="Bispo anatólico que virou Sinterklaas e Papai Noel", badge="IDENTIDADE #03"),
        BoardNode(id="n4", title="KRAMPUS & PURITANOS", role="Medo alpino e leis armadas de 1647 antes da era vitoriana", badge="REPRESSÃO #04"),
    ]

    # 25 rigorously fact-checked scenes (~92-97 words each -> ~2,340 words total, ~16m30s-17m20s!)
    raw_specs: List[Dict[str, Any]] = [
        # ---------------- ACT 0: COLD OPEN HOOK (00:00 - 01:15, cadence 2.2s) ----------------
        {
            "act_id": "ACT_0_COLD_OPEN_HOOK",
            "act_label": "COLD OPEN",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 2.2,
            "pattern_interrupt": False,
            "lt_title": "EUROPA • 25 DE DEZEMBRO",
            "lt_sub": "ARQUIVO HISTÓRICO • A PARADOXAL NOITE DE INVERNO",
            "headline": "NATAL: DOIS MIL ANOS DE RITUAIS, MOTINS E REESCRITA",
            "quote": "Por trás das luzes de dezembro escondem-se leis militares, inversões sociais romanas e séculos de disputa pelo controle do inverno.",
            "map_orig": "ROMA",
            "map_dest": "LONDRES",
            "map_metric": "2.000 ANOS DE TRANSFORMAÇÃO",
            "photo_q": "dark candlelit antique european winter street medieval",
            "broll_q": "burning candle dark shadow winter",
            "pip_q": "fireplace embers dark room",
            "shots": [
                "Dramatic chiaroscuro wide cinema still of a dark Victorian European living room lit only by real beeswax candles on a spruce tree casting long ominous shadows",
                "Intimate close-up of wax candles melting over ancient evergreen pine branches and antique tarnished ornaments in darkness",
                "Atmospheric 17th-century cobblestone alleyway in thick winter fog lit by flickering iron torches carried by shadowy figures",
                "Dark museum archival table covered with weathered parchment scrolls, wax seals, antique iron keys, and flickering candlelight",
                "Moody silhouette of an ancient European stone cathedral emerging through freezing December mist at twilight",
            ],
            "narration": (
                "Todo dia vinte e cinco de dezembro, bilhões de pessoas celebram o Natal acreditando estar diante de uma noite de paz e tradição imutável. "
                "Montamos árvores iluminadas, trocamos presentes e repetimos músicas acolhedoras sem suspeitar da história turbulenta enterrada sob cada símbolo da nossa sala. "
                "Durante a maior parte dos últimos dois mil anos, o final de dezembro não foi uma festa calma dentro de casa: "
                "foi território de rituais pagãos, inversão social extrema, decretos imperiais, criaturas folclóricas nas montanhas e motins armados reprimidos por soldados."
            ),
        },
        {
            "act_id": "ACT_0_COLD_OPEN_HOOK",
            "act_label": "COLD OPEN",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "fern_3d_reconstruction",
            "cut_cadence_s": 2.2,
            "pattern_interrupt": False,
            "lt_title": "DOSSIÊ FORENSE • 217 A.C. A 1931",
            "lt_sub": "QUATRO CAMADAS ENTERRADAS SOB UMA ÚNICA DATA",
            "headline": "COMO IMPÉRIOS, IGREJAS E EDITORAS REDESENHARAM DEZEMBRO",
            "quote": "Cada símbolo natalino moderno sobreviveu como um fóssil cultural de disputas políticas e religiosas ao longo de dois milênios.",
            "map_orig": "ROMA",
            "map_dest": "NOVA YORK",
            "map_metric": "5 ERAS • 1 DATA DISPUTADA",
            "photo_q": "ancient parchment archive historical timeline scrolls candle",
            "broll_q": "old leather book candle dark archive",
            "pip_q": "candle flame dark shadow",
            "shots": [
                "Dark archival close-up of layered ancient Latin manuscripts, medieval woodcut engravings, and 17th-century parliamentary decrees under dramatic top light",
                "Shadowy silhouette of an antique Roman marble bust illuminated by a single cold moonlight beam in an obsidian museum gallery",
                "Close-up of weathered iron chains resting beside tarnished silver coins and old wax-sealed documents on dark oak",
                "Atmospheric dark portrait of a 19th-century London engraving press printing dramatic winter woodcuts by oil lamp",
                "Moody chiaroscuro wide shot of a candlelit antique European library filled with towering leather-bound historical chronicles",
            ],
            "narration": (
                "Se abríssemos os arquivos históricos da Europa como um investigador abre uma cena forense, descobriríamos que quase nada no Natal nasceu no mesmo século ou no mesmo país. "
                "A data veio de disputas solares no Império Romano. "
                "O nome do bom velhinho nasceu de um bispo duro da Anatólia que derrubava templos antigos. "
                "Houve anos em que cantar canções natalinas dava prisão na Inglaterra e multa pesada na América Colonial. "
                "Mas como um festival de caos, inversão social e decretos militares foi cirurgicamente reescrito para se tornar a noite mais sagrada do planeta?"
            ),
        },
        # ---------------- ACT 1: WORLD BUILDING (01:15 - 04:30, cadence 4.0s) ----------------
        {
            "act_id": "ACT_1_WORLD_BUILDING",
            "act_label": "CAPÍTULO I",
            "chapter_card": _spaced_chapter_label("I", lang=clean_lang),
            "chapter_subtitle": "A NOITE EM QUE O SOL MORRIA",
            "visual_mode": "cinema_multishot",
            "cut_cadence_s": 4.0,
            "pattern_interrupt": False,
            "lt_title": "MEDITERRÂNEO • SOLSTÍCIO DE INVERNO",
            "lt_sub": "EUROPA AGRÁRIA PRÉ-CRISTÃ • O MEDO DA ESCURIDÃO",
            "headline": "ANTES DA ELETRICIDADE, DEZEMBRO ERA UMA SENTENÇA DE SOBREVIVÊNCIA",
            "quote": "No solstício de inverno, os dias atingiam o ponto mais curto do ano e o abate do gado garantia a última fartura antes da fome.",
            "map_orig": "NORTE DA EUROPA",
            "map_dest": "MEDITERRÂNEO",
            "map_metric": "21 A 25 DE DEZEMBRO • SOLSTÍCIO",
            "photo_q": "ancient winter solstice bonfire snow forest dark",
            "broll_q": "snow pine forest dark winter mist",
            "pip_q": "fireplace burning logs dark",
            "shots": [
                "Pre-Christian ancient European winter solstice wide shot of a vast frozen pine forest at dusk beneath a low dying pale sun on the horizon",
                "Ancient agrarian villagers in rough woven wool cloaks huddled around a roaring outdoor wooden bonfire against freezing snowstorm darkness",
                "Close-up of frost-covered stone sundial and weathered carved calendar stones buried under freezing December sleet",
                "Atmospheric interior of an ancient timber hall lit by smoky tallow torches and hanging evergreen pine boughs in deep winter",
                "Dramatic aerial silhouette of mist-shrouded ancient stone ruins under a brooding wintry slate-blue twilight sky",
            ],
            "narration": (
                "Para entender por que dezembro sempre mexeu tanto com a mente humana, volte a um mundo sem aquecimento, eletricidade ou supermercados. "
                "Na Europa agrária antiga, o solstício de inverno marcava o momento mais perigoso do ano. "
                "O sol nascia cada vez mais baixo no horizonte, as noites alongavam e os estoques de grãos encolhiam. "
                "Sem pasto para manter os rebanhos no gelo, as comunidades abatiam grande parte do gado nessa época, transformando dezembro na última fartura de carne fresca e vinho antes dos meses cruéis da fome."
            ),
        },
        {
            "act_id": "ACT_1_WORLD_BUILDING",
            "act_label": "CAPÍTULO I",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "2d_schematic_over_realism",
            "cut_cadence_s": 4.0,
            "pattern_interrupt": False,
            "lt_title": "ROMA • 217 A.C.",
            "lt_sub": "TEMPLO DE SATURNO • A CRISE APÓS O LAGO TRASIMENO",
            "headline": "217 A.C.: SENADO ROMANO OFICIALIZA A SATURNÁLIA EM MEIO AO PÂNICO",
            "quote": "Após o massacre contra Aníbal no Lago Trasimeno, Roma consultou os Livros Sibilinos e expandiu os banquetes públicos de Saturno.",
            "map_orig": "LAGO TRASIMENO",
            "map_dest": "ROMA",
            "map_metric": "17 A 23 DE DEZEMBRO • 217 A.C.",
            "photo_q": "Temple of Saturn Roman Forum ruins historical painting",
            "broll_q": "ancient roman ruins stone twilight",
            "pip_q": "burning torch stone wall dark",
            "shots": [
                "Ancient Rome 217 BC monumental stone columns of the Temple of Saturn in the Roman Forum lit by dramatic blazing braziers at night",
                "Roman senators in dark woolen togas consulting ancient sacred parchment scrolls inside a shadowed marble chamber by oil lamps",
                "Wide historical painting style view of Roman legions marching in defeat through misty Italian hills after the Battle of Lake Trasimene",
                "Close-up of a weathered Roman bronze statue of Saturn draped in loosened woolen ribbons illuminated by warm flickering torchlight",
                "Crowds of ancient Roman citizens in tunics gathering before marble steps carrying flaming torches under a stormy winter night sky",
            ],
            "narration": (
                "No coração da República Romana, esse terror diante da escuridão ganhou forma oficial num momento de pânico militar. "
                "Em duzentos e dezessete antes de Cristo, o general cartaginês Aníbal esmagou as legiões romanas na emboscada do Lago Trasimeno. "
                "Temendo ter perdido o favor dos deuses, o Senado consultou os Livros Sibilinos e decretou um banquete público no Templo de Saturno. "
                "As cordas de lã que amarravam a estátua do deus foram soltas, oficializando a Saturnália como válvula de celebração entre dezessete e vinte e três de dezembro."
            ),
        },
        {
            "act_id": "ACT_1_WORLD_BUILDING",
            "act_label": "CAPÍTULO I",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 4.0,
            "pattern_interrupt": False,
            "lt_title": "ROMA • TEMPLO DE SATURNO",
            "lt_sub": "SATURNÁLIA • O REI DA DESORDEM E OS PRESENTES DE CERA",
            "headline": "ESCRAVOS À MESA, DADOS LIBERADOS E VELAS DE CERA NO INVERNO ROMANO",
            "quote": "Durante a Saturnália, os romanos trocavam velas de cera (cerei) e bonecos de argila (sigillaria) enquanto suspendiam a hierarquia rígida.",
            "map_orig": "FÓRUM ROMANO",
            "map_dest": "ROMA",
            "map_metric": "REX SATURNALICIUS • INVERSÃO SOCIAL",
            "photo_q": "Roman Saturnalia banquet classical oil painting",
            "broll_q": "candle flame dark banquet shadow",
            "pip_q": "ancient clay pottery candle dark",
            "shots": [
                "Ancient Rome 217 BC chiaroscuro oil painting of a Roman Saturnalia candlelit banquet hall where masters pour wine for seated servants beneath evergreen garlands",
                "Close-up of ancient carved bone dice rolling across a scarred dark oak Roman tavern table beside clay wine amphorae and wax candles",
                "Portrait of a laughing Roman reveler crowned as Rex Saturnalicius wearing a conical felt pileus cap in dramatic torchlight",
                "Still life of antique Roman beeswax taper candles cerei and small terracotta figurines sigillaria arranged on dark stone",
                "Atmospheric shadowed view of a Roman stone street decorated with fresh pine and holly branches glowing faintly by oil lamps",
            ],
            "narration": (
                "Durante a Saturnália, a ordem rígida de Roma virava temporariamente de cabeça para baixo. "
                "Tribunais fechavam, guerras não podiam ser declaradas e até os jogos de dados, proibidos no restante do ano, eram liberados em praça pública. "
                "Em muitas casas, senhores vestiam roupas simples, serviam a refeição aos escravizados e sorteavam um Rei da Desordem, o Rex Saturnalicius, encarregado de dar ordens absurdas durante o banquete. "
                "As portas ganhavam ramos verdes, e os cidadãos trocavam presentes simbólicos: velas de cera, chamadas cerei, para celebrar a volta da luz, e pequenas estatuetas de argila conhecidas como sigillaria."
            ),
        },
        {
            "act_id": "ACT_1_WORLD_BUILDING",
            "act_label": "CAPÍTULO I",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "fern_3d_reconstruction",
            "cut_cadence_s": 4.0,
            "pattern_interrupt": False,
            "lt_title": "ROMA • 274 D.C.",
            "lt_sub": "IMPERADOR AURELIANO • DIES NATALIS SOLIS INVICTI",
            "headline": "274 D.C.: AURELIANO TRANSFORMA O SOL INVICTO EM CULTO DE ESTADO",
            "quote": "Para unificar um império despedaçado por guerras civis, Aureliano consagrou o templo do Sol Invicto em vinte e cinco de dezembro.",
            "map_orig": "PALMIRA",
            "map_dest": "ROMA",
            "map_metric": "25 DE DEZEMBRO • 274 D.C.",
            "photo_q": "Emperor Aurelian Roman coin Sol Invictus bust museum",
            "broll_q": "ancient roman marble statue dark shadow",
            "pip_q": "solar eclipse dark sky dramatic",
            "shots": [
                "Late Roman Empire 274 AD dramatic chiaroscuro portrait of Emperor Aurelian in weathered Roman bronze cuirass beneath a blazing golden solar halo in deep shadow",
                "Close-up of an ancient Roman gold coin struck with the radiate crown of Sol Invictus gleaming on dark obsidian stone",
                "Monumental shadowy silhouette of the newly consecrated Temple of Sol Invictus in Rome with towering Corinthian marble columns under winter twilight",
                "Torchlit Roman chariot race arena Circus Maximus shrouded in winter dust and evening mist in third-century Rome",
                "Dramatic dark stone relief of radiant sun rays carved in weathered Roman marble lit from a stark side angle",
            ],
            "narration": (
                "Quase cinco séculos depois, o calendário romano recebeu outra peça decisiva. "
                "No século terceiro, o Império quase se partiu em pedaços sob invasões, pragas e imperadores assassinados em sequência. "
                "Ao reconquistar as províncias rebeldes, o imperador Aureliano percebeu que precisava de um símbolo capaz de unificar exércitos e culturas diversas. "
                "Em duzentos e setenta e quatro depois de Cristo, Aureliano elevou o culto ao Sol Invicto a religião de Estado, fixando o nascimento do Sol Invencível em vinte e cinco de dezembro, a data do solstício no calendário juliano."
            ),
        },
        {
            "act_id": "ACT_1_WORLD_BUILDING",
            "act_label": "CAPÍTULO I",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "newspaper_highlighter",
            "cut_cadence_s": 4.0,
            "pattern_interrupt": False,
            "lt_title": "ROMA • 336 D.C.",
            "lt_sub": "CRONÓGRAFO DE 354 • O PRIMEIRO REGISTRO LITÚRGICO",
            "headline": "CRONÓGRAFO DE 354 REGISTRA A PRIMEIRA CELEBRAÇÃO CRISTÃ EM 25 DE DEZEMBRO",
            "quote": "Não houve um decreto único de Constantino impondo a data; o calendário romano de 336 d.C. mostra a absorção gradual do solstício.",
            "map_orig": "CONSTANTINOPLA",
            "map_dest": "ROMA",
            "map_metric": "CRONÓGRAFO DE 354 • REGISTRO 336 D.C.",
            "photo_q": "Chronograph of 354 ancient Roman manuscript Constantine bust",
            "broll_q": "ancient manuscript parchment candle dark",
            "pip_q": "gothic stone arches candlelight dark",
            "shots": [
                "Late Roman Empire 336 AD close-up of an illuminated Latin parchment calendar codex the Chronograph of 354 opened beside a reed pen and flickering oil lamp",
                "Chiaroscuro portrait of Emperor Constantine in imperial Roman purple cloak standing inside a dimly lit fourth-century basilica",
                "Early Christian stone basilica interior in fourth-century Rome illuminated solely by hanging brass oil chandeliers and incense smoke",
                "Close-up of weathered Roman stone inscription with early Latin numerals and chi-rho monogram carved in deep relief",
                "Shadowy nocturnal procession of fourth-century Roman clergy holding tall beeswax tapers through cold marble colonnades",
            ],
            "narration": (
                "Durante décadas, repetiu-se a versão simplificada de que o imperador Constantino assinou um decreto transformando Cristo no Sol Invicto. "
                "Os arquivos reais mostram uma estratégia mais sutil. "
                "Os Evangelhos nunca informam o dia do nascimento de Jesus. "
                "O primeiro registro ligando a festa a vinte e cinco de dezembro surge no Cronógrafo de trezentos e cinquenta e quatro, que preservou o calendário litúrgico de Roma de trezentos e trinta e seis, no último ano de Constantino. "
                "Em vez de combater o solstício, a Igreja absorveu a data e reescreveu seu sentido."
            ),
        },
        # ---------------- ACT 2: DEEP MECHANICS (04:30 - 11:15, cadence 3.5s, PI @ Sc07 & Sc12) ----------------
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO II",
            "chapter_card": _spaced_chapter_label("II", lang=clean_lang),
            "chapter_subtitle": "O BISPO, O DEUS E A FERA",
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": True,
            "lt_title": "MIRA • SÉCULO IV",
            "lt_sub": "LÍCIA ROMANA (ATUAL TURQUIA) • O REAL BISPO NICOLAU",
            "headline": "ANTES DO TRENÓ, SÃO NICOLAU ERA UM BISPO IMPLACÁVEL NA ANATÓLIA",
            "quote": "Crônicas bizantinas descrevem Nicolau salvando três irmãs com bolsas de ouro e liderando a demolição do templo pagão de Ártemis em Mira.",
            "map_orig": "MIRA",
            "map_dest": "NICEIA",
            "map_metric": "CONCÍLIO DE NICEIA • 325 D.C.",
            "photo_q": "Saint Nicholas of Myra Byzantine icon antique painting",
            "broll_q": "ancient stone temple ruins fog dark",
            "pip_q": "gold coins parchment dark candle",
            "shots": [
                "4th century AD Byzantine Anatolia dark chiaroscuro portrait of Bishop Nicholas of Myra in weathered Greek episcopal robes holding an iron-bound scripture in candlelight",
                "Close-up of small worn leather pouches overflowing with hammered Roman gold solidi coins resting on a dark wooden windowsill at night",
                "Dramatic shadowed scene of fourth-century Christian crowds tearing down crumbling marble columns of the pagan Temple of Artemis in ancient Lycia by torchlight",
                "Ancient coastal stone ruins of Myra in Anatolia silhouetted against a brooding stormy Mediterranean winter sky",
                "Candlelit Byzantine stone council hall evoking the 325 AD Council of Nicaea with bearded Greek bishops seated in deep chiaroscuro",
            ],
            "narration": (
                "Enquanto Roma reescrevia dezembro, um homem de carne e osso vivia na costa sul da atual Turquia, na antiga província romana da Lícia: Nicolau, bispo de Mira no século quarto. "
                "Longe da imagem sorridente de hoje, crônicas bizantinas retratam um líder rigoroso e combativo. "
                "Ele participou do Concílio de Niceia em trezentos e vinte e cinco, atirou bolsas de ouro pela janela para salvar três irmãs empobrecidas da servidão e liderou a demolição do templo pagão de Ártemis em Mira."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO II",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "dark_map_route",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "MIRA A AMSTERDÃ • SÉC. XI–XVII",
            "lt_sub": "DA ANATÓLIA AO MAR DO NORTE • DE NICOLAU A PAPAI NOEL",
            "headline": "COMO MARINHEIROS HOLANDESES TRANSFORMARAM SÃO NICOLAU EM SANTA CLAUS",
            "quote": "Relíquias levadas a Bari em 1087 espalharam o culto pela Europa; nos Países Baixos, Sint Nikolaas virou Sinterklaas e depois Santa Claus.",
            "map_orig": "MIRA",
            "map_dest": "AMSTERDÃ",
            "map_metric": "NICOLAU -> SINTERKLAAS -> PAPAI NOEL",
            "photo_q": "17th century Dutch galleon harbor winter historical painting",
            "broll_q": "dark ocean waves mist night",
            "pip_q": "antique nautical map compass candle",
            "shots": [
                "17th century Dutch Golden Age oil painting style wide shot of wooden sailing ships moored in a freezing foggy Amsterdam canal at night under oil lanterns",
                "Medieval Italian sailors in eleventh-century wool cloaks carrying a carved stone reliquary chest by flickering torches in Bari harbor",
                "Close-up of an antique brass astrolabe, weathered nautical chart of Europe, and candle wax dripping onto dark timber",
                "17th-century Dutch street scene in snow with a tall robed Sinterklaas figure wearing a bishop mitre illuminated by warm tavern windows",
                "Shadowy archival etching of colonial New Amsterdam timber houses along a wintry icy waterfront in the 1600s",
            ],
            "narration": (
                "Mas como um bispo grego do Mediterrâneo virou o nosso Papai Noel? "
                "Em mil e oitenta e sete, marinheiros italianos levaram os restos mortais de Nicolau para Bari, espalhando seu culto entre navegantes por toda a Europa. "
                "Nos portos da Holanda, São Nicolau foi encurtado pela fala popular para Sinterklaas, celebrado todo dezembro com presentes nos sapatos. "
                "Quando colonos holandeses levaram Sinterklaas para Nova Amsterdã, a pronúncia inglesa fundiu o nome em Santa Claus, a raiz direta do Papai Noel."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO II",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "cinema_multishot",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "ESCANDINÁVIA • YULE MEDIEVAL",
            "lt_sub": "JÓL E A CAÇADA SELVAGEM • ODIN NO CÉU DE INVERNO",
            "headline": "NO NORTE GELADO, ODIN CAVALGAVA AS TEMPESTADES DO SOLSTÍCIO DE YULE",
            "quote": "Durante as doze noites de Yule, povos germânicos acendiam o tronco sagrado e temiam a Caçada Selvagem liderada pelo deus barbudo Odin.",
            "map_orig": "ESCANDINÁVIA",
            "map_dest": "ALEMANHA",
            "map_metric": "YULE (JÓL) • 12 NOITES DE INVERNO",
            "photo_q": "Norse mythology Odin Wild Hunt painting winter night",
            "broll_q": "snow forest night dark wind",
            "pip_q": "burning fireplace yule log dark",
            "shots": [
                "9th century Early Medieval Scandinavian winter painting of a towering cloaked bearded rider evoking Odin on a dark warhorse silhouetted across a stormy moonlight sky",
                "Massive oak Yule log burning furiously inside a smoky Viking timber longhouse hearth surrounded by carved Norse pillars",
                "Close-up of weathered leather children boots stuffed with golden winter straw and oats placed beside a stone Nordic fireplace",
                "Shadowy snow-draped pine forest in medieval Scandinavia with eerie silver moonlight piercing heavy winter fog",
                "Weathered Viking runestone half-buried in deep December snow lit by the amber glow of a distant iron brazier",
            ],
            "narration": (
                "Enquanto o bispo avançava pelo Mediterrâneo, o norte da Europa guardava um inverno ainda mais sombrio. "
                "Entre escandinavos e germânicos, o solstício era o Yule, ou Jól, doze noites em que troncos imensos ardiam na lareira para afastar o frio e os espíritos. "
                "Nas tempestades mais violentas de dezembro, o deus barbudo Odin liderava a Caçada Selvagem pelos céus montado em Sleipnir, seu cavalo de oito patas. "
                "Crianças deixavam botas com palha perto do fogo para alimentar a montaria divina, esperando doces ou pequenos presentes em troca."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO II",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "ALPES AUSTRÍACOS • SÉCULO XI",
            "lt_sub": "KRAMPUSNACHT • O PACTO DUALISTA COM A FERA DE CHIFRES",
            "headline": "NOS ALPES MEDIEVAIS, SÃO NICOLAU GANHOU UMA SOMBRA ATERRORIZANTE: KRAMPUS",
            "quote": "Na noite de cinco de dezembro, Krampus arrastava correntes enferrujadas, varas de bétula e um cesto de madeira pelas vilas alpinas.",
            "map_orig": "ALPES AUSTRÍACOS",
            "map_dest": "BAVIERA",
            "map_metric": "5 DE DEZEMBRO • KRAMPUSNACHT",
            "photo_q": "antique vintage Krampus Austrian folklore engraving postcard",
            "broll_q": "foggy medieval alpine village snow night",
            "pip_q": "rusted iron chains dark shadow",
            "shots": [
                "11th century Medieval Austrian Alps dark gothic portrait of the horned winter folklore demon Krampus with weathered goat horns, matted dark fur, and rusted chains standing in a snowy mountain alley",
                "Close-up of heavy corroded medieval iron chains and bundled dried birch switches resting in fresh snow under faint lantern light",
                "Atmospheric 11th-century timber alpine village nestled beneath jagged snow-covered Austrian peaks in freezing blue moonlight",
                "Dramatic chiaroscuro wide shot of medieval peasant parents barring a heavy oak cottage door against howling December wind",
                "Weathered antique Central European woodcut illustration style depiction of a tall robed Saint Nicholas standing beside a dark horned shadow",
            ],
            "narration": (
                "Nos vales isolados dos Alpes austríacos e da Baviera, no século onze, a Igreja enfrentou um dilema impossível: as populações montanhesas simplesmente se recusavam a abandonar seus antigos espíritos de inverno. "
                "A solução folclórica foi um pacto sombrio de disciplina moral. "
                "Em vez de apagar o medo, a tradição o colocou ao lado do santo. "
                "Enquanto São Nicolau premiava os obedientes, sua contraparte demoníaca, o Krampus, descia das montanhas na noite de cinco de dezembro, a Krampusnacht. "
                "Com chifres retorcidos, correntes enferrujadas, varas de bétula chamadas Ruten e um cesto de madeira às costas, a criatura existia para lembrar que o inverno não perdoava os culpados."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO II",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "video_over_video_collage",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "EUROPA TUDOR • SÉC. XIV–XVI",
            "lt_sub": "ABADE DA DESORDEM E WASSAILING • O CAOS NAS RUAS",
            "headline": "NA IDADE MÉDIA, DEZEMBRO ERA UMA VÁLVULA EXPLOSIVA DE MULTIDÕES MASCARADAS",
            "quote": "Grupos de camponeses praticavam o wassailing às portas dos palácios exigindo comida, bebida e moedas sob ameaça de tumulto.",
            "map_orig": "INGLATERRA",
            "map_dest": "FRANÇA",
            "map_metric": "TWELFTH NIGHT • ABADE DA DESORDEM",
            "photo_q": "Bruegel medieval winter carnival painting Tudor festival",
            "broll_q": "medieval stone castle fog night",
            "pip_q": "burning torch medieval tavern dark",
            "shots": [
                "15th-century Late Medieval and Tudor Europe Pieter Bruegel style dark oil painting of a rowdy winter street crowd wearing eerie wooden masks carrying flaming torches",
                "Heavy iron-studded oak gates of a wealthy Tudor stone manor house besieged at night by poor peasants holding pewter wassail bowls",
                "Candlelit medieval tavern hall overflowing with masked revelers crowning a ragged jester as the Lord of Misrule",
                "Close-up of a steaming carved wooden wassail bowl filled with dark spiced ale and roasted apples on a rough oak table",
                "Moody winter evening view of crooked half-timbered Tudor London streets shrouded in woodsmoke and dark shadows",
            ],
            "narration": (
                "Entre os séculos catorze e dezesseis, o Natal europeu continuava a léguas de distância de uma reunião familiar tranquila. "
                "Das cortes dos reis Tudor às vielas lamacentas de Londres e Paris, as doze noites de festa reviviam o velho caos da Saturnália sob o comando do Abade da Desordem, o Lord of Misrule. "
                "Multidões de trabalhadores mascarados marchavam pelas ruas praticando o wassailing: batiam com força às portas das mansões aristocráticas exigindo comida, cerveja quente e moedas. "
                "Se os ricos se recusassem a abrir a despensa, janelas eram quebradas e muros pichados. "
                "Para os nobres, dezembro havia se tornado uma válvula social perigosamente volátil."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO III",
            "chapter_card": _spaced_chapter_label("III", lang=clean_lang),
            "chapter_subtitle": "O NATAL PROIBIDO POR LEI",
            "visual_mode": "2d_schematic_over_realism",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": True,
            "lt_title": "INGLATERRA • 1644–1647",
            "lt_sub": "PARLAMENTO LONGO E OLIVER CROMWELL • A ABOLIÇÃO PURITANA",
            "headline": "1647: PARLAMENTO INGLÊS DECRETA O NATAL UMA ABOMINAÇÃO PAGÃ ILEGAL",
            "quote": "Justamente pelas raízes pagãs da Saturnália e pela desordem nas ruas, puritanos proibiram o feriado e impuseram jejum obrigatório.",
            "map_orig": "WESTMINSTER",
            "map_dest": "INGLATERRA",
            "map_metric": "DECRETO PARLAMENTAR • JUNHO DE 1647",
            "photo_q": "Oliver Cromwell 17th century portrait English Civil War engraving",
            "broll_q": "dark gothic stone hall candle shadow",
            "pip_q": "antique parchment decree wax seal",
            "shots": [
                "1647 17th-century English Civil War Puritan England dark chiaroscuro oil portrait of Oliver Cromwell in blackened iron breastplate and plain white Puritan collar",
                "Dimly lit 17th-century Westminster parliamentary chamber packed with stern black-hatted Puritan lawmakers signing a wax-sealed parchment ordinance",
                "Close-up of a weathered 1647 English printed broadside proclamation nailed to a damp stone wall in freezing December rain",
                "Column of 17th-century New Model Army Roundhead pikemen and musketeers in lobster-tail steel helmets marching through foggy cobblestone streets",
                "Dark minimalist interior of a stripped Puritan stone church in 1640s England with bare whitewashed walls and zero winter greenery",
            ],
            "narration": (
                "E foi exatamente essa herança pagã e barulhenta que desencadeou o golpe mais radical contra o feriado na história ocidental. "
                "Em meio à Guerra Civil Inglesa, os puritanos que dominavam o Parlamento Longo em Londres passaram a denunciar o Natal como uma abominação pagã e papista sem nenhuma base nas Escrituras. "
                "Entre mil seiscentos e quarenta e quatro e mil seiscentos e quarenta e sete, o Parlamento aboliu oficialmente o Natal, a Páscoa e Pentecostes. "
                "O dia vinte e cinco de dezembro foi transformado por lei em uma jornada obrigatória de jejum, penitência e comércio aberto, fiscalizada pelo temido Novo Exército Modelo liderado por Oliver Cromwell."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO III",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "CANTERBURY • 25 DEZ 1647",
            "lt_sub": "KENT, INGLATERRA • O MOTIM DO PUDIM DE AMEIXA",
            "headline": "25 DE DEZEMBRO DE 1647: O MOTIM DO PUDIM DE AMEIXA EXPLODE EM CANTERBURY",
            "quote": "Quando o prefeito obrigou lojas a abrir em Canterbury, moradores jogaram futebol nas ruas, tomaram os portões da cidade e acenderam a Segunda Guerra Civil.",
            "map_orig": "CANTERBURY",
            "map_dest": "LONDRES",
            "map_metric": "25 DEZ 1647 • CANTERBURY, KENT",
            "photo_q": "Canterbury Westgate medieval gate 17th century England engraving",
            "broll_q": "medieval cobblestone street rain fog dark",
            "pip_q": "burning torch cobblestone night dark",
            "shots": [
                "1647 17th-century English Civil War Puritan England dramatic wide oil painting of angry 17th-century townsfolk in woolen doublets and cloaks clashing with steel-helmeted Roundhead pikemen beneath Canterbury medieval Westgate stone towers",
                "Close-up of a dark dense 17th-century English steamed plum pudding wrapped in coarse linen cloth lying beside fresh holly sprigs on wet medieval cobblestones",
                "Half-timbered 17th-century Canterbury wooden shopfronts with smashed leaded-glass windows and flickering oil lanterns in winter dusk",
                "Shadowy troop of 17th-century English parliamentary cavalry in iron buff coats riding with flintlock muskets through freezing mist toward Kent",
                "Historic dark stone silhouette of Canterbury Cathedral rising behind smoky torches in December 1647",
            ],
            "narration": (
                "A proibição rapidamente incendiou o interior da Inglaterra. "
                "Na manhã de vinte e cinco de dezembro de mil seiscentos e quarenta e sete, em Canterbury, no condado de Kent, o prefeito puritano Michael Page ordenou que todas as lojas abrissem. "
                "A reação foi explosiva: moradores penduraram azevinho nas fachadas, distribuíram pudim de ameixa nas ruas, improvisaram uma partida de futebol em desafio aberto e espancaram os guardas. "
                "Conhecido como o Motim do Pudim de Ameixa, o levante tomou os portões de Canterbury e acendeu o estopim da Segunda Guerra Civil Inglesa."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO III",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "dark_map_route",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "LONDRES A BOSTON • 1652–1659",
            "lt_sub": "PROIBIÇÃO TRANSATLÂNTICA • MULTA DE CINCO XELINS",
            "headline": "SOLDADOS FAREJAVAM CHAMINÉS EM LONDRES E BOSTON MULTAVA QUEM FOLGASSE",
            "quote": "Em 1659, a Corte Geral de Massachusetts impôs multa de cinco xelins a qualquer colono pego festejando ou faltando ao trabalho no Natal.",
            "map_orig": "LONDRES",
            "map_dest": "BOSTON",
            "map_metric": "MULTA DE 5 XELINS • MASSACHUSETTS 1659",
            "photo_q": "17th century colonial Boston Puritan engraving historical",
            "broll_q": "smoke chimney dark winter roof night",
            "pip_q": "antique silver shillings coins dark",
            "shots": [
                "1659 17th-century Colonial Puritan Massachusetts dark atmospheric scene of a Puritan watchman in wide-brimmed black hat inspecting wooden colonial Boston houses in falling snow by lantern light",
                "1652 Cromwellian London oil painting style view of Roundhead soldiers patrolling narrow foggy timber alleys peering up at smoking brick chimneys",
                "Close-up of a handwritten 1659 Massachusetts Bay Colony parchment law book beside five tarnished 17th-century silver shilling coins",
                "Cold misty North Atlantic wooden merchant ship sailing through dark winter swells between England and New England in the 1650s",
                "Dimly lit 17th-century English domestic hearth where a fearful family hides a roasting goose behind shuttered wooden windows",
            ],
            "narration": (
                "A repressão ao Natal atravessou até o Oceano Atlântico. "
                "Em Londres, durante a década de mil seiscentos e cinquenta, cronistas relataram soldados patrulhando becos para farejar chaminés suspeitas de assar ganso ou carne festiva às escondidas, derrubando portas e confiscando jantares inteiros. "
                "Do outro lado do mar, nas colônias puritanas da Nova Inglaterra, a vigilância foi ainda mais duradoura. "
                "Em maio de mil seiscentos e cinquenta e nove, a Corte Geral de Massachusetts, em Boston, aprovou uma lei explícita: qualquer pessoa flagrada celebrando o Natal, preparando banquetes ou se recusando a trabalhar no dia vinte e cinco de dezembro pagaria uma multa pesada de cinco xelins."
            ),
        },
        {
            "act_id": "ACT_2_DEEP_MECHANICS",
            "act_label": "CAPÍTULO III",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "newspaper_highlighter",
            "cut_cadence_s": 3.5,
            "pattern_interrupt": False,
            "lt_title": "LONDRES • 1660",
            "lt_sub": "A RESTAURAÇÃO DE CARLOS II • O RETORNO DA FESTA",
            "headline": "1660: APÓS A MORTE DE CROMWELL, REI CARLOS II REVOGA O BANIMENTO",
            "quote": "A Restauração reabriu teatros e tavernas e devolveu a folia ruidosa de dezembro — deixando a elite britânica inquieta diante das ruas.",
            "map_orig": "HOLANDA",
            "map_dest": "LONDRES",
            "map_metric": "RESTAURAÇÃO MONÁRQUICA • 1660",
            "photo_q": "King Charles II 1660 Restoration portrait painting museum",
            "broll_q": "gothic cathedral candle flame dark",
            "pip_q": "antique crown velvet shadow dark",
            "shots": [
                "1660 Restoration England King Charles II regal chiaroscuro Baroque oil portrait of King Charles II in velvet robes and long curled wig inside Whitehall Palace",
                "Candlelit 1660s London Restoration theater stage and bustling wooden tavern reopening with musicians and merrymakers in seventeenth-century doublets",
                "Close-up of a royal red wax seal stamped onto the 1660 Restoration proclamation repealing Cromwellian Puritan ordinances",
                "Dramatic shadowed procession along London cobblestone streets in 1660 with golden torches illuminating medieval timber facades",
                "Atmospheric 17th-century aristocratic parlor where wealthy London merchants gaze cautiously out leaded windows at rowdy December revelers",
            ],
            "narration": (
                "A ditadura puritana, porém, não resistiu ao próprio criador. "
                "Oliver Cromwell morreu em mil seiscentos e cinquenta e oito e, em mil seiscentos e sessenta, a Restauração levou o rei Carlos Segundo ao trono. "
                "Ao contrário de versões distorcidas, a Restauração não transformou o Natal em silêncio e oração: Carlos Segundo revogou o banimento, reabriu teatros e tavernas e devolveu a folia ruidosa de dezembro. "
                "Mas o trauma das revoltas armadas deixou a elite britânica obcecada por uma forma de domar dezembro."
            ),
        },
        # ---------------- ACT 3: CLIMAX & REVELATION (11:15 - 15:30, cadence 2.7s, PI @ Sc16) ----------------
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": _spaced_chapter_label("IV", lang=clean_lang),
            "chapter_subtitle": "A DOMESTICAÇÃO PERFEITA",
            "visual_mode": "fern_3d_reconstruction",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": True,
            "lt_title": "LONDRES • INÍCIO DO SÉC. XIX",
            "lt_sub": "REVOLUÇÃO INDUSTRIAL • O MEDO DA BURGUESIA",
            "headline": "NAS CIDADES DE FULIGEM, A VELHA TRADIÇÃO DE RUA VIROU AMEAÇA DE REVOLTA",
            "quote": "Com fábricas, trabalho infantil e miséria extrema em Londres e Manchester, operários batendo às portas em dezembro aterrorizavam a elite.",
            "map_orig": "MANCHESTER",
            "map_dest": "LONDRES",
            "map_metric": "REVOLUÇÃO INDUSTRIAL • 1800–1840",
            "photo_q": "19th century Victorian London smog factory Gustave Dore engraving",
            "broll_q": "foggy historic european alley night",
            "pip_q": "dark coal smoke vintage chimney",
            "shots": [
                "1840s Victorian London 19th century Gustave Dore style dark chiaroscuro engraving of soot-blackened brick textile factories belching winter coal smoke over crowded slums",
                "Shadowy Victorian Manchester alley in freezing mist with exhausted 19th-century workers in tattered wool coats passing gas streetlamps",
                "Heavy iron wrought-iron gates of a wealthy 1830s London Georgian townhouse lit by flickering gaslights separating rich interiors from dark streets",
                "Close-up of coal dust, iron factory gears, and worn ledger books illuminated by a single trembling oil wick lamp",
                "Moody atmospheric shot of a crowded early 19th-century Thames dockyard shrouded in yellow winter fog and torchlight",
            ],
            "narration": (
                "No início do século dezenove, a Revolução Industrial transformou Londres e Manchester em barris de pólvora cobertos de fuligem. "
                "Fábricas esmagavam operários e crianças em jornadas exaustivas sob desigualdade brutal. "
                "Nesse cenário explosivo, bandos de trabalhadores pobres batendo às portas das mansões no wassailing exigindo bebida e moedas deixaram de parecer folclore: para a burguesia assustada, aquilo cheirava a revolução urbana. "
                "Se os soldados de Cromwell não destruíram o Natal à força, o século dezenove tentaria algo mais esperto: tirá-lo das ruas e trancá-lo na sala."
            ),
        },
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "video_over_video_collage",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": False,
            "lt_title": "NOVA YORK • 1822–1823",
            "lt_sub": "CLEMENT CLARKE MOORE • A INVENÇÃO DO TRENÓ E DAS RENAS",
            "headline": "1823: UM POEMA DE NOVA YORK REINVENTA O VISITANTE DE INVERNO",
            "quote": "Publicado em 1823, 'A Visit from St. Nicholas' substituiu tumultos de rua por um elfo alegre descendo em silêncio pela chaminé.",
            "map_orig": "NOVA YORK",
            "map_dest": "LONDRES",
            "map_metric": "DEZEMBRO DE 1823 • TROY SENTINEL",
            "photo_q": "1823 Clement Clarke Moore Visit from St Nicholas antique illustration",
            "broll_q": "fireplace hearth dark night antique",
            "pip_q": "snow falling dark Victorian rooftop",
            "shots": [
                "1820s Early 19th-century Regency New York candlelit study where patrician scholar Clement Clarke Moore writes with a goose quill pen on parchment beside a frosted window",
                "Antique 1823 newspaper printing broadsheet of the Troy Sentinel showing classic early 19th-century typography under warm amber lamp light",
                "Atmospheric snow-covered 1820s New York brick townhouse rooftops and smoking chimneys beneath a crisp winter full moon",
                "Cozy yet dimly lit 1820s brick family hearth with knitted wool stockings hung quietly in deep chiaroscuro candlelight",
                "Vintage 19th-century dark copperplate engraving aesthetic of a miniature sleigh drawn across moonlight clouds above quiet sleeping rooftops",
            ],
            "narration": (
                "O primeiro passo cirúrgico dessa engenharia cultural aconteceu em Nova York, no inverno de mil oitocentos e vinte e dois. "
                "Preocupado com as arruaças natalinas que tomavam as ruas da cidade, o acadêmico aristocrata Clement Clarke Moore compôs para seus filhos um poema publicado anonimamente em dezembro de mil oitocentos e vinte e três: Uma Visita de São Nicolau. "
                "Em poucos versos, o antigo bispo severo e os bandos barulhentos das ruas desapareceram. "
                "No lugar deles surgiu um elfo simpático, inofensivo e silencioso, que chegava de trenó puxado por oito renas e descia privadamente pela chaminé da família respeitável enquanto as crianças dormiam."
            ),
        },
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": False,
            "lt_title": "LONDRES • DEZEMBRO DE 1843",
            "lt_sub": "CHARLES DICKENS • UM CONTO DE NATAL",
            "headline": "DEZEMBRO DE 1843: DICKENS ESCREVE A NOVELA QUE REFUNDOU O NATAL",
            "quote": "Escrito em apenas seis semanas por um autor endividado, 'Um Conto de Natal' redefiniu a data como caridade íntima e redenção familiar.",
            "map_orig": "LONDRES",
            "map_dest": "REINO UNIDO",
            "map_metric": "6 SEMANAS • 19 DE DEZEMBRO DE 1843",
            "photo_q": "Charles Dickens A Christmas Carol 1843 original John Leech illustration",
            "broll_q": "candle burning antique desk book dark",
            "pip_q": "snowy cobblestone Victorian london night",
            "shots": [
                "1840s Victorian London 19th century chiaroscuro portrait of bearded novelist Charles Dickens writing furiously by tallow candlelight at a cluttered mahogany desk",
                "Original 1843 Victorian leather-bound first edition book with gilt edges resting beside inkwell and brass spectacles on dark wood",
                "Atmospheric Victorian London foggy gaslit cobblestone street evoking Ebenezer Scrooge walking past shuttered counting houses in falling snow",
                "Warm candlelit Victorian family dinner table in a modest brick cottage glowing softly against the freezing winter darkness outside",
                "Dramatic shadowy silhouette of an iron door knocker on a weathered 1840s London oak door misted with frost",
            ],
            "narration": (
                "Vinte anos depois, em dezembro de mil oitocentos e quarenta e três, foi a vez da Inglaterra receber o roteiro emocional definitivo da nova festa. "
                "Afundado em dívidas e indignado com um relatório parlamentar sobre o trabalho infantil nas fábricas britânicas, o escritor Charles Dickens redigiu em apenas seis semanas febris uma novela curta chamada Um Conto de Natal. "
                "A transformação do avarento Ebenezer Scrooge vendeu toda a primeira tiragem antes da véspera e operou um milagre cultural: converteu o Natal de um rito coletivo e conflituoso de rua em um drama íntimo de consciência, caridade doméstica e perdão ao redor da mesa familiar."
            ),
        },
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "newspaper_highlighter",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": False,
            "lt_title": "WINDSOR • 1848",
            "lt_sub": "ILLUSTRATED LONDON NEWS • RAINHA VITÓRIA E PRÍNCIPE ALBERT",
            "headline": "1848: UMA GRAVURA REAL POPULARIZA A ÁRVORE DE NATAL NO MUNDO INTEIRO",
            "quote": "A xilogravura da família real britânica ao redor de um pinheiro iluminado no Castelo de Windsor transformou um costume alemão em padrão global.",
            "map_orig": "ALEMANHA",
            "map_dest": "WINDSOR",
            "map_metric": "ILLUSTRATED LONDON NEWS • DEZ 1848",
            "photo_q": "Queen Victoria Prince Albert 1848 Christmas tree Illustrated London News engraving",
            "broll_q": "historic castle winter twilight snow",
            "pip_q": "beeswax candles evergreen pine tree dark",
            "shots": [
                "1840s Victorian London 19th century authentic chiaroscuro historical scene of Queen Victoria and German-born Prince Albert with their children gathered calmly around a tabletop spruce tree lit by real beeswax candles and dried fruit inside Windsor Castle",
                "Close-up of an authentic 1848 Victorian woodcut engraving printed on archival broadsheet paper under warm directional gallery lighting",
                "Intimate macro shot of tiny wax candles clipped to dark evergreen pine needles alongside hand-blown Victorian glass baubles and gilded walnuts",
                "Majestic snow-dusted stone battlements of Windsor Castle towering in quiet winter twilight mist in 1848",
                "Candlelit 1840s Victorian middle-class London drawing room adopting the newly fashionable indoor evergreen tree",
            ],
            "narration": (
                "Faltava apenas uma imagem icônica capaz de selar essa revolução doméstica para milhões de lares, e ela chegou cinco anos mais tarde. "
                "Em dezembro de mil oitocentos e quarenta e oito, o jornal Illustrated London News estampou uma xilogravura histórica: a rainha Vitória, seu marido alemão, o príncipe Albert, e seus filhos reunidos com serenidade ao redor de uma árvore de Natal decorada dentro do Castelo de Windsor. "
                "Até então, enfeitar pinheiros dentro de casa era visto na Grã-Bretanha como um hábito regional da Alemanha. "
                "Da noite para o dia, a gravura real transformou a árvore iluminada no símbolo máximo da família respeitável na Europa e nas Américas."
            ),
        },
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "2d_schematic_over_realism",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": False,
            "lt_title": "NOVA YORK • 1863–1881",
            "lt_sub": "HARPER'S WEEKLY • THOMAS NAST E O LIVRO DE VIGILÂNCIA",
            "headline": "THOMAS NAST CRIA O POLO NORTE E TROCA AS CORRENTES DE KRAMPUS POR UM LIVRO",
            "quote": "Entre 1863 e 1881, as ilustrações de Nast deram ao Papai Noel oficina polar, casaco de pele e o registro moral de crianças boas e más.",
            "map_orig": "NOVA YORK",
            "map_dest": "POLO NORTE",
            "map_metric": "HARPER'S WEEKLY • 1863–1881",
            "photo_q": "Thomas Nast Merry Old Santa Claus 1881 Harpers Weekly engraving",
            "broll_q": "antique printing press engraving paper dark",
            "pip_q": "old parchment ledger quill dark candle",
            "shots": [
                "1870s Late 19th-century Victorian New York wood engraving era studio of illustrator Thomas Nast sketching Merry Old Santa Claus on a dark woodblock by oil lamp",
                "Close-up of a weathered 19th-century leather-bound ledger book opened to handwritten columns of children names under warm candlelight",
                "Archival Victorian woodcut engraving aesthetic of a rotund bearded Santa Claus in heavy fur-trimmed winter coat carrying wooden toys and a clay pipe",
                "Dark atmospheric 19th-century wooden toy-making workbench scattered with hand-carved rocking horses, paint jars, and brass tools",
                "Snowy nocturnal Victorian New York newspaper printing press rolling out thick stacks of 1881 winter holiday editions",
            ],
            "narration": (
                "Enquanto a árvore conquistava as salas britânicas, o cartunista político Thomas Nast completava o desenho visual do Papai Noel nas páginas da revista americana Harper's Weekly, entre mil oitocentos e sessenta e três e mil oitocentos e oitenta e um. "
                "Foi Nast quem inventou a oficina secreta no Polo Norte, consolidou o casaco volumoso debruado de pele branca e popularizou o livro de registros de crianças bem-comportadas e travessas. "
                "Repare na sutileza psicológica dessa troca: o velho terror físico das correntes e varas de Krampus foi aposentado, mas substituído por uma vigilância vitoriana invisível que moldava a obediência infantil o ano inteiro."
            ),
        },
        {
            "act_id": "ACT_3_CLIMAX_REVELATION",
            "act_label": "CAPÍTULO IV",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "video_over_video_collage",
            "cut_cadence_s": 2.7,
            "pattern_interrupt": False,
            "lt_title": "CHICAGO • 1931",
            "lt_sub": "HADDON SUNDBLOM • A PADRONIZAÇÃO COMERCIAL GLOBAL",
            "headline": "1931: NA GRANDE DEPRESSÃO, A PUBLICIDADE FIXA O ÍCONE VERMELHO NO PLANETA",
            "quote": "As pinturas a óleo de Haddon Sundblom para a Coca-Cola consolidaram o Papai Noel humano, acolhedor e vermelho-e-branco exportado globalmente.",
            "map_orig": "CHICAGO",
            "map_dest": "MUNDO",
            "map_metric": "1931 • ICONOGRAFIA GLOBAL",
            "photo_q": "1930s Great Depression vintage winter department store window Chicago",
            "broll_q": "vintage film projector warm glow dark",
            "pip_q": "oil painting brush canvas studio dark",
            "shots": [
                "1931 Great Depression era early 20th-century America dark atmospheric painter studio where illustrator Haddon Sundblom works with oil brushes on a warm canvas of a human-scaled red-coated Santa Claus",
                "1930s snow-dusted Chicago department store display window glowing warmly in amber tungsten light along a dark wintry avenue with 1930s wool-coated pedestrians",
                "Close-up of vintage 1930s oil paint tubes, crimson pigment on a wooden palette, and archival magazine layout proofs under a brass lamp",
                "Atmospheric 1930s family gathered around a glowing wooden cathedral radio receiver on a cold December evening",
                "Archival sepia-toned 1930s winter streetcar gliding slowly through softly falling snow in pre-war America",
            ],
            "narration": (
                "A peça final dessa engenharia visual chegou no auge da Grande Depressão. "
                "Em mil novecentos e trinta e um, buscando vender refrigerante também nos meses gelados, a Coca-Cola contratou o ilustrador Haddon Sundblom para pintar anúncios de inverno em revistas nacionais. "
                "Embora o vermelho já aparecesse em ilustrações anteriores, foi o pincel a óleo de Sundblom que fixou no imaginário coletivo um Papai Noel de estatura humana, rosto rosado, olhar caloroso e traje vermelho e branco impecável. "
                "Impulsionada pelo rádio, pelas vitrines das grandes lojas de departamento e depois pela televisão, aquela silhueta comercial atravessou fronteiras e padronizou o Natal em praticamente todos os continentes."
            ),
        },
        # ---------------- ACT 4: ABRUPT ENDING (15:30 - 17:00, final ~75s, ZERO CTA, abrupt 0.5s cut) ----------------
        {
            "act_id": "ACT_4_ABRUPT_ENDING",
            "act_label": "EPÍLOGO",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "sliding_timeline",
            "cut_cadence_s": 4.5,
            "pattern_interrupt": False,
            "lt_title": "SÍNTESE FORENSE • 217 A.C. A 1931",
            "lt_sub": "CADA ENFEITE NA SALA É UM FÓSSIL ARQUEOLÓGICO",
            "headline": "SEIS SÉCULOS E SEIS IMPÉRIOS REUNIDOS NA MESMA SALA DE ESTAR",
            "quote": "Os ramos verdes vêm da Saturnália, a data do Sol Invictus, os presentes de Mira, o trenó de Odin, a árvore de Windsor e o casaco de 1931.",
            "map_orig": "ROMA",
            "map_dest": "HOJE",
            "map_metric": "ARQUEOLOGIA DO NATAL",
            "photo_q": "dark candlelit pine tree antique ornaments chiaroscuro",
            "broll_q": "candle flame dark quiet shadow",
            "pip_q": "antique evergreen wreath beeswax candle",
            "shots": [
                "Dramatic museum forensic chiaroscuro collage still of antique Roman wax candles, medieval evergreen boughs, old parchment seals, and hand-blown Victorian glass spheres on dark slate",
                "Slow atmospheric view of a quiet darkened modern living room lit solely by warm candlelight flickering across pine branches",
                "Close-up of a single crimson glass ornament reflecting a warm candle flame in pitch darkness",
                "Shadowy silhouette of ancient evergreen pine needles dusted with snow outside a leaded glass window",
            ],
            "narration": (
                "Quando colocamos todas as peças lado a lado na mesa forense, o mapa completo se revela com clareza impressionante. "
                "Cada enfeite que você segura nas mãos em dezembro é um fóssil arqueológico sobrevivente de outro mundo. "
                "Os ramos verdes e as velas vêm da Saturnália romana. "
                "O dia vinte e cinco de dezembro ecoa o solstício do Sol Invictus absorvido no século quarto. "
                "Os presentes secretos herdaram o nome do bispo Nicolau de Mira, o trenó nos céus carrega o rastro da Caçada Selvagem de Odin, o pinheiro na sala nasceu em Windsor e o casaco vermelho ganhou o mundo nas revistas do século vinte."
            ),
        },
        {
            "act_id": "ACT_4_ABRUPT_ENDING",
            "act_label": "EPÍLOGO",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "red_string_board",
            "cut_cadence_s": 4.5,
            "pattern_interrupt": False,
            "lt_title": "LEGADO • 2.000 ANOS DE HISTÓRIA",
            "lt_sub": "POR QUE NENHUM DECRETO CONSEGUIU APAGAR DEZEMBRO",
            "headline": "IMPÉRIOS CAÍRAM E LEIS PROIBIRAM — MAS A FOGUEIRA DE INVERNO SOBREVIVEU",
            "quote": "Por trás de reis, parlamentos e campanhas publicitárias, dezembro resistiu porque responde a um medo humano mais antigo que qualquer nação.",
            "map_orig": "ANTIGUIDADE",
            "map_dest": "PRESENTE",
            "map_metric": "SOBREVIVÊNCIA ANCESTRAL",
            "photo_q": "flickering hearth fire dark stone room winter",
            "broll_q": "fireplace embers glowing dark night",
            "pip_q": "dark winter sky faint twilight",
            "shots": [
                "Atmospheric wide chiaroscuro cinema shot of a lone glowing hearth fire burning softly inside a dark stone chamber as snow drifts silently past the window",
                "Close-up of glowing red wood embers pulsing gently in deep obsidian darkness",
                "Dark historic European cathedral silhouette standing quietly under a deep indigo winter solstice twilight sky",
                "Moody shadowy silhouette of a lone human figure looking out a tall frost-rimmed window into a silent snow-covered forest",
            ],
            "narration": (
                "Impérios gigantescos desmoronaram, parlamentos armados tentaram varrer a festa do calendário e grandes corporações redesenharam sua embalagem para vender sonhos em escala industrial. "
                "Mesmo assim, nenhuma lei, nenhum exército e nenhuma reforma conseguiu apagar o dia vinte e cinco de dezembro. "
                "Talvez porque, por baixo de todos os decretos políticos, interesses econômicos e contos açucarados, os seres humanos modernos ainda carreguem exatamente a mesma necessidade instintiva que movia nossos ancestrais dois mil anos atrás: acender luzes, reunir os seus e desafiar o frio quando o ano parece chegar ao fim."
            ),
        },
        {
            "act_id": "ACT_4_ABRUPT_ENDING",
            "act_label": "EPÍLOGO",
            "chapter_card": None,
            "chapter_subtitle": None,
            "visual_mode": "parallax_25d_photo",
            "cut_cadence_s": 4.5,
            "pattern_interrupt": False,
            "lt_title": "25 DE DEZEMBRO • O ETERNO SOLSTÍCIO",
            "lt_sub": "A FOGUEIRA ANCESTRAL NA SALA ESCURA",
            "headline": "A NOITE EM QUE O SOL MORREU",
            "quote": "As luzes na sala escura ainda respondem ao mesmo ritual de dois mil anos atrás.",
            "map_orig": "SOLSTÍCIO",
            "map_dest": "HOJE",
            "map_metric": "25 DE DEZEMBRO",
            "photo_q": "lone glowing beeswax candle dark shadow Christmas tree silhouette",
            "broll_q": "single candle flame darkness quiet",
            "pip_q": "dark pine branch shadow candle",
            "shots": [
                "Haunting chiaroscuro cinema still of a quiet dark living room where a single tree lit by warm candle-like amber lights casts tall ancestral shadows across dark walls",
                "Intimate slow close-up of a solitary beeswax candle flame flickering steadily in deep velvet darkness",
                "Atmospheric backlit silhouette of a person standing motionless gazing at warm amber winter light inside a silent dark room",
            ],
            "narration": (
                "A história oficial tentou cobrir tudo com neve limpa e papel brilhante, mas a memória mais profunda nunca desaparece de verdade. "
                "Quando você apagar as luzes nesta noite de vinte e cinco de dezembro, olhe para o brilho das velas e da árvore na sala escura: você está apenas celebrando uma festa moderna... ou ainda está mantendo acesa a fogueira ancestral contra a noite em que o sol morreu?"
            ),
        },
    ]

    # For ultra-short smoke tests (<= 1.5 min in 9:16), pick a concise fact-checked chronological slice;
    # otherwise deliver the COMPLETE 25-scene, 5-Act masterpiece!
    if float(target_minutes or 17.0) <= 1.5 and aspect_ratio == "9:16":
        selected_specs = [raw_specs[i] for i in (0, 3, 6, 7, 10, 13, 18, 24)]
    else:
        selected_specs = raw_specs

    scenes: List[NetflixDocScene] = []
    for idx, sp in enumerate(selected_specs):
        lt_t = _normalize_upper(_clean_doc_text(sp["lt_title"]))
        lt_s = _normalize_upper(_clean_doc_text(sp["lt_sub"]))
        locked_shots: List[str] = []
        for raw_sh in sp["shots"]:
            sh_p = _sanitize_dark_history_prompt(raw_sh, mood="dark_horror")
            if is_vertical:
                sh_p = _enforce_vertical_prompt_framing(sh_p)
            sh_p = _enforce_historical_era_prompt_lock(sh_p, lt_t, lt_s)
            locked_shots.append(sh_p)

        vmode: VisualModeType = sp["visual_mode"]
        # Safety invariant: dark_map_route ONLY when origin != destination
        if vmode == "dark_map_route" and sp["map_orig"].strip().lower() == sp["map_dest"].strip().lower():
            vmode = "2d_schematic_over_realism"

        narr_txt = _normalize_pt_century_ordinals_in_text(_clean_doc_text(sp["narration"]), lang=clean_lang)
        scenes.append(
            NetflixDocScene(
                scene_id=f"doc_sc_{idx + 1:02d}",
                act_id=sp["act_id"],
                act_label=sp["act_label"],
                chapter_card=sp["chapter_card"],
                chapter_subtitle=sp["chapter_subtitle"],
                visual_mode=vmode,
                visual_category=_resolve_visual_category(vmode, is_broll_shot=False),
                cut_cadence_s=float(sp["cut_cadence_s"]),
                pattern_interrupt=bool(sp["pattern_interrupt"]),
                mood="dark_horror",
                narration=narr_txt,
                lower_third_title=lt_t,
                lower_third_subtitle=lt_s,
                highlight_color="#EAB308" if idx % 2 == 0 else "#D9381E",
                evidence_headline=_clean_doc_text(sp["headline"]),
                evidence_quote=_clean_doc_text(sp["quote"]),
                map_origin=_clean_doc_text(sp["map_orig"]),
                map_destination=_clean_doc_text(sp["map_dest"]),
                map_metric=_clean_doc_text(sp["map_metric"]),
                timeline_points=global_timeline,
                board_nodes=global_nodes,
                image_prompt_en=locked_shots[0] if locked_shots else sp["photo_q"],
                bespoke_image_prompt_en=locked_shots[0] if locked_shots else "",
                prefer_gemini_photo=True,
                broll_query_en=sp["broll_q"],
                pip_broll_query_en=sp["pip_q"],
                photo_query_en=sp["photo_q"],
                extra_photo_queries_en=[sp["photo_q"], sp["broll_q"], sp["pip_q"]],
                shot_prompts_en=locked_shots,
                transition_type=_select_transition_for_scene(idx, vmode, sp["chapter_card"] is not None),
            )
        )

    plan_obj = NetflixDocPlan(
        schema_version="3.0.0",
        pipeline_name="Mixed_Media_High_Retention_Documentary_Engine",
        title="A Noite em que o Sol Morreu: A Real História Oculta do Natal" if not is_en else "The Night the Sun Died: The Real Hidden History of Christmas",
        subtitle="Arquivo Histórico • De Roma (217 a.C.) à Era Moderna" if not is_en else "Historical Archive • From Rome (217 BC) to the Modern Era",
        channel_name="Arquivos Sombrios" if not is_en else "Dark Vault Files",
        mood="dark_horror",
        lang=clean_lang,
        aspect_ratio=aspect_ratio,
        target_minutes=round(float(target_minutes or 17.0), 2),
        lut_file="02_dark_wealth.cube",
        voice_id=voice_id,
        caption_style=caption_style,
        thumbnail_hook="O NATAL PROIBIDO" if not is_en else "FORBIDDEN CHRISTMAS",
        topic_source="curated_5act_masterpiece_v3",
        tokens_used=0,
        cost_usd=0.0,
        pattern_interrupt_times=[240.0, 480.0, 720.0] if len(scenes) >= 20 else [],
        scenes=scenes,
        hashtags=["#documentario", "#historia", "#natal", "#historiaobscura", "#superhistorico"],
    )
    return audit_netflix_doc_plan(plan_obj.model_dump(), lang=clean_lang)


def generate_netflix_doc_plan(
    topic: str,
    aspect_ratio: str = "16:9",
    target_minutes: Optional[float] = None,
    lang: str = "pt_br",
    custom_directives: str = "",
    caption_style: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a complete investigative Netflix / MagnatesMedia / Super Histórico / Vox documentary plan (dict).

    - Schema v3.0.0 (`Mixed_Media_High_Retention_Documentary_Engine`, `16:9` default, supports up to `18.0` min).
    - For Christmas / dark-winter historical topics in `16:9` or `target_minutes >= 12.0`, builds the
      fact-checked 25-Scene, 5-Act Masterpiece (~2,250-2,450 words, ~16m-17m30s / 960-1,050s).
    - Matches the 10 curated financial dossiers when the topic clearly requests one of them.
    - For ANY new arbitrary open topic, invokes LIVE DeepSeek (`deepseek-chat`) or Google Gemini with
      automatic failover, enforcing era-locked prompts and strict forward chronology.
    - Always runs the final plan through `agents.retention_doctor.audit_netflix_doc_plan`.
    """
    ar: Literal["16:9", "9:16"] = "9:16" if str(aspect_ratio).strip() == "9:16" else "16:9"
    clean_lang = "en_us" if str(lang).lower().startswith("en") else "pt_br"
    is_en = clean_lang == "en_us"
    default_min = 17.0 if ar == "16:9" else 2.75
    t_min = max(0.35, min(20.0, float(target_minutes if target_minutes is not None else default_min)))
    target_seconds = max(25.0, t_min * 60.0)

    default_cap = "selective_emphasis" if ar == "16:9" else "cinema_minimal"
    if caption_style and resolve_caption_style is not None:
        resolved_cap_style = resolve_caption_style(caption_style)
    elif caption_style:
        resolved_cap_style = str(caption_style).strip() or default_cap
    else:
        resolved_cap_style = default_cap

    # =========================================================================
    # PATH 0: 5-ACT 25-SCENE HISTORICAL CHRISTMAS MASTERPIECE (16:9 OR >= 12m)
    # =========================================================================
    if _is_christmas_dark_history_topic(topic) and (ar == "16:9" or t_min >= 12.0):
        return _build_christmas_5act_masterpiece_plan(
            aspect_ratio=ar,
            target_minutes=t_min if t_min >= 12.0 else 17.0,
            clean_lang=clean_lang,
            caption_style=resolved_cap_style,
        )

    # Budget spoken narration cleanly for both short docs and 15-18 min (25-scene) YouTube documentaries
    if t_min >= 12.0:
        n_scenes = 25
        min_scene_words = 88
        max_scene_words = 98
    else:
        pace_wps = 2.05
        rough_scenes = max(4, min(60, int(round(max(20.0, target_seconds - 4.5) / 11.5))))
        est_chapters = _estimate_chapter_count(rough_scenes)
        overhead_s = est_chapters * 1.65 + rough_scenes * 0.42 + 1.25
        spoken_budget_s = max(14.0, target_seconds - overhead_s)
        total_target_words = max(48, int(round(spoken_budget_s * pace_wps)))
        words_per_sc_divisor = 25.0 if target_seconds >= 120.0 else 21.0
        n_scenes = max(4, min(60, int(round(total_target_words / words_per_sc_divisor))))
        est_chapters = _estimate_chapter_count(n_scenes)
        overhead_s = est_chapters * 1.65 + n_scenes * 0.42 + 1.25
        spoken_budget_s = max(14.0, target_seconds - overhead_s)
        total_target_words = max(48, int(round(spoken_budget_s * pace_wps)))
        avg_words_per_scene = total_target_words / float(n_scenes)
        if avg_words_per_scene >= 19.0:
            min_scene_words = max(14, int(math.floor(avg_words_per_scene)) - 4)
            max_scene_words = min(28, int(math.floor(avg_words_per_scene)) + 1)
        else:
            min_scene_words = max(11, int(round(avg_words_per_scene)) - 2)
            max_scene_words = min(24, int(round(avg_words_per_scene)) + 2)
    voice_id = "en-US-AndrewMultilingualNeural" if is_en else "Charon"

    matched_curated = _match_curated_dossier(topic)
    tokens_used = 0
    cost_usd = 0.0
    topic_source = "curated"

    # =========================================================================
    # PATH A: ONE OF THE 10 CURATED SIGNATURE FINANCIAL DOSSIERS
    # =========================================================================
    if matched_curated is not None:
        dossier = matched_curated
        mood = "corporate_thriller"
        channel_name = "Vault Files" if is_en else "Dossiê Capital"
        title = _clean_doc_text(dossier["title_en"] if is_en else dossier["title_pt"])
        subtitle = _clean_doc_text(dossier["sub_en"] if is_en else dossier["sub_pt"])
        thumb_hook = _clean_doc_text(dossier["hook_en"] if is_en else dossier["hook_pt"])
        base_narr = list(dossier["narr_en"] if is_en else dossier["narr_pt"])
        chapter_subs = _default_chapter_subtitles_for_mood(mood, is_en)

        # Optional LLM expansion for longer mid-roll curated documentaries (> 0.6 min)
        settings = get_settings() or {}
        dkey = str(settings.get("deepseek_api_key") or "").strip()
        gkey = str(settings.get("gemini_api_key") or "").strip()
        if n_scenes > len(base_narr) and (dkey or gkey):
            sys_p = (
                f"You are an investigative documentary scriptwriter (Netflix / MagnatesMedia style) writing in {'American English' if is_en else 'Brazilian Portuguese'}. "
                f"Write exactly {n_scenes} gripping, factual narration paragraphs (18-26 words each) about '{title}'. "
                'Return ONLY valid JSON: {"lines":["..."]}'
            )
            try:
                if dkey:
                    from openai import OpenAI

                    cli = OpenAI(api_key=dkey, base_url="https://api.deepseek.com", timeout=35.0)
                    resp = cli.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": f"TOPIC: {title}"}],
                        temperature=0.7,
                        max_tokens=min(4000, n_scenes * 75),
                        response_format={"type": "json_object"},
                    )
                    data = _extract_clean_json(resp.choices[0].message.content or "{}")
                    if isinstance(data.get("lines"), list) and len(data["lines"]) >= 5:
                        base_narr = [str(x).strip() for x in data["lines"][:n_scenes]]
                        u = resp.usage
                        pt = int(getattr(u, "prompt_tokens", 500))
                        ct = int(getattr(u, "completion_tokens", 500))
                        tokens_used = pt + ct
                        cost_usd = 0.0002
                        record_token_usage("deepseek", "deepseek-chat", pt, ct, 0, cost_usd)
            except Exception:
                pass

        while len(base_narr) < n_scenes:
            idx_add = len(base_narr)
            tp = dossier["timeline"][idx_add % len(dossier["timeline"])]
            nd = dossier["nodes"][idx_add % len(dossier["nodes"])]
            if is_en:
                base_narr.append(
                    f"In {tp['date']}, forensic investigators cross-referenced {nd['title']} ({nd['role']}) and uncovered a critical milestone of {tp['value']} linked directly to {dossier['dest']}."
                )
            else:
                base_narr.append(
                    f"Em {tp['date']}, os auditores forenses cruzaram os registros de {nd['title']} ({nd['role']}) e descobriram uma movimentação crítica de {tp['value']} conectada a {dossier['dest']}."
                )

        broll_pool = list(dossier.get("broll_queries") or _OPEN_TOPIC_FALLBACK_MEDIA["corporate_thriller"]["broll"])
        pip_pool = list(dossier.get("pip_queries") or _OPEN_TOPIC_FALLBACK_MEDIA["corporate_thriller"]["pip"])
        photo_pool = list(dossier.get("photo_queries") or _OPEN_TOPIC_FALLBACK_MEDIA["corporate_thriller"]["photos"])

        scenes: List[NetflixDocScene] = []
        chapter_counter = 0
        chapter_step = max(2, len(base_narr) // min(4, max(2, len(base_narr) // 2)))

        for idx, line_txt in enumerate(base_narr):
            vmode: VisualModeType = _select_visual_mode_for_scene(idx, len(base_narr))
            chap_card: Optional[str] = None
            chap_sub: Optional[str] = None
            if idx == 0:
                act_lbl = "COLD OPEN"
            elif idx == 1 or (idx >= 3 and (idx - 1) % chapter_step == 0 and chapter_counter < 4):
                roman = ROMAN_NUMERALS[min(chapter_counter, len(ROMAN_NUMERALS) - 1)]
                chap_card = _spaced_chapter_label(roman, lang=clean_lang)
                chap_sub = chapter_subs[min(chapter_counter, len(chapter_subs) - 1)]
                act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"
                chapter_counter += 1
            else:
                roman = ROMAN_NUMERALS[max(0, min(chapter_counter - 1, len(ROMAN_NUMERALS) - 1))]
                act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"

            tp_cur = dossier["timeline"][idx % len(dossier["timeline"])]
            lt_title = f"{dossier['origin']} • {dossier['dest']} • {tp_cur['date']}"
            lt_sub = f"{subtitle.upper()} • {tp_cur['value']}"

            broll_q = broll_pool[idx % len(broll_pool)]
            pip_q = pip_pool[idx % len(pip_pool)]
            if pip_q.lower() == broll_q.lower() and len(pip_pool) > 1:
                pip_q = pip_pool[(idx + 1) % len(pip_pool)]
            photo_q = photo_pool[idx % len(photo_pool)]
            extra_photos = [photo_pool[(idx + off) % len(photo_pool)] for off in range(4)]

            scenes.append(
                NetflixDocScene(
                    scene_id=f"doc_sc_{idx + 1:02d}",
                    act_label=act_lbl,
                    chapter_card=chap_card,
                    chapter_subtitle=chap_sub,
                    visual_mode=vmode,
                    mood=mood,
                    narration=_clean_doc_text(line_txt),
                    lower_third_title=_normalize_upper(_clean_doc_text(lt_title)),
                    lower_third_subtitle=_normalize_upper(_clean_doc_text(lt_sub)),
                    highlight_color="#FFD166" if idx % 2 == 0 else "#FF2E93",
                    evidence_headline=_clean_doc_text(dossier["headline"]),
                    evidence_quote=_clean_doc_text(dossier["quote_en"] if is_en else dossier["quote_pt"]),
                    map_origin=_clean_doc_text(dossier["origin"]),
                    map_destination=_clean_doc_text(dossier["dest"]),
                    map_metric=_clean_doc_text(dossier["metric_en"] if is_en else dossier["metric_pt"]),
                    timeline_points=[TimelinePoint(**pt) for pt in dossier["timeline"]],
                    board_nodes=[BoardNode(**nd) for nd in dossier["nodes"]],
                    image_prompt_en=photo_q,
                    bespoke_image_prompt_en="",
                    prefer_gemini_photo=False,
                    broll_query_en=broll_q,
                    pip_broll_query_en=pip_q,
                    photo_query_en=photo_q,
                    extra_photo_queries_en=extra_photos,
                    transition_type=_select_transition_for_scene(idx, vmode, chap_card is not None),
                )
            )

        _ensure_topic_open_loops(scenes, mood=mood, clean_lang=clean_lang)
        plan_obj = NetflixDocPlan(
            title=title,
            subtitle=subtitle,
            channel_name=channel_name,
            mood=mood,
            lang=clean_lang,
            aspect_ratio=ar,
            target_minutes=t_min,
            lut_file="02_dark_wealth.cube",
            voice_id=voice_id,
            caption_style=resolved_cap_style,
            thumbnail_hook=thumb_hook,
            topic_source=topic_source,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            scenes=scenes,
            hashtags=["#documentario", "#investigacao", "#financas", "#dossiecapital" if not is_en else "#vaultfiles"],
        )
        return audit_netflix_doc_plan(plan_obj.model_dump(), lang=clean_lang)

    # =========================================================================
    # PATH B: TRUE UNLIMITED OPEN-TOPIC AI DOCUMENTARY DIRECTOR (ANY TOPIC!)
    # =========================================================================
    mood_hint = _classify_topic_mood(topic)
    llm_res = _call_open_topic_director_llm(
        topic=topic,
        n_scenes=n_scenes,
        clean_lang=clean_lang,
        mood_hint=mood_hint,
        custom_directives=custom_directives,
        aspect_ratio=ar,
        min_scene_words=min_scene_words,
        max_scene_words=max_scene_words,
        target_seconds=target_seconds,
    )

    if llm_res is not None:
        raw_plan, topic_source, tokens_used, cost_usd = llm_res
        mood = _normalize_mood(raw_plan.get("mood"), topic)
        media_defaults = _OPEN_TOPIC_FALLBACK_MEDIA.get(mood, _OPEN_TOPIC_FALLBACK_MEDIA["epic_history"])
        off_seed = _build_open_topic_offline_dossier(topic, clean_lang=clean_lang, mood=mood)

        def _safe_field(val: Any, fallback: str) -> str:
            txt = _clean_doc_text(str(val or "").strip())
            if not txt:
                return fallback
            if mood != "corporate_thriller" and _FORBIDDEN_FINANCE_LEFTOVERS_RE.search(txt):
                return fallback
            return txt

        title = _safe_field(raw_plan.get("title"), off_seed["title"])
        subtitle = _safe_field(raw_plan.get("subtitle"), off_seed["subtitle"])
        channel_name = _safe_field(raw_plan.get("channel_name"), _default_channel_for_mood(mood, is_en))
        thumb_hook = _safe_field(raw_plan.get("thumbnail_hook"), off_seed["thumbnail_hook"]).upper()
        # Keep thumbnail hook crisp (max 3-4 words)
        if len(thumb_hook.split()) > 4:
            thumb_hook = " ".join(thumb_hook.split()[:3])

        default_chap_subs = _default_chapter_subtitles_for_mood(mood, is_en)

        global_origin = _safe_field(raw_plan.get("map_origin"), off_seed["map_origin"])
        global_dest = _safe_field(raw_plan.get("map_destination"), off_seed["map_destination"])
        global_metric = _safe_field(raw_plan.get("map_metric"), off_seed["map_metric"])
        global_headline = _safe_field(raw_plan.get("evidence_headline"), off_seed["evidence_headline"])
        global_quote = _safe_field(raw_plan.get("evidence_quote"), off_seed["evidence_quote"])

        # Timeline points (4 real historical/topic milestones)
        raw_tl = raw_plan.get("timeline_points")
        timeline_pts: List[TimelinePoint] = []
        if isinstance(raw_tl, list):
            for idx_t, item in enumerate(raw_tl[:6]):
                if isinstance(item, dict):
                    fb_t = off_seed["timeline_points"][idx_t % len(off_seed["timeline_points"])]
                    timeline_pts.append(
                        TimelinePoint(
                            date=_safe_field(item.get("date"), fb_t["date"]),
                            label=_safe_field(item.get("label"), fb_t["label"]),
                            value=_safe_field(item.get("value"), fb_t["value"]),
                        )
                    )
        while len(timeline_pts) < 4:
            fb_t = off_seed["timeline_points"][len(timeline_pts) % len(off_seed["timeline_points"])]
            timeline_pts.append(TimelinePoint(**fb_t))

        # Board nodes (4 real entities/concepts from the topic)
        raw_nodes = raw_plan.get("board_nodes")
        board_nodes: List[BoardNode] = []
        if isinstance(raw_nodes, list):
            for idx_n, item in enumerate(raw_nodes[:4]):
                if isinstance(item, dict):
                    fb_n = off_seed["board_nodes"][idx_n % len(off_seed["board_nodes"])]
                    board_nodes.append(
                        BoardNode(
                            id=str(item.get("id") or f"n{idx_n + 1}"),
                            title=_safe_field(item.get("title"), fb_n["title"])[:24],
                            role=_safe_field(item.get("role"), fb_n["role"])[:32],
                            badge=_safe_field(item.get("badge"), fb_n["badge"])[:20],
                        )
                    )
        while len(board_nodes) < 4:
            fb_n = off_seed["board_nodes"][len(board_nodes) % len(off_seed["board_nodes"])]
            board_nodes.append(BoardNode(**fb_n))

        raw_scenes = [s for s in (raw_plan.get("scenes") or []) if isinstance(s, dict)]
        # Collect all topic-authentic English photo queries generated across scenes for rich multi-photo pools
        topic_photo_pool: List[str] = []
        for rs in raw_scenes:
            pq_r = _safe_field(rs.get("photo_query_en"), "")
            if pq_r and pq_r.lower() not in {x.lower() for x in topic_photo_pool}:
                topic_photo_pool.append(pq_r)
            for ep in (rs.get("extra_photo_queries_en") or []):
                ep_c = _safe_field(ep, "")
                if ep_c and ep_c.lower() not in {x.lower() for x in topic_photo_pool}:
                    topic_photo_pool.append(ep_c)
        for fb_p in media_defaults["photos"]:
            if len(topic_photo_pool) >= 8:
                break
            if fb_p.lower() not in {x.lower() for x in topic_photo_pool}:
                topic_photo_pool.append(fb_p)

        # Pad scenes cleanly if LLM returned slightly fewer than n_scenes (e.g., long target_minutes)
        while len(raw_scenes) < n_scenes:
            idx_pad = len(raw_scenes)
            tp_p = timeline_pts[idx_pad % len(timeline_pts)]
            nd_p = board_nodes[idx_pad % len(board_nodes)]
            narr_pad = (
                f"In {tp_p.date}, historical accounts surrounding {nd_p.title} ({nd_p.role}) revealed a turning point marked by {tp_p.label}."
                if is_en
                else f"Em {tp_p.date}, os registros envolvendo {nd_p.title} ({nd_p.role}) revelaram uma virada decisiva marcada por {tp_p.label}."
            )
            raw_scenes.append({
                "chapter_subtitle": _normalize_upper(tp_p.label)[:36],
                "narration": narr_pad,
                "lower_third_title": _normalize_upper(f"{global_origin} • {global_dest} • {tp_p.date}"),
                "lower_third_subtitle": _normalize_upper(f"{nd_p.title} • {tp_p.value}"),
                "evidence_headline": global_headline,
                "evidence_quote": global_quote,
                "map_origin": global_origin,
                "map_destination": global_dest,
                "map_metric": global_metric,
                "broll_query_en": media_defaults["broll"][idx_pad % len(media_defaults["broll"])],
                "pip_broll_query_en": media_defaults["pip"][idx_pad % len(media_defaults["pip"])],
                "photo_query_en": topic_photo_pool[idx_pad % len(topic_photo_pool)],
                "extra_photo_queries_en": [topic_photo_pool[(idx_pad + k) % len(topic_photo_pool)] for k in range(4)],
                "bespoke_image_prompt_en": (
                    f"Vertical full-bleed 9:16 dark atmospheric 35mm documentary still of {nd_p.title} in {global_origin}, chiaroscuro lighting, no text"
                    if ar == "9:16"
                    else f"dark atmospheric 35mm documentary still of {nd_p.title} in {global_origin}, chiaroscuro lighting, no text"
                ),
                "prefer_gemini_photo": mood in ("dark_horror", "epic_history"),
            })

        scenes = []
        chapter_counter = 0
        chapter_step = max(2, n_scenes // min(4, max(2, n_scenes // 2)))

        for idx, rs in enumerate(raw_scenes[:n_scenes]):
            vmode = _select_visual_mode_for_scene(idx, n_scenes)
            tp_cur = timeline_pts[idx % len(timeline_pts)]
            sc_orig = _safe_field(rs.get("map_origin"), global_origin)
            sc_dest = _safe_field(rs.get("map_destination"), global_dest)
            if vmode == "dark_map_route" and sc_orig.strip().lower() == sc_dest.strip().lower():
                vmode = "2d_schematic_over_realism"
            sc_metric = _safe_field(rs.get("map_metric"), global_metric)
            lt_title = _normalize_upper(_safe_field(rs.get("lower_third_title"), f"{sc_orig} • {sc_dest} • {tp_cur.date}"))
            lt_sub = _normalize_upper(_safe_field(rs.get("lower_third_subtitle"), f"{subtitle} • {tp_cur.value}"))
            sc_head = _safe_field(rs.get("evidence_headline"), global_headline)
            sc_quote = _safe_field(rs.get("evidence_quote"), global_quote)
            sc_narr = _normalize_pt_century_ordinals_in_text(
                _safe_field(rs.get("narration"), off_seed["narr"][idx % len(off_seed["narr"])]),
                lang=clean_lang,
            )

            act_id, sc_cadence, sc_pi = _assign_act_metadata_for_index(idx, n_scenes)
            chap_card = None
            chap_sub = None
            if idx == 0:
                act_lbl = "COLD OPEN"
            elif idx == 1 or (idx >= 3 and (idx - 1) % chapter_step == 0 and chapter_counter < 4):
                roman = ROMAN_NUMERALS[min(chapter_counter, len(ROMAN_NUMERALS) - 1)]
                chap_card = _spaced_chapter_label(roman, lang=clean_lang)
                # Read chapter_subtitle DIRECTLY from THIS opening scene (NEVER shift a detached top-level array!)
                raw_sc_chap_sub = _safe_field(rs.get("chapter_subtitle"), "")
                if raw_sc_chap_sub:
                    chap_sub = _normalize_upper(raw_sc_chap_sub)
                else:
                    head_toks = [w_tok for w_tok in _normalize_upper(sc_head).split() if w_tok]
                    if head_toks and sc_head.strip().lower() != global_headline.strip().lower():
                        chap_sub = " ".join(head_toks[:4])
                    else:
                        lt_lead = lt_title.split("•")[0].strip()
                        if lt_lead and len(lt_lead) >= 3:
                            chap_sub = lt_lead
                        else:
                            chap_sub = _normalize_upper(default_chap_subs[min(chapter_counter, len(default_chap_subs) - 1)])
                act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"
                chapter_counter += 1
            else:
                roman = ROMAN_NUMERALS[max(0, min(chapter_counter - 1, len(ROMAN_NUMERALS) - 1))]
                act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"

            broll_q = _safe_field(rs.get("broll_query_en"), media_defaults["broll"][idx % len(media_defaults["broll"])])
            pip_q = _safe_field(rs.get("pip_broll_query_en"), media_defaults["pip"][idx % len(media_defaults["pip"])])
            if pip_q.lower() == broll_q.lower():
                pip_q = media_defaults["pip"][(idx + 1) % len(media_defaults["pip"])]

            photo_q = _safe_field(rs.get("photo_query_en"), topic_photo_pool[idx % len(topic_photo_pool)])
            raw_extra = rs.get("extra_photo_queries_en")
            extra_photos: List[str] = []
            if isinstance(raw_extra, list):
                for ep in raw_extra:
                    ep_c = _safe_field(ep, "")
                    if ep_c and ep_c.lower() not in {x.lower() for x in extra_photos}:
                        extra_photos.append(ep_c)
            for off_i in range(len(topic_photo_pool)):
                if len(extra_photos) >= 4:
                    break
                cand = topic_photo_pool[(idx + off_i) % len(topic_photo_pool)]
                if cand.lower() not in {x.lower() for x in extra_photos}:
                    extra_photos.append(cand)

            default_bespoke = (
                f"Vertical full-bleed 9:16 35mm dark documentary still of {photo_q}, dramatic chiaroscuro lighting, no text"
                if ar == "9:16"
                else f"cinematic 35mm dark documentary still of {photo_q}, dramatic chiaroscuro lighting, no text"
            )
            bespoke_p = _sanitize_dark_history_prompt(
                _safe_field(rs.get("bespoke_image_prompt_en"), default_bespoke),
                mood=mood,
            )
            if ar == "9:16":
                bespoke_p = _enforce_vertical_prompt_framing(bespoke_p)
            if mood in ("dark_horror", "epic_history"):
                bespoke_p = _enforce_historical_era_prompt_lock(bespoke_p, lt_title, lt_sub)
            raw_shots = rs.get("shot_prompts_en")
            shot_prompts: List[str] = []
            if isinstance(raw_shots, list):
                for sp in raw_shots:
                    sp_c = _sanitize_dark_history_prompt(_safe_field(sp, ""), mood=mood)
                    if ar == "9:16":
                        sp_c = _enforce_vertical_prompt_framing(sp_c)
                    if mood in ("dark_horror", "epic_history") and sp_c:
                        sp_c = _enforce_historical_era_prompt_lock(sp_c, lt_title, lt_sub)
                    if sp_c and sp_c.lower() not in {x.lower() for x in shot_prompts}:
                        shot_prompts.append(sp_c)
            if bespoke_p and bespoke_p.lower() not in {x.lower() for x in shot_prompts}:
                shot_prompts.insert(0, bespoke_p)
            # Ensure at least 5 distinct chronological bespoke shot prompts per scene (zero repetition!)
            if ar == "9:16":
                angle_cues = (
                    "Vertical full-bleed 9:16 35mm cinema still of",
                    "Intimate vertical close-up detail shot of",
                    "Moody vertical chiaroscuro candlelight documentary frame of",
                    "Shadowy nocturnal 9:16 portrait cinema still of",
                    "Haunting vertical historic archival 35mm film still of",
                )
            else:
                angle_cues = (
                    "dramatic wide establishing 35mm cinema still of",
                    "tense atmospheric close-up detail shot of",
                    "moody chiaroscuro candlelight documentary frame of",
                    "shadowy nocturnal cinema still of",
                    "haunting historic archival 35mm film still of",
                )
            for eq_i, eq in enumerate([photo_q, *extra_photos]):
                if len(shot_prompts) >= 6:
                    break
                eq_clean = str(eq or "").strip()
                if not eq_clean:
                    continue
                cand_sp = f"{angle_cues[eq_i % len(angle_cues)]} {eq_clean} ({lt_title}), 35mm film grain, no text"
                if mood in ("dark_horror", "epic_history"):
                    cand_sp = _enforce_historical_era_prompt_lock(cand_sp, lt_title, lt_sub)
                if cand_sp.lower() not in {x.lower() for x in shot_prompts}:
                    shot_prompts.append(cand_sp)
            pref_gem = bool(rs.get("prefer_gemini_photo", mood == "dark_horror" and idx in (0, 3)))

            scenes.append(
                NetflixDocScene(
                    scene_id=f"doc_sc_{idx + 1:02d}",
                    act_id=act_id,
                    act_label=act_lbl,
                    chapter_card=chap_card,
                    chapter_subtitle=chap_sub,
                    visual_mode=vmode,
                    visual_category=_resolve_visual_category(vmode, is_broll_shot=False),
                    cut_cadence_s=sc_cadence,
                    pattern_interrupt=sc_pi,
                    mood=mood,
                    narration=sc_narr,
                    lower_third_title=lt_title,
                    lower_third_subtitle=lt_sub,
                    highlight_color="#EAB308" if idx % 2 == 0 else "#D9381E",
                    evidence_headline=sc_head,
                    evidence_quote=sc_quote,
                    map_origin=sc_orig,
                    map_destination=sc_dest,
                    map_metric=sc_metric,
                    timeline_points=timeline_pts,
                    board_nodes=board_nodes,
                    image_prompt_en=bespoke_p or photo_q,
                    bespoke_image_prompt_en=bespoke_p,
                    prefer_gemini_photo=pref_gem,
                    broll_query_en=broll_q,
                    pip_broll_query_en=pip_q,
                    photo_query_en=photo_q,
                    extra_photo_queries_en=extra_photos[:4],
                    shot_prompts_en=shot_prompts[:6],
                    transition_type=_select_transition_for_scene(idx, vmode, chap_card is not None),
                )
            )

        raw_tags = raw_plan.get("hashtags")
        if isinstance(raw_tags, list) and raw_tags:
            hashtags = [str(t).strip() for t in raw_tags[:6] if str(t).strip()]
            hashtags = [t if t.startswith("#") else f"#{t}" for t in hashtags]
        else:
            hashtags = (
                ["#documentario", "#historiaobscura", "#misterio", "#cinema"]
                if mood == "dark_horror"
                else ["#documentario", "#historia", "#investigacao", "#cinema"]
            )

        _ensure_topic_open_loops(scenes, mood=mood, clean_lang=clean_lang)
        plan_obj = NetflixDocPlan(
            title=title,
            subtitle=subtitle,
            channel_name=channel_name,
            mood=mood,
            lang=clean_lang,
            aspect_ratio=ar,
            target_minutes=t_min,
            lut_file="02_dark_wealth.cube",
            voice_id=voice_id,
            caption_style=resolved_cap_style,
            thumbnail_hook=thumb_hook,
            topic_source=topic_source,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            pattern_interrupt_times=[240.0, 480.0, 720.0] if t_min >= 12.0 else [],
            scenes=scenes,
            hashtags=hashtags,
        )
        return audit_netflix_doc_plan(plan_obj.model_dump(), lang=clean_lang)

    # =========================================================================
    # PATH C: OFFLINE MOOD-ADAPTIVE FALLBACK (ONLY IF BOTH DEEPSEEK & GEMINI FAIL)
    # =========================================================================
    topic_source = "open_topic_synthesizer"
    mood = mood_hint
    off = _build_open_topic_offline_dossier(topic, clean_lang=clean_lang, mood=mood)
    base_narr = list(off["narr"])
    while len(base_narr) < n_scenes:
        idx_add = len(base_narr)
        tp = off["timeline_points"][idx_add % len(off["timeline_points"])]
        nd = off["board_nodes"][idx_add % len(off["board_nodes"])]
        base_narr.append(
            f"In {tp['date']}, archival chronicles linked {nd['title']} ({nd['role']}) to {tp['label']}."
            if is_en
            else f"Em {tp['date']}, as crônicas históricas conectaram {nd['title']} ({nd['role']}) a {tp['label']}."
        )

    scenes = []
    chapter_counter = 0
    chapter_step = max(2, len(base_narr) // min(4, max(2, len(base_narr) // 2)))
    broll_pool = off["broll_queries"]
    pip_pool = off["pip_queries"]
    photo_pool = off["photo_queries"]
    chap_subs = off["chapter_subtitles"]

    for idx, line_txt in enumerate(base_narr[:n_scenes]):
        vmode = _select_visual_mode_for_scene(idx, n_scenes)
        if vmode == "dark_map_route" and str(off["map_origin"]).strip().lower() == str(off["map_destination"]).strip().lower():
            vmode = "2d_schematic_over_realism"
        act_id, sc_cadence, sc_pi = _assign_act_metadata_for_index(idx, n_scenes)
        chap_card = None
        chap_sub = None
        if idx == 0:
            act_lbl = "COLD OPEN"
        elif idx == 1 or (idx >= 3 and (idx - 1) % chapter_step == 0 and chapter_counter < 4):
            roman = ROMAN_NUMERALS[min(chapter_counter, len(ROMAN_NUMERALS) - 1)]
            chap_card = _spaced_chapter_label(roman, lang=clean_lang)
            chap_sub = chap_subs[min(chapter_counter, len(chap_subs) - 1)]
            act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"
            chapter_counter += 1
        else:
            roman = ROMAN_NUMERALS[max(0, min(chapter_counter - 1, len(ROMAN_NUMERALS) - 1))]
            act_lbl = f"CAPÍTULO {roman}" if not is_en else f"CHAPTER {roman}"

        tp_cur = off["timeline_points"][idx % len(off["timeline_points"])]
        photo_q = photo_pool[idx % len(photo_pool)]
        lt_t_off = _normalize_upper(_clean_doc_text(f"{off['map_origin']} • {off['map_destination']} • {tp_cur['date']}"))
        lt_s_off = _normalize_upper(_clean_doc_text(f"{off['subtitle']} • {tp_cur['value']}"))
        bp_off = (
            f"Vertical full-bleed 9:16 dark atmospheric 35mm documentary still of {photo_q}, chiaroscuro lighting, no text"
            if ar == "9:16"
            else f"dark atmospheric 35mm documentary still of {photo_q}, chiaroscuro lighting, no text"
        )
        if mood in ("dark_horror", "epic_history"):
            bp_off = _enforce_historical_era_prompt_lock(bp_off, lt_t_off, lt_s_off)
        scenes.append(
            NetflixDocScene(
                scene_id=f"doc_sc_{idx + 1:02d}",
                act_id=act_id,
                act_label=act_lbl,
                chapter_card=chap_card,
                chapter_subtitle=chap_sub,
                visual_mode=vmode,
                visual_category=_resolve_visual_category(vmode, is_broll_shot=False),
                cut_cadence_s=sc_cadence,
                pattern_interrupt=sc_pi,
                mood=mood,
                narration=_clean_doc_text(line_txt),
                lower_third_title=lt_t_off,
                lower_third_subtitle=lt_s_off,
                highlight_color="#EAB308" if idx % 2 == 0 else "#D9381E",
                evidence_headline=_clean_doc_text(off["evidence_headline"]),
                evidence_quote=_clean_doc_text(off["evidence_quote"]),
                map_origin=_clean_doc_text(off["map_origin"]),
                map_destination=_clean_doc_text(off["map_destination"]),
                map_metric=_clean_doc_text(off["map_metric"]),
                timeline_points=[TimelinePoint(**pt) for pt in off["timeline_points"]],
                board_nodes=[BoardNode(**nd) for nd in off["board_nodes"]],
                image_prompt_en=bp_off,
                bespoke_image_prompt_en=bp_off,
                prefer_gemini_photo=(mood == "dark_horror"),
                broll_query_en=broll_pool[idx % len(broll_pool)],
                pip_broll_query_en=pip_pool[idx % len(pip_pool)],
                photo_query_en=photo_q,
                extra_photo_queries_en=[photo_pool[(idx + k) % len(photo_pool)] for k in range(4)],
                shot_prompts_en=[bp_off],
                transition_type=_select_transition_for_scene(idx, vmode, chap_card is not None),
            )
        )

    _ensure_topic_open_loops(scenes, mood=mood, clean_lang=clean_lang)
    plan_obj = NetflixDocPlan(
        title=off["title"],
        subtitle=off["subtitle"],
        channel_name=off["channel_name"],
        mood=mood,
        lang=clean_lang,
        aspect_ratio=ar,
        target_minutes=t_min,
        lut_file="02_dark_wealth.cube",
        voice_id=voice_id,
        caption_style=resolved_cap_style,
        thumbnail_hook=off["thumbnail_hook"],
        topic_source=topic_source,
        tokens_used=0,
        cost_usd=0.0,
        pattern_interrupt_times=[240.0, 480.0, 720.0] if t_min >= 12.0 else [],
        scenes=scenes,
        hashtags=["#documentario", "#historia", "#misterio", "#cinema"],
    )
    return audit_netflix_doc_plan(plan_obj.model_dump(), lang=clean_lang)


# Canonical alias referenced by v3.0.0 documentary pipeline spec
_plan_netflix_doc_script = generate_netflix_doc_plan


# ---------------------------------------------------------------------------
# 3. Narrator Voice Synthesizer per Scene (PT-BR & EN-US + Exact WordBoundary)
# ---------------------------------------------------------------------------
def _probe_wav_duration_s(wav_path: Path) -> float:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            sr = wf.getframerate()
            if sr > 0:
                return round(float(frames) / float(sr), 3)
    except Exception:
        pass
    try:
        return round(float(_probe_video_duration(wav_path)), 3)
    except Exception:
        return 0.0


def _is_valid_cached_scene_mp4(
    path: Path,
    expected_w: int,
    expected_h: int,
    expected_fps: int,
    expected_dur_s: float,
    tol_s: float = 0.22,
) -> bool:
    """Return True iff `path` is a complete, playable video matching target WxH, FPS, and duration."""
    if not path.exists() or path.stat().st_size < 16_384:
        return False
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            timeout=8,
        )
        info = json.loads(out)
        dur = float((info.get("format") or {}).get("duration") or 0.0)
        if dur <= 0.3 or abs(dur - float(expected_dur_s)) > tol_s:
            return False
        vstreams = [s for s in (info.get("streams") or []) if s.get("codec_type") == "video"]
        if not vstreams:
            return False
        vs = vstreams[0]
        if int(vs.get("width") or 0) != int(expected_w) or int(vs.get("height") or 0) != int(expected_h):
            return False
        rfr = str(vs.get("r_frame_rate") or "0/1")
        num, den = (rfr.split("/", 1) + ["1"])[:2]
        fps_actual = float(num) / max(1.0, float(den))
        if abs(fps_actual - float(expected_fps)) > 1.5:
            return False
        return True
    except Exception:
        return False


_GEMINI_VOICE_NAMES = {str(v.get("id") or "") for v in GEMINI_EXPRESSIVE_VOICES}

_DOC_ACTING_DIRECTIONS: Dict[str, Dict[str, str]] = {
    "dark_horror": {
        "pt": "Narre como um locutor humano de documentário viral sombrio da Netflix: voz grave, firme e magnética em português do Brasil natural, ritmo envolvente e dinâmico (cerca de 2,6 palavras por segundo), pausas curtas e naturais de respiração nas vírgulas, dicção cristalina — nunca lento, arrastado ou robótico.",
        "en": "Narrate like a human Netflix dark-history documentary host: deep, magnetic, cinematic voice, engaging brisk storytelling pace (~2.6 words per second), brief natural breaths at commas, crisp diction — never slow, sluggish, or robotic.",
    },
    "investigative_crime": {
        "pt": "Narre como um jornalista investigativo de documentário true-crime: voz firme, séria e humana em português do Brasil natural, ritmo envolvente e ágil (~2,6 palavras por segundo) com pausas curtas nas revelações, nunca lento ou arrastado.",
        "en": "Narrate like a prestige true-crime documentary host: grounded, tense, engaging pace (~2.6 words per second) with brief natural pauses on twists, crisp diction, never sluggish.",
    },
    "epic_history": {
        "pt": "Narre como um documentarista histórico de cinema: voz profunda, emotiva e cativante em português do Brasil natural, ritmo envolvente (~2,5 palavras por segundo) com respiração curta natural, nunca arrastado.",
        "en": "Narrate like an epic cinema documentary historian: rich, evocative, human voice with engaging brisk cadence (~2.5 words per second) and brief natural breaths.",
    },
    "corporate_thriller": {
        "pt": "Narre no estilo MagnatesMedia em português do Brasil: voz firme, inteligente e cinematográfica, ritmo dinâmico (~2,7 palavras por segundo) com micro-pausas estratégicas antes dos números e reviravoltas, 100% natural e humano.",
        "en": "Narrate in MagnatesMedia documentary thriller style: crisp, authoritative, dynamic storytelling pace (~2.7 words per second) with crisp pauses before twists.",
    },
}


_ACT_ACTING_FALLBACKS_PT: Dict[str, str] = {
    "ACT_0_COLD_OPEN_HOOK": "Gancho investigativo urgente e magnético (estilo Super Histórico / H2 History): pausas afiadas antes das revelações e entonação interrogativa ascendente-descendente genuína de provocação em qualquer pergunta '?'.",
    "ACT_1_WORLD_BUILDING": "Cronista histórico atmosférico de cinema (Super Histórico / H2 History): voz grave, ressonância profunda e autoridade narrativa serena (~138 WPM).",
    "ACT_2_DEEP_MECHANICS": "Ritmo investigativo tenso e forense: destaque claro em datas, decretos proibidos e conexões ocultas entre séculos (~142 WPM).",
    "ACT_3_CLIMAX_REVELATION": "Clímax dramático e revelação de alto impacto: momentum narrativo crescente e peso teatral nas viradas históricas (~146 WPM).",
    "ACT_4_ABRUPT_ENDING": "Reflexão filosófica final mais lenta (~110 WPM), profunda e assombrosa: sustente pausa dramática antes da pergunta final e termine '?' com verdadeira curva interrogativa de dúvida, nunca como afirmação plana.",
}


def _resolve_scene_acting_direction(act_id: str, mood: str, lang: str, text: str) -> str:
    """Resolve tailored 5-Act acting direction (delegating to `engine.gemini_tts.build_act_acting_direction` when present)."""
    if build_act_acting_direction is not None:
        try:
            got = build_act_acting_direction(act_id=act_id, mood=mood, lang=lang, text=text)
            if got and str(got).strip():
                return str(got).strip()
        except Exception:
            pass
    is_en = str(lang).lower().startswith("en")
    mood_dir = _DOC_ACTING_DIRECTIONS.get(str(mood or "dark_horror"), _DOC_ACTING_DIRECTIONS["dark_horror"])
    base = mood_dir["en" if is_en else "pt"]
    act_hint = _ACT_ACTING_FALLBACKS_PT.get(str(act_id or ""), "")
    if "?" in str(text or ""):
        q_rule = (
            " CRITICAL QUESTION PROSODY: Any sentence ending with '?' MUST use genuine rising-falling "
            "interrogative pitch contour of suspense and doubt — NEVER flatten '?' into a statement period."
        )
        return f"{base} {act_hint}{q_rule}".strip()
    return f"{base} {act_hint}".strip()


async def _synthesize_doc_scene_narration(
    text: str,
    voice_id: str,
    lang: str,
    work_dir: Path,
    tag: str,
    thermal_limit_c: float = 85.0,
    rate: str = "+0%",
    pitch: str = "-4Hz",
    resume: bool = False,
    reuse_existing_wav_if_no_words: bool = False,
    voice_engine: str = "auto",
    mood: str = "dark_horror",
    act_id: str = "ACT_1_WORLD_BUILDING",
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Synthesize natural human-acting cinema documentary narration (Gemini Expressive TTS primary,
    natural pause-preserving edge-tts fallback, checkpoint/resume aware).
    """
    raw_mp3 = work_dir / f"{tag}_raw.mp3"
    raw_wav = work_dir / f"{tag}_raw.wav"
    vad_wav = work_dir / f"{tag}_vad.wav"
    words_json = work_dir / f"{tag}_words.json"

    if resume and vad_wav.exists() and vad_wav.stat().st_size > 4096:
        cached_dur = _probe_wav_duration_s(vad_wav)
        if cached_dur > 0.3:
            if words_json.exists():
                try:
                    cached_words = json.loads(words_json.read_text(encoding="utf-8"))
                    if isinstance(cached_words, list):
                        return vad_wav, cached_words, cached_dur
                except Exception:
                    pass
            if reuse_existing_wav_if_no_words:
                est_words = _estimate_word_timestamps(text, cached_dur)
                return vad_wav, est_words, cached_dur

    spoken_text = normalize_narration_for_speech(text, lang=lang)
    is_en = str(lang).lower().startswith("en")
    eff_engine = str(voice_engine or "auto").strip().lower()
    if voice_id in _GEMINI_VOICE_NAMES and eff_engine in ("auto", "gemini_tts", "gemini"):
        eff_engine = "gemini_tts"

    # 1. PRIORITY 1: Google Gemini Native Expressive TTS (Real human breathing, emotion, pauses & diction!)
    gem_ok, gem_key = has_valid_gemini_key()
    if gem_ok and eff_engine in ("auto", "gemini_tts", "gemini"):
        default_gem_voice = {
            "dark_horror": "Charon",
            "epic_history": "Charon",
            "investigative_crime": "Orus",
            "corporate_thriller": "Fenrir",
        }.get(str(mood or "dark_horror"), "Charon")
        gem_voice = voice_id if voice_id in _GEMINI_VOICE_NAMES else default_gem_voice
        acting_dir = _resolve_scene_acting_direction(act_id=act_id, mood=str(mood or "dark_horror"), lang=lang, text=spoken_text)
        max_sane_dur = max(7.0, len(spoken_text.split()) * 0.68)
        for gem_try in range(2):
            try:
                await asyncio.to_thread(
                    synthesize_gemini_tts_line,
                    spoken_text,
                    raw_wav,
                    gem_voice,
                    acting_dir if gem_try == 0 else (acting_dir + " Speak briskly with zero long pauses."),
                    gem_key,
                    lang,
                    thermal_limit_c,
                )
                raw_dur = _probe_wav_duration_s(raw_wav)
                # Trim dead leading/trailing room-tone hiss AND cap >0.35s internal gaps cleanly
                out_wav, _, out_dur = await asyncio.to_thread(
                    trim_silence_vad,
                    raw_wav,
                    vad_wav,
                    [],
                    0.35,
                    0.10,
                    thermal_limit_c,
                    False,
                )
                had_hiss_tail_glitch = (raw_dur > out_dur * 1.85) and ((raw_dur - out_dur) > 8.0)
                min_sane_dur = max(1.6, len(spoken_text.split()) * 0.24)
                if (out_dur > max_sane_dur or had_hiss_tail_glitch or out_dur < min_sane_dur) and gem_try == 0:
                    print(
                        f"[NetflixDoc] Gemini TTS anomaly (raw={raw_dur:.1f}s, trim={out_dur:.1f}s, words={len(spoken_text.split())}) on {tag}, retrying cleanly...",
                        flush=True,
                    )
                    continue
                if out_dur > max_sane_dur * 1.45:
                    raise RuntimeError(f"Gemini TTS duration glitch ({out_dur:.1f}s for {len(spoken_text.split())} words)")
                if had_hiss_tail_glitch and out_dur < min_sane_dur * 1.15:
                    raise RuntimeError(f"Gemini TTS dropped tail words (raw={raw_dur:.1f}s, trim={out_dur:.1f}s)")
                aligned_words = await asyncio.to_thread(
                    align_script_words_to_audio,
                    out_wav,
                    text,
                    out_dur,
                    lang,
                )
                try:
                    words_json.write_text(json.dumps(aligned_words, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return out_wav, aligned_words, out_dur
            except Exception as exc:
                if gem_try == 0:
                    continue
                print(f"[NetflixDoc] Gemini Expressive TTS fallback -> edge-tts ({str(exc)[:110]})", flush=True)

    # 2. PRIORITY 2: Natural pause-preserving Edge-TTS (never rushed +8% unless explicitly desired)
    default_v = "en-US-AndrewMultilingualNeural" if is_en else "pt-BR-AntonioNeural"
    edge_voice_id = voice_id if (voice_id and "Neural" in voice_id) else default_v
    candidates = [edge_voice_id, default_v, "pt-BR-AntonioNeural", "en-US-AndrewMultilingualNeural"]
    # Keep documentary speech natural (avoid robotic fast-forward when default "+8%" came from viral shorts UI)
    eff_rate = "+0%" if str(rate or "").strip() in ("", "+8%", "+5%") else str(rate).strip()
    eff_pitch = "-4Hz" if str(pitch or "").strip() in ("", "+0Hz") else str(pitch).strip()

    for v_try in candidates:
        try:
            comm = edge_tts.Communicate(
                text=spoken_text,
                voice=v_try,
                rate=eff_rate,
                pitch=eff_pitch,
                boundary="WordBoundary",
            )
            words: List[Dict[str, Any]] = []
            chunks = bytearray()
            async for ch in comm.stream():
                if ch.get("type") == "audio":
                    chunks.extend(ch["data"])
                elif ch.get("type") == "WordBoundary":
                    st = float(ch["offset"]) / 10_000_000.0
                    dur = float(ch["duration"]) / 10_000_000.0
                    words.append({"word": str(ch["text"]).strip(), "start": round(st, 3), "end": round(st + max(0.06, dur), 3)})
            if chunks:
                raw_mp3.write_bytes(bytes(chunks))
                out_wav, trimmed_words, out_dur = trim_silence_vad(
                    raw_mp3,
                    vad_wav,
                    words,
                    max_pause_s=0.45,
                    consonant_pad_s=0.11,
                    thermal_limit_c=thermal_limit_c,
                    trim_edges_only=True,
                )
                try:
                    words_json.write_text(json.dumps(trimmed_words, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return out_wav, trimmed_words, out_dur
        except Exception:
            continue

    # Offline fallback via espeak-ng or pure-Python harmonic narration envelope
    try:
        _, words = _synthesize_espeak_fallback(spoken_text, raw_wav)
        out_wav, trimmed_words, out_dur = trim_silence_vad(raw_wav, vad_wav, words, thermal_limit_c=thermal_limit_c, trim_edges_only=True)
        try:
            words_json.write_text(json.dumps(trimmed_words, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return out_wav, trimmed_words, out_dur
    except Exception:
        import numpy as np

        words = _estimate_word_timestamps(text, max(2.4, min(9.0, len(text.split()) * 0.36)))
        dur_est = round((words[-1]["end"] + 0.18) if words else 3.0, 3)
        sr = 48000
        t_arr = np.linspace(0.0, dur_est, int(sr * dur_est), endpoint=False, dtype=np.float32)
        env = np.zeros_like(t_arr)
        for wd in words:
            mask = (t_arr >= wd["start"]) & (t_arr <= wd["end"])
            if np.any(mask):
                w_t = (t_arr[mask] - wd["start"]) / max(0.05, wd["end"] - wd["start"])
                env[mask] = np.sin(np.pi * w_t) * (0.7 + 0.3 * np.sin(2.0 * np.pi * 3.5 * w_t))
        f0 = 112.0
        sig = env * (
            0.60 * np.sin(2.0 * np.pi * f0 * t_arr)
            + 0.28 * np.sin(2.0 * np.pi * f0 * 2.0 * t_arr)
            + 0.12 * np.sin(2.0 * np.pi * f0 * 3.0 * t_arr)
        )
        pcm16 = np.clip(sig * 14000.0, -32000.0, 32000.0).astype(np.int16)
        stereo = np.column_stack([pcm16, pcm16])
        with wave.open(str(vad_wav), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(stereo.tobytes())
        try:
            words_json.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return vad_wav, words, dur_est


# ---------------------------------------------------------------------------
# 4. Real Media Scene Bundle + Video Backdrop, PiP Monitor & Photo Helpers
# ---------------------------------------------------------------------------
@dataclass
class SceneMediaAssets:
    primary_broll_mp4: Optional[Path] = None
    pip_broll_mp4: Optional[Path] = None
    primary_photo_path: Optional[Path] = None
    extra_photo_paths: List[Path] = field(default_factory=list)
    shot_sequence: List[Tuple[str, Path]] = field(default_factory=list)  # Ordered UNIQUE shots: [("photo"|"video", path), ...]


@dataclass
class LoadedSceneSkiaMedia:
    primary_photo: Optional[skia.Image] = None
    parallax_bg: Optional[skia.Image] = None
    parallax_fg: Optional[skia.Image] = None
    extra_photos: List[skia.Image] = field(default_factory=list)
    # Ordered UNIQUE visual layers matching assets.shot_sequence (ZERO modulo repetition!):
    # Each tuple is ("video_primary", None) | ("photo_25d", (bg_img, fg_img)) | ("photo_still", skia_img)
    shot_layers: List[Tuple[str, Any]] = field(default_factory=list)
    primary_photo_layer_idx: Optional[int] = None
    u2netp_separated: bool = False


def _draw_image_cover(
    canvas: skia.Canvas,
    img: skia.Image,
    dst_rect: skia.Rect,
    paint: Optional[skia.Paint] = None,
    y_bias: float = 0.5,
) -> None:
    """Draw `img` into `dst_rect` with aspect-cover cropping (ZERO stretching!).
    `y_bias` in [0.0, 1.0]: 0.5 = center crop, 0.15 = top-weighted crop (preserves heads/faces/horns).
    """
    iw = float(img.width())
    ih = float(img.height())
    dw = float(dst_rect.width())
    dh = float(dst_rect.height())
    if iw <= 0.0 or ih <= 0.0 or dw <= 0.0 or dh <= 0.0:
        return
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


def _load_skia_image_cover_biased(
    img_path: Path,
    target_w: int,
    target_h: int,
    y_bias: float = 0.16,
) -> Optional[skia.Image]:
    """Load an image with top-weighted aspect-cover crop into `(target_w, target_h)` so faces/heads/horns are never decapitated."""
    if img_path is None:
        return None
    p = Path(img_path)
    if not p.exists():
        return None
    tw = max(16, int(target_w))
    th = max(16, int(target_h))
    try:
        raw = skia.Image.open(str(p))
        if raw is not None and raw.width() > 0 and raw.height() > 0:
            surf = skia.Surface(tw, th)
            _draw_image_cover(surf.getCanvas(), raw, skia.Rect.MakeWH(tw, th), y_bias=y_bias)
            return surf.makeImageSnapshot()
    except Exception:
        pass
    return load_skia_image_cover(p, tw, th)


def _draw_obsidian_cinema_backdrop(canvas: skia.Canvas, w: int, h: int, t: float) -> None:
    """Emergency fallback backdrop only when no real video frame is available."""
    bg = skia.Paint()
    bg.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.5, h * 0.42),
            max(w, h) * 0.78,
            [skia.ColorSetARGB(255, 24, 20, 44), skia.ColorSetARGB(255, 11, 7, 19)],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), bg)

    grid_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=skia.ColorSetARGB(18, 179, 136, 255))
    step = 96
    ox = int((t * 14.0) % step)
    for x in range(-ox, w + step, step):
        canvas.drawLine(x, 0, x, h, grid_p)
    for y in range(0, h + step, step):
        canvas.drawLine(0, y, w, y, grid_p)


_MASTER_COLOR_GRADE_FILTER: Optional[skia.ColorFilter] = None
_CACHED_UNIFIER_PLATES: Dict[Tuple[int, int], List[skia.Image]] = {}
_FAST_SAMPLING = skia.SamplingOptions()


def _get_master_color_grade_filter() -> skia.ColorFilter:
    """Build & cache the v3.0.0 Visual Cohesion Unifier Stack C++ Skia ColorMatrix:
    contrast +12%, saturation -22%, shadows_tint #0D1B2A, highlights_tint #E0C097.
    Runs in C++ Skia uniformly on raw video & photo layers BEFORE UI overlays!
    """
    global _MASTER_COLOR_GRADE_FILTER
    if _MASTER_COLOR_GRADE_FILTER is None:
        c = 1.12       # +12% contrast
        s = 0.78       # -22% saturation
        rw, gw, bw = 0.2126, 0.7152, 0.0722
        inv_s = 1.0 - s
        hi_r, hi_g, hi_b = 1.045, 0.992, 0.915
        sh_r, sh_g, sh_b = 0.006, 0.013, 0.022
        off_c = 0.5 * (1.0 - c)
        mat = [
            c * hi_r * (rw * inv_s + s), c * hi_r * (gw * inv_s),     c * hi_r * (bw * inv_s),     0.0, off_c * hi_r + sh_r,
            c * hi_g * (rw * inv_s),     c * hi_g * (gw * inv_s + s), c * hi_g * (bw * inv_s),     0.0, off_c * hi_g + sh_g,
            c * hi_b * (rw * inv_s),     c * hi_b * (gw * inv_s),     c * hi_b * (bw * inv_s + s), 0.0, off_c * hi_b + sh_b,
            0.0,                         0.0,                         0.0,                         1.0, 0.0,
        ]
        _MASTER_COLOR_GRADE_FILTER = skia.ColorFilters.Matrix(mat)
    return _MASTER_COLOR_GRADE_FILTER


def _get_master_color_grade_paint() -> skia.Paint:
    p = skia.Paint(AntiAlias=True)
    p.setColorFilter(_get_master_color_grade_filter())
    return p


def _pregrade_skia_image(img: Optional[skia.Image]) -> Optional[skia.Image]:
    """Apply the v3.0.0 master_color_grade (+12% contrast, -22% sat, #0D1B2A/#E0C097) ONCE at image load time
    so per-frame 30fps drawing uses raw SIMD blits (`paint=None`, 0.0 ms color filter overhead!).
    """
    if img is None:
        return None
    try:
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return img
        info = skia.ImageInfo.Make(iw, ih, skia.ColorType.kBGRA_8888_ColorType, skia.AlphaType.kPremul_AlphaType)
        surf = skia.Surface(info)
        if surf is None:
            surf = skia.Surface(iw, ih)
        c = surf.getCanvas()
        c.clear(skia.ColorSetARGB(0, 0, 0, 0))
        c.drawImage(img, 0, 0, _LINEAR_SAMPLING, _get_master_color_grade_paint())
        return surf.makeImageSnapshot()
    except Exception:
        return img


def _get_combined_unifier_plate(
    frame_idx: int,
    vignette_intensity: float = 0.35,
    grain_opacity: float = 0.14,
) -> skia.Image:
    """Pre-bake 4 combined (vignette + 35mm film grain) plates at 480x270 once so the per-frame
    render loop applies BOTH vignette (0.35) and 35mm grain (0.14) in ONE single fast blit (~4 ms/frame)!
    """
    v_key = int(round(vignette_intensity * 100.0))
    g_key = int(round(grain_opacity * 100.0))
    cache_key = (v_key, g_key)
    plates = _CACHED_UNIFIER_PLATES.get(cache_key)
    if not plates:
        uw, uh = 480, 270
        yy, xx = np.mgrid[0:uh, 0:uw].astype(np.float32)
        dx = (xx - uw * 0.5) / (uw * 0.5)
        dy = (yy - uh * 0.48) / (uh * 0.5)
        r2 = np.clip((dx * dx + dy * dy) * 0.72, 0.0, 1.0)
        vig_a = (r2 ** 1.35) * float(vignette_intensity) * 185.0
        base_g_a = float(grain_opacity) * 95.0
        tot_a = np.clip(vig_a + base_g_a, 0.0, 225.0).astype(np.uint8)

        plates = []
        for seed in (20261122, 20261123, 20261124, 20261125):
            rng = np.random.default_rng(seed)
            grain = rng.normal(32.0, 26.0, size=(uh, uw)).clip(0.0, 96.0)
            # Blend dark slate-navy vignette (#0D1B2A) with monochrome 35mm grain in premultiplied BGRA
            g_weight = (base_g_a / np.maximum(1.0, tot_a.astype(np.float32)))
            b_val = (22.0 * (1.0 - g_weight) + grain * g_weight) * (tot_a.astype(np.float32) / 255.0)
            g_val = (15.0 * (1.0 - g_weight) + grain * g_weight) * (tot_a.astype(np.float32) / 255.0)
            r_val = (10.0 * (1.0 - g_weight) + grain * g_weight) * (tot_a.astype(np.float32) / 255.0)
            bgra = np.empty((uh, uw, 4), dtype=np.uint8)
            bgra[:, :, 0] = np.clip(b_val, 0, 255).astype(np.uint8)
            bgra[:, :, 1] = np.clip(g_val, 0, 255).astype(np.uint8)
            bgra[:, :, 2] = np.clip(r_val, 0, 255).astype(np.uint8)
            bgra[:, :, 3] = tot_a
            plates.append(
                skia.Image.fromarray(
                    np.ascontiguousarray(bgra),
                    colorType=skia.ColorType.kBGRA_8888_ColorType,
                    alphaType=skia.AlphaType.kPremul_AlphaType,
                )
            )
        _CACHED_UNIFIER_PLATES[cache_key] = plates
    return plates[frame_idx % len(plates)]


def _draw_visual_cohesion_unifier_overlay(
    canvas: skia.Canvas,
    w: int,
    h: int,
    frame_idx: int,
    t: float,
    vignette_intensity: float = 0.35,
    grain_opacity: float = 0.14,
    dust_opacity: float = 0.16,
) -> None:
    """Apply the v3.0.0 Visual Cohesion Unifier Stack in ONE fast combined SIMD blit (~3.5 ms/frame):
    vignette (0.35) + 35mm film grain (0.14) + subtle atmospheric dust motes (0.16).
    """
    if vignette_intensity > 0.01 or grain_opacity > 0.01:
        plate = _get_combined_unifier_plate(frame_idx, vignette_intensity=vignette_intensity, grain_opacity=grain_opacity)
        canvas.drawImageRect(
            plate,
            skia.Rect.MakeWH(plate.width(), plate.height()),
            skia.Rect.MakeWH(w, h),
            _FAST_SAMPLING,
            None,
            skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
        )

    if dust_opacity > 0.01:
        mote_alpha = int(max(12, min(140, round(dust_opacity * 255.0))))
        mote_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(mote_alpha, 224, 192, 151))
        for mi in range(10):
            mx_m = (mi * 197 + t * (19.0 + (mi % 4) * 6.5)) % w
            my_m = (mi * 131 - t * (11.0 + (mi % 3) * 4.5)) % h
            canvas.drawCircle(mx_m, my_m, 1.5 + (mi % 3) * 0.85, mote_p)


def _draw_video_backdrop_layer(
    canvas: skia.Canvas,
    w: int,
    h: int,
    video_frame: Optional[skia.Image],
    t: float,
    prog: float,
    scrim_alpha: int = 160,
    ken_burns_zoom: float = 0.055,
    show_grid: bool = False,
    show_dust: bool = True,
    apply_master_grade: bool = True,
) -> None:
    """Draw REAL MOVING HD B-ROLL VIDEO across the full canvas with unified v3.0.0 master_color_grade,
    subtle Ken Burns motion & fast flat scrim (vignette handled by `_draw_visual_cohesion_unifier_overlay`)."""
    if video_frame is not None:
        zoom = 1.0 + ken_burns_zoom * prog
        pan_x = (prog - 0.5) * -22.0
        canvas.save()
        canvas.clipRect(skia.Rect.MakeWH(w, h))
        canvas.translate(w * 0.5 + pan_x, h * 0.5)
        canvas.scale(zoom, zoom)
        dst = skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h)
        grade_paint = _get_master_color_grade_paint() if apply_master_grade else None
        canvas.drawImageRect(
            video_frame,
            skia.Rect.MakeWH(video_frame.width(), video_frame.height()),
            dst,
            _FAST_SAMPLING,
            grade_paint,
            skia.Canvas.SrcRectConstraint.kFast_SrcRectConstraint,
        )
        canvas.restore()

        if scrim_alpha > 0:
            canvas.drawRect(
                skia.Rect.MakeWH(w, h),
                skia.Paint(Color=skia.ColorSetARGB(max(0, min(235, scrim_alpha)), 11, 15, 23)),
            )
    else:
        _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    if show_grid:
        grid_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.0,
            Color=skia.ColorSetARGB(16, 224, 192, 151),
        )
        step = 96
        ox = int((t * 14.0) % step)
        for x in range(-ox, w + step, step):
            canvas.drawLine(x, 0, x, h, grid_p)
        for y in range(0, h + step, step):
            canvas.drawLine(0, y, w, y, grid_p)

    if show_dust:
        dust_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(40, 224, 192, 151))
        for i in range(10):
            dx = (i * 193 + t * (16 + (i % 5) * 5)) % w
            dy = (i * 137 - t * (10 + (i % 4) * 4)) % h
            rad = 1.6 + (i % 3) * 0.9
            canvas.drawCircle(dx, dy, rad, dust_p)


def _draw_monochrome_sepia_photo(
    canvas: skia.Canvas,
    img: skia.Image,
    rect: skia.Rect,
    radius: float = 6.0,
    halftone_lines: bool = True,
    y_bias: float = 0.15,
) -> None:
    """Draw a real photograph in authentic high-contrast monochrome/sepia newspaper halftone print style."""
    # High-contrast warm archival newsprint monochrome/sepia 4x5 color matrix
    sepia_matrix = [
        0.36, 0.70, 0.14, 0.0, -0.06,
        0.34, 0.66, 0.13, 0.0, -0.07,
        0.29, 0.56, 0.11, 0.0, -0.08,
        0.00, 0.00, 0.00, 1.0,  0.00,
    ]
    photo_paint = skia.Paint(AntiAlias=True)
    photo_paint.setColorFilter(skia.ColorFilters.Matrix(sepia_matrix))

    canvas.save()
    rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    canvas.clipRRect(rrect, doAntiAlias=True)
    _draw_image_cover(canvas, img, rect, paint=photo_paint, y_bias=y_bias)

    # Subtle newsprint halftone horizontal print grain
    if halftone_lines:
        ht_p = skia.Paint(Color=skia.ColorSetARGB(24, 24, 18, 12))
        y_start = int(rect.top())
        y_end = int(rect.bottom())
        for sy in range(y_start, y_end, 4):
            canvas.drawLine(rect.left(), sy, rect.right(), sy, ht_p)

    # Subtle aged newsprint corner vignette
    vig = skia.Paint()
    vig.setShader(
        skia.GradientShader.MakeRadial(
            (rect.centerX(), rect.centerY()),
            max(rect.width(), rect.height()) * 0.68,
            [skia.ColorSetARGB(0, 20, 14, 8), skia.ColorSetARGB(65, 20, 14, 8)],
        )
    )
    canvas.drawRect(rect, vig)
    canvas.restore()

    # Crisp double black archival print border
    ink_outer = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=skia.ColorSetARGB(230, 28, 22, 30))
    canvas.drawRRect(rrect, ink_outer)


def _draw_pip_forensic_monitor(
    canvas: skia.Canvas,
    pip_frame: Optional[skia.Image],
    cx: float,
    cy: float,
    pip_w: float,
    pip_h: float,
    tilt_deg: float,
    border_hex: str,
    badge_text: str,
    caption_text: str,
    body_t: float,
    t: float,
    ui_tf: skia.Typeface,
    enter_delay: float = 0.06,
) -> None:
    """Render Netflix / MagnatesMedia Video-over-Video Picture-in-Picture Forensic Broadcast Monitor.

    Features:
      - 16px rounded frame with subtle tilt (-2° / +2°)
      - Heavy dark drop shadow + glowing #FF2E93 / #FFD166 border
      - Real moving second HD video inside clipped frame
      - Subtle horizontal broadcast scanlines + corner viewfinder brackets
      - Blinking vector red dot + 'REC • ARQUIVO DE VÍDEO' top badge (zero missing glyphs!)
      - Smooth `_ease_out_back` spring entrance
    """
    if pip_frame is None:
        return

    ent_raw = max(0.0, min(1.0, (body_t - enter_delay) / 0.42))
    spring = _ease_out_back(ent_raw)
    alpha_f = _ease_out_cubic(min(1.0, ent_raw * 1.45))
    if alpha_f <= 0.02:
        return

    sc = 0.78 + 0.22 * spring
    y_lift = (1.0 - min(1.0, spring)) * 34.0 + math.sin(t * 1.6) * 2.8

    canvas.save()
    canvas.translate(cx, cy + y_lift)
    canvas.rotate(tilt_deg)
    canvas.scale(sc, sc)

    rect = skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, pip_h)
    rrect = skia.RRect.MakeRectXY(rect, 16.0, 16.0)

    # 1. Heavy cinema drop shadow + subtle outer accent glow
    shadow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(245 * alpha_f), 8, 6, 16))
    shadow_p.setImageFilter(skia.ImageFilters.DropShadow(0, 22, 42, 42, skia.ColorSetARGB(int(230 * alpha_f), 0, 0, 0)))
    canvas.drawRRect(rrect, shadow_p)

    halo_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=8.0,
        Color=hex_to_skia(border_hex, int(95 * alpha_f)),
    )
    halo_p.setImageFilter(skia.ImageFilters.Blur(7, 7))
    canvas.drawRRect(rrect, halo_p)

    # 2. Clipped interior: Real moving second video + subtle broadcast scanlines + HUD
    canvas.save()
    canvas.clipRRect(rrect, doAntiAlias=True)

    vid_paint = skia.Paint(AntiAlias=True)
    vid_paint.setAlphaf(alpha_f)
    canvas.drawImageRect(pip_frame, rect, _LINEAR_SAMPLING, vid_paint)

    # Subtle top & bottom broadcast legibility gradients
    top_grad = skia.Paint()
    top_grad.setShader(
        skia.GradientShader.MakeLinear(
            [(0, -pip_h * 0.5), (0, -pip_h * 0.5 + 72.0)],
            [skia.ColorSetARGB(int(175 * alpha_f), 9, 6, 18), skia.ColorSetARGB(0, 9, 6, 18)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, -pip_h * 0.5, pip_w, 72.0), top_grad)

    bot_grad = skia.Paint()
    bot_grad.setShader(
        skia.GradientShader.MakeLinear(
            [(0, pip_h * 0.5 - 64.0), (0, pip_h * 0.5)],
            [skia.ColorSetARGB(0, 9, 6, 18), skia.ColorSetARGB(int(195 * alpha_f), 9, 6, 18)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(-pip_w * 0.5, pip_h * 0.5 - 64.0, pip_w, 64.0), bot_grad)

    # Subtle CRT/broadcast horizontal scanlines
    scan_p = skia.Paint(Color=skia.ColorSetARGB(int(26 * alpha_f), 0, 0, 0))
    for sy in range(int(-pip_h * 0.5), int(pip_h * 0.5), 4):
        canvas.drawLine(-pip_w * 0.5, sy, pip_w * 0.5, sy, scan_p)

    # Inner tactical corner brackets
    brk_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=2.5,
        Color=hex_to_skia(border_hex, int(190 * alpha_f)),
    )
    blen = min(24.0, pip_w * 0.06)
    for sx_c in (-1, 1):
        for sy_c in (-1, 1):
            bx_c = sx_c * (pip_w * 0.5 - 12.0)
            by_c = sy_c * (pip_h * 0.5 - 12.0)
            canvas.drawLine(bx_c, by_c, bx_c - sx_c * blen, by_c, brk_p)
            canvas.drawLine(bx_c, by_c, bx_c, by_c - sy_c * blen, brk_p)

    # Blinking red dot (vector circle — NEVER Unicode '●'!) + 'REC • ARQUIVO DE VÍDEO' pill
    badge_clean = _sanitize_glyphs(badge_text.upper(), typeface=ui_tf)
    b_font, b_lns = _wrap_text_to_width(badge_clean, ui_tf, 16.0, 12.0, pip_w - 76.0, 1)
    b_str = b_lns[0] if b_lns else "REC • ARQUIVO DE VÍDEO"
    bw = float(b_font.measureText(b_str))
    pill_w = min(pip_w - 32.0, bw + 44.0)
    pill_h = 30.0
    pill_x = -pip_w * 0.5 + 16.0
    pill_y = -pip_h * 0.5 + 14.0
    pill_r = skia.Rect.MakeXYWH(pill_x, pill_y, pill_w, pill_h)
    canvas.drawRoundRect(pill_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(210 * alpha_f), 11, 7, 19)))
    canvas.drawRoundRect(
        pill_r,
        8.0,
        8.0,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.4, Color=hex_to_skia(border_hex, int(180 * alpha_f))),
    )

    blink = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(t * 7.5))
    dot_cx = pill_x + 15.0
    dot_cy = pill_y + pill_h * 0.5
    dot_glow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(180 * blink * alpha_f), 255, 38, 78))
    dot_glow.setImageFilter(skia.ImageFilters.Blur(4, 4))
    canvas.drawCircle(dot_cx, dot_cy, 7.5, dot_glow)
    canvas.drawCircle(dot_cx, dot_cy, 5.2, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(255 * blink * alpha_f), 255, 42, 82)))

    _draw_safe_string(
        canvas,
        b_str,
        pill_x + 28.0,
        pill_y + 20.5,
        b_font,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(250 * alpha_f), 255, 255, 255)),
    )

    # Bottom forensic timecode + caption tag
    tc_min = int(t // 60)
    tc_sec = int(t % 60)
    tc_frm = int((t - int(t)) * 30)
    tc_str = f"CAM-02 • {tc_min:02d}:{tc_sec:02d}:{tc_frm:02d}"
    bot_label = f"{_sanitize_glyphs(caption_text.upper(), typeface=ui_tf)}  •  {tc_str}"
    c_font, c_lns = _wrap_text_to_width(bot_label, ui_tf, 15.0, 11.5, pip_w - 36.0, 1)
    if c_lns:
        _draw_safe_string(
            canvas,
            c_lns[0],
            -pip_w * 0.5 + 18.0,
            pip_h * 0.5 - 16.0,
            c_font,
            skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", int(240 * alpha_f))),
        )

    canvas.restore()

    # 3. Crisp glowing border stroke
    border_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=3.5,
        Color=hex_to_skia(border_hex, int(245 * alpha_f)),
    )
    canvas.drawRRect(rrect, border_p)
    canvas.restore()


# ---------------------------------------------------------------------------
# 5. The 7 Investigative Skia C++ Visual Mode Renderers (Real Video + PiP + Photos)
# ---------------------------------------------------------------------------
def _draw_mode_broll_video_pip(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Mode 1 (Cold Open / Narrative Momentum): Full-bleed crisp real HD video + Video-over-Video PiP monitor + glassmorphic dossier."""
    # Crisp, vivid moving HD B-roll video (subtle cinema vignette, NOT flat dark grid!)
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=58,
        ken_burns_zoom=0.07,
        show_grid=False,
        show_dust=True,
    )

    is_wide = w >= h
    rec_badge = "REC • VIDEO ARCHIVE" if is_en else "REC • ARQUIVO DE VÍDEO"
    mood = str(getattr(scene, "mood", "corporate_thriller") or "corporate_thriller")
    if mood == "dark_horror":
        dossier_badge = f"DARK ARCHIVE • {scene.act_label}" if is_en else f"ARQUIVO SOMBRIO • {scene.act_label}"
    elif mood == "epic_history":
        dossier_badge = f"HISTORICAL ARCHIVE • {scene.act_label}" if is_en else f"ARQUIVO HISTÓRICO • {scene.act_label}"
    elif mood == "investigative_crime":
        dossier_badge = f"CASE FILE • {scene.act_label}" if is_en else f"DOSSIÊ CRIMINAL • {scene.act_label}"
    else:
        dossier_badge = f"CLASSIFIED FILE • {scene.act_label}" if is_en else f"DOSSIÊ CONFIDENCIAL • {scene.act_label}"

    if is_wide:
        # Left glassmorphic editorial dossier panel (clearly shows moving video behind & around it)
        ent = _ease_out_cubic(min(1.0, body_t / 0.40))
        card_w = 770.0
        card_h = 560.0
        cx_left = 72.0 - (1.0 - ent) * 42.0
        cy_top = 112.0

        c_rect = skia.Rect.MakeXYWH(cx_left, cy_top, card_w, card_h)
        c_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(186, 12, 9, 24))
        c_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 36, 36, skia.ColorSetARGB(200, 0, 0, 0)))
        canvas.drawRoundRect(c_rect, 20.0, 20.0, c_bg)
        canvas.drawRoundRect(
            c_rect,
            20.0,
            20.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#FFD166", 190)),
        )
        # Left accent vertical bar
        canvas.drawRoundRect(
            skia.Rect.MakeXYWH(cx_left, cy_top + 24.0, 8.0, card_h - 48.0),
            4.0,
            4.0,
            skia.Paint(AntiAlias=True, Color=hex_to_skia(scene.highlight_color)),
        )

        # Classification badge
        b_font, b_lns = _wrap_text_to_width(dossier_badge, ui_tf, 20.0, 15.0, card_w - 72.0, 1)
        if b_lns:
            _draw_safe_string(canvas, b_lns[0], cx_left + 34.0, cy_top + 48.0, b_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

        # Big golden metric
        m_font, m_lns = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 54.0, 30.0, card_w - 68.0, 2)
        my = cy_top + 114.0
        for ln in m_lns:
            _draw_safe_string(canvas, ln, cx_left + 34.0, my, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            my += m_font.getSize() * 1.16

        # Sharp headline
        h_font, h_lns = _wrap_text_to_width(scene.evidence_headline.upper(), ui_tf, 24.0, 17.0, card_w - 68.0, 2)
        hy = max(my + 8.0, cy_top + 204.0)
        for ln in h_lns:
            _draw_safe_string(canvas, ln, cx_left + 34.0, hy, h_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            hy += h_font.getSize() * 1.24

        # Embedded real archival photo inset inside bottom half of dossier card
        photo_top = max(hy + 14.0, cy_top + 278.0)
        photo_h = max(130.0, (cy_top + card_h - 24.0) - photo_top)
        photo_rect = skia.Rect.MakeXYWH(cx_left + 34.0, photo_top, card_w - 68.0, photo_h)
        if media.primary_photo is not None:
            canvas.save()
            prr = skia.RRect.MakeRectXY(photo_rect, 12.0, 12.0)
            canvas.clipRRect(prr, doAntiAlias=True)
            canvas.drawImageRect(media.primary_photo, photo_rect, _LINEAR_SAMPLING)
            # Subtle bottom label bar over archival photo
            bar_r = skia.Rect.MakeXYWH(photo_rect.left(), photo_rect.bottom() - 36.0, photo_rect.width(), 36.0)
            canvas.drawRect(bar_r, skia.Paint(Color=skia.ColorSetARGB(190, 11, 7, 19)))
            cap_txt = f"{scene.map_origin.upper()} • {scene.map_destination.upper()}"
            cf, cl = _wrap_text_to_width(cap_txt, ui_tf, 16.0, 12.0, photo_rect.width() - 24.0, 1)
            if cl:
                _draw_safe_string(canvas, cl[0], photo_rect.left() + 14.0, photo_rect.bottom() - 12.0, cf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            canvas.restore()
            canvas.drawRRect(prr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#FFD166", 190)))

        # Right side: Large Video-over-Video (PiP) Forensic Broadcast Monitor
        _draw_pip_forensic_monitor(
            canvas=canvas,
            pip_frame=pip_frame or primary_frame,
            cx=w * 0.725,
            cy=h * 0.39,
            pip_w=780.0,
            pip_h=440.0,
            tilt_deg=-2.0,
            border_hex="#FF2E93",
            badge_text=rec_badge,
            caption_text=f"{scene.map_origin} • {scene.map_destination}",
            body_t=body_t,
            t=t,
            ui_tf=ui_tf,
        )
    else:
        # 9:16 Vertical Doc layout
        _draw_pip_forensic_monitor(
            canvas=canvas,
            pip_frame=pip_frame or primary_frame,
            cx=w * 0.50,
            cy=h * 0.28,
            pip_w=w * 0.84,
            pip_h=w * 0.84 * 0.5625,
            tilt_deg=-1.8,
            border_hex="#FF2E93",
            badge_text=rec_badge,
            caption_text=f"{scene.map_origin} • {scene.map_destination}",
            body_t=body_t,
            t=t,
            ui_tf=ui_tf,
        )
        card_w = w - 120.0
        card_h = 420.0
        c_rect = skia.Rect.MakeXYWH(60.0, h * 0.48, card_w, card_h)
        canvas.drawRoundRect(c_rect, 20.0, 20.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 12, 9, 24)))
        canvas.drawRoundRect(
            c_rect,
            20.0,
            20.0,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#FFD166")),
        )
        m_font, m_lns = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 46.0, 28.0, card_w - 64.0, 2)
        my = h * 0.48 + 76.0
        for ln in m_lns:
            _draw_safe_string(canvas, ln, 92.0, my, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            my += m_font.getSize() * 1.15
        if media.primary_photo is not None:
            pr = skia.Rect.MakeXYWH(92.0, my + 12.0, card_w - 64.0, max(120.0, (h * 0.48 + card_h - 28.0) - (my + 12.0)))
            prr = skia.RRect.MakeRectXY(pr, 12.0, 12.0)
            canvas.save()
            canvas.clipRRect(prr, doAntiAlias=True)
            canvas.drawImageRect(media.primary_photo, pr, _LINEAR_SAMPLING)
            canvas.restore()
            canvas.drawRRect(prr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#FFD166")))


def _draw_mode_video_pip_evidence(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Mode 7: Split-Screen Video + Dossier (Left 54% crisp moving real B-roll w/ Ken Burns + PiP monitor, Right 46% glassmorphic evidence card + real archival photo)."""
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=172,
        ken_burns_zoom=0.04,
        show_grid=True,
        show_dust=True,
    )

    is_wide = w >= h
    rec_badge = "REC • VIDEO ARCHIVE" if is_en else "REC • ARQUIVO DE VÍDEO"
    main_cam_lbl = "LIVE ARCHIVE FEED" if is_en else "ARQUIVO PRINCIPAL"

    if is_wide:
        margin_x = 56.0
        top_y = 54.0
        panel_h = 682.0
        total_w = w - margin_x * 2.0
        gap = 28.0
        left_w = (total_w - gap) * 0.54
        right_w = (total_w - gap) * 0.46

        # LEFT 54%: Crisp Moving Real B-Roll Video Viewport with Ken Burns pan
        left_r = skia.Rect.MakeXYWH(margin_x, top_y, left_w, panel_h)
        left_rr = skia.RRect.MakeRectXY(left_r, 18.0, 18.0)
        vp_shadow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 8, 6, 16))
        vp_shadow.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 34, 34, skia.ColorSetARGB(210, 0, 0, 0)))
        canvas.drawRRect(left_rr, vp_shadow)

        canvas.save()
        canvas.clipRRect(left_rr, doAntiAlias=True)
        if primary_frame is not None:
            kb_zoom = 1.05 + 0.08 * prog
            kb_pan_x = (prog - 0.5) * -34.0
            canvas.save()
            canvas.translate(left_r.centerX() + kb_pan_x, left_r.centerY())
            canvas.scale(kb_zoom, kb_zoom)
            canvas.drawImageRect(
                primary_frame,
                skia.Rect.MakeXYWH(-left_w * 0.5, -panel_h * 0.5, left_w, panel_h),
                _LINEAR_SAMPLING,
            )
            canvas.restore()

        # Subtle cinema scanlines + top-left live badge
        top_scrim = skia.Paint()
        top_scrim.setShader(
            skia.GradientShader.MakeLinear(
                [(0, top_y), (0, top_y + 84.0)],
                [skia.ColorSetARGB(175, 8, 6, 16), skia.ColorSetARGB(0, 8, 6, 16)],
            )
        )
        canvas.drawRect(skia.Rect.MakeXYWH(margin_x, top_y, left_w, 84.0), top_scrim)

        # Blinking red dot + MAIN CAM label
        blink = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 7.0))
        pill_r = skia.Rect.MakeXYWH(margin_x + 20.0, top_y + 18.0, 270.0, 34.0)
        canvas.drawRoundRect(pill_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(210, 11, 7, 19)))
        canvas.drawCircle(margin_x + 38.0, top_y + 35.0, 5.5, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(255 * blink), 255, 42, 82)))
        bf = skia.Font(ui_tf, 16.0)
        _draw_safe_string(canvas, f"REC • {main_cam_lbl}", margin_x + 52.0, top_y + 41.0, bf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        canvas.restore()
        canvas.drawRRect(left_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166", 220)))

        # Video-over-Video PiP inset anchored in bottom-right of left video panel
        _draw_pip_forensic_monitor(
            canvas=canvas,
            pip_frame=pip_frame,
            cx=margin_x + left_w - 220.0,
            cy=top_y + panel_h - 142.0,
            pip_w=390.0,
            pip_h=220.0,
            tilt_deg=2.0,
            border_hex="#FF2E93",
            badge_text=rec_badge,
            caption_text=scene.map_destination,
            body_t=body_t,
            t=t,
            ui_tf=ui_tf,
        )

        # RIGHT 46%: Glassmorphic Evidence Card + Real Archival Photograph
        right_x = margin_x + left_w + gap
        right_r = skia.Rect.MakeXYWH(right_x, top_y, right_w, panel_h)
        right_rr = skia.RRect.MakeRectXY(right_r, 18.0, 18.0)
        rc_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(212, 14, 11, 28))
        rc_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 34, 34, skia.ColorSetARGB(205, 0, 0, 0)))
        canvas.drawRRect(right_rr, rc_bg)
        canvas.drawRRect(
            right_rr,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#FF2E93", 205)),
        )

        # Top real archival photo inside right glassmorphic card
        pad = 28.0
        photo_h = 290.0
        pr = skia.Rect.MakeXYWH(right_x + pad, top_y + pad, right_w - pad * 2.0, photo_h)
        prr = skia.RRect.MakeRectXY(pr, 12.0, 12.0)
        if media.primary_photo is not None:
            canvas.save()
            canvas.clipRRect(prr, doAntiAlias=True)
            canvas.drawImageRect(media.primary_photo, pr, _LINEAR_SAMPLING)
            canvas.restore()
            canvas.drawRRect(prr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#FFD166", 200)))

        # Evidence metadata & quote below photo
        ty = top_y + pad + photo_h + 36.0
        tag_str = f"EVIDÊNCIA FOTOGRÁFICA • {scene.act_label}" if not is_en else f"ARCHIVAL EVIDENCE • {scene.act_label}"
        tf_b, tl_b = _wrap_text_to_width(tag_str, ui_tf, 18.0, 14.0, right_w - pad * 2.0, 1)
        if tl_b:
            _draw_safe_string(canvas, tl_b[0], right_x + pad, ty, tf_b, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

        mf, ml = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 42.0, 26.0, right_w - pad * 2.0, 2)
        my = ty + 48.0
        for ln in ml:
            _draw_safe_string(canvas, ln, right_x + pad, my, mf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            my += mf.getSize() * 1.15

        qf, ql = _wrap_text_to_width(scene.evidence_quote, ui_tf, 23.0, 16.0, right_w - pad * 2.0, 4)
        qy = my + 12.0
        for ln in ql:
            if qy > top_y + panel_h - 24.0:
                break
            _draw_safe_string(canvas, ln, right_x + pad, qy, qf, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235, 232, 228, 246)))
            qy += qf.getSize() * 1.32
    else:
        # 9:16 Stacked Split-Screen: Top video + PiP, Bottom glassmorphic evidence card + photo
        pad = 54.0
        vw = w - pad * 2.0
        vh = 560.0
        vr = skia.Rect.MakeXYWH(pad, 200.0, vw, vh)
        vrr = skia.RRect.MakeRectXY(vr, 18.0, 18.0)
        canvas.save()
        canvas.clipRRect(vrr, doAntiAlias=True)
        if primary_frame is not None:
            canvas.drawImageRect(primary_frame, vr, _LINEAR_SAMPLING)
        canvas.restore()
        canvas.drawRRect(vrr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166")))
        _draw_pip_forensic_monitor(
            canvas=canvas,
            pip_frame=pip_frame,
            cx=w - pad - 210.0,
            cy=200.0 + vh - 125.0,
            pip_w=360.0,
            pip_h=202.0,
            tilt_deg=2.0,
            border_hex="#FF2E93",
            badge_text=rec_badge,
            caption_text=scene.map_destination,
            body_t=body_t,
            t=t,
            ui_tf=ui_tf,
        )
        cr = skia.Rect.MakeXYWH(pad, 790.0, vw, 640.0)
        canvas.drawRoundRect(cr, 18.0, 18.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 14, 11, 28)))
        canvas.drawRoundRect(cr, 18.0, 18.0, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#FF2E93")))
        if media.primary_photo is not None:
            pr = skia.Rect.MakeXYWH(pad + 28.0, 818.0, vw - 56.0, 310.0)
            prr = skia.RRect.MakeRectXY(pr, 12.0, 12.0)
            canvas.save()
            canvas.clipRRect(prr, doAntiAlias=True)
            canvas.drawImageRect(media.primary_photo, pr, _LINEAR_SAMPLING)
            canvas.restore()
        mf, ml = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 40.0, 26.0, vw - 56.0, 1)
        if ml:
            _draw_safe_string(canvas, ml[0], pad + 28.0, 1184.0, mf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
        qf, ql = _wrap_text_to_width(scene.evidence_quote, ui_tf, 24.0, 17.0, vw - 56.0, 4)
        qy = 1236.0
        for ln in ql:
            _draw_safe_string(canvas, ln, pad + 28.0, qy, qf, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            qy += qf.getSize() * 1.32


try:
    from engine.pro_motion_graphics import extract_depth_stamp_text as _pro_extract_depth_stamp_text
except Exception:
    _pro_extract_depth_stamp_text = None  # type: ignore

_CACHED_FALLBACK_TITLE_TF: Optional[skia.Typeface] = None

_PT_ORDINAL_TO_ROMAN: Dict[str, str] = {
    "PRIMEIRO": "I",
    "SEGUNDO": "II",
    "TERCEIRO": "III",
    "QUARTO": "IV",
    "QUINTO": "V",
    "SEXTO": "VI",
    "SÉTIMO": "VII",
    "SETIMO": "VII",
    "OITAVO": "VIII",
    "NONO": "IX",
    "DÉCIMO": "X",
    "DECIMO": "X",
    "ONZE": "XI",
    "DOZE": "XII",
    "TREZE": "XIII",
    "QUATORZE": "XIV",
    "CATORZE": "XIV",
    "QUINZE": "XV",
    "DEZESSEIS": "XVI",
    "DEZESSETE": "XVII",
    "DEZOITO": "XVIII",
    "DEZENOVE": "XIX",
    "VINTE": "XX",
}


def _extract_depth_stamp_text(scene: Optional[NetflixDocScene]) -> str:
    """Extract a crisp 1-2 word stamp (year like '336 d.C.', '1647', 'SÉC. IV' or key entity from `scene.lower_third_title`)
    for rendering behind the 2.5D foreground subject.
    """
    if _pro_extract_depth_stamp_text is not None and scene is not None:
        try:
            st = str(_pro_extract_depth_stamp_text(scene) or "").strip()
            if st:
                return st
        except Exception:
            pass
    if scene is None:
        return "ARQUIVO"
    lt = _normalize_upper(str(getattr(scene, "lower_third_title", "") or "")).strip()
    sub = _normalize_upper(str(getattr(scene, "lower_third_subtitle", "") or "")).strip()
    combined = f"{lt} • {sub}"

    # 1. Explicit year with era suffix (e.g. '336 D.C.', '217 A.C.')
    m_era = re.search(r"\b(\d{1,4}\s*(?:D\.?\s*C\.?|A\.?\s*C\.?|B\.?\s*C\.?|A\.?\s*D\.?))\b", combined)
    if m_era:
        raw_era = re.sub(r"\s+", " ", m_era.group(1).strip())
        raw_era = re.sub(r"D\.?\s*C\.?$", "d.C.", raw_era)
        raw_era = re.sub(r"A\.?\s*C\.?$", "a.C.", raw_era)
        return raw_era

    # 2. Roman century stamp (e.g. 'SÉC. IV', 'SÉCULO XI')
    m_sec_rom = re.search(r"\bS[ÉE]C(?:ULO|\.)?\s+([IVXLCDM]{1,5})\b", combined)
    if m_sec_rom:
        return f"SÉC. {m_sec_rom.group(1)}"

    # 3. Spelled-out Portuguese century in lower-third (e.g. 'SÉCULO QUARTO' -> 'SÉC. IV')
    m_sec_pt = re.search(
        r"\bS[ÉE]C(?:ULO|\.)?\s+(PRIMEIRO|SEGUNDO|TERCEIRO|QUARTO|QUINTO|SEXTO|S[ÉE]TIMO|OITAVO|NONO|D[ÉE]CIMO|ONZE|DOZE|TREZE|QUATORZE|CATORZE|QUINZE|DEZESSEIS|DEZESSETE|DEZOITO|DEZENOVE|VINTE)\b",
        combined,
    )
    if m_sec_pt:
        rom = _PT_ORDINAL_TO_ROMAN.get(m_sec_pt.group(1), m_sec_pt.group(1))
        return f"SÉC. {rom}"

    # 4. 3 or 4 digit historical year (e.g. '1647', '1995', '336')
    m_yr = re.search(r"\b(1\d{3}|20\d{2}|[2-9]\d{2})\b", combined)
    if m_yr:
        return m_yr.group(1)

    # 5. Crisp 1-2 word key entity or location from lower_third_title
    parts = [p.strip() for p in re.split(r"[•\-|]", lt) if p.strip()]
    if parts:
        for cand in reversed(parts):
            words = cand.split()
            if 1 <= len(words) <= 2 and len(cand) <= 16:
                return cand
        return " ".join(parts[0].split()[:2])[:16]
    return "ARQUIVO"


def _draw_fallback_depth_title_behind_subject(
    canvas: skia.Canvas,
    w: int,
    h: int,
    text: str,
    shot_prog: float,
    t: float,
    title_tf: skia.Typeface,
    mood: str = "dark_horror",
) -> None:
    """Built-in fallback 3D Depth Title rendered BETWEEN bg_img and fg_img when pro_motion_graphics is not yet merged."""
    stamp = _sanitize_glyphs(str(text or "").strip().upper(), typeface=title_tf)
    if not stamp:
        return
    is_wide = w >= h
    target_w = w * 0.84
    f_size = 240.0 if is_wide else 210.0
    font = skia.Font(title_tf, f_size)
    while f_size > 68.0 and float(font.measureText(stamp)) > target_w:
        f_size -= 6.0
        font = skia.Font(title_tf, f_size)
    tw = float(font.measureText(stamp))
    drift_x = (shot_prog - 0.5) * -22.0
    cx = (w - tw) * 0.5 + drift_x
    cy = h * (0.37 if is_wide else 0.34)

    sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(190, 0, 0, 0))
    sh_p.setImageFilter(skia.ImageFilters.DropShadowOnly(0.0, 14.0, 26.0, 26.0, skia.ColorSetARGB(215, 0, 0, 0)))
    canvas.drawString(stamp, cx, cy, font, sh_p)

    fill_p = skia.Paint(AntiAlias=True)
    fill_p.setShader(
        skia.GradientShader.MakeLinear(
            [(cx, cy - f_size * 0.85), (cx, cy + f_size * 0.15)],
            [hex_to_skia("#FFE082", 205), hex_to_skia("#D4AF37", 198), hex_to_skia("#9E1B24", 185)],
            [0.0, 0.55, 1.0],
        )
    )
    canvas.drawString(stamp, cx, cy, font, fill_p)


def _draw_fullbleed_parallax_shot(
    canvas: skia.Canvas,
    w: int,
    h: int,
    bg_img: Optional[skia.Image],
    fg_img: Optional[skia.Image],
    shot_prog: float,
    t: float,
    pan_dir: float = 1.0,
    scene: Optional[NetflixDocScene] = None,
    title_tf: Optional[skia.Typeface] = None,
    shot_local_t: float = 0.0,
    stamp_text: Optional[str] = None,
    allow_depth_title: bool = True,
) -> None:
    """Render an unobstructed full-bleed edge-to-edge 2.5D parallax cinema shot (Schema v3.0.0):
      - Counter-directional depth motion: Background `1.06 -> 1.00`, Foreground `1.00 -> 1.14`
      - Unified `master_color_grade` C++ Skia ColorMatrix applied pre-UI
      - 3D Depth Title rendered strictly on Shot 0 (`allow_depth_title=True`) BETWEEN `bg_img` and `fg_img`,
        passing `fg_img` for alpha-aware rule-of-thirds placement (>=88% unoccluded legibility)!
    """
    global _CACHED_FALLBACK_TITLE_TF
    full_r = skia.Rect.MakeXYWH(0, 0, w, h)
    canvas.clear(skia.ColorSetARGB(255, 11, 14, 21))
    eff_mood = str(getattr(scene, "mood", "dark_horror") or "dark_horror") if scene is not None else "dark_horror"
    p_clamped = max(0.0, min(1.0, float(shot_prog)))
    grade_paint = _get_master_color_grade_paint()

    if bg_img is not None:
        # Counter-directional 2.5D parallax: Background pulls gently 1.06 -> 1.00 while Foreground pushes 1.00 -> 1.14
        bg_zoom = (1.06 - 0.06 * p_clamped) if fg_img is not None else (1.00 + 0.07 * p_clamped)
        bg_pan_x = (p_clamped - 0.5) * (-8.0 * pan_dir)
        bg_pan_y = (p_clamped - 0.5) * -3.0
        canvas.save()
        canvas.translate(w * 0.5 + bg_pan_x, h * 0.44 + bg_pan_y)
        canvas.scale(bg_zoom, bg_zoom)
        canvas.translate(-w * 0.5, -h * 0.44)
        _draw_image_cover(canvas, bg_img, full_r, paint=None)
        canvas.restore()

        # Atmospheric floating dust / warm candlelight embers sandwiched behind foreground subject
        mote_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(64, 224, 192, 151))
        for mi in range(14):
            mx_m = (mi * 197 + t * (24 + (mi % 4) * 8)) % w
            my_m = (mi * 131 - t * (16 + (mi % 3) * 6)) % h
            canvas.drawCircle(mx_m, my_m, 1.8 + (mi % 3) * 1.1, mote_p)

        # Giant 3D Depth Title strictly on Shot 0 (NEVER repeating on Shot 1/2!) right BETWEEN bg_img and fg_img
        if fg_img is not None and allow_depth_title:
            resolved_stamp = str(stamp_text or _extract_depth_stamp_text(scene)).strip()
            eff_tf = title_tf
            if eff_tf is None:
                if _CACHED_FALLBACK_TITLE_TF is None:
                    _CACHED_FALLBACK_TITLE_TF, _ = _load_verified_typeface("Montserrat-Black.ttf", role="doc_title")
                eff_tf = _CACHED_FALLBACK_TITLE_TF
            if resolved_stamp and eff_tf is not None:
                if draw_depth_title_behind_subject is not None:
                    if _DEPTH_TITLE_ACCEPTS_FG_IMG:
                        draw_depth_title_behind_subject(
                            canvas, w, h, resolved_stamp, p_clamped, t, eff_tf, mood=eff_mood, fg_img=fg_img
                        )
                    else:
                        draw_depth_title_behind_subject(
                            canvas, w, h, resolved_stamp, p_clamped, t, eff_tf, mood=eff_mood
                        )
                else:
                    _draw_fallback_depth_title_behind_subject(
                        canvas, w, h, resolved_stamp, p_clamped, t, eff_tf, mood=eff_mood
                    )

        if fg_img is not None:
            # Counter-directional foreground push-in: 1.00 -> 1.14
            fg_zoom = 1.00 + 0.14 * p_clamped
            fg_pan_x = (p_clamped - 0.5) * (14.0 * pan_dir)
            fg_pan_y = (p_clamped - 0.5) * -5.0
            canvas.save()
            canvas.translate(w * 0.5 + fg_pan_x, h * 0.44 + fg_pan_y)
            canvas.scale(fg_zoom, fg_zoom)
            canvas.translate(-w * 0.5, -h * 0.44)
            _draw_image_cover(canvas, fg_img, full_r, paint=None)
            canvas.restore()

    if draw_anamorphic_film_burn_and_bokeh is not None:
        draw_anamorphic_film_burn_and_bokeh(canvas, w, h, t, shot_local_t, mood=eff_mood)


def _draw_single_unique_shot_layer(
    canvas: skia.Canvas,
    w: int,
    h: int,
    layer: Tuple[str, Any],
    shot_prog: float,
    t: float,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    pan_dir: float = 1.0,
    scene: Optional[NetflixDocScene] = None,
    title_tf: Optional[skia.Typeface] = None,
    shot_local_t: float = 0.0,
    allow_depth_title: bool = True,
) -> None:
    """Render one single unique visual shot (moving B-roll, 2.5D u2netp parallax, or Ken Burns bespoke still)."""
    kind, payload = layer
    if kind == "video_primary" and primary_frame is not None:
        _draw_video_backdrop_layer(
            canvas,
            w,
            h,
            primary_frame,
            t,
            shot_prog,
            scrim_alpha=34,
            ken_burns_zoom=0.09,
            show_grid=False,
            show_dust=True,
        )
    elif kind == "video_secondary" and (pip_frame is not None or primary_frame is not None):
        _draw_video_backdrop_layer(
            canvas,
            w,
            h,
            pip_frame or primary_frame,
            t,
            shot_prog,
            scrim_alpha=32,
            ken_burns_zoom=0.11,
            show_grid=False,
            show_dust=True,
        )
    elif kind == "photo_25d" and isinstance(payload, tuple) and len(payload) == 2:
        bg_img, fg_img = payload
        _draw_fullbleed_parallax_shot(
            canvas,
            w,
            h,
            bg_img or primary_frame,
            fg_img,
            shot_prog,
            t,
            pan_dir=pan_dir,
            scene=scene,
            title_tf=title_tf,
            shot_local_t=shot_local_t,
            allow_depth_title=allow_depth_title,
        )
    elif kind == "photo_still" and payload is not None:
        _draw_fullbleed_parallax_shot(
            canvas,
            w,
            h,
            payload,
            None,
            shot_prog,
            t,
            pan_dir=pan_dir,
            scene=scene,
            title_tf=title_tf,
            shot_local_t=shot_local_t,
            allow_depth_title=False,
        )
    else:
        _draw_video_backdrop_layer(
            canvas,
            w,
            h,
            primary_frame,
            t,
            shot_prog,
            scrim_alpha=38,
            ken_burns_zoom=0.08,
            show_grid=False,
            show_dust=True,
        )


def _draw_unique_shot_slice(
    canvas: skia.Canvas,
    w: int,
    h: int,
    layers: List[Tuple[str, Any]],
    slice_t: float,
    slice_dur: float,
    t: float,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    s_idx: int = 0,
    cut_flash_on_first: bool = False,
    scene: Optional[NetflixDocScene] = None,
    title_tf: Optional[skia.Typeface] = None,
    allow_scene_depth_title: bool = True,
) -> None:
    """Step strictly 1-to-1 across `layers` with ZERO modulo wrap-around (`min(n-1, ...)`),
    firing 3D Depth Title strictly on Shot 0 (`shot_idx == 0 and allow_scene_depth_title`)!
    """
    if not layers:
        _draw_video_backdrop_layer(
            canvas, w, h, primary_frame, t, min(1.0, slice_t / max(0.2, slice_dur)),
            scrim_alpha=36, ken_burns_zoom=0.09, show_grid=False, show_dust=True,
        )
        return
    n_shots = len(layers)
    shot_dur = max(0.8, slice_dur / float(n_shots))
    shot_idx = min(n_shots - 1, max(0, int(slice_t / shot_dur)))
    shot_local_t = max(0.0, slice_t - shot_idx * shot_dur)
    shot_prog = min(1.0, shot_local_t / shot_dur)
    pan_dir = 1.0 if (shot_idx + s_idx) % 2 == 0 else -1.0

    _draw_single_unique_shot_layer(
        canvas,
        w,
        h,
        layers[shot_idx],
        shot_prog,
        t,
        primary_frame,
        pip_frame,
        pan_dir=pan_dir,
        scene=scene,
        title_tf=title_tf,
        shot_local_t=shot_local_t,
        allow_depth_title=(allow_scene_depth_title and shot_idx == 0),
    )

    if (shot_idx > 0 or cut_flash_on_first) and shot_local_t < 0.11:
        cut_k = 1.0 - (shot_local_t / 0.11)
        flash_alpha = int(92 * (cut_k ** 1.6))
        canvas.drawRect(
            skia.Rect.MakeXYWH(0, 0, w, h),
            skia.Paint(Color=skia.ColorSetARGB(flash_alpha, 224, 192, 151)),
        )


def _draw_mode_2d_schematic_over_realism(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Layer 2 (`2D_Infographic_Over_Realism` — Vox / Johnny Harris):
    Delegates to `engine.pro_motion_graphics.draw_2d_schematic_over_realism` when available,
    else renders animated 2D tactical reticles, dashed callout vectors, and breakdown bars in
    `#EAB308`, `#D9381E`, `#F8FAFC` over a 65% brightness desaturated realistic backdrop.
    """
    eff_bg = backdrop_img or media.parallax_bg or media.primary_photo
    if draw_2d_schematic_over_realism is not None:
        try:
            draw_2d_schematic_over_realism(
                canvas, w, h, scene, prog, t, title_tf, ui_tf, eff_bg
            )
            return
        except Exception:
            pass

    _draw_video_backdrop_layer(
        canvas, w, h, eff_bg, t, prog, scrim_alpha=126, ken_burns_zoom=0.05, show_grid=True, show_dust=False
    )
    is_wide = w >= h
    ent = _ease_out_cubic(min(1.0, body_t / 0.55))

    # Tactical target reticle over focal point
    rx = w * (0.34 if is_wide else 0.50)
    ry = h * (0.44 if is_wide else 0.34)
    rad = (128.0 if is_wide else 104.0) * (0.88 + 0.12 * ent)
    gold_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.6, Color=hex_to_skia("#EAB308", 225))
    crim_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.2, Color=hex_to_skia("#D9381E", 230))
    canvas.drawCircle(rx, ry, rad, gold_p)
    canvas.drawCircle(rx, ry, rad * 0.58, crim_p)
    canvas.drawLine(rx - rad * 1.25, ry, rx - rad * 0.72, ry, gold_p)
    canvas.drawLine(rx + rad * 0.72, ry, rx + rad * 1.25, ry, gold_p)
    canvas.drawLine(rx, ry - rad * 1.25, rx, ry - rad * 0.72, gold_p)
    canvas.drawLine(rx, ry + rad * 0.72, rx, ry + rad * 1.25, gold_p)

    # Animated dashed callout connector from reticle to schematic breakdown panel
    panel_x = w * 0.54 if is_wide else 68.0
    panel_y = h * 0.18 if is_wide else h * 0.50
    panel_w = w * 0.40 if is_wide else (w - 136.0)
    panel_h = h * 0.56 if is_wide else h * 0.31
    if is_wide:
        conn_end_x = rx + (panel_x - rx) * _ease_out_cubic(min(1.0, prog / 0.32))
        dash_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#EAB308", 220))
        dash_p.setPathEffect(skia.DashPathEffect.Make([12.0, 8.0], -t * 28.0))
        canvas.drawLine(rx + rad, ry, conn_end_x, panel_y + 92.0, dash_p)

    # Right schematic glass card
    pr = skia.Rect.MakeXYWH(panel_x, panel_y, panel_w, panel_h)
    canvas.drawRoundRect(pr, 12.0, 12.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(216, 15, 19, 26)))
    canvas.drawRoundRect(pr, 12.0, 12.0, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#EAB308", 195)))
    canvas.drawRect(skia.Rect.MakeXYWH(panel_x, panel_y + 18.0, 5.0, panel_h - 36.0), skia.Paint(Color=hex_to_skia("#D9381E")))

    tag_txt = "SCHEMATIC ANALYSIS" if is_en else "ANÁLISE ESQUEMÁTICA • ARQUIVO"
    tf_k, tl_k = _wrap_text_to_width(tag_txt, ui_tf, 18.0, 13.0, panel_w - 56.0, 1)
    if tl_k:
        _draw_safe_string(canvas, tl_k[0], panel_x + 28.0, panel_y + 42.0, tf_k, skia.Paint(AntiAlias=True, Color=hex_to_skia("#EAB308")))

    h_f, h_lns = _wrap_text_to_width(scene.evidence_headline.upper(), title_tf, 32.0, 20.0, panel_w - 56.0, 2)
    hy = panel_y + 88.0
    for hl in h_lns:
        _draw_safe_string(canvas, hl, panel_x + 28.0, hy, h_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC")))
        hy += h_f.getSize() * 1.18

    q_f, q_lns = _wrap_text_to_width(scene.evidence_quote, ui_tf, 21.0, 15.0, panel_w - 56.0, 3)
    qy = hy + 18.0
    for ql in q_lns:
        _draw_safe_string(canvas, ql, panel_x + 28.0, qy, q_f, skia.Paint(AntiAlias=True, Color=hex_to_skia("#E0C097")))
        qy += q_f.getSize() * 1.28

    # Animated 3-step historical breakdown bars
    pts = (scene.timeline_points or [])[:3]
    by = max(qy + 22.0, panel_y + panel_h - 178.0)
    bar_w_max = panel_w - 64.0
    for b_i, pt in enumerate(pts):
        row_y = by + b_i * 52.0
        if row_y + 34.0 > panel_y + panel_h - 14.0:
            break
        bf, bl = _wrap_text_to_width(f"{pt.date} — {pt.label}", ui_tf, 16.0, 12.0, bar_w_max, 1)
        if bl:
            _draw_safe_string(canvas, bl[0], panel_x + 28.0, row_y, bf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 230)))
        fill_frac = _ease_out_cubic(min(1.0, max(0.0, (prog - b_i * 0.12) / 0.35))) * (0.62 + 0.18 * b_i)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(panel_x + 28.0, row_y + 10.0, bar_w_max, 10.0), 5.0, 5.0, skia.Paint(Color=skia.ColorSetARGB(90, 248, 250, 252)))
        canvas.drawRoundRect(
            skia.Rect.MakeXYWH(panel_x + 28.0, row_y + 10.0, max(12.0, bar_w_max * fill_frac), 10.0),
            5.0,
            5.0,
            skia.Paint(Color=hex_to_skia("#EAB308" if b_i % 2 == 0 else "#D9381E")),
        )


def _draw_mode_video_over_video_collage(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Layer 3 (`Video_Over_Video_PiP` — Floating Archival PiP Collage):
    Delegates to `engine.pro_motion_graphics.draw_video_over_video_collage` when available,
    else renders dark blurred B-roll/grid (`40%` opacity) with 1-3 floating tilted archival PiP cards
    (`2px solid rgba(255,255,255,0.18)`, drop shadow, `#FFD700` multiply highlighter wipe).
    """
    eff_bg = backdrop_img or media.parallax_bg or media.primary_photo
    pip_cards: List[skia.Image] = []
    if pip_frame is not None:
        pip_cards.append(pip_frame)
    for ep in (media.extra_photos or []):
        if len(pip_cards) < 3:
            pip_cards.append(ep)
    if not pip_cards and media.primary_photo is not None:
        pip_cards.append(media.primary_photo)

    if draw_video_over_video_collage is not None:
        try:
            draw_video_over_video_collage(
                canvas, w, h, scene, prog, t, title_tf, ui_tf, eff_bg, pip_cards
            )
            return
        except Exception:
            pass

    canvas.clear(hex_to_skia("#121417"))
    _draw_video_backdrop_layer(
        canvas, w, h, eff_bg, t, prog, scrim_alpha=172, ken_burns_zoom=0.04, show_grid=True, show_dust=False
    )
    is_wide = w >= h
    n_cards = max(1, min(3, len(pip_cards)))
    if is_wide:
        if n_cards == 1:
            slots = [(w * 0.50, h * 0.44, w * 0.62, h * 0.58, -1.2)]
        elif n_cards == 2:
            slots = [
                (w * 0.32, h * 0.43, w * 0.44, h * 0.52, -1.8),
                (w * 0.68, h * 0.48, w * 0.42, h * 0.50, 1.7),
            ]
        else:
            slots = [
                (w * 0.24, h * 0.44, w * 0.34, h * 0.44, -2.0),
                (w * 0.52, h * 0.40, w * 0.36, h * 0.48, 0.8),
                (w * 0.78, h * 0.49, w * 0.33, h * 0.43, 1.9),
            ]
    else:
        slots = [
            (w * 0.50, h * (0.28 + idx * 0.21), w * 0.78, h * 0.24, -1.5 if idx % 2 == 0 else 1.5)
            for idx in range(n_cards)
        ]

    grade_paint = _get_master_color_grade_paint()
    for c_i, (cx, cy, cw, ch, rot_deg) in enumerate(slots):
        ent = _ease_out_back(max(0.0, min(1.0, (body_t - c_i * 0.14) / 0.42)))
        slide_y = (1.0 - ent) * 48.0
        canvas.save()
        canvas.translate(cx, cy + slide_y)
        canvas.rotate(rot_deg)
        sc = 0.88 + 0.12 * ent
        canvas.scale(sc, sc)
        cr = skia.Rect.MakeXYWH(-cw * 0.5, -ch * 0.5, cw, ch)
        crr = skia.RRect.MakeRectXY(cr, 12.0, 12.0)

        # Fast stacked soft offset shadows (0.1 ms/frame vs 55 ms/frame CPU Gaussian DropShadow)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-cw * 0.5 - 6.0, -ch * 0.5 + 14.0, cw + 12.0, ch + 12.0), 16.0, 16.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(115, 0, 0, 0)))
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-cw * 0.5 - 2.0, -ch * 0.5 + 8.0, cw + 4.0, ch + 4.0), 14.0, 14.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(170, 0, 0, 0)))
        canvas.drawRRect(crr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(245, 18, 20, 23)))

        canvas.save()
        canvas.clipRRect(crr, doAntiAlias=True)
        if c_i < len(pip_cards):
            _draw_image_cover(canvas, pip_cards[c_i], cr, paint=None, y_bias=0.22)
        canvas.restore()

        canvas.drawRRect(
            crr,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=skia.ColorSetARGB(46, 255, 255, 255)),
        )
        canvas.restore()

    # Synced #FFD700 brush-stroke highlight headline ribbon
    ribbon_w = min(w * 0.74, 1180.0)
    ribbon_x = (w - ribbon_w) * 0.5
    ribbon_y = h * (0.79 if is_wide else 0.76)
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(ribbon_x, ribbon_y, ribbon_w, 62.0),
        10.0,
        10.0,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(220, 16, 19, 25)),
    )
    hl_prog = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.12) / 0.36)))
    hl_p = skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD700", 185))
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(ribbon_x + 14.0, ribbon_y + 10.0, max(0.0, (ribbon_w - 28.0) * hl_prog), 42.0),
        6.0,
        6.0,
        hl_p,
    )
    hf, hlns = _wrap_text_to_width(scene.evidence_headline.upper(), title_tf, 27.0, 17.0, ribbon_w - 44.0, 1)
    if hlns:
        _draw_safe_string(
            canvas,
            hlns[0],
            ribbon_x + 24.0,
            ribbon_y + 40.0,
            hf,
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 16, 18, 22) if hl_prog > 0.45 else hex_to_skia("#F8FAFC")),
        )


def _draw_mode_fern_3d_reconstruction(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    backdrop_img: Optional[skia.Image],
    fg_img: Optional[skia.Image],
    is_en: bool = False,
) -> None:
    """Layer 4 (`Dark_3D_Reconstruction` — Fern Minimalist 3D Spatial Wireframe & Backlit Silhouette):
    Delegates to `engine.pro_motion_graphics.draw_fern_3d_reconstruction` when available,
    else renders a `#121417` slate void with orbiting perspective 3D architectural grid, volumetric
    spotlight cone, backlit subject silhouette, and `#D9381E`/`#EAB308`/`#38BDF8` forensic rings.
    """
    if draw_fern_3d_reconstruction is not None:
        try:
            draw_fern_3d_reconstruction(
                canvas, w, h, scene, prog, t, title_tf, ui_tf, backdrop_img=backdrop_img, fg_img=fg_img
            )
            return
        except Exception:
            pass

    canvas.clear(hex_to_skia("#121417"))
    vp_x = w * 0.5 + math.sin(prog * math.pi * 0.8) * (w * 0.06)
    vp_y = h * 0.40

    # Perspective 3D wireframe architectural floor & radial depth rays
    grid_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, Color=skia.ColorSetARGB(55, 248, 250, 252))
    for i in range(-10, 11):
        bx = vp_x + i * (w * 0.14)
        canvas.drawLine(vp_x + i * 24.0, vp_y, bx, float(h), grid_p)
    for r_i in range(1, 10):
        k = (r_i / 9.0) ** 1.75
        ry = vp_y + k * (h - vp_y)
        canvas.drawLine(0.0, ry, float(w), ry, grid_p)

    # Volumetric spotlight cone from top center
    cone = skia.Path()
    cone.moveTo(vp_x - 36.0, 0.0)
    cone.lineTo(vp_x + 36.0, 0.0)
    cone.lineTo(vp_x + w * 0.24, float(h))
    cone.lineTo(vp_x - w * 0.24, float(h))
    cone.close()
    cone_p = skia.Paint(AntiAlias=True)
    cone_p.setShader(
        skia.GradientShader.MakeLinear(
            [(vp_x, 0.0), (vp_x, float(h))],
            [skia.ColorSetARGB(88, 224, 192, 151), skia.ColorSetARGB(6, 56, 189, 248)],
        )
    )
    canvas.drawPath(cone, cone_p)

    # Backlit dark silhouette from fg_img alpha mask (or subtle dimmed architectural backdrop)
    if fg_img is not None:
        sil_p = skia.Paint(AntiAlias=True)
        sil_p.setColorFilter(skia.ColorFilters.Blend(skia.ColorSetARGB(255, 10, 13, 18), skia.BlendMode.kSrcIn))
        canvas.save()
        sc = 1.0 + 0.08 * prog
        canvas.translate(w * 0.5, h * 0.52)
        canvas.scale(sc, sc)
        canvas.translate(-w * 0.5, -h * 0.52)
        _draw_image_cover(canvas, fg_img, skia.Rect.MakeWH(w, h), paint=sil_p)
        canvas.restore()
    elif backdrop_img is not None:
        dim_p = skia.Paint(AntiAlias=True)
        dim_p.setAlphaf(0.32)
        dim_p.setColorFilter(_get_master_color_grade_filter())
        _draw_image_cover(canvas, backdrop_img, skia.Rect.MakeWH(w, h), paint=dim_p)

    # Tactical concentric floor target circles (#D9381E, #EAB308, #38BDF8)
    for ring_i, (r_rx, r_ry, col_hex) in enumerate(((260.0, 62.0, "#D9381E"), (175.0, 42.0, "#EAB308"), (105.0, 26.0, "#38BDF8"))):
        pulse = 1.0 + 0.04 * math.sin(t * 4.0 + ring_i)
        rr = skia.Rect.MakeXYWH(vp_x - r_rx * pulse, h * 0.72 - r_ry * pulse, r_rx * 2.0 * pulse, r_ry * 2.0 * pulse)
        canvas.drawOval(rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.6, Color=hex_to_skia(col_hex, 215)))

    # Forensic digital UI telemetry header
    hdr_lbl = "3D RECONSTRUCTION • ARCHIVAL MODEL" if is_en else "RECONSTRUÇÃO 3D • MODELO FORENSE"
    hf0 = skia.Font(ui_tf, 18.0)
    _draw_safe_string(canvas, hdr_lbl, 96.0, 72.0, hf0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#38BDF8", 225)))
    tf_m, tl_m = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 40.0, 24.0, w - 192.0, 1)
    if tl_m:
        _draw_safe_string(canvas, tl_m[0], 96.0, 122.0, tf_m, skia.Paint(AntiAlias=True, Color=hex_to_skia("#F8FAFC", 238)))


def _draw_mode_cinema_multishot(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    body_dur: float,
    t: float,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    cut_cadence_s: float = 2.6,
    s_idx: int = 0,
    title_tf: Optional[skia.Typeface] = None,
) -> None:
    """Cinema v7 Primary Visual Mode: clean, unobstructed FULL-SCREEN ZERO-REPETITION multi-shot storytelling!
    Always opens on hero 2.5D parallax plate (Shot 0) with 3D Depth Title strictly on Shot 0!
    """
    layers = list(media.shot_layers or [])
    if not layers:
        if (media.parallax_bg or media.primary_photo) is not None:
            layers.append(("photo_25d", (media.parallax_bg or media.primary_photo, media.parallax_fg)))
        if primary_frame is not None:
            layers.append(("video_primary", None))
        for ep in (media.extra_photos or []):
            layers.append(("photo_still", ep))
        if pip_frame is not None:
            layers.append(("video_secondary", None))

    _draw_unique_shot_slice(
        canvas,
        w,
        h,
        layers,
        slice_t=body_t,
        slice_dur=max(0.5, body_dur),
        t=t,
        primary_frame=primary_frame,
        pip_frame=pip_frame,
        s_idx=s_idx,
        cut_flash_on_first=False,
        scene=scene,
        title_tf=title_tf,
        allow_scene_depth_title=True,
    )


def _draw_mode_parallax_25d_photo(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
    body_dur: float = 10.0,
    s_idx: int = 0,
) -> None:
    """Mode 4 (Cinema v6): Multi-shot 2.5D u2netp Parallax & Bespoke Cinema cuts across BOTH 16:9 and 9:16!
    NEVER freezes 18s on a single photo and NEVER stretches into a mismatched matte — cuts smoothly across
    all unique shots in `media.shot_layers` with 3D Depth Titles behind 2.5D subjects!
    """
    is_wide = w >= h
    if media.shot_layers:
        _draw_unique_shot_slice(
            canvas,
            w,
            h,
            media.shot_layers,
            slice_t=body_t,
            slice_dur=max(0.5, body_dur),
            t=t,
            primary_frame=primary_frame,
            pip_frame=None,
            s_idx=s_idx,
            cut_flash_on_first=False,
            scene=scene,
            title_tf=title_tf,
        )
        return

    if not is_wide:
        _draw_fullbleed_parallax_shot(
            canvas,
            w,
            h,
            media.parallax_bg or media.primary_photo or primary_frame,
            media.parallax_fg,
            prog,
            t,
            pan_dir=1.0,
            scene=scene,
            title_tf=title_tf,
            shot_local_t=body_t,
        )
        return

    # 16:9 widescreen fallback when no multi-shot layers exist (aspect-cover crop -> ZERO stretch!)
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=125,
        ken_burns_zoom=0.06,
        show_grid=False,
        show_dust=True,
    )

    frame_w = w * 0.76
    frame_h = h * 0.61
    fy = h * 0.06

    plate_r = skia.Rect.MakeXYWH(-frame_w * 0.5, -frame_h * 0.5, frame_w, frame_h)
    plate_rr = skia.RRect.MakeRectXY(plate_r, 20.0, 20.0)

    canvas.save()
    canvas.translate(w * 0.5, fy + frame_h * 0.5)

    # Heavy dramatic cinema matte drop shadow
    matte_shadow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 16, 13, 28))
    matte_shadow.setImageFilter(skia.ImageFilters.DropShadow(0, 24, 46, 46, skia.ColorSetARGB(225, 0, 0, 0)))
    canvas.drawRRect(plate_rr, matte_shadow)

    # Clipped 2.5D Parallax Photo Stage
    canvas.save()
    canvas.clipRRect(plate_rr, doAntiAlias=True)

    bg_img = media.parallax_bg or media.primary_photo
    fg_img = media.parallax_fg

    # Crisp 16px parallax without blurry foreground DropShadow or aspect-ratio stretch
    bg_pan_x = (prog - 0.5) * -6.0
    bg_zoom = 1.03 + 0.045 * prog
    pivot_y = -frame_h * 0.16

    if bg_img is not None:
        canvas.save()
        canvas.translate(bg_pan_x, pivot_y)
        canvas.scale(bg_zoom, bg_zoom)
        canvas.translate(0.0, -pivot_y)
        _draw_image_cover(canvas, bg_img, plate_r, y_bias=0.35)
        canvas.restore()

        # Atmospheric depth haze & warm projector motes sandwiched BETWEEN background and 2.5D foreground!
        haze_p = skia.Paint(Color=skia.ColorSetARGB(34, 18, 12, 34))
        canvas.drawRect(plate_r, haze_p)
        mote_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(62, 255, 209, 102))
        for mi in range(12):
            mx_m = -frame_w * 0.48 + ((mi * 173 + t * (22 + (mi % 4) * 8)) % (frame_w * 0.96))
            my_m = -frame_h * 0.46 + ((mi * 119 - t * (14 + (mi % 3) * 6)) % (frame_h * 0.92))
            canvas.drawCircle(mx_m, my_m, 2.0 + (mi % 3) * 1.1, mote_p)

        if fg_img is not None:
            fg_pan_x = (prog - 0.5) * 10.0
            fg_pan_y = (prog - 0.5) * -4.0
            fg_zoom = 1.05 + 0.065 * prog
            canvas.save()
            canvas.translate(fg_pan_x, pivot_y + fg_pan_y)
            canvas.scale(fg_zoom, fg_zoom)
            canvas.translate(0.0, -pivot_y)
            fg_paint = skia.Paint(AntiAlias=True)
            _draw_image_cover(canvas, fg_img, plate_r, paint=fg_paint, y_bias=0.35)
            canvas.restore()
    else:
        # Fallback archival tone plate if completely offline with no photo
        grad_p = skia.Paint()
        grad_p.setShader(
            skia.GradientShader.MakeLinear(
                [(-frame_w * 0.5, -frame_h * 0.5), (frame_w * 0.5, frame_h * 0.5)],
                [skia.ColorSetARGB(255, 34, 30, 52), skia.ColorSetARGB(255, 18, 15, 30)],
            )
        )
        canvas.drawRect(plate_r, grad_p)

    # Anamorphic subtle dark edge vignette inside cinema matte
    vig = skia.Paint()
    vig.setShader(
        skia.GradientShader.MakeRadial(
            (0.0, 0.0),
            max(frame_w, frame_h) * 0.65,
            [skia.ColorSetARGB(0, 8, 6, 16), skia.ColorSetARGB(135, 8, 6, 16)],
        )
    )
    canvas.drawRect(plate_r, vig)

    # Top-left forensic 2.5D archive tag inside cinema matte
    tag_lbl = "2.5D DEPTH ARCHIVE • FORENSIC PHOTO" if is_en else "ARQUIVO 2.5D • FOTO FORENSE"
    tag_r = skia.Rect.MakeXYWH(-frame_w * 0.5 + 24.0, -frame_h * 0.5 + 20.0, 340.0, 34.0)
    canvas.drawRoundRect(tag_r, 8.0, 8.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 11, 7, 19)))
    tf_tag, tl_tag = _wrap_text_to_width(tag_lbl, ui_tf, 16.0, 12.0, 316.0, 1)
    if tl_tag:
        _draw_safe_string(canvas, tl_tag[0], -frame_w * 0.5 + 38.0, -frame_h * 0.5 + 42.5, tf_tag, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    canvas.restore()

    # Cinema matte golden border + viewfinder corner brackets
    canvas.drawRRect(plate_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166", 200)))
    brk_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.5, Color=hex_to_skia(scene.highlight_color))
    bw_c = 34.0
    for sx_c in (-1, 1):
        for sy_c in (-1, 1):
            cx_c = sx_c * (frame_w * 0.5 - 18.0)
            cy_c = sy_c * (frame_h * 0.5 - 18.0)
            canvas.drawLine(cx_c, cy_c, cx_c - sx_c * bw_c, cy_c, brk_p)
            canvas.drawLine(cx_c, cy_c, cx_c, cy_c - sy_c * bw_c, brk_p)
    canvas.restore()

    # Sleek floating foreground evidence badge anchored cleanly at bottom-right (leaves 80%+ of 2.5D photo unobstructed!)
    ent_card = _ease_out_back(min(1.0, body_t / 0.45))
    fg_pan_x = (prog - 0.5) * 26.0
    card_w = min(650.0, w * 0.44) if is_wide else (w - 130.0)
    card_h = 158.0 if is_wide else 195.0
    card_cx = (w * 0.5 + frame_w * 0.5 - card_w * 0.5 - 24.0 + fg_pan_x) if is_wide else (w * 0.5)
    card_cy = (fy + frame_h - card_h * 0.42) if is_wide else (fy + frame_h + card_h * 0.62)
    # Clamp cleanly inside safe horizontal bounds
    card_cx = max(card_w * 0.5 + 48.0, min(w - card_w * 0.5 - 48.0, card_cx))

    canvas.save()
    canvas.translate(card_cx, card_cy)
    sc_c = 0.88 + 0.12 * ent_card
    canvas.scale(sc_c, sc_c)

    fg_rect = skia.Rect.MakeXYWH(-card_w * 0.5, -card_h * 0.5, card_w, card_h)
    fg_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(222, 12, 9, 24))
    fg_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 34, 34, skia.ColorSetARGB(220, 0, 0, 0)))
    canvas.drawRoundRect(fg_rect, 18.0, 18.0, fg_bg)
    canvas.drawRoundRect(
        fg_rect,
        18.0,
        18.0,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia(scene.highlight_color)),
    )

    badge_txt = f"ARCHIVED EVIDENCE • {scene.act_label}" if is_en else f"EVIDÊNCIA ARQUIVADA • {scene.act_label}"
    b_font, b_lns = _wrap_text_to_width(badge_txt, ui_tf, 18.0, 14.0, card_w - 56.0, 1)
    if b_lns:
        _draw_safe_string(canvas, b_lns[0], -card_w * 0.5 + 28.0, -card_h * 0.5 + 36.0, b_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    m_font, m_lines = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 40.0, 24.0, card_w - 56.0, 1)
    if m_lines:
        _draw_safe_string(canvas, m_lines[0], -card_w * 0.5 + 28.0, -card_h * 0.5 + 88.0, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

    s_font, s_lines = _wrap_text_to_width(scene.evidence_headline, ui_tf, 20.0, 15.0, card_w - 56.0, 1)
    if s_lines:
        _draw_safe_string(
            canvas,
            s_lines[0],
            -card_w * 0.5 + 28.0,
            card_h * 0.5 - 24.0,
            s_font,
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 230, 225, 245)),
        )
    canvas.restore()


def _draw_mode_newspaper_highlighter(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Mode 2: Delegate to Pro Motion Graphics `draw_pro_archival_newspaper` (with built-in fallback)."""
    if draw_pro_archival_newspaper is not None:
        photo_img = media.primary_photo if media is not None else None
        draw_pro_archival_newspaper(
            canvas, w, h, scene, prog, body_t, t, title_tf, ui_tf, primary_frame, photo_img, is_en=is_en
        )
        return
    # Real moving HD B-roll video visibly playing behind the tilted editorial broadsheet!
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=155,
        ken_burns_zoom=0.05,
        show_grid=False,
        show_dust=True,
    )

    is_wide = w >= h
    paper_w = min(w - 130.0, 1460.0 if is_wide else 940.0)
    inner_w = paper_w - 92.0

    # Pre-measure headline & quote so `paper_h` hugs the actual content tightly (ZERO 45% empty beige bottom!)
    h_font, h_lines = _wrap_text_to_width(_normalize_upper(scene.evidence_headline), title_tf, 44.0 if is_wide else 42.0, 24.0, inner_w, 2)
    n_h_lines = max(1, len(h_lines))
    headline_step = h_font.getSize() * 1.15
    # Distance from card top to `content_top` (masthead + double rule + headline + divider + 18px gap)
    header_height = 42.0 + 66.0 + (n_h_lines * headline_step) - 12.0 + 18.0

    if is_wide:
        paper_h = h * 0.61
        py = h * 0.075
        q_font_v = None
        q_lines_v: List[str] = []
        v_photo_h = 0.0
        v_q_box_h = 0.0
    else:
        # 9:16 Vertical Broadsheet: balanced editorial inset (~1.40:1 aspect, top-weighted crop) + tight height
        q_font_v, q_lines_v = _wrap_text_to_width(scene.evidence_quote, ui_tf, 28.0, 18.0, inner_w - 40.0, 4)
        v_line_step = q_font_v.getSize() * 1.38
        v_q_box_h = max(1, len(q_lines_v)) * v_line_step + 40.0
        # Target ~1.40:1 editorial aspect (inside 1.35:1-1.45:1) so portraits keep head/horns intact
        v_photo_h = round(inner_w / 1.40)
        cap_and_gap = 38.0
        bottom_pad = 32.0
        max_paper_h = h * 0.66
        raw_paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        if raw_paper_h > max_paper_h:
            shrink = raw_paper_h - max_paper_h
            v_photo_h = max(round(inner_w / 1.45), v_photo_h - shrink)
        paper_h = header_height + v_photo_h + cap_and_gap + v_q_box_h + bottom_pad
        # Center cleanly inside the clear vertical window between lower-third (~170px) and captions (~1520px)
        py = max(170.0, min(h * 0.16, (h * 0.78 - paper_h) * 0.5 + 85.0))

    # Slow 2.5D editorial camera push-in
    cam_scale = 1.0 + 0.05 * prog
    tilt_deg = -1.3 + 0.9 * prog

    canvas.save()
    canvas.translate(w * 0.5, py + paper_h * 0.5)
    canvas.scale(cam_scale, cam_scale)
    canvas.rotate(tilt_deg)

    p_rect = skia.Rect.MakeXYWH(-paper_w * 0.5, -paper_h * 0.5, paper_w, paper_h)
    paper_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 244, 237, 221))
    paper_paint.setImageFilter(skia.ImageFilters.DropShadow(0, 24, 46, 46, skia.ColorSetARGB(225, 0, 0, 0)))
    canvas.drawRoundRect(p_rect, 12.0, 12.0, paper_paint)

    ink_dark = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 20, 17, 26))
    ink_muted = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(178, 66, 60, 72))
    rule_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=skia.ColorSetARGB(255, 36, 30, 42))

    left_x = -paper_w * 0.5 + 46.0
    right_x = paper_w * 0.5 - 46.0
    top_y = -paper_h * 0.5 + 42.0

    # Mood-aware Archival Masthead (NEVER force Financial masthead on Horror/History/Crime docs!)
    mood = str(getattr(scene, "mood", "corporate_thriller") or "corporate_thriller")
    if mood == "dark_horror":
        mast_txt = (
            "DARK HISTORY CHRONICLE   •   RESTRICTED ARCHIVE EDITION"
            if is_en
            else "ARQUIVO HISTÓRICO OBSCURO   •   EDIÇÃO CONFIDENCIAL"
        )
    elif mood == "investigative_crime":
        mast_txt = (
            "INVESTIGATIVE CHRONICLE   •   FORENSIC CASE EDITION"
            if is_en
            else "CRÔNICA INVESTIGATIVA   •   EDIÇÃO FORENSE"
        )
    elif mood == "epic_history":
        mast_txt = (
            "HISTORICAL ARCHIVE   •   SPECIAL CHRONICLE EDITION"
            if is_en
            else "ARQUIVOS DA HISTÓRIA   •   EDIÇÃO ESPECIAL"
        )
    else:
        mast_txt = "THE FINANCIAL DOSSIER   •   FORENSIC ARCHIVE EDITION"
    mast_font, mast_lns = _wrap_text_to_width(mast_txt, ui_tf, 21.0, 14.0, inner_w, 1)
    if mast_lns:
        _draw_safe_string(canvas, mast_lns[0], left_x, top_y, mast_font, ink_muted)
    canvas.drawLine(left_x, top_y + 13.0, right_x, top_y + 13.0, rule_p)
    canvas.drawLine(left_x, top_y + 19.0, right_x, top_y + 19.0, rule_p)

    # Bold Newspaper Headline (auto-wrapped to 2 lines, never clips)
    hy = top_y + 66.0
    for ln in h_lines:
        _draw_safe_string(canvas, ln, left_x, hy, h_font, ink_dark)
        hy += headline_step

    rule_y = hy - 12.0
    canvas.drawLine(left_x, rule_y, right_x, rule_y, rule_p)

    content_top = rule_y + 18.0
    content_bottom = paper_h * 0.5 - 32.0
    content_h = max(140.0, content_bottom - content_top)

    if is_wide:
        # TWO-COLUMN BROADSHEET: Left 41% REAL monochrome/sepia photograph, Right 56% Highlighted evidence quote!
        photo_col_w = inner_w * 0.41
        gap_col = inner_w * 0.03
        quote_col_x = left_x + photo_col_w + gap_col
        quote_col_w = inner_w - photo_col_w - gap_col

        photo_h = max(160.0, content_h - 32.0)
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, photo_col_w, photo_h)
        if media.primary_photo is not None:
            _draw_monochrome_sepia_photo(canvas, media.primary_photo, photo_rect, radius=6.0, halftone_lines=True, y_bias=0.16)
        else:
            canvas.drawRect(photo_rect, skia.Paint(Color=skia.ColorSetARGB(40, 30, 25, 35)))
            canvas.drawRect(photo_rect, rule_p)

        # Archival photo caption underneath
        photo_cap = (
            f"ARCHIVAL PHOTO • {scene.map_origin.upper()} - {scene.map_destination.upper()}"
            if is_en
            else f"ARQUIVO FOTOGRÁFICO • {scene.map_origin.upper()} - {scene.map_destination.upper()}"
        )
        pc_f, pc_l = _wrap_text_to_width(photo_cap, ui_tf, 15.0, 11.5, photo_col_w, 1)
        if pc_l:
            _draw_safe_string(canvas, pc_l[0], left_x, content_top + photo_h + 22.0, pc_f, ink_muted)

        # Decorative faux newspaper body print lines behind right column
        col_line_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5.5, Color=skia.ColorSetARGB(40, 38, 33, 46))
        for cy_f in range(int(content_top + 8), int(content_bottom - 8), 18):
            canvas.drawLine(quote_col_x, cy_f, quote_col_x + quote_col_w * 0.47, cy_f, col_line_p)
            canvas.drawLine(quote_col_x + quote_col_w * 0.52, cy_f, right_x, cy_f, col_line_p)

        # Highlighted Key Evidence Quote Box on right column
        q_font, q_lines = _wrap_text_to_width(scene.evidence_quote, ui_tf, 30.0, 19.0, quote_col_w - 40.0, 4)
        line_step = q_font.getSize() * 1.40
        q_box_h = min(content_h - 16.0, len(q_lines) * line_step + 44.0)
        q_box_y = content_top + max(6.0, (content_h - q_box_h) * 0.42)

        callout_r = skia.Rect.MakeXYWH(quote_col_x, q_box_y, quote_col_w, q_box_h)
        canvas.drawRoundRect(callout_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 251, 247, 236)))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, rule_p)

        sweep_total = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.06) / 0.68)))
        hl_hex = scene.highlight_color if scene.highlight_color in ("#FFD166", "#FF2E93") else "#FFD166"
        hl_color = hex_to_skia(hl_hex, alpha=215 if hl_hex == "#FFD166" else 178)
        hl_paint = skia.Paint(AntiAlias=True, Color=hl_color)
        hl_paint.setBlendMode(skia.BlendMode.kMultiply)

        n_lns = max(1, len(q_lines))
        qy = q_box_y + 44.0
        for idx_l, qln in enumerate(q_lines):
            _draw_safe_string(canvas, qln, quote_col_x + 20.0, qy, q_font, ink_dark)
            line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
            if line_prog > 0.01:
                lw = float(q_font.measureText(qln))
                hl_rect = skia.Rect.MakeXYWH(
                    quote_col_x + 12.0,
                    qy - q_font.getSize() * 0.88,
                    (lw + 16.0) * line_prog,
                    q_font.getSize() * 1.18,
                )
                canvas.drawRoundRect(hl_rect, 8.0, 8.0, hl_paint)
            qy += line_step
    else:
        # 9:16 Vertical Broadsheet: Balanced ~1.40:1 editorial inset photo (top-weighted crop) + archival caption + tight quote box
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, inner_w, v_photo_h)
        if media.primary_photo is not None:
            _draw_monochrome_sepia_photo(canvas, media.primary_photo, photo_rect, radius=6.0, halftone_lines=True, y_bias=0.14)
        else:
            canvas.drawRect(photo_rect, skia.Paint(Color=skia.ColorSetARGB(40, 30, 25, 35)))
            canvas.drawRect(photo_rect, rule_p)

        # Concise archival photo caption underneath inset photo
        photo_cap = (
            f"ARCHIVAL EXHIBIT • {_normalize_upper(scene.lower_third_title)}"
            if is_en
            else f"ARQUIVO FOTOGRÁFICO • {_normalize_upper(scene.lower_third_title)}"
        )
        pc_f, pc_l = _wrap_text_to_width(photo_cap, ui_tf, 15.0, 11.5, inner_w, 1)
        if pc_l:
            _draw_safe_string(canvas, pc_l[0], left_x, content_top + v_photo_h + 22.0, pc_f, ink_muted)

        q_box_y = content_top + v_photo_h + 38.0
        assert q_font_v is not None
        line_step = q_font_v.getSize() * 1.38
        callout_r = skia.Rect.MakeXYWH(left_x, q_box_y, inner_w, v_q_box_h)
        canvas.drawRoundRect(callout_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 251, 247, 236)))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, rule_p)

        sweep_total = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.06) / 0.68)))
        hl_hex = scene.highlight_color if scene.highlight_color in ("#FFD166", "#FF2E93") else "#FFD166"
        hl_paint = skia.Paint(AntiAlias=True, Color=hex_to_skia(hl_hex, alpha=215 if hl_hex == "#FFD166" else 178))
        hl_paint.setBlendMode(skia.BlendMode.kMultiply)

        n_lns = max(1, len(q_lines_v))
        qy = q_box_y + 42.0
        for idx_l, qln in enumerate(q_lines_v):
            _draw_safe_string(canvas, qln, left_x + 20.0, qy, q_font_v, ink_dark)
            line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
            if line_prog > 0.01:
                lw = float(q_font_v.measureText(qln))
                canvas.drawRoundRect(
                    skia.Rect.MakeXYWH(left_x + 12.0, qy - q_font_v.getSize() * 0.88, (lw + 16.0) * line_prog, q_font_v.getSize() * 1.16),
                    8.0,
                    8.0,
                    hl_paint,
                )
            qy += line_step

    canvas.restore()


def _draw_mode_dark_map_route(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    pip_frame: Optional[skia.Image],
    is_en: bool = False,
) -> None:
    """Mode 3: Delegate to Pro Motion Graphics `draw_pro_cartographic_map` (with built-in fallback)."""
    if draw_pro_cartographic_map is not None:
        draw_pro_cartographic_map(
            canvas, w, h, scene, prog, body_t, t, title_tf, ui_tf, primary_frame, pip_frame, is_en=is_en
        )
        return
    # Real moving HD B-roll video continuously playing behind and through the translucent tactical glass map!
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=150,
        ken_burns_zoom=0.05,
        show_grid=False,
        show_dust=True,
    )

    is_wide = w >= h
    rec_badge = "REC • VIDEO ARCHIVE" if is_en else "REC • ARQUIVO DE VÍDEO"

    if is_wide:
        map_w = w * 0.91
        map_h = h * 0.64
        mx = (w - map_w) * 0.5
        my = h * 0.055
    else:
        map_w = w * 0.88
        map_h = h * 0.37
        mx = (w - map_w) * 0.5
        my = h * 0.12

    map_r = skia.Rect.MakeXYWH(mx, my, map_w, map_h)
    map_rr = skia.RRect.MakeRectXY(map_r, 22.0, 22.0)

    # Translucent glass tactical panel (alpha=162 so moving HD video texture clearly shimmers behind the map!)
    map_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(162, 11, 16, 34))
    map_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 36, 36, skia.ColorSetARGB(200, 0, 0, 0)))
    canvas.drawRRect(map_rr, map_bg)

    canvas.save()
    canvas.clipRRect(map_rr, doAntiAlias=True)

    # Subtle tactical coordinate grid inside map
    mgrid = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=skia.ColorSetARGB(34, 179, 136, 255))
    for gx in range(int(mx), int(mx + map_w), 88):
        canvas.drawLine(gx, my, gx, my + map_h, mgrid)
    for gy in range(int(my), int(my + map_h), 88):
        canvas.drawLine(mx, gy, mx + map_w, gy, mgrid)

    # Stylized translucent vector continents
    land_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(88, 38, 56, 98))
    land_stroke = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.8, Color=skia.ColorSetARGB(135, 92, 128, 210))
    for cx_f, cy_f, rx_f, ry_f in [
        (0.18, 0.38, 0.12, 0.17),
        (0.24, 0.70, 0.08, 0.15),
        (0.42, 0.34, 0.11, 0.14),
        (0.45, 0.63, 0.10, 0.16),
        (0.64, 0.42, 0.14, 0.18),
    ]:
        oval = skia.Rect.MakeXYWH(mx + map_w * (cx_f - rx_f), my + map_h * (cy_f - ry_f), map_w * rx_f * 2, map_h * ry_f * 2)
        canvas.drawRoundRect(oval, 42.0, 42.0, land_p)
        canvas.drawRoundRect(oval, 42.0, 42.0, land_stroke)

    # Route coordinates carefully placed left-to-center-right so the PiP monitor on the right NEVER overlaps labels!
    if is_wide:
        p_orig = (mx + map_w * 0.16, my + map_h * 0.66)
        p_dest = (mx + map_w * 0.56, my + map_h * 0.36)
        p_ctrl = (mx + map_w * 0.36, my + map_h * 0.12)
        pip_cx = mx + map_w * 0.81
        pip_cy = my + map_h * 0.55
        pip_w = 570.0
        pip_h = 330.0
    else:
        p_orig = (mx + map_w * 0.22, my + map_h * 0.66)
        p_dest = (mx + map_w * 0.78, my + map_h * 0.38)
        p_ctrl = (mx + map_w * 0.50, my + map_h * 0.12)
        pip_cx = w * 0.50
        pip_cy = my + map_h + 235.0
        pip_w = 780.0
        pip_h = 438.0

    # Tactical radar concentric rings around destination
    ring_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.6, Color=skia.ColorSetARGB(82, 255, 46, 147))
    for rad in (34.0, 68.0, 106.0):
        pulse_r = rad + ((t * 28.0) % 34.0)
        canvas.drawCircle(p_dest[0], p_dest[1], pulse_r, ring_p)

    # Animated progressive dashed route from p_orig -> p_dest along quadratic Bézier
    route_prog = _ease_out_cubic(min(1.0, max(0.06, prog * 1.25)))
    route_path = skia.Path()
    steps = 48
    max_step = max(2, int(steps * route_prog))
    cur_tip = p_orig
    for si in range(max_step + 1):
        u = si / float(steps)
        bx = ((1 - u) ** 2) * p_orig[0] + 2 * (1 - u) * u * p_ctrl[0] + (u ** 2) * p_dest[0]
        by = ((1 - u) ** 2) * p_orig[1] + 2 * (1 - u) * u * p_ctrl[1] + (u ** 2) * p_dest[1]
        if si == 0:
            route_path.moveTo(bx, by)
        else:
            route_path.lineTo(bx, by)
        cur_tip = (bx, by)

    glow_route = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=10.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(120, 255, 46, 147),
    )
    glow_route.setImageFilter(skia.ImageFilters.Blur(6, 6))
    canvas.drawPath(route_path, glow_route)

    dash_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=5.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#FFD166"),
    )
    dash_p.setPathEffect(skia.DashPathEffect.Make([18.0, 12.0], -t * 70.0))
    canvas.drawPath(route_path, dash_p)

    # Sleek glowing connector wire linking destination beacon -> live PiP forensic monitor!
    if is_wide and pip_frame is not None:
        conn_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=3.0,
            Color=hex_to_skia("#FF2E93", 205),
        )
        conn_p.setPathEffect(skia.DashPathEffect.Make([10.0, 8.0], -t * 45.0))
        canvas.drawLine(p_dest[0] + 18.0, p_dest[1], pip_cx - pip_w * 0.5, pip_cy - 30.0, conn_p)

    # Origin Pin + Label
    canvas.drawCircle(p_orig[0], p_orig[1], 12.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B388FF")))
    canvas.drawCircle(p_orig[0], p_orig[1], 6.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
    o_font, o_lines = _wrap_text_to_width(scene.map_origin.upper(), title_tf, 28.0, 18.0, map_w * 0.28, 1)
    if o_lines:
        _draw_safe_string(canvas, o_lines[0], max(mx + 24.0, p_orig[0] - 28.0), p_orig[1] + 44.0, o_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

    # Glowing Destination Pin + Pulsing Beacon
    pin_pulse = 14.0 + 4.5 * math.sin(t * 8.0)
    pin_glow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(150, 255, 46, 147))
    pin_glow.setImageFilter(skia.ImageFilters.Blur(8, 8))
    canvas.drawCircle(p_dest[0], p_dest[1], pin_pulse * 1.7, pin_glow)
    canvas.drawCircle(p_dest[0], p_dest[1], pin_pulse, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93")))
    canvas.drawCircle(p_dest[0], p_dest[1], 6.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))
    canvas.drawCircle(cur_tip[0], cur_tip[1], 8.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

    d_font, d_lines = _wrap_text_to_width(scene.map_destination.upper(), title_tf, 30.0, 18.0, map_w * 0.28, 1)
    if d_lines:
        dw = float(d_font.measureText(d_lines[0]))
        max_dx = (pip_cx - pip_w * 0.5 - dw - 24.0) if is_wide else (mx + map_w - dw - 24.0)
        dx_lbl = min(max_dx, max(mx + 24.0, p_dest[0] - dw * 0.5))
        _draw_safe_string(canvas, d_lines[0], dx_lbl, p_dest[1] + 46.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

    # Top-left HUD Metric Banner inside map
    hud_w = min(map_w * 0.48, 560.0) if is_wide else (map_w - 56.0)
    hud_r = skia.Rect.MakeXYWH(mx + 26.0, my + 24.0, hud_w, 88.0)
    canvas.drawRoundRect(hud_r, 14.0, 14.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(220, 11, 7, 19)))
    canvas.drawRoundRect(hud_r, 14.0, 14.0, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=hex_to_skia("#B8FF01")))
    m_font, m_lines = _wrap_text_to_width(scene.map_metric.upper(), title_tf, 31.0, 19.0, hud_w - 36.0, 1)
    if m_lines:
        _draw_safe_string(canvas, m_lines[0], mx + 44.0, my + 78.0, m_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))
    mood = str(getattr(scene, "mood", "corporate_thriller") or "corporate_thriller")
    if mood == "dark_horror":
        hud_sub_txt = "HISTORICAL ORIGIN & FOLKLORE TRAIL" if is_en else "ORIGEM HISTÓRICA & ROTA DO MITO"
    elif mood == "investigative_crime":
        hud_sub_txt = "FORENSIC EVIDENCE & ROUTE TRACKING" if is_en else "RASTREAMENTO DE PISTAS & ROTA"
    elif mood == "epic_history":
        hud_sub_txt = "HISTORICAL ROUTE & CHRONOLOGY" if is_en else "ROTA HISTÓRICA & EXPANSÃO"
    else:
        hud_sub_txt = "FORENSIC CAPITAL FLOW TRACKING" if is_en else "RASTREAMENTO FORENSE DE FLUXO"
    sub_hud, sub_lns = _wrap_text_to_width(hud_sub_txt, ui_tf, 16.0, 12.0, hud_w - 36.0, 1)
    if sub_lns:
        _draw_safe_string(canvas, sub_lns[0], mx + 44.0, my + 46.0, sub_hud, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 179, 136, 255)))

    canvas.restore()
    canvas.drawRRect(map_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#B388FF", 175)))

    # Video-over-Video (PiP) Forensic Monitor floating cleanly over the map!
    _draw_pip_forensic_monitor(
        canvas=canvas,
        pip_frame=pip_frame or primary_frame,
        cx=pip_cx,
        cy=pip_cy,
        pip_w=pip_w,
        pip_h=pip_h,
        tilt_deg=1.8 if is_wide else -1.5,
        border_hex="#FFD166",
        badge_text=rec_badge,
        caption_text=f"{scene.map_destination} • LIVE",
        body_t=body_t,
        t=t,
        ui_tf=ui_tf,
    )


def _draw_mode_sliding_timeline(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Mode 6: Delegate to Pro Motion Graphics `draw_pro_odometer_timeline` (with built-in fallback)."""
    photo_pool = (
        (media.extra_photos if media.extra_photos else ([media.primary_photo] if media.primary_photo is not None else []))
        if media is not None
        else []
    )
    if draw_pro_odometer_timeline is not None:
        draw_pro_odometer_timeline(
            canvas, w, h, scene, prog, body_t, t, title_tf, ui_tf, primary_frame, photo_pool, is_en=is_en
        )
        return
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=155,
        ken_burns_zoom=0.05,
        show_grid=True,
        show_dust=True,
    )

    pts = scene.timeline_points or [
        TimelinePoint(date="FASE I", label="Origem Documentada", value="INÍCIO"),
        TimelinePoint(date="FASE II", label="Virada Histórica", value="RUPTURA"),
        TimelinePoint(date="FASE III", label="Clímax dos Eventos", value="REVELAÇÃO"),
    ]
    n_pts = len(pts)
    active_float = prog * max(1, n_pts - 1)
    active_idx = min(n_pts - 1, int(round(active_float)))
    is_wide = w >= h

    photo_pool = media.extra_photos if media.extra_photos else ([media.primary_photo] if media.primary_photo is not None else [])

    if is_wide:
        rail_y = h * 0.42
        slot_spacing = 490.0
        cam_x = w * 0.5 - active_float * slot_spacing

        canvas.save()
        canvas.drawLine(80.0, rail_y, w - 80.0, rail_y, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0, Color=skia.ColorSetARGB(105, 179, 136, 255)))
        fill_x = 80.0 + (w - 160.0) * _ease_out_cubic(prog)
        canvas.drawLine(80.0, rail_y, fill_x, rail_y, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6.0, Color=hex_to_skia("#FFD166")))

        for idx, pt in enumerate(pts):
            nx = cam_x + idx * slot_spacing
            if nx < -320.0 or nx > w + 320.0:
                continue
            is_act = idx == active_idx
            card_w = 450.0 if is_act else 375.0
            card_h = 316.0 if is_act else 210.0

            # Keep bottom of lower cards strictly above Lower Third (y=782)!
            if idx % 2 == 0:
                cy_card = max(46.0, rail_y - card_h - 32.0)
            else:
                cy_card = min(h * 0.71 - card_h, rail_y + 34.0)

            cx_card = max(56.0, min(w - card_w - 56.0, nx - card_w * 0.5))
            # Vertical stem linking rail node cleanly into card horizontal span
            stem_x = max(cx_card + 24.0, min(cx_card + card_w - 24.0, nx))
            stem_y = (cy_card + card_h) if idx % 2 == 0 else cy_card
            canvas.drawLine(
                nx,
                rail_y,
                stem_x,
                stem_y,
                skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, Color=hex_to_skia("#FFD166" if is_act else "#B388FF", 180)),
            )

            # Node circle on rail
            canvas.drawCircle(nx, rail_y, 18.0 if is_act else 11.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93" if is_act else "#B388FF")))
            canvas.drawCircle(nx, rail_y, 7.0, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            c_rect = skia.Rect.MakeXYWH(cx_card, cy_card, card_w, card_h)
            c_rr = skia.RRect.MakeRectXY(c_rect, 18.0, 18.0)

            c_bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(236 if is_act else 192, 16, 13, 32))
            c_bg.setImageFilter(skia.ImageFilters.DropShadow(0, 16, 30, 30, skia.ColorSetARGB(195, 0, 0, 0)))
            canvas.drawRRect(c_rr, c_bg)

            text_top_y = cy_card
            # REAL PHOTOGRAPH INSET HEADER inside the highlighted active timeline card!
            if is_act and photo_pool:
                act_photo = photo_pool[idx % len(photo_pool)]
                hdr_h = 128.0
                hdr_r = skia.Rect.MakeXYWH(cx_card, cy_card, card_w, hdr_h)
                canvas.save()
                canvas.clipRRect(c_rr, doAntiAlias=True)
                canvas.drawImageRect(act_photo, hdr_r, _LINEAR_SAMPLING)
                # Smooth gradient fade into dark card body
                fade_p = skia.Paint()
                fade_p.setShader(
                    skia.GradientShader.MakeLinear(
                        [(0, cy_card + hdr_h * 0.35), (0, cy_card + hdr_h)],
                        [skia.ColorSetARGB(0, 16, 13, 32), skia.ColorSetARGB(236, 16, 13, 32)],
                    )
                )
                canvas.drawRect(hdr_r, fade_p)
                # Top-left highlight pill
                badge_lbl = "KEY MILESTONE" if is_en else "MARCO CRÍTICO"
                canvas.drawRoundRect(
                    skia.Rect.MakeXYWH(cx_card + 16.0, cy_card + 14.0, 164.0, 26.0),
                    6.0,
                    6.0,
                    skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 11, 7, 19)),
                )
                bf = skia.Font(ui_tf, 14.0)
                _draw_safe_string(canvas, badge_lbl, cx_card + 26.0, cy_card + 32.0, bf, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))
                canvas.restore()
                text_top_y = cy_card + hdr_h - 6.0

            b_col = hex_to_skia("#FFD166" if is_act else "#B388FF", 245 if is_act else 125)
            canvas.drawRRect(c_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.5 if is_act else 2.0, Color=b_col))

            # Date badge
            d_font, d_lns = _wrap_text_to_width(pt.date.upper(), title_tf, 28.0 if is_act else 26.0, 18.0, card_w - 44.0, 1)
            if d_lns:
                _draw_safe_string(canvas, d_lns[0], cx_card + 22.0, text_top_y + 38.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01" if is_act else "#B388FF")))

            # Financial Value
            v_font, v_lns = _wrap_text_to_width(pt.value.upper(), title_tf, 42.0 if is_act else 38.0, 24.0, card_w - 44.0, 1)
            if v_lns:
                _draw_safe_string(canvas, v_lns[0], cx_card + 22.0, text_top_y + 92.0, v_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))

            # Event Label
            l_font, l_lns = _wrap_text_to_width(pt.label, ui_tf, 22.0, 15.0, card_w - 44.0, 2)
            ly = text_top_y + 134.0
            for lln in l_lns:
                _draw_safe_string(canvas, lln, cx_card + 22.0, ly, l_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                ly += 26.0
        canvas.restore()
    else:
        # 9:16 Vertical sliding timeline with real photo inset inside active card
        rail_x = 112.0
        top_y = h * 0.14
        slot_h = 265.0
        canvas.drawLine(rail_x, top_y, rail_x, top_y + slot_h * (min(4, n_pts) - 0.5), skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5.0, Color=hex_to_skia("#FFD166")))
        for idx, pt in enumerate(pts[:4]):
            ny = top_y + idx * slot_h
            is_act = idx == active_idx
            canvas.drawCircle(rail_x, ny + 75.0, 16.0 if is_act else 10.0, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93" if is_act else "#B388FF")))
            card_w = w - 200.0
            card_h = 225.0 if is_act else 185.0
            c_rect = skia.Rect.MakeXYWH(rail_x + 38.0, ny, card_w, card_h)
            c_rr = skia.RRect.MakeRectXY(c_rect, 18.0, 18.0)
            canvas.drawRRect(c_rr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(225, 16, 13, 32)))
            canvas.drawRRect(c_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#FFD166" if is_act else "#B388FF")))

            text_w = card_w - 48.0
            if is_act and photo_pool:
                pw_in = 230.0
                pr = skia.Rect.MakeXYWH(rail_x + 38.0 + card_w - pw_in - 16.0, ny + 16.0, pw_in, card_h - 32.0)
                prr = skia.RRect.MakeRectXY(pr, 12.0, 12.0)
                canvas.save()
                canvas.clipRRect(prr, doAntiAlias=True)
                canvas.drawImageRect(photo_pool[idx % len(photo_pool)], pr, _LINEAR_SAMPLING)
                canvas.restore()
                text_w = card_w - pw_in - 68.0

            d_txt = f"{pt.date} • {pt.value}"
            d_font, d_lns = _wrap_text_to_width(d_txt, title_tf, 32.0, 20.0, text_w, 1)
            if d_lns:
                _draw_safe_string(canvas, d_lns[0], rail_x + 62.0, ny + 68.0, d_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            l_font, l_lns = _wrap_text_to_width(pt.label, ui_tf, 24.0, 17.0, text_w, 2)
            ly = ny + 124.0
            for ln in l_lns:
                _draw_safe_string(canvas, ln, rail_x + 62.0, ly, l_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                ly += 30.0


def _draw_mode_red_string_board(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    prog: float,
    body_t: float,
    t: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    primary_frame: Optional[skia.Image],
    media: LoadedSceneSkiaMedia,
    is_en: bool = False,
) -> None:
    """Mode 5: Delegate to Pro Motion Graphics `draw_pro_forensic_string_board` (with built-in fallback)."""
    photo_pool = (
        (media.extra_photos if media.extra_photos else ([media.primary_photo] if media.primary_photo is not None else []))
        if media is not None
        else []
    )
    if draw_pro_forensic_string_board is not None:
        draw_pro_forensic_string_board(
            canvas, w, h, scene, prog, body_t, t, title_tf, ui_tf, primary_frame, photo_pool, is_en=is_en
        )
        return
    # Subtle moving real HD B-roll video behind the investigative board (NEVER flat void!)
    _draw_video_backdrop_layer(
        canvas,
        w,
        h,
        primary_frame,
        t,
        prog,
        scrim_alpha=158,
        ken_burns_zoom=0.045,
        show_grid=True,
        show_dust=True,
    )

    nodes = (scene.board_nodes or [
        BoardNode(id="n1", title="ORIGEM #01", role="Ponto Inicial", badge="ARQUIVO"),
        BoardNode(id="n2", title="REGISTRO OCULTO", role="Crônica Antiga", badge="PROVA"),
        BoardNode(id="n3", title="VIRADA CRÍTICA", role="Evento Decisivo", badge="EVIDÊNCIA"),
        BoardNode(id="n4", title="LEGADO FINAL", role="Verdade Exposta", badge="DESFECHO"),
    ])[:4]

    photo_pool = media.extra_photos if media.extra_photos else ([media.primary_photo] if media.primary_photo is not None else [])

    is_wide = w >= h
    if is_wide:
        # 2x2 Polaroid + Obsidian Evidence Cards with wide central corridor for glowing #FF2E93 strings & visible B-roll!
        centers = [
            (460.0, 210.0),
            (1460.0, 206.0),
            (470.0, 545.0),
            (1450.0, 540.0),
        ]
        tilts = (-1.8, 1.6, 1.4, -1.7)
        card_w, card_h = 560.0, 270.0
    else:
        centers = [
            (w * 0.50, h * 0.19),
            (w * 0.50, h * 0.345),
            (w * 0.50, h * 0.50),
            (w * 0.50, h * 0.655),
        ]
        tilts = (-1.2, 1.2, -1.0, 1.1)
        card_w, card_h = w - 130.0, 236.0

    if is_wide:
        # Place thumbtack pins cleanly on the INNER edges of the 2x2 cards so glowing #FF2E93 strings
        # weave dramatically across the open central corridor with generous clearance from card text!
        pin_coords = [
            (centers[0][0] + card_w * 0.478, centers[0][1] + card_h * 0.10),
            (centers[1][0] - card_w * 0.478, centers[1][1] + card_h * 0.10),
            (centers[2][0] + card_w * 0.478, centers[2][1] - card_h * 0.12),
            (centers[3][0] - card_w * 0.478, centers[3][1] - card_h * 0.12),
        ][: len(nodes)]
    else:
        pin_coords = [(cx + (card_w * 0.465 if i % 2 == 0 else -card_w * 0.465), cy) for i, (cx, cy) in enumerate(centers[: len(nodes)])]

    # 1. Draw Polaroid-Mounted Obsidian Evidence Cards
    for idx, nd in enumerate(nodes):
        cx, cy = centers[idx]
        ent = _ease_out_back(max(0.0, min(1.0, (body_t - idx * 0.07) / 0.38)))
        sc = 0.86 + 0.14 * ent

        canvas.save()
        canvas.translate(cx, cy)
        canvas.rotate(tilts[idx])
        canvas.scale(sc, sc)

        rx = -card_w * 0.5
        ry = -card_h * 0.5
        c_rect = skia.Rect.MakeXYWH(rx, ry, card_w, card_h)
        c_rr = skia.RRect.MakeRectXY(c_rect, 16.0, 16.0)

        bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(232, 16, 13, 30))
        bg.setImageFilter(skia.ImageFilters.DropShadow(0, 18, 34, 34, skia.ColorSetARGB(215, 0, 0, 0)))
        canvas.drawRRect(c_rr, bg)

        b_col = hex_to_skia("#FF2E93" if idx % 2 == 0 else "#FFD166")
        canvas.drawRRect(c_rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.8, Color=b_col))

        # Left Polaroid Evidence Photo Frame (distinct REAL photograph per node; extra left inset on right-column cards to clear pin!)
        pol_w = 198.0 if is_wide else 184.0
        pol_h = card_h - 34.0
        pol_x = rx + (28.0 if (is_wide and idx % 2 == 1) else 18.0)
        pol_y = ry + 17.0
        pol_rect = skia.Rect.MakeXYWH(pol_x, pol_y, pol_w, pol_h)

        # Warm off-white Polaroid matte frame with slight opposing tilt for authentic tack-board depth
        canvas.save()
        canvas.translate(pol_rect.centerX(), pol_rect.centerY())
        canvas.rotate(-2.2 if idx % 2 == 0 else 2.0)
        p_local = skia.Rect.MakeXYWH(-pol_w * 0.5, -pol_h * 0.5, pol_w, pol_h)
        pol_paper = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 245, 240, 230))
        pol_paper.setImageFilter(skia.ImageFilters.DropShadow(0, 8, 16, 16, skia.ColorSetARGB(170, 0, 0, 0)))
        canvas.drawRoundRect(p_local, 6.0, 6.0, pol_paper)

        # Inner real photo cutout inside Polaroid frame
        img_pad = 9.0
        img_bot_pad = 32.0
        img_r = skia.Rect.MakeXYWH(
            -pol_w * 0.5 + img_pad,
            -pol_h * 0.5 + img_pad,
            pol_w - img_pad * 2.0,
            pol_h - img_pad - img_bot_pad,
        )
        if photo_pool:
            node_img = photo_pool[idx % len(photo_pool)]
            canvas.save()
            canvas.clipRect(img_r)
            canvas.drawImageRect(node_img, img_r, _LINEAR_SAMPLING)
            canvas.restore()
            canvas.drawRect(img_r, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0, Color=skia.ColorSetARGB(120, 40, 35, 45)))
        else:
            canvas.drawRect(img_r, skia.Paint(Color=skia.ColorSetARGB(255, 34, 30, 50)))

        # Crisp typed evidence stamp at bottom of Polaroid
        ev_stamp = f"EXHIBIT #{idx + 1:02d}" if is_en else f"PROVA #{idx + 1:02d}"
        st_font = skia.Font(ui_tf, 13.5)
        st_w = float(st_font.measureText(ev_stamp))
        _draw_safe_string(
            canvas,
            ev_stamp,
            -st_w * 0.5,
            pol_h * 0.5 - 10.0,
            st_font,
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 30, 25, 38)),
        )
        canvas.restore()

        # Right Obsidian Node Text Info (extra right-side padding on left-column cards so text stays generously clear of the pink pin!)
        tx = pol_x + pol_w + 22.0
        right_pin_pad = 58.0 if (idx % 2 == 0) else 28.0
        tw_max = max(120.0, (rx + card_w - right_pin_pad) - tx)

        b_font, b_lns = _wrap_text_to_width(nd.badge.upper(), ui_tf, 19.0, 13.5, tw_max, 1)
        if b_lns:
            _draw_safe_string(canvas, b_lns[0], tx, ry + 54.0, b_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

        t_font, t_lns = _wrap_text_to_width(nd.title.upper(), title_tf, 32.0, 20.0, tw_max, 2)
        ty_n = ry + 106.0
        for tln in t_lns:
            _draw_safe_string(canvas, tln, tx, ty_n, t_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            ty_n += t_font.getSize() * 1.15

        r_font, r_lns = _wrap_text_to_width(nd.role, ui_tf, 21.0, 15.0, tw_max, 2)
        ry_n = max(ty_n + 10.0, ry + card_h - 68.0)
        for rln in r_lns:
            if ry_n > ry + card_h - 14.0:
                break
            _draw_safe_string(canvas, rln, tx, ry_n, r_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
            ry_n += r_font.getSize() * 1.24

        canvas.restore()

    # 2. Draw Glowing Red/Pink Investigative Strings (#FF2E93) connecting the pins!
    edges = [(0, 1), (0, 2), (1, 3), (2, 3), (0, 3), (1, 2)]
    str_glow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=11.0,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(125, 255, 46, 147),
    )
    str_glow.setImageFilter(skia.ImageFilters.Blur(7, 7))
    str_core = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4.5,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=hex_to_skia("#FF2E93"),
    )

    for e_idx, (i0, i1) in enumerate(edges):
        if i0 >= len(pin_coords) or i1 >= len(pin_coords):
            continue
        p0 = pin_coords[i0]
        p1 = pin_coords[i1]
        edge_prog = _ease_out_cubic(min(1.0, max(0.25, (prog * 1.95) - e_idx * 0.08)))
        mx_e = p0[0] + (p1[0] - p0[0]) * edge_prog
        my_e = p0[1] + (p1[1] - p0[1]) * edge_prog
        ctrl_x = (p0[0] + mx_e) * 0.5
        ctrl_y = (p0[1] + my_e) * 0.5 + 32.0

        sp = skia.Path()
        sp.moveTo(p0[0], p0[1])
        sp.quadTo(ctrl_x, ctrl_y, mx_e, my_e)
        canvas.drawPath(sp, str_glow)
        canvas.drawPath(sp, str_core)

    # Metallic Thumbtacks pinned at the top center of each evidence card
    for px_p, py_p in pin_coords:
        canvas.drawCircle(px_p, py_p + 3.0, 12.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(140, 0, 0, 0)))
        canvas.drawCircle(px_p, py_p, 11.5, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FF2E93")))
        canvas.drawCircle(px_p - 2.5, py_p - 2.5, 4.2, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))


# ---------------------------------------------------------------------------
# 6. Sleek Chapter Cards, Lower Thirds & Widescreen Cinema Subtitles
# ---------------------------------------------------------------------------
def _draw_chapter_card_overlay(
    canvas: skia.Canvas,
    w: int,
    h: int,
    chapter_title: str,
    chapter_subtitle: str,
    local_t: float,
    chapter_dur: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
) -> None:
    """Render full-screen Netflix / MagnatesMedia wide letter-spaced Chapter Card ('C A P Í T U L O   I') over darkened moving B-roll."""
    fade_in = _ease_out_cubic(local_t / 0.25)
    fade_out = _ease_out_cubic((chapter_dur - local_t) / 0.28) if (chapter_dur - local_t) < 0.28 else 1.0
    alpha = int(255 * min(fade_in, fade_out))
    if alpha <= 6:
        return

    # Translucent dark veil lets real moving B-roll / archival painting breathe behind the chapter reveal (~150 combined scrim)
    canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.ColorSetARGB(int(alpha * 0.48), 9, 12, 18)))

    # Expanding golden horizontal cinema divider lines
    line_w = (w * 0.46) * _ease_out_cubic(local_t / 0.75)
    line_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
    canvas.drawLine(w * 0.5 - line_w * 0.5, h * 0.43, w * 0.5 + line_w * 0.5, h * 0.43, line_p)
    canvas.drawLine(w * 0.5 - line_w * 0.5, h * 0.59, w * 0.5 + line_w * 0.5, h * 0.59, line_p)

    # Wide letter-spaced C A P Í T U L O     I (preserving generous multi-space gap before Roman numeral!)
    clean_ct = _sanitize_glyphs(chapter_title, typeface=title_tf, preserve_spacing=True)
    # Guarantee generous visual gap before Roman numeral even if caller passed tighter spacing
    clean_ct = re.sub(r"(C A P Í T U L O)\s+([IVX])", r"\1     \2", clean_ct)
    clean_ct = re.sub(r"(C H A P T E R)\s+([IVX])", r"\1     \2", clean_ct)
    if clean_ct:
        max_ct_w = w - 160.0
        ct_size = 58.0
        c_font = skia.Font(title_tf, ct_size)
        while ct_size > 26.0 and float(c_font.measureText(clean_ct)) > max_ct_w:
            ct_size -= 2.5
            c_font = skia.Font(title_tf, ct_size)
        cw = float(c_font.measureText(clean_ct))
        cp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 209, 102))
        cp.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 24, 24, skia.ColorSetARGB(int(alpha * 0.65), 255, 209, 102)))
        _draw_safe_string(canvas, clean_ct, (w - cw) * 0.5, h * 0.39, c_font, cp, preserve_spacing=True)

    if chapter_subtitle:
        clean_sub = _sanitize_glyphs(_normalize_upper(chapter_subtitle), typeface=ui_tf)
        s_font, s_lns = _wrap_text_to_width(clean_sub, ui_tf, 42.0, 24.0, w - 180.0, 1)
        if s_lns:
            sw = float(s_font.measureText(s_lns[0]))
            _draw_safe_string(canvas, s_lns[0], (w - sw) * 0.5, h * 0.53, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 255, 255)))


def _draw_sleek_lower_third(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene: NetflixDocScene,
    local_t: float,
    scene_dur: float,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    max_display_s: float = 3.8,
) -> None:
    """Draw sleek investigative documentary Lower Third in mobile safe-zone (`y=192px`, `+38%` larger text,
    tight auto-fitted pill width) by delegating to `draw_pro_safezone_lower_third` (with safe-zone fallback).
    """
    if draw_pro_safezone_lower_third is not None:
        draw_pro_safezone_lower_third(
            canvas,
            w,
            h,
            scene.lower_third_title,
            scene.lower_third_subtitle,
            local_t,
            scene_dur,
            title_tf,
            ui_tf,
            max_display_s=max_display_s,
        )
        return

    vis_dur = min(scene_dur, max_display_s)
    if local_t >= vis_dur:
        return
    enter = _ease_out_cubic(local_t / 0.35)
    exit_a = _ease_out_cubic((vis_dur - local_t) / 0.35) if (vis_dur - local_t) < 0.35 else 1.0
    alpha = int(242 * min(enter, exit_a))
    if alpha <= 10:
        return

    is_wide = w >= h
    max_avail_w = (w * 0.62) if is_wide else (w - 92.0)
    lt_title_clean = _sanitize_glyphs(_normalize_upper(scene.lower_third_title), typeface=title_tf)
    t_font, t_lns = _wrap_text_to_width(lt_title_clean, title_tf, 35.0, 22.0, max_avail_w - 56.0, 1)
    t_str = t_lns[0] if t_lns else ""
    t_w = float(t_font.measureText(t_str)) if t_str else 0.0

    lt_sub_clean = _sanitize_glyphs(_normalize_upper(scene.lower_third_subtitle), typeface=ui_tf)
    s_font, s_lns = _wrap_text_to_width(lt_sub_clean, ui_tf, 25.0, 16.0, max_avail_w - 56.0, 1)
    s_str = s_lns[0] if s_lns else ""
    s_w = float(s_font.measureText(s_str)) if s_str else 0.0

    box_w = max(240.0, min(max_avail_w, max(t_w, s_w) + 56.0))
    box_h = 104.0
    bx = (68.0 if is_wide else 46.0) + (1.0 - enter) * -32.0
    by = (h * 0.728) if is_wide else 192.0

    r = skia.Rect.MakeXYWH(bx, by, box_w, box_h)
    bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.90), 12, 9, 22))
    bg.setImageFilter(skia.ImageFilters.DropShadow(0, 10, 20, 20, skia.ColorSetARGB(int(alpha * 0.75), 0, 0, 0)))
    canvas.drawRoundRect(r, 14.0, 14.0, bg)

    # Vertical glowing accent bar on left edge
    bar_r = skia.Rect.MakeXYWH(bx, by + 10.0, 8.0, box_h - 20.0)
    canvas.drawRoundRect(bar_r, 4.0, 4.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(scene.highlight_color, alpha)))

    if t_str:
        _draw_safe_string(canvas, t_str, bx + 26.0, by + 44.0, t_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", alpha)))
    if s_str:
        _draw_safe_string(canvas, s_str, bx + 26.0, by + 81.0, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 244, 239, 230)))


def _draw_doc_subtitles(
    canvas: skia.Canvas,
    w: int,
    h: int,
    chunks: List[Dict[str, Any]],
    t: float,
    caption_tf: skia.Typeface,
    caption_style: str = "cinema_minimal",
    mood: str = "dark_horror",
) -> None:
    """Render studio-grade kinetic documentary subtitles via `engine.kinetic_captions.draw_kinetic_captions`
    using `DARK_CINEMA_PILL_PALETTE` (`#9E1B24` crimson, `#FFD166` gold, `#D97706` amber) when
    `mood in ('dark_horror', 'epic_history', 'investigative_crime')`.
    """
    resolved_style = (
        resolve_caption_style(caption_style)
        if resolve_caption_style is not None
        else str(caption_style or "cinema_minimal").strip().lower()
    )
    if resolved_style == "none":
        return

    is_wide = w >= h
    norm_mood = str(mood or "dark_horror").strip().lower()
    active_palette = (
        DARK_CINEMA_PILL_PALETTE
        if norm_mood in ("dark_horror", "epic_history", "investigative_crime")
        else ACTIVE_PILL_PALETTE
    )

    # Contrast lower-third cinema scrim so kinetic captions stay razor-sharp over moving footage
    scrim = skia.Paint()
    scrim.setShader(
        skia.GradientShader.MakeLinear(
            [(0, h * 0.80), (0, h)],
            [skia.ColorSetARGB(0, 11, 7, 19), skia.ColorSetARGB(210, 11, 7, 19)],
        )
    )
    canvas.drawRect(skia.Rect.MakeXYWH(0, h * 0.80, w, h * 0.20), scrim)

    if draw_kinetic_captions is not None:
        draw_kinetic_captions(
            canvas=canvas,
            chunks=chunks,
            t=t,
            w=w,
            h=h,
            typeface=caption_tf,
            style=resolved_style,
            y_ratio=0.905 if is_wide else 0.84,
            font_size=58.0 if is_wide else 72.0,
            palette=active_palette,
        )
        return

    # Built-in fallback if kinetic_captions module is unavailable
    base_size = 58.0 if is_wide else 72.0
    cap_font = skia.Font(caption_tf, base_size)
    space_w = max(24.0, float(cap_font.measureText(" ")) * 1.42)
    fm = cap_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    for ch in chunks:
        if ch["start"] <= t <= ch["end"]:
            w_list = ch["words"]
            active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
            pad_x, pad_y = 22.0, 10.0
            toks = []
            tot_w = 0.0
            for wd in w_list:
                txt = _sanitize_glyphs(_clean_doc_text(wd["word"]).upper(), typeface=caption_tf)
                if not txt:
                    continue
                is_act = wd is active_wd
                sc = 1.10 if is_act else 1.0
                tw = float(cap_font.measureText(txt))
                sw = (tw + pad_x * 2.0) * sc if is_act else tw
                toks.append({"txt": txt, "w": tw, "sw": sw, "act": is_act, "sc": sc, "pidx": int(wd.get("g_idx", 0))})
                tot_w += sw
            if toks:
                tot_w += space_w * (len(toks) - 1)
                max_line_w = w * 0.84
                lscale = min(1.0, max_line_w / max(1.0, tot_w))
                cap_y = h * (0.905 if is_wide else 0.84)
                canvas.save()
                canvas.translate(w * 0.5, cap_y)
                canvas.scale(lscale, lscale)
                cx_pos = -tot_w * 0.5
                pos_map = {}
                for tk in toks:
                    pos_map[id(tk)] = cx_pos + tk["sw"] * 0.5
                    cx_pos += tk["sw"] + space_w
                for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                    canvas.save()
                    canvas.translate(pos_map[id(tk)], 0.0)
                    if tk["act"]:
                        canvas.scale(tk["sc"], tk["sc"])
                        pbg, ptx, (gr, gg, gb, ga) = active_palette[tk["pidx"] % len(active_palette)]
                        pr = skia.Rect.MakeXYWH(-tk["w"] * 0.5 - pad_x, -ascent - pad_y, tk["w"] + pad_x * 2.0, ascent + descent + pad_y * 2.0)
                        pp = skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg))
                        pp.setImageFilter(skia.ImageFilters.DropShadow(0, 6, 16, 16, skia.ColorSetARGB(ga, gr, gg, gb)))
                        canvas.drawRoundRect(pr, 18.0, 18.0, pp)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                    else:
                        stp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=10.0, StrokeJoin=skia.Paint.kRound_Join, Color=skia.ColorSetARGB(255, 8, 5, 14))
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, stp)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                    canvas.restore()
                canvas.restore()
            break


# ---------------------------------------------------------------------------
# 7. Scene-by-Scene Documentary Render Engine (Real Video + PiP + Photos + Flat RAM)
# ---------------------------------------------------------------------------
GRAPHIC_BOOKEND_MODES: Tuple[VisualModeType, ...] = (
    "newspaper_highlighter",
    "dark_map_route",
    "sliding_timeline",
    "red_string_board",
    "2d_schematic_over_realism",
    "video_over_video_collage",
    "fern_3d_reconstruction",
)


def _compute_bookended_graphic_window(
    visual_mode: str,
    body_dur: float,
    n_shot_layers: int,
    cut_cadence_s: float = 2.6,
) -> Optional[Tuple[float, float, int]]:
    """Return `(g_start, g_end, pre_count)` when a graphic mode bookends its centerpiece with cinema shots, else `None`.
    Shared between `_render_single_doc_scene_to_disk` and SFX scheduling so graphic foley aligns to the exact frame!
    """
    if visual_mode not in GRAPHIC_BOOKEND_MODES or body_dur <= 7.2 or n_shot_layers < 2:
        return None
    # Give timelines / string boards / 3D reconstructions comfortable breathing room in 38-42s scenes (~8-12s),
    # while staying snappy (~4.8-6.4s) in shorter 10-15s scenes.
    g_dur = min(11.5, max(5.2, body_dur * 0.34))
    pre_dur = max(2.4, min(7.5, (body_dur - g_dur) * 0.36))
    g_start = pre_dur
    g_end = min(body_dur - 2.0, g_start + g_dur)
    pre_count = max(1, min(n_shot_layers - 1, int(round(pre_dur / max(2.0, float(cut_cadence_s or 2.6))))))
    return g_start, g_end, pre_count


def _active_slice_layer(
    layers: List[Tuple[str, Any]],
    slice_t: float,
    slice_dur: float,
) -> Optional[Tuple[str, Any]]:
    """Return the exact layer tuple active at `slice_t` inside `_draw_unique_shot_slice`."""
    if not layers:
        return None
    n_shots = len(layers)
    shot_dur = max(0.8, slice_dur / float(n_shots))
    shot_idx = min(n_shots - 1, max(0, int(slice_t / shot_dur)))
    return layers[shot_idx]


def _extract_skia_image_from_shot_layer(
    layer: Optional[Tuple[str, Any]],
    primary_frame: Optional[skia.Image],
) -> Optional[skia.Image]:
    """Return a static or decoded Skia Image from a shot_layers entry."""
    if layer is None:
        return primary_frame
    kind, payload = layer
    if kind == "photo_25d" and isinstance(payload, tuple) and len(payload) >= 1 and payload[0] is not None:
        return payload[0]
    if kind == "photo_still" and payload is not None:
        return payload
    return primary_frame


def _layer_needs_primary_video(layer: Optional[Tuple[str, Any]]) -> bool:
    """Return False when `layer` is a self-contained static/2.5D photo so H.264 B-roll decoding can be skipped."""
    if layer is None:
        return True
    kind, payload = layer
    if kind == "photo_still":
        return payload is None
    if kind == "photo_25d":
        return not (isinstance(payload, tuple) and len(payload) == 2 and payload[0] is not None)
    return True


def _load_scene_skia_photos(
    scene: NetflixDocScene,
    assets: SceneMediaAssets,
    w: int,
    h: int,
) -> LoadedSceneSkiaMedia:
    """Pre-load real & bespoke Google Flow photographs into Skia Images once before the 30fps loop (zero per-frame I/O)."""
    loaded = LoadedSceneSkiaMedia()
    is_wide = w >= h
    primary_resolved: Optional[Path] = None
    if assets.primary_photo_path is not None:
        try:
            primary_resolved = Path(assets.primary_photo_path).resolve()
        except Exception:
            primary_resolved = Path(assets.primary_photo_path)

    # 1. Load every UNIQUE shot in assets.shot_sequence (ZERO modulo wrap-around!)
    # Apply genuine u2netp 2.5D foreground/background separation to up to 2 hero photo shots per scene!
    parallax_budget = 2 if scene.visual_mode in ("cinema_multishot", "parallax_25d_photo") else 1
    used_parallax = 0
    for kind, media_path in (assets.shot_sequence or []):
        if kind == "video":
            loaded.shot_layers.append(("video_primary", None))
        elif kind == "photo" and media_path is not None and Path(media_path).exists():
            is_primary_match = False
            if primary_resolved is not None:
                try:
                    is_primary_match = Path(media_path).resolve() == primary_resolved
                except Exception:
                    is_primary_match = Path(media_path) == primary_resolved
            if used_parallax < parallax_budget:
                bg_img, fg_img = separate_photo_25d_u2netp(media_path, w, h)
                bg_img = _pregrade_skia_image(bg_img)
                fg_img = _pregrade_skia_image(fg_img)
                if bg_img is not None:
                    loaded.shot_layers.append(("photo_25d", (bg_img, fg_img)))
                    if is_primary_match and loaded.primary_photo_layer_idx is None:
                        loaded.primary_photo_layer_idx = len(loaded.shot_layers) - 1
                    if loaded.parallax_bg is None:
                        loaded.parallax_bg = bg_img
                        loaded.parallax_fg = fg_img
                    if fg_img is not None:
                        loaded.u2netp_separated = True
                    used_parallax += 1
                    continue
            still_img = _pregrade_skia_image(load_skia_image_cover(media_path, w, h))
            if still_img is not None:
                loaded.shot_layers.append(("photo_still", still_img))
                if is_primary_match and loaded.primary_photo_layer_idx is None:
                    loaded.primary_photo_layer_idx = len(loaded.shot_layers) - 1
                if loaded.parallax_bg is None:
                    loaded.parallax_bg = still_img

    # 2. Load mode-specific graphic card photos (newspaper inset, evidence board cards, timeline cards)
    if scene.visual_mode in ("parallax_25d_photo", "cinema_multishot") and assets.primary_photo_path is not None:
        if loaded.parallax_bg is not None:
            loaded.primary_photo = loaded.parallax_bg
        else:
            matte_w, matte_h = (w, h) if (scene.visual_mode == "cinema_multishot" or not is_wide) else (int(round(w * 0.76)), int(round(h * 0.61)))
            bg_img, fg_img = separate_photo_25d_u2netp(assets.primary_photo_path, matte_w, matte_h)
            if bg_img is not None:
                loaded.parallax_bg = bg_img
                loaded.parallax_fg = fg_img
                loaded.primary_photo = bg_img
                loaded.u2netp_separated = fg_img is not None
            else:
                loaded.primary_photo = load_skia_image_cover(assets.primary_photo_path, matte_w, matte_h)
    elif assets.primary_photo_path is not None:
        if scene.visual_mode == "newspaper_highlighter":
            # Balanced ~1.40:1 editorial aspect with top-weighted crop so faces/horns are NEVER decapitated!
            pw, ph = (600, 420) if is_wide else (848, 606)
            loaded.primary_photo = _load_skia_image_cover_biased(
                assets.primary_photo_path,
                pw,
                ph,
                y_bias=0.16 if is_wide else 0.14,
            )
        else:
            if scene.visual_mode == "video_pip_evidence":
                pw, ph = (760, 340) if is_wide else (880, 340)
            elif scene.visual_mode == "broll_video_pip":
                pw, ph = (720, 240) if is_wide else (860, 260)
            else:
                pw, ph = (640, 400)
            loaded.primary_photo = load_skia_image_cover(assets.primary_photo_path, pw, ph)

    if assets.extra_photo_paths:
        if scene.visual_mode == "cinema_multishot":
            ew, eh = w, h
        elif scene.visual_mode == "video_over_video_collage":
            ew, eh = (760, 520) if is_wide else (840, 480)
        elif scene.visual_mode == "red_string_board":
            ew, eh = (320, 320) if is_wide else (260, 260)
        elif scene.visual_mode == "sliding_timeline":
            ew, eh = (520, 260) if is_wide else (260, 220)
        else:
            ew, eh = (560, 360)
        for ep in assets.extra_photo_paths:
            img = load_skia_image_cover(ep, ew, eh)
            if img is not None:
                loaded.extra_photos.append(img)

    return loaded


def _compute_pip_dimensions(visual_mode: VisualModeType, is_wide: bool) -> Tuple[int, int]:
    if visual_mode == "cinema_multishot":
        return (1920, 1080) if is_wide else (1080, 1920)
    if visual_mode == "video_over_video_collage":
        return (860, 540) if is_wide else (840, 472)
    if visual_mode == "broll_video_pip":
        return (780, 440) if is_wide else (908, 512)
    if visual_mode == "dark_map_route":
        return (570, 330) if is_wide else (780, 438)
    if visual_mode == "video_pip_evidence":
        return (390, 220) if is_wide else (360, 202)
    return (620, 350)


def _render_single_doc_scene_to_disk(
    scene: NetflixDocScene,
    s_idx: int,
    scene_dur: float,
    chapter_intro_s: float,
    scene_words: List[Dict[str, Any]],
    global_t_offset: float,
    total_est_dur: float,
    out_scene_mp4: Path,
    w: int,
    h: int,
    fps: int,
    lut_path: Path,
    title_tf: skia.Typeface,
    ui_tf: skia.Typeface,
    caption_tf: skia.Typeface,
    thermal_limit_c: float,
    media_assets: Optional[SceneMediaAssets] = None,
    lang: str = "pt_br",
    caption_style: str = "selective_emphasis",
    cut_cadence_s: float = 2.6,
    prev_lower_third_title: Optional[str] = None,
    abrupt_cut_black_at_local_t: Optional[float] = None,
) -> Tuple[Path, bool]:
    """Render one documentary scene at 30fps in C++ Skia directly to disk with zero-copy BGRA surface
    (`MakeRasterDirect` + `memoryview`), direct VAAPI hardware encode (65-160+ FPS, zero CPU lut3d/noise bottleneck),
    0.85x slow-motion atmospheric B-roll, unified `master_color_grade` C++ ColorMatrix, 35mm film grain,
    and all 5 Mixed-Media documentary visual categories!
    """
    try:
        os.nice(10)
    except OSError:
        pass
    thermal_guard_wait(limit_c=thermal_limit_c)

    assets = media_assets or SceneMediaAssets()
    is_en = str(lang).lower().startswith("en")
    is_wide = w >= h

    # Pre-load static Skia photos / u2netp 2.5D layers once before frame loop
    loaded_media = _load_scene_skia_photos(scene, assets, w, h)

    # Open sequential low-RAM VideoLayerReaders at 0.85x atmospheric slow-motion playback!
    primary_reader: Optional[VideoLayerReader] = None
    pip_reader: Optional[VideoLayerReader] = None
    if assets.primary_broll_mp4 is not None and Path(assets.primary_broll_mp4).exists():
        primary_reader = VideoLayerReader(assets.primary_broll_mp4, w, h, fps=fps, playback_speed=0.85)
    if scene.visual_mode in PIP_ENABLED_MODES and assets.pip_broll_mp4 is not None and Path(assets.pip_broll_mp4).exists():
        pip_w, pip_h = _compute_pip_dimensions(scene.visual_mode, is_wide)
        pip_reader = VideoLayerReader(assets.pip_broll_mp4, pip_w, pip_h, fps=fps, playback_speed=0.85)

    # Zero-copy BGRA Skia surface backed directly by a NumPy array (exact kBGRA_8888 matches FFmpeg -pix_fmt bgra!)
    frame_buf = np.zeros((h, w, 4), dtype=np.uint8)
    surf_info = skia.ImageInfo.Make(
        w,
        h,
        skia.ColorType.kBGRA_8888_ColorType,
        skia.AlphaType.kPremul_AlphaType,
    )
    surface = skia.Surface.MakeRasterDirect(surf_info, frame_buf)
    if surface is None:
        surface = skia.Surface(w, h)
        frame_mv = None
    else:
        frame_mv = memoryview(frame_buf)

    chunks = group_words_into_chunks(scene_words, max_words=3)
    total_frames = max(1, int(round(scene_dur * fps)))
    exact_dur = total_frames / float(fps)
    body_dur = max(0.5, exact_dur - chapter_intro_s)
    eff_cadence = float(getattr(scene, "cut_cadence_s", None) or cut_cadence_s or 2.6)

    # Precompute bookended graphic window & non-repeating pre/post layers ONCE before frame loop
    bookend_win = _compute_bookended_graphic_window(
        scene.visual_mode,
        body_dur,
        len(loaded_media.shot_layers),
        cut_cadence_s=eff_cadence,
    )
    use_bookended_graphic = bookend_win is not None
    g_start = 0.0
    g_end = 0.0
    pre_layers: List[Tuple[str, Any]] = []
    post_layers: List[Tuple[str, Any]] = []
    chapter_backdrop_layer: Optional[Tuple[str, Any]] = None
    graphic_backdrop_layer: Optional[Tuple[str, Any]] = None
    if chapter_intro_s > 0.0 and len(loaded_media.shot_layers) >= 2:
        chapter_backdrop_layer = loaded_media.shot_layers[-1]

    if bookend_win is not None:
        g_start, g_end, pre_count = bookend_win
        card_photo_idx = loaded_media.primary_photo_layer_idx
        if card_photo_idx is None and scene.visual_mode == "newspaper_highlighter":
            for i_l, (k_l, _) in enumerate(loaded_media.shot_layers):
                if k_l in ("photo_25d", "photo_still"):
                    card_photo_idx = i_l
                    break
        if scene.visual_mode == "newspaper_highlighter" and card_photo_idx is not None:
            non_card_layers = [
                lyr for i_l, lyr in enumerate(loaded_media.shot_layers)
                if i_l != card_photo_idx
            ]
            if len(non_card_layers) >= 2:
                eff_pre = max(1, min(len(non_card_layers) - 1, int(round(g_start / max(2.0, eff_cadence)))))
                pre_layers = non_card_layers[:eff_pre]
                post_layers = non_card_layers[eff_pre:] or non_card_layers[-1:]
            elif len(non_card_layers) == 1:
                pre_layers = loaded_media.shot_layers[:pre_count]
                post_layers = non_card_layers
            else:
                pre_layers = loaded_media.shot_layers[:pre_count]
                post_layers = loaded_media.shot_layers[pre_count:] or loaded_media.shot_layers[-1:]
        else:
            pre_layers = loaded_media.shot_layers[:pre_count]
            post_layers = loaded_media.shot_layers[pre_count:] or loaded_media.shot_layers[-1:]

        if len(loaded_media.shot_layers) >= 2:
            if chapter_intro_s > 0.0 and not pre_layers:
                pre_layers = [loaded_media.shot_layers[0]]
            pre_first = pre_layers[0] if pre_layers else loaded_media.shot_layers[0]
            for cand_lyr in loaded_media.shot_layers:
                if cand_lyr is not pre_first and cand_lyr is not chapter_backdrop_layer:
                    graphic_backdrop_layer = cand_lyr
                    break
            if graphic_backdrop_layer is None:
                for cand_lyr in loaded_media.shot_layers:
                    if cand_lyr is not pre_first:
                        graphic_backdrop_layer = cand_lyr
                        break

    # Show sleek Lower-Third on Scene 0, Chapter Starts, ANY Location/Era Change, or every 4th scene
    cur_lt_norm = _normalize_upper(_clean_doc_text(scene.lower_third_title))
    prev_lt_norm = _normalize_upper(_clean_doc_text(prev_lower_third_title or "")) if prev_lower_third_title is not None else ""
    location_changed = bool(cur_lt_norm) and (prev_lower_third_title is not None) and (cur_lt_norm != prev_lt_norm)
    show_lower_third = (
        s_idx == 0
        or scene.chapter_card is not None
        or location_changed
        or (s_idx % 4 == 0)
    )

    # Direct VAAPI hardware suffix (zero CPU lut3d+blend and zero CPU noise bottleneck -> 65-160+ FPS!)
    # Master color grade (+12% contrast, -22% sat, #0D1B2A/#E0C097), 35mm grain & vignette run inside C++ Skia!
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    vf_chain = hw_suffix

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-vf",
        vf_chain,
        "-t",
        f"{exact_dur:.4f}",
        *enc_args,
        "-an",
        str(out_scene_mp4),
    ]

    ffmpeg_err_path = out_scene_mp4.parent / f"ffmpeg_sc{s_idx:03d}.err"
    err_fh = open(ffmpeg_err_path, "wb")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=err_fh,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
    )
    assert proc.stdin is not None

    primary_darken = 0.16 if scene.visual_mode in ("broll_video_pip", "parallax_25d_photo") else 0.0

    # Pre-build slim 3px archival crimson-gold progress bar paint (replaces neon pink/lime bar!)
    prog_bar_paint = skia.Paint(AntiAlias=True)
    prog_bar_paint.setShader(
        skia.GradientShader.MakeLinear(
            [(0, 0), (w, 0)],
            [hex_to_skia("#D9381E", 170), hex_to_skia("#EAB308", 170)],
        )
    )

    try:
        for fi in range(total_frames):
            local_t = fi / float(fps)
            global_t = global_t_offset + local_t
            c = surface.getCanvas()

            # ACT_4_ABRUPT_ENDING: Hard cut to black cleanly after final spoken beat + 0.50s
            if abrupt_cut_black_at_local_t is not None and local_t >= abrupt_cut_black_at_local_t:
                c.clear(skia.ColorBLACK)
                proc.stdin.write(frame_mv if frame_mv is not None else surface.makeImageSnapshot().tobytes())
                continue

            in_chapter_intro = chapter_intro_s > 0.0 and local_t < chapter_intro_s
            body_t = 0.0 if in_chapter_intro else max(0.0, local_t - chapter_intro_s)

            # Skip H.264 video decoding on frames where a static/2.5D photo shot is active (3x+ CPU speedup!)
            need_primary_video = False
            need_pip_video = False
            if in_chapter_intro:
                need_primary_video = _layer_needs_primary_video(chapter_backdrop_layer) if chapter_backdrop_layer is not None else True
            elif use_bookended_graphic:
                if body_t < g_start:
                    active_lyr = _active_slice_layer(pre_layers, body_t, g_start)
                    need_primary_video = _layer_needs_primary_video(active_lyr)
                    need_pip_video = (active_lyr is not None and active_lyr[0] == "video_secondary")
                elif body_t >= g_end:
                    active_lyr = _active_slice_layer(post_layers, body_t - g_end, max(0.4, body_dur - g_end))
                    need_primary_video = _layer_needs_primary_video(active_lyr)
                    need_pip_video = (active_lyr is not None and active_lyr[0] == "video_secondary")
                else:
                    need_primary_video = _layer_needs_primary_video(graphic_backdrop_layer) if graphic_backdrop_layer is not None else True
                    need_pip_video = scene.visual_mode in ("dark_map_route", "video_over_video_collage")
            elif scene.visual_mode in ("cinema_multishot", "parallax_25d_photo"):
                if loaded_media.shot_layers:
                    active_lyr = _active_slice_layer(loaded_media.shot_layers, body_t, body_dur)
                    need_primary_video = _layer_needs_primary_video(active_lyr)
                    need_pip_video = (active_lyr is not None and active_lyr[0] == "video_secondary")
                else:
                    need_primary_video = (
                        scene.visual_mode == "cinema_multishot"
                        or is_wide
                        or (loaded_media.parallax_bg is None and loaded_media.primary_photo is None)
                    )
                    need_pip_video = (scene.visual_mode == "cinema_multishot")
            else:
                need_primary_video = True
                need_pip_video = (scene.visual_mode in PIP_ENABLED_MODES)

            primary_frame = (
                primary_reader.read_skia_frame(darken_alpha=primary_darken)
                if (need_primary_video and primary_reader is not None)
                else None
            )
            fallback_backdrop = primary_frame or loaded_media.parallax_bg or loaded_media.primary_photo
            chapter_backdrop = (
                _extract_skia_image_from_shot_layer(chapter_backdrop_layer, primary_frame)
                or loaded_media.parallax_bg
                or fallback_backdrop
            )
            graphic_backdrop = (
                _extract_skia_image_from_shot_layer(graphic_backdrop_layer, primary_frame)
                or fallback_backdrop
            )

            if in_chapter_intro:
                _draw_video_backdrop_layer(
                    c,
                    w,
                    h,
                    chapter_backdrop,
                    global_t,
                    local_t / max(0.1, chapter_intro_s),
                    scrim_alpha=84,
                    ken_burns_zoom=0.04,
                    show_grid=False,
                    show_dust=False,
                )
                _draw_visual_cohesion_unifier_overlay(c, w, h, fi, global_t, vignette_intensity=0.35, grain_opacity=0.14, dust_opacity=0.16)
                _draw_chapter_card_overlay(
                    c,
                    w,
                    h,
                    scene.chapter_card or _spaced_chapter_label("I", lang=lang),
                    scene.chapter_subtitle or "",
                    local_t,
                    chapter_intro_s,
                    title_tf,
                    ui_tf,
                )
            else:
                prog = min(1.0, body_t / body_dur)
                pip_frame = (
                    pip_reader.read_skia_frame(darken_alpha=0.0)
                    if (need_pip_video and pip_reader is not None)
                    else None
                )

                if use_bookended_graphic:
                    if body_t < g_start:
                        _draw_unique_shot_slice(
                            c, w, h, pre_layers, body_t, g_start, global_t, primary_frame, pip_frame,
                            s_idx=s_idx, scene=scene, title_tf=title_tf, allow_scene_depth_title=True,
                        )
                    elif body_t >= g_end:
                        _draw_unique_shot_slice(
                            c, w, h, post_layers, body_t - g_end, max(0.4, body_dur - g_end), global_t,
                            primary_frame, pip_frame, s_idx=s_idx + 1, cut_flash_on_first=True,
                            scene=scene, title_tf=title_tf, allow_scene_depth_title=False,
                        )
                    else:
                        g_t = body_t - g_start
                        g_prog = min(1.0, g_t / max(0.3, g_end - g_start))
                        if scene.visual_mode == "newspaper_highlighter":
                            _draw_mode_newspaper_highlighter(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                        elif scene.visual_mode == "dark_map_route":
                            _draw_mode_dark_map_route(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, pip_frame or graphic_backdrop, is_en=is_en)
                        elif scene.visual_mode == "sliding_timeline":
                            _draw_mode_sliding_timeline(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                        elif scene.visual_mode == "2d_schematic_over_realism":
                            _draw_mode_2d_schematic_over_realism(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                        elif scene.visual_mode == "video_over_video_collage":
                            _draw_mode_video_over_video_collage(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, pip_frame, loaded_media, is_en=is_en)
                        elif scene.visual_mode == "fern_3d_reconstruction":
                            _draw_mode_fern_3d_reconstruction(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media.parallax_fg, is_en=is_en)
                        else:
                            _draw_mode_red_string_board(c, w, h, scene, g_prog, g_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                        if g_t < 0.11:
                            ck = 1.0 - (g_t / 0.11)
                            c.drawRect(skia.Rect.MakeXYWH(0, 0, w, h), skia.Paint(Color=skia.ColorSetARGB(int(88 * (ck ** 1.6)), 224, 192, 151)))
                elif scene.visual_mode == "cinema_multishot":
                    _draw_mode_cinema_multishot(
                        c, w, h, scene, prog, body_t, body_dur, global_t, primary_frame, pip_frame, loaded_media,
                        cut_cadence_s=eff_cadence, s_idx=s_idx, title_tf=title_tf,
                    )
                elif scene.visual_mode == "broll_video_pip":
                    _draw_mode_broll_video_pip(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, fallback_backdrop, pip_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "video_pip_evidence":
                    _draw_mode_video_pip_evidence(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, fallback_backdrop, pip_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "newspaper_highlighter":
                    _draw_mode_newspaper_highlighter(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                elif scene.visual_mode == "dark_map_route":
                    _draw_mode_dark_map_route(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, pip_frame or graphic_backdrop, is_en=is_en)
                elif scene.visual_mode == "sliding_timeline":
                    _draw_mode_sliding_timeline(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                elif scene.visual_mode == "2d_schematic_over_realism":
                    _draw_mode_2d_schematic_over_realism(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                elif scene.visual_mode == "video_over_video_collage":
                    _draw_mode_video_over_video_collage(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, pip_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "fern_3d_reconstruction":
                    _draw_mode_fern_3d_reconstruction(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media.parallax_fg, is_en=is_en)
                elif scene.visual_mode == "red_string_board":
                    _draw_mode_red_string_board(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, graphic_backdrop, loaded_media, is_en=is_en)
                else:
                    _draw_mode_parallax_25d_photo(
                        c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, fallback_backdrop, loaded_media,
                        is_en=is_en, body_dur=body_dur, s_idx=s_idx,
                    )

                # Visual Cohesion Unifier Stack (vignette 0.35 + 35mm film grain 0.14 + dust motes 0.16)
                _draw_visual_cohesion_unifier_overlay(c, w, h, fi, global_t, vignette_intensity=0.35, grain_opacity=0.14, dust_opacity=0.16)

                if show_lower_third:
                    _draw_sleek_lower_third(c, w, h, scene, body_t, body_dur, title_tf, ui_tf, max_display_s=3.8)
                _draw_doc_subtitles(c, w, h, chunks, local_t, caption_tf, caption_style=caption_style, mood=scene.mood)

            # Subtle 3px archival crimson-gold progress thread (#D9381E -> #EAB308, alpha 170)
            bar_w = max(6.0, w * min(1.0, global_t / max(0.1, total_est_dur)))
            c.drawRect(skia.Rect.MakeXYWH(0.0, 0.0, bar_w, 3.0), prog_bar_paint)

            proc.stdin.write(frame_mv if frame_mv is not None else surface.makeImageSnapshot().tobytes())
    except BrokenPipeError:
        pass
    finally:
        if primary_reader is not None:
            primary_reader.close()
        if pip_reader is not None:
            pip_reader.close()
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=240)
        finally:
            try:
                err_fh.close()
            except Exception:
                pass

    if proc.returncode != 0:
        err_txt = ""
        try:
            err_txt = ffmpeg_err_path.read_text(encoding="utf-8", errors="ignore")[-4000:]
        except Exception:
            pass
        raise RuntimeError(f"NetflixDoc scene #{s_idx + 1} encode failed: {err_txt}")
    return out_scene_mp4, loaded_media.u2netp_separated


def _find_cached_work_asset(work_dir: Path, prefix: str, min_bytes: int = 4096) -> Optional[Path]:
    for cand in sorted(work_dir.glob(f"{prefix}_*")):
        try:
            if cand.exists() and cand.stat().st_size >= min_bytes:
                return cand
        except Exception:
            continue
    return None


def _find_cached_slot_photo(work_dir: Path, slot_key: str, min_bytes: int = 12_000) -> Optional[Path]:
    """Locate any cached bespoke Flow or archival photo for `slot_key` (`flow_{slot_key}*` OR `photo_{slot_key}*`)."""
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    for pattern in (f"flow_{slot_key}*", f"photo_{slot_key}*"):
        for cand in sorted(work_dir.glob(pattern)):
            try:
                if cand.is_file() and cand.suffix.lower() in valid_exts and cand.stat().st_size >= min_bytes:
                    return cand
            except Exception:
                continue
    return None


def _prefetch_scene_media_sync(
    scenes: List[NetflixDocScene],
    work_dir: Path,
    aspect_ratio: str,
    mood: str = "corporate_thriller",
    resume: bool = False,
    scene_shot_counts: Optional[List[int]] = None,
    skip_scene_indices: Optional[Set[int]] = None,
) -> Tuple[List[SceneMediaAssets], Dict[str, Any]]:
    """Cinema v5 Zero-Repetition + 100% Context-Verified Media Orchestrator:
      1. Skips already-rendered scenes (`skip_scene_indices`) completely on resume (zero wasted Flow/Vision calls!).
      2. Pre-screens atmospheric B-roll videos via Multimodal Gemini Vision Critic (score >= 7/10)
         BEFORE downloading (zero off-topic stock!).
      3. Batches ALL chronological per-phrase bespoke stills across unrendered scenes into ONE SINGLE
         logged-in Google Flow Pro (`Nano Banana 2.1`) session (native 9:16 / 16:9, vertical-safe prompts for 9:16),
         generating exact `scene_shot_counts[s_idx]` UNIQUE visuals per scene!
      4. Enforces global SHA256 + 64-bit perceptual `dhash` deduplication across the ENTIRE video
         so ZERO images or videos EVER repeat inside a scene or across scenes!
    """
    used_video_hashes: Set[str] = set()
    used_photo_urls: Set[str] = set()
    used_dhashes: Set[int] = set()
    skip_set: Set[int] = set(skip_scene_indices or ())
    is_vertical = str(aspect_ratio).strip() == "9:16"

    assets_list: List[SceneMediaAssets] = [SceneMediaAssets() for _ in scenes]
    broll_clips_used: List[str] = []
    pip_clips_used: List[str] = []
    photos_used: List[str] = []

    def _register_dhash(path: Path) -> bool:
        dh = compute_file_dhash(path)
        if is_perceptual_duplicate(dh, used_dhashes, max_hamming=8):
            return False
        if dh is not None:
            used_dhashes.add(dh)
        return True

    # -------------------------------------------------------------------------
    # PHASE A: Vision-Verified Atmospheric Moving HD B-Roll (at most 1 per scene;
    # if stock doesn't truly match >= 7/10, leave None -> upgraded to bespoke Flow art!)
    # -------------------------------------------------------------------------
    for s_idx, sc in enumerate(scenes):
        if s_idx in skip_set:
            continue
        item = assets_list[s_idx]
        sc_mood = str(getattr(sc, "mood", None) or mood or "corporate_thriller")
        mood_defaults = _OPEN_TOPIC_FALLBACK_MEDIA.get(sc_mood, _OPEN_TOPIC_FALLBACK_MEDIA["epic_history"])

        main_mp4 = _find_cached_work_asset(work_dir, f"broll_sc{s_idx:02d}_main", min_bytes=32_768) if resume else None
        if main_mp4 is None:
            broll_q = sc.broll_query_en or mood_defaults["broll"][s_idx % len(mood_defaults["broll"])]
            main_mp4 = fetch_doc_broll_clip(
                broll_q,
                work_dir,
                f"sc{s_idx:02d}_main",
                used_video_hashes,
                aspect_ratio=aspect_ratio,
                mood=sc_mood,
                scene_context=sc.narration,
                used_dhashes=used_dhashes,
                strict_vision=True,
            )
        if main_mp4 is not None:
            item.primary_broll_mp4 = main_mp4
            broll_clips_used.append(str(main_mp4))

        # Secondary PiP video ONLY for genuine PiP monitor modes (matches PIP_ENABLED_MODES exactly!)
        if sc.visual_mode in PIP_ENABLED_MODES:
            pip_mp4 = _find_cached_work_asset(work_dir, f"broll_sc{s_idx:02d}_pip", min_bytes=32_768) if resume else None
            if pip_mp4 is None:
                pip_q = sc.pip_broll_query_en or mood_defaults["pip"][s_idx % len(mood_defaults["pip"])]
                pip_mp4 = fetch_doc_broll_clip(
                    pip_q,
                    work_dir,
                    f"sc{s_idx:02d}_pip",
                    used_video_hashes,
                    aspect_ratio="16:9",
                    mood=sc_mood,
                    scene_context=sc.narration,
                    used_dhashes=used_dhashes,
                    strict_vision=True,
                )
            if pip_mp4 is not None:
                item.pip_broll_mp4 = pip_mp4
                pip_clips_used.append(str(pip_mp4))

    # -------------------------------------------------------------------------
    # PHASE B: Plan exact UNIQUE bespoke visual slots across ALL unrendered scenes & batch-generate
    # them in ONE SINGLE logged-in Google Flow Pro (`Nano Banana 2.1`) session!
    # -------------------------------------------------------------------------
    batch_items: List[Dict[str, Any]] = []
    # Track per-scene planned slots: list of (slot_key, role, prompt_en, fallback_query, out_path)
    scene_slot_specs: List[List[Dict[str, Any]]] = []
    global_used_prompts: Set[str] = set()

    if is_vertical:
        camera_angles = (
            "Vertical full-bleed 9:16 35mm cinema still showing",
            "Intimate vertical close-up detail shot focusing on",
            "Moody vertical nocturnal chiaroscuro candlelight scene depicting",
            "Haunting vertical low-angle dark historical documentary portrait of",
            "Tall atmospheric vertical silhouette in mist and shadow showing",
            "Cinematic vertical top-down archival mystery frame of",
        )
    else:
        camera_angles = (
            "dramatic wide establishing 35mm cinema still showing",
            "tense intimate close-up detail shot focusing on",
            "moody nocturnal chiaroscuro candlelight scene depicting",
            "haunting low-angle dark historical documentary frame of",
            "atmospheric silhouette in mist and shadow showing",
            "cinematic overhead archival mystery frame of",
        )

    for s_idx, sc in enumerate(scenes):
        if s_idx in skip_set:
            scene_slot_specs.append([])
            continue
        item = assets_list[s_idx]
        sc_mood = str(getattr(sc, "mood", None) or mood or "corporate_thriller")
        mood_defaults = _OPEN_TOPIC_FALLBACK_MEDIA.get(sc_mood, _OPEN_TOPIC_FALLBACK_MEDIA["epic_history"])
        target_shots = (
            max(3, min(12, int(scene_shot_counts[s_idx])))
            if (scene_shot_counts and s_idx < len(scene_shot_counts))
            else 4
        )
        n_seq_photos = max(3, target_shots - (1 if item.primary_broll_mp4 else 0))

        # Build an ordered list of rich, chronological, scene-specific English visual prompts
        prompt_candidates: List[str] = []
        for sp in list(getattr(sc, "shot_prompts_en", None) or []):
            sp_c = str(sp or "").strip()
            if is_vertical:
                sp_c = _enforce_vertical_prompt_framing(sp_c)
            if sp_c and sp_c.lower() not in {x.lower() for x in prompt_candidates}:
                prompt_candidates.append(sp_c)
        if sc.bespoke_image_prompt_en:
            bp_c = sc.bespoke_image_prompt_en.strip()
            if is_vertical:
                bp_c = _enforce_vertical_prompt_framing(bp_c)
            if bp_c and bp_c.lower() not in {x.lower() for x in prompt_candidates}:
                prompt_candidates.insert(0, bp_c)

        fallback_queries = [q for q in [sc.photo_query_en, *(sc.extra_photo_queries_en or [])] if str(q or "").strip()]
        if not fallback_queries:
            fallback_queries = list(mood_defaults["photos"])

        for fq_i, fq in enumerate(fallback_queries):
            if len(prompt_candidates) >= n_seq_photos + 2:
                break
            p_gen = f"{camera_angles[(s_idx + fq_i) % len(camera_angles)]} {fq} ({sc.lower_third_title}), dark 35mm film grain, no text"
            if p_gen.lower() not in {x.lower() for x in prompt_candidates}:
                prompt_candidates.append(p_gen)

        while len(prompt_candidates) < n_seq_photos:
            k_extra = len(prompt_candidates)
            p_gen = (
                f"{camera_angles[(s_idx + k_extra) % len(camera_angles)]} "
                f"{sc.lower_third_title} — {sc.evidence_headline}, dark atmospheric period detail #{k_extra + 1}, 35mm cinema still, no text"
            )
            prompt_candidates.append(p_gen)

        specs_for_scene: List[Dict[str, Any]] = []
        for sh_i in range(n_seq_photos):
            p_txt = prompt_candidates[sh_i]
            if is_vertical:
                p_txt = _enforce_vertical_prompt_framing(p_txt)
            # Mandatory Historical Era-Lock before Google Flow generation (blocks modern police/cars/hoodies/LEDs!)
            if sc_mood in ("dark_horror", "epic_history"):
                p_txt = _enforce_historical_era_prompt_lock(p_txt, sc.lower_third_title, sc.lower_third_subtitle)
            if p_txt.lower() in global_used_prompts:
                p_txt = f"{p_txt} — alternate angle #{s_idx + 1}-{sh_i + 1}"
            global_used_prompts.add(p_txt.lower())

            slot_key = f"sc{s_idx:02d}_shot{sh_i:02d}"
            out_p = work_dir / f"flow_{slot_key}.jpg"
            fb_q = fallback_queries[sh_i % len(fallback_queries)]
            cached_p = _find_cached_slot_photo(work_dir, slot_key, min_bytes=12_000) if resume else None
            spec = {
                "key": slot_key,
                "role": "shot",
                "prompt_en": p_txt,
                "fallback_query": fb_q,
                "out_path": out_p,
                "cached": cached_p,
            }
            specs_for_scene.append(spec)
            if cached_p is None:
                batch_items.append({"key": slot_key, "prompt_en": p_txt, "out_path": out_p})

        scene_slot_specs.append(specs_for_scene)

    # Execute ONE single Google Flow Pro (`Nano Banana 2.1`) batch session for ALL bespoke shots!
    flow_results: Dict[str, Path] = {}
    if batch_items:
        print(
            f"[NetflixDoc] Generating {len(batch_items)} unique era-locked {aspect_ratio} cinema stills via Google Flow Pro (Nano Banana 2.1)...",
            flush=True,
        )
        flow_results = generate_flow_batch_images_sync(
            batch_items,
            aspect_ratio=aspect_ratio,
            mood=mood,
        )
        print(
            f"[NetflixDoc] Google Flow Pro batch delivered {len(flow_results)}/{len(batch_items)} bespoke cinema stills!",
            flush=True,
        )

    # -------------------------------------------------------------------------
    # PHASE C: Assemble strictly UNIQUE, NON-REPEATING `shot_sequence` per scene
    # + Screen Flow plates for historical anachronisms (replacing rejected plates
    #   with Priority 1 Wikimedia Commons archival plates!)
    # -------------------------------------------------------------------------
    anachronism_rejections = 0
    wikimedia_archival_count = 0
    for s_idx, sc in enumerate(scenes):
        if s_idx in skip_set:
            continue
        item = assets_list[s_idx]
        sc_mood = str(getattr(sc, "mood", None) or mood or "corporate_thriller")
        scene_photos: List[Path] = []
        _, is_pre_modern = _extract_historical_era_lock(sc.lower_third_title, sc.lower_third_subtitle, sc.narration)

        for spec in scene_slot_specs[s_idx]:
            key = spec["key"]
            ppath: Optional[Path] = spec["cached"] or flow_results.get(key)
            if ppath is not None and Path(ppath).exists():
                flow_ok = True
                if sc_mood in ("dark_horror", "epic_history") and is_pre_modern:
                    # Gemini Vision anachronism screening on bespoke Flow plates (rejects modern police/vans/hoodies!)
                    ok_ana, ana_sc, ana_why = verify_historical_anachronism_vision(
                        Path(ppath),
                        query=spec["prompt_en"],
                        lower_third_title=sc.lower_third_title,
                        lower_third_subtitle=sc.lower_third_subtitle,
                        mood=sc_mood,
                        strict_vision=False,
                    )
                    if not ok_ana and ana_why != "no_vision_key":
                        anachronism_rejections += 1
                        flow_ok = False
                        print(
                            f"[NetflixDoc] Vision REJECTED anachronistic Flow plate {Path(ppath).name} "
                            f"({ana_sc}/10: {ana_why}) -> replacing via Wikimedia Commons!",
                            flush=True,
                        )
                if flow_ok and _register_dhash(Path(ppath)):
                    scene_photos.append(Path(ppath))
                    photos_used.append(str(ppath))
                    continue

            # Priority 1 Free Archival Source: Wikimedia Commons API (public domain / CC, >=900px, Vision + dHash!)
            wiki_path = fetch_wikimedia_commons_archival_photo(
                query_en=spec["fallback_query"],
                out_dir=work_dir,
                prefix=f"wiki_{key}",
                is_wide=(not is_vertical),
                topic_context=f"{sc.lower_third_title} {sc.narration}",
                mood=sc_mood,
                used_urls=used_photo_urls,
                used_dhashes=used_dhashes,
                strict_vision=True,
            )
            if wiki_path is not None and wiki_path.exists():
                wikimedia_archival_count += 1
                scene_photos.append(wiki_path)
                photos_used.append(str(wiki_path))
                continue

            # Secondary Vision-verified archival fallback (Openverse / Pixabay / era-locked Flow regen)
            fb_path = fetch_doc_hero_or_archival_photo(
                spec["fallback_query"],
                work_dir,
                key,
                min_width=640,
                used_urls=used_photo_urls,
                mood=sc_mood,
                prefer_gemini=False,
                aspect_ratio=aspect_ratio,
                bespoke_prompt_en=spec["prompt_en"],
                scene_context=f"{sc.lower_third_title} — {sc.narration}",
                used_dhashes=used_dhashes,
                strict_vision=True,
                allow_duplicate=False,
            )
            if fb_path is not None and fb_path.exists():
                scene_photos.append(fb_path)
                photos_used.append(str(fb_path))

        # Populate primary_photo_path & initial extra_photo_paths
        if scene_photos:
            item.primary_photo_path = scene_photos[0]
            if sc.visual_mode in ("red_string_board", "sliding_timeline", "video_over_video_collage"):
                item.extra_photo_paths = list(scene_photos[:4])
            else:
                item.extra_photo_paths = list(scene_photos[1:])

        # ALWAYS open every scene on its strongest hero 2.5D parallax plate (Shot 0 = hero photo, NEVER weak stock B-roll!)
        seq: List[Tuple[str, Path]] = []
        if item.primary_broll_mp4 is not None and scene_photos:
            seq.append(("photo", scene_photos[0]))
            seq.append(("video", item.primary_broll_mp4))
            for p_rem in scene_photos[1:]:
                seq.append(("photo", p_rem))
        elif scene_photos:
            for p_rem in scene_photos:
                seq.append(("photo", p_rem))
        elif item.primary_broll_mp4 is not None:
            seq.append(("video", item.primary_broll_mp4))

        item.shot_sequence = seq
        print(
            f"[NetflixDoc] Scene {s_idx + 1}/{len(scenes)} ({sc.visual_mode}) assembled {len(seq)} UNIQUE non-repeating shots "
            f"(hero_first=True, video={1 if item.primary_broll_mp4 else 0}, bespoke/archival_photos={len(scene_photos)})",
            flush=True,
        )

    # -------------------------------------------------------------------------
    # PHASE D: Era-Matched Global Hero Plates for `sliding_timeline` & `red_string_board`
    # Guarantees Saturnalia gets the Saturnalia plate, Sol Invictus gets 274/336 AD,
    # São Nicolau gets Myra, Krampus gets Krampus — NEVER duplicating King Charles II!
    # -------------------------------------------------------------------------
    global_hero_photos_by_scene: List[Optional[Path]] = []
    for s_idx, sc in enumerate(scenes):
        hero_p = assets_list[s_idx].primary_photo_path
        if hero_p is None:
            hero_p = _find_cached_slot_photo(work_dir, f"sc{s_idx:02d}_shot00", min_bytes=8_000)
        global_hero_photos_by_scene.append(hero_p)

    _bind_global_era_matched_board_and_timeline_photos(
        scenes=scenes,
        assets_list=assets_list,
        global_hero_photos_by_scene=global_hero_photos_by_scene,
    )

    telemetry = {
        "broll_clips_used": broll_clips_used,
        "broll_clips_count": len(broll_clips_used),
        "pip_clips_used": pip_clips_used,
        "pip_clips_count": len(pip_clips_used),
        "photos_used": photos_used,
        "photos_count": len(photos_used),
        "unique_dhashes_count": len(used_dhashes),
        "google_flow_bespoke_count": len(flow_results),
        "wikimedia_archival_count": wikimedia_archival_count,
        "anachronism_rejections_count": anachronism_rejections,
        "video_over_video_active": len(pip_clips_used) > 0,
    }
    return assets_list, telemetry


def _fold_ascii_lower(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _bind_global_era_matched_board_and_timeline_photos(
    scenes: List[NetflixDocScene],
    assets_list: List[SceneMediaAssets],
    global_hero_photos_by_scene: List[Optional[Path]],
) -> None:
    """Populate `item.extra_photo_paths` for every `sliding_timeline` and `red_string_board` scene
    with the ACTUAL matching historical scene hero plates corresponding to each milestone/node!
    """
    available_pairs: List[Tuple[int, Path, str]] = []
    for idx_s, (sc, hero_p) in enumerate(zip(scenes, global_hero_photos_by_scene)):
        if hero_p is not None and Path(hero_p).exists():
            sig_text = _fold_ascii_lower(
                f"{sc.lower_third_title} {sc.lower_third_subtitle} {sc.evidence_headline} {sc.photo_query_en} {sc.narration[:240]}"
            )
            available_pairs.append((idx_s, Path(hero_p), sig_text))
    if not available_pairs:
        return

    stop_toks = {
        "de", "da", "do", "dos", "das", "em", "no", "na", "e", "o", "a", "os", "as", "por", "para",
        "com", "uma", "um", "que", "seu", "sua", "era", "ano", "anos", "the", "and", "of", "in",
    }

    def _pick_best_plate_for_text(item_text: str, used_paths: Set[str], exclude_scene_idx: int) -> Optional[Path]:
        norm_q = _fold_ascii_lower(item_text)
        tokens = [tok for tok in re.findall(r"[a-z0-9]{3,}", norm_q) if tok not in stop_toks]
        year_tokens = re.findall(r"\b\d{3,4}\b", norm_q)
        best_score = -1
        best_path: Optional[Path] = None
        for idx_s, path_s, sig_txt in available_pairs:
            p_key = str(path_s.resolve()) if path_s.exists() else str(path_s)
            if p_key in used_paths:
                continue
            score = 0
            for yt in year_tokens:
                if yt in sig_txt:
                    score += 12
            for tk in tokens:
                if tk in sig_txt:
                    score += 4
                elif len(tk) >= 5 and tk[:5] in sig_txt:
                    score += 2
            if idx_s != exclude_scene_idx:
                score += 1  # slight preference for the actual historical source scene over the recap scene itself
            if score > best_score:
                best_score = score
                best_path = path_s
        if best_path is not None and best_score >= 3:
            used_paths.add(str(best_path.resolve()) if best_path.exists() else str(best_path))
            return best_path
        # Fallback: first unused distinct hero plate across the documentary
        for _, path_s, _ in available_pairs:
            p_key = str(path_s.resolve()) if path_s.exists() else str(path_s)
            if p_key not in used_paths:
                used_paths.add(p_key)
                return path_s
        return None

    for s_idx, sc in enumerate(scenes):
        if sc.visual_mode not in ("sliding_timeline", "red_string_board"):
            continue
        item = assets_list[s_idx]
        used_p: Set[str] = set()
        matched_paths: List[Path] = []
        if sc.visual_mode == "sliding_timeline":
            targets = [f"{pt.date} {pt.label} {pt.value}" for pt in (sc.timeline_points or [])[:6]]
        else:
            targets = [f"{nd.title} {nd.role} {nd.badge}" for nd in (sc.board_nodes or [])[:4]]
        for t_txt in targets:
            picked = _pick_best_plate_for_text(t_txt, used_p, exclude_scene_idx=s_idx)
            if picked is not None:
                matched_paths.append(picked)
        if matched_paths:
            item.extra_photo_paths = matched_paths


def _pick_sfx(sfx_dir: Path, *names: str) -> Optional[Path]:
    """Return the first existing upgraded Hollywood SFX file in `sfx_dir`."""
    for name in names:
        p = sfx_dir / name
        if p.exists() and p.stat().st_size > 2048:
            return p
    return None


def _select_doc_music_bed(
    plan_obj: NetflixDocPlan,
    music_mp3: Optional[Union[Path, str]] = None,
    thermal_limit_c: float = 85.0,
) -> Optional[Path]:
    """Select the mood-matched cinema atmosphere music bed unless the caller explicitly forces a file or 'none'."""
    if isinstance(music_mp3, str) and music_mp3.strip().lower() == "none":
        return None

    music_dir = ASSETS_DIR / "music"
    mood = str(plan_obj.mood or _classify_topic_mood(plan_obj.title)).strip().lower()

    if mood in ("dark_horror", "investigative_crime"):
        upgraded_path: Optional[Path] = None
        if ensure_upgraded_dark_horror_music is not None:
            try:
                got = ensure_upgraded_dark_horror_music(force_regen=False)
                if got is not None and Path(got).exists():
                    upgraded_path = Path(got)
            except Exception as exc:
                print(f"[NetflixDoc] ensure_upgraded_dark_horror_music fallback: {exc}", flush=True)
        if music_mp3 is not None and str(music_mp3).strip().lower() not in ("", "auto"):
            p_forced = Path(music_mp3)
            if p_forced.exists() and p_forced.name not in ("epic_doc.mp3", "dark_pulse.mp3", "dark_mystery_horror.mp3"):
                return p_forced
        if upgraded_path is not None:
            return upgraded_path
        cand = music_dir / "dark_mystery_horror.mp3"
        if cand.exists():
            return cand
        if select_music_for_mood is not None:
            try:
                return select_music_for_mood(plan_obj.title, default_file="dark_mystery_horror.mp3", mood=mood)
            except Exception:
                pass
        return music_dir / "dark_pulse.mp3"

    if music_mp3 is not None and str(music_mp3).strip().lower() not in ("", "auto"):
        p_forced = Path(music_mp3)
        if p_forced.exists():
            return p_forced

    if mood == "corporate_thriller":
        cand = music_dir / "dark_pulse.mp3"
        return cand if cand.exists() else (music_dir / "epic_doc.mp3")

    if mood == "epic_history":
        cand = music_dir / "epic_doc.mp3"
        return cand if cand.exists() else (music_dir / "dark_mystery_horror.mp3")

    if select_music_for_mood is not None:
        try:
            return select_music_for_mood(plan_obj.title, default_file="epic_doc.mp3", mood=mood)
        except Exception:
            pass
    return music_dir / "dark_pulse.mp3"


def _probe_video_duration(path: Path) -> float:
    """Return accurate container/stream duration in seconds via ffprobe."""
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
        val = float((res.stdout or "").strip() or 0.0)
        if val > 0.05:
            return val
    except Exception:
        pass
    return _get_wav_duration(path)


def _concat_scenes_with_xfade(
    scene_mp4_paths: List[Path],
    transitions: List[str],
    xfade_dur: float,
    fps: int,
    out_mp4: Path,
    work_dir: Path,
    thermal_limit_c: float,
    scene_durs: Optional[List[float]] = None,
) -> Tuple[Path, bool]:
    """Concatenate rendered documentary scenes using smooth 0.40s FFmpeg `xfade` cinema transitions
    (`fadeblack`, `smoothleft`, `zoomin`, `dissolve`, `wiperight`) with hardware QuickSync VAAPI
    encoding (and automatic software fallback + drift-free trimmed concat fallback) while keeping
    Core i5 RAM & thermals safe.
    """
    if not scene_mp4_paths:
        raise RuntimeError("Nenhuma cena renderizada para concatenar.")
    if len(scene_mp4_paths) == 1:
        run_ffmpeg_safe(
            ["ffmpeg", "-y", "-v", "error", "-i", str(scene_mp4_paths[0]), "-c:v", "copy", "-an", str(out_mp4)],
            thermal_limit_c=thermal_limit_c,
        )
        return out_mp4, False

    # Balanced batch reduction if documentary has > 10 scenes so RAM stays flat on Core i5!
    if len(scene_mp4_paths) > 10:
        batch_size = 8
        batch_outs: List[Path] = []
        batch_trs: List[str] = []
        batch_durs: List[float] = []
        for b_idx, start in enumerate(range(0, len(scene_mp4_paths), batch_size)):
            chunk_paths = scene_mp4_paths[start : start + batch_size]
            chunk_trs = transitions[start : start + len(chunk_paths) - 1]
            chunk_durs = scene_durs[start : start + len(chunk_paths)] if scene_durs is not None else None
            b_out = work_dir / f"_xfade_batch_{b_idx:02d}.mp4"
            _concat_scenes_with_xfade(
                chunk_paths,
                chunk_trs,
                xfade_dur=xfade_dur,
                fps=fps,
                out_mp4=b_out,
                work_dir=work_dir,
                thermal_limit_c=thermal_limit_c,
                scene_durs=chunk_durs,
            )
            batch_outs.append(b_out)
            if chunk_durs is not None:
                batch_durs.append(round(sum(chunk_durs), 4))
            boundary_tr_idx = start + len(chunk_paths) - 1
            if boundary_tr_idx < len(transitions):
                batch_trs.append(transitions[boundary_tr_idx])
        return _concat_scenes_with_xfade(
            batch_outs,
            batch_trs,
            xfade_dur=xfade_dur,
            fps=fps,
            out_mp4=out_mp4,
            work_dir=work_dir,
            thermal_limit_c=thermal_limit_c,
            scene_durs=batch_durs if batch_durs else None,
        )

    durs = [_probe_video_duration(p) for p in scene_mp4_paths]
    eff_d = min(float(xfade_dur), max(0.12, min(durs) * 0.35))

    def _run_xfade_pass(use_vaapi: Optional[bool]) -> None:
        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19, use_vaapi=use_vaapi)
        inputs: List[str] = []
        filter_parts: List[str] = []
        for idx, p in enumerate(scene_mp4_paths):
            inputs.extend(["-i", str(p)])
            filter_parts.append(f"[{idx}:v]fps={fps},format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[v{idx}]")

        accum_dur = durs[0]
        prev_lbl = "[v0]"
        for i in range(1, len(scene_mp4_paths)):
            tr_name = transitions[i - 1] if (i - 1) < len(transitions) else CINEMA_XFADE_POOL[(i - 1) % len(CINEMA_XFADE_POOL)]
            if tr_name not in ("fadeblack", "smoothleft", "zoomin", "dissolve", "wiperight", "fade", "hblur", "smoothright"):
                tr_name = "fadeblack"
            offset = max(0.05, round(accum_dur - eff_d, 4))
            out_lbl = f"[xf{i}]"
            filter_parts.append(
                f"{prev_lbl}[v{i}]xfade=transition={tr_name}:duration={eff_d:.3f}:offset={offset:.4f}{out_lbl}"
            )
            prev_lbl = out_lbl
            accum_dur = offset + durs[i]

        filter_parts.append(f"{prev_lbl}{hw_suffix}[vout]")

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            *pre_args,
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]",
            *enc_args,
            "-an",
            str(out_mp4),
        ]
        run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c, timeout=420)

    try:
        _run_xfade_pass(use_vaapi=None)
        return out_mp4, True
    except Exception as exc_hw:
        print(f"[NetflixDoc] xfade VAAPI fallback -> libx264 ({exc_hw})", flush=True)
        try:
            _run_xfade_pass(use_vaapi=False)
            return out_mp4, True
        except Exception as exc_sw:
            print(f"[NetflixDoc] xfade emergency concat fallback ({exc_sw})", flush=True)
            # Trim scenes 0..N-2 to exact `scene_dur` (-t) so removing xfade NEVER introduces +0.40s/scene A/V drift!
            trimmed_paths: List[Path] = []
            for idx_f, p_f in enumerate(scene_mp4_paths):
                if idx_f < len(scene_mp4_paths) - 1:
                    if scene_durs is not None and idx_f < len(scene_durs) and float(scene_durs[idx_f]) > 0.2:
                        trim_d = float(scene_durs[idx_f])
                    else:
                        trim_d = max(0.2, float(durs[idx_f]) - float(xfade_dur))
                    trim_out = work_dir / f"_fallback_trim_{out_mp4.stem}_{idx_f:03d}.mp4"
                    run_ffmpeg_safe(
                        [
                            "ffmpeg", "-y", "-v", "error",
                            "-i", str(p_f),
                            "-t", f"{trim_d:.4f}",
                            "-vf", f"fps={fps},format=yuv420p",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                            "-an", str(trim_out),
                        ],
                        thermal_limit_c=thermal_limit_c,
                        timeout=180,
                    )
                    trimmed_paths.append(trim_out)
                else:
                    trimmed_paths.append(p_f)
            video_concat_txt = work_dir / "doc_video_concat_fallback.txt"
            video_concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in trimmed_paths), encoding="utf-8")
            run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(video_concat_txt),
                    "-vf", f"fps={fps},format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                    "-an", str(out_mp4),
                ],
                thermal_limit_c=thermal_limit_c,
                timeout=300,
            )
            return out_mp4, False


def _fmt_edl_ts(seconds: float) -> str:
    sec = max(0.0, float(seconds))
    mins = int(sec // 60)
    rem = sec - mins * 60.0
    return f"{mins:02d}:{rem:04.1f}"


def _map_xfade_to_edl_transition(tr_name: str, is_chapter: bool = False) -> str:
    if is_chapter:
        return "Light leak"
    t = str(tr_name or "").strip().lower()
    if t in ("smoothleft", "wiperight", "smoothright"):
        return "Whip pan"
    if t in ("fadeblack", "dissolve", "zoomin"):
        return "Light leak"
    return "Hard cut"


def _build_edl_timeline_json(
    plan_obj: NetflixDocPlan,
    scene_records: List[Dict[str, Any]],
    sfx_events: List[Tuple[Path, float, float]],
    pattern_interrupt_times: List[float],
    total_dur_s: float,
) -> Dict[str, Any]:
    """Export the complete shot-by-shot Reverse-Engineered JSON Edit Decision List (`edl_timeline.json`)
    following the mandatory schema_version 3.0.0 EDL structure.
    """
    breakdown: List[Dict[str, Any]] = []
    hook_cuts = 0
    hook_shot_durs: List[float] = []

    def _sfx_in_window(t0: float, t1: float) -> List[str]:
        hits: List[str] = []
        for s_p, s_t, _ in sfx_events:
            if (t0 - 0.35) <= s_t <= (t1 + 0.10):
                nm = Path(s_p).name
                if nm not in hits:
                    hits.append(nm)
        return hits

    for rec in scene_records:
        s_idx = int(rec["s_idx"])
        sc: NetflixDocScene = rec["scene"]
        sc_start = float(rec["start_t"])
        ch_intro = float(rec["chapter_intro_s"])
        body_start = sc_start + ch_intro
        body_dur = max(0.5, float(rec["body_dur"]))
        tr_in = _map_xfade_to_edl_transition(str(rec.get("transition_type") or ""), is_chapter=bool(sc.chapter_card))
        assets: SceneMediaAssets = rec.get("media_assets") or SceneMediaAssets()
        seq = list(assets.shot_sequence or [])
        n_shots = max(1, len(seq))
        cad = float(getattr(sc, "cut_cadence_s", None) or 3.0)
        bookend_w = _compute_bookended_graphic_window(sc.visual_mode, body_dur, n_shots, cut_cadence_s=cad)

        is_pi = bool(getattr(sc, "pattern_interrupt", False)) or any(abs(sc_start - tp) <= 4.0 for tp in pattern_interrupt_times)
        music_state = (
            "Hard mute to absolute silence for 1.25s (Pattern Interrupt) then resume at -28 dB under voice"
            if is_pi
            else ("Slower reflective coda fading out abruptly 0.50s after final word" if sc.act_id == "ACT_4_ABRUPT_ENDING" else "Evolving 4-movement documentary score (-23 dB base, auto-ducked to -28 dB under voice)")
        )

        # Build shot-level EDL entries across pre-graphic, centerpiece graphic, and post-graphic slices (or multi-shot)
        slices: List[Tuple[float, float, str, str, str, str, str, str]] = []
        if bookend_w is not None:
            g_start, g_end, pre_cnt = bookend_w
            pre_shots = seq[:pre_cnt] or [("photo", Path("hero"))]
            post_shots = seq[pre_cnt:] or seq[-1:] or [("photo", Path("still"))]
            # Pre-graphic shots
            pre_sd = max(0.4, g_start / float(len(pre_shots)))
            for i_p, (k_p, _) in enumerate(pre_shots):
                t0 = body_start + i_p * pre_sd
                t1 = body_start + (i_p + 1) * pre_sd
                vcat = "Atmospheric_B_Roll" if k_p == "video" else "2.5D_Parallax"
                cam = "0.85x slow-motion push-in 1.00->1.09" if k_p == "video" else "Counter-directional 2.5D parallax (BG 1.06->1.00, FG 1.00->1.14)"
                slices.append((
                    t0, t1, vcat,
                    "Desaturated 0.85x slow-motion B-roll (master_color_grade)" if k_p == "video" else "Inpainted 3px-DOF blurred archival plate (master_color_grade)",
                    "Atmospheric dust motes + 35mm film grain (0.14)" if (k_p == "video" or i_p > 0) else "3D Depth Title in rule-of-thirds negative space behind subject",
                    f"Date/Location Stamp ({sc.lower_third_title}) + Selective-Emphasis Captions",
                    cam,
                    tr_in if i_p == 0 else "Hard cut",
                ))
            # Centerpiece graphic slice
            g_vcat = _resolve_visual_category(sc.visual_mode, is_broll_shot=False)
            g_bg = {
                "2D_Infographic_Over_Realism": "65%-brightness realistic plate or dark cartographic slate",
                "Video_Over_Video_PiP": "Dark textured grid + 15px blurred B-roll (40% opacity)",
                "Dark_3D_Reconstruction": "#121417 obsidian slate void with 3D perspective wireframe floor",
            }.get(g_vcat, "Graded archival backdrop")
            g_mid = f"Animated {sc.visual_mode} ({sc.evidence_headline[:48]})"
            g_cam = "Virtual camera track / subtle push-in over mixed-media graphic"
            slices.append((
                body_start + g_start, body_start + g_end, g_vcat, g_bg, g_mid,
                "Selective-Emphasis Courier Prime keyword captions + 3px crimson-gold progress thread",
                g_cam, "Whip pan" if g_vcat == "2D_Infographic_Over_Realism" else "Hard cut",
            ))
            # Post-graphic shots
            post_dur = max(0.4, body_dur - g_end)
            post_sd = max(0.4, post_dur / float(len(post_shots)))
            for i_q, (k_q, _) in enumerate(post_shots):
                t0 = body_start + g_end + i_q * post_sd
                t1 = body_start + g_end + (i_q + 1) * post_sd
                vcat = "Atmospheric_B_Roll" if k_q == "video" else "2.5D_Parallax"
                cam = "0.85x slow-motion drift" if k_q == "video" else "Slow Ken Burns push 1.00->1.07"
                slices.append((
                    t0, t1, vcat,
                    "0.85x slow-motion period B-roll" if k_q == "video" else "Graded archival/bespoke historical still",
                    "35mm grain (0.14) + floating dust motes (0.16)",
                    "Selective-Emphasis keyword captions (depth title suppressed on Shot 1+)",
                    cam, "Light leak" if i_q == 0 else "Hard cut",
                ))
        else:
            sd = max(0.5, body_dur / float(n_shots))
            for i_s in range(n_shots):
                k_s = seq[i_s][0] if i_s < len(seq) else "photo"
                t0 = body_start + i_s * sd
                t1 = body_start + (i_s + 1) * sd
                vcat = "Atmospheric_B_Roll" if k_s == "video" else _resolve_visual_category(sc.visual_mode, is_broll_shot=False)
                cam = (
                    "0.85x slow-motion drift 1.00->1.09"
                    if k_s == "video"
                    else ("Counter-directional 2.5D parallax (BG 1.06->1.00, FG 1.00->1.14)" if i_s == 0 else "Slow Ken Burns drift 1.00->1.07")
                )
                slices.append((
                    t0, t1, vcat,
                    "0.85x slow-motion B-roll (master_color_grade)" if k_s == "video" else "3px-DOF inpainted historical plate (master_color_grade)",
                    f"3D Depth Title behind subject (Shot 0)" if (i_s == 0 and vcat == "2.5D_Parallax") else f"{sc.visual_mode} motion layer",
                    f"Date/Location Stamp ({sc.lower_third_title}) + Selective-Emphasis Captions",
                    cam,
                    tr_in if i_s == 0 else "Hard cut",
                ))

        for t0, t1, vcat, bg_desc, mid_desc, fg_desc, cam_m, tr_lbl in slices:
            dur_s = round(max(0.1, t1 - t0), 2)
            if t0 < 45.0:
                hook_cuts += 1
                hook_shot_durs.append(dur_s)
            breakdown.append({
                "scene_id": sc.scene_id,
                "act_id": sc.act_id,
                "timestamp_start": _fmt_edl_ts(t0),
                "timestamp_end": _fmt_edl_ts(t1),
                "duration_sec": dur_s,
                "visual_category": vcat,
                "layer_composition": {
                    "background": bg_desc,
                    "midground_animation": mid_desc,
                    "foreground_overlay": fg_desc,
                },
                "camera_motion": cam_m,
                "transition_in": tr_lbl,
                "audio_sync": {
                    "music_state": music_state,
                    "sfx_triggers": _sfx_in_window(t0, t1),
                },
            })

    avg_hook_dur = round(sum(hook_shot_durs) / float(max(1, len(hook_shot_durs))), 2) if hook_shot_durs else 2.5
    return {
        "schema_version": "3.0.0",
        "pipeline_name": plan_obj.pipeline_name,
        "title": plan_obj.title,
        "reference_source_url": "local://Mixed_Media_High_Retention_Documentary_Engine/v3.0.0",
        "total_duration_sec": round(float(total_dur_s), 2),
        "hook_metrics_00_to_45s": {
            "total_cuts": hook_cuts,
            "average_shot_duration_sec": avg_hook_dur,
            "opening_hook_mechanic": "Names core topic keyword in first sentence, establishes central historical paradox across 2.5D parallax & dark 3D reconstruction, ends Cold Open with provocative interrogative hook.",
        },
        "timeline_breakdown": breakdown,
        "reproducible_style_rules": [
            "Open every scene on its strongest era-locked 2.5D hero plate (never weak stock B-roll).",
            "Apply 3px Gaussian DOF blur to separated backgrounds and counter-directional scale (FG 1.00->1.14 vs BG 1.06->1.00).",
            "Fire 3D Depth Title strictly on Shot 0 of a scene with alpha-aware >=88% unoccluded placement.",
            "Enforce uniform Visual Cohesion Unifier Stack (contrast +12%, sat -22%, shadows #0D1B2A, highlights #E0C097, vignette 0.35, 35mm grain 0.14, dust 0.16).",
            "Maintain -14 LUFS voice, -23 dB base / -28 dB ducked evolving score, 1.25s silence pattern interrupts @ 240s/480s/720s, and 0.50s abrupt zero-CTA ending.",
        ],
    }


async def render_netflix_documentary(
    plan: Union[Dict[str, Any], NetflixDocPlan],
    work_dir: Path,
    out_master_mp4: Path,
    music_mp3: Optional[Union[Path, str]] = None,
    fps: int = 30,
    thermal_limit_c: float = 85.0,
    progress_cb=None,
    caption_style: Optional[str] = None,
    music_volume: float = 0.34,
    voice_rate: str = "+0%",
    voice_pitch: str = "-4Hz",
    resume: bool = False,
    voice_engine: str = "auto",
    cut_cadence_s: float = 2.6,
) -> Dict[str, Any]:
    """Render a complete Mixed-Media High-Retention Documentary (`schema_version: 3.0.0`, 16:9 & 9:16)
    scene-by-scene to disk with zero-copy BGRA Skia C++ surfaces, direct VAAPI hardware encoding,
    Wikimedia Commons + era-locked Google Flow plates, 0.85x slow-motion Vision-gated B-roll,
    all 5 Mixed-Media visual categories, 5-Act expressive TTS, 240s pattern interrupts, 0.50s abrupt ending,
    and automatic export of `outputs/<job_id>/script.json` + `outputs/<job_id>/edl_timeline.json`.
    """
    fps = 30 if int(fps) <= 30 else 60
    work_dir = Path(work_dir)
    out_master_mp4 = Path(out_master_mp4)
    out_dir = out_master_mp4.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    plan_obj = NetflixDocPlan.model_validate(plan_dict)
    doc_mood = _normalize_mood(plan_obj.mood, plan_obj.title)
    plan_obj.mood = doc_mood
    for sc in plan_obj.scenes:
        if not sc.mood or (sc.mood == "corporate_thriller" and doc_mood != "corporate_thriller"):
            sc.mood = doc_mood

    # Always export `outputs/<job_id>/script.json` cleanly at the start of every documentary render
    script_export_path = out_dir / "script.json"
    try:
        script_export_path.write_text(
            json.dumps(plan_obj.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc_sc:
        print(f"[NetflixDoc] Could not export script.json: {exc_sc}", flush=True)

    default_cap = "selective_emphasis" if plan_obj.aspect_ratio == "16:9" else "cinema_minimal"
    raw_cap_style = str(caption_style or plan_obj.caption_style or default_cap).strip()
    if resolve_caption_style is not None:
        eff_caption_style = resolve_caption_style(raw_cap_style)
    else:
        eff_caption_style = raw_cap_style

    w, h = (1920, 1080) if plan_obj.aspect_ratio == "16:9" else (1080, 1920)
    lut_path = ASSETS_DIR / "luts" / (plan_obj.lut_file or "02_dark_wealth.cube")
    sfx_dir = ASSETS_DIR / "sfx"

    if ensure_pro_cinema_sfx is not None:
        try:
            await asyncio.to_thread(ensure_pro_cinema_sfx, False, thermal_limit_c)
        except Exception:
            pass

    resolved_music_mp3 = _select_doc_music_bed(plan_obj, music_mp3=music_mp3, thermal_limit_c=thermal_limit_c)
    eff_music_vol = max(0.28, min(0.50, float(music_volume if music_volume is not None else 0.34)))

    # Prefer Cinzel-Bold.ttf & CourierPrime-Bold.ttf when available (v3.0.0 typography), fallback cleanly
    fonts_dir = ASSETS_DIR / "fonts"
    title_font_name = "Cinzel-Bold.ttf" if (fonts_dir / "Cinzel-Bold.ttf").exists() else "Montserrat-Black.ttf"
    ui_font_name = "CourierPrime-Bold.ttf" if (fonts_dir / "CourierPrime-Bold.ttf").exists() else "PlusJakartaSans-ExtraBold.ttf"
    cap_font_name = "CourierPrime-Bold.ttf" if (plan_obj.aspect_ratio == "16:9" and (fonts_dir / "CourierPrime-Bold.ttf").exists()) else "Montserrat-Black.ttf"
    title_tf, font_info = _load_verified_typeface(title_font_name, role="doc_title")
    ui_tf, _ = _load_verified_typeface(ui_font_name, role="doc_ui")
    caption_tf, _ = _load_verified_typeface(cap_font_name, role="doc_caption")

    # 1. AUDIO-FIRST: Synthesize 5-Act expressive narration + per-scene LUFS leveling + Whisper word timestamps
    scene_records: List[Dict[str, Any]] = []
    scene_shot_counts: List[int] = []
    already_rendered_mask: List[bool] = []
    all_words: List[Dict[str, Any]] = []
    audio_parts: List[Path] = []
    sfx_events: List[Tuple[Path, float, float]] = []
    transitions_plan: List[str] = []

    def _add_sfx(t_s: float, vol: float, *cand_names: str) -> None:
        p_sfx = _pick_sfx(sfx_dir, *cand_names)
        if p_sfx is not None and t_s >= 0.0:
            sfx_events.append((p_sfx, round(t_s, 3), float(vol)))

    cursor_t = 0.0
    pause_gap_within_act_s = 0.30
    pause_gap_between_acts_s = 0.42
    # Abrupt 0.50s ending per ACT_4_ABRUPT_ENDING specification
    tail_pad_s = 0.50
    xfade_dur = CINEMA_XFADE_DURATION_S
    gap_short_wav = work_dir / "_doc_gap_short.wav"
    gap_std_wav = work_dir / "_doc_gap.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{pause_gap_within_act_s:.2f}", str(gap_short_wav)],
        thermal_limit_c=thermal_limit_c,
    )
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{pause_gap_between_acts_s:.2f}", str(gap_std_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    n_scenes = len(plan_obj.scenes)
    is_dark_mood = doc_mood in ("dark_horror", "investigative_crime")
    default_cad = max(1.8, min(4.5, float(cut_cadence_s or 2.6)))

    for s_idx, sc in enumerate(plan_obj.scenes):
        if progress_cb:
            pct = 10 + int(18 * ((s_idx + 1) / float(max(1, n_scenes))))
            progress_cb(pct, f"Sintetizando narração 5-Atos cena {s_idx + 1}/{n_scenes} ({sc.act_id} | {sc.visual_mode})...")

        is_last_scene = s_idx == (n_scenes - 1)
        next_act_differs = (not is_last_scene) and (plan_obj.scenes[s_idx + 1].act_id != sc.act_id)
        sc_pause_s = 0.0 if is_last_scene else (pause_gap_between_acts_s if next_act_differs else pause_gap_within_act_s)
        sc_gap_wav = None if is_last_scene else (gap_std_wav if next_act_differs else gap_short_wav)

        tr_name = sc.transition_type or _select_transition_for_scene(s_idx, sc.visual_mode, sc.chapter_card is not None)
        if s_idx > 0:
            transitions_plan.append(tr_name)

        chapter_intro_s = 1.65 if sc.chapter_card else 0.0
        chap_gap_wav = work_dir / f"_chap_intro_{s_idx:03d}.wav"
        if chapter_intro_s > 0.0:
            run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{chapter_intro_s:.2f}",
                    str(chap_gap_wav),
                ],
                thermal_limit_c=thermal_limit_c,
            )
            audio_parts.append(chap_gap_wav)

        existing_sc_mp4 = work_dir / f"doc_scene_{s_idx:03d}.mp4"
        existing_vad_wav = work_dir / f"doc_narr_{s_idx:03d}_vad.wav"
        scene_already_rendered = False
        if resume and existing_sc_mp4.exists() and existing_vad_wav.exists():
            est_wav_d = _probe_wav_duration_s(existing_vad_wav)
            if est_wav_d > 0.3:
                exp_sc_d = round(
                    chapter_intro_s + est_wav_d + sc_pause_s + (tail_pad_s if is_last_scene else xfade_dur),
                    3,
                )
                scene_already_rendered = _is_valid_cached_scene_mp4(existing_sc_mp4, w, h, fps, exp_sc_d, tol_s=0.35)

        wav_p, words, speech_dur = await _synthesize_doc_scene_narration(
            sc.narration,
            plan_obj.voice_id,
            plan_obj.lang,
            work_dir,
            f"doc_narr_{s_idx:03d}",
            thermal_limit_c=thermal_limit_c,
            rate=voice_rate,
            pitch=voice_pitch,
            resume=resume,
            reuse_existing_wav_if_no_words=scene_already_rendered,
            voice_engine=voice_engine,
            mood=doc_mood,
            act_id=str(getattr(sc, "act_id", "ACT_1_WORLD_BUILDING") or "ACT_1_WORLD_BUILDING"),
        )

        if normalize_scene_wav_lufs is not None and wav_p is not None and Path(wav_p).exists():
            try:
                norm_wav_p = await asyncio.to_thread(
                    normalize_scene_wav_lufs,
                    wav_p,
                    -18.0,
                    thermal_limit_c,
                )
                if norm_wav_p is not None and Path(norm_wav_p).exists():
                    wav_p = Path(norm_wav_p)
                    norm_dur = _probe_wav_duration_s(wav_p)
                    if norm_dur > 0.3:
                        speech_dur = norm_dur
            except Exception as exc_norm:
                print(f"[NetflixDoc] Per-scene voice LUFS leveling skipped on scene {s_idx + 1}: {exc_norm}", flush=True)

        local_words: List[Dict[str, Any]] = []
        for wd in words:
            lw = {
                "word": wd["word"],
                "start": round(chapter_intro_s + float(wd["start"]), 3),
                "end": round(chapter_intro_s + float(wd["end"]), 3),
            }
            local_words.append(lw)
            all_words.append(
                {
                    "word": wd["word"],
                    "start": round(cursor_t + lw["start"], 3),
                    "end": round(cursor_t + lw["end"], 3),
                }
            )

        audio_scene_dur = round(chapter_intro_s + speech_dur + sc_pause_s, 3)
        scene_dur_with_tail = round(audio_scene_dur + (tail_pad_s if is_last_scene else 0.0), 3)
        render_dur = round(scene_dur_with_tail + (xfade_dur if not is_last_scene else 0.0), 3)
        exact_dur = max(1, int(round(render_dur * fps))) / float(fps)
        body_dur = max(0.5, exact_dur - chapter_intro_s)

        sc_cad = float(getattr(sc, "cut_cadence_s", None) or default_cad)
        n_shots_for_scene = max(3, min(12, int(round(body_dur / max(1.8, sc_cad)))))
        scene_shot_counts.append(n_shots_for_scene)

        if resume and existing_sc_mp4.exists():
            scene_already_rendered = _is_valid_cached_scene_mp4(existing_sc_mp4, w, h, fps, render_dur, tol_s=0.35)
        already_rendered_mask.append(scene_already_rendered)

        scene_records.append(
            {
                "s_idx": s_idx,
                "scene": sc,
                "start_t": cursor_t,
                "speech_end_local_t": round(chapter_intro_s + speech_dur, 3),
                "scene_dur": scene_dur_with_tail,
                "render_dur": render_dur,
                "exact_dur": exact_dur,
                "body_dur": body_dur,
                "chapter_intro_s": chapter_intro_s,
                "transition_type": tr_name,
                "already_rendered": scene_already_rendered,
                "local_words": local_words,
                "media_assets": SceneMediaAssets(),
            }
        )
        audio_parts.append(wav_p)
        if sc_gap_wav is not None:
            audio_parts.append(sc_gap_wav)
        cursor_t = round(cursor_t + audio_scene_dur, 3)

    # 2. ZERO-REPETITION ERA-LOCKED MEDIA ORCHESTRATOR
    skip_scene_indices: Set[int] = {idx_r for idx_r, is_done in enumerate(already_rendered_mask) if is_done}
    total_planned_shots = sum(
        cnt for idx_c, cnt in enumerate(scene_shot_counts) if idx_c not in skip_scene_indices
    )
    if progress_cb:
        progress_cb(
            30,
            f"♻️ Reaproveitando {len(skip_scene_indices)}/{n_scenes} cenas já renderizadas e mídias em cache..."
            if (resume and skip_scene_indices)
            else f"Gerando {total_planned_shots} planos históricos sem anacronismos (Wikimedia Commons + Google Flow Pro + Gemini Vision)...",
        )
    scene_media_list, media_telemetry = await asyncio.to_thread(
        _prefetch_scene_media_sync,
        plan_obj.scenes,
        work_dir,
        plan_obj.aspect_ratio,
        doc_mood,
        resume,
        scene_shot_counts,
        skip_scene_indices,
    )
    for idx_m, rec in enumerate(scene_records):
        if idx_m < len(scene_media_list):
            rec["media_assets"] = scene_media_list[idx_m]

    # 2.5 EXACT VISUAL-ALIGNED TACTILE MIXED-MEDIA FOLEY & PATTERN INTERRUPTS (Schema v3.0.0)
    computed_pi_times: List[float] = []
    for rec in scene_records:
        s_idx = rec["s_idx"]
        sc: NetflixDocScene = rec["scene"]
        sc_start_t = float(rec["start_t"])
        chapter_intro_s = float(rec["chapter_intro_s"])
        body_start_t = sc_start_t + chapter_intro_s
        body_dur = float(rec["body_dur"])
        tr_name = str(rec["transition_type"])
        is_last_scene = s_idx == (n_scenes - 1)
        sc_cad = float(getattr(sc, "cut_cadence_s", None) or default_cad)

        if bool(getattr(sc, "pattern_interrupt", False)) and sc_start_t >= 30.0:
            computed_pi_times.append(round(sc_start_t, 2))
            _add_sfx(sc_start_t + 0.02, 0.34, "pattern_interrupt_shutter.wav", "camera_shutter.wav", "ui_click.wav")

        if s_idx > 0:
            if sc.chapter_card:
                if sc_start_t >= 1.4:
                    _add_sfx(max(0.0, sc_start_t - 2.48), 0.22, "riser_tension.wav")
            elif tr_name in ("smoothleft", "wiperight"):
                _add_sfx(max(0.0, sc_start_t - 0.42), 0.28, "whoosh_deep.wav", "whoosh_fast.wav")
            elif tr_name == "zoomin":
                _add_sfx(max(0.0, sc_start_t - 0.04), 0.26, "scene_cut_sub_pulse.wav", "flash_impact.wav", "cinematic_hit.wav")
            elif s_idx % 2 == 0:
                _add_sfx(max(0.0, sc_start_t - 0.04), 0.24, "scene_cut_sub_pulse.wav", "sub_boom.wav")

        if chapter_intro_s > 0.0:
            # Varied chapter stings (avoid repeating identical horror_braam 5x!)
            if s_idx % 3 == 0:
                _add_sfx(sc_start_t + 0.04, 0.32, "sub_boom.wav", "scene_cut_sub_pulse.wav")
            elif doc_mood == "dark_horror" and sc.act_id != "ACT_3_CLIMAX_REVELATION":
                _add_sfx(sc_start_t + 0.04, 0.28, "horror_braam.wav", "sub_boom.wav")
            else:
                _add_sfx(sc_start_t + 0.04, 0.30, "scene_cut_sub_pulse.wav", "cinematic_hit.wav", "sub_boom.wav")

        if s_idx == 0:
            _add_sfx(0.04, 0.28, "scene_cut_sub_pulse.wav", "sub_boom.wav", "cinematic_hit.wav")

        seq_len = len(rec["media_assets"].shot_sequence or [])
        if seq_len == 0 and rec["already_rendered"]:
            cached_shots = len(list(work_dir.glob(f"flow_sc{s_idx:02d}_shot*"))) + len(list(work_dir.glob(f"photo_sc{s_idx:02d}_shot*")))
            has_cached_broll = 1 if _find_cached_work_asset(work_dir, f"broll_sc{s_idx:02d}_main", min_bytes=32_768) else 0
            seq_len = (cached_shots + has_cached_broll) or scene_shot_counts[s_idx]

        if sc.visual_mode in ("cinema_multishot", "parallax_25d_photo"):
            if seq_len >= 2:
                shot_dur = max(0.8, body_dur / float(seq_len))
                safe_cut_limit = (body_dur - xfade_dur - 0.15) if not is_last_scene else (body_dur - 0.15)
                for si_cut in range(1, seq_len):
                    cut_local_t = si_cut * shot_dur
                    if cut_local_t >= safe_cut_limit:
                        break
                    cut_t = body_start_t + cut_local_t
                    if si_cut % 2 == 1:
                        _add_sfx(max(0.0, cut_t - 0.18), 0.18, "scene_cut_sub_pulse.wav", "whoosh_fast.wav")
        elif sc.visual_mode in ("broll_video_pip", "video_pip_evidence"):
            _add_sfx(body_start_t + 0.12, 0.28, "pip_card_slide.wav", "whoosh_fast.wav")
        elif sc.visual_mode in GRAPHIC_BOOKEND_MODES:
            bookend_w = _compute_bookended_graphic_window(
                sc.visual_mode,
                body_dur,
                seq_len,
                cut_cadence_s=sc_cad,
            )
            graphic_enter_t = (body_start_t + bookend_w[0]) if bookend_w is not None else (body_start_t + 0.10)
            if sc.visual_mode == "newspaper_highlighter":
                _add_sfx(graphic_enter_t, 0.30, "pip_card_slide.wav", "paper_flip.wav")
                _add_sfx(graphic_enter_t + 0.45, 0.32, "marker_highlight_stroke.wav", "paper_flip.wav")
            elif sc.visual_mode in ("dark_map_route", "2d_schematic_over_realism"):
                _add_sfx(graphic_enter_t, 0.28, "vector_draw_tick.wav", "ui_click.wav")
                _add_sfx(max(0.0, graphic_enter_t - 0.20), 0.18, "whoosh_fast.wav")
            elif sc.visual_mode == "sliding_timeline":
                _add_sfx(graphic_enter_t, 0.28, "vector_draw_tick.wav", "ui_click.wav", "sub_boom.wav")
            elif sc.visual_mode == "video_over_video_collage":
                _add_sfx(graphic_enter_t, 0.30, "pip_card_slide.wav", "paper_flip.wav")
                _add_sfx(graphic_enter_t + 0.50, 0.30, "marker_highlight_stroke.wav", "ui_click.wav")
            elif sc.visual_mode == "fern_3d_reconstruction":
                _add_sfx(graphic_enter_t, 0.28, "scene_cut_sub_pulse.wav", "sub_boom.wav")
                _add_sfx(graphic_enter_t + 0.32, 0.22, "vector_draw_tick.wav", "ui_click.wav")
            elif sc.visual_mode == "red_string_board":
                _add_sfx(graphic_enter_t, 0.30, "pip_card_slide.wav", "paper_flip.wav")
                _add_sfx(graphic_enter_t + 0.24, 0.26, "vector_draw_tick.wav", "heartbeat.wav")

    if not computed_pi_times and cursor_t >= 280.0:
        computed_pi_times = [float(tp) for tp in (240.0, 480.0, 720.0) if tp < cursor_t - 20.0]

    # Concatenate full narration WAV and master Broadcast Audio (-14 LUFS + -23/-28 dB music + PI mutes + 0.50s abrupt ending)
    concat_audio_txt = work_dir / "doc_audio_concat.txt"
    concat_audio_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in audio_parts), encoding="utf-8")
    raw_full_wav = work_dir / "doc_narration_full.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_audio_txt), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_full_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    master_audio = work_dir / "doc_master_audio.m4a"
    master_kwargs: Dict[str, Any] = {"thermal_limit_c": thermal_limit_c}
    try:
        mba_params = inspect.signature(master_broadcast_audio).parameters
        if "pattern_interrupt_times" in mba_params:
            master_kwargs["pattern_interrupt_times"] = computed_pi_times
        if "abrupt_ending_cut" in mba_params:
            master_kwargs["abrupt_ending_cut"] = True
    except Exception:
        pass

    master_audio, final_dur = await asyncio.to_thread(
        master_broadcast_audio,
        raw_full_wav,
        resolved_music_mp3,
        sfx_events,
        master_audio,
        cursor_t,
        eff_music_vol,
        tail_pad_s,
        **master_kwargs,
    )

    if scene_records:
        actual_tail_delta = max(0.0, round(final_dur - cursor_t, 3))
        if abs(actual_tail_delta - tail_pad_s) > 0.005:
            base_last = round(scene_records[-1]["scene_dur"] - tail_pad_s, 3)
            scene_records[-1]["scene_dur"] = round(base_last + actual_tail_delta, 3)
            scene_records[-1]["render_dur"] = scene_records[-1]["scene_dur"]

    # Export complete Reverse-Engineered EDL (`outputs/<job_id>/edl_timeline.json`)
    edl_export_path = out_dir / "edl_timeline.json"
    edl_payload = _build_edl_timeline_json(
        plan_obj=plan_obj,
        scene_records=scene_records,
        sfx_events=sfx_events,
        pattern_interrupt_times=computed_pi_times,
        total_dur_s=final_dur,
    )
    try:
        edl_export_path.write_text(json.dumps(edl_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc_edl:
        print(f"[NetflixDoc] Could not export edl_timeline.json: {exc_edl}", flush=True)

    # 3. Render each scene to disk one-by-one (zero-copy BGRA Skia + VAAPI 65+ FPS -> flat RAM!)
    scene_mp4_paths: List[Path] = []
    u2netp_25d_used = False
    for rec in scene_records:
        s_idx = rec["s_idx"]
        sc: NetflixDocScene = rec["scene"]
        out_sc_mp4 = work_dir / f"doc_scene_{s_idx:03d}.mp4"
        is_last_scene = s_idx == (n_scenes - 1)
        if resume and (rec.get("already_rendered") or _is_valid_cached_scene_mp4(out_sc_mp4, w, h, fps, rec["render_dur"], tol_s=0.35)):
            if progress_cb:
                pct = 45 + int(40 * ((s_idx + 1) / float(max(1, n_scenes))))
                progress_cb(
                    pct,
                    f"♻️ Reaproveitando cena já renderizada {s_idx + 1}/{n_scenes} [{sc.visual_mode}] ({w}x{h} @ {fps}fps)...",
                )
            if sc.visual_mode == "parallax_25d_photo":
                u2netp_25d_used = True
            scene_mp4_paths.append(out_sc_mp4)
            continue

        if progress_cb:
            pct = 45 + int(40 * ((s_idx + 1) / float(max(1, n_scenes))))
            progress_cb(
                pct,
                f"Renderizando cena Skia C++ Zero-Copy {s_idx + 1}/{n_scenes} [{sc.visual_mode}] ({w}x{h} @ {fps}fps)...",
            )
        prev_lt_title = plan_obj.scenes[s_idx - 1].lower_third_title if s_idx > 0 else None
        sc_cad = float(getattr(sc, "cut_cadence_s", None) or default_cad)
        abrupt_cut_t = (
            round(float(rec["speech_end_local_t"]) + 0.45, 3)
            if (is_last_scene and sc.act_id == "ACT_4_ABRUPT_ENDING")
            else None
        )
        rendered_p, did_u2netp = await asyncio.to_thread(
            _render_single_doc_scene_to_disk,
            sc,
            s_idx,
            rec["render_dur"],
            rec["chapter_intro_s"],
            rec["local_words"],
            rec["start_t"],
            final_dur,
            out_sc_mp4,
            w,
            h,
            fps,
            lut_path,
            title_tf,
            ui_tf,
            caption_tf,
            thermal_limit_c,
            rec["media_assets"],
            plan_obj.lang,
            eff_caption_style,
            sc_cad,
            prev_lt_title,
            abrupt_cut_t,
        )
        if did_u2netp:
            u2netp_25d_used = True
        scene_mp4_paths.append(rendered_p)

    # 4. Join rendered scenes with smooth 0.40s FFmpeg `xfade` cinema transitions + mux master broadcast audio
    if progress_cb:
        progress_cb(88, "Aplicando transições cinema FFmpeg xfade (0.40s) e mixagem master -14 LUFS...")
    base_scenes_mp4 = work_dir / "base_scenes.mp4"
    base_scenes_mp4, xfade_active = await asyncio.to_thread(
        _concat_scenes_with_xfade,
        scene_mp4_paths,
        transitions_plan,
        xfade_dur,
        fps,
        base_scenes_mp4,
        work_dir,
        thermal_limit_c,
        [float(rec["scene_dur"]) for rec in scene_records],
    )

    run_ffmpeg_safe(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(base_scenes_mp4),
            "-i", str(master_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "copy",
            "-shortest",
            "-movflags", "+faststart",
            str(out_master_mp4),
        ],
        thermal_limit_c=thermal_limit_c,
    )

    chapters_used = [sc.chapter_card for sc in plan_obj.scenes if sc.chapter_card]
    modes_used = [sc.visual_mode for sc in plan_obj.scenes]

    return {
        "schema_version": "3.0.0",
        "pipeline_name": plan_obj.pipeline_name,
        "master_mp4": str(out_master_mp4),
        "master_audio": str(master_audio),
        "base_scenes_mp4": str(base_scenes_mp4),
        "script_json_path": str(script_export_path),
        "edl_timeline_path": str(edl_export_path),
        "words": all_words,
        "duration_s": round(_probe_video_duration(out_master_mp4), 2),
        "aspect_ratio": plan_obj.aspect_ratio,
        "width": w,
        "height": h,
        "fps": fps,
        "lang": plan_obj.lang,
        "mood": doc_mood,
        "music_bed": str(resolved_music_mp3) if resolved_music_mp3 else "none",
        "caption_style": eff_caption_style,
        "channel_name": plan_obj.channel_name,
        "voice_id": plan_obj.voice_id,
        "lut_file": plan_obj.lut_file,
        "film_grain": "35mm_skia_unifier_active",
        "xfade_active": xfade_active,
        "xfade_duration_s": xfade_dur if xfade_active else 0.0,
        "transitions_used": transitions_plan,
        "pattern_interrupt_times": computed_pi_times,
        "sfx_events_count": len(sfx_events),
        "doc_engine": "mixed_media_high_retention_doc_engine_v3",
        "font_verified": font_info,
        "title": plan_obj.title,
        "subtitle": plan_obj.subtitle,
        "thumbnail_hook": plan_obj.thumbnail_hook,
        "topic_source": plan_obj.topic_source,
        "scenes_count": len(plan_obj.scenes),
        "chapters": chapters_used,
        "visual_modes_used": modes_used,
        "u2netp_25d_active": u2netp_25d_used,
        **media_telemetry,
    }


render_netflix_doc_video = render_netflix_documentary
