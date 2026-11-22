"""FrimeRise Google AI Studio Gemini 2.5 Flash Native Expressive & Multi-Speaker TTS.
Uses the user's Google AI Studio API key (AIza...) via official REST API:
  - Single-character expressive acting TTS (with tone/accent/emotion direction)
  - Native Multi-Speaker Dialogue TTS (multiSpeakerVoiceConfig)
  - Automatic graceful fallback to Edge-TTS if key is missing or invalid.
"""
from __future__ import annotations

import base64
import re
import subprocess
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from database import get_settings, record_token_usage
from engine.intel_vaapi import run_ffmpeg_safe

GEMINI_TTS_MODELS = ("gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_MODEL = GEMINI_TTS_MODELS[0]
GEMINI_TEXT_MODELS = ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash")

_ROMAN_TO_PT: Dict[str, str] = {
    "I": "um",
    "II": "dois",
    "III": "três",
    "IV": "quatro",
    "V": "cinco",
    "VI": "seis",
    "VII": "sete",
    "VIII": "oito",
    "IX": "nove",
    "X": "dez",
    "XI": "onze",
    "XII": "doze",
    "XIII": "treze",
    "XIV": "quatorze",
    "XV": "quinze",
    "XVI": "dezesseis",
    "XVII": "dezessete",
    "XVIII": "dezoito",
    "XIX": "dezenove",
    "XX": "vinte",
    "XXI": "vinte e um",
}

# Formal PT-BR grammar for centuries, monarchs & popes:
# I..X -> ordinal (primeiro..décimo), XI..XXI -> cardinal (onze..vinte e um)
_ROMAN_CENTURY_PT: Dict[str, str] = {
    "I": "primeiro",
    "II": "segundo",
    "III": "terceiro",
    "IV": "quarto",
    "V": "quinto",
    "VI": "sexto",
    "VII": "sétimo",
    "VIII": "oitavo",
    "IX": "nono",
    "X": "décimo",
    "XI": "onze",
    "XII": "doze",
    "XIII": "treze",
    "XIV": "quatorze",
    "XV": "quinze",
    "XVI": "dezesseis",
    "XVII": "dezessete",
    "XVIII": "dezoito",
    "XIX": "dezenove",
    "XX": "vinte",
    "XXI": "vinte e um",
}

_CARDINAL_CENTURY_TO_ORDINAL_PT: Dict[str, str] = {
    "um": "primeiro",
    "1": "primeiro",
    "dois": "segundo",
    "2": "segundo",
    "três": "terceiro",
    "tres": "terceiro",
    "3": "terceiro",
    "quatro": "quarto",
    "4": "quarto",
    "cinco": "quinto",
    "5": "quinto",
    "seis": "sexto",
    "6": "sexto",
    "sete": "sétimo",
    "7": "sétimo",
    "oito": "oitavo",
    "8": "oitavo",
    "nove": "nono",
    "9": "nono",
    "dez": "décimo",
    "10": "décimo",
}

_ROMAN_ORDINAL_FEM_PT: Dict[str, str] = {
    "I": "primeira",
    "II": "segunda",
    "III": "terceira",
    "IV": "quarta",
    "V": "quinta",
    "VI": "sexta",
    "VII": "sétima",
    "VIII": "oitava",
    "IX": "nona",
    "X": "décima",
}

_FEMALE_MONARCH_NAMES = {
    "maria", "isabel", "elizabeth", "elisabete", "catarina", "joana",
    "teresa", "leopoldina", "carlota", "ana", "vitória", "vitoria", "cleópatra",
}

_ROMAN_TO_EN: Dict[str, str] = {
    "I": "first",
    "II": "second",
    "III": "third",
    "IV": "fourth",
    "V": "fifth",
    "VI": "sixth",
    "VII": "seventh",
    "VIII": "eighth",
    "IX": "ninth",
    "X": "tenth",
    "XI": "eleventh",
    "XII": "twelfth",
    "XIII": "thirteenth",
    "XIV": "fourteenth",
    "XV": "fifteenth",
    "XVI": "sixteenth",
    "XVII": "seventeenth",
    "XVIII": "eighteenth",
    "XIX": "nineteenth",
    "XX": "twentieth",
    "XXI": "twenty-first",
}


def _expand_currency_pt(text: str, symbol: str, singular: str, plural: str) -> str:
    pat = re.compile(
        rf"(?<!\w){re.escape(symbol)}\s*(\d+(?:[.,]\d+)*)(?:\s+(mil|milh[aã]o|milh[oõ]es|bilh[aã]o|bilh[oõ]es|trilh[aã]o|trilh[oõ]es))?\b",
        flags=re.I,
    )

    def _repl(m: re.Match[str]) -> str:
        num_s = m.group(1)
        scale = m.group(2)
        if scale:
            if scale.lower() == "mil":
                return f"{num_s} mil {plural}"
            return f"{num_s} {scale} de {plural}"
        unit = singular if num_s in ("1", "1,00", "1.00") else plural
        return f"{num_s} {unit}"

    return pat.sub(_repl, text)


def _expand_currency_en(text: str, symbol: str, singular: str, plural: str) -> str:
    pat = re.compile(
        rf"(?<!\w){re.escape(symbol)}\s*(\d+(?:[.,]\d+)*)(?:\s+(thousand|million|billion|trillion))?\b",
        flags=re.I,
    )

    def _repl(m: re.Match[str]) -> str:
        num_s = m.group(1)
        scale = m.group(2)
        if scale:
            return f"{num_s} {scale} {plural}"
        unit = singular if num_s in ("1", "1.00") else plural
        return f"{num_s} {unit}"

    return pat.sub(_repl, text)


def normalize_narration_for_speech(text: str, lang: str = "pt_br") -> str:
    """Normalize abbreviations, Roman numerals, currencies, units, monarchs, and raw symbols
    so TTS diction is natural, grammatical, and fluid.
    """
    s = (text or "").strip()
    if not s:
        return ""
    s = re.sub(r"[*_`#\[\]]+", "", s)
    s = re.sub(r"\s*[|•]\s*", ", ", s)
    s = re.sub(r"\s*[—–]\s*", " — ", s)
    s = re.sub(r"\s{2,}", " ", s)

    is_en = str(lang or "pt_br").lower().startswith("en")
    if is_en:
        s = re.sub(r"\bB\.C\.E?\.?\b", "before Christ", s, flags=re.I)
        s = re.sub(r"\bA\.D\.?\b", "A D", s, flags=re.I)
        s = re.sub(
            r"\b(?:cent\.?|century)\s+([IVX]{1,4})\b",
            lambda m: f"the {_ROMAN_TO_EN.get(m.group(1).upper(), m.group(1))} century",
            s,
            flags=re.I,
        )
        s = _expand_currency_en(s, "US$", "dollar", "dollars")
        s = _expand_currency_en(s, "R$", "real", "reais")
        s = _expand_currency_en(s, "£", "pound", "pounds")
        s = _expand_currency_en(s, "€", "euro", "euros")
        s = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 percent", s)
        s = re.sub(
            r"([+-]?\d+(?:[.,]\d+)?)\s*[°º]\s*C\b",
            lambda m: f"{m.group(1)} {'degree' if m.group(1) in ('1', '-1', '+1') else 'degrees'} Celsius",
            s,
        )
        s = re.sub(r"(\d+(?:[.,]\d+)?)\s*km/h\b", r"\1 kilometers per hour", s, flags=re.I)
        s = re.sub(
            r"(\d+(?:[.,]\d+)?)\s*km\b",
            lambda m: f"{m.group(1)} {'kilometer' if m.group(1) == '1' else 'kilometers'}",
            s,
            flags=re.I,
        )
        s = re.sub(r"\s*&\s*", " and ", s)
    else:
        # 1. Centuries (PT-BR formal grammar: I..X -> ordinal, XI..XXI -> cardinal)
        s = re.sub(
            r"\bs[eé]c\.?\s*([IVX]{1,4})\b",
            lambda m: f"século {_ROMAN_CENTURY_PT.get(m.group(1).upper(), m.group(1))}",
            s,
            flags=re.I,
        )
        s = re.sub(
            r"\bs[eé]culo\s+([IVX]{1,4})\b",
            lambda m: f"século {_ROMAN_CENTURY_PT.get(m.group(1).upper(), m.group(1))}",
            s,
            flags=re.I,
        )
        s = re.sub(
            r"\bs[eé]c(?:ulo|\.?)\s+(um|dois|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|[1-9]|10)\b",
            lambda m: f"século {_CARDINAL_CENTURY_TO_ORDINAL_PT.get(m.group(1).lower(), m.group(1))}",
            s,
            flags=re.I,
        )
        s = re.sub(
            r"\bcap[ií]tulo\s+([IVX]{1,4})\b",
            lambda m: f"capítulo {_ROMAN_TO_PT.get(m.group(1).upper(), m.group(1))}",
            s,
            flags=re.I,
        )

        # 2. Monarchs, nobles & popes (e.g. "D. Pedro II" -> "Dom Pedro segundo", "D. Maria I" -> "Dona Maria primeira")
        s = re.sub(
            r"\bD\.\s+([A-ZÀ-Ý][a-zà-ÿ]+)\b",
            lambda m: f"{'Dona' if m.group(1).lower() in _FEMALE_MONARCH_NAMES else 'Dom'} {m.group(1)}",
            s,
        )

        def _monarch_roman_repl(m: re.Match[str]) -> str:
            prefix = m.group(1)
            rom = m.group(2)
            if rom not in _ROMAN_CENTURY_PT:
                return m.group(0)
            low_pref = prefix.lower()
            is_fem = (
                low_pref.startswith(("dona ", "rainha ", "imperatriz "))
                or any(fn in low_pref.split() for fn in _FEMALE_MONARCH_NAMES)
            )
            spoken = (_ROMAN_ORDINAL_FEM_PT.get(rom) if is_fem else None) or _ROMAN_CENTURY_PT[rom]
            return f"{prefix} {spoken}"

        s = re.sub(
            r"\b((?:Dom|Dona|Rei|Rainha|Papa|Imperador|Imperatriz|Czar|Pr[ií]ncipe)\s+[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)?)\s+([IVX]{1,4})\b",
            _monarch_roman_repl,
            s,
        )
        s = re.sub(
            r"\b(Pedro|Jo[aã]o|Henrique|Lu[ií]s|Carlos|F[ei]lipe|Afonso|Eduardo|Jorge|Nicolau|Alexandre|Isabel|Elizabeth|Catarina|Bento|Pio|Greg[oó]rio|Inoc[eê]ncio|Le[aã]o|Urbano|Clemente|J[uú]lio)\s+([IVX]{1,4})\b",
            _monarch_roman_repl,
            s,
        )

        # 3. Currencies (R$, US$, £, €)
        s = _expand_currency_pt(s, "US$", "dólar", "dólares")
        s = _expand_currency_pt(s, "R$", "real", "reais")
        s = _expand_currency_pt(s, "£", "libra", "libras")
        s = _expand_currency_pt(s, "€", "euro", "euros")

        # 4. Percentages, temperatures, distances & ampersand
        s = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 por cento", s)
        s = re.sub(
            r"([+-]?\d+(?:[.,]\d+)?)\s*[°º]\s*C\b",
            lambda m: f"{m.group(1)} {'grau' if m.group(1) in ('1', '-1', '+1') else 'graus'} Celsius",
            s,
        )
        s = re.sub(r"(\d+(?:[.,]\d+)?)\s*km/h\b", r"\1 quilômetros por hora", s, flags=re.I)
        s = re.sub(
            r"(\d+(?:[.,]\d+)?)\s*km\b",
            lambda m: f"{m.group(1)} {'quilômetro' if m.group(1) == '1' else 'quilômetros'}",
            s,
            flags=re.I,
        )
        s = re.sub(r"\s*&\s*", " e ", s)

        # 5. Historical era & common abbreviations
        s = re.sub(r"\ba\.C\.(?=\W|$)|\ba\.C\b", "antes de Cristo", s, flags=re.I)
        s = re.sub(r"\bd\.C\.(?=\W|$)|\bd\.C\b", "depois de Cristo", s, flags=re.I)
        s = re.sub(r"\bEUA\b", "Estados Unidos", s)
        s = re.sub(r"\betc\.(?=\W|$)|\betc\b", "etcétera", s, flags=re.I)

    return re.sub(r"\s{2,}", " ", s).strip()

GEMINI_EXPRESSIVE_VOICES = [
    {"id": "Puck", "name": "Puck (Masculino • Energético / Comédia)", "gender": "M"},
    {"id": "Charon", "name": "Charon (Masculino • Grave / Épico / Chefe)", "gender": "M"},
    {"id": "Fenrir", "name": "Fenrir (Masculino • Intenso / Dramático)", "gender": "M"},
    {"id": "Orus", "name": "Orus (Masculino • Firme / Narrador)", "gender": "M"},
    {"id": "Kore", "name": "Kore (Feminino • Firme / Comercial)", "gender": "F"},
    {"id": "Aoede", "name": "Aoede (Feminino • Expressiva / Storytelling)", "gender": "F"},
    {"id": "Zephyr", "name": "Zephyr (Feminino • Jovem / Dinâmica)", "gender": "F"},
    {"id": "Leda", "name": "Leda (Feminino • Suave / Elegante)", "gender": "F"},
]


def _pcm24k_to_wav48k(pcm_bytes: bytes, out_wav: Path, thermal_limit_c: float = 85.0) -> float:
    """Convert raw 24kHz 16-bit mono PCM returned by Gemini TTS into broadcast 48kHz stereo WAV."""
    if not pcm_bytes or len(pcm_bytes) < 2:
        raise ValueError("PCM vazio ou corrompido retornado pelo Gemini TTS")
    if len(pcm_bytes) % 2 != 0:
        pcm_bytes = pcm_bytes[:-1]
    raw_24k = out_wav.with_name(out_wav.stem + "_24k.wav")
    with wave.open(str(raw_24k), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)

    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw_24k), "-ac", "2", "-ar", "48000", str(out_wav)],
        thermal_limit_c=thermal_limit_c,
    )
    raw_24k.unlink(missing_ok=True)
    with wave.open(str(out_wav), "rb") as wf:
        return round(wf.getnframes() / float(wf.getframerate()), 3)


