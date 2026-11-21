"""FrimeRise Hollywood Cinema Sound Design Engine (48kHz Stereo Pro SFX + Dark Cinema Score).

Synthesizes rich, multi-layered 48kHz stereo cinema sound effects and atmospheric
dark-mystery/horror music beds purely with NumPy + SciPy (100% permissive license, zero GPL):
- 15 upgraded cinema SFX in `assets/sfx/`:
  `sub_boom.wav`, `horror_braam.wav`, `cinematic_hit.wav`, `whoosh_fast.wav`,
  `whoosh_deep.wav`, `riser_tension.wav`, `paper_flip.wav`, `flash_impact.wav`,
  `heartbeat.wav`, `pop_bubble.wav`, `glitch_digital.wav`, `camera_shutter.wav`,
  `cash_chime.wav`, `typing_tick.wav`, `ui_click.wav`
- Seamless 45s dark mystery/horror cinema music bed: `assets/music/dark_mystery_horror.mp3`
- Public helpers: `ensure_pro_cinema_sfx()` and `select_music_for_mood(topic, default_file)`
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import signal

from engine.intel_vaapi import run_ffmpeg_safe

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
SFX_DIR = ASSETS_DIR / "sfx"
MUSIC_DIR = ASSETS_DIR / "music"

SR = 48000
PRO_SFX_VERSION = "pro_cinema_sfx_v3"
VERSION_STAMP_FILE = SFX_DIR / ".pro_cinema_sfx_version.json"

ALL_SFX_NAMES: Tuple[str, ...] = (
    "sub_boom.wav",
    "horror_braam.wav",
    "cinematic_hit.wav",
    "whoosh_fast.wav",
    "whoosh_deep.wav",
    "riser_tension.wav",
    "paper_flip.wav",
    "flash_impact.wav",
    "heartbeat.wav",
    "pop_bubble.wav",
    "glitch_digital.wav",
    "camera_shutter.wav",
    "cash_chime.wav",
    "typing_tick.wav",
    "ui_click.wav",
)


# ---------------------------------------------------------------------------
# Core Studio DSP Building Blocks (Pure NumPy + SciPy, 48kHz Stereo)
# ---------------------------------------------------------------------------
def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _white_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    x = rng.standard_normal(n)
    rms = np.sqrt(np.mean(x * x) + 1e-12)
    return x / rms


def _pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """True 1/f spectral pink noise for organic wind, rumble, and hall tails."""
    n_fft = max(2, n)
    w = rng.standard_normal(n_fft)
    spec = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)
    scale = np.zeros_like(freqs)
    mask = freqs >= 18.0
    scale[mask] = 1.0 / np.sqrt(freqs[mask])
    shaped = np.fft.irfft(spec * scale, n=n_fft)[:n]
    rms = np.sqrt(np.mean(shaped * shaped) + 1e-12)
    return shaped / rms


def _brown_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Deep 1/f^2 spectral brown noise for cinema LFE pressure & dark wind."""
    n_fft = max(2, n)
    w = rng.standard_normal(n_fft)
    spec = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)
    scale = np.zeros_like(freqs)
    mask = freqs >= 20.0
    scale[mask] = 1.0 / freqs[mask]
    shaped = np.fft.irfft(spec * scale, n=n_fft)[:n]
    rms = np.sqrt(np.mean(shaped * shaped) + 1e-12)
    return shaped / rms


def _butter(x: np.ndarray, cutoff: Any, btype: str = "lowpass", order: int = 4) -> np.ndarray:
    nyq = SR * 0.5
    if isinstance(cutoff, (tuple, list)):
        wn = [max(10.0, min(nyq * 0.96, float(c))) / nyq for c in cutoff]
    else:
        wn = max(10.0, min(nyq * 0.96, float(cutoff))) / nyq
    sos = signal.butter(order, wn, btype=btype, output="sos")
    if x.ndim == 2:
        out = np.empty_like(x)
        out[:, 0] = signal.sosfilt(sos, x[:, 0])
        out[:, 1] = signal.sosfilt(sos, x[:, 1])
        return out
    return signal.sosfilt(sos, x)


def _rbj_biquad(freq: float, q: float, mode: str) -> Tuple[np.ndarray, np.ndarray]:
    """Audio EQ Cookbook biquad filter coefficients."""
    f = max(28.0, min(SR * 0.42, float(freq)))
    qv = max(0.55, min(7.0, float(q)))
    w0 = 2.0 * math.pi * f / SR
    cw = math.cos(w0)
    sw = math.sin(w0)
    alpha = sw / (2.0 * qv)
    if mode == "lowpass":
        b0 = (1.0 - cw) * 0.5
        b1 = 1.0 - cw
        b2 = (1.0 - cw) * 0.5
    elif mode == "highpass":
        b0 = (1.0 + cw) * 0.5
        b1 = -(1.0 + cw)
        b2 = (1.0 + cw) * 0.5
    else:  # bandpass (constant 0 dB peak gain)
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * cw
    a2 = 1.0 - alpha
    return np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64), np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)


def _resonant_filter_sweep(
    x: np.ndarray,
    f_curve: np.ndarray,
    q_curve: Any = 1.6,
    mode: str = "lowpass",
    block: int = 64,
) -> np.ndarray:
    """Zero-click time-varying resonant biquad filter sweep with continuous state."""
    n = len(x)
    out = np.empty(n, dtype=np.float64)
    q_arr = np.full(n, float(q_curve), dtype=np.float64) if np.isscalar(q_curve) else np.asarray(q_curve, dtype=np.float64)
    zi = np.zeros(2, dtype=np.float64)
    for start in range(0, n, block):
        end = min(n, start + block)
        mid = (start + end) // 2
        b, a = _rbj_biquad(float(f_curve[mid]), float(q_arr[mid]), mode)
        y, zi = signal.lfilter(b, a, x[start:end], zi=zi)
        out[start:end] = y
    return out


def _soft_saturate(x: np.ndarray, drive: float = 2.0, asym: float = 0.08) -> np.ndarray:
    """Warm asymmetric analog tape/tube saturation for heavy cinema punch."""
    d = max(0.25, float(drive))
    shaped = np.tanh(d * (x + asym * (x * x))) / math.tanh(d)
    # Remove tiny DC offset introduced by even-harmonic asymmetry
    if shaped.ndim == 2:
        shaped = shaped - np.mean(shaped, axis=0, keepdims=True)
    else:
        shaped = shaped - np.mean(shaped)
    return shaped


def _stereo_pan(mono: np.ndarray, pan: Any) -> np.ndarray:
    """Constant-power stereo panning (-1.0 = full Left, +1.0 = full Right)."""
    if np.isscalar(pan):
        ang = (max(-1.0, min(1.0, float(pan))) + 1.0) * (math.pi * 0.25)
        return np.column_stack([mono * math.cos(ang), mono * math.sin(ang)])
    p = np.clip(np.asarray(pan, dtype=np.float64), -1.0, 1.0)
    ang = (p + 1.0) * (math.pi * 0.25)
    return np.column_stack([mono * np.cos(ang), mono * np.sin(ang)])


def _to_stereo(mono: np.ndarray, delay_ms: float = 0.55, side_gain: float = 0.14) -> np.ndarray:
    """Convert mono to rich phase-safe stereo using subtle Haas micro-offset."""
    n = len(mono)
    d = max(1, int(delay_ms * SR / 1000.0))
    delayed = np.zeros(n, dtype=np.float64)
    if d < n:
        delayed[d:] = mono[:-d]
    left = mono + side_gain * (mono - delayed)
    right = mono - side_gain * (mono - delayed)
    return np.column_stack([left, right])


