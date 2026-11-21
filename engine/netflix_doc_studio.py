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
import json
import math
import os
import re
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

import edge_tts
import httpx
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
from engine.gemini_tts import (
    GEMINI_EXPRESSIVE_VOICES,
    has_valid_gemini_key,
    normalize_narration_for_speech,
    synthesize_gemini_tts_line,
)
from engine.doc_media_engine import (
    VideoLayerReader,
    fetch_doc_broll_clip,
    fetch_doc_hero_or_archival_photo,
    fetch_doc_real_photo,
    load_skia_image_cover,
    separate_photo_25d_u2netp,
)
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
    from engine.pro_sfx_studio import ensure_pro_cinema_sfx, select_music_for_mood
except Exception:
    ensure_pro_cinema_sfx = None  # type: ignore
    select_music_for_mood = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
SKILLS_DIR = BASE_DIR / "skills"
DOC_BG_CACHE = BASE_DIR / "data" / "doc_bgs"
DOC_BG_CACHE.mkdir(parents=True, exist_ok=True)

VisualModeType = Literal[
    "cinema_multishot",
    "broll_video_pip",
    "newspaper_highlighter",
    "dark_map_route",
    "parallax_25d_photo",
    "red_string_board",
    "sliding_timeline",
    "video_pip_evidence",
]

# Cinema v3 visual rhythm: ~60% clean full-screen fast-cut multi-shot & full-bleed 2.5D art,
# ~40% varied investigative set-pieces (newspaper, dark map, red-string board, timeline).
VISUAL_MODES: Tuple[VisualModeType, ...] = (
    "cinema_multishot",
    "newspaper_highlighter",
    "cinema_multishot",
    "parallax_25d_photo",
    "cinema_multishot",
    "dark_map_route",
    "cinema_multishot",
    "red_string_board",
    "cinema_multishot",
    "sliding_timeline",
)

PIP_ENABLED_MODES: Tuple[VisualModeType, ...] = (
    "cinema_multishot",
    "broll_video_pip",
    "dark_map_route",
    "video_pip_evidence",
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

CINEMA_XFADE_DURATION_S: float = 0.35
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


def _spaced_chapter_label(roman: str, lang: str = "pt_br") -> str:
    """Return wide letter-spaced cinema chapter title with generous gap before the Roman numeral."""
    r_spaced = " ".join(list(roman.strip()))
    if lang == "en_us":
        return f"C A P Í T U L O     {r_spaced}   •   C H A P T E R     {r_spaced}"
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
    act_label: str = "ACT I"
    chapter_card: Optional[str] = None
    chapter_subtitle: Optional[str] = None
    visual_mode: VisualModeType = "broll_video_pip"
    mood: str = "corporate_thriller"
    narration: str
    lower_third_title: str
    lower_third_subtitle: str
    highlight_color: str = "#FFD166"
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
    transition_type: Optional[str] = None


# Backwards/shorthand alias
DocScene = NetflixDocScene


class NetflixDocPlan(BaseModel):
    title: str
    subtitle: str
    channel_name: str = "Dossiê Capital"
    mood: str = "corporate_thriller"
    lang: str = "pt_br"
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    target_minutes: float = 0.5
    lut_file: str = "02_dark_wealth.cube"
    voice_id: str = "pt-BR-AntonioNeural"
    caption_style: str = "cinema_minimal"
    thumbnail_hook: str = "A VERDADE OCULTA"
    topic_source: str = "curated"
    tokens_used: int = 0
    cost_usd: float = 0.0
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
    r"historic\s+bank\s+building\s+london|london\s+financial\s+district)\b",
    re.IGNORECASE,
)

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
    since_loop_s = 0.0
    b_idx = 0
    for idx, sc in enumerate(scenes):
        txt = sc.narration.strip()
        dur_est = max(2.2, len(txt.split()) / 2.65)
        since_loop_s += dur_est
        if OPEN_LOOP_MARKERS_RE.search(txt):
            since_loop_s = 0.0
            continue
        # Inject an authentic mood-matched question on scene 0 or whenever >= 18s elapsed without a hook
        # (never repeat the same bridge question twice in one video!)
        if (idx == 0 or (idx < len(scenes) - 1 and since_loop_s >= 18.0)) and b_idx < len(pool):
            q = pool[b_idx]
            b_idx += 1
            sc.narration = f"{txt.rstrip('.!?')}... {q}"
            since_loop_s = 0.0


