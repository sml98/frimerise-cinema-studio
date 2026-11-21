"""FrimeRise End-to-End Video Manufacturing Pipeline (3 Master Engines + Twin Channels Edition).
Orchestrates all 3 Master Engines:
  1. cinematic_broll: Vídeo Dinâmico Viral / Bespoke 2.5D + Hormozi Captions + 3D LUT + Motion Cards
  2. cartoon_2d: Animação 2D Cartoon Multi-Personagens (60 FPS, Line Boil 8fps, Rhubarb 9-Visemas)
  3. netflix_doc: Documentário Cinema Netflix / MagnatesMedia 16:9 & 9:16 (Cold Open, Capítulos, 5 Modos Skia)
Plus:
  - 3 Magnetic 1280x720 A/B/C Thumbnails (with exact 3-word hooks)
  - Cascade 16:9 -> 5 Vertical Shorts 9:16 (Zero Tokens)
  - Multi-Language Dubbing & Re-Timing (PT-BR / EN-US / ES)
  - ShadowHash 3 Mutations + 540p WhatsApp Preview + CapCut ZIP + Kdenlive OTIO
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import skia

from agents.llm_router import generate_viral_script
from database import (
    append_job_log,
    create_job,
    get_client,
    get_job,
    get_preset,
    get_settings,
    update_job,
)
from engine.audio_dsp import (
    ALL_EDGE_VOICES,
    KOKORO_VOICES,
    generate_narration,
    master_broadcast_audio,
    normalize_edge_pitch,
    normalize_edge_rate,
)
from engine.blueprint_cloner import render_cloned_cartoon_from_blueprint
from engine.cartoon_2d_studio import generate_cartoon_episode_plan, render_cartoon_episode
from engine.exporters import (
    export_capcut_zip,
    export_kdenlive_otio,
    export_whatsapp_preview_540p,
    splice_dual_hook_b,
)
from engine.global_scaler import dub_video_job_multi_language, extract_5_viral_shorts_from_16x9
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    read_cpu_temperature_c,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.skia_compositor import SkiaMotionCompositor, render_cover_9x16
from engine.smart_vision import (
    assemble_scenes_with_xfade,
    detect_face_center_x,
    evaluate_clip_quality,
    fetch_unique_real_clip,
    prepare_styled_scene,
)
from engine.thumbnail_studio import generate_ab_thumbnails_16x9
from engine.viral_cloner import VideoDNAExtractor
from publisher.shadowhash import generate_shadowhash_variants

# Defensive imports for Worker 1-6 modules
try:
    from engine.netflix_doc_studio import generate_netflix_doc_plan, render_netflix_documentary
except ImportError:
    generate_netflix_doc_plan = None  # type: ignore
    render_netflix_documentary = None  # type: ignore

try:
    from agents.retention_doctor import audit_netflix_doc_plan
except ImportError:
    audit_netflix_doc_plan = None  # type: ignore

from engine.flow_vault import fetch_or_generate_flow_music
from engine.gdrive_sync import upload_job_to_gdrive
from engine.gemini_tts import has_valid_gemini_key

try:
    from engine.bespoke_visuals import render_25d_parallax_clip, render_bespoke_scene_clip
except ImportError:
    render_25d_parallax_clip = None  # type: ignore
    render_bespoke_scene_clip = None  # type: ignore

try:
    from engine.doc_media_engine import fetch_doc_real_photo
except ImportError:
    fetch_doc_real_photo = None  # type: ignore

try:
    from engine.pro_sfx_studio import select_music_for_mood
except ImportError:
    select_music_for_mood = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

_ASPECT_DIMS: Dict[str, Tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
}

_VALID_VISUAL_LIBRARIES: Tuple[str, ...] = (
    "real_broll",
    "photos_25d",
    "video_over_video",
    "skia_graphics",
    "cartoon_2d_layer",
    "bespoke_ai",
    "cinema_35mm_sfx",
)

_VALID_CAPTION_STYLES: Tuple[str, ...] = (
    "hormozi_neon",
    "karaoke_glow",
    "word_slam",
    "cinema_minimal",
    "typewriter_highlight",
    "none",
)

_GEMINI_VOICE_IDS: Set[str] = {"Puck", "Charon", "Fenrir", "Orus", "Kore", "Aoede", "Zephyr", "Leda"}
_EDGE_VOICE_IDS: Set[str] = {v["id"] for v in ALL_EDGE_VOICES}


def _normalize_language(raw_lang: Optional[str]) -> str:
    norm = str(raw_lang or "pt_br").strip().lower().replace("-", "_")
    if norm.startswith("en"):
        return "en_us"
    if norm.startswith("es"):
        return "es"
    return "pt_br"


def _default_edge_for_lang(lang: str) -> str:
    if lang == "en_us":
        return "en-US-AndrewMultilingualNeural"
    if lang == "es":
        return "es-MX-JorgeNeural"
    return "pt-BR-AntonioNeural"


def _resolve_voice_overrides(
    opts: Dict[str, Any],
    client: Dict[str, Any],
    preset: Dict[str, Any],
    engine_style: str,
    language: str,
) -> Tuple[str, str, Dict[str, float], str, str]:
    """Resolve user voice overrides cleanly over client/preset defaults across all 3 engines."""
    raw_engine = str(opts.get("voice_engine") or "").strip().lower()
    raw_voice_id = str(opts.get("voice_id") or "").strip()
    voice_rate = normalize_edge_rate(opts.get("voice_rate") or "+8%")
    voice_pitch = normalize_edge_pitch(opts.get("voice_pitch") or "+0Hz")

    if raw_engine in ("gemini_tts", "edge", "kokoro"):
        eff_engine = raw_engine
    elif engine_style == "cartoon_2d":
        c_ve = str(opts.get("cartoon_voice_engine") or "gemini_tts").strip().lower()
        eff_engine = c_ve if c_ve in ("gemini_tts", "edge", "kokoro") else "gemini_tts"
    elif engine_style == "netflix_doc":
        gem_ok, _ = has_valid_gemini_key()
        if gem_ok:
            eff_engine = "gemini_tts"
        else:
            eff_engine = str(client.get("voice_engine") or preset.get("voice_engine") or "edge").strip().lower()
            if eff_engine not in ("gemini_tts", "edge", "kokoro"):
                eff_engine = "edge"
    else:
        eff_engine = str(client.get("voice_engine") or preset.get("voice_engine") or "edge").strip().lower()
        if eff_engine not in ("gemini_tts", "edge", "kokoro"):
            eff_engine = "edge"

    if raw_voice_id:
        eff_voice_id = raw_voice_id
    else:
        client_vid = str(client.get("voice_id") or preset.get("voice_id") or "").strip()
        if eff_engine == "gemini_tts":
            default_gem = "Charon" if engine_style == "netflix_doc" else "Puck"
            eff_voice_id = client_vid if client_vid in _GEMINI_VOICE_IDS else default_gem
        elif eff_engine == "kokoro":
            eff_voice_id = client_vid if client_vid in KOKORO_VOICES else "pm_alex"
        else:
            # Auto-align language voice when user picks EN-US or ES without explicitly choosing a voice_id
            if language == "en_us" and not client_vid.lower().startswith("en-"):
                eff_voice_id = "en-US-AndrewMultilingualNeural"
            elif language == "es" and not client_vid.lower().startswith("es-"):
                eff_voice_id = "es-MX-JorgeNeural"
            else:
                eff_voice_id = client_vid or _default_edge_for_lang(language)

    # Guard mismatched voice_id vs chosen engine
    if eff_engine == "gemini_tts" and eff_voice_id not in _GEMINI_VOICE_IDS:
        female_hint = any(k in eff_voice_id.lower() for k in ("francisca", "thalita", "ava", "dalia", "dora", "heart"))
        eff_voice_id = "Kore" if female_hint else "Puck"
    elif eff_engine == "kokoro" and eff_voice_id not in KOKORO_VOICES:
        female_hint = any(k in eff_voice_id.lower() for k in ("francisca", "thalita", "ava", "dalia", "kore", "aoede"))
        eff_voice_id = "af_heart" if (language == "en_us" and female_hint) else ("pf_dora" if female_hint else ("am_adam" if language == "en_us" else "pm_alex"))
    elif eff_engine == "edge" and eff_voice_id not in _EDGE_VOICE_IDS and "Neural" not in eff_voice_id:
        eff_voice_id = _default_edge_for_lang(language)

    try:
        eff_blend = json.loads(client.get("voice_blend") or preset.get("voice_blend", "{}"))
        if not isinstance(eff_blend, dict):
            eff_blend = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}
    except Exception:
        eff_blend = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}

    if eff_engine == "kokoro" and raw_voice_id in KOKORO_VOICES:
        eff_blend = {raw_voice_id: 1.0}

    return eff_engine, eff_voice_id, eff_blend, voice_rate, voice_pitch


def _create_silent_music_bed(work_dir: Path, thermal_limit_c: float = 85.0) -> Path:
    """Create a lightweight 2s silent MP3 so engines with internal default fallbacks stay 100% muted."""
    silent_mp3 = work_dir / "_silent_music_bed.mp3"
    if not silent_mp3.exists():
        run_ffmpeg_safe(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "2.0", "-c:a", "libmp3lame", "-b:a", "64k",
                str(silent_mp3),
            ],
            thermal_limit_c=thermal_limit_c,
        )
    return silent_mp3


async def _resolve_music_selection(
    music_opt: Optional[str],
    music_volume: float,
    use_flow_music: bool,
    preset: Dict[str, Any],
    default_filename: str,
    topic: str,
    duration_s: float,
    work_dir: Path,
    thermal_limit_c: float = 85.0,
    allow_none: bool = True,
    allow_mood_auto: bool = False,
) -> Tuple[Optional[Path], str]:
    """Resolve background music path & metadata label respecting 'none', 'flow_vault', custom '.mp3', or 'auto'."""
    m_opt = str(music_opt or "").strip()
    m_low = m_opt.lower()

    if m_low == "none" or music_volume <= 0.001:
        if allow_none:
            return None, "none"
        return _create_silent_music_bed(work_dir, thermal_limit_c=thermal_limit_c), "none"

    if m_low == "flow_vault" or (use_flow_music and m_low in ("", "auto")):
        if fetch_or_generate_flow_music is not None:
            try:
                p = await fetch_or_generate_flow_music(topic, max(20.0, duration_s))
                if p and Path(p).exists():
                    return Path(p), "flow_vault"
            except Exception:
                pass

    if m_opt and m_low not in ("auto", "flow_vault", "none"):
        cand = ASSETS_DIR / "music" / Path(m_opt).name
        if cand.exists():
            return cand, cand.name

    # Auto mode: optionally pick topic-mood music (e.g. dark_mystery_horror.mp3 for macabre topics)
    if allow_mood_auto:
        if select_music_for_mood is not None:
            try:
                mood_p = select_music_for_mood(topic, default_file=preset.get("music_file", default_filename))
                if mood_p and Path(mood_p).exists():
                    return Path(mood_p), Path(mood_p).name
            except Exception:
                pass
        return None, "auto"

    preset_m = ASSETS_DIR / "music" / preset.get("music_file", default_filename)
    if preset_m.exists():
        return preset_m, preset_m.name
    fallback_m = ASSETS_DIR / "music" / default_filename
    return (fallback_m if fallback_m.exists() else None), (fallback_m.name if fallback_m.exists() else "none")


def _reframe_video_to_dims(
    in_mp4: Path,
    out_mp4: Path,
    target_w: int,
    target_h: int,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Cleanly aspect-cover center-crop any video to (target_w, target_h) preserving audio stream."""
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={target_w}:{target_h},"
        f"{hw_suffix}"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        "-i", str(in_mp4),
        "-vf", vf,
        *enc_args,
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c)
    return out_mp4


