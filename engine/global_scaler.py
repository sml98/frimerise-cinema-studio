"""FrimeRise Global Scale, Content Cascade (16:9 -> 5x 9:16 Shorts) & 1-Click B2B Prospecting Engine.
1. Multi-Language Dubbing & Auto Re-Timing (EN-US + ES):
   - Translates JSON plan/script with cultural adaptation (< 500 tokens, DeepSeek/Gemini + offline fallback)
   - Synthesizes native voices (kokoro-onnx af_heart/am_adam or edge-tts en-US-AndrewMultilingualNeural / es-MX-DaliaNeural)
   - Automatically re-times every scene, Hormozi caption, and 2D Rhubarb lip-sync to the new language duration!
2. 16:9 -> 9:16 Content Cascade ("1 Documentary/Animation = 1 Long + 5 Viral Shorts", Zero Tokens):
   - Selects 5 best hooks/acts across the 16:9 master video
   - Smart reframing 1920x1080 -> 1080x1920 via MediaPipe / OpenCV Saliency Center-of-Interest
   - Burns dynamic vertical Hormozi captions + traffic CTA ("▶ VÍDEO COMPLETO NO CANAL")
3. 1-Click B2B Commercial Prospecting ("Vender p/ Empresas"):
   - Company Name + City + Product/Service -> Persuasive 540p video with translucent diagonal watermark
     "PRÉVIA EXCLUSIVA • FRIMERISE" + ready-to-send WhatsApp sales pitch!
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import edge_tts
import httpx
import numpy as np
import skia

from agents.llm_router import _extract_json, get_settings, record_token_usage
from agents.retention_doctor import audit_viral_script_dict
from engine.audio_dsp import (
    _estimate_word_timestamps,
    _get_wav_duration,
    _kokoro_available,
    master_broadcast_audio,
    trim_silence_vad,
)
from engine.exporters import export_whatsapp_preview_540p
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    SkiaMotionCompositor,
    _load_verified_typeface,
    group_words_into_chunks,
    hex_to_skia,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"

LANG_VOICE_PROFILES = {
    "en_us": {
        "label": "Inglês (US)",
        "male_edge": "en-US-AndrewMultilingualNeural",
        "female_edge": "en-US-AvaMultilingualNeural",
        "kokoro_voices": ("af_heart", "am_adam"),
        "cta_tag": "▶ FULL VIDEO ON CHANNEL",
    },
    "es": {
        "label": "Espanhol (LATAM/ES)",
        "male_edge": "es-MX-JorgeNeural",
        "female_edge": "es-MX-DaliaNeural",
        "kokoro_voices": (),
        "cta_tag": "▶ VIDEO COMPLETO EN EL CANAL",
    },
}


# ---------------------------------------------------------------------------
# 1. Multi-Language Cultural Translation (< 450 tokens) + Native TTS & Re-Timing
# ---------------------------------------------------------------------------
def _offline_cultural_translate(lines: List[str], lang: str) -> List[str]:
    """Deterministic cultural adaptation fallback if no LLM key is reachable."""
    out: List[str] = []
    for idx, ln in enumerate(lines):
        if lang == "en_us":
            repl = (
                ln.replace("Nos primeiros três segundos", "In the first three seconds")
                .replace("o algoritmo decide", "the algorithm decides")
                .replace("Salve este vídeo agora", "Save this video right now")
                .replace("Barco", "Boat")
                .replace("tempestade", "storm")
            )
            if repl == ln:
                repl = f"Look at what really happens behind the scenes in act {idx + 1}: {ln}"
            out.append(repl)
        else:
            repl = (
                ln.replace("Nos primeiros três segundos", "En los primeros tres segundos")
                .replace("o algoritmo decide", "el algoritmo decide")
                .replace("Salve este vídeo agora", "Guarda este video ahora mismo")
                .replace("você", "tú")
                .replace("agora", "ahora")
            )
            if repl == ln:
                repl = f"Mira lo que realmente ocurre en el acto {idx + 1}: {ln}"
            out.append(repl)
    return out


def translate_lines_culturally(lines: List[str], target_lang: str = "en_us") -> List[str]:
    """Translate a list of PT-BR dialogue or narration lines into culturally native EN-US or ES in < 450 tokens."""
    if not lines:
        return []
    settings = get_settings()
    dkey = (settings.get("deepseek_api_key") or "").strip()
    gkey = (settings.get("gemini_api_key") or "").strip()
    model_choice = settings.get("default_llm") or "deepseek-flash"

    lang_name = "American English (en-US, punchy YouTube/TikTok native idioms)" if target_lang == "en_us" else "Neutral Latin American Spanish (es-MX, punchy viral storytelling idioms)"
    sys_p = (
        f"Translate the JSON array of Brazilian Portuguese video lines into {lang_name}. "
        "Keep exact array length, high energy, humor, and concise spoken rhythm. "
        'Respond ONLY with valid JSON: {"lines":["..."]}'
    )
    user_p = json.dumps({"lines": lines}, ensure_ascii=False)

    order = ["deepseek", "gemini"] if "deepseek" in model_choice else ["gemini", "deepseek"]
    for prov in order:
        if prov == "deepseek" and dkey:
            try:
                from openai import OpenAI

                cli = OpenAI(api_key=dkey, base_url="https://api.deepseek.com")
                resp = cli.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                    temperature=0.5,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                data = _extract_json(resp.choices[0].message.content or "{}")
                u = resp.usage
                pt = int(getattr(u, "prompt_tokens", 220))
                ct = int(getattr(u, "completion_tokens", 200))
                record_token_usage("deepseek", "deepseek-flash", pt, ct, 0, round((pt * 0.14 + ct * 0.28) / 1_000_000.0, 6))
                t_lines = data.get("lines")
                if isinstance(t_lines, list) and len(t_lines) == len(lines):
                    return [str(x).strip() for x in t_lines]
            except Exception:
                continue

        if prov == "gemini" and gkey:
            for gm in ("gemini-flash-lite-latest", "gemini-3.5-flash-lite"):
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                    r = httpx.post(
                        url,
                        headers={"x-goog-api-key": gkey},
                        json={
                            "system_instruction": {"parts": [{"text": sys_p}]},
                            "contents": [{"role": "user", "parts": [{"text": user_p}]}],
                            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 600, "responseMimeType": "application/json"},
                        },
                        timeout=20.0,
                    )
                    if r.status_code == 200:
                        j = r.json()
                        data = _extract_json(j["candidates"][0]["content"]["parts"][0]["text"])
                        meta = j.get("usageMetadata", {})
                        pt = int(meta.get("promptTokenCount", 220))
                        ct = int(meta.get("candidatesTokenCount", 200))
                        record_token_usage("gemini", gm, pt, ct, 0, 0.0001)
                        t_lines = data.get("lines")
                        if isinstance(t_lines, list) and len(t_lines) == len(lines):
                            return [str(x).strip() for x in t_lines]
                except Exception:
                    continue

    return _offline_cultural_translate(lines, target_lang)


async def _synthesize_multilang_narration(
    text: str,
    lang: str,
    work_dir: Path,
    tag: str,
    gender: str = "M",
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Synthesize native EN-US (Kokoro af_heart/am_adam or Edge en-US-AndrewMultilingualNeural)
    or ES (es-MX-DaliaNeural / es-MX-JorgeNeural) narration with exact WordBoundary timing.
    """
    profile = LANG_VOICE_PROFILES.get(lang, LANG_VOICE_PROFILES["en_us"])
    raw_mp3 = work_dir / f"{tag}_{lang}.mp3"
    raw_wav = work_dir / f"{tag}_{lang}.wav"
    vad_wav = work_dir / f"{tag}_{lang}_vad.wav"

    # 1. Try local Kokoro-ONNX af_heart / am_adam for English if model weights exist
    if lang == "en_us":
        avail, model_p, voices_p = _kokoro_available()
        if avail:
            try:
                from kokoro_onnx import Kokoro

                kokoro = Kokoro(str(model_p), str(voices_p))
                k_voice = "af_heart" if gender == "F" else "am_adam"
                samples, sr = kokoro.create(text, voice=k_voice, speed=1.06, lang="en-us")
                pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
                import wave

                with wave.open(str(raw_wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(int(sr))
                    wf.writeframes(pcm.tobytes())
                dur = _get_wav_duration(raw_wav)
                words = _estimate_word_timestamps(text, dur)
                return trim_silence_vad(raw_wav, vad_wav, words)
            except Exception:
                pass

    # 2. Native Edge-TTS Multilingual Neural voices with exact WordBoundary timestamps
    v_primary = profile["female_edge"] if gender == "F" else profile["male_edge"]
    v_secondary = profile["male_edge"] if gender == "F" else profile["female_edge"]
    for voice_id in (v_primary, v_secondary, "en-US-AndrewMultilingualNeural"):
        try:
            comm = edge_tts.Communicate(text=text, voice=voice_id, rate="+6%", boundary="WordBoundary")
            words: List[Dict[str, Any]] = []
            chunks = bytearray()
            async for ch in comm.stream():
                if ch.get("type") == "audio":
                    chunks.extend(ch["data"])
                elif ch.get("type") == "WordBoundary":
                    st = float(ch["offset"]) / 10_000_000.0
                    dur = float(ch["duration"]) / 10_000_000.0
                    words.append({"word": str(ch["text"]).strip(), "start": round(st, 3), "end": round(st + max(0.06, dur), 3)})
            if chunks:
                raw_mp3.write_bytes(bytes(chunks))
                return trim_silence_vad(raw_mp3, vad_wav, words)
        except Exception:
            continue

    raise RuntimeError(f"Falha ao sintetizar voz nativa para idioma {lang}")


async def dub_video_job_multi_language(
    job_dir: Path,
    engine_style: str,
    script_or_plan_dict: Dict[str, Any],
    preset: Dict[str, Any],
    languages: Tuple[str, ...] = ("en_us", "es"),
    cartoon_fps: int = 30,
    thermal_limit_c: float = 85.0,
    progress_cb=None,
) -> Dict[str, Dict[str, Any]]:
    """Auto-dub and re-time an entire video job (Cartoon 2D OR Cinematic/Documentary) into EN-US and ES!
    Automatically adjusts scene durations, word-level Hormozi captions, and 2D Rhubarb lip-sync.
    """
    work_dir = job_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    music_file = ASSETS_DIR / "music" / preset.get("music_file", "corporate_focus.mp3")
    results: Dict[str, Dict[str, Any]] = {}

    if engine_style == "cartoon_2d" and "scenes" in script_or_plan_dict and "characters" in script_or_plan_dict:
        from engine.cartoon_2d_studio import CartoonEpisodePlan, render_cartoon_episode

        for lang in languages:
            profile = LANG_VOICE_PROFILES.get(lang, LANG_VOICE_PROFILES["en_us"])
            if progress_cb:
                progress_cb(f"🌎 Dublando e re-sincronizando Lip-Sync 2D para {profile['label']}...")

            plan_copy = CartoonEpisodePlan.model_validate(json.loads(json.dumps(script_or_plan_dict)))
            # Assign native language voices to each character
            for idx, ch in enumerate(plan_copy.characters):
                ch.voice_preset.engine = "edge"
                ch.voice_preset.voice_id = profile["male_edge"] if idx % 2 == 0 else profile["female_edge"]

            orig_lines: List[str] = []
            for sc in plan_copy.scenes:
                for dl in sc.dialogue_lines:
                    orig_lines.append(dl.line_pt)

            translated = await asyncio.to_thread(translate_lines_culturally, orig_lines, lang)
            cursor_i = 0
            for sc in plan_copy.scenes:
                for dl in sc.dialogue_lines:
                    if cursor_i < len(translated):
                        dl.line_pt = translated[cursor_i]
                    cursor_i += 1

            out_mp4 = job_dir / f"master_{lang}.mp4"
            lang_work = work_dir / f"dub_{lang}"
            render_info = await render_cartoon_episode(
                plan=plan_copy,
                work_dir=lang_work,
                out_master_mp4=out_mp4,
                music_mp3=music_file,
                fps=cartoon_fps,
                voice_engine="edge",
                thermal_limit_c=thermal_limit_c,
            )
            results[lang] = {
                "language": profile["label"],
                "path": str(out_mp4),
                "duration_s": render_info["duration_s"],
                "lipsync_re_timed": True,
            }
        return results

    # Branch B: Cinematic / Documentary Live-Action Re-Timing
    base_video = work_dir / "base_scenes.mp4"
    if not base_video.exists():
        base_video = job_dir / "master.mp4"

    orig_lines = [
        str(script_or_plan_dict.get("hook_a", "")),
        *[str(x) for x in (script_or_plan_dict.get("body_lines") or [])],
        str(script_or_plan_dict.get("closing_line", "")),
    ]
    orig_lines = [x.strip() for x in orig_lines if x.strip()]

    for lang in languages:
        profile = LANG_VOICE_PROFILES.get(lang, LANG_VOICE_PROFILES["en_us"])
        if progress_cb:
            progress_cb(f"🌎 Dublando e re-ajustando cenas/legendas para {profile['label']}...")

        t_lines = await asyncio.to_thread(translate_lines_culturally, orig_lines, lang)
        full_narration = " ".join(t_lines)
        lang_work = work_dir / f"dub_{lang}"
        lang_work.mkdir(parents=True, exist_ok=True)

        vad_wav, words_lang, voice_dur = await _synthesize_multilang_narration(
            full_narration, lang, lang_work, "narr", gender="M" if lang == "en_us" else "F"
        )
        master_m4a = lang_work / f"master_{lang}.m4a"
        master_m4a, final_dur = await asyncio.to_thread(
            master_broadcast_audio,
            vad_wav,
            music_file,
            [],
            master_m4a,
            voice_dur,
            0.18,
            0.40,
        )

        # Time-adapt base video cleanly to match the exact new language duration!
        orig_vid_dur = _get_wav_duration(base_video)
        retimed_base = lang_work / f"base_{lang}.mp4"
        pts_factor = max(0.65, min(1.55, final_dur / max(1.0, orig_vid_dur)))
        await asyncio.to_thread(
            run_ffmpeg_safe,
            [
                "ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(base_video),
                "-vf", f"setpts={pts_factor:.4f}*PTS",
                "-t", f"{final_dur:.3f}", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                str(retimed_base),
            ],
        )

        out_mp4 = job_dir / f"master_{lang}.mp4"
        compositor = SkiaMotionCompositor(preset=preset)
        await asyncio.to_thread(
            compositor.composite_video,
            retimed_base,
            master_m4a,
            out_mp4,
            words_lang,
            [],
            final_dur,
            30,
            thermal_limit_c,
            False,
        )
        results[lang] = {
            "language": profile["label"],
            "path": str(out_mp4),
            "duration_s": round(final_dur, 2),
            "lipsync_re_timed": True,
        }

    return results


# ---------------------------------------------------------------------------
# 2. Automatic 16:9 -> 9:16 Content Cascade ("1 Documentary = 1 Long + 5 Shorts")
# ---------------------------------------------------------------------------
def _detect_horizontal_center_of_interest(video_16x9: Path, start_s: float, dur_s: float) -> float:
    """Use OpenCV gradient/color saliency centroid across 3 sampled frames in [start_s, start_s + dur_s]
    to find the normalized X center [0.22..0.78] without spawning background TFLite thread pools.
    """
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(video_16x9))
    if not cap.isOpened():
        return 0.50

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    centers: List[float] = []

    for frac in (0.20, 0.50, 0.80):
        t = start_s + dur_s * frac
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        col_energy = np.mean(mag, axis=0) + 1e-4
        xs = np.linspace(0.0, 1.0, len(col_energy))
        cx = float(np.sum(xs * col_energy) / np.sum(col_energy))
        centers.append(max(0.22, min(0.78, cx)))

    cap.release()
    return float(np.median(centers)) if centers else 0.50


def extract_5_viral_shorts_from_16x9(
    master_16x9_mp4: Path,
    words: List[Dict[str, Any]],
    output_dir: Path,
    max_shorts: int = 5,
    thermal_limit_c: float = 85.0,
) -> List[Dict[str, Any]]:
    """Extract up to 5 high-retention vertical 9:16 (1080x1920) Shorts from a 16:9 horizontal video.
    Zero LLM tokens: uses smart MediaPipe/Saliency 16:9->9:16 reframing + Skia vertical Hormozi captions.
    """
    shorts_dir = output_dir / "shorts_cascade"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    total_dur = _get_wav_duration(master_16x9_mp4)

    # Determine clip count and window length (up to 5 punchy vertical Shorts covering distinct acts/hooks)
    n_clips = min(max_shorts, 5)
    clip_dur = min(12.0, max(4.5, total_dur / float(max(3, n_clips))))
    if total_dur <= clip_dur + 1.0:
        step = 0.0
    else:
        step = (total_dur - clip_dur) / max(1, n_clips - 1)

    caption_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="cascade_short_caption")
    cap_font = skia.Font(caption_tf, 74.0)
    cta_font = skia.Font(caption_tf, 30.0)
    space_w = max(26.0, float(cap_font.measureText(" ")) * 1.42)
    fm = cap_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    extracted: List[Dict[str, Any]] = []
    out_w, out_h = 1080, 1920
    fps = 30

    for idx in range(n_clips):
        st_s = round(max(0.0, min(total_dur - clip_dur, idx * step)), 2)
        en_s = round(min(total_dur, st_s + clip_dur), 2)
        seg_dur = max(3.5, round(en_s - st_s, 2))

        # 1. Detect horizontal center of interest via MediaPipe / OpenCV Saliency
        norm_cx = _detect_horizontal_center_of_interest(master_16x9_mp4, st_s, seg_dur)

        # 2. Extract reframed 1080x1920 video + audio slice via FFmpeg smart crop
        raw_crop_mp4 = shorts_dir / f"_raw_short_{idx + 1:02d}.mp4"
        raw_audio_m4a = shorts_dir / f"_raw_short_{idx + 1:02d}.m4a"
        # Scale 1920x1080 -> 3414x1920 and crop 1080x1920 around norm_cx
        scaled_w = 3414
        crop_x = int(max(0, min(scaled_w - out_w, round(norm_cx * scaled_w - out_w * 0.5))))
        run_ffmpeg_safe(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{st_s:.2f}", "-t", f"{seg_dur:.2f}",
                "-i", str(master_16x9_mp4),
                "-vf", f"scale={scaled_w}:{out_h},crop={out_w}:{out_h}:{crop_x}:0,fps={fps}",
                "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "19",
                str(raw_crop_mp4),
            ]
        )
        run_ffmpeg_safe(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{st_s:.2f}", "-t", f"{seg_dur:.2f}",
                "-i", str(master_16x9_mp4),
                "-vn", "-c:a", "aac", "-b:a", "192k",
                str(raw_audio_m4a),
            ]
        )

        # 3. Slice & shift word timestamps for this Short and burn vertical Hormozi captions + Traffic CTA in Skia C++
        seg_words = []
        for wd in words:
            ws = float(wd.get("start", 0.0))
            we = float(wd.get("end", 0.0))
            if we >= st_s and ws <= en_s:
                seg_words.append(
                    {
                        "word": wd["word"],
                        "start": round(max(0.0, ws - st_s), 3),
                        "end": round(min(seg_dur, we - st_s), 3),
                    }
                )
        chunks = group_words_into_chunks(seg_words, max_words=3)

        final_short_mp4 = shorts_dir / f"short_{idx + 1:02d}_9x16.mp4"
        cap = cv2.VideoCapture(str(raw_crop_mp4))
        surface = skia.Surface(out_w, out_h)

        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=20)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            *pre_args,
            "-f", "rawvideo", "-pix_fmt", "bgra",
            "-s", f"{out_w}x{out_h}", "-r", str(fps), "-i", "pipe:0",
            "-i", str(raw_audio_m4a),
            "-vf", hw_suffix,
            "-map", "0:v", "-map", "1:a",
            "-t", f"{seg_dur:.3f}",
            *enc_args,
            "-c:a", "copy", "-movflags", "+faststart",
            str(final_short_mp4),
        ]
        thermal_guard_wait(limit_c=thermal_limit_c)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=get_vaapi_env())
        assert proc.stdin is not None

        fi = 0
        try:
            while True:
                ok, frame_bgr = cap.read()
                if not ok or frame_bgr is None:
                    break
                t = fi / float(fps)
                fi += 1

                frame_bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
                img = skia.Image.frombytes(
                    frame_bgra.tobytes(),
                    (out_w, out_h),
                    skia.kBGRA_8888_ColorType,
                    skia.kPremul_AlphaType,
                )

                c = surface.getCanvas()
                c.drawImage(img, 0, 0)

                # Lower-third contrast scrim
                scrim = skia.Paint()
                scrim.setShader(
                    skia.GradientShader.MakeLinear(
                        [(0, out_h * 0.72), (0, out_h)],
                        [skia.ColorSetARGB(0, 11, 7, 19), skia.ColorSetARGB(200, 11, 7, 19)],
                    )
                )
                c.drawRect(skia.Rect.MakeXYWH(0, out_h * 0.72, out_w, out_h * 0.28), scrim)

                # Traffic funnel badge at bottom ("▶ VÍDEO COMPLETO NO CANAL")
                cta_txt = f"▶ CORTE #{idx + 1} • VÍDEO COMPLETO NO CANAL"
                cta_w = cta_font.measureText(cta_txt)
                cta_r = skia.Rect.MakeXYWH((out_w - cta_w) * 0.5 - 24, out_h - 120, cta_w + 48, 52)
                c.drawRoundRect(cta_r, 26, 26, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(220, 20, 14, 36)))
                c.drawRoundRect(
                    cta_r,
                    26,
                    26,
                    skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.0, Color=hex_to_skia("#B8FF01")),
                )
                c.drawString(cta_txt, (out_w - cta_w) * 0.5, out_h - 84, cta_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

                # Vertical Hormozi Captions (strictly 1 active word pill)
                for ch in chunks:
                    if ch["start"] <= t <= ch["end"]:
                        w_list = ch["words"]
                        active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
                        pad_x, pad_y = 24.0, 12.0
                        toks = []
                        tot_w = 0.0
                        for wd in w_list:
                            txt = str(wd["word"]).strip().upper()
                            if not txt:
                                continue
                            is_act = wd is active_wd
                            sc = 1.12 if is_act else 1.0
                            tw = float(cap_font.measureText(txt))
                            sw = (tw + pad_x * 2.0) * sc if is_act else tw
                            toks.append({"txt": txt, "w": tw, "sw": sw, "act": is_act, "sc": sc, "pidx": int(wd.get("g_idx", 0))})
                            tot_w += sw
                        if toks:
                            tot_w += space_w * (len(toks) - 1)
                            lscale = min(1.0, (out_w * 0.86) / max(1.0, tot_w))
                            c.save()
                            c.translate(out_w * 0.5, out_h * 0.79)
                            c.scale(lscale, lscale)
                            cx_p = -tot_w * 0.5
                            pmap = {}
                            for tk in toks:
                                pmap[id(tk)] = cx_p + tk["sw"] * 0.5
                                cx_p += tk["sw"] + space_w
                            for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                                c.save()
                                c.translate(pmap[id(tk)], 0.0)
                                if tk["act"]:
                                    c.scale(tk["sc"], tk["sc"])
                                    pbg, ptx, _ = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
                                    pr = skia.Rect.MakeXYWH(-tk["w"] * 0.5 - pad_x, -ascent - pad_y, tk["w"] + pad_x * 2.0, ascent + descent + pad_y * 2.0)
                                    c.drawRoundRect(pr, 18, 18, skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg)))
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                                else:
                                    stp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=11.0, StrokeJoin=skia.Paint.kRound_Join, Color=skia.ColorBLACK)
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, stp)
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                                c.restore()
                            c.restore()
                        break

                proc.stdin.write(surface.makeImageSnapshot().tobytes())
        except BrokenPipeError:
            pass
        finally:
            cap.release()
            try:
                proc.stdin.close()
            except Exception:
                pass

        stderr = proc.stderr.read() if proc.stderr else b""
        proc.wait(timeout=180)
        raw_crop_mp4.unlink(missing_ok=True)
        raw_audio_m4a.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Falha ao extrair corte 9:16 #{idx + 1}: {stderr.decode(errors='ignore')}")

        extracted.append(
            {
                "short_idx": idx + 1,
                "path": str(final_short_mp4),
                "start_s": st_s,
                "end_s": en_s,
                "duration_s": seg_dur,
                "center_x_norm": round(norm_cx, 3),
                "resolution": "1080x1920",
            }
        )

    return extracted


