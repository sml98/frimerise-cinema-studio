"""FrimeRise Broadcast Audio DSP Studio.
- Local Expressive Voices: Kokoro-ONNX + OpenVINO Voice Blender (pf_dora, pm_alex, pm_santa)
- Instant Cloud Voices: edge-tts >= 7.3.0 with boundary="WordBoundary" exact timestamps
- Offline fallback: espeak-ng PT-BR
- Neural Silence Trimming: Silero VAD ONNX (preserving final consonants) + energy VAD fallback
- Broadcast FM Chain (100% permissive FFmpeg filters — ZERO GPL pedalboard):
    highpass=f=85 -> De-Esser 6500Hz -> Presence 3200Hz -> loudnorm=-14 LUFS -> sidechaincompress
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
import numpy as np
import onnxruntime as ort
from scipy import signal

from engine.intel_vaapi import run_ffmpeg_safe

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
MODELS_DIR = BASE_DIR / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

PT_BR_EDGE_VOICES = [
    {"id": "pt-BR-AntonioNeural", "name": "Antônio (Masculino • Autoridade)", "gender": "M", "lang": "pt_br"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca (Feminino • Premium)", "gender": "F", "lang": "pt_br"},
    {"id": "pt-BR-ThalitaMultilingualNeural", "name": "Thalita (Feminino • Comercial UGC)", "gender": "F", "lang": "pt_br"},
]

ALL_EDGE_VOICES = [
    {"id": "pt-BR-AntonioNeural", "name": "🇧🇷 Antônio (PT-BR • Masculino Autoridade)", "gender": "M", "lang": "pt_br"},
    {"id": "pt-BR-FranciscaNeural", "name": "🇧🇷 Francisca (PT-BR • Feminino Premium)", "gender": "F", "lang": "pt_br"},
    {"id": "pt-BR-ThalitaMultilingualNeural", "name": "🇧🇷 Thalita (PT-BR • Feminino Comercial UGC)", "gender": "F", "lang": "pt_br"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "🇺🇸 Andrew (EN-US • Male Documentary/Narrator)", "gender": "M", "lang": "en_us"},
    {"id": "en-US-AvaMultilingualNeural", "name": "🇺🇸 Ava (EN-US • Female Warm/Viral)", "gender": "F", "lang": "en_us"},
    {"id": "en-US-GuyNeural", "name": "🇺🇸 Guy (EN-US • Male Energetic/News)", "gender": "M", "lang": "en_us"},
    {"id": "es-MX-JorgeNeural", "name": "🇪🇸 Jorge (ES • Masculino Firme/Impacto)", "gender": "M", "lang": "es"},
    {"id": "es-MX-DaliaNeural", "name": "🇪🇸 Dalia (ES • Femenino Dinámica)", "gender": "F", "lang": "es"},
]

KOKORO_PT_VOICES = ["pf_dora", "pm_alex", "pm_santa"]
KOKORO_VOICES = ["pm_alex", "pf_dora", "pm_santa", "af_heart", "am_adam"]


def normalize_edge_rate(rate: Optional[str]) -> str:
    """Sanitize Edge-TTS rate string (e.g. '-6%', '+0%', '+8%', '+15%') within safe bounds."""
    raw = str(rate if rate is not None else "+8%").strip().replace(" ", "")
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%?$", raw)
    if not m:
        return "+8%"
    val = int(round(max(-50.0, min(100.0, float(m.group(1))))))
    return f"+{val}%" if val >= 0 else f"{val}%"


def normalize_edge_pitch(pitch: Optional[str]) -> str:
    """Sanitize Edge-TTS pitch string (e.g. '-8Hz', '+0Hz', '+8Hz') within safe bounds."""
    raw = str(pitch if pitch is not None else "+0Hz").strip().replace(" ", "")
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)(?:hz)?$", raw, re.IGNORECASE)
    if not m:
        return "+0Hz"
    val = int(round(max(-50.0, min(50.0, float(m.group(1))))))
    return f"+{val}Hz" if val >= 0 else f"{val}Hz"


def _parse_signed_int(val_str: str, default: int = 0) -> int:
    m = re.search(r"([+-]?\d+)", str(val_str or ""))
    return int(m.group(1)) if m else default


def _rate_to_kokoro_speed(rate: str) -> float:
    pct = _parse_signed_int(rate, 8)
    return round(max(0.65, min(1.55, 1.0 + pct / 100.0)), 2)


def _infer_lang_from_voice_id(voice_id: str, fallback: str = "pt_br") -> str:
    vid = str(voice_id or "").strip().lower()
    if vid.startswith("en-") or vid.startswith("af_") or vid.startswith("am_"):
        return "en_us"
    if vid.startswith("es-"):
        return "es"
    if vid.startswith("pt-") or vid.startswith("pf_") or vid.startswith("pm_"):
        return "pt_br"
    fb = str(fallback or "pt_br").strip().lower().replace("-", "_")
    if fb.startswith("en"):
        return "en_us"
    if fb.startswith("es"):
        return "es"
    return "pt_br"


def _default_edge_voice_for_lang(language: str, female: bool = False) -> str:
    lang = str(language or "pt_br").strip().lower().replace("-", "_")
    if lang.startswith("en"):
        return "en-US-AvaMultilingualNeural" if female else "en-US-AndrewMultilingualNeural"
    if lang.startswith("es"):
        return "es-MX-DaliaNeural" if female else "es-MX-JorgeNeural"
    return "pt-BR-FranciscaNeural" if female else "pt-BR-AntonioNeural"


def _build_gemini_acting_direction(rate: str, pitch: str, language: str = "pt_br") -> str:
    """Translate user rate/pitch settings into rich Gemini TTS acting direction cues."""
    lang = str(language or "pt_br").strip().lower().replace("-", "_")
    lang_desc = {
        "en_us": "American English",
        "es": "Neutral Latin American Spanish",
    }.get(lang, "Brazilian Portuguese")

    rate_num = _parse_signed_int(rate, 8)
    if rate_num <= -4:
        pace_cue = "with a slow, deliberate, cinematic documentary pace and thoughtful pauses"
    elif rate_num <= 3:
        pace_cue = "with a clear, natural, conversational broadcast pace"
    elif rate_num <= 11:
        pace_cue = "with a dynamic, engaging, viral storytelling rhythm"
    else:
        pace_cue = "with a fast, punchy, high-energy short-form viral delivery"

    pitch_num = _parse_signed_int(pitch, 0)
    if pitch_num <= -4:
        pitch_cue = "and a deep, resonant, authoritative lower vocal pitch"
    elif pitch_num >= 4:
        pitch_cue = "and a bright, expressive, upbeat higher vocal pitch"
    else:
        pitch_cue = "and a balanced, crisp studio vocal tone"

    return f"Read aloud in {lang_desc} {pace_cue}, {pitch_cue}."


def _get_wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
        )
        return float(res.stdout.strip() or 5.0)


def _estimate_word_timestamps(text: str, total_duration: float) -> List[Dict[str, Any]]:
    """Fallback proportional word timing when exact WordBoundary is unavailable."""
    words = [w for w in text.strip().split() if w]
    if not words:
        return []
    weights = [max(2, len(w)) + (3 if w[-1] in ".!?,;:" else 0) for w in words]
    total_w = float(sum(weights))
    cursor = 0.08
    usable = max(0.5, total_duration - 0.16)
    result = []
    for w, wt in zip(words, weights):
        dur = usable * (wt / total_w)
        result.append({"word": w, "start": round(cursor, 3), "end": round(cursor + dur, 3)})
        cursor += dur
    return result


# ---------------------------------------------------------------------------
# 1. Kokoro-ONNX + OpenVINO Voice Blender (Local Expressive PT-BR)
# ---------------------------------------------------------------------------
def _kokoro_available() -> Tuple[bool, Path, Path]:
    model_path = MODELS_DIR / "kokoro-v1.0.onnx"
    voices_path = MODELS_DIR / "voices-v1.0.bin"
    return (model_path.exists() and voices_path.exists()), model_path, voices_path


def synthesize_kokoro_blended(
    text: str,
    out_wav: Path,
    blend_weights: Dict[str, float],
    speed: float = 1.08,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Synthesize PT-BR speech locally via Kokoro-ONNX + OpenVINO with Voice Blender."""
    avail, model_path, voices_path = _kokoro_available()
    if not avail:
        raise RuntimeError("Modelos Kokoro ONNX ainda não baixados localmente (usando Edge-TTS instantâneo).")

    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(model_path), str(voices_path))
    # Voice Blender: linear interpolation of speaker embedding vectors across all supported Kokoro voices
    vectors = []
    weights = []
    dominant_voice = "pm_alex"
    max_w = -1.0
    candidate_voices = list(dict.fromkeys([*KOKORO_VOICES, *list(blend_weights.keys())]))
    for vname in candidate_voices:
        w = float(blend_weights.get(vname, 0.0))
        if w > 0.0:
            try:
                vec = kokoro.get_voice_style(vname)
                vectors.append(vec)
                weights.append(w)
                if w > max_w:
                    max_w = w
                    dominant_voice = vname
            except Exception:
                continue

    if not vectors:
        blended_style = kokoro.get_voice_style("pm_alex")
    else:
        total_w = sum(weights)
        blended_style = sum(v * (w / total_w) for v, w in zip(vectors, weights))

    kokoro_lang = "en-us" if dominant_voice.startswith(("af_", "am_")) else "pt-br"
    samples, sr = kokoro.create(text, voice=blended_style, speed=speed, lang=kokoro_lang)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())

    dur = _get_wav_duration(out_wav)
    return out_wav, _estimate_word_timestamps(text, dur)


