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
    "key": "D Minor / Phrygian (Gothic Horror, Cello Ostinato & Macabre Celesta)",
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
# High-Craft Broadcast Stereo Music Synthesizer (48kHz, Vocal-Pocket EQ)
# ---------------------------------------------------------------------------
def _bandpass(x: np.ndarray, low: float, high: float, sr: int = SAMPLE_RATE, order: int = 3) -> np.ndarray:
    nyq = 0.5 * sr
    lo = max(20.0, min(low, nyq - 200.0)) / nyq
    hi = max(lo + 0.01, min(high, nyq - 100.0) / nyq)
    sos = signal.butter(order, [lo, hi], btype="band", output="sos")
    return signal.sosfilt(sos, x)


def _save_stereo_wav(path: Path, stereo: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    if stereo.ndim == 1:
        stereo = np.column_stack([stereo, stereo])
    # Target -16.0 LUFS (~0.158 RMS) with soft saturation ceiling at -1.5 dBFS (0.84)
    rms = float(np.sqrt(np.mean(stereo * stereo) + 1e-12))
    if rms > 1e-6:
        scaled = stereo * (0.175 / rms)
        norm = np.tanh(scaled / 0.84) * 0.84
    else:
        peak = float(np.max(np.abs(stereo))) + 1e-9
        norm = np.clip((stereo / peak) * 0.84, -1.0, 1.0)
    pcm = (np.clip(norm, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _bowed_string_voice(
    freq: float,
    t_arr: np.ndarray,
    detune: float = 1.0,
    vib_hz: float = 4.6,
    vib_depth: float = 0.0036,
    phase_offset: float = 0.0,
) -> np.ndarray:
    """Synthesize a rich bowed Cello/Viola string voice with expressive vibrato and strong 250-2,200Hz harmonics."""
    vib = 1.0 + vib_depth * np.sin(2.0 * np.pi * vib_hz * t_arr + phase_offset)
    inst_f = (freq * detune) * vib
    ph = 2.0 * np.pi * np.cumsum(inst_f) / float(SAMPLE_RATE) + phase_offset
    # Fundamental + rich 2nd, 3rd, 4th, 5th, 6th overtones placing body right in 250-2,200 Hz
    return (
        0.48 * np.sin(ph)
        + 0.68 * np.sin(2.0 * ph + 0.15)
        + 0.52 * np.sin(3.0 * ph + 0.35)
        + 0.38 * np.sin(4.0 * ph + 0.55)
        + 0.24 * np.sin(5.0 * ph + 0.80)
        + 0.14 * np.sin(6.0 * ph + 1.05)
    )


def _synthesize_procedural_track(
    out_mp3: Union[Path, str],
    mood_raw: Union[str, float, Path] = "dark_horror_cinema",
    profile_key: Optional[Union[str, float]] = None,
    duration_s: float = 45.0,
) -> Dict[str, Any]:
    """Synthesize a rich, original 48kHz stereo Netflix/A24 dark-cinema instrumental score
    normalized to `-16.0 LUFS` with strong mid-range (`250-2,200 Hz`) instrumentation:
      a) Tense Bowed Cello & Viola Ostinato in D Minor (`66 BPM`, `146.8 Hz D3`, `174.6 Hz F3`,
         `220.0 Hz A3`, `233.1 Hz Bb3`, `207.6 Hz G#3` + bowed overtones & vibrato)
      b) Haunting Macabre Music-Box / Celesta & Minor Piano Motif (`587 Hz D5`, `698 Hz F5`,
         `880 Hz A5`, `932 Hz Bb5`, `830 Hz G#5`, `659 Hz E5`) with bell-like metallic attack,
         exponential decay & dotted-8th stereo delay echo
      c) Distant Cathedral Tubular Bells (`293.7 Hz D4` + inharmonic partials) on bar boundaries
         + deep heartbeat sub-pulse (`55-90 Hz`).
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
    bpm = float(prof["bpm"]) if is_dark_cinema else (float(prof["bpm"]) + float((seed_int % 5) - 2) * 0.5)
    beat_s = 60.0 / bpm
    bar_s = beat_s * 4.0
    bars = max(4, int(math.ceil(target_s / bar_s)))
    total_s = target_s
    n = int(round(total_s * SAMPLE_RATE))

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)
    celesta_l = np.zeros(n, dtype=np.float64)
    celesta_r = np.zeros(n, dtype=np.float64)

    chords: List[List[float]] = prof["chords"]
    bass_notes: List[float] = prof["bass_notes"]
    motif_intervals: List[float] = prof["motif_intervals"]
    ostinato_notes: List[float] = prof.get(
        "ostinato_notes",
        [146.83, 174.61, 220.00, 233.08, 220.00, 207.65, 220.00, 174.61],
    )
    celesta_notes: List[float] = prof.get(
        "celesta_notes",
        [587.33, 698.46, 880.00, 932.33, 880.00, 830.61, 698.46, 659.25],
    )
    bell_notes: List[float] = prof.get("bell_notes", [293.66, 233.08, 293.66, 220.00])
    sub_drive = float(prof.get("sub_drive", 1.5))
    perc_style = str(prof.get("perc_style", "investigative_pulse"))

    bar_samples = max(1, int(round(bar_s * SAMPLE_RATE)))
    beat_samples = max(1, int(round(beat_s * SAMPLE_RATE)))
    step_samples = max(1, beat_samples // 2)  # 8th-note grid

    for b_idx in range(bars):
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

        # 1. Sustained Bowed Cello & Viola Ensemble Section (or Stereo Polysynth Pad)
        pad_l = np.zeros(seg_len, dtype=np.float64)
        pad_r = np.zeros(seg_len, dtype=np.float64)
        lfo = 0.85 + 0.15 * np.sin(2.0 * np.pi * (0.24 + 0.03 * (b_idx % 3)) * seg_t)
        for i, freq in enumerate(chord):
            det_l = 1.0 + (0.0022 if i % 2 == 0 else -0.0017)
            det_r = 1.0 + (-0.0022 if i % 2 == 0 else 0.0017)
            pan_l = 0.68 if i % 2 == 0 else 0.36
            pan_r = 0.36 if i % 2 == 0 else 0.68
            if is_dark_cinema:
                voice_l = _bowed_string_voice(freq, seg_t, detune=det_l, vib_hz=4.4 + 0.25 * i, phase_offset=0.5 * i)
                voice_r = _bowed_string_voice(freq, seg_t, detune=det_r, vib_hz=4.5 + 0.22 * i, phase_offset=0.5 * i + 0.7)
                pad_l += voice_l * (0.18 * pan_l)
                pad_r += voice_r * (0.18 * pan_r)
            else:
                voice_l = np.sin(2.0 * np.pi * (freq * det_l) * seg_t) + 0.35 * np.sin(2.0 * np.pi * (freq * 2.0) * seg_t)
                voice_r = np.sin(2.0 * np.pi * (freq * det_r) * seg_t) + 0.35 * np.sin(2.0 * np.pi * (freq * 2.0) * seg_t)
                pad_l += voice_l * (0.15 * pan_l)
                pad_r += voice_r * (0.15 * pan_r)

        attack_s = min(0.20, max(0.04, seg_len / float(SAMPLE_RATE) * 0.12))
        pad_env = np.minimum(1.0, seg_t / attack_s) * np.minimum(1.0, (seg_t[-1] - seg_t + 1e-4) / attack_s)
        left[start:end] += pad_l * pad_env * lfo
        right[start:end] += pad_r * pad_env * lfo

        # 2. Controlled Deep Sub-Bass Foundation (55-90 Hz)
        if perc_style == "horror_heartbeat":
            swell = 0.55 + 0.45 * np.sin(np.pi * seg_t / max(0.1, seg_t[-1]))
            eerie_det = 1.0 + 0.003 * np.sin(2.0 * np.pi * 0.35 * seg_t)
            sub_wave = np.tanh(
                sub_drive * (0.70 * np.sin(2.0 * np.pi * (bass_f * eerie_det) * seg_t) + 0.45 * np.sin(2.0 * np.pi * (bass_f * 2.0) * seg_t))
            ) * 0.14 * swell
        elif perc_style in ("investigative_pulse", "driving_viral"):
            pulse_rate = (bpm / 60.0) * 2.0
            pulse_env = 0.55 + 0.45 * np.sin(2.0 * np.pi * pulse_rate * seg_t)
            sub_wave = np.tanh(sub_drive * np.sin(2.0 * np.pi * bass_f * seg_t)) * 0.16 * pulse_env
        elif perc_style == "cinema_taiko":
            swell = 0.60 + 0.40 * np.sin(np.pi * seg_t / max(0.1, seg_t[-1]))
            sub_wave = np.tanh(sub_drive * (np.sin(2.0 * np.pi * bass_f * seg_t) + 0.40 * np.sin(2.0 * np.pi * (bass_f * 2.0) * seg_t))) * 0.16 * swell
        elif perc_style == "bouncy_pizzicato":
            bounce_env = np.exp(-5.5 * (seg_t % (beat_s * 0.5)))
            sub_wave = np.sin(2.0 * np.pi * bass_f * seg_t) * 0.20 * bounce_env
        else:
            wobble = 1.0 + 0.0025 * np.sin(2.0 * np.pi * 1.4 * seg_t)
            sub_wave = np.tanh(sub_drive * np.sin(2.0 * np.pi * (bass_f * wobble) * seg_t)) * 0.18

        left[start:end] += sub_wave
        right[start:end] += sub_wave

        # 3a. Tense Bowed Cello & Viola 8th-Note Ostinato in D Minor (146.8-233.1 Hz + 2nd/3rd/4th/5th overtones)
        # 3b. Haunting Macabre Music-Box / Celesta & Minor Piano Motif (587-932 Hz + stereo delay echo)
        for st_idx in range(8):
            st_pos = start + st_idx * step_samples
            if st_pos >= end:
                break

            if is_dark_cinema:
                # (a) Bowed Cello & Viola Ostinato stroke
                ost_end = min(n, st_pos + int(step_samples * 1.25))
                ost_len = ost_end - st_pos
                if ost_len > 32:
                    ot = np.linspace(0.0, ost_len / float(SAMPLE_RATE), ost_len, endpoint=False)
                    ost_f = ostinato_notes[(st_idx + (b_idx % 2) * 2) % len(ostinato_notes)]
                    bow_atk = 1.0 - np.exp(-ot / 0.024)
                    bow_dec = np.exp(-2.35 * ot)
                    bow_env = bow_atk * bow_dec
                    # Cello fundamental (D3..Bb3) + Viola octave double (D4..Bb4) with rich mid-band harmonics
                    cello_sig = _bowed_string_voice(ost_f, ot, detune=0.999, vib_hz=4.8, phase_offset=st_idx * 0.4)
                    viola_sig = _bowed_string_voice(ost_f * 2.0, ot, detune=1.0015, vib_hz=5.1, phase_offset=st_idx * 0.6 + 0.5)
                    rosin = _bandpass(rng.standard_normal(ost_len), 420.0, 1750.0, order=2) * np.exp(-6.5 * ot) * 0.08
                    ost_accent = 1.18 if (st_idx % 2 == 0) else 0.88
                    bow_wave_l = (cello_sig * 0.64 + viola_sig * 0.44 + rosin) * bow_env * 0.25 * ost_accent
                    bow_wave_r = (cello_sig * 0.46 + viola_sig * 0.62 + rosin) * bow_env * 0.25 * ost_accent
                    left[st_pos:ost_end] += bow_wave_l
                    right[st_pos:ost_end] += bow_wave_r

                # (b) Haunting Macabre Music-Box / Celesta & Minor Piano Motif
                cel_end = min(n, st_pos + int(step_samples * 2.4))
                cel_len = cel_end - st_pos
                if cel_len > 32:
                    ct = np.linspace(0.0, cel_len / float(SAMPLE_RATE), cel_len, endpoint=False)
                    cel_f = celesta_notes[(st_idx + (b_idx % 4) * 2) % len(celesta_notes)]
                    # Bell-like metallic attack + warm minor piano octave body (293-466 Hz) + crystalline celesta (587-932 Hz)
                    cel_atk = 1.0 - np.exp(-ct / 0.0035)
                    cel_body = (
                        0.68 * np.sin(2.0 * np.pi * cel_f * ct) * np.exp(-2.15 * ct)
                        + 0.48 * np.sin(2.0 * np.pi * (cel_f * 0.5) * ct) * np.exp(-1.75 * ct)
                        + 0.34 * np.sin(2.0 * np.pi * (cel_f * 2.0) * ct) * np.exp(-3.8 * ct)
                        + 0.20 * np.sin(2.0 * np.pi * (cel_f * 3.008) * ct) * np.exp(-9.5 * ct)
                        + 0.12 * np.sin(2.0 * np.pi * (cel_f * 4.19) * ct) * np.exp(-16.0 * ct)
                    ) * cel_atk
                    cel_gain = 0.24 if (st_idx in (0, 2, 3, 5, 6)) else 0.16
                    pan_c = 0.76 if (st_idx % 2 == 0) else 0.28
                    celesta_l[st_pos:cel_end] += cel_body * cel_gain * pan_c
                    celesta_r[st_pos:cel_end] += cel_body * cel_gain * (1.04 - pan_c)
            else:
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

        # 3c. Distant Cathedral Tubular Bells (293.7 Hz D4 + inharmonic bell partials) on bar boundaries
        if is_dark_cinema:
            bell_len = min(n - start, int(2.85 * SAMPLE_RATE))
            if bell_len > 64:
                bt_arr = np.linspace(0.0, bell_len / float(SAMPLE_RATE), bell_len, endpoint=False)
                bell_f = bell_notes[b_idx % len(bell_notes)]
                bell_atk = 1.0 - np.exp(-bt_arr / 0.005)
                # Authentic tubular bell inharmonic partials centered around 293.66 Hz (D4) -> 1,200 Hz
                bell_sig_l = (
                    0.42 * np.sin(2.0 * np.pi * (bell_f * 0.5) * bt_arr) * np.exp(-1.15 * bt_arr)
                    + 0.95 * np.sin(2.0 * np.pi * bell_f * bt_arr) * np.exp(-1.45 * bt_arr)
                    + 0.58 * np.sin(2.0 * np.pi * (bell_f * 1.183) * bt_arr + 0.3) * np.exp(-1.85 * bt_arr)
                    + 0.48 * np.sin(2.0 * np.pi * (bell_f * 1.506) * bt_arr + 0.7) * np.exp(-2.15 * bt_arr)
                    + 0.62 * np.sin(2.0 * np.pi * (bell_f * 2.002) * bt_arr + 1.1) * np.exp(-2.45 * bt_arr)
                    + 0.34 * np.sin(2.0 * np.pi * (bell_f * 2.514) * bt_arr + 1.5) * np.exp(-3.10 * bt_arr)
                    + 0.22 * np.sin(2.0 * np.pi * (bell_f * 3.011) * bt_arr + 1.9) * np.exp(-3.90 * bt_arr)
                ) * bell_atk * 0.21
                bell_sig_r = np.roll(bell_sig_l, 22) * 0.98
                left[start : start + bell_len] += bell_sig_l
                right[start : start + bell_len] += bell_sig_r

    # Apply stereo ping-pong delay echo to Macabre Music-Box / Celesta motif
    if is_dark_cinema:
        d1 = max(1, int(round(beat_s * 0.375 * SAMPLE_RATE)))  # dotted-16th / 8th stereo echo
        d2 = max(1, int(round(beat_s * 0.75 * SAMPLE_RATE)))
        echo_l = celesta_l.copy()
        echo_r = celesta_r.copy()
        if d1 < n:
            echo_l[d1:] += celesta_r[:-d1] * 0.48
            echo_r[d1:] += celesta_l[:-d1] * 0.48
        if d2 < n:
            echo_l[d2:] += celesta_l[:-d2] * 0.26
            echo_r[d2:] += celesta_r[:-d2] * 0.26
        left += echo_l
        right += echo_r

    # 4. Broadcast Rhythmic Percussion & Deep Heartbeat Sub-Pulse (55-90 Hz)
    total_beats = int(math.ceil(n / float(beat_samples)))
    for bt in range(total_beats):
        pos = bt * beat_samples
        if pos >= n:
            break
        k_len = min(int(0.45 * SAMPLE_RATE), n - pos)
        if k_len <= 16:
            continue
        kt = np.linspace(0.0, k_len / float(SAMPLE_RATE), k_len, endpoint=False)

        if perc_style == "horror_heartbeat":
            if bt % 2 == 0:
                # Deep realistic double-thump heartbeat sub-pulse (55-90 Hz)
                f_lub = 56.0 + 34.0 * np.exp(-18.0 * kt)
                ph_lub = 2.0 * np.pi * np.cumsum(f_lub) / float(SAMPLE_RATE)
                lub = np.tanh(1.4 * np.sin(ph_lub)) * np.exp(-9.5 * kt) * 0.15
                dt_dub = np.maximum(0.0, kt - 0.24)
                m_dub = (kt >= 0.24).astype(np.float64)
                f_dub = 55.0 + 30.0 * np.exp(-20.0 * dt_dub)
                ph_dub = 2.0 * np.pi * np.cumsum(f_dub * m_dub) / float(SAMPLE_RATE)
                dub = m_dub * np.tanh(1.3 * np.sin(ph_dub)) * np.exp(-11.0 * dt_dub) * 0.12
                thump = lub + dub
                left[pos : pos + k_len] += thump
                right[pos : pos + k_len] += thump
            continue

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

        off_pos = pos + step_samples
        if off_pos < n and perc_style in ("investigative_pulse", "modern_tech", "driving_viral"):
            gh_len = min(int(0.08 * SAMPLE_RATE), n - off_pos)
            if gh_len > 16:
                ght = np.linspace(0.0, gh_len / float(SAMPLE_RATE), gh_len, endpoint=False)
                gh = _bandpass(rng.standard_normal(gh_len), 6500.0, 13000.0) * np.exp(-85.0 * ght) * 0.04
                left[off_pos : off_pos + gh_len] += gh * 0.8
                right[off_pos : off_pos + gh_len] += gh * 1.1

    # 5. Warm Cinema Filtering (preserving full 250-2,200 Hz Cello + Celesta + Tubular Bell clarity!)
    nyq = 0.5 * SAMPLE_RATE
    cutoff_hz = float(prof.get("cutoff_hz", 6500.0))
    sos_lp = signal.butter(2, min(cutoff_hz, nyq - 200.0) / nyq, btype="low", output="sos")
    left_eq = signal.sosfilt(sos_lp, left)
    right_eq = signal.sosfilt(sos_lp, right)

    # Reinforce 280-2,100 Hz mid-range presence for mobile & broadcast speaker translation
    if is_dark_cinema:
        mid_l = _bandpass(left_eq, 280.0, 2100.0, order=2)
        mid_r = _bandpass(right_eq, 280.0, 2100.0, order=2)
        left_eq = left_eq + 0.38 * mid_l
        right_eq = right_eq + 0.38 * mid_r

    # Smooth 0.15s fade-in and 0.25s fade-out so looping is click-free
    fade_in = min(int(0.15 * SAMPLE_RATE), n // 8)
    fade_out = min(int(0.25 * SAMPLE_RATE), n // 6)
    if fade_in > 0:
        env_in = np.linspace(0.0, 1.0, fade_in)
        left_eq[:fade_in] *= env_in
        right_eq[:fade_in] *= env_in
    if fade_out > 0:
        env_out = np.linspace(1.0, 0.0, fade_out)
        left_eq[-fade_out:] *= env_out
        right_eq[-fade_out:] *= env_out

    stereo = np.column_stack([left_eq, right_eq])
    target_out.parent.mkdir(parents=True, exist_ok=True)
    tmp_wav = target_out.with_name(f"{target_out.stem}_raw_tmp.wav")
    _save_stereo_wav(tmp_wav, stereo, sr=SAMPLE_RATE)

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
                    "loudnorm=I=-16.0:TP=-1.5:LRA=9",
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
                    "loudnorm=I=-16.0:TP=-1.5:LRA=9",
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
        "key": prof["key"],
        "duration_s": round(total_s, 2),
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "lufs_target": -16.0,
    }


# Keep backward-compatible alias
_synthesize_flow_music_bed = _synthesize_procedural_track


def measure_track_midband_rms(
    audio_path: Path,
    low_hz: float = 300.0,
    high_hz: float = 2000.0,
) -> Tuple[float, float, float]:
    """Return `(mid_rms, total_rms, mid_to_total_ratio)` for an audio file in the 300-2000 Hz mid-band."""
    p = Path(audio_path)
    if not p.exists() or p.stat().st_size < 256:
        return 0.0, 0.0, 0.0
    try:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
            capture_output=True,
            timeout=30,
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


def ensure_upgraded_dark_horror_music(force_regen: bool = True, duration_s: float = 45.0) -> Path:
    """Regenerate both the `FlowVault` `dark_horror_cinema` track AND `assets/music/dark_mystery_horror.mp3`
    whenever `force_regen=True` OR when existing track mid-band (`300-2000 Hz`) RMS is too weak (`< 0.068`).
    Returns the ready `assets/music/dark_mystery_horror.mp3` path.
    """
    assets_music_dir = BASE_DIR / "assets" / "music"
    assets_music_dir.mkdir(parents=True, exist_ok=True)
    dark_mp3 = assets_music_dir / "dark_mystery_horror.mp3"

    mid_rms, _, mid_ratio = measure_track_midband_rms(dark_mp3)
    assets_weak = (not dark_mp3.exists()) or (mid_rms < 0.068) or (mid_ratio < 0.42)

    vault_path = fetch_or_generate_flow_music_sync(
        "dark_horror_cinema",
        duration_s=duration_s,
        force_regen=bool(force_regen or assets_weak),
    )
    v_mid_rms, _, v_mid_ratio = measure_track_midband_rms(vault_path)
    if v_mid_rms < 0.068 or v_mid_ratio < 0.42:
        vault_path = fetch_or_generate_flow_music_sync(
            "dark_horror_cinema",
            duration_s=duration_s,
            force_regen=True,
        )

    if force_regen or assets_weak:
        if vault_path.exists() and vault_path.resolve() != dark_mp3.resolve():
            shutil.copy2(vault_path, dark_mp3)
        else:
            _synthesize_procedural_track(
                out_mp3=dark_mp3,
                mood_raw="dark_horror_cinema",
                profile_key="dark_horror_cinema",
                duration_s=duration_s,
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
