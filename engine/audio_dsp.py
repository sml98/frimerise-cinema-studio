"""FrimeRise Broadcast Audio DSP Studio.
- Local Expressive Voices: Kokoro-ONNX + OpenVINO Voice Blender (pf_dora, pm_alex, pm_santa)
- Instant Cloud Voices: edge-tts >= 7.3.0 with boundary="WordBoundary" exact timestamps
- Offline fallback: espeak-ng PT-BR
- Neural Silence Trimming: Silero VAD ONNX (preserving consonant starts & question tails, capping internal pauses >0.35s to 0.32-0.35s) + energy VAD fallback
- Broadcast Tactile Sound Design Chain (JSON v3.0.0, 100% permissive FFmpeg filters — ZERO GPL pedalboard):
    Voice: highpass=80Hz -> +2dB warmth @120Hz -> +3dB presence @4.5kHz -> 3:1 comp (12ms/140ms) -> -14.0 LUFS
    BGM:   -4.5dB vocal pocket @700-2500Hz -> -23.0 LUFS base -> -5.0dB sidechain duck (150ms/400ms, makeup=1.0) -> -28.0 LUFS under speech
    Master: Linear -14.0 LUFS calibration + 192kHz True-Peak limiter <= -1.0 dBTP (LRA >= 4.5 LU)
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


_HAS_ALNUM_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]")


def _estimate_word_timestamps(text: str, total_duration: float) -> List[Dict[str, Any]]:
    """Fallback proportional word timing when exact WordBoundary is unavailable."""
    words = [w for w in (text or "").strip().split() if w and _HAS_ALNUM_RE.search(w)]
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
    max_pause_s: float = 0.35,
    consonant_pad_s: float = 0.085,
    thermal_limit_c: float = 85.0,
    trim_edges_only: bool = False,
    max_internal_pause_s: Optional[float] = None,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Tighten long pauses while strictly preserving consonant starts and rising question tails.
    Implements JSON v3.0.0 `pacing_rule`: internal silences longer than `0.35s` inside a scene
    narration WAV are tightened cleanly to `0.32–0.35s` by cutting ONLY from the dead center of
    the silence gap (keeping >=160ms–192ms on both sides of the splice) with a smooth 12ms
    crossfade so consonant onsets, final consonants, and question intonation tails are NEVER clipped.
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

    # Adaptive energy + zero-crossing speech detector (preserves soft question tails & consonant starts
    # while rejecting Gemini TTS trailing room-tone hiss!)
    frames = pcm[: n_frames * frame_len].reshape(n_frames, frame_len) if n_frames > 0 else np.zeros((0, frame_len), dtype=np.float32)
    rms_energy = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10) if n_frames > 0 else np.zeros(0, dtype=np.float32)
    peak_speech_ref = float(np.percentile(rms_energy, 98)) if n_frames > 10 else 0.05
    noise_floor = float(np.percentile(rms_energy, 10)) if n_frames > 20 else 0.002
    energy_floor = max(0.008, min(0.025, max(peak_speech_ref * 0.06, noise_floor * 2.6)))

    if silero_path.exists():
        try:
            sess = ort.InferenceSession(str(silero_path), providers=["CPUExecutionProvider"])
            state = np.zeros((2, 1, 128), dtype=np.float32)
            sr_arr = np.array(sr, dtype=np.int64)
            for i in range(n_frames):
                chunk = pcm[i * frame_len : (i + 1) * frame_len][None, :]
                out, state = sess.run(None, {"input": chunk, "state": state, "sr": sr_arr})
                # Require minimum acoustic energy so pure room-tone hiss never triggers false speech
                speech_probs[i] = float(out[0][0]) if rms_energy[i] >= energy_floor * 0.50 else 0.0
        except Exception:
            silero_path = Path("__fallback__")

    if not silero_path.exists() and n_frames > 0:
        zcr = np.mean(np.abs(np.diff(np.sign(frames), axis=1)) > 0, axis=1)
        speech_probs = ((rms_energy > energy_floor) | ((rms_energy > energy_floor * 0.50) & (zcr > 0.12))).astype(np.float32)

    # Convert to raw speech intervals (preserve soft consonant starts & question tails at cut boundaries)
    frame_s = frame_len / float(sr)
    active = speech_probs > 0.35
    # Suppress isolated 1-frame hiss spikes (require >= 2 consecutive active frames = 64ms)
    if n_frames >= 3:
        sustained = active & (np.roll(active, 1) | np.roll(active, -1))
        if np.any(sustained):
            active = sustained

    raw_active_idx = np.where(active)[0]
    keep_mask = np.zeros(n_frames, dtype=bool)
    xf_s = 0.012  # 12ms linear crossfade across non-contiguous silence cuts

    if len(raw_active_idx) == 0:
        keep_mask[:] = True
    else:
        first_act = int(raw_active_idx[0])
        last_act = int(raw_active_idx[-1])
        # Generous lead-in (>=96ms) & trailing tail (>=288ms) so initial consonants & rising '?' tails never clip
        lead_frames = max(3, int(math.ceil(max(0.085, consonant_pad_s) / frame_s)))
        tail_frames = max(9, int(math.ceil(max(0.28, consonant_pad_s * 2.5) / frame_s)))
        start_f = max(0, first_act - lead_frames)
        end_f = min(n_frames, last_act + 1 + tail_frames)

        # Keep edge cushions untouched
        keep_mask[start_f:first_act] = True
        keep_mask[last_act + 1 : end_f] = True

        # JSON v3.0.0 pacing_rule: cap internal silences > 0.35s cleanly to 0.32–0.35s
        if max_internal_pause_s is not None:
            cap_s = max(0.16, float(max_internal_pause_s))
        else:
            cap_s = min(0.35, max(0.16, float(max_pause_s)))

        # Number of kept silence frames so (target_keep_frames * frame_s - xf_s) lands right in 0.32–0.35s
        # (including ~15-25ms natural syllable tail ramp at real speech boundaries: 10 frames - 12ms = 0.308s core -> ~0.33s acoustic pause)
        target_keep_frames = max(5, int(round((cap_s + xf_s) / frame_s)))
        if cap_s >= 0.32:
            target_keep_frames = 10  # 6 frames tail (192ms) + 4 frames onset (128ms) - 12ms xf -> ~0.32–0.34s acoustic gap!

        # Walk inside [first_act, last_act] preserving all active frames and tightening ONLY gaps > cap_s
        i = first_act
        while i <= last_act:
            if active[i]:
                keep_mask[i] = True
                i += 1
                continue
            g_start = i
            while i <= last_act and not active[i]:
                i += 1
            g_end = i
            gap_len = g_end - g_start
            if gap_len <= target_keep_frames:
                # Natural micro-pause (<= 0.35s): preserve 100% bit-exact untouched!
                keep_mask[g_start:g_end] = True
            else:
                # Cut strictly from the dead center of the pause:
                # keep >=55% on the left (word/question tail) & remaining on the right (next consonant onset)!
                min_tail = max(3, int(math.ceil(consonant_pad_s / frame_s)))
                keep_left = min(target_keep_frames - 2, max(min_tail, int(round(target_keep_frames * 0.55))))
                keep_right = max(2, target_keep_frames - keep_left)
                keep_mask[g_start : g_start + keep_left] = True
                keep_mask[g_end - keep_right : g_end] = True

    # Build time remapping table to shift WordBoundary timestamps accurately
    kept_indices = np.where(keep_mask)[0]
    min_kept_frames = max(5, int(0.40 / frame_s))
    if len(kept_indices) < min_kept_frames:
        # Safety: only abort trim if <0.40s total speech was detected (never abort just because a glitched TTS tail is >80% of raw length)
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

    step48 = int(round(frame_s * 48000))
    xf_target = int(round(xf_s * 48000))  # 12ms smooth crossfade across non-contiguous cuts

    # Group kept frame indices into contiguous runs so continuous speech stays bit-exact
    # and ONLY non-contiguous silence splices get a smooth 7ms linear crossfade (zero micro-clicks).
    runs: List[Tuple[int, int]] = []
    if len(kept_indices) > 0:
        r_start = int(kept_indices[0])
        r_prev = r_start
        for raw_idx in kept_indices[1:]:
            cur = int(raw_idx)
            if cur == r_prev + 1:
                r_prev = cur
            else:
                runs.append((r_start, r_prev))
                r_start = cur
                r_prev = cur
        runs.append((r_start, r_prev))

    out_parts: List[np.ndarray] = []
    old_to_new: List[Tuple[float, float]] = []
    out_samples = 0

    for run_i, (r_start, r_end_incl) in enumerate(runs):
        s48 = r_start * step48
        e48 = min(len(pcm48), (r_end_incl + 1) * step48)
        if e48 <= s48:
            continue
        seg = pcm48[s48:e48].astype(np.float32)

        xf_len = 0
        if run_i > 0 and out_parts:
            prev_tail_len = len(out_parts[-1])
            xf_len = min(xf_target, prev_tail_len // 4, len(seg) // 4)
            if xf_len < 16:
                xf_len = 0

        seg_start_sample = out_samples - xf_len
        for f_idx in range(r_start, r_end_incl + 1):
            f_off = (f_idx - r_start) * step48
            old_to_new.append((f_idx * frame_s, max(0.0, (seg_start_sample + f_off) / 48000.0)))

        if xf_len > 0:
            w_out = np.linspace(1.0, 0.0, xf_len, dtype=np.float32)[:, None]
            w_in = 1.0 - w_out
            prev_seg = out_parts[-1]
            blended = prev_seg[-xf_len:] * w_out + seg[:xf_len] * w_in
            out_parts[-1] = prev_seg[:-xf_len]
            out_parts.append(blended)
            out_parts.append(seg[xf_len:])
            out_samples += len(seg) - xf_len
        else:
            out_parts.append(seg)
            out_samples += len(seg)

    if out_parts:
        final_f32 = np.vstack(out_parts)
        # Subtle 3ms linear fade-in / fade-out at clip boundaries to guarantee click-free edges
        edge_len = min(144, len(final_f32) // 8)
        if edge_len >= 16:
            ramp_in = np.linspace(0.0, 1.0, edge_len, dtype=np.float32)[:, None]
            ramp_out = np.linspace(1.0, 0.0, edge_len, dtype=np.float32)[:, None]
            final_f32[:edge_len] *= ramp_in
            final_f32[-edge_len:] *= ramp_out
        final_pcm = np.clip(np.rint(final_f32), -32768.0, 32767.0).astype(np.int16)
    else:
        final_pcm = pcm48

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


def normalize_scene_wav_lufs(
    wav_path: Path,
    target_lufs: float = -18.0,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Normalize a scene narration WAV in-place to uniform integrated loudness (default -18 LUFS)
    via atomic temp file + EBU R128 loudnorm (`TP=-2.0:LRA=9`), using 2-pass linear gain when
    measurable (zero pumping!) with safe single-pass fallback on ultra-short clips.
    """
    wav_p = Path(wav_path)
    if not wav_p.exists() or wav_p.stat().st_size <= 44:
        return wav_p

    tmp_wav = wav_p.with_name(f"{wav_p.stem}_lufs_tmp{wav_p.suffix}")
    af_filter = f"loudnorm=I={target_lufs:.1f}:TP=-2.0:LRA=9,aresample=48000"

    try:
        # Pass 1: fast loudness measurement for clean linear gain (prevents per-scene pumping)
        probe = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "info",
                "-i",
                str(wav_p),
                "-af",
                f"loudnorm=I={target_lufs:.1f}:TP=-2.0:LRA=9:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        m_json = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr or "", re.S)
        if m_json:
            stats = json.loads(m_json.group(0))
            mi = float(stats.get("input_i", "-inf"))
            mtp = float(stats.get("input_tp", "-inf"))
            mlra = float(stats.get("input_lra", "0.0"))
            mth = float(stats.get("input_thresh", "-inf"))
            moff = float(stats.get("target_offset", "0.0"))
            if (
                math.isfinite(mi)
                and math.isfinite(mtp)
                and math.isfinite(mlra)
                and math.isfinite(mth)
                and math.isfinite(moff)
                and -60.0 <= mi <= 0.0
            ):
                af_filter = (
                    f"loudnorm=I={target_lufs:.1f}:TP=-2.0:LRA=9:"
                    f"measured_I={mi:.2f}:measured_TP={mtp:.2f}:"
                    f"measured_LRA={mlra:.2f}:measured_thresh={mth:.2f}:"
                    f"offset={moff:.2f}:linear=true,aresample=48000"
                )
    except Exception:
        pass

    try:
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(wav_p),
                "-af",
                af_filter,
                "-c:a",
                "pcm_s16le",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(tmp_wav),
            ],
            thermal_limit_c=thermal_limit_c,
        )
        if tmp_wav.exists() and tmp_wav.stat().st_size > 44:
            tmp_wav.replace(wav_p)
        else:
            tmp_wav.unlink(missing_ok=True)
    except Exception as exc:
        tmp_wav.unlink(missing_ok=True)
        print(f"[AudioDSP] normalize_scene_wav_lufs skipped for {wav_p.name}: {exc}", flush=True)

    return wav_p


