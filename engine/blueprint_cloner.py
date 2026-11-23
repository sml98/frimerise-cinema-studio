"""FrimeRise Autonomous Blueprint Cloner (Exact-Duration, Scene-Mirrored, Anti-Plagiarism 2D Animator).
Takes ANY VideoBlueprint extracted by engine/viral_cloner.py (from YouTube/TikTok/Reels URL or .mp4)
and automatically replicates:
  - EXACT duration_s (±0.05s)
  - EXACT aspect ratio & layout (4:5 1080x1350 with top header bar, 9:16 1080x1920, 16:9 1920x1080, 1:1)
  - EXACT scene cut timestamps, camera rhythms, poses & emotional beats
While guaranteeing ZERO plagiarism:
  - 100% original procedural 2D character designs (distinct colors, outfits, hair, accessories, voices)
  - Hue-shifted original 2D vector art backdrops drawn fresh in C++ Skia
  - Rewritten / adapted Brazilian Portuguese dialogue placed at exact source timestamps with 6-viseme lip-sync.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np
import skia

from agents.llm_router import _extract_json, get_settings, record_token_usage
from engine.audio_dsp import master_broadcast_audio
from engine.cartoon_2d_studio import (
    CartoonCharacter,
    VisualRig,
    VoicePreset,
    _synthesize_character_line,
)
from engine.cartoon_v2_renderer import (
    draw_cartoon_puppet_v2,
    draw_comic_speed_lines,
    draw_foreground_boat_v2,
    draw_parallax_scenery_v2,
)
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.rhubarb_lipsync import extract_rhubarb_visemes
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    _load_verified_typeface,
    _wrap_text_to_width,
    group_words_into_chunks,
    hex_to_skia,
)
from engine.viral_cloner import _paraphrase_line_brazilian

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"


# ---------------------------------------------------------------------------
# 1. Anti-Plagiarism Original Character Cast Generator
# ---------------------------------------------------------------------------
def build_original_cast(topic: str, blueprint: Dict[str, Any]) -> Tuple[CartoonCharacter, CartoonCharacter]:
    """Generate a 100% original 2-character cast visually distinct from any reference video."""
    tl = f"{topic} {blueprint.get('title', '')} {blueprint.get('transcript', '')[:400]}".lower()
    is_biblical = any(k in tl for k in ("jonas", "baleia", "piaba", "peixe", "nínive", "ninive", "bíblia", "biblia", "davi", "moisés", "noé", "rei", "profeta"))
    is_business = any(k in tl for k in ("empresa", "chefe", "dinheiro", "venda", "cliente", "bitcoin", "mercado", "salário", "escritório"))

    if is_biblical:
        # Distinct vibrant teal/gold & cobalt/crimson original outfits (never copying brown/gray original!)
        c_main = CartoonCharacter(
            char_id="protag",
            name="Protagonista",
            voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="+15Hz", rate="+11%"),
            visual_rig=VisualRig(
                skin_color="#F4C7A1",
                outfit="robe_biblical",
                accessory="beard_staff",
                primary_color="#0EA5E9",    # Vibrant cyan/blue tunic (totally distinct from brown!)
                secondary_color="#FFD166",  # Golden sash
                hair_color="#4A2511",
                pill_color_index=0,
            ),
        )
        c_other = CartoonCharacter(
            char_id="partner",
            name="Interlocutor",
            voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="-13Hz", rate="+8%"),
            visual_rig=VisualRig(
                skin_color="#E5B28D",
                outfit="king_crown",
                accessory="crown",
                primary_color="#7C3AED",    # Royal violet robe
                secondary_color="#FF2E93",
                hair_color="#1F2937",
                pill_color_index=1,
            ),
        )
        return c_main, c_other

    if is_business:
        c_main = CartoonCharacter(
            char_id="protag",
            name="Protagonista",
            voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="+15Hz", rate="+11%"),
            visual_rig=VisualRig(
                skin_color="#F2C6A0",
                outfit="modern_hoodie",
                accessory="cap",
                primary_color="#B388FF",
                secondary_color="#B8FF01",
                hair_color="#231815",
                pill_color_index=0,
            ),
        )
        c_other = CartoonCharacter(
            char_id="partner",
            name="Chefe",
            voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="-13Hz", rate="+8%"),
            visual_rig=VisualRig(
                skin_color="#E6B08A",
                outfit="suit_boss",
                accessory="tie",
                primary_color="#1E293B",
                secondary_color="#FF2E93",
                hair_color="#374151",
                pill_color_index=1,
            ),
        )
        return c_main, c_other

    c_main = CartoonCharacter(
        char_id="protag",
        name="Personagem A",
        voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="+14Hz", rate="+10%"),
        visual_rig=VisualRig(
            skin_color="#F3C5A2",
            outfit="modern_hoodie",
            accessory="none",
            primary_color="#FF2E93",
            secondary_color="#FFD166",
            hair_color="#2A1B12",
            pill_color_index=0,
        ),
    )
    c_other = CartoonCharacter(
        char_id="partner",
        name="Personagem B",
        voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-FranciscaNeural", pitch="+2Hz", rate="+9%"),
        visual_rig=VisualRig(
            skin_color="#E8B892",
            outfit="sailor",
            accessory="cap",
            primary_color="#10B981",
            secondary_color="#FFFFFF",
            hair_color="#1F2937",
            pill_color_index=1,
        ),
    )
    return c_main, c_other


# ---------------------------------------------------------------------------
# 2. Original Non-Plagiarized Dialogue Adapter (Keeps Exact Timestamps)
# ---------------------------------------------------------------------------
def _rewrite_segments_anti_plagiarism(
    segments: List[Dict[str, Any]],
    topic: str,
    ref_title: str,
    tone: str,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """Rewrite header title & dialogue segments into coherent, funny, 100% original PT-BR
    keeping exact timestamps. Automatically fails over between Gemini and DeepSeek!
    Returns (header_title, rewritten_segments, provider_used).
    """
    clean_header = topic.strip() if topic.strip() else ref_title.strip()
    if not clean_header or clean_header.lower().startswith("clone viral"):
        clean_header = ref_title.strip() or "História Animada"
    if "piaba" in clean_header.lower():
        clean_header = clean_header.replace("piaba", "baleia gigante").replace("Piaba", "Baleia Gigante")
    elif "jonas" in clean_header.lower() and ":" not in clean_header:
        clean_header = "A Fuga de Jonas e o Peixe Gigante:"
    elif not clean_header.endswith(":"):
        clean_header = clean_header[:44] + ":"

    if not segments:
        return clean_header, [], "none"

    settings = get_settings()
    model_choice = settings.get("default_llm") or "deepseek-flash"
    gkey = (settings.get("gemini_api_key") or "").strip()
    dkey = (settings.get("deepseek_api_key") or "").strip()

    # Build ordered provider list so if the primary fails (e.g. HTTP 400), it ALWAYS fails over to the other!
    providers: List[str] = []
    if "deepseek" in model_choice:
        if dkey:
            providers.append("deepseek")
        if gkey:
            providers.append("gemini")
    else:
        if gkey:
            providers.append("gemini")
        if dkey:
            providers.append("deepseek")

    compact_in = [
        {"i": s["idx"], "sp": int(s.get("speaker_slot", 0)), "dur": round(float(s["end"]) - float(s["start"]), 1), "t": s["text"][:140]}
        for s in segments
    ]
    sys_p = (
        "Você é roteirista sênior de animações de comédia em Português-BR (estilo @animabible7 e OverSimplified). "
        "Os trechos abaixo vieram de uma transcrição automática (Whisper) que pode conter erros fonéticos ou palavras sem sentido. "
        f"Sua missão: reconstruir e reescrever TODA a conversa em Português-BR 100% coerente, natural, engraçada e original (sem plágio), "
        f"seguindo o tema '{clean_header}' no tom '{tone}'. "
        "REGRAS OBRIGATÓRIAS:\n"
        "1. Corrija completamente qualquer palavra mal transcrita para falas claras que façam 100% sentido na história.\n"
        "2. Mantenha EXATAMENTE o mesmo número de itens e o mesmo índice 'i' (cada fala deve caber no tempo 'dur' em segundos).\n"
        "3. Mantenha o diálogo dinâmico entre sp=0 (protagonista) e sp=1 (interlocutor).\n"
        'Retorne APENAS JSON válido: {"header":"Título curto:","lines":[{"i":0,"t":"Fala limpa e engraçada"},...]}'
    )
    user_p = json.dumps(compact_in, ensure_ascii=False)

    for prov in providers:
        try:
            raw_json = None
            if prov == "gemini":
                for gm in ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                    r = httpx.post(
                        url,
                        headers={"x-goog-api-key": gkey},
                        json={
                            "system_instruction": {"parts": [{"text": sys_p}]},
                            "contents": [{"role": "user", "parts": [{"text": user_p}]}],
                            "generationConfig": {"temperature": 0.75, "maxOutputTokens": 4096, "responseMimeType": "application/json"},
                        },
                        timeout=45.0,
                    )
                    if r.status_code == 200:
                        raw_json = _extract_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                        record_token_usage("gemini", gm, 1400, 1400, 0, 0.00035)
                        break
                    print(f"[BlueprintCloner] Gemini {gm} falhou (HTTP {r.status_code}), tentando próximo...", flush=True)
            elif prov == "deepseek":
                from openai import OpenAI

                cli = OpenAI(api_key=dkey, base_url="https://api.deepseek.com")
                resp = cli.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                    temperature=0.75,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )
                raw_json = _extract_json(resp.choices[0].message.content or "{}")
                u = resp.usage
                pt = int(getattr(u, "prompt_tokens", 1400))
                ct = int(getattr(u, "completion_tokens", 1400))
                cost = round((pt * 0.14 + ct * 0.28) / 1_000_000.0, 5)
                record_token_usage("deepseek", "deepseek-flash", pt, ct, 0, cost)

            if raw_json and isinstance(raw_json.get("lines"), list) and len(raw_json["lines"]) >= max(1, len(segments) // 2):
                by_i = {int(x["i"]): str(x["t"]).strip() for x in raw_json["lines"] if "i" in x and "t" in x}
                out_segs = []
                for s in segments:
                    ns = dict(s)
                    ns["text"] = by_i.get(s["idx"], _paraphrase_line_brazilian(s["text"], tone, s["idx"]))
                    out_segs.append(ns)
                hdr = str(raw_json.get("header") or clean_header)[:48]
                print(f"[BlueprintCloner] Diálogo reescrito com sucesso via {prov} ({len(by_i)}/{len(segments)} falas)!", flush=True)
                return hdr, out_segs, prov
        except Exception as exc:
            print(f"[BlueprintCloner] Aviso provedor {prov}: {exc}", flush=True)
            continue

    # Fast local PT-BR fallback only if ALL LLM providers failed
    out_segs = []
    for s in segments:
        ns = dict(s)
        ns["text"] = _paraphrase_line_brazilian(s["text"], tone, s["idx"])
        out_segs.append(ns)
    return clean_header, out_segs, "local_fallback"


# ---------------------------------------------------------------------------
# 3. Rich 2D Vector Storyboard Stage Renderer (Mirrors Every Scene Mood & Pose)
# ---------------------------------------------------------------------------
def _draw_storyboard_backdrop(
    canvas: skia.Canvas,
    sx: float,
    sy: float,
    sw: float,
    sh: float,
    scene: Dict[str, Any],
    t: float,
) -> None:
    """Draw a 100% original hand-drawn-feel 2D cartoon environment matching the scene's mood & layout."""
    stype = scene.get("scene_type", "boat_deck")
    weather = scene.get("weather_fx") or []
    is_dark = bool(scene.get("is_dark", False))
    outline = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7.0, Color=skia.ColorSetARGB(255, 16, 12, 24))

    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(sx, sy, sw, sh))
    canvas.translate(sx, sy)

    if stype == "storm_closeup" or is_dark:
        # Moody dark storm sky + dramatic lightning spotlight
        bg = skia.Paint()
        bg.setShader(
            skia.GradientShader.MakeRadial(
                (sw * 0.5, sh * 0.45),
                sw * 0.75,
                [skia.ColorSetARGB(255, 36, 40, 82), skia.ColorSetARGB(255, 13, 14, 34)],
            )
        )
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), bg)
        # Diagonal falling cartoon rain
        rain_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorSetARGB(145, 175, 215, 255))
        for ri in range(32):
            rx = (ri * 89 + int(t * 480)) % int(sw + 100) - 50
            ry = (ri * 149 + int(t * 1350)) % int(sh + 100) - 50
            canvas.drawLine(rx, ry, rx - 22, ry + 58, rain_p)
        if "lightning" in weather and (int(t * 4) % 9 == 0):
            canvas.drawRect(skia.Rect.MakeWH(sw, sh), skia.Paint(Color=skia.ColorSetARGB(85, 245, 250, 255)))

    elif stype == "boat_deck":
        # Bright daytime sky + drifting cartoon clouds + ocean horizon + perspective wooden boat deck
        sky_p = skia.Paint()
        sky_p.setShader(
            skia.GradientShader.MakeLinear(
                [(0, 0), (0, sh * 0.52)],
                [skia.ColorSetARGB(255, 96, 196, 245), skia.ColorSetARGB(255, 200, 238, 255)],
            )
        )
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, sw, sh * 0.54), sky_p)

        # Fluffy drifting cartoon clouds
        cp = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
        c_out = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5, Color=skia.ColorSetARGB(255, 110, 175, 215))
        for ci in range(3):
            cx = ((ci * sw * 0.42 + t * (22 + ci * 5)) % (sw + 240)) - 120
            cy = sh * (0.20 + 0.07 * (ci % 2))
            for dx, dy, rad in ((-64, 16, 52), (0, -8, 72), (68, 16, 54)):
                canvas.drawCircle(cx + dx, cy + dy, rad, cp)
                canvas.drawCircle(cx + dx, cy + dy, rad, c_out)

        # Ocean band
        sea_p = skia.Paint()
        sea_p.setShader(
            skia.GradientShader.MakeLinear(
                [(0, sh * 0.48), (0, sh * 0.80)],
                [skia.ColorSetARGB(255, 37, 118, 178), skia.ColorSetARGB(255, 20, 74, 128)],
            )
        )
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.48, sw, sh * 0.34), sea_p)

        # Rocking perspective wooden ship deck in foreground
        sway = math.sin(t * 2.4) * 10.0
        deck = skia.Path()
        deck.moveTo(-40, sh * 0.72 + sway)
        deck.lineTo(sw * 0.84, sh * 0.70 - sway)
        deck.lineTo(sw + 40, sh * 0.84 - sway)
        deck.lineTo(sw + 40, sh + 20)
        deck.lineTo(-40, sh + 20)
        deck.close()
        canvas.drawPath(deck, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 152, 102, 68)))
        canvas.drawPath(deck, outline)
        plank = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorSetARGB(190, 92, 58, 34))
        for py_f in (0.78, 0.85, 0.92):
            canvas.drawLine(0, sh * py_f + sway * 0.6, sw, sh * (py_f + 0.02) - sway * 0.6, plank)

    elif stype == "desert_run":
        # Open bright cyan/mint sky + sandy desert ground + grass tufts & rocky desert skull prop
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, sw, sh * 0.74), skia.Paint(Color=skia.ColorSetARGB(255, 178, 240, 242)))
        ground = skia.Path()
        ground.moveTo(0, sh * 0.72)
        for x in range(0, int(sw) + 60, 60):
            ground.lineTo(x, sh * 0.72 + 12 * math.sin(x * 0.008))
        ground.lineTo(sw, sh)
        ground.lineTo(0, sh)
        ground.close()
        canvas.drawPath(ground, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 178, 138, 96)))
        canvas.drawPath(ground, outline)

        # Scrolling desert tufts & cactus for dynamic running feel
        tuft_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, StrokeCap=skia.Paint.kRound_Cap, Color=skia.ColorSetARGB(255, 108, 78, 48))
        scroll = (t * 160.0) % sw
        for ti in range(4):
            tx = (ti * sw * 0.28 - scroll) % sw
            ty = sh * (0.82 + 0.04 * (ti % 2))
            canvas.drawLine(tx, ty, tx - 16, ty - 28, tuft_p)
            canvas.drawLine(tx, ty, tx, ty - 34, tuft_p)
            canvas.drawLine(tx, ty, tx + 16, ty - 26, tuft_p)

    elif stype == "palace_throne":
        # Stone palace interior + decorative top frieze + tall royal crimson throne in center
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), skia.Paint(Color=skia.ColorSetARGB(255, 172, 166, 152)))
        # Top ancient frieze stripe
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, sw, sh * 0.14), skia.Paint(Color=skia.ColorSetARGB(255, 206, 200, 186)))
        canvas.drawLine(0, sh * 0.14, sw, sh * 0.14, outline)
        # Tall Royal Throne centered
        throne_back = skia.Rect.MakeXYWH(sw * 0.34, sh * 0.18, sw * 0.32, sh * 0.62)
        canvas.drawRoundRect(throne_back, 28, 28, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 128, 92, 52)))
        canvas.drawRoundRect(throne_back, 28, 28, outline)
        cushion = skia.Rect.MakeXYWH(sw * 0.38, sh * 0.22, sw * 0.24, sh * 0.50)
        canvas.drawRoundRect(cushion, 20, 20, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 204, 62, 42)))
        canvas.drawRoundRect(cushion, 20, 20, outline)
        # Floor
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.78, sw, sh * 0.22), skia.Paint(Color=skia.ColorSetARGB(255, 148, 144, 134)))
        canvas.drawLine(0, sh * 0.78, sw, sh * 0.78, outline)

    elif stype == "hill_sulking":
        # Dusty twilight sky + big rocky brown hill with cartoon boulders
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), skia.Paint(Color=skia.ColorSetARGB(255, 136, 164, 174)))
        hill = skia.Path()
        hill.moveTo(0, sh)
        hill.lineTo(0, sh * 0.34)
        hill.quadTo(sw * 0.50, sh * 0.04, sw, sh * 0.36)
        hill.lineTo(sw, sh)
        hill.close()
        canvas.drawPath(hill, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 152, 114, 96)))
        canvas.drawPath(hill, outline)
        # Cartoon boulders
        b_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 122, 90, 78))
        for bx, by, bw, bh in [(0.12, 0.28, 90, 56), (0.80, 0.24, 110, 64), (0.84, 0.48, 120, 72)]:
            r = skia.Rect.MakeXYWH(sw * bx, sh * by, bw, bh)
            canvas.drawOval(r, b_p)
            canvas.drawOval(r, outline)

    elif stype == "city_wall_tree":
        # Sky + ancient fortified stone city walls & towers + lush green tree shade on right
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, sw, sh * 0.74), skia.Paint(Color=skia.ColorSetARGB(255, 142, 198, 224)))
        # Ancient city fortress wall
        wall_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 156, 148, 134))
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.44, sw, sh * 0.30), wall_p)
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.44, sw, sh * 0.30), outline)
        # Ziggurat / towers on horizon
        for tx, tw, th in [(0.12, 0.14, 0.12), (0.36, 0.26, 0.18), (0.72, 0.14, 0.10)]:
            tr = skia.Rect.MakeXYWH(sw * tx, sh * (0.44 - th), sw * tw, sh * th)
            canvas.drawRect(tr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 132, 120, 102)))
            canvas.drawRect(tr, outline)
        # Grassy ground + tree shadow
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.72, sw, sh * 0.28), skia.Paint(Color=skia.ColorSetARGB(255, 142, 166, 116)))
        canvas.drawLine(0, sh * 0.72, sw, sh * 0.72, outline)
        # Lush green cartoon tree canopy top-right
        tree_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 42, 104, 48))
        for cx, cy, cr in [(0.74, 0.14, 120), (0.88, 0.18, 135), (0.96, 0.32, 110), (0.82, 0.28, 115)]:
            canvas.drawCircle(sw * cx, sh * cy, cr, tree_p)
            canvas.drawCircle(sw * cx, sh * cy, cr, outline)

    else:
        # Clean vibrant sky & ground using anti-plagiarism hue-shifted colors extracted from the scene!
        sky_col = hex_to_skia(scene.get("sky_color", "#60C4F5"))
        gnd_col = hex_to_skia(scene.get("ground_color", "#946A46"))
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, sw, sh * 0.70), skia.Paint(Color=sky_col))
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.70, sw, sh * 0.30), skia.Paint(Color=gnd_col))
        canvas.drawLine(0, sh * 0.70, sw, sh * 0.70, outline)

    canvas.restore()


