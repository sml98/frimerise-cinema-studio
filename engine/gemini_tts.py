"""FrimeRise Google AI Studio Gemini 2.5 Flash Native Expressive & Multi-Speaker TTS.
Uses the user's Google AI Studio API key (AIza...) via official REST API:
  - Single-character expressive acting TTS (with tone/accent/emotion direction)
  - Native Multi-Speaker Dialogue TTS (multiSpeakerVoiceConfig)
  - Automatic graceful fallback to Edge-TTS if key is missing or invalid.
"""
from __future__ import annotations

import base64
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from database import get_settings, record_token_usage
from engine.intel_vaapi import run_ffmpeg_safe

GEMINI_TTS_MODELS = ("gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_MODEL = GEMINI_TTS_MODELS[0]
GEMINI_TEXT_MODELS = ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash")

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


def _pcm24k_to_wav48k(pcm_bytes: bytes, out_wav: Path) -> float:
    """Convert raw 24kHz 16-bit mono PCM returned by Gemini TTS into broadcast 48kHz stereo WAV."""
    raw_24k = out_wav.with_name(out_wav.stem + "_24k.wav")
    with wave.open(str(raw_24k), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)

    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw_24k), "-ac", "2", "-ar", "48000", str(out_wav)]
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


def synthesize_gemini_tts_line(
    text: str,
    out_wav: Path,
    voice_name: str = "Puck",
    acting_direction: str = "Read aloud in Brazilian Portuguese with expressive, natural cartoon voice acting.",
    api_key: Optional[str] = None,
) -> Tuple[Path, float]:
    """Synthesize a single expressive speech line using Google Gemini Native TTS (x-goog-api-key)."""
    key = (api_key or get_settings().get("gemini_api_key") or "").strip()
    if not key:
        raise RuntimeError("Chave Gemini API não configurada.")

    clean_text = text.strip()
    prompt = f"Read aloud ONLY the following Brazilian Portuguese transcript as audio ({acting_direction}):\n{clean_text}"
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

    for model_id in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=35.0)
            if r.status_code != 200:
                last_err = f"Gemini TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                continue

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
                continue

            pcm = base64.b64decode(audio_b64)
            dur_s = _pcm24k_to_wav48k(pcm, out_wav)

            meta = j.get("usageMetadata", {})
            pt = int(meta.get("promptTokenCount", 40))
            ct = int(meta.get("candidatesTokenCount", 120))
            record_token_usage("gemini-tts", model_id, pt, ct, 0, round((pt * 0.5 + ct * 10.0) / 1_000_000.0, 5))
            return out_wav, dur_s
        except Exception as exc:
            last_err = str(exc)
            continue

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

    for model_id in GEMINI_TTS_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            if r.status_code != 200:
                last_err = f"Gemini Multi-Speaker TTS ({model_id}) HTTP {r.status_code}: {r.text[:160]}"
                continue

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
                continue

            pcm = base64.b64decode(audio_b64)
            dur_s = _pcm24k_to_wav48k(pcm, out_wav)
            meta = j.get("usageMetadata", {})
            pt = int(meta.get("promptTokenCount", 120))
            ct = int(meta.get("candidatesTokenCount", 400))
            record_token_usage("gemini-tts", model_id, pt, ct, 0, round((pt * 0.5 + ct * 10.0) / 1_000_000.0, 5))
            return out_wav, dur_s
        except Exception as exc:
            last_err = str(exc)
            continue

    raise RuntimeError(last_err)