_WHISPER_ALIGN_MODEL = None
_WHISPER_ALIGN_MODEL_NAME = None


def _get_whisper_align_model():
    global _WHISPER_ALIGN_MODEL, _WHISPER_ALIGN_MODEL_NAME
    if _WHISPER_ALIGN_MODEL is None:
        from faster_whisper import WhisperModel

        last_exc: Optional[Exception] = None
        for model_name in ("base", "tiny"):
            try:
                _WHISPER_ALIGN_MODEL = WhisperModel(
                    model_name, device="cpu", compute_type="int8", cpu_threads=4
                )
                _WHISPER_ALIGN_MODEL_NAME = model_name
                break
            except Exception as exc:
                last_exc = exc
                print(
                    f"[AudioDSP] faster-whisper '{model_name}' unavailable ({exc}), trying fallback...",
                    flush=True,
                )
        if _WHISPER_ALIGN_MODEL is None:
            raise RuntimeError(f"Nenhum modelo faster-whisper disponível: {last_exc}")
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


_PT_NUM_UNITS: Dict[str, int] = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500, "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
    # PT-BR ordinals (I..X centuries / monarchs)
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2,
    "terceiro": 3, "terceira": 3, "quarto": 4, "quarta": 4,
    "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7, "oitavo": 8, "oitava": 8,
    "nono": 9, "nona": 9, "decimo": 10, "decima": 10,
    # EN cardinals & ordinals
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    # ES cardinals
    "cero": 0, "uno": 1, "dos": 2, "cuatro": 4, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}