# ---------------------------------------------------------------------------
# 4. Exact-Duration Blueprint Cloner Renderer
# ---------------------------------------------------------------------------
async def _fit_wav_to_slot(wav_path: Path, max_dur_s: float) -> Tuple[np.ndarray, float]:
    """Read 48kHz stereo WAV; if longer than max_dur_s, gently speed up with FFmpeg atempo."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        dur = wf.getnframes() / float(sr)

    if max_dur_s > 0.35 and dur > max_dur_s * 1.04:
        tempo = min(1.38, max(1.02, dur / max_dur_s))
        sped_wav = wav_path.with_name(wav_path.stem + "_fit.wav")
        run_ffmpeg_safe(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(wav_path),
                "-af", f"atempo={tempo:.3f}",
                "-ac", "2", "-ar", "48000", str(sped_wav),
            ]
        )
        wav_path = sped_wav
        with wave.open(str(wav_path), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            dur = wf.getnframes() / float(wf.getframerate())

    pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
    return pcm, dur


async def render_cloned_cartoon_from_blueprint(
    blueprint: Dict[str, Any],
    topic: str,
    tone: str,
    work_dir: Path,
    out_master_mp4: Path,
    music_mp3: Optional[Path] = None,
    fps: int = 30,
    voice_engine: str = "gemini_tts",
    thermal_limit_c: float = 85.0,
    progress_cb=None,
) -> Dict[str, Any]:
    """Render an EXACT-DURATION, scene-mirrored, anti-plagiarism Cartoon Studio v2 clone of ANY reference video."""
    fps = 60 if int(fps) >= 60 else 30
    work_dir.mkdir(parents=True, exist_ok=True)
    target_dur = max(6.0, float(blueprint.get("duration_s") or blueprint.get("duration") or 30.0))
    w = int(blueprint.get("width") or 1080)
    h = int(blueprint.get("height") or 1350)
    aspect_ratio = str(blueprint.get("aspect_ratio") or "4:5")
    has_header = bool(blueprint.get("has_header_bar", aspect_ratio == "4:5"))
    header_h = int(round(h * 0.20)) if has_header else 0

    scenes = blueprint.get("scenes") or [
        {"scene_idx": 0, "start": 0.0, "end": target_dur, "scene_type": "boat_deck", "camera_shot": "wide_two_shot", "pose": "standing", "weather_fx": ["waves"], "is_dark": False}
    ]
    raw_segments = blueprint.get("segments") or []

    # 1. Build 100% original anti-plagiarism character cast & rewritten dialogue
    c_left, c_right = build_original_cast(topic, blueprint)
    header_title, segments, llm_provider_used = await asyncio.to_thread(
        _rewrite_segments_anti_plagiarism,
        raw_segments,
        topic,
        str(blueprint.get("title", "")),
        tone,
    )

    if progress_cb:
        progress_cb(
            20,
            f"Blueprint extraído: {target_dur:.1f}s ({w}x{h} {aspect_ratio} @ {fps}fps) | {len(scenes)} cenas | {len(segments)} falas via {llm_provider_used}",
        )

    # 2. Synthesize ALL dialogue segments & place on exact-duration 48kHz canvas
    sem = asyncio.Semaphore(2 if voice_engine == "gemini_tts" else 6)
    sr = 48000
    total_samples = int(round(target_dur * sr))
    master_pcm = np.zeros((total_samples, 2), dtype=np.float32)

    async def _synth_one(idx: int, seg: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            sp_slot = int(seg.get("speaker_slot", 0))
            char = c_left if sp_slot == 0 else c_right
            txt = str(seg.get("text", "")).strip()
            if not txt:
                return {"idx": idx, "empty": True}
            wav_p, words, dur = await _synthesize_character_line(
                txt,
                char.voice_preset,
                work_dir,
                f"cln_{idx:03d}",
                voice_engine=voice_engine,
                emotion=str(seg.get("emotion", "neutral")),
                speaker_slot=sp_slot,
            )
            return {"idx": idx, "seg": seg, "char": char, "wav": wav_p, "words": words, "dur": dur, "empty": False}

    synth_results = await asyncio.gather(*[_synth_one(i, s) for i, s in enumerate(segments)])
    valid_results = [r for r in synth_results if not r.get("empty")]

    # Place each clip at its exact timestamp seg.start (fitting slot via gentle atempo if needed)
    all_words: List[Dict[str, Any]] = []
    speech_events: List[Dict[str, Any]] = []
    total_frames = max(1, int(math.ceil(target_dur * fps)))
    frame_speaker = [-1] * total_frames       # 0 = left, 1 = right, -1 = silent
    frame_viseme = ["X"] * total_frames
    frame_energy = [0.0] * total_frames
    frame_emotion = ["neutral"] * total_frames
    lipsync_engine = "rhubarb_v1.14_phonetic_9visemes"

    for pos_i, item in enumerate(valid_results):
        seg = item["seg"]
        char: CartoonCharacter = item["char"]
        start_s = max(0.0, float(seg["start"]))
        next_start = float(valid_results[pos_i + 1]["seg"]["start"]) if pos_i + 1 < len(valid_results) else target_dur
        slot_max = max(0.45, min(target_dur - start_s, next_start - start_s - 0.04))

        pcm, fit_dur = await _fit_wav_to_slot(item["wav"], slot_max)
        s0 = int(start_s * sr)
        s1 = min(total_samples, s0 + len(pcm))
        if s1 > s0:
            master_pcm[s0:s1] += pcm[: s1 - s0]

        # Scale word timestamps to fitted duration & add to master captions
        orig_dur = max(0.05, float(item["dur"]))
        t_scale = fit_dur / orig_dur
        fitted_words = []
        for wd in item["words"]:
            ws = round(start_s + float(wd["start"]) * t_scale, 3)
            we = round(start_s + float(wd["end"]) * t_scale, 3)
            fitted_words.append({"word": wd["word"], "start": ws, "end": max(ws + 0.05, we)})
            all_words.append(fitted_words[-1])

        # Compute Rhubarb v1.14 9-viseme phonetic lip-sync for this fitted segment!
        fit_wav = item["wav"].with_name(item["wav"].stem + "_fit.wav")
        src_wav_lip = fit_wav if fit_wav.exists() else item["wav"]
        vis_list, eng_list, lipsync_engine = await asyncio.to_thread(
            extract_rhubarb_visemes,
            src_wav_lip,
            fps,
            str(seg.get("emotion", "neutral")),
        )
        sp_slot = 0 if char.char_id == c_left.char_id else 1
        f_start = int(start_s * fps)
        emo = str(seg.get("emotion", "neutral"))
        for k, (vis, eng) in enumerate(zip(vis_list, eng_list)):
            fi = f_start + k
            if 0 <= fi < total_frames:
                frame_speaker[fi] = sp_slot
                frame_viseme[fi] = vis
                frame_energy[fi] = eng
                frame_emotion[fi] = emo

        speech_events.append({"start": start_s, "end": start_s + fit_dur, "speaker": sp_slot, "emotion": emo})

    # Write exact-duration raw 48kHz dialogue WAV
    raw_dialogue_wav = work_dir / "cloned_dialogue_exact.wav"
    peak = max(1.0, float(np.max(np.abs(master_pcm))))
    pcm_int16 = (np.clip(master_pcm / peak, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(raw_dialogue_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_int16.tobytes())

    if progress_cb:
        progress_cb(44, f"Áudio sincronizado em tempo exato ({target_dur:.2f}s) + Lip-Sync de 6 bocas pronto!")

    # 3. Master Broadcast Audio locked to EXACT target_dur (tail_pad_s=0.0 so duration matches reference!)
    sfx_dir = ASSETS_DIR / "sfx"
    sfx_events: List[Tuple[Path, float, float]] = []
    for sc in scenes[1:20]:  # subtle whoosh on major scene transitions
        sfx_events.append((sfx_dir / "whoosh_fast.wav", max(0.0, float(sc["start"]) - 0.08), 0.22))

    master_audio = work_dir / "cloned_master_audio.m4a"
    master_audio, _ = await asyncio.to_thread(
        master_broadcast_audio,
        raw_dialogue_wav,
        music_mp3,
        sfx_events,
        master_audio,
        target_dur,
        0.11,
        0.0,
    )

    if progress_cb:
        progress_cb(52, f"Renderizando {len(scenes)} cenas espelhadas em Skia C++ ({w}x{h} @ 30fps, {target_dur:.1f}s)...")

    # 4. C++ Skia 30fps Exact-Duration Storyboard Renderer -> Intel QuickSync h264_vaapi
    header_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="clone_header")
    caption_tf, font_info = _load_verified_typeface("Montserrat-Black.ttf", role="clone_caption")
    chunks = group_words_into_chunks(all_words, max_words=3)

    surface = skia.Surface(w, h)
    stage_y = float(header_h)
    stage_h = float(h - header_h)
    stage_w = float(w)

    # Pre-fit top header bar text once
    hdr_font, hdr_lines = _wrap_text_to_width(header_title, header_tf, 58.0, 34.0, w - 96.0, max_lines=2)
    cap_font = skia.Font(caption_tf, 64.0 if aspect_ratio == "4:5" else 72.0)
    space_w = max(26.0, float(cap_font.measureText(" ")) * 1.42)
    fm = cap_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=20)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *pre_args,
        "-f", "rawvideo", "-pix_fmt", "bgra",
        "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
        "-i", str(master_audio),
        "-vf", hw_suffix,
        "-map", "0:v", "-map", "1:a",
        "-t", f"{target_dur:.3f}",
        *enc_args,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_master_mp4),
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

    scene_cursor = 0
    chunk_cursor = 0
    last_speaker = 0

    try:
        for fi in range(total_frames):
            t = fi / float(fps)
            # Advance active scene pointer in O(1)
            while scene_cursor + 1 < len(scenes) and t >= float(scenes[scene_cursor + 1]["start"]):
                scene_cursor += 1
            sc = scenes[scene_cursor]

            sp = frame_speaker[fi]
            if sp >= 0:
                last_speaker = sp
            is_talking = sp >= 0
            act_vis = frame_viseme[fi]
            act_eng = frame_energy[fi]
            act_emo = frame_emotion[fi]

            # Reactive listener emotion
            list_emo = "shocked" if act_emo in ("angry", "shocked") else ("smug" if act_emo == "laughing" else "neutral")

            c = surface.getCanvas()
            c.clear(skia.ColorBLACK)

            # A. Stage with dynamic camera motion mirroring the cloned scene
            c.save()
            c.clipRect(skia.Rect.MakeXYWH(0, stage_y, stage_w, stage_h))

            cam = sc.get("camera_shot", "wide_two_shot")
            pose = sc.get("pose", "standing")
            if cam == "shake_panic":
                sx_j = math.sin(t * 46.0) * 12.0
                sy_j = math.cos(t * 51.0) * 9.0
                c.translate(stage_w * 0.5 + sx_j, stage_y + stage_h * 0.5 + sy_j)
                c.scale(1.06, 1.06)
                c.translate(-stage_w * 0.5, -(stage_y + stage_h * 0.5))
            elif cam == "closeup_speaker":
                zoom = 1.24
                max_sx = stage_w * (zoom - 1.0) / (2.0 * zoom)
                want_sx = stage_w * (-0.16 if last_speaker == 0 else 0.16)
                sh_x = max(-max_sx, min(max_sx, want_sx))
                c.translate(stage_w * 0.5, stage_y + stage_h * 0.5)
                c.scale(zoom, zoom)
                c.translate(-(stage_w * 0.5 + sh_x), -(stage_y + stage_h * 0.52))

            # Draw original Cartoon Studio v2 2.5D Parallax scenery (8fps line boil + cel-shading!)
            sc_type = str(sc.get("scene_type", "boat_deck"))
            sc_weather = list(sc.get("weather_fx") or [])
            is_dark_sc = bool(sc.get("is_dark", False)) or sc_type == "storm_closeup"
            cam_pan_x = math.sin(t * 0.7) * 38.0 + (-45.0 if last_speaker == 0 else 45.0) * 0.35
            draw_parallax_scenery_v2(c, 0, stage_y, stage_w, stage_h, sc_type, sc_weather, t, cam_pan_x=cam_pan_x)

            # Draw original non-plagiarized Cartoon Studio v2 puppets (Bean heads, IK arms, legs, Rhubarb 9-visemes!)
            base_sc = (stage_h / 1080.0) * 1.04
            if pose == "closeup_dramatic":
                draw_cartoon_puppet_v2(
                    c, c_left if last_speaker == 0 else c_right,
                    stage_w * 0.50, stage_y + stage_h * 0.66, base_sc * 1.46, 1,
                    emotion=act_emo if act_emo != "neutral" else "shocked",
                    viseme=act_vis if is_talking else "X",
                    speech_energy=act_eng, is_speaking=is_talking, t=t, blink_offset=0.2,
                    pose="closeup_dramatic", dark_storm_lighting=is_dark_sc,
                )
            elif pose == "running":
                sc_prog = (t - float(sc["start"])) / max(1.0, float(sc.get("duration", 4.0)))
                rx = stage_w * (0.16 + 0.68 * (sc_prog % 1.0))
                rbob = abs(math.sin(t * 14.0)) * 26.0
                draw_cartoon_puppet_v2(
                    c, c_left, rx, stage_y + stage_h * 0.64 - rbob, base_sc * 0.90, +1,
                    emotion="shocked" if act_emo == "neutral" else act_emo,
                    viseme=act_vis if is_talking else "C",
                    speech_energy=act_eng, is_speaking=is_talking, t=t, blink_offset=0.4,
                    pose="running", dark_storm_lighting=is_dark_sc,
                )
            elif pose == "lying_under_tree":
                c.save()
                c.translate(stage_w * 0.68, stage_y + stage_h * 0.76)
                c.rotate(-72.0)
                draw_cartoon_puppet_v2(
                    c, c_left, 0, 0, base_sc * 0.92, +1,
                    emotion=act_emo if act_emo != "neutral" else "shocked",
                    viseme=act_vis if is_talking else "X",
                    speech_energy=act_eng, is_speaking=is_talking, t=t, blink_offset=0.6,
                    pose="lying_under_tree", dark_storm_lighting=is_dark_sc,
                )
                c.restore()
            elif pose == "arms_crossed":
                draw_cartoon_puppet_v2(
                    c, c_left, stage_w * 0.50, stage_y + stage_h * 0.62, base_sc * 1.12, +1,
                    emotion="angry" if act_emo == "neutral" else act_emo,
                    viseme=act_vis if is_talking else "X",
                    speech_energy=act_eng, is_speaking=is_talking, t=t, blink_offset=0.8,
                    pose="arms_crossed", dark_storm_lighting=is_dark_sc,
                )
            else:
                py = stage_y + stage_h * 0.62
                draw_cartoon_puppet_v2(
                    c, c_left, stage_w * 0.28, py, base_sc, +1,
                    emotion=act_emo if last_speaker == 0 else list_emo,
                    viseme=act_vis if (is_talking and sp == 0) else "X",
                    speech_energy=act_eng if (is_talking and sp == 0) else 0.0,
                    is_speaking=(is_talking and sp == 0), t=t, blink_offset=0.0,
                    pose="standing", dark_storm_lighting=is_dark_sc,
                )
                draw_cartoon_puppet_v2(
                    c, c_right, stage_w * 0.72, py, base_sc, -1,
                    emotion=act_emo if last_speaker == 1 else list_emo,
                    viseme=act_vis if (is_talking and sp == 1) else "X",
                    speech_energy=act_eng if (is_talking and sp == 1) else 0.0,
                    is_speaking=(is_talking and sp == 1), t=t, blink_offset=1.5,
                    pose="standing", dark_storm_lighting=is_dark_sc,
                )

            draw_foreground_boat_v2(c, 0, stage_y, stage_w, stage_h, sc_type, sc_weather, t)
            if cam == "shake_panic" or (act_emo in ("shocked", "angry") and act_eng > 0.45):
                c.save()
                c.translate(0, stage_y)
                draw_comic_speed_lines(c, stage_w, stage_h, t, intensity=0.60 if cam == "shake_panic" else 0.38)
                c.restore()
            c.restore()

            # B. Top Black Header Bar (when reference has @animabible7 4:5 meme-story title header!)
            if has_header:
                c.drawRect(skia.Rect.MakeXYWH(0, 0, w, header_h), skia.Paint(Color=skia.ColorBLACK))
                line_step = hdr_font.getSize() * 1.24
                y0 = header_h * 0.56 - ((len(hdr_lines) - 1) * line_step) / 2.0
                wp = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
                for idx_h, hln in enumerate(hdr_lines):
                    hw = hdr_font.measureText(hln)
                    c.drawString(hln, (w - hw) / 2.0, y0 + idx_h * line_step, hdr_font, wp)

            # C. Floating Hormozi/Cartoon Captions tucked cleanly near bottom
            while chunk_cursor + 1 < len(chunks) and t > chunks[chunk_cursor]["end"]:
                chunk_cursor += 1
            if chunk_cursor < len(chunks):
                ch = chunks[chunk_cursor]
                if ch["start"] <= t <= ch["end"]:
                    w_list = ch["words"]
                    active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
                    pad_x, pad_y = 22.0, 10.0
                    toks = []
                    tot_w = 0.0
                    for wd in w_list:
                        txt = str(wd["word"]).strip().upper()
                        if not txt:
                            continue
                        is_act = wd is active_wd
                        sc_w = 1.10 if is_act else 1.0
                        tw = float(cap_font.measureText(txt))
                        sw_slot = (tw + pad_x * 2.0) * sc_w if is_act else tw
                        toks.append({"txt": txt, "w": tw, "sw": sw_slot, "act": is_act, "sc": sc_w, "pidx": int(wd.get("g_idx", 0))})
                        tot_w += sw_slot
                    if toks:
                        tot_w += space_w * (len(toks) - 1)
                        lscale = min(1.0, (w * 0.86) / max(1.0, tot_w))
                        cap_y = h - 72.0
                        c.save()
                        c.translate(w / 2.0, cap_y)
                        c.scale(lscale, lscale)
                        cx_p = -tot_w / 2.0
                        pmap = {}
                        for tk in toks:
                            pmap[id(tk)] = cx_p + tk["sw"] / 2.0
                            cx_p += tk["sw"] + space_w
                        for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                            c.save()
                            c.translate(pmap[id(tk)], 0.0)
                            if tk["act"]:
                                c.scale(tk["sc"], tk["sc"])
                                pbg, ptx, (gr, gg, gb, ga) = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
                                pr = skia.Rect.MakeXYWH(-tk["w"] / 2.0 - pad_x, -ascent - pad_y, tk["w"] + pad_x * 2.0, ascent + descent + pad_y * 2.0)
                                c.drawRoundRect(pr, 18, 18, skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg)))
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                            else:
                                stp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=10.0, StrokeJoin=skia.Paint.kRound_Join, Color=skia.ColorBLACK)
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, cap_font, stp)
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                            c.restore()
                        c.restore()

            proc.stdin.write(surface.makeImageSnapshot().tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait(timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"Blueprint Cartoon2D encode failed: {stderr.decode(errors='ignore')}")

    return {
        "master_mp4": str(out_master_mp4),
        "master_audio": str(master_audio),
        "words": all_words,
        "duration_s": round(target_dur, 2),
        "aspect_ratio": aspect_ratio,
        "width": w,
        "height": h,
        "fps": fps,
        "voice_engine": voice_engine,
        "lipsync_engine": lipsync_engine,
        "cartoon_engine": "cartoon_studio_v2_line_boil_2.5d",
        "header_title": header_title,
        "has_header_bar": has_header,
        "llm_provider_used": llm_provider_used,
        "font_verified": font_info,
        "characters_count": 2,
        "scenes_count": len(scenes),
        "dialogue_count": len(valid_results),
    }
