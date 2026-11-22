"""FrimeRise Studio-Grade Kinetic Caption Engine (Skia C++).

Provides genuine frame-by-frame motion physics (30fps & 60fps smooth) across 5 pro
caption presets plus a clean `none` mode, reusable by all FrimeRise render engines
(SkiaMotionCompositor, NetflixDocStudio, GlobalScaler, Cartoon2DStudio, etc.).

Public API:
- CAPTION_STYLES: Dict[str, Dict[str, Any]]
- CAPTION_STYLE_IDS: Tuple[str, ...]
- DEFAULT_CAPTION_PALETTE: List[Tuple[str, str, Tuple[int, int, int, int]]]
- list_caption_styles() -> List[Dict[str, Any]]
- resolve_caption_style(style: Optional[str]) -> str
- draw_kinetic_captions(
      canvas, chunks, t, w, h, typeface,
      style="hormozi_neon", y_ratio=0.84, font_size=None, palette=None,
  ) -> None
"""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import skia

BASE_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"
EMOJI_FONT_PATH = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
_EMOJI_TF_LOADED = False
_EMOJI_TF_CACHE: Optional[skia.Typeface] = None
_COURIER_BOLD_TF_LOADED = False
_COURIER_BOLD_TF_CACHE: Optional[skia.Typeface] = None
_SELECTIVE_CHUNKS_CACHE: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}

# Default 3-color neon rotation: (accent_bg_hex, contrast_text_hex, glow_rgba)
DEFAULT_CAPTION_PALETTE: List[Tuple[str, str, Tuple[int, int, int, int]]] = [
    ("#B8FF01", "#0B0713", (184, 255, 1, 195)),   # Verde Lima Neon + Ink escuro
    ("#FF2E93", "#FFFFFF", (255, 46, 147, 205)),  # Rosa Frime Neon + Branco puro
    ("#FFD166", "#0B0713", (255, 209, 102, 195)), # Dourado Editorial + Ink escuro
]

# Dark-Cinema 3-color historical/horror rotation: Blood Crimson + Antique Gold + Torch Amber
# Eliminates upbeat neon lime green & bubblegum pink in dark-history / horror / investigative documentaries.
DARK_CINEMA_PILL_PALETTE: List[Tuple[str, str, Tuple[int, int, int, int]]] = [
    ("#9E1B24", "#FFFFFF", (185, 28, 38, 175)),   # Blood Crimson + Pure White
    ("#FFD166", "#0B0713", (255, 209, 102, 170)), # Antique Gold + Obsidian Ink
    ("#D97706", "#FFFFFF", (225, 125, 18, 165)),  # Torch Amber + Pure White
]

ACTIVE_PILL_PALETTE: List[Tuple[str, str, Tuple[int, int, int, int]]] = DEFAULT_CAPTION_PALETTE

DARK_CINEMA_MOODS: Tuple[str, ...] = (
    "dark_horror",
    "epic_history",
    "investigative_crime",
    "dark_cinema",
    "dark_mystery",
    "dark_horror_cinema",
    "dark_investigative",
    "historical_epic",
)


def _is_default_neon_palette(
    pal: Optional[List[Tuple[str, str, Tuple[int, int, int, int]]]]
) -> bool:
    """Return True if `pal` is None or contains the default neon lime/pink palette colors."""
    if not pal:
        return True
    if pal == DEFAULT_CAPTION_PALETTE:
        return True
    bg_hexes = {
        str(item[0]).strip().upper()
        for item in pal
        if isinstance(item, (tuple, list)) and len(item) >= 2
    }
    return "#B8FF01" in bg_hexes or "#FF2E93" in bg_hexes


def resolve_caption_palette(
    palette: Optional[List[Tuple[str, str, Tuple[int, int, int, int]]]] = None,
    mood: str = "",
    style: Optional[str] = None,
) -> List[Tuple[str, str, Tuple[int, int, int, int]]]:
    """Auto-select DARK_CINEMA_PILL_PALETTE whenever mood is dark/historical/investigative
    or style is 'dark_cinema' and no custom non-neon palette was forced.
    """
    mood_norm = str(mood or "").strip().lower()
    style_norm = str(style or "").strip().lower().replace("-", "_").replace(" ", "_")
    is_dark = (
        mood_norm in DARK_CINEMA_MOODS
        or style_norm == "dark_cinema"
        or any(k in mood_norm for k in ("horror", "history", "investig", "crime", "macabr", "dark"))
    )
    if is_dark and _is_default_neon_palette(palette):
        return list(DARK_CINEMA_PILL_PALETTE)
    if palette and len(palette) > 0:
        return list(palette)
    return list(DEFAULT_CAPTION_PALETTE)

CAPTION_STYLES: Dict[str, Dict[str, Any]] = {
    "hormozi_neon": {
        "id": "hormozi_neon",
        "label": "Hormozi Neon (CapCut Pro Bounce)",
        "badge": "CapCut Pro",
        "desc": "Entrada slide-up com mola, pop elástico (1.0->1.24->1.13), micro-inclinação ±2.2° e pílula neon dual-bloom.",
        "accent": "#B8FF01",
        "best_for": ["cinematic_broll", "cartoon_2d", "shorts"],
    },
    "karaoke_glow": {
        "id": "karaoke_glow",
        "label": "Karaoke Glow (Varredura Neon)",
        "badge": "Viral Sync",
        "desc": "Gradiente neon ouro/lima varrendo cada palavra da esquerda para a direita em sincronia exata + onda flutuante.",
        "accent": "#38F9D7",
        "best_for": ["cinematic_broll", "music", "shorts"],
    },
    "word_slam": {
        "id": "word_slam",
        "label": "Word Slam (Impacto 3D)",
        "badge": "High Impact",
        "desc": "Tipografia gigante entrando de 1.48x->1.00x com micro-shake, gradiente metálico 3D e sombra cinema.",
        "accent": "#FF2E93",
        "best_for": ["cinematic_broll", "hooks", "shorts"],
    },
    "selective_emphasis": {
        "id": "selective_emphasis",
        "label": "Selective Emphasis (Doc 16:9 Keyword Stamp)",
        "badge": "Vox / Fern",
        "desc": "Dispara apenas em datas, anos, séculos, nomes históricos e verbos de impacto em Courier Prime Bold 64px.",
        "accent": "#EAB308",
        "best_for": ["netflix_doc", "documentary", "youtube", "16:9"],
    },
    "cinema_minimal": {
        "id": "cinema_minimal",
        "label": "Cinema Minimal (Netflix Blur / 16:9 Selective)",
        "badge": "Netflix Doc",
        "desc": "Modo Selective Emphasis em 16:9 (Courier Prime 64px em palavras-chave) e blur-reveal elegante em 9:16.",
        "accent": "#FFD166",
        "best_for": ["netflix_doc", "documentary", "youtube"],
    },
    "typewriter_highlight": {
        "id": "typewriter_highlight",
        "label": "Typewriter Dossiê (Marca-Texto)",
        "badge": "Investigativo",
        "desc": "Revelação caractere por caractere com cursor e marca-texto neon animado sob a palavra ativa.",
        "accent": "#FFD166",
        "best_for": ["netflix_doc", "investigative", "dossier"],
    },
    "none": {
        "id": "none",
        "label": "Sem Legendas (Master Limpo)",
        "badge": "Clean Feed",
        "desc": "Desativa legendas queimadas no vídeo para edição externa ou master limpo.",
        "accent": "#94A3B8",
        "best_for": ["clean_master"],
    },
}

CAPTION_STYLE_IDS: Tuple[str, ...] = tuple(CAPTION_STYLES.keys())

_STYLE_ALIASES: Dict[str, str] = {
    "hormozi_neon": "hormozi_neon",
    "hormozi_bounce": "hormozi_neon",
    "hormozi": "hormozi_neon",
    "spring_pill_gradient": "hormozi_neon",
    "capcut": "hormozi_neon",
    "capcut_pro": "hormozi_neon",
    "neon": "hormozi_neon",
    "dark_cinema": "hormozi_neon",
    "default": "hormozi_neon",
    "karaoke_glow": "karaoke_glow",
    "karaoke": "karaoke_glow",
    "neon_sweep": "karaoke_glow",
    "gradient_wipe": "karaoke_glow",
    "word_slam": "word_slam",
    "slam": "word_slam",
    "impact_slam": "word_slam",
    "impact": "word_slam",
    "selective_emphasis": "selective_emphasis",
    "selective": "selective_emphasis",
    "keyword_kinetic": "selective_emphasis",
    "keyword_kinetic_captions": "selective_emphasis",
    "keyword_emphasis": "selective_emphasis",
    "doc_selective": "selective_emphasis",
    "cinema_minimal": "cinema_minimal",
    "cinema": "cinema_minimal",
    "netflix": "cinema_minimal",
    "netflix_minimal": "cinema_minimal",
    "minimal": "cinema_minimal",
    "editorial": "cinema_minimal",
    "blur_reveal": "cinema_minimal",
    "typewriter_highlight": "typewriter_highlight",
    "typewriter": "typewriter_highlight",
    "dossier": "typewriter_highlight",
    "highlighter": "typewriter_highlight",
    "documentary": "typewriter_highlight",
    "none": "none",
    "off": "none",
    "disabled": "none",
    "clean": "none",
}

_GLYPH_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2212", "-"),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2026", "..."),
    ("\u2192", "->"),
    ("\u2190", "<-"),
    ("\u200b", ""),
    ("\u200c", ""),
    ("\u200d", ""),
    ("\ufeff", ""),
)


def list_caption_styles() -> List[Dict[str, Any]]:
    """Return UI/API-friendly ordered list of caption style descriptors."""
    return [dict(v) for v in CAPTION_STYLES.values()]


def resolve_caption_style(style: Optional[str]) -> str:
    """Normalize any user/preset/legacy caption style name into a canonical CAPTION_STYLES key."""
    if style is None:
        return "hormozi_neon"
    key = str(style).strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return "hormozi_neon"
    return _STYLE_ALIASES.get(key, "hormozi_neon")


# ---------------------------------------------------------------------------
# Color, Emoji & Typography Helpers
# ---------------------------------------------------------------------------
def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    s = hex_color.strip().lstrip("#")
    if len(s) >= 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return 255, 255, 255


def _hex_to_skia(hex_color: str, alpha: int = 255) -> int:
    r, g, b = _hex_to_rgb(hex_color)
    return skia.ColorSetARGB(max(0, min(255, int(alpha))), r, g, b)


def _brighten_rgb(r: int, g: int, b: int, factor: float) -> Tuple[int, int, int]:
    return (
        max(0, min(255, int(round(r * factor + 255.0 * max(0.0, factor - 1.0) * 0.45)))),
        max(0, min(255, int(round(g * factor + 255.0 * max(0.0, factor - 1.0) * 0.45)))),
        max(0, min(255, int(round(b * factor + 255.0 * max(0.0, factor - 1.0) * 0.45)))),
    )


def _get_emoji_typeface() -> Optional[skia.Typeface]:
    global _EMOJI_TF_LOADED, _EMOJI_TF_CACHE
    if not _EMOJI_TF_LOADED:
        _EMOJI_TF_LOADED = True
        if EMOJI_FONT_PATH.exists():
            try:
                _EMOJI_TF_CACHE = skia.Typeface.MakeFromFile(str(EMOJI_FONT_PATH))
            except Exception:
                _EMOJI_TF_CACHE = None
    return _EMOJI_TF_CACHE


def _get_courier_prime_bold_typeface(fallback: Optional[skia.Typeface] = None) -> Optional[skia.Typeface]:
    """Load and cache authentic Google Fonts CourierPrime-Bold.ttf for 16:9 Selective Emphasis."""
    global _COURIER_BOLD_TF_LOADED, _COURIER_BOLD_TF_CACHE
    if not _COURIER_BOLD_TF_LOADED:
        _COURIER_BOLD_TF_LOADED = True
        for fname in ("CourierPrime-Bold.ttf", "CourierPrime-Regular.ttf"):
            fpath = FONTS_DIR / fname
            if fpath.exists() and fpath.stat().st_size > 20_000:
                try:
                    tf = skia.Typeface.MakeFromFile(str(fpath))
                    if tf is not None:
                        _COURIER_BOLD_TF_CACHE = tf
                        break
                except Exception:
                    pass
    return _COURIER_BOLD_TF_CACHE if _COURIER_BOLD_TF_CACHE is not None else fallback


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return 0x1F300 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x1F1E6 <= cp <= 0x1F1FF