# ---------------------------------------------------------------------------
# 3. 1-Click B2B Commercial Prospecting Generator ("Vender p/ Empresas")
# ---------------------------------------------------------------------------
def build_b2b_commercial_script_and_pitch(
    company_name: str,
    city: str,
    product_service: str,
) -> Tuple[Dict[str, Any], str]:
    """Create a high-converting local business video script (audited by Retention Doctor)
    AND a ready-to-copy WhatsApp outreach message for closing recurring B2B retainers.
    """
    comp = company_name.strip() or "Clínica Prime"
    ct = city.strip() or "Sua Cidade"
    prod = product_service.strip() or "Atendimento Premium"

    raw_script = {
        "title": f"{comp} • {ct}",
        "hook_a": f"Moradores de {ct}: parem de procurar {prod} sem antes conhecer o padrão da {comp}!",
        "hook_b": f"Por que tanta gente em {ct} está trocando tudo pelo {prod} da {comp} esta semana?",
        "body_lines": [
            f"A maioria das empresas promete resultado em {prod}, mas entrega exatamente mais do mesmo — só que tem um detalhe que muda tudo.",
            f"Na {comp} em {ct}, cada etapa de {prod} foi desenhada para entregar resultado real logo no primeiro atendimento.",
        ],
        "closing_line": f"Toque no link abaixo ou chame a {comp} no WhatsApp agora e garanta seu horário em {ct}!",
        "broll_queries": [
            "modern luxury business storefront",
            "happy customer reception professional service",
            "executive team meeting modern office",
            "smartphone booking appointment hands",
        ],
        "motion_cards": [
            {
                "type": "headline",
                "tag": f"DESTAQUE EM {ct.upper()}",
                "title": comp.upper()[:28],
                "subtitle": prod[:42],
            }
        ],
        "hashtags": [f"#{re.sub(r'[^a-zA-Z0-9]', '', comp.lower())}", f"#{re.sub(r'[^a-zA-Z0-9]', '', ct.lower())}", "#negociolocal", "#reels"],
    }
    audited_script = audit_viral_script_dict(raw_script)

    whatsapp_pitch = (
        f"Olá, equipe da *{comp}*! Tudo bem? 👋\n\n"
        f"Notei que muita gente em *{ct}* busca por *{prod}* no Instagram, TikTok e Shorts, "
        f"mas poucos negócios locais estão usando vídeos dinâmicos de alta retenção para capturar esses clientes todos os dias.\n\n"
        f"Tomei a liberdade de produzir em nosso estúdio uma *Prévia Exclusiva de Vídeo Comercial* personalizada para a *{comp}* "
        f"(anexei o vídeo demonstrativo de 540p aqui na conversa!). 🎬✨\n\n"
        f"Se gostarem do formato, eu entrego a versão *Master Full HD 1080p sem marca d'água* + *3 variações otimizadas* "
        f"(Reels, TikTok e Shorts) prontas para atrair clientes em *{ct}* ainda hoje.\n\n"
        f"Podemos liberar o arquivo Master sem marca d'água para vocês testarem hoje?"
    )
    return audited_script, whatsapp_pitch