def _dark_hall_reverb(
    stereo: np.ndarray,
    decay_s: float = 1.6,
    predelay_ms: float = 18.0,
    damp_hz: float = 2600.0,
    mix: float = 0.38,
    extend_tail: bool = False,
    seed: int = 101,
) -> np.ndarray:
    """True stereo cinema scoring-hall convolution reverb (multi-band damped synthetic IR)."""
    rng = _rng(seed)
    ir_len = max(int(0.35 * SR), int(decay_s * SR))
    t = np.arange(ir_len, dtype=np.float64) / SR
    pre = int(predelay_ms * SR / 1000.0)

    ir = np.zeros((ir_len, 2), dtype=np.float64)
    # 1. Specular early reflections (14 alternating L/R taps)
    er_times_ms = [11, 17, 23, 29, 36, 43, 51, 59, 67, 76, 84, 93, 104, 118]
    for i, ms in enumerate(er_times_ms):
        idx = int(ms * SR / 1000.0)
        if idx < ir_len:
            gain = 0.55 * (0.83 ** i) * (1.0 if i % 3 else -1.0)
            ch = i % 2
            ir[idx, ch] += gain
            ir[min(ir_len - 1, idx + 19), 1 - ch] += gain * 0.35

    # 2. Dense decorrelated 3-band late diffuse tail (lows decay slower than highs)
    bloom = 1.0 - np.exp(-t / 0.032)
    env_low = bloom * np.exp(-6.9 * t / max(0.25, decay_s * 1.15))
    env_mid = bloom * np.exp(-6.9 * t / max(0.20, decay_s * 0.78))
    env_hi = bloom * np.exp(-6.9 * t / max(0.12, decay_s * 0.36))

    for ch in range(2):
        n_raw = rng.standard_normal(ir_len)
        low_b = _butter(n_raw, 420.0, "lowpass", order=2) * env_low
        mid_b = _butter(n_raw, (420.0, damp_hz), "bandpass", order=2) * env_mid
        hi_b = _butter(n_raw, damp_hz, "highpass", order=2) * env_hi
        diffuse = low_b * 0.55 + mid_b * 0.48 + hi_b * 0.22
        if pre < ir_len:
            ir[pre:, ch] += diffuse[: ir_len - pre]

    # Smooth tail end of IR
    fade_n = min(int(0.08 * SR), ir_len // 4)
    if fade_n > 0:
        ir[-fade_n:, :] *= np.linspace(1.0, 0.0, fade_n)[:, None]

    # Normalize IR power
    ir_energy = np.sqrt(np.sum(ir * ir) * 0.5 + 1e-12)
    ir /= max(1e-6, ir_energy)

    wet_l = signal.fftconvolve(stereo[:, 0], ir[:, 0], mode="full")
    wet_r = signal.fftconvolve(stereo[:, 1], ir[:, 1], mode="full")
    if extend_tail:
        out_len = len(wet_l)
        dry_pad = np.zeros((out_len, 2), dtype=np.float64)
        dry_pad[: len(stereo)] = stereo
        wet = np.column_stack([wet_l, wet_r])
    else:
        out_len = len(stereo)
        dry_pad = stereo
        wet = np.column_stack([wet_l[:out_len], wet_r[:out_len]])

    # Match wet RMS to dry RMS so `mix` accurately controls true wet/dry balance
    dry_rms = float(np.sqrt(np.mean(dry_pad * dry_pad) + 1e-12))
    wet_rms = float(np.sqrt(np.mean(wet * wet) + 1e-12))
    if wet_rms > 1e-9:
        wet = wet * (dry_rms / wet_rms)

    # Keep LFE sub-bass (< 110Hz) mono-compatible while preserving lush wide stereo mids/highs
    wet_low = _butter(wet, 110.0, "lowpass", order=2)
    wet_low_mono = 0.5 * (wet_low[:, 0] + wet_low[:, 1])
    wet_hi = wet - wet_low
    wet = np.column_stack([wet_low_mono, wet_low_mono]) + wet_hi

    return dry_pad * (1.0 - mix * 0.40) + wet * mix


def _master_stereo(
    stereo: np.ndarray,
    target_peak_db: float = -0.8,
    fade_in_ms: float = 2.0,
    fade_out_ms: float = 24.0,
    bus_drive: float = 1.35,
) -> np.ndarray:
    """Broadcast cinema SFX master chain: 22Hz subsonic DC clean -> soft bus glue -> -0.8 dBFS peak."""
    st = np.asarray(stereo, dtype=np.float64)
    if st.ndim == 1:
        st = np.column_stack([st, st])
    # High-pass 22Hz preserves full 30Hz cinema LFE while eliminating subsonic DC drift
    st = _butter(st, 22.0, "highpass", order=3)

    # Peak normalize before gentle bus glue so bus saturation behaves consistently
    peak = float(np.max(np.abs(st)))
    if peak > 1e-9:
        st = st / peak

    # Gentle bus soft-limiter / punch glue
    if bus_drive > 1.0:
        st = np.tanh(bus_drive * st) / math.tanh(bus_drive)

    # Final precise target peak normalization
    peak2 = float(np.max(np.abs(st)))
    target_lin = 10.0 ** (target_peak_db / 20.0)
    if peak2 > 1e-9:
        st = st * (target_lin / peak2)

    # Click-free micro fades
    fi = min(len(st) // 6, max(1, int(fade_in_ms * SR / 1000.0)))
    fo = min(len(st) // 3, max(1, int(fade_out_ms * SR / 1000.0)))
    if fi > 1:
        st[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    if fo > 1:
        st[-fo:] *= (np.cos(np.linspace(0.0, math.pi * 0.5, fo)) ** 2)[:, None]

    return np.clip(st, -0.995, 0.995)


def _write_wav_stereo(path: Path, stereo: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return path


def _poly_saw(phase: np.ndarray) -> np.ndarray:
    """Rich harmonically warm sawtooth wave (bandwidth-controlled via additive/soft shape)."""
    # Sum first 12 harmonics for rich brassy warmth without harsh Nyquist aliasing
    out = np.zeros_like(phase)
    for k in range(1, 13):
        out += ((-1.0) ** (k + 1)) * (1.0 / k) * np.sin(k * phase)
    return out * (2.0 / math.pi)


# ---------------------------------------------------------------------------
# 15 Hollywood Cinema Sound Effects (48kHz Stereo)
# ---------------------------------------------------------------------------
def synth_sub_boom() -> np.ndarray:
    """Massive cinema trailer LFE sub-drop (95Hz -> 32Hz bend + soft saturation + transient + 1.8s dark hall)."""
    rng = _rng(1001)
    dur = 2.35
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # 1. Exponential pitch-drop sub core (95Hz -> 32Hz) + warm octave harmonic
    f_sub = 31.5 + (96.0 - 31.5) * np.exp(-t / 0.24)
    phase = 2.0 * math.pi * np.cumsum(f_sub) / SR
    env_sub = (1.0 - np.exp(-t / 0.004)) * np.exp(-t / 0.95)
    sub_core = np.sin(phase) * env_sub
    sub_harm = 0.34 * np.sin(2.0 * phase + 0.3) * np.exp(-t / 0.42) * (1.0 - np.exp(-t / 0.003))
    sub_sat = _soft_saturate(sub_core + sub_harm, drive=2.3, asym=0.10)
    sub_sat = _butter(sub_sat, 260.0, "lowpass", order=3)

    # 2. Low-pass filtered chest-slam impact transient
    f_punch = 58.0 + 360.0 * np.exp(-t / 0.018)
    ph_punch = 2.0 * math.pi * np.cumsum(f_punch) / SR
    punch_body = np.sin(ph_punch) * np.exp(-t / 0.055) * (1.0 - np.exp(-t / 0.0015))
    noise_hit = _butter(_pink_noise(n, rng), 920.0, "lowpass", order=3) * np.exp(-t / 0.048) * (1.0 - np.exp(-t / 0.001))
    transient = _soft_saturate(punch_body * 0.95 + noise_hit * 0.72, drive=2.6)

    # 3. Dark LFE rumble bed
    rumble = _butter(_brown_noise(n, rng), (28.0, 140.0), "bandpass", order=2) * np.exp(-t / 0.85) * 0.35

    dry = _to_stereo(sub_sat * 1.10 + transient * 0.78 + rumble, delay_ms=0.75, side_gain=0.18)
    wet = _dark_hall_reverb(dry, decay_s=1.85, predelay_ms=16.0, damp_hz=1100.0, mix=0.46, seed=1002)
    return _master_stereo(wet, target_peak_db=-0.7, fade_in_ms=1.5, fade_out_ms=90.0, bus_drive=1.45)


def synth_horror_braam() -> np.ndarray:
    """Chilling Hans Zimmer / A24 dark horror brass-drone BRAAM."""
    rng = _rng(2001)
    dur = 2.85
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # Dark D-minor / Phrygian ominous brass voicing (D1, D2 detuned stack, F2, Eb2 tension, A2)
    voices = [
        (36.71, 0.90, 0.00),    # D1 deep sub brass
        (73.42, 0.80, -0.35),   # D2 core L
        (73.88, 0.78, +0.35),   # D2 detuned +11 cents R
        (72.98, 0.72, -0.15),   # D2 detuned -10 cents
        (87.31, 0.45, +0.45),   # F2 dark minor 3rd
        (77.78, 0.30, -0.50),   # Eb2 Phrygian horror semitone
        (110.00, 0.52, +0.20),  # A2 brass 5th
        (146.83, 0.32, -0.25),  # D3 upper brass rasp
    ]

    # Attack bloom + dramatic brass swell + dark decaying growl
    env = (1.0 - np.exp(-t / 0.085)) * np.exp(-np.maximum(0.0, t - 0.55) / 1.15)
    # Slow pitch sag (-18 cents over tail) for dreadful cinema gravity
    pitch_sag = 1.0 - 0.012 * (1.0 - np.exp(-t / 1.4))

    brass_l = np.zeros(n, dtype=np.float64)
    brass_r = np.zeros(n, dtype=np.float64)
    for idx, (freq, amp, pan) in enumerate(voices):
        # Subtle organic breath vibrato per brass player
        vib = 1.0 + 0.0035 * np.sin(2.0 * math.pi * (2.6 + idx * 0.43) * t + idx)
        inst_f = freq * pitch_sag * vib
        ph = 2.0 * math.pi * np.cumsum(inst_f) / SR + idx * 0.7
        sig = _poly_saw(ph) * amp
        st = _stereo_pan(sig, pan)
        brass_l += st[:, 0]
        brass_r += st[:, 1]

    # Resonant low-pass brass filter sweep: closed -> roaring open -> ominous dark close
    f_sweep = 160.0 + 1680.0 * (1.0 - np.exp(-t / 0.14)) * np.exp(-t / 0.92)
    q_sweep = 1.4 + 1.8 * np.exp(-((t - 0.25) / 0.35) ** 2)
    filt_l = _resonant_filter_sweep(brass_l, f_sweep, q_sweep, mode="lowpass")
    filt_r = _resonant_filter_sweep(brass_r, f_sweep * 1.04, q_sweep, mode="lowpass")

    # Add sub-octave weight + independent stereo raspy brass air burst
    sub_ph = 2.0 * math.pi * np.cumsum(36.71 * pitch_sag) / SR
    sub = np.sin(sub_ph) * env * 1.05
    air_l = _butter(_pink_noise(n, rng), (450.0, 2200.0), "bandpass", order=2) * env * 0.22
    air_r = _butter(_pink_noise(n, rng), (450.0, 2200.0), "bandpass", order=2) * env * 0.22

    braam = np.column_stack([
        _soft_saturate(filt_l * env * 0.72 + sub + air_l, drive=2.4, asym=0.10),
        _soft_saturate(filt_r * env * 0.72 + sub + air_r, drive=2.4, asym=0.10),
    ])

    # Subtle initial sub impact kick to anchor the braam on scene cut
    kick_f = 42.0 + 140.0 * np.exp(-t / 0.024)
    kick = np.sin(2.0 * math.pi * np.cumsum(kick_f) / SR) * np.exp(-t / 0.09) * 0.75
    braam[:, 0] += kick
    braam[:, 1] += kick

    wet = _dark_hall_reverb(braam, decay_s=2.25, predelay_ms=22.0, damp_hz=2100.0, mix=0.48, seed=2002)
    return _master_stereo(wet, target_peak_db=-0.7, fade_in_ms=4.0, fade_out_ms=120.0, bus_drive=1.55)


def synth_cinematic_hit() -> np.ndarray:
    """Punchy Hollywood trailer drum slam (layered taiko tom + metallic anvil + noise burst + wide tail)."""
    rng = _rng(3001)
    dur = 2.15
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # 1. Layered Taiko / Low Tom Slam
    f1 = 44.0 + 138.0 * np.exp(-t / 0.032)
    f2 = 34.0 + 82.0 * np.exp(-t / 0.055)
    tom1 = np.sin(2.0 * math.pi * np.cumsum(f1) / SR) * np.exp(-t / 0.34)
    tom2 = np.sin(2.0 * math.pi * np.cumsum(f2) / SR) * np.exp(-t / 0.62)
    drum = _soft_saturate((tom1 * 0.95 + tom2 * 0.85) * (1.0 - np.exp(-t / 0.002)), drive=2.4)

    # 2. Metallic Anvil Transient (inharmonic ring)
    anvil_freqs = [690.0, 1185.0, 1940.0, 3110.0, 4760.0, 6420.0]
    anvil_l = np.zeros(n, dtype=np.float64)
    anvil_r = np.zeros(n, dtype=np.float64)
    for i, af in enumerate(anvil_freqs):
        dec = 0.24 / (1.0 + i * 0.45)
        al = np.sin(2.0 * math.pi * af * t) * np.exp(-t / dec) * (0.42 / (1.0 + i * 0.35))
        ar = np.sin(2.0 * math.pi * (af * 1.007) * t + 0.5) * np.exp(-t / dec) * (0.42 / (1.0 + i * 0.35))
        anvil_l += al
        anvil_r += ar

    # 3. Filtered noise crack & air slam
    crack = _butter(_white_noise(n, rng), (600.0, 6200.0), "bandpass", order=2) * np.exp(-t / 0.038)
    body_noise = _butter(_pink_noise(n, rng), (140.0, 1800.0), "bandpass", order=2) * np.exp(-t / 0.14)

    dry = np.column_stack([
        drum + anvil_l * 0.65 + crack * 0.58 + body_noise * 0.50,
        drum + anvil_r * 0.65 + np.roll(crack, 14) * 0.58 + np.roll(body_noise, 27) * 0.50,
    ])
    wet = _dark_hall_reverb(dry, decay_s=1.65, predelay_ms=14.0, damp_hz=3100.0, mix=0.45, seed=3002)
    return _master_stereo(wet, target_peak_db=-0.7, fade_in_ms=1.0, fade_out_ms=80.0, bus_drive=1.50)


def synth_whoosh_fast() -> np.ndarray:
    """Realistic Premiere/DaVinci wind-whip transition swoosh (L->R panned bandpass pink noise + Doppler sub)."""
    rng = _rng(4001)
    dur = 0.64
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR
    peak_t = 0.27

    # Asymmetric bell envelope (fast whip-in, airy whip-out)
    env = np.where(
        t < peak_t,
        np.exp(-((t - peak_t) / 0.115) ** 2),
        np.exp(-((t - peak_t) / 0.175) ** 2),
    )

    # Bandpass frequency sweep peaking right at the whip apex
    f_band = 240.0 + 3400.0 * (env ** 1.35)
    f_air = 1200.0 + 5200.0 * (env ** 1.6)
    pink1 = _pink_noise(n, rng)
    pink2 = _pink_noise(n, rng)
    wind_core = _resonant_filter_sweep(pink1, f_band, q_curve=1.9, mode="bandpass") * env
    wind_air = _resonant_filter_sweep(pink2, f_air, q_curve=1.3, mode="bandpass") * (env ** 1.4) * 0.55

    # Doppler LFE air-pressure body
    f_doppler = 48.0 + 95.0 * env
    doppler = np.sin(2.0 * math.pi * np.cumsum(f_doppler) / SR) * (env ** 1.3) * 0.62

    # Smooth L -> R stereo fly-by pan
    pan_curve = np.tanh((t - peak_t) * 6.5) * 0.82
    st_core = _stereo_pan(wind_core * 1.15 + doppler, pan_curve)
    st_air = _stereo_pan(wind_air, pan_curve * 0.95)
    dry = st_core + st_air

    wet = _dark_hall_reverb(dry, decay_s=0.65, predelay_ms=8.0, damp_hz=3800.0, mix=0.25, seed=4002)
    return _master_stereo(wet, target_peak_db=-0.8, fade_in_ms=6.0, fade_out_ms=35.0, bus_drive=1.35)


def synth_whoosh_deep() -> np.ndarray:
    """Deep dark cinema transition swoosh (wide stereo L->R sweeping noise + massive Doppler sub swell)."""
    rng = _rng(5001)
    dur = 1.18
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR
    peak_t = 0.48

    env = np.where(
        t < peak_t,
        np.exp(-((t - peak_t) / 0.21) ** 2),
        np.exp(-((t - peak_t) / 0.34) ** 2),
    )

    f_low_band = 110.0 + 1350.0 * (env ** 1.25)
    f_mid_band = 380.0 + 2400.0 * (env ** 1.55)
    n1 = _pink_noise(n, rng) * 0.7 + _brown_noise(n, rng) * 0.5
    n2 = _pink_noise(n, rng)

    sw_low = _resonant_filter_sweep(n1, f_low_band, q_curve=1.7, mode="bandpass") * env
    sw_mid = _resonant_filter_sweep(n2, f_mid_band, q_curve=2.1, mode="bandpass") * (env ** 1.3) * 0.60

    # Deep LFE cinema pressure wave
    f_sub = 34.0 + 62.0 * env
    sub = _soft_saturate(np.sin(2.0 * math.pi * np.cumsum(f_sub) / SR) * (env ** 1.15), drive=1.9) * 0.90

    pan_curve = np.tanh((t - peak_t) * 3.8) * 0.85
    dry = _stereo_pan(sw_low * 1.1 + sw_mid, pan_curve) + _stereo_pan(sub, pan_curve * 0.45)

    wet = _dark_hall_reverb(dry, decay_s=1.25, predelay_ms=14.0, damp_hz=2400.0, mix=0.38, seed=5002)
    return _master_stereo(wet, target_peak_db=-0.8, fade_in_ms=12.0, fade_out_ms=60.0, bus_drive=1.40)


def synth_riser_tension() -> np.ndarray:
    """2.5s psychological thriller tension riser (rising filtered noise + Shepard harmonic swell + sharp cutoff)."""
    rng = _rng(6001)
    build_s = 2.48
    tail_s = 0.14
    dur = build_s + tail_s
    n = int(dur * SR)
    nb = int(build_s * SR)
    t = np.arange(n, dtype=np.float64) / SR
    prog = np.clip(t / build_s, 0.0, 1.0)

    # Sharp breathless cutoff right at 2.48s
    gate = np.ones(n, dtype=np.float64)
    cut_fade = int(0.012 * SR)
    gate[nb - cut_fade : nb] = np.linspace(1.0, 0.0, cut_fade)
    gate[nb:] = 0.0

    # Accelerating exponential energy curve
    rise_env = (0.08 + 0.92 * (prog ** 2.15)) * gate

    # 1. Rising resonant noise sweep (180Hz -> 6800Hz, Q tightening 1.4 -> 5.2)
    f_noise = 180.0 * ((6800.0 / 180.0) ** (prog ** 1.45))
    q_noise = 1.4 + 3.8 * (prog ** 1.8)
    n_l = _resonant_filter_sweep(_pink_noise(n, rng), f_noise, q_noise, mode="bandpass")
    n_r = _resonant_filter_sweep(_pink_noise(n, rng), f_noise * 1.03, q_noise, mode="bandpass")

    # 2. Shepard-like overlapping eerie rising harmonic tones (dissonant thriller cluster)
    shep_l = np.zeros(n, dtype=np.float64)
    shep_r = np.zeros(n, dtype=np.float64)
    base_octaves = [55.0, 110.0, 220.0, 440.0]
    for idx, f0 in enumerate(base_octaves):
        # Rise 1.5 octaves smoothly; bell-shaped spectral window over frequency
        f_inst = f0 * (2.0 ** (1.65 * (prog ** 1.35)))
        # Spectral bell centered near 320Hz
        bell = np.exp(-0.5 * ((np.log2(f_inst / 320.0)) / 1.45) ** 2)
        ph_l = 2.0 * math.pi * np.cumsum(f_inst) / SR
        ph_r = 2.0 * math.pi * np.cumsum(f_inst * 1.006) / SR  # eerie stereo beating
        # Minor-second tension harmonic near climax
        f_tens = f_inst * 1.05946
        ph_t = 2.0 * math.pi * np.cumsum(f_tens) / SR
        shep_l += (np.sin(ph_l) + 0.45 * np.sin(2.0 * ph_l) + 0.30 * prog * np.sin(ph_t)) * bell
        shep_r += (np.sin(ph_r) + 0.45 * np.sin(2.0 * ph_r) + 0.30 * prog * np.sin(ph_t + 0.7)) * bell

    # 3. Accelerating psychological pulse tremor (3Hz -> 16Hz)
    pulse_f = 3.0 + 13.0 * (prog ** 1.8)
    trem = 0.72 + 0.28 * np.sin(2.0 * math.pi * np.cumsum(pulse_f) / SR)
    sub_swell = np.sin(2.0 * math.pi * np.cumsum(42.0 + 46.0 * prog) / SR) * (prog ** 1.7) * 0.65

    dry = np.column_stack([
        _soft_saturate((n_l * 0.75 + shep_l * 0.42 + sub_swell) * rise_env * trem, drive=1.9),
        _soft_saturate((n_r * 0.75 + shep_r * 0.42 + sub_swell) * rise_env * trem, drive=1.9),
    ])
    # Short room tail so the sharp cutoff still feels dramatic & airy
    wet = _dark_hall_reverb(dry, decay_s=0.45, predelay_ms=10.0, damp_hz=3400.0, mix=0.22, seed=6002)
    return _master_stereo(wet, target_peak_db=-0.7, fade_in_ms=25.0, fade_out_ms=25.0, bus_drive=1.40)


def synth_paper_flip() -> np.ndarray:
    """Crisp archival newspaper / dossier page snap & rustle."""
    rng = _rng(7001)
    dur = 0.38
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # Stage 1: Finger-lift initial friction rustle (0 - 95ms)
    e1 = np.exp(-((t - 0.048) / 0.032) ** 2)
    rustle1 = _butter(_white_noise(n, rng), (1800.0, 8500.0), "bandpass", order=3) * e1 * 0.55

    # Stage 2: Crisp page turn snap crack (at 108ms)
    dt2 = np.maximum(0.0, t - 0.098)
    e2 = np.where(t >= 0.098, (1.0 - np.exp(-dt2 / 0.0025)) * np.exp(-dt2 / 0.032), 0.0)
    snap = _butter(_white_noise(n, rng), (950.0, 6800.0), "bandpass", order=3) * e2 * 1.35
    # Paper body flex resonant thump (280Hz - 750Hz)
    flex = _butter(_pink_noise(n, rng), (260.0, 1200.0), "bandpass", order=2) * e2 * 0.85

    # Stage 3: Page settle flutter (145ms - 310ms)
    e3 = np.exp(-((t - 0.205) / 0.068) ** 2) * (0.65 + 0.35 * np.sin(2.0 * math.pi * 29.0 * t))
    settle = _butter(_white_noise(n, rng), (1400.0, 5600.0), "bandpass", order=2) * e3 * 0.45

    # Slight L -> R spatial page turn sweep
    pan = np.clip((t - 0.14) * 3.5, -0.55, 0.55)
    dry = _stereo_pan(rustle1 + snap + flex + settle, pan)
    wet = _dark_hall_reverb(dry, decay_s=0.35, predelay_ms=6.0, damp_hz=4500.0, mix=0.14, seed=7002)
    return _master_stereo(wet, target_peak_db=-0.9, fade_in_ms=2.0, fade_out_ms=25.0, bus_drive=1.25)


def synth_flash_impact() -> np.ndarray:
    """Crisp camera flash / pro cut-transition hit (tight transient click + warm sub punch + airy tail)."""
    rng = _rng(8001)
    dur = 0.62
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # 1. Razor-sharp bright flash transient burst
    flash_click = _butter(_white_noise(n, rng), (2200.0, 12500.0), "bandpass", order=3) * np.exp(-t / 0.022)
    # Subtle xenon flash capacitor micro-zing (4.6kHz -> 2.1kHz fast sweep)
    f_zing = 2100.0 + 2900.0 * np.exp(-t / 0.028)
    zing = np.sin(2.0 * math.pi * np.cumsum(f_zing) / SR) * np.exp(-t / 0.032) * 0.25

    # 2. Warm tight sub-kick punch (132Hz -> 44Hz)
    f_kick = 44.0 + 92.0 * np.exp(-t / 0.026)
    kick = _soft_saturate(np.sin(2.0 * math.pi * np.cumsum(f_kick) / SR) * np.exp(-t / 0.125), drive=2.2)

    # 3. Tight airy swoosh exhale
    air = _butter(_pink_noise(n, rng), (450.0, 4800.0), "bandpass", order=2) * np.exp(-t / 0.14) * 0.45

    dry = np.column_stack([
        flash_click * 0.85 + zing + kick * 1.15 + air,
        np.roll(flash_click, 11) * 0.85 + zing * 0.9 + kick * 1.15 + np.roll(air, 19),
    ])
    wet = _dark_hall_reverb(dry, decay_s=0.58, predelay_ms=10.0, damp_hz=4200.0, mix=0.26, seed=8002)
    return _master_stereo(wet, target_peak_db=-0.7, fade_in_ms=0.8, fade_out_ms=35.0, bus_drive=1.45)


def synth_heartbeat() -> np.ndarray:
    """Deep realistic double-thump lub-dub cinema heartbeat."""
    rng = _rng(9001)
    dur = 1.18
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    def _thump(t0: float, f_hi: float, f_lo: float, decay: float, amp: float) -> np.ndarray:
        dt = np.maximum(0.0, t - t0)
        mask = (t >= t0).astype(np.float64)
        f = f_lo + (f_hi - f_lo) * np.exp(-dt / 0.032)
        ph = 2.0 * math.pi * np.cumsum(f * mask) / SR
        env = mask * (1.0 - np.exp(-dt / 0.012)) * np.exp(-dt / decay)
        tone = np.sin(ph) * env + 0.25 * np.sin(2.0 * ph) * env * np.exp(-dt / 0.05)
        blood = _butter(_brown_noise(n, rng), 160.0, "lowpass", order=3) * env * 0.55
        return _soft_saturate(tone + blood, drive=2.1) * amp

    lub = _thump(0.03, 82.0, 35.0, 0.115, 1.00)
    dub = _thump(0.29, 98.0, 42.0, 0.095, 0.82)
    dry = _to_stereo(_butter(lub + dub, 240.0, "lowpass", order=3), delay_ms=0.65, side_gain=0.14)
    wet = _dark_hall_reverb(dry, decay_s=0.95, predelay_ms=14.0, damp_hz=520.0, mix=0.30, seed=9002)
    return _master_stereo(wet, target_peak_db=-0.8, fade_in_ms=3.0, fade_out_ms=65.0, bus_drive=1.40)


def synth_pop_bubble() -> np.ndarray:
    """Crisp, snappy modern motion-graphics pop."""
    rng = _rng(10001)
    dur = 0.22
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # Rapid upward pitch snap 240Hz -> 980Hz
    f = 240.0 + 760.0 * (1.0 - np.exp(-t / 0.022))
    ph = 2.0 * math.pi * np.cumsum(f) / SR
    env = (1.0 - np.exp(-t / 0.002)) * np.exp(-t / 0.036)
    body = (np.sin(ph) + 0.28 * np.sin(2.0 * ph)) * env
    snap = _butter(_white_noise(n, rng), (1800.0, 6200.0), "bandpass", order=2) * np.exp(-t / 0.008) * 0.30
    dry = _to_stereo(body + snap, delay_ms=0.4, side_gain=0.18)
    wet = _dark_hall_reverb(dry, decay_s=0.28, predelay_ms=5.0, damp_hz=4500.0, mix=0.14, seed=10002)
    return _master_stereo(wet, target_peak_db=-0.9, fade_in_ms=1.0, fade_out_ms=18.0, bus_drive=1.25)


def synth_glitch_digital() -> np.ndarray:
    """Punchy cyber/VHS digital data-corrupt glitch."""
    rng = _rng(11001)
    dur = 0.44
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    sig_l = np.zeros(n, dtype=np.float64)
    sig_r = np.zeros(n, dtype=np.float64)

    # Stuttered micro-slices with FM burst & sample-and-hold bit-crushing
    slice_len = int(0.028 * SR)
    for idx, s in enumerate(range(0, n, slice_len)):
        e = min(n, s + slice_len)
        ts = t[s:e]
        mode = idx % 4
        if mode == 0:
            # Harsh FM burst
            fc = 420.0 + (idx * 230.0) % 2400.0
            fm = np.sin(2.0 * math.pi * fc * ts + 4.5 * np.sin(2.0 * math.pi * (fc * 1.73) * ts))
            sig_l[s:e] = fm * 0.85
            sig_r[s:e] = np.roll(fm, 9) * 0.65
        elif mode == 1:
            # Sample-and-hold digital noise stutter
            step = max(4, 14 - (idx % 7))
            raw = rng.uniform(-1.0, 1.0, (e - s) // step + 1)
            crushed = np.repeat(raw, step)[: e - s]
            sig_l[s:e] = crushed * 0.55
            sig_r[s:e] = -crushed * 0.80
        elif mode == 2:
            # Micro dropout + sharp zap
            zap = np.sin(2.0 * math.pi * (2800.0 * np.exp(-(ts - ts[0]) / 0.012)) * (ts - ts[0]))
            sig_l[s:e] = zap * 0.35
            sig_r[s:e] = zap * 0.90
        else:
            # Low sub-glitch thud
            thud = np.sin(2.0 * math.pi * 92.0 * ts) * np.exp(-(ts - ts[0]) / 0.015)
            sig_l[s:e] = thud * 0.9
            sig_r[s:e] = thud * 0.9

    env = (1.0 - np.exp(-t / 0.002)) * np.exp(-np.maximum(0.0, t - 0.24) / 0.085)
    dry = np.column_stack([
        _butter(sig_l * env, (70.0, 8800.0), "bandpass", order=2),
        _butter(sig_r * env, (70.0, 8800.0), "bandpass", order=2),
    ])
    return _master_stereo(dry, target_peak_db=-0.9, fade_in_ms=1.0, fade_out_ms=20.0, bus_drive=1.45)


def synth_camera_shutter() -> np.ndarray:
    """Realistic 35mm / DSLR mechanical archival camera shutter click-clack."""
    rng = _rng(12001)
    dur = 0.30
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    def _mech_hit(t0: float, f_body: float, f_hi: float, dec: float, amp: float) -> np.ndarray:
        dt = np.maximum(0.0, t - t0)
        m = (t >= t0).astype(np.float64)
        e_fast = m * np.exp(-dt / dec)
        e_body = m * np.exp(-dt / (dec * 2.2))
        click = _butter(_white_noise(n, rng), (f_hi * 0.5, min(14000.0, f_hi * 2.4)), "bandpass", order=3) * e_fast
        body = np.sin(2.0 * math.pi * f_body * dt) * e_body * 0.55
        metal = np.sin(2.0 * math.pi * (f_hi * 0.72) * dt) * np.exp(-dt / (dec * 0.9)) * m * 0.30
        return (click + body + metal) * amp

    # Mirror-up click at 2ms + focal-plane curtain clack at 52ms + micro spring settle at 98ms
    c1 = _mech_hit(0.002, 260.0, 4600.0, 0.0085, 1.00)
    c2 = _mech_hit(0.052, 195.0, 3400.0, 0.0110, 0.88)
    c3 = _mech_hit(0.098, 420.0, 5800.0, 0.0060, 0.28)
    dry = _stereo_pan(c1, -0.18) + _stereo_pan(c2, +0.20) + _stereo_pan(c3, 0.0)
    wet = _dark_hall_reverb(dry, decay_s=0.32, predelay_ms=6.0, damp_hz=4200.0, mix=0.14, seed=12002)
    return _master_stereo(wet, target_peak_db=-0.8, fade_in_ms=0.5, fade_out_ms=22.0, bus_drive=1.35)


def synth_cash_chime() -> np.ndarray:
    """Crisp luxury metallic coin/chime swell (rich FM bell chord + stereo shimmer)."""
    rng = _rng(13001)
    dur = 1.02
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # E major / bright luxury bell intervals staggered slightly like a crisp arpeggio/coin ring
    notes = [
        (0.000, 1318.51, 0.65, -0.35),  # E6
        (0.032, 1975.53, 0.72, +0.35),  # B6
        (0.068, 2637.02, 0.85, -0.10),  # E7
        (0.070, 3322.44, 0.45, +0.25),  # G#7 sparkle
    ]
    st = np.zeros((n, 2), dtype=np.float64)
    for t0, freq, amp, pan in notes:
        dt = np.maximum(0.0, t - t0)
        m = (t >= t0).astype(np.float64)
        env = m * (1.0 - np.exp(-dt / 0.002)) * np.exp(-dt / 0.34)
        # FM metallic shimmer
        mod = np.sin(2.0 * math.pi * (freq * 2.41) * dt) * np.exp(-dt / 0.065) * 1.4
        bell = (np.sin(2.0 * math.pi * freq * dt + mod) + 0.35 * np.sin(2.0 * math.pi * (freq * 1.003) * dt)) * env * amp
        st += _stereo_pan(bell, pan)

    # Crisp metallic coin attack transient
    ping = _butter(_white_noise(n, rng), (4500.0, 12000.0), "bandpass", order=2) * np.exp(-t / 0.012) * 0.28
    st[:, 0] += ping
    st[:, 1] += np.roll(ping, 8)

    wet = _dark_hall_reverb(st, decay_s=0.85, predelay_ms=10.0, damp_hz=6500.0, mix=0.30, seed=13002)
    return _master_stereo(wet, target_peak_db=-0.8, fade_in_ms=1.0, fade_out_ms=55.0, bus_drive=1.20)


def synth_typing_tick() -> np.ndarray:
    """Crisp vintage investigative typewriter / mechanical keystrike."""
    rng = _rng(14001)
    dur = 0.09
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    key_snap = _butter(_white_noise(n, rng), (2400.0, 9200.0), "bandpass", order=3) * np.exp(-t / 0.0055)
    platen_thud = np.sin(2.0 * math.pi * (240.0 + 180.0 * np.exp(-t / 0.008)) * t) * np.exp(-t / 0.014) * 0.72
    metal_ping = np.sin(2.0 * math.pi * 3850.0 * t) * np.exp(-t / 0.009) * 0.32
    dry = _to_stereo(key_snap * 0.95 + platen_thud + metal_ping, delay_ms=0.25, side_gain=0.14)
    return _master_stereo(dry, target_peak_db=-0.9, fade_in_ms=0.4, fade_out_ms=10.0, bus_drive=1.30)


def synth_ui_click() -> np.ndarray:
    """Sleek modern documentary HUD / dossier pin tactile click."""
    rng = _rng(15001)
    dur = 0.11
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # Tactile woodblock-like ping + crisp micro-transient
    f = 780.0 + 620.0 * np.exp(-t / 0.005)
    ping = np.sin(2.0 * math.pi * np.cumsum(f) / SR) * np.exp(-t / 0.015)
    tick = _butter(_white_noise(n, rng), (2600.0, 9500.0), "bandpass", order=2) * np.exp(-t / 0.004) * 0.65
    dry = _to_stereo(ping * 0.95 + tick, delay_ms=0.3, side_gain=0.16)
    return _master_stereo(dry, target_peak_db=-0.9, fade_in_ms=0.4, fade_out_ms=12.0, bus_drive=1.25)


_SFX_BUILDERS = {
    "sub_boom.wav": synth_sub_boom,
    "horror_braam.wav": synth_horror_braam,
    "cinematic_hit.wav": synth_cinematic_hit,
    "whoosh_fast.wav": synth_whoosh_fast,
    "whoosh_deep.wav": synth_whoosh_deep,
    "riser_tension.wav": synth_riser_tension,
    "paper_flip.wav": synth_paper_flip,
    "flash_impact.wav": synth_flash_impact,
    "heartbeat.wav": synth_heartbeat,
    "pop_bubble.wav": synth_pop_bubble,
    "glitch_digital.wav": synth_glitch_digital,
    "camera_shutter.wav": synth_camera_shutter,
    "cash_chime.wav": synth_cash_chime,
    "typing_tick.wav": synth_typing_tick,
    "ui_click.wav": synth_ui_click,
}


# ---------------------------------------------------------------------------
# Dark Mystery / Horror Cinema Music Bed (45s Seamless Broadcast Stereo MP3)
# ---------------------------------------------------------------------------
def synthesize_dark_mystery_horror_music(
    out_mp3: Path = MUSIC_DIR / "dark_mystery_horror.mp3",
    duration_s: float = 45.0,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Synthesize a seamless 45s dark ambient mystery/horror cinema music bed:
    - Deep bowed cello/contrabass drone evolving across D minor / Phrygian harmony
    - Haunting sparse minor piano / celesta-bell motifs with cathedral decay
    - Subtle dark tension sub-pulse (68 BPM) + eerie air texture
    - Equal-power seamless loop splice + FFmpeg broadcast stereo 48kHz MP3 master.
    """
    out_mp3 = Path(out_mp3)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    rng = _rng(77001)

    xfade_s = 3.0
    raw_dur = duration_s + xfade_s
    n = int(raw_dur * SR)
    t = np.arange(n, dtype=np.float64) / SR

    # 1. Deep Cello / Contrabass Drone Pad (4 harmonic acts across 48s in D minor / Phrygian)
    # Slow breathing progression: Dm -> Dm(add b9) -> Bbmaj7/D -> A7sus4/D
    # Root D1=36.71, D2=73.42, A2=110.00, moving voice F2(87.31) -> Eb2(77.78) -> F2(87.31) -> E2(82.41)
    prog_times = np.array([0.0, 11.0, 13.0, 23.0, 25.0, 35.0, 37.0, raw_dur])
    mov_freqs = np.array([87.31, 87.31, 77.78, 77.78, 92.50, 92.50, 82.41, 87.31])
    mov_f_curve = np.interp(t, prog_times, mov_freqs)

    upper_times = np.array([0.0, 12.0, 24.0, 36.0, raw_dur])
    upper_freqs = np.array([174.61, 155.56, 164.81, 146.83, 174.61])  # F3 -> Eb3 -> E3 -> D3 -> F3
    upper_f_curve = np.interp(t, upper_times, upper_freqs)

    def _bowed_string(freq_or_curve: Any, detune_ratio: float, vib_hz: float, ph_off: float) -> np.ndarray:
        vib = 1.0 + 0.0028 * np.sin(2.0 * math.pi * vib_hz * t + ph_off)
        f = np.asarray(freq_or_curve, dtype=np.float64) * detune_ratio * vib
        if f.ndim == 0:
            ph = 2.0 * math.pi * float(f) * t + ph_off
        else:
            ph = 2.0 * math.pi * np.cumsum(f) / SR + ph_off
        # Warm cello harmonic spectrum (fundamental + rich 2nd, 3rd, 4th, 5th)
        return (
            0.55 * np.sin(ph)
            + 0.28 * np.sin(2.0 * ph)
            + 0.16 * np.sin(3.0 * ph)
            + 0.09 * np.sin(4.0 * ph)
            + 0.05 * np.sin(5.0 * ph)
        )

    sub_drone = np.sin(2.0 * math.pi * 36.71 * t) * (0.78 + 0.22 * np.sin(2.0 * math.pi * 0.08 * t))
    cello_l = (
        _bowed_string(73.42, 0.9985, 0.31, 0.2) * 0.55
        + _bowed_string(110.00, 1.0018, 0.27, 1.1) * 0.34
        + _bowed_string(mov_f_curve, 0.9990, 0.23, 2.0) * 0.42
        + _bowed_string(upper_f_curve, 1.0022, 0.37, 0.6) * 0.22
    )
    cello_r = (
        _bowed_string(73.42, 1.0016, 0.29, 0.9) * 0.55
        + _bowed_string(110.00, 0.9983, 0.33, 1.7) * 0.34
        + _bowed_string(mov_f_curve, 1.0014, 0.26, 2.5) * 0.42
        + _bowed_string(upper_f_curve, 0.9978, 0.35, 1.3) * 0.22
    )

    # Slow breathing low-pass sweep keeps vocal intelligibility pocket (1-3.5kHz) super clean
    lp_curve = 310.0 + 240.0 * (0.5 + 0.5 * np.sin(2.0 * math.pi * (t / 15.0) - 0.6))
    drone_l = _resonant_filter_sweep(cello_l, lp_curve, q_curve=1.05, mode="lowpass", block=256)
    drone_r = _resonant_filter_sweep(cello_r, lp_curve * 1.04, q_curve=1.05, mode="lowpass", block=256)
    drone_st = np.column_stack([
        _soft_saturate(drone_l * 0.85 + sub_drone * 0.48, drive=1.5),
        _soft_saturate(drone_r * 0.85 + sub_drone * 0.48, drive=1.5),
    ])

    # 2. Haunting Sparse Minor Piano / Celesta-Bell Motifs (D minor / Phrygian eerie phrases)
    # Note frequencies: A4=440, Bb4=466.16, C#5=554.37, D5=587.33, Eb5=622.25, E5=659.25, F5=698.46, A5=880.0
    motif_events: List[Tuple[float, float, float, float]] = [
        # Phrase 1 (Mystery open)
        (1.8, 587.33, 0.42, -0.35),   # D5
        (3.5, 698.46, 0.36, +0.28),   # F5
        (5.4, 659.25, 0.34, -0.22),   # E5
        (7.8, 466.16, 0.38, +0.35),   # Bb4
        # Phrase 2 (Phrygian chill)
        (12.2, 440.00, 0.40, -0.30),  # A4
        (14.0, 587.33, 0.38, +0.30),  # D5
        (15.9, 622.25, 0.44, -0.40),  # Eb5 (eerie half-step!)
        (18.6, 440.00, 0.36, +0.20),  # A4
        # Phrase 3 (High celesta music-box dread — iconic dark winter/horror feel!)
        (23.5, 880.00, 0.30, +0.38),  # A5
        (25.1, 698.46, 0.34, -0.32),  # F5
        (26.8, 659.25, 0.32, +0.26),  # E5
        (28.5, 587.33, 0.40, -0.25),  # D5
        (30.9, 554.37, 0.38, +0.35),  # C#5 (harmonic minor tension!)
        # Phrase 4 (Resolution back into loop)
        (35.8, 587.33, 0.40, -0.28),  # D5
        (37.9, 622.25, 0.34, +0.32),  # Eb5
        (40.2, 587.33, 0.38, -0.18),  # D5
        (42.6, 440.00, 0.34, +0.22),  # A4
    ]
    piano_st = np.zeros((n, 2), dtype=np.float64)
    for t0, freq, amp, pan in motif_events:
        idx0 = int(t0 * SR)
        note_len = min(n - idx0, int(4.2 * SR))
        if note_len <= 100:
            continue
        tn = np.arange(note_len, dtype=np.float64) / SR
        # Realistic felt-piano / haunting celesta envelope & gentle inharmonic overtone decay
        atk = 1.0 - np.exp(-tn / 0.009)
        body = (
            0.70 * np.sin(2.0 * math.pi * freq * tn) * np.exp(-tn / 1.85)
            + 0.24 * np.sin(2.0 * math.pi * (freq * 2.001) * tn) * np.exp(-tn / 0.95)
            + 0.11 * np.sin(2.0 * math.pi * (freq * 3.004) * tn) * np.exp(-tn / 0.48)
            + 0.06 * np.sin(2.0 * math.pi * (freq * 0.5) * tn) * np.exp(-tn / 2.2)
        ) * atk
        # Soft felt hammer thud
        hammer = np.sin(2.0 * math.pi * (freq * 4.2) * tn) * np.exp(-tn / 0.018) * 0.09
        note_mono = (body + hammer) * amp
        st_n = _stereo_pan(note_mono, pan)
        piano_st[idx0 : idx0 + note_len] += st_n

    # Drench piano/celesta motifs in cavernous dark cathedral reverb
    piano_wet = _dark_hall_reverb(piano_st, decay_s=2.8, predelay_ms=28.0, damp_hz=2600.0, mix=0.62, seed=77002)

    # 3. Subtle Tension Pulse (68 BPM muted cinema pulse + ghostly wind bed)
    bpm = 68.0
    beat_s = 60.0 / bpm
    pulse_mono = np.zeros(n, dtype=np.float64)
    # Build tension gently after first 4s
    pulse_t = 0.0
    beat_idx = 0
    while pulse_t < raw_dur - 0.5:
        idx0 = int(pulse_t * SR)
        pl = min(n - idx0, int(0.42 * SR))
        if pl > 64:
            tp = np.arange(pl, dtype=np.float64) / SR
            accent = 1.0 if (beat_idx % 4 == 0) else (0.58 if (beat_idx % 2 == 0) else 0.28)
            f_p = 36.71 + 26.0 * np.exp(-tp / 0.045)
            p_wave = np.sin(2.0 * math.pi * np.cumsum(f_p) / SR) * (1.0 - np.exp(-tp / 0.012)) * np.exp(-tp / 0.14)
            # Subtle muted clockwork tick on off-beats
            tick = np.sin(2.0 * math.pi * 1120.0 * tp) * np.exp(-tp / 0.008) * (0.04 if beat_idx % 2 else 0.015)
            pulse_mono[idx0 : idx0 + pl] += (p_wave * 0.42 * accent + tick)
        pulse_t += beat_s
        beat_idx += 1

    # Eerie cold winter/cave wind texture (subtle stereo swirl)
    wind_l = _butter(_pink_noise(n, rng), (180.0, 950.0), "bandpass", order=2) * (0.06 + 0.04 * np.sin(2.0 * math.pi * 0.09 * t))
    wind_r = _butter(_pink_noise(n, rng), (210.0, 1020.0), "bandpass", order=2) * (0.06 + 0.04 * np.cos(2.0 * math.pi * 0.07 * t))

    pulse_st = _to_stereo(pulse_mono, delay_ms=0.8, side_gain=0.12)
    mix_raw = drone_st * 0.72 + piano_wet * 0.64 + pulse_st * 0.56 + np.column_stack([wind_l, wind_r])

    # Subtle overall hall glue
    mix_glued = _dark_hall_reverb(mix_raw, decay_s=1.8, predelay_ms=20.0, damp_hz=2000.0, mix=0.22, seed=77003)

    # 4. Seamless equal-power loop splice (last xfade_s crossfaded into first xfade_s -> exact duration_s)
    n_out = int(duration_s * SR)
    n_xf = min(int(xfade_s * SR), n - n_out)
    looped = mix_glued[:n_out].copy()
    if n_xf > 0:
        fade_in = np.sin(np.linspace(0.0, math.pi * 0.5, n_xf))[:, None]
        fade_out = np.cos(np.linspace(0.0, math.pi * 0.5, n_xf))[:, None]
        looped[:n_xf] = looped[:n_xf] * fade_in + mix_glued[n_out : n_out + n_xf] * fade_out

    mastered = _master_stereo(looped, target_peak_db=-1.5, fade_in_ms=8.0, fade_out_ms=8.0, bus_drive=1.20)
    tmp_wav = out_mp3.with_suffix(".tmp.wav")
    _write_wav_stereo(tmp_wav, mastered)
    try:
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(tmp_wav),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=9",
                "-ar",
                str(SR),
                "-ac",
                "2",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(out_mp3),
            ],
            thermal_limit_c=thermal_limit_c,
        )
    finally:
        tmp_wav.unlink(missing_ok=True)
    return out_mp3


# ---------------------------------------------------------------------------
# Public API: ensure_pro_cinema_sfx & select_music_for_mood
# ---------------------------------------------------------------------------
def ensure_pro_cinema_sfx(force: bool = False, thermal_limit_c: float = 85.0) -> Dict[str, Any]:
    """Ensure all 15 upgraded 48kHz stereo cinema SFX in `assets/sfx/` and
    `assets/music/dark_mystery_horror.mp3` exist at Pro Cinema v3 quality.
    """
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    current_ver = ""
    if VERSION_STAMP_FILE.exists():
        try:
            current_ver = str(json.loads(VERSION_STAMP_FILE.read_text(encoding="utf-8")).get("version", ""))
        except Exception:
            current_ver = ""

    need_upgrade = force or (current_ver != PRO_SFX_VERSION)
    generated: List[str] = []
    sfx_map: Dict[str, str] = {}

    for fname in ALL_SFX_NAMES:
        fpath = SFX_DIR / fname
        if need_upgrade or not fpath.exists() or fpath.stat().st_size < 4096:
            stereo = _SFX_BUILDERS[fname]()
            _write_wav_stereo(fpath, stereo)
            generated.append(fname)
        sfx_map[fname] = str(fpath)

    dark_music = MUSIC_DIR / "dark_mystery_horror.mp3"
    if need_upgrade or not dark_music.exists() or dark_music.stat().st_size < 100_000:
        synthesize_dark_mystery_horror_music(dark_music, duration_s=45.0, thermal_limit_c=thermal_limit_c)
        generated.append("dark_mystery_horror.mp3")

    VERSION_STAMP_FILE.write_text(
        json.dumps(
            {
                "version": PRO_SFX_VERSION,
                "sample_rate": SR,
                "channels": 2,
                "sfx_count": len(sfx_map),
                "dark_music": str(dark_music),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    music_map = {p.name: str(p) for p in sorted(MUSIC_DIR.glob("*.mp3"))}
    return {
        "version": PRO_SFX_VERSION,
        "sfx": sfx_map,
        "music": music_map,
        "generated": generated,
    }


def _norm_text(s: str) -> str:
    raw = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", raw.lower()).strip()


_DARK_HORROR_KEYWORDS = (
    "dark_horror",
    "horror",
    "terror",
    "macabr",
    "sombri",
    "sinistr",
    "assombr",
    "misteri",
    "mystery",
    "true_crime",
    "true crime",
    "crime",
    "assassin",
    "murder",
    "killer",
    "serial",
    "krampus",
    "saturnalia",
    "occult",
    "ocult",
    "ritual",
    "maldicao",
    "curse",
    "demon",
    "diabo",
    "fantasm",
    "ghost",
    "haunt",
    "creepy",
    "scary",
    "medo",
    "pesadelo",
    "nightmare",
    "desaparec",
    "vanish",
    "seita",
    "cult",
    "morte",
    "dead",
    "death",
    "sangue",
    "blood",
    "halloween",
    "brux",
    "witch",
    "folclore",
    "folklore",
    "lenda urbana",
    "urban legend",
    "abandoned",
    "abandonad",
    "bizarro",
    "perturbador",
    "disturbing",
    "conspirac",
    "proibid",
    "forbidden",
    "segredo oculto",
    "dark secret",
)

_DARK_PULSE_KEYWORDS = (
    "dark_pulse",
    "thriller",
    "fraude",
    "fraud",
    "colapso",
    "collapse",
    "banco",
    "bank",
    "bilhao",
    "bilhoes",
    "billion",
    "wall street",
    "mercado",
    "crise",
    "crash",
    "escandalo",
    "scandal",
    "corrup",
    "mafia",
    "cartel",
    "esquema",
    "piramide",
    "lavagem",
    "hack",
    "cyber",
    "espion",
    "espionage",
    "cia",
    "fbi",
    "mossad",
    "dossie",
    "dossier",
    "barings",
    "enron",
    "ftx",
)

_LOFI_KEYWORDS = (
    "lo_fi",
    "lofi",
    "estudo",
    "study",
    "rotina",
    "habito",
    "habit",
    "produtiv",
    "relax",
    "calmo",
    "calm",
    "meditac",
    "minimalis",
    "leitura",
)

_CORPORATE_KEYWORDS = (
    "corporate",
    "empresa",
    "negocio",
    "business",
    "b2b",
    "vendas",
    "sales",
    "marketing",
    "startup",
    "empreend",
    "gestao",
    "estrategia",
    "saas",
    "ia ",
    "inteligencia artificial",
)


def select_music_for_mood(
    topic: str,
    default_file: str = "epic_doc.mp3",
    mood: str = "",
) -> Path:
    """Select the best matching cinema music bed for a topic and/or explicit mood token."""
    combined = _norm_text(f"{mood} {topic}")

    dark_horror_path = MUSIC_DIR / "dark_mystery_horror.mp3"
    if any(kw in combined for kw in _DARK_HORROR_KEYWORDS):
        if not dark_horror_path.exists():
            synthesize_dark_mystery_horror_music(dark_horror_path)
        return dark_horror_path

    dark_pulse_path = MUSIC_DIR / "dark_pulse.mp3"
    if any(kw in combined for kw in _DARK_PULSE_KEYWORDS) and dark_pulse_path.exists():
        return dark_pulse_path

    lofi_path = MUSIC_DIR / "lo_fi_study.mp3"
    if any(kw in combined for kw in _LOFI_KEYWORDS) and lofi_path.exists():
        return lofi_path

    corp_path = MUSIC_DIR / "corporate_focus.mp3"
    if any(kw in combined for kw in _CORPORATE_KEYWORDS) and corp_path.exists():
        return corp_path

    fallback = MUSIC_DIR / default_file
    if fallback.exists():
        return fallback
    for cand in ("epic_doc.mp3", "dark_pulse.mp3", "dark_mystery_horror.mp3", "corporate_focus.mp3"):
        p = MUSIC_DIR / cand
        if p.exists():
            return p
    return synthesize_dark_mystery_horror_music(dark_horror_path)


if __name__ == "__main__":
    res = ensure_pro_cinema_sfx(force=True, thermal_limit_c=95.0)
    print(json.dumps(res, indent=2, ensure_ascii=False))