def _has_alnum_or_emoji(txt: str) -> bool:
    """Return True if token contains at least one alphanumeric character or emoji (rejects '-', '—', '–', '...')."""
    return any(ch.isalnum() or _is_emoji(ch) for ch in txt)


def _strip_accents_upper(text: str) -> str:
    nfd = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").upper()


def _sanitize_word_text(raw: str, typeface: Optional[skia.Typeface], uppercase: bool = True) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return ""
    for src, dst in _GLYPH_REPLACEMENTS:
        if src in txt:
            txt = txt.replace(src, dst)
    if uppercase:
        # Preserve canonical 'a.C.' / 'd.C.' notation in uppercase stamps
        m_era = re.match(r"^(\d{1,4})\s*([ad]\.?\s*c\.?)([.,!?;:]*)$", txt, flags=re.IGNORECASE)
        if m_era:
            era = "a.C." if m_era.group(2).lower().startswith("a") else "d.C."
            txt = f"{m_era.group(1)} {era}{m_era.group(3)}"
        else:
            txt = txt.upper()
    if typeface is not None:
        out_chars: List[str] = []
        for ch in txt:
            if ch == " " or _is_emoji(ch):
                out_chars.append(ch)
            else:
                try:
                    if typeface.unicharToGlyph(ord(ch)) != 0:
                        out_chars.append(ch)
                except Exception:
                    out_chars.append(ch)
        txt = "".join(out_chars)
    cleaned = txt.strip()
    if not cleaned or not _has_alnum_or_emoji(cleaned):
        return ""
    return cleaned


# ---------------------------------------------------------------------------
# Spelled-Out PT-BR Number / Date / Century Compaction & Selective Emphasis
# ---------------------------------------------------------------------------
_PT_UNITS: Dict[str, int] = {
    "ZERO": 0, "UM": 1, "UMA": 1, "DOIS": 2, "DUAS": 2, "TRES": 3,
    "QUATRO": 4, "CINCO": 5, "SEIS": 6, "SETE": 7, "OITO": 8, "NOVE": 9,
}
_PT_TEENS: Dict[str, int] = {
    "DEZ": 10, "ONZE": 11, "DOZE": 12, "TREZE": 13, "CATORZE": 14, "QUATORZE": 14,
    "QUINZE": 15, "DEZESSEIS": 16, "DEZESSETE": 17, "DEZOITO": 18, "DEZENOVE": 19,
}
_PT_TENS: Dict[str, int] = {
    "VINTE": 20, "TRINTA": 30, "QUARENTA": 40, "CINQUENTA": 50,
    "SESSENTA": 60, "SETENTA": 70, "OITENTA": 80, "NOVENTA": 90,
}
_PT_HUNDREDS: Dict[str, int] = {
    "CEM": 100, "CENTO": 100, "DUZENTOS": 200, "DUZENTAS": 200,
    "TREZENTOS": 300, "TREZENTAS": 300, "QUATROCENTOS": 400, "QUATROCENTAS": 400,
    "QUINHENTOS": 500, "QUINHENTAS": 500, "SEISCENTOS": 600, "SEISCENTAS": 600,
    "SETECENTOS": 700, "SETECENTAS": 700, "OITOCENTOS": 800, "OITOCENTAS": 800,
    "NOVECENTOS": 900, "NOVECENTAS": 900,
}
_PT_CENTURY_ORDINALS: Dict[Tuple[str, ...], str] = {
    ("PRIMEIRO",): "I", ("UM",): "I", ("I",): "I", ("1",): "I",
    ("SEGUNDO",): "II", ("DOIS",): "II", ("II",): "II", ("2",): "II",
    ("TERCEIRO",): "III", ("TRES",): "III", ("III",): "III", ("3",): "III",
    ("QUARTO",): "IV", ("QUATRO",): "IV", ("IV",): "IV", ("4",): "IV",
    ("QUINTO",): "V", ("CINCO",): "V", ("V",): "V", ("5",): "V",
    ("SEXTO",): "VI", ("SEIS",): "VI", ("VI",): "VI", ("6",): "VI",
    ("SETIMO",): "VII", ("SETE",): "VII", ("VII",): "VII", ("7",): "VII",
    ("OITAVO",): "VIII", ("OITO",): "VIII", ("VIII",): "VIII", ("8",): "VIII",
    ("NONO",): "IX", ("NOVE",): "IX", ("IX",): "IX", ("9",): "IX",
    ("DECIMO",): "X", ("DEZ",): "X", ("X",): "X", ("10",): "X",
    ("DECIMO", "PRIMEIRO"): "XI", ("ONZE",): "XI", ("XI",): "XI", ("11",): "XI",
    ("DECIMO", "SEGUNDO"): "XII", ("DOZE",): "XII", ("XII",): "XII", ("12",): "XII",
    ("DECIMO", "TERCEIRO"): "XIII", ("TREZE",): "XIII", ("XIII",): "XIII", ("13",): "XIII",
    ("DECIMO", "QUARTO"): "XIV", ("CATORZE",): "XIV", ("QUATORZE",): "XIV", ("XIV",): "XIV", ("14",): "XIV",
    ("DECIMO", "QUINTO"): "XV", ("QUINZE",): "XV", ("XV",): "XV", ("15",): "XV",
    ("DECIMO", "SEXTO"): "XVI", ("DEZESSEIS",): "XVI", ("XVI",): "XVI", ("16",): "XVI",
    ("DECIMO", "SETIMO"): "XVII", ("DEZESSETE",): "XVII", ("XVII",): "XVII", ("17",): "XVII",
    ("DECIMO", "OITAVO"): "XVIII", ("DEZOITO",): "XVIII", ("XVIII",): "XVIII", ("18",): "XVIII",
    ("DECIMO", "NONO"): "XIX", ("DEZENOVE",): "XIX", ("XIX",): "XIX", ("19",): "XIX",
    ("VIGESIMO",): "XX", ("VINTE",): "XX", ("XX",): "XX", ("20",): "XX",
    ("VIGESIMO", "PRIMEIRO"): "XXI", ("VINTE", "E", "UM"): "XXI", ("XXI",): "XXI", ("21",): "XXI",
}
_DANGLING_CONJUNCTIONS = {
    "E", "OU", "DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS",
    "O", "A", "OS", "AS", "UM", "UMA", "COM", "POR", "PARA", "QUE", "SE",
}

# Multi-word secret code names, historical entities, and dates for Selective Emphasis
_SELECTIVE_MULTIWORD_PHRASES: Dict[Tuple[str, ...], Tuple[str, str]] = {
    ("SOL", "INVICTUS"): ("SOL INVICTUS", "entity"),
    ("PAPAI", "NOEL"): ("PAPAI NOEL", "entity"),
    ("SANTA", "CLAUS"): ("SANTA CLAUS", "entity"),
    ("SAO", "NICOLAU"): ("SÃO NICOLAU", "entity"),
    ("BISPO", "NICOLAU"): ("BISPO NICOLAU", "entity"),
    ("OLIVER", "CROMWELL"): ("OLIVER CROMWELL", "entity"),
    ("CARLOS", "SEGUNDO"): ("CARLOS II", "entity"),
    ("CARLOS", "II"): ("CARLOS II", "entity"),
    ("REI", "CARLOS", "II"): ("REI CARLOS II", "entity"),
    ("RAINHA", "VITORIA"): ("RAINHA VITÓRIA", "entity"),
    ("PRINCIPE", "ALBERT"): ("PRÍNCIPE ALBERT", "entity"),
    ("CHARLES", "DICKENS"): ("CHARLES DICKENS", "entity"),
    ("EBENEZER", "SCROOGE"): ("SCROOGE", "entity"),
    ("THOMAS", "NAST"): ("THOMAS NAST", "entity"),
    ("HADDON", "SUNDBLOM"): ("HADDON SUNDBLOM", "entity"),
    ("CLEMENT", "MOORE"): ("CLEMENT MOORE", "entity"),
    ("CACADA", "SELVAGEM"): ("CAÇADA SELVAGEM", "danger"),
    ("WILD", "HUNT"): ("WILD HUNT", "danger"),
    ("PUDIM", "DE", "AMEIXA"): ("PUDIM DE AMEIXA", "entity"),
    ("PLUM", "PUDDING"): ("PLUM PUDDING", "entity"),
    ("CONTO", "DE", "NATAL"): ("CONTO DE NATAL", "entity"),
    ("COCA", "COLA"): ("COCA-COLA", "entity"),
    ("NOVA", "YORK"): ("NOVA YORK", "entity"),
    ("NOVA", "IORQUE"): ("NOVA YORK", "entity"),
    ("TEMPLO", "DE", "ARTEMIS"): ("TEMPLO DE ÁRTEMIS", "entity"),
    ("CONCILIO", "DE", "NICEIA"): ("CONCÍLIO DE NICEIA", "entity"),
    ("SOLSTICIO", "DE", "INVERNO"): ("SOLSTÍCIO DE INVERNO", "entity"),
    ("LAGO", "TRASIMENO"): ("LAGO TRASIMENO", "entity"),
    ("CRONOGRAFO", "DE", "354"): ("CRONÓGRAFO DE 354", "date_num"),
    ("ABADE", "DA", "DESORDEM"): ("ABADE DA DESORDEM", "danger"),
    ("NATAL", "MACABRO"): ("NATAL MACABRO", "danger"),
    ("25", "DE", "DEZEMBRO"): ("25 DE DEZEMBRO", "date_num"),
    ("5", "DE", "DEZEMBRO"): ("5 DE DEZEMBRO", "date_num"),
    ("17", "DE", "DEZEMBRO"): ("17 DE DEZEMBRO", "date_num"),
}

_SELECTIVE_HISTORICAL_NOUNS: Dict[str, str] = {
    "SATURNALIA": "entity",
    "KRAMPUS": "danger",
    "KRAMPUSNACHT": "danger",
    "CROMWELL": "entity",
    "CANTERBURY": "entity",
    "NATAL": "entity",
    "YULE": "entity",
    "ODIN": "entity",
    "SLEIPNIR": "entity",
    "SINTERKLAAS": "entity",
    "NICOLAU": "entity",
    "CONSTANTINO": "entity",
    "AURELIANO": "entity",
    "DICKENS": "entity",
    "SCROOGE": "entity",
    "VITORIA": "entity",
    "WINDSOR": "entity",
    "PURITANOS": "entity",
    "PURITANO": "entity",
    "SOLSTICIO": "entity",
    "PAGAOS": "entity",
    "PAGAO": "entity",
    "ROMA": "entity",
    "LONDRES": "entity",
    "MIRA": "entity",
    "ALPES": "entity",
    "BOSTON": "entity",
    "MASSACHUSETTS": "entity",
    "ANIBAL": "entity",
    "TRASIMENO": "entity",
    "WASSAILING": "entity",
    "SIGILLARIA": "entity",
    "BAVIERA": "entity",
    "VATICANO": "entity",
    "PARLAMENTO": "entity",
    "MOTIM": "danger",
    "REVOLTA": "danger",
    "PROIBICAO": "danger",
    "INQUISICAO": "danger",
    "SACRIFICIO": "danger",
    "SACRIFICIOS": "danger",
    "SANGUE": "danger",
    "SOMBRA": "danger",
    "FOGUEIRA": "entity",
    "IMPERADOR": "entity",
    "EXERCITO": "danger",
    "HERESIA": "danger",
    "CAOS": "danger",
    "ORGIAS": "danger",
    "ESCRAVOS": "entity",
    "PROPAGANDA": "danger",
    "COCA-COLA": "entity",
    "DECRETOS": "danger",
    "DECRETO": "danger",
    "GUERRA": "danger",
    "PRISAO": "danger",
    "CORRENTES": "danger",
    "DEMONIOS": "danger",
    "DEMONIO": "danger",
    "ESCURIDAO": "danger",
}

_SELECTIVE_IMPACT_VERBS = {
    "PROIBIRAM", "PROIBIU", "PROIBIDO", "PROIBIR",
    "INVADIAM", "INVADIRAM", "INVADIU", "INVADIR",
    "DEMOLIA", "DEMOLIU", "DEMOLIR", "DEMOLIRAM",
    "EXPLODIU", "EXPLODIRAM", "EXPLODIR",
    "APAGAR", "APAGARAM", "APAGOU",
    "MORREU", "MORRER", "MORRIAM",
    "MATAVA", "MATARAM", "MATOU",
    "DESTRUIU", "DESTRUIRAM", "DESTRUIR",
    "REESCRITO", "REESCREVEU", "REESCREVERAM",
    "TERRORIZAVA", "ATERRORIZAVA", "ATERRORIZAVAM",
    "BANIU", "BANIRAM", "BANIDO",
    "QUEIMARAM", "QUEIMOU", "QUEIMAVAM",
    "PRENDIAM", "PRENDERAM", "PRENDEU",
    "ARRASTAVAM", "ARRASTARAM",
    "DOMESTICOU", "DOMESTICARAM", "DOMESTICANDO",
    "DECRETOU", "DECRETARAM", "DECRETAVA",
    "ESCONDERAM", "OCULTARAM", "OCULTOU",
    "TOMARAM", "REVOLTOU", "REVOLTARAM",
    "SOBREVIVEU", "MASSACROU", "CAIU", "RENASCEU",
    "ASSOMBRA", "DEVORAVA", "PERSEGUIAM", "FORCOU",
    "FORCAVA", "ESMAGOU", "EXTINGUIU", "REVOGOU",
}


