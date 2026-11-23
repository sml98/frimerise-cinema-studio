"""FrimeRise Global Scale, Content Cascade (16:9 -> 5x 9:16 Shorts) & 1-Click B2B Prospecting Engine.
1. Multi-Language Dubbing & Mathematical Re-Timing (PT-BR <-> EN-US <-> ES):
   - Translates JSON plan/script with cultural adaptation (< 500 tokens, DeepSeek/Gemini + offline fallback)
   - Synthesizes native voices (kokoro-onnx af_heart/am_adam/pm_alex/pf_dora or edge-tts
     en-US-AndrewMultilingualNeural / es-MX-DaliaNeural / pt-BR-AntonioNeural)
   - Mathematically recalculates every scene cut, Hormozi caption, and 2D lip-sync to the new language duration
     across `netflix_doc`, `cartoon_2d`, and `cinematic_broll`!
2. 16:9 -> 9:16 Content Cascade ("1 Documentary/Animation = 1 Long + 5 Viral Shorts", Zero Tokens):
   - Scores and extracts the 5 highest-impact moments across the 16:9 master video
   - Smart reframing 1920x1080 -> 1080x1920 via MediaPipe BlazeFace / OpenCV Saliency Center-of-Interest
   - Burns dynamic vertical Hormozi captions + traffic CTA pill pointing to the full video
3. 1-Click B2B Commercial Prospecting ("Vender p/ Empresas"):
   - Delegates to `engine.b2b_pitch_maker` while preserving backward-compatible `build_b2b_commercial_script_and_pitch`.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import edge_tts
import httpx
import numpy as np
from scipy.interpolate import PchipInterpolator
import skia

from agents.llm_router import _extract_json, get_settings, record_token_usage
from agents.retention_doctor import (
    _detect_lang,
    audit_netflix_doc_plan,
    audit_viral_script_dict,
)
from engine.audio_dsp import (
    _estimate_word_timestamps,
    _get_wav_duration,
    _kokoro_available,
    master_broadcast_audio,
    trim_silence_vad,
)
from engine.b2b_pitch_maker import (
    generate_b2b_pitch_bundle,
    render_b2b_540p_demo,
)
from engine.exporters import export_whatsapp_preview_540p
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.pro_sfx_studio import ensure_pro_cinema_sfx
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    SkiaMotionCompositor,
    _load_verified_typeface,
    group_words_into_chunks,
    hex_to_skia,
)

try:
    from engine.kinetic_captions import draw_kinetic_captions as _draw_kinetic_captions
except Exception:
    _draw_kinetic_captions = None

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"

LANG_VOICE_PROFILES: Dict[str, Dict[str, Any]] = {
    "pt_br": {
        "label": "Português (BR)",
        "male_edge": "pt-BR-AntonioNeural",
        "female_edge": "pt-BR-FranciscaNeural",
        "kokoro_voices": ("pm_alex", "pf_dora"),
        "kokoro_lang": "pt-br",
        "cta_tag": "▶ ASSISTA COMPLETO NO CANAL",
    },
    "en_us": {
        "label": "Inglês (US)",
        "male_edge": "en-US-AndrewMultilingualNeural",
        "female_edge": "en-US-AvaMultilingualNeural",
        "kokoro_voices": ("am_adam", "af_heart"),
        "kokoro_lang": "en-us",
        "cta_tag": "▶ FULL VIDEO ON CHANNEL",
    },
    "es": {
        "label": "Espanhol (LATAM/ES)",
        "male_edge": "es-MX-JorgeNeural",
        "female_edge": "es-MX-DaliaNeural",
        "kokoro_voices": (),
        "kokoro_lang": "es",
        "cta_tag": "▶ VIDEO COMPLETO EN EL CANAL",
    },
}


# ---------------------------------------------------------------------------
# 1. Multi-Language Cultural Translation (< 500 tokens) + Native TTS & Mathematical Re-Timing
# ---------------------------------------------------------------------------
_PT_TO_EN_PHRASES = [
    ("Nos primeiros três segundos", "In the first three seconds"),
    ("o algoritmo decide", "the algorithm decides"),
    ("Salve este vídeo agora", "Save this video right now"),
    ("Olha o que quase ninguém percebe", "Look at what almost nobody notices"),
    ("Presta atenção neste detalhe", "Pay close attention to this detail"),
    ("Mas havia uma falha fatal escondida nos arquivos", "But there was a fatal flaw hidden in the files"),
    ("como ninguém percebeu antes do colapso", "how did nobody notice before the collapse"),
    ("Mas espera", "But wait"),
    ("bilhão", "billion"),
    ("bilhões", "billions"),
    ("milhões", "millions"),
    ("escondeu", "hid"),
    ("segredo", "secret"),
    ("documento", "document"),
    ("banco", "bank"),
    ("império", "empire"),
    ("colapso", "collapse"),
    ("fraude", "fraud"),
    ("dinheiro", "money"),
    ("mercado", "market"),
]

_PT_TO_ES_PHRASES = [
    ("Nos primeiros três segundos", "En los primeros tres segundos"),
    ("o algoritmo decide", "el algoritmo decide"),
    ("Salve este vídeo agora", "Guarda este video ahora mismo"),
    ("Olha o que quase ninguém percebe", "Mira lo que casi nadie nota"),
    ("Presta atenção neste detalhe", "Presta atención a este detalle"),
    ("Mas havia uma falha fatal escondida nos arquivos", "Pero había una falla fatal oculta en los archivos"),
    ("como ninguém percebeu antes do colapso", "cómo nadie lo notó antes del colapso"),
    ("Mas espera", "Pero espera"),
    ("bilhão", "mil millones"),
    ("bilhões", "miles de millones"),
    ("milhões", "millones"),
    ("escondeu", "ocultó"),
    ("segredo", "secreto"),
    ("documento", "documento"),
    ("império", "imperio"),
    ("colapso", "colapso"),
    ("você", "tú"),
    ("agora", "ahora"),
]

_EN_TO_PT_PHRASES = [
    ("In the first three seconds", "Nos primeiros três segundos"),
    ("the algorithm decides", "o algoritmo decide"),
    ("Save this video right now", "Salve este vídeo agora"),
    ("Here is what nobody tells you", "Olha o que quase ninguém te conta"),
    ("Look closely at this", "Presta atenção neste detalhe"),
    ("But there was one fatal flaw hidden in the vault", "Mas havia uma falha fatal escondida no cofre"),
    ("But wait", "Mas espera"),
    ("billion", "bilhão"),
    ("billions", "bilhões"),
    ("millions", "milhões"),
    ("secret", "segredo"),
    ("collapse", "colapso"),
    ("fraud", "fraude"),
    ("money", "dinheiro"),
]


def _offline_cultural_translate(lines: List[str], lang: str) -> List[str]:
    """Deterministic cultural adaptation fallback if no LLM key is reachable."""
    out: List[str] = []
    for idx, ln in enumerate(lines):
        src = str(ln or "").strip()
        if not src:
            out.append("")
            continue
        if lang == "en_us":
            repl = src
            for k, v in _PT_TO_EN_PHRASES:
                repl = re.sub(re.escape(k), v, repl, flags=re.IGNORECASE)
            if repl == src and _detect_lang(src) != "en_us":
                repl = f"In Act {idx + 1}, the investigation reveals what really happened behind closed doors: {src}"
            out.append(repl)
        elif lang == "es":
            repl = src
            for k, v in _PT_TO_ES_PHRASES:
                repl = re.sub(re.escape(k), v, repl, flags=re.IGNORECASE)
            if repl == src and _detect_lang(src) != "es":
                repl = f"En el acto {idx + 1}, la investigación revela lo que realmente ocurrió: {src}"
            out.append(repl)
        else:  # pt_br
            repl = src
            for k, v in _EN_TO_PT_PHRASES:
                repl = re.sub(re.escape(k), v, repl, flags=re.IGNORECASE)
            if repl == src and _detect_lang(src) != "pt_br":
                repl = f"No ato {idx + 1}, os arquivos revelam o que realmente aconteceu nos bastidores: {src}"
            out.append(repl)
    return out


def translate_lines_culturally(lines: List[str], target_lang: str = "en_us") -> List[str]:
    """Translate a list of dialogue or narration lines into culturally native PT-BR, EN-US, or ES in < 500 tokens."""
    if not lines:
        return []
    norm_lang = target_lang.strip().lower().replace("-", "_")
    if norm_lang not in LANG_VOICE_PROFILES:
        norm_lang = "en_us"

    settings = get_settings()
    dkey = (settings.get("deepseek_api_key") or "").strip()
    gkey = (settings.get("gemini_api_key") or "").strip()
    model_choice = settings.get("default_llm") or "deepseek-flash"

    lang_desc = {
        "en_us": "American English (en-US, punchy YouTube/MagnatesMedia native idioms)",
        "es": "Neutral Latin American Spanish (es-MX, punchy viral storytelling idioms)",
        "pt_br": "Brazilian Portuguese (pt-BR, high-retention investigative & viral storytelling idioms)",
    }[norm_lang]

    sys_p = (
        f"Translate the JSON array of video script lines into {lang_desc}. "
        "Keep exact array length, high tension, cultural idioms, and concise spoken rhythm (< 500 tokens). "
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
                    temperature=0.4,
                    max_tokens=450,
                    response_format={"type": "json_object"},
                )
                data = _extract_json(resp.choices[0].message.content or "{}")
                u = resp.usage
                pt = int(getattr(u, "prompt_tokens", 200))
                ct = int(getattr(u, "completion_tokens", 180))
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
                            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 450, "responseMimeType": "application/json"},
                        },
                        timeout=18.0,
                    )
                    if r.status_code == 200:
                        j = r.json()
                        data = _extract_json(j["candidates"][0]["content"]["parts"][0]["text"])
                        meta = j.get("usageMetadata", {})
                        pt = int(meta.get("promptTokenCount", 200))
                        ct = int(meta.get("candidatesTokenCount", 180))
                        record_token_usage("gemini", gm, pt, ct, 0, 0.0001)
                        t_lines = data.get("lines")
                        if isinstance(t_lines, list) and len(t_lines) == len(lines):
                            return [str(x).strip() for x in t_lines]
                except Exception:
                    continue

    return _offline_cultural_translate(lines, norm_lang)


def recalculate_scene_cuts_and_timing(
    plan_or_script: Dict[str, Any],
    translated_lines: List[str],
    new_total_duration_s: float,
    new_words: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Mathematically recalculate all scene cut timestamps (`start_s`, `end_s`, `duration_s`),
    Hormozi caption chunks, and 2D lip-sync viseme cues for a translated video plan/script.
    """
    updated = json.loads(json.dumps(plan_or_script))
    total_dur = max(1.0, float(new_total_duration_s))

    # 1. Calculate proportional weights from translated line word counts
    weights = [max(1, len(str(ln).split())) for ln in translated_lines] if translated_lines else [1]
    weight_sum = float(sum(weights)) or 1.0

    scenes = updated.get("scenes")
    scene_cuts: List[Dict[str, Any]] = []
    narration_keys = ("narration", "text", "line_pt", "voiceover", "script_line", "script", "dialogue")

    if isinstance(scenes, list) and scenes:
        # Map translated lines back into scene narration or dialogue lines and compute exact scene cuts
        line_cursor = 0
        scene_weights: List[float] = []
        for sc in scenes:
            if not isinstance(sc, dict):
                scene_weights.append(1.0)
                continue
            if isinstance(sc.get("dialogue_lines"), list) and sc["dialogue_lines"]:
                w_sc = 0.0
                for dl in sc["dialogue_lines"]:
                    if line_cursor < len(translated_lines):
                        dl["line_pt"] = translated_lines[line_cursor]
                        w_sc += max(1, len(translated_lines[line_cursor].split()))
                        line_cursor += 1
                    else:
                        w_sc += max(1, len(str(dl.get("line_pt", "")).split()))
                scene_weights.append(max(1.0, w_sc))
            else:
                t_key = next((nk for nk in narration_keys if nk in sc), "narration")
                if line_cursor < len(translated_lines):
                    sc[t_key] = translated_lines[line_cursor]
                    w_sc = float(max(1, len(translated_lines[line_cursor].split())))
                    line_cursor += 1
                else:
                    w_sc = float(max(1, len(str(sc.get(t_key, "")).split())))
                scene_weights.append(w_sc)

        sw_sum = sum(scene_weights) or 1.0
        cursor_t = 0.0
        for idx, sc in enumerate(scenes):
            sc_dur = round(total_dur * (scene_weights[idx] / sw_sum), 3)
            if idx == len(scenes) - 1:
                sc_dur = round(max(0.5, total_dur - cursor_t), 3)
            st_s = round(cursor_t, 3)
            en_s = round(cursor_t + sc_dur, 3)
            cursor_t = en_s
            if isinstance(sc, dict):
                sc["start_s"] = st_s
                sc["end_s"] = en_s
                sc["duration_s"] = sc_dur
                # Recalculate 2D lip-sync viseme cues if present on scene or dialogue lines
                if isinstance(sc.get("dialogue_lines"), list) and sc["dialogue_lines"]:
                    dl_count = len(sc["dialogue_lines"])
                    dl_dur = round(sc_dur / float(dl_count), 3)
                    dl_t = st_s
                    for dl in sc["dialogue_lines"]:
                        dl["start_s"] = round(dl_t, 3)
                        dl["end_s"] = round(min(en_s, dl_t + dl_dur), 3)
                        dl["duration_s"] = round(dl["end_s"] - dl["start_s"], 3)
                        dl_t = dl["end_s"]
            scene_cuts.append({"scene_index": idx + 1, "start_s": st_s, "end_s": en_s, "duration_s": sc_dur})
    else:
        # Viral / B-Roll script without explicit scenes array: compute mathematical scene cuts per translated line
        cursor_t = 0.0
        for idx, w_val in enumerate(weights):
            sc_dur = round(total_dur * (w_val / weight_sum), 3)
            if idx == len(weights) - 1:
                sc_dur = round(max(0.5, total_dur - cursor_t), 3)
            st_s = round(cursor_t, 3)
            en_s = round(cursor_t + sc_dur, 3)
            cursor_t = en_s
            scene_cuts.append({"scene_index": idx + 1, "start_s": st_s, "end_s": en_s, "duration_s": sc_dur})
        if translated_lines:
            updated["hook_a"] = translated_lines[0]
            if len(translated_lines) > 2:
                updated["body_lines"] = translated_lines[1:-1]
                updated["closing_line"] = translated_lines[-1]
            elif len(translated_lines) == 2:
                updated["body_lines"] = [translated_lines[1]]

    # 2. Mathematically recalculate Hormozi 2-3 word caption chunks
    hormozi_chunks = group_words_into_chunks(new_words, max_words=3)
    updated["retimed_duration_s"] = round(total_dur, 3)
    updated["scene_cuts"] = scene_cuts
    updated["hormozi_captions_count"] = len(hormozi_chunks)
    updated["words_count"] = len(new_words)
    return updated


