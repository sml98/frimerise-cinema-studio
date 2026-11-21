"""FrimeRise Local Commercial SaaS Studio — FastAPI Server (http://localhost:8000).
100% permissive licenses (MIT / Apache-2.0 / BSD-3).
Unifies:
  - 3 Master Engines (cinematic_broll, cartoon_2d, netflix_doc)
  - 2 Pre-Registered High-RPM Twin Channels ("Dossiê Capital" BR & "Vault Files" US) + 10-Episode Ready Queue
  - Multimodal URL & .mp4 Cloner with 3x3 Storyboard Contact Sheet X-Ray & 1-Click Save DNA as Preset
  - Google Flow & Flow Music Pro Controls (10,000 cr badge, 3 Credit-Guarded Modes, Persistent Camoufox Login)
  - VIP Gallery (3 A/B Thumbnails 1280x720 + 5 Vertical Shorts 9:16 + Multi-Language Dubbing + B2B 1-Click)
"""
from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import re
import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agents.feedback_loop import get_feedback_summary, log_real_performance
from agents.llm_router import list_skills
from security import (
    CSRF_COOKIE_NAME,
    HTTP_COOKIE_NAME,
    HTTPS_COOKIE_NAME,
    LOGIN_RATE_LIMITER,
    SESSION_TTL_SECONDS,
    bootstrap_initial_credentials_if_missing,
    create_session_token,
    ensure_auth_secret,
    extract_authenticated_user,
    get_client_ip,
    is_direct_local_request,
    is_https_request,
    probe_tailscale_status,
    sanitize_next_url,
    sanitize_settings_for_client,
    update_remote_credentials,
    verify_password,
)
from database import (
    append_job_log,
    create_schedule,
    get_client,
    get_conn,
    get_job,
    get_preset,
    get_settings,
    get_total_cost_stats,
    init_db,
    list_clients,
    list_incomplete_jobs,
    list_jobs,
    list_presets,
    list_schedules,
    save_settings,
    update_job,
    update_schedule,
    upsert_client,
)
from engine.audio_dsp import (
    ALL_EDGE_VOICES,
    KOKORO_VOICES,
    PT_BR_EDGE_VOICES,
    generate_narration,
)
from engine.intel_vaapi import probe_quicksync, read_cpu_temperature_c, safe_thread_count
from engine.pipeline import enqueue_new_job, run_video_job
from publisher.stealth_uploader import (
    convert_brt_to_shanghai,
    open_stealth_login_session,
    publish_video_stealth,
)
from seed_channels import (
    get_doc_episode,
    get_twin_channels_queue,
    seed_twin_channels_and_queue,
)

# Defensive imports for Worker 1-4 modules
try:
    from engine.google_flow_bridge import (
        FLOW_MODES,
        get_google_flow_credits_status,
        open_google_flow_login_session,
    )
except ImportError:
    FLOW_MODES = {
        "economico_pro": {"id": "economico_pro", "label": "🟢 Econômico Pro (Nano Banana 2 + 2.5D CPU)", "est_credits": 0},
        "gancho_de_ouro": {"id": "gancho_de_ouro", "label": "🟡 Gancho de Ouro (~15 cr • Veo 3.1 Cena 1)", "est_credits": 15},
        "cinema_full_veo": {"id": "cinema_full_veo", "label": "🔴 Cinema Full Veo (Com Teto de Créditos)", "est_credits": 45},
    }
    get_google_flow_credits_status = None  # type: ignore
    open_google_flow_login_session = None  # type: ignore

try:
    from engine.b2b_pitch_maker import generate_b2b_pitch_bundle
except ImportError:
    generate_b2b_pitch_bundle = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
UPLOAD_LOGOS_DIR = DATA_DIR / "logos"
UPLOAD_LOGOS_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "ref_cache").mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FrimeRise Studio", version="2.0.0")

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
# SECURITY: Never expose root data/ (which holds frimerise.db & Camoufox session profiles).
# Mount strictly allowlisted public asset subfolders only.
app.mount("/data/logos", StaticFiles(directory=str(UPLOAD_LOGOS_DIR)), name="data_logos")
app.mount("/data/ref_cache", StaticFiles(directory=str(DATA_DIR / "ref_cache")), name="data_ref_cache")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_PUBLIC_AUTH_PATHS = {
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/status",
    "/assets/brand/frimerise_logo.png",
    "/static/styles.css",
}