def _strip_word_punct(word: str) -> Tuple[str, str]:
    """Split a token into (core_without_edge_punct, trailing_punct)."""
    raw = str(word or "").strip()
    m = re.match(r"^[\"'(«\[]*(.*?)([.,!?;:»\])\"']*)$", raw)
    if not m:
        return raw, ""
    return m.group(1), m.group(2)


def _parse_pt_number_sequence(tokens: List[Dict[str, Any]], start_idx: int) -> Optional[Tuple[int, int, str]]:
    """Parse a spelled-out Portuguese number starting at `start_idx`.
    Returns `(end_idx_exclusive, value, trailing_punct)` or None.
    Safely avoids converting standalone articles like 'um' / 'uma' into '1'.
    """
    n = len(tokens)
    if start_idx >= n:
        return None

    def _norm_at(idx: int) -> Tuple[str, str]:
        core, punct = _strip_word_punct(tokens[idx]["word"])
        return _strip_accents_upper(core), punct

    first_norm, first_punct = _norm_at(start_idx)
    if first_norm not in _PT_UNITS and first_norm not in _PT_TEENS and first_norm not in _PT_TENS and first_norm not in _PT_HUNDREDS and first_norm != "MIL":
        return None

    i = start_idx
    total = 0
    current = 0
    matched_words = 0
    last_punct = ""
    has_thousand = False
    has_hundred = False
    has_ten = False

    while i < n:
        norm, punct = _norm_at(i)
        if norm == "E" and matched_words > 0 and (i + 1) < n:
            nxt_norm, _ = _norm_at(i + 1)
            if nxt_norm in _PT_UNITS or nxt_norm in _PT_TEENS or nxt_norm in _PT_TENS or nxt_norm in _PT_HUNDREDS or nxt_norm == "MIL":
                i += 1
                continue
            break

        if norm == "MIL" and not has_thousand:
            total += (current if current > 0 else 1) * 1000
            current = 0
            has_thousand = True
            matched_words += 1
            last_punct = punct
            i += 1
            if punct and punct not in (",",):
                break
            continue

        if norm in _PT_HUNDREDS and not has_hundred and not has_ten:
            current += _PT_HUNDREDS[norm]
            has_hundred = True
            matched_words += 1
            last_punct = punct
            i += 1
            if punct and punct not in (",",):
                break
            continue

        if norm in _PT_TEENS and not has_ten:
            current += _PT_TEENS[norm]
            has_ten = True
            matched_words += 1
            last_punct = punct
            i += 1
            break

        if norm in _PT_TENS and not has_ten:
            current += _PT_TENS[norm]
            has_ten = True
            matched_words += 1
            last_punct = punct
            i += 1
            if punct and punct not in (",",):
                break
            continue

        if norm in _PT_UNITS:
            # Avoid chaining two raw units like "um dois"
            if matched_words > 0 and not (has_thousand or has_hundred or has_ten):
                break
            current += _PT_UNITS[norm]
            matched_words += 1
            last_punct = punct
            i += 1
            # Peek if followed by "mil" (e.g., "dois mil")
            if i < n and _norm_at(i)[0] == "MIL" and not has_thousand and not punct:
                continue
            break

        break

    val = total + current
    if matched_words == 0 or val <= 0:
        return None

    # Guard against turning lone articles/small prose words ("um conto", "uma noite", "dois lados") into digits
    if matched_words == 1:
        if first_norm in ("UM", "UMA", "DOIS", "DUAS", "TRES", "QUATRO", "CINCO", "SEIS", "SETE", "OITO", "NOVE"):
            # Only convert lone small number if directly followed by era ("a.C."/"d.C."/"antes de cristo") or "%"/"por cento"
            next_is_qual = False
            if i < n:
                n1 = _norm_at(i)[0]
                if n1 in ("POR", "MILHOES", "BILHOES", "ANTES", "DEPOIS", "AC", "DC"):
                    next_is_qual = True
            if not next_is_qual:
                return None
        if first_norm in ("MIL", "CEM", "DEZ", "VINTE", "TRINTA", "QUARENTA", "CINQUENTA", "SESSENTA", "SETENTA", "OITENTA", "NOVENTA"):
            # Convert lone round numbers >= 100 or when followed by "de" / "anos" / "por cento" / era
            if val < 100:
                if i < n and _norm_at(i)[0] in ("POR", "ANOS", "DE", "MIL", "MILHOES", "BILHOES"):
                    pass
                else:
                    return None

    return i, val, last_punct