async def _synthesize_multilang_narration(
    text: str,
    lang: str,
    work_dir: Path,
    tag: str,
    gender: str = "M",
    thermal_limit_c: float = 85.0,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Synthesize native PT-BR, EN-US (Kokoro am_adam/af_heart or Edge en-US-AndrewMultilingualNeural),
    or ES (es-MX-DaliaNeural / es-MX-JorgeNeural) narration with exact WordBoundary timing.
    Includes a deterministic offline speech-cadence WAV fallback if offline.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    norm_lang = lang.strip().lower().replace("-", "_")
    profile = LANG_VOICE_PROFILES.get(norm_lang, LANG_VOICE_PROFILES["en_us"])
    raw_mp3 = work_dir / f"{tag}_{norm_lang}.mp3"
    raw_wav = work_dir / f"{tag}_{norm_lang}.wav"
    vad_wav = work_dir / f"{tag}_{norm_lang}_vad.wav"

    # 1. Try local Kokoro-ONNX (am_adam / af_heart for EN-US, pm_alex / pf_dora for PT-BR) if weights exist
    if norm_lang in ("en_us", "pt_br") and profile.get("kokoro_voices"):
        avail, model_p, voices_p = _kokoro_available()
        if avail:
            try:
                from kokoro_onnx import Kokoro

                kokoro = Kokoro(str(model_p), str(voices_p))
                k_male, k_female = profile["kokoro_voices"]
                k_voice = k_female if gender == "F" else k_male
                samples, sr = kokoro.create(text, voice=k_voice, speed=1.06, lang=profile["kokoro_lang"])
                pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
                with wave.open(str(raw_wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(int(sr))
                    wf.writeframes(pcm.tobytes())
                dur = _get_wav_duration(raw_wav)
                words = _estimate_word_timestamps(text, dur)
                return trim_silence_vad(raw_wav, vad_wav, words, thermal_limit_c=thermal_limit_c)
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
                return trim_silence_vad(raw_mp3, vad_wav, words, thermal_limit_c=thermal_limit_c)
        except Exception:
            continue

    # 3. Deterministic offline speech-envelope WAV fallback so offline tests never crash
    word_list = [w for w in str(text or "").split() if w.strip()]
    est_dur = max(3.5, round(len(word_list) / 2.7, 2))
    sr = 24000
    t = np.linspace(0.0, est_dur, int(est_dur * sr), endpoint=False)
    sig = 0.14 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 3.0 * t)) * np.sin(2.0 * np.pi * 175.0 * t)
    pcm = (np.clip(sig, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(vad_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return vad_wav, _estimate_word_timestamps(text, est_dur), est_dur


def _probe_video_dimensions(video_path: Path) -> Tuple[int, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 1080, 1920
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
    cap.release()
    return w, h


def _draw_fallback_hormozi_captions(
    canvas: skia.Canvas,
    chunks: List[Dict[str, Any]],
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    y_ratio: float = 0.79,
    font_size: float = 74.0,
) -> None:
    """Clean drop-shadow single-active-pill Hormozi caption fallback if kinetic_captions is absent."""
    cap_font = skia.Font(typeface, float(font_size))
    space_w = max(22.0, float(cap_font.measureText(" ")) * 1.40)
    fm = cap_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))
    shadow_filter = skia.ImageFilters.DropShadow(0.0, 6.0, 9.0, 9.0, skia.ColorSetARGB(195, 0, 0, 0))

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
                lscale = min(1.0, (w * 0.86) / max(1.0, tot_w))
                canvas.save()
                canvas.translate(w * 0.5, h * y_ratio)
                canvas.scale(lscale, lscale)
                cx_p = -tot_w * 0.5
                pmap = {}
                for tk in toks:
                    pmap[id(tk)] = cx_p + tk["sw"] * 0.5
                    cx_p += tk["sw"] + space_w
                for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                    canvas.save()
                    canvas.translate(pmap[id(tk)], 0.0)
                    if tk["act"]:
                        canvas.scale(tk["sc"], tk["sc"])
                        pbg, ptx, _ = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
                        pr = skia.Rect.MakeXYWH(
                            -tk["w"] * 0.5 - pad_x,
                            -ascent - pad_y,
                            tk["w"] + pad_x * 2.0,
                            ascent + descent + pad_y * 2.0,
                        )
                        pill_paint = skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg))
                        pill_paint.setImageFilter(shadow_filter)
                        canvas.drawRoundRect(pr, 18, 18, pill_paint)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                    else:
                        stp = skia.Paint(
                            AntiAlias=True,
                            Style=skia.Paint.kStroke_Style,
                            StrokeWidth=11.0,
                            StrokeJoin=skia.Paint.kRound_Join,
                            Color=skia.ColorBLACK,
                        )
                        stp.setImageFilter(shadow_filter)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, stp)
                        canvas.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                    canvas.restore()
                canvas.restore()
            break