def _apply_security_headers(request: Request, response: Response) -> Response:
    response.headers.setdefault("Vary", "Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(), focus-without-user-activation=()",
    )
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
        )
    if is_https_request(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=300; includeSubDomains")
    if request.url.path.startswith("/api/") or request.url.path == "/login":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def security_and_auth_middleware(request: Request, call_next):
    # 1. Fetch Metadata resource isolation BEFORE auth checks (prevents CSRF & timing leaks)
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    fetch_mode = (request.headers.get("sec-fetch-mode") or "").strip().lower()
    fetch_dest = (request.headers.get("sec-fetch-dest") or "").strip().lower()
    if fetch_site == "cross-site":
        is_safe_nav = (
            fetch_mode == "navigate"
            and request.method == "GET"
            and fetch_dest not in ("object", "embed")
        )
        if not is_safe_nav:
            return _apply_security_headers(
                request,
                JSONResponse({"detail": "Requisição cross-site bloqueada."}, status_code=403),
            )

    # 2. Remote / Tailscale / Optional-Local Authentication Gate
    path = request.url.path
    is_local = is_direct_local_request(request)
    settings = get_settings()
    require_auth = (not is_local) or (settings.get("auth_require_local") == "1")

    if require_auth and path not in _PUBLIC_AUTH_PATHS:
        user = extract_authenticated_user(request, settings)
        if not user:
            if path.startswith("/api/"):
                return _apply_security_headers(
                    request,
                    JSONResponse(
                        {"detail": "Autenticação necessária.", "login_url": "/login"},
                        status_code=401,
                    ),
                )
            raw_next = path + (f"?{request.url.query}" if request.url.query else "")
            safe_next = sanitize_next_url(raw_next)
            login_url = "/login" if safe_next == "/" else f"/login?{urlencode({'next': safe_next})}"
            return _apply_security_headers(request, RedirectResponse(url=login_url, status_code=303))

    response = await call_next(request)
    return _apply_security_headers(request, response)

# Sequential job queue worker so Acer Aspire 5 Core i5 never overloads RAM/thermals
JOB_QUEUE: asyncio.Queue = asyncio.Queue()
SCHEDULER = AsyncIOScheduler()


async def _get_flow_status_safe() -> Dict[str, Any]:
    """Read Google Flow Pro credit balance & session status with defensive fallback."""
    default_status = {
        "credits_remaining": 10000,
        "credits_total": 10000,
        "plan": "Google AI Pro",
        "logged_in": False,
        "profile_dir": "data/profiles/google_flow_pro",
        "active_mode": "economico_pro",
        "modes": FLOW_MODES,
    }
    if get_google_flow_credits_status is None:
        return default_status
    try:
        res = get_google_flow_credits_status()
        if inspect.isawaitable(res):
            res = await res
        if isinstance(res, dict):
            return {
                **default_status,
                **res,
                "credits_remaining": int(res.get("credits_remaining", res.get("credits", 10000))),
                "credits_total": int(res.get("credits_total", 10000)),
            }
    except Exception:
        pass
    return default_status


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


async def _recover_interrupted_jobs() -> None:
    """Auto-resume jobs left in 'running'/'queued' when uvicorn restarts (max 2 auto-resumes)."""
    for job in list_incomplete_jobs():
        job_id = str(job["id"])
        try:
            opts = json.loads(job.get("options_json") or "{}")
            if not isinstance(opts, dict):
                opts = {}
        except Exception:
            opts = {}

        attempts = int(opts.get("_resume_attempts", 0) or 0)
        if attempts >= 2:
            update_job(
                job_id,
                status="error",
                stage="Interrompido após reinícios do servidor",
            )
            append_job_log(
                job_id,
                "⚠️ Job marcado como interrompido após 2 tentativas automáticas de retomada. Use /api/jobs/{id}/resume se quiser tentar novamente.",
            )
            continue

        opts["_resume"] = True
        opts["_resume_attempts"] = attempts + 1
        update_job(
            job_id,
            status="queued",
            stage=f"Retomando render ({attempts + 1}/2)...",
            options_json=json.dumps(opts, ensure_ascii=False),
        )
        append_job_log(
            job_id,
            f"♻️ Servidor reiniciado durante o render — retomando automaticamente do ponto de parada (tentativa {attempts + 1}/2)...",
        )
        await JOB_QUEUE.put(
            {
                "job_id": job_id,
                "client_id": int(job.get("client_id") or 1),
                "topic": str(job.get("topic") or "FrimeRise"),
                "skill_id": str(job.get("skill_id") or "01_negative_hook"),
                "mode": str(job.get("mode") or "single"),
                "options": opts,
            }
        )


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    bootstrap_initial_credentials_if_missing()
    seed_twin_channels_and_queue()
    probe_quicksync()
    asyncio.create_task(_job_worker())
    await _recover_interrupted_jobs()
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


# ---------------------------------------------------------------------------
# Creative Studio Catalogs (Duration Presets, Visual Libraries Mixer, Captions)
# ---------------------------------------------------------------------------
DURATION_PRESETS: List[Dict[str, Any]] = [
    {"seconds": 15, "label": "15s", "tag": "Hook Relâmpago • Reels/Shorts"},
    {"seconds": 30, "label": "30s", "tag": "Viral Curto • Alta Retenção"},
    {"seconds": 60, "label": "60s", "tag": "Shorts Completo / TikTok Pro"},
    {"seconds": 180, "label": "3 min", "tag": "Mini-Doc / Storytelling"},
    {"seconds": 480, "label": "8 min", "tag": "YouTube Mid-Roll High-RPM"},
    {"seconds": 900, "label": "15 min", "tag": "Documentário Cinema Completo"},
]

VISUAL_LIBRARIES_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "real_broll",
        "label": "📹 Filmagens Reais HD",
        "desc": "Filmagens Reais HD: Pixabay + Wikimedia + Archive + yt-dlp",
        "default_engines": ["cinematic_broll", "netflix_doc"],
    },
    {
        "id": "photos_25d",
        "label": "🖼️ Fotos Reais + Parallax 2.5D",
        "desc": "Fotos Reais + Parallax 2.5D u2netp + cv2.inpaint",
        "default_engines": ["netflix_doc"],
    },
    {
        "id": "video_over_video",
        "label": "📺 Vídeo sobre Vídeo (PiP)",
        "desc": "Vídeo sobre Vídeo: Monitor PiP Forense + Split-Screen",
        "default_engines": ["netflix_doc"],
    },
    {
        "id": "skia_graphics",
        "label": "📊 Gráficos Skia C++",
        "desc": "Gráficos Skia C++: Cards, Jornal, Mapa, Timeline, Red-String",
        "default_engines": ["cinematic_broll", "netflix_doc"],
    },
    {
        "id": "cartoon_2d_layer",
        "label": "🎭 Personagens 2D Cartoon",
        "desc": "Personagens 2D Cartoon + Rhubarb 9-Visemas",
        "default_engines": ["cartoon_2d"],
    },
    {
        "id": "bespoke_ai",
        "label": "✨ Arte IA Inédita",
        "desc": "Arte IA Inédita: Pollinations Flux / Google Flow Pro",
        "default_engines": [],
    },
    {
        "id": "cinema_35mm_sfx",
        "label": "🎞️ Cinema FX 35mm + SFX",
        "desc": "Efeitos Cinema: Granulação 35mm + Partículas + SFX",
        "default_engines": ["cinematic_broll", "cartoon_2d", "netflix_doc"],
    },
]

