"""FrimeRise Zero-Copyright Original Music & Asset Vault (engine/flow_vault.py).

Manages `data/flow_vault/` and `data/flow_vault/vault_index.json`:
- Indexes generated instrumental tracks from `flowmusic.app` / broadcast DSP synthesizer
- Indexes generated scene images (`Nano Banana 2` / Character Sheets / Pollinations / Skia)
- Indexes generated video clips (`Veo 3.1 Light` / `Omni 1.1 Flash`) by mood/prompt SHA-256 hash
- Guarantees 0-credit reuse whenever a matching mood or visual prompt has already been generated
- Provides `async def fetch_or_generate_flow_music(mood: str, duration_s: float = 30.0) -> Path`
  delivering a 48kHz stereo broadcast instrumental track ready for `-14 LUFS` `sidechaincompress`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import signal

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from engine.intel_vaapi import run_ffmpeg_safe
except Exception:  # pragma: no cover
    def run_ffmpeg_safe(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)


VAULT_DIR = BASE_DIR / "data" / "flow_vault"
VAULT_MUSIC_DIR = VAULT_DIR / "music"
VAULT_IMAGES_DIR = VAULT_DIR / "images"
VAULT_VEO_DIR = VAULT_DIR / "veo_clips"
VAULT_CHARACTERS_DIR = VAULT_DIR / "character_sheets"
VAULT_INDEX_PATH = VAULT_DIR / "vault_index.json"

SAMPLE_RATE = 48000

# ---------------------------------------------------------------------------
# Musical Mood Profiles (48kHz Broadcast Stereo Instrumental Beds)
# ---------------------------------------------------------------------------
_DARK_HORROR_PROFILE: Dict[str, Any] = {
    "bpm": 66.0,
    "key": "D Minor / D Dorian (4-Movement Evolving Score: Clockwork, Bowed Cello & Lute, Muted Brass & Felt Piano)",
    "chords": [
        [146.83, 174.61, 220.00, 293.66],  # Dm (D3, F3, A3, D4)
        [116.54, 174.61, 233.08, 293.66],  # Bb (Bb2, F3, Bb3, D4)
        [138.59, 174.61, 207.65, 293.66],  # G#dim/D (C#3, F3, G#3, D4)
        [110.00, 164.81, 207.65, 277.18],  # A7(b9) tension (A2, E3, G#3, C#4)
    ],
    "ostinato_notes": [146.83, 174.61, 220.00, 233.08, 220.00, 207.65, 220.00, 174.61],
    "celesta_notes": [587.33, 698.46, 880.00, 932.33, 880.00, 830.61, 698.46, 659.25],
    "bell_notes": [293.66, 233.08, 293.66, 220.00],
    "bass_notes": [73.42, 58.27, 65.41, 55.00],
    "motif_intervals": [1.0, 1.189, 1.498, 1.587, 1.498, 1.414, 1.189, 1.122],
    "cutoff_hz": 5200.0,
    "sub_drive": 1.55,
    "perc_style": "horror_heartbeat",
}

_DARK_INVESTIGATIVE_PROFILE: Dict[str, Any] = {
    "bpm": 88.0,
    "key": "D Minor (Dorian/Aeolian Investigative Cello & Pulse)",
    "chords": [
        [146.83, 174.61, 220.00, 261.63],  # Dm7
        [130.81, 164.81, 196.00, 246.94],  # Cmaj7/E tension
        [116.54, 146.83, 174.61, 220.00],  # Bbmaj7
        [110.00, 138.59, 164.81, 207.65],  # A7alt
    ],
    "ostinato_notes": [146.83, 220.00, 174.61, 220.00, 233.08, 220.00, 174.61, 164.81],
    "celesta_notes": [587.33, 659.25, 698.46, 880.00, 698.46, 659.25, 587.33, 554.37],
    "bell_notes": [293.66, 261.63, 233.08, 220.00],
    "bass_notes": [73.42, 65.41, 58.27, 55.00],
    "motif_intervals": [1.0, 1.189, 1.498, 1.335, 1.0, 1.782, 1.498, 1.189],
    "cutoff_hz": 5800.0,
    "sub_drive": 1.55,
    "perc_style": "investigative_pulse",
}

_HISTORICAL_EPIC_PROFILE: Dict[str, Any] = {
    "bpm": 76.0,
    "key": "D Minor / C Minor (Historical Epic Strings & Cathedral Bells)",
    "chords": [
        [146.83, 174.61, 220.00, 293.66],  # Dm
        [116.54, 146.83, 174.61, 233.08],  # Bb
        [130.81, 164.81, 196.00, 261.63],  # C
        [110.00, 138.59, 164.81, 220.00],  # A
    ],
    "ostinato_notes": [146.83, 174.61, 220.00, 293.66, 233.08, 220.00, 174.61, 164.81],
    "celesta_notes": [587.33, 880.00, 698.46, 659.25, 587.33, 932.33, 880.00, 698.46],
    "bell_notes": [293.66, 233.08, 261.63, 220.00],
    "bass_notes": [73.42, 58.27, 65.41, 55.00],
    "motif_intervals": [1.0, 1.498, 2.0, 1.782, 1.498, 1.189, 1.0, 0.749],
    "cutoff_hz": 6400.0,
    "sub_drive": 1.65,
    "perc_style": "cinema_taiko",
}

MOOD_PROFILES: Dict[str, Dict[str, Any]] = {
    "dark_horror_cinema": _DARK_HORROR_PROFILE,
    "dark_mystery": dict(_DARK_HORROR_PROFILE),
    "dark_investigative": _DARK_INVESTIGATIVE_PROFILE,
    "investigative_pulse": dict(_DARK_INVESTIGATIVE_PROFILE),
    "epic_cinema": _HISTORICAL_EPIC_PROFILE,
    "historical_epic": dict(_HISTORICAL_EPIC_PROFILE),
    "cyber_corporate": {
        "bpm": 120.0,
        "key": "F# Minor (Cyber-Luxury SaaS & B2B)",
        "chords": [
            [185.00, 220.00, 277.18, 329.63],  # F#m7
            [146.83, 185.00, 220.00, 277.18],  # Dmaj7
            [164.81, 207.65, 246.94, 329.63],  # E6
            [138.59, 164.81, 207.65, 277.18],  # C#m7
        ],
        "bass_notes": [92.50, 73.42, 82.41, 69.30],
        "motif_intervals": [1.0, 1.335, 1.498, 2.0, 1.498, 1.335, 1.189, 1.498],
        "cutoff_hz": 7800.0,
        "sub_drive": 1.40,
        "perc_style": "modern_tech",
    },
    "bouncy_cartoon": {
        "bpm": 126.0,
        "key": "G Major (2D Cartoon Comedy Groove)",
        "chords": [
            [196.00, 246.94, 293.66, 392.00],  # G
            [164.81, 196.00, 246.94, 329.63],  # Em
            [130.81, 164.81, 196.00, 261.63],  # C
            [146.83, 185.00, 220.00, 293.66],  # D7
        ],
        "bass_notes": [98.00, 82.41, 65.41, 73.42],
        "motif_intervals": [1.0, 1.260, 1.498, 2.0, 1.682, 1.498, 1.260, 1.0],
        "cutoff_hz": 8200.0,
        "sub_drive": 1.20,
        "perc_style": "bouncy_pizzicato",
    },
    "lofi_velvet": {
        "bpm": 84.0,
        "key": "A Minor 9 (Warm Storytime Lo-Fi)",
        "chords": [
            [220.00, 261.63, 329.63, 392.00],  # Am7
            [146.83, 174.61, 220.00, 261.63],  # Dm7
            [196.00, 246.94, 293.66, 349.23],  # G7
            [130.81, 164.81, 196.00, 246.94],  # Cmaj7
        ],
        "bass_notes": [110.00, 73.42, 98.00, 65.41],
        "motif_intervals": [1.0, 1.189, 1.498, 1.782, 1.498, 1.189, 1.0, 0.891],
        "cutoff_hz": 4100.0,
        "sub_drive": 1.25,
        "perc_style": "lofi_boom_bap",
    },
    "viral_momentum": {
        "bpm": 128.0,
        "key": "E Minor (High-Retention Viral Hook)",
        "chords": [
            [164.81, 196.00, 246.94, 329.63],  # Em
            [130.81, 164.81, 196.00, 261.63],  # C
            [146.83, 185.00, 220.00, 293.66],  # D
            [123.47, 155.56, 185.00, 246.94],  # Bm
        ],
        "bass_notes": [82.41, 65.41, 73.42, 61.74],
        "motif_intervals": [1.0, 1.498, 1.335, 2.0, 1.498, 1.782, 1.498, 1.189],
        "cutoff_hz": 8600.0,
        "sub_drive": 1.75,
        "perc_style": "driving_viral",
    },
}

MOOD_KEYWORD_MAP: List[Tuple[Tuple[str, ...], str]] = [
    (("horror", "macabr", "terror", "sombrio", "sombria", "krampus", "natal", "christmas", "pagan", "ocult", "occult", "demon", "brux", "witch", "ghost", "creep", "assombr", "dark_horror", "dark_mystery"), "dark_horror_cinema"),
    (("investig", "dark", "wealth", "dossie", "dossiê", "vault", "crime", "mister", "myster", "thriller", "suspense", "fraude", "fraud", "pulse"), "dark_investigative"),
    (("epic", "doc", "netflix", "magnates", "cinema", "histor", "war", "guerra", "empire", "bilh", "billion", "colapso", "collapse"), "epic_cinema"),
    (("cartoon", "comed", "coméd", "humor", "nordest", "funny", "2d", "bouncy", "meme", "anim"), "bouncy_cartoon"),
    (("corp", "b2b", "business", "negóc", "saas", "tech", "comercial", "commercial", "focus", "pitch", "clean"), "cyber_corporate"),
    (("lofi", "lo-fi", "lo_fi", "chill", "study", "warm", "story", "calm", "relax"), "lofi_velvet"),
    (("viral", "dynamic", "dinâm", "hook", "gancho", "fast", "phonk", "energ", "hype", "short", "reel", "tiktok"), "viral_momentum"),
]


def ensure_vault_dirs() -> None:
    for d in (VAULT_DIR, VAULT_MUSIC_DIR, VAULT_IMAGES_DIR, VAULT_VEO_DIR, VAULT_CHARACTERS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def normalize_music_mood(mood: str) -> str:
    """Map an arbitrary PT-BR/EN-US mood or script tone string to a canonical synthesis profile."""
    raw = (mood or "").strip().lower()
    if raw in MOOD_PROFILES:
        return raw
    for keywords, target in MOOD_KEYWORD_MAP:
        if any(k in raw for k in keywords):
            return target
    return "dark_investigative"


def compute_vault_hash(
    prompt_or_mood: str,
    kind: str = "generic",
    aspect_ratio: str = "9:16",
    extra: str = "",
) -> str:
    """Compute a deterministic 16-char SHA-256 hash for any mood, image prompt, or Veo clip prompt."""
    cleaned = re.sub(r"\s+", " ", (prompt_or_mood or "").strip().lower())
    payload = f"{kind.strip().lower()}::{aspect_ratio.strip()}::{cleaned}::{extra.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Alias for backward/cross-worker compatibility
compute_prompt_hash = compute_vault_hash


def _default_index_payload() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_assets": 0,
            "music_count": 0,
            "image_count": 0,
            "veo_clip_count": 0,
            "character_sheet_count": 0,
            "credits_saved_by_reuse": 0,
            "total_reuses": 0,
        },
        "music": {},
        "images": {},
        "veo_clips": {},
        "character_sheets": {},
    }


def _rel_to_base(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)


class FlowVault:
    """Persistent Zero-Credit Asset Vault indexing Flow Music tracks, Nano Banana 2 images, and Veo clips."""

    def __init__(self, vault_dir: Path = VAULT_DIR) -> None:
        self.vault_dir = Path(vault_dir)
        self.music_dir = self.vault_dir / "music"
        self.images_dir = self.vault_dir / "images"
        self.veo_dir = self.vault_dir / "veo_clips"
        self.characters_dir = self.vault_dir / "character_sheets"
        self.index_path = self.vault_dir / "vault_index.json"
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        for d in (self.vault_dir, self.music_dir, self.images_dir, self.veo_dir, self.characters_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.save_index(_default_index_payload())

    def load_index(self) -> Dict[str, Any]:
        self._ensure_initialized()
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return _default_index_payload()
            for section in ("music", "images", "veo_clips", "character_sheets"):
                if section not in data or not isinstance(data[section], dict):
                    data[section] = {}
            if "stats" not in data or not isinstance(data["stats"], dict):
                data["stats"] = _default_index_payload()["stats"]
            return data
        except Exception:
            return _default_index_payload()

    def _recalculate_stats(self, index: Dict[str, Any]) -> None:
        stats = index.setdefault("stats", {})
        m_cnt = len(index.get("music", {}))
        i_cnt = len(index.get("images", {}))
        v_cnt = len(index.get("veo_clips", {}))
        c_cnt = len(index.get("character_sheets", {}))
        stats["music_count"] = m_cnt
        stats["image_count"] = i_cnt
        stats["veo_clip_count"] = v_cnt
        stats["character_sheet_count"] = c_cnt
        stats["total_assets"] = m_cnt + i_cnt + v_cnt + c_cnt
        stats.setdefault("credits_saved_by_reuse", 0)
        stats.setdefault("total_reuses", 0)
        index["updated_at"] = datetime.now(timezone.utc).isoformat()

    def save_index(self, index: Dict[str, Any]) -> None:
        self._recalculate_stats(index)
        tmp_path = self.index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.index_path)

    @staticmethod
    def _section_for_kind(kind: str) -> str:
        k = (kind or "").strip().lower()
        if k in ("music", "audio", "bgm", "track"):
            return "music"
        if k in ("image", "images", "img", "photo", "nano_banana", "nano_banana_2"):
            return "images"
        if k in ("veo", "veo_clip", "veo_clips", "video", "clip"):
            return "veo_clips"
        if k in ("character", "character_sheet", "character_sheets", "ingredient"):
            return "character_sheets"
        return "images"

    def lookup_asset(
        self,
        kind: str,
        prompt_or_mood: str,
        aspect_ratio: str = "9:16",
        extra: str = "",
        record_reuse: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Look up an indexed asset by prompt/mood hash. Increments reuse stats if found on disk."""
        section = self._section_for_kind(kind)
        asset_hash = compute_vault_hash(prompt_or_mood, kind=section, aspect_ratio=aspect_ratio, extra=extra)
        index = self.load_index()
        bucket = index.get(section, {})
        entry = bucket.get(asset_hash)
        if not entry:
            return None

        rel_or_abs = entry.get("path", "")
        if not rel_or_abs:
            return None
        candidate = Path(rel_or_abs)
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
        if not candidate.exists() or candidate.stat().st_size < 128:
            return None

        if record_reuse:
            entry["reuse_count"] = int(entry.get("reuse_count", 0)) + 1
            entry["last_reused_at"] = datetime.now(timezone.utc).isoformat()
            saved_cr = int(entry.get("credits_value", entry.get("credits_cost", 15 if section == "veo_clips" else 0)))
            index["stats"]["total_reuses"] = int(index["stats"].get("total_reuses", 0)) + 1
            index["stats"]["credits_saved_by_reuse"] = int(index["stats"].get("credits_saved_by_reuse", 0)) + saved_cr
            self.save_index(index)

        out = dict(entry)
        out["abs_path"] = str(candidate.resolve())
        return out

    # Aliases
    get_asset = lookup_asset
    find_asset = lookup_asset

    def store_asset(
        self,
        kind: str,
        prompt_or_mood: str,
        file_path: Path,
        aspect_ratio: str = "9:16",
        credits_cost: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        extra: str = "",
        copy_into_vault: bool = True,
    ) -> Dict[str, Any]:
        """Store or register an asset in `data/flow_vault/` and update `vault_index.json`."""
        src_path = Path(file_path)
        if not src_path.exists():
            raise FileNotFoundError(f"Asset file not found for FlowVault: {src_path}")

        section = self._section_for_kind(kind)
        asset_hash = compute_vault_hash(prompt_or_mood, kind=section, aspect_ratio=aspect_ratio, extra=extra)
        target_dir = {
            "music": self.music_dir,
            "images": self.images_dir,
            "veo_clips": self.veo_dir,
            "character_sheets": self.characters_dir,
        }[section]
        target_dir.mkdir(parents=True, exist_ok=True)

        dest_path = src_path
        if copy_into_vault and not str(src_path.resolve()).startswith(str(target_dir.resolve())):
            prefix = {"music": "flow_music", "images": "flow_img", "veo_clips": "flow_veo", "character_sheets": "flow_char"}[section]
            ext = src_path.suffix or (".mp3" if section == "music" else ".mp4" if section == "veo_clips" else ".png")
            dest_path = target_dir / f"{prefix}_{asset_hash}{ext}"
            if src_path.resolve() != dest_path.resolve():
                shutil.copy2(src_path, dest_path)

        index = self.load_index()
        bucket = index.setdefault(section, {})
        existing = bucket.get(asset_hash, {})
        entry: Dict[str, Any] = {
            "hash": asset_hash,
            "kind": section,
            "prompt": (prompt_or_mood or "").strip(),
            "aspect_ratio": aspect_ratio,
            "path": _rel_to_base(dest_path),
            "abs_path": str(dest_path.resolve()),
            "size_bytes": dest_path.stat().st_size,
            "credits_cost": int(credits_cost),
            "credits_value": int(credits_cost if credits_cost > 0 else (15 if section == "veo_clips" else 0)),
            "reuse_count": int(existing.get("reuse_count", 0)),
            "created_at": existing.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            entry.update(metadata)
        bucket[asset_hash] = entry
        self.save_index(index)
        return entry

    # Aliases
    register_asset = store_asset
    index_asset = store_asset

    def get_stats(self) -> Dict[str, Any]:
        index = self.load_index()
        self._recalculate_stats(index)
        return dict(index["stats"])

    def list_assets(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        index = self.load_index()
        if kind:
            sec = self._section_for_kind(kind)
            return list(index.get(sec, {}).values())
        items: List[Dict[str, Any]] = []
        for sec in ("music", "images", "veo_clips", "character_sheets"):
            items.extend(index.get(sec, {}).values())
        return items


_VAULT_SINGLETON: Optional[FlowVault] = None


def get_flow_vault() -> FlowVault:
    global _VAULT_SINGLETON
    if _VAULT_SINGLETON is None:
        _VAULT_SINGLETON = FlowVault()
    return _VAULT_SINGLETON


def get_vault_index() -> Dict[str, Any]:
    return get_flow_vault().load_index()


def get_vault_stats() -> Dict[str, Any]:
    return get_flow_vault().get_stats()


def lookup_vault_asset(
    kind: str,
    prompt_or_mood: str,
    aspect_ratio: str = "9:16",
    extra: str = "",
) -> Optional[Dict[str, Any]]:
    return get_flow_vault().lookup_asset(kind=kind, prompt_or_mood=prompt_or_mood, aspect_ratio=aspect_ratio, extra=extra)


def store_vault_asset(
    kind: str,
    prompt_or_mood: str,
    file_path: Path,
    aspect_ratio: str = "9:16",
    credits_cost: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
    extra: str = "",
) -> Dict[str, Any]:
    return get_flow_vault().store_asset(
        kind=kind,
        prompt_or_mood=prompt_or_mood,
        file_path=file_path,
        aspect_ratio=aspect_ratio,
        credits_cost=credits_cost,
        metadata=metadata,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# High-Craft Broadcast Stereo Music Synthesizer (48kHz, 4-Movement Evolving Score)
# ---------------------------------------------------------------------------
DARK_SCORE_BPM = 66.0
DARK_SCORE_BARS = 48
DARK_SCORE_BAR_S = 240.0 / DARK_SCORE_BPM  # 3.6363636s per 4/4 bar @ 66 BPM
DARK_SCORE_DURATION_S = round(DARK_SCORE_BARS * DARK_SCORE_BAR_S, 3)  # 174.545s (exact 48 bars)
DARK_SCORE_VERSION = "v7_4movement_48bar"


def _bandpass(x: np.ndarray, low: float, high: float, sr: int = SAMPLE_RATE, order: int = 3) -> np.ndarray:
    nyq = 0.5 * sr
    lo = max(20.0, min(low, nyq - 200.0)) / nyq
    hi = max(lo + 0.01, min(high, nyq - 100.0) / nyq)
    sos = signal.butter(order, [lo, hi], btype="band", output="sos")
    return signal.sosfilt(sos, x)


def _lowpass(x: np.ndarray, cutoff: float, sr: int = SAMPLE_RATE, order: int = 2) -> np.ndarray:
    nyq = 0.5 * sr
    wn = max(30.0, min(cutoff, nyq - 150.0)) / nyq
    sos = signal.butter(order, wn, btype="low", output="sos")
    return signal.sosfilt(sos, x)


def _highpass(x: np.ndarray, cutoff: float, sr: int = SAMPLE_RATE, order: int = 2) -> np.ndarray:
    nyq = 0.5 * sr
    wn = max(15.0, min(cutoff, nyq - 200.0)) / nyq
    sos = signal.butter(order, wn, btype="high", output="sos")
    return signal.sosfilt(sos, x)


def _pink_noise_score(n: int, rng: np.random.Generator, sr: int = SAMPLE_RATE) -> np.ndarray:
    n_fft = max(2, n)
    w = rng.standard_normal(n_fft)
    spec = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    scale = np.zeros_like(freqs)
    mask = freqs >= 20.0
    scale[mask] = 1.0 / np.sqrt(freqs[mask])
    y = np.fft.irfft(spec * scale, n=n_fft)[:n]
    rms = float(np.sqrt(np.mean(y * y) + 1e-12))
    return y / max(1e-9, rms)


def _save_stereo_wav(path: Path, stereo: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """Save 48kHz stereo float array as PCM-16 WAV preserving full natural dynamic range (no brickwall squash)."""
    if stereo.ndim == 1:
        stereo = np.column_stack([stereo, stereo])
    peak = float(np.max(np.abs(stereo)))
    if peak > 1e-9:
        # Leave generous headroom (-2.0 dBFS peak) so linear LUFS calibration preserves macro dynamics
        norm = stereo * (0.79 / peak)
    else:
        norm = stereo
    pcm = (np.clip(norm, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _measure_lufs_flow(audio_path: Path) -> Optional[float]:
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "info",
                "-i",
                str(audio_path),
                "-af",
                "loudnorm=I=-16.0:TP=-1.5:LRA=11:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
        if m:
            mi = float(json.loads(m[-1]).get("input_i", "-inf"))
            if math.isfinite(mi) and -70.0 <= mi <= 0.0:
                return mi
    except Exception:
        pass
    return None


def _acoustic_warm_string(
    freq: float,
    t_arr: np.ndarray,
    detune: float = 1.0,
    vib_hz: float = 4.4,
    vib_depth: float = 0.0028,
    phase_offset: float = 0.0,
    brightness: float = 0.55,
) -> np.ndarray:
    """Natural acoustic bowed Cello / Contrabass / Viola string voice with steep 1/k^1.6 harmonic
    rolloff and delayed human vibrato onset — warm orchestral wood resonance, NEVER harsh 90s MIDI organ.
    """
    vib_onset = 1.0 - np.exp(-t_arr / 0.48)
    vib = 1.0 + (vib_depth * vib_onset) * np.sin(2.0 * np.pi * vib_hz * t_arr + phase_offset)
    inst_f = (freq * detune) * vib
    ph = 2.0 * np.pi * np.cumsum(inst_f) / float(SAMPLE_RATE) + phase_offset
    b = max(0.25, min(1.0, float(brightness)))
    return (
        1.00 * np.sin(ph)
        + (0.42 * b) * np.sin(2.0 * ph + 0.18)
        + (0.20 * (b ** 1.2)) * np.sin(3.0 * ph + 0.42)
        + (0.09 * (b ** 1.4)) * np.sin(4.0 * ph + 0.70)
        + (0.035 * (b ** 1.6)) * np.sin(5.0 * ph + 1.05)
    )


def _bowed_string_voice(
    freq: float,
    t_arr: np.ndarray,
    detune: float = 1.0,
    vib_hz: float = 4.6,
    vib_depth: float = 0.0030,
    phase_offset: float = 0.0,
) -> np.ndarray:
    """Backward-compatible warm acoustic bowed string helper."""
    return _acoustic_warm_string(
        freq, t_arr, detune=detune, vib_hz=vib_hz, vib_depth=vib_depth, phase_offset=phase_offset, brightness=0.65
    )


def _scoring_hall_convolve_loop(
    stereo: np.ndarray,
    decay_s: float = 2.35,
    predelay_ms: float = 22.0,
    damp_hz: float = 2100.0,
    mix: float = 0.34,
    seed: int = 71042,
) -> np.ndarray:
    """Warm stereo scoring-stage convolution reverb with circular tail-wrap so bar-locked loops
    wrap seamlessly from Bar N back into Bar 1 with zero boundary click or gap.
    """
    n = len(stereo)
    rng = np.random.default_rng(seed)
    ir_len = max(int(0.5 * SAMPLE_RATE), min(n // 2, int(decay_s * SAMPLE_RATE)))
    t_ir = np.arange(ir_len, dtype=np.float64) / float(SAMPLE_RATE)
    pre = int(predelay_ms * SAMPLE_RATE / 1000.0)

    ir = np.zeros((ir_len, 2), dtype=np.float64)
    er_ms = [13, 19, 27, 34, 43, 52, 64, 77, 91, 108]
    for i, ms in enumerate(er_ms):
        idx = int(ms * SAMPLE_RATE / 1000.0)
        if idx < ir_len:
            g = 0.48 * (0.82 ** i) * (1.0 if i % 2 == 0 else -1.0)
            ir[idx, i % 2] += g
            ir[min(ir_len - 1, idx + 17), 1 - (i % 2)] += g * 0.32

    bloom = 1.0 - np.exp(-t_ir / 0.038)
    env_lo = bloom * np.exp(-6.9 * t_ir / max(0.3, decay_s * 1.12))
    env_mid = bloom * np.exp(-6.9 * t_ir / max(0.25, decay_s * 0.72))
    env_hi = bloom * np.exp(-6.9 * t_ir / max(0.15, decay_s * 0.32))
    for ch in range(2):
        nr = rng.standard_normal(ir_len)
        lo_b = _lowpass(nr, 380.0, order=2) * env_lo
        mid_b = _bandpass(nr, 380.0, damp_hz, order=2) * env_mid
        hi_b = _highpass(nr, damp_hz, order=2) * env_hi
        diff = lo_b * 0.58 + mid_b * 0.44 + hi_b * 0.14
        if pre < ir_len:
            ir[pre:, ch] += diff[: ir_len - pre]

    fade_ir = min(int(0.08 * SAMPLE_RATE), ir_len // 4)
    if fade_ir > 0:
        ir[-fade_ir:, :] *= np.linspace(1.0, 0.0, fade_ir)[:, None]
    ir /= max(1e-6, float(np.sqrt(np.sum(ir * ir) * 0.5 + 1e-12)))

    wet_l = signal.fftconvolve(stereo[:, 0], ir[:, 0], mode="full")
    wet_r = signal.fftconvolve(stereo[:, 1], ir[:, 1], mode="full")
    # Circularly wrap reverb tail past bar N back into bar 1 for an invisible bar-locked loop seam!
    out_wet = np.column_stack([wet_l[:n].copy(), wet_r[:n].copy()])
    tail_len = len(wet_l) - n
    if tail_len > 0:
        wrap_len = min(n, tail_len)
        out_wet[:wrap_len, 0] += wet_l[n : n + wrap_len]
        out_wet[:wrap_len, 1] += wet_r[n : n + wrap_len]

    dry_rms = float(np.sqrt(np.mean(stereo * stereo) + 1e-12))
    wet_rms = float(np.sqrt(np.mean(out_wet * out_wet) + 1e-12))
    if wet_rms > 1e-9:
        out_wet *= dry_rms / wet_rms

    # Keep sub-110Hz mono-compatible
    wet_sub_l = _lowpass(out_wet[:, 0], 110.0, order=2)
    wet_sub_r = _lowpass(out_wet[:, 1], 110.0, order=2)
    wet_sub_m = 0.5 * (wet_sub_l + wet_sub_r)
    out_wet[:, 0] = (out_wet[:, 0] - wet_sub_l) + wet_sub_m
    out_wet[:, 1] = (out_wet[:, 1] - wet_sub_r) + wet_sub_m

    return stereo * (1.0 - mix * 0.35) + out_wet * mix


def _synthesize_4movement_doc_score_stereo(
    bars: int,
    bpm: float,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, float, int]:
    """Synthesize a metric bar-locked (`66 BPM`, `1 bar = 3.63636s`, `48 bars = 174.55s`)
    4-Movement Evolving Documentary Score matching JSON v3.0.0 `genre_progression`:
      - Movement I  (Bars 1–8,  Cold Open Hook): Dark ticking clockwork escapement pulse + deep D1/A1 sub drone + rising string tension swell.
      - Movement II (Bars 9–20, Historical World Building): Warm acoustic bowed cello & contrabass ensemble + sparse ancient Dorian lute/harp fifths.
      - Movement III(Bars 21–36, Investigative Deep Mechanics): Minimalist investigative brushed pulse + muted low brass/horn swells + sparse suspense celesta.
      - Movement IV (Bars 37–48, Climax & Philosophical Resolution): Dramatic layered orchestral string crescendo (Bars 37–44) -> haunting solo cello & melancholic felt-piano coda (Bars 45–48).
    """
    eff_bars = max(8, int(round(bars / 4.0)) * 4)
    beat_s = 60.0 / float(bpm)
    bar_s = beat_s * 4.0
    total_s = eff_bars * bar_s
    n = int(round(total_s * SAMPLE_RATE))

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)
    hall_send_l = np.zeros(n, dtype=np.float64)
    hall_send_r = np.zeros(n, dtype=np.float64)

    bar_samples = max(1, int(round(bar_s * SAMPLE_RATE)))
    beat_samples = max(1, int(round(beat_s * SAMPLE_RATE)))

    # Movement boundaries (exact 8 / 12 / 16 / 8 / 4 proportions -> exact 1..8, 9..20, 21..36, 37..44, 45..48 for 48 bars)
    m1_end = max(2, int(round(eff_bars * (8.0 / 48.0))))
    m2_end = max(m1_end + 2, int(round(eff_bars * (20.0 / 48.0))))
    m3_end = max(m2_end + 2, int(round(eff_bars * (36.0 / 48.0))))
    m4_peak_end = max(m3_end + 1, int(round(eff_bars * (44.0 / 48.0))))

    # Helper to add stereo note safely with wrap-free bounds
    def _add_pan(dst_l: np.ndarray, dst_r: np.ndarray, pos: int, sig: np.ndarray, pan: float = 0.0) -> None:
        if pos >= n or len(sig) == 0:
            return
        end_p = min(n, pos + len(sig))
        seg = sig[: end_p - pos]
        ang = (max(-1.0, min(1.0, pan)) + 1.0) * (math.pi * 0.25)
        dst_l[pos:end_p] += seg * math.cos(ang)
        dst_r[pos:end_p] += seg * math.sin(ang)

    # Pre-synthesized acoustic helpers
    def _clockwork_tick(is_accent: bool, soft_ghost: bool = False) -> np.ndarray:
        dur_tk = 0.095
        nk = int(dur_tk * SAMPLE_RATE)
        tk = np.arange(nk, dtype=np.float64) / float(SAMPLE_RATE)
        if is_accent:
            f_hi, f_mid, f_wood = 2050.0, 940.0, 260.0
            amp = 0.14 if not soft_ghost else 0.055
        else:
            f_hi, f_mid, f_wood = 1620.0, 740.0, 215.0
            amp = 0.105 if not soft_ghost else 0.045
        wood = np.sin(2.0 * np.pi * f_wood * tk) * np.exp(-tk / 0.011) * 0.55
        metal = (
            np.sin(2.0 * np.pi * f_mid * tk) * np.exp(-tk / 0.0085) * 0.60
            + np.sin(2.0 * np.pi * f_hi * tk) * np.exp(-tk / 0.0055) * 0.35
        )
        click = _bandpass(rng.standard_normal(nk), 900.0, 3600.0, order=2) * np.exp(-tk / 0.004) * 0.28
        return _lowpass((wood + metal + click) * (1.0 - np.exp(-tk / 0.0008)), 4200.0, order=2) * amp

    def _dorian_lute_pluck(freq: float, dur_p: float = 2.6, amp: float = 0.14) -> np.ndarray:
        np_len = int(dur_p * SAMPLE_RATE)
        tp = np.arange(np_len, dtype=np.float64) / float(SAMPLE_RATE)
        atk = 1.0 - np.exp(-tp / 0.0045)
        # Warm antique gut-string modal decay (upper harmonics damp quickly like wooden lute/harp)
        body = (
            1.00 * np.sin(2.0 * np.pi * freq * tp) * np.exp(-1.15 * tp)
            + 0.42 * np.sin(2.0 * np.pi * (freq * 2.0006) * tp + 0.2) * np.exp(-2.45 * tp)
            + 0.16 * np.sin(2.0 * np.pi * (freq * 3.0018) * tp + 0.5) * np.exp(-4.80 * tp)
            + 0.06 * np.sin(2.0 * np.pi * (freq * 4.004) * tp + 0.9) * np.exp(-8.50 * tp)
        ) * atk
        # Soft finger-pluck wood thump
        thump = _bandpass(rng.standard_normal(np_len), 180.0, 720.0, order=2) * np.exp(-tp / 0.009) * 0.12
        return _lowpass(body + thump, 2400.0, order=2) * amp

    def _felt_piano_note(freq: float, dur_n: float = 4.2, amp: float = 0.22) -> np.ndarray:
        nn = int(dur_n * SAMPLE_RATE)
        tn = np.arange(nn, dtype=np.float64) / float(SAMPLE_RATE)
        atk = 1.0 - np.exp(-tn / 0.011)
        # Nils Frahm / Olafur Arnalds warm felt-piano spectrum (fundamental-heavy, muted hammer)
        B = 0.00032
        sig = (
            1.00 * np.sin(2.0 * np.pi * freq * tn) * np.exp(-tn / 2.65)
            + 0.34 * np.sin(2.0 * np.pi * (freq * 2.0 * math.sqrt(1.0 + 4.0 * B)) * tn + 0.15) * np.exp(-tn / 1.40)
            + 0.11 * np.sin(2.0 * np.pi * (freq * 3.0 * math.sqrt(1.0 + 9.0 * B)) * tn + 0.40) * np.exp(-tn / 0.72)
            + 0.035 * np.sin(2.0 * np.pi * (freq * 4.0 * math.sqrt(1.0 + 16.0 * B)) * tn + 0.80) * np.exp(-tn / 0.38)
            + 0.14 * np.sin(2.0 * np.pi * (freq * 0.5) * tn) * np.exp(-tn / 2.20)
        ) * atk
        felt_thump = _bandpass(_pink_noise_score(nn, rng), 120.0, 620.0, order=2) * np.exp(-tn / 0.022) * 0.10
        return _lowpass(sig + felt_thump, 1750.0, order=2) * amp

    def _sparse_celesta_note(freq: float, dur_c: float = 3.0, amp: float = 0.11) -> np.ndarray:
        nc = int(dur_c * SAMPLE_RATE)
        tc = np.arange(nc, dtype=np.float64) / float(SAMPLE_RATE)
        atk = 1.0 - np.exp(-tc / 0.005)
        sig = (
            0.82 * np.sin(2.0 * np.pi * freq * tc) * np.exp(-tc / 1.55)
            + 0.24 * np.sin(2.0 * np.pi * (freq * 2.002) * tc + 0.3) * np.exp(-tc / 0.75)
            + 0.08 * np.sin(2.0 * np.pi * (freq * 3.012) * tc + 0.7) * np.exp(-tc / 0.28)
            + 0.18 * np.sin(2.0 * np.pi * (freq * 0.5) * tc) * np.exp(-tc / 1.85)
        ) * atk
        return _lowpass(sig, 3100.0, order=2) * amp

    # Harmonic tables across the 4 movements (D Minor / D Dorian / Phrygian)
    # Movement II (Dorian Historical World Building): Dm -> C/D -> Bbmaj7 -> Am7 -> Gm7 -> Dm -> C -> A7sus4
    m2_chords = [
        (36.71, [73.42, 110.00, 146.83, 174.61]),  # Dm
        (36.71, [65.41, 110.00, 130.81, 196.00]),  # C/D Dorian
        (58.27, [58.27, 110.00, 146.83, 174.61]),  # Bbmaj7
        (55.00, [55.00, 110.00, 130.81, 164.81]),  # Am7
        (49.00, [73.42, 98.00, 146.83, 174.61]),   # Gm7
        (36.71, [73.42, 110.00, 146.83, 174.61]),  # Dm
    ]
    m2_lute_fifths = [
        (146.83, 220.00),  # D3-A3
        (130.81, 196.00),  # C3-G3
        (174.61, 261.63),  # F3-C4
        (164.81, 246.94),  # E3-B3 (Dorian 6th color!)
        (196.00, 293.66),  # G3-D4
        (146.83, 220.00),  # D3-A3
    ]

    # Movement III (Investigative Deep Mechanics): Dm -> Bb/D -> Gm/D -> A7sus4
    m3_brass_roots = [73.42, 58.27, 65.41, 55.00]  # D2, Bb1, C2, A1
    m3_celesta_phrases = [
        [(0.0, 587.33, -0.35), (1.5, 698.46, 0.32), (3.0, 659.25, -0.22)],  # D5, F5, E5
        [(0.5, 440.00, 0.30), (2.0, 622.25, -0.38)],                        # A4, Eb5 (Phrygian chill!)
        [(0.0, 587.33, -0.28), (2.0, 554.37, 0.34), (3.0, 440.00, -0.18)],  # D5, C#5, A4
        [(1.0, 698.46, 0.25), (2.5, 587.33, -0.30)],                        # F5, D5
    ]

    # Movement IVa (Bars 37-44 Climax): Dramatic layered orchestral string crescendo
    m4_climax_chords = [
        (36.71, 73.42, 146.83, 220.00, 293.66, 349.23),  # Dm wide
        (58.27, 58.27, 116.54, 174.61, 293.66, 349.23),  # Bbmaj7 wide
        (49.00, 98.00, 146.83, 174.61, 233.08, 349.23),  # Gm7 wide
        (55.00, 55.00, 110.00, 164.81, 220.00, 329.63),  # A5/A7 dramatic suspend
        (36.71, 73.42, 146.83, 220.00, 349.23, 440.00),  # Dm soaring octave
        (58.27, 58.27, 146.83, 233.08, 349.23, 466.16),  # Bb towering
        (65.41, 65.41, 130.81, 196.00, 329.63, 392.00),  # C heroic tension
        (55.00, 55.00, 110.00, 164.81, 277.18, 440.00),  # A major dominant crest -> resolves to Dm coda!
    ]

    # Movement IVb (Bars 45-48 Philosophical Resolution Coda): Solo Cello + Felt Piano
    m4_coda_cello_notes = [
        (174.61, 164.81),  # Bar 45: F3 -> E3 sigh
        (146.83, 130.81),  # Bar 46: D3 -> C3 lament
        (110.00, 146.83),  # Bar 47: A2 -> D3 yearning
        (146.83, 146.83),  # Bar 48: D3 serene resolution
    ]
    m4_coda_piano_notes = [
        [(0.0, 293.66, -0.18), (2.0, 440.00, 0.24)],   # D4, A4
        [(0.0, 349.23, -0.22), (2.5, 329.63, 0.18)],   # F4, E4
        [(0.0, 233.08, 0.22), (2.0, 220.00, -0.20)],   # Bb3, A3
        [(0.0, 293.66, 0.00)],                         # D4 lingering final chord
    ]

    for b_idx in range(eff_bars):
        start = b_idx * bar_samples
        if start >= n:
            break
        end = min(n, start + bar_samples)
        seg_len = end - start
        if seg_len <= 64:
            continue
        seg_t = np.arange(seg_len, dtype=np.float64) / float(SAMPLE_RATE)
        bar_dur = seg_len / float(SAMPLE_RATE)
        # Smooth organic bar crossfade envelope
        bar_env = np.minimum(1.0, seg_t / 0.38) * np.minimum(1.0, (bar_dur - seg_t + 1e-4) / 0.42)

        # ------------------------------------------------------------------
        # MOVEMENT I: Cold Open Hook (Bars 1-8) — Tense, lean clockwork & sub-bass build
        # ------------------------------------------------------------------
        if b_idx < m1_end:
            m1_prog = (b_idx + seg_t / max(0.1, bar_dur)) / float(m1_end)
            # 1. Deep D1/A1 Sub-Bass Contrabass Drone (restrained dark floor building across Bars 1-8)
            sub_swell = 0.50 + 0.50 * m1_prog
            d1_drone = (
                0.76 * np.sin(2.0 * np.pi * 36.71 * seg_t + 0.2 * b_idx)
                + 0.34 * np.sin(2.0 * np.pi * 55.00 * seg_t + 0.7)  # A1 dark fifth
                + 0.26 * np.sin(2.0 * np.pi * 73.42 * seg_t + 0.3)  # D2 cello fundamental
            ) * sub_swell * 0.165
            left[start:end] += d1_drone * bar_env
            right[start:end] += d1_drone * bar_env

            # 2. Dark Ticking Clockwork Escapement Pulse (66 BPM)
            for bt in range(4):
                bt_pos = start + bt * beat_samples
                tick = _clockwork_tick(is_accent=(bt % 2 == 0))
                pan_tk = -0.18 if (bt % 2 == 0) else 0.18
                _add_pan(left, right, bt_pos, tick * (0.72 + 0.40 * (b_idx / float(m1_end))), pan=pan_tk)
                # Subtle 8th-note escapement double-tick in the second half of Movement I (bars 5-8)
                if b_idx >= m1_end // 2 and bt in (1, 3):
                    g_pos = bt_pos + beat_samples // 2
                    gtick = _clockwork_tick(is_accent=False, soft_ghost=True)
                    _add_pan(left, right, g_pos, gtick, pan=-pan_tk * 0.7)

            # 3. Rising String Tension Swell (creeping from D3 -> Eb3 -> F3 -> A3 across Bars 1-8)
            tens_notes = [146.83, 146.83, 155.56, 155.56, 174.61, 174.61, 207.65, 220.00]
            tf = tens_notes[b_idx % len(tens_notes)]
            swell_gain = 0.04 + 0.16 * (m1_prog ** 1.35)
            st_l = _acoustic_warm_string(tf, seg_t, detune=0.997, vib_hz=4.1, phase_offset=0.3 * b_idx, brightness=0.52)
            st_r = _acoustic_warm_string(tf, seg_t, detune=1.003, vib_hz=4.5, phase_offset=0.3 * b_idx + 1.1, brightness=0.52)
            st_l = _lowpass(st_l, 820.0 + 520.0 * (b_idx / float(m1_end)), order=2)
            st_r = _lowpass(st_r, 820.0 + 520.0 * (b_idx / float(m1_end)), order=2)
            hall_send_l[start:end] += st_l * swell_gain * bar_env
            hall_send_r[start:end] += st_r * swell_gain * bar_env

        # ------------------------------------------------------------------
        # MOVEMENT II: Historical World Building (Bars 9-20) — Warm acoustic cello & Dorian lute
        # ------------------------------------------------------------------
        elif b_idx < m2_end:
            local_b = b_idx - m1_end
            sub_f, cello_notes = m2_chords[(local_b // 2) % len(m2_chords)]

            # 1. Warm Acoustic Bowed Cello & Contrabass Ensemble (natural wood warmth, zero organ buzz)
            cb = (
                0.85 * np.sin(2.0 * np.pi * sub_f * seg_t)
                + 0.35 * np.sin(2.0 * np.pi * (sub_f * 2.0) * seg_t + 0.2)
            ) * 0.205
            left[start:end] += cb * bar_env
            right[start:end] += cb * bar_env

            ens_l = np.zeros(seg_len, dtype=np.float64)
            ens_r = np.zeros(seg_len, dtype=np.float64)
            bow_phrase = 0.74 + 0.26 * np.sin(np.pi * seg_t / max(0.1, bar_dur))
            for vi, vf in enumerate(cello_notes):
                v_l = _acoustic_warm_string(vf, seg_t, detune=0.9975 - 0.0005 * vi, vib_hz=4.2 + 0.22 * vi, phase_offset=vi * 0.9, brightness=0.54)
                v_r = _acoustic_warm_string(vf, seg_t, detune=1.0025 + 0.0005 * vi, vib_hz=4.3 + 0.19 * vi, phase_offset=vi * 0.9 + 1.4, brightness=0.54)
                pan_w = 0.62 if (vi % 2 == 0) else 0.38
                ens_l += v_l * (0.105 * pan_w)
                ens_r += v_r * (0.105 * (1.0 - pan_w))
            # Soft bow rosin breath
            rosin = _bandpass(_pink_noise_score(seg_len, rng), 520.0, 1450.0, order=2) * 0.010 * bow_phrase
            ens_l = _lowpass(ens_l, 980.0, order=2) + rosin
            ens_r = _lowpass(ens_r, 980.0, order=2) + rosin * 0.9
            hall_send_l[start:end] += ens_l * bar_env * bow_phrase
            hall_send_r[start:end] += ens_r * bar_env * bow_phrase

            # 2. Sparse Ancient Dorian Lute / Archival Harp Open Fifths
            f_root, f_fifth = m2_lute_fifths[local_b % len(m2_lute_fifths)]
            # Beat 1 root pluck + Beat 2.5 open fifth pluck (spacious historical phrasing)
            pl_root = _dorian_lute_pluck(f_root, dur_p=2.8, amp=0.175)
            pl_fifth = _dorian_lute_pluck(f_fifth, dur_p=2.6, amp=0.150)
            _add_pan(hall_send_l, hall_send_r, start, pl_root, pan=-0.34 if local_b % 2 == 0 else 0.34)
            _add_pan(hall_send_l, hall_send_r, start + int(1.5 * beat_samples), pl_fifth, pan=0.36 if local_b % 2 == 0 else -0.36)
            if local_b % 2 == 1:
                pl_oct = _dorian_lute_pluck(f_root * 2.0, dur_p=2.0, amp=0.105)
                _add_pan(hall_send_l, hall_send_r, start + int(3.0 * beat_samples), pl_oct, pan=-0.18)

        # ------------------------------------------------------------------
        # MOVEMENT III: Investigative Deep Mechanics (Bars 21-36) — Brushed pulse, muted brass & sparse celesta
        # ------------------------------------------------------------------
        elif b_idx < m3_end:
            local_b = b_idx - m2_end
            root_f = m3_brass_roots[(local_b // 2) % len(m3_brass_roots)]

            # 1. Minimalist Investigative Brushed Pulse + Deep Muffled Frame-Drum Heartbeat
            for bt in range(4):
                bt_pos = start + bt * beat_samples
                if bt == 0 or (bt == 2 and local_b % 2 == 1):
                    # Soft muffled frame drum downbeat (58 -> 38 Hz)
                    dl = min(n - bt_pos, int(0.38 * SAMPLE_RATE))
                    if dl > 64:
                        dt = np.arange(dl, dtype=np.float64) / float(SAMPLE_RATE)
                        f_dr = 38.0 + 26.0 * np.exp(-dt / 0.032)
                        drum = np.sin(2.0 * np.pi * np.cumsum(f_dr) / float(SAMPLE_RATE)) * (1.0 - np.exp(-dt / 0.008)) * np.exp(-dt / 0.14)
                        amp_d = 0.28 if bt == 0 else 0.18
                        left[bt_pos : bt_pos + dl] += drum * amp_d
                        right[bt_pos : bt_pos + dl] += drum * amp_d
                # Minimalist brushed parchment / wire pulse on off-beat 8ths
                br_pos = bt_pos + beat_samples // 2
                bl = min(n - br_pos, int(0.11 * SAMPLE_RATE))
                if bl > 64:
                    tb = np.arange(bl, dtype=np.float64) / float(SAMPLE_RATE)
                    br = _bandpass(_pink_noise_score(bl, rng), 1900.0, 4600.0, order=2) * (1.0 - np.exp(-tb / 0.006)) * np.exp(-tb / 0.032) * 0.042
                    _add_pan(left, right, br_pos, br, pan=-0.22 if bt % 2 == 0 else 0.22)

            # 2. Pulsing Contrabass Anchor (quarter-note investigative tension)
            pulse_env = 0.56 + 0.44 * (0.5 + 0.5 * np.sin(2.0 * np.pi * (bpm / 60.0) * seg_t - math.pi * 0.5))
            bass_sig = (
                0.82 * np.sin(2.0 * np.pi * root_f * seg_t)
                + 0.34 * np.sin(2.0 * np.pi * (root_f * 0.5) * seg_t)
                + 0.24 * np.sin(2.0 * np.pi * (root_f * 2.0) * seg_t)
            ) * pulse_env * 0.275 * bar_env
            left[start:end] += bass_sig
            right[start:end] += bass_sig

            # 3. Muted Low Brass / French Horn Swells (warm dark swells every 2 bars)
            if local_b % 2 == 0:
                swell_dur = min(n - start, bar_samples * 2)
                st_h = np.arange(swell_dur, dtype=np.float64) / float(SAMPLE_RATE)
                sd = swell_dur / float(SAMPLE_RATE)
                # Smooth arch swell peaking at 55% of the 2-bar phrase
                h_env = np.sin(np.pi * np.clip(st_h / max(0.2, sd), 0.0, 1.0)) ** 1.25
                fifth_f = root_f * 1.4983  # open 5th brass voicing
                h_l = (
                    _acoustic_warm_string(root_f, st_h, detune=0.998, vib_hz=2.8, vib_depth=0.0018, brightness=0.76) * 0.68
                    + _acoustic_warm_string(fifth_f, st_h, detune=1.002, vib_hz=3.1, vib_depth=0.0016, phase_offset=0.8, brightness=0.68) * 0.52
                )
                h_r = (
                    _acoustic_warm_string(root_f, st_h, detune=1.002, vib_hz=2.9, vib_depth=0.0018, phase_offset=0.5, brightness=0.76) * 0.68
                    + _acoustic_warm_string(fifth_f, st_h, detune=0.998, vib_hz=3.0, vib_depth=0.0016, phase_offset=1.3, brightness=0.68) * 0.52
                )
                # Warm muted brass lowpass (dark & noble, never piercing)
                h_l = _lowpass(h_l, 640.0, order=2) * h_env * 0.36
                h_r = _lowpass(h_r, 640.0, order=2) * h_env * 0.36
                hall_send_l[start : start + swell_dur] += h_l
                hall_send_r[start : start + swell_dur] += h_r

            # 4. Subtle Suspense Celesta Motif (ONLY on sparse bars — NEVER every 8th note!)
            if local_b % 4 in (1, 3):
                phrase = m3_celesta_phrases[(local_b // 2) % len(m3_celesta_phrases)]
                for beat_off, cf, cpan in phrase:
                    cpos = start + int(round(beat_off * beat_samples))
                    cnote = _sparse_celesta_note(cf, dur_c=2.8, amp=0.145)
                    _add_pan(hall_send_l, hall_send_r, cpos, cnote, pan=cpan)

        # ------------------------------------------------------------------
        # MOVEMENT IVa: Dramatic Layered Orchestral String Crescendo (Bars 37-44)
        # ------------------------------------------------------------------
        elif b_idx < m4_peak_end:
            local_b = b_idx - m3_end
            cresc_len = max(1, m4_peak_end - m3_end)
            cresc_prog = (local_b + seg_t / max(0.1, bar_dur)) / float(cresc_len)
            # True soaring orchestral climax swell (0.88 -> 1.62), pulling back cleanly on final 2 beats of Bar 44
            cresc_gain = 0.88 + 0.74 * (cresc_prog ** 1.12)
            if local_b == cresc_len - 1:
                cresc_gain = cresc_gain * np.where(seg_t > bar_dur * 0.68, np.maximum(0.28, 1.0 - (seg_t - bar_dur * 0.68) / (bar_dur * 0.32)), 1.0)

            voicing = m4_climax_chords[local_b % len(m4_climax_chords)]
            sub_f = voicing[0]
            # Deep contrabass + timpani swell on bar downbeat
            cb_sig = (
                0.86 * np.sin(2.0 * np.pi * sub_f * seg_t)
                + 0.42 * np.sin(2.0 * np.pi * (sub_f * 2.0) * seg_t + 0.25)
            ) * 0.30 * cresc_gain * bar_env
            left[start:end] += cb_sig
            right[start:end] += cb_sig

            # Warm orchestral timpani downbeat swell
            tl = min(n - start, int(1.15 * SAMPLE_RATE))
            if tl > 64:
                tt = np.arange(tl, dtype=np.float64) / float(SAMPLE_RATE)
                f_timp = sub_f * 1.5 + 32.0 * np.exp(-tt / 0.045)
                timp = np.sin(2.0 * np.pi * np.cumsum(f_timp) / float(SAMPLE_RATE)) * (1.0 - np.exp(-tt / 0.014)) * np.exp(-tt / 0.36) * (0.22 + 0.18 * (local_b / float(cresc_len)))
                left[start : start + tl] += timp
                right[start : start + tl] += timp

            # Layered Cello + Viola + High Violin Section
            orch_l = np.zeros(seg_len, dtype=np.float64)
            orch_r = np.zeros(seg_len, dtype=np.float64)
            for vi, vf in enumerate(voicing[1:]):
                w_voice = [0.28, 0.23, 0.19, 0.16, 0.13][min(vi, 4)]
                bri = 0.58 + 0.24 * (local_b / float(cresc_len))
                vl = _acoustic_warm_string(vf, seg_t, detune=0.9965 + 0.0007 * vi, vib_hz=4.5 + 0.25 * vi, vib_depth=0.0032, phase_offset=vi * 1.1, brightness=bri)
                vr = _acoustic_warm_string(vf, seg_t, detune=1.0035 - 0.0007 * vi, vib_hz=4.6 + 0.21 * vi, vib_depth=0.0032, phase_offset=vi * 1.1 + 1.5, brightness=bri)
                pan_l = 0.68 if (vi % 2 == 0) else 0.34
                orch_l += vl * (w_voice * pan_l)
                orch_r += vr * (w_voice * (1.02 - pan_l))

            lp_cut = 1250.0 + 750.0 * (local_b / float(cresc_len))
            orch_l = _lowpass(orch_l, lp_cut, order=2) * cresc_gain * bar_env
            orch_r = _lowpass(orch_r, lp_cut, order=2) * cresc_gain * bar_env
            hall_send_l[start:end] += orch_l
            hall_send_r[start:end] += orch_r

        # ------------------------------------------------------------------
        # MOVEMENT IVb: Haunting Solo Cello & Melancholic Felt-Piano Coda (Bars 45-48)
        # ------------------------------------------------------------------
        else:
            local_b = b_idx - m4_peak_end
            coda_len = max(1, eff_bars - m4_peak_end)
            # Intimate receding coda drop after the climax
            coda_fade = 0.85 * (1.0 - 0.35 * (local_b / float(coda_len)))

            # 1. Whisper-soft D1/D2 pedal cushion
            pedal = (
                0.70 * np.sin(2.0 * np.pi * 36.71 * seg_t)
                + 0.28 * np.sin(2.0 * np.pi * 73.42 * seg_t)
            ) * 0.085 * coda_fade * bar_env
            left[start:end] += pedal
            right[start:end] += pedal

            # 2. Expressive Solo Bowed Cello Lament (2 legato half-bar notes per bar)
            f_a, f_b = m4_coda_cello_notes[local_b % len(m4_coda_cello_notes)]
            # Smooth portamento glide at mid-bar
            glide = 1.0 / (1.0 + np.exp(-(seg_t - bar_dur * 0.50) / 0.085))
            f_solo = f_a * (1.0 - glide) + f_b * glide
            ph_s = 2.0 * np.pi * np.cumsum(f_solo * (1.0 + 0.0038 * (1.0 - np.exp(-seg_t / 0.5)) * np.sin(2.0 * np.pi * 4.7 * seg_t))) / float(SAMPLE_RATE)
            solo_raw = (
                1.00 * np.sin(ph_s)
                + 0.44 * np.sin(2.0 * ph_s + 0.2)
                + 0.18 * np.sin(3.0 * ph_s + 0.5)
                + 0.07 * np.sin(4.0 * ph_s + 0.8)
            )
            solo_env = np.minimum(1.0, seg_t / 0.55) * np.minimum(1.0, (bar_dur - seg_t + 1e-4) / 0.65)
            solo_cello = _lowpass(solo_raw, 1080.0, order=2) * solo_env * 0.145 * coda_fade
            _add_pan(hall_send_l, hall_send_r, start, solo_cello, pan=-0.16)

            # 3. Sparse Melancholic Felt-Piano Notes
            for beat_off, pf, ppan in m4_coda_piano_notes[local_b % len(m4_coda_piano_notes)]:
                ppos = start + int(round(beat_off * beat_samples))
                pnote = _felt_piano_note(pf, dur_n=4.4, amp=0.175 * coda_fade)
                _add_pan(hall_send_l, hall_send_r, ppos, pnote, pan=ppan)

    # Combine dry foundation + hall-reverberated acoustic ensemble
    hall_st = np.column_stack([hall_send_l, hall_send_r])
    hall_wet = _scoring_hall_convolve_loop(hall_st, decay_s=2.40, predelay_ms=22.0, damp_hz=2050.0, mix=0.42, seed=71048)

    mix_l = left + hall_wet[:, 0]
    mix_r = right + hall_wet[:, 1]

    # Balanced Broadcast Mastering EQ (NO vocal-masking mid boost! Respects 400-2500 Hz speech intelligibility)
    mix_l = _highpass(mix_l, 26.0, order=2)
    mix_r = _highpass(mix_r, 26.0, order=2)
    mix_l = _lowpass(mix_l, 5200.0, order=2)
    mix_r = _lowpass(mix_r, 5200.0, order=2)

    # Gentle -2.5 dB courtesy dip across 750-2300 Hz so raw score sits harmoniously behind narration
    dip_l = _bandpass(mix_l, 750.0, 2300.0, order=2)
    dip_r = _bandpass(mix_r, 750.0, 2300.0, order=2)
    mix_l = mix_l - 0.24 * dip_l
    mix_r = mix_r - 0.24 * dip_r

    # Micro 12ms boundary taper for click-free loop wrap (zero dead fade gap!)
    xf_edge = min(int(0.012 * SAMPLE_RATE), n // 32)
    if xf_edge > 4:
        ramp_in = np.linspace(0.0, 1.0, xf_edge)
        ramp_out = np.linspace(1.0, 0.0, xf_edge)
        mix_l[:xf_edge] *= ramp_in
        mix_r[:xf_edge] *= ramp_in
        mix_l[-xf_edge:] *= ramp_out
        mix_r[-xf_edge:] *= ramp_out

    return np.column_stack([mix_l, mix_r]), total_s, eff_bars


def _synthesize_procedural_track(
    out_mp3: Union[Path, str],
    mood_raw: Union[str, float, Path] = "dark_horror_cinema",
    profile_key: Optional[Union[str, float]] = None,
    duration_s: float = DARK_SCORE_DURATION_S,
) -> Dict[str, Any]:
    """Synthesize a metric bar-locked (`66 BPM`, `48 bars = 174.55s`) 4-Movement Evolving
    Documentary Score for dark-cinema / historical moods (or tailored procedural bed for other moods),
    calibrated linearly to `-16.0 LUFS` while preserving full orchestral dynamic range (`LRA >= 4.5 LU`)
    and balanced `400–2500 Hz` mid-range (zero vocal masking!).
    """
    # Flexible argument normalization for direct unit-test and internal callers
    if isinstance(out_mp3, Path) or str(out_mp3).endswith((".mp3", ".wav")):
        target_out = Path(out_mp3)
        if isinstance(mood_raw, (int, float)):
            duration_s = float(mood_raw)
            mood_str = str(profile_key or "dark_horror_cinema")
            prof_str = str(profile_key or normalize_music_mood(mood_str))
        else:
            mood_str = str(mood_raw or "dark_horror_cinema")
            if isinstance(profile_key, (int, float)):
                duration_s = float(profile_key)
                prof_str = normalize_music_mood(mood_str)
            else:
                prof_str = str(profile_key or normalize_music_mood(mood_str))
    else:
        mood_str = str(out_mp3 or "dark_horror_cinema")
        prof_str = normalize_music_mood(mood_str)
        if isinstance(mood_raw, (int, float)):
            duration_s = float(mood_raw)
            target_out = (
                Path(profile_key)
                if isinstance(profile_key, (str, Path))
                else (VAULT_MUSIC_DIR / f"flow_music_{prof_str}.mp3")
            )
        else:
            target_out = Path(mood_raw)
            if isinstance(profile_key, (int, float)):
                duration_s = float(profile_key)

    if prof_str not in MOOD_PROFILES:
        prof_str = normalize_music_mood(prof_str)
    prof = MOOD_PROFILES.get(prof_str, MOOD_PROFILES["dark_horror_cinema"])
    target_s = max(12.0, min(300.0, float(duration_s)))

    seed_int = int(hashlib.sha256((mood_str or prof_str).encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed_int)

    is_dark_cinema = prof_str in (
        "dark_horror_cinema",
        "dark_mystery",
        "dark_investigative",
        "investigative_pulse",
        "epic_cinema",
        "historical_epic",
    )

    if is_dark_cinema:
        bpm = DARK_SCORE_BPM if prof_str in ("dark_horror_cinema", "dark_mystery") else float(prof["bpm"])
        bar_s = 240.0 / bpm
        req_bars = max(8, int(round(target_s / bar_s)))
        stereo, total_s, eff_bars = _synthesize_4movement_doc_score_stereo(req_bars, bpm, rng)
    else:
        bpm = float(prof["bpm"]) + float((seed_int % 5) - 2) * 0.5
        beat_s = 60.0 / bpm
        bar_s = beat_s * 4.0
        eff_bars = max(4, int(round(target_s / bar_s)))
        total_s = eff_bars * bar_s
        n = int(round(total_s * SAMPLE_RATE))

        left = np.zeros(n, dtype=np.float64)
        right = np.zeros(n, dtype=np.float64)
        chords: List[List[float]] = prof["chords"]
        bass_notes: List[float] = prof["bass_notes"]
        motif_intervals: List[float] = prof["motif_intervals"]
        sub_drive = float(prof.get("sub_drive", 1.5))
        perc_style = str(prof.get("perc_style", "investigative_pulse"))

        bar_samples = max(1, int(round(bar_s * SAMPLE_RATE)))
        beat_samples = max(1, int(round(beat_s * SAMPLE_RATE)))
        step_samples = max(1, beat_samples // 2)

        for b_idx in range(eff_bars):
            start = b_idx * bar_samples
            if start >= n:
                break
            end = min(n, start + bar_samples)
            seg_len = end - start
            if seg_len <= 0:
                continue
            seg_t = np.linspace(0.0, seg_len / float(SAMPLE_RATE), seg_len, endpoint=False)
            chord = chords[b_idx % len(chords)]
            bass_f = bass_notes[b_idx % len(bass_notes)]

            pad_l = np.zeros(seg_len, dtype=np.float64)
            pad_r = np.zeros(seg_len, dtype=np.float64)
            lfo = 0.85 + 0.15 * np.sin(2.0 * np.pi * (0.24 + 0.03 * (b_idx % 3)) * seg_t)
            for i, freq in enumerate(chord):
                det_l = 1.0 + (0.0022 if i % 2 == 0 else -0.0017)
                det_r = 1.0 + (-0.0022 if i % 2 == 0 else 0.0017)
                pan_l = 0.68 if i % 2 == 0 else 0.36
                pan_r = 0.36 if i % 2 == 0 else 0.68
                voice_l = np.sin(2.0 * np.pi * (freq * det_l) * seg_t) + 0.35 * np.sin(2.0 * np.pi * (freq * 2.0) * seg_t)
                voice_r = np.sin(2.0 * np.pi * (freq * det_r) * seg_t) + 0.35 * np.sin(2.0 * np.pi * (freq * 2.0) * seg_t)
                pad_l += voice_l * (0.15 * pan_l)
                pad_r += voice_r * (0.15 * pan_r)

            attack_s = min(0.20, max(0.04, seg_len / float(SAMPLE_RATE) * 0.12))
            pad_env = np.minimum(1.0, seg_t / attack_s) * np.minimum(1.0, (seg_t[-1] - seg_t + 1e-4) / attack_s)
            left[start:end] += pad_l * pad_env * lfo
            right[start:end] += pad_r * pad_env * lfo

            if perc_style == "bouncy_pizzicato":
                bounce_env = np.exp(-5.5 * (seg_t % (beat_s * 0.5)))
                sub_wave = np.sin(2.0 * np.pi * bass_f * seg_t) * 0.20 * bounce_env
            else:
                wobble = 1.0 + 0.0025 * np.sin(2.0 * np.pi * 1.4 * seg_t)
                sub_wave = np.tanh(sub_drive * np.sin(2.0 * np.pi * (bass_f * wobble) * seg_t)) * 0.18
            left[start:end] += sub_wave
            right[start:end] += sub_wave

            for st_idx in range(8):
                st_pos = start + st_idx * step_samples
                if st_pos >= end:
                    break
                st_end = min(end, st_pos + step_samples)
                st_len = st_end - st_pos
                if st_len <= 16:
                    continue
                nt = np.linspace(0.0, st_len / float(SAMPLE_RATE), st_len, endpoint=False)
                root_note = chord[0] * (2.0 if perc_style != "lofi_boom_bap" else 1.0)
                ratio = motif_intervals[(st_idx + (b_idx % 2)) % len(motif_intervals)]
                note_f = root_note * ratio
                decay = 8.5 if perc_style == "bouncy_pizzicato" else 4.8
                pluck_env = np.minimum(1.0, nt / 0.008) * np.exp(-decay * nt)
                pluck = (
                    np.sin(2.0 * np.pi * note_f * nt)
                    + 0.45 * np.sin(2.0 * np.pi * (note_f * 2.0) * nt) * np.exp(-8.0 * nt)
                ) * pluck_env * 0.16
                pan_alt = 0.72 if st_idx % 2 == 0 else 0.36
                left[st_pos:st_end] += pluck * pan_alt
                right[st_pos:st_end] += pluck * (1.08 - pan_alt)

        total_beats = int(math.ceil(n / float(beat_samples)))
        for bt in range(total_beats):
            pos = bt * beat_samples
            if pos >= n:
                break
            k_len = min(int(0.45 * SAMPLE_RATE), n - pos)
            if k_len <= 16:
                continue
            kt = np.linspace(0.0, k_len / float(SAMPLE_RATE), k_len, endpoint=False)
            if bt % 2 == 0:
                f_sweep = 90.0 * np.exp(-22.0 * kt) + 52.0
                phase = 2.0 * np.pi * np.cumsum(f_sweep) / float(SAMPLE_RATE)
                kick = np.tanh(1.4 * np.sin(phase)) * np.exp(-13.5 * kt) * 0.17
                left[pos : pos + k_len] += kick
                right[pos : pos + k_len] += kick
            else:
                noise = rng.standard_normal(k_len)
                hat_l = _bandpass(noise, 5200.0, 12500.0) * np.exp(-55.0 * kt) * 0.065
                hat_r = _bandpass(rng.standard_normal(k_len), 5400.0, 12800.0) * np.exp(-58.0 * kt) * 0.065
                left[pos : pos + k_len] += hat_l
                right[pos : pos + k_len] += hat_r

        cutoff_hz = float(prof.get("cutoff_hz", 6500.0))
        left_eq = _lowpass(left, cutoff_hz, order=2)
        right_eq = _lowpass(right, cutoff_hz, order=2)
        fade_in = min(int(0.15 * SAMPLE_RATE), n // 8)
        fade_out = min(int(0.25 * SAMPLE_RATE), n // 6)
        if fade_in > 0:
            left_eq[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
            right_eq[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
        if fade_out > 0:
            left_eq[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)
            right_eq[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)
        stereo = np.column_stack([left_eq, right_eq])

    target_out.parent.mkdir(parents=True, exist_ok=True)
    tmp_wav = target_out.with_name(f"{target_out.stem}_raw_tmp.wav")
    _save_stereo_wav(tmp_wav, stereo, sr=SAMPLE_RATE)

    # Exact linear LUFS calibration to -16.0 LUFS + transparent 192kHz peak limiter
    # (preserves 100% of the 4-Movement macro dynamic range LRA >= 4.5 LU — zero dynamic loudnorm crushing!)
    raw_lufs = _measure_lufs_flow(tmp_wav)
    cal_db = max(-14.0, min(14.0, -16.0 - raw_lufs)) if raw_lufs is not None else 0.0
    master_af = (
        f"volume={cal_db:+.2f}dB,"
        "aresample=192000,"
        "alimiter=limit=0.84:level=false:attack=3:release=45:latency=true,"
        f"aresample={SAMPLE_RATE}"
    )

    if target_out.suffix.lower() == ".wav":
        try:
            norm_wav = target_out.with_name(f"{target_out.stem}_lufs_tmp.wav")
            run_ffmpeg_safe(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(tmp_wav),
                    "-af",
                    master_af,
                    "-c:a",
                    "pcm_s16le",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "2",
                    str(norm_wav),
                ]
            )
            norm_wav.replace(target_out)
            tmp_wav.unlink(missing_ok=True)
        except Exception:
            tmp_wav.replace(target_out)
        final_file = target_out
    else:
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
                    master_af,
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "2",
                    str(target_out),
                ]
            )
            tmp_wav.unlink(missing_ok=True)
            final_file = target_out
        except Exception:
            final_file = tmp_wav

    return {
        "path": final_file,
        "profile": prof_str,
        "bpm": round(bpm, 1),
        "bars": eff_bars,
        "key": prof["key"],
        "duration_s": round(total_s, 2),
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "lufs_target": -16.0,
        "score_version": DARK_SCORE_VERSION if is_dark_cinema else "v7_procedural",
    }


def _generate_procedural_bgm_wav(
    out_wav: Union[Path, str],
    mood_raw: str = "dark_horror_cinema",
    duration_s: float = DARK_SCORE_DURATION_S,
) -> Dict[str, Any]:
    """Generate a bar-locked 48kHz stereo WAV BGM score (4-Movement Evolving Score for dark_horror_cinema)."""
    target_wav = Path(out_wav)
    if target_wav.suffix.lower() != ".wav":
        target_wav = target_wav.with_suffix(".wav")
    return _synthesize_procedural_track(
        out_mp3=target_wav,
        mood_raw=mood_raw,
        profile_key=normalize_music_mood(mood_raw),
        duration_s=duration_s,
    )


# Keep backward-compatible alias
_synthesize_flow_music_bed = _synthesize_procedural_track


def measure_track_midband_rms(
    audio_path: Path,
    low_hz: float = 400.0,
    high_hz: float = 2500.0,
) -> Tuple[float, float, float]:
    """Return `(mid_rms, total_rms, mid_to_total_ratio)` for an audio file in the 400-2500 Hz vocal band."""
    p = Path(audio_path)
    if not p.exists() or p.stat().st_size < 256:
        return 0.0, 0.0, 0.0
    try:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
            capture_output=True,
            timeout=60,
        )
        if not res.stdout:
            return 0.0, 0.0, 0.0
        pcm = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float64) / 32768.0
        if len(pcm) < 256:
            return 0.0, 0.0, 0.0
        total_rms = float(np.sqrt(np.mean(pcm * pcm) + 1e-12))
        mid = _bandpass(pcm, low_hz, high_hz, sr=SAMPLE_RATE, order=3)
        mid_rms = float(np.sqrt(np.mean(mid * mid) + 1e-12))
        return mid_rms, total_rms, (mid_rms / max(1e-9, total_rms))
    except Exception:
        return 0.0, 0.0, 0.0


def _probe_audio_duration_s(audio_path: Path) -> float:
    p = Path(audio_path)
    if not p.exists() or p.stat().st_size < 256:
        return 0.0
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(res.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def ensure_upgraded_dark_horror_music(
    force_regen: bool = True,
    duration_s: float = DARK_SCORE_DURATION_S,
) -> Path:
    """Regenerate BOTH `data/flow_vault/music/dark_horror_cinema.wav` AND
    `assets/music/dark_mystery_horror.mp3` with the metric bar-locked 48-bar (`174.55s` @ `66 BPM`)
    4-Movement Evolving Documentary Score whenever `force_regen=True`, either file is missing/short
    (`< 110s`), or mid-band (`400-2500 Hz`) is unbalanced/masking (`> 0.45` ratio).
    Returns the ready `assets/music/dark_mystery_horror.mp3` path.
    """
    ensure_vault_dirs()
    assets_music_dir = BASE_DIR / "assets" / "music"
    assets_music_dir.mkdir(parents=True, exist_ok=True)
    dark_mp3 = assets_music_dir / "dark_mystery_horror.mp3"
    vault_wav = VAULT_MUSIC_DIR / "dark_horror_cinema.wav"

    mp3_dur = _probe_audio_duration_s(dark_mp3)
    wav_dur = _probe_audio_duration_s(vault_wav)
    mid_rms, total_rms, mid_ratio = measure_track_midband_rms(dark_mp3)
    needs_upgrade = (
        bool(force_regen)
        or (not dark_mp3.exists())
        or (not vault_wav.exists())
        or (mp3_dur < 110.0)
        or (wav_dur < 110.0)
        or (total_rms < 0.04)
        or (mid_ratio > 0.45)
    )

    if needs_upgrade:
        # 1. Generate canonical 48-bar 4-Movement WAV in data/flow_vault/music/dark_horror_cinema.wav
        meta = _generate_procedural_bgm_wav(
            out_wav=vault_wav,
            mood_raw="dark_horror_cinema",
            duration_s=duration_s,
        )
        # 2. Encode assets/music/dark_mystery_horror.mp3 cleanly from that exact bar-locked WAV
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(vault_wav),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "2",
                str(dark_mp3),
            ]
        )
        # 3. Register in FlowVault index for zero-credit reuse
        vault = get_flow_vault()
        dur_bucket = f"{int(round(max(12.0, float(meta['duration_s'])) / 5.0) * 5)}s"
        vault.store_asset(
            kind="music",
            prompt_or_mood="dark_horror_cinema",
            file_path=vault_wav,
            aspect_ratio="stereo",
            credits_cost=0,
            extra=dur_bucket,
            copy_into_vault=False,
            metadata={
                "mood": "dark_horror_cinema",
                "mood_profile": "dark_horror_cinema",
                "bpm": meta["bpm"],
                "bars": meta.get("bars", DARK_SCORE_BARS),
                "key": meta["key"],
                "duration_s": meta["duration_s"],
                "sample_rate": SAMPLE_RATE,
                "channels": 2,
                "source": "flowmusic.app_vault_dsp_4movement",
                "score_version": DARK_SCORE_VERSION,
                "lufs_target": -16.0,
                "sidechain_ready": True,
            },
        )

    return dark_mp3.resolve()


def fetch_or_generate_flow_music_sync(
    mood: str,
    duration_s: float = 30.0,
    prompt: Optional[str] = None,
    force_regen: bool = False,
) -> Path:
    """Synchronous implementation of `fetch_or_generate_flow_music`."""
    vault = get_flow_vault()
    clean_mood = (mood or "dark_investigative").strip()
    profile_key = normalize_music_mood(f"{clean_mood} {prompt or ''}")
    dur_bucket = f"{int(round(max(12.0, float(duration_s)) / 5.0) * 5)}s"
    query_key = f"{clean_mood}|{prompt or ''}" if prompt else clean_mood

    if not force_regen:
        # 1. Exact mood + duration bucket lookup in vault
        hit = vault.lookup_asset(
            kind="music",
            prompt_or_mood=query_key,
            aspect_ratio="stereo",
            extra=dur_bucket,
            record_reuse=True,
        )
        if hit and Path(hit["abs_path"]).exists():
            return Path(hit["abs_path"])

        # 2. Fallback check: any existing vault track with same normalized mood & duration >= requested
        index = vault.load_index()
        for entry in index.get("music", {}).values():
            if entry.get("mood_profile") == profile_key and float(entry.get("duration_s", 0.0)) >= float(duration_s) * 0.85:
                cand = BASE_DIR / entry.get("path", "")
                if cand.exists() and cand.stat().st_size > 1024:
                    entry["reuse_count"] = int(entry.get("reuse_count", 0)) + 1
                    index["stats"]["total_reuses"] = int(index["stats"].get("total_reuses", 0)) + 1
                    vault.save_index(index)
                    return cand.resolve()

    # 3. Synthesize tailored broadcast stereo track and index in data/flow_vault/
    track_hash = compute_vault_hash(query_key, kind="music", aspect_ratio="stereo", extra=dur_bucket)
    out_mp3 = vault.music_dir / f"flow_music_{profile_key}_{track_hash}.mp3"
    synth_meta = _synthesize_flow_music_bed(
        out_mp3=out_mp3,
        mood_raw=query_key,
        profile_key=profile_key,
        duration_s=duration_s,
    )
    final_path = Path(synth_meta["path"])
    vault.store_asset(
        kind="music",
        prompt_or_mood=query_key,
        file_path=final_path,
        aspect_ratio="stereo",
        credits_cost=0,
        extra=dur_bucket,
        copy_into_vault=False,
        metadata={
            "mood": clean_mood,
            "mood_profile": profile_key,
            "bpm": synth_meta["bpm"],
            "key": synth_meta["key"],
            "duration_s": synth_meta["duration_s"],
            "sample_rate": synth_meta["sample_rate"],
            "channels": synth_meta["channels"],
            "source": "flowmusic.app_vault_dsp",
            "lufs_target": -16.0,
            "sidechain_ready": True,
        },
    )
    return final_path.resolve()


async def fetch_or_generate_flow_music(
    mood: str,
    duration_s: float = 30.0,
    prompt: Optional[str] = None,
    force_regen: bool = False,
) -> Path:
    """Check `data/flow_vault/` first; synthesize/automate a broadcast stereo instrumental track
    tailored to `mood` when needed, index it in `data/flow_vault/vault_index.json`, and return
    a ready `.mp3`/`.wav` `Path` for `-14 LUFS` `sidechaincompress` (0 credits).
    """
    return await asyncio.to_thread(
        fetch_or_generate_flow_music_sync,
        mood,
        duration_s,
        prompt,
        force_regen,
    )


if __name__ == "__main__":
    async def _selftest() -> None:
        p1 = await fetch_or_generate_flow_music("dark_investigative", duration_s=15.0)
        p2 = await fetch_or_generate_flow_music("dark_investigative", duration_s=15.0)
        stats = get_vault_stats()
        print(json.dumps({"track": str(p1), "reused_same_path": p1 == p2, "stats": stats}, indent=2, ensure_ascii=False))

    asyncio.run(_selftest())