def _draw_captions_pro(
    canvas: skia.Canvas,
    chunks: List[Dict[str, Any]],
    t: float,
    w: int,
    h: int,
    typeface: skia.Typeface,
    style: str = "hormozi_neon",
    y_ratio: float = 0.79,
    font_size: float = 74.0,
) -> None:
    """Render kinetic captions via engine.kinetic_captions with clean Hormozi fallback."""
    if str(style or "").strip().lower() == "none":
        return
    if _draw_kinetic_captions is not None:
        try:
            _draw_kinetic_captions(
                canvas=canvas,
                chunks=chunks,
                t=t,
                w=w,
                h=h,
                typeface=typeface,
                style=style,
                y_ratio=y_ratio,
                font_size=font_size,
                palette=ACTIVE_PILL_PALETTE,
            )
            return
        except Exception:
            pass
    _draw_fallback_hormozi_captions(canvas, chunks, t, w, h, typeface, y_ratio=y_ratio, font_size=font_size)


def _composite_hormozi_captions_any_aspect(
    bg_video: Path,
    audio_m4a: Path,
    out_mp4: Path,
    words: List[Dict[str, Any]],
    duration_s: float,
    preset: Dict[str, Any],
    fps: int = 30,
    thermal_limit_c: float = 85.0,
    caption_style: str = "hormozi_neon",
) -> Path:
    """Composite kinetic Hormozi captions onto either 9:16 (1080x1920) or 16:9 (1920x1080) video."""
    vid_w, vid_h = _probe_video_dimensions(bg_video)
    resolved_style = str(caption_style or preset.get("caption_style") or "hormozi_neon")
    if vid_w <= vid_h:
        compositor = SkiaMotionCompositor(preset=preset, width=vid_w, height=vid_h)
        try:
            return compositor.composite_onto_video(
                bg_video=bg_video,
                audio_m4a=audio_m4a,
                output_mp4=out_mp4,
                duration_s=duration_s,
                words=words,
                motion_cards=[],
                fps=fps,
                show_motion_cards=False,
                thermal_limit_c=thermal_limit_c,
                caption_style=resolved_style,
            )
        except TypeError:
            return compositor.composite_onto_video(
                bg_video=bg_video,
                audio_m4a=audio_m4a,
                output_mp4=out_mp4,
                duration_s=duration_s,
                words=words,
                motion_cards=[],
                fps=fps,
                show_motion_cards=False,
                thermal_limit_c=thermal_limit_c,
            )

    # 16:9 Widescreen Kinetic Caption Compositor (positioned cleanly at y = vid_h * 0.84)
    thermal_guard_wait(limit_c=thermal_limit_c)
    chunks = group_words_into_chunks(words, max_words=3)
    total_frames = max(1, int(math.ceil(duration_s * fps)))
    tf, _ = _load_verified_typeface(preset.get("font_file", "Montserrat-Black.ttf"), role="dub_16x9_caption")
    f_size = 64.0 if vid_w >= 1920 else 44.0

    surf = skia.Surface(vid_w, vid_h)
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        "-i", str(bg_video),
        "-f", "rawvideo", "-pix_fmt", "bgra",
        "-s", f"{vid_w}x{vid_h}", "-r", str(fps), "-i", "pipe:0",
        "-i", str(audio_m4a),
        "-filter_complex", f"[0:v][1:v]overlay=0:0:shortest=1,{hw_suffix}[vout]",
        "-map", "[vout]", "-map", "2:a",
        "-t", f"{duration_s:.3f}",
        *enc_args,
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=get_vaapi_env(), preexec_fn=nice_preexec)
    assert proc.stdin is not None
    try:
        for f_idx in range(total_frames):
            t = f_idx / float(fps)
            c = surf.getCanvas()
            c.clear(skia.Color4f(0, 0, 0, 0))
            _draw_captions_pro(
                c,
                chunks,
                t,
                vid_w,
                vid_h,
                tf,
                style=resolved_style,
                y_ratio=0.84,
                font_size=f_size,
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
    proc.wait(timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"Falha ao compor legendas 16:9 dubladas: {stderr.decode(errors='ignore')}")
    return out_mp4


def _extract_narration_lines_from_plan(script_or_plan_dict: Dict[str, Any]) -> List[str]:
    """Extract ordered spoken lines from any FrimeRise plan (`netflix_doc`, `cartoon_2d`, or `cinematic_broll`)."""
    lines: List[str] = []
    scenes = script_or_plan_dict.get("scenes")
    narration_keys = ("narration", "text", "line_pt", "voiceover", "script_line", "script", "dialogue")
    if isinstance(scenes, list) and scenes:
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            if isinstance(sc.get("dialogue_lines"), list) and sc["dialogue_lines"]:
                for dl in sc["dialogue_lines"]:
                    txt = str(dl.get("line_pt") or dl.get("text") or "").strip()
                    if txt:
                        lines.append(txt)
            else:
                for nk in narration_keys:
                    if sc.get(nk) and str(sc[nk]).strip():
                        lines.append(str(sc[nk]).strip())
                        break
    if not lines:
        raw = [
            str(script_or_plan_dict.get("cold_open") or script_or_plan_dict.get("hook_a") or ""),
            *[str(x) for x in (script_or_plan_dict.get("body_lines") or [])],
            str(script_or_plan_dict.get("closing_line") or ""),
        ]
        lines = [x.strip() for x in raw if x.strip()]
    return lines


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
    """Auto-dub and mathematically re-time an entire video job (`cartoon_2d`, `netflix_doc`, or `cinematic_broll`)
    into target languages (`pt_br`, `en_us`, `es`).
    Automatically recalculates scene cuts, word-level Hormozi captions, and 2D lip-sync.
    """
    job_dir = Path(job_dir)
    work_dir = job_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    music_file = ASSETS_DIR / "music" / preset.get("music_file", "corporate_focus.mp3")
    results: Dict[str, Dict[str, Any]] = {}

    # Branch A: 2D Cartoon Multi-Character Episode Re-Dubbing & 9-Viseme Lip-Sync Re-Timing
    if engine_style == "cartoon_2d" and "scenes" in script_or_plan_dict and "characters" in script_or_plan_dict:
        from engine.cartoon_2d_studio import CartoonEpisodePlan, render_cartoon_episode

        for lang in languages:
            norm_lang = lang.strip().lower().replace("-", "_")
            profile = LANG_VOICE_PROFILES.get(norm_lang, LANG_VOICE_PROFILES["en_us"])
            if progress_cb:
                progress_cb(f"🌎 Dublando e re-sincronizando Lip-Sync 2D para {profile['label']}...")

            plan_copy = CartoonEpisodePlan.model_validate(json.loads(json.dumps(script_or_plan_dict)))
            for idx, ch in enumerate(plan_copy.characters):
                ch.voice_preset.engine = "edge"
                ch.voice_preset.voice_id = profile["male_edge"] if idx % 2 == 0 else profile["female_edge"]

            orig_lines: List[str] = []
            for sc in plan_copy.scenes:
                for dl in sc.dialogue_lines:
                    orig_lines.append(dl.line_pt)

            translated = await asyncio.to_thread(translate_lines_culturally, orig_lines, norm_lang)
            cursor_i = 0
            for sc in plan_copy.scenes:
                for dl in sc.dialogue_lines:
                    if cursor_i < len(translated):
                        dl.line_pt = translated[cursor_i]
                    cursor_i += 1

            out_mp4 = job_dir / f"master_{norm_lang}.mp4"
            lang_work = work_dir / f"dub_{norm_lang}"
            render_info = await render_cartoon_episode(
                plan=plan_copy,
                work_dir=lang_work,
                out_master_mp4=out_mp4,
                music_mp3=music_file,
                fps=cartoon_fps,
                voice_engine="edge",
                thermal_limit_c=thermal_limit_c,
            )
            retimed_plan = recalculate_scene_cuts_and_timing(
                plan_copy.model_dump(),
                translated,
                float(render_info["duration_s"]),
                render_info.get("words", []),
            )
            results[norm_lang] = {
                "language": profile["label"],
                "path": str(out_mp4),
                "duration_s": render_info["duration_s"],
                "scene_cuts": retimed_plan["scene_cuts"],
                "hormozi_captions_count": retimed_plan["hormozi_captions_count"],
                "lipsync_re_timed": True,
            }
        return results

    # Branch B: Netflix Documentary (`netflix_doc`) OR Cinematic Viral (`cinematic_broll`) Re-Timing
    base_video = work_dir / "bg_assembled.mp4"
    if not base_video.exists():
        base_video = work_dir / "base_scenes.mp4"
    if not base_video.exists():
        base_video = job_dir / "master.mp4"

    orig_lines = _extract_narration_lines_from_plan(script_or_plan_dict)
    if not orig_lines:
        orig_lines = [str(script_or_plan_dict.get("title") or "Investigação exclusiva nos arquivos confidenciais.")]

    for lang in languages:
        norm_lang = lang.strip().lower().replace("-", "_")
        profile = LANG_VOICE_PROFILES.get(norm_lang, LANG_VOICE_PROFILES["en_us"])
        if progress_cb:
            progress_cb(f"🌎 Dublando e recalculando cortes/legendas para {profile['label']}...")

        t_lines = await asyncio.to_thread(translate_lines_culturally, orig_lines, norm_lang)
        lang_work = work_dir / f"dub_{norm_lang}"
        lang_work.mkdir(parents=True, exist_ok=True)
        out_mp4 = job_dir / f"master_{norm_lang}.mp4"

        # If this is a Netflix Documentary plan and no base_video exists yet, try native netflix_doc renderer first
        if engine_style == "netflix_doc" and not base_video.exists():
            try:
                from engine.netflix_doc_studio import render_netflix_documentary

                doc_plan_copy = recalculate_scene_cuts_and_timing(script_or_plan_dict, t_lines, 20.0, [])
                doc_plan_copy["lang"] = norm_lang
                doc_plan_copy["voice_id"] = profile["male_edge"]
                doc_plan_copy = audit_netflix_doc_plan(doc_plan_copy, lang=norm_lang)
                doc_info = await render_netflix_documentary(
                    plan=doc_plan_copy,
                    work_dir=lang_work,
                    out_master_mp4=out_mp4,
                    music_mp3=music_file,
                    fps=30,
                    thermal_limit_c=thermal_limit_c,
                )
                retimed_doc = recalculate_scene_cuts_and_timing(
                    doc_plan_copy,
                    t_lines,
                    float(doc_info.get("duration_s", 20.0)),
                    doc_info.get("words", []),
                )
                results[norm_lang] = {
                    "language": profile["label"],
                    "path": str(out_mp4),
                    "duration_s": round(float(doc_info.get("duration_s", 20.0)), 2),
                    "scene_cuts": retimed_doc["scene_cuts"],
                    "hormozi_captions_count": retimed_doc["hormozi_captions_count"],
                    "lipsync_re_timed": True,
                }
                continue
            except Exception:
                pass

        full_narration = " ".join(t_lines)
        vad_wav, words_lang, voice_dur = await _synthesize_multilang_narration(
            full_narration,
            norm_lang,
            lang_work,
            "narr",
            gender="M" if norm_lang in ("en_us", "pt_br") else "F",
            thermal_limit_c=thermal_limit_c,
        )
        master_m4a = lang_work / f"master_{norm_lang}.m4a"
        master_m4a, final_dur = await asyncio.to_thread(
            master_broadcast_audio,
            vad_wav,
            music_file,
            [],
            master_m4a,
            voice_dur,
            0.18,
            0.40,
            thermal_limit_c,
        )

        # Mathematically recalculate all scene cuts & Hormozi captions for the new language duration
        retimed_plan = recalculate_scene_cuts_and_timing(
            script_or_plan_dict,
            t_lines,
            final_dur,
            words_lang,
        )
        if engine_style == "netflix_doc":
            retimed_plan = audit_netflix_doc_plan(retimed_plan, lang=norm_lang)
        else:
            retimed_plan = audit_viral_script_dict(retimed_plan, lang=norm_lang)

        (lang_work / f"retimed_plan_{norm_lang}.json").write_text(
            json.dumps(retimed_plan, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Time-adapt base video cleanly to match the exact new language duration
        orig_vid_dur = _get_wav_duration(base_video) if base_video.exists() else final_dur
        retimed_base = lang_work / f"base_{norm_lang}.mp4"
        pts_factor = max(0.65, min(1.55, final_dur / max(1.0, orig_vid_dur)))
        await asyncio.to_thread(
            run_ffmpeg_safe,
            [
                "ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(base_video),
                "-vf", f"setpts={pts_factor:.4f}*PTS",
                "-t", f"{final_dur:.3f}", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                str(retimed_base),
            ],
            thermal_limit_c,
        )

        await asyncio.to_thread(
            _composite_hormozi_captions_any_aspect,
            retimed_base,
            master_m4a,
            out_mp4,
            words_lang,
            final_dur,
            preset,
            30,
            thermal_limit_c,
        )
        results[norm_lang] = {
            "language": profile["label"],
            "path": str(out_mp4),
            "duration_s": round(final_dur, 2),
            "scene_cuts": retimed_plan["scene_cuts"],
            "hormozi_captions_count": retimed_plan["hormozi_captions_count"],
            "lipsync_re_timed": True,
        }

    return results


# ---------------------------------------------------------------------------
# 2. Automatic 16:9 -> 9:16 Content Cascade ("1 Documentary = 1 Long + 5 Shorts")
#    Pro Cinema Viral Cuts: Smooth 0.5s Tracking + Punch-In Zoom + Flash SFX +
#    Wide-Graphic Cinema Bleed + Kinetic Captions + Glassmorphic CTA
# ---------------------------------------------------------------------------
def _has_audio_stream(video_path: Path) -> bool:
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(res.stdout.strip())
    except Exception:
        return False


def _create_face_detectors() -> Tuple[Any, Any]:
    """Initialize MediaPipe BlazeFace (preferred) or OpenCV Haar cascade fallback."""
    mp_detector = None
    try:
        import mediapipe as mp

        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
            mp_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.45
            )
    except Exception:
        mp_detector = None

    cascade = None
    if mp_detector is None:
        try:
            xml = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            if xml.exists():
                cascade = cv2.CascadeClassifier(str(xml))
        except Exception:
            cascade = None
    return mp_detector, cascade


def _analyze_frame_coi_and_layout(
    frame_bgr: np.ndarray,
    mp_detector: Any,
    cascade: Any,
    prev_gray: Optional[np.ndarray] = None,
) -> Tuple[float, float, np.ndarray]:
    """Analyze a single 16:9 frame (downscaled internally to 480x270) and return:
    - cx_norm in [0.20..0.80]: horizontal subject center-of-interest
    - wide_score in {0.0, 1.0}: 1.0 when framing wide investigative graphics/boards/newspapers/timelines
    - small_gray: 480x270 grayscale for next-frame motion energy saliency
    """
    small = cv2.resize(frame_bgr, (480, 270), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    # Focus on upper 82% so bottom 16:9 subtitles never distort horizontal tracking or layout detection
    roi_h = int(h * 0.82)
    roi = small[:roi_h, :, :]
    gray_full = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = gray_full[:roi_h, :]

    face_cx: Optional[float] = None
    if mp_detector is not None:
        try:
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            res = mp_detector.process(rgb)
            if res and getattr(res, "detections", None):
                best_det = max(
                    res.detections,
                    key=lambda d: float(d.location_data.relative_bounding_box.width)
                    * float(d.location_data.relative_bounding_box.height),
                )
                box = best_det.location_data.relative_bounding_box
                face_cx = float(box.xmin + box.width * 0.5)
        except Exception:
            face_cx = None

    if face_cx is None and cascade is not None:
        try:
            faces = cascade.detectMultiScale(gray, 1.18, 4, minSize=(26, 26))
            if len(faces) > 0:
                fx, _, fw, _ = max(faces, key=lambda r: int(r[2]) * int(r[3]))
                face_cx = float((fx + fw * 0.5) / max(1, w))
        except Exception:
            face_cx = None

    # OpenCV Sobel gradient + HSV saturation + temporal motion saliency
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32) * 0.35
    motion = np.zeros_like(mag)
    if prev_gray is not None and prev_gray.shape == gray_full.shape:
        motion = cv2.absdiff(gray, prev_gray[:roi_h, :]).astype(np.float32) * 0.50

    # Detect framed 16:9 documentary layouts BEFORE face short-circuit:
    # horizontal inset border lines (e.g., parallax_25d_photo, broll_video_pip, newspaper, cards)
    # and dark outer pillar/letterbox studio margins framing an interior graphic.
    abs_gy = np.abs(gy)
    row_line_cov = np.mean(abs_gy[8 : max(9, roi_h - 6), 48:432] > 42.0, axis=1)
    max_hline = float(np.max(row_line_cov)) if row_line_cov.size else 0.0
    outer_l = float(np.mean(gray[:, :34]))
    outer_r = float(np.mean(gray[:, 446:]))
    outer_t = float(np.mean(gray[:14, :]))
    inner_mean = float(np.mean(gray[22 : min(roi_h, 180), 56:424]))
    has_doc_frame = (
        (max_hline >= 0.44)
        or (max(outer_l, outer_r) < 42.0 and inner_mean > max(outer_l, outer_r) + 18.0)
        or (outer_t < 32.0 and max_hline >= 0.36)
    )

    if face_cx is not None:
        cx_norm = max(0.20, min(0.80, face_cx))
        # Preserve sleek CinemaScope framing when the face lives inside a framed 16:9 documentary UI layout;
        # only use dramatic full-bleed portrait tracking on unframed raw 16:9 camera footage.
        return cx_norm, (1.0 if has_doc_frame else 0.0), gray_full

    col_energy = np.mean(mag + sat + motion, axis=0) + 1e-4
    xs = np.linspace(0.0, 1.0, len(col_energy))
    # Mild center prior prevents drifting into empty dark margins
    center_prior = 0.75 + 0.25 * np.exp(-((xs - 0.5) / 0.34) ** 2)
    weighted = col_energy * center_prior
    cx_norm = float(np.sum(xs * weighted) / max(1e-6, float(np.sum(weighted))))
    cx_norm = max(0.22, min(0.78, cx_norm))

    # Wide investigative graphic / archival newspaper / title card / timeline / red-string board detection
    l_edge = float(np.mean(mag[:, 24:158] > 55.0))
    c_edge = float(np.mean(mag[:, 158:322] > 55.0))
    r_edge = float(np.mean(mag[:, 322:456] > 55.0))
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    hl = float(np.mean(lap[:, 24:158] > 35.0))
    hr = float(np.mean(lap[:, 322:456] > 35.0))
    side_balance = min(l_edge, r_edge) / max(1e-4, c_edge)
    bright_lr = min(
        float(np.mean(gray[:, 24:158] > 155)),
        float(np.mean(gray[:, 322:456] > 155)),
    )

    is_wide_graphic = (
        has_doc_frame
        or (bright_lr >= 0.14)
        or (side_balance >= 0.50 and min(l_edge, r_edge) >= 0.048 and min(hl, hr) >= 0.045)
    )
    return cx_norm, (1.0 if is_wide_graphic else 0.0), gray_full


def _analyze_clip_tracking_and_framing(
    clip_mp4: Path,
    fps: float = 30.0,
    sample_step_s: float = 0.5,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """Sample horizontal center-of-interest (`cx`) and wide-graphic framing score every 0.5s
    across `clip_mp4`, then smoothly interpolate frame-by-frame with cubic Hermite (PCHIP) +
    fluid-head velocity damping (zero jitter, zero overshoot).
    """
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(clip_mp4))
    if not cap.isOpened():
        return np.array([0.50], dtype=np.float64), np.array([0.0], dtype=np.float64), 1

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps_in = float(cap.get(cv2.CAP_PROP_FPS) or fps or 30.0)
    step_f = max(1, int(round(fps_in * sample_step_s)))

    mp_detector, cascade = _create_face_detectors()
    sample_frames: List[int] = []
    sample_cx: List[float] = []
    sample_wide: List[float] = []
    prev_gray: Optional[np.ndarray] = None

    fi = 0
    last_frame_bgr: Optional[np.ndarray] = None
    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok or frame_bgr is None:
                break
            last_frame_bgr = frame_bgr
            if fi % step_f == 0:
                cx, ws, prev_gray = _analyze_frame_coi_and_layout(frame_bgr, mp_detector, cascade, prev_gray)
                sample_frames.append(fi)
                sample_cx.append(cx)
                sample_wide.append(ws)
            fi += 1
        actual_frames = max(1, fi)
        if last_frame_bgr is not None and (not sample_frames or sample_frames[-1] < actual_frames - 1):
            cx, ws, _ = _analyze_frame_coi_and_layout(last_frame_bgr, mp_detector, cascade, prev_gray)
            sample_frames.append(actual_frames - 1)
            sample_cx.append(cx)
            sample_wide.append(ws)
    finally:
        cap.release()
        if mp_detector is not None:
            try:
                mp_detector.close()
            except Exception:
                pass

    n_frames = max(1, total_frames if total_frames > 0 else (sample_frames[-1] + 1 if sample_frames else 1))
    if not sample_frames:
        return np.full(n_frames, 0.50, dtype=np.float64), np.zeros(n_frames, dtype=np.float64), n_frames

    if len(sample_frames) == 1:
        return (
            np.full(n_frames, sample_cx[0], dtype=np.float64),
            np.full(n_frames, sample_wide[0], dtype=np.float64),
            n_frames,
        )

    # 3-tap smoothing on raw 0.5s samples eliminates single-frame detection glitches
    cx_arr = np.asarray(sample_cx, dtype=np.float64)
    w_arr = np.asarray(sample_wide, dtype=np.float64)
    if len(cx_arr) >= 3:
        sm_cx = cx_arr.copy()
        sm_cx[1:-1] = 0.22 * cx_arr[:-2] + 0.56 * cx_arr[1:-1] + 0.22 * cx_arr[2:]
        cx_arr = sm_cx
        # Suppress isolated 0.5s wide-graphic flickers
        sm_w = w_arr.copy()
        for i in range(1, len(w_arr) - 1):
            if w_arr[i - 1] == w_arr[i + 1]:
                sm_w[i] = w_arr[i - 1]
        w_arr = sm_w

    t_samples = np.asarray(sample_frames, dtype=np.float64)
    t_all = np.arange(n_frames, dtype=np.float64)
    cx_interp = PchipInterpolator(t_samples, cx_arr, extrapolate=True)(t_all)
    w_interp = PchipInterpolator(t_samples, w_arr, extrapolate=True)(t_all)

    # Fluid-head camera damping for silky Steadicam-like pan velocity
    cx_smooth = np.empty_like(cx_interp)
    cx_smooth[0] = float(np.clip(cx_interp[0], 0.20, 0.80))
    max_step = 0.0045  # max ~13.5% frame width per second at 30fps
    for i in range(1, n_frames):
        target = float(np.clip(cx_interp[i], 0.20, 0.80))
        desired = cx_smooth[i - 1] + 0.16 * (target - cx_smooth[i - 1])
        delta = max(-max_step, min(max_step, desired - cx_smooth[i - 1]))
        cx_smooth[i] = cx_smooth[i - 1] + delta

    # Clip-level CinemaScope hysteresis: if >=35% of sampled frames in this Short contain framed 16:9
    # documentary UI cards/borders/boards, keep sleek CinemaScope bleed consistently across the clip
    # so transitions never jolt mid-Short and documentary cards/captions never clip or collide.
    if float(np.mean(w_arr >= 0.5)) >= 0.35:
        wide_smooth = np.ones(n_frames, dtype=np.float64)
    else:
        # Cosine-eased smooth layout blend in [0.0, 1.0]
        w_clamped = np.clip(w_interp, 0.0, 1.0)
        # Apply gentle 12-frame moving average (~0.4s) so layout shifts glide smoothly
        if n_frames > 12:
            k = np.ones(12, dtype=np.float64) / 12.0
            w_clamped = np.convolve(np.pad(w_clamped, (6, 5), mode="edge"), k, mode="valid")[:n_frames]
        wide_smooth = 0.5 - 0.5 * np.cos(math.pi * np.clip(w_clamped, 0.0, 1.0))
    return cx_smooth, wide_smooth, n_frames


def _detect_horizontal_center_of_interest(video_16x9: Path, start_s: float, dur_s: float) -> float:
    """Backward-compatible helper returning median horizontal subject centroid [0.22..0.78]
    sampled every 0.5s across [start_s, start_s + dur_s].
    """
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(video_16x9))
    if not cap.isOpened():
        return 0.50

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    mp_detector, cascade = _create_face_detectors()
    centers: List[float] = []
    prev_gray: Optional[np.ndarray] = None
    n_steps = max(3, int(round(dur_s / 0.5)) + 1)
    try:
        for t in np.linspace(start_s, start_s + max(0.2, dur_s), num=min(n_steps, 24)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            cx, _, prev_gray = _analyze_frame_coi_and_layout(frame, mp_detector, cascade, prev_gray)
            centers.append(cx)
    finally:
        cap.release()
        if mp_detector is not None:
            try:
                mp_detector.close()
            except Exception:
                pass
    return float(np.median(centers)) if centers else 0.50


def _score_window_impact(words: List[Dict[str, Any]], st_s: float, en_s: float) -> float:
    """Zero-token impact scorer for a candidate Short window [st_s, en_s]:
    Rewards high-retention figures ($, %, digits), cliffhanger questions (?), exclamations (!),
    high-tension mystery/finance/history hook keywords, and brisk speaking cadence.
    """
    score = 1.0
    win_words = [
        str(w.get("word", ""))
        for w in words
        if float(w.get("end", 0.0)) >= st_s and float(w.get("start", 0.0)) <= en_s
    ]
    if not win_words:
        return score
    score += len(win_words) * 0.35
    impact_keywords = {
        "bilhão", "bilhões", "milhões", "billion", "billions", "millions",
        "segredo", "secret", "fraude", "fraud", "colapso", "collapse",
        "macabra", "macabro", "sombrio", "sombria", "proibido", "proibida",
        "ritual", "krampus", "terror", "morte", "verdade", "mistério",
        "nunca", "crime", "maldição", "oculto", "oculta", "história",
        "dark", "forbidden", "banned", "truth", "never", "hidden", "mystery",
        "curse", "death", "horror", "ritual", "sinister",
    }
    for wd in win_words:
        if "?" in wd:
            score += 3.5
        if "!" in wd:
            score += 2.0
        if any(c.isdigit() for c in wd) or "$" in wd or "%" in wd:
            score += 4.0
        low = wd.lower().strip(".,!?;:\"'()[]")
        if low in impact_keywords:
            score += 3.0
    return round(score, 2)


def _select_5_highest_impact_windows(
    total_dur: float,
    words: List[Dict[str, Any]],
    n_clips: int = 5,
) -> List[Tuple[float, float, float]]:
    """Select `n_clips` (default 5) highest-impact time windows (start_s, end_s, impact_score)
    distributed across the 16:9 video acts.
    """
    n_clips = max(1, min(5, int(n_clips)))
    clip_dur = min(15.0, max(3.5, total_dur / float(max(2.5, n_clips * 0.85))))
    if total_dur <= clip_dur + 0.5:
        return [(0.0, round(total_dur, 2), _score_window_impact(words, 0.0, total_dur)) for _ in range(n_clips)]

    max_start = max(0.0, total_dur - clip_dur)
    zone_span = max_start / float(max(1, n_clips))
    selected: List[Tuple[float, float, float]] = []

    for idx in range(n_clips):
        z_start = idx * zone_span
        z_end = min(max_start, (idx + 1) * zone_span)
        candidates = np.linspace(z_start, z_end, num=5) if z_end > z_start + 0.2 else [z_start]
        best_st = float(candidates[0])
        best_score = -1.0
        for cand in candidates:
            st = round(float(max(0.0, min(max_start, cand))), 2)
            en = round(min(total_dur, st + clip_dur), 2)
            sc = _score_window_impact(words, st, en)
            if sc > best_score:
                best_score = sc
                best_st = st
        selected.append((best_st, round(min(total_dur, best_st + clip_dur), 2), best_score))

    return selected


def _build_cinema_vignette_image(out_w: int, out_h: int) -> skia.Image:
    """Pre-render a smooth radial cinema vignette overlay for instant per-frame compositing."""
    vs = skia.Surface(out_w, out_h)
    vc = vs.getCanvas()
    vc.clear(skia.Color4f(0, 0, 0, 0))
    rad = math.hypot(out_w * 0.5, out_h * 0.5) * 1.06
    vp = skia.Paint(AntiAlias=True)
    vp.setShader(
        skia.GradientShader.MakeRadial(
            (out_w * 0.5, out_h * 0.45),
            rad,
            [
                skia.ColorSetARGB(0, 6, 7, 12),
                skia.ColorSetARGB(0, 6, 7, 12),
                skia.ColorSetARGB(62, 6, 7, 12),
                skia.ColorSetARGB(148, 4, 5, 10),
            ],
            [0.0, 0.46, 0.78, 1.0],
        )
    )
    vc.drawRect(skia.Rect.MakeWH(out_w, out_h), vp)
    return vs.makeImageSnapshot()


def _warp_subpixel_crop(
    frame_bgr: np.ndarray,
    cx_norm: float,
    zoom: float,
    dst_w: int,
    dst_h: int,
    src_y_crop_ratio: float = 1.0,
) -> np.ndarray:
    """Subpixel-accurate smooth pan & zoom warp from 16:9 source into (dst_w, dst_h)."""
    src_h_full, src_w = frame_bgr.shape[:2]
    src_h = max(64, int(round(src_h_full * max(0.5, min(1.0, src_y_crop_ratio)))))
    base_scale = max(dst_w / float(src_w), dst_h / float(src_h))
    scale = base_scale * max(1.0, float(zoom))

    vis_w = dst_w / scale
    vis_h = dst_h / scale
    cx_px = float(np.clip(cx_norm * src_w, vis_w * 0.5, max(vis_w * 0.5, src_w - vis_w * 0.5)))
    cy_px = float(np.clip(src_h * 0.5, vis_h * 0.5, max(vis_h * 0.5, src_h - vis_h * 0.5)))

    tx = dst_w * 0.5 - cx_px * scale
    ty = dst_h * 0.5 - cy_px * scale
    mat = np.array([[scale, 0.0, tx], [0.0, scale, ty]], dtype=np.float32)
    return cv2.warpAffine(
        frame_bgr,
        mat,
        (dst_w, dst_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _render_blurred_cinema_bleed(frame_bgr: np.ndarray, cx_norm: float, out_w: int, out_h: int) -> np.ndarray:
    """Fast silky-bokeh darkened vertical background bleed for wide investigative graphic framing."""
    small_w, small_h = 135, 240
    cropped_sm = _warp_subpixel_crop(frame_bgr, cx_norm, zoom=1.18, dst_w=small_w, dst_h=small_h)
    blurred = cv2.GaussianBlur(cropped_sm, (23, 23), 0)
    # Atmospheric dark-cinema grade so foreground wide board pops with zero clutter
    dark = np.clip(blurred.astype(np.float32) * 0.36, 0, 255).astype(np.uint8)
    return cv2.resize(dark, (out_w, out_h), interpolation=cv2.INTER_LINEAR)


def _draw_glassmorphic_cta(
    canvas: skia.Canvas,
    out_w: int,
    out_h: int,
    cta_label: str,
    cta_font: skia.Font,
    alpha_mul: float = 1.0,
) -> None:
    """Render a subtle frosted-glass cinema CTA strip near the bottom of the 9:16 Short."""
    if alpha_mul <= 0.01:
        return
    clean_txt = str(cta_label or "ASSISTA COMPLETO NO CANAL").lstrip("▶► ").strip().upper()
    tw = float(cta_font.measureText(clean_txt))
    badge_d = 26.0
    gap = 12.0
    pad_x = 22.0
    inner_w = badge_d + gap + tw
    pill_w = inner_w + pad_x * 2.0
    pill_h = 52.0
    max_pill_w = out_w * 0.84
    scale = min(1.0, max_pill_w / max(1.0, pill_w))

    cx = out_w * 0.5
    cy = out_h - 118.0
    a_bg_top = int(round(176 * alpha_mul))
    a_bg_bot = int(round(212 * alpha_mul))
    a_border_top = int(round(92 * alpha_mul))
    a_border_bot = int(round(28 * alpha_mul))
    a_shadow = int(round(135 * alpha_mul))
    a_text = int(round(240 * alpha_mul))
    a_accent = int(round(235 * alpha_mul))

    canvas.save()
    canvas.translate(cx, cy)
    canvas.scale(scale, scale)

    rect = skia.Rect.MakeXYWH(-pill_w * 0.5, -pill_h * 0.5, pill_w, pill_h)
    r_rad = pill_h * 0.5

    # Frosted dark smoked-glass body + subtle drop shadow
    bg_paint = skia.Paint(AntiAlias=True)
    bg_paint.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, -pill_h * 0.5), (0.0, pill_h * 0.5)],
            [skia.ColorSetARGB(a_bg_top, 24, 27, 40), skia.ColorSetARGB(a_bg_bot, 10, 12, 20)],
        )
    )
    bg_paint.setImageFilter(
        skia.ImageFilters.DropShadow(0.0, 6.0, 14.0, 14.0, skia.ColorSetARGB(a_shadow, 0, 0, 0))
    )
    canvas.drawRoundRect(rect, r_rad, r_rad, bg_paint)

    # Fine specular glass rim highlight
    border_paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.5)
    border_paint.setShader(
        skia.GradientShader.MakeLinear(
            [(0.0, -pill_h * 0.5), (0.0, pill_h * 0.5)],
            [skia.ColorSetARGB(a_border_top, 255, 255, 255), skia.ColorSetARGB(a_border_bot, 255, 255, 255)],
        )
    )
    canvas.drawRoundRect(rect, r_rad, r_rad, border_paint)

    # Crisp vector play badge (guaranteed zero tofu/missing-glyph box)
    left_x = -inner_w * 0.5
    play_cx = left_x + badge_d * 0.5
    canvas.drawCircle(
        play_cx,
        0.0,
        badge_d * 0.5,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(a_accent, 255, 209, 102)),
    )
    tri = skia.Path()
    tri.moveTo(play_cx - 3.5, -5.5)
    tri.lineTo(play_cx + 6.0, 0.0)
    tri.lineTo(play_cx - 3.5, 5.5)
    tri.close()
    canvas.drawPath(tri, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(a_text, 12, 13, 20)))

    # Crisp ivory uppercase CTA label
    fm = cta_font.getMetrics()
    baseline_y = (abs(float(fm.fAscent)) - abs(float(fm.fDescent))) * 0.5
    txt_x = left_x + badge_d + gap
    canvas.drawString(
        clean_txt,
        txt_x,
        baseline_y,
        cta_font,
        skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(a_text, 244, 246, 252)),
    )
    canvas.restore()