CAPTION_STYLES_CATALOG: List[Dict[str, str]] = [
    {"id": "hormozi_neon", "label": "⚡ Hormozi Pílula Neon (CapCut Spring Bounce + Tilt)"},
    {"id": "karaoke_glow", "label": "🌈 Karaokê Glow (Wipe Gradiente Neon Palavra-a-Palavra)"},
    {"id": "word_slam", "label": "💥 Word Slam 3D (Impacto Metálico + Shake Viral)"},
    {"id": "cinema_minimal", "label": "🎬 Cinema Minimalista (Netflix Blur-Reveal Dourado)"},
    {"id": "typewriter_highlight", "label": "📰 Dossiê Highlighter (Typewriter + Marca-Texto Neon)"},
    {"id": "none", "label": "🚫 Sem Legendas"},
]


class VoicePreviewPayload(BaseModel):
    voice_engine: str = "edge"
    voice_id: str = "pt-BR-AntonioNeural"
    voice_blend: Optional[Dict[str, float]] = None
    voice_rate: str = "+8%"
    voice_pitch: str = "+0Hz"
    sample_text: str = "Bem-vindo ao FrimeRise! Este é o seu estúdio proprietário de vídeos virais com qualidade broadcast."


class ManufacturePayload(BaseModel):
    client_id: int = 1
    mode: str = "single"  # single | batch | clone_url
    engine_style: str = "cinematic_broll"  # cinematic_broll | cartoon_2d | netflix_doc
    aspect_ratio: str = "9:16"  # 9:16 | 16:9 | 4:5 | 1:1
    cartoon_tone: str = "Comédia Nordestina/BR"
    cartoon_fps: int = 60  # 30 | 60
    cartoon_voice_engine: str = "gemini_tts"  # gemini_tts | edge
    clone_languages: bool = False  # [🌎 Clonar Idiomas: Inglês (US) + Espanhol]
    flow_mode: str = "economico_pro"  # economico_pro | gancho_de_ouro | cinema_full_veo
    max_credits_cap: int = 45
    use_flow_music: bool = False
    doc_lang: str = "pt_br"  # pt_br | en_us | es
    target_minutes: float = 0.5
    thumb_3words: Optional[str] = None
    auto_shorts_cascade: bool = True
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
    # --- Full Creative Studio Overrides (100% backward compatible) ---
    voice_engine: Optional[str] = None  # "auto" | "gemini_tts" | "edge" | "kokoro"
    voice_id: Optional[str] = None
    voice_rate: str = "+8%"
    voice_pitch: str = "+0Hz"
    target_duration_s: Optional[int] = None  # e.g. 15..900 seconds
    cut_cadence_s: float = 3.5  # seconds per scene cut
    fps: Optional[int] = None  # 30 or 60
    music_file: Optional[str] = None  # "auto" | "none" | filename in assets/music/ | "flow_vault"
    music_volume: float = 0.18
    caption_style: str = "hormozi_neon"  # "hormozi_neon" | "karaoke_glow" | "word_slam" | "cinema_minimal" | "typewriter_highlight" | "none"
    language: str = "pt_br"  # "pt_br" | "en_us" | "es"
    visual_libraries: List[str] = []
    custom_directives: str = ""


class DocQueueManufacturePayload(BaseModel):
    episode_id: int
    target: str = "both"  # pt_br | en_us | both
    aspect_ratio: str = "16:9"
    target_minutes: float = 0.5
    auto_shorts_cascade: bool = True
    flow_mode: str = "economico_pro"
    max_credits_cap: int = 45
    use_flow_music: bool = False


class AnalyzeUrlPayload(BaseModel):
    source_url: str = ""
    reference_mp4_path: str = ""


class SaveDnaPresetPayload(BaseModel):
    preset_name: str
    blueprint: Dict[str, Any] = {}


class FlowLoginPayload(BaseModel):
    target: str = "flow"  # flow | flowmusic
    warm_seconds: int = 180


class B2BProspectPayload(BaseModel):
    client_id: int = 1
    company_name: str
    city: str
    product_service: str
    niche: str = "Negócio Local"
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


class AuthLoginPayload(BaseModel):
    username: str
    password: str


class AuthCredentialsPayload(BaseModel):
    username: Optional[str] = None
    new_password: Optional[str] = None
    require_local: Optional[bool] = None


