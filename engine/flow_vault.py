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
from typing import Any, Dict, List, Optional, Tuple

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
MOOD_PROFILES: Dict[str, Dict[str, Any]] = {
    "dark_investigative": {
        "bpm": 98.0,
        "key": "D Minor (Dorian/Aeolian Tension)",
        "chords": [
            [146.83, 174.61, 220.00, 261.63],  # Dm7
            [130.81, 164.81, 196.00, 246.94],  # Cmaj7/E tension
            [116.54, 146.83, 174.61, 220.00],  # Bbmaj7
            [110.00, 138.59, 164.81, 207.65],  # A7alt
        ],
        "bass_notes": [73.42, 65.41, 58.27, 55.00],
        "motif_intervals": [1.0, 1.189, 1.498, 1.335, 1.0, 1.782, 1.498, 1.189],
        "cutoff_hz": 5800.0,
        "sub_drive": 1.65,
        "perc_style": "investigative_pulse",
    },
    "epic_cinema": {
        "bpm": 92.0,
        "key": "C Minor (Cinema Documentary)",
        "chords": [
            [130.81, 155.56, 196.00, 261.63],  # Cm
            [103.83, 130.81, 155.56, 207.65],  # Ab
            [116.54, 146.83, 174.61, 233.08],  # Bb
            [98.00, 123.47, 146.83, 196.00],   # Gm
        ],
        "bass_notes": [65.41, 51.91, 58.27, 49.00],
        "motif_intervals": [1.0, 1.498, 2.0, 1.782, 1.498, 1.189, 1.0, 0.749],
        "cutoff_hz": 6800.0,
        "sub_drive": 1.85,
        "perc_style": "cinema_taiko",
    },
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
    peak = float(np.max(np.abs(stereo))) + 1e-9
    norm = np.clip((stereo / peak) * 0.86, -1.0, 1.0)
    pcm = (norm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _synthesize_flow_music_bed(
    out_mp3: Path,
    mood_raw: str,
    profile_key: str,
    duration_s: float,
) -> Dict[str, Any]:
    """Synthesize a rich, original 48kHz stereo instrumental track tailored to the script mood.

    Designed specifically for `-14 LUFS` voice `sidechaincompress`:
    - Stereo detuned analog polysynth pads with slow LFO filter movement
    - Deep harmonic sub-bass & rhythmic ostinato
    - Signature mood arpeggio/motif panned in wide stereo
    - Carved vocal pocket (1.2kHz - 3.4kHz gentle attenuation) so narration stays crystal clear
    """
    prof = MOOD_PROFILES.get(profile_key, MOOD_PROFILES["dark_investigative"])
    target_s = max(12.0, min(300.0, float(duration_s)))

    # Deterministic variation from the specific raw mood string so distinct mood prompts have unique character
    seed_int = int(hashlib.sha256((mood_raw or profile_key).encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed_int)

    bpm = float(prof["bpm"]) + float((seed_int % 5) - 2) * 0.5
    beat_s = 60.0 / bpm
    bar_s = beat_s * 4.0
    bars = max(4, int(math.ceil(target_s / bar_s)))
    total_s = target_s
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

        # 1. Wide Stereo Detuned Polysynth Pad + Octave Warmth
        pad_l = np.zeros(seg_len, dtype=np.float64)
        pad_r = np.zeros(seg_len, dtype=np.float64)
        lfo = 0.82 + 0.18 * np.sin(2.0 * np.pi * (0.22 + 0.03 * (b_idx % 3)) * seg_t)
        for i, freq in enumerate(chord):
            det_l = 1.0 + (0.0024 if i % 2 == 0 else -0.0018)
            det_r = 1.0 + (-0.0024 if i % 2 == 0 else 0.0018)
            pan_l = 0.65 if i % 2 == 0 else 0.38
            pan_r = 0.38 if i % 2 == 0 else 0.65
            voice_l = np.sin(2.0 * np.pi * (freq * det_l) * seg_t) + 0.25 * np.sin(2.0 * np.pi * (freq * 0.5) * seg_t)
            voice_r = np.sin(2.0 * np.pi * (freq * det_r) * seg_t) + 0.25 * np.sin(2.0 * np.pi * (freq * 0.5) * seg_t)
            pad_l += voice_l * (0.14 * pan_l)
            pad_r += voice_r * (0.14 * pan_r)

        attack_s = min(0.22, max(0.04, seg_len / float(SAMPLE_RATE) * 0.15))
        pad_env = np.minimum(1.0, seg_t / attack_s) * np.minimum(1.0, (seg_t[-1] - seg_t + 1e-4) / attack_s)
        left[start:end] += pad_l * pad_env * lfo
        right[start:end] += pad_r * pad_env * lfo

        # 2. Deep Sub-Bass & Harmonic Ostinato
        if perc_style in ("investigative_pulse", "driving_viral"):
            pulse_rate = (bpm / 60.0) * 2.0
            pulse_env = 0.55 + 0.45 * np.sin(2.0 * np.pi * pulse_rate * seg_t)
            sub_wave = np.tanh(sub_drive * np.sin(2.0 * np.pi * bass_f * seg_t)) * 0.27 * pulse_env
        elif perc_style == "cinema_taiko":
            swell = 0.60 + 0.40 * np.sin(np.pi * seg_t / max(0.1, seg_t[-1]))
            sub_wave = np.tanh(sub_drive * (np.sin(2.0 * np.pi * bass_f * seg_t) + 0.35 * np.sin(2.0 * np.pi * (bass_f * 2.0) * seg_t))) * 0.29 * swell
        elif perc_style == "bouncy_pizzicato":
            bounce_env = np.exp(-5.5 * (seg_t % (beat_s * 0.5)))
            sub_wave = np.sin(2.0 * np.pi * bass_f * seg_t) * 0.24 * bounce_env
        else:
            wobble = 1.0 + 0.0025 * np.sin(2.0 * np.pi * 1.4 * seg_t)
            sub_wave = np.tanh(sub_drive * np.sin(2.0 * np.pi * (bass_f * wobble) * seg_t)) * 0.23

        left[start:end] += sub_wave
        right[start:end] += sub_wave

        # 3. Signature Stereo Motif / Arpeggio Pluck (8th notes across the bar)
        root_note = chord[0] * (2.0 if perc_style != "lofi_boom_bap" else 1.0)
        for st_idx in range(8):
            st_pos = start + st_idx * step_samples
            if st_pos >= end:
                break
            st_end = min(end, st_pos + step_samples)
            st_len = st_end - st_pos
            if st_len <= 16:
                continue
            nt = np.linspace(0.0, st_len / float(SAMPLE_RATE), st_len, endpoint=False)
            ratio = motif_intervals[(st_idx + (b_idx % 2)) % len(motif_intervals)]
            note_f = root_note * ratio
            decay = 8.5 if perc_style == "bouncy_pizzicato" else 5.2
            pluck_env = np.minimum(1.0, nt / 0.008) * np.exp(-decay * nt)
            pluck = (np.sin(2.0 * np.pi * note_f * nt) + 0.35 * np.sin(2.0 * np.pi * (note_f * 2.0) * nt) * np.exp(-12.0 * nt)) * pluck_env * 0.11
            pan_alt = 0.72 if st_idx % 2 == 0 else 0.36
            left[st_pos:st_end] += pluck * pan_alt
            right[st_pos:st_end] += pluck * (1.08 - pan_alt)

    # 4. Broadcast Rhythmic Percussion & Cinematic Downbeats
    total_beats = int(math.ceil(n / float(beat_samples)))
    for bt in range(total_beats):
        pos = bt * beat_samples
        if pos >= n:
            break
        k_len = min(int(0.18 * SAMPLE_RATE), n - pos)
        if k_len <= 16:
            continue
        kt = np.linspace(0.0, k_len / float(SAMPLE_RATE), k_len, endpoint=False)

        if bt % 2 == 0:
            # Punchy low kick / heartbeat pulse
            f_sweep = 115.0 * np.exp(-28.0 * kt) + 41.0
            phase = 2.0 * np.pi * np.cumsum(f_sweep) / float(SAMPLE_RATE)
            kick = np.tanh(1.5 * np.sin(phase)) * np.exp(-14.5 * kt) * 0.25
            left[pos : pos + k_len] += kick
            right[pos : pos + k_len] += kick
        else:
            # Crisp stereo hat / shaker tick
            noise = rng.standard_normal(k_len)
            hat_l = _bandpass(noise, 5200.0, 12500.0) * np.exp(-55.0 * kt) * 0.075
            hat_r = _bandpass(rng.standard_normal(k_len), 5400.0, 12800.0) * np.exp(-58.0 * kt) * 0.075
            left[pos : pos + k_len] += hat_l
            right[pos : pos + k_len] += hat_r

        # Subtle off-beat ghost hi-hat on 8th note
        off_pos = pos + step_samples
        if off_pos < n and perc_style in ("investigative_pulse", "modern_tech", "driving_viral"):
            gh_len = min(int(0.08 * SAMPLE_RATE), n - off_pos)
            if gh_len > 16:
                ght = np.linspace(0.0, gh_len / float(SAMPLE_RATE), gh_len, endpoint=False)
                gh = _bandpass(rng.standard_normal(gh_len), 6500.0, 13000.0) * np.exp(-85.0 * ght) * 0.045
                left[off_pos : off_pos + gh_len] += gh * 0.8
                right[off_pos : off_pos + gh_len] += gh * 1.1

    # 5. Vocal-Pocket EQ & Warm Low-Pass Roll-Off (leaves 1.2kHz-3.4kHz roomy for narrator voice)
    nyq = 0.5 * SAMPLE_RATE
    cutoff_hz = float(prof.get("cutoff_hz", 6500.0))
    sos_lp = signal.butter(2, min(cutoff_hz, nyq - 200.0) / nyq, btype="low", output="sos")
    left_lp = signal.sosfilt(sos_lp, left)
    right_lp = signal.sosfilt(sos_lp, right)

    # Subtle vocal-band notch (-2.5dB equivalent by subtracting 22% of 1.3kHz-3.2kHz midrange from center)
    mid_band_l = _bandpass(left_lp, 1300.0, 3200.0, order=2)
    mid_band_r = _bandpass(right_lp, 1300.0, 3200.0, order=2)
    left_eq = left_lp - 0.22 * mid_band_l
    right_eq = right_lp - 0.22 * mid_band_r

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
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp_wav = out_mp3.with_suffix(".wav")
    _save_stereo_wav(tmp_wav, stereo, sr=SAMPLE_RATE)

    try:
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(tmp_wav),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "2",
                str(out_mp3),
            ]
        )
        tmp_wav.unlink(missing_ok=True)
        final_file = out_mp3
    except Exception:
        # Keep crystal-clear WAV if mp3 encoder unavailable
        final_file = tmp_wav

    return {
        "path": final_file,
        "profile": profile_key,
        "bpm": round(bpm, 1),
        "key": prof["key"],
        "duration_s": round(total_s, 2),
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
    }


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
            "lufs_target": -14.0,
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