def has_valid_gemini_key() -> Tuple[bool, str]:
    key = (get_settings().get("gemini_api_key") or "").strip()
    # Supports both new AQ.... Gemini API keys AND classic AIza... keys via x-goog-api-key header!
    if (key.startswith("AQ.") and len(key) >= 32) or (key.startswith("AIza") and 35 <= len(key) <= 45):
        return True, key
    return False, key


def _compute_backoff_s(attempt: int, status_code: Optional[int] = None, retry_after: Optional[str] = None) -> float:
    """Compute bounded exponential backoff delay (respecting Retry-After header on HTTP 429/503)."""
    if retry_after:
        try:
            ra = float(str(retry_after).strip())
            if ra > 0.0:
                return min(15.0, max(0.5, ra))
        except Exception:
            pass
    base = 1.5 if status_code == 429 else 1.0
    return min(12.0, base * (2 ** max(0, attempt)))


# ---------------------------------------------------------------------------
# Expressive Punctuation, True Interrogative Prosody & 5-Act Voice Direction
# ---------------------------------------------------------------------------
_ELLIPSIS_TOKEN = "\uE001"
_DOT_TOKEN = "\uE002"

_ACT_DIRECTION_PROFILES: Dict[str, Dict[str, str]] = {
    "ACT_0_COLD_OPEN_HOOK": {
        "pt": (
            "ACT 0 — COLD OPEN HOOK: Urgent, gripping investigative documentary hook in natural Brazilian Portuguese "
            "(~150-160 WPM). Deliver sharp, deliberate suspense pauses before shocking contradictions, build dark intrigue "
            "from the very first syllable, and land any closing question with a provocative rising interrogative inflection."
        ),
        "en": (
            "ACT 0 — COLD OPEN HOOK: Urgent, gripping investigative documentary hook in natural American English "
            "(~150-160 WPM). Deliver sharp, deliberate suspense pauses before shocking contradictions, build dark intrigue "
            "from the very first syllable, and land any closing question with a provocative rising interrogative inflection."
        ),
        "es": (
            "ACT 0 — COLD OPEN HOOK: Urgent, gripping investigative documentary hook in neutral Latin American Spanish "
            "(~150-160 WPM). Deliver sharp suspense pauses before shocking contradictions and land any closing question "
            "with a provocative rising interrogative inflection."
        ),
    },
    "ACT_1_WORLD_BUILDING": {
        "pt": (
            "ACT 1 — HISTORICAL WORLD BUILDING: Atmospheric, immersive historical chronicler in Super Histórico / "
            "H2 History documentary style (natural Brazilian Portuguese, ~135-145 WPM). Deep vocal resonance, rich "
            "baritone gravitas, vivid historical immersion, and unhurried authority that transports the listener into the era."
        ),
        "en": (
            "ACT 1 — HISTORICAL WORLD BUILDING: Atmospheric, immersive historical chronicler in prestige History Channel "
            "/ Netflix documentary style (~135-145 WPM). Deep vocal resonance, baritone gravitas, and vivid authority."
        ),
        "es": (
            "ACT 1 — HISTORICAL WORLD BUILDING: Atmospheric, immersive historical chronicler in prestige documentary "
            "style (~135-145 WPM). Deep vocal resonance, baritone gravitas, and vivid historical authority."
        ),
    },
    "ACT_2_DEEP_MECHANICS": {
        "pt": (
            "ACT 2 — DEEP MECHANICS & FORENSIC INVESTIGATION: Forensic, tense investigative pacing in natural Brazilian "
            "Portuguese (~142-152 WPM). Articulate secret mechanisms, historical dates, decrees, and hidden causal links "
            "with crisp analytical emphasis and mounting investigative pressure."
        ),
        "en": (
            "ACT 2 — DEEP MECHANICS & FORENSIC INVESTIGATION: Forensic, tense investigative pacing (~142-152 WPM). "
            "Emphasize secret mechanisms, historical dates, forbidden decrees, and hidden causal links with sharp clarity."
        ),
        "es": (
            "ACT 2 — DEEP MECHANICS & FORENSIC INVESTIGATION: Forensic, tense investigative pacing (~142-152 WPM). "
            "Emphasize secret mechanisms, historical dates, and forbidden decrees with sharp investigative clarity."
        ),
    },
    "ACT_3_CLIMAX_REVELATION": {
        "pt": (
            "ACT 3 — CLIMAX & DRAMATIC REVELATION: High-stakes dramatic revelation and intense narrative momentum in "
            "natural Brazilian Portuguese (~148-158 WPM). Escalate vocal intensity and emotional urgency on turning points, "
            "letting pivotal reveals strike with unmistakable cinematic weight."
        ),
        "en": (
            "ACT 3 — CLIMAX & DRAMATIC REVELATION: High-stakes dramatic revelation and intense narrative momentum "
            "(~148-158 WPM). Escalate vocal intensity on turning points so pivotal historical reveals strike with cinematic weight."
        ),
        "es": (
            "ACT 3 — CLIMAX & DRAMATIC REVELATION: High-stakes dramatic revelation and intense narrative momentum "
            "(~148-158 WPM). Escalate vocal intensity on turning points so pivotal reveals strike with cinematic weight."
        ),
    },
    "ACT_4_ABRUPT_ENDING": {
        "pt": (
            "ACT 4 — PHILOSOPHICAL RESOLUTION & ABRUPT ENDING: Slower (~110 WPM), deeply philosophical, intimate, and "
            "haunting final reflection in natural Brazilian Portuguese. Lower your vocal cadence, give every clause room "
            "to breathe, and land the final question or thesis with lingering emotional weight and stark finality."
        ),
        "en": (
            "ACT 4 — PHILOSOPHICAL RESOLUTION & ABRUPT ENDING: Slower (~110 WPM), deeply philosophical, intimate, and "
            "haunting final reflection. Lower vocal cadence, give every clause room to breathe, and land the final "
            "question or thesis with lingering emotional weight and stark finality."
        ),
        "es": (
            "ACT 4 — PHILOSOPHICAL RESOLUTION & ABRUPT ENDING: Slower (~110 WPM), deeply philosophical, intimate, and "
            "haunting final reflection. Land the final question or thesis with lingering emotional weight and stark finality."
        ),
    },
}

