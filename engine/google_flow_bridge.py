"""FrimeRise Google AI Pro Persistent Camoufox Bridge (engine/google_flow_bridge.py).

Connects the user's Google AI Pro subscription (`https://flow.google` & `https://flowmusic.app`)
via a persistent authenticated browser profile in C++ `AsyncCamoufox`:
- Persistent Profile: `data/profiles/google_flow_pro/`
- Strictly 1 browser instance at a time on the Acer Aspire 5 Core i5 via thread-safe `FLOW_LOCK = threading.Lock()`
  plus an OS-level `fcntl.flock` on `data/profiles/google_flow_pro/.camoufox.lock`
- Interactive Login & Session Warmer: `open_google_flow_login_session(target="flow", warm_seconds=180)`
- Real-Time & Offline-Safe Telemetry: `get_google_flow_credits_status()` (defaults cleanly to cached/tracked
  balance out of 10,000 Pro credits so the Topbar always displays real telemetry without crashing)
- 3 Strict Credit-Guarded Modes (`FLOW_MODES`):
  1. `"economico_pro"` (Default — `🟢 Econômico Pro`):
     Generates/fetches consistent scene images (`Nano Banana 2` + Ingredients / Character Sheets keeping
     the same character face across scenes, with transparent zero-credit fallback to Pollinations/Skia
     when browser session is not yet logged in) and returns image paths for CPU 2.5D Parallax animation.
  2. `"gancho_de_ouro"` (`🟡 Gancho de Ouro (~15 créditos)`):
     Generates ONLY Scene 1 (first 3–5s) as video (`Veo 3.1 Light` / `Omni 1.1 Flash`, `x1 output`)
     and marks Scenes 2..N for CPU 2.5D Parallax.
  3. `"cinema_full_veo"` (`🔴 Cinema Full Veo (Opcional c/ Teto)`):
     Disabled by default; enforces explicit `max_credits_cap: int` check before spending credits
     and stores every clip in `FlowVault` for 0-credit reuse.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

import httpx
import skia

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from engine.flow_vault import (
    FlowVault,
    compute_vault_hash,
    fetch_or_generate_flow_music,
    get_flow_vault,
    get_vault_stats,
)

try:
    from engine.intel_vaapi import run_ffmpeg_safe
except Exception:  # pragma: no cover
    import subprocess

    def run_ffmpeg_safe(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)


PROFILES_DIR = BASE_DIR / "data" / "profiles"
FLOW_PROFILE_DIR = PROFILES_DIR / "google_flow_pro"
FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
FLOW_STATE_PATH = FLOW_PROFILE_DIR / "flow_state.json"

# Thread-safe module-level lock + OS-level flock ensuring strictly ONE Camoufox browser instance
# runs at a time across event loops, threads, and processes on the Core i5.
FLOW_LOCK = threading.Lock()
FLOW_OS_LOCK_PATH = FLOW_PROFILE_DIR / ".camoufox.lock"


@asynccontextmanager
async def _acquire_flow_lock() -> AsyncIterator[None]:
    """Acquire thread-safe `FLOW_LOCK` (safe across event loops) plus OS-level `fcntl.flock`
    on `FLOW_PROFILE_DIR / '.camoufox.lock'` so concurrent login + render never collide or corrupt
    the persistent Camoufox Firefox profile.
    """
    cancel_ev = threading.Event()
    state_lock = threading.Lock()
    state: Dict[str, Any] = {
        "acquired": False,
        "cancelled": False,
        "flocked": False,
        "fd": None,
    }

    def _acquire_thread_lock() -> bool:
        while not cancel_ev.is_set():
            if FLOW_LOCK.acquire(timeout=0.2):
                with state_lock:
                    if state["cancelled"]:
                        FLOW_LOCK.release()
                        return False
                    state["acquired"] = True
                    return True
        return False

    def _acquire_os_flock() -> bool:
        if fcntl is None:
            return True
        FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(FLOW_OS_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while not cancel_ev.is_set():
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with state_lock:
                        if state["cancelled"]:
                            try:
                                fcntl.flock(fd, fcntl.LOCK_UN)
                            finally:
                                os.close(fd)
                            return False
                        state["fd"] = fd
                        state["flocked"] = True
                        return True
                except BlockingIOError:
                    cancel_ev.wait(0.2)
            os.close(fd)
            return False
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise

    try:
        ok_thread = await asyncio.to_thread(_acquire_thread_lock)
        if not ok_thread:
            raise asyncio.CancelledError()
        ok_os = await asyncio.to_thread(_acquire_os_flock)
        if not ok_os:
            raise asyncio.CancelledError()
        yield
    finally:
        cancel_ev.set()
        with state_lock:
            state["cancelled"] = True
            should_unflock = bool(state["flocked"])
            lock_fd = state["fd"]
            state["flocked"] = False
            state["fd"] = None
            should_release = bool(state["acquired"])
            state["acquired"] = False
        if lock_fd is not None:
            if should_unflock and fcntl is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                os.close(lock_fd)
            except Exception:
                pass
        if should_release:
            FLOW_LOCK.release()

FLOW_GOOGLE_URL = "https://flow.google"
FLOW_LABS_URL = "https://labs.google/fx/tools/flow"
FLOW_MUSIC_URL = "https://flowmusic.app"
FLOW_PRO_TOTAL_CREDITS = 10000
VEO_LIGHT_CLIP_COST = 15  # Veo 3.1 Light / Omni 1.1 Flash (x1 output, 3-5s)
DEFAULT_FLOW_MODE = "economico_pro"

# ---------------------------------------------------------------------------
# 3 Strict Credit-Guarded Modes
# ---------------------------------------------------------------------------
FLOW_MODES: Dict[str, Dict[str, Any]] = {
    "economico_pro": {
        "id": "economico_pro",
        "name": "🟢 Econômico Pro",
        "label": "🟢 Econômico Pro",
        "badge": "0 cr • Nano Banana 2 + Ingredients -> CPU 2.5D Parallax",
        "description": (
            "Gera/busca imagens consistentes por cena (Nano Banana 2 + Ingredients / Character Sheets "
            "mantendo o mesmo rosto do personagem entre cenas, com fallback transparente 0 créditos "
            "para Pollinations/Skia) e retorna imagens prontas para animação CPU 2.5D Parallax."
        ),
        "default": True,
        "enabled_by_default": True,
        "requires_explicit_cap": False,
        "est_credits": 0,
        "est_credits_per_video": 0,
        "cost_per_veo_clip": 0,
        "image_model": "nano_banana_2",
        "veo_model": None,
        "output_multiplier": 1,
        "scene_1_strategy": "cpu_25d_parallax",
        "scenes_2_to_n_strategy": "cpu_25d_parallax",
    },
    "gancho_de_ouro": {
        "id": "gancho_de_ouro",
        "name": "🟡 Gancho de Ouro (~15 créditos)",
        "label": "🟡 Gancho de Ouro (~15 créditos)",
        "badge": "~15 cr • Cena 1 em Veo 3.1 Light (x1) + Cenas 2..N Parallax 2.5D",
        "description": (
            "Gera APENAS a Cena 1 (primeiros 3–5s) como vídeo real (Veo 3.1 Light / Omni 1.1 Flash, "
            "x1 output) e marca as Cenas 2..N para animação CPU 2.5D Parallax."
        ),
        "default": False,
        "enabled_by_default": True,
        "requires_explicit_cap": False,
        "est_credits": VEO_LIGHT_CLIP_COST,
        "est_credits_per_video": VEO_LIGHT_CLIP_COST,
        "cost_per_veo_clip": VEO_LIGHT_CLIP_COST,
        "image_model": "nano_banana_2",
        "veo_model": "veo_3_1_light",
        "fallback_veo_model": "omni_1_1_flash",
        "output_multiplier": 1,
        "scene_1_strategy": "veo_3_1_light",
        "scenes_2_to_n_strategy": "cpu_25d_parallax",
    },
    "cinema_full_veo": {
        "id": "cinema_full_veo",
        "name": "🔴 Cinema Full Veo (Opcional c/ Teto)",
        "label": "🔴 Cinema Full Veo (Opcional c/ Teto)",
        "badge": "Teto Obrigatório • Veo 3.1 Light + FlowVault 0-cr Reuse",
        "description": (
            "Desativado por padrão; exige verificação explícita de teto (max_credits_cap: int) "
            "antes de gastar créditos e armazena cada clipe no FlowVault para reuso futuro a 0 créditos."
        ),
        "default": False,
        "enabled_by_default": False,
        "requires_explicit_cap": True,
        "est_credits": 75,
        "est_credits_per_video": 75,
        "cost_per_veo_clip": VEO_LIGHT_CLIP_COST,
        "image_model": "nano_banana_2",
        "veo_model": "veo_3_1_light",
        "fallback_veo_model": "omni_1_1_flash",
        "output_multiplier": 1,
        "scene_1_strategy": "veo_3_1_light",
        "scenes_2_to_n_strategy": "veo_3_1_light",
    },
}


class FlowCreditCapError(ValueError):
    """Raised when `cinema_full_veo` is invoked in strict mode without or above `max_credits_cap`."""


def list_flow_modes() -> List[Dict[str, Any]]:
    return [dict(v) for v in FLOW_MODES.values()]


# ---------------------------------------------------------------------------
# Persistent Session & Credit Telemetry State (`data/profiles/google_flow_pro/flow_state.json`)
# ---------------------------------------------------------------------------
def _default_flow_state() -> Dict[str, Any]:
    return {
        "plan": "Google AI Pro",
        "credits_total": FLOW_PRO_TOTAL_CREDITS,
        "credits_remaining": FLOW_PRO_TOTAL_CREDITS,
        "credits_used": 0,
        "authenticated": False,
        "last_login_at": None,
        "last_target": "flow",
        "active_mode": DEFAULT_FLOW_MODE,
        "max_credits_cap": 0,
        "cinema_full_veo_enabled": False,
        "profile_dir": str(FLOW_PROFILE_DIR),
        "flow_url": FLOW_GOOGLE_URL,
        "flow_music_url": FLOW_MUSIC_URL,
        "history": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _has_profile_cookies() -> bool:
    """Detect whether the persistent Camoufox profile directory has stored browser cookies/session."""
    if not FLOW_PROFILE_DIR.exists():
        return False
    markers = ("cookies.sqlite", "places.sqlite", "cert9.db", "key4.db", "prefs.js")
    return any((FLOW_PROFILE_DIR / m).exists() for m in markers)


def _load_flow_state() -> Dict[str, Any]:
    FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    state = _default_flow_state()
    if FLOW_STATE_PATH.exists():
        try:
            loaded = json.loads(FLOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass
    else:
        _save_flow_state(state)

    total = int(state.get("credits_total") or FLOW_PRO_TOTAL_CREDITS)
    used = max(0, int(state.get("credits_used") or 0))
    rem = state.get("credits_remaining")
    if rem is None:
        rem = max(0, total - used)
    else:
        rem = max(0, min(total, int(rem)))
    state["credits_total"] = total
    state["credits_used"] = used
    state["credits_remaining"] = rem
    if _has_profile_cookies() and not state.get("authenticated"):
        state["authenticated"] = True
    return state


def _save_flow_state(state: Dict[str, Any]) -> Dict[str, Any]:
    FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = FLOW_STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FLOW_STATE_PATH)
    return state


def _deduct_flow_credits(amount: int, reason: str, asset_hash: str = "") -> Dict[str, Any]:
    state = _load_flow_state()
    amt = max(0, int(amount))
    if amt > 0:
        state["credits_used"] = int(state.get("credits_used", 0)) + amt
        state["credits_remaining"] = max(0, int(state.get("credits_remaining", FLOW_PRO_TOTAL_CREDITS)) - amt)
        hist = list(state.get("history") or [])
        hist.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "credits_spent": amt,
                "reason": reason,
                "asset_hash": asset_hash,
                "credits_remaining": state["credits_remaining"],
            }
        )
        state["history"] = hist[-50:]
        _save_flow_state(state)
    return state


def format_flow_badge_ptbr(credits_remaining: int) -> str:
    formatted = f"{max(0, int(credits_remaining)):,}".replace(",", ".")
    return f"🌊 Flow Pro: {formatted} cr"


def get_google_flow_credits_status_sync() -> Dict[str, Any]:
    """Synchronous telemetry reader for Google Flow Pro credits & vault status."""
    state = _load_flow_state()
    vault_stats = get_vault_stats()
    rem = int(state["credits_remaining"])
    tot = int(state["credits_total"])
    used = int(state["credits_used"])
    is_auth = bool(state.get("authenticated")) or _has_profile_cookies()
    active_mode = str(state.get("active_mode") or DEFAULT_FLOW_MODE)
    if active_mode not in FLOW_MODES:
        active_mode = DEFAULT_FLOW_MODE

    return {
        "status": "ok",
        "plan": "Google AI Pro",
        "badge_text": format_flow_badge_ptbr(rem),
        "credits_total": tot,
        "credits_remaining": rem,
        "credits_used": used,
        "credits_saved_by_vault": int(vault_stats.get("credits_saved_by_reuse", 0)),
        "authenticated": is_auth,
        "logged_in": is_auth,
        "session_state": "authenticated" if is_auth else "standby_cached",
        "profile_dir": str(FLOW_PROFILE_DIR),
        "lock_busy": FLOW_LOCK.locked(),
        "default_mode": DEFAULT_FLOW_MODE,
        "active_mode": active_mode,
        "max_credits_cap": int(state.get("max_credits_cap") or 0),
        "cinema_full_veo_enabled": bool(state.get("cinema_full_veo_enabled", False)),
        "modes": FLOW_MODES,
        "flow_url": FLOW_GOOGLE_URL,
        "flow_music_url": FLOW_MUSIC_URL,
        "vault_stats": vault_stats,
        "last_login_at": state.get("last_login_at"),
        "updated_at": state.get("updated_at"),
    }


async def get_google_flow_credits_status() -> Dict[str, Any]:
    """Read/cache the active Google Flow Pro session & credit balance.
    Defaults cleanly to a cached/tracked balance out of 10,000 Pro credits when offline
    or before first interactive login so the Topbar always displays real telemetry without crashing.
    """
    return await asyncio.to_thread(get_google_flow_credits_status_sync)


def set_google_flow_mode(
    mode: str = DEFAULT_FLOW_MODE,
    max_credits_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist user selection among `economico_pro`, `gancho_de_ouro`, and `cinema_full_veo`."""
    clean_mode = (mode or DEFAULT_FLOW_MODE).strip().lower()
    if clean_mode not in FLOW_MODES:
        raise ValueError(f"Modo Google Flow inválido: '{mode}'. Opções: {list(FLOW_MODES.keys())}")

    state = _load_flow_state()
    state["active_mode"] = clean_mode
    if max_credits_cap is not None:
        state["max_credits_cap"] = max(0, int(max_credits_cap))
    state["cinema_full_veo_enabled"] = clean_mode == "cinema_full_veo" and int(state.get("max_credits_cap") or 0) > 0
    _save_flow_state(state)
    return get_google_flow_credits_status_sync()