# ---------------------------------------------------------------------------
# 2. Edge-TTS >= 7.3.0 with Exact WordBoundary Timestamps
# ---------------------------------------------------------------------------
async def synthesize_edge_tts(
    text: str,
    out_mp3: Path,
    voice: str = "pt-BR-AntonioNeural",
    rate: str = "+8%",
    pitch: str = "+0Hz",
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Instant cloud TTS (PT-BR / EN-US / ES) with custom speed/pitch & native WordBoundary timestamps."""
    clean_rate = normalize_edge_rate(rate)
    clean_pitch = normalize_edge_pitch(pitch)
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=clean_rate,
        pitch=clean_pitch,
        boundary="WordBoundary",
    )
    words: List[Dict[str, Any]] = []
    audio_chunks = bytearray()

    async for chunk in communicate.stream():
        ctype = chunk.get("type")
        if ctype == "audio":
            audio_chunks.extend(chunk["data"])
        elif ctype == "WordBoundary":
            start_s = float(chunk["offset"]) / 10_000_000.0
            dur_s = float(chunk["duration"]) / 10_000_000.0
            words.append(
                {
                    "word": str(chunk["text"]).strip(),
                    "start": round(start_s, 3),
                    "end": round(start_s + max(0.06, dur_s), 3),
                }
            )

    if not audio_chunks:
        raise RuntimeError("Edge-TTS retornou áudio vazio")

    out_mp3.write_bytes(bytes(audio_chunks))
    if not words:
        dur = _get_wav_duration(out_mp3)
        words = _estimate_word_timestamps(text, dur)
    return out_mp3, words


def _synthesize_espeak_fallback(text: str, out_wav: Path, language: str = "pt_br") -> Tuple[Path, List[Dict[str, Any]]]:
    """100% offline TTS fallback via espeak-ng (PT-BR / EN-US / ES) if internet is offline."""
    espeak_lang = {"en_us": "en-us", "es": "es"}.get(str(language or "pt_br").lower(), "pt-br")
    subprocess.run(
        ["espeak-ng", "-v", espeak_lang, "-s", "165", "-w", str(out_wav), text],
        check=True,
        capture_output=True,
    )
    dur = _get_wav_duration(out_wav)
    return out_wav, _estimate_word_timestamps(text, dur)


# ---------------------------------------------------------------------------
# 3. Neural Silence Trimming (Silero VAD ONNX + Consonant-Safe RMS Fallback)
# ---------------------------------------------------------------------------
def trim_silence_vad(
    input_audio: Path,
    output_wav: Path,
    words: List[Dict[str, Any]],
    max_pause_s: float = 0.28,
    consonant_pad_s: float = 0.085,
    thermal_limit_c: float = 85.0,
    trim_edges_only: bool = False,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Tighten long pauses while strictly preserving final consonants (+85ms tail).
    When `trim_edges_only=True` (Cinema Documentary mode), trims ONLY dead leading/trailing
    silence and preserves 100% of internal natural breathing and dramatic punctuation pauses.
    """
    raw_16k = output_wav.with_name(output_wav.stem + "_16k.wav")
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-i", str(input_audio), "-ac", "1", "-ar", "16000", str(raw_16k)],
        thermal_limit_c=thermal_limit_c,
    )

    with wave.open(str(raw_16k), "rb") as wf:
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

    # Try Silero VAD ONNX if cached; otherwise fast frame-level spectral/RMS VAD
    silero_path = MODELS_DIR / "silero_vad.onnx"
    frame_len = 512  # 32ms at 16kHz
    n_frames = len(pcm) // frame_len
    speech_probs = np.zeros(n_frames, dtype=np.float32)

    # Adaptive energy + zero-crossing speech detector (immune to long Gemini TTS trailing room-tone hiss!)
    frames = pcm[: n_frames * frame_len].reshape(n_frames, frame_len) if n_frames > 0 else np.zeros((0, frame_len), dtype=np.float32)
    rms_energy = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10) if n_frames > 0 else np.zeros(0, dtype=np.float32)
    peak_speech_ref = float(np.percentile(rms_energy, 92)) if n_frames > 10 else 0.05
    energy_floor = max(0.014, peak_speech_ref * 0.11)

    if silero_path.exists():
        try:
            sess = ort.InferenceSession(str(silero_path), providers=["CPUExecutionProvider"])
            state = np.zeros((2, 1, 128), dtype=np.float32)
            sr_arr = np.array(sr, dtype=np.int64)
            for i in range(n_frames):
                chunk = pcm[i * frame_len : (i + 1) * frame_len][None, :]
                out, state = sess.run(None, {"input": chunk, "state": state, "sr": sr_arr})
                # Require minimum acoustic energy so pure room-tone hiss never triggers false speech
                speech_probs[i] = float(out[0][0]) if rms_energy[i] >= energy_floor * 0.55 else 0.0
        except Exception:
            silero_path = Path("__fallback__")

    if not silero_path.exists() and n_frames > 0:
        zcr = np.mean(np.abs(np.diff(np.sign(frames), axis=1)) > 0, axis=1)
        speech_probs = ((rms_energy > energy_floor) | ((rms_energy > energy_floor * 0.55) & (zcr > 0.12))).astype(np.float32)

    # Convert to speech intervals with generous consonant tail pad
    frame_s = frame_len / float(sr)
    pad_frames = int(math.ceil(consonant_pad_s / frame_s))
    active = speech_probs > 0.35
    # Suppress isolated 1-frame hiss spikes (require >= 2 consecutive active frames = 64ms)
    if n_frames >= 3:
        sustained = active & (np.roll(active, 1) | np.roll(active, -1))
        if np.any(sustained):
            active = sustained
    # Dilate active mask so final consonants ("s", "r", "t", "k") are NEVER clipped
    if n_frames > 0 and np.any(active):
        kernel = np.ones(pad_frames * 2 + 1, dtype=np.int32)
        dilated = np.convolve(active.astype(np.int32), kernel, mode="same") > 0
    else:
        dilated = np.ones(n_frames, dtype=bool)

    # Keep natural micro-pauses up to max_pause_s; ALWAYS preserve clean lead-in & tail after last real speech
    active_idx = np.where(dilated)[0]
    keep_mask = np.zeros(n_frames, dtype=bool)
    if trim_edges_only and len(active_idx) > 0:
        lead_frames = int(math.ceil(0.06 / frame_s))
        tail_frames = int(math.ceil(0.24 / frame_s))
        start_f = max(0, int(active_idx[0]) - lead_frames)
        end_f = min(n_frames, int(active_idx[-1]) + tail_frames)
        # Preserve all natural human breaths (<= 0.50s), while capping any glitched long internal silence (> 0.50s)
        max_internal_sil = int(max(0.45, max_pause_s) / frame_s)
        sil_run = 0
        for i in range(start_f, end_f):
            if dilated[i] or i < int(active_idx[0]) or i > int(active_idx[-1]):
                keep_mask[i] = True
                sil_run = 0
            else:
                sil_run += 1
                if sil_run <= max_internal_sil:
                    keep_mask[i] = True
    else:
        max_sil_frames = int(max_pause_s / frame_s)
        sil_run = 0
        for i in range(n_frames):
            if dilated[i]:
                keep_mask[i] = True
                sil_run = 0
            else:
                sil_run += 1
                if sil_run <= max_sil_frames:
                    keep_mask[i] = True

        if len(active_idx) > 0:
            last_speech = int(active_idx[-1])
            tail_frames = int(math.ceil(0.25 / frame_s))
            keep_mask[last_speech : min(n_frames, last_speech + tail_frames)] = True

    # Build time remapping table to shift WordBoundary timestamps accurately
    kept_indices = np.where(keep_mask)[0]
    if len(kept_indices) < max(5, int(n_frames * 0.2)):
        # Safety: if audio was very quiet, keep untouched
        run_ffmpeg_safe(
            ["ffmpeg", "-y", "-v", "error", "-i", str(input_audio), "-ac", "2", "-ar", "48000", str(output_wav)],
            thermal_limit_c=thermal_limit_c,
        )
        raw_16k.unlink(missing_ok=True)
        return output_wav, words, _get_wav_duration(output_wav)

    # Decode original at 48kHz for zero quality loss while cutting
    raw_48k = output_wav.with_name(output_wav.stem + "_48k.wav")
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-i", str(input_audio), "-ac", "2", "-ar", "48000", str(raw_48k)],
        thermal_limit_c=thermal_limit_c,
    )
    with wave.open(str(raw_48k), "rb") as wf:
        pcm48 = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).reshape(-1, 2)

    step48 = int(frame_s * 48000)
    chunks_out = []
    old_to_new: List[Tuple[float, float]] = []
    new_t = 0.0
    for idx in kept_indices:
        s48 = idx * step48
        e48 = min(len(pcm48), s48 + step48)
        if e48 > s48:
            chunks_out.append(pcm48[s48:e48])
            old_to_new.append((idx * frame_s, new_t))
            new_t += (e48 - s48) / 48000.0

    final_pcm = np.vstack(chunks_out) if chunks_out else pcm48
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(final_pcm.astype(np.int16).tobytes())

    raw_16k.unlink(missing_ok=True)
    raw_48k.unlink(missing_ok=True)

    # Remap word timestamps smoothly
    if old_to_new:
        old_ts = np.array([x[0] for x in old_to_new])
        new_ts = np.array([x[1] for x in old_to_new])
        remapped_words = []
        for w in words:
            ns = float(np.interp(w["start"], old_ts, new_ts))
            ne = float(np.interp(w["end"], old_ts, new_ts))
            remapped_words.append({"word": w["word"], "start": round(ns, 3), "end": round(max(ns + 0.06, ne), 3)})
    else:
        remapped_words = words

    dur = len(final_pcm) / 48000.0
    return output_wav, remapped_words, round(dur, 3)


