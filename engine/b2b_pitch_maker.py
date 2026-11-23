"""FrimeRise Dedicated B2B Local Pitch Maker ("Vender p/ Empresas" 1-Click Prospecting Engine).
Provides:
  1. `generate_b2b_pitch_bundle(company_name: str, city: str, product_service: str, niche: str = "Negócio Local") -> dict`
     Generates a high-converting local business video script audited by Retention Doctor +
     ready-to-copy WhatsApp outreach copy + follow-up script + retainer pricing tiers.
  2. `async def render_b2b_540p_demo(...) -> dict`
     Produces a persuasive 540p commercial demo video (`540x960` 9:16 or `960x540` 16:9) with
     Hormozi captions, dynamic B2B Headline/Counter Motion Cards, broadcast audio (-14 LUFS),
     and the diagonal translucent watermark `PRÉVIA EXCLUSIVA • FRIMERISE`.
"""
from __future__ import annotations

import asyncio
import math
import re
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import skia

from agents.retention_doctor import audit_viral_script_dict
from engine.audio_dsp import (
    _estimate_word_timestamps,
    generate_narration,
    master_broadcast_audio,
)
from engine.exporters import export_whatsapp_preview_540p
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    thermal_guard_wait,
)
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    _load_verified_typeface,
    _wrap_text_to_width,
    group_words_into_chunks,
    hex_to_skia,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
MEDIA_CACHE_DIR = BASE_DIR / "data" / "media_cache"

DEFAULT_B2B_WATERMARK = "PRÉVIA EXCLUSIVA • FRIMERISE"


def generate_b2b_pitch_bundle(
    company_name: str,
    city: str,
    product_service: str,
    niche: str = "Negócio Local",
) -> Dict[str, Any]:
    """Create a complete B2B Local Prospecting Bundle:
    - Persuasive commercial script (audited by Retention Doctor with active Open Loops)
    - Ready-to-copy WhatsApp initial outreach message + 24h follow-up copy
    - Diagonal watermark spec ('PRÉVIA EXCLUSIVA • FRIMERISE')
    """
    comp = str(company_name or "").strip() or "Clínica Prime"
    ct = str(city or "").strip() or "Sua Cidade"
    prod = str(product_service or "").strip() or "Atendimento Premium"
    nch = str(niche or "").strip() or "Negócio Local"

    raw_script: Dict[str, Any] = {
        "title": f"{comp} • {ct}",
        "niche": nch,
        "hook_a": f"Moradores de {ct}: parem de procurar {prod} sem antes conhecer o padrão da {comp}!",
        "hook_b": f"Por que tanta gente em {ct} está trocando tudo pelo {prod} da {comp} esta semana?",
        "body_lines": [
            f"A maioria das empresas de {nch.lower()} promete resultado em {prod}, mas entrega mais do mesmo — só que tem um detalhe que muda tudo: o que diferencia quem realmente resolve?",
            f"Na {comp} em {ct}, cada etapa de {prod} foi desenhada para entregar qualidade superior e atendimento imediato.",
        ],
        "closing_line": f"Toque no link abaixo ou chame a {comp} no WhatsApp agora e garanta seu atendimento em {ct}!",
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
            },
            {
                "type": "counter",
                "prefix": "+",
                "target": 340,
                "suffix": "%",
                "label": f"PROCURA EM {ct.upper()[:18]}",
            },
        ],
        "hashtags": [
            f"#{re.sub(r'[^a-zA-Z0-9]', '', comp.lower()) or 'empresa'}",
            f"#{re.sub(r'[^a-zA-Z0-9]', '', ct.lower()) or 'cidade'}",
            "#negociolocal",
            "#reels",
        ],
    }

    audited_script = audit_viral_script_dict(raw_script, lang="pt_br")

    whatsapp_pitch = (
        f"Olá, equipe da *{comp}*! Tudo bem? 👋\n\n"
        f"Notei que muita gente em *{ct}* busca por *{prod}* no Instagram, TikTok e Shorts, "
        f"mas poucos negócios no segmento de *{nch}* estão usando vídeos dinâmicos de alta retenção "
        f"para capturar esses clientes todos os dias.\n\n"
        f"Tomei a liberdade de produzir em nosso estúdio uma *Prévia Exclusiva de Vídeo Comercial* personalizada para a *{comp}* "
        f"(anexei o vídeo demonstrativo em 540p aqui na conversa!). 🎬✨\n\n"
        f"Se gostarem do formato, eu entrego a versão *Master Full HD 1080p sem marca d'água* + *3 variações otimizadas* "
        f"(Reels, TikTok e Shorts) prontas para atrair clientes em *{ct}* ainda hoje.\n\n"
        f"Podemos liberar o arquivo Master sem marca d'água para vocês testarem hoje?"
    )

    followup_pitch = (
        f"Oi, pessoal da *{comp}*! Passando rápido para saber se conseguiram assistir à prévia de vídeo "
        f"sobre *{prod}* em *{ct}* que enviei acima. 🎥\n\n"
        f"Consigo liberar o arquivo *Master 1080p limpo (sem a marca d'água '{DEFAULT_B2B_WATERMARK}')* "
        f"com condição especial de boas-vindas hoje. Querem que eu envie por aqui?"
    )

    return {
        "company_name": comp,
        "city": ct,
        "product_service": prod,
        "niche": nch,
        "topic": f"B2B • {comp} ({ct}) — {prod}",
        "watermark_text": DEFAULT_B2B_WATERMARK,
        "script": audited_script,
        "whatsapp_pitch": whatsapp_pitch,
        "whatsapp_copy": whatsapp_pitch,
        "outreach_message": whatsapp_pitch,
        "followup_pitch": followup_pitch,
        "retention_audit": audited_script.get("retention_audit", {}),
        "pricing_tiers": [
            {"plan": "Vídeo Único Master 1080p", "price_brl": 197, "deliverables": "1 Vídeo 1080p s/ marca d'água + 3 variações ShadowHash"},
            {"plan": "Pacote Mensal Local (4 Vídeos)", "price_brl": 597, "deliverables": "1 Vídeo/semana + Legendas Hormozi + Roteiro Anti-Tédio"},
            {"plan": "Domínio Local VIP (12 Vídeos)", "price_brl": 1497, "deliverables": "3 Vídeos/semana + Dual-Hook A/B + Capas HD"},
        ],
    }


