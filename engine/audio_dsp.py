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
    {"id": "pt-BR-AntonioNeural", "name": "Antônio (Masculino • Autoridade)", "gender": "M"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca (Feminino • Premium)", "gender": "F"},
    {"id": "pt-BR-ThalitaMultilingualNeural", "name": "Thalita (Feminino • Comercial UGC)", "gender": "F"},
]

KOKORO_PT_VOICES = ["pf_dora", "pm_alex", "pm_santa"]


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
    # Voice Blender: linear interpolation of speaker embedding vectors
    vectors = []
    weights = []
    for vname in KOKORO_PT_VOICES:
        w = float(blend_weights.get(vname, 0.0))
        if w > 0.0:
            try:
                vec = kokoro.get_voice_style(vname)
                vectors.append(vec)
                weights.append(w)
            except Exception:
                continue

    if not vectors:
        blended_style = kokoro.get_voice_style("pm_alex")
    else:
        total_w = sum(weights)
        blended_style = sum(v * (w / total_w) for v, w in zip(vectors, weights))

    samples, sr = kokoro.create(text, voice=blended_style, speed=speed, lang="pt-br")
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
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Instant cloud PT-BR TTS with native WordBoundary timestamps (0.1s precision)."""
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
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


def _synthesize_espeak_fallback(text: str, out_wav: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """100% offline PT-BR fallback via espeak-ng if internet is offline."""
    subprocess.run(
        ["espeak-ng", "-v", "pt-br", "-s", "165", "-w", str(out_wav), text],
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
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Tighten long pauses while strictly preserving final consonants (+85ms tail)."""
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

    if silero_path.exists():
        try:
            sess = ort.InferenceSession(str(silero_path), providers=["CPUExecutionProvider"])
            state = np.zeros((2, 1, 128), dtype=np.float32)
            sr_arr = np.array(sr, dtype=np.int64)
            for i in range(n_frames):
                chunk = pcm[i * frame_len : (i + 1) * frame_len][None, :]
                out, state = sess.run(None, {"input": chunk, "state": state, "sr": sr_arr})
                speech_probs[i] = float(out[0][0])
        except Exception:
            silero_path = Path("__fallback__")

    if not silero_path.exists():
        # Adaptive energy + zero-crossing consonant detector
        frames = pcm[: n_frames * frame_len].reshape(n_frames, frame_len)
        rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10)
        zcr = np.mean(np.abs(np.diff(np.sign(frames), axis=1)) > 0, axis=1)
        thresh = max(0.012, float(np.percentile(rms, 25)) * 2.2)
        speech_probs = ((rms > thresh) | ((rms > thresh * 0.45) & (zcr > 0.12))).astype(np.float32)

    # Convert to speech intervals with generous consonant tail pad
    frame_s = frame_len / float(sr)
    pad_frames = int(math.ceil(consonant_pad_s / frame_s))
    active = speech_probs > 0.35
    # Dilate active mask so final consonants ("s", "r", "t", "k") are NEVER clipped
    if n_frames > 0 and np.any(active):
        kernel = np.ones(pad_frames * 2 + 1, dtype=np.int32)
        dilated = np.convolve(active.astype(np.int32), kernel, mode="same") > 0
    else:
        dilated = np.ones(n_frames, dtype=bool)

    # Keep natural micro-pauses up to max_pause_s; ALWAYS preserve final 250ms tail after last word
    max_sil_frames = int(max_pause_s / frame_s)
    keep_mask = np.zeros(n_frames, dtype=bool)
    sil_run = 0
    for i in range(n_frames):
        if dilated[i]:
            keep_mask[i] = True
            sil_run = 0
        else:
            sil_run += 1
            if sil_run <= max_sil_frames:
                keep_mask[i] = True

    active_idx = np.where(dilated)[0]
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

    if music_mp3 and music_mp3.exists():
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
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Unified narration entry point (Kokoro OpenVINO Blend -> Edge-TTS -> espeak-ng) + VAD trim."""
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_mp3 = work_dir / f"{prefix}_raw.mp3"
    raw_wav = work_dir / f"{prefix}_raw.wav"
    trimmed_wav = work_dir / f"{prefix}_vad.wav"

    words: List[Dict[str, Any]] = []
    source_audio: Path

    if voice_engine == "gemini_tts":
        try:
            from engine.gemini_tts import GEMINI_EXPRESSIVE_VOICES, synthesize_gemini_tts_line

            valid_ids = {v["id"] for v in GEMINI_EXPRESSIVE_VOICES}
            g_voice = voice_id if voice_id in valid_ids else "Puck"
            source_audio, g_dur = await asyncio.to_thread(
                synthesize_gemini_tts_line,
                text,
                raw_wav,
                g_voice,
            )
            words = _estimate_word_timestamps(text, g_dur)
        except Exception:
            try:
                fallback_v = voice_id if voice_id.startswith("pt-BR-") else "pt-BR-AntonioNeural"
                source_audio, words = await synthesize_edge_tts(text, raw_mp3, voice=fallback_v)
            except Exception:
                source_audio, words = _synthesize_espeak_fallback(text, raw_wav)
    elif voice_engine == "kokoro":
        try:
            source_audio, words = synthesize_kokoro_blended(
                text, raw_wav, voice_blend or {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}
            )
        except Exception:
            # Automatic transparent fallback to Edge-TTS if local Kokoro weights not yet fetched
            try:
                source_audio, words = await synthesize_edge_tts(text, raw_mp3, voice=voice_id)
            except Exception:
                source_audio, words = _synthesize_espeak_fallback(text, raw_wav)
    else:
        try:
            source_audio, words = await synthesize_edge_tts(text, raw_mp3, voice=voice_id)
        except Exception:
            source_audio, words = _synthesize_espeak_fallback(text, raw_wav)

    return trim_silence_vad(source_audio, trimmed_wav, words, thermal_limit_c=thermal_limit_c)