def compact_spelled_numbers_in_words(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize raw word timestamps and compact PT-BR spelled-out years, numbers, and centuries
    into crisp numerals/dates (e.g. 'mil seiscentos e quarenta e sete' -> '1647',
    'trezentos e trinta e seis' -> '336', 'duzentos e dezessete antes de cristo' -> '217 a.C.',
    'século décimo primeiro' -> 'SÉC. XI').
    """
    # 1. Split multi-word entries & drop standalone pure punctuation
    flat: List[Dict[str, Any]] = []
    for w in words or []:
        raw = str(w.get("word", w.get("text", ""))).strip()
        parts = [p for p in re.split(r"\s+", raw) if p and _has_alnum_or_emoji(p)]
        if not parts:
            continue
        st = float(w.get("start", 0.0))
        en = float(w.get("end", st + 0.06))
        step = max(0.06, (en - st) / float(len(parts)))
        for j, part in enumerate(parts):
            flat.append(
                {
                    "word": part,
                    "start": round(st + j * step, 3),
                    "end": round(st + (j + 1) * step, 3),
                }
            )

    out: List[Dict[str, Any]] = []
    n = len(flat)
    i = 0
    while i < n:
        core_i, punct_i = _strip_word_punct(flat[i]["word"])
        norm_i = _strip_accents_upper(core_i)

        # A) Century expressions: "século quarto" / "século décimo primeiro" / "século XIX" / "séc. IV"
        if norm_i in ("SECULO", "SEC", "SEC.") and (i + 1) < n:
            matched_cent = None
            for span_len in (3, 2, 1):
                if i + 1 + span_len <= n:
                    cand_tuple = tuple(
                        _strip_accents_upper(_strip_word_punct(flat[i + 1 + k]["word"])[0])
                        for k in range(span_len)
                    )
                    if cand_tuple in _PT_CENTURY_ORDINALS:
                        _, end_p = _strip_word_punct(flat[i + span_len]["word"])
                        matched_cent = (i + 1 + span_len, f"SÉC. {_PT_CENTURY_ORDINALS[cand_tuple]}{end_p}")
                        break
            if matched_cent is not None:
                end_idx, cent_str = matched_cent
                out.append(
                    {
                        "word": cent_str,
                        "start": flat[i]["start"],
                        "end": flat[end_idx - 1]["end"],
                        "g_idx": len(out),
                    }
                )
                i = end_idx
                continue

        # B) Already-numeric token followed by "antes de cristo" / "depois de cristo" / "a.C." / "d.C."
        if re.fullmatch(r"\d{1,4}", core_i):
            era_suffix = ""
            advance = 1
            if i + 3 < n:
                t1 = _strip_accents_upper(_strip_word_punct(flat[i + 1]["word"])[0])
                t2 = _strip_accents_upper(_strip_word_punct(flat[i + 2]["word"])[0])
                t3, p3 = _strip_word_punct(flat[i + 3]["word"])
                t3_n = _strip_accents_upper(t3)
                if t1 == "ANTES" and t2 == "DE" and t3_n == "CRISTO":
                    era_suffix = f" a.C.{p3}"
                    advance = 4
                elif t1 == "DEPOIS" and t2 == "DE" and t3_n == "CRISTO":
                    era_suffix = f" d.C.{p3}"
                    advance = 4
            if not era_suffix and i + 1 < n:
                c1, p1 = _strip_word_punct(flat[i + 1]["word"])
                n1 = _strip_accents_upper(c1).replace(".", "")
                if n1 == "AC":
                    era_suffix = f" a.C.{p1}"
                    advance = 2
                elif n1 == "DC":
                    era_suffix = f" d.C.{p1}"
                    advance = 2
            if era_suffix:
                out.append(
                    {
                        "word": f"{core_i}{era_suffix}",
                        "start": flat[i]["start"],
                        "end": flat[i + advance - 1]["end"],
                        "g_idx": len(out),
                    }
                )
                i += advance
                continue

        # C) Spelled-out Portuguese number / year sequence
        parsed = _parse_pt_number_sequence(flat, i)
        if parsed is not None:
            end_idx, val, trail_p = parsed
            text_val = str(val)
            # Check for trailing "antes de cristo" / "depois de cristo" / "a.C." / "d.C." / "por cento"
            if end_idx + 2 < n:
                t1 = _strip_accents_upper(_strip_word_punct(flat[end_idx]["word"])[0])
                t2 = _strip_accents_upper(_strip_word_punct(flat[end_idx + 1]["word"])[0])
                t3_raw, p3 = _strip_word_punct(flat[end_idx + 2]["word"])
                t3 = _strip_accents_upper(t3_raw)
                if t1 == "ANTES" and t2 == "DE" and t3 == "CRISTO":
                    text_val = f"{val} a.C."
                    trail_p = p3
                    end_idx += 3
                elif t1 == "DEPOIS" and t2 == "DE" and t3 == "CRISTO":
                    text_val = f"{val} d.C."
                    trail_p = p3
                    end_idx += 3
            if end_idx + 1 < n and "C." not in text_val:
                t1 = _strip_accents_upper(_strip_word_punct(flat[end_idx]["word"])[0])
                t2_raw, p2 = _strip_word_punct(flat[end_idx + 1]["word"])
                t2 = _strip_accents_upper(t2_raw)
                if t1 == "POR" and t2 == "CENTO":
                    text_val = f"{val}%"
                    trail_p = p2
                    end_idx += 2
            if end_idx < n and "C." not in text_val and "%" not in text_val:
                c_next, p_next = _strip_word_punct(flat[end_idx]["word"])
                n_next = _strip_accents_upper(c_next).replace(".", "")
                if n_next == "AC":
                    text_val = f"{val} a.C."
                    trail_p = p_next
                    end_idx += 1
                elif n_next == "DC":
                    text_val = f"{val} d.C."
                    trail_p = p_next
                    end_idx += 1

            out.append(
                {
                    "word": f"{text_val}{trail_p}",
                    "start": flat[i]["start"],
                    "end": flat[end_idx - 1]["end"],
                    "g_idx": len(out),
                }
            )
            i = end_idx
            continue

        item = dict(flat[i])
        item["g_idx"] = len(out)
        out.append(item)
        i += 1

    return out


def build_selective_emphasis_chunks(
    words: List[Dict[str, Any]],
    min_display_s: float = 0.72,
    max_display_s: float = 1.65,
) -> List[Dict[str, Any]]:
    """Build 16:9 Documentary Selective Emphasis keyword triggers (NO continuous karaoke!).
    Triggers ONLY on:
      - numbers, dates, years, centuries ('217 a.C.', '336', '1647', '1843', 'SÉC. IV', 'SÉC. XI')
      - secret code names & key historical nouns ('SATURNÁLIA', 'SOL INVICTUS', 'KRAMPUS', 'PAPAI NOEL', 'CROMWELL', 'CANTERBURY')
      - dramatic impact verbs ('PROIBIRAM', 'INVADIAM', 'DEMOLIA', 'EXPLODIU', 'APAGAR', 'MORREU')
    """
    compacted = compact_spelled_numbers_in_words(words)
    if not compacted:
        return []

    triggers: List[Dict[str, Any]] = []
    n = len(compacted)
    i = 0
    while i < n:
        # 1. Check multi-word historical / date phrases first (up to 3 words)
        phrase_hit = None
        for span in (3, 2):
            if i + span <= n:
                key_t = tuple(
                    _strip_accents_upper(_strip_word_punct(compacted[i + k]["word"])[0])
                    for k in range(span)
                )
                if key_t in _SELECTIVE_MULTIWORD_PHRASES:
                    disp_txt, cat = _SELECTIVE_MULTIWORD_PHRASES[key_t]
                    phrase_hit = (i + span, disp_txt, cat)
                    break

        if phrase_hit is not None:
            end_i, disp_txt, cat = phrase_hit
            st = float(compacted[i]["start"])
            en = float(compacted[end_i - 1]["end"])
            triggers.append(
                {
                    "start": st,
                    "end": max(en, st + min_display_s),
                    "selective": True,
                    "category": cat,
                    "accent_hex": "#D9381E" if cat in ("verb", "danger") else "#EAB308",
                    "words": [
                        {
                            "word": disp_txt,
                            "start": st,
                            "end": max(en, st + min_display_s),
                            "g_idx": len(triggers),
                        }
                    ],
                }
            )
            i = end_i
            continue

        # 2. Check single compacted token
        core, _ = _strip_word_punct(compacted[i]["word"])
        norm = _strip_accents_upper(core)
        cat = ""
        disp = ""

        # Numbers, years, dates, centuries (e.g. '217 a.C.', '336', '1647', '1843', 'SÉC. IV', 'SÉC. XI')
        if norm.startswith("SEC.") or re.search(r"\d", core):
            # Preserve 'a.C.' / 'd.C.' formatting cleanly
            m_era = re.match(r"^(\d{1,4})\s*([ad]\.?\s*c\.?)$", core, flags=re.IGNORECASE)
            if m_era:
                era = "a.C." if m_era.group(2).lower().startswith("a") else "d.C."
                disp = f"{m_era.group(1)} {era}"
            else:
                disp = unicodedata.normalize("NFC", core).upper()
            cat = "date_num"
        elif norm in _SELECTIVE_HISTORICAL_NOUNS:
            disp = unicodedata.normalize("NFC", core).upper()
            cat = _SELECTIVE_HISTORICAL_NOUNS[norm]
        elif norm in _SELECTIVE_IMPACT_VERBS:
            disp = unicodedata.normalize("NFC", core).upper()
            cat = "verb"

        if cat and disp:
            st = float(compacted[i]["start"])
            en = float(compacted[i]["end"])
            dur_end = min(st + max_display_s, max(en + 0.25, st + min_display_s))
            triggers.append(
                {
                    "start": st,
                    "end": dur_end,
                    "selective": True,
                    "category": cat,
                    "accent_hex": "#D9381E" if cat in ("verb", "danger") else "#EAB308",
                    "words": [
                        {
                            "word": disp,
                            "start": st,
                            "end": dur_end,
                            "g_idx": len(triggers),
                        }
                    ],
                }
            )
        i += 1

    # Ensure strictly non-overlapping display windows
    for idx in range(len(triggers) - 1):
        nxt_st = float(triggers[idx + 1]["start"])
        if float(triggers[idx]["end"]) > nxt_st - 0.04:
            new_end = max(float(triggers[idx]["start"]) + 0.18, nxt_st - 0.04)
            triggers[idx]["end"] = round(new_end, 3)
            triggers[idx]["words"][0]["end"] = round(new_end, 3)
        else:
            triggers[idx]["end"] = round(min(float(triggers[idx]["end"]), float(triggers[idx]["start"]) + max_display_s), 3)
            triggers[idx]["words"][0]["end"] = triggers[idx]["end"]

    return triggers


def group_words_into_chunks(
    words: List[Dict[str, Any]],
    max_words: int = 3,
    selective: bool = False,
) -> List[Dict[str, Any]]:
    """Split multi-word tokens, compact spelled-out numbers/years/centuries into numerals,
    strip standalone pure-punctuation tokens (e.g. '-', '—', '–', '...'), prevent orphaned
    conjunction chunks ('E TRINTA E', 'E QUARENTA E'), and group into crisp 2-3 word chunks.
    When `selective=True`, returns only Selective Emphasis keyword triggers.
    """
    if selective:
        return build_selective_emphasis_chunks(words)

    clean_words = compact_spelled_numbers_in_words(words)

    chunks: List[Dict[str, Any]] = []
    buf: List[Dict[str, Any]] = []
    n_clean = len(clean_words)
    for idx_w, w in enumerate(clean_words):
        buf.append(w)
        txt = w["word"]
        end_punct = txt.endswith((".", "!", "?", ";", ":"))
        char_len = sum(len(x["word"]) for x in buf) + max(0, len(buf) - 1)
        last_norm = _strip_accents_upper(_strip_word_punct(txt)[0])
        is_dangling_end = (last_norm in _DANGLING_CONJUNCTIONS) and (not end_punct) and ((idx_w + 1) < n_clean)

        should_flush = (len(buf) >= max_words or end_punct or char_len >= 16)
        # Never end a chunk on a dangling conjunction ('E', 'DE', 'DA', 'DO') if we can absorb 1 more word
        if should_flush and is_dangling_end and len(buf) <= max_words:
            should_flush = False
        if should_flush:
            chunks.append(
                {
                    "start": buf[0]["start"],
                    "end": buf[-1]["end"],
                    "words": list(buf),
                }
            )
            buf = []
    if buf:
        # Avoid a 1-word orphaned conjunction trailing chunk by merging into previous chunk if close
        if (
            len(buf) == 1
            and chunks
            and _strip_accents_upper(_strip_word_punct(buf[0]["word"])[0]) in _DANGLING_CONJUNCTIONS
            and (buf[0]["start"] - chunks[-1]["end"]) <= 0.35
        ):
            chunks[-1]["words"].append(buf[0])
            chunks[-1]["end"] = buf[0]["end"]
        else:
            chunks.append({"start": buf[0]["start"], "end": buf[-1]["end"], "words": buf})

    for i in range(len(chunks) - 1):
        gap = chunks[i + 1]["start"] - chunks[i]["end"]
        if 0 < gap <= 0.30:
            chunks[i]["end"] = chunks[i + 1]["start"]
    return chunks


# ---------------------------------------------------------------------------
# Continuous Frame-Rate-Independent Physics Curves (30fps / 60fps / 120fps)
# ---------------------------------------------------------------------------
def _clamp01(x: float) -> float:
    return 0.0 if x <= 0.0 else (1.0 if x >= 1.0 else x)


def _ease_out_cubic(x: float) -> float:
    u = _clamp01(x)
    return 1.0 - (1.0 - u) ** 3


def _ease_out_quart(x: float) -> float:
    u = _clamp01(x)
    return 1.0 - (1.0 - u) ** 4


def _ease_out_back(x: float, overshoot: float = 1.55) -> float:
    u = _clamp01(x) - 1.0
    return 1.0 + (overshoot + 1.0) * (u ** 3) + overshoot * (u ** 2)


def _spring_pop_hormozi(age_s: float) -> float:
    """Damped elastic spring pop: 1.00 -> ~1.24 peak (~0.045s) -> subtle rebound -> 1.13 settle."""
    if age_s <= 0.0:
        return 1.0
    if age_s >= 0.30:
        return 1.13
    return 1.13 + math.exp(-17.5 * age_s) * (
        -0.13 * math.cos(33.0 * age_s) + 0.275 * math.sin(33.0 * age_s)
    )


def _spring_slam(age_s: float) -> float:
    """High-impact slam: 1.48x -> ~1.16x at 0.04s -> ~0.94x squash -> 1.00x solid lock."""
    if age_s <= 0.0:
        return 1.48
    if age_s >= 0.30:
        return 1.00
    return 1.00 + 0.48 * math.exp(-16.5 * age_s) * math.cos(23.5 * age_s)


# ---------------------------------------------------------------------------
# Chunk & Active-Word Resolution (Strictly <= 1 Active Word Per Frame)
# ---------------------------------------------------------------------------
def _find_active_chunk(chunks: List[Dict[str, Any]], t: float) -> Tuple[Optional[Dict[str, Any]], int]:
    """Return the latest active chunk whose [start, end] spans t (zero double-draw at cuts)."""
    best: Optional[Dict[str, Any]] = None
    best_idx = -1
    for idx, ch in enumerate(chunks):
        st = float(ch.get("start", 0.0))
        en = float(ch.get("end", 0.0))
        if st <= t <= en:
            best = ch
            best_idx = idx
    return best, best_idx


def _prepare_tokens(
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    font: skia.Font,
    emoji_font: skia.Font,
    typeface: skia.Typeface,
    uppercase: bool = True,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Build normalized word tokens for a chunk and pick STRICTLY ONE active word index."""
    raw_words = chunk.get("words") or []
    tokens: List[Dict[str, Any]] = []
    for idx, wd in enumerate(raw_words):
        raw_txt = wd.get("word", wd.get("text", ""))
        txt = _sanitize_word_text(str(raw_txt), typeface=typeface, uppercase=uppercase)
        if not txt:
            continue
        w_st = float(wd.get("start", chunk.get("start", 0.0)))
        w_en = max(w_st + 0.05, float(wd.get("end", w_st + 0.25)))
        has_emoji = any(_is_emoji(ch) for ch in txt)
        f_use = emoji_font if (has_emoji and len(txt) <= 2) else font
        tw = float(f_use.measureText(txt))
        tokens.append(
            {
                "text": txt,
                "start": w_st,
                "end": w_en,
                "dur": max(0.06, w_en - w_st),
                "w": tw,
                "g_idx": int(wd.get("g_idx", chunk_idx * 3 + idx)),
                "idx": len(tokens),
                "font": f_use,
                "is_numeric": any(ch.isdigit() for ch in txt),
            }
        )

    if not tokens:
        return [], None

    # If a stripped leading punctuation token left chunk["start"] earlier than the first real word,
    # do not render the chunk prematurely during that dead gap.
    if t < tokens[0]["start"] - 0.05:
        return [], None

    # Strictly ONE active word per frame:
    # 1) Prefer the last token whose [start, end) contains t (inclusive on the final token).
    active_idx: Optional[int] = None
    last_i = len(tokens) - 1
    for i, tok in enumerate(tokens):
        if i < last_i:
            if tok["start"] <= t < tok["end"]:
                active_idx = i
        else:
            if tok["start"] <= t <= tok["end"]:
                active_idx = i

    # 2) Bridge tiny inter-word gaps or hold the final word cleanly until chunk end (zero flicker).
    if active_idx is None:
        most_recent: Optional[int] = None
        for i, tok in enumerate(tokens):
            if tok["start"] <= t:
                most_recent = i
        if most_recent is not None:
            active_idx = most_recent
        elif tokens[0]["start"] - t <= 0.05:
            active_idx = 0

    return tokens, active_idx


def _resolve_base_font_size(w: int, h: int, style: str, font_size: Optional[float]) -> float:
    if font_size is not None and float(font_size) > 4.0:
        return float(font_size)
    if w > h:
        # 16:9 widescreen (e.g. 1920x1080 -> 64px, 1280x720 -> 43px)
        base = 64.0 * (w / 1920.0)
    elif h > int(w * 1.35):
        # 9:16 vertical shorts/reels (1080x1920 -> 82px)
        base = 82.0 * (w / 1080.0)
    else:
        # 4:5 or 1:1 square
        base = 74.0 * (w / 1080.0)

    if style == "cinema_minimal":
        return base * (0.86 if w > h else 0.80)
    if style == "typewriter_highlight":
        return base * (0.86 if w > h else 0.80)
    return base


def _draw_elliptical_glow(
    canvas: skia.Canvas,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    rgb: Tuple[int, int, int],
    peak_alpha: int,
) -> None:
    """Draw a seamless 4-stop Gaussian-falloff elliptical glow (zero harsh orb edges)."""
    if peak_alpha <= 2 or rx <= 1.0 or ry <= 1.0:
        return
    r, g, b = rgb
    a0 = max(0, min(255, int(peak_alpha)))
    a1 = int(round(a0 * 0.42))
    a2 = int(round(a0 * 0.11))
    canvas.save()
    canvas.translate(cx, cy)
    canvas.scale(1.0, ry / rx)
    p = skia.Paint(AntiAlias=True)
    p.setShader(
        skia.GradientShader.MakeRadial(
            center=(0.0, 0.0),
            radius=rx,
            colors=[
                skia.ColorSetARGB(a0, r, g, b),
                skia.ColorSetARGB(a1, r, g, b),
                skia.ColorSetARGB(a2, r, g, b),
                skia.ColorSetARGB(0, r, g, b),
            ],
            positions=[0.0, 0.36, 0.68, 1.0],
        )
    )
    canvas.drawCircle(0.0, 0.0, rx, p)
    canvas.restore()


# ---------------------------------------------------------------------------
# Style 1: hormozi_neon (CapCut Pro Spring Bounce + Micro-Tilt + Dual-Bloom)
# ---------------------------------------------------------------------------
def _render_hormozi_neon(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    cy: float,
    base_size: float,
    palette: List[Tuple[str, str, Tuple[int, int, int, int]]],
) -> None:
    font = skia.Font(typeface, base_size)
    emoji_tf = _get_emoji_typeface()
    emoji_font = skia.Font(emoji_tf, base_size * 0.90) if emoji_tf else font

    tokens, active_idx = _prepare_tokens(chunk, chunk_idx, t, font, emoji_font, typeface, uppercase=True)
    if not tokens:
        return

    chunk_start = float(chunk.get("start", tokens[0]["start"]))
    chunk_age = max(0.0, t - chunk_start)

    # Chunk entrance: ease_out_back slide-up (+28px -> 0px) + alpha fade (0 -> 255) over 0.18s
    ent_slide_prog = _ease_out_back(_clamp01(chunk_age / 0.18), overshoot=1.55)
    slide_y = (1.0 - ent_slide_prog) * (28.0 * (base_size / 82.0))
    ent_alpha = int(round(255.0 * _ease_out_cubic(_clamp01(chunk_age / 0.12))))
    if ent_alpha <= 6:
        return

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    space_w = max(base_size * 0.36, float(font.measureText(" ")) * 1.48)
    pad_x = base_size * 0.34
    pad_y = base_size * 0.17
    pill_radius = base_size * 0.27
    stroke_w = max(7.0, base_size * 0.145)

    # Compute current and peak-stabilized widths so:
    # 1) ZERO word overlap at every frame (even at 1.24x peak + ±2.2° tilt!)
    # 2) ZERO line-scale jitter while a word pops!
    peak_extra_w = 0.0
    raw_sum_w = 0.0
    total_w = 0.0

    for i, tok in enumerate(tokens):
        is_act = (i == active_idx)
        tok["active"] = is_act
        raw_sum_w += tok["w"]
        # Worst-case slot footprint if THIS token were at peak 1.24x + tilt projection
        worst_slot = (tok["w"] + pad_x * 2.0) * 1.25 + base_size * 0.12
        peak_extra_w = max(peak_extra_w, worst_slot - tok["w"])

        if is_act:
            word_age = max(0.0, t - tok["start"])
            sc = _spring_pop_hormozi(word_age)
            pill_exp = _ease_out_back(_clamp01(word_age / 0.11), overshoot=1.25)
            # Smoothly expand pill width from 0.42 -> 1.0 (clamped >= 0.42)
            pill_x_factor = max(0.42, min(1.08, 0.42 + 0.58 * pill_exp))
            tilt_sign = 1.0 if (tok["g_idx"] % 2 == 0) else -1.0
            tilt_deg = tilt_sign * 2.2 * _ease_out_back(_clamp01(word_age / 0.13), overshoot=1.35)
            # Reserve full rendered rotated pill width + breathing buffer -> strictly ZERO overlap
            tilt_pad = (ascent + descent + pad_y * 2.0) * abs(math.sin(math.radians(tilt_deg))) * 0.5
            rendered_w = (tok["w"] + pad_x * 2.0 * pill_x_factor) * max(1.0, sc) + tilt_pad * 2.0 + 6.0
            tok["word_age"] = word_age
            tok["scale"] = sc
            tok["pill_x_factor"] = pill_x_factor
            tok["tilt_deg"] = tilt_deg
            tok["slot_w"] = max(tok["w"], rendered_w)
        else:
            tok["word_age"] = -1.0
            tok["scale"] = 1.0
            tok["pill_x_factor"] = 0.0
            tok["tilt_deg"] = 0.0
            tok["slot_w"] = tok["w"]
        total_w += tok["slot_w"]

    gap_total = space_w * max(0, len(tokens) - 1)
    total_w += gap_total
    peak_total_w = raw_sum_w + peak_extra_w + gap_total

    # Safe margin: 7.5% on left & right (max 85% viewport width)
    max_line_w = float(w) * 0.85
    line_scale = min(1.0, max_line_w / max(1.0, total_w, peak_total_w))

    # Composite chunk alpha smoothly via saveLayer only during entrance fade
    use_layer = ent_alpha < 252
    if use_layer:
        band_h = max(220.0, base_size * 3.0)
        layer_rect = skia.Rect.MakeXYWH(0.0, max(0.0, cy - band_h), float(w), min(float(h), band_h * 2.0))
        lp = skia.Paint(AntiAlias=True)
        lp.setAlpha(ent_alpha)
        canvas.saveLayer(layer_rect, lp)
    else:
        canvas.save()

    canvas.translate(float(w) * 0.5, cy + slide_y)
    canvas.scale(line_scale, line_scale)

    # Compute exact non-overlapping center X for every token
    cursor_x = -total_w * 0.5
    centers: Dict[int, float] = {}
    for tok in tokens:
        centers[tok["idx"]] = cursor_x + tok["slot_w"] * 0.5
        cursor_x += tok["slot_w"] + space_w

    # Draw inactive words first, active word on top
    draw_order = [tok for tok in tokens if not tok["active"]] + [tok for tok in tokens if tok["active"]]

    for tok in draw_order:
        w_cx = centers[tok["idx"]]
        # Subtle per-word entrance ripple during first 0.22s
        stagger_age = max(0.0, chunk_age - tok["idx"] * 0.022)
        stagger_y = (1.0 - _ease_out_cubic(_clamp01(stagger_age / 0.14))) * (10.0 * (base_size / 82.0))

        canvas.save()
        canvas.translate(w_cx, stagger_y)

        if tok["active"]:
            word_age = tok["word_age"]
            canvas.rotate(tok["tilt_deg"])
            canvas.scale(tok["scale"], tok["scale"])

            pill_bg_hex, pill_txt_hex, (gr, gg, gb, ga) = palette[tok["g_idx"] % len(palette)]
            pr_r, pr_g, pr_b = _hex_to_rgb(pill_bg_hex)

            # Subtle brightness pulse on active pill (peaks right after pop, gentle hum after)
            pulse = 1.0 + 0.075 * math.exp(-3.5 * word_age) + 0.045 * math.sin(word_age * 16.0)
            hi_r, hi_g, hi_b = _brighten_rgb(pr_r, pr_g, pr_b, min(1.26, 1.08 * pulse))
            lo_r, lo_g, lo_b = (
                max(0, int(pr_r * 0.88)),
                max(0, int(pr_g * 0.88)),
                max(0, int(pr_b * 0.88)),
            )

            half_pw = (tok["w"] * 0.5 + pad_x) * tok["pill_x_factor"]
            # Guarantee pill always cleanly encloses the active word glyphs once open
            half_pw = max(half_pw, tok["w"] * 0.5 + pad_x * 0.45)
            pill_h = ascent + descent + pad_y * 2.0
            pill_top = -ascent - pad_y
            pill_rect = skia.Rect.MakeXYWH(-half_pw, pill_top, half_pw * 2.0, pill_h)

            # Pass 1: Dual-pass outer soft ambient neon bloom
            outer_bloom_rect = skia.Rect.MakeXYWH(
                -half_pw - 5.0, pill_top - 4.0, half_pw * 2.0 + 10.0, pill_h + 8.0
            )
            bloom_alpha = max(60, min(230, int(round(ga * 0.58 * pulse))))
            bloom_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(bloom_alpha, gr, gg, gb))
            bloom_paint.setImageFilter(skia.ImageFilters.Blur(14.0, 14.0))
            canvas.drawRoundRect(outer_bloom_rect, pill_radius + 4.0, pill_radius + 4.0, bloom_paint)

            # Pass 2: Main glowing gradient pill + tight inner neon drop shadow
            pill_paint = skia.Paint(AntiAlias=True)
            pill_paint.setShader(
                skia.GradientShader.MakeLinear(
                    points=[(0.0, pill_top), (0.0, pill_top + pill_h)],
                    colors=[
                        skia.ColorSetARGB(255, hi_r, hi_g, hi_b),
                        skia.ColorSetARGB(255, pr_r, pr_g, pr_b),
                        skia.ColorSetARGB(255, lo_r, lo_g, lo_b),
                    ],
                    positions=[0.0, 0.52, 1.0],
                )
            )
            inner_glow_a = max(90, min(255, int(round(ga * 0.90))))
            pill_paint.setImageFilter(
                skia.ImageFilters.DropShadow(0.0, 5.0, 12.0, 12.0, skia.ColorSetARGB(inner_glow_a, gr, gg, gb))
            )
            canvas.drawRoundRect(pill_rect, pill_radius, pill_radius, pill_paint)

            # Subtle specular rim highlight for CapCut Pro glass-neon finish
            rim_paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.2,
                Color=skia.ColorSetARGB(120, 255, 255, 255),
            )
            canvas.drawRoundRect(pill_rect, pill_radius, pill_radius, rim_paint)

            # Crisp text inside active pill
            if pill_txt_hex.upper() == "#FFFFFF":
                st_p = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(3.5, base_size * 0.06),
                    StrokeJoin=skia.Paint.kRound_Join,
                    StrokeCap=skia.Paint.kRound_Cap,
                    Color=skia.ColorSetARGB(210, 11, 7, 19),
                )
                canvas.drawString(tok["text"], -tok["w"] * 0.5, 0.0, tok["font"], st_p)
            txt_paint = skia.Paint(AntiAlias=True, Color=_hex_to_skia(pill_txt_hex, 255))
            canvas.drawString(tok["text"], -tok["w"] * 0.5, 0.0, tok["font"], txt_paint)
        else:
            # Floating bold UPPERCASE word (ZERO box) with thick dark stroke + feathered shadow
            shadow_p = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=stroke_w,
                StrokeJoin=skia.Paint.kRound_Join,
                StrokeCap=skia.Paint.kRound_Cap,
                Color=skia.ColorSetARGB(255, 6, 4, 12),
            )
            shadow_p.setImageFilter(
                skia.ImageFilters.DropShadow(0.0, 6.0, 10.0, 10.0, skia.ColorSetARGB(215, 0, 0, 0))
            )
            canvas.drawString(tok["text"], -tok["w"] * 0.5, 0.0, tok["font"], shadow_p)

            is_past = (active_idx is not None and tok["idx"] < active_idx)
            if tok["is_numeric"]:
                fill_color = skia.ColorSetARGB(255, 255, 209, 102)
            elif is_past:
                fill_color = skia.ColorSetARGB(255, 255, 255, 255)
            else:
                fill_color = skia.ColorSetARGB(238, 240, 244, 252)
            canvas.drawString(tok["text"], -tok["w"] * 0.5, 0.0, tok["font"], skia.Paint(AntiAlias=True, Color=fill_color))

        canvas.restore()

    canvas.restore()