def _style_scene_clip_ffmpeg(
    raw_clip: Path,
    out_mp4: Path,
    duration_s: float,
    lut_file: str,
    scene_index: int,
    target_w: int,
    target_h: int,
    fps: int = 30,
    enable_cinema_fx: bool = True,
    apply_motion_zoom: bool = True,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Style ANY source scene clip (real B-roll, 2.5D photo, bespoke AI, or cartoon cutaway) to exact
    (target_w, target_h, fps) with optional face-centered Ken Burns zoom, 3D LUT (.cube),
    35mm cinema film grain, and dynamically-scaled vignette/scrim overlays.
    """
    lut_path = ASSETS_DIR / "luts" / lut_file
    vignette_path = ASSETS_DIR / "overlays" / "vignette_9x16.png"
    scrim_path = ASSETS_DIR / "overlays" / "safe_scrim.png"

    safe_dur = max(1.0, float(duration_s))
    vf_chain: List[str] = [f"fps={fps}"]

    if apply_motion_zoom:
        face_x = detect_face_center_x(raw_clip)
        super_w = int(round(target_w * 1.25 / 2.0) * 2)
        super_h = int(round(target_h * 1.25 / 2.0) * 2)
        crop_w = int(round(target_w * 1.10 / 2.0) * 2)
        crop_h = int(round(target_h * 1.10 / 2.0) * 2)
        dx_max = max(4, min(38, (super_w - crop_w) // 3))
        dy_max = max(4, min(44, (super_h - crop_h) // 3))
        direction = 1 if scene_index % 2 == 0 else -1
        cx_expr = f"clip((iw-{super_w})*{face_x:.3f},0,max(0,iw-{super_w}))"
        drift_x = f"({super_w}-{crop_w})/2+({direction})*{dx_max}*(t/{safe_dur:.2f})"
        drift_y = f"({super_h}-{crop_h})/2+{dy_max}*(t/{safe_dur:.2f})"
        vf_chain.extend([
            f"scale={super_w}:{super_h}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop=w={super_w}:h={super_h}:x='{cx_expr}':y='(ih-{super_h})/2'",
            f"crop=w={crop_w}:h={crop_h}:x='{drift_x}':y='{drift_y}'",
            f"scale={target_w}:{target_h}:flags=lanczos",
        ])
    else:
        vf_chain.extend([
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={target_w}:{target_h}",
        ])

    if lut_path.exists():
        esc_lut = str(lut_path).replace("\\", "/").replace(":", "\\:")
        vf_chain.append(f"lut3d=file='{esc_lut}'")

    if enable_cinema_fx:
        # Subtle organic 35mm cinema film grain
        vf_chain.append("noise=alls=5:allf=t+u")

    vf_chain.append("format=yuv420p")

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    inputs = ["-stream_loop", "-1", "-i", str(raw_clip)]
    filter_parts = [f"[0:v]{','.join(vf_chain)}[base]"]
    cur = "[base]"
    idx = 1

    if vignette_path.exists():
        inputs.extend(["-i", str(vignette_path)])
        filter_parts.append(f"[{idx}:v]scale={target_w}:{target_h}[vig];{cur}[vig]overlay=0:0[v1]")
        cur = "[v1]"
        idx += 1
    if scrim_path.exists():
        inputs.extend(["-i", str(scrim_path)])
        filter_parts.append(f"[{idx}:v]scale={target_w}:{target_h}[scr];{cur}[scr]overlay=0:0[v2]")
        cur = "[v2]"
        idx += 1

    filter_parts.append(f"{cur}{hw_suffix}[vout]")

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]",
        "-t", f"{duration_s:.3f}",
        "-video_track_timescale", "30000",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c)
    return out_mp4


def _apply_pip_video_overlay(
    base_scene_mp4: Path,
    pip_raw_clip: Path,
    out_mp4: Path,
    duration_s: float,
    target_w: int,
    target_h: int,
    fps: int = 30,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Composite a sleek Picture-in-Picture (Video-over-Video) forensic monitor inset over a styled scene."""
    pip_w = int(round((target_w * (0.40 if target_w <= target_h else 0.34)) / 2.0) * 2)
    pip_h = int(round((pip_w * 9.0 / 16.0) / 2.0) * 2)
    margin_x = int(target_w * 0.045)
    margin_y = int(target_h * 0.065)
    pip_x = target_w - pip_w - margin_x
    pip_y = margin_y

    # Render glowing cyber-luxury monitor frame in Skia C++ (zero debug text!)
    frame_png = out_mp4.with_suffix(".pip_frame.png")
    pad = 14
    fw, fh = pip_w + pad * 2, pip_h + pad * 2
    surf = skia.Surface(fw, fh)
    c = surf.getCanvas()
    c.clear(skia.Color4f(0, 0, 0, 0))
    outer = skia.Rect.MakeXYWH(pad - 3, pad - 3, pip_w + 6, pip_h + 6)
    border_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.5, Color=skia.ColorSetARGB(235, 255, 46, 147))
    border_p.setImageFilter(skia.ImageFilters.DropShadow(0, 0, 10, 10, skia.ColorSetARGB(180, 255, 46, 147)))
    c.drawRoundRect(outer, 16, 16, border_p)
    # Corner viewfinder ticks in Warm Gold (#FFD166)
    tick_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=skia.ColorSetARGB(230, 255, 209, 102))
    tl = 20.0
    c.drawLine(pad + 6, pad + 6, pad + 6 + tl, pad + 6, tick_p)
    c.drawLine(pad + 6, pad + 6, pad + 6, pad + 6 + tl, tick_p)
    c.drawLine(pad + pip_w - 6 - tl, pad + pip_h - 6, pad + pip_w - 6, pad + pip_h - 6, tick_p)
    c.drawLine(pad + pip_w - 6, pad + pip_h - 6 - tl, pad + pip_w - 6, pad + pip_h - 6, tick_p)
    # Subtle red REC indicator dot (pure graphic, zero text)
    c.drawCircle(pad + 22, pad + 22, 6.5, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(245, 255, 46, 95)))
    surf.makeImageSnapshot().save(str(frame_png), skia.kPNG)

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    fc = (
        f"[1:v]fps={fps},scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={pip_w}:{pip_h},format=rgba[pip];"
        f"[0:v][pip]overlay={pip_x}:{pip_y}:shortest=1[v_pip];"
        f"[v_pip][2:v]overlay={pip_x - pad}:{pip_y - pad}:shortest=1,{hw_suffix}[vout]"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        "-i", str(base_scene_mp4),
        "-stream_loop", "-1", "-i", str(pip_raw_clip),
        "-i", str(frame_png),
        "-filter_complex", fc,
        "-map", "[vout]",
        "-t", f"{duration_s:.3f}",
        "-video_track_timescale", "30000",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c)
    frame_png.unlink(missing_ok=True)
    return out_mp4