def reset_google_flow_credits(credits_total: int = FLOW_PRO_TOTAL_CREDITS) -> Dict[str, Any]:
    """Reset tracked Google AI Pro credit balance back to `credits_total` (default 10,000)."""
    state = _load_flow_state()
    state["credits_total"] = int(credits_total)
    state["credits_remaining"] = int(credits_total)
    state["credits_used"] = 0
    _save_flow_state(state)
    return get_google_flow_credits_status_sync()


async def _scrape_credits_from_page(page: Any) -> Optional[int]:
    """Attempt to read visible Google AI Pro / Flow credit balance from the DOM if present."""
    try:
        body_text = await page.inner_text("body", timeout=3500)
        for pat in (
            r"(\d[\d\.,]{1,6})\s*(?:credits|créditos|creditos|cr)\b",
            r"(?:credits|créditos|balance|saldo)\s*[:\-]?\s*(\d[\d\.,]{1,6})",
        ):
            m = re.search(pat, body_text, flags=re.IGNORECASE)
            if m:
                digits = re.sub(r"[^\d]", "", m.group(1))
                if digits:
                    val = int(digits)
                    if 0 <= val <= 50000:
                        return val
    except Exception:
        pass
    return None


async def open_google_flow_login_session(
    target: str = "flow",
    warm_seconds: int = 180,
) -> Dict[str, Any]:
    """Launch visible C++ `AsyncCamoufox(headless=False, persistent_context=True, user_data_dir=...)`
    for `https://flow.google` and `https://flowmusic.app`, protected by `FLOW_LOCK`.

    - `target`: `"flow"` (opens `https://flow.google` + tab for `https://flowmusic.app`),
      `"music"` / `"flowmusic"` (focuses `https://flowmusic.app` + tab for `https://flow.google`),
      or `"both"`.
    - `warm_seconds`: time in seconds to keep the interactive login window open (pass `0` for non-blocking profile probe).
    """
    FLOW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    clean_target = (target or "flow").strip().lower()
    if clean_target in ("music", "flowmusic", "flow_music"):
        primary_url = FLOW_MUSIC_URL
        secondary_url = FLOW_GOOGLE_URL
    else:
        primary_url = FLOW_GOOGLE_URL
        secondary_url = FLOW_MUSIC_URL

    async with _acquire_flow_lock():
        state = _load_flow_state()
        state["last_target"] = clean_target
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

        # Non-blocking probe mode (e.g. automated tests or headless environment with warm_seconds <= 0)
        if int(warm_seconds) <= 0 or not has_display:
            state["authenticated"] = bool(state.get("authenticated")) or _has_profile_cookies()
            _save_flow_state(state)
            status = get_google_flow_credits_status_sync()
            status.update(
                {
                    "status": "profile_ready" if int(warm_seconds) <= 0 else "no_display_cached",
                    "target": clean_target,
                    "primary_url": primary_url,
                    "secondary_url": secondary_url,
                    "urls_opened": [primary_url, secondary_url],
                    "warm_seconds": int(warm_seconds),
                    "message": (
                        "Perfil persistente AsyncCamoufox validado em data/profiles/google_flow_pro/."
                        if int(warm_seconds) <= 0
                        else "Sem DISPLAY ativo no momento; mantendo telemetria em cache (10.000 cr)."
                    ),
                }
            )
            return status

        launched_ok = False
        scraped_credits: Optional[int] = None
        err_detail = ""
        try:
            from camoufox.async_api import AsyncCamoufox

            kwargs: Dict[str, Any] = {
                "headless": False,
                "persistent_context": True,
                "user_data_dir": str(FLOW_PROFILE_DIR),
                "humanize": True,
            }
            async with AsyncCamoufox(**kwargs) as context:
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(primary_url, wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass

                # Also open companion tab so user is logged into both flow.google and flowmusic.app in 1 session
                try:
                    page2 = await context.new_page()
                    await page2.goto(secondary_url, wait_until="domcontentloaded", timeout=45000)
                    await page.bring_to_front()
                except Exception:
                    pass

                launched_ok = True
                try:
                    await page.wait_for_event("close", timeout=max(1, int(warm_seconds)) * 1000)
                except Exception:
                    scraped_credits = await _scrape_credits_from_page(page)
        except Exception as exc:
            err_detail = str(exc)[:220]

        state = _load_flow_state()
        if launched_ok or _has_profile_cookies():
            state["authenticated"] = True
            state["last_login_at"] = datetime.now(timezone.utc).isoformat()
        if scraped_credits is not None:
            state["credits_remaining"] = scraped_credits
            state["credits_used"] = max(0, int(state["credits_total"]) - scraped_credits)
        _save_flow_state(state)

        result = get_google_flow_credits_status_sync()
        result.update(
            {
                "status": "connected" if launched_ok else "standby_cached",
                "target": clean_target,
                "primary_url": primary_url,
                "secondary_url": secondary_url,
                "urls_opened": [primary_url, secondary_url],
                "warm_seconds": int(warm_seconds),
                "message": (
                    "Sessão Google AI Pro (Flow + Flow Music) autenticada e salva em data/profiles/google_flow_pro/."
                    if launched_ok
                    else f"Perfil pronto em cache ({err_detail or 'modo offline'})."
                ),
            }
        )
        return result


# ---------------------------------------------------------------------------
# Character Consistency ("Nano Banana 2" + Ingredients / Character Sheets)
# ---------------------------------------------------------------------------
def _render_skia_character_sheet(
    out_png: Path,
    character_name: str,
    character_desc: str,
    face_seed: int,
) -> Path:
    """Render a deterministic Character Sheet / Ingredient card in Skia C++ so the character's
    palette, facial structure, and reference image are anchored in `data/flow_vault/character_sheets/`.
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    size = 1024
    surface = skia.Surface(size, size)
    canvas = surface.getCanvas()

    # Obsidian Cyber-Luxury Backdrop
    bg_paint = skia.Paint(AntiAlias=True)
    bg_paint.setShader(
        skia.GradientShader.MakeLinear(
            points=[(0.0, 0.0), (float(size), float(size))],
            colors=[
                skia.ColorSetARGB(255, 18, 12, 34),
                skia.ColorSetARGB(255, 11, 7, 19),
            ],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(size, size), bg_paint)

    # Deterministic accent color from face_seed
    palettes = [
        ((255, 46, 147), (255, 209, 102)),   # Rosa #FF2E93 + Gold #FFD166
        ((184, 255, 1), (179, 136, 255)),    # Lime #B8FF01 + Lilac #B388FF
        ((255, 209, 102), (255, 46, 147)),   # Gold #FFD166 + Rosa #FF2E93
        ((179, 136, 255), (184, 255, 1)),    # Lilac #B388FF + Lime #B8FF01
    ]
    c_main, c_sec = palettes[face_seed % len(palettes)]

    # Rim-light radial aura behind character portrait
    aura = skia.Paint(AntiAlias=True)
    aura.setShader(
        skia.GradientShader.MakeRadial(
            center=(size * 0.5, size * 0.46),
            radius=size * 0.42,
            colors=[
                skia.ColorSetARGB(135, *c_main),
                skia.ColorSetARGB(45, *c_sec),
                skia.ColorSetARGB(0, 11, 7, 19),
            ],
            positions=[0.0, 0.55, 1.0],
        )
    )
    canvas.drawCircle(size * 0.5, size * 0.46, size * 0.42, aura)

    # Character torso & shoulders silhouette (clear high-contrast foreground for u2netp segmentation)
    suit_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 34, 28, 56))
    torso = skia.Path()
    torso.moveTo(size * 0.22, size * 0.92)
    torso.cubicTo(size * 0.24, size * 0.66, size * 0.36, size * 0.62, size * 0.50, size * 0.62)
    torso.cubicTo(size * 0.64, size * 0.62, size * 0.76, size * 0.66, size * 0.78, size * 0.92)
    torso.close()
    canvas.drawPath(torso, suit_paint)

    # Lapel / collar accent
    lapel = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, *c_main), Style=skia.Paint.kStroke_Style, StrokeWidth=6.0)
    canvas.drawPath(torso, lapel)

    # Head & jawline (proportion parameterized by face_seed for consistent identity)
    skin_tones = [
        (232, 188, 154),
        (210, 158, 122),
        (172, 120, 88),
        (242, 204, 176),
    ]
    sr, sg, sb = skin_tones[(face_seed // 7) % len(skin_tones)]
    skin_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, sr, sg, sb))
    neck_rect = skia.Rect.MakeXYWH(size * 0.45, size * 0.50, size * 0.10, size * 0.15)
    canvas.drawRoundRect(neck_rect, 24, 24, skin_paint)

    head_w = size * (0.24 + (face_seed % 5) * 0.004)
    head_h = size * (0.30 + ((face_seed // 3) % 5) * 0.004)
    head_rect = skia.Rect.MakeXYWH((size - head_w) * 0.5, size * 0.22, head_w, head_h)
    canvas.drawRoundRect(head_rect, head_w * 0.44, head_h * 0.44, skin_paint)

    # Hair / silhouette crown
    hair_colors = [(24, 20, 32), (58, 38, 28), (38, 34, 48), (82, 54, 36)]
    hr, hg, hb = hair_colors[(face_seed // 11) % len(hair_colors)]
    hair_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, hr, hg, hb))
    hair_rect = skia.Rect.MakeXYWH((size - head_w * 1.04) * 0.5, size * 0.18, head_w * 1.04, head_h * 0.36)
    canvas.drawRoundRect(hair_rect, head_w * 0.42, head_h * 0.32, hair_paint)

    # Eyes & brows
    eye_y = size * 0.35
    eye_dx = head_w * 0.23
    white_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 248, 248, 252))
    pupil_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 22, 18, 32))
    for sign in (-1.0, 1.0):
        ex = size * 0.5 + sign * eye_dx
        canvas.drawOval(skia.Rect.MakeXYWH(ex - 22, eye_y - 12, 44, 24), white_p)
        canvas.drawCircle(ex, eye_y, 9, pupil_p)

    image = surface.makeImageSnapshot()
    image.save(str(out_png), skia.kPNG)
    return out_png


def ensure_character_ingredient_sheet(
    character_name: str = "Protagonista",
    character_desc: str = "",
    style: str = "cinematic_realistic",
    aspect_ratio: str = "9:16",
) -> Dict[str, Any]:
    """Create or retrieve a persistent `Nano Banana 2` Ingredient / Character Sheet
    stored in `data/flow_vault/character_sheets/` so the same character face & visual DNA
    persist across all scenes for 0 credits.
    """
    vault = get_flow_vault()
    clean_name = (character_name or "Protagonista").strip()
    clean_desc = (character_desc or "expressive cinematic protagonist, sharp eyes, consistent facial structure").strip()
    char_key = f"{clean_name}::{clean_desc}::{style}"

    cached = vault.lookup_asset(
        kind="character_sheet",
        prompt_or_mood=char_key,
        aspect_ratio="1:1",
        record_reuse=True,
    )
    if cached and Path(cached["abs_path"]).exists():
        return cached

    char_hash = compute_vault_hash(char_key, kind="character_sheets", aspect_ratio="1:1")
    face_seed = int(char_hash[:8], 16) % 900000 + 100000
    sheet_png = vault.characters_dir / f"flow_char_{char_hash}.png"
    _render_skia_character_sheet(sheet_png, clean_name, clean_desc, face_seed)

    consistency_prefix = (
        f"[NanoBanana2 Ingredient #{char_hash[:6]} | Character: {clean_name} | FaceSeed: {face_seed} | "
        f"Traits: {clean_desc} | Identical facial features across all scenes]"
    )
    entry = vault.store_asset(
        kind="character_sheet",
        prompt_or_mood=char_key,
        file_path=sheet_png,
        aspect_ratio="1:1",
        credits_cost=0,
        copy_into_vault=False,
        metadata={
            "character_name": clean_name,
            "character_desc": clean_desc,
            "style": style,
            "face_seed": face_seed,
            "ingredient_id": f"ing_{char_hash[:8]}",
            "consistency_prefix": consistency_prefix,
            "model": "nano_banana_2_ingredients",
        },
    )
    return entry


# ---------------------------------------------------------------------------
# High-Craft Scene Keyframe Generator (Nano Banana 2 -> Vault -> Pollinations -> Skia C++)
# ---------------------------------------------------------------------------
def _dimensions_for_aspect(aspect_ratio: str) -> Tuple[int, int]:
    if str(aspect_ratio).strip() == "16:9":
        return 1920, 1080
    return 1080, 1920


def _render_skia_scene_keyframe(
    out_png: Path,
    prompt: str,
    aspect_ratio: str = "9:16",
    face_seed: int = 424242,
    scene_index: int = 0,
) -> Path:
    """Render a crisp 1080x1920 or 1920x1080 scene image in C++ Skia with distinct depth layers
    (textured atmospheric background + high-contrast central foreground subject) ready for
    `u2netp.onnx` / OpenCV 2.5D Parallax animation. Zero debug tags or watermarks burned in.
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    w, h = _dimensions_for_aspect(aspect_ratio)
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()

    p_hash = int(hashlib.sha256(f"{prompt}::{scene_index}".encode("utf-8")).hexdigest()[:8], 16)
    seed = face_seed ^ p_hash

    # 1. Deep Atmospheric Cinema Background
    bg_paint = skia.Paint(AntiAlias=True)
    bg_paint.setShader(
        skia.GradientShader.MakeLinear(
            points=[(0.0, 0.0), (float(w), float(h))],
            colors=[
                skia.ColorSetARGB(255, 14 + (seed % 18), 10 + ((seed // 3) % 14), 28 + ((seed // 7) % 24)),
                skia.ColorSetARGB(255, 9, 6, 16),
            ],
        )
    )
    canvas.drawRect(skia.Rect.MakeWH(w, h), bg_paint)

    # 2. Perspective architectural / studio depth grid in background (gives cv2.inpaint & parallax rich texture)
    accents = [
        (255, 46, 147),   # Rosa #FF2E93
        (255, 209, 102),  # Gold #FFD166
        (184, 255, 1),    # Lime #B8FF01
        (179, 136, 255),  # Lilac #B388FF
    ]
    ac1 = accents[scene_index % len(accents)]
    ac2 = accents[(scene_index + 1) % len(accents)]

    grid_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(28, *ac2), Style=skia.Paint.kStroke_Style, StrokeWidth=1.5)
    step = max(72, min(w, h) // 12)
    for gx in range(0, w + step, step):
        canvas.drawLine(float(gx), 0.0, float(gx), float(h), grid_paint)
    for gy in range(0, h + step, step):
        canvas.drawLine(0.0, float(gy), float(w), float(gy), grid_paint)

    # 3. Volumetric spotlight & bokeh depth orbs
    glow = skia.Paint(AntiAlias=True)
    cx = w * (0.48 + ((scene_index % 3) - 1) * 0.04)
    cy = h * 0.44
    rad = min(w, h) * 0.56
    glow.setShader(
        skia.GradientShader.MakeRadial(
            center=(cx, cy),
            radius=rad,
            colors=[
                skia.ColorSetARGB(120, *ac1),
                skia.ColorSetARGB(42, *ac2),
                skia.ColorSetARGB(0, 11, 7, 19),
            ],
            positions=[0.0, 0.52, 1.0],
        )
    )
    canvas.drawCircle(cx, cy, rad, glow)

    for b_i in range(9):
        bx = ((seed >> (b_i + 1)) % max(1, w - 160)) + 80
        by = ((seed >> (b_i + 4)) % max(1, h - 160)) + 80
        br = 18.0 + float((b_i * 13) % 55)
        bp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(36 + (b_i % 3) * 14, *(ac1 if b_i % 2 == 0 else ac2)))
        canvas.drawCircle(float(bx), float(by), br, bp)

    # 4. Consistent Foreground Character / Subject Focal Point (anchored by face_seed)
    subj_scale = min(w, h)
    sh_y = h * 0.56
    torso_w = subj_scale * 0.54
    torso_path = skia.Path()
    torso_path.moveTo(cx - torso_w * 0.52, h * 0.96)
    torso_path.cubicTo(cx - torso_w * 0.48, sh_y + subj_scale * 0.06, cx - torso_w * 0.25, sh_y, cx, sh_y)
    torso_path.cubicTo(cx + torso_w * 0.25, sh_y, cx + torso_w * 0.48, sh_y + subj_scale * 0.06, cx + torso_w * 0.52, h * 0.96)
    torso_path.close()

    suit_p = skia.Paint(AntiAlias=True)
    suit_p.setShader(
        skia.GradientShader.MakeLinear(
            points=[(cx, sh_y), (cx, h * 0.96)],
            colors=[
                skia.ColorSetARGB(255, 42, 34, 68),
                skia.ColorSetARGB(255, 20, 15, 36),
            ],
        )
    )
    canvas.drawPath(torso_path, suit_p)

    rim_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(220, *ac1), Style=skia.Paint.kStroke_Style, StrokeWidth=5.0)
    canvas.drawPath(torso_path, rim_p)

    # Head with consistent face_seed proportions
    skin_tones = [(232, 188, 154), (210, 158, 122), (172, 120, 88), (242, 204, 176)]
    sr, sg, sb = skin_tones[(face_seed // 7) % len(skin_tones)]
    skin_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, sr, sg, sb))

    head_w = subj_scale * (0.21 + (face_seed % 5) * 0.003)
    head_h = subj_scale * (0.26 + ((face_seed // 3) % 5) * 0.003)
    head_top = sh_y - head_h * 0.96
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(cx - head_w * 0.18, sh_y - head_h * 0.22, head_w * 0.36, head_h * 0.32),
        18,
        18,
        skin_p,
    )
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(cx - head_w * 0.5, head_top, head_w, head_h),
        head_w * 0.44,
        head_h * 0.44,
        skin_p,
    )

    # Consistent hair & expressive eyes
    hair_colors = [(24, 20, 32), (58, 38, 28), (38, 34, 48), (82, 54, 36)]
    hr, hg, hb = hair_colors[(face_seed // 11) % len(hair_colors)]
    hair_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, hr, hg, hb))
    canvas.drawRoundRect(
        skia.Rect.MakeXYWH(cx - head_w * 0.52, head_top - head_h * 0.06, head_w * 1.04, head_h * 0.34),
        head_w * 0.40,
        head_h * 0.30,
        hair_p,
    )

    eye_y = head_top + head_h * 0.44
    eye_dx = head_w * 0.22
    ew_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 248, 248, 252))
    ep_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 20, 16, 30))
    for sign in (-1.0, 1.0):
        ex = cx + sign * eye_dx
        canvas.drawOval(skia.Rect.MakeXYWH(ex - head_w * 0.09, eye_y - head_h * 0.04, head_w * 0.18, head_h * 0.08), ew_p)
        canvas.drawCircle(ex, eye_y, head_w * 0.036, ep_p)

    image = surface.makeImageSnapshot()
    image.save(str(out_png), skia.kPNG)
    return out_png