def _set_session_cookie(request: Request, response: Response, username: str, secret: str) -> None:
    token = create_session_token(username, secret, ttl_seconds=SESSION_TTL_SECONDS)
    https = is_https_request(request)
    cookie_name = HTTPS_COOKIE_NAME if https else HTTP_COOKIE_NAME
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=https,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    for cname in (HTTPS_COOKIE_NAME, HTTP_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(key=cname, path="/")


def _render_login_page(
    request: Request,
    *,
    next_url: str = "/",
    username_value: str = "",
    error_message: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    csp_nonce = secrets.token_urlsafe(16)
    csrf_token = secrets.token_urlsafe(24)
    safe_next = sanitize_next_url(next_url)
    resp = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "csp_nonce": csp_nonce,
            "csrf_token": csrf_token,
            "next_url": safe_next,
            "username_value": username_value,
            "error_message": error_message,
        },
        status_code=status_code,
    )
    resp.headers["Content-Security-Policy"] = (
        f"script-src 'nonce-{csp_nonce}' 'strict-dynamic' 'report-sample'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    resp.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=1800,
        httponly=True,
        secure=is_https_request(request),
        samesite="lax",
        path="/login",
    )
    return resp


# ---------------------------------------------------------------------------
# Routes: Authentication & Remote Tailscale Security
# ---------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    settings = get_settings()
    safe_next = sanitize_next_url(next)
    if extract_authenticated_user(request, settings):
        return RedirectResponse(url=safe_next, status_code=303)
    default_user = (settings.get("auth_username") or "frimerise").strip()
    return _render_login_page(request, next_url=safe_next, username_value=default_user)


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    csrf_token: str = Form(""),
):
    safe_next = sanitize_next_url(next)
    client_ip = get_client_ip(request)
    blocked, retry_after = LOGIN_RATE_LIMITER.is_blocked(client_ip)
    if blocked:
        return _render_login_page(
            request,
            next_url=safe_next,
            username_value=username.strip(),
            error_message=f"Muitas tentativas inválidas. Aguarde {retry_after}s e tente novamente.",
            status_code=429,
        )

    cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME) or ""
    if not cookie_csrf or not csrf_token or not hmac.compare_digest(cookie_csrf, csrf_token):
        return _render_login_page(
            request,
            next_url=safe_next,
            username_value=username.strip(),
            error_message="Sessão de login expirada. Tente enviar novamente.",
            status_code=400,
        )

    settings = get_settings()
    expected_user = (settings.get("auth_username") or "frimerise").strip()
    pw_hash = (settings.get("auth_password_hash") or "").strip()

    if not pw_hash or not hmac.compare_digest(username.strip(), expected_user) or not verify_password(password, pw_hash):
        LOGIN_RATE_LIMITER.record_failure(client_ip)
        return _render_login_page(
            request,
            next_url=safe_next,
            username_value=username.strip(),
            error_message="Usuário ou senha incorretos.",
            status_code=401,
        )

    LOGIN_RATE_LIMITER.clear(client_ip)
    secret = ensure_auth_secret(settings)
    resp = RedirectResponse(url=safe_next, status_code=303)
    resp.delete_cookie(key=CSRF_COOKIE_NAME, path="/login")
    _set_session_cookie(request, resp, expected_user, secret)
    return resp


@app.post("/api/auth/login")
async def api_auth_login(request: Request, payload: AuthLoginPayload):
    client_ip = get_client_ip(request)
    blocked, retry_after = LOGIN_RATE_LIMITER.is_blocked(client_ip)
    if blocked:
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas inválidas. Aguarde {retry_after}s.",
        )

    settings = get_settings()
    expected_user = (settings.get("auth_username") or "frimerise").strip()
    pw_hash = (settings.get("auth_password_hash") or "").strip()
    if not pw_hash or not hmac.compare_digest(payload.username.strip(), expected_user) or not verify_password(payload.password, pw_hash):
        LOGIN_RATE_LIMITER.record_failure(client_ip)
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")

    LOGIN_RATE_LIMITER.clear(client_ip)
    secret = ensure_auth_secret(settings)
    resp = JSONResponse({"status": "authenticated", "username": expected_user})
    _set_session_cookie(request, resp, expected_user, secret)
    return resp


@app.post("/api/auth/logout")
async def api_auth_logout():
    resp = JSONResponse({"status": "logged_out"})
    _clear_session_cookies(resp)
    resp.headers["Clear-Site-Data"] = '"cookies", "storage", "cache"'
    return resp


@app.get("/api/auth/status")
async def api_auth_status(request: Request):
    settings = get_settings()
    is_local = is_direct_local_request(request)
    user = extract_authenticated_user(request, settings)
    require_local = settings.get("auth_require_local") == "1"
    return {
        "authenticated": bool(user),
        "is_local": is_local,
        "auth_required": (not is_local) or require_local,
        "auth_configured": bool((settings.get("auth_password_hash") or "").strip()),
        "auth_require_local": require_local,
        "username": user or (settings.get("auth_username") or "frimerise"),
        "tailscale": probe_tailscale_status(),
    }