def _call_open_topic_director_llm(
    topic: str,
    n_scenes: int,
    clean_lang: str,
    mood_hint: str,
    custom_directives: str = "",
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
    lang_label = "American English" if is_en else "Brazilian Portuguese (PT-BR)"
    skill_path = SKILLS_DIR / "10_netflix_investigative_doc.md"
    skill_excerpt = skill_path.read_text(encoding="utf-8")[:900] if skill_path.exists() else ""

    sys_prompt = (
        f"You are an Emmy-winning Netflix / A24 / Nostalgia / MagnatesMedia Documentary Showrunner & Historian writing in {lang_label}.\n"
        "Create a 100% ORIGINAL, deeply researched, spine-tingling, cinematic documentary script strictly about the user's EXACT TOPIC.\n"
        "ABSOLUTE STORYTELLING & VOICE RULES:\n"
        "1. CONTINUOUS HUMAN NARRATIVE: Write like a master human storyteller telling ONE gripping, continuous story from Cold Open to unforgettable ending — NEVER disjointed bullet points, NEVER repeating ideas across scenes, and NEVER pasting the user's raw prompt text inside narration or headlines!\n"
        "2. REAL HISTORICAL DEPTH: Cite real eras, real years (e.g., 1647, 4th century, 1890s), real places (Rome, Austrian Alps, Myra, London, Iceland), real historical figures/folklore/edicts, and genuine plot twists!\n"
        "3. NATURAL SPOKEN RHYTHM FOR VOICE ACTING: Each scene narration MUST be 16-24 crisp, visceral spoken words. Write spoken Portuguese/English naturally with commas and occasional ellipses (...) so the voice actor breathes and pauses dramatically. Spell out centuries naturally (write 'século quatro' instead of 'SÉC. IV', 'antes de Cristo' instead of 'a.C.').\n"
        "4. ZERO ROBOTIC AI CLICHÉS: NEVER write 'Em um mundo onde', 'Vamos mergulhar', 'Em conclusão', 'Por trás da imagem familiar', 'As crônicas históricas conectaram', 'In a world where', or 'Let's dive in'.\n"
        "5. RETENTION HOOKS: Scene 0 MUST be an explosive, chilling Cold Open that grabs attention in 2 seconds and ends with a sharp open-loop question (?). Keep building curiosity with natural unanswered tension every 2-3 scenes.\n"
        "6. VISUAL PRECISION (ZERO OFF-TOPIC STOCK!): Every scene needs concrete, atmospheric English visual queries:\n"
        "   - `broll_query_en` and `pip_broll_query_en` (MUST differ from each other): concrete, real atmospheric stock video phrases that exist on Pixabay (e.g., 'snow pine forest night', 'burning candle dark shadow', 'medieval stone castle fog', 'gothic cathedral interior', 'crackling fireplace dark', 'winter snow village night', 'old leather book candle', 'ancient roman stone ruins'). NEVER use abstract words like 'floor', 'butterfly', 'background', 'texture', or 'darkness' alone.\n"
        "   - `photo_query_en` and `extra_photo_queries_en` (3-4 distinct concrete English museum/historical/photographic subjects matching THAT exact scene — e.g., 'Krampus Austrian folklore mask', 'Roman Saturnalia festival painting', 'Saint Nicholas Byzantine icon', 'Puritan Oliver Cromwell 17th century engraving', 'Victorian gothic winter postcard').\n"
        "   - `bespoke_image_prompt_en`: vivid 16-26 word English dark-cinema photographic still prompt depicting THAT scene's exact historical moment, dramatic candlelight/chiaroscuro, 35mm film grain, ZERO text/words/letters.\n"
        "   - `prefer_gemini_photo`: true for vivid historical/macabre/folklore scenes where custom AI cinema art beats generic stock.\n"
        "7. UNIQUE PER-SCENE UI METADATA: Give every scene its OWN specific `evidence_headline` (<= 48 chars, punchy newspaper headline), `evidence_quote` (1 gripping historical fact for THAT scene), and `lower_third_title` (`LOCATION • ERA`).\n"
        "8. Classify `mood` strictly as ONE of: \"dark_horror\", \"investigative_crime\", \"epic_history\", \"corporate_thriller\".\n"
        "Return ONLY valid JSON matching this exact schema:\n"
        "{\n"
        '  "title": "Editorial documentary title",\n'
        '  "subtitle": "Short archival subtitle (e.g. Arquivo Histórico • Roma & Alpes)",\n'
        '  "channel_name": "Topic-authentic cinema channel name",\n'
        '  "mood": "dark_horror | investigative_crime | epic_history | corporate_thriller",\n'
        '  "thumbnail_hook": "2-3 PUNCHY WORDS",\n'
        '  "chapter_subtitles": ["CHAPTER 1 SUBTITLE", "CHAPTER 2 SUBTITLE", "CHAPTER 3 SUBTITLE", "CHAPTER 4 SUBTITLE"],\n'
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
        '      "narration": "18-26 gripping words...",\n'
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
        '      "bespoke_image_prompt_en": "dark cinema photorealistic scene description, no text",\n'
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
                f"Por trás da imagem familiar de {clean_t}, arquivos antigos escondem uma origem muito mais sombria — o que realmente acontecia no começo?",
                f"Manuscritos e crônicas de séculos passados mostram que {clean_t} nasceu em meio a temores antigos e rituais de inverno hoje quase esquecidos.",
                "À medida que essas tradições cruzavam fronteiras pela Europa, figuras temidas e advertências noturnas moldaram o imaginário popular.",
                "Com o passar dos séculos, relatos desconfortáveis foram reescritos para parecerem inofensivos — mas qual detalhe sobreviveu nas entrelinhas?",
                f"Ao revisitar os documentos originais de {clean_t}, fica claro que a história verdadeira nunca foi tão inocente quanto parecia.",
            ]
            if not is_en
            else [
                f"Behind the familiar image of {clean_t}, ancient archives conceal a far darker origin — what truly happened in the beginning?",
                f"Centuries-old chronicles reveal that {clean_t} took shape amid forgotten winter fears and stark ancient rituals.",
                "As these traditions traveled across borders, grim folkloric figures and midnight warnings haunted entire villages.",
                "Over generations, unsettling records were softened into harmless tales — yet which chilling trace survived intact?",
                f"Reopening the primary archives of {clean_t} proves the real history was never as innocent as modern memory claims.",
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
                f"A história oficial sobre {clean_t} deixa de fora um capítulo decisivo — o que os arquivos antigos realmente escondem?",
                f"Documentos de época mostram que as raízes de {clean_t} surgiram sob circunstâncias muito mais tensas do que se imagina.",
                "Cada testemunho preservado conecta lugares distantes e revela como pequenas decisões alteraram o destino de milhares de pessoas.",
                "Quando a cronologia completa é colocada lado a lado, o contraste entre mito e realidade chama atenção — por que isso foi esquecido?",
                f"Entender a verdadeira trajetória de {clean_t} muda completamente a forma como enxergamos esse episódio até hoje.",
            ]
            if not is_en
            else [
                f"The familiar story of {clean_t} leaves out its most decisive chapter — what do the original archives actually reveal?",
                f"Period records show the roots of {clean_t} emerged under far more dramatic circumstances than most people realize.",
                "Each preserved testimony connects distant places and exposes how pivotal turning points reshaped an entire generation.",
                "When the complete timeline is placed side by side, myth separates sharply from reality — why was this forgotten?",
                f"Uncovering the true chronicle of {clean_t} transforms how we understand its lasting legacy today.",
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


def generate_netflix_doc_plan(
    topic: str,
    aspect_ratio: str = "16:9",
    target_minutes: float = 0.5,
    lang: str = "pt_br",
    custom_directives: str = "",
    caption_style: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a complete investigative Netflix / MagnatesMedia / Dark History documentary plan (dict).

    - Matches the 10 curated financial dossiers when the topic clearly requests one of them.
    - For ANY new arbitrary open topic (dark history, horror folklore, mysteries, true crime,
      ancient history, biographies, science, etc.), invokes the user's LIVE DeepSeek (`deepseek-chat`)
      or Google Gemini (`gemini-flash-lite-latest` via `x-goog-api-key`) AI Director with automatic
      failover to author a 100% original, deeply researched documentary plan with zero financial boilerplate!
    - Always runs the final plan through `agents.retention_doctor.audit_netflix_doc_plan`.
    """
    ar: Literal["16:9", "9:16"] = "9:16" if str(aspect_ratio).strip() == "9:16" else "16:9"
    clean_lang = "en_us" if str(lang).lower().startswith("en") else "pt_br"
    is_en = clean_lang == "en_us"
    t_min = max(0.35, min(15.0, float(target_minutes or 0.5)))
    target_seconds = max(25.0, t_min * 60.0)
    # Each narrated cinema beat (~16-24 words with natural breathing) lasts ~7.8s and cuts visually every 2.5-3.2s
    n_scenes = max(5, min(60, int(round(target_seconds / 7.8))))
    voice_id = "en-US-AndrewMultilingualNeural" if is_en else "pt-BR-AntonioNeural"
    resolved_cap_style = (
        resolve_caption_style(caption_style)
        if (caption_style and resolve_caption_style is not None)
        else (str(caption_style or "cinema_minimal").strip() or "cinema_minimal")
    )

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
            vmode: VisualModeType = VISUAL_MODES[idx % len(VISUAL_MODES)]
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
                    lower_third_title=_clean_doc_text(lt_title),
                    lower_third_subtitle=_clean_doc_text(lt_sub),
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

        raw_chap_subs = raw_plan.get("chapter_subtitles")
        default_chap_subs = _default_chapter_subtitles_for_mood(mood, is_en)
        if isinstance(raw_chap_subs, list) and len(raw_chap_subs) >= 2:
            chapter_subs = [_safe_field(c, default_chap_subs[i % len(default_chap_subs)]).upper() for i, c in enumerate(raw_chap_subs[:4])]
            while len(chapter_subs) < 4:
                chapter_subs.append(default_chap_subs[len(chapter_subs)])
        else:
            chapter_subs = default_chap_subs

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
                "narration": narr_pad,
                "lower_third_title": f"{global_origin} • {global_dest} • {tp_p.date}",
                "lower_third_subtitle": f"{nd_p.title} • {tp_p.value}",
                "evidence_headline": global_headline,
                "evidence_quote": global_quote,
                "map_origin": global_origin,
                "map_destination": global_dest,
                "map_metric": global_metric,
                "broll_query_en": media_defaults["broll"][idx_pad % len(media_defaults["broll"])],
                "pip_broll_query_en": media_defaults["pip"][idx_pad % len(media_defaults["pip"])],
                "photo_query_en": topic_photo_pool[idx_pad % len(topic_photo_pool)],
                "extra_photo_queries_en": [topic_photo_pool[(idx_pad + k) % len(topic_photo_pool)] for k in range(4)],
                "bespoke_image_prompt_en": f"dark atmospheric 35mm documentary still of {nd_p.title} in {global_origin}, chiaroscuro lighting, no text",
                "prefer_gemini_photo": mood in ("dark_horror", "epic_history"),
            })

        scenes = []
        chapter_counter = 0
        chapter_step = max(2, n_scenes // min(4, max(2, n_scenes // 2)))

        for idx, rs in enumerate(raw_scenes[:n_scenes]):
            vmode = VISUAL_MODES[idx % len(VISUAL_MODES)]
            chap_card = None
            chap_sub = None
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

            tp_cur = timeline_pts[idx % len(timeline_pts)]
            sc_orig = _safe_field(rs.get("map_origin"), global_origin)
            sc_dest = _safe_field(rs.get("map_destination"), global_dest)
            sc_metric = _safe_field(rs.get("map_metric"), global_metric)
            lt_title = _safe_field(rs.get("lower_third_title"), f"{sc_orig} • {sc_dest} • {tp_cur.date}")
            lt_sub = _safe_field(rs.get("lower_third_subtitle"), f"{subtitle.upper()} • {tp_cur.value}")
            sc_head = _safe_field(rs.get("evidence_headline"), global_headline)
            sc_quote = _safe_field(rs.get("evidence_quote"), global_quote)
            sc_narr = _safe_field(rs.get("narration"), off_seed["narr"][idx % len(off_seed["narr"])])

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

            bespoke_p = _safe_field(
                rs.get("bespoke_image_prompt_en"),
                f"cinematic 35mm dark documentary still of {photo_q}, dramatic chiaroscuro lighting, no text",
            )
            pref_gem = bool(rs.get("prefer_gemini_photo", mood == "dark_horror" and idx in (0, 3)))

            scenes.append(
                NetflixDocScene(
                    scene_id=f"doc_sc_{idx + 1:02d}",
                    act_label=act_lbl,
                    chapter_card=chap_card,
                    chapter_subtitle=chap_sub,
                    visual_mode=vmode,
                    mood=mood,
                    narration=sc_narr,
                    lower_third_title=lt_title,
                    lower_third_subtitle=lt_sub,
                    highlight_color="#FFD166" if idx % 2 == 0 else "#FF2E93",
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
        vmode = VISUAL_MODES[idx % len(VISUAL_MODES)]
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
        scenes.append(
            NetflixDocScene(
                scene_id=f"doc_sc_{idx + 1:02d}",
                act_label=act_lbl,
                chapter_card=chap_card,
                chapter_subtitle=chap_sub,
                visual_mode=vmode,
                mood=mood,
                narration=_clean_doc_text(line_txt),
                lower_third_title=_clean_doc_text(f"{off['map_origin']} • {off['map_destination']} • {tp_cur['date']}"),
                lower_third_subtitle=_clean_doc_text(f"{off['subtitle'].upper()} • {tp_cur['value']}"),
                highlight_color="#FFD166" if idx % 2 == 0 else "#FF2E93",
                evidence_headline=_clean_doc_text(off["evidence_headline"]),
                evidence_quote=_clean_doc_text(off["evidence_quote"]),
                map_origin=_clean_doc_text(off["map_origin"]),
                map_destination=_clean_doc_text(off["map_destination"]),
                map_metric=_clean_doc_text(off["map_metric"]),
                timeline_points=[TimelinePoint(**pt) for pt in off["timeline_points"]],
                board_nodes=[BoardNode(**nd) for nd in off["board_nodes"]],
                image_prompt_en=photo_q,
                bespoke_image_prompt_en=f"dark atmospheric 35mm documentary still of {photo_q}, chiaroscuro lighting, no text",
                prefer_gemini_photo=(mood == "dark_horror"),
                broll_query_en=broll_pool[idx % len(broll_pool)],
                pip_broll_query_en=pip_pool[idx % len(pip_pool)],
                photo_query_en=photo_q,
                extra_photo_queries_en=[photo_pool[(idx + k) % len(photo_pool)] for k in range(4)],
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
        scenes=scenes,
        hashtags=["#documentario", "#historia", "#misterio", "#cinema"],
    )
    return audit_netflix_doc_plan(plan_obj.model_dump(), lang=clean_lang)


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
        "pt": "Narre como um locutor humano de documentário sombrio da Netflix: voz grave, envolvente e cinematográfica, ritmo calmo e tenso, pausas naturais nas vírgulas e reticências, respiração sutil e dicção brasileira impecável, sem pressa e sem soar robótico.",
        "en": "Narrate like a human Netflix dark-history documentary voice actor: deep, haunting, cinematic gravity, calm suspenseful pacing, natural breaths and short pauses at commas and ellipses, crisp diction, never robotic.",
    },
    "investigative_crime": {
        "pt": "Narre como um jornalista investigativo de documentário true-crime: voz firme, séria e humana, ritmo natural com pausas dramáticas nas revelações e perguntas, dicção clara em português do Brasil, sem pressa.",
        "en": "Narrate like a Prestige true-crime documentary host: grounded, tense, human voice with natural pauses on revelations and questions, crisp diction, never rushed.",
    },
    "epic_history": {
        "pt": "Narre como um documentarista histórico de cinema: voz profunda, emotiva e cativante, ritmo cadenciado com respiração natural e pausas elegantes nas vírgulas, português do Brasil natural.",
        "en": "Narrate like an epic cinema documentary historian: rich, evocative, deeply human voice with measured pacing and natural breathing pauses.",
    },
    "corporate_thriller": {
        "pt": "Narre no estilo MagnatesMedia em português do Brasil: voz firme, inteligente e cinematográfica, ritmo envolvente com pausas estratégicas antes dos números e reviravoltas, 100% natural e humano.",
        "en": "Narrate in MagnatesMedia documentary thriller style: crisp, authoritative, human storytelling voice with dramatic pauses before twists and numbers.",
    },
}


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
        mood_dir = _DOC_ACTING_DIRECTIONS.get(str(mood or "dark_horror"), _DOC_ACTING_DIRECTIONS["dark_horror"])
        acting_dir = mood_dir["en" if is_en else "pt"]
        try:
            await asyncio.to_thread(
                synthesize_gemini_tts_line,
                spoken_text,
                raw_wav,
                gem_voice,
                acting_dir,
                gem_key,
                lang,
                thermal_limit_c,
            )
            # Trim ONLY dead outer silence — preserve 100% of human internal breaths & dramatic pauses!
            out_wav, _, out_dur = await asyncio.to_thread(
                trim_silence_vad,
                raw_wav,
                vad_wav,
                [],
                0.45,
                0.11,
                thermal_limit_c,
                True,
            )
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


@dataclass
class LoadedSceneSkiaMedia:
    primary_photo: Optional[skia.Image] = None
    parallax_bg: Optional[skia.Image] = None
    parallax_fg: Optional[skia.Image] = None
    extra_photos: List[skia.Image] = field(default_factory=list)
    u2netp_separated: bool = False


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
) -> None:
    """Draw REAL MOVING HD B-ROLL VIDEO across the full canvas with subtle Ken Burns motion & cinema scrim."""
    if video_frame is not None:
        zoom = 1.0 + ken_burns_zoom * prog
        pan_x = (prog - 0.5) * -22.0
        canvas.save()
        canvas.clipRect(skia.Rect.MakeWH(w, h))
        canvas.translate(w * 0.5 + pan_x, h * 0.5)
        canvas.scale(zoom, zoom)
        dst = skia.Rect.MakeXYWH(-w * 0.5, -h * 0.5, w, h)
        canvas.drawImageRect(video_frame, dst, _LINEAR_SAMPLING)
        canvas.restore()

        # Sleek Dark Wealth radial cinema scrim — keeps moving footage clearly visible underneath!
        if scrim_alpha > 0:
            center_a = max(0, min(230, scrim_alpha - 26))
            edge_a = max(0, min(235, scrim_alpha + 24))
            scrim = skia.Paint()
            scrim.setShader(
                skia.GradientShader.MakeRadial(
                    (w * 0.5, h * 0.45),
                    max(w, h) * 0.72,
                    [skia.ColorSetARGB(center_a, 14, 10, 28), skia.ColorSetARGB(edge_a, 8, 5, 16)],
                )
            )
            canvas.drawRect(skia.Rect.MakeWH(w, h), scrim)
    else:
        _draw_obsidian_cinema_backdrop(canvas, w, h, t)

    if show_grid:
        grid_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.0,
            Color=skia.ColorSetARGB(16, 179, 136, 255),
        )
        step = 96
        ox = int((t * 14.0) % step)
        for x in range(-ox, w + step, step):
            canvas.drawLine(x, 0, x, h, grid_p)
        for y in range(0, h + step, step):
            canvas.drawLine(0, y, w, y, grid_p)

    if show_dust:
        dust_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(42, 255, 209, 102))
        for i in range(14):
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
    canvas.drawImageRect(img, rect, _LINEAR_SAMPLING, photo_paint)

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


def _draw_fullbleed_parallax_shot(
    canvas: skia.Canvas,
    w: int,
    h: int,
    bg_img: Optional[skia.Image],
    fg_img: Optional[skia.Image],
    shot_prog: float,
    t: float,
    pan_dir: float = 1.0,
) -> None:
    """Render an unobstructed full-bleed edge-to-edge 2.5D parallax cinema shot with subtle embers & vignette."""
    full_r = skia.Rect.MakeXYWH(0, 0, w, h)
    canvas.clear(skia.ColorSetARGB(255, 9, 7, 16))
    if bg_img is not None:
        bg_zoom = 1.05 + 0.08 * shot_prog
        bg_pan_x = (shot_prog - 0.5) * (-26.0 * pan_dir)
        bg_pan_y = (shot_prog - 0.5) * -10.0
        canvas.save()
        canvas.translate(w * 0.5 + bg_pan_x, h * 0.42 + bg_pan_y)
        canvas.scale(bg_zoom, bg_zoom)
        canvas.translate(-w * 0.5, -h * 0.42)
        canvas.drawImageRect(bg_img, full_r, _LINEAR_SAMPLING)
        canvas.restore()

        # Atmospheric floating dust / warm candlelight embers
        mote_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(72, 255, 209, 102))
        for mi in range(16):
            mx_m = ((mi * 197 + t * (26 + (mi % 4) * 9)) % w)
            my_m = ((mi * 131 - t * (18 + (mi % 3) * 7)) % h)
            canvas.drawCircle(mx_m, my_m, 2.0 + (mi % 3) * 1.2, mote_p)

        if fg_img is not None:
            fg_zoom = 1.07 + 0.145 * shot_prog
            fg_pan_x = (shot_prog - 0.5) * (44.0 * pan_dir)
            fg_pan_y = (shot_prog - 0.5) * -14.0
            canvas.save()
            canvas.translate(w * 0.5 + fg_pan_x, h * 0.42 + fg_pan_y)
            canvas.scale(fg_zoom, fg_zoom)
            canvas.translate(-w * 0.5, -h * 0.42)
            fg_paint = skia.Paint(AntiAlias=True)
            fg_paint.setImageFilter(skia.ImageFilters.DropShadow(0, 14, 28, 28, skia.ColorSetARGB(145, 0, 0, 0)))
            canvas.drawImageRect(fg_img, full_r, _LINEAR_SAMPLING, fg_paint)
            canvas.restore()

    # Subtle cinematic edge vignette (keeps center bright and dramatic)
    vig = skia.Paint()
    vig.setShader(
        skia.GradientShader.MakeRadial(
            (w * 0.5, h * 0.46),
            max(w, h) * 0.68,
            [skia.ColorSetARGB(0, 8, 6, 16), skia.ColorSetARGB(158, 8, 6, 16)],
        )
    )
    canvas.drawRect(full_r, vig)


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
) -> None:
    """Cinema v3 Primary Visual Mode: clean, unobstructed FULL-SCREEN multi-shot storytelling!
    Automatically cuts visually every ~`cut_cadence_s` (2.0-3.5s) across distinct visual beats:
      Shot 0: Full-screen HD Atmospheric B-Roll #1 with smooth dynamic push-in
      Shot 1: Full-bleed Archival / Google Flow Art in 2.5D u2netp Parallax with drifting embers
      Shot 2: Full-screen Secondary HD B-Roll #2 (or Archival Photo #2) with dramatic camera punch-in
      Shot 3: Archival / Google Flow Art #2 (on longer beats)
    Includes a crisp 0.13s dark-cinema flash/cut transition right on every internal visual cut!
    """
    eff_cadence = max(1.8, min(4.2, float(cut_cadence_s or 2.6)))
    n_shots = max(2, min(4, int(round(body_dur / eff_cadence))))
    shot_dur = max(1.2, body_dur / float(n_shots))
    shot_idx = min(n_shots - 1, int(body_t / shot_dur))
    shot_local_t = max(0.0, body_t - shot_idx * shot_dur)
    shot_prog = min(1.0, shot_local_t / shot_dur)

    # Build ordered sequence of distinct full-screen visual layers for this scene
    shot_slots: List[str] = []
    if s_idx % 2 == 0:
        if primary_frame is not None:
            shot_slots.append("video_primary")
        if (media.parallax_bg or media.primary_photo) is not None:
            shot_slots.append("photo_25d_primary")
        if pip_frame is not None:
            shot_slots.append("video_secondary")
        if media.extra_photos:
            shot_slots.append("photo_extra_0")
    else:
        if (media.parallax_bg or media.primary_photo) is not None:
            shot_slots.append("photo_25d_primary")
        if primary_frame is not None:
            shot_slots.append("video_primary")
        if media.extra_photos:
            shot_slots.append("photo_extra_0")
        if pip_frame is not None:
            shot_slots.append("video_secondary")
    if not shot_slots:
        shot_slots = ["video_primary"]

    kind = shot_slots[shot_idx % len(shot_slots)]
    pan_dir = 1.0 if (shot_idx + s_idx) % 2 == 0 else -1.0

    if kind == "video_primary":
        _draw_video_backdrop_layer(
            canvas,
            w,
            h,
            primary_frame,
            t,
            shot_prog,
            scrim_alpha=36,
            ken_burns_zoom=0.09,
            show_grid=False,
            show_dust=True,
        )
    elif kind == "video_secondary":
        _draw_video_backdrop_layer(
            canvas,
            w,
            h,
            pip_frame or primary_frame,
            t,
            shot_prog,
            scrim_alpha=34,
            ken_burns_zoom=0.11,
            show_grid=False,
            show_dust=True,
        )
    elif kind == "photo_25d_primary":
        _draw_fullbleed_parallax_shot(
            canvas,
            w,
            h,
            media.parallax_bg or media.primary_photo,
            media.parallax_fg,
            shot_prog,
            t,
            pan_dir=pan_dir,
        )
    else:
        extra_img = media.extra_photos[0] if media.extra_photos else (media.parallax_bg or media.primary_photo)
        _draw_fullbleed_parallax_shot(
            canvas,
            w,
            h,
            extra_img,
            None,
            shot_prog,
            t,
            pan_dir=-pan_dir,
        )

    # Crisp 0.13s cinema cut flash / micro-dip right on each internal shot switch
    if shot_idx > 0 and shot_local_t < 0.13:
        cut_k = 1.0 - (shot_local_t / 0.13)
        flash_alpha = int(115 * (cut_k ** 1.6))
        canvas.drawRect(
            skia.Rect.MakeXYWH(0, 0, w, h),
            skia.Paint(Color=skia.ColorSetARGB(flash_alpha, 255, 224, 175)),
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
) -> None:
    """Mode 4: Real high-res photo separated via `separate_photo_25d_u2netp` (foreground moves 2.2x faster than background!).
    In 9:16 vertical mobile cinema, renders FULL-BLEED edge-to-edge without heavy dashboard boxes!
    """
    is_wide = w >= h
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
        )
        return

    # 16:9 widescreen cinema matte presentation over moving dark HD B-roll
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

    is_wide = w >= h
    frame_w = w * (0.76 if is_wide else 0.88)
    frame_h = h * (0.61 if is_wide else 0.45)
    fy = h * (0.06 if is_wide else 0.14)

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

    # Background plate moves at 1.0x speed; foreground subject cutout moves 2.2x faster!
    # Anchor scale pivot near upper-third (-0.16 * frame_h) so portraits/architecture heads never crop at top edge.
    bg_pan_x = (prog - 0.5) * -22.0
    bg_zoom = 1.02 + 0.045 * prog
    pivot_y = -frame_h * 0.16

    if bg_img is not None:
        canvas.save()
        canvas.translate(bg_pan_x, pivot_y)
        canvas.scale(bg_zoom, bg_zoom)
        canvas.translate(0.0, -pivot_y)
        canvas.drawImageRect(bg_img, plate_r, _LINEAR_SAMPLING)
        canvas.restore()

        # Atmospheric depth haze & warm projector motes sandwiched BETWEEN background and 2.5D foreground!
        haze_p = skia.Paint(Color=skia.ColorSetARGB(34, 18, 12, 34))
        canvas.drawRect(plate_r, haze_p)
        mote_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(62, 255, 209, 102))
        for mi in range(12):
            mx_m = -frame_w * 0.48 + ((mi * 173 + t * (22 + (mi % 4) * 8)) % (frame_w * 0.96))
            my_m = -frame_h * 0.46 + ((mi * 119 - t * (14 + (mi % 3) * 6)) % (frame_h * 0.92))
            canvas.drawCircle(mx_m, my_m, 2.0 + (mi % 3) * 1.1, mote_p)

        # Foreground u2netp subject cutout moving 2.2x faster with higher parallax zoom!
        if fg_img is not None:
            fg_pan_x = (prog - 0.5) * 48.4   # exact 2.2x relative displacement vs bg_pan_x (-22 -> +48.4)
            fg_pan_y = (prog - 0.5) * -6.0
            fg_zoom = 1.03 + 0.099 * prog    # exact 2.2x zoom velocity vs bg_zoom (0.045 -> 0.099)
            canvas.save()
            canvas.translate(fg_pan_x, pivot_y + fg_pan_y)
            canvas.scale(fg_zoom, fg_zoom)
            canvas.translate(0.0, -pivot_y)
            fg_paint = skia.Paint(AntiAlias=True)
            fg_paint.setImageFilter(skia.ImageFilters.DropShadow(0, 12, 24, 24, skia.ColorSetARGB(155, 0, 0, 0)))
            canvas.drawImageRect(fg_img, plate_r, _LINEAR_SAMPLING, fg_paint)
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
    """Mode 2: Moving real HD B-roll video backdrop + archival broadsheet with REAL monochrome/sepia editorial photograph & animated Multiply highlighter sweep."""
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
    paper_h = h * (0.61 if is_wide else 0.50)
    py = h * (0.075 if is_wide else 0.145)

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
    inner_w = paper_w - 92.0
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
    h_font, h_lines = _wrap_text_to_width(scene.evidence_headline.upper(), title_tf, 44.0, 24.0, inner_w, 2)
    hy = top_y + 66.0
    for ln in h_lines:
        _draw_safe_string(canvas, ln, left_x, hy, h_font, ink_dark)
        hy += h_font.getSize() * 1.15

    rule_y = hy - 12.0
    canvas.drawLine(left_x, rule_y, right_x, rule_y, rule_p)

    content_top = rule_y + 18.0
    content_bottom = paper_h * 0.5 - 30.0
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
            _draw_monochrome_sepia_photo(canvas, media.primary_photo, photo_rect, radius=6.0, halftone_lines=True)
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
        # 9:16 Vertical Broadsheet: Real monochrome/sepia photo banner on top, highlighted quote below
        photo_h = min(310.0, content_h * 0.48)
        photo_rect = skia.Rect.MakeXYWH(left_x, content_top, inner_w, photo_h)
        if media.primary_photo is not None:
            _draw_monochrome_sepia_photo(canvas, media.primary_photo, photo_rect, radius=6.0, halftone_lines=True)

        q_box_y = content_top + photo_h + 24.0
        rem_h = max(120.0, content_bottom - q_box_y)
        q_font, q_lines = _wrap_text_to_width(scene.evidence_quote, ui_tf, 28.0, 18.0, inner_w - 40.0, 4)
        line_step = q_font.getSize() * 1.38
        callout_r = skia.Rect.MakeXYWH(left_x, q_box_y, inner_w, min(rem_h, len(q_lines) * line_step + 40.0))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(250, 251, 247, 236)))
        canvas.drawRoundRect(callout_r, 10.0, 10.0, rule_p)

        sweep_total = _ease_out_cubic(min(1.0, max(0.0, (prog - 0.06) / 0.68)))
        hl_hex = scene.highlight_color if scene.highlight_color in ("#FFD166", "#FF2E93") else "#FFD166"
        hl_paint = skia.Paint(AntiAlias=True, Color=hex_to_skia(hl_hex, alpha=215 if hl_hex == "#FFD166" else 178))
        hl_paint.setBlendMode(skia.BlendMode.kMultiply)

        n_lns = max(1, len(q_lines))
        qy = q_box_y + 42.0
        for idx_l, qln in enumerate(q_lines):
            _draw_safe_string(canvas, qln, left_x + 20.0, qy, q_font, ink_dark)
            line_prog = max(0.0, min(1.0, sweep_total * n_lns - idx_l))
            if line_prog > 0.01:
                lw = float(q_font.measureText(qln))
                canvas.drawRoundRect(
                    skia.Rect.MakeXYWH(left_x + 12.0, qy - q_font.getSize() * 0.88, (lw + 16.0) * line_prog, q_font.getSize() * 1.16),
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
    """Mode 3: Moving HD B-roll backdrop + translucent tactical world/city route map + live Video-over-Video PiP forensic monitor!"""
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
    """Mode 6: Real moving HD B-roll video backdrop + sliding timeline with REAL photo inset header inside highlighted active card!"""
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
    """Mode 5: Moving HD B-roll backdrop + 3-4 distinct REAL photographs mounted inside Polaroid evidence frames pinned to obsidian nodes with glowing #FF2E93 strings!"""
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

    # Translucent dark veil lets real moving B-roll footage breathe dimly behind the chapter reveal!
    canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.ColorSetARGB(int(alpha * 0.72), 9, 6, 16)))

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
        clean_sub = _sanitize_glyphs(chapter_subtitle.upper(), typeface=ui_tf)
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
    max_display_s: float = 3.2,
) -> None:
    """Draw sleek investigative documentary Lower Third that enters cleanly and fades out after `max_display_s`
    so the cinema footage remains unobstructed.
    """
    vis_dur = min(scene_dur, max_display_s)
    if local_t >= vis_dur:
        return
    enter = _ease_out_cubic(local_t / 0.35)
    exit_a = _ease_out_cubic((vis_dur - local_t) / 0.35) if (vis_dur - local_t) < 0.35 else 1.0
    alpha = int(235 * min(enter, exit_a))
    if alpha <= 10:
        return

    is_wide = w >= h
    box_w = min(w - 140.0, 640.0 if is_wide else 860.0)
    box_h = 90.0
    bx = 72.0 + (1.0 - enter) * -32.0
    by = h * 0.728 if is_wide else 74.0

    r = skia.Rect.MakeXYWH(bx, by, box_w, box_h)
    bg = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.88), 12, 9, 22))
    bg.setImageFilter(skia.ImageFilters.DropShadow(0, 10, 20, 20, skia.ColorSetARGB(int(alpha * 0.7), 0, 0, 0)))
    canvas.drawRoundRect(r, 14.0, 14.0, bg)

    # Vertical glowing accent bar on left edge
    bar_r = skia.Rect.MakeXYWH(bx, by + 10.0, 8.0, box_h - 20.0)
    canvas.drawRoundRect(bar_r, 4.0, 4.0, skia.Paint(AntiAlias=True, Color=hex_to_skia(scene.highlight_color, alpha)))

    lt_title_clean = _sanitize_glyphs(scene.lower_third_title.upper(), typeface=title_tf)
    t_font, t_lns = _wrap_text_to_width(lt_title_clean, title_tf, 26.0, 16.0, box_w - 44.0, 1)
    if t_lns:
        _draw_safe_string(canvas, t_lns[0], bx + 26.0, by + 39.0, t_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166", alpha)))

    lt_sub_clean = _sanitize_glyphs(scene.lower_third_subtitle.upper(), typeface=ui_tf)
    s_font, s_lns = _wrap_text_to_width(lt_sub_clean, ui_tf, 19.0, 13.5, box_w - 44.0, 1)
    if s_lns:
        _draw_safe_string(canvas, s_lns[0], bx + 26.0, by + 71.0, s_font, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 218, 212, 238)))