_MOOD_TONE_OVERLAYS: Dict[str, str] = {
    "dark_horror": "Vocal color: dark gothic suspense, hushed dread, magnetic low-baritone timber (A24 / Netflix dark documentary).",
    "investigative_crime": "Vocal color: grounded forensic true-crime tension, crisp journalistic authority, coiled suspense.",
    "epic_history": "Vocal color: sweeping prestige cinema historian, noble resonance, dramatic emotional gravitas.",
    "corporate_thriller": "Vocal color: sharp investigative financial thriller (MagnatesMedia style), razor-crisp precision on numbers and twists.",
}


def _normalize_act_id(act_id: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", str(act_id or "").strip().lower()).strip("_")
    if not raw:
        return "ACT_1_WORLD_BUILDING"
    if "act_0" in raw or "cold_open" in raw or "hook" in raw:
        return "ACT_0_COLD_OPEN_HOOK"
    if "act_1" in raw or "world_building" in raw or "world" in raw:
        return "ACT_1_WORLD_BUILDING"
    if "act_2" in raw or "deep_mechanics" in raw or "mechanics" in raw or "investig" in raw:
        return "ACT_2_DEEP_MECHANICS"
    if "act_3" in raw or "climax" in raw or "revelation" in raw:
        return "ACT_3_CLIMAX_REVELATION"
    if "act_4" in raw or "abrupt" in raw or "ending" in raw or "epilog" in raw or "outro" in raw:
        return "ACT_4_ABRUPT_ENDING"
    return "ACT_1_WORLD_BUILDING"


def extract_interrogative_sentences(text: str) -> List[str]:
    """Extract every sentence ending with '?' while preserving internal ellipses ('...'),
    colons (':'), em-dashes ('—'), and abbreviations ('a.C.', 'd.C.', 'Séc.', 'D.').
    """
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if "?" not in raw:
        return []

    # Mask ellipses and common period-bearing abbreviations so they never split a question in half
    masked = raw.replace("...", _ELLIPSIS_TOKEN).replace("…", _ELLIPSIS_TOKEN)
    masked = re.sub(
        r"\b(a\.C|d\.C|B\.C\.E|B\.C|A\.D|s[eé]c|etc|Sr|Sra|Dr|Dra|Prof|D)\.",
        lambda m: m.group(1).replace(".", _DOT_TOKEN) + _DOT_TOKEN,
        masked,
        flags=re.I,
    )

    # Split into sentences keeping terminal punctuation (., !, ?)
    parts = re.findall(r"[^.!?\n]+[.!?]+|[^.!?\n]+$", masked)
    questions: List[str] = []
    for seg in parts:
        restored = seg.replace(_ELLIPSIS_TOKEN, "...").replace(_DOT_TOKEN, ".").strip()
        if restored.endswith("?"):
            # Strip stray leading quotes/bullets while keeping the full interrogative clause
            cleaned = restored.lstrip("«\"' ").strip()
            if cleaned:
                questions.append(cleaned)
    return questions


def build_punctuation_prosody_direction(
    clean_text: str,
    raw_text: str = "",
    lang: str = "pt_br",
) -> str:
    """Inspect punctuation & sentence structure and build an expressive prosody direction block
    guaranteeing genuine interrogative pitch contours on '?' and theatrical pacing on ':', '—', '...'.
    """
    src_text = clean_text or raw_text or ""
    combined_raw = f"{raw_text} {clean_text}"
    interrogative_sentences = extract_interrogative_sentences(src_text)
    if not interrogative_sentences and raw_text:
        interrogative_sentences = extract_interrogative_sentences(raw_text)

    blocks: List[str] = []

    if interrogative_sentences:
        quoted_qs = " | ".join(f'"{q}"' for q in interrogative_sentences)
        blocks.append(
            "CRITICAL QUESTION PROSODY: The sentence(s) ending in '?' MUST be spoken with a genuine, deep, "
            "suspenseful INTERROGATIVE rising-falling pitch contour of doubt and provocation — NEVER flatten a "
            "question '?' into a normal affirmative statement period. Hold a 0.35s dramatic pause right before "
            f"the final question phrase. Exact question sentence(s) to inflect interrogatively: {quoted_qs}."
        )

    has_dramatic_punct = any(tok in combined_raw for tok in (":", "—", "–", "...", "…"))
    blocks.append(
        "Honor every comma (0.18s micro-pause), colon/dash (0.30s dramatic reveal pause before the key fact), "
        "and period (0.35s resonant weight) with deep theatrical authority (Super Histórico / H2 History narrator style)."
    )
    if has_dramatic_punct:
        blocks.append(
            "Pause deliberately on every colon (:), em-dash (—), and ellipsis (...) so the key historical reveal "
            "lands with palpable suspense and vocal depth."
        )
    if "!" in src_text:
        blocks.append(
            "Deliver exclamation sentences with controlled dramatic gravitas and resonant chest emphasis, never cartoonish shouting."
        )

    return " ".join(blocks)


def build_act_acting_direction(
    act_id: str,
    mood: str = "dark_horror",
    lang: str = "pt_br",
    text: str = "",
) -> str:
    """Return a tailored Gemini TTS acting direction for any of the 5 documentary acts
    (`ACT_0_COLD_OPEN_HOOK` through `ACT_4_ABRUPT_ENDING`), enriched with mood color and
    punctuation/interrogative prosody rules when `text` is provided.
    """
    canonical_act = _normalize_act_id(act_id)
    lang_low = str(lang or "pt_br").strip().lower()
    lang_key = "en" if lang_low.startswith("en") else ("es" if lang_low.startswith("es") else "pt")
    act_prompt = _ACT_DIRECTION_PROFILES[canonical_act][lang_key]

    mood_key = str(mood or "dark_horror").strip().lower()
    mood_overlay = _MOOD_TONE_OVERLAYS.get(mood_key, _MOOD_TONE_OVERLAYS["dark_horror"])

    parts = [act_prompt, mood_overlay]
    if (text or "").strip():
        clean_t = normalize_narration_for_speech(text, lang=lang)
        parts.append(build_punctuation_prosody_direction(clean_t, raw_text=text, lang=lang))
    else:
        parts.append(
            "Honor every comma (0.18s micro-pause), colon/dash (0.30s dramatic reveal pause before the key fact), "
            "and period (0.35s resonant weight) with deep theatrical authority (Super Histórico / H2 History narrator style)."
        )
    return " ".join(parts)


def build_gemini_tts_prompt(
    text: str,
    acting_direction: str = "Read aloud in Brazilian Portuguese with expressive, natural voice acting.",
    lang: str = "pt_br",
) -> Tuple[str, str, str]:
    """Normalize transcript, attach dynamic Punctuation & Interrogative Prosody directions,
    and return `(prompt, clean_text, enriched_acting_direction)`.
    """
    clean_text = normalize_narration_for_speech(text, lang=lang)
    base_dir = (acting_direction or "").strip()
    prosody_block = build_punctuation_prosody_direction(clean_text, raw_text=text, lang=lang)

    # Avoid duplicating prosody directions if caller already used build_act_acting_direction(..., text=...)
    has_q_block = "CRITICAL QUESTION PROSODY" in base_dir
    has_punct_block = "Honor every comma (0.18s micro-pause)" in base_dir
    if has_punct_block and (has_q_block or "?" not in clean_text):
        enriched_direction = base_dir
    elif has_punct_block and "?" in clean_text and not has_q_block:
        # Caller had base punctuation rule (without text) — inject only the missing question prosody block!
        qs = extract_interrogative_sentences(clean_text) or extract_interrogative_sentences(text)
        quoted_qs = " | ".join(f'"{q}"' for q in qs)
        q_only = (
            "CRITICAL QUESTION PROSODY: The sentence(s) ending in '?' MUST be spoken with a genuine, deep, "
            "suspenseful INTERROGATIVE rising-falling pitch contour of doubt and provocation — NEVER flatten a "
            "question '?' into a normal affirmative statement period. Hold a 0.35s dramatic pause right before "
            f"the final question phrase. Exact question sentence(s) to inflect interrogatively: {quoted_qs}."
        )
        enriched_direction = f"{base_dir} {q_only}".strip()
    else:
        enriched_direction = f"{base_dir} {prosody_block}".strip() if base_dir else prosody_block

    lang_low = str(lang or "pt_br").lower()
    lang_label = (
        "American English" if lang_low.startswith("en")
        else ("Latin American Spanish" if lang_low.startswith("es") else "Brazilian Portuguese")
    )
    prompt = f"Read aloud ONLY the following {lang_label} transcript as natural spoken audio ({enriched_direction}):\n{clean_text}"
    return prompt, clean_text, enriched_direction


def synthesize_gemini_tts_line(
    text: str,
    out_wav: Path,
    voice_name: str = "Puck",
    acting_direction: str = "Read aloud in Brazilian Portuguese with expressive, natural voice acting.",
    api_key: Optional[str] = None,
    lang: str = "pt_br",
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, float]:
    """Synthesize a single expressive speech line using Google Gemini Native TTS (x-goog-api-key)."""
    key = (api_key or get_settings().get("gemini_api_key") or "").strip()
    if not key:
        raise RuntimeError("Chave Gemini API não configurada.")

    prompt, _, _ = build_gemini_tts_prompt(text=text, acting_direction=acting_direction, lang=lang)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name,
                    }
                }
            },
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    last_err = "Gemini TTS indisponível"
    max_attempts = 4

    for model_id in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        for attempt in range(max_attempts):
            try:
                r = httpx.post(url, json=payload, headers=headers, timeout=45.0)
                if r.status_code in (429, 500, 502, 503):
                    last_err = f"Gemini TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                    if attempt < max_attempts - 1:
                        wait_s = _compute_backoff_s(
                            attempt,
                            status_code=r.status_code,
                            retry_after=r.headers.get("Retry-After") if hasattr(r, "headers") else None,
                        )
                        time.sleep(wait_s)
                        continue
                    break
                if r.status_code != 200:
                    last_err = f"Gemini TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                    break

                j = r.json()
                parts = j.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                audio_b64 = ""
                for p in parts:
                    idata = p.get("inlineData") or p.get("inline_data")
                    if idata and idata.get("data"):
                        audio_b64 = idata["data"]
                        break
                if not audio_b64:
                    last_err = f"Gemini TTS ({model_id}) retornou resposta sem áudio."
                    break

                pcm = base64.b64decode(audio_b64)
                dur_s = _pcm24k_to_wav48k(pcm, out_wav, thermal_limit_c=thermal_limit_c)

                meta = j.get("usageMetadata", {})
                pt = int(meta.get("promptTokenCount", 40))
                ct = int(meta.get("candidatesTokenCount", 120))
                record_token_usage("gemini-tts", model_id, pt, ct, 0, round((pt * 0.5 + ct * 10.0) / 1_000_000.0, 5))
                return out_wav, dur_s
            except Exception as exc:
                last_err = str(exc)
                if attempt < max_attempts - 1:
                    time.sleep(_compute_backoff_s(attempt))
                    continue
                break

    raise RuntimeError(last_err)