# ---------------------------------------------------------------------------
# Style 2: karaoke_glow (Dynamic Left-to-Right Neon Gradient Wipe + Wave)
# ---------------------------------------------------------------------------
def _render_karaoke_glow(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    cy: float,
    base_size: float,
    palette: List[Tuple[str, str, Tuple[int, int, int, int]]],
) -> None:
    font = skia.Font(typeface, base_size)
    emoji_tf = _get_emoji_typeface()
    emoji_font = skia.Font(emoji_tf, base_size * 0.90) if emoji_tf else font

    tokens, active_idx = _prepare_tokens(chunk, chunk_idx, t, font, emoji_font, typeface, uppercase=True)
    if not tokens:
        return

    chunk_start = float(chunk.get("start", tokens[0]["start"]))
    chunk_age = max(0.0, t - chunk_start)

    ent_p = _ease_out_cubic(_clamp01(chunk_age / 0.16))
    slide_y = (1.0 - ent_p) * (20.0 * (base_size / 82.0))
    ent_alpha = int(round(255.0 * ent_p))
    if ent_alpha <= 6:
        return

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    space_w = max(base_size * 0.34, float(font.measureText(" ")) * 1.42)
    stroke_w = max(7.0, base_size * 0.135)

    # Reserve tiny 1.09x headroom on active word so zero neighbor overlap
    total_w = 0.0
    for i, tok in enumerate(tokens):
        is_act = (i == active_idx)
        tok["active"] = is_act
        if is_act:
            word_age = max(0.0, t - tok["start"])
            sc = 1.0 + 0.09 * _ease_out_back(_clamp01(word_age / 0.14), overshoot=1.2)
            fill_prog = _clamp01((t - tok["start"]) / max(0.06, tok["end"] - tok["start"]))
        elif active_idx is not None and i < active_idx:
            sc = 1.02
            fill_prog = 1.0
        else:
            sc = 1.0
            fill_prog = 0.0
        tok["scale"] = sc
        tok["fill_prog"] = fill_prog
        tok["slot_w"] = tok["w"] * max(1.04, sc)
        total_w += tok["slot_w"]

    total_w += space_w * max(0, len(tokens) - 1)
    max_line_w = float(w) * 0.85
    line_scale = min(1.0, max_line_w / max(1.0, total_w))

    use_layer = ent_alpha < 252
    if use_layer:
        band_h = max(200.0, base_size * 2.8)
        layer_rect = skia.Rect.MakeXYWH(0.0, max(0.0, cy - band_h), float(w), min(float(h), band_h * 2.0))
        lp = skia.Paint(AntiAlias=True)
        lp.setAlpha(ent_alpha)
        canvas.saveLayer(layer_rect, lp)
    else:
        canvas.save()

    canvas.translate(float(w) * 0.5, cy + slide_y)
    canvas.scale(line_scale, line_scale)

    cursor_x = -total_w * 0.5
    for tok in tokens:
        w_cx = cursor_x + tok["slot_w"] * 0.5
        cursor_x += tok["slot_w"] + space_w

        # Subtle floating sine wave per word + gentle lift on active word
        wave_amp = base_size * 0.055
        wave_y = math.sin(t * 7.0 + tok["idx"] * 1.15) * wave_amp
        if tok["active"]:
            wave_y -= base_size * 0.055

        canvas.save()
        canvas.translate(w_cx, wave_y)
        canvas.scale(tok["scale"], tok["scale"])

        tw = tok["w"]
        fill_prog = tok["fill_prog"]
        wipe_x = -tw * 0.5 + tw * fill_prog

        # Seamless elliptical neon aura tracking the live karaoke sweep edge
        use_dark_pal = not _is_default_neon_palette(palette)
        halo_rgb = (255, 209, 102) if use_dark_pal else (196, 245, 42)
        if tok["active"] or fill_prog > 0.02:
            halo_rx = max(tw * 0.62, base_size * 0.98)
            halo_ry = max(ascent * 0.92, base_size * 0.62)
            halo_x = wipe_x if tok["active"] else 0.0
            halo_a = 84 if tok["active"] else 34
            _draw_elliptical_glow(
                canvas,
                halo_x,
                -ascent * 0.36,
                halo_rx,
                halo_ry,
                halo_rgb,
                halo_a,
            )

        # Layer 1: Base unlit stroke + shadow + frosted silver-white fill
        base_stroke = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=stroke_w,
            StrokeJoin=skia.Paint.kRound_Join,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=skia.ColorSetARGB(255, 6, 5, 14),
        )
        base_stroke.setImageFilter(
            skia.ImageFilters.DropShadow(0.0, 6.0, 10.0, 10.0, skia.ColorSetARGB(215, 0, 0, 0))
        )
        canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], base_stroke)

        unlit_fill = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 205, 214, 230))
        canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], unlit_fill)

        # Layer 2: Clipped left-to-right gradient wipe via canvas.clipRect
        if fill_prog > 0.005:
            clip_w = max(1.0, tw * fill_prog + 4.0)
            clip_rect = skia.Rect.MakeXYWH(
                -tw * 0.5 - 6.0,
                -ascent - 24.0,
                clip_w + 6.0,
                ascent + descent + 48.0,
            )
            canvas.save()
            canvas.clipRect(clip_rect)

            wipe_colors = (
                [
                    skia.ColorSetARGB(255, 255, 236, 170),  # Antique Gold Highlight
                    skia.ColorSetARGB(255, 255, 209, 102),  # Antique Gold
                    skia.ColorSetARGB(255, 217, 119, 6),    # Torch Amber
                ]
                if use_dark_pal
                else [
                    skia.ColorSetARGB(255, 255, 214, 70),   # Neon Gold
                    skia.ColorSetARGB(255, 184, 255, 1),    # Electric Lime
                    skia.ColorSetARGB(255, 232, 255, 128),  # Luminous Lime Highlight
                ]
            )
            glow_sh_c = (
                skia.ColorSetARGB(185, 255, 209, 102)
                if use_dark_pal
                else skia.ColorSetARGB(185, 184, 255, 1)
            )
            grad_p = skia.Paint(AntiAlias=True)
            grad_p.setShader(
                skia.GradientShader.MakeLinear(
                    points=[(-tw * 0.5, -ascent), (tw * 0.5, descent * 0.4)],
                    colors=wipe_colors,
                    positions=[0.0, 0.60, 1.0],
                )
            )
            if tok["active"]:
                grad_p.setImageFilter(
                    skia.ImageFilters.DropShadow(0.0, 0.0, 8.0, 8.0, glow_sh_c)
                )
            canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], grad_p)
            canvas.restore()

            # Subtle glowing karaoke wipe bar below the lit segment of the active word
            if tok["active"]:
                bar_y = descent * 0.55 + 5.0
                bar_w = max(8.0, tw * fill_prog)
                bar_rect = skia.Rect.MakeXYWH(-tw * 0.5, bar_y, bar_w, max(4.5, base_size * 0.065))
                bar_p = skia.Paint(AntiAlias=True)
                bar_end_c = (
                    skia.ColorSetARGB(255, 185, 28, 38)
                    if use_dark_pal
                    else skia.ColorSetARGB(255, 184, 255, 1)
                )
                bar_p.setShader(
                    skia.GradientShader.MakeLinear(
                        points=[(-tw * 0.5, bar_y), (-tw * 0.5 + bar_w, bar_y)],
                        colors=[skia.ColorSetARGB(255, 255, 209, 102), bar_end_c],
                    )
                )
                bar_p.setImageFilter(
                    skia.ImageFilters.DropShadow(0.0, 0.0, 10.0, 10.0, glow_sh_c)
                )
                canvas.drawRoundRect(bar_rect, 4.0, 4.0, bar_p)

        canvas.restore()

    canvas.restore()