def _draw_doc_subtitles(
    canvas: skia.Canvas,
    w: int,
    h: int,
    chunks: List[Dict[str, Any]],
    t: float,
    caption_tf: skia.Typeface,
    caption_style: str = "cinema_minimal",
) -> None:
    """Render studio-grade kinetic documentary subtitles via `engine.kinetic_captions.draw_kinetic_captions`
    (supporting all 6 presets: `hormozi_neon`, `karaoke_glow`, `word_slam`, `cinema_minimal`,
    `typewriter_highlight`, `none`) with guaranteed zero edge clipping and built-in fallback.
    """
    resolved_style = (
        resolve_caption_style(caption_style)
        if resolve_caption_style is not None
        else str(caption_style or "cinema_minimal").strip().lower()
    )
    if resolved_style == "none":
        return

    is_wide = w >= h
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
            palette=ACTIVE_PILL_PALETTE,
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
                        pbg, ptx, (gr, gg, gb, ga) = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
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
def _load_scene_skia_photos(
    scene: NetflixDocScene,
    assets: SceneMediaAssets,
    w: int,
    h: int,
) -> LoadedSceneSkiaMedia:
    """Pre-load real photographs into Skia Images once before the 30fps loop (zero per-frame I/O)."""
    loaded = LoadedSceneSkiaMedia()
    is_wide = w >= h

    if scene.visual_mode in ("parallax_25d_photo", "cinema_multishot") and assets.primary_photo_path is not None:
        if scene.visual_mode == "cinema_multishot" or not is_wide:
            matte_w, matte_h = w, h
        else:
            matte_w = int(round(w * 0.76))
            matte_h = int(round(h * 0.61))
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
            pw, ph = (620, 420) if is_wide else (840, 360)
        elif scene.visual_mode == "video_pip_evidence":
            pw, ph = (760, 340) if is_wide else (880, 340)
        elif scene.visual_mode == "broll_video_pip":
            pw, ph = (720, 240) if is_wide else (860, 260)
        else:
            pw, ph = (640, 400)
        loaded.primary_photo = load_skia_image_cover(assets.primary_photo_path, pw, ph)

    if assets.extra_photo_paths:
        if scene.visual_mode == "cinema_multishot":
            ew, eh = w, h
        elif scene.visual_mode == "red_string_board":
            ew, eh = (260, 260)
        elif scene.visual_mode == "sliding_timeline":
            ew, eh = (460, 180) if is_wide else (260, 220)
        else:
            ew, eh = (480, 300)
        for ep in assets.extra_photo_paths:
            img = load_skia_image_cover(ep, ew, eh)
            if img is not None:
                loaded.extra_photos.append(img)

    return loaded