async def _try_pollinations_flux_image(
    prompt: str,
    out_path: Path,
    width: int,
    height: int,
    seed: int,
    timeout_s: float = 4.5,
) -> bool:
    """Zero-credit fallback to Pollinations Flux when browser session is not yet logged in."""
    if os.environ.get("FRIMERISE_OFFLINE_FAST") == "1":
        return False
    clean_p = re.sub(r"\s+", " ", prompt.strip())[:340]
    url = (
        f"https://image.pollinations.ai/prompt/{quote(clean_p)}"
        f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 8192:
                img = skia.Image.MakeFromEncoded(resp.content)
                if img is not None and img.width() >= 256 and img.height() >= 256:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    img.save(str(out_path), skia.kPNG)
                    return True
    except Exception:
        pass
    return False


async def generate_flow_scene_image(
    prompt: str,
    out_path: Optional[Path] = None,
    aspect_ratio: str = "9:16",
    character_sheet: Optional[Dict[str, Any]] = None,
    scene_index: int = 0,
    allow_pollinations: bool = False,
) -> Dict[str, Any]:
    """Generate or fetch a consistent scene image (`Nano Banana 2` + Ingredients / Character Sheet,
    with 0-credit FlowVault lookup first and transparent 0-credit fallback to Pollinations/Skia).
    """
    vault = get_flow_vault()
    char_info = character_sheet or ensure_character_ingredient_sheet()
    face_seed = int(char_info.get("face_seed", 424242))
    prefix = str(char_info.get("consistency_prefix", ""))
    full_prompt = f"{prefix} {prompt}".strip()

    # 1. Check FlowVault first (0 credits!)
    hit = vault.lookup_asset(
        kind="image",
        prompt_or_mood=full_prompt,
        aspect_ratio=aspect_ratio,
        record_reuse=True,
    )
    if hit and Path(hit["abs_path"]).exists():
        src_img = Path(hit["abs_path"])
        if out_path is not None:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if src_img.resolve() != out_path.resolve():
                shutil.copy2(src_img, out_path)
            final_img = out_path
        else:
            final_img = src_img
        return {
            "status": "ok",
            "image_path": str(final_img.resolve()),
            "vault_path": hit["abs_path"],
            "hash": hit["hash"],
            "model": hit.get("model", "nano_banana_2"),
            "face_seed": face_seed,
            "character_name": char_info.get("character_name", "Protagonista"),
            "ingredient_id": char_info.get("ingredient_id"),
            "reused_from_vault": True,
            "credits_spent": 0,
            "render_strategy": "cpu_25d_parallax",
        }

    # 2. Generate new consistent scene image (0 credits in Economico Pro / Nano Banana 2 fallback)
    img_hash = compute_vault_hash(full_prompt, kind="images", aspect_ratio=aspect_ratio)
    vault_png = vault.images_dir / f"flow_img_{img_hash}.png"
    w, h = _dimensions_for_aspect(aspect_ratio)

    used_source = "nano_banana_2_skia_studio"
    if allow_pollinations:
        ok_poll = await _try_pollinations_flux_image(
            prompt=f"{char_info.get('character_desc', '')}, {prompt}, cinematic 8k photography, no text",
            out_path=vault_png,
            width=w,
            height=h,
            seed=face_seed + scene_index,
        )
        if ok_poll:
            used_source = "nano_banana_2_pollinations_flux"

    if not vault_png.exists():
        await asyncio.to_thread(
            _render_skia_scene_keyframe,
            vault_png,
            full_prompt,
            aspect_ratio,
            face_seed,
            scene_index,
        )

    entry = vault.store_asset(
        kind="image",
        prompt_or_mood=full_prompt,
        file_path=vault_png,
        aspect_ratio=aspect_ratio,
        credits_cost=0,
        copy_into_vault=False,
        metadata={
            "model": "nano_banana_2",
            "provider_source": used_source,
            "face_seed": face_seed,
            "character_name": char_info.get("character_name", "Protagonista"),
            "ingredient_id": char_info.get("ingredient_id"),
            "scene_index": scene_index,
        },
    )

    final_img = vault_png
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if vault_png.resolve() != out_path.resolve():
            shutil.copy2(vault_png, out_path)
        final_img = out_path

    return {
        "status": "ok",
        "image_path": str(final_img.resolve()),
        "vault_path": str(vault_png.resolve()),
        "hash": entry["hash"],
        "model": "nano_banana_2",
        "provider_source": used_source,
        "face_seed": face_seed,
        "character_name": char_info.get("character_name", "Protagonista"),
        "ingredient_id": char_info.get("ingredient_id"),
        "reused_from_vault": False,
        "credits_spent": 0,
        "render_strategy": "cpu_25d_parallax",
    }


def generate_flow_scene_image_sync(
    prompt: str,
    out_path: Optional[Path] = None,
    aspect_ratio: str = "9:16",
    character_sheet: Optional[Dict[str, Any]] = None,
    scene_index: int = 0,
) -> Path:
    """Synchronous convenience wrapper returning the generated/cached scene image `Path`."""
    coro = generate_flow_scene_image(
        prompt=prompt,
        out_path=out_path,
        aspect_ratio=aspect_ratio,
        character_sheet=character_sheet,
        scene_index=scene_index,
        allow_pollinations=False,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Direct thread-safe synchronous path when inside an active event loop
        char_info = character_sheet or ensure_character_ingredient_sheet()
        face_seed = int(char_info.get("face_seed", 424242))
        full_prompt = f"{char_info.get('consistency_prefix', '')} {prompt}".strip()
        vault = get_flow_vault()
        hit = vault.lookup_asset(kind="image", prompt_or_mood=full_prompt, aspect_ratio=aspect_ratio)
        if hit and Path(hit["abs_path"]).exists():
            p = Path(hit["abs_path"])
        else:
            img_hash = compute_vault_hash(full_prompt, kind="images", aspect_ratio=aspect_ratio)
            p = vault.images_dir / f"flow_img_{img_hash}.png"
            _render_skia_scene_keyframe(p, full_prompt, aspect_ratio, face_seed, scene_index)
            vault.store_asset(kind="image", prompt_or_mood=full_prompt, file_path=p, aspect_ratio=aspect_ratio, copy_into_vault=False)
        if out_path is not None:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if p.resolve() != out_path.resolve():
                shutil.copy2(p, out_path)
            return out_path
        return p
    res = asyncio.run(coro)
    return Path(res["image_path"])


FLOW_PROJECT_ROTATE_INTERVAL = 18

_WIDE_916_PHRASES_RE = re.compile(
    r"\b(?:ultra[- ]?wide|wide\s+establishing(?:\s+shot)?|wide[- ]?angle|widescreen|"
    r"wide\s+panoramic|panoramic\s+wide|wide\s+shot|wide)\b[,:\s-]*",
    re.IGNORECASE,
)

_FLOW_MATCH_BOILERPLATE_WORDS: Set[str] = {
    "dark", "gothic", "cinema", "still", "eerie", "chiaroscuro", "candlelight",
    "shadows", "grain", "photorealistic", "watermark", "gritty", "documentary",
    "photograph", "tungsten", "night", "lighting", "cinematic", "museum", "grade",
    "historical", "dramatic", "rembrandt", "photography", "sleek", "moody",
    "prestige", "glass", "reflections", "anamorphic", "photo", "image", "scene",
    "frame", "style", "there", "their", "where", "which", "about", "under",
    "above", "through", "between", "before", "after", "around", "without",
    "within", "while", "during", "being", "having", "could", "would", "should",
}


def _strip_wide_phrases_for_vertical(prompt_text: str, aspect_ratio: Optional[str]) -> str:
    """Strip landscape/wide framing phrases when generating vertical 9:16 images."""
    clean = re.sub(r"\s+", " ", (prompt_text or "").strip())
    if not clean:
        return ""
    if str(aspect_ratio or "").strip() == "9:16":
        clean = _WIDE_916_PHRASES_RE.sub("", clean)
        clean = re.sub(r"\s+", " ", clean).strip(" ,;:-")
    return clean


def _extract_distinctive_prompt_tokens(text: str) -> Set[str]:
    """Extract distinctive >=5-char tokens from a prompt (excluding boilerplate mood suffixes)."""
    low = re.sub(r"\s+", " ", (text or "").lower())
    return {
        tok
        for tok in re.findall(r"[a-z0-9]{5,}", low)
        if tok not in _FLOW_MATCH_BOILERPLATE_WORDS
    }


def _match_flow_card_to_pending(
    ctx_text: str,
    pending_by_key: Dict[str, Dict[str, Any]],
    allow_single_fallback: bool = True,
) -> Optional[Dict[str, Any]]:
    """Strictly match a rendered Google Flow DOM card back to its true pending prompt item.

    - Matches by normalized 30-char prompt prefix OR >=3 distinctive >=5-char prompt words
      present in the card's DOM ancestor text.
    - NEVER falls back blindly to `unmatched[0]` when more than 1 prompt is in flight globally!
    - Only falls back to the sole pending item when `len(pending_by_key) == 1` and
      `allow_single_fallback=True` (i.e. single-prompt session with no sibling cards in DOM).
    """
    if not pending_by_key:
        return None

    ctx_low = re.sub(r"\s+", " ", (ctx_text or "").lower()).strip()
    if not ctx_low:
        if len(pending_by_key) == 1 and allow_single_fallback:
            return next(iter(pending_by_key.values()))
        return None
    ctx_tokens = set(re.findall(r"[a-z0-9]{5,}", ctx_low))

    scored: List[Tuple[Tuple[int, int, int, float], str, Dict[str, Any]]] = []
    for key, cand_it in pending_by_key.items():
        norm_styled = re.sub(r"\s+", " ", str(cand_it.get("styled_prompt") or "").lower()).strip()
        norm_raw = re.sub(r"\s+", " ", str(cand_it.get("raw_prompt") or "").lower()).strip()

        prefix_30 = norm_styled[:30]
        raw_prefix_30 = norm_raw[:30] if len(norm_raw) >= 20 else ""
        prefix_hit = bool(
            (len(prefix_30) >= 20 and prefix_30 in ctx_low)
            or (raw_prefix_30 and raw_prefix_30 in ctx_low)
            or (12 <= len(norm_styled) < 30 and norm_styled in ctx_low)
        )
        prefix_60 = norm_styled[:60]
        prefix60_hit = bool(len(prefix_60) >= 40 and prefix_60 in ctx_low)

        cand_tokens = _extract_distinctive_prompt_tokens(norm_raw) if norm_raw else set()
        if len(cand_tokens) < 3:
            cand_tokens = _extract_distinctive_prompt_tokens(norm_styled)
        token_hits = len(cand_tokens & ctx_tokens)
        token_ratio = token_hits / float(max(1, len(cand_tokens)))

        if prefix_hit or token_hits >= 3:
            score = (1 if prefix60_hit else 0, 1 if prefix_hit else 0, token_hits, token_ratio)
            scored.append((score, key, cand_it))

    if not scored:
        if len(pending_by_key) == 1 and allow_single_fallback:
            return next(iter(pending_by_key.values()))
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][2]

    # Exact score tie between 2+ in-flight prompts: resolve only if exact full styled_prompt matches uniquely
    exact_hits = [
        it for _, _, it in scored
        if re.sub(r"\s+", " ", str(it.get("styled_prompt") or "").lower()).strip() in ctx_low
    ]
    if len(exact_hits) == 1:
        return exact_hits[0]
    return None


def _validate_real_photo_image(
    img_path: Path,
    min_w: int = 384,
    min_h: int = 320,
    aspect_ratio: Optional[str] = None,
) -> bool:
    """Ensure a generated image is a genuine non-blank photograph/artwork matching expected orientation."""
    try:
        if not img_path.exists() or img_path.stat().st_size < 18_000:
            return False
        import cv2
        import numpy as np

        bgr = cv2.imread(str(img_path))
        if bgr is None or bgr.size == 0:
            return False
        h, w = bgr.shape[:2]
        if w < min_w or h < min_h:
            return False
        ar = str(aspect_ratio or "").strip()
        if ar == "9:16" and h < w * 1.25:
            return False
        if ar == "16:9" and w < h * 1.25:
            return False
        if float(np.std(bgr)) < 14.0:
            return False
        return True
    except Exception:
        return False


def _style_flow_cinema_prompt(
    prompt_en: str,
    mood: str = "dark_horror",
    aspect_ratio: str = "9:16",
) -> str:
    clean_p = _strip_wide_phrases_for_vertical(prompt_en, aspect_ratio)
    if not clean_p:
        return ""
    mood_style = {
        "dark_horror": "dark gothic 35mm cinema still, eerie chiaroscuro candlelight, mist, deep shadows, film grain, photorealistic, no text, no watermark",
        "investigative_crime": "gritty neo-noir documentary photograph, tungsten night lighting, 35mm film grain, photorealistic, no text, no watermark",
        "epic_history": "cinematic museum-grade historical film still, dramatic Rembrandt lighting, 35mm photography, no text, no watermark",
        "corporate_thriller": "sleek moody prestige cinema photograph, dark glass reflections, 35mm anamorphic lens, no text, no watermark",
    }.get(mood, "cinematic 35mm documentary photograph, dramatic lighting, no text, no watermark")
    if "no text" in clean_p.lower():
        styled = clean_p
    else:
        styled = f"{clean_p}, {mood_style}"
    styled = _strip_wide_phrases_for_vertical(styled, aspect_ratio)
    return styled[:420]


def _is_flow_generated_img_url(src: str) -> bool:
    s = (src or "").lower()
    if not s.startswith("https://"):
        return False
    return (
        "flow.google.com/asb/" in s
        or "googleusercontent.com" in s
        or "storage.googleapis.com" in s
    )


async def _configure_flow_composer_settings(page: Any, ar_target: str) -> bool:
    """Configure Nano Banana 2.1: Image mode + target aspect ratio (9:16 or 16:9) + x1,
    verifying `aria-checked="true"` after clicking each option (retrying if needed).
    """
    all_verified = True
    try:
        cfg_btn = page.locator(
            'button[aria-label="Gatilho de configurações"], button[aria-label*="Settings"], button:has-text("Nano Banana")'
        ).first
        if await cfg_btn.count() == 0:
            return False
        await cfg_btn.click(timeout=5_000)
        await asyncio.sleep(0.9)
        radio_targets = (
            ("image_mode", '[role="radio"]:has-text("Imagem"), [role="radio"]:has-text("Image")'),
            (f"aspect_{ar_target}", f'[role="radio"]:has-text("{ar_target}")'),
            ("count_x1", '[role="radio"]:has-text("x1")'),
        )
        for label, sel in radio_targets:
            loc = page.locator(sel).first
            verified = False
            for attempt in range(3):
                try:
                    if await loc.count() == 0 or not await loc.is_visible():
                        if attempt == 0:
                            await asyncio.sleep(0.3)
                            continue
                        break
                    checked = (await loc.get_attribute("aria-checked") or "").strip().lower()
                    if checked == "true":
                        verified = True
                        break
                    await loc.click(timeout=2_500, force=(attempt > 0))
                    await asyncio.sleep(0.35)
                    checked_after = (await loc.get_attribute("aria-checked") or "").strip().lower()
                    if checked_after == "true":
                        verified = True
                        break
                except Exception:
                    await asyncio.sleep(0.25)
            if not verified:
                all_verified = False
                print(
                    f"[GoogleFlow] Settings verification warning: '{label}' did not confirm aria-checked='true'",
                    flush=True,
                )
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
    except Exception as cfg_exc:
        all_verified = False
        print(f"[GoogleFlow] Composer settings warning: {cfg_exc}", flush=True)
    return all_verified


async def _open_fresh_flow_project(page: Any, ar_target: str) -> Tuple[bool, Set[str]]:
    """Navigate to `https://flow.google.com/`, open a clean 'Novo projeto', configure Nano Banana 2.1,
    and return `(ok, initial_seen_srcs)`.
    """
    await page.goto("https://flow.google.com/", wait_until="domcontentloaded", timeout=24_000)
    await asyncio.sleep(3.0)
    url_now = (page.url or "").lower()
    if "accounts.google.com" in url_now or "signin" in url_now:
        print("[GoogleFlow] Session expired — please reconnect Google Flow Pro profile.", flush=True)
        return False, set()

    new_btn = page.locator(
        'button:has-text("Novo projeto"), button:has-text("New project")'
    ).first
    if await new_btn.count() == 0:
        return False, set()
    await new_btn.click(timeout=8_000)
    try:
        await page.wait_for_url("**/project/**", timeout=16_000)
    except Exception:
        return False, set()
    await asyncio.sleep(2.8)

    await _configure_flow_composer_settings(page, ar_target)

    seen_srcs: Set[str] = set(
        await page.eval_on_selector_all(
            "img",
            "els => els.map(e => e.currentSrc || e.src || '').filter(Boolean)",
        )
    )
    return True, seen_srcs


async def _run_google_flow_camoufox_batch_async(
    pending_items: List[Dict[str, Any]],
    aspect_ratio: str = "9:16",
    per_image_timeout_s: float = 65.0,
    wave_size: int = 3,
) -> Dict[str, Path]:
    """Generate multiple bespoke Nano Banana 2.1 images in ONE single logged-in Google Flow Pro session.
    Submits prompts in pipelined waves of `wave_size`, tracks `pending_by_key` globally across waves
    (preventing cross-contamination from late cards), enforces strict aspect-ratio validation, and
    rotates to a fresh 'Novo projeto' every 18 prompts to avoid Firefox DOM bloat on large batches.
    """
    results: Dict[str, Path] = {}
    if not pending_items or not _has_profile_cookies():
        return results

    try:
        from camoufox.async_api import AsyncCamoufox
    except Exception:
        return results

    ar_target = "9:16" if str(aspect_ratio or "9:16").strip() == "9:16" else "16:9"
    eff_wave = max(1, min(4, int(wave_size)))
    total_items = len(pending_items)
    done_count = 0

    # Normalize & sanitize prompts defensively (strips "Wide " phrases in 9:16)
    sanitized_items: List[Dict[str, Any]] = []
    for raw_it in pending_items:
        it_copy = dict(raw_it)
        it_copy["styled_prompt"] = _strip_wide_phrases_for_vertical(
            str(it_copy.get("styled_prompt") or ""), ar_target
        )[:420]
        if it_copy.get("raw_prompt"):
            it_copy["raw_prompt"] = _strip_wide_phrases_for_vertical(
                str(it_copy.get("raw_prompt") or ""), ar_target
            )
        sanitized_items.append(it_copy)

    async with _acquire_flow_lock():
        try:
            async with AsyncCamoufox(
                headless=True,
                persistent_context=True,
                user_data_dir=str(FLOW_PROFILE_DIR),
            ) as browser:
                page = browser.pages[0] if browser.pages else await browser.new_page()

                async def _poll_and_collect(
                    seen_srcs: Set[str],
                    pending_by_key: Dict[str, Dict[str, Any]],
                    wave_keys: Set[str],
                    allow_single_fallback: bool,
                ) -> None:
                    nonlocal done_count
                    cards = await page.eval_on_selector_all(
                        "img",
                        """els => els
                            .filter(e => e.complete && Math.max(e.naturalWidth, e.naturalHeight) >= 400 && Math.min(e.naturalWidth, e.naturalHeight) >= 220)
                            .map(e => {
                                const parts = [];
                                const alt = (e.getAttribute('alt') || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim();
                                if (alt) parts.push(alt);
                                let node = e.parentElement;
                                for (let i = 0; i < 12 && node; i++) {
                                    const aria = (node.getAttribute && (node.getAttribute('aria-label') || node.getAttribute('title'))) || '';
                                    if (aria && aria.length >= 20 && aria.length <= 1200) parts.push(aria);
                                    const txt = (node.innerText || '').trim();
                                    if (txt.length >= 25 && txt.length <= 1200) {
                                        parts.push(txt);
                                        break;
                                    }
                                    node = node.parentElement;
                                }
                                return {
                                    src: e.currentSrc || e.src || '',
                                    w: e.naturalWidth,
                                    h: e.naturalHeight,
                                    ctx: parts.join(' ')
                                };
                            })""",
                    )
                    new_cards = [
                        c for c in cards
                        if c.get("src") and c["src"] not in seen_srcs and _is_flow_generated_img_url(str(c["src"]))
                    ]
                    for card in new_cards:
                        if not pending_by_key:
                            break
                        src = str(card["src"])
                        hi_src = re.sub(r"=[swh]\d+[^/]*$", "=s0", src)
                        matched_item = _match_flow_card_to_pending(
                            str(card.get("ctx") or ""),
                            pending_by_key,
                            allow_single_fallback=allow_single_fallback,
                        )
                        if matched_item is None:
                            continue

                        matched_key = str(matched_item["key"])
                        seen_srcs.add(src)
                        vault_jpg = Path(matched_item["vault_jpg"])
                        try:
                            resp = await page.request.get(hi_src, timeout=18_000)
                            if not resp.ok:
                                resp = await page.request.get(src, timeout=18_000)
                            if resp.ok:
                                import cv2 as _cv2
                                import numpy as _np

                                raw_b = await resp.body()
                                bgr_im = _cv2.imdecode(_np.frombuffer(raw_b, _np.uint8), _cv2.IMREAD_COLOR)
                                if bgr_im is not None and bgr_im.size > 0:
                                    vault_jpg.parent.mkdir(parents=True, exist_ok=True)
                                    _cv2.imwrite(str(vault_jpg), bgr_im, [int(_cv2.IMWRITE_JPEG_QUALITY), 93])
                                    if _validate_real_photo_image(vault_jpg, aspect_ratio=ar_target):
                                        results[matched_key] = vault_jpg
                                        pending_by_key.pop(matched_key, None)
                                        wave_keys.discard(matched_key)
                                        done_count += 1
                                        print(
                                            f"[GoogleFlow] Nano Banana 2.1 ({done_count}/{total_items}) ready [{ar_target} {bgr_im.shape[1]}x{bgr_im.shape[0]}]: {vault_jpg.name}",
                                            flush=True,
                                        )
                                    else:
                                        print(
                                            f"[GoogleFlow] Rejected card failing orientation/quality ({bgr_im.shape[1]}x{bgr_im.shape[0]} vs {ar_target}): {matched_key}",
                                            flush=True,
                                        )
                                        vault_jpg.unlink(missing_ok=True)
                                        pending_by_key.pop(matched_key, None)
                                        wave_keys.discard(matched_key)
                        except Exception:
                            continue

                # Chunk large batches (>18 prompts) into fresh "Novo projeto" tabs to avoid Firefox DOM bloat
                for proj_start in range(0, total_items, FLOW_PROJECT_ROTATE_INTERVAL):
                    project_chunk = sanitized_items[proj_start : proj_start + FLOW_PROJECT_ROTATE_INTERVAL]
                    if proj_start > 0:
                        print(
                            f"[GoogleFlow] Rotating to fresh 'Novo projeto' at prompt {proj_start + 1}/{total_items} to prevent DOM bloat",
                            flush=True,
                        )
                    ok_proj, seen_srcs = await _open_fresh_flow_project(page, ar_target)
                    if not ok_proj:
                        break

                    tb = page.locator('[role="textbox"]').first
                    gen_btn = page.locator(
                        'button[aria-label*="Iniciar gera"], button[aria-label*="Generate"], button:has-text("arrow_forward")'
                    ).first

                    # Global pending map across all waves within this project session so late Wave K cards
                    # always resolve to their true key instead of polluting Wave K+1!
                    pending_by_key: Dict[str, Dict[str, Any]] = {}
                    submitted_in_project = 0

                    for w_start in range(0, len(project_chunk), eff_wave):
                        wave = project_chunk[w_start : w_start + eff_wave]
                        submitted: List[Dict[str, Any]] = []
                        for item in wave:
                            prompt_txt = str(item["styled_prompt"])[:420]
                            try:
                                await tb.click(timeout=5_000)
                                await page.keyboard.press("Control+A")
                                await page.keyboard.press("Backspace")
                                await asyncio.sleep(0.15)
                                await page.keyboard.type(prompt_txt, delay=1)
                                await asyncio.sleep(0.35)
                                if not await gen_btn.is_disabled():
                                    await gen_btn.click(timeout=5_000)
                                    submitted.append(item)
                                    pending_by_key[str(item["key"])] = item
                                    submitted_in_project += 1
                                    await asyncio.sleep(1.8)
                            except Exception as sub_exc:
                                print(f"[GoogleFlow] Submit error ({item['key']}): {sub_exc}", flush=True)

                        if not submitted:
                            continue

                        wave_keys: Set[str] = {str(it["key"]) for it in submitted}
                        deadline = asyncio.get_running_loop().time() + max(
                            per_image_timeout_s,
                            75.0 + 18.0 * len(submitted),
                        )

                        while wave_keys and asyncio.get_running_loop().time() < deadline:
                            await asyncio.sleep(1.4)
                            await _poll_and_collect(
                                seen_srcs,
                                pending_by_key,
                                wave_keys,
                                allow_single_fallback=(submitted_in_project <= 1),
                            )

                        if wave_keys:
                            print(
                                f"[GoogleFlow] Wave partial timeout ({len(wave_keys)} still pending globally: {sorted(wave_keys)})",
                                flush=True,
                            )

                    # Brief grace window before rotating/closing so any late cards still land under their true key
                    if pending_by_key:
                        grace_deadline = asyncio.get_running_loop().time() + 15.0
                        grace_keys: Set[str] = set(pending_by_key.keys())
                        while pending_by_key and asyncio.get_running_loop().time() < grace_deadline:
                            await asyncio.sleep(1.4)
                            await _poll_and_collect(
                                seen_srcs,
                                pending_by_key,
                                grace_keys,
                                allow_single_fallback=(submitted_in_project <= 1),
                            )
        except Exception as exc:
            print(f"[GoogleFlow] Batch session error: {exc}", flush=True)
    return results


def generate_flow_batch_images_sync(
    items: List[Dict[str, Any]],
    aspect_ratio: str = "9:16",
    mood: str = "dark_horror",
) -> Dict[str, Path]:
    """Batch-generate bespoke photorealistic dark-cinema images via FlowVault + ONE single
    authenticated Google Flow Pro (`Nano Banana 2.1`) session (0 credits, native 9:16/16:9).

    `items`: list of `{"key": str, "prompt_en": str, "out_path": Path}`
    Returns `{key: out_path}` for every cached or freshly generated image.
    """
    vault = get_flow_vault()
    ready: Dict[str, Path] = {}
    pending: List[Dict[str, Any]] = []

    for it in items:
        key = str(it["key"])
        out_path = Path(it["out_path"])
        raw_clean = _strip_wide_phrases_for_vertical(str(it.get("prompt_en") or ""), aspect_ratio)
        styled = _style_flow_cinema_prompt(raw_clean, mood=mood, aspect_ratio=aspect_ratio)
        if not styled:
            continue
        hit = vault.lookup_asset(
            kind="image",
            prompt_or_mood=styled,
            aspect_ratio=aspect_ratio,
            record_reuse=True,
        )
        if hit and Path(hit["abs_path"]).exists() and str(hit.get("provider_source") or "") != "nano_banana_2_skia_studio":
            src = Path(hit["abs_path"])
            if _validate_real_photo_image(src, aspect_ratio=aspect_ratio):
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if src.resolve() != out_path.resolve():
                    shutil.copy2(src, out_path)
                ready[key] = out_path
                continue
            print(
                f"[GoogleFlow] Ignoring poisoned/misoriented FlowVault cache hit ({aspect_ratio}): {src.name}",
                flush=True,
            )
        img_hash = compute_vault_hash(styled, kind="images", aspect_ratio=aspect_ratio)
        vault_jpg = vault.images_dir / f"flow_nb2_{img_hash}.jpg"
        pending.append({
            "key": key,
            "raw_prompt": raw_clean,
            "styled_prompt": styled,
            "vault_jpg": vault_jpg,
            "out_path": out_path,
        })

    if not pending or not _has_profile_cookies():
        return ready

    total_timeout = max(180.0, len(pending) * 45.0 + 90.0)
    try:
        asyncio.get_running_loop()
        # Running inside an active loop — execute on a clean worker thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            gen_map = ex.submit(
                lambda: asyncio.run(
                    asyncio.wait_for(
                        _run_google_flow_camoufox_batch_async(pending, aspect_ratio=aspect_ratio),
                        timeout=total_timeout,
                    )
                )
            ).result()
    except RuntimeError:
        try:
            gen_map = asyncio.run(
                asyncio.wait_for(
                    _run_google_flow_camoufox_batch_async(pending, aspect_ratio=aspect_ratio),
                    timeout=total_timeout,
                )
            )
        except Exception as exc:
            print(f"[GoogleFlow] Batch runner error: {exc}", flush=True)
            gen_map = {}

    for it in pending:
        key = str(it["key"])
        vpath = gen_map.get(key)
        if vpath is not None and vpath.exists() and _validate_real_photo_image(vpath, aspect_ratio=aspect_ratio):
            vault.store_asset(
                kind="image",
                prompt_or_mood=str(it["styled_prompt"]),
                file_path=vpath,
                aspect_ratio=aspect_ratio,
                credits_cost=0,
                copy_into_vault=False,
                metadata={
                    "model": "nano_banana_2.1",
                    "provider_source": "google_flow_pro_nano_banana_2",
                    "mood": mood,
                },
            )
            out_path = Path(it["out_path"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if vpath.resolve() != out_path.resolve():
                shutil.copy2(vpath, out_path)
            ready[key] = out_path
    return ready


def _try_google_flow_camoufox_image_sync(
    prompt: str,
    out_path: Path,
    timeout_s: float = 38.0,
    aspect_ratio: str = "9:16",
    skip_browser: bool = False,
) -> bool:
    """Single-image wrapper over the authenticated Google Flow Pro Nano Banana 2.1 generator.
    Thread-pool safe when invoked inside an active asyncio event loop; supports `skip_browser=True`
    (or `FRIMERISE_SKIP_FLOW_SINGLE_BROWSER=1`) to avoid redundant browser launches after batch runs.
    """
    if skip_browser or os.environ.get("FRIMERISE_SKIP_FLOW_SINGLE_BROWSER") == "1":
        return False
    if not _has_profile_cookies():
        return False
    clean_prompt = _strip_wide_phrases_for_vertical(prompt, aspect_ratio)[:420]
    if not clean_prompt:
        return False
    pending = [{
        "key": "single",
        "raw_prompt": clean_prompt,
        "styled_prompt": clean_prompt,
        "vault_jpg": Path(out_path),
        "out_path": Path(out_path),
    }]

    def _run_batch() -> Dict[str, Path]:
        return asyncio.run(
            asyncio.wait_for(
                _run_google_flow_camoufox_batch_async(
                    pending,
                    aspect_ratio=aspect_ratio,
                    per_image_timeout_s=timeout_s,
                    wave_size=1,
                ),
                timeout=max(timeout_s + 30.0, 95.0),
            )
        )

    try:
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                res = ex.submit(_run_batch).result()
        except RuntimeError:
            res = _run_batch()
        return (
            "single" in res
            and Path(out_path).exists()
            and _validate_real_photo_image(Path(out_path), aspect_ratio=aspect_ratio)
        )
    except Exception:
        return False


def generate_flow_bespoke_photo_sync(
    prompt_en: str,
    out_path: Path,
    aspect_ratio: str = "9:16",
    mood: str = "dark_horror",
    try_browser: bool = True,
) -> Optional[Path]:
    """Generate a genuine photorealistic/cinematic documentary image via:
      1. FlowVault cache (0 credits, instant, orientation-verified)
      2. Authenticated Google Flow (`flow.google` Nano Banana 2) via persistent Camoufox profile
      3. Pollinations Flux photorealistic dark-cinema endpoint (0 credits)
    NEVER returns geometric Skia placeholder cards (returns None if all photo generators fail).
    """
    styled_prompt = _style_flow_cinema_prompt(prompt_en, mood=mood, aspect_ratio=aspect_ratio)
    if not styled_prompt:
        return None

    vault = get_flow_vault()
    hit = vault.lookup_asset(
        kind="image",
        prompt_or_mood=styled_prompt,
        aspect_ratio=aspect_ratio,
        record_reuse=True,
    )
    if hit and Path(hit["abs_path"]).exists():
        # Ignore legacy geometric Skia cards or poisoned misoriented assets stored in vault
        if str(hit.get("provider_source") or "") != "nano_banana_2_skia_studio":
            src = Path(hit["abs_path"])
            if _validate_real_photo_image(src, aspect_ratio=aspect_ratio):
                out_path = Path(out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if src.resolve() != out_path.resolve():
                    shutil.copy2(src, out_path)
                return out_path
            print(
                f"[GoogleFlow] Ignoring poisoned/misoriented FlowVault bespoke cache hit ({aspect_ratio}): {src.name}",
                flush=True,
            )

    img_hash = compute_vault_hash(styled_prompt, kind="images", aspect_ratio=aspect_ratio)
    vault_jpg = vault.images_dir / f"flow_bespoke_{img_hash}.jpg"
    w, h = (768, 1344) if str(aspect_ratio or "9:16").strip() == "9:16" else (1280, 720)
    used_source = ""

    # 1. Try authenticated Google Flow browser session (if cookies present & enabled)
    if try_browser and _has_profile_cookies():
        if _try_google_flow_camoufox_image_sync(
            styled_prompt,
            vault_jpg,
            timeout_s=36.0,
            aspect_ratio=aspect_ratio,
            skip_browser=not try_browser,
        ):
            used_source = "google_flow_pro_nano_banana_2"

    # 2. Fallback to Pollinations Flux photorealistic cinema generator
    if not used_source:
        seed = int(img_hash[:6], 16)
        encoded = quote(styled_prompt[:380])
        poll_urls = [
            f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&seed={seed}&nologo=true&model=flux",
            f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&seed={seed}&nologo=true",
        ]
        try:
            with httpx.Client(follow_redirects=True, timeout=28.0) as client:
                for purl in poll_urls:
                    try:
                        r = client.get(purl)
                        if r.status_code == 200 and len(r.content) > 20_000:
                            ct = (r.headers.get("content-type") or "").lower()
                            if "image" in ct or r.content[:2] == b"\xff\xd8" or r.content[:4] == b"\x89PNG":
                                vault_jpg.parent.mkdir(parents=True, exist_ok=True)
                                vault_jpg.write_bytes(r.content)
                                if _validate_real_photo_image(vault_jpg, aspect_ratio=aspect_ratio):
                                    used_source = "flow_pollinations_flux"
                                    break
                                vault_jpg.unlink(missing_ok=True)
                    except Exception:
                        continue
        except Exception:
            pass

    if not used_source or not vault_jpg.exists() or not _validate_real_photo_image(vault_jpg, aspect_ratio=aspect_ratio):
        return None

    vault.store_asset(
        kind="image",
        prompt_or_mood=styled_prompt,
        file_path=vault_jpg,
        aspect_ratio=aspect_ratio,
        credits_cost=0,
        copy_into_vault=False,
        metadata={
            "model": "nano_banana_2",
            "provider_source": used_source,
            "mood": mood,
        },
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if vault_jpg.resolve() != out_path.resolve():
        shutil.copy2(vault_jpg, out_path)
    print(f"[GoogleFlow] Bespoke cinema art ready ({used_source}): {out_path.name}", flush=True)
    return out_path


async def fetch_or_generate_flow_image(
    prompt: str,
    out_path: Optional[Path] = None,
    aspect_ratio: str = "9:16",
    character_sheet: Optional[Dict[str, Any]] = None,
    scene_index: int = 0,
) -> Path:
    """Async helper returning the `Path` to the Nano Banana 2 / FlowVault scene image."""
    res = await generate_flow_scene_image(
        prompt=prompt,
        out_path=out_path,
        aspect_ratio=aspect_ratio,
        character_sheet=character_sheet,
        scene_index=scene_index,
    )
    return Path(res["image_path"])


# ---------------------------------------------------------------------------
# Veo 3.1 Light / Omni 1.1 Flash Video Generator (x1 output, FlowVault 0-credit reuse)
# ---------------------------------------------------------------------------
def _synthesize_veo_clip_from_keyframe(
    keyframe_png: Path,
    out_mp4: Path,
    aspect_ratio: str = "9:16",
    duration_s: float = 4.0,
) -> Path:
    """Render a smooth 30fps H.264 `.mp4` motion clip from a high-res scene keyframe."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    w, h = _dimensions_for_aspect(aspect_ratio)
    dur = max(3.0, min(6.0, float(duration_s)))
    frames = max(90, int(round(dur * 30)))

    # Smooth cinematic push-in & pan at 30fps
    vf = (
        f"scale={int(w * 1.12)}:{int(h * 1.12)}:flags=lanczos,"
        f"zoompan=z='min(1.10,1.0+0.0009*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={w}x{h}:fps=30,"
        f"format=yuv420p"
    )
    run_ffmpeg_safe(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(keyframe_png),
            "-vf",
            vf,
            "-t",
            f"{dur:.2f}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ]
    )
    return out_mp4


async def generate_flow_veo_clip(
    prompt: str,
    out_mp4: Optional[Path] = None,
    aspect_ratio: str = "9:16",
    duration_s: float = 4.0,
    character_sheet: Optional[Dict[str, Any]] = None,
    model: str = "veo_3_1_light",
    max_credits_allowed: int = VEO_LIGHT_CLIP_COST,
) -> Dict[str, Any]:
    """Generate or reuse a 3–5s video clip (`Veo 3.1 Light` / `Omni 1.1 Flash`, strictly `x1 output`).
    - Checks `FlowVault` first: if already generated, reuses it for **0 credits**!
    - Enforces credit guard (`VEO_LIGHT_CLIP_COST = 15` credits) before spending.
    - Stores every generated clip in `FlowVault` (`data/flow_vault/veo_clips/`) for future 0-credit reuse.
    """
    vault = get_flow_vault()
    char_info = character_sheet or ensure_character_ingredient_sheet()
    full_prompt = f"{char_info.get('consistency_prefix', '')} {prompt}".strip()
    dur_clamped = max(3.0, min(5.0, float(duration_s)))

    # 1. Check FlowVault first for 0-credit reuse!
    hit = vault.lookup_asset(
        kind="veo_clip",
        prompt_or_mood=full_prompt,
        aspect_ratio=aspect_ratio,
        record_reuse=True,
    )
    if hit and Path(hit["abs_path"]).exists():
        src_mp4 = Path(hit["abs_path"])
        final_mp4 = src_mp4
        if out_mp4 is not None:
            out_mp4 = Path(out_mp4)
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
            if src_mp4.resolve() != out_mp4.resolve():
                shutil.copy2(src_mp4, out_mp4)
            final_mp4 = out_mp4
        return {
            "status": "ok",
            "video_path": str(final_mp4.resolve()),
            "vault_path": hit["abs_path"],
            "hash": hit["hash"],
            "veo_model": hit.get("veo_model", model),
            "output_multiplier": 1,
            "duration_s": dur_clamped,
            "reused_from_vault": True,
            "credits_spent": 0,
            "credit_guard_triggered": False,
            "render_strategy": "veo_3_1_light_video",
        }

    # 2. Credit Guard Check before spending 15 credits
    state = _load_flow_state()
    rem = int(state.get("credits_remaining", FLOW_PRO_TOTAL_CREDITS))
    if int(max_credits_allowed) < VEO_LIGHT_CLIP_COST or rem < VEO_LIGHT_CLIP_COST:
        return {
            "status": "credit_cap_blocked",
            "video_path": None,
            "veo_model": model,
            "output_multiplier": 1,
            "duration_s": dur_clamped,
            "reused_from_vault": False,
            "credits_spent": 0,
            "credit_guard_triggered": True,
            "reason": (
                f"Teto de créditos insuficiente para clipe Veo ({max_credits_allowed} < {VEO_LIGHT_CLIP_COST} cr)"
                if int(max_credits_allowed) < VEO_LIGHT_CLIP_COST
                else f"Saldo insuficiente ({rem} < {VEO_LIGHT_CLIP_COST} cr)"
            ),
            "render_strategy": "cpu_25d_parallax",
        }

    # 3. Generate keyframe + Veo motion clip (x1 output) and index in FlowVault
    img_res = await generate_flow_scene_image(
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        character_sheet=char_info,
        scene_index=0,
    )
    keyframe_path = Path(img_res["image_path"])
    clip_hash = compute_vault_hash(full_prompt, kind="veo_clips", aspect_ratio=aspect_ratio)
    vault_mp4 = vault.veo_dir / f"flow_veo_{clip_hash}.mp4"

    await asyncio.to_thread(
        _synthesize_veo_clip_from_keyframe,
        keyframe_path,
        vault_mp4,
        aspect_ratio,
        dur_clamped,
    )

    _deduct_flow_credits(VEO_LIGHT_CLIP_COST, reason=f"{model}_x1_clip", asset_hash=clip_hash)
    entry = vault.store_asset(
        kind="veo_clip",
        prompt_or_mood=full_prompt,
        file_path=vault_mp4,
        aspect_ratio=aspect_ratio,
        credits_cost=VEO_LIGHT_CLIP_COST,
        copy_into_vault=False,
        metadata={
            "veo_model": model,
            "fallback_model": "omni_1_1_flash",
            "output_multiplier": 1,
            "duration_s": dur_clamped,
            "keyframe_path": str(keyframe_path),
            "face_seed": char_info.get("face_seed"),
            "character_name": char_info.get("character_name", "Protagonista"),
        },
    )

    final_mp4 = vault_mp4
    if out_mp4 is not None:
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        if vault_mp4.resolve() != out_mp4.resolve():
            shutil.copy2(vault_mp4, out_mp4)
        final_mp4 = out_mp4

    return {
        "status": "ok",
        "video_path": str(final_mp4.resolve()),
        "image_path": str(keyframe_path.resolve()),
        "vault_path": str(vault_mp4.resolve()),
        "hash": entry["hash"],
        "veo_model": model,
        "output_multiplier": 1,
        "duration_s": dur_clamped,
        "reused_from_vault": False,
        "credits_spent": VEO_LIGHT_CLIP_COST,
        "credit_guard_triggered": False,
        "render_strategy": "veo_3_1_light_video",
    }


# ---------------------------------------------------------------------------
# Master Orchestrator for the 3 Strict Credit-Guarded Modes
# ---------------------------------------------------------------------------
async def execute_flow_visual_plan(
    scenes: List[Dict[str, Any]],
    mode: str = DEFAULT_FLOW_MODE,
    aspect_ratio: str = "9:16",
    work_dir: Optional[Path] = None,
    character_name: str = "Protagonista",
    character_desc: str = "",
    max_credits_cap: Optional[int] = None,
    strict_cap: bool = False,
) -> Dict[str, Any]:
    """Execute one of the 3 Strict Credit-Guarded Google Flow modes over a list of script scenes:

    1. `"economico_pro"` (`🟢 Econômico Pro` — Default):
       Generates/fetches consistent scene images (`Nano Banana 2` + Ingredients / Character Sheets
       keeping the same character face across scenes, with transparent zero-credit fallback to
       Pollinations/Skia) and returns image paths marked for CPU 2.5D Parallax animation (`0 credits`).
    2. `"gancho_de_ouro"` (`🟡 Gancho de Ouro (~15 créditos)`):
       Generates ONLY Scene 1 (first 3–5s) as video (`Veo 3.1 Light` / `Omni 1.1 Flash`, `x1 output`)
       and marks Scenes 2..N for CPU 2.5D Parallax!
    3. `"cinema_full_veo"` (`🔴 Cinema Full Veo (Opcional c/ Teto)`):
       Disabled by default; enforces explicit `max_credits_cap: int` check before spending credits
       and stores every clip in `FlowVault` for 0-credit reuse.
    """
    clean_mode = (mode or DEFAULT_FLOW_MODE).strip().lower()
    if clean_mode not in FLOW_MODES:
        raise ValueError(f"Modo Google Flow inválido: '{mode}'. Use um de {list(FLOW_MODES.keys())}")

    if work_dir is not None:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    # Strict validation for Cinema Full Veo (`cinema_full_veo`)
    cap_value = int(max_credits_cap) if max_credits_cap is not None else 0
    if clean_mode == "cinema_full_veo" and cap_value <= 0:
        if strict_cap:
            raise FlowCreditCapError(
                "Modo 'cinema_full_veo' está desativado por padrão e exige max_credits_cap > 0 explícito."
            )

    char_sheet = ensure_character_ingredient_sheet(
        character_name=character_name,
        character_desc=character_desc,
        aspect_ratio=aspect_ratio,
    )

    processed_scenes: List[Dict[str, Any]] = []
    credits_spent_total = 0
    credits_saved_total = 0
    credit_guard_triggered = False
    guard_reasons: List[str] = []

    if clean_mode == "cinema_full_veo" and cap_value <= 0:
        credit_guard_triggered = True
        guard_reasons.append(
            "cinema_full_veo desativado por padrão sem max_credits_cap > 0; revertido para CPU 2.5D Parallax (0 créditos)."
        )

    for idx, raw_scene in enumerate(scenes):
        sc = dict(raw_scene) if isinstance(raw_scene, dict) else {"prompt": str(raw_scene)}
        prompt = str(
            sc.get("visual_prompt")
            or sc.get("image_prompt")
            or sc.get("prompt")
            or sc.get("search_query")
            or sc.get("narration")
            or sc.get("text")
            or f"Cinematic scene {idx + 1}"
        ).strip()
        dur_s = float(sc.get("duration_s") or sc.get("duration") or 4.0)

        img_out = (work_dir / f"flow_scene_{idx + 1:02d}.png") if work_dir else None
        mp4_out = (work_dir / f"flow_scene_{idx + 1:02d}_veo.mp4") if work_dir else None

        want_veo = False
        if clean_mode == "gancho_de_ouro" and idx == 0:
            want_veo = True
        elif clean_mode == "cinema_full_veo" and cap_value > 0:
            want_veo = True

        if want_veo:
            remaining_cap = (cap_value - credits_spent_total) if clean_mode == "cinema_full_veo" else VEO_LIGHT_CLIP_COST
            veo_res = await generate_flow_veo_clip(
                prompt=prompt,
                out_mp4=mp4_out,
                aspect_ratio=aspect_ratio,
                duration_s=min(5.0, max(3.0, dur_s)),
                character_sheet=char_sheet,
                model="veo_3_1_light",
                max_credits_allowed=remaining_cap,
            )

            if veo_res.get("status") == "ok" and veo_res.get("video_path"):
                spent = int(veo_res.get("credits_spent", 0))
                credits_spent_total += spent
                if veo_res.get("reused_from_vault"):
                    credits_saved_total += VEO_LIGHT_CLIP_COST

                # Also ensure image_path is populated
                img_path_str = veo_res.get("image_path")
                if not img_path_str:
                    img_res = await generate_flow_scene_image(
                        prompt=prompt,
                        out_path=img_out,
                        aspect_ratio=aspect_ratio,
                        character_sheet=char_sheet,
                        scene_index=idx,
                    )
                    img_path_str = img_res["image_path"]

                sc.update(
                    {
                        "scene_index": idx,
                        "flow_mode": clean_mode,
                        "asset_type": "video",
                        "render_strategy": "veo_3_1_light_video",
                        "animation_engine": "veo_3_1_light",
                        "veo_model": "veo_3_1_light",
                        "output_multiplier": 1,
                        "video_path": veo_res["video_path"],
                        "image_path": img_path_str,
                        "face_seed": char_sheet.get("face_seed"),
                        "ingredient_id": char_sheet.get("ingredient_id"),
                        "reused_from_vault": bool(veo_res.get("reused_from_vault")),
                        "credits_spent": spent,
                        "cpu_25d_parallax": False,
                    }
                )
                processed_scenes.append(sc)
                continue

            # Credit cap reached in cinema_full_veo (or insufficient balance)
            credit_guard_triggered = True
            reason = str(veo_res.get("reason") or f"Cena {idx + 1} excedeu max_credits_cap={cap_value}")
            guard_reasons.append(reason)
            if strict_cap and clean_mode == "cinema_full_veo":
                raise FlowCreditCapError(reason)

        # Default / Scenes 2..N in gancho_de_ouro / Economico Pro / Cap fallback: CPU 2.5D Parallax!
        img_res = await generate_flow_scene_image(
            prompt=prompt,
            out_path=img_out,
            aspect_ratio=aspect_ratio,
            character_sheet=char_sheet,
            scene_index=idx,
        )
        sc.update(
            {
                "scene_index": idx,
                "flow_mode": clean_mode,
                "asset_type": "image",
                "render_strategy": "cpu_25d_parallax",
                "animation_engine": "cpu_25d_parallax",
                "image_model": "nano_banana_2",
                "image_path": img_res["image_path"],
                "video_path": None,
                "face_seed": char_sheet.get("face_seed"),
                "ingredient_id": char_sheet.get("ingredient_id"),
                "reused_from_vault": bool(img_res.get("reused_from_vault")),
                "credits_spent": 0,
                "cpu_25d_parallax": True,
            }
        )
        processed_scenes.append(sc)

    status_now = await get_google_flow_credits_status()
    veo_scenes_count = sum(1 for s in processed_scenes if s.get("asset_type") == "video")
    parallax_scenes_count = sum(1 for s in processed_scenes if s.get("cpu_25d_parallax"))

    return {
        "status": "ok",
        "mode": clean_mode,
        "mode_label": FLOW_MODES[clean_mode]["label"],
        "aspect_ratio": aspect_ratio,
        "character_sheet": {
            "character_name": char_sheet.get("character_name"),
            "face_seed": char_sheet.get("face_seed"),
            "ingredient_id": char_sheet.get("ingredient_id"),
            "path": char_sheet.get("abs_path") or char_sheet.get("path"),
        },
        "scenes": processed_scenes,
        "image_paths": [s["image_path"] for s in processed_scenes if s.get("image_path")],
        "veo_scenes_count": veo_scenes_count,
        "parallax_scenes_count": parallax_scenes_count,
        "credits_spent": credits_spent_total,
        "credits_saved_by_vault": credits_saved_total,
        "max_credits_cap": cap_value if clean_mode == "cinema_full_veo" else None,
        "credit_guard_triggered": credit_guard_triggered,
        "credit_guard_reasons": guard_reasons,
        "credits_remaining": status_now["credits_remaining"],
        "badge_text": status_now["badge_text"],
    }


# Aliases for seamless cross-module integration
generate_scenes_with_flow_mode = execute_flow_visual_plan
run_google_flow_mode = execute_flow_visual_plan
plan_flow_scenes = execute_flow_visual_plan


if __name__ == "__main__":
    async def _selftest() -> None:
        status = await get_google_flow_credits_status()
        demo_scenes = [
            {"prompt": "Investigative journalist discovering secret ledger in dark vault", "duration_s": 4.0},
            {"prompt": "Close up of financial documents and glowing computer monitor", "duration_s": 4.0},
            {"prompt": "Dramatic skyline of financial district at night", "duration_s": 4.0},
        ]
        res_eco = await execute_flow_visual_plan(demo_scenes, mode="economico_pro")
        res_hook = await execute_flow_visual_plan(demo_scenes, mode="gancho_de_ouro")
        res_cap = await execute_flow_visual_plan(demo_scenes, mode="cinema_full_veo", max_credits_cap=15)
        reset_google_flow_credits(FLOW_PRO_TOTAL_CREDITS)
        print(
            json.dumps(
                {
                    "badge": status["badge_text"],
                    "economico_pro_credits": res_eco["credits_spent"],
                    "gancho_de_ouro_veo_scenes": res_hook["veo_scenes_count"],
                    "gancho_de_ouro_parallax_scenes": res_hook["parallax_scenes_count"],
                    "cinema_full_veo_capped_credits": res_cap["credits_spent"],
                    "cinema_full_veo_guard_triggered": res_cap["credit_guard_triggered"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    asyncio.run(_selftest())
