"""FrimeRise SQLite Database Layer (data/frimerise.db).
100% standard-library sqlite3 (permissive PSF license).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "frimerise.db"


DEFAULT_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "frimerise_signature",
        "name": "FrimeRise Signature",
        "tagline": "Estética Cyber-Luxury oficial: Verde Lima, Dourado, Rosa Frime e Lilás",
        "is_default": 1,
        "lut_file": "01_frimerise_signature.cube",
        "font_file": "Montserrat-Black.ttf",
        "music_file": "dark_pulse.mp3",
        "primary_color": "#FF2E93",
        "secondary_color": "#B388FF",
        "highlight_color": "#B8FF01",
        "accent_gold": "#FFD166",
        "bg_box_color": "#140E24CC",
        "text_color": "#FFFFFF",
        "stroke_color": "#0B0713",
        "caption_style": "spring_pill_gradient",
        "voice_engine": "edge",
        "voice_id": "pt-BR-AntonioNeural",
        "voice_blend": json.dumps({"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}),
        "motion_cards": 1,
        "sfx_intensity": "high",
    },
    {
        "id": "hormozi_rebel",
        "name": "Hormozi Rebel",
        "tagline": "Cortes rápidos, palavras-chave em Verde Lima e Amarelo explosivo + emojis",
        "is_default": 0,
        "lut_file": "02_dark_wealth.cube",
        "font_file": "Anton-Regular.ttf",
        "music_file": "dark_pulse.mp3",
        "primary_color": "#B8FF01",
        "secondary_color": "#FFD166",
        "highlight_color": "#B8FF01",
        "accent_gold": "#FFD166",
        "bg_box_color": "#000000B0",
        "text_color": "#FFFFFF",
        "stroke_color": "#000000",
        "caption_style": "hormozi_bounce",
        "voice_engine": "edge",
        "voice_id": "pt-BR-AntonioNeural",
        "voice_blend": json.dumps({"pf_dora": 0.0, "pm_alex": 0.8, "pm_santa": 0.2}),
        "motion_cards": 1,
        "sfx_intensity": "high",
    },
    {
        "id": "magnates_doc",
        "name": "Magnates Doc",
        "tagline": "Mini-documentário cinematográfico com gráficos de barras e LUT Teal & Orange",
        "is_default": 0,
        "lut_file": "03_teal_orange_cinema.cube",
        "font_file": "BebasNeue-Regular.ttf",
        "music_file": "epic_doc.mp3",
        "primary_color": "#FFD166",
        "secondary_color": "#38BDF8",
        "highlight_color": "#FFD166",
        "accent_gold": "#FFD166",
        "bg_box_color": "#090D16D9",
        "text_color": "#F8FAFC",
        "stroke_color": "#020617",
        "caption_style": "cinematic_serif_bar",
        "voice_engine": "edge",
        "voice_id": "pt-BR-FabioNeural",
        "voice_blend": json.dumps({"pf_dora": 0.0, "pm_alex": 0.4, "pm_santa": 0.6}),
        "motion_cards": 1,
        "sfx_intensity": "medium",
    },
    {
        "id": "mrbeast_hyper",
        "name": "MrBeast Hyper",
        "tagline": "Energia máxima, contadores numéricos gigantes e transições rápidas",
        "is_default": 0,
        "lut_file": "04_crisp_commercial.cube",
        "font_file": "Montserrat-Black.ttf",
        "music_file": "corporate_focus.mp3",
        "primary_color": "#FF2E93",
        "secondary_color": "#B8FF01",
        "highlight_color": "#FFD166",
        "accent_gold": "#FFD166",
        "bg_box_color": "#FF2E93DD",
        "text_color": "#FFFFFF",
        "stroke_color": "#0B0713",
        "caption_style": "hyper_pop",
        "voice_engine": "edge",
        "voice_id": "pt-BR-JulioNeural",
        "voice_blend": json.dumps({"pf_dora": 0.2, "pm_alex": 0.8, "pm_santa": 0.0}),
        "motion_cards": 1,
        "sfx_intensity": "high",
    },
    {
        "id": "luxury_minimalist",
        "name": "Luxury Minimalist",
        "tagline": "Sofisticação clean com dourado metálico, ritmo cadenciado e tipografia elegante",
        "is_default": 0,
        "lut_file": "02_dark_wealth.cube",
        "font_file": "PlusJakartaSans-ExtraBold.ttf",
        "music_file": "lo_fi_study.mp3",
        "primary_color": "#FFD166",
        "secondary_color": "#B388FF",
        "highlight_color": "#FFD166",
        "accent_gold": "#FFD166",
        "bg_box_color": "#0B0713B8",
        "text_color": "#F5F3FF",
        "stroke_color": "#0B0713",
        "caption_style": "minimal_gold",
        "voice_engine": "edge",
        "voice_id": "pt-BR-FranciscaNeural",
        "voice_blend": json.dumps({"pf_dora": 0.85, "pm_alex": 0.15, "pm_santa": 0.0}),
        "motion_cards": 1,
        "sfx_intensity": "low",
    },
    {
        "id": "local_business_ugc",
        "name": "Local Business Ads (UGC)",
        "tagline": "Anúncios comerciais de alta conversão para clínicas, lojas, imóveis e delivery",
        "is_default": 0,
        "lut_file": "04_crisp_commercial.cube",
        "font_file": "PlusJakartaSans-ExtraBold.ttf",
        "music_file": "corporate_focus.mp3",
        "primary_color": "#FF2E93",
        "secondary_color": "#B8FF01",
        "highlight_color": "#B8FF01",
        "accent_gold": "#FFD166",
        "bg_box_color": "#140E24E6",
        "text_color": "#FFFFFF",
        "stroke_color": "#0B0713",
        "caption_style": "commercial_highlight",
        "voice_engine": "edge",
        "voice_id": "pt-BR-ThalitaNeural",
        "voice_blend": json.dumps({"pf_dora": 1.0, "pm_alex": 0.0, "pm_santa": 0.0}),
        "motion_cards": 1,
        "sfx_intensity": "medium",
    },
    {
        "id": "dark_mystery",
        "name": "Dark Mystery",
        "tagline": "Suspense hipnótico, psicologia sombria e curiosidades com brilho Lilás/Neon",
        "is_default": 0,
        "lut_file": "05_cyber_neon.cube",
        "font_file": "Montserrat-ExtraBold.ttf",
        "music_file": "dark_pulse.mp3",
        "primary_color": "#B388FF",
        "secondary_color": "#FF2E93",
        "highlight_color": "#B388FF",
        "accent_gold": "#FFD166",
        "bg_box_color": "#0B0713E6",
        "text_color": "#EDE9FE",
        "stroke_color": "#05020A",
        "caption_style": "neon_glow",
        "voice_engine": "edge",
        "voice_id": "pt-BR-NicolauNeural",
        "voice_blend": json.dumps({"pf_dora": 0.0, "pm_alex": 0.3, "pm_santa": 0.7}),
        "motion_cards": 1,
        "sfx_intensity": "high",
    },
]


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tagline TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                lut_file TEXT NOT NULL,
                font_file TEXT NOT NULL,
                music_file TEXT NOT NULL,
                primary_color TEXT NOT NULL,
                secondary_color TEXT NOT NULL,
                highlight_color TEXT NOT NULL,
                accent_gold TEXT NOT NULL,
                bg_box_color TEXT NOT NULL,
                text_color TEXT NOT NULL,
                stroke_color TEXT NOT NULL,
                caption_style TEXT NOT NULL,
                voice_engine TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                voice_blend TEXT NOT NULL,
                motion_cards INTEGER DEFAULT 1,
                sfx_intensity TEXT DEFAULT 'high'
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                niche TEXT NOT NULL DEFAULT 'Negócios & IA',
                preset_id TEXT NOT NULL DEFAULT 'frimerise_signature',
                lut_file TEXT NOT NULL DEFAULT '01_frimerise_signature.cube',
                voice_engine TEXT NOT NULL DEFAULT 'edge',
                voice_id TEXT NOT NULL DEFAULT 'pt-BR-AntonioNeural',
                voice_blend TEXT NOT NULL DEFAULT '{"pf_dora":0.35,"pm_alex":0.65,"pm_santa":0.0}',
                logo_path TEXT DEFAULT '',
                proxy_url TEXT DEFAULT '',
                watermark_text TEXT NOT NULL DEFAULT 'PRÉVIA • FRIMERISE',
                tiktok_connected INTEGER DEFAULT 0,
                youtube_connected INTEGER DEFAULT 0,
                facebook_connected INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                client_id INTEGER,
                mode TEXT NOT NULL DEFAULT 'single',
                topic TEXT NOT NULL,
                skill_id TEXT NOT NULL DEFAULT '01_negative_hook',
                status TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT 'Na fila',
                log TEXT NOT NULL DEFAULT '',
                script_json TEXT DEFAULT '{}',
                options_json TEXT DEFAULT '{}',
                master_path TEXT DEFAULT '',
                hook_a_path TEXT DEFAULT '',
                hook_b_path TEXT DEFAULT '',
                tiktok_path TEXT DEFAULT '',
                reels_path TEXT DEFAULT '',
                shorts_path TEXT DEFAULT '',
                preview_path TEXT DEFAULT '',
                capcut_zip_path TEXT DEFAULT '',
                otio_path TEXT DEFAULT '',
                cover_path TEXT DEFAULT '',
                duration_s REAL DEFAULT 0.0,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                views_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS media_history (
                url_hash TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                local_path TEXT DEFAULT '',
                used_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                client_id INTEGER,
                platform TEXT NOT NULL,
                scheduled_brt TEXT NOT NULL,
                scheduled_target_tz TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'scheduled',
                result_log TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analytics_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                hook_variant TEXT NOT NULL DEFAULT 'A',
                platform TEXT NOT NULL DEFAULT 'tiktok',
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                retention_pct REAL NOT NULL DEFAULT 0.0,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );
            """
        )

        # Seed default presets
        for p in DEFAULT_PRESETS:
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
                p,
            )

        # Seed default showcase client if none exists
        cur = conn.execute("SELECT COUNT(*) AS c FROM clients")
        if cur.fetchone()["c"] == 0:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO clients (
                    name, niche, preset_id, lut_file, voice_engine, voice_id,
                    voice_blend, logo_path, watermark_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "FrimeRise Official Studio",
                    "IA, Negócios & Crescimento Viral",
                    "frimerise_signature",
                    "01_frimerise_signature.cube",
                    "edge",
                    "pt-BR-AntonioNeural",
                    json.dumps({"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0}),
                    "assets/brand/frimerise_logo.png",
                    "PRÉVIA • FRIMERISE",
                    now,
                ),
            )

        # Default settings
        defaults = {
            "default_llm": "gemini-3.5-flash-lite",
            "ollama_url": "http://localhost:11434",
            "thermal_limit_c": "85",
            "pexels_api_key": "",
            "pixabay_api_key": "",
            "deepseek_api_key": "",
            "gemini_api_key": "",
            "openai_api_key": "",
        }
        now = datetime.now().isoformat(timespec="seconds")
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (k, v, now),
            )