def _compute_pip_dimensions(visual_mode: VisualModeType, is_wide: bool) -> Tuple[int, int]:
    if visual_mode == "cinema_multishot":
        return (1920, 1080) if is_wide else (1080, 1920)
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
    caption_style: str = "cinema_minimal",
    cut_cadence_s: float = 2.6,
) -> Tuple[Path, bool]:
    """Render one documentary scene at 30fps in C++ Skia directly to disk with REAL moving B-roll video,
    Video-over-Video PiP monitor, REAL photographs, kinetic captions, LUT 02_dark_wealth.cube & 35mm film grain.
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

    # Open sequential low-RAM VideoLayerReaders for Main HD B-Roll + optional PiP Video-over-Video
    primary_reader: Optional[VideoLayerReader] = None
    pip_reader: Optional[VideoLayerReader] = None
    if assets.primary_broll_mp4 is not None and Path(assets.primary_broll_mp4).exists():
        primary_reader = VideoLayerReader(assets.primary_broll_mp4, w, h, fps=fps)
    if scene.visual_mode in PIP_ENABLED_MODES and assets.pip_broll_mp4 is not None and Path(assets.pip_broll_mp4).exists():
        pip_w, pip_h = _compute_pip_dimensions(scene.visual_mode, is_wide)
        pip_reader = VideoLayerReader(assets.pip_broll_mp4, pip_w, pip_h, fps=fps)

    surface = skia.Surface(w, h)
    chunks = group_words_into_chunks(scene_words, max_words=3)
    total_frames = max(1, int(round(scene_dur * fps)))
    exact_dur = total_frames / float(fps)

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    vf_parts = []
    if lut_path.exists():
        # Subtle 32% LUT blend preserves crisp legibility of Gold/Lime/Pink UI overlays while imparting Dark Wealth cinema grade
        vf_parts.append(
            f"split[orig][lut_in];[lut_in]lut3d=file='{lut_path.as_posix()}':interp=trilinear[lut_out];"
            f"[orig][lut_out]blend=all_mode=normal:all_opacity=0.32"
        )
    # Subtle 35mm cinema film grain
    vf_parts.append("noise=alls=4:allf=t+u")
    vf_parts.append(hw_suffix)
    vf_chain = ",".join(vf_parts)

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

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
    )
    assert proc.stdin is not None

    # Darken level for primary video reader (crisp & vivid on video-first modes; full brightness on scrim modes so scrim alone controls visibility!)
    primary_darken = 0.18 if scene.visual_mode in ("broll_video_pip", "parallax_25d_photo") else 0.0

    try:
        for fi in range(total_frames):
            local_t = fi / float(fps)
            global_t = global_t_offset + local_t
            c = surface.getCanvas()

            primary_frame = primary_reader.read_skia_frame(darken_alpha=primary_darken) if primary_reader is not None else None

            if chapter_intro_s > 0.0 and local_t < chapter_intro_s:
                _draw_video_backdrop_layer(
                    c,
                    w,
                    h,
                    primary_frame,
                    global_t,
                    local_t / max(0.1, chapter_intro_s),
                    scrim_alpha=155,
                    ken_burns_zoom=0.04,
                    show_grid=False,
                    show_dust=True,
                )
                _draw_chapter_card_overlay(
                    c,
                    w,
                    h,
                    scene.chapter_card or _spaced_chapter_label("I"),
                    scene.chapter_subtitle or "",
                    local_t,
                    chapter_intro_s,
                    title_tf,
                    ui_tf,
                )
            else:
                body_t = max(0.0, local_t - chapter_intro_s)
                body_dur = max(0.5, exact_dur - chapter_intro_s)
                prog = min(1.0, body_t / body_dur)
                pip_frame = pip_reader.read_skia_frame(darken_alpha=0.0) if pip_reader is not None else None

                if scene.visual_mode == "cinema_multishot":
                    _draw_mode_cinema_multishot(
                        c, w, h, scene, prog, body_t, body_dur, global_t, primary_frame, pip_frame, loaded_media,
                        cut_cadence_s=cut_cadence_s, s_idx=s_idx,
                    )
                elif scene.visual_mode == "broll_video_pip":
                    _draw_mode_broll_video_pip(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, pip_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "video_pip_evidence":
                    _draw_mode_video_pip_evidence(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, pip_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "newspaper_highlighter":
                    _draw_mode_newspaper_highlighter(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "dark_map_route":
                    _draw_mode_dark_map_route(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, pip_frame, is_en=is_en)
                elif scene.visual_mode == "sliding_timeline":
                    _draw_mode_sliding_timeline(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, loaded_media, is_en=is_en)
                elif scene.visual_mode == "red_string_board":
                    _draw_mode_red_string_board(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, loaded_media, is_en=is_en)
                else:
                    _draw_mode_parallax_25d_photo(c, w, h, scene, prog, body_t, global_t, title_tf, ui_tf, primary_frame, loaded_media, is_en=is_en)

                # Show sleek Lower-Third ONLY on Act/Location shifts (prevents repetitive dashboard clutter!)
                if s_idx == 0 or scene.chapter_card is not None or (s_idx % 4 == 0):
                    _draw_sleek_lower_third(c, w, h, scene, body_t, body_dur, title_tf, ui_tf, max_display_s=3.2)
                _draw_doc_subtitles(c, w, h, chunks, local_t, caption_tf, caption_style=caption_style)

            # Top slim cinema progress bar
            bar_w = max(8.0, w * min(1.0, global_t / max(0.1, total_est_dur)))
            bar_p = skia.Paint(AntiAlias=True)
            bar_p.setShader(
                skia.GradientShader.MakeLinear(
                    [(0, 0), (w, 0)],
                    [hex_to_skia("#FFD166"), hex_to_skia("#FF2E93"), hex_to_skia("#B8FF01")],
                )
            )
            c.drawRoundRect(skia.Rect.MakeXYWH(0, 0, bar_w, 8), 4.0, 4.0, bar_p)

            proc.stdin.write(surface.makeImageSnapshot().tobytes())
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

    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait(timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"NetflixDoc scene #{s_idx + 1} encode failed: {stderr.decode(errors='ignore')}")
    return out_scene_mp4, loaded_media.u2netp_separated


def _find_cached_work_asset(work_dir: Path, prefix: str, min_bytes: int = 4096) -> Optional[Path]:
    for cand in sorted(work_dir.glob(f"{prefix}_*")):
        try:
            if cand.exists() and cand.stat().st_size >= min_bytes:
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
) -> Tuple[List[SceneMediaAssets], Dict[str, Any]]:
    """Fetch unique real HD B-roll videos, secondary PiP videos, and real/bespoke Gemini archival photographs."""
    used_video_hashes: Set[str] = set()
    used_photo_urls: Set[str] = set()

    assets_list: List[SceneMediaAssets] = []
    broll_clips_used: List[str] = []
    pip_clips_used: List[str] = []
    photos_used: List[str] = []
    fallback_video_pool: List[Path] = []
    fallback_photo_pool: List[Path] = []

    for s_idx, sc in enumerate(scenes):
        item = SceneMediaAssets()
        sc_mood = str(getattr(sc, "mood", None) or mood or "corporate_thriller")
        mood_defaults = _OPEN_TOPIC_FALLBACK_MEDIA.get(sc_mood, _OPEN_TOPIC_FALLBACK_MEDIA["epic_history"])

        # 1. Primary HD B-Roll Video (EVERY SINGLE SCENE — mood-aware, never finance stocks for horror/history!)
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
            )
        if main_mp4 is None and fallback_video_pool:
            main_mp4 = fallback_video_pool[s_idx % len(fallback_video_pool)]
        if main_mp4 is not None:
            item.primary_broll_mp4 = main_mp4
            broll_clips_used.append(str(main_mp4))
            if main_mp4 not in fallback_video_pool:
                fallback_video_pool.append(main_mp4)

        # 2. Secondary Video-over-Video (PiP) B-Roll Video
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
                )
            if pip_mp4 is None and fallback_video_pool:
                alt = next((p for p in fallback_video_pool if p != main_mp4), fallback_video_pool[0])
                pip_mp4 = alt
            if pip_mp4 is not None:
                item.pip_broll_mp4 = pip_mp4
                pip_clips_used.append(str(pip_mp4))
                if pip_mp4 not in fallback_video_pool:
                    fallback_video_pool.append(pip_mp4)

        # 3. Real / Bespoke Archival Photographs (Gemini Native Image + Pixabay + Wikimedia seamless blend!)
        if sc.visual_mode == "red_string_board":
            q_list = list(sc.extra_photo_queries_en or [])
            if not q_list:
                q_list = [sc.photo_query_en or mood_defaults["photos"][0], *mood_defaults["photos"][:3]]
            for pi in range(4):
                ppath = _find_cached_work_asset(work_dir, f"photo_sc{s_idx:02d}_board_{pi + 1}") if resume else None
                if ppath is None:
                    pq = q_list[pi % len(q_list)]
                    ppath = fetch_doc_hero_or_archival_photo(
                        pq,
                        work_dir,
                        f"sc{s_idx:02d}_board_{pi + 1}",
                        min_width=640,
                        used_urls=used_photo_urls,
                        mood=sc_mood,
                        prefer_gemini=(bool(sc.prefer_gemini_photo) and pi == 0),
                        aspect_ratio="16:9",
                        bespoke_prompt_en=sc.bespoke_image_prompt_en if pi == 0 else "",
                    )
                if ppath is None and fallback_photo_pool:
                    ppath = fallback_photo_pool[pi % len(fallback_photo_pool)]
                if ppath is not None:
                    item.extra_photo_paths.append(ppath)
                    photos_used.append(str(ppath))
                    if ppath not in fallback_photo_pool:
                        fallback_photo_pool.append(ppath)
            if item.extra_photo_paths:
                item.primary_photo_path = item.extra_photo_paths[0]
        elif sc.visual_mode == "sliding_timeline":
            q_list = list(sc.extra_photo_queries_en or [sc.photo_query_en or mood_defaults["photos"][0]])
            for pi in range(min(3, max(2, len(sc.timeline_points)))):
                ppath = _find_cached_work_asset(work_dir, f"photo_sc{s_idx:02d}_tl_{pi + 1}") if resume else None
                if ppath is None:
                    pq = q_list[pi % len(q_list)]
                    ppath = fetch_doc_hero_or_archival_photo(
                        pq,
                        work_dir,
                        f"sc{s_idx:02d}_tl_{pi + 1}",
                        min_width=640,
                        used_urls=used_photo_urls,
                        mood=sc_mood,
                        prefer_gemini=(bool(sc.prefer_gemini_photo) and pi == 0),
                        aspect_ratio="16:9",
                    )
                if ppath is None and fallback_photo_pool:
                    ppath = fallback_photo_pool[pi % len(fallback_photo_pool)]
                if ppath is not None:
                    item.extra_photo_paths.append(ppath)
                    photos_used.append(str(ppath))
                    if ppath not in fallback_photo_pool:
                        fallback_photo_pool.append(ppath)
            if item.extra_photo_paths:
                item.primary_photo_path = item.extra_photo_paths[0]
        elif sc.visual_mode == "cinema_multishot":
            # Fetch primary high-res archival / Google Flow bespoke plate + 1 extra distinct photo for multi-shot cuts!
            ppath = _find_cached_work_asset(work_dir, f"photo_sc{s_idx:02d}_photo") if resume else None
            if ppath is None:
                pq = sc.photo_query_en or sc.image_prompt_en or mood_defaults["photos"][s_idx % len(mood_defaults["photos"])]
                ppath = fetch_doc_hero_or_archival_photo(
                    pq,
                    work_dir,
                    f"sc{s_idx:02d}_photo",
                    min_width=760,
                    used_urls=used_photo_urls,
                    mood=sc_mood,
                    prefer_gemini=bool(sc.prefer_gemini_photo),
                    aspect_ratio=aspect_ratio,
                    bespoke_prompt_en=sc.bespoke_image_prompt_en or "",
                )
            if ppath is None and fallback_photo_pool:
                ppath = fallback_photo_pool[s_idx % len(fallback_photo_pool)]
            if ppath is not None:
                item.primary_photo_path = ppath
                photos_used.append(str(ppath))
                if ppath not in fallback_photo_pool:
                    fallback_photo_pool.append(ppath)

            # Secondary distinct archival/Flow photo for Shot 3
            extra_q_list = list(sc.extra_photo_queries_en or [])
            extra_q = next((q for q in extra_q_list if q.lower() != (sc.photo_query_en or "").lower()), "") or mood_defaults["photos"][(s_idx + 2) % len(mood_defaults["photos"])]
            epath = _find_cached_work_asset(work_dir, f"photo_sc{s_idx:02d}_ms2") if resume else None
            if epath is None:
                epath = fetch_doc_hero_or_archival_photo(
                    extra_q,
                    work_dir,
                    f"sc{s_idx:02d}_ms2",
                    min_width=720,
                    used_urls=used_photo_urls,
                    mood=sc_mood,
                    prefer_gemini=False,
                    aspect_ratio=aspect_ratio,
                )
            if epath is not None:
                item.extra_photo_paths.append(epath)
                photos_used.append(str(epath))
                if epath not in fallback_photo_pool:
                    fallback_photo_pool.append(epath)
        elif sc.visual_mode in ("parallax_25d_photo", "newspaper_highlighter", "broll_video_pip", "video_pip_evidence"):
            min_w = 800 if sc.visual_mode == "parallax_25d_photo" else 640
            ppath = _find_cached_work_asset(work_dir, f"photo_sc{s_idx:02d}_photo") if resume else None
            if ppath is None:
                pq = sc.photo_query_en or sc.image_prompt_en or mood_defaults["photos"][s_idx % len(mood_defaults["photos"])]
                ppath = fetch_doc_hero_or_archival_photo(
                    pq,
                    work_dir,
                    f"sc{s_idx:02d}_photo",
                    min_width=min_w,
                    used_urls=used_photo_urls,
                    mood=sc_mood,
                    prefer_gemini=bool(sc.prefer_gemini_photo),
                    aspect_ratio=aspect_ratio,
                    bespoke_prompt_en=sc.bespoke_image_prompt_en or "",
                )
            if ppath is None and fallback_photo_pool:
                ppath = fallback_photo_pool[s_idx % len(fallback_photo_pool)]
            if ppath is not None:
                item.primary_photo_path = ppath
                photos_used.append(str(ppath))
                if ppath not in fallback_photo_pool:
                    fallback_photo_pool.append(ppath)

        assets_list.append(item)

    telemetry = {
        "broll_clips_used": broll_clips_used,
        "broll_clips_count": len(broll_clips_used),
        "pip_clips_used": pip_clips_used,
        "pip_clips_count": len(pip_clips_used),
        "photos_used": photos_used,
        "photos_count": len(photos_used),
        "video_over_video_active": len(pip_clips_used) > 0,
    }
    return assets_list, telemetry


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
    if music_mp3 is not None and str(music_mp3).strip().lower() not in ("", "auto"):
        p_forced = Path(music_mp3)
        if p_forced.exists():
            return p_forced

    music_dir = ASSETS_DIR / "music"
    mood = str(plan_obj.mood or _classify_topic_mood(plan_obj.title)).strip().lower()

    if mood in ("dark_horror", "investigative_crime"):
        cand = music_dir / "dark_mystery_horror.mp3"
        if cand.exists():
            return cand
        if select_music_for_mood is not None:
            try:
                return select_music_for_mood(plan_obj.title, default_file="dark_mystery_horror.mp3", mood=mood)
            except Exception:
                pass
        return music_dir / "dark_pulse.mp3"

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
) -> Tuple[Path, bool]:
    """Concatenate rendered documentary scenes using smooth 0.35s FFmpeg `xfade` cinema transitions
    (`fadeblack`, `smoothleft`, `zoomin`, `dissolve`, `wiperight`) with hardware QuickSync VAAPI
    encoding (and automatic software fallback) while keeping Core i5 RAM & thermals safe.
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
        for b_idx, start in enumerate(range(0, len(scene_mp4_paths), batch_size)):
            chunk_paths = scene_mp4_paths[start : start + batch_size]
            chunk_trs = transitions[start : start + len(chunk_paths) - 1]
            b_out = work_dir / f"_xfade_batch_{b_idx:02d}.mp4"
            _concat_scenes_with_xfade(
                chunk_paths,
                chunk_trs,
                xfade_dur=xfade_dur,
                fps=fps,
                out_mp4=b_out,
                work_dir=work_dir,
                thermal_limit_c=thermal_limit_c,
            )
            batch_outs.append(b_out)
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
            video_concat_txt = work_dir / "doc_video_concat_fallback.txt"
            video_concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in scene_mp4_paths), encoding="utf-8")
            run_ffmpeg_safe(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(video_concat_txt),
                    "-c:v", "copy", "-an",
                    str(out_mp4),
                ],
                thermal_limit_c=thermal_limit_c,
            )
            return out_mp4, False