# ---------------------------------------------------------------------------
# Style 3: word_slam (Viral High-Impact 3D Metallic Slam + Micro-Shake)
# ---------------------------------------------------------------------------
def _render_word_slam(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    cy: float,
    base_size: float,
    palette: List[Tuple[str, str, Tuple[int, int, int, int]]],
) -> None:
    # Giant impact scale (1.28x normal captions, safely auto-fitted so 1.48x peak NEVER clips!)
    slam_size = base_size * 1.28
    font = skia.Font(typeface, slam_size)
    emoji_tf = _get_emoji_typeface()
    emoji_font = skia.Font(emoji_tf, slam_size * 0.90) if emoji_tf else font

    tokens, active_idx = _prepare_tokens(chunk, chunk_idx, t, font, emoji_font, typeface, uppercase=True)
    if not tokens:
        return

    tok = tokens[active_idx if active_idx is not None else 0]
    word_age = max(0.0, t - tok["start"])

    # Slam physics: 1.48x -> 1.00x with damped overshoot + micro-shake kick on first 0.09s
    slam_sc = _spring_slam(word_age)
    alpha = int(round(255.0 * _ease_out_cubic(_clamp01(word_age / 0.045))))
    if alpha <= 6:
        return

    shake_x = 0.0
    shake_y = 0.0
    shake_deg = 0.0
    if word_age < 0.095:
        env = (1.0 - word_age / 0.095) ** 1.55
        seed = float(tok["g_idx"]) * 1.91 + 0.7
        shake_x = math.sin(word_age * 165.0 + seed) * (slam_size * 0.095) * env
        shake_y = math.cos(word_age * 195.0 + seed * 1.4) * (slam_size * 0.068) * env
        shake_deg = math.sin(word_age * 125.0 + seed * 0.8) * 2.8 * env

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))
    tw = max(1.0, tok["w"])

    # Guarantee zero clipping even at peak 1.48x slam + horizontal shake!
    max_w = float(w) * 0.84
    base_fit = min(1.0, max_w / (tw * 1.48 + slam_size * 0.25))

    # Alternate metallic 3D gradients: Gold Chrome & Crimson/Amber (dark-cinema) or Rose/Lime (neon)
    use_dark_pal = not _is_default_neon_palette(palette)
    variant = tok["g_idx"] % 3
    if variant == 0:
        # Gold Metallic Chrome
        grad_colors = [
            skia.ColorSetARGB(alpha, 255, 255, 255),
            skia.ColorSetARGB(alpha, 255, 245, 196),
            skia.ColorSetARGB(alpha, 255, 209, 102),
            skia.ColorSetARGB(alpha, 214, 146, 24),
        ]
        extrude_color = skia.ColorSetARGB(alpha, 56, 32, 6)
        impact_rgb = (255, 209, 102)
    elif variant == 1:
        if use_dark_pal:
            # Blood Crimson Metallic Chrome
            grad_colors = [
                skia.ColorSetARGB(alpha, 255, 255, 255),
                skia.ColorSetARGB(alpha, 255, 210, 214),
                skia.ColorSetARGB(alpha, 185, 28, 38),
                skia.ColorSetARGB(alpha, 120, 14, 22),
            ]
            extrude_color = skia.ColorSetARGB(alpha, 46, 6, 10)
            impact_rgb = (185, 28, 38)
        else:
            # Neon Rose Metallic Chrome
            grad_colors = [
                skia.ColorSetARGB(alpha, 255, 255, 255),
                skia.ColorSetARGB(alpha, 255, 214, 236),
                skia.ColorSetARGB(alpha, 255, 46, 147),
                skia.ColorSetARGB(alpha, 178, 16, 94),
            ]
            extrude_color = skia.ColorSetARGB(alpha, 52, 8, 34)
            impact_rgb = (255, 46, 147)
    else:
        if use_dark_pal:
            # Torch Amber Metallic Chrome
            grad_colors = [
                skia.ColorSetARGB(alpha, 255, 255, 255),
                skia.ColorSetARGB(alpha, 255, 230, 184),
                skia.ColorSetARGB(alpha, 217, 119, 6),
                skia.ColorSetARGB(alpha, 146, 64, 14),
            ]
            extrude_color = skia.ColorSetARGB(alpha, 48, 22, 4)
            impact_rgb = (225, 125, 18)
        else:
            # Electric Lime Metallic Chrome
            grad_colors = [
                skia.ColorSetARGB(alpha, 255, 255, 255),
                skia.ColorSetARGB(alpha, 236, 255, 184),
                skia.ColorSetARGB(alpha, 184, 255, 1),
                skia.ColorSetARGB(alpha, 106, 176, 0),
            ]
            extrude_color = skia.ColorSetARGB(alpha, 20, 42, 4)
            impact_rgb = (184, 255, 1)

    canvas.save()
    canvas.translate(float(w) * 0.5 + shake_x, cy + shake_y)
    canvas.rotate(shake_deg)
    canvas.scale(base_fit * slam_sc, base_fit * slam_sc)

    # Elliptical impact flash burst wrapping cleanly around the slammed typography
    if word_age < 0.14:
        burst_p = 1.0 - word_age / 0.14
        grow = 0.88 + 0.28 * (1.0 - burst_p)
        burst_rx = max(tw * 0.72, slam_size * 1.15) * grow
        burst_ry = max(ascent * 0.95, slam_size * 0.70) * grow
        _draw_elliptical_glow(
            canvas,
            0.0,
            -ascent * 0.35,
            burst_rx,
            burst_ry,
            impact_rgb,
            int(round(105.0 * burst_p)),
        )

    stroke_w = max(9.0, slam_size * 0.135)

    # Layer 1: Deep feathered cinema drop shadow
    cinema_shadow = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=stroke_w + 4.0,
        StrokeJoin=skia.Paint.kRound_Join,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(int(alpha * 0.85), 0, 0, 0),
    )
    cinema_shadow.setImageFilter(
        skia.ImageFilters.DropShadow(0.0, 12.0, 16.0, 16.0, skia.ColorSetARGB(int(alpha * 0.90), 0, 0, 0))
    )
    canvas.drawString(tok["text"], -tw * 0.5, 6.0, tok["font"], cinema_shadow)

    # Layer 2: 3D vertical extrusion bevel steps
    ext_paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStrokeAndFill_Style,
        StrokeWidth=stroke_w * 0.88,
        StrokeJoin=skia.Paint.kRound_Join,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=extrude_color,
    )
    ext_step = max(2.2, slam_size * 0.026)
    for step_i in (4, 3, 2, 1):
        canvas.drawString(tok["text"], -tw * 0.5, step_i * ext_step, tok["font"], ext_paint)

    # Layer 3: Crisp heavy dark outline on front face
    outline_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=stroke_w,
        StrokeJoin=skia.Paint.kRound_Join,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(alpha, 8, 5, 16),
    )
    canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], outline_p)

    # Layer 4: 3D vertical metallic chrome gradient fill
    fill_p = skia.Paint(AntiAlias=True)
    fill_p.setShader(
        skia.GradientShader.MakeLinear(
            points=[(0.0, -ascent * 0.95), (0.0, descent * 0.25)],
            colors=grad_colors,
            positions=[0.0, 0.34, 0.72, 1.0],
        )
    )
    canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], fill_p)

    canvas.restore()