def _render_cartoon_cutaway_scene(
    out_mp4: Path,
    duration_s: float,
    target_w: int,
    target_h: int,
    fps: int = 30,
    scene_index: int = 0,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Render an expressive 2D Cartoon cutaway clip in Skia C++ when 'cartoon_2d_layer' is mixed into cinematic_broll."""
    from engine.cartoon_2d_studio import CartoonCharacter, VisualRig, VoicePreset
    from engine.cartoon_v2_renderer import draw_cartoon_puppet_v2, draw_parallax_scenery_v2

    thermal_guard_wait(limit_c=thermal_limit_c)
    total_frames = max(1, int(math.ceil(duration_s * fps)))
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        "-f", "rawvideo", "-pix_fmt", "bgra",
        "-s", f"{target_w}x{target_h}", "-r", str(fps), "-i", "pipe:0",
        "-vf", hw_suffix,
        "-t", f"{duration_s:.3f}",
        "-video_track_timescale", "30000",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    char_a = CartoonCharacter(
        char_id="host_a",
        name="Host",
        voice_preset=VoicePreset(),
        visual_rig=VisualRig(
            skin_color="#F1C29B",
            outfit="modern_hoodie",
            accessory="cap",
            primary_color="#FF2E93",
            secondary_color="#FFD166",
            hair_color="#2A1B12",
        ),
    )
    char_b = CartoonCharacter(
        char_id="host_b",
        name="Analista",
        voice_preset=VoicePreset(),
        visual_rig=VisualRig(
            skin_color="#E6B08A",
            outfit="suit_boss",
            accessory="tie",
            primary_color="#2563EB",
            secondary_color="#B8FF01",
            hair_color="#1F2937",
        ),
    )
    env_types = ("office", "street", "palace")
    env_t = env_types[scene_index % len(env_types)]
    vis_cycle = ("A", "C", "D", "B", "E", "F", "X")

    surf = skia.Surface(target_w, target_h)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
    )
    assert proc.stdin is not None
    try:
        scale_p = min(target_w, target_h) / 1080.0 * 1.12
        py = target_h * 0.56
        for fi in range(total_frames):
            t = fi / float(fps)
            c = surf.getCanvas()
            c.clear(skia.ColorSetARGB(255, 11, 7, 19))
            draw_parallax_scenery_v2(c, 0, 0, target_w, target_h, env_t, [], t, cam_pan_x=math.sin(t * 0.9) * 36.0)
            vis = vis_cycle[int(t * 8.0) % len(vis_cycle)]
            draw_cartoon_puppet_v2(
                c, char_a, target_w * 0.30, py, scale_p, +1,
                emotion="smug" if scene_index % 2 == 0 else "shocked",
                viseme=vis, speech_energy=0.65, is_speaking=True, t=t, blink_offset=0.0,
            )
            draw_cartoon_puppet_v2(
                c, char_b, target_w * 0.70, py, scale_p, -1,
                emotion="laughing" if scene_index % 2 == 0 else "neutral",
                viseme="X", speech_energy=0.0, is_speaking=False, t=t, blink_offset=1.3,
            )
            proc.stdin.write(surf.makeImageSnapshot().tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait(timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"Cartoon cutaway render failed: {stderr.decode(errors='ignore')}")
    return out_mp4


def _assemble_mixed_scenes_with_xfade(
    scene_paths: List[Path],
    scene_durations: List[float],
    out_mp4: Path,
    target_w: int,
    target_h: int,
    fps: int = 30,
    xfade_dur: float = 0.30,
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, List[float]]:
    """Stitch mixed-library scenes with guaranteed matching resolution/fps/timebase + smooth FFmpeg xfade."""
    if len(scene_paths) == 1:
        if scene_paths[0] != out_mp4:
            run_ffmpeg_safe(
                ["ffmpeg", "-y", "-v", "error", "-i", str(scene_paths[0]), "-c", "copy", str(out_mp4)],
                thermal_limit_c=thermal_limit_c,
            )
        return out_mp4, []

    transitions = ["fade", "wipeleft", "smoothup", "slideright", "smoothleft", "dissolve"]
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)

    inputs: List[str] = []
    filter_parts: List[str] = []
    for i, p in enumerate(scene_paths):
        inputs.extend(["-i", str(p)])
        filter_parts.append(
            f"[{i}:v]fps={fps},scale={target_w}:{target_h}:flags=lanczos,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[s{i}]"
        )

    transition_times: List[float] = []
    prev_label = "[s0]"
    offset = max(0.3, scene_durations[0] - xfade_dur)

    for i in range(1, len(scene_paths)):
        tr = transitions[(i - 1) % len(transitions)]
        out_lbl = f"[xf{i}]"
        safe_offset = max(0.25, offset)
        transition_times.append(round(safe_offset, 3))
        filter_parts.append(
            f"{prev_label}[s{i}]xfade=transition={tr}:duration={xfade_dur:.2f}:offset={safe_offset:.3f}{out_lbl}"
        )
        prev_label = out_lbl
        offset = safe_offset + max(0.5, scene_durations[i] - xfade_dur)

    filter_parts.append(f"{prev_label}{hw_suffix}[vout]")

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]",
        *enc_args,
        "-an",
        str(out_mp4),
    ]
    run_ffmpeg_safe(cmd, thermal_limit_c=thermal_limit_c)
    return out_mp4, transition_times


def _composite_with_style(
    compositor: SkiaMotionCompositor,
    bg_video: Path,
    audio_m4a: Path,
    output_mp4: Path,
    duration_s: float,
    words: List[Dict[str, Any]],
    motion_cards: List[Dict[str, Any]],
    fps: int,
    use_motion_cards: bool,
    caption_style: str,
    aspect_ratio: str,
    thermal_limit_c: float,
) -> Path:
    """Composite kinetic captions & Skia motion cards respecting caption_style ('none' skips burn-in!) and aspect ratio."""
    eff_style = caption_style if caption_style in _VALID_CAPTION_STYLES else "hormozi_neon"
    if eff_style == "none" and not use_motion_cards:
        # Clean master without captions or cards: fast lossless video+audio mux
        run_ffmpeg_safe(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(bg_video),
                "-i", str(audio_m4a),
                "-map", "0:v", "-map", "1:a",
                "-t", f"{duration_s:.3f}",
                "-c:v", "copy", "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_mp4),
            ],
            thermal_limit_c=thermal_limit_c,
        )
        return output_mp4

    eff_words = [] if eff_style == "none" else words
    y_ratio_map = {"9:16": 0.76, "16:9": 0.86, "4:5": 0.82, "1:1": 0.83}
    y_ratio = y_ratio_map.get(aspect_ratio, 0.78)
    font_size = 76.0 if aspect_ratio == "9:16" else (62.0 if aspect_ratio == "16:9" else 68.0)

    sig = inspect.signature(compositor.composite_onto_video)
    kwargs: Dict[str, Any] = {}
    if "caption_style" in sig.parameters:
        kwargs["caption_style"] = eff_style
    if "y_ratio" in sig.parameters:
        kwargs["y_ratio"] = y_ratio
    if "font_size" in sig.parameters:
        kwargs["font_size"] = font_size

    return compositor.composite_onto_video(
        bg_video,
        audio_m4a,
        output_mp4,
        duration_s,
        eff_words,
        motion_cards,
        fps,
        use_motion_cards,
        thermal_limit_c,
        **kwargs,
    )


def _rel_output(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)


def _call_generate_ab_thumbnails(
    master_mp4: Path,
    title: str,
    job_dir: Path,
    custom_3words: Optional[str] = None,
) -> Dict[str, Any]:
    """Call generate_ab_thumbnails_16x9 supporting both custom_3words and legacy 3-arg signature."""
    if custom_3words:
        try:
            sig = inspect.signature(generate_ab_thumbnails_16x9)
            if "custom_3words" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            ):
                return generate_ab_thumbnails_16x9(master_mp4, title, job_dir, custom_3words=custom_3words)
        except Exception:
            pass
    return generate_ab_thumbnails_16x9(master_mp4, title, job_dir)


def _schedule_motion_cards(raw_cards: List[Dict[str, Any]], duration_s: float) -> List[Dict[str, Any]]:
    """Schedule 1-2 short punchy Motion Graphics Cards (strictly 2.5s to 3.5s each) over real footage."""
    if not raw_cards or duration_s < 8.0:
        return []
    n = min(2, len(raw_cards))
    scheduled = []
    card_dur = 3.0
    anchors = [duration_s * 0.34, duration_s * 0.68] if n == 2 else [duration_s * 0.45]
    for idx in range(n):
        card = dict(raw_cards[idx])
        st = round(max(3.6, anchors[idx] - card_dur / 2.0), 2)
        en = round(min(duration_s - 1.2, st + card_dur), 2)
        if en - st >= 2.5:
            card["start"] = st
            card["end"] = en
            scheduled.append(card)
    return scheduled


async def run_video_job(
    job_id: str,
    client_id: int,
    topic: str,
    skill_id: str = "01_negative_hook",
    mode: str = "single",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a complete FrimeRise manufacturing job across all 3 Master Engines with full creative controls."""
    opts = options or {}
    seamless_loop = bool(opts.get("seamless_loop", True))
    dual_hook_ab = bool(opts.get("dual_hook_ab", True))
    source_url = str(opts.get("source_url", "")).strip()
    reference_mp4_path = str(opts.get("reference_mp4_path", "")).strip()
    custom_script = opts.get("custom_script")
    engine_style = str(opts.get("engine_style", "cinematic_broll")).strip()
    if engine_style not in ("cinematic_broll", "cartoon_2d", "netflix_doc"):
        engine_style = "cinematic_broll"

    raw_ar = str(opts.get("aspect_ratio") or "").strip()
    if raw_ar in _ASPECT_DIMS:
        aspect_ratio = raw_ar
    elif engine_style == "netflix_doc":
        aspect_ratio = "16:9"
    else:
        aspect_ratio = "9:16"
    target_w, target_h = _ASPECT_DIMS[aspect_ratio]

    cartoon_tone = str(opts.get("cartoon_tone", "Comédia Nordestina/BR")).strip()
    cartoon_fps = 60 if int(opts.get("cartoon_fps", 60)) >= 60 else 30
    resolved_fps = (
        (60 if int(opts["fps"]) >= 60 else 30)
        if opts.get("fps") is not None
        else (cartoon_fps if engine_style == "cartoon_2d" else 30)
    )
    clone_languages = bool(opts.get("clone_languages", False))
    flow_mode = str(opts.get("flow_mode", "economico_pro")).strip()
    max_credits_cap = int(opts.get("max_credits_cap", 45) or 45)
    use_flow_music = bool(opts.get("use_flow_music", False))
    thumb_3words = str(opts.get("thumb_3words") or "").strip() or None
    auto_shorts_cascade = bool(opts.get("auto_shorts_cascade", engine_style == "netflix_doc"))
    target_minutes = float(opts.get("target_minutes") or 0.5)

    # Full Creative Studio overrides
    raw_target_dur = opts.get("target_duration_s")
    target_duration_s: Optional[int] = (
        max(10, min(900, int(raw_target_dur))) if raw_target_dur is not None and str(raw_target_dur).strip() != "" else None
    )
    cut_cadence_s = max(1.5, min(10.0, float(opts.get("cut_cadence_s") or 3.5)))
    music_opt = opts.get("music_file")
    music_volume = max(0.0, min(0.60, float(opts["music_volume"]) if opts.get("music_volume") is not None else 0.18))
    caption_style = str(opts.get("caption_style") or "hormozi_neon").strip().lower()
    if caption_style not in _VALID_CAPTION_STYLES:
        caption_style = "hormozi_neon"
    custom_directives = str(opts.get("custom_directives") or "").strip()

    # Visual libraries mixer resolution (backward compatible when omitted/empty)
    explicit_libs = [
        str(x).strip()
        for x in (opts.get("visual_libraries") or [])
        if str(x).strip() in _VALID_VISUAL_LIBRARIES
    ]
    explicit_libs = list(dict.fromkeys(explicit_libs))
    if explicit_libs:
        active_visual_libraries = explicit_libs
        use_motion_cards = "skia_graphics" in active_visual_libraries
        enable_cinema_fx = "cinema_35mm_sfx" in active_visual_libraries
    else:
        use_motion_cards = bool(opts.get("motion_cards", True))
        enable_cinema_fx = True
        if engine_style == "cartoon_2d":
            active_visual_libraries = ["cartoon_2d_layer", "cinema_35mm_sfx"]
        elif engine_style == "netflix_doc":
            active_visual_libraries = ["real_broll", "photos_25d", "video_over_video", "skia_graphics", "cinema_35mm_sfx"]
        else:
            active_visual_libraries = ["real_broll"] + (["skia_graphics"] if use_motion_cards else []) + ["cinema_35mm_sfx"]

    job_dir = OUTPUTS_DIR / job_id
    work_dir = job_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    thermal_limit = float(opts.get("thermal_limit_c") or settings.get("thermal_limit_c") or 85.0)
    client = get_client(client_id)
    preset = get_preset(opts.get("preset_id") or client.get("preset_id") or "frimerise_signature")
    lut_file = opts.get("lut_file") or client.get("lut_file") or preset.get("lut_file", "01_frimerise_signature.cube")
    watermark_text = str(opts.get("watermark_text") or client.get("watermark_text") or "PRÉVIA • FRIMERISE").strip()

    # Language resolution (explicit language > doc_lang > client voice heuristic)
    client_vid_low = str(client.get("voice_id") or "").lower()
    if opts.get("language"):
        language = _normalize_language(opts.get("language"))
    elif opts.get("doc_lang"):
        language = _normalize_language(opts.get("doc_lang"))
    elif "en-us" in client_vid_low or client.get("name") == "Vault Files":
        language = "en_us"
    elif "es-" in client_vid_low:
        language = "es"
    else:
        language = "pt_br"

    eff_voice_engine, eff_voice_id, eff_voice_blend, voice_rate, voice_pitch = _resolve_voice_overrides(
        opts, client, preset, engine_style, language
    )

    def _build_creative_config(music_label: str, final_aspect: str, final_fps: int, final_libs: List[str]) -> Dict[str, Any]:
        return {
            "voice_engine": eff_voice_engine,
            "voice_id": eff_voice_id,
            "voice_rate": voice_rate,
            "voice_pitch": voice_pitch,
            "target_duration_s": target_duration_s,
            "cut_cadence_s": cut_cadence_s,
            "fps": final_fps,
            "aspect_ratio": final_aspect,
            "preset_id": str(preset.get("id") or opts.get("preset_id") or "frimerise_signature"),
            "lut_file": lut_file,
            "music_file": music_label,
            "music_volume": round(music_volume, 3),
            "caption_style": caption_style,
            "language": language,
            "visual_libraries": list(final_libs),
            "custom_directives": custom_directives,
        }

    try:
        update_job(job_id, status="running", progress=5, stage="Analisando DNA & Roteirizando")
        append_job_log(
            job_id,
            f"Iniciando fabricação | Cliente: {client['name']} | Motor: {engine_style} | Formato: {aspect_ratio} ({resolved_fps}fps) "
            f"| Voz: {eff_voice_engine}/{eff_voice_id} ({voice_rate}, {voice_pitch}) | Mix: {', '.join(active_visual_libraries)}",
        )

        reference_transcript = ""
        detected_dna: Optional[Dict[str, Any]] = None
        if mode == "clone_url" and (source_url or reference_mp4_path):
            extractor = VideoDNAExtractor()
            if reference_mp4_path and (BASE_DIR / reference_mp4_path).exists():
                append_job_log(job_id, "Analisando DNA do MP4 enviado via VideoDNAExtractor...", progress=10, stage="Extraindo DNA do Vídeo")
                detected_dna = await asyncio.to_thread(extractor.extract_from_local_mp4, BASE_DIR / reference_mp4_path, topic)
            elif source_url:
                append_job_log(job_id, f"Clonando URL via VideoDNAExtractor ({source_url})...", progress=10, stage="Extraindo DNA da URL Viral")
                detected_dna = await asyncio.to_thread(extractor.extract_from_url, source_url)

            if detected_dna:
                reference_transcript = detected_dna.get("transcript", "")
                if not topic or topic.lower().startswith("clone viral"):
                    topic = detected_dna.get("title", "Conteúdo Viral Clonado")
                    update_job(job_id, topic=topic)
                dna_style = str(
                    detected_dna.get("classified_engine")
                    or detected_dna.get("engine_classification")
                    or detected_dna.get("style", "live_action_broll")
                ).lower()
                append_job_log(
                    job_id,
                    f"VideoDNAExtractor detectou: {dna_style} (confiança={detected_dna.get('confidence', 0):.0%}, "
                    f"cadência={detected_dna.get('scene_cadence', {})}, tom='{detected_dna.get('detected_tone', '')}')",
                )
                if dna_style in ("2d_cartoon_animation", "2d_cartoon", "cartoon_2d"):
                    engine_style = "cartoon_2d"
                    if not opts.get("cartoon_tone"):
                        cartoon_tone = detected_dna.get("detected_tone", cartoon_tone)
                    if not opts.get("aspect_ratio") and detected_dna.get("aspect_ratio") in _ASPECT_DIMS:
                        aspect_ratio = detected_dna["aspect_ratio"]
                        target_w, target_h = _ASPECT_DIMS[aspect_ratio]
                    append_job_log(job_id, "Chaveamento automático ativado -> Motor Animação 2D Cartoon (cartoon_2d_studio.py)!")
                elif dna_style in ("netflix_doc", "documentary", "investigative_doc"):
                    engine_style = "netflix_doc"
                    if not opts.get("aspect_ratio") and detected_dna.get("aspect_ratio") in _ASPECT_DIMS:
                        aspect_ratio = detected_dna["aspect_ratio"]
                        target_w, target_h = _ASPECT_DIMS[aspect_ratio]
                    append_job_log(job_id, "Chaveamento automático ativado -> Motor Documentário Cinema Netflix (netflix_doc_studio.py)!")

        # =====================================================================
        # BRANCH A: 2D CARTOON ANIMATION STUDIO (Blueprint Exact-Duration Clone OR Fresh Episode)
        # =====================================================================
        if engine_style == "cartoon_2d":
            master_mp4 = job_dir / "master.mp4"
            studio_ar = "16:9" if aspect_ratio == "16:9" else "9:16"
            music_file, music_label = await _resolve_music_selection(
                music_opt=music_opt,
                music_volume=music_volume,
                use_flow_music=use_flow_music,
                preset=preset,
                default_filename="corporate_focus.mp3",
                topic=cartoon_tone,
                duration_s=float(target_duration_s or 35),
                work_dir=work_dir,
                thermal_limit_c=thermal_limit,
                allow_none=False,
                allow_mood_auto=False,
            )

            def _cb(pct: int, msg: str) -> None:
                append_job_log(job_id, msg, progress=pct, stage=msg[:60])

            if detected_dna and detected_dna.get("scenes"):
                append_job_log(
                    job_id,
                    f"Iniciando Clonagem Estrutural Exata ({detected_dna.get('duration_s')}s | {detected_dna.get('aspect_ratio')} | "
                    f"{len(detected_dna.get('scenes', []))} cenas | Header Bar: {detected_dna.get('has_header_bar')})...",
                    progress=16,
                    stage="Clonando Blueprint em Tempo Exato (Anti-Plágio)",
                )
                update_job(job_id, script_json=json.dumps({
                    "mode": "blueprint_exact_clone",
                    "source_url": source_url,
                    "source_duration_s": detected_dna.get("duration_s"),
                    "aspect_ratio": detected_dna.get("aspect_ratio"),
                    "scenes_count": len(detected_dna.get("scenes", [])),
                    "segments_count": len(detected_dna.get("segments", [])),
                }, ensure_ascii=False))
                render_info = await render_cloned_cartoon_from_blueprint(
                    blueprint=detected_dna,
                    topic=topic,
                    tone=cartoon_tone,
                    work_dir=work_dir,
                    out_master_mp4=master_mp4,
                    music_mp3=music_file,
                    fps=resolved_fps,
                    voice_engine=eff_voice_engine,
                    thermal_limit_c=thermal_limit,
                    progress_cb=_cb,
                )
                aspect_ratio = render_info["aspect_ratio"]
                target_w, target_h = _ASPECT_DIMS.get(aspect_ratio, (1080, 1920))
                ep_title = render_info.get("header_title") or topic
                plan = None
            else:
                append_job_log(
                    job_id,
                    f"Gerando episódio Cartoon 2D v2 ({aspect_ratio} @ {resolved_fps}fps | Voz: {eff_voice_engine}/{eff_voice_id} | Tom: {cartoon_tone})...",
                    progress=15,
                    stage="Roteirizando Diálogos Multi-Personagens",
                )
                eff_cartoon_topic = f"{topic} ({custom_directives[:120]})" if custom_directives else topic
                plan, llm_meta = await asyncio.to_thread(
                    generate_cartoon_episode_plan,
                    topic=eff_cartoon_topic,
                    tone=cartoon_tone,
                    aspect_ratio=studio_ar,
                    reference_transcript=reference_transcript,
                )
                # Apply user's voice engine, voice_id, rate, and pitch overrides cleanly to cast
                for c_idx, ch in enumerate(plan.characters):
                    if eff_voice_engine in ("edge", "kokoro", "gemini_tts"):
                        ch.voice_preset.engine = eff_voice_engine  # type: ignore[assignment]
                    ch.voice_preset.rate = voice_rate
                    if c_idx == 0:
                        if opts.get("voice_id"):
                            ch.voice_preset.voice_id = eff_voice_id
                            if eff_voice_engine == "kokoro" and eff_voice_id in KOKORO_VOICES:
                                ch.voice_preset.kokoro_voice = eff_voice_id
                        if opts.get("voice_pitch"):
                            ch.voice_preset.pitch = voice_pitch
                    elif opts.get("voice_pitch"):
                        # Keep 2nd character distinctly pitched relative to user choice
                        ch.voice_preset.pitch = "-10Hz" if not voice_pitch.startswith("-") else "+10Hz"

                # Respect short target_duration_s if explicitly requested (e.g. <= 18s -> 2 punchy scenes)
                if target_duration_s is not None and target_duration_s <= 18 and len(plan.scenes) > 2:
                    plan.scenes = plan.scenes[:2]

                update_job(
                    job_id,
                    script_json=plan.model_dump_json(),
                    tokens_used=int(llm_meta.get("tokens_used", 0)),
                    cost_usd=float(llm_meta.get("cost_usd", 0.0)),
                )
                append_job_log(
                    job_id,
                    f"Episódio '{plan.title}' criado: {len(plan.characters)} personagens, {len(plan.scenes)} cenas.",
                    progress=22,
                    stage="Sintetizando Vozes & Rhubarb Lip-Sync 9-Visemas",
                )
                render_info = await render_cartoon_episode(
                    plan=plan,
                    work_dir=work_dir,
                    out_master_mp4=master_mp4,
                    music_mp3=music_file,
                    fps=resolved_fps,
                    voice_engine=eff_voice_engine,
                    thermal_limit_c=thermal_limit,
                    progress_cb=_cb,
                )
                ep_title = plan.title

            # If user requested 4:5 or 1:1 on cartoon_2d, cleanly aspect-cover reframe master
            if aspect_ratio in ("4:5", "1:1"):
                reframed = work_dir / "cartoon_reframed.mp4"
                await asyncio.to_thread(_reframe_video_to_dims, master_mp4, reframed, target_w, target_h, thermal_limit)
                reframed.replace(master_mp4)
                vid_w, vid_h = target_w, target_h
            else:
                vid_w = int(render_info["width"])
                vid_h = int(render_info["height"])

            duration_s = float(render_info["duration_s"])
            master_audio = Path(render_info["master_audio"])
            words_a = render_info["words"]

            append_job_log(job_id, "Aplicando ShadowHash (3 mutações iPhone 16 Pro)...", progress=82, stage="Gerando Mutações ShadowHash")
            sh_variants = await asyncio.to_thread(generate_shadowhash_variants, master_mp4, job_dir)

            append_job_log(job_id, "Empacotando Central VIP (Prévia 540p, CapCut .zip, Kdenlive .otio, Capa HD)...", progress=90, stage="Exportando Pacote Comercial VIP")
            preview_mp4 = job_dir / "preview_540p.mp4"
            await asyncio.to_thread(export_whatsapp_preview_540p, master_mp4, preview_mp4, watermark_text, aspect_ratio)

            capcut_zip = job_dir / "capcut_project.zip"
            await asyncio.to_thread(
                export_capcut_zip,
                f"FrimeRise_2D_{job_id[:8]}",
                master_mp4,
                master_audio,
                music_file if music_label != "none" else None,
                words_a,
                duration_s,
                capcut_zip,
                vid_w,
                vid_h,
            )

            otio_path = job_dir / "timeline.otio"
            await asyncio.to_thread(
                export_kdenlive_otio,
                ep_title,
                master_mp4,
                master_audio,
                music_file if music_label != "none" else None,
                words_a,
                duration_s,
                otio_path,
            )

            frame_snap = work_dir / "cover_bg.png"
            try:
                await asyncio.to_thread(
                    run_ffmpeg_safe,
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(2.0, duration_s * 0.25):.2f}", "-i", str(master_mp4), "-frames:v", "1", str(frame_snap)],
                    thermal_limit_c=thermal_limit,
                )
            except Exception:
                frame_snap = Path("")

            cover_png = job_dir / "cover_9x16.png"
            await asyncio.to_thread(
                render_cover_9x16,
                ep_title,
                "",
                preset,
                cover_png,
                frame_snap if frame_snap.exists() else None,
            )

            ab_thumbs: Dict[str, Any] = {}
            if aspect_ratio == "16:9" or opts.get("generate_thumbnails_ab") or thumb_3words:
                append_job_log(job_id, "Gerando 3 Thumbnails Magnéticas 1280x720 (Skia C++ + rembg u2netp)...", progress=93, stage="Gerando 3 Thumbnails A/B 1280x720")
                raw_thumbs = await asyncio.to_thread(_call_generate_ab_thumbnails, master_mp4, ep_title, job_dir, thumb_3words)
                ab_thumbs = {
                    "thumb_a": _rel_output(Path(raw_thumbs["thumb_a"])),
                    "thumb_b": _rel_output(Path(raw_thumbs["thumb_b"])),
                    "thumb_c": _rel_output(Path(raw_thumbs["thumb_c"])),
                    "headline_words": raw_thumbs.get("headline_words", thumb_3words or ""),
                }

            dubbed_langs: Dict[str, Any] = {}
            if clone_languages and plan is not None:
                append_job_log(job_id, "🌎 Clonando Idiomas (Inglês US + Espanhol) com Re-Timing & Lip-Sync 2D...", progress=95, stage="Dublando EN-US + ES & Re-Timing Lip-Sync")
                dubbed_raw = await dub_video_job_multi_language(
                    job_dir=job_dir,
                    engine_style="cartoon_2d",
                    script_or_plan_dict=plan.model_dump(),
                    preset=preset,
                    languages=("en_us", "es"),
                    cartoon_fps=30,
                    thermal_limit_c=thermal_limit,
                    progress_cb=lambda m: append_job_log(job_id, m),
                )
                for lk, lv in dubbed_raw.items():
                    dubbed_langs[lk] = {**lv, "path": _rel_output(Path(lv["path"]))}

            (job_dir / "words.json").write_text(json.dumps(words_a, ensure_ascii=False), encoding="utf-8")
            quality_report = {
                "job_id": job_id,
                "engine_style": "cartoon_2d",
                "flow_mode": flow_mode,
                "cartoon_engine": render_info.get("cartoon_engine", "cartoon_studio_v2_line_boil_2.5d"),
                "clone_mode": "blueprint_exact_duration" if (detected_dna and detected_dna.get("scenes")) else "fresh_episode",
                "aspect_ratio": aspect_ratio,
                "resolution": f"{vid_w}x{vid_h}",
                "fps": int(render_info.get("fps", resolved_fps)),
                "voice_engine": render_info.get("voice_engine", eff_voice_engine),
                "has_header_bar": bool(render_info.get("has_header_bar", False)),
                "tone": cartoon_tone,
                "characters_count": render_info["characters_count"],
                "scenes_count": render_info["scenes_count"],
                "lipsync_visemes": 9,
                "lipsync_engine": render_info.get("lipsync_engine", "rhubarb_v1.14_phonetic_9visemes"),
                "chroma_key_filter": "active",
                "font_verified": render_info["font_verified"],
                "source_duration_s": detected_dna.get("duration_s") if detected_dna else None,
                "duration_s": round(duration_s, 2),
                "creative_config": _build_creative_config(music_label, aspect_ratio, int(render_info.get("fps", resolved_fps)), active_visual_libraries),
                "ab_thumbnails": ab_thumbs,
                "dubbed_languages": dubbed_langs,
                "shorts_cascade": [],
                "dna_detected": {k: v for k, v in (detected_dna or {}).items() if k not in ("scenes", "segments")},
            }
            (job_dir / "quality_report.json").write_text(json.dumps(quality_report, indent=2, ensure_ascii=False), encoding="utf-8")

            now_done = datetime.now().isoformat(timespec="seconds")
            update_job(
                job_id,
                status="completed",
                progress=100,
                stage="Animação 2D Concluída • Pronta para Entrega",
                master_path=_rel_output(master_mp4),
                hook_a_path=_rel_output(master_mp4),
                hook_b_path="",
                tiktok_path=_rel_output(Path(sh_variants["tiktok"]["path"])),
                reels_path=_rel_output(Path(sh_variants["reels"]["path"])),
                shorts_path=_rel_output(Path(sh_variants["shorts"]["path"])),
                preview_path=_rel_output(preview_mp4),
                capcut_zip_path=_rel_output(capcut_zip),
                otio_path=_rel_output(otio_path),
                cover_path=_rel_output(cover_png),
                duration_s=round(duration_s, 2),
                completed_at=now_done,
            )
            append_job_log(job_id, f"ANIMAÇÃO 2D FINALIZADA COM SUCESSO! ({duration_s:.1f}s | {vid_w}x{vid_h} | 9-Viseme Lip-Sync)", progress=100)
            return {"job_id": job_id, "status": "completed", "engine_style": "cartoon_2d", "master_path": str(master_mp4)}

        # =====================================================================
        # BRANCH B: NETFLIX / MAGNATESMEDIA CINEMA DOCUMENTARY STUDIO (16:9, 9:16, 4:5, 1:1)
        # =====================================================================
        if engine_style == "netflix_doc":
            if generate_netflix_doc_plan is None or render_netflix_documentary is None:
                raise RuntimeError("Módulo engine/netflix_doc_studio.py não disponível.")

            doc_lang = language
            doc_target_minutes = (
                max(0.25, round(float(target_duration_s) / 60.0, 3))
                if target_duration_s is not None
                else target_minutes
            )
            studio_ar = "9:16" if aspect_ratio in ("9:16", "4:5", "1:1") else "16:9"
            master_mp4 = job_dir / "master.mp4"
            music_file, music_label = await _resolve_music_selection(
                music_opt=music_opt,
                music_volume=music_volume,
                use_flow_music=use_flow_music,
                preset=preset,
                default_filename="epic_doc.mp3",
                topic=topic,
                duration_s=max(30.0, doc_target_minutes * 60.0),
                work_dir=work_dir,
                thermal_limit_c=thermal_limit,
                allow_none=False,
                allow_mood_auto=True,
            )

            def _doc_cb(pct: int, msg: str) -> None:
                append_job_log(job_id, msg, progress=pct, stage=msg[:60])

            is_resume = bool(opts.get("_resume", False))
            doc_plan: Optional[Dict[str, Any]] = None
            if is_resume:
                try:
                    existing_job = get_job(job_id) or {}
                    saved_raw = existing_job.get("script_json") or ""
                    if saved_raw:
                        parsed_plan = json.loads(saved_raw)
                        if isinstance(parsed_plan, dict) and isinstance(parsed_plan.get("scenes"), list) and parsed_plan["scenes"]:
                            doc_plan = parsed_plan
                            append_job_log(
                                job_id,
                                f"♻️ Retomando Documentário Cinema '{doc_plan.get('title', topic)}' com o mesmo roteiro ({len(doc_plan['scenes'])} cenas) e reaproveitando cenas já renderizadas...",
                                progress=22,
                                stage="Retomando Cenas Investigativas Skia C++",
                            )
                except Exception:
                    doc_plan = None

            if doc_plan is None:
                append_job_log(
                    job_id,
                    f"Gerando roteiro documental investigativo ({aspect_ratio} | Alvo: {doc_target_minutes:.2f}min | Idioma: {doc_lang} | LUT: {lut_file})...",
                    progress=14,
                    stage="Estruturando Cold Open & Capítulos Netflix Doc",
                )
                eff_doc_topic = f"{topic} — {custom_directives[:140]}" if custom_directives else topic
                maybe_plan = generate_netflix_doc_plan(
                    topic=eff_doc_topic,
                    aspect_ratio=studio_ar,
                    target_minutes=doc_target_minutes,
                    lang=doc_lang,
                )
                if inspect.isawaitable(maybe_plan):
                    doc_plan = await maybe_plan
                else:
                    doc_plan = maybe_plan

                if not isinstance(doc_plan, dict):
                    doc_plan = doc_plan.model_dump() if hasattr(doc_plan, "model_dump") else dict(doc_plan)

                # Enforce user LUT, voice, caption style, directives & visual library mix on documentary plan
                doc_plan["lut_file"] = lut_file
                if eff_voice_id:
                    doc_plan["voice_id"] = eff_voice_id
                doc_plan["caption_style"] = caption_style
                if custom_directives:
                    doc_plan["custom_directives"] = custom_directives

                if explicit_libs and isinstance(doc_plan.get("scenes"), list):
                    allow_pip = "video_over_video" in explicit_libs
                    allow_25d = "photos_25d" in explicit_libs
                    allow_skia = "skia_graphics" in explicit_libs
                    for sc_d in doc_plan["scenes"]:
                        vm = str(sc_d.get("visual_mode") or "")
                        if not allow_pip and vm in ("broll_video_pip", "video_pip_evidence"):
                            sc_d["visual_mode"] = "parallax_25d_photo" if allow_25d else "newspaper_highlighter"
                        elif not allow_25d and vm == "parallax_25d_photo":
                            sc_d["visual_mode"] = "broll_video_pip" if allow_pip else "sliding_timeline"
                        elif not allow_skia and vm in ("newspaper_highlighter", "dark_map_route", "red_string_board", "sliding_timeline"):
                            sc_d["visual_mode"] = "broll_video_pip" if allow_pip else "parallax_25d_photo"

                if audit_netflix_doc_plan is not None:
                    try:
                        doc_plan = audit_netflix_doc_plan(doc_plan)
                    except Exception:
                        pass

                update_job(
                    job_id,
                    script_json=json.dumps(doc_plan, ensure_ascii=False),
                    tokens_used=int(doc_plan.get("tokens_used", 0)),
                    cost_usd=float(doc_plan.get("cost_usd", 0.0)),
                )

                append_job_log(
                    job_id,
                    f"Renderizando Documentário Cinema '{doc_plan.get('title', topic)}' em Skia C++ ({resolved_fps}fps | Legenda: {caption_style})...",
                    progress=22,
                    stage="Renderizando Cenas Investigativas Skia C++",
                )
            doc_render_kwargs: Dict[str, Any] = {
                "plan": doc_plan,
                "work_dir": work_dir,
                "out_master_mp4": master_mp4,
                "music_mp3": music_file,
                "fps": resolved_fps,
                "thermal_limit_c": thermal_limit,
                "progress_cb": _doc_cb,
            }
            doc_sig = inspect.signature(render_netflix_documentary)
            if "caption_style" in doc_sig.parameters:
                doc_render_kwargs["caption_style"] = caption_style
            if "music_volume" in doc_sig.parameters:
                doc_render_kwargs["music_volume"] = music_volume
            if "voice_rate" in doc_sig.parameters:
                doc_render_kwargs["voice_rate"] = voice_rate
            if "voice_pitch" in doc_sig.parameters:
                doc_render_kwargs["voice_pitch"] = voice_pitch
            if "resume" in doc_sig.parameters:
                doc_render_kwargs["resume"] = is_resume
            if "voice_engine" in doc_sig.parameters:
                doc_render_kwargs["voice_engine"] = eff_voice_engine
            if "cut_cadence_s" in doc_sig.parameters:
                doc_render_kwargs["cut_cadence_s"] = cut_cadence_s

            render_info = await render_netflix_documentary(**doc_render_kwargs)

            if aspect_ratio in ("4:5", "1:1"):
                reframed = work_dir / "doc_reframed.mp4"
                await asyncio.to_thread(_reframe_video_to_dims, master_mp4, reframed, target_w, target_h, thermal_limit)
                reframed.replace(master_mp4)
                vid_w, vid_h = target_w, target_h
            else:
                vid_w = int(render_info.get("width", target_w))
                vid_h = int(render_info.get("height", target_h))

            duration_s = float(render_info.get("duration_s", 25.0))
            master_audio = Path(render_info.get("master_audio") or (work_dir / "master_audio.m4a"))
            words_a = render_info.get("words", [])
            doc_title = str(doc_plan.get("title") or topic)

            append_job_log(job_id, "Aplicando ShadowHash (3 mutações iPhone 16 Pro)...", progress=82, stage="Gerando Mutações ShadowHash")
            sh_variants = await asyncio.to_thread(generate_shadowhash_variants, master_mp4, job_dir)

            append_job_log(job_id, "Empacotando Central VIP (Prévia 540p, CapCut .zip, Kdenlive .otio, Capa HD)...", progress=88, stage="Exportando Pacote Comercial VIP")
            preview_mp4 = job_dir / "preview_540p.mp4"
            await asyncio.to_thread(export_whatsapp_preview_540p, master_mp4, preview_mp4, watermark_text, aspect_ratio)

            capcut_zip = job_dir / "capcut_project.zip"
            if master_audio.exists():
                await asyncio.to_thread(
                    export_capcut_zip,
                    f"FrimeRise_Doc_{job_id[:8]}",
                    master_mp4,
                    master_audio,
                    music_file if music_label != "none" else None,
                    words_a,
                    duration_s,
                    capcut_zip,
                    vid_w,
                    vid_h,
                )
            otio_path = job_dir / "timeline.otio"
            if master_audio.exists():
                await asyncio.to_thread(
                    export_kdenlive_otio,
                    doc_title,
                    master_mp4,
                    master_audio,
                    music_file if music_label != "none" else None,
                    words_a,
                    duration_s,
                    otio_path,
                )

            frame_snap = work_dir / "cover_bg.png"
            try:
                await asyncio.to_thread(
                    run_ffmpeg_safe,
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(2.5, duration_s * 0.25):.2f}", "-i", str(master_mp4), "-frames:v", "1", str(frame_snap)],
                    thermal_limit_c=thermal_limit,
                )
            except Exception:
                frame_snap = Path("")

            cover_png = job_dir / "cover_9x16.png"
            await asyncio.to_thread(
                render_cover_9x16,
                doc_title,
                "",
                preset,
                cover_png,
                frame_snap if frame_snap.exists() else None,
            )

            # 3 Magnetic 1280x720 A/B/C Thumbnails with custom 3-word hook
            append_job_log(
                job_id,
                f"Gerando 3 Thumbnails Magnéticas 1280x720 (Texto 3-palavras: '{thumb_3words or doc_title[:22]}')...",
                progress=92,
                stage="Gerando 3 Thumbnails A/B 1280x720",
            )
            raw_thumbs = await asyncio.to_thread(_call_generate_ab_thumbnails, master_mp4, doc_title, job_dir, thumb_3words)
            ab_thumbs_doc = {
                "thumb_a": _rel_output(Path(raw_thumbs["thumb_a"])),
                "thumb_b": _rel_output(Path(raw_thumbs["thumb_b"])),
                "thumb_c": _rel_output(Path(raw_thumbs["thumb_c"])),
                "headline_words": raw_thumbs.get("headline_words", thumb_3words or ""),
            }

            # Cascade 16:9 -> 5 Vertical Shorts 9:16 (Zero Tokens)
            shorts_cascade: List[Dict[str, Any]] = []
            if auto_shorts_cascade and aspect_ratio == "16:9":
                append_job_log(job_id, "⚡ Extraindo Cascata de 5 Shorts Virais 9:16 (Zero Tokens)...", progress=95, stage="Extraindo 5 Cortes Virais 9:16")
                try:
                    raw_shorts = await asyncio.to_thread(extract_5_viral_shorts_from_16x9, master_mp4, words_a, job_dir, 5)
                    for s in raw_shorts:
                        s["url"] = "/" + _rel_output(Path(s["path"]))
                    shorts_cascade = raw_shorts
                except Exception as exc:
                    append_job_log(job_id, f"Aviso na cascata 9:16: {exc}")

            dubbed_langs_doc: Dict[str, Any] = {}
            if clone_languages:
                append_job_log(job_id, "🌎 Clonando Idiomas (Inglês US + Espanhol) com Re-Timing Documental...", progress=97, stage="Dublando EN-US + ES")
                try:
                    dubbed_raw = await dub_video_job_multi_language(
                        job_dir=job_dir,
                        engine_style="netflix_doc",
                        script_or_plan_dict=doc_plan,
                        preset=preset,
                        languages=("en_us", "es") if doc_lang == "pt_br" else ("pt_br", "es"),
                        thermal_limit_c=thermal_limit,
                        progress_cb=lambda m: append_job_log(job_id, m),
                    )
                    for lk, lv in dubbed_raw.items():
                        dubbed_langs_doc[lk] = {**lv, "path": _rel_output(Path(lv["path"]))}
                except Exception as exc:
                    append_job_log(job_id, f"Aviso na dublagem documental: {exc}")

            # Optional automatic Google Drive backup into named project folder (saves local disk space!)
            gdrive_backup: Dict[str, Any] = {"status": "skipped"}
            if settings.get("gdrive_auto_upload", "1") == "1":
                append_job_log(job_id, "☁️ Verificando backup automático em pasta nomeada no Google Drive...", progress=98, stage="Sincronizando Google Drive")
                gdrive_backup = await asyncio.to_thread(upload_job_to_gdrive, job_dir, doc_title, job_id)
                if gdrive_backup.get("status") == "uploaded":
                    append_job_log(
                        job_id,
                        f"☁️ Backup salvo no Google Drive: {gdrive_backup.get('remote_path')} ({gdrive_backup.get('files_uploaded')} arquivos, {gdrive_backup.get('total_mb')} MB)"
                        + (f" | Liberados {gdrive_backup.get('freed_mb')} MB no SSD!" if gdrive_backup.get("pruned_local") else ""),
                    )

            (job_dir / "words.json").write_text(json.dumps(words_a, ensure_ascii=False), encoding="utf-8")
            quality_report = {
                "job_id": job_id,
                "engine_style": "netflix_doc",
                "flow_mode": flow_mode,
                "doc_lang": doc_lang,
                "thumb_3words": thumb_3words,
                "aspect_ratio": aspect_ratio,
                "resolution": f"{vid_w}x{vid_h}",
                "fps": int(render_info.get("fps", resolved_fps)),
                "lut_file": lut_file,
                "chroma_key_filter": "active",
                "retention_audit": doc_plan.get("retention_audit", {}),
                "creative_config": _build_creative_config(music_label, aspect_ratio, int(render_info.get("fps", resolved_fps)), active_visual_libraries),
                "visual_modes_used": render_info.get("visual_modes_used", []),
                "ab_thumbnails": ab_thumbs_doc,
                "shorts_cascade": shorts_cascade,
                "dubbed_languages": dubbed_langs_doc,
                "gdrive_backup": gdrive_backup,
                "scenes_count": render_info.get("scenes_count", len(doc_plan.get("scenes", []))),
                "duration_s": round(duration_s, 2),
            }
            (job_dir / "quality_report.json").write_text(json.dumps(quality_report, indent=2, ensure_ascii=False), encoding="utf-8")

            now_done = datetime.now().isoformat(timespec="seconds")
            done_stage = (
                f"Documentário Cinema Concluído • 3 Thumbs + {len(shorts_cascade)} Shorts Prontos"
                if shorts_cascade
                else "Documentário Cinema Concluído • 3 Thumbs A/B Prontas"
            )
            update_job(
                job_id,
                status="completed",
                progress=100,
                stage=done_stage,
                master_path=_rel_output(master_mp4) if master_mp4.exists() else _rel_output(preview_mp4),
                hook_a_path=_rel_output(master_mp4) if master_mp4.exists() else _rel_output(preview_mp4),
                hook_b_path="",
                tiktok_path=_rel_output(Path(sh_variants["tiktok"]["path"])) if Path(sh_variants["tiktok"]["path"]).exists() else "",
                reels_path=_rel_output(Path(sh_variants["reels"]["path"])) if Path(sh_variants["reels"]["path"]).exists() else "",
                shorts_path=_rel_output(Path(sh_variants["shorts"]["path"])) if Path(sh_variants["shorts"]["path"]).exists() else "",
                preview_path=_rel_output(preview_mp4),
                capcut_zip_path=_rel_output(capcut_zip) if capcut_zip.exists() else "",
                otio_path=_rel_output(otio_path) if otio_path.exists() else "",
                cover_path=_rel_output(cover_png),
                duration_s=round(duration_s, 2),
                completed_at=now_done,
            )
            append_job_log(
                job_id,
                f"DOCUMENTÁRIO CINEMA FINALIZADO COM SUCESSO! ({duration_s:.1f}s | {vid_w}x{vid_h} @ {int(render_info.get('fps', resolved_fps))}fps | 3 Thumbs A/B"
                + (f" + {len(shorts_cascade)} Shorts)" if shorts_cascade else ")"),
                progress=100,
            )
            return {"job_id": job_id, "status": "completed", "engine_style": "netflix_doc", "master_path": str(master_mp4)}

        # =====================================================================
        # BRANCH C: CINEMATIC VIRAL / HYBRID VISUAL LIBRARY MIXER (cinematic_broll)
        # =====================================================================
        script_target_s = target_duration_s if target_duration_s is not None else 30
        if custom_script:
            script = custom_script
        else:
            script = await asyncio.to_thread(
                generate_viral_script,
                topic=topic,
                skill_id=skill_id,
                niche=client.get("niche", "Negócios & IA"),
                seamless_loop=seamless_loop,
                reference_transcript=reference_transcript,
                target_duration_s=script_target_s,
                language=language,
                custom_directives=custom_directives,
            )

        update_job(
            job_id,
            script_json=json.dumps(script, ensure_ascii=False),
            tokens_used=int(script.get("tokens_used", 0)),
            cost_usd=float(script.get("cost_usd", 0.0)),
        )
        append_job_log(
            job_id,
            f"Roteiro gerado via {script.get('provider_used', 'local')} | Idioma: {language} | Alvo: {script_target_s}s "
            f"({script.get('tokens_used', 0)} tokens | ${script.get('cost_usd', 0.0):.5f})",
            progress=16,
            stage="Sintetizando Áudio Broadcast",
        )

        # 2. Narration (Hook A + Body + Complete Closing) + VAD Trim with FULL Voice Overrides
        hook_a_text = str(script.get("hook_a", topic)).strip()
        hook_b_text = str(script.get("hook_b", hook_a_text)).strip()
        body_lines = [str(x).strip() for x in script.get("body_lines", []) if str(x).strip()]
        closing_line = str(script.get("closing_line") or script.get("loop_bridge") or "").strip()
        if closing_line.endswith("..."):
            closing_line = closing_line.rstrip(".") + (
                " and transform your results today."
                if language == "en_us"
                else (" y transforma tus resultados hoy." if language == "es" else " e transforme seus resultados hoje.")
            )
        full_text_a = " ".join([hook_a_text, *body_lines, closing_line]).strip()

        narr_wav, words_a, speech_dur = await generate_narration(
            text=full_text_a,
            work_dir=work_dir,
            voice_engine=eff_voice_engine,
            voice_id=eff_voice_id,
            voice_blend=eff_voice_blend,
            prefix="narr_a",
            rate=voice_rate,
            pitch=voice_pitch,
            thermal_limit_c=thermal_limit,
            language=language,
        )
        duration_s = round(speech_dur + 0.40, 3)

        hook_word_count = max(3, len(hook_a_text.split()))
        if len(words_a) > hook_word_count:
            hook_split_s = float(words_a[hook_word_count - 1]["end"]) + 0.05
        else:
            hook_split_s = min(3.5, duration_s * 0.25)
        hook_split_s = max(2.0, min(duration_s * 0.40, hook_split_s))

        append_job_log(
            job_id,
            f"Narração concluída ({eff_voice_engine}/{eff_voice_id} | {voice_rate}, {voice_pitch} | "
            f"{speech_dur:.2f}s voz + 0.40s cauda = {duration_s:.2f}s | {len(words_a)} palavras)",
            progress=28,
            stage=f"Mixando Bibliotecas Visuais (Corte a cada ~{cut_cadence_s:.1f}s)",
        )

        # 3. Real Hybrid Visual Library Mixer (real_broll + photos_25d + bespoke_ai + cartoon_2d_layer + video_over_video)
        queries = script.get("broll_queries") or [
            "city night aerial drone",
            "modern office laptop work",
            "financial growth chart business",
            "neon street night timelapse",
            "entrepreneur smartphone coffee",
            "luxury architecture sunset",
        ]
        xfade_dur = 0.30
        n_scenes = max(3, min(60, int(round(duration_s / cut_cadence_s))))
        scene_dur = max(1.6, (duration_s + xfade_dur * (n_scenes - 1)) / float(n_scenes))

        # Build ordered scene-source mix from active_visual_libraries
        scene_source_libs: List[str] = [
            lib for lib in ("real_broll", "photos_25d", "bespoke_ai", "cartoon_2d_layer")
            if lib in active_visual_libraries
        ]
        if not scene_source_libs:
            scene_source_libs = ["real_broll"]
        want_pip_overlay = "video_over_video" in active_visual_libraries

        # Ensure n_scenes is at least len(scene_source_libs) so EVERY chosen library appears in the final video!
        if n_scenes < len(scene_source_libs):
            n_scenes = len(scene_source_libs)
            scene_dur = max(1.5, (duration_s + xfade_dur * (n_scenes - 1)) / float(n_scenes))

        pixabay_key = settings.get("pixabay_api_key", "")
        pexels_key = settings.get("pexels_api_key", "")
        used_hashes: Set[str] = set()
        used_photo_urls: Set[str] = set()

        quality_clips: List[Dict[str, Any]] = []
        styled_scenes: List[Path] = []
        scene_durations: List[float] = []
        library_usage_counts: Dict[str, int] = {}
        bespoke_ar = "16:9" if aspect_ratio == "16:9" else "9:16"
        use_google_flow_flag = flow_mode in ("gancho_de_ouro", "cinema_full_veo")

        pip_applied_count = 0

        for idx in range(n_scenes):
            q = queries[idx % len(queries)]
            chosen_lib = scene_source_libs[idx % len(scene_source_libs)]
            scene_out = work_dir / f"scene_{idx:02d}.mp4"
            actual_lib = chosen_lib
            clip_label = ""
            q_info: Dict[str, Any] = {
                "passed": True,
                "blur_score": 120.0,
                "chroma_key_filter": "active",
                "chroma_key_detected": False,
                "green_pixel_ratio": 0.0,
                "reason": "ok",
            }

            # --- Library 1: Real Archival/Editorial Photo + u2netp 2.5D Parallax ---
            if chosen_lib == "photos_25d" and fetch_doc_real_photo is not None and render_25d_parallax_clip is not None:
                try:
                    photo_p = await asyncio.to_thread(
                        fetch_doc_real_photo,
                        q,
                        work_dir,
                        f"mix_photo_{idx:02d}",
                        640,
                        used_photo_urls,
                    )
                    if photo_p is not None and Path(photo_p).exists():
                        raw_25d = work_dir / f"raw_25d_{idx:02d}.mp4"
                        cam_motions = ("zoom_in", "pan", "punch_in", "zoom_out")
                        await asyncio.to_thread(
                            render_25d_parallax_clip,
                            photo_p,
                            raw_25d,
                            scene_dur,
                            bespoke_ar,
                            cam_motions[idx % len(cam_motions)],
                            resolved_fps,
                            idx,
                            thermal_limit,
                        )
                        await asyncio.to_thread(
                            _style_scene_clip_ffmpeg,
                            raw_25d,
                            scene_out,
                            scene_dur,
                            lut_file,
                            idx,
                            target_w,
                            target_h,
                            resolved_fps,
                            enable_cinema_fx,
                            False,
                            thermal_limit,
                        )
                        clip_label = Path(photo_p).name
                        actual_lib = "photos_25d"
                    else:
                        chosen_lib = "real_broll"
                except Exception as exc:
                    append_job_log(job_id, f"Aviso photos_25d cena {idx + 1} (fallback real_broll): {exc}")
                    chosen_lib = "real_broll"

            # --- Library 2: Bespoke Anti-Stock AI Artwork (Pollinations Flux / Google Flow Pro) + 2.5D ---
            if chosen_lib == "bespoke_ai" and render_bespoke_scene_clip is not None:
                try:
                    raw_ai = work_dir / f"raw_bespoke_{idx:02d}.mp4"
                    # Keep full-bleed parallax_25d when captions are enabled so zero editorial text clashes with subtitles
                    ai_style = "mixed_media" if (caption_style == "none" and idx % 2 == 1) else "parallax_25d"
                    cam_motions = ("punch_in", "zoom_in", "pan", "zoom_out")
                    await asyncio.to_thread(
                        render_bespoke_scene_clip,
                        q,
                        raw_ai,
                        scene_dur,
                        bespoke_ar,
                        ai_style,
                        idx,
                        cam_motions[idx % len(cam_motions)],
                        str(script.get("title", topic))[:36],
                        "",
                        None,
                        use_google_flow_flag and (idx == 0 or flow_mode == "cinema_full_veo"),
                        flow_mode,
                        resolved_fps,
                        thermal_limit,
                    )
                    await asyncio.to_thread(
                        _style_scene_clip_ffmpeg,
                        raw_ai,
                        scene_out,
                        scene_dur,
                        lut_file,
                        idx,
                        target_w,
                        target_h,
                        resolved_fps,
                        enable_cinema_fx,
                        False,
                        thermal_limit,
                    )
                    clip_label = f"bespoke_ai_{ai_style}_{idx:02d}.mp4"
                    actual_lib = "bespoke_ai"
                except Exception as exc:
                    append_job_log(job_id, f"Aviso bespoke_ai cena {idx + 1} (fallback real_broll): {exc}")
                    chosen_lib = "real_broll"

            # --- Library 3: 2D Cartoon Cutaway Layer (Skia C++ v2 Puppets) ---
            if chosen_lib == "cartoon_2d_layer":
                try:
                    raw_c2d = work_dir / f"raw_cartoon_{idx:02d}.mp4"
                    await asyncio.to_thread(
                        _render_cartoon_cutaway_scene,
                        raw_c2d,
                        scene_dur,
                        target_w,
                        target_h,
                        resolved_fps,
                        idx,
                        thermal_limit,
                    )
                    await asyncio.to_thread(
                        _style_scene_clip_ffmpeg,
                        raw_c2d,
                        scene_out,
                        scene_dur,
                        lut_file,
                        idx,
                        target_w,
                        target_h,
                        resolved_fps,
                        enable_cinema_fx,
                        False,
                        thermal_limit,
                    )
                    clip_label = f"cartoon_2d_cutaway_{idx:02d}.mp4"
                    actual_lib = "cartoon_2d_layer"
                except Exception as exc:
                    append_job_log(job_id, f"Aviso cartoon_2d_layer cena {idx + 1} (fallback real_broll): {exc}")
                    chosen_lib = "real_broll"

            # --- Library 4 (Default / Real B-Roll): Pixabay + Pexels + yt-dlp + Wikimedia + Archive ---
            if chosen_lib == "real_broll" or not scene_out.exists():
                raw_clip = await asyncio.to_thread(
                    fetch_unique_real_clip,
                    q,
                    pixabay_key,
                    pexels_key,
                    used_hashes,
                    idx,
                )
                q_info = await asyncio.to_thread(evaluate_clip_quality, raw_clip, 20.0)
                await asyncio.to_thread(
                    _style_scene_clip_ffmpeg,
                    raw_clip,
                    scene_out,
                    scene_dur,
                    lut_file,
                    idx,
                    target_w,
                    target_h,
                    resolved_fps,
                    enable_cinema_fx,
                    True,
                    thermal_limit,
                )
                clip_label = raw_clip.name
                actual_lib = "real_broll"

            # --- Optional Enhancer: Video-over-Video (PiP Forensic Monitor Inset) ---
            pip_applied = False
            if want_pip_overlay and (idx == 0 or (idx % 2 == 0 and pip_applied_count < 2)):
                try:
                    pip_q = queries[(idx + 2) % len(queries)]
                    pip_raw = await asyncio.to_thread(
                        fetch_unique_real_clip,
                        pip_q,
                        pixabay_key,
                        pexels_key,
                        used_hashes,
                        n_scenes + idx + 5,
                    )
                    pip_out = work_dir / f"scene_{idx:02d}_pip.mp4"
                    await asyncio.to_thread(
                        _apply_pip_video_overlay,
                        scene_out,
                        pip_raw,
                        pip_out,
                        scene_dur,
                        target_w,
                        target_h,
                        resolved_fps,
                        thermal_limit,
                    )
                    pip_out.replace(scene_out)
                    pip_applied = True
                    pip_applied_count += 1
                    library_usage_counts["video_over_video"] = library_usage_counts.get("video_over_video", 0) + 1
                except Exception as exc:
                    append_job_log(job_id, f"Aviso video_over_video PiP cena {idx + 1}: {exc}")

            library_usage_counts[actual_lib] = library_usage_counts.get(actual_lib, 0) + 1
            if enable_cinema_fx:
                library_usage_counts["cinema_35mm_sfx"] = library_usage_counts.get("cinema_35mm_sfx", 0) + 1

            quality_clips.append({
                "scene": idx + 1,
                "library": actual_lib,
                "pip_overlay": pip_applied,
                "clip": clip_label,
                **q_info,
            })
            styled_scenes.append(scene_out)
            scene_durations.append(scene_dur)
            pct = 28 + int(24 * ((idx + 1) / float(n_scenes)))
            append_job_log(
                job_id,
                f"Cena {idx + 1}/{n_scenes} [{actual_lib}{'+PiP' if pip_applied else ''}] ({scene_dur:.1f}s): {clip_label} | blur={q_info['blur_score']} | green={q_info['green_pixel_ratio']:.1%}",
                progress=pct,
            )

        bg_assembled = work_dir / "bg_assembled.mp4"
        bg_assembled, transition_times = await asyncio.to_thread(
            _assemble_mixed_scenes_with_xfade,
            styled_scenes,
            scene_durations,
            bg_assembled,
            target_w,
            target_h,
            resolved_fps,
            xfade_dur,
            thermal_limit,
        )
        append_job_log(
            job_id,
            f"{n_scenes} cenas híbridas montadas (~{scene_dur:.1f}s/cena | {target_w}x{target_h}@{resolved_fps}fps) com LUT '{lut_file}' + xfade (CPU: {read_cpu_temperature_c()}°C)",
            progress=55,
            stage="Masterizando Áudio Broadcast (-14 LUFS + Cauda 0.4s)",
        )

        # 4. Broadcast FM Audio Mastering + 0.40s Tail + Custom Music/Volume + Timed SFX
        music_file, music_label = await _resolve_music_selection(
            music_opt=music_opt,
            music_volume=music_volume,
            use_flow_music=use_flow_music,
            preset=preset,
            default_filename="dark_pulse.mp3",
            topic=topic,
            duration_s=duration_s,
            work_dir=work_dir,
            thermal_limit_c=thermal_limit,
            allow_none=True,
            allow_mood_auto=(str(music_opt or "").strip().lower() in ("", "auto")),
        )
        sfx_dir = ASSETS_DIR / "sfx"
        motion_cards = _schedule_motion_cards(script.get("motion_cards", []), duration_s) if use_motion_cards else []
        if use_motion_cards and motion_cards:
            library_usage_counts["skia_graphics"] = len(motion_cards)

        sfx_events: List[Tuple[Path, float, float]] = []
        if enable_cinema_fx:
            sfx_events.append((sfx_dir / "cinematic_hit.wav", 0.05, 0.34))
            for t_i, tt in enumerate(transition_times):
                tr_sfx = "whoosh_deep.wav" if (t_i % 2 == 1 and (sfx_dir / "whoosh_deep.wav").exists()) else "whoosh_fast.wav"
                sfx_events.append((sfx_dir / tr_sfx, max(0.0, tt - 0.10), 0.36))
            for mc in motion_cards:
                sfx_name = "cash_chime.wav" if mc.get("type") == "counter" else "pop_bubble.wav"
                sfx_events.append((sfx_dir / sfx_name, float(mc["start"]), 0.32))

        master_audio = work_dir / "master_broadcast.m4a"
        master_audio, duration_s = await asyncio.to_thread(
            master_broadcast_audio,
            narr_wav,
            music_file,
            sfx_events,
            master_audio,
            speech_dur,
            music_volume,
            0.40,
            thermal_limit,
        )
        append_job_log(
            job_id,
            f"Áudio Broadcast concluído ({duration_s:.2f}s | Trilha: {music_label} @ {int(round(music_volume * 100))}%).",
            progress=62,
            stage=f"Renderizando Legendas ({caption_style}) & Cards Skia C++",
        )

        # 5. C++ Skia Compositor (Kinetic Captions + Skia Motion Cards, ANY Aspect Ratio & FPS)
        compositor = SkiaMotionCompositor(preset=preset, width=target_w, height=target_h)
        append_job_log(job_id, f"Tipografia Skia C++ validada: {compositor.font_info} | Estilo legenda: {caption_style}")

        master_mp4 = job_dir / "master.mp4"
        await asyncio.to_thread(
            _composite_with_style,
            compositor,
            bg_assembled,
            master_audio,
            master_mp4,
            duration_s,
            words_a,
            motion_cards,
            resolved_fps,
            use_motion_cards,
            caption_style,
            aspect_ratio,
            thermal_limit,
        )

        hook_a_mp4 = master_mp4
        hook_b_mp4 = Path("")

        # 6. Dual-Hook A/B Export (Real Footage for Hook B, ZERO debug card text!)
        if dual_hook_ab and hook_b_text and hook_b_text != hook_a_text:
            append_job_log(
                job_id,
                "Gerando Versão B (abertura alternativa com filmagem real + concat -c copy)...",
                progress=72,
                stage="Gerando Versão B (Dual-Hook A/B)",
            )
            narr_b_wav, words_b, speech_b = await generate_narration(
                text=hook_b_text,
                work_dir=work_dir,
                voice_engine=eff_voice_engine,
                voice_id=eff_voice_id,
                voice_blend=eff_voice_blend,
                prefix="narr_b",
                rate=voice_rate,
                pitch=voice_pitch,
                thermal_limit_c=thermal_limit,
                language=language,
            )
            audio_b = work_dir / "hook_b_audio.m4a"
            b_sfx = [(sfx_dir / "sub_boom.wav", 0.04, 0.36)] if enable_cinema_fx else []
            audio_b, dur_b = await asyncio.to_thread(
                master_broadcast_audio,
                narr_b_wav,
                music_file,
                b_sfx,
                audio_b,
                speech_b,
                music_volume,
                0.12,
                thermal_limit,
            )
            raw_b = await asyncio.to_thread(
                fetch_unique_real_clip,
                queries[-1],
                pixabay_key,
                pexels_key,
                used_hashes,
                n_scenes + 1,
            )
            bg_b_styled = work_dir / "bg_hook_b_styled.mp4"
            await asyncio.to_thread(
                _style_scene_clip_ffmpeg,
                raw_b,
                bg_b_styled,
                dur_b,
                lut_file,
                n_scenes + 1,
                target_w,
                target_h,
                resolved_fps,
                enable_cinema_fx,
                True,
                thermal_limit,
            )

            hook_b_intro = work_dir / "hook_b_intro.mp4"
            await asyncio.to_thread(
                _composite_with_style,
                compositor,
                bg_b_styled,
                audio_b,
                hook_b_intro,
                dur_b,
                words_b,
                [],
                resolved_fps,
                False,
                caption_style,
                aspect_ratio,
                thermal_limit,
            )
            hook_b_mp4 = job_dir / "master_hook_b.mp4"
            await asyncio.to_thread(splice_dual_hook_b, master_mp4, hook_b_intro, hook_split_s, hook_b_mp4)

        # 7. Anti-Shadowban ShadowHash 3 Mutations
        append_job_log(
            job_id,
            "Aplicando Polimorfismo Binário ShadowHash (iPhone 16 Pro atoms, zero Lavf, 3 hashes exclusivos)...",
            progress=82,
            stage="Gerando Mutações ShadowHash",
        )
        sh_variants = await asyncio.to_thread(generate_shadowhash_variants, master_mp4, job_dir)

        # 8. 540p WhatsApp Preview (ONLY place with watermark!) + CapCut ZIP + Kdenlive OTIO + Clean Cover
        append_job_log(
            job_id,
            "Empacotando Central VIP: Prévia 540p WhatsApp (com marca d'água), CapCut .zip, Kdenlive .otio e Capa HD...",
            progress=92,
            stage="Exportando Pacote Comercial VIP",
        )
        preview_mp4 = job_dir / "preview_540p.mp4"
        await asyncio.to_thread(export_whatsapp_preview_540p, master_mp4, preview_mp4, watermark_text, aspect_ratio)

        capcut_zip = job_dir / "capcut_project.zip"
        await asyncio.to_thread(
            export_capcut_zip,
            f"FrimeRise_{job_id[:8]}",
            master_mp4,
            master_audio,
            music_file,
            words_a,
            duration_s,
            capcut_zip,
            target_w,
            target_h,
        )

        otio_path = job_dir / "timeline.otio"
        await asyncio.to_thread(
            export_kdenlive_otio,
            script.get("title", topic),
            master_mp4,
            master_audio,
            music_file,
            words_a,
            duration_s,
            otio_path,
        )

        frame_snap = work_dir / "cover_bg.png"
        try:
            await asyncio.to_thread(
                run_ffmpeg_safe,
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.5, duration_s * 0.2):.2f}", "-i", str(bg_assembled), "-frames:v", "1", str(frame_snap)],
                thermal_limit_c=thermal_limit,
            )
        except Exception:
            frame_snap = Path("")

        cover_png = job_dir / "cover_9x16.png"
        await asyncio.to_thread(
            render_cover_9x16,
            str(script.get("title", topic)),
            "",
            preset,
            cover_png,
            frame_snap if frame_snap.exists() else None,
        )

        ab_thumbs_live: Dict[str, Any] = {}
        if aspect_ratio == "16:9" or opts.get("generate_thumbnails_ab") or thumb_3words:
            append_job_log(job_id, "Gerando 3 Thumbnails Magnéticas 1280x720 (Skia C++ + rembg u2netp)...", progress=94, stage="Gerando 3 Thumbnails A/B 1280x720")
            raw_thumbs = await asyncio.to_thread(_call_generate_ab_thumbnails, master_mp4, str(script.get("title", topic)), job_dir, thumb_3words)
            ab_thumbs_live = {
                "thumb_a": _rel_output(Path(raw_thumbs["thumb_a"])),
                "thumb_b": _rel_output(Path(raw_thumbs["thumb_b"])),
                "thumb_c": _rel_output(Path(raw_thumbs["thumb_c"])),
                "headline_words": raw_thumbs.get("headline_words", thumb_3words or ""),
            }

        dubbed_langs_live: Dict[str, Any] = {}
        if clone_languages:
            append_job_log(job_id, "🌎 Clonando Idiomas (Inglês US + Espanhol) com Re-Timing Automático...", progress=96, stage="Dublando EN-US + ES & Re-Timing")
            dubbed_raw = await dub_video_job_multi_language(
                job_dir=job_dir,
                engine_style="cinematic_broll",
                script_or_plan_dict=script,
                preset=preset,
                languages=("en_us", "es"),
                thermal_limit_c=thermal_limit,
                progress_cb=lambda m: append_job_log(job_id, m),
            )
            for lk, lv in dubbed_raw.items():
                dubbed_langs_live[lk] = {**lv, "path": _rel_output(Path(lv["path"]))}

        visual_libraries_used = [lib for lib in _VALID_VISUAL_LIBRARIES if library_usage_counts.get(lib, 0) > 0]

        (job_dir / "words.json").write_text(json.dumps(words_a, ensure_ascii=False), encoding="utf-8")
        quality_report = {
            "job_id": job_id,
            "engine_style": "cinematic_broll",
            "flow_mode": flow_mode,
            "max_credits_cap": max_credits_cap,
            "aspect_ratio": aspect_ratio,
            "resolution": f"{target_w}x{target_h}",
            "fps": resolved_fps,
            "lut_file": lut_file,
            "caption_style": caption_style,
            "chroma_key_filter": "active",
            "chroma_key_threshold": 0.30,
            "font_verified": compositor.font_info,
            "retention_audit": script.get("retention_audit", {}),
            "creative_config": _build_creative_config(music_label, aspect_ratio, resolved_fps, active_visual_libraries),
            "visual_libraries_used": visual_libraries_used,
            "visual_library_counts": library_usage_counts,
            "ab_thumbnails": ab_thumbs_live,
            "dubbed_languages": dubbed_langs_live,
            "shorts_cascade": [],
            "scenes_count": len(quality_clips),
            "clips": quality_clips,
            "duration_s": round(duration_s, 2),
        }
        (job_dir / "quality_report.json").write_text(
            json.dumps(quality_report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        now_done = datetime.now().isoformat(timespec="seconds")
        update_job(
            job_id,
            status="completed",
            progress=100,
            stage="Concluído • Pronto para Entrega & Publicação",
            master_path=_rel_output(master_mp4),
            hook_a_path=_rel_output(hook_a_mp4),
            hook_b_path=_rel_output(hook_b_mp4) if hook_b_mp4 and hook_b_mp4.exists() else "",
            tiktok_path=_rel_output(Path(sh_variants["tiktok"]["path"])),
            reels_path=_rel_output(Path(sh_variants["reels"]["path"])),
            shorts_path=_rel_output(Path(sh_variants["shorts"]["path"])),
            preview_path=_rel_output(preview_mp4),
            capcut_zip_path=_rel_output(capcut_zip),
            otio_path=_rel_output(otio_path),
            cover_path=_rel_output(cover_png),
            duration_s=round(duration_s, 2),
            completed_at=now_done,
        )
        append_job_log(
            job_id,
            f"FINALIZADO COM SUCESSO! {n_scenes} cenas ({', '.join(visual_libraries_used)}) + Legendas ({caption_style}) + Pacote VIP prontos.",
            progress=100,
        )
        return {"job_id": job_id, "status": "completed", "engine_style": "cinematic_broll", "master_path": str(master_mp4)}

    except Exception as exc:
        update_job(job_id, status="error", stage=f"Erro: {str(exc)[:100]}")
        append_job_log(job_id, f"ERRO NA FABRICAÇÃO: {exc}")
        raise


def enqueue_new_job(
    client_id: int,
    topic: str,
    skill_id: str = "01_negative_hook",
    mode: str = "single",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job_id = f"fr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return create_job(job_id, client_id, mode, topic, skill_id, options or {})