async def render_netflix_documentary(
    plan: Union[Dict[str, Any], NetflixDocPlan],
    work_dir: Path,
    out_master_mp4: Path,
    music_mp3: Optional[Union[Path, str]] = None,
    fps: int = 30,
    thermal_limit_c: float = 85.0,
    progress_cb=None,
    caption_style: Optional[str] = None,
    music_volume: float = 0.17,
    voice_rate: str = "+0%",
    voice_pitch: str = "-4Hz",
    resume: bool = False,
    voice_engine: str = "auto",
    cut_cadence_s: float = 2.6,
) -> Dict[str, Any]:
    """Render a complete Netflix / MagnatesMedia / Dark History cinema documentary scene-by-scene to disk
    with REAL moving HD B-roll video in every scene, Video-over-Video (PiP), REAL/Bespoke Gemini photographs
    + u2netp 2.5D parallax, 0.35s FFmpeg `xfade` cinema transitions, Hollywood multi-layered SFX,
    mood-matched atmosphere music bed, kinetic captions, LUT 02_dark_wealth.cube, 35mm film grain,
    and -14 LUFS broadcast audio mastering.
    """
    fps = 30 if int(fps) <= 30 else 60
    work_dir = Path(work_dir)
    out_master_mp4 = Path(out_master_mp4)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_master_mp4.parent.mkdir(parents=True, exist_ok=True)

    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    plan_obj = NetflixDocPlan.model_validate(plan_dict)
    doc_mood = _normalize_mood(plan_obj.mood, plan_obj.title)
    plan_obj.mood = doc_mood
    for sc in plan_obj.scenes:
        if not sc.mood or (sc.mood == "corporate_thriller" and doc_mood != "corporate_thriller"):
            sc.mood = doc_mood

    eff_caption_style = str(caption_style or plan_obj.caption_style or "cinema_minimal").strip()
    if resolve_caption_style is not None:
        eff_caption_style = resolve_caption_style(eff_caption_style)

    w, h = (1920, 1080) if plan_obj.aspect_ratio == "16:9" else (1080, 1920)
    lut_path = ASSETS_DIR / "luts" / (plan_obj.lut_file or "02_dark_wealth.cube")
    sfx_dir = ASSETS_DIR / "sfx"

    # Guarantee Pro Cinema Hollywood SFX & dark_mystery_horror.mp3 exist before audio mastering
    if ensure_pro_cinema_sfx is not None:
        try:
            await asyncio.to_thread(ensure_pro_cinema_sfx, False, thermal_limit_c)
        except Exception:
            pass

    resolved_music_mp3 = _select_doc_music_bed(plan_obj, music_mp3=music_mp3, thermal_limit_c=thermal_limit_c)
    eff_music_vol = max(0.0, min(0.45, float(music_volume if music_volume is not None else 0.17)))

    title_tf, font_info = _load_verified_typeface("Montserrat-Black.ttf", role="doc_title")
    ui_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="doc_ui")
    caption_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="doc_caption")

    # 1. Pre-fetch real HD B-roll videos, secondary PiP videos, and real/bespoke archival photographs for all scenes
    if progress_cb:
        progress_cb(
            10,
            "♻️ Reaproveitando mídias B-roll HD e fotos em cache do ponto de parada..."
            if resume
            else "Capturando vídeos B-roll HD, feeds PiP e fotografias/artes cinematográficas de arquivo...",
        )
    scene_media_list, media_telemetry = await asyncio.to_thread(
        _prefetch_scene_media_sync,
        plan_obj.scenes,
        work_dir,
        plan_obj.aspect_ratio,
        doc_mood,
        resume,
    )

    # 2. Synthesize narration per scene & compute exact timeline with Chapter Cards + Hollywood SFX
    scene_records: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    audio_parts: List[Path] = []
    sfx_events: List[Tuple[Path, float, float]] = []
    transitions_plan: List[str] = []

    def _add_sfx(t_s: float, vol: float, *cand_names: str) -> None:
        p_sfx = _pick_sfx(sfx_dir, *cand_names)
        if p_sfx is not None and t_s >= 0.0:
            sfx_events.append((p_sfx, round(t_s, 3), float(vol)))

    cursor_t = 0.0
    pause_gap_s = 0.24
    xfade_dur = CINEMA_XFADE_DURATION_S
    gap_wav = work_dir / "_doc_gap.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{pause_gap_s:.2f}", str(gap_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    n_scenes = len(plan_obj.scenes)
    is_dark_mood = doc_mood in ("dark_horror", "investigative_crime")

    for s_idx, sc in enumerate(plan_obj.scenes):
        if progress_cb:
            pct = 18 + int(24 * ((s_idx + 1) / float(max(1, n_scenes))))
            progress_cb(pct, f"Sintetizando narração cinema cena {s_idx + 1}/{n_scenes} ({sc.visual_mode})...")

        tr_name = sc.transition_type or _select_transition_for_scene(s_idx, sc.visual_mode, sc.chapter_card is not None)
        if s_idx > 0:
            transitions_plan.append(tr_name)
            # Sync Hollywood transition SFX RIGHT on the 0.35s xfade cut!
            if sc.chapter_card:
                # Rising thriller tension leading straight into the black dip + Chapter Card braam/boom!
                if cursor_t >= 1.4:
                    _add_sfx(cursor_t - 1.25, 0.26, "riser_tension.wav")
            elif tr_name in ("smoothleft", "wiperight"):
                _add_sfx(max(0.0, cursor_t - 0.06), 0.42, "whoosh_deep.wav", "whoosh_fast.wav")
            elif tr_name == "zoomin":
                _add_sfx(max(0.0, cursor_t - 0.04), 0.44, "flash_impact.wav", "cinematic_hit.wav")
            else:
                _add_sfx(max(0.0, cursor_t - 0.05), 0.38, "whoosh_deep.wav")
                _add_sfx(cursor_t + 0.03, 0.32, "sub_boom.wav")

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
            # Signature Chapter Card impact: chilling horror_braam for dark_horror, massive sub_boom for all others!
            if doc_mood == "dark_horror":
                _add_sfx(cursor_t + 0.04, 0.56, "horror_braam.wav", "sub_boom.wav")
            else:
                _add_sfx(cursor_t + 0.04, 0.54, "sub_boom.wav", "cinematic_hit.wav")

        existing_sc_mp4 = work_dir / f"doc_scene_{s_idx:03d}.mp4"
        existing_vad_wav = work_dir / f"doc_narr_{s_idx:03d}_vad.wav"
        scene_already_rendered = False
        if resume and existing_sc_mp4.exists() and existing_vad_wav.exists():
            est_wav_d = _probe_wav_duration_s(existing_vad_wav)
            if est_wav_d > 0.3:
                exp_sc_d = round(chapter_intro_s + est_wav_d + pause_gap_s + (xfade_dur if s_idx < n_scenes - 1 else 0.0), 3)
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
        )

        # Shift scene words by chapter_intro_s (local scene time) and cursor_t (master time)
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

        # Hollywood mood-matched foley & scene-entrance SFX
        body_start_t = cursor_t + chapter_intro_s
        if s_idx == 0:
            if is_dark_mood:
                _add_sfx(0.04, 0.56, "horror_braam.wav", "sub_boom.wav")
            else:
                _add_sfx(0.04, 0.50, "cinematic_hit.wav", "sub_boom.wav")
        if sc.visual_mode == "cinema_multishot":
            eff_cad = max(1.8, min(4.2, float(cut_cadence_s or 2.6)))
            body_est = max(1.0, speech_dur + pause_gap_s)
            n_sub = max(2, min(4, int(round(body_est / eff_cad))))
            sub_dur = body_est / float(n_sub)
            for si_cut in range(1, n_sub):
                cut_t = body_start_t + si_cut * sub_dur
                if si_cut % 2 == 1:
                    _add_sfx(cut_t - 0.04, 0.24, "whoosh_fast.wav", "camera_shutter.wav")
                else:
                    _add_sfx(cut_t - 0.03, 0.22, "flash_impact.wav", "whoosh_fast.wav")
        elif sc.visual_mode == "broll_video_pip":
            _add_sfx(body_start_t + 0.14, 0.34, "whoosh_fast.wav", "whoosh_deep.wav")
        elif sc.visual_mode == "video_pip_evidence":
            _add_sfx(body_start_t + 0.12, 0.36, "flash_impact.wav", "ui_click.wav")
        elif sc.visual_mode == "parallax_25d_photo":
            _add_sfx(body_start_t + 0.12, 0.40, "flash_impact.wav", "camera_shutter.wav")
        elif sc.visual_mode == "newspaper_highlighter":
            _add_sfx(body_start_t + 0.10, 0.44, "paper_flip.wav", "whoosh_deep.wav")
        elif sc.visual_mode == "dark_map_route":
            _add_sfx(body_start_t + 0.14, 0.32, "ui_click.wav")
            _add_sfx(body_start_t + 0.24, 0.28, "whoosh_fast.wav")
        elif sc.visual_mode == "sliding_timeline":
            if doc_mood == "corporate_thriller":
                _add_sfx(body_start_t + 0.16, 0.32, "cash_chime.wav", "ui_click.wav")
            else:
                _add_sfx(body_start_t + 0.14, 0.38, "sub_boom.wav", "ui_click.wav")
        elif sc.visual_mode == "red_string_board":
            _add_sfx(body_start_t + 0.10, 0.38, "heartbeat.wav", "sub_boom.wav")
            _add_sfx(body_start_t + 0.36, 0.30, "paper_flip.wav", "whoosh_fast.wav")

        audio_scene_dur = round(chapter_intro_s + speech_dur + pause_gap_s, 3)
        scene_records.append(
            {
                "s_idx": s_idx,
                "scene": sc,
                "start_t": cursor_t,
                "scene_dur": audio_scene_dur,
                "chapter_intro_s": chapter_intro_s,
                "local_words": local_words,
                "media_assets": scene_media_list[s_idx],
            }
        )
        audio_parts.append(wav_p)
        audio_parts.append(gap_wav)
        cursor_t = round(cursor_t + audio_scene_dur, 3)

    # Concatenate full narration WAV and master Broadcast Audio (-14 LUFS + 0.40s clean tail)
    concat_audio_txt = work_dir / "doc_audio_concat.txt"
    concat_audio_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in audio_parts), encoding="utf-8")
    raw_full_wav = work_dir / "doc_narration_full.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_audio_txt), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_full_wav)],
        thermal_limit_c=thermal_limit_c,
    )

    master_audio = work_dir / "doc_master_audio.m4a"
    master_audio, final_dur = await asyncio.to_thread(
        master_broadcast_audio,
        raw_full_wav,
        resolved_music_mp3,
        sfx_events,
        master_audio,
        cursor_t,
        eff_music_vol,
        0.40,
        thermal_limit_c=thermal_limit_c,
    )

    # Extend last scene by 0.40s broadcast audio tail; add +0.35s visual handle to scenes 0..N-2 for exact A/V sync across xfade!
    if scene_records:
        tail_delta = max(0.0, round(final_dur - cursor_t, 3))
        scene_records[-1]["scene_dur"] = round(scene_records[-1]["scene_dur"] + tail_delta, 3)
        for idx_r, rec in enumerate(scene_records):
            rec["render_dur"] = round(rec["scene_dur"] + (xfade_dur if idx_r < len(scene_records) - 1 else 0.0), 3)

    # 3. Render each scene to disk one-by-one (os.nice(10) + thermal_guard_wait -> flat RAM!)
    scene_mp4_paths: List[Path] = []
    u2netp_25d_used = False
    for rec in scene_records:
        s_idx = rec["s_idx"]
        sc: NetflixDocScene = rec["scene"]
        out_sc_mp4 = work_dir / f"doc_scene_{s_idx:03d}.mp4"
        if resume and _is_valid_cached_scene_mp4(out_sc_mp4, w, h, fps, rec["render_dur"]):
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
                f"Renderizando cena Skia C++ {s_idx + 1}/{n_scenes} [{sc.visual_mode}] ({w}x{h} @ {fps}fps | Vídeo Real + PiP + Fotos)...",
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
            cut_cadence_s,
        )
        if did_u2netp:
            u2netp_25d_used = True
        scene_mp4_paths.append(rendered_p)

    # 4. Join rendered scenes with smooth 0.35s FFmpeg `xfade` cinema transitions + mux master broadcast audio
    if progress_cb:
        progress_cb(88, "Aplicando transições cinema FFmpeg xfade (0.35s) e mixagem master -14 LUFS...")
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
        "master_mp4": str(out_master_mp4),
        "master_audio": str(master_audio),
        "base_scenes_mp4": str(base_scenes_mp4),
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
        "film_grain": "35mm_active",
        "xfade_active": xfade_active,
        "xfade_duration_s": xfade_dur if xfade_active else 0.0,
        "transitions_used": transitions_plan,
        "sfx_events_count": len(sfx_events),
        "doc_engine": "netflix_magnates_cinema_v3_open_topic_xfade",
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