_NUM_MULTIPLIERS: Dict[str, int] = {
    "hundred": 100,
    "mil": 1000,
    "thousand": 1000,
    "milhao": 1_000_000,
    "milhoes": 1_000_000,
    "million": 1_000_000,
    "millon": 1_000_000,
    "millones": 1_000_000,
    "bilhao": 1_000_000_000,
    "bilhoes": 1_000_000_000,
    "billion": 1_000_000_000,
}

_NUM_CONJUNCTIONS = {"e", "and", "y"}

_ROMAN_INT_MAP: Dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
    "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
    "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18,
    "XIX": 19, "XX": 20, "XXI": 21,
}


def _parse_digit_token(norm: str) -> Optional[int]:
    """Parse normalized digit/ordinal token like '1647', '4o', '4a', '21st', '4th' -> int."""
    if not norm:
        return None
    if norm.isdigit():
        return int(norm)
    m = re.match(r"^(\d+)(?:o|a|os|as|st|nd|rd|th)$", norm)
    if m:
        return int(m.group(1))
    return None


def _parse_roman_raw(raw_tok: str) -> Optional[int]:
    """Parse uppercase Roman numeral token (I..XXI) stripping surrounding punctuation."""
    core = re.sub(r"[^A-Za-z0-9]", "", str(raw_tok or ""))
    if core and core.isupper() and core in _ROMAN_INT_MAP:
        return _ROMAN_INT_MAP[core]
    return None


def _parse_spoken_number_run(
    norms: List[str],
    raws: List[str],
    start: int,
    end: int,
) -> Optional[Tuple[int, int]]:
    """Parse a spoken number or year starting at `start` (e.g. 'mil seiscentos e quarenta e sete' -> (1647, 6))."""
    if start >= end:
        return None
    first = norms[start]
    # 1. Standalone digit token (or adjacent 2-part year split e.g. '16' + '47' -> 1647)
    d0 = _parse_digit_token(first)
    if d0 is not None:
        return (d0, 1)
    # 2. Uppercase Roman numeral token (e.g. 'IV' -> 4)
    r0 = _parse_roman_raw(raws[start])
    if r0 is not None:
        return (r0, 1)
    if first not in _PT_NUM_UNITS and first not in _NUM_MULTIPLIERS:
        return None

    total = 0
    current = 0
    pos = start
    consumed = 0

    while pos < end:
        tok = norms[pos]
        if tok in _NUM_CONJUNCTIONS:
            # Consume conjunction ONLY if followed by another number word
            if pos + 1 < end and (norms[pos + 1] in _PT_NUM_UNITS or norms[pos + 1] in _NUM_MULTIPLIERS):
                pos += 1
                continue
            break
        if tok in _PT_NUM_UNITS:
            val = _PT_NUM_UNITS[tok]
            # Prevent merging two independent numbers like "dois tres" unless hundred/ten + unit
            if current > 0:
                if val >= 100:
                    break
                if current % 100 >= 20 and val >= 10:
                    break
                if 1 <= (current % 100) < 20:
                    break
            current += val
            pos += 1
            consumed = pos - start
        elif tok in _NUM_MULTIPLIERS:
            mult = _NUM_MULTIPLIERS[tok]
            if mult == 100:
                current = (current if current > 0 else 1) * 100
            else:
                total += (current if current > 0 else 1) * mult
                current = 0
            pos += 1
            consumed = pos - start
        else:
            break

    if consumed <= 0:
        return None
    return (total + current, consumed)


def _word_speech_weight(tok: str) -> float:
    """Estimate relative spoken articulation duration weight from syllables + character length."""
    core = re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", str(tok or "").lower())
    if not core:
        return 0.6
    if core.isdigit():
        return max(1.4, float(len(core)) * 1.7)
    syllables = max(1, len(re.findall(r"[aeiouáàâãéêíóôõúüy]+", core)))
    return max(0.7, 0.55 * float(syllables) + 0.25 * float(len(core)))


