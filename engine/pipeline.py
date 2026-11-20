"""FrimeRise End-to-End Video Manufacturing Pipeline (Real Footage + Hormozi Captions Edition).
Orchestrates:
  Script (clean complete ending, zero debug labels) ->
  Broadcast Audio + VAD + 0.40s clean tail & fadeout ->
  Zero-Key Real Footage (Pixabay -> Pexels -> yt-dlp -> Wikimedia -> Archive) changing every 3-4s
    + 9:16 Smart Crop + Subpixel Zoom + 3D LUT + xfade + whoosh SFX ->
  C++ Skia Compositor (Heavy Montserrat-Black 900 Hormozi captions + 2.5-3.5s auto-wrapped Motion Cards
    with dynamic boxblur depth-of-field, ZERO watermark on Master) ->
  Intel QuickSync VAAPI -> Dual-Hook A/B Splice -> 3 ShadowHash Mutations ->
  540p WhatsApp Watermarked Preview -> CapCut ZIP -> Kdenlive OTIO -> Clean 9:16 HD Cover.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agents.llm_router import generate_viral_script
from database import (
    append_job_log,
    create_job,
    get_client,
    get_preset,
    get_settings,
    update_job,
)
from engine.audio_dsp import generate_narration, master_broadcast_audio
from engine.blueprint_cloner import render_cloned_cartoon_from_blueprint
from engine.cartoon_2d_studio import generate_cartoon_episode_plan, render_cartoon_episode
from engine.exporters import (
    export_capcut_zip,
    export_kdenlive_otio,
    export_whatsapp_preview_540p,
    splice_dual_hook_b,
)
from engine.global_scaler import dub_video_job_multi_language
from engine.intel_vaapi import read_cpu_temperature_c, run_ffmpeg_safe
from engine.skia_compositor import SkiaMotionCompositor, render_cover_9x16
from engine.smart_vision import (
    assemble_scenes_with_xfade,
    evaluate_clip_quality,
    fetch_unique_real_clip,
    prepare_styled_scene,
)
from engine.thumbnail_studio import generate_ab_thumbnails_16x9
from engine.viral_cloner import VideoDNAExtractor
from publisher.shadowhash import generate_shadowhash_variants

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _rel_output(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)


def _schedule_motion_cards(raw_cards: List[Dict[str, Any]], duration_s: float) -> List[Dict[str, Any]]:
    """Schedule 1-2 short punchy Motion Graphics Cards (strictly 2.5s to 3.5s each) over real footage."""
    if not raw_cards or duration_s < 8.0:
        return []
    # Prefer bar_chart & counter data cards; show max 2 brief cards spaced well apart so footage breathes
    n = min(2, len(raw_cards))
    scheduled = []
    card_dur = 3.0  # Strictly inside 2.5s - 3.5s
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
    """Execute a complete FrimeRise manufacturing job with real HD footage and clean broadcast polish."""
    opts = options or {}
    use_motion_cards = bool(opts.get("motion_cards", True))
    seamless_loop = bool(opts.get("seamless_loop", True))
    dual_hook_ab = bool(opts.get("dual_hook_ab", True))
    source_url = str(opts.get("source_url", "")).strip()
    reference_mp4_path = str(opts.get("reference_mp4_path", "")).strip()
    custom_script = opts.get("custom_script")
    engine_style = str(opts.get("engine_style", "cinematic_broll")).strip()
    aspect_ratio = "16:9" if str(opts.get("aspect_ratio", "9:16")) == "16:9" else "9:16"
    cartoon_tone = str(opts.get("cartoon_tone", "Comédia Nordestina/BR")).strip()
    cartoon_fps = 60 if int(opts.get("cartoon_fps", 60)) >= 60 else 30
    cartoon_voice_engine = str(opts.get("cartoon_voice_engine", "gemini_tts")).strip()
    clone_languages = bool(opts.get("clone_languages", False))

    job_dir = OUTPUTS_DIR / job_id
    work_dir = job_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    thermal_limit = float(settings.get("thermal_limit_c") or 85.0)
    client = get_client(client_id)
    preset = get_preset(opts.get("preset_id") or client.get("preset_id") or "frimerise_signature")
    lut_file = opts.get("lut_file") or client.get("lut_file") or preset.get("lut_file", "01_frimerise_signature.cube")
    watermark_text = str(opts.get("watermark_text") or client.get("watermark_text") or "PRÉVIA • FRIMERISE").strip()

    try:
        update_job(job_id, status="running", progress=5, stage="Analisando DNA & Roteirizando")
        append_job_log(job_id, f"Iniciando fabricação | Cliente: {client['name']} | Estilo: {engine_style} | Formato: {aspect_ratio}")

        reference_transcript = ""
        detected_dna: Optional[Dict[str, Any]] = None
        if mode == "clone_url" and (source_url or reference_mp4_path):
            extractor = VideoDNAExtractor()
            if reference_mp4_path and (BASE_DIR / reference_mp4_path).exists():
                append_job_log(job_id, f"Analisando DNA do MP4 enviado via VideoDNAExtractor...", progress=10, stage="Extraindo DNA do Vídeo")
                detected_dna = await asyncio.to_thread(extractor.extract_from_local_mp4, BASE_DIR / reference_mp4_path, topic)
            elif source_url:
                append_job_log(job_id, f"Clonando URL via VideoDNAExtractor ({source_url})...", progress=10, stage="Extraindo DNA da URL Viral")
                detected_dna = await asyncio.to_thread(extractor.extract_from_url, source_url)

            if detected_dna:
                reference_transcript = detected_dna.get("transcript", "")
                if not topic or topic.lower().startswith("clone viral"):
                    topic = detected_dna.get("title", "Conteúdo Viral Clonado")
                    update_job(job_id, topic=topic)
                dna_style = detected_dna.get("style", "live_action_broll")
                append_job_log(
                    job_id,
                    f"VideoDNAExtractor detectou: {dna_style} (confiança={detected_dna.get('confidence', 0):.0%}, "
                    f"falantes≈{detected_dna.get('estimated_speakers', 2)}, tom='{detected_dna.get('detected_tone', '')}')",
                )
                if dna_style == "2d_cartoon_animation":
                    engine_style = "cartoon_2d"
                    if not opts.get("cartoon_tone"):
                        cartoon_tone = detected_dna.get("detected_tone", cartoon_tone)
                    if not opts.get("aspect_ratio") and detected_dna.get("aspect_ratio") in ("9:16", "16:9"):
                        aspect_ratio = detected_dna["aspect_ratio"]
                    append_job_log(job_id, "Chaveamento automático ativado -> Motor Animação 2D Cartoon (cartoon_2d_studio.py)!")

        # =====================================================================
        # BRANCH A: 2D CARTOON ANIMATION STUDIO (Blueprint Exact-Duration Clone OR Fresh Episode)
        # =====================================================================
        if engine_style == "cartoon_2d":
            master_mp4 = job_dir / "master.mp4"
            music_file = ASSETS_DIR / "music" / preset.get("music_file", "corporate_focus.mp3")

            def _cb(pct: int, msg: str) -> None:
                append_job_log(job_id, msg, progress=pct, stage=msg[:60])

            # If we reverse-engineered a reference VideoBlueprint with scenes & segments, mirror its EXACT
            # duration, aspect ratio, header bar, scene cuts & animation beats with original anti-plagiarism visuals!
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
                    fps=cartoon_fps,
                    voice_engine=cartoon_voice_engine,
                    thermal_limit_c=thermal_limit,
                    progress_cb=_cb,
                )
                aspect_ratio = render_info["aspect_ratio"]
                ep_title = render_info.get("header_title") or topic
            else:
                append_job_log(job_id, f"Gerando episódio Cartoon 2D v2 ({aspect_ratio} @ {cartoon_fps}fps | Voz: {cartoon_voice_engine} | Tom: {cartoon_tone})...", progress=15, stage="Roteirizando Diálogos Multi-Personagens")
                plan, llm_meta = await asyncio.to_thread(
                    generate_cartoon_episode_plan,
                    topic=topic,
                    tone=cartoon_tone,
                    aspect_ratio=aspect_ratio,
                    reference_transcript=reference_transcript,
                )
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
                    fps=cartoon_fps,
                    voice_engine=cartoon_voice_engine,
                    thermal_limit_c=thermal_limit,
                    progress_cb=_cb,
                )
                ep_title = plan.title

            duration_s = float(render_info["duration_s"])
            master_audio = Path(render_info["master_audio"])
            words_a = render_info["words"]
            vid_w = int(render_info["width"])
            vid_h = int(render_info["height"])

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
                music_file,
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
                music_file,
                words_a,
                duration_s,
                otio_path,
            )

            frame_snap = work_dir / "cover_bg.png"
            try:
                await asyncio.to_thread(
                    run_ffmpeg_safe,
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(2.0, duration_s * 0.25):.2f}", "-i", str(master_mp4), "-frames:v", "1", str(frame_snap)],
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

            # Automatic 3 Magnetic 1280x720 A/B/C Thumbnails when aspect_ratio == 16:9 (or requested)
            ab_thumbs: Dict[str, str] = {}
            if aspect_ratio == "16:9" or opts.get("generate_thumbnails_ab"):
                append_job_log(job_id, "Gerando 3 Thumbnails Magnéticas 1280x720 (Skia C++ + rembg u2netp)...", progress=93, stage="Gerando 3 Thumbnails A/B 1280x720")
                raw_thumbs = await asyncio.to_thread(generate_ab_thumbnails_16x9, master_mp4, ep_title, job_dir)
                ab_thumbs = {
                    "thumb_a": _rel_output(Path(raw_thumbs["thumb_a"])),
                    "thumb_b": _rel_output(Path(raw_thumbs["thumb_b"])),
                    "thumb_c": _rel_output(Path(raw_thumbs["thumb_c"])),
                    "headline_words": raw_thumbs["headline_words"],
                }

            # Automatic Multi-Language Dubbing & Re-Timing (EN-US + ES) when clone_languages=True
            dubbed_langs: Dict[str, Any] = {}
            if clone_languages and not (detected_dna and detected_dna.get("scenes")):
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
                "cartoon_engine": render_info.get("cartoon_engine", "cartoon_studio_v2_line_boil_2.5d"),
                "clone_mode": "blueprint_exact_duration" if (detected_dna and detected_dna.get("scenes")) else "fresh_episode",
                "aspect_ratio": aspect_ratio,
                "resolution": f"{vid_w}x{vid_h}",
                "fps": int(render_info.get("fps", cartoon_fps)),
                "voice_engine": render_info.get("voice_engine", cartoon_voice_engine),
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
            append_job_log(job_id, f"ANIMAÇÃO 2D FINALIZADA COM SUCESSO! ({duration_s:.1f}s | {vid_w}x{vid_h} | 6-Viseme Lip-Sync)", progress=100)
            return {"job_id": job_id, "status": "completed", "engine_style": "cartoon_2d", "master_path": str(master_mp4)}

        # 1. Script generation (guaranteed complete final sentence, zero debug text)
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
            )

        update_job(
            job_id,
            script_json=json.dumps(script, ensure_ascii=False),
            tokens_used=int(script.get("tokens_used", 0)),
            cost_usd=float(script.get("cost_usd", 0.0)),
        )
        append_job_log(
            job_id,
            f"Roteiro gerado via {script.get('provider_used', 'local')} ({script.get('tokens_used', 0)} tokens | ${script.get('cost_usd', 0.0):.5f})",
            progress=16,
            stage="Sintetizando Áudio Broadcast",
        )

        # 2. Narration (Hook A + Body + Complete Closing) + VAD Trim
        hook_a_text = str(script.get("hook_a", topic)).strip()
        hook_b_text = str(script.get("hook_b", hook_a_text)).strip()
        body_lines = [str(x).strip() for x in script.get("body_lines", []) if str(x).strip()]
        closing_line = str(script.get("closing_line") or script.get("loop_bridge") or "").strip()
        # Safety: never leave dangling ellipsis like "porque..."
        if closing_line.endswith("..."):
            closing_line = closing_line.rstrip(".") + " e transforme seus resultados hoje."
        full_text_a = " ".join([hook_a_text, *body_lines, closing_line]).strip()

        voice_engine = client.get("voice_engine") or preset.get("voice_engine", "edge")
        voice_id = client.get("voice_id") or preset.get("voice_id", "pt-BR-AntonioNeural")
        try:
            voice_blend = json.loads(client.get("voice_blend") or preset.get("voice_blend", "{}"))
        except Exception:
            voice_blend = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}

        narr_wav, words_a, speech_dur = await generate_narration(
            text=full_text_a,
            work_dir=work_dir,
            voice_engine=voice_engine,
            voice_id=voice_id,
            voice_blend=voice_blend,
            prefix="narr_a",
        )
        # Final video duration includes 0.40s breathing tail for clean audio finish
        duration_s = round(speech_dur + 0.40, 3)

        hook_word_count = max(3, len(hook_a_text.split()))
        if len(words_a) > hook_word_count:
            hook_split_s = float(words_a[hook_word_count - 1]["end"]) + 0.05
        else:
            hook_split_s = min(3.5, duration_s * 0.25)
        hook_split_s = max(2.0, min(duration_s * 0.40, hook_split_s))

        append_job_log(
            job_id,
            f"Narração PT-BR concluída ({speech_dur:.2f}s voz + 0.40s cauda = {duration_s:.2f}s | {len(words_a)} palavras)",
            progress=28,
            stage="Baixando Filmagens Reais HD (Troca a cada ~3.5s)",
        )

        # 3. High-Retention Real Footage (NEW real video clip every ~3.5 seconds!)
        queries = script.get("broll_queries") or [
            "city night aerial drone",
            "modern office laptop work",
            "financial growth chart business",
            "neon street night timelapse",
            "entrepreneur smartphone coffee",
            "luxury architecture sunset",
        ]
        xfade_dur = 0.30
        n_scenes = max(4, int(round(duration_s / 3.5)))
        scene_dur = (duration_s + xfade_dur * (n_scenes - 1)) / float(n_scenes)

        pixabay_key = settings.get("pixabay_api_key", "")
        pexels_key = settings.get("pexels_api_key", "")
        used_hashes: Set[str] = set()

        quality_clips: List[Dict[str, Any]] = []
        styled_scenes: List[Path] = []
        scene_durations: List[float] = []
        for idx in range(n_scenes):
            q = queries[idx % len(queries)]
            raw_clip = await asyncio.to_thread(
                fetch_unique_real_clip,
                q,
                pixabay_key,
                pexels_key,
                used_hashes,
                idx,
            )
            q_info = await asyncio.to_thread(evaluate_clip_quality, raw_clip, 20.0)
            quality_clips.append({"scene": idx + 1, "clip": raw_clip.name, **q_info})
            scene_out = work_dir / f"scene_{idx:02d}.mp4"
            await asyncio.to_thread(
                prepare_styled_scene,
                raw_clip,
                scene_out,
                scene_dur,
                lut_file,
                idx,
            )
            styled_scenes.append(scene_out)
            scene_durations.append(scene_dur)
            pct = 28 + int(24 * ((idx + 1) / float(n_scenes)))
            append_job_log(
                job_id,
                f"Cena real {idx+1}/{n_scenes} ({scene_dur:.1f}s): {raw_clip.name} | blur={q_info['blur_score']} | green={q_info['green_pixel_ratio']:.1%} | chroma_key_filter=active",
                progress=pct,
            )

        bg_assembled = work_dir / "bg_assembled.mp4"
        bg_assembled, transition_times = await asyncio.to_thread(
            assemble_scenes_with_xfade,
            styled_scenes,
            scene_durations,
            bg_assembled,
            xfade_dur,
        )
        append_job_log(
            job_id,
            f"{n_scenes} cenas reais montadas (~{scene_dur:.1f}s/cena) com LUT '{lut_file}' + xfade (CPU: {read_cpu_temperature_c()}°C)",
            progress=55,
            stage="Masterizando Áudio Broadcast (-14 LUFS + Cauda 0.4s)",
        )

        # 4. Broadcast FM Audio Mastering + 0.40s Tail + Smooth Music Fadeout + Timed SFX
        music_file = ASSETS_DIR / "music" / preset.get("music_file", "dark_pulse.mp3")
        sfx_dir = ASSETS_DIR / "sfx"
        motion_cards = _schedule_motion_cards(script.get("motion_cards", []), duration_s)

        sfx_events = [(sfx_dir / "cinematic_hit.wav", 0.05, 0.34)]
        for tt in transition_times:
            sfx_events.append((sfx_dir / "whoosh_fast.wav", max(0.0, tt - 0.10), 0.38))
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
            0.19,
            0.40,
        )
        append_job_log(
            job_id,
            f"Áudio Broadcast concluído ({duration_s:.2f}s com 0.40s de cauda limpa e fade-out suave).",
            progress=62,
            stage="Renderizando Legendas Hormozi & Cards (Skia C++ + QuickSync)",
        )

        # 5. C++ Skia Compositor (Heavy Montserrat-Black 900, ZERO watermark on Master)
        compositor = SkiaMotionCompositor(preset=preset)
        append_job_log(job_id, f"Tipografia Skia C++ validada: {compositor.font_info}")

        master_mp4 = job_dir / "master.mp4"
        await asyncio.to_thread(
            compositor.composite_onto_video,
            bg_assembled,
            master_audio,
            master_mp4,
            duration_s,
            words_a,
            motion_cards,
            30,
            use_motion_cards,
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
                voice_engine=voice_engine,
                voice_id=voice_id,
                voice_blend=voice_blend,
                prefix="narr_b",
            )
            audio_b = work_dir / "hook_b_audio.m4a"
            audio_b, dur_b = await asyncio.to_thread(
                master_broadcast_audio,
                narr_b_wav,
                music_file,
                [(sfx_dir / "sub_boom.wav", 0.04, 0.36)],
                audio_b,
                speech_b,
                0.19,
                0.12,
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
            await asyncio.to_thread(prepare_styled_scene, raw_b, bg_b_styled, dur_b, lut_file, n_scenes + 1)

            hook_b_intro = work_dir / "hook_b_intro.mp4"
            # ZERO debug cards on Hook B — clean real footage + Hormozi captions only!
            await asyncio.to_thread(
                compositor.composite_onto_video,
                bg_b_styled,
                audio_b,
                hook_b_intro,
                dur_b,
                words_b,
                [],
                30,
                False,
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
        await asyncio.to_thread(export_whatsapp_preview_540p, master_mp4, preview_mp4, watermark_text)

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

        # Extract a clean frame from real footage for editorial 9:16 Cover
        frame_snap = work_dir / "cover_bg.png"
        try:
            await asyncio.to_thread(
                run_ffmpeg_safe,
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.5, duration_s * 0.2):.2f}", "-i", str(bg_assembled), "-frames:v", "1", str(frame_snap)],
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

        ab_thumbs_live: Dict[str, str] = {}
        if aspect_ratio == "16:9" or opts.get("generate_thumbnails_ab"):
            append_job_log(job_id, "Gerando 3 Thumbnails Magnéticas 1280x720 (Skia C++ + rembg u2netp)...", progress=94, stage="Gerando 3 Thumbnails A/B 1280x720")
            raw_thumbs = await asyncio.to_thread(generate_ab_thumbnails_16x9, master_mp4, str(script.get("title", topic)), job_dir)
            ab_thumbs_live = {
                "thumb_a": _rel_output(Path(raw_thumbs["thumb_a"])),
                "thumb_b": _rel_output(Path(raw_thumbs["thumb_b"])),
                "thumb_c": _rel_output(Path(raw_thumbs["thumb_c"])),
                "headline_words": raw_thumbs["headline_words"],
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

        (job_dir / "words.json").write_text(json.dumps(words_a, ensure_ascii=False), encoding="utf-8")
        quality_report = {
            "job_id": job_id,
            "aspect_ratio": aspect_ratio,
            "chroma_key_filter": "active",
            "chroma_key_threshold": 0.35,
            "font_verified": compositor.font_info,
            "retention_audit": script.get("retention_audit", {}),
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
            f"FINALIZADO COM SUCESSO! {n_scenes} cenas reais HD + Legendas Hormozi + Pacote VIP prontos.",
            progress=100,
        )
        return {"job_id": job_id, "status": "completed", "master_path": str(master_mp4)}

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