def _mix_pro_short_audio(
    master_16x9_mp4: Path,
    st_s: float,
    seg_dur: float,
    out_audio_m4a: Path,
    thermal_limit_c: float = 85.0,
) -> Path:
    """Extract Short audio slice with smooth 0.25s fade-in/out and mix Hollywood
    `flash_impact.wav` + `whoosh_fast.wav` directly onto the Short's audio track (zero pops/clipping).
    """
    sfx_dir = ASSETS_DIR / "sfx"
    flash_wav = sfx_dir / "flash_impact.wav"
    whoosh_wav = sfx_dir / "whoosh_fast.wav"
    has_src_audio = _has_audio_stream(master_16x9_mp4)
    fade_out_st = max(0.0, seg_dur - 0.25)

    inputs: List[str] = []
    filter_parts: List[str] = []
    mix_labels: List[str] = []
    next_idx = 0

    if has_src_audio:
        inputs.extend(["-ss", f"{st_s:.3f}", "-t", f"{seg_dur:.3f}", "-i", str(master_16x9_mp4)])
        filter_parts.append(
            f"[{next_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"afade=t=in:st=0:d=0.25,apad=whole_dur={seg_dur:.3f},atrim=0:{seg_dur:.3f},asetpts=PTS-STARTPTS[base]"
        )
    else:
        inputs.extend(["-f", "lavfi", "-t", f"{seg_dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
        filter_parts.append(f"[{next_idx}:a]atrim=0:{seg_dur:.3f},asetpts=PTS-STARTPTS[base]")
    mix_labels.append("[base]")
    next_idx += 1

    if flash_wav.exists():
        inputs.extend(["-i", str(flash_wav)])
        filter_parts.append(
            f"[{next_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume=0.52,adelay=15|15,apad=whole_dur={seg_dur:.3f},atrim=0:{seg_dur:.3f}[sfx_flash]"
        )
        mix_labels.append("[sfx_flash]")
        next_idx += 1

    if whoosh_wav.exists():
        inputs.extend(["-i", str(whoosh_wav)])
        filter_parts.append(
            f"[{next_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume=0.42,adelay=0|0,apad=whole_dur={seg_dur:.3f},atrim=0:{seg_dur:.3f}[sfx_whoosh]"
        )
        mix_labels.append("[sfx_whoosh]")
        next_idx += 1

    if len(mix_labels) == 1:
        filter_parts.append(
            f"[base]afade=t=out:st={fade_out_st:.3f}:d=0.25,alimiter=limit=0.95[aout]"
        )
    else:
        joined = "".join(mix_labels)
        filter_parts.append(
            f"{joined}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0,"
            f"afade=t=out:st={fade_out_st:.3f}:d=0.25,alimiter=limit=0.95[aout]"
        )

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
            "[aout]",
            "-t",
            f"{seg_dur:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out_audio_m4a),
        ],
        thermal_limit_c=thermal_limit_c,
    )
    return out_audio_m4a