def get_settings() -> Dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def save_settings(updates: Dict[str, Any]) -> Dict[str, str]:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        for k, v in updates.items():
            if v is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (str(k), str(v), now),
            )
    return get_settings()


def list_presets() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM presets ORDER BY is_default DESC, name ASC").fetchall()
        return [dict(r) for r in rows]


def get_preset(preset_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        if row:
            return dict(row)
        row = conn.execute("SELECT * FROM presets WHERE is_default = 1 LIMIT 1").fetchone()
        return dict(row) if row else DEFAULT_PRESETS[0]


def list_clients() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def get_client(client_id: Optional[int]) -> Dict[str, Any]:
    with get_conn() as conn:
        if client_id:
            row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
            if row:
                return dict(row)
        row = conn.execute("SELECT * FROM clients ORDER BY id ASC LIMIT 1").fetchone()
        return dict(row)


def upsert_client(data: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    blend = data.get("voice_blend", {"pf_dora": 0.35, "pm_alex": 0.65, "pm_santa": 0.0})
    if not isinstance(blend, str):
        blend = json.dumps(blend)
    with get_conn() as conn:
        cid = data.get("id")
        if cid:
            conn.execute(
                """
                UPDATE clients SET
                    name=?, niche=?, preset_id=?, lut_file=?, voice_engine=?, voice_id=?,
                    voice_blend=?, logo_path=?, proxy_url=?, watermark_text=?
                WHERE id=?
                """,
                (
                    data.get("name", "Cliente FrimeRise"),
                    data.get("niche", "Geral"),
                    data.get("preset_id", "frimerise_signature"),
                    data.get("lut_file", "01_frimerise_signature.cube"),
                    data.get("voice_engine", "edge"),
                    data.get("voice_id", "pt-BR-AntonioNeural"),
                    blend,
                    data.get("logo_path", ""),
                    data.get("proxy_url", ""),
                    data.get("watermark_text", "PRÉVIA • FRIMERISE"),
                    int(cid),
                ),
            )
            return get_client(int(cid))
        cur = conn.execute(
            """
            INSERT INTO clients (
                name, niche, preset_id, lut_file, voice_engine, voice_id,
                voice_blend, logo_path, proxy_url, watermark_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("name", "Novo Cliente"),
                data.get("niche", "Negócios"),
                data.get("preset_id", "frimerise_signature"),
                data.get("lut_file", "01_frimerise_signature.cube"),
                data.get("voice_engine", "edge"),
                data.get("voice_id", "pt-BR-AntonioNeural"),
                blend,
                data.get("logo_path", "assets/brand/frimerise_logo.png"),
                data.get("proxy_url", ""),
                data.get("watermark_text", "PRÉVIA • FRIMERISE"),
                now,
            ),
        )
        return get_client(cur.lastrowid)


def set_client_connection(client_id: int, platform: str, connected: bool) -> None:
    col = {
        "tiktok": "tiktok_connected",
        "youtube": "youtube_connected",
        "facebook": "facebook_connected",
    }.get(platform)
    if not col:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE clients SET {col} = ? WHERE id = ?", (1 if connected else 0, client_id))


def create_job(
    job_id: str,
    client_id: int,
    mode: str,
    topic: str,
    skill_id: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, client_id, mode, topic, skill_id, status, progress, stage, options_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', 0, 'Na fila', ?, ?)
            """,
            (job_id, client_id, mode, topic, skill_id, json.dumps(options, ensure_ascii=False), now),
        )
    return get_job(job_id)


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", vals)


def append_job_log(job_id: str, message: str, progress: Optional[int] = None, stage: Optional[str] = None) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {message}\n"
    with get_conn() as conn:
        row = conn.execute("SELECT log FROM jobs WHERE id = ?", (job_id,)).fetchone()
        existing = row["log"] if row else ""
        updates = {"log": existing + line}
        if progress is not None:
            updates["progress"] = progress
        if stage is not None:
            updates["stage"] = stage
        cols = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", list(updates.values()) + [job_id])


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT j.*, c.name AS client_name FROM jobs j LEFT JOIN clients c ON j.client_id = c.id ORDER BY j.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_incomplete_jobs() -> List[Dict[str, Any]]:
    """Return jobs left in 'running' or 'queued' state (e.g. after a server restart)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('running', 'queued') ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def record_token_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    cost_usd: float,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens, cached_tokens, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (provider, model, prompt_tokens, completion_tokens, cached_tokens, cost_usd, now),
        )


def get_total_cost_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total_usd, COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS total_tokens, COUNT(*) AS calls FROM token_usage"
        ).fetchone()
        jobs_done = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE status='completed'").fetchone()["c"]
        return {
            "total_usd": round(float(row["total_usd"]), 5),
            "total_tokens": int(row["total_tokens"]),
            "calls": int(row["calls"]),
            "jobs_done": int(jobs_done),
        }


def is_media_used(url_hash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM media_history WHERE url_hash = ?", (url_hash,)).fetchone()
        return row is not None


def mark_media_used(url_hash: str, source: str, query: str, local_path: str = "") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO media_history (url_hash, source, query, local_path, used_at) VALUES (?, ?, ?, ?, ?)",
            (url_hash, source, query, local_path, now),
        )


def create_schedule(
    job_id: str,
    client_id: int,
    platform: str,
    scheduled_brt: str,
    scheduled_target_tz: str,
    caption: str,
) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO schedules (job_id, client_id, platform, scheduled_brt, scheduled_target_tz, caption, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?)
            """,
            (job_id, client_id, platform, scheduled_brt, scheduled_target_tz, caption, now),
        )
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_schedules() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.*, j.topic, c.name AS client_name
            FROM schedules s
            LEFT JOIN jobs j ON s.job_id = j.id
            LEFT JOIN clients c ON s.client_id = c.id
            ORDER BY s.scheduled_brt ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_schedule(schedule_id: int, status: str, result_log: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE schedules SET status = ?, result_log = ? WHERE id = ?",
            (status, result_log, schedule_id),
        )


def record_feedback(
    job_id: str,
    skill_id: str,
    hook_variant: str,
    platform: str,
    views: int,
    likes: int,
    retention_pct: float,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO analytics_feedback (job_id, skill_id, hook_variant, platform, views, likes, retention_pct, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, skill_id, hook_variant, platform, views, likes, retention_pct, now),
        )
        conn.execute("UPDATE jobs SET views_count = views_count + ? WHERE id = ?", (views, job_id))


def get_top_performing_skills() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT skill_id,
                   COUNT(*) AS samples,
                   AVG(views) AS avg_views,
                   AVG(retention_pct) AS avg_retention,
                   SUM(views) AS total_views
            FROM analytics_feedback
            GROUP BY skill_id
            ORDER BY avg_views DESC, avg_retention DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