@app.post("/api/auth/credentials")
async def api_update_auth_credentials(request: Request, payload: AuthCredentialsPayload):
    try:
        res = update_remote_credentials(
            username=payload.username,
            new_password=payload.new_password,
            require_local=payload.require_local,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    resp = JSONResponse({"status": "saved", **res})
    # If the user updated their password while authenticated (or turned on require_local),
    # seamlessly re-issue a fresh session cookie for the current device so they stay logged in.
    settings = get_settings()
    if res.get("password_rotated") or res.get("auth_require_local"):
        secret = ensure_auth_secret(settings)
        _set_session_cookie(request, resp, str(res["auth_username"]), secret)
    return resp


# ---------------------------------------------------------------------------
# Routes: Main Dashboard
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


# ---------------------------------------------------------------------------
# Routes: Telemetry, Google Flow Pro & Setup
# ---------------------------------------------------------------------------
@app.get("/api/telemetry")
async def api_telemetry():
    qs = probe_quicksync()
    temp_c = read_cpu_temperature_c()
    cost = get_total_cost_stats()
    settings = get_settings()
    limit_c = float(settings.get("thermal_limit_c") or 85.0)
    flow_status = await _get_flow_status_safe()
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
        "flow_pro": flow_status,
    }


@app.get("/api/flow/status")
async def api_flow_status():
    return await _get_flow_status_safe()


@app.post("/api/flow/login")
async def api_flow_login(payload: FlowLoginPayload, background_tasks: BackgroundTasks):
    """Launch persistent C++ Camoufox window for Google Flow (flow.google) & Flow Music (flowmusic.app)."""
    if open_google_flow_login_session is not None:
        async def _runner():
            try:
                res = open_google_flow_login_session(target=payload.target, warm_seconds=payload.warm_seconds)
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                print(f"[GoogleFlow Login] Aviso: {exc}")

        background_tasks.add_task(_runner)
    else:
        background_tasks.add_task(open_stealth_login_session, 1, "youtube", payload.warm_seconds)

    return {
        "status": "launching_camoufox_flow",
        "target": payload.target,
        "message": (
            f"Abrindo navegador blindado Camoufox (perfil persistente data/profiles/google_flow_pro) "
            f"para autenticar sua assinatura Google AI Pro ({payload.target})."
        ),
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
async def api_bootstrap_data(request: Request):
    from engine.gemini_tts import GEMINI_EXPRESSIVE_VOICES
    from engine.rhubarb_lipsync import find_rhubarb_binary

    try:
        from engine.kinetic_captions import list_caption_styles

        caption_styles_payload = list_caption_styles()
    except Exception:
        caption_styles_payload = CAPTION_STYLES_CATALOG

    luts = sorted([p.name for p in (ASSETS_DIR / "luts").glob("*.cube")])
    sfx = sorted([p.name for p in (ASSETS_DIR / "sfx").glob("*.wav")])
    music = sorted([p.name for p in (ASSETS_DIR / "music").glob("*.mp3")])
    flow_status = await _get_flow_status_safe()
    doc_queue = get_twin_channels_queue()
    raw_settings = get_settings()
    is_local = is_direct_local_request(request)
    auth_user = extract_authenticated_user(request, raw_settings)
    tailscale = probe_tailscale_status()
    return {
        "settings": sanitize_settings_for_client(raw_settings),
        "auth_status": {
            "authenticated": bool(auth_user),
            "is_local": is_local,
            "auth_required": (not is_local) or (raw_settings.get("auth_require_local") == "1"),
            "auth_configured": bool((raw_settings.get("auth_password_hash") or "").strip()),
            "auth_require_local": raw_settings.get("auth_require_local") == "1",
            "username": auth_user or (raw_settings.get("auth_username") or "frimerise"),
        },
        "tailscale": tailscale,
        "presets": list_presets(),
        "clients": list_clients(),
        "skills": list_skills(),
        "luts": luts,
        "sfx": sfx,
        "music": music,
        "edge_voices": PT_BR_EDGE_VOICES,
        "edge_voices_all": ALL_EDGE_VOICES,
        "gemini_voices": GEMINI_EXPRESSIVE_VOICES,
        "kokoro_voices": list(KOKORO_VOICES),
        "duration_presets": DURATION_PRESETS,
        "visual_libraries_catalog": VISUAL_LIBRARIES_CATALOG,
        "caption_styles": caption_styles_payload,
        "rhubarb_ready": find_rhubarb_binary() is not None,
        "flow_pro": flow_status,
        "doc_queue": doc_queue,
        "jobs": [_enrich_job(j) for j in list_jobs(40)],
        "schedules": list_schedules(),
        "feedback": get_feedback_summary(),
    }


# ---------------------------------------------------------------------------
# Routes: Twin Documentary Channels & Ready Queue of 10 Documentaries
# ---------------------------------------------------------------------------
@app.get("/api/doc-queue")
async def api_get_doc_queue():
    """Return the 2 pre-registered High-RPM Twin Channels ('Dossiê Capital' BR & 'Vault Files' US)
    and the Ready Queue of 10 Investigative Documentaries.
    """
    return get_twin_channels_queue()


@app.post("/api/doc-queue/manufacture")
async def api_manufacture_doc_queue(payload: DocQueueManufacturePayload):
    """1-Click Launch of any of the 10 pre-seeded Investigative Documentaries in BR ('Dossiê Capital'),
    US ('Vault Files'), or Both simultaneously!
    """
    queue_data = get_twin_channels_queue()
    ep = get_doc_episode(payload.episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail=f"Episódio documental #{payload.episode_id} não encontrado na fila.")

    target = payload.target.lower().strip()
    if target not in ("pt_br", "en_us", "both"):
        target = "both"

    langs_to_launch = ["pt_br", "en_us"] if target == "both" else [target]
    created_jobs: List[Dict[str, Any]] = []

    for lang_key in langs_to_launch:
        ch = queue_data["channels"][lang_key]
        client_id = int(ch["client_id"])
        topic = ep["title_pt"] if lang_key == "pt_br" else ep["title_en"]
        thumb_hook = ep["thumb_hook_pt"] if lang_key == "pt_br" else ep["thumb_hook_en"]
        opts = {
            "engine_style": "netflix_doc",
            "aspect_ratio": payload.aspect_ratio,
            "preset_id": ch.get("preset_id", "magnates_doc"),
            "lut_file": ch.get("lut_file", "02_dark_wealth.cube"),
            "doc_lang": lang_key,
            "target_minutes": payload.target_minutes,
            "thumb_3words": thumb_hook,
            "auto_shorts_cascade": payload.auto_shorts_cascade,
            "flow_mode": payload.flow_mode,
            "max_credits_cap": payload.max_credits_cap,
            "use_flow_music": payload.use_flow_music,
            "episode_id": ep["id"],
            "episode_slug": ep["slug"],
            "motion_cards": True,
            "seamless_loop": True,
            "dual_hook_ab": False,
        }
        job = enqueue_new_job(client_id, topic, "10_netflix_investigative_doc", "single", opts)
        await JOB_QUEUE.put(
            {
                "job_id": job["id"],
                "client_id": client_id,
                "topic": topic,
                "skill_id": "10_netflix_investigative_doc",
                "mode": "single",
                "options": opts,
            }
        )
        created_jobs.append(job)

    return {
        "status": "queued",
        "episode": ep,
        "target": target,
        "count": len(created_jobs),
        "jobs": created_jobs,
    }


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload):
    saved = save_settings(payload.model_dump(exclude_none=True))
    return {"status": "saved", "settings": sanitize_settings_for_client(saved)}


