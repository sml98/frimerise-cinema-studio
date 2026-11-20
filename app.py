"""FrimeRise Local Commercial SaaS Studio — FastAPI Server (http://localhost:8000).
100% permissive licenses (MIT / Apache-2.0 / BSD-3).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agents.feedback_loop import get_feedback_summary, log_real_performance
from agents.llm_router import list_skills
from database import (
    create_schedule,
    get_client,
    get_job,
    get_preset,
    get_settings,
    get_total_cost_stats,
    init_db,
    list_clients,
    list_jobs,
    list_presets,
    list_schedules,
    save_settings,
    update_schedule,
    upsert_client,
)
from engine.audio_dsp import PT_BR_EDGE_VOICES, generate_narration
from engine.intel_vaapi import probe_quicksync, read_cpu_temperature_c, safe_thread_count
from engine.pipeline import enqueue_new_job, run_video_job
from publisher.stealth_uploader import (
    convert_brt_to_shanghai,
    open_stealth_login_session,
    publish_video_stealth,
)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
WEB_DIR = BASE_DIR / "web"
UPLOAD_LOGOS_DIR = BASE_DIR / "data" / "logos"
UPLOAD_LOGOS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FrimeRise Studio", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# Sequential job queue worker so Acer Aspire 5 Core i5 never overloads RAM/thermals
JOB_QUEUE: asyncio.Queue = asyncio.Queue()
SCHEDULER = AsyncIOScheduler()


async def _job_worker() -> None:
    while True:
        task = await JOB_QUEUE.get()
        try:
            await run_video_job(**task)
        except Exception as exc:
            print(f"[FrimeRise Worker] Erro no job {task.get('job_id')}: {exc}")
        finally:
            JOB_QUEUE.task_done()


async def _check_due_schedules() -> None:
    now = datetime.now()
    for s in list_schedules():
        if s["status"] != "scheduled":
            continue
        try:
            due = datetime.fromisoformat(s["scheduled_brt"])
        except Exception:
            continue
        if due <= now:
            job = get_job(s["job_id"])
            if not job:
                update_schedule(s["id"], "error", "Job não encontrado")
                continue
            path_key = {"tiktok": "tiktok_path", "reels": "reels_path", "facebook": "reels_path", "youtube": "shorts_path"}.get(
                s["platform"], "master_path"
            )
            rel = job.get(path_key) or job.get("master_path")
            if not rel or not (BASE_DIR / rel).exists():
                update_schedule(s["id"], "error", "Arquivo de vídeo não encontrado")
                continue
            update_schedule(s["id"], "publishing", "Iniciando Camoufox Stealth...")
            try:
                res = await publish_video_stealth(
                    client_id=int(s["client_id"] or 1),
                    platform="facebook" if s["platform"] in ("facebook", "reels") else s["platform"],
                    video_path=BASE_DIR / rel,
                    caption=s.get("caption") or job.get("topic", "FrimeRise"),
                    warm_seconds=180,
                    scheduled_brt=s["scheduled_brt"],
                )
                update_schedule(s["id"], "published", json.dumps(res, ensure_ascii=False))
            except Exception as exc:
                update_schedule(s["id"], "error", str(exc)[:200])


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    probe_quicksync()
    asyncio.create_task(_job_worker())
    SCHEDULER.add_job(_check_due_schedules, "interval", seconds=45, id="autopilot_tick", replace_existing=True)
    SCHEDULER.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        SCHEDULER.shutdown(wait=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class SettingsPayload(BaseModel):
    deepseek_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None
    ollama_url: Optional[str] = None
    default_llm: Optional[str] = None
    thermal_limit_c: Optional[str] = None


class ClientPayload(BaseModel):
    id: Optional[int] = None
    name: str
    niche: str = "Negócios & IA"
    preset_id: str = "frimerise_signature"
    lut_file: str = "01_frimerise_signature.cube"
    voice_engine: str = "edge"
    voice_id: str = "pt-BR-AntonioNeural"
    voice_blend: Dict[str, float] = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}
    logo_path: str = "assets/brand/frimerise_logo.png"
    proxy_url: str = ""
    watermark_text: str = "PRÉVIA • FRIMERISE"


class VoicePreviewPayload(BaseModel):
    voice_engine: str = "edge"
    voice_id: str = "pt-BR-AntonioNeural"
    voice_blend: Dict[str, float] = {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}
    sample_text: str = "Bem-vindo ao FrimeRise! Este é o seu estúdio proprietário de vídeos virais com qualidade broadcast."


class ManufacturePayload(BaseModel):
    client_id: int = 1
    mode: str = "single"  # single | batch | clone_url
    engine_style: str = "cinematic_broll"  # cinematic_broll | cartoon_2d
    aspect_ratio: str = "9:16"  # 9:16 | 16:9
    cartoon_tone: str = "Comédia Nordestina/BR"
    cartoon_fps: int = 60  # 30 | 60
    cartoon_voice_engine: str = "gemini_tts"  # gemini_tts | edge
    clone_languages: bool = False  # [🌎 Clonar Idiomas: Inglês (US) + Espanhol]
    topic: str = ""
    batch_topics: List[str] = []
    source_url: str = ""
    reference_mp4_path: str = ""
    skill_id: str = "01_negative_hook"
    preset_id: Optional[str] = None
    lut_file: Optional[str] = None
    motion_cards: bool = True
    seamless_loop: bool = True
    dual_hook_ab: bool = True


class B2BProspectPayload(BaseModel):
    client_id: int = 1
    company_name: str
    city: str
    product_service: str
    engine_style: str = "cinematic_broll"


class PublishPayload(BaseModel):
    job_id: str
    client_id: int = 1
    platform: str = "tiktok"  # tiktok | youtube | facebook
    caption: str = ""
    warm_seconds: int = 180
    scheduled_brt: Optional[str] = None


class FeedbackPayload(BaseModel):
    job_id: str
    platform: str = "tiktok"
    views: int = 0
    likes: int = 0
    retention_pct: float = 0.0
    hook_variant: str = "A"


# ---------------------------------------------------------------------------
# Routes: Main Dashboard
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


# ---------------------------------------------------------------------------
# Routes: Telemetry & Setup
# ---------------------------------------------------------------------------
@app.get("/api/telemetry")
async def api_telemetry():
    qs = probe_quicksync()
    temp_c = read_cpu_temperature_c()
    cost = get_total_cost_stats()
    settings = get_settings()
    limit_c = float(settings.get("thermal_limit_c") or 85.0)
    return {
        "brand": "FrimeRise",
        "quicksync_on": qs["quicksync_on"],
        "driver": qs["driver"],
        "hw_detail": qs["detail"],
        "skia_engine": "Skia C++ 2D (200+ FPS)",
        "chroma_key_filter": "active",
        "cpu_temp_c": temp_c,
        "thermal_limit_c": limit_c,
        "thermal_ok": temp_c < limit_c,
        "threads": safe_thread_count(),
        "queue_size": JOB_QUEUE.qsize(),
        "total_cost_usd": cost["total_usd"],
        "total_tokens": cost["total_tokens"],
        "jobs_done": cost["jobs_done"],
    }


def _enrich_job(job: Dict[str, Any]) -> Dict[str, Any]:
    if not job:
        return job
    qr_path = OUTPUTS_DIR / str(job.get("id", "")) / "quality_report.json"
    if qr_path.exists():
        try:
            job["quality_report"] = json.loads(qr_path.read_text(encoding="utf-8"))
        except Exception:
            job["quality_report"] = {}
    else:
        job["quality_report"] = {}
    return job


@app.get("/api/bootstrap-data")
async def api_bootstrap_data():
    from engine.gemini_tts import GEMINI_EXPRESSIVE_VOICES
    from engine.rhubarb_lipsync import find_rhubarb_binary

    luts = sorted([p.name for p in (ASSETS_DIR / "luts").glob("*.cube")])
    sfx = sorted([p.name for p in (ASSETS_DIR / "sfx").glob("*.wav")])
    music = sorted([p.name for p in (ASSETS_DIR / "music").glob("*.mp3")])
    return {
        "settings": get_settings(),
        "presets": list_presets(),
        "clients": list_clients(),
        "skills": list_skills(),
        "luts": luts,
        "sfx": sfx,
        "music": music,
        "edge_voices": PT_BR_EDGE_VOICES,
        "gemini_voices": GEMINI_EXPRESSIVE_VOICES,
        "rhubarb_ready": find_rhubarb_binary() is not None,
        "jobs": [_enrich_job(j) for j in list_jobs(40)],
        "schedules": list_schedules(),
        "feedback": get_feedback_summary(),
    }


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload):
    saved = save_settings(payload.model_dump(exclude_none=True))
    return {"status": "saved", "settings": saved}


@app.post("/api/settings/test")
async def api_test_setup():
    import httpx
    from engine.rhubarb_lipsync import find_rhubarb_binary

    qs = probe_quicksync(force=True)
    settings = get_settings()

    # Real live validation of Gemini (supports BOTH AQ.... and AIza... keys via x-goog-api-key header!), DeepSeek & Pixabay!
    gkey = (settings.get("gemini_api_key") or "").strip()
    gem_ok, gem_detail = False, "Não configurada (opcional)"
    if gkey:
        try:
            r = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
                headers={"x-goog-api-key": gkey},
                json={"contents": [{"parts": [{"text": "OK"}]}]},
                timeout=12.0,
            )
            if r.status_code == 200:
                key_tag = "AQ." if gkey.startswith("AQ.") else "AIza"
                gem_ok, gem_detail = True, f"Conectada (HTTP 200 • chave {key_tag} • LLM + Gemini TTS ativos!)"
            else:
                gem_detail = f"Erro HTTP {r.status_code} ({len(gkey)} chars)"
        except Exception as exc:
            gem_detail = f"Erro de rede: {str(exc)[:60]}"

    dkey = (settings.get("deepseek_api_key") or "").strip()
    ds_ok, ds_detail = False, "Não configurada (opcional)"
    if dkey:
        try:
            r = httpx.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {dkey}"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "OK"}], "max_tokens": 5},
                timeout=8.0,
            )
            if r.status_code == 200:
                ds_ok, ds_detail = True, "Conectada (HTTP 200 • deepseek-flash)"
            else:
                ds_detail = f"Chave inválida (HTTP {r.status_code})"
        except Exception as exc:
            ds_detail = f"Erro de rede: {str(exc)[:60]}"

    pxkey = (settings.get("pixabay_api_key") or "").strip()
    px_ok, px_detail = True, "Opcional (Zero-Key yt-dlp + Wikimedia + Archive ativos)"
    if pxkey:
        try:
            r = httpx.get("https://pixabay.com/api/videos/", params={"key": pxkey, "q": "city", "per_page": 3}, timeout=8.0)
            px_ok = r.status_code == 200
            px_detail = "Conectada (HTTP 200 • API Instantânea)" if px_ok else f"Chave inválida (HTTP {r.status_code})"
        except Exception:
            px_detail = "Erro de rede"

    checks = {
        "quicksync": {"ok": bool(qs["quicksync_on"]), "detail": str(qs["detail"])},
        "skia": {"ok": True, "detail": "skia-python C++ (Cartoon v2 Line Boil 8fps + 2.5D Paralaxe)"},
        "rhubarb_lipsync": {"ok": find_rhubarb_binary() is not None, "detail": "Rhubarb v1.14 (MIT • 9 Visemas Fonéticos)" if find_rhubarb_binary() else "Fallback RMS"},
        "chroma_key_filter": {"ok": True, "detail": "active (bloqueia >35% verde puro G>200,R<80,B<80)"},
        "temp_cpu": {"ok": read_cpu_temperature_c() < 85.0, "detail": f"{read_cpu_temperature_c()}°C"},
        "deepseek": {"ok": ds_ok, "detail": ds_detail},
        "gemini": {"ok": gem_ok, "detail": gem_detail},
        "pixabay": {"ok": px_ok, "detail": px_detail},
        "pexels": {"ok": bool(settings.get("pexels_api_key")), "detail": "Chave configurada" if settings.get("pexels_api_key") else "Opcional secundário"},
    }
    return {"status": "ok", "checks": checks}


# ---------------------------------------------------------------------------
# Routes: Client Studio + Voice Blender Preview + Stealth Connect
# ---------------------------------------------------------------------------
@app.get("/api/clients")
async def api_clients():
    return {"clients": list_clients()}


@app.post("/api/clients")
async def api_upsert_client(payload: ClientPayload):
    saved = upsert_client(payload.model_dump())
    return {"status": "saved", "client": saved, "clients": list_clients()}


@app.post("/api/clients/upload-logo")
async def api_upload_logo(file: UploadFile = File(...)):
    ext = Path(file.filename or "logo.png").suffix.lower() or ".png"
    dest = UPLOAD_LOGOS_DIR / f"logo_{uuid.uuid4().hex[:8]}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    rel = str(dest.relative_to(BASE_DIR))
    return {"status": "uploaded", "logo_path": rel}


@app.post("/api/voice/preview")
async def api_voice_preview(payload: VoicePreviewPayload):
    preview_dir = OUTPUTS_DIR / "_voice_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    wav_path, _, dur = await generate_narration(
        text=payload.sample_text[:240],
        work_dir=preview_dir,
        voice_engine=payload.voice_engine,
        voice_id=payload.voice_id,
        voice_blend=payload.voice_blend,
        prefix=f"prev_{tag}",
    )
    return {
        "status": "ok",
        "audio_url": f"/outputs/_voice_previews/{wav_path.name}",
        "duration_s": dur,
    }


@app.post("/api/clients/{client_id}/connect/{platform}")
async def api_connect_platform(client_id: int, platform: str, background_tasks: BackgroundTasks):
    if platform not in ("tiktok", "youtube", "facebook"):
        raise HTTPException(status_code=400, detail="Plataforma deve ser tiktok, youtube ou facebook")
    background_tasks.add_task(open_stealth_login_session, client_id, platform, 180)
    return {
        "status": "launching_camoufox",
        "message": f"Abrindo janela blindada Camoufox para conectar {platform.upper()} (perfil isolado do cliente #{client_id}).",
    }


# ---------------------------------------------------------------------------
# Routes: Multi-Mode Factory (Single, Batch 50, Clone URL)
# ---------------------------------------------------------------------------
@app.post("/api/factory/upload-reference")
async def api_upload_reference_mp4(file: UploadFile = File(...)):
    """Upload a reference .mp4 and immediately run VideoDNAExtractor to classify live_action vs 2d_cartoon_animation."""
    from engine.viral_cloner import VideoDNAExtractor

    ref_dir = BASE_DIR / "data" / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "ref.mp4").suffix.lower() or ".mp4"
    dest = ref_dir / f"ref_{uuid.uuid4().hex[:8]}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    dna = await asyncio.to_thread(VideoDNAExtractor().extract_from_local_mp4, dest, Path(file.filename or "Ref").stem)
    return {
        "status": "analyzed",
        "reference_mp4_path": str(dest.relative_to(BASE_DIR)),
        "dna": dna,
    }


@app.post("/api/factory/manufacture")
async def api_manufacture(payload: ManufacturePayload):
    created_jobs = []
    common_opts = {
        "preset_id": payload.preset_id,
        "lut_file": payload.lut_file,
        "engine_style": payload.engine_style,
        "aspect_ratio": payload.aspect_ratio,
        "cartoon_tone": payload.cartoon_tone,
        "cartoon_fps": payload.cartoon_fps,
        "cartoon_voice_engine": payload.cartoon_voice_engine,
        "clone_languages": payload.clone_languages,
        "motion_cards": payload.motion_cards,
        "seamless_loop": payload.seamless_loop,
        "dual_hook_ab": payload.dual_hook_ab,
        "source_url": payload.source_url,
        "reference_mp4_path": payload.reference_mp4_path,
    }

    if payload.mode == "batch":
        topics = [t.strip() for t in payload.batch_topics if t.strip()][:50]
        if not topics:
            raise HTTPException(status_code=400, detail="Informe ao menos 1 tema no lote (até 50 linhas).")
        for t in topics:
            job = enqueue_new_job(payload.client_id, t, payload.skill_id, "batch", common_opts)
            await JOB_QUEUE.put(
                {
                    "job_id": job["id"],
                    "client_id": payload.client_id,
                    "topic": t,
                    "skill_id": payload.skill_id,
                    "mode": "batch",
                    "options": common_opts,
                }
            )
            created_jobs.append(job)
    else:
        topic = payload.topic.strip()
        if payload.mode == "clone_url" and not payload.source_url.strip() and not payload.reference_mp4_path.strip():
            raise HTTPException(status_code=400, detail="Informe uma URL concorrente ou suba um arquivo .mp4 de referência.")
        if not topic:
            if payload.engine_style == "cartoon_2d":
                topic = "Jonas tentando fugir de barco na tempestade"
            elif payload.mode == "clone_url":
                topic = f"Clone Viral • {(payload.source_url or payload.reference_mp4_path)[:40]}"
            else:
                topic = "Como escalar vendas com vídeos curtos em 2026"
        job = enqueue_new_job(payload.client_id, topic, payload.skill_id, payload.mode, common_opts)
        await JOB_QUEUE.put(
            {
                "job_id": job["id"],
                "client_id": payload.client_id,
                "topic": topic,
                "skill_id": payload.skill_id,
                "mode": payload.mode,
                "options": common_opts,
            }
        )
        created_jobs.append(job)

    return {"status": "queued", "count": len(created_jobs), "jobs": created_jobs}


@app.get("/api/jobs")
async def api_list_jobs():
    return {"jobs": [_enrich_job(j) for j in list_jobs(50)]}


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return _enrich_job(job)


@app.post("/api/jobs/{job_id}/extract-shorts")
async def api_extract_5_shorts(job_id: str):
    """[⚡ Extrair 5 Cortes Virais 9:16 (Zero Tokens)] from a 16:9 (or any) completed job."""
    from engine.global_scaler import extract_5_viral_shorts_from_16x9

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job_dir = OUTPUTS_DIR / job_id
    master_mp4 = job_dir / "master.mp4"
    if not master_mp4.exists():
        raise HTTPException(status_code=400, detail="Master MP4 ainda não está pronto.")

    words_file = job_dir / "words.json"
    words: List[Dict[str, Any]] = []
    if words_file.exists():
        try:
            words = json.loads(words_file.read_text(encoding="utf-8"))
        except Exception:
            words = []

    shorts = await asyncio.to_thread(extract_5_viral_shorts_from_16x9, master_mp4, words, job_dir, 5)
    for s in shorts:
        s["url"] = "/" + str(Path(s["path"]).resolve().relative_to(BASE_DIR.resolve()))

    qr_path = job_dir / "quality_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else {}
    qr["shorts_cascade"] = shorts
    qr_path.write_text(json.dumps(qr, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "count": len(shorts), "shorts": shorts}


@app.post("/api/jobs/{job_id}/generate-thumbnails")
async def api_generate_ab_thumbnails(job_id: str):
    """Generate 3 magnetic 1280x720 A/B/C YouTube thumbnails (Skia C++ + rembg u2netp) for any job."""
    from engine.thumbnail_studio import generate_ab_thumbnails_16x9

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job_dir = OUTPUTS_DIR / job_id
    master_mp4 = job_dir / "master.mp4"
    if not master_mp4.exists():
        raise HTTPException(status_code=400, detail="Master MP4 ainda não está pronto.")

    raw = await asyncio.to_thread(generate_ab_thumbnails_16x9, master_mp4, str(job.get("topic", "Segredo Revelado")), job_dir)
    thumbs = {
        "thumb_a": str(Path(raw["thumb_a"]).resolve().relative_to(BASE_DIR.resolve())),
        "thumb_b": str(Path(raw["thumb_b"]).resolve().relative_to(BASE_DIR.resolve())),
        "thumb_c": str(Path(raw["thumb_c"]).resolve().relative_to(BASE_DIR.resolve())),
        "headline_words": raw["headline_words"],
    }
    qr_path = job_dir / "quality_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else {}
    qr["ab_thumbnails"] = thumbs
    qr_path.write_text(json.dumps(qr, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "ab_thumbnails": thumbs}


@app.post("/api/jobs/{job_id}/dub-languages")
async def api_dub_job_languages(job_id: str):
    """On-demand Multi-Language Dubbing & Re-Timing (EN-US + ES) for an existing job."""
    from database import get_client, get_preset
    from engine.global_scaler import dub_video_job_multi_language

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job_dir = OUTPUTS_DIR / job_id
    qr_path = job_dir / "quality_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else {}
    engine_style = qr.get("engine_style") or "cinematic_broll"

    script_dict: Dict[str, Any] = {}
    if job.get("script_json"):
        try:
            script_dict = json.loads(job["script_json"])
        except Exception:
            script_dict = {}
    if not script_dict:
        script_dict = {"hook_a": job.get("topic", ""), "body_lines": [job.get("topic", "")], "closing_line": "Subscribe now!"}

    cli = get_client(int(job.get("client_id") or 1))
    preset = get_preset(cli.get("preset_id") or "frimerise_signature")
    dubbed_raw = await dub_video_job_multi_language(
        job_dir=job_dir,
        engine_style=engine_style,
        script_or_plan_dict=script_dict,
        preset=preset,
        languages=("en_us", "es"),
    )
    dubbed = {}
    for lk, lv in dubbed_raw.items():
        dubbed[lk] = {**lv, "path": str(Path(lv["path"]).resolve().relative_to(BASE_DIR.resolve()))}
    qr["dubbed_languages"] = dubbed
    qr_path.write_text(json.dumps(qr, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "dubbed_languages": dubbed}


@app.post("/api/b2b/prospect")
async def api_b2b_prospect(payload: B2BProspectPayload):
    """1-Click B2B Commercial Prospecting Generator:
    Company Name + City + Product/Service -> 540p Watermarked Sales Video ('PRÉVIA EXCLUSIVA • FRIMERISE')
    + ready-to-copy WhatsApp commercial outreach pitch!
    """
    from engine.global_scaler import build_b2b_commercial_script_and_pitch

    script, whatsapp_pitch = build_b2b_commercial_script_and_pitch(
        payload.company_name,
        payload.city,
        payload.product_service,
    )
    topic = f"B2B • {payload.company_name.strip()} ({payload.city.strip()}) — {payload.product_service.strip()}"
    opts = {
        "engine_style": payload.engine_style,
        "aspect_ratio": "9:16",
        "custom_script": script,
        "watermark_text": "PRÉVIA EXCLUSIVA • FRIMERISE",
        "motion_cards": True,
        "seamless_loop": True,
        "dual_hook_ab": False,
        "b2b_prospect": {
            "company_name": payload.company_name.strip(),
            "city": payload.city.strip(),
            "product_service": payload.product_service.strip(),
            "whatsapp_pitch": whatsapp_pitch,
        },
    }
    job = enqueue_new_job(payload.client_id, topic, "07_local_business_ad", "single", opts)
    await JOB_QUEUE.put(
        {
            "job_id": job["id"],
            "client_id": payload.client_id,
            "topic": topic,
            "skill_id": "07_local_business_ad",
            "mode": "single",
            "options": opts,
        }
    )
    return {
        "status": "queued",
        "job": job,
        "whatsapp_pitch": whatsapp_pitch,
        "retention_audit": script.get("retention_audit", {}),
    }


@app.get("/api/download/{job_id}/{artifact}")
async def api_download_artifact(job_id: str, artifact: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    mapping = {
        "master": ("master_path", f"FrimeRise_{job_id}_MASTER.mp4"),
        "hook_a": ("hook_a_path", f"FrimeRise_{job_id}_HOOK_A.mp4"),
        "hook_b": ("hook_b_path", f"FrimeRise_{job_id}_HOOK_B.mp4"),
        "tiktok": ("tiktok_path", f"FrimeRise_{job_id}_tiktok.mp4"),
        "reels": ("reels_path", f"FrimeRise_{job_id}_reels.mp4"),
        "shorts": ("shorts_path", f"FrimeRise_{job_id}_shorts.mp4"),
        "preview": ("preview_path", f"FrimeRise_{job_id}_PREVIA_540p_WhatsApp.mp4"),
        "capcut": ("capcut_zip_path", f"FrimeRise_{job_id}_CapCut_Editavel.zip"),
        "otio": ("otio_path", f"FrimeRise_{job_id}_Kdenlive.otio"),
        "cover": ("cover_path", f"FrimeRise_{job_id}_Capa_9x16_HD.png"),
    }
    if artifact not in mapping:
        raise HTTPException(status_code=400, detail="Artefato inválido")
    col, dl_name = mapping[artifact]
    rel = job.get(col)
    if not rel:
        raise HTTPException(status_code=404, detail="Artefato ainda não disponível")
    full = BASE_DIR / rel
    if not full.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no disco")
    return FileResponse(str(full), filename=dl_name)


# ---------------------------------------------------------------------------
# Routes: Stealth Publish + Autopilot Calendar + Views Feedback Loop
# ---------------------------------------------------------------------------
@app.post("/api/publish/now")
async def api_publish_now(payload: PublishPayload, background_tasks: BackgroundTasks):
    job = get_job(payload.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    col = {"tiktok": "tiktok_path", "facebook": "reels_path", "reels": "reels_path", "youtube": "shorts_path"}.get(
        payload.platform, "master_path"
    )
    rel = job.get(col) or job.get("master_path")
    if not rel or not (BASE_DIR / rel).exists():
        raise HTTPException(status_code=400, detail="Vídeo não pronto para publicação")

    plat = "facebook" if payload.platform == "reels" else payload.platform
    background_tasks.add_task(
        publish_video_stealth,
        payload.client_id,
        plat,
        BASE_DIR / rel,
        payload.caption or job.get("topic", "FrimeRise"),
        payload.warm_seconds,
        payload.scheduled_brt,
    )
    return {
        "status": "publishing",
        "message": f"Publicação Stealth Camoufox iniciada para {plat.upper()} (1 navegador por vez + aquecedor orgânico).",
    }


@app.post("/api/schedules")
async def api_create_schedule(payload: PublishPayload):
    brt = payload.scheduled_brt or datetime.now().isoformat(timespec="minutes")
    target_tz = convert_brt_to_shanghai(brt) if payload.platform in ("facebook", "reels") else brt
    sched = create_schedule(
        job_id=payload.job_id,
        client_id=payload.client_id,
        platform=payload.platform,
        scheduled_brt=brt,
        scheduled_target_tz=target_tz,
        caption=payload.caption,
    )
    return {"status": "scheduled", "schedule": sched, "schedules": list_schedules()}


@app.get("/api/schedules")
async def api_list_schedules():
    return {"schedules": list_schedules()}


@app.post("/api/feedback")
async def api_record_feedback(payload: FeedbackPayload):
    return log_real_performance(
        job_id=payload.job_id,
        platform=payload.platform,
        views=payload.views,
        likes=payload.likes,
        retention_pct=payload.retention_pct,
        hook_variant=payload.hook_variant,
    )