# ---------------------------------------------------------------------------
# Style 4: cinema_minimal (Netflix / MagnatesMedia Editorial Blur-Reveal)
# ---------------------------------------------------------------------------
def _render_cinema_minimal(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    cy: float,
    base_size: float,
    palette: List[Tuple[str, str, Tuple[int, int, int, int]]],
) -> None:
    font = skia.Font(typeface, base_size)
    emoji_tf = _get_emoji_typeface()
    emoji_font = skia.Font(emoji_tf, base_size * 0.90) if emoji_tf else font

    tokens, active_idx = _prepare_tokens(chunk, chunk_idx, t, font, emoji_font, typeface, uppercase=True)
    if not tokens:
        return

    chunk_start = float(chunk.get("start", tokens[0]["start"]))
    chunk_age = max(0.0, t - chunk_start)

    # Smooth blur-to-sharp entrance (Blur 6 -> 0 over 0.16s) + subtle fade-up & tracking settle
    ent_p = _clamp01(chunk_age / 0.16)
    eased_ent = _ease_out_cubic(ent_p)
    blur_sigma = 6.0 * ((1.0 - eased_ent) ** 1.35)
    slide_y = (1.0 - eased_ent) * (16.0 * (base_size / 64.0))
    ent_alpha = int(round(255.0 * eased_ent))
    if ent_alpha <= 6:
        return

    # Subtle editorial spacing expansion settling smoothly into tight refined tracking
    extra_track = (1.0 - eased_ent) * (14.0 * (base_size / 64.0))
    space_w = max(base_size * 0.36, float(font.measureText(" ")) * 1.45) + extra_track

    total_w = 0.0
    for i, tok in enumerate(tokens):
        is_act = (i == active_idx)
        tok["active"] = is_act
        if is_act:
            word_age = max(0.0, t - tok["start"])
            glow_p = _ease_out_cubic(_clamp01(word_age / 0.14))
            sc = 1.0 + 0.055 * glow_p
            tok["glow_p"] = glow_p
        else:
            sc = 1.0
            tok["glow_p"] = 0.0
        tok["scale"] = sc
        tok["slot_w"] = tok["w"] * max(1.03, sc)
        total_w += tok["slot_w"]

    total_w += space_w * max(0, len(tokens) - 1)
    max_line_w = float(w) * 0.84
    line_scale = min(1.0, max_line_w / max(1.0, total_w))

    # Single-pass saveLayer for authentic editorial blur-reveal + alpha composite
    use_layer = (ent_alpha < 252) or (blur_sigma > 0.15)
    if use_layer:
        band_h = max(180.0, base_size * 2.8)
        layer_rect = skia.Rect.MakeXYWH(0.0, max(0.0, cy - band_h), float(w), min(float(h), band_h * 2.0))
        lp = skia.Paint(AntiAlias=True)
        lp.setAlpha(ent_alpha)
        if blur_sigma > 0.15:
            lp.setImageFilter(skia.ImageFilters.Blur(blur_sigma, blur_sigma))
        canvas.saveLayer(layer_rect, lp)
    else:
        canvas.save()

    canvas.translate(float(w) * 0.5, cy + slide_y)
    canvas.scale(line_scale, line_scale)

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    cursor_x = -total_w * 0.5
    for tok in tokens:
        w_cx = cursor_x + tok["slot_w"] * 0.5
        cursor_x += tok["slot_w"] + space_w
        tw = tok["w"]

        canvas.save()
        if tok["active"]:
            lift_y = -base_size * 0.04 * tok["glow_p"]
            canvas.translate(w_cx, lift_y)
            canvas.scale(tok["scale"], tok["scale"])

            # ZERO blocky boxes! Seamless elliptical warm golden editorial bloom behind active word
            _draw_elliptical_glow(
                canvas,
                0.0,
                -ascent * 0.35,
                max(tw * 0.68, base_size * 1.05),
                max(ascent * 0.88, base_size * 0.56),
                (255, 209, 102),
                int(round(62.0 * tok["glow_p"])),
            )

            # Deep feathered cinema drop shadow (no thick cartoon outline)
            sh_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 0, 0, 0))
            sh_p.setImageFilter(skia.ImageFilters.Blur(9.0, 9.0))
            canvas.drawString(tok["text"], -tw * 0.5, 4.0, tok["font"], sh_p)

            # Warm gold editorial highlight text + warm golden outer glow
            gold_p = skia.Paint(AntiAlias=True)
            gold_p.setShader(
                skia.GradientShader.MakeLinear(
                    points=[(0.0, -ascent), (0.0, descent * 0.2)],
                    colors=[
                        skia.ColorSetARGB(255, 255, 244, 206),
                        skia.ColorSetARGB(255, 255, 209, 102),
                    ],
                )
            )
            gold_p.setImageFilter(
                skia.ImageFilters.DropShadow(
                    0.0, 0.0, 14.0, 14.0, skia.ColorSetARGB(int(165 * tok["glow_p"]), 255, 209, 102)
                )
            )
            canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], gold_p)
        else:
            canvas.translate(w_cx, 0.0)
            # Soft feathered cinema drop shadow for clean legibility on any bright/dark scene
            sh_wide = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 0, 0, 0))
            sh_wide.setImageFilter(skia.ImageFilters.Blur(10.0, 10.0))
            canvas.drawString(tok["text"], -tw * 0.5, 4.5, tok["font"], sh_wide)

            # Subtle dark 2px anti-bleed edge + warm editorial off-white fill
            thin_edge = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.4,
                StrokeJoin=skia.Paint.kRound_Join,
                Color=skia.ColorSetARGB(165, 8, 6, 14),
            )
            canvas.drawString(tok["text"], -tw * 0.5, 0.0, tok["font"], thin_edge)

            is_past = (active_idx is not None and tok["idx"] < active_idx)
            txt_a = 245 if is_past else 198
            canvas.drawString(
                tok["text"],
                -tw * 0.5,
                0.0,
                tok["font"],
                skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(txt_a, 245, 243, 238)),
            )

        canvas.restore()

    canvas.restore()


# ---------------------------------------------------------------------------
# Style 5: typewriter_highlight (Investigative Documentary Dossier)
# ---------------------------------------------------------------------------
def _render_typewriter_highlight(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    cy: float,
    base_size: float,
    palette: List[Tuple[str, str, Tuple[int, int, int, int]]],
) -> None:
    font = skia.Font(typeface, base_size)
    emoji_tf = _get_emoji_typeface()
    emoji_font = skia.Font(emoji_tf, base_size * 0.90) if emoji_tf else font

    tokens, active_idx = _prepare_tokens(chunk, chunk_idx, t, font, emoji_font, typeface, uppercase=True)
    if not tokens or active_idx is None:
        return

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    space_w = max(base_size * 0.36, float(font.measureText(" ")) * 1.44)
    # Reserve full centered line width up front -> ZERO horizontal jump as characters type in!
    total_w = sum(tok["w"] for tok in tokens) + space_w * max(0, len(tokens) - 1)
    max_line_w = float(w) * 0.84
    line_scale = min(1.0, max_line_w / max(1.0, total_w))

    canvas.save()
    canvas.translate(float(w) * 0.5, cy)
    canvas.scale(line_scale, line_scale)

    cursor_x = -total_w * 0.5
    for i, tok in enumerate(tokens):
        word_left = cursor_x
        cursor_x += tok["w"] + space_w

        if i > active_idx:
            # Future words stay untyped until their spoken timestamp
            continue

        tw = tok["w"]
        is_act = (i == active_idx)

        if is_act:
            word_age = max(0.0, t - tok["start"])
            # Crisp progressive character reveal over first ~62% of the word's duration
            char_prog = _clamp01(word_age / max(0.08, tok["dur"] * 0.62))
            n_chars = max(1, int(math.ceil(len(tok["text"]) * char_prog)))
            visible_txt = tok["text"][:n_chars]
            vis_w = float(tok["font"].measureText(visible_txt))

            # Animated glowing dossier highlighter & neon underline sweeping cleanly behind typed characters
            hl_prog = _ease_out_cubic(_clamp01(word_age / max(0.11, tok["dur"] * 0.72)))
            hl_w = max(12.0, min(vis_w + 16.0, (tw + 16.0) * hl_prog))

            # Rotate subtle investigative highlighter tint (Warm Amber Gold / Dossier Pink / Acid Lime)
            hl_hex, _, (gr, gg, gb, ga) = palette[(tok["g_idx"] + 2) % len(palette)]
            hr, hg, hb = _hex_to_rgb(hl_hex)

            # 1) Soft luminous outer glow beneath active keyword (works on both transparent & opaque canvases!)
            hl_top = -ascent * 0.34
            hl_h = ascent * 0.34 + descent + 8.0
            glow_bar = skia.Rect.MakeXYWH(word_left - 8.0, hl_top - 3.0, hl_w, hl_h + 6.0)
            glow_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(ga * 0.48), gr, gg, gb))
            glow_p.setImageFilter(skia.ImageFilters.Blur(10.0, 10.0))
            canvas.drawRoundRect(glow_bar, 6.0, 6.0, glow_p)

            # 2) Translucent dossier marker-pen swipe ribbon behind lower half of keyword
            marker_rect = skia.Rect.MakeXYWH(word_left - 8.0, hl_top, hl_w, hl_h)
            marker_p = skia.Paint(AntiAlias=True)
            marker_p.setShader(
                skia.GradientShader.MakeLinear(
                    points=[(word_left - 8.0, hl_top), (word_left - 8.0 + hl_w, hl_top)],
                    colors=[
                        skia.ColorSetARGB(150, hr, hg, hb),
                        skia.ColorSetARGB(205, hr, hg, hb),
                    ],
                )
            )
            canvas.drawRoundRect(marker_rect, 5.0, 5.0, marker_p)

            # 3) Crisp glowing neon underline sweeping directly under baseline
            ul_y = descent + 6.0
            ul_h = max(4.5, base_size * 0.075)
            ul_rect = skia.Rect.MakeXYWH(word_left - 8.0, ul_y, hl_w, ul_h)
            ul_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, hr, hg, hb))
            ul_p.setImageFilter(
                skia.ImageFilters.DropShadow(0.0, 0.0, 8.0, 8.0, skia.ColorSetARGB(220, gr, gg, gb))
            )
            canvas.drawRoundRect(ul_rect, 3.0, 3.0, ul_p)
        else:
            visible_txt = tok["text"]
            vis_w = tw

        # Crisp investigative transcript stroke + shadow + bright ivory ink
        st_p = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=max(5.5, base_size * 0.105),
            StrokeJoin=skia.Paint.kRound_Join,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=skia.ColorSetARGB(240, 8, 7, 14),
        )
        st_p.setImageFilter(
            skia.ImageFilters.DropShadow(0.0, 5.0, 10.0, 10.0, skia.ColorSetARGB(205, 0, 0, 0))
        )
        canvas.drawString(visible_txt, word_left, 0.0, tok["font"], st_p)

        fill_c = skia.ColorSetARGB(255, 255, 255, 255) if is_act else skia.ColorSetARGB(236, 238, 235, 224)
        canvas.drawString(visible_txt, word_left, 0.0, tok["font"], skia.Paint(AntiAlias=True, Color=fill_c))

        # Blinking dossier typewriter caret right after the active typing edge
        if is_act:
            blink = 0.55 + 0.45 * math.sin(t * 18.0)
            caret_a = int(round(255.0 * blink))
            caret_w = max(4.0, base_size * 0.085)
            caret_rect = skia.Rect.MakeXYWH(
                word_left + vis_w + 5.0,
                -ascent * 0.88,
                caret_w,
                ascent * 0.96,
            )
            caret_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(caret_a, 255, 209, 102))
            caret_p.setImageFilter(
                skia.ImageFilters.DropShadow(0.0, 0.0, 8.0, 8.0, skia.ColorSetARGB(int(caret_a * 0.8), 255, 209, 102))
            )
            canvas.drawRoundRect(caret_rect, 2.0, 2.0, caret_p)

    canvas.restore()