def extract_5_viral_shorts_from_16x9(
    master_16x9_mp4: Union[str, Path],
    words: List[Dict[str, Any]],
    output_dir: Union[str, Path],
    max_shorts: int = 5,
    thermal_limit_c: float = 85.0,
    caption_style: str = "hormozi_neon",
) -> List[Dict[str, Any]]:
    """Extract up to 5 Pro Cinema vertical 9:16 (1080x1920) Shorts from a 16:9 master video.
    Zero LLM tokens:
    - Dynamic 0.5s active-subject tracking (MediaPipe/OpenCV saliency) with cubic Hermite (PCHIP) smoothing
    - Hook punch-in zoom (1.00x -> 1.10x over 1.4s) + 3-frame cinema flash transition + radial vignette
    - Sleek blur-framed upper/lower cinema bleed when framing wide investigative graphics/newspapers/boards
    - Mixes Hollywood `flash_impact.wav` + `whoosh_fast.wav` with 0.25s smooth fade-in/fade-out
    - Kinetic vertical Hormozi captions (`draw_kinetic_captions`) + subtle glassmorphic CTA strip
    """
    master_16x9_mp4 = Path(master_16x9_mp4)
    output_dir = Path(output_dir)
    shorts_dir = output_dir / "shorts_cascade"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    total_dur = max(4.0, _get_wav_duration(master_16x9_mp4))

    # Guarantee Hollywood cinema transition SFX are synthesized and up to date
    try:
        ensure_pro_cinema_sfx(force=False, thermal_limit_c=thermal_limit_c)
    except Exception:
        pass

    # Auto-recover words from output_dir/words.json or synthesize fallback word timestamps if empty
    if not words:
        words_file = output_dir / "words.json"
        if words_file.exists():
            try:
                words = json.loads(words_file.read_text(encoding="utf-8"))
            except Exception:
                words = []
    if not words:
        fallback_line = "ASSISTA AO DOCUMENTÁRIO COMPLETO NO CANAL AGORA MESMO " * max(2, int(total_dur // 4))
        words = _estimate_word_timestamps(fallback_line.strip(), total_dur)

    sample_text = " ".join(str(w.get("word", "")) for w in words[:40])
    detected_lang = _detect_lang(sample_text)
    cta_base = LANG_VOICE_PROFILES.get(detected_lang, LANG_VOICE_PROFILES["pt_br"])["cta_tag"]

    n_clips = min(max_shorts, 5)
    windows = _select_5_highest_impact_windows(total_dur, words, n_clips=n_clips)

    caption_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="cascade_short_caption")
    cta_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="cascade_short_cta")
    cta_font = skia.Font(cta_tf, 24.0)

    extracted: List[Dict[str, Any]] = []
    out_w, out_h = 1080, 1920
    fps = 30
    vignette_img = _build_cinema_vignette_image(out_w, out_h)

    for idx, (st_s, en_s, impact_score) in enumerate(windows):
        seg_dur = max(3.0, round(en_s - st_s, 2))
        raw_src_mp4 = shorts_dir / f"_raw_src_16x9_{idx + 1:02d}.mp4"
        mixed_audio_m4a = shorts_dir / f"_raw_short_audio_{idx + 1:02d}.m4a"

        # 1. Extract frame-accurate 16:9 30fps video slice (full width preserved for dynamic tracking & bleed framing)
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{st_s:.3f}",
                "-t",
                f"{seg_dur:.3f}",
                "-i",
                str(master_16x9_mp4),
                "-vf",
                f"fps={fps}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "18",
                str(raw_src_mp4),
            ],
            thermal_limit_c=thermal_limit_c,
        )

        # 2. Mix Pro Cinema Short audio (0.25s smooth fade-in/out + flash_impact.wav + whoosh_fast.wav)
        _mix_pro_short_audio(
            master_16x9_mp4=master_16x9_mp4,
            st_s=st_s,
            seg_dur=seg_dur,
            out_audio_m4a=mixed_audio_m4a,
            thermal_limit_c=thermal_limit_c,
        )

        # 3. Dynamic 0.5s active-subject tracking + wide-graphic framing analysis with cubic smoothing
        cx_curve, wide_curve, _ = _analyze_clip_tracking_and_framing(raw_src_mp4, fps=float(fps), sample_step_s=0.5)
        median_cx = float(np.median(cx_curve)) if len(cx_curve) else 0.50
        wide_ratio = float(np.mean(wide_curve > 0.5)) if len(wide_curve) else 0.0

        # 4. Slice & shift word timestamps for this Short
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
        if not seg_words:
            seg_words = _estimate_word_timestamps(f"PARTE {idx + 1} DO DOCUMENTÁRIO COMPLETO", seg_dur)
        chunks = group_words_into_chunks(seg_words, max_words=3)

        # 5. Composite Pro Cinema 9:16 video stream frame-by-frame in Skia C++
        final_short_mp4 = shorts_dir / f"short_{idx + 1:02d}_9x16.mp4"
        cap = cv2.VideoCapture(str(raw_src_mp4))
        surface = skia.Surface(out_w, out_h)

        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=20)
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            *pre_args,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{out_w}x{out_h}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-i",
            str(mixed_audio_m4a),
            "-vf",
            hw_suffix,
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-t",
            f"{seg_dur:.3f}",
            *enc_args,
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(final_short_mp4),
        ]
        thermal_guard_wait(limit_c=thermal_limit_c)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=get_vaapi_env(),
            preexec_fn=nice_preexec,
        )
        assert proc.stdin is not None

        fi = 0
        try:
            while True:
                ok, frame_bgr = cap.read()
                if not ok or frame_bgr is None:
                    break
                t = fi / float(fps)
                c_idx = min(fi, len(cx_curve) - 1)
                cx_t = float(cx_curve[c_idx])
                wide_t = float(wide_curve[c_idx])

                # Dynamic Hook Punch-In Zoom: smooth 1.00x -> 1.10x over first 1.4s, then gentle cinema life
                if t <= 1.4:
                    p = t / 1.4
                    ease_out = 1.0 - (1.0 - p) ** 3
                    zoom_t = 1.00 + 0.10 * ease_out
                else:
                    rest_p = min(1.0, (t - 1.4) / max(1.0, seg_dur - 1.4))
                    zoom_t = 1.10 - 0.045 * rest_p + 0.007 * math.sin((t - 1.4) * 1.15)

                c = surface.getCanvas()
                c.clear(skia.ColorBLACK)

                if wide_t < 0.03:
                    # Full-bleed smooth Steadicam vertical tracking (crop bottom 12% to avoid legacy 16:9 subtitle bleed)
                    framed_bgr = _warp_subpixel_crop(frame_bgr, cx_t, zoom_t, out_w, out_h, src_y_crop_ratio=0.88)
                    framed_bgra = cv2.cvtColor(framed_bgr, cv2.COLOR_BGR2BGRA)
                    img = skia.Image.frombytes(
                        framed_bgra.tobytes(),
                        (out_w, out_h),
                        skia.kBGRA_8888_ColorType,
                        skia.kPremul_AlphaType,
                    )
                    c.drawImage(img, 0, 0)
                else:
                    # Sleek blur-framed upper/lower cinema bleed for wide investigative graphics/newspapers/boards
                    bg_bleed_bgr = _render_blurred_cinema_bleed(frame_bgr, cx_t, out_w, out_h)
                    bg_bleed_bgra = cv2.cvtColor(bg_bleed_bgr, cv2.COLOR_BGR2BGRA)
                    bg_img = skia.Image.frombytes(
                        bg_bleed_bgra.tobytes(),
                        (out_w, out_h),
                        skia.kBGRA_8888_ColorType,
                        skia.kPremul_AlphaType,
                    )
                    c.drawImage(bg_img, 0, 0)

                    # Smoothly interpolate foreground window from full-bleed -> sleek CinemaScope framed window
                    # (1044x480 with y_crop=0.815 matches 1920x880 aspect = 2.18:1 -> 0% horizontal clipping
                    # AND cleanly trims off legacy 16:9 bottom subtitles at y>=82%!)
                    fg_x = 18.0 * wide_t
                    fg_y = 455.0 * wide_t
                    fg_w = max(64, int(round(out_w - 36.0 * wide_t)))
                    fg_h = max(64, int(round(out_h - (out_h - 480.0) * wide_t)))
                    # Blend pan center gently toward 0.50 in wide mode so full-width headlines stay perfectly centered
                    eff_cx = cx_t * (1.0 - 0.85 * wide_t) + 0.50 * (0.85 * wide_t)
                    eff_zoom = 1.0 + (zoom_t - 1.0) * (1.0 - 0.78 * wide_t)
                    y_crop = 1.0 - 0.185 * wide_t
                    fg_bgr = _warp_subpixel_crop(
                        frame_bgr,
                        eff_cx,
                        zoom=eff_zoom,
                        dst_w=fg_w,
                        dst_h=fg_h,
                        src_y_crop_ratio=y_crop,
                    )
                    fg_bgra = cv2.cvtColor(fg_bgr, cv2.COLOR_BGR2BGRA)
                    fg_img = skia.Image.frombytes(
                        fg_bgra.tobytes(),
                        (fg_w, fg_h),
                        skia.kBGRA_8888_ColorType,
                        skia.kPremul_AlphaType,
                    )

                    fg_rect = skia.Rect.MakeXYWH(fg_x, fg_y, float(fg_w), float(fg_h))
                    corner_r = 22.0 * wide_t

                    # Soft dark elevation shadow behind wide graphic window
                    sh_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(195 * wide_t), 0, 0, 0))
                    sh_paint.setImageFilter(
                        skia.ImageFilters.DropShadowOnly(0.0, 14.0, 26.0, 26.0, skia.ColorSetARGB(int(185 * wide_t), 0, 0, 0))
                    )
                    c.drawRoundRect(fg_rect, corner_r, corner_r, sh_paint)

                    # Clipped crisp rounded wide cinema window
                    c.save()
                    clip_p = skia.Path()
                    clip_p.addRoundRect(fg_rect, corner_r, corner_r)
                    c.clipPath(clip_p, doAntiAlias=True)
                    c.drawImage(fg_img, fg_x, fg_y)
                    c.restore()

                    # Delicate frosty hairline cinema border
                    rim_paint = skia.Paint(
                        AntiAlias=True,
                        Style=skia.Paint.kStroke_Style,
                        StrokeWidth=1.8,
                        Color=skia.ColorSetARGB(int(72 * wide_t), 255, 255, 255),
                    )
                    c.drawRoundRect(fg_rect, corner_r, corner_r, rim_paint)

                # Cinema radial vignette for instant Netflix/A24 depth
                c.drawImage(vignette_img, 0, 0)

                # Lower-third contrast scrim so vertical captions & CTA always pop cleanly
                scrim = skia.Paint()
                scrim.setShader(
                    skia.GradientShader.MakeLinear(
                        [(0, out_h * 0.68), (0, out_h)],
                        [
                            skia.ColorSetARGB(0, 8, 7, 14),
                            skia.ColorSetARGB(150, 8, 7, 14),
                            skia.ColorSetARGB(232, 6, 6, 12),
                        ],
                        [0.0, 0.45, 1.0],
                    )
                )
                c.drawRect(skia.Rect.MakeXYWH(0, out_h * 0.68, out_w, out_h * 0.32), scrim)

                # Clean modern vertical Kinetic Hormozi Captions (strictly 1 active word pill, drop shadow)
                _draw_captions_pro(
                    c,
                    chunks,
                    t,
                    out_w,
                    out_h,
                    caption_tf,
                    style=caption_style,
                    y_ratio=0.775,
                    font_size=74.0,
                )

                # Subtle glassmorphic CTA strip fading in smoothly after the 3-frame flash impact
                cta_alpha = min(1.0, max(0.0, (t - 0.18) / 0.32))
                _draw_glassmorphic_cta(c, out_w, out_h, cta_base, cta_font, alpha_mul=cta_alpha)

                # Subtle 3-frame cinema flash transition right at t=0.0 (fi in 0, 1, 2)
                if fi < 3:
                    flash_alphas = (165, 92, 36)
                    fa = flash_alphas[fi]
                    fp = skia.Paint(AntiAlias=True)
                    fp.setShader(
                        skia.GradientShader.MakeRadial(
                            (out_w * 0.5, out_h * 0.44),
                            out_h * 0.65,
                            [
                                skia.ColorSetARGB(fa, 255, 250, 236),
                                skia.ColorSetARGB(int(fa * 0.55), 255, 224, 178),
                                skia.ColorSetARGB(int(fa * 0.25), 14, 12, 20),
                            ],
                            [0.0, 0.45, 1.0],
                        )
                    )
                    c.drawRect(skia.Rect.MakeWH(out_w, out_h), fp)
                    if fi == 0:
                        # Subtle anamorphic flash streak across optical center
                        streak_p = skia.Paint(AntiAlias=True)
                        streak_p.setShader(
                            skia.GradientShader.MakeLinear(
                                [(0.0, out_h * 0.44), (float(out_w), out_h * 0.44)],
                                [
                                    skia.ColorSetARGB(0, 255, 245, 220),
                                    skia.ColorSetARGB(135, 255, 248, 230),
                                    skia.ColorSetARGB(0, 255, 245, 220),
                                ],
                                [0.0, 0.5, 1.0],
                            )
                        )
                        c.drawRect(skia.Rect.MakeXYWH(0, out_h * 0.44 - 14, out_w, 28), streak_p)

                # Smooth cinema dark fade-out during the final 0.22s
                if seg_dur - t < 0.22:
                    fade_a = int(round(215.0 * min(1.0, max(0.0, (0.22 - (seg_dur - t)) / 0.22))))
                    c.drawRect(skia.Rect.MakeWH(out_w, out_h), skia.Paint(Color=skia.ColorSetARGB(fade_a, 6, 6, 10)))

                proc.stdin.write(surface.makeImageSnapshot().tobytes())
                fi += 1
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
        raw_src_mp4.unlink(missing_ok=True)
        mixed_audio_m4a.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Falha ao extrair corte 9:16 #{idx + 1}: {stderr.decode(errors='ignore')}")

        extracted.append(
            {
                "short_idx": idx + 1,
                "path": str(final_short_mp4),
                "start_s": st_s,
                "end_s": en_s,
                "duration_s": seg_dur,
                "impact_score": impact_score,
                "center_x_norm": round(median_cx, 3),
                "wide_bleed_ratio": round(wide_ratio, 3),
                "cta_tag": cta_base,
                "resolution": "1080x1920",
                "pro_cinema_cuts": True,
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
    niche: str = "Negócio Local",
) -> Tuple[Dict[str, Any], str]:
    """Create a high-converting local business video script (audited by Retention Doctor)
    AND a ready-to-copy WhatsApp outreach message for closing recurring B2B retainers.
    Delegates to `engine.b2b_pitch_maker.generate_b2b_pitch_bundle`.
    """
    bundle = generate_b2b_pitch_bundle(
        company_name=company_name,
        city=city,
        product_service=product_service,
        niche=niche,
    )
    return bundle["script"], bundle["whatsapp_pitch"]