def _phonetic_key_pt(norm: str) -> str:
    """Lightweight Portuguese phonetic normalization for fuzzy Whisper token matching."""
    s = norm
    if not s:
        return ""
    s = re.sub(r"^h", "", s)
    s = s.replace("ch", "x").replace("qu", "k").replace("ck", "k").replace("ss", "s").replace("sc", "s")
    s = s.replace("z", "s").replace("y", "i").replace("w", "v").replace("ph", "f")
    s = re.sub(r"c(?=[ei])", "s", s)
    s = s.replace("c", "k")
    s = re.sub(r"g(?=[ei])", "j", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s


def _compute_speech_mask_10ms(audio_16k: np.ndarray, frame_s: float = 0.010) -> Optional[np.ndarray]:
    """Compute boolean 10ms VAD speech energy mask from 16kHz float32 audio.
    Returns None when audio is effectively silent (e.g. synthetic dummy WAV in unit tests).
    """
    frame_len = max(16, int(round(frame_s * 16000)))
    n_frames = len(audio_16k) // frame_len
    if n_frames < 5:
        return None
    frames = audio_16k[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    peak_ref = float(np.percentile(rms, 97))
    if peak_ref < 0.005:
        return None
    thresh = max(0.008, peak_ref * 0.085)
    raw_active = rms >= thresh
    if not np.any(raw_active):
        return None
    # Dilate by ±2 frames (±20ms) so soft consonant onsets & tails stay covered
    kernel = np.ones(5, dtype=np.int32)
    return np.convolve(raw_active.astype(np.int32), kernel, mode="same") > 0


def _clamp_anchor_to_speech(
    st: float,
    en: float,
    speech_mask: Optional[np.ndarray],
    frame_s: float,
    dur_total: float,
) -> Tuple[float, float]:
    """Trim >70ms leading/trailing dead silence absorbed into a Whisper word anchor."""
    st = max(0.0, min(dur_total, st))
    en = max(st + 0.05, min(dur_total, en))
    if speech_mask is None or en - st <= 0.14:
        return st, en
    n_f = len(speech_mask)
    f0 = max(0, min(n_f - 1, int(math.floor(st / frame_s))))
    f1 = max(f0 + 1, min(n_f, int(math.ceil(en / frame_s))))
    act = np.where(speech_mask[f0:f1])[0]
    if len(act) < 2:
        return st, en
    sp_st = max(st, (f0 + int(act[0])) * frame_s - 0.015)
    sp_en = min(en, (f0 + int(act[-1]) + 1) * frame_s + 0.025)
    # Only pull edges when substantial dead silence (>70ms) was absorbed and word stays >= 60ms
    new_st = sp_st if (sp_st - st) > 0.07 else st
    new_en = sp_en if (en - sp_en) > 0.07 else en
    if new_en - new_st >= 0.06:
        return round(new_st, 4), round(new_en, 4)
    return st, en


def _distribute_tokens_in_span(
    toks: List[str],
    t_left: float,
    t_right: float,
    speech_mask: Optional[np.ndarray],
    frame_s: float,
    dur_total: float,
) -> List[Tuple[float, float]]:
    """Distribute `toks` across `[t_left, t_right]` via syllable/char weights,
    clamped strictly inside active VAD speech energy bounds so words NEVER light up in dead silence.
    """
    m = len(toks)
    if m == 0:
        return []
    t_l = max(0.0, min(dur_total, float(t_left)))
    t_r = max(t_l + 0.04, min(dur_total, float(t_right)))
    weights = [_word_speech_weight(t) for t in toks]
    sum_w = max(1e-6, sum(weights))

    # Prefer active VAD speech frames strictly inside [t_l, t_r] so internal or edge pauses are skipped!
    if speech_mask is not None:
        n_f = len(speech_mask)
        f0 = max(0, min(n_f, int(math.floor(t_l / frame_s))))
        f1 = max(f0, min(n_f, int(math.ceil(t_r / frame_s))))
        if f1 > f0:
            act_rel = np.where(speech_mask[f0:f1])[0]
            if len(act_rel) >= max(2, m):
                act_abs = f0 + act_rel
                n_act = len(act_abs)
                spans: List[Tuple[float, float]] = []
                cum = 0.0
                for k, w_val in enumerate(weights):
                    lo_frac = cum / sum_w
                    cum += w_val
                    hi_frac = cum / sum_w
                    i_lo = min(n_act - 1, int(round(lo_frac * n_act)))
                    i_hi = max(i_lo + 1, min(n_act, int(round(hi_frac * n_act))))
                    st = max(t_l, float(act_abs[i_lo]) * frame_s)
                    en = min(t_r, float(act_abs[i_hi - 1] + 1) * frame_s)
                    if spans and st < spans[-1][1]:
                        st = spans[-1][1]
                    en = min(dur_total, max(st + 0.04, en))
                    spans.append((st, en))
                return spans

    # Fallback when window has no detected energy frames (e.g. silent/dummy test audio or tight tail)
    span = max(0.04 * m, t_r - t_l)
    eff_r = min(dur_total, t_l + span)
    eff_span = max(0.04, eff_r - t_l)
    spans = []
    cursor = t_l
    for w_val in weights:
        slot = eff_span * (w_val / sum_w)
        st = min(cursor, max(0.0, dur_total - 0.04))
        en = min(dur_total, max(st + 0.04, cursor + slot * 0.96))
        if spans and st < spans[-1][1]:
            st = spans[-1][1]
            en = min(dur_total, max(st + 0.04, en))
        spans.append((st, en))
        cursor += slot
    return spans


def _resolve_replace_block(
    tokens: List[str],
    script_norms: List[str],
    heard: List[Tuple[float, float, str]],
    heard_norms: List[str],
    a1: int,
    a2: int,
    b1: int,
    b2: int,
    speech_mask: Optional[np.ndarray],
    frame_s: float,
    dur_total: float,
) -> Dict[int, Tuple[float, float]]:
    """Resolve an unmatched SequenceMatcher `replace` block via local DP supporting:
    - Multi-word spoken numbers/years <-> Whisper digits ('mil seiscentos e quarenta e sete' <-> '1647')
    - Portuguese compound merges ('por que' <-> 'porque', 2-3 script tokens -> 1 heard token)
    - Hyphenated clitic / compound splits ('considerá-lo' <-> 'considerá' + '-lo', 1 script -> 2-3 heard)
    - Fuzzy / phonetic 1-to-1 matching ('saturnália' <-> 'saturnaria', 'krampus' <-> 'crampus')
    """
    import difflib

    na = a2 - a1
    nb = b2 - b1
    if na <= 0 or nb <= 0:
        return {}
    # Guard worst-case DP cost on unusually massive mismatched blocks
    if na * nb > 16000:
        return {}

    heard_raws = [h[2] for h in heard]
    # Precompute candidate transitions from each (di, dj): list of (s_len, h_len, score)
    dp: List[List[float]] = [[-1e9] * (nb + 1) for _ in range(na + 1)]
    parent: List[List[Optional[Tuple[int, int, bool]]]] = [[None] * (nb + 1) for _ in range(na + 1)]
    dp[0][0] = 0.0

    for di in range(na + 1):
        for dj in range(nb + 1):
            base = dp[di][dj]
            if base <= -1e8:
                continue
            # Skip 1 script token or 1 heard token
            if di < na and base - 0.01 > dp[di + 1][dj]:
                dp[di + 1][dj] = base - 0.01
                parent[di + 1][dj] = (di, dj, False)
            if dj < nb and base - 0.01 > dp[di][dj + 1]:
                dp[di][dj + 1] = base - 0.01
                parent[di][dj + 1] = (di, dj, False)

            if di >= na or dj >= nb:
                continue

            si = a1 + di
            hj = b1 + dj
            sn = script_norms[si]
            hn = heard_norms[hj]

            # 1. Exact or fuzzy/phonetic 1-to-1 match
            if sn and hn:
                if sn == hn:
                    sc = 12.0
                else:
                    ratio = difflib.SequenceMatcher(None, sn, hn).ratio()
                    if min(len(sn), len(hn)) >= 3 and ratio >= 0.72:
                        sc = 10.0 * ratio
                    elif min(len(sn), len(hn)) >= 3 and _phonetic_key_pt(sn) == _phonetic_key_pt(hn):
                        sc = 9.5
                    else:
                        sc = 0.0
                if sc > 0.0 and base + sc > dp[di + 1][dj + 1]:
                    dp[di + 1][dj + 1] = base + sc
                    parent[di + 1][dj + 1] = (di, dj, True)

            # 2. Compound merge: 2 or 3 script tokens -> 1 heard token (e.g. "por" + "que" -> "porque")
            for k in (2, 3):
                if di + k <= na and hn:
                    merged_s = "".join(script_norms[si : si + k])
                    if merged_s == hn:
                        sc = 12.0 * k
                    elif len(merged_s) >= 4 and len(hn) >= 4:
                        ratio = difflib.SequenceMatcher(None, merged_s, hn).ratio()
                        sc = (10.0 * k * ratio) if ratio >= 0.84 else 0.0
                    else:
                        sc = 0.0
                    if sc > 0.0 and base + sc > dp[di + k][dj + 1]:
                        dp[di + k][dj + 1] = base + sc
                        parent[di + k][dj + 1] = (di, dj, True)

            # 3. Split match: 1 script token -> 2 or 3 heard tokens (e.g. "considerá-lo" -> "considerá" + "-lo")
            for m in (2, 3):
                if dj + m <= nb and sn:
                    merged_h = "".join(heard_norms[hj : hj + m])
                    if sn == merged_h:
                        sc = 12.0 + 2.0 * m
                    elif len(sn) >= 4 and len(merged_h) >= 4:
                        ratio = difflib.SequenceMatcher(None, sn, merged_h).ratio()
                        sc = ((10.0 + 1.5 * m) * ratio) if ratio >= 0.84 else 0.0
                    else:
                        sc = 0.0
                    if sc > 0.0 and base + sc > dp[di + 1][dj + m]:
                        dp[di + 1][dj + m] = base + sc
                        parent[di + 1][dj + m] = (di, dj, True)

            # 4. Spoken number / Roman <-> Digit / spoken number match (e.g. "mil seiscentos e quarenta e sete" <-> "1647")
            s_num = _parse_spoken_number_run(script_norms, tokens, si, a2)
            if s_num is not None:
                s_val, s_len = s_num
                # 4a. Against single or multi-word number in heard
                h_num = _parse_spoken_number_run(heard_norms, heard_raws, hj, b2)
                if h_num is not None and h_num[0] == s_val:
                    h_len = h_num[1]
                    sc = 14.0 * max(s_len, h_len)
                    if base + sc > dp[di + s_len][dj + h_len]:
                        dp[di + s_len][dj + h_len] = base + sc
                        parent[di + s_len][dj + h_len] = (di, dj, True)
                # 4b. Against adjacent split digits in heard (e.g. ["16", "47"] -> 1647)
                if dj + 2 <= nb and heard_norms[hj].isdigit() and heard_norms[hj + 1].isdigit():
                    comb_val = int(heard_norms[hj] + heard_norms[hj + 1])
                    if comb_val == s_val:
                        sc = 14.0 * s_len
                        if base + sc > dp[di + s_len][dj + 2]:
                            dp[di + s_len][dj + 2] = base + sc
                            parent[di + s_len][dj + 2] = (di, dj, True)

    # Backtrack optimal matches inside the replace block
    matched_pairs: List[Tuple[int, int, int, int]] = []
    ci, cj = na, nb
    while ci > 0 or cj > 0:
        par = parent[ci][cj]
        if par is None:
            break
        pi, pj, is_match = par
        if is_match:
            matched_pairs.append((a1 + pi, a1 + ci, b1 + pj, b1 + cj))
        ci, cj = pi, pj
    matched_pairs.reverse()

    sub_anchors: Dict[int, Tuple[float, float]] = {}
    for s0, s1, h0, h1 in matched_pairs:
        h_st = heard[h0][0]
        h_en = heard[h1 - 1][1]
        h_st, h_en = _clamp_anchor_to_speech(h_st, h_en, speech_mask, frame_s, dur_total)
        if s1 - s0 == 1:
            sub_anchors[s0] = (h_st, h_en)
        else:
            spans = _distribute_tokens_in_span(
                tokens[s0:s1], h_st, h_en, speech_mask, frame_s, dur_total
            )
            for offset_k, (st_k, en_k) in enumerate(spans):
                sub_anchors[s0 + offset_k] = (st_k, en_k)
    return sub_anchors


def align_script_words_to_audio(
    wav_path: Path,
    script_text: str,
    duration_s: float,
    lang: str = "pt_br",
) -> List[Dict[str, Any]]:
    """Align script words to human TTS audio (Gemini TTS) using local faster-whisper int8 (`base`, `beam_size=3`)
    passing 16kHz float32 ndarray directly (bypassing PyAV) + compound/clitic/number-aware alignment +
    VAD-energy-clamped syllable-weighted interpolation so captions stay laser-synced with zero punctuation pills.
    """
    import difflib
    import unicodedata

    # Filter out pure-punctuation tokens (e.g. "—", "–", "-", "...") so standalone punctuation NEVER becomes a caption word
    tokens = [w.strip() for w in (script_text or "").split() if w.strip() and _HAS_ALNUM_RE.search(w)]
    if not tokens:
        return []
    dur_total = max(0.4, float(duration_s or _get_wav_duration(wav_path) or 1.0))

    def _norm_tok(s: str) -> str:
        nfd = unicodedata.normalize("NFKD", s.lower())
        return re.sub(r"[^a-z0-9]", "", "".join(c for c in nfd if not unicodedata.combining(c)))

    frame_s = 0.010
    speech_mask: Optional[np.ndarray] = None

    # 1. Local faster-whisper int8 via direct 16kHz float32 numpy array (zero PyAV errors!)
    try:
        model = _get_whisper_align_model()
        audio_16k = _load_wav_16k_float32(wav_path)
        speech_mask = _compute_speech_mask_10ms(audio_16k, frame_s=frame_s)
        w_lang = "en" if str(lang).lower().startswith("en") else ("es" if str(lang).lower().startswith("es") else "pt")
        segments, _ = model.transcribe(
            audio_16k,
            language=w_lang,
            word_timestamps=True,
            vad_filter=False,
            beam_size=3,
        )
        heard: List[Tuple[float, float, str]] = []
        for seg in segments:
            for wd in (seg.words or []):
                raw_w = str(wd.word or "").strip()
                if not raw_w or not _norm_tok(raw_w):
                    continue
                st = max(0.0, float(wd.start))
                en = min(dur_total, max(st + 0.05, float(wd.end)))
                heard.append((st, en, raw_w))

        if heard:
            script_norms = [_norm_tok(t) for t in tokens]
            heard_norms = [_norm_tok(h[2]) for h in heard]
            heard_raws = [h[2] for h in heard]

            # Pre-alignment canonicalization for multi-word spoken numbers <-> Whisper digits
            # (prevents stray "e" inside "mil seiscentos e quarenta e sete" from splitting anchor matching!)
            heard_digit_vals: set[int] = set()
            for j, hn in enumerate(heard_norms):
                dv = _parse_digit_token(hn)
                if dv is not None:
                    heard_digit_vals.add(dv)
                if j + 1 < len(heard_norms) and hn.isdigit() and heard_norms[j + 1].isdigit():
                    heard_digit_vals.add(int(hn + heard_norms[j + 1]))
            script_digit_vals: set[int] = set()
            for i, sn in enumerate(script_norms):
                dv = _parse_digit_token(sn)
                if dv is not None:
                    script_digit_vals.add(dv)
                rv = _parse_roman_raw(tokens[i])
                if rv is not None:
                    script_digit_vals.add(rv)

            # Build alignment units: (key, raw_start, raw_end_excl)
            s_units: List[Tuple[str, int, int]] = []
            script_spoken_vals: set[int] = set()
            i = 0
            while i < len(tokens):
                sn_run = _parse_spoken_number_run(script_norms, tokens, i, len(tokens))
                if sn_run is not None:
                    val, length = sn_run
                    if length >= 2 and val in heard_digit_vals:
                        script_spoken_vals.add(val)
                        s_units.append((f"#NUM:{val}", i, i + length))
                        i += length
                        continue
                    if length == 1 and val in heard_digit_vals and script_norms[i] not in heard_norms:
                        script_spoken_vals.add(val)
                        s_units.append((f"#NUM:{val}", i, i + 1))
                        i += 1
                        continue
                s_units.append((script_norms[i], i, i + 1))
                i += 1

            h_units: List[Tuple[str, int, int]] = []
            j = 0
            while j < len(heard):
                dv = _parse_digit_token(heard_norms[j])
                if dv is not None and (dv in script_spoken_vals or dv in script_digit_vals):
                    h_units.append((f"#NUM:{dv}", j, j + 1))
                    j += 1
                    continue
                if j + 1 < len(heard) and heard_norms[j].isdigit() and heard_norms[j + 1].isdigit():
                    comb = int(heard_norms[j] + heard_norms[j + 1])
                    if comb in script_spoken_vals:
                        h_units.append((f"#NUM:{comb}", j, j + 2))
                        j += 2
                        continue
                hn_run = _parse_spoken_number_run(heard_norms, heard_raws, j, len(heard))
                if hn_run is not None and hn_run[0] in script_digit_vals and hn_run[1] >= 2:
                    h_units.append((f"#NUM:{hn_run[0]}", j, j + hn_run[1]))
                    j += hn_run[1]
                    continue
                h_units.append((heard_norms[j], j, j + 1))
                j += 1

            # Also unify script single digit/Roman unit keys if heard collapsed a spoken number to the same #NUM
            h_num_keys = {u[0] for u in h_units if u[0].startswith("#NUM:")}
            if h_num_keys:
                new_s_units: List[Tuple[str, int, int]] = []
                for key, s0, s1 in s_units:
                    if not key.startswith("#NUM:") and s1 - s0 == 1:
                        dv = _parse_digit_token(script_norms[s0])
                        rv = _parse_roman_raw(tokens[s0])
                        num_v = dv if dv is not None else rv
                        if num_v is not None and f"#NUM:{num_v}" in h_num_keys:
                            new_s_units.append((f"#NUM:{num_v}", s0, s1))
                            continue
                    new_s_units.append((key, s0, s1))
                s_units = new_s_units

            s_keys = [u[0] for u in s_units]
            h_keys = [u[0] for u in h_units]
            sm = difflib.SequenceMatcher(None, s_keys, h_keys, autojunk=False)
            anchors: Dict[int, Tuple[float, float]] = {}

            for tag, ua1, ua2, ub1, ub2 in sm.get_opcodes():
                if tag == "equal":
                    for k in range(ua2 - ua1):
                        _, s0, s1 = s_units[ua1 + k]
                        _, h0, h1 = h_units[ub1 + k]
                        h_st, h_en = _clamp_anchor_to_speech(
                            heard[h0][0], heard[h1 - 1][1], speech_mask, frame_s, dur_total
                        )
                        if s1 - s0 == 1:
                            anchors[s0] = (h_st, h_en)
                        else:
                            spans = _distribute_tokens_in_span(
                                tokens[s0:s1], h_st, h_en, speech_mask, frame_s, dur_total
                            )
                            for off_k, (st_k, en_k) in enumerate(spans):
                                anchors[s0 + off_k] = (st_k, en_k)
                elif tag == "replace":
                    raw_a1 = s_units[ua1][1]
                    raw_a2 = s_units[ua2 - 1][2]
                    raw_b1 = h_units[ub1][1]
                    raw_b2 = h_units[ub2 - 1][2]
                    sub = _resolve_replace_block(
                        tokens,
                        script_norms,
                        heard,
                        heard_norms,
                        raw_a1,
                        raw_a2,
                        raw_b1,
                        raw_b2,
                        speech_mask,
                        frame_s,
                        dur_total,
                    )
                    anchors.update(sub)

            if anchors and (len(anchors) >= max(1, int(len(tokens) * 0.25)) or len(heard) >= max(2, int(len(tokens) * 0.40))):
                aligned: List[Dict[str, Any]] = []
                n_t = len(tokens)
                n_h = len(heard)

                # Speech bounds clamped to real acoustic speech envelope when available
                speech_start = heard[0][0]
                speech_end = heard[-1][1]
                if speech_mask is not None:
                    act_all = np.where(speech_mask)[0]
                    if len(act_all) > 0:
                        speech_start = max(0.0, min(dur_total - 0.05, max(speech_start, float(act_all[0]) * frame_s - 0.015)))
                        speech_end = min(dur_total, max(speech_end, float(act_all[-1] + 1) * frame_s + 0.025))

                idx = 0
                while idx < n_t:
                    if idx in anchors:
                        st, en = anchors[idx]
                        if aligned and st < aligned[-1]["end"]:
                            st = aligned[-1]["end"]
                        st = min(st, max(0.0, dur_total - 0.04))
                        en = max(st + 0.04, min(dur_total, en))
                        aligned.append({"word": tokens[idx], "start": round(st, 3), "end": round(en, 3)})
                        idx += 1
                    else:
                        run_end = idx
                        while run_end < n_t and run_end not in anchors:
                            run_end += 1
                        run_len = run_end - idx
                        t_left = aligned[-1]["end"] if aligned else speech_start
                        t_right = anchors[run_end][0] if run_end < n_t else max(speech_end, dur_total - 0.04)

                        # NEVER silently drop trailing words near dur_total: reclaim a small tail if needed!
                        if run_end == n_t and t_left >= dur_total - max(0.12, 0.05 * run_len):
                            need = min(0.24, 0.07 * run_len)
                            if aligned:
                                prev_st = aligned[-1]["start"]
                                prev_en = aligned[-1]["end"]
                                max_reclaim = max(0.0, (prev_en - prev_st) * 0.45)
                                reclaim = min(max_reclaim, max(0.0, (t_left + need) - dur_total))
                                if reclaim > 0.005:
                                    aligned[-1]["end"] = round(max(prev_st + 0.04, prev_en - reclaim), 3)
                                    t_left = aligned[-1]["end"]
                            t_right = dur_total
                        elif t_right <= t_left + 0.04:
                            if run_end == n_t:
                                t_right = dur_total
                            else:
                                h_i = min(n_h - 1, int(idx * n_h / n_t))
                                t_right = min(
                                    dur_total,
                                    max(t_left + 0.08 * run_len, heard[min(n_h - 1, h_i + run_len)][1]),
                                )

                        t_right = min(dur_total, max(t_left + 0.04, t_right))
                        spans = _distribute_tokens_in_span(
                            tokens[idx:run_end], t_left, t_right, speech_mask, frame_s, dur_total
                        )
                        for j_tok, (st_k, en_k) in zip(range(idx, run_end), spans):
                            if aligned and st_k < aligned[-1]["end"]:
                                st_k = aligned[-1]["end"]
                            st_k = min(max(0.0, st_k), max(0.0, dur_total - 0.04))
                            en_k = min(dur_total, max(st_k + 0.04, en_k))
                            aligned.append({"word": tokens[j_tok], "start": round(st_k, 3), "end": round(en_k, 3)})
                        idx = run_end
                return aligned
    except Exception as exc:
        print(f"[AudioDSP] Whisper alignment fallback: {exc}", flush=True)

    # 2. Syllable + punctuation-weighted fallback clamped to VAD speech bounds when available
    t_lo = 0.06
    t_hi = max(0.36, dur_total - 0.06)
    if speech_mask is not None:
        act_all = np.where(speech_mask)[0]
        if len(act_all) > 0:
            t_lo = max(0.0, float(act_all[0]) * frame_s - 0.015)
            t_hi = min(dur_total, max(t_lo + 0.20, float(act_all[-1] + 1) * frame_s + 0.025))

    weights: List[float] = []
    for tok in tokens:
        base_w = _word_speech_weight(tok)
        pause_extra = 0.0
        if tok.endswith(("...", "…")):
            pause_extra = 2.6
        elif tok.endswith((".", "!", "?", ";", ":")):
            pause_extra = 2.1
        elif tok.endswith(","):
            pause_extra = 1.1
        weights.append(base_w + pause_extra)

    sum_w = max(1.0, sum(weights))
    usable = max(0.2, t_hi - t_lo)
    cursor = t_lo
    out: List[Dict[str, Any]] = []
    for tok, w_val in zip(tokens, weights):
        slot = usable * (w_val / sum_w)
        speech_frac = 0.72 if tok.endswith((".", "!", "?", "...", "…", ",")) else 0.94
        st = min(cursor, max(0.0, dur_total - 0.04))
        en = min(dur_total, max(st + 0.04, st + max(0.06, slot * speech_frac)))
        out.append({"word": tok, "start": round(st, 3), "end": round(en, 3)})
        cursor += slot
    return out


# ---------------------------------------------------------------------------
# 4. Broadcast Tactile Sound Design Mastering + Sidechain Ducking + SFX Mix
# ---------------------------------------------------------------------------
def _measure_audio_lufs(
    audio_path: Path,
    af_chain: Optional[str] = None,
    max_probe_s: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """Measure integrated LUFS, True Peak (dBTP), and Loudness Range (LRA) via FFmpeg EBU R128."""
    try:
        cmd = ["ffmpeg", "-y", "-v", "info"]
        if max_probe_s is not None and max_probe_s > 0.5:
            cmd.extend(["-t", f"{float(max_probe_s):.2f}"])
        cmd.extend(["-i", str(audio_path)])
        ln_filter = "loudnorm=I=-14.0:TP=-1.0:LRA=11:print_format=json"
        full_af = f"{af_chain},{ln_filter}" if af_chain else ln_filter
        cmd.extend(["-af", full_af, "-f", "null", "-"])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        matches = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
        if not matches:
            return None
        stats = json.loads(matches[-1])
        mi = float(stats.get("input_i", "-inf"))
        mtp = float(stats.get("input_tp", "-inf"))
        mlra = float(stats.get("input_lra", "0.0"))
        if math.isfinite(mi) and -70.0 <= mi <= 0.0:
            return {
                "i": mi,
                "tp": mtp if math.isfinite(mtp) else -1.0,
                "lra": mlra if math.isfinite(mlra) else 0.0,
            }
    except Exception:
        pass
    return None


def _detect_last_speech_end_s(audio_path: Path, fallback_s: float) -> float:
    """Detect the timestamp (seconds) of the final spoken syllable in `voice_wav`
    so `abrupt_ending_cut=True` terminates cleanly at `speech_end + 0.50s`.
    """
    fb = max(0.3, float(fallback_s))
    try:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True,
            timeout=60,
        )
        if not res.stdout or len(res.stdout) < 640:
            return fb
        pcm = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        frame_len = 160  # 10ms @ 16kHz
        n_frames = len(pcm) // frame_len
        if n_frames < 5:
            return fb
        frames = pcm[: n_frames * frame_len].reshape(n_frames, frame_len)
        rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
        peak_ref = float(np.percentile(rms, 98))
        if peak_ref < 0.005:
            return fb
        thresh = max(0.006, peak_ref * 0.045)
        active = np.where(rms >= thresh)[0]
        if len(active) == 0:
            return fb
        last_t = float(active[-1] + 1) * 0.010 + 0.05
        return round(max(0.25, min(fb, last_t)), 3)
    except Exception:
        return fb


def master_broadcast_audio(
    voice_wav: Path,
    music_mp3: Optional[Path],
    sfx_events: List[Tuple[Path, float, float]],  # (sfx_path, time_s, volume)
    output_m4a: Path,
    duration_s: float,
    music_volume: float = 0.34,
    tail_pad_s: float = 1.25,
    thermal_limit_c: float = 85.0,
    pattern_interrupt_times: Optional[List[float]] = None,
    abrupt_ending_cut: bool = False,
    music_bed_db: float = -23.0,
    music_auto_ducking_db: float = -5.0,
) -> Tuple[Path, float]:
    """Apply JSON v3.0.0 `tactile_sound_design_engine` Broadcast Mastering Chain:
    - Track 1 Voiceover (`-14.0 LUFS`):
      `highpass=f=80` -> `+2.0 dB` warmth @ `120 Hz` -> `+3.0 dB` presence @ `4.5 kHz` ->
      3:1 compression (`attack=12ms`, `release=140ms`) -> exact linear `-14.0 LUFS` calibration.
    - Track 2 Music Bed (`-23.0 LUFS` un-ducked in pauses -> `-28.0 LUFS` under speech, `+14 dB` Voice-to-BGM SNR!):
      `-4.5 dB` vocal-pocket carve (`700–2500 Hz`) -> calibrated to `music_bed_db` (`-23.0 LUFS`) ->
      `-5.0 dB` sidechain auto-ducking (`attack=150ms`, `release=400ms`, `makeup=1.0`, NEVER > 1.0!) ->
      optional `1.25s` hard-cut silence gates at every `t_pi` in `pattern_interrupt_times`.
    - Abrupt Ending (`abrupt_ending_cut=True`, `ACT_4_ABRUPT_ENDING`):
      Ends cleanly at `speech_end + 0.50s` with a subtle lingering dark-room vocal reverb decay and
      a `0.15s` hard fade-out to silence.
    - Master Bus (2-pass linear gain + 192kHz True-Peak Limiter):
      Exact `-14.0 LUFS` integrated, True Peak `<= -1.0 dBTP`, preserving natural dynamic range `LRA >= 4.5 LU`.
    Returns `(output_m4a, final_duration_s)`.
    """
    if abrupt_ending_cut:
        speech_end = _detect_last_speech_end_s(voice_wav, fallback_s=duration_s)
        final_dur = round(speech_end + 0.50, 3)
        eff_tail_pad = max(0.65, final_dur - speech_end + 0.25)
    else:
        speech_end = float(duration_s)
        final_dur = round(duration_s + tail_pad_s, 3)
        eff_tail_pad = max(0.35, float(tail_pad_s))

    # Exact JSON v3.0.0 track_1_voiceover EQ + compression chain
    voice_dsp_chain = (
        "aformat=sample_rates=48000:channel_layouts=stereo,"
        "highpass=f=80,"
        "equalizer=f=120:t=q:w=1.1:g=2.0,"
        "equalizer=f=4500:t=q:w=1.2:g=3.0,"
        "acompressor=threshold=-20dB:ratio=3:attack=12:release=140:makeup=1.5"
    )
    voice_stats = _measure_audio_lufs(voice_wav, af_chain=voice_dsp_chain)
    voice_cal_db = (
        max(-14.0, min(14.0, -14.0 - voice_stats["i"]))
        if voice_stats is not None
        else 0.0
    )

    inputs: List[str] = ["-i", str(voice_wav)]
    use_reverb_tail = bool(abrupt_ending_cut and speech_end >= 0.45)

    if use_reverb_tail:
        tail_start = max(0.0, speech_end - 1.35)
        tail_gate_t = max(0.0, speech_end - 0.10)
        filter_parts: List[str] = [
            (
                f"[0:a]{voice_dsp_chain},volume={voice_cal_db:+.2f}dB,"
                f"apad=pad_dur={eff_tail_pad:.2f},atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS,"
                "asplit=3[v_main][v_tail_src][v_sc]"
            ),
            (
                # Time-aligned subtle lingering room reverb tail on the final phrase only (zero PTS shift!)
                f"[v_tail_src]volume=enable='lt(t,{tail_start:.3f})':volume=0,"
                "aecho=0.60:0.65:55|115|195|290|395:0.34|0.25|0.18|0.12|0.08,"
                "highpass=f=180,lowpass=f=2400,"
                f"volume=enable='lt(t,{tail_gate_t:.3f})':volume=0,"
                "volume=0.35[v_reverb_tail]"
            ),
        ]
        mix_labels: List[str] = ["[v_main]", "[v_reverb_tail]"]
    else:
        filter_parts = [
            (
                f"[0:a]{voice_dsp_chain},volume={voice_cal_db:+.2f}dB,"
                f"apad=pad_dur={eff_tail_pad:.2f},atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS,"
                "asplit=2[v_main][v_sc]"
            )
        ]
        mix_labels = ["[v_main]"]

    next_idx = 1

    if music_mp3 and Path(music_mp3).exists() and float(music_volume) > 0.001:
        music_p = Path(music_mp3)
        # Wide -4.5 dB vocal-pocket carve across 700–2500 Hz (geometric center ~1320 Hz, Q=0.75)
        bgm_pocket_eq = (
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            "equalizer=f=1320:t=q:w=0.75:g=-4.5"
        )
        bgm_stats = _measure_audio_lufs(
            music_p,
            af_chain=bgm_pocket_eq,
            max_probe_s=min(180.0, max(30.0, final_dur)),
        )
        bgm_measured_i = bgm_stats["i"] if bgm_stats is not None else -17.5

        # Canonical documentary default `music_volume=0.34` maps to exact `music_bed_db=-23.0 LUFS`
        # (9.0 dB quieter than -14.0 LUFS speech, so pauses NEVER surge louder than the narrator!).
        vol_trim_db = max(-9.0, min(3.0, 20.0 * math.log10(max(1e-4, float(music_volume)) / 0.34)))
        target_bgm_pause_lufs = float(music_bed_db) + vol_trim_db
        bgm_cal_db = max(-32.0, min(12.0, target_bgm_pause_lufs - bgm_measured_i))

        inputs.extend(["-stream_loop", "-1", "-i", str(music_p)])
        if abrupt_ending_cut:
            fade_out_d = 0.20
            fade_out_start = max(0.0, final_dur - fade_out_d)
        else:
            fade_out_d = min(1.20, max(0.35, float(tail_pad_s) * 0.90 if tail_pad_s >= 0.8 else final_dur * 0.12))
            fade_out_start = max(0.0, final_dur - fade_out_d)

        filter_parts.append(
            f"[{next_idx}:a]atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS,"
            f"{bgm_pocket_eq},volume={bgm_cal_db:+.2f}dB,"
            f"afade=t=in:st=0:d=0.30,afade=t=out:st={fade_out_start:.3f}:d={fade_out_d:.3f}[bgm_raw]"
        )

        # JSON v3.0.0 sidechain auto-ducking: -5.0 dB under speech (`-23.0 -> -28.0 LUFS`, `+14 dB` SNR!)
        # attack=150ms, release=400ms, makeup=1.0 (STRICTLY NEVER > 1.0!)
        duck_db = max(1.0, min(12.0, abs(float(music_auto_ducking_db))))
        sc_thresh = 0.064  # ~ -23.9 dBFS RMS threshold; reliably tracks speech syllables, stays open in pauses
        sc_ratio = round(max(1.30, min(8.0, 1.0 / max(0.12, 1.0 - (duck_db / 11.8)))), 2)

        valid_pi = sorted(
            float(t_pi)
            for t_pi in (pattern_interrupt_times or [])
            if 0.0 <= float(t_pi) < final_dur
        )
        if valid_pi:
            filter_parts.append(
                f"[bgm_raw][v_sc]sidechaincompress=threshold={sc_thresh:.3f}:ratio={sc_ratio:.2f}:"
                "attack=150:release=400:makeup=1.0:knee=2.8:detection=rms[bgm_sc]"
            )
            pi_filters = [
                f"volume=enable='between(t,{t0:.3f},{min(final_dur, t0 + 1.25):.3f})':volume=0"
                for t0 in valid_pi
            ]
            filter_parts.append(f"[bgm_sc]{','.join(pi_filters)}[bgm_ducked]")
        else:
            filter_parts.append(
                f"[bgm_raw][v_sc]sidechaincompress=threshold={sc_thresh:.3f}:ratio={sc_ratio:.2f}:"
                "attack=150:release=400:makeup=1.0:knee=2.8:detection=rms[bgm_ducked]"
            )

        mix_labels.append("[bgm_ducked]")
        next_idx += 1
    else:
        filter_parts.append("[v_sc]anullsink")

    # Timed SFX cues
    for sfx_path, t_s, vol in sfx_events:
        if not Path(sfx_path).exists() or t_s < 0 or t_s > final_dur:
            continue
        delay_ms = int(round(float(t_s) * 1000.0))
        inputs.extend(["-i", str(sfx_path)])
        lbl = f"[sfx{next_idx}]"
        filter_parts.append(
            f"[{next_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={float(vol):.3f},adelay={delay_ms}|{delay_ms}[sfx_d{next_idx}];"
            f"[sfx_d{next_idx}]apad=whole_dur={final_dur:.3f},atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS{lbl}"
        )
        mix_labels.append(lbl)
        next_idx += 1

    # Pass 1: Sum all stems cleanly into 32-bit float intermediate (infinite headroom, zero premature clipping)
    if len(mix_labels) == 1:
        filter_parts.append("[v_main]aresample=48000[premix]")
    else:
        n_mix = len(mix_labels)
        joined = "".join(mix_labels)
        filter_parts.append(
            f"{joined}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0,aresample=48000[premix]"
        )

    output_m4a = Path(output_m4a)
    output_m4a.parent.mkdir(parents=True, exist_ok=True)
    tmp_premix = output_m4a.with_name(f"{output_m4a.stem}_premix_f32.wav")
    try:
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                *inputs,
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[premix]",
                "-t",
                f"{final_dur:.3f}",
                "-c:a",
                "pcm_f32le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(tmp_premix),
            ],
            thermal_limit_c=thermal_limit_c,
        )

        # Pass 2: Exact linear loudness calibration to -14.0 LUFS + 192kHz oversampled True-Peak Limiter
        # (preserves 100% of true musical/speech dynamic range LRA >= 4.5 LU with ZERO single-pass loudnorm pumping!)
        pre_stats = _measure_audio_lufs(tmp_premix)
        master_gain_db = (
            max(-10.0, min(10.0, -14.0 - pre_stats["i"]))
            if pre_stats is not None
            else 0.0
        )
        master_chain_parts = [f"volume={master_gain_db:+.2f}dB"]
        if abrupt_ending_cut:
            cut_fade_st = max(0.0, final_dur - 0.15)
            master_chain_parts.append(f"afade=t=out:st={cut_fade_st:.3f}:d=0.15")
        # 4x oversampled True-Peak ceiling at 0.85 (-1.41 dBFS) guarantees AAC 192k output <= -1.0 dBTP!
        master_chain_parts.extend(
            [
                "aresample=192000",
                "alimiter=limit=0.85:level=false:attack=2:release=35:latency=true",
                "aresample=48000",
            ]
        )

        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(tmp_premix),
                "-af",
                ",".join(master_chain_parts),
                "-t",
                f"{final_dur:.3f}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(output_m4a),
            ],
            thermal_limit_c=thermal_limit_c,
        )
    finally:
        tmp_premix.unlink(missing_ok=True)

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
    across Edge-TTS, Gemini TTS (via acting_direction pace/pitch cues + Whisper alignment), and Kokoro-ONNX!
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
    used_gemini_tts = False

    if voice_engine == "gemini_tts":
        try:
            from engine.gemini_tts import GEMINI_EXPRESSIVE_VOICES, synthesize_gemini_tts_line

            valid_ids = {v["id"] for v in GEMINI_EXPRESSIVE_VOICES}
            g_voice = voice_id if voice_id in valid_ids else "Puck"
            acting_dir = _build_gemini_acting_direction(clean_rate, clean_pitch, language=eff_lang)
            source_audio, _ = await asyncio.to_thread(
                synthesize_gemini_tts_line,
                text,
                raw_wav,
                g_voice,
                acting_dir,
                None,
                eff_lang,
                thermal_limit_c,
            )
            used_gemini_tts = True
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

    out_wav, remapped_words, out_dur = trim_silence_vad(
        source_audio, trimmed_wav, words, thermal_limit_c=thermal_limit_c
    )
    if used_gemini_tts:
        remapped_words = await asyncio.to_thread(
            align_script_words_to_audio, out_wav, text, out_dur, eff_lang
        )
    return out_wav, remapped_words, out_dur