# ---------------------------------------------------------------------------
# Style 6: selective_emphasis (16:9 Documentary Keyword Emphasis — Courier Prime Bold 64px)
# ---------------------------------------------------------------------------
def _cubic_bezier_doc_snap(x: float, x1: float = 0.22, y1: float = 1.0, x2: float = 0.36, y2: float = 1.0) -> float:
    """Exact CSS cubic-bezier(0.22, 1, 0.36, 1) ease-out quint-like snap."""
    t_target = _clamp01(x)
    if t_target <= 0.0:
        return 0.0
    if t_target >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        inv = 1.0 - mid
        bx = 3.0 * inv * inv * mid * x1 + 3.0 * inv * mid * mid * x2 + mid * mid * mid
        if bx < t_target:
            lo = mid
        else:
            hi = mid
    u = 0.5 * (lo + hi)
    inv = 1.0 - u
    return 3.0 * inv * inv * u * y1 + 3.0 * inv * u * u * y2 + u * u * u


def _ensure_selective_chunks(chunk_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return cached Selective Emphasis keyword chunks whether the caller passed pre-filtered
    selective chunks or raw continuous word chunks.
    """
    if not chunk_list:
        return []
    if all(bool(ch.get("selective")) for ch in chunk_list):
        return chunk_list

    first_ch = chunk_list[0]
    last_ch = chunk_list[-1]
    first_ws = first_ch.get("words") or []
    last_ws = last_ch.get("words") or []
    cache_key = (
        len(chunk_list),
        round(float(first_ch.get("start", 0.0)), 3),
        round(float(last_ch.get("end", 0.0)), 3),
        str(first_ws[0].get("word", "")) if first_ws else "",
        str(last_ws[-1].get("word", "")) if last_ws else "",
    )
    cached = _SELECTIVE_CHUNKS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    flat_words: List[Dict[str, Any]] = []
    for ch in chunk_list:
        for wd in ch.get("words") or []:
            flat_words.append(wd)
    selective = build_selective_emphasis_chunks(flat_words)
    if len(_SELECTIVE_CHUNKS_CACHE) >= 32:
        _SELECTIVE_CHUNKS_CACHE.clear()
    _SELECTIVE_CHUNKS_CACHE[cache_key] = selective
    return selective


def _render_selective_emphasis(
    canvas: skia.Canvas,
    chunk: Dict[str, Any],
    chunk_idx: int,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    base_size: float,
    lower_third_active: bool = False,
) -> None:
    """Render JSON v3.0.0 `keyword_kinetic_captions` in Selective Emphasis mode:
    - Courier Prime Bold 64px (`#FFFFFF`)
    - Drop shadow `0px 4px 16px rgba(0,0,0,0.85)`
    - `#EAB308` / `#D9381E` tactical bracket & animated underline accent
    - Positioned at `bottom_right` (`x = w - 96 - text_w, y = h - 92`) when lower-left date stamp is active,
      or centered at `y = h - 108` otherwise.
    """
    words = chunk.get("words") or []
    if not words:
        return

    cp_tf = _get_courier_prime_bold_typeface(fallback=typeface) or typeface
    raw_label = " ".join(str(wd.get("word", wd.get("text", ""))).strip() for wd in words).strip()
    label = _sanitize_word_text(raw_label, typeface=cp_tf, uppercase=True)
    if not label:
        return

    chunk_start = float(chunk.get("start", words[0].get("start", 0.0)))
    chunk_end = float(chunk.get("end", words[-1].get("end", chunk_start + 0.8)))
    age = max(0.0, t - chunk_start)
    rem = max(0.0, chunk_end - t)

    ent = _cubic_bezier_doc_snap(_clamp01(age / 0.24))
    exit_p = _ease_out_cubic(_clamp01(rem / 0.16)) if rem < 0.16 else 1.0
    alpha = int(round(255.0 * min(ent, exit_p)))
    if alpha <= 6:
        return

    is_wide = w >= h
    scale_ref = (float(w) / 1920.0) if is_wide else (float(w) / 1080.0)
    eff_size = float(base_size) if (base_size > 10.0) else (64.0 * scale_ref)

    max_avail_w = float(w) * (0.44 if (is_wide and lower_third_active) else 0.80)
    font = skia.Font(cp_tf, eff_size)
    font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
    text_w = float(font.measureText(label))
    if text_w > max_avail_w and text_w > 1.0:
        eff_size = max(28.0, eff_size * (max_avail_w / text_w))
        font = skia.Font(cp_tf, eff_size)
        font.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        text_w = float(font.measureText(label))

    fm = font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    margin_x = 96.0 * (float(w) / 1920.0) if is_wide else 56.0
    if is_wide and lower_third_active:
        text_x = max(float(w) * 0.48, float(w) - margin_x - text_w)
        baseline_y = float(h) - 92.0 * (float(h) / 1080.0)
    elif is_wide:
        text_x = (float(w) - text_w) * 0.5
        baseline_y = float(h) - 108.0 * (float(h) / 1080.0)
    else:
        text_x = (float(w) - text_w) * 0.5
        baseline_y = float(h) * 0.82

    accent_hex = str(chunk.get("accent_hex") or "")
    if not accent_hex:
        cat = str(chunk.get("category") or "")
        accent_hex = "#D9381E" if cat in ("verb", "danger") else "#EAB308"
    ar, ag, ab = _hex_to_rgb(accent_hex)

    slide_y = (1.0 - ent) * 14.0
    draw_y = baseline_y + slide_y

    # Subtle translucent slate tactical frame behind keyword (zero bulky cartoon box)
    pad_x = max(14.0, eff_size * 0.28)
    pad_top = max(10.0, eff_size * 0.20)
    pad_bot = max(12.0, eff_size * 0.24)
    box_l = text_x - pad_x
    box_t = draw_y - ascent - pad_top
    box_w = text_w + pad_x * 2.0
    box_h = ascent + descent + pad_top + pad_bot

    # Clip left-to-right reveal on entrance for snappy Vox/Johnny Harris kinetic feel
    canvas.save()
    reveal_w = (box_w + 48.0) * max(0.05, ent)
    canvas.clipRect(skia.Rect.MakeXYWH(box_l - 24.0, box_t - 24.0, reveal_w, box_h + 64.0))

    bg_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(alpha * 0.48), 18, 20, 23))
    canvas.drawRoundRect(skia.Rect.MakeXYWH(box_l, box_t, box_w, box_h), 6.0, 6.0, bg_p)

    # Tactical left & right square brackets `[` `]` in #EAB308 / #D9381E
    brk_len = max(12.0, eff_size * 0.24)
    brk_p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=max(2.5, eff_size * 0.055),
        StrokeCap=skia.Paint.kSquare_Cap,
        Color=skia.ColorSetARGB(alpha, ar, ag, ab),
    )
    # Left bracket `[`
    canvas.drawLine(box_l, box_t, box_l + brk_len, box_t, brk_p)
    canvas.drawLine(box_l, box_t, box_l, box_t + box_h, brk_p)
    canvas.drawLine(box_l, box_t + box_h, box_l + brk_len, box_t + box_h, brk_p)
    # Right bracket `]`
    box_r = box_l + box_w
    canvas.drawLine(box_r - brk_len, box_t, box_r, box_t, brk_p)
    canvas.drawLine(box_r, box_t, box_r, box_t + box_h, brk_p)
    canvas.drawLine(box_r - brk_len, box_t + box_h, box_r, box_t + box_h, brk_p)

    # Animated sweeping underline bar beneath baseline (`#EAB308` or `#D9381E`)
    ul_prog = _cubic_bezier_doc_snap(_clamp01(age / 0.30))
    ul_y = draw_y + descent + 5.0
    ul_h = max(3.5, eff_size * 0.065)
    ul_rect = skia.Rect.MakeXYWH(text_x, ul_y, max(6.0, text_w * ul_prog), ul_h)
    canvas.drawRoundRect(ul_rect, 2.0, 2.0, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, ar, ag, ab)))

    # Pure #FFFFFF Courier Prime Bold 64px text with fast 2-pass cinema drop shadow
    sh_soft = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(round(alpha * 0.42)), 0, 0, 0))
    canvas.drawString(label, text_x + 1.0, draw_y + 6.0, font, sh_soft)
    sh_tight = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(round(alpha * 0.85)), 0, 0, 0))
    canvas.drawString(label, text_x, draw_y + 3.5, font, sh_tight)
    txt_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(alpha, 255, 255, 255))
    canvas.drawString(label, text_x, draw_y, font, txt_p)
    canvas.restore()


# ---------------------------------------------------------------------------
# Unified Public Entry Point
# ---------------------------------------------------------------------------
def draw_kinetic_captions(
    canvas: skia.Canvas,
    chunks: Any,
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    style: str = "hormozi_neon",
    y_ratio: float = 0.84,
    font_size: Optional[float] = None,
    palette: Optional[List[Tuple[str, str, Tuple[int, int, int, int]]]] = None,
    mood: str = "",
    caption_style: Optional[str] = None,
    lower_third_active: Optional[bool] = None,
    selective_mode: Optional[bool] = None,
    scene_local_t: Optional[float] = None,
    **kwargs: Any,
) -> None:
    """Render studio-grade frame-by-frame kinetic captions onto any Skia Canvas.

    Supports 6 animated presets (`hormozi_neon`, `karaoke_glow`, `word_slam`,
    `cinema_minimal`, `typewriter_highlight`, `selective_emphasis`) plus `dark_cinema` and `none`.
    In 16:9 widescreen (`w >= h`), `selective_emphasis` is the default for `selective_emphasis`
    and `cinema_minimal` documentary renders (triggering ONLY on numbers/dates/centuries,
    historical entities, and dramatic impact verbs in Courier Prime Bold 64px — NEVER continuous karaoke).
    """
    raw_style = caption_style if caption_style is not None else style
    resolved_style = resolve_caption_style(raw_style)
    if resolved_style == "none" or not chunks or w <= 0 or h <= 0:
        return

    is_wide = int(w) >= int(h)
    use_selective = (
        resolved_style == "selective_emphasis"
        or (selective_mode is True)
        or (is_wide and resolved_style == "cinema_minimal" and selective_mode is not False)
    )

    chunk_list: List[Dict[str, Any]] = [chunks] if isinstance(chunks, dict) else list(chunks)
    if use_selective:
        sel_chunks = _ensure_selective_chunks(chunk_list)
        chunk, chunk_idx = _find_active_chunk(sel_chunks, float(t))
        if chunk is None:
            return
        if lower_third_active is None:
            lt_active = bool(chunk.get("lower_third_active", False))
            if not lt_active and scene_local_t is not None:
                lt_active = 0.0 <= float(scene_local_t) < 3.8
        else:
            lt_active = bool(lower_third_active)
        # Default to exact 64px Courier Prime Bold at 1920x1080 (ignore legacy 58px cinema_minimal default)
        if font_size is None or (is_wide and abs(float(font_size) - 58.0) < 0.5):
            sel_size = 64.0 * (float(w) / 1920.0) if is_wide else 56.0 * (float(w) / 1080.0)
        else:
            sel_size = float(font_size)
        _render_selective_emphasis(
            canvas,
            chunk,
            chunk_idx,
            float(t),
            int(w),
            int(h),
            typeface,
            sel_size,
            lower_third_active=lt_active,
        )
        return

    chunk, chunk_idx = _find_active_chunk(chunk_list, float(t))
    if chunk is None:
        return

    cy = float(h) * max(0.12, min(0.94, float(y_ratio)))
    base_size = _resolve_base_font_size(int(w), int(h), resolved_style, font_size)
    pal = resolve_caption_palette(palette=palette, mood=mood, style=raw_style)

    if resolved_style == "karaoke_glow":
        _render_karaoke_glow(canvas, chunk, chunk_idx, float(t), int(w), int(h), typeface, cy, base_size, pal)
    elif resolved_style == "word_slam":
        _render_word_slam(canvas, chunk, chunk_idx, float(t), int(w), int(h), typeface, cy, base_size, pal)
    elif resolved_style == "cinema_minimal":
        _render_cinema_minimal(canvas, chunk, chunk_idx, float(t), int(w), int(h), typeface, cy, base_size, pal)
    elif resolved_style == "typewriter_highlight":
        _render_typewriter_highlight(canvas, chunk, chunk_idx, float(t), int(w), int(h), typeface, cy, base_size, pal)
    else:
        _render_hormozi_neon(canvas, chunk, chunk_idx, float(t), int(w), int(h), typeface, cy, base_size, pal)


# Alias for single-chunk / cross-module callers
draw_kinetic_caption_chunk = draw_kinetic_captions