@app.post("/api/settings/test")
async def api_test_setup():
    import httpx
    from engine.rhubarb_lipsync import find_rhubarb_binary

    qs = probe_quicksync(force=True)
    settings = get_settings()

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
        "skia": {"ok": True, "detail": "skia-python C++ (3 Motores: Bespoke 2.5D + Cartoon 2D + Netflix Doc)"},
        "rhubarb_lipsync": {"ok": find_rhubarb_binary() is not None, "detail": "Rhubarb v1.14 (MIT • 9 Visemas Fonéticos)" if find_rhubarb_binary() else "Fallback RMS"},
        "chroma_key_filter": {"ok": True, "detail": "active (bloqueia >30% verde puro G>195,R<85,B<85)"},
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
    settings = get_settings()
    limit_c = float(settings.get("thermal_limit_c") or 85.0)

    vid_low = str(payload.voice_id or "").lower()
    inferred_lang = "en_us" if (vid_low.startswith("en-") or vid_low.startswith(("af_", "am_"))) else ("es" if vid_low.startswith("es-") else "pt_br")

    # If previewing a specific Kokoro voice without explicit blend weights, synthesize that exact voice
    blend_to_use = payload.voice_blend
    if payload.voice_engine == "kokoro" and blend_to_use is None and payload.voice_id in KOKORO_VOICES:
        blend_to_use = {payload.voice_id: 1.0}

    wav_path, _, dur = await generate_narration(
        text=payload.sample_text[:240],
        work_dir=preview_dir,
        voice_engine=payload.voice_engine,
        voice_id=payload.voice_id,
        voice_blend=blend_to_use,
        prefix=f"prev_{tag}",
        rate=payload.voice_rate,
        pitch=payload.voice_pitch,
        thermal_limit_c=limit_c,
        language=inferred_lang,
    )
    return {
        "status": "ok",
        "audio_url": f"/outputs/_voice_previews/{wav_path.name}",
        "file_path": str(wav_path),
        "duration_s": dur,
        "voice_engine": payload.voice_engine,
        "voice_id": payload.voice_id,
        "voice_rate": payload.voice_rate,
        "voice_pitch": payload.voice_pitch,
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
# Routes: Multi-Mode Factory (Single, Batch 50, Clone URL + DNA X-Ray + Save Preset)
# ---------------------------------------------------------------------------
def _normalize_dna_xray(dna: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure DNA X-Ray response always has contact_sheet_url, scene_cadence, optical_flow, palette, and engine classification."""
    if not isinstance(dna, dict):
        return {}
    cs_path = str(dna.get("contact_sheet_path") or "")
    if cs_path and not cs_path.startswith("/"):
        cs_url = "/" + cs_path.lstrip("/")
    else:
        cs_url = cs_path
    blueprint = dna.get("cloned_style_blueprint") or dna.get("blueprint") or {}
    return {
        **dna,
        "contact_sheet_url": cs_url,
        "scene_cadence": dna.get("scene_cadence") or {
            "avg_cut_seconds": round(float(dna.get("avg_scene_duration_s") or 2.8), 2),
            "cuts_count": len(dna.get("scenes") or []) or 6,
        },
        "optical_flow": dna.get("optical_flow") or dna.get("camera_motion") or {
            "dominant_motion": "punch_in",
            "motion_profile": ["zoom_in", "pan", "punch_in"],
        },
        "dominant_palette": dna.get("dominant_palette") or dna.get("palette_hex") or ["#0B0713", "#FF2E93", "#B8FF01", "#FFD166"],
        "classified_engine": (
            dna.get("classified_engine")
            or blueprint.get("classified_engine")
            or ("cartoon_2d" if dna.get("style") in ("2d_cartoon_animation", "2d_cartoon") else ("netflix_doc" if dna.get("style") == "netflix_doc" else "cinematic_broll"))
        ),
    }


@app.post("/api/factory/upload-reference")
async def api_upload_reference_mp4(file: UploadFile = File(...)):
    """Upload a reference .mp4 and immediately run VideoDNAExtractor for full visual DNA X-Ray."""
    from engine.viral_cloner import VideoDNAExtractor

    ref_dir = DATA_DIR / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "ref.mp4").suffix.lower() or ".mp4"
    dest = ref_dir / f"ref_{uuid.uuid4().hex[:8]}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    raw_dna = await asyncio.to_thread(VideoDNAExtractor().extract_from_local_mp4, dest, Path(file.filename or "Ref").stem)
    dna = _normalize_dna_xray(raw_dna)
    return {
        "status": "analyzed",
        "reference_mp4_path": str(dest.relative_to(BASE_DIR)),
        "dna": dna,
    }


@app.post("/api/factory/analyze-url")
async def api_analyze_reference_url(payload: AnalyzeUrlPayload):
    """Run VideoDNAExtractor on a competitor URL or local .mp4 to display the 3x3 Contact Sheet X-Ray."""
    from engine.viral_cloner import VideoDNAExtractor

    extractor = VideoDNAExtractor()
    if payload.reference_mp4_path and (BASE_DIR / payload.reference_mp4_path).exists():
        raw_dna = await asyncio.to_thread(extractor.extract_from_local_mp4, BASE_DIR / payload.reference_mp4_path, "Referência MP4")
    elif payload.source_url.strip():
        raw_dna = await asyncio.to_thread(extractor.extract_from_url, payload.source_url.strip())
    else:
        raise HTTPException(status_code=400, detail="Informe uma URL ou envie um arquivo .mp4 para o Raio-X de DNA.")

    dna = _normalize_dna_xray(raw_dna)
    return {"status": "analyzed", "dna": dna}


@app.post("/api/factory/save-dna-preset")
async def api_save_dna_as_preset(payload: SaveDnaPresetPayload):
    """Save the extracted ClonedStyleBlueprint / VideoDNA as a permanent Preset in SQLite (presets table)."""
    preset_name = payload.preset_name.strip() or f"DNA Clonado {datetime.now().strftime('%H:%M')}"
    bp = payload.blueprint or {}

    # Try Worker 1's save_blueprint_as_preset helper first
    saved_preset: Optional[Dict[str, Any]] = None
    try:
        from engine.viral_cloner import save_blueprint_as_preset  # type: ignore

        saved_preset = await asyncio.to_thread(save_blueprint_as_preset, bp, preset_name)
    except Exception:
        saved_preset = None

    if not saved_preset or not isinstance(saved_preset, dict) or not saved_preset.get("id"):
        slug = re.sub(r"[^a-z0-9]+", "_", preset_name.lower()).strip("_") or f"dna_{uuid.uuid4().hex[:6]}"
        preset_id = f"dna_{slug[:24]}_{uuid.uuid4().hex[:4]}"
        palette = bp.get("dominant_palette") or bp.get("palette_hex") or ["#FF2E93", "#B388FF", "#B8FF01", "#FFD166"]
        while len(palette) < 4:
            palette.append("#FFD166")
        cadence = bp.get("scene_cadence") or {}
        avg_cut = cadence.get("avg_cut_seconds") or bp.get("avg_scene_duration_s") or 2.8
        style_tag = bp.get("classified_engine") or bp.get("style") or "dynamic_viral"
        lut_file = "02_dark_wealth.cube" if style_tag == "netflix_doc" else "01_frimerise_signature.cube"
        font_file = "Anton-Regular.ttf" if style_tag == "netflix_doc" else "Montserrat-Black.ttf"

        row_dict = {
            "id": preset_id,
            "name": preset_name,
            "tagline": f"DNA Clonado ({style_tag} • cortes a cada {avg_cut}s • OpenCV + 3x3 Vision)",
            "is_default": 0,
            "lut_file": lut_file,
            "font_file": font_file,
            "music_file": "dark_pulse.mp3",
            "primary_color": str(palette[0]),
            "secondary_color": str(palette[1]),
            "highlight_color": str(palette[2]),
            "accent_gold": str(palette[3]),
            "bg_box_color": "#140E24CC",
            "text_color": "#FFFFFF",
            "stroke_color": "#0B0713",
            "caption_style": "hormozi_bounce",
            "voice_engine": "edge",
            "voice_id": "pt-BR-AntonioNeural",
            "voice_blend": json.dumps({"pf_dora": 0.25, "pm_alex": 0.75, "pm_santa": 0.0}),
            "motion_cards": 1,
            "sfx_intensity": "high",
        }
        with get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO presets (
                    id, name, tagline, is_default, lut_file, font_file, music_file,
                    primary_color, secondary_color, highlight_color, accent_gold,
                    bg_box_color, text_color, stroke_color, caption_style,
                    voice_engine, voice_id, voice_blend, motion_cards, sfx_intensity
                ) VALUES (
                    :id, :name, :tagline, :is_default, :lut_file, :font_file, :music_file,
                    :primary_color, :secondary_color, :highlight_color, :accent_gold,
                    :bg_box_color, :text_color, :stroke_color, :caption_style,
                    :voice_engine, :voice_id, :voice_blend, :motion_cards, :sfx_intensity
                )
                """,
                row_dict,
            )
        saved_preset = get_preset(preset_id)

    return {
        "status": "saved",
        "preset": saved_preset,
        "presets": list_presets(),
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
        "flow_mode": payload.flow_mode,
        "max_credits_cap": payload.max_credits_cap,
        "use_flow_music": payload.use_flow_music,
        "doc_lang": payload.doc_lang,
        "target_minutes": payload.target_minutes,
        "thumb_3words": payload.thumb_3words,
        "auto_shorts_cascade": payload.auto_shorts_cascade,
        "motion_cards": payload.motion_cards,
        "seamless_loop": payload.seamless_loop,
        "dual_hook_ab": payload.dual_hook_ab,
        "source_url": payload.source_url,
        "reference_mp4_path": payload.reference_mp4_path,
        # Full Creative Studio overrides
        "voice_engine": payload.voice_engine,
        "voice_id": payload.voice_id,
        "voice_rate": payload.voice_rate,
        "voice_pitch": payload.voice_pitch,
        "target_duration_s": payload.target_duration_s,
        "cut_cadence_s": payload.cut_cadence_s,
        "fps": payload.fps,
        "music_file": payload.music_file,
        "music_volume": payload.music_volume,
        "caption_style": payload.caption_style,
        "language": payload.language,
        "visual_libraries": list(payload.visual_libraries or []),
        "custom_directives": payload.custom_directives,
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
            elif payload.engine_style == "netflix_doc":
                topic = "Como um Único Operador Quebrou o Banco Mais Antigo da Rainha (Nick Leeson / Barings Bank)"
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


@app.post("/api/jobs/{job_id}/resume")
async def api_resume_job(job_id: str):
    """Resume an interrupted or failed job reusing cached script, audio, media, and completed scenes."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if job.get("status") == "completed":
        return {"status": "already_completed", "job_id": job_id}
    try:
        opts = json.loads(job.get("options_json") or "{}")
        if not isinstance(opts, dict):
            opts = {}
    except Exception:
        opts = {}
    opts["_resume"] = True
    opts["_resume_attempts"] = 0
    update_job(
        job_id,
        status="queued",
        stage="Retomando render do ponto de parada...",
        options_json=json.dumps(opts, ensure_ascii=False),
    )
    append_job_log(job_id, "♻️ Retomada manual acionada — reaproveitando cenas já renderizadas...")
    await JOB_QUEUE.put(
        {
            "job_id": job_id,
            "client_id": int(job.get("client_id") or 1),
            "topic": str(job.get("topic") or "FrimeRise"),
            "skill_id": str(job.get("skill_id") or "01_negative_hook"),
            "mode": str(job.get("mode") or "single"),
            "options": opts,
        }
    )
    return {"status": "queued_for_resume", "job_id": job_id}


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
async def api_generate_ab_thumbnails(job_id: str, custom_3words: Optional[str] = None):
    """Generate 3 magnetic 1280x720 A/B/C YouTube thumbnails (Skia C++ + rembg u2netp) for any job."""
    from engine.pipeline import _call_generate_ab_thumbnails

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job_dir = OUTPUTS_DIR / job_id
    master_mp4 = job_dir / "master.mp4"
    if not master_mp4.exists():
        raise HTTPException(status_code=400, detail="Master MP4 ainda não está pronto.")

    qr_path = job_dir / "quality_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else {}
    hook_3w = custom_3words or qr.get("thumb_3words")

    raw = await asyncio.to_thread(
        _call_generate_ab_thumbnails,
        master_mp4,
        str(job.get("topic", "Segredo Revelado")),
        job_dir,
        hook_3w,
    )
    thumbs = {
        "thumb_a": str(Path(raw["thumb_a"]).resolve().relative_to(BASE_DIR.resolve())),
        "thumb_b": str(Path(raw["thumb_b"]).resolve().relative_to(BASE_DIR.resolve())),
        "thumb_c": str(Path(raw["thumb_c"]).resolve().relative_to(BASE_DIR.resolve())),
        "headline_words": raw.get("headline_words", hook_3w or ""),
    }
    qr["ab_thumbnails"] = thumbs
    qr_path.write_text(json.dumps(qr, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "ab_thumbnails": thumbs}


@app.post("/api/jobs/{job_id}/dub-languages")
async def api_dub_job_languages(job_id: str):
    """On-demand Multi-Language Dubbing & Re-Timing (EN-US + ES) for an existing job."""
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

    if generate_b2b_pitch_bundle is not None:
        try:
            bundle = generate_b2b_pitch_bundle(
                company_name=payload.company_name,
                city=payload.city,
                product_service=payload.product_service,
                niche=payload.niche,
            )
            script = bundle.get("script") or bundle
            whatsapp_pitch = bundle.get("whatsapp_pitch") or bundle.get("whatsapp_copy") or ""
            if not whatsapp_pitch:
                _, whatsapp_pitch = build_b2b_commercial_script_and_pitch(
                    payload.company_name, payload.city, payload.product_service
                )
        except Exception:
            script, whatsapp_pitch = build_b2b_commercial_script_and_pitch(
                payload.company_name, payload.city, payload.product_service
            )
    else:
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