def _synthesize_offline_fallback_wav(text: str, out_wav: Path, target_dur_s: float = 6.0) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Deterministic broadcast speech-envelope WAV fallback if offline or TTS service is unreachable."""
    words_list = [w for w in str(text or "").split() if w.strip()]
    dur = max(4.5, min(14.0, target_dur_s if target_dur_s > 0 else len(words_list) / 2.8))
    sr = 24000
    n_samples = int(dur * sr)
    t = np.linspace(0.0, dur, n_samples, endpoint=False)
    envelope = 0.5 + 0.5 * np.sin(2.0 * np.pi * 3.2 * t)
    wave_sig = 0.14 * envelope * (np.sin(2.0 * np.pi * 165.0 * t) + 0.5 * np.sin(2.0 * np.pi * 330.0 * t))
    pcm = (np.clip(wave_sig, -1.0, 1.0) * 32767.0).astype(np.int16)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    words = _estimate_word_timestamps(text, dur)
    return out_wav, words, dur


def _load_cached_broll_frames(width: int, height: int) -> List[skia.Image]:
    """Sample a few real footage keyframes from data/media_cache if available for B2B backdrop texture."""
    imgs: List[skia.Image] = []
    if not MEDIA_CACHE_DIR.exists():
        return imgs
    mp4s = sorted(MEDIA_CACHE_DIR.glob("*.mp4"))[:3]
    for mp4 in mp4s:
        cap = cv2.VideoCapture(str(mp4))
        if not cap.isOpened():
            continue
        ok, frame = cap.read()
        cap.release()
        if ok and frame is not None:
            resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            bgra = cv2.cvtColor(resized, cv2.COLOR_BGR2BGRA)
            imgs.append(
                skia.Image.frombytes(
                    bgra.tobytes(),
                    (width, height),
                    skia.kBGRA_8888_ColorType,
                    skia.kPremul_AlphaType,
                )
            )
    return imgs


async def render_b2b_540p_demo(
    company_name: Union[str, Dict[str, Any]] = "Clínica Prime",
    city: Union[str, Path] = "São Paulo",
    product_service: str = "Atendimento Premium",
    niche: str = "Negócio Local",
    output_dir: Optional[Union[str, Path]] = None,
    out_mp4: Optional[Union[str, Path]] = None,
    master_video: Optional[Union[str, Path]] = None,
    aspect_ratio: str = "9:16",
    watermark_text: str = DEFAULT_B2B_WATERMARK,
    voice_id: str = "pt-BR-AntonioNeural",
    fps: int = 30,
    max_demo_seconds: float = 12.0,
    thermal_limit_c: float = 85.0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Render a persuasive 540p B2B commercial demo video with the diagonal translucent watermark
    `PRÉVIA EXCLUSIVA • FRIMERISE` + ready-to-copy WhatsApp outreach copy.

    Supports both:
      - `await render_b2b_540p_demo("Clínica Prime", "São Paulo", "Implantes Dentários", "Odontologia", output_dir=...)`
      - `await render_b2b_540p_demo(bundle_dict, output_dir=...)`
    """
    if isinstance(company_name, dict):
        bundle = dict(company_name)
        if isinstance(city, Path) or (isinstance(city, str) and ("/" in city or "\\" in city)):
            output_dir = Path(city)
        comp = str(bundle.get("company_name") or "Clínica Prime")
        ct = str(bundle.get("city") or "Sua Cidade")
        prod = str(bundle.get("product_service") or "Atendimento Premium")
        nch = str(bundle.get("niche") or niche or "Negócio Local")
        if "script" not in bundle or "whatsapp_pitch" not in bundle:
            bundle = generate_b2b_pitch_bundle(comp, ct, prod, nch)
    else:
        comp = str(company_name or "Clínica Prime").strip()
        ct = str(city or "Sua Cidade").strip()
        prod = str(product_service or "Atendimento Premium").strip()
        nch = str(niche or "Negócio Local").strip()
        bundle = generate_b2b_pitch_bundle(comp, ct, prod, nch)

    wm_txt = str(watermark_text or bundle.get("watermark_text") or DEFAULT_B2B_WATERMARK).strip()
    if out_mp4 is not None:
        preview_mp4 = Path(out_mp4)
        job_dir = preview_mp4.parent
    elif output_dir is not None:
        job_dir = Path(output_dir)
        preview_mp4 = job_dir / "preview_540p.mp4"
    else:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", comp.lower()).strip("_")[:20] or "b2b"
        job_dir = OUTPUTS_DIR / f"b2b_{slug}_{uuid.uuid4().hex[:6]}"
        preview_mp4 = job_dir / "preview_540p.mp4"

    job_dir.mkdir(parents=True, exist_ok=True)
    work_dir = job_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    master_mp4 = job_dir / "master_b2b_clean.mp4"

    dims = {"16:9": (960, 540), "4:5": (540, 676), "1:1": (540, 540), "9:16": (540, 960)}
    pw, ph = dims.get(aspect_ratio, (540, 960))

    # Fast path if an existing master_video was already rendered
    if master_video and Path(master_video).exists():
        src_master = Path(master_video)
        await asyncio.to_thread(
            export_whatsapp_preview_540p,
            src_master,
            preview_mp4,
            wm_txt,
            aspect_ratio,
        )
        return {
            "status": "completed",
            "company_name": comp,
            "city": ct,
            "product_service": prod,
            "niche": nch,
            "preview_540p_path": str(preview_mp4),
            "video_path": str(preview_mp4),
            "master_path": str(src_master),
            "watermark_text": wm_txt,
            "resolution": f"{pw}x{ph}",
            "aspect_ratio": aspect_ratio,
            "whatsapp_pitch": bundle["whatsapp_pitch"],
            "whatsapp_copy": bundle["whatsapp_pitch"],
            "script": bundle["script"],
            "retention_audit": bundle["retention_audit"],
        }

    # 1. Synthesize narration + broadcast master audio (-14 LUFS)
    script = bundle["script"]
    full_text = " ".join(
        [
            str(script.get("hook_a", "")),
            *[str(x) for x in (script.get("body_lines") or [])[:1]],
            str(script.get("closing_line", "")),
        ]
    ).strip()

    try:
        narr_wav, words, speech_dur = await generate_narration(
            text=full_text,
            work_dir=work_dir,
            voice_engine="edge",
            voice_id=voice_id,
            prefix="b2b_narr",
        )
    except Exception:
        narr_wav, words, speech_dur = await asyncio.to_thread(
            _synthesize_offline_fallback_wav,
            full_text,
            work_dir / "b2b_narr_fallback.wav",
            6.5,
        )

    if max_demo_seconds and speech_dur > max_demo_seconds:
        speech_dur = float(max_demo_seconds)
        words = [w for w in words if float(w.get("start", 0.0)) < speech_dur]
        for w in words:
            w["end"] = min(speech_dur, float(w.get("end", speech_dur)))

    music_file = ASSETS_DIR / "music" / "corporate_focus.mp3"
    sfx_dir = ASSETS_DIR / "sfx"
    sfx_events = []
    if (sfx_dir / "cinematic_hit.wav").exists():
        sfx_events.append((sfx_dir / "cinematic_hit.wav", 0.05, 0.32))
    if (sfx_dir / "cash_chime.wav").exists():
        sfx_events.append((sfx_dir / "cash_chime.wav", min(2.2, speech_dur * 0.45), 0.30))

    master_audio = work_dir / "b2b_master.m4a"
    master_audio, duration_s = await asyncio.to_thread(
        master_broadcast_audio,
        narr_wav,
        music_file,
        sfx_events,
        master_audio,
        speech_dur,
        0.18,
        0.35,
    )
    if max_demo_seconds and duration_s > max_demo_seconds + 0.5:
        duration_s = round(float(max_demo_seconds), 2)

    # 2. Render clean 540p master video in Skia C++ (B2B Commercial Cards + Hormozi Captions)
    def _render_clean_b2b_video() -> Path:
        thermal_guard_wait(limit_c=thermal_limit_c)
        surf = skia.Surface(pw, ph)
        main_tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="b2b_main")
        anton_tf, _ = _load_verified_typeface("Anton-Regular.ttf", role="b2b_anton")
        ui_tf, _ = _load_verified_typeface("PlusJakartaSans-ExtraBold.ttf", role="b2b_ui")

        cached_imgs = _load_cached_broll_frames(pw, ph)
        chunks = group_words_into_chunks(words, max_words=3)
        total_frames = max(1, int(math.ceil(duration_s * fps)))

        cap_font = skia.Font(main_tf, 42.0 if pw <= 600 else 38.0)
        space_w = max(16.0, float(cap_font.measureText(" ")) * 1.40)
        fm = cap_font.getMetrics()
        ascent = abs(float(fm.fAscent))
        descent = abs(float(fm.fDescent))

        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=22)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            *pre_args,
            "-f", "rawvideo", "-pix_fmt", "bgra",
            "-s", f"{pw}x{ph}", "-r", str(fps), "-i", "pipe:0",
            "-i", str(master_audio),
            "-vf", hw_suffix,
            "-map", "0:v", "-map", "1:a",
            "-t", f"{duration_s:.3f}",
            *enc_args,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(master_mp4),
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=get_vaapi_env(),
            preexec_fn=nice_preexec,
        )
        assert proc.stdin is not None

        try:
            for f_idx in range(total_frames):
                t = f_idx / float(fps)
                c = surf.getCanvas()
                c.clear(hex_to_skia("#0B0713"))

                # Scene cut every ~3.2s with subtle 2.5D zoom
                scene_idx = int(t / 3.2)
                local_t = (t % 3.2) / 3.2
                zoom = 1.02 + 0.08 * local_t

                if cached_imgs:
                    bg_img = cached_imgs[scene_idx % len(cached_imgs)]
                    c.save()
                    c.translate(pw * 0.5, ph * 0.5)
                    c.scale(zoom, zoom)
                    c.translate(-pw * 0.5, -ph * 0.5)
                    c.drawImage(bg_img, 0, 0)
                    c.restore()

                # Cyber-Luxury atmospheric gradient overlay
                grad = skia.Paint()
                grad.setShader(
                    skia.GradientShader.MakeLinear(
                        [(0, 0), (pw, ph)],
                        [
                            skia.ColorSetARGB(215 if cached_imgs else 255, 11, 7, 19),
                            skia.ColorSetARGB(185 if cached_imgs else 255, 24, 14, 44),
                            skia.ColorSetARGB(230 if cached_imgs else 255, 11, 7, 19),
                        ],
                        [0.0, 0.5, 1.0],
                    )
                )
                c.drawRect(skia.Rect.MakeWH(pw, ph), grad)

                # Ambient neon spotlight pulse
                spot = skia.Paint()
                spot_col = hex_to_skia("#FF2E93", 75) if scene_idx % 2 == 0 else hex_to_skia("#B8FF01", 65)
                spot.setShader(
                    skia.GradientShader.MakeRadial(
                        (pw * 0.5, ph * 0.34),
                        max(pw, ph) * 0.55,
                        [spot_col, skia.ColorSetARGB(0, 11, 7, 19)],
                    )
                )
                c.drawRect(skia.Rect.MakeWH(pw, ph), spot)

                # Top progress bar
                prog_w = max(4.0, pw * (t / max(0.1, duration_s)))
                c.drawRect(skia.Rect.MakeXYWH(0, 0, prog_w, 6), skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")))

                # B2B Brand Feature Card in upper/middle area
                card_w = pw * 0.86
                card_x = (pw - card_w) * 0.5
                card_y = ph * 0.14
                card_h = ph * 0.34
                card_r = skia.Rect.MakeXYWH(card_x, card_y, card_w, card_h)
                c.drawRoundRect(card_r, 20, 20, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(215, 20, 14, 36)))
                c.drawRoundRect(
                    card_r,
                    20,
                    20,
                    skia.Paint(
                        AntiAlias=True,
                        Style=skia.Paint.kStroke_Style,
                        StrokeWidth=2.5,
                        Color=hex_to_skia("#FFD166" if scene_idx % 2 else "#FF2E93"),
                    ),
                )

                # Tag pill (DESTAQUE EM CIDADE)
                tag_txt = f"DESTAQUE EM {ct.upper()}"[:28]
                tag_font, tag_lines = _wrap_text_to_width(tag_txt, ui_tf, 18.0, 13.0, card_w - 40.0, 1)
                tag_s = tag_lines[0] if tag_lines else tag_txt
                tw_tag = tag_font.measureText(tag_s)
                c.drawRoundRect(
                    skia.Rect.MakeXYWH((pw - tw_tag) * 0.5 - 14, card_y + 20, tw_tag + 28, 30),
                    15,
                    15,
                    skia.Paint(AntiAlias=True, Color=hex_to_skia("#B8FF01")),
                )
                c.drawString(tag_s, (pw - tw_tag) * 0.5, card_y + 41, tag_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#0B0713")))

                # Company Name headline (auto-wrapped, zero clipping)
                comp_font, comp_lines = _wrap_text_to_width(comp.upper(), anton_tf, 42.0, 22.0, card_w - 36.0, 2)
                cy_text = card_y + 94.0
                for cln in comp_lines:
                    cw_ln = comp_font.measureText(cln)
                    c.drawString(cln, (pw - cw_ln) * 0.5, cy_text, comp_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                    cy_text += comp_font.getSize() * 1.15

                # Product / Service subtitle
                prod_font, prod_lines = _wrap_text_to_width(prod.upper(), main_tf, 22.0, 14.0, card_w - 36.0, 2)
                cy_text += 8.0
                for pln in prod_lines:
                    pw_ln = prod_font.measureText(pln)
                    c.drawString(pln, (pw - pw_ln) * 0.5, cy_text, prod_font, skia.Paint(AntiAlias=True, Color=hex_to_skia("#FFD166")))
                    cy_text += prod_font.getSize() * 1.22

                # Hormozi active-word pill captions at lower third
                for ch in chunks:
                    if ch["start"] <= t <= ch["end"]:
                        w_list = ch["words"]
                        active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
                        pad_x, pad_y = 14.0, 7.0
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
                            lscale = min(1.0, (pw * 0.86) / max(1.0, tot_w))
                            c.save()
                            c.translate(pw * 0.5, ph * 0.72)
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
                                    c.drawRoundRect(pr, 12, 12, skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg)))
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                                else:
                                    stp = skia.Paint(
                                        AntiAlias=True,
                                        Style=skia.Paint.kStroke_Style,
                                        StrokeWidth=6.5,
                                        StrokeJoin=skia.Paint.kRound_Join,
                                        Color=skia.ColorBLACK,
                                    )
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, stp)
                                    c.drawString(tk["txt"], -tk["w"] * 0.5, 0.0, cap_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                                c.restore()
                            c.restore()
                        break

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
            raise RuntimeError(f"Falha ao renderizar B2B demo: {stderr.decode(errors='ignore')}")
        return master_mp4

    await asyncio.to_thread(_render_clean_b2b_video)

    # 3. Apply the diagonal translucent watermark "PRÉVIA EXCLUSIVA • FRIMERISE" at 540p
    await asyncio.to_thread(
        export_whatsapp_preview_540p,
        master_mp4,
        preview_mp4,
        wm_txt,
        aspect_ratio,
    )

    return {
        "status": "completed",
        "company_name": comp,
        "city": ct,
        "product_service": prod,
        "niche": nch,
        "preview_540p_path": str(preview_mp4),
        "video_path": str(preview_mp4),
        "master_path": str(master_mp4),
        "watermark_text": wm_txt,
        "resolution": f"{pw}x{ph}",
        "aspect_ratio": aspect_ratio,
        "duration_s": round(duration_s, 2),
        "whatsapp_pitch": bundle["whatsapp_pitch"],
        "whatsapp_copy": bundle["whatsapp_pitch"],
        "outreach_message": bundle["whatsapp_pitch"],
        "followup_pitch": bundle["followup_pitch"],
        "script": bundle["script"],
        "retention_audit": bundle["retention_audit"],
    }