def synthesize_gemini_multispeaker_dialogue(
    dialogue_lines: List[Dict[str, str]],
    speaker_voices: Dict[str, str],
    out_wav: Path,
    direction: str = "TTS the following conversation in Brazilian Portuguese with comic, expressive voice acting:",
    api_key: Optional[str] = None,
) -> Tuple[Path, float]:
    """Synthesize an entire multi-character conversation in ONE API call using multiSpeakerVoiceConfig."""
    key = (api_key or get_settings().get("gemini_api_key") or "").strip()
    if not key:
        raise RuntimeError("Chave Gemini API não configurada.")

    script_text = "\n".join(f"{ln['speaker']}: {ln['text']}" for ln in dialogue_lines)
    prompt = f"{direction}\n{script_text}"
    speaker_cfgs = [
        {
            "speaker": sp_name,
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v_name}},
        }
        for sp_name, v_name in speaker_voices.items()
    ]

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": speaker_cfgs,
                }
            },
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    last_err = "Gemini Multi-Speaker TTS indisponível"
    max_attempts = 4

    for model_id in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        for attempt in range(max_attempts):
            try:
                r = httpx.post(url, json=payload, headers=headers, timeout=60.0)
                if r.status_code in (429, 500, 502, 503):
                    last_err = f"Gemini Multi-Speaker TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                    if attempt < max_attempts - 1:
                        time.sleep(
                            _compute_backoff_s(
                                attempt,
                                status_code=r.status_code,
                                retry_after=r.headers.get("Retry-After") if hasattr(r, "headers") else None,
                            )
                        )
                        continue
                    break
                if r.status_code != 200:
                    last_err = f"Gemini Multi-Speaker TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                    break

                j = r.json()
                parts = j.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                audio_b64 = ""
                for p in parts:
                    idata = p.get("inlineData") or p.get("inline_data")
                    if idata and idata.get("data"):
                        audio_b64 = idata["data"]
                        break
                if not audio_b64:
                    last_err = f"Gemini Multi-Speaker TTS ({model_id}) sem áudio."
                    break

                pcm = base64.b64decode(audio_b64)
                dur_s = _pcm24k_to_wav48k(pcm, out_wav)
                meta = j.get("usageMetadata", {})
                pt = int(meta.get("promptTokenCount", 120))
                ct = int(meta.get("candidatesTokenCount", 400))
                record_token_usage("gemini-tts", model_id, pt, ct, 0, round((pt * 0.5 + ct * 10.0) / 1_000_000.0, 5))
                return out_wav, dur_s
            except Exception as exc:
                last_err = str(exc)
                if attempt < max_attempts - 1:
                    time.sleep(_compute_backoff_s(attempt))
                    continue
                break

    raise RuntimeError(last_err)
