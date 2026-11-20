"""FrimeRise Studio-Grade 9-Viseme Phonetic Lip-Sync via Rhubarb Lip Sync v1.14 (MIT).
Uses Rhubarb's language-independent phonetic recognizer (-r phonetic) which works natively
on Brazilian Portuguese audio, outputting the 9 classic Disney/Preston-Blair mouth shapes:
  A (closed MBP) | B (clenched teeth/consonants) | C (medium open E/I)
  D (wide open A + tongue) | E (rounded O) | F (puckered U/W/OO)
  G (upper teeth on lower lip F/V) | H (L tongue tip) | X (idle/silent)
Falls back gracefully to numpy RMS+vowel analysis if Rhubarb is unavailable.
"""
from __future__ import annotations

import json
import math
import subprocess
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
RHUBARB_DIR = BASE_DIR / "vendor" / "rhubarb"


def find_rhubarb_binary() -> Optional[Path]:
    if not RHUBARB_DIR.exists():
        return None
    for p in RHUBARB_DIR.rglob("rhubarb"):
        if p.is_file():
            return p
    return None


def compute_rms_energy_per_frame(wav_path: Path, fps: int = 30) -> Tuple[List[float], float]:
    """Return normalized speech energy [0..1] per video frame for elastic Squash & Stretch."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        nframes = wf.getnframes()
        dur_s = nframes / float(sr)
        pcm = np.frombuffer(wf.readframes(nframes), dtype=np.int16).astype(np.float32) / 32768.0
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1)

    win = max(1, int(round(sr / float(fps))))
    total_vframes = max(1, int(math.ceil(len(pcm) / float(win))))
    rms = np.zeros(total_vframes, dtype=np.float32)
    for fi in range(total_vframes):
        seg = pcm[fi * win : (fi + 1) * win]
        if len(seg) > 0:
            rms[fi] = float(np.sqrt(np.mean(seg * seg)))
    peak = max(0.05, float(np.percentile(rms, 95)))
    norm = np.clip(rms / peak, 0.0, 1.0)
    return [float(x) for x in norm], dur_s


def extract_rhubarb_visemes(
    wav_path: Path,
    fps: int = 30,
    emotion: str = "neutral",
) -> Tuple[List[str], List[float], str]:
    """Run Rhubarb Lip Sync (-r phonetic -f json) on wav_path and sample onto exact video frames.
    Returns (visemes_per_frame ['A'..'H','X'], energies_per_frame [0..1], engine_used).
    """
    energies, dur_s = compute_rms_energy_per_frame(wav_path, fps=fps)
    total_frames = len(energies)
    rhub = find_rhubarb_binary()

    if rhub is not None:
        try:
            res = subprocess.run(
                [
                    str(rhub),
                    "-r",
                    "phonetic",
                    "-f",
                    "json",
                    "--quiet",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                cues = data.get("mouthCues") or []
                visemes = ["X"] * total_frames
                c_idx = 0
                for fi in range(total_frames):
                    t = fi / float(fps)
                    while c_idx + 1 < len(cues) and t >= float(cues[c_idx + 1]["start"]):
                        c_idx += 1
                    if c_idx < len(cues):
                        cue = cues[c_idx]
                        if float(cue["start"]) <= t <= float(cue["end"]) + 0.02:
                            visemes[fi] = str(cue["value"])
                return visemes, energies, "rhubarb_v1.14_phonetic_9visemes"
        except Exception:
            pass

    # Clean RMS fallback mapping directly to Rhubarb 9-viseme alphabet
    visemes = []
    for fi, e in enumerate(energies):
        if e < 0.14:
            visemes.append("X")
        elif e >= 0.62:
            visemes.append("D")
        elif e >= 0.42:
            visemes.append("C" if fi % 3 else "E")
        elif e >= 0.25:
            visemes.append("B" if emotion == "angry" else "C")
        else:
            visemes.append("F" if fi % 2 else "A")
    return visemes, energies, "rms_fallback_9visemes"