_WHISPER_ALIGN_MODEL = None


def _get_whisper_align_model():
    global _WHISPER_ALIGN_MODEL
    if _WHISPER_ALIGN_MODEL is None:
        from faster_whisper import WhisperModel

        _WHISPER_ALIGN_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=4)
    return _WHISPER_ALIGN_MODEL


def _load_wav_16k_float32(wav_path: Path) -> np.ndarray:
    """Decode PCM WAV directly to 16kHz mono float32 ndarray (bypasses PyAV version mismatches!)."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if sr != 16000 and len(pcm) > 0:
        pcm = signal.resample_poly(pcm, 16000, sr).astype(np.float32)
    return pcm.astype(np.float32, copy=False)


def align_script_words_to_audio(
    wav_path: Path,
    script_text: str,
    duration_s: float,
    lang: str = "pt_br",
) -> List[Dict[str, Any]]:
    """Align script words to human TTS audio (Gemini TTS) using local faster-whisper int8
    (passing 16kHz float32 ndarray directly to bypass PyAV) + SequenceMatcher token alignment
    so captions stay laser-synced to real human breaths and dramatic pauses.
    """
    import difflib
    import unicodedata

    tokens = [w.strip() for w in (script_text or "").split() if w.strip()]
    if not tokens:
        return []
    dur_total = max(0.4, float(duration_s or _get_wav_duration(wav_path) or 1.0))

    def _norm_tok(s: str) -> str:
        nfd = unicodedata.normalize("NFKD", s.lower())
        return re.sub(r"[^a-z0-9]", "", "".join(c for c in nfd if not unicodedata.combining(c)))

    # 1. Local faster-whisper int8 via direct 16kHz float32 numpy array (zero PyAV errors!)
    try:
        model = _get_whisper_align_model()
        audio_16k = _load_wav_16k_float32(wav_path)
        w_lang = "en" if str(lang).lower().startswith("en") else ("es" if str(lang).lower().startswith("es") else "pt")
        segments, _ = model.transcribe(
            audio_16k,
            language=w_lang,
            word_timestamps=True,
            vad_filter=False,
            beam_size=1,
        )
        heard: List[Tuple[float, float, str]] = []
        for seg in segments:
            for wd in (seg.words or []):
                st = max(0.0, float(wd.start))
                en = min(dur_total, max(st + 0.06, float(wd.end)))
                heard.append((st, en, str(wd.word or "").strip()))

        if len(heard) >= max(2, int(len(tokens) * 0.45)):
            script_norms = [_norm_tok(t) for t in tokens]
            heard_norms = [_norm_tok(h[2]) for h in heard]
            sm = difflib.SequenceMatcher(None, script_norms, heard_norms, autojunk=False)
            anchors: Dict[int, Tuple[float, float]] = {}
            for blk in sm.get_matching_blocks():
                for k in range(blk.size):
                    anchors[blk.a + k] = (heard[blk.b + k][0], heard[blk.b + k][1])

            aligned: List[Dict[str, Any]] = []
            n_t = len(tokens)
            n_h = len(heard)
            speech_start = heard[0][0]
            speech_end = heard[-1][1]

            # Fill any unmatched tokens cleanly by interpolating between neighboring matched anchors
            idx = 0
            while idx < n_t:
                if idx in anchors:
                    st, en = anchors[idx]
                    if aligned and st < aligned[-1]["end"]:
                        st = aligned[-1]["end"]
                    en = max(st + 0.06, min(dur_total, en))
                    aligned.append({"word": tokens[idx], "start": round(st, 3), "end": round(en, 3)})
                    idx += 1
                else:
                    run_end = idx
                    while run_end < n_t and run_end not in anchors:
                        run_end += 1
                    t_left = aligned[-1]["end"] if aligned else speech_start
                    t_right = anchors[run_end][0] if run_end < n_t else speech_end
                    if t_right <= t_left + 0.05:
                        h_i = min(n_h - 1, int(idx * n_h / n_t))
                        t_right = max(t_left + 0.14 * (run_end - idx), heard[min(n_h - 1, h_i + (run_end - idx))][1])
                    span = max(0.08 * (run_end - idx), t_right - t_left)
                    step = span / float(run_end - idx)
                    for k, j_tok in enumerate(range(idx, run_end)):
                        st = t_left + k * step
                        en = min(dur_total, st + max(0.06, step * 0.92))
                        aligned.append({"word": tokens[j_tok], "start": round(st, 3), "end": round(en, 3)})
                    idx = run_end
            return aligned
    except Exception as exc:
        print(f"[AudioDSP] Whisper alignment fallback: {exc}", flush=True)

    # 2. Punctuation-weighted fallback (accounts for comma/period/ellipsis breathing pauses!)
    weights: List[float] = []
    for tok in tokens:
        base_w = max(2.2, float(len(re.sub(r"[^\wÀ-ÿ]", "", tok))))
        pause_extra = 0.0
        if tok.endswith(("...", "…")):
            pause_extra = 3.8
        elif tok.endswith((".", "!", "?", ";", ":")):
            pause_extra = 3.0
        elif tok.endswith(","):
            pause_extra = 1.6
        weights.append(base_w + pause_extra)

    sum_w = max(1.0, sum(weights))
    usable = max(0.3, dur_total - 0.14)
    cursor = 0.06
    out: List[Dict[str, Any]] = []
    for tok, w_val in zip(tokens, weights):
        slot = usable * (w_val / sum_w)
        # Keep displayed word end tight before the trailing punctuation pause
        speech_frac = 0.72 if tok.endswith((".", "!", "?", "...", ",")) else 0.94
        st = cursor
        en = min(dur_total, st + max(0.08, slot * speech_frac))
        out.append({"word": tok, "start": round(st, 3), "end": round(en, 3)})
        cursor += slot
    return out


# ---------------------------------------------------------------------------
# 4. Broadcast FM Mastering + Sidechain Music Ducking + SFX Mix
# ---------------------------------------------------------------------------
def master_broadcast_audio(
    voice_wav: Path,
    music_mp3: Optional[Path],
    sfx_events: List[Tuple[Path, float, float]],  # (sfx_path, time_s, volume)
    output_m4a: Path,
    duration_s: float,
    music_volume: float = 0.19,
    tail_pad_s: float = 0.40,
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, float]:
    """Apply Broadcast FM Chain:
    highpass=85Hz -> De-Esser 6500Hz -> Presence 3200Hz -> loudnorm=-14 LUFS
    + 0.40s clean ending tail (apad=pad_dur=0.40) + smooth musical fade-out
    + Sidechain-compressed looping music bed + timed SFX hits.
    Returns (output_m4a, final_duration_s).
    """
    final_dur = round(duration_s + tail_pad_s, 3)
    inputs = ["-i", str(voice_wav)]
    filter_parts = [
        # FM Broadcast voice chain + 0.40s clean breathing tail so speech never cuts abruptly
        (
            "[0:a]highpass=f=85,"
            "equalizer=f=6500:t=q:w=2.0:g=-4.5,"
            "equalizer=f=3200:t=q:w=1.4:g=3.2,"
            "acompressor=threshold=-18dB:ratio=3:attack=8:release=120:makeup=2,"
            "loudnorm=I=-14:TP=-1.5:LRA=11,"
            f"apad=pad_dur={tail_pad_s:.2f},atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS,"
            "asplit=2[v_main][v_sc]"
        )
    ]

    mix_labels = ["[v_main]"]
    next_idx = 1

    if music_mp3 and music_mp3.exists() and music_volume > 0.001:
        inputs.extend(["-stream_loop", "-1", "-i", str(music_mp3)])
        fade_out_d = min(0.85, max(0.35, final_dur * 0.12))
        fade_out_start = max(0.0, final_dur - fade_out_d)
        filter_parts.append(
            f"[{next_idx}:a]atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS,"
            f"volume={music_volume:.3f},afade=t=in:st=0:d=0.30,afade=t=out:st={fade_out_start:.3f}:d={fade_out_d:.3f}[bgm_raw]"
        )
        # Sidechain compression ducks music automatically whenever narrator speaks
        filter_parts.append(
            "[bgm_raw][v_sc]sidechaincompress=threshold=0.03:ratio=5.5:attack=15:release=260:makeup=1[bgm_ducked]"
        )
        mix_labels.append("[bgm_ducked]")
        next_idx += 1
    else:
        filter_parts.append("[v_sc]anullsink")

    # Timed SFX cues
    for sfx_path, t_s, vol in sfx_events:
        if not sfx_path.exists() or t_s < 0 or t_s > final_dur:
            continue
        delay_ms = int(t_s * 1000)
        inputs.extend(["-i", str(sfx_path)])
        lbl = f"[sfx{next_idx}]"
        filter_parts.append(
            f"[{next_idx}:a]aresample=48000,volume={vol:.3f},adelay={delay_ms}|{delay_ms}[sfx_d{next_idx}];"
            f"[sfx_d{next_idx}]apad=whole_dur={final_dur:.3f},atrim=0:{final_dur:.3f}{lbl}"
        )
        mix_labels.append(lbl)
        next_idx += 1

    if len(mix_labels) == 1:
        filter_parts.append("[v_main]alimiter=limit=0.95[aout]")
    else:
        n_mix = len(mix_labels)
        joined = "".join(mix_labels)
        filter_parts.append(
            f"{joined}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.95[aout]"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[aout]",
        "-t",
        f"{final_dur:.3f}",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        str(output_m4a),
    ]
    run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c)
    return output_m4a, final_dur


async def generate_narration(
    text: str,
    work_dir: Path,
    voice_engine: str = "edge",
    voice_id: str = "pt-BR-AntonioNeural",
    voice_blend: Optional[Dict[str, float]] = None,
    prefix: str = "narr",
    rate: str = "+8%",
    pitch: str = "+0Hz",
    thermal_limit_c: float = 85.0,
    language: str = "pt_br",
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Unified narration entry point (Gemini Expressive TTS / Kokoro Blend / Edge-TTS -> espeak-ng) + VAD trim.
    Supports custom speed (`rate`, e.g. '+8%', '-6%') and pitch (`pitch`, e.g. '+0Hz', '-8Hz', '+8Hz')
    across Edge-TTS, Gemini TTS (via acting_direction pace/pitch cues), and Kokoro-ONNX!
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_mp3 = work_dir / f"{prefix}_raw.mp3"
    raw_wav = work_dir / f"{prefix}_raw.wav"
    trimmed_wav = work_dir / f"{prefix}_vad.wav"

    clean_rate = normalize_edge_rate(rate)
    clean_pitch = normalize_edge_pitch(pitch)
    eff_lang = _infer_lang_from_voice_id(voice_id, fallback=language)
    known_edge_ids = {v["id"] for v in ALL_EDGE_VOICES}

    def _safe_edge_voice(raw_vid: str) -> str:
        vid = str(raw_vid or "").strip()
        if vid in known_edge_ids or ("Neural" in vid and "-" in vid):
            return vid
        female_hint = vid.lower() in ("kore", "aoede", "zephyr", "leda", "pf_dora", "af_heart")
        return _default_edge_voice_for_lang(eff_lang, female=female_hint)

    words: List[Dict[str, Any]] = []
    source_audio: Path

    if voice_engine == "gemini_tts":
        try:
            from engine.gemini_tts import GEMINI_EXPRESSIVE_VOICES, synthesize_gemini_tts_line

            valid_ids = {v["id"] for v in GEMINI_EXPRESSIVE_VOICES}
            g_voice = voice_id if voice_id in valid_ids else "Puck"
            acting_dir = _build_gemini_acting_direction(clean_rate, clean_pitch, language=eff_lang)
            source_audio, g_dur = await asyncio.to_thread(
                synthesize_gemini_tts_line,
                text,
                raw_wav,
                g_voice,
                acting_dir,
            )
            words = _estimate_word_timestamps(text, g_dur)
        except Exception:
            try:
                fallback_v = _safe_edge_voice(voice_id)
                source_audio, words = await synthesize_edge_tts(
                    text, raw_mp3, voice=fallback_v, rate=clean_rate, pitch=clean_pitch
                )
            except Exception:
                source_audio, words = _synthesize_espeak_fallback(text, raw_wav, language=eff_lang)
    elif voice_engine == "kokoro":
        try:
            if voice_blend:
                eff_blend = voice_blend
            elif voice_id in KOKORO_VOICES:
                eff_blend = {voice_id: 1.0}
            else:
                eff_blend = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}
            source_audio, words = synthesize_kokoro_blended(
                text, raw_wav, eff_blend, speed=_rate_to_kokoro_speed(clean_rate)
            )
        except Exception:
            # Automatic transparent fallback to Edge-TTS if local Kokoro weights not yet fetched
            try:
                fallback_v = _safe_edge_voice(voice_id)
                source_audio, words = await synthesize_edge_tts(
                    text, raw_mp3, voice=fallback_v, rate=clean_rate, pitch=clean_pitch
                )
            except Exception:
                source_audio, words = _synthesize_espeak_fallback(text, raw_wav, language=eff_lang)
    else:
        try:
            edge_v = _safe_edge_voice(voice_id)
            source_audio, words = await synthesize_edge_tts(
                text, raw_mp3, voice=edge_v, rate=clean_rate, pitch=clean_pitch
            )
        except Exception:
            source_audio, words = _synthesize_espeak_fallback(text, raw_wav, language=eff_lang)

    return trim_silence_vad(source_audio, trimmed_wav, words, thermal_limit_c=thermal_limit_c)
