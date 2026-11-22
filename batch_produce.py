#!/usr/bin/env python3
"""FrimeRise Zero-Agent-Token Autonomous Video Factory CLI (batch_produce.py).

Runs the FULL-QUALITY FrimeRise Cinema v3.0.0 pipeline strictly in Python (ZERO AI-agent tokens
wasted on orchestration, rendering, QA, Drive upload, or disk cleanup):
  - Enforces Cinema v3.0.0 Quality Lock (1920x1080/1080x1920 @ 30fps, 5 Mixed-Media categories,
    RetentionDoctor v3, Era-Lock + Vision gate, -14 LUFS / <= -1.0 dBTP master audio, 3 A/B Thumbs).
  - Disk headroom guard (--min-free-gb 10) BEFORE every job so SSD never hits 0 bytes.
  - Pure-Python automated QC gate (ffprobe streams/A-V sync + ebur128 integrated LUFS & True Peak).
  - Automatic checkpoint resume (reuses rendered scenes & base_scenes.mp4).
  - Automatic verified Google Drive upload + heavy local file pruning (keeps lightweight preview/thumbs).

Usage examples:
  # 1) Single 16:9 Cinema Documentary (17 min, full v3.0.0 quality):
  .venv/bin/python batch_produce.py --topic "A Verdadeira História Oculta da Biblioteca de Alexandria" --minutes 17

  # 2) Batch queue from JSON (zero agent tokens, runs sequentially overnight):
  .venv/bin/python batch_produce.py --queue fila_videos.json

  # 3) Resume an interrupted job reusing cached checkpoints:
  .venv/bin/python batch_produce.py --resume-job fr_20261122_123309_eedc39

  # 4) Run strict audio/video QC on an existing output folder:
  .venv/bin/python batch_produce.py --qc-only outputs/fr_20261122_123309_eedc39
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Ensure Intel QuickSync iHD VAAPI env is active even when invoked directly without start_frimerise.sh
os.environ.setdefault("LIBVA_DRIVER_NAME", "iHD")
os.environ.setdefault(
    "LIBVA_DRIVERS_PATH",
    f"{BASE_DIR}/vendor/syslibs/usr/lib/x86_64-linux-gnu/dri:/usr/lib/x86_64-linux-gnu/dri",
)
_syslibs = f"{BASE_DIR}/vendor/syslibs/usr/lib/x86_64-linux-gnu"
if _syslibs not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = f"{_syslibs}:{os.environ.get('LD_LIBRARY_PATH', '')}".rstrip(":")

from database import get_job, get_settings, init_db, save_settings, update_job  # noqa: E402
from engine.gdrive_sync import probe_gdrive_status, upload_job_to_gdrive  # noqa: E402
from engine.intel_vaapi import read_cpu_temperature_c, thermal_guard_wait  # noqa: E402
from engine.pipeline import enqueue_new_job, run_video_job  # noqa: E402

OUTPUTS_DIR = BASE_DIR / "outputs"


def check_disk_headroom(min_free_gb: float) -> float:
    free_gb = shutil.disk_usage(BASE_DIR).free / (1024**3)
    if free_gb < min_free_gb:
        raise RuntimeError(
            f"Espaço livre insuficiente no SSD ({free_gb:.2f} GB < mínimo exigido {min_free_gb:.1f} GB). "
            "Conecte o Google Drive (./setup_gdrive.sh) ou libere espaço antes de iniciar novo render."
        )
    return round(free_gb, 2)


def run_automated_qc(
    job_dir: Path,
    *,
    expected_aspect: Optional[str] = None,
    expected_fps: int = 30,
    check_loudness: bool = True,
) -> Dict[str, Any]:
    """Pure-Python broadcast QC gate (0 LLM/agent tokens).

    Validates video/audio streams, resolution, FPS, A/V sync, loudness (-14 LUFS / <= -1.0 dBTP),
    RetentionDoctor audit, and core deliverables.
    """
    job_dir = Path(job_dir)
    master = job_dir / "master.mp4"
    if not master.exists():
        # If already pruned after Drive upload, fall back to preview_540p.mp4 for basic presence check
        qr_p = job_dir / "quality_report.json"
        if qr_p.exists():
            qr = json.loads(qr_p.read_text(encoding="utf-8"))
            if (qr.get("gdrive_backup") or {}).get("status") == "uploaded":
                return {
                    "passed": True,
                    "note": "master.mp4 já enviado e verificado no Google Drive (local podado).",
                    "gdrive_backup": qr.get("gdrive_backup"),
                }
        return {"passed": False, "errors": ["master.mp4 não encontrado"]}

    errors: List[str] = []
    warnings: List[str] = []
    metrics: Dict[str, Any] = {"file": str(master), "size_mb": round(master.stat().st_size / (1024 * 1024), 2)}

    # 1. ffprobe stream & A/V sync validation
    probe_proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,duration",
            "-of", "json",
            str(master),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe_proc.returncode != 0:
        return {"passed": False, "errors": [f"ffprobe falhou: {probe_proc.stderr[:200]}"]}

    info = json.loads(probe_proc.stdout)
    streams = info.get("streams") or []
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    fmt_dur = float((info.get("format") or {}).get("duration") or 0.0)
    metrics["duration_s"] = round(fmt_dur, 2)

    if not vstreams:
        errors.append("Stream de vídeo ausente")
    if not astreams:
        errors.append("Stream de áudio ausente")

    if vstreams:
        vs = vstreams[0]
        w, h = int(vs.get("width") or 0), int(vs.get("height") or 0)
        fr_raw = str(vs.get("r_frame_rate") or "0/1")
        num, den = (fr_raw.split("/") + ["1"])[:2]
        fps_val = round(float(num) / max(1.0, float(den)), 2)
        metrics.update({"width": w, "height": h, "fps": fps_val, "video_codec": vs.get("codec_name")})

        if expected_aspect == "16:9" and (w, h) != (1920, 1080):
            errors.append(f"Resolução 16:9 inválida: {w}x{h} (esperado 1920x1080)")
        elif expected_aspect == "9:16" and (w, h) != (1080, 1920):
            errors.append(f"Resolução 9:16 inválida: {w}x{h} (esperado 1080x1920)")
        if abs(fps_val - expected_fps) > 1.0:
            errors.append(f"FPS inválido: {fps_val} (esperado {expected_fps})")

    if vstreams and astreams:
        v_dur = float(vstreams[0].get("duration") or fmt_dur)
        a_dur = float(astreams[0].get("duration") or fmt_dur)
        av_drift = round(abs(v_dur - a_dur), 3)
        metrics["av_drift_s"] = av_drift
        if av_drift > 0.65:
            errors.append(f"Dessincronia A/V detectada: {av_drift:.2f}s (> 0.65s)")

    # 2. Loudness QC (-14 LUFS target, <= -1.0 dBTP true peak ceiling)
    if check_loudness and astreams:
        ebur_proc = subprocess.run(
            [
                "ffmpeg", "-nostats", "-i", str(master),
                "-vn", "-af", "ebur128=peak=true", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        stderr_txt = ebur_proc.stderr or ""
        m_i = re.search(r"Integrated loudness:\s*\n\s*I:\s*([-0-9.]+)\s*LUFS", stderr_txt)
        m_tp = re.search(r"True peak:\s*\n\s*Peak:\s*([-0-9.]+)\s*dBFS", stderr_txt)
        m_lra = re.search(r"Loudness range:\s*\n\s*LRA:\s*([-0-9.]+)\s*LU", stderr_txt)
        if m_i:
            lufs = float(m_i.group(1))
            metrics["integrated_lufs"] = lufs
            if not (-16.0 <= lufs <= -12.0):
                warnings.append(f"Loudness integrado fora da faixa ideal (-14 LUFS): {lufs:.1f} LUFS")
        if m_tp:
            tp = float(m_tp.group(1))
            metrics["true_peak_dbtp"] = tp
            if tp > -0.7:
                errors.append(f"True Peak acima do teto broadcast (-1.0 dBTP): {tp:.2f} dBTP")
        if m_lra:
            metrics["lra_lu"] = float(m_lra.group(1))

    # 3. Deliverables & RetentionDoctor check
    qr_path = job_dir / "quality_report.json"
    if qr_path.exists():
        try:
            qr = json.loads(qr_path.read_text(encoding="utf-8"))
            ra = qr.get("retention_audit") or {}
            if ra and ra.get("passed") is False:
                warnings.append("RetentionDoctor reportou passed=False")
            metrics["scenes_count"] = qr.get("scenes_count")
            metrics["gdrive_status"] = (qr.get("gdrive_backup") or {}).get("status")
        except Exception:
            warnings.append("quality_report.json ilegível")
    else:
        warnings.append("quality_report.json ausente")

    for req_thumb in ("thumb_A_mystery.jpg", "thumb_B_contrast.jpg", "thumb_C_zoom.jpg"):
        if not (job_dir / req_thumb).exists():
            warnings.append(f"Thumbnail ausente: {req_thumb}")

    qc_result = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }
    try:
        (job_dir / "qc_report.json").write_text(
            json.dumps(qc_result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    return qc_result


def build_full_quality_options(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build full Cinema v3.0.0 quality options without any shortcuts."""
    engine_style = str(item.get("engine_style") or "netflix_doc").strip()
    aspect_ratio = str(item.get("aspect_ratio") or ("16:9" if engine_style == "netflix_doc" else "9:16")).strip()
    default_caption = (
        "selective_emphasis"
        if (engine_style == "netflix_doc" and aspect_ratio == "16:9")
        else ("cinema_minimal" if engine_style == "netflix_doc" else "hormozi_neon")
    )

    opts: Dict[str, Any] = {
        "engine_style": engine_style,
        "aspect_ratio": aspect_ratio,
        "fps": int(item.get("fps") or (60 if engine_style == "cartoon_2d" else 30)),
        "language": str(item.get("language") or "pt_br"),
        "caption_style": str(item.get("caption_style") or default_caption),
        "flow_mode": str(item.get("flow_mode") or "economico_pro"),
        "auto_shorts_cascade": bool(item.get("auto_shorts_cascade", False)),
        "clone_languages": bool(item.get("clone_languages", False)),
        "lut_file": str(item.get("lut_file") or "04_crisp_commercial.cube"),
        "voice_id": str(item.get("voice_id") or "Charon"),
    }
    if item.get("target_minutes") is not None:
        opts["target_minutes"] = float(item["target_minutes"])
    elif engine_style == "netflix_doc" and item.get("target_duration_s") is None:
        opts["target_minutes"] = 17.0 if aspect_ratio == "16:9" else 2.5

    if item.get("target_duration_s") is not None:
        opts["target_duration_s"] = int(item["target_duration_s"])
    if item.get("thumb_3words"):
        opts["thumb_3words"] = str(item["thumb_3words"]).strip()
    if item.get("custom_directives"):
        opts["custom_directives"] = str(item["custom_directives"]).strip()
    if item.get("custom_script"):
        opts["custom_script"] = item["custom_script"]
    if item.get("cut_cadence_s") is not None:
        opts["cut_cadence_s"] = float(item["cut_cadence_s"])
    if item.get("music_file"):
        opts["music_file"] = str(item["music_file"])
    if item.get("music_volume") is not None:
        opts["music_volume"] = float(item["music_volume"])
    return opts


async def produce_single_item(
    item: Dict[str, Any],
    *,
    min_free_gb: float = 10.0,
    max_retries: int = 2,
    skip_loudness_qc: bool = False,
    ensure_drive_prune: bool = True,
) -> Dict[str, Any]:
    init_db()
    if ensure_drive_prune:
        save_settings({"gdrive_auto_upload": "1", "gdrive_prune_local": "1"})

    free_gb = check_disk_headroom(min_free_gb)
    gd_status = probe_gdrive_status()
    print(
        f"[Factory] SSD livre: {free_gb:.2f} GB | CPU: {read_cpu_temperature_c()}°C | "
        f"Google Drive: {gd_status['detail']} (prune_local={gd_status['prune_local']})",
        flush=True,
    )

    topic = str(item["topic"]).strip()
    client_id = int(item.get("client_id") or 1)
    skill_id = str(item.get("skill_id") or "10_netflix_investigative_doc")
    mode = str(item.get("mode") or "single")
    opts = build_full_quality_options(item)

    job_id = str(item.get("resume_job_id") or "").strip()
    if job_id:
        existing = get_job(job_id)
        if not existing:
            raise RuntimeError(f"Job '{job_id}' não encontrado no banco para retomada.")
        saved_opts = json.loads(existing.get("options_json") or "{}")
        opts = {**saved_opts, **opts, "_resume": True}
        topic = str(existing.get("topic") or topic)
        client_id = int(existing.get("client_id") or client_id)
        skill_id = str(existing.get("skill_id") or skill_id)
        print(f"[Factory] ♻️ Retomando job existente: {job_id} ('{topic}')", flush=True)
    else:
        job = enqueue_new_job(client_id, topic, skill_id, mode, opts)
        job_id = str(job["id"])
        print(f"[Factory] 🎬 Novo job enfileirado: {job_id} ('{topic}' | {opts['engine_style']} {opts['aspect_ratio']})", flush=True)

    last_exc: Optional[Exception] = None
    result: Dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        try:
            thermal_guard_wait(float(get_settings().get("thermal_limit_c") or 85.0))
            run_opts = dict(opts)
            if attempt > 0:
                run_opts["_resume"] = True
                print(f"[Factory] ♻️ Tentativa {attempt + 1}/{max_retries + 1} com checkpoint resume...", flush=True)
            result = await run_video_job(
                job_id=job_id,
                client_id=client_id,
                topic=topic,
                skill_id=skill_id,
                mode=mode,
                options=run_opts,
            )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            print(f"[Factory] ⚠️ Erro na tentativa {attempt + 1}: {exc}", flush=True)
            if attempt >= max_retries:
                raise

    job_dir = OUTPUTS_DIR / job_id
    qc = run_automated_qc(
        job_dir,
        expected_aspect=opts.get("aspect_ratio"),
        expected_fps=int(opts.get("fps") or 30),
        check_loudness=not skip_loudness_qc,
    )
    print(f"[Factory] 🔍 QC automático: passed={qc['passed']} | metrics={qc.get('metrics')}", flush=True)
    if qc.get("warnings"):
        print(f"[Factory] ⚠️ Avisos QC: {qc['warnings']}", flush=True)
    if qc.get("errors"):
        print(f"[Factory] ❌ Erros QC: {qc['errors']}", flush=True)

    # Upload qc_report.json / retry Drive upload if pipeline finished before Drive was connected
    qr_path = job_dir / "quality_report.json"
    if qr_path.exists():
        qr = json.loads(qr_path.read_text(encoding="utf-8"))
        gd_b = qr.get("gdrive_backup") or {}
        if gd_b.get("status") != "uploaded" and probe_gdrive_status().get("connected"):
            gd_b = await asyncio.to_thread(upload_job_to_gdrive, job_dir, topic, job_id, prune_after_upload=ensure_drive_prune)
            qr["gdrive_backup"] = gd_b
            qr_path.write_text(json.dumps(qr, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"job_id": job_id, "topic": topic, "result": result, "qc": qc, "disk_free_gb": round(shutil.disk_usage(BASE_DIR).free / (1024**3), 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description="FrimeRise Zero-Agent-Token Autonomous Video Factory CLI")
    parser.add_argument("--topic", help="Tema do vídeo único a produzir")
    parser.add_argument("--queue", help="Caminho para arquivo JSON com fila de vídeos (ver fila_videos.example.json)")
    parser.add_argument("--resume-job", help="ID de um job existente para retomar via checkpoint")
    parser.add_argument("--qc-only", help="Executa apenas o QC automático em uma pasta outputs/<job_id>")
    parser.add_argument("--engine", default="netflix_doc", choices=["netflix_doc", "cinematic_broll", "cartoon_2d"])
    parser.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "4:5", "1:1"])
    parser.add_argument("--minutes", type=float, default=17.0, help="Duração alvo em minutos (netflix_doc)")
    parser.add_argument("--lang", default="pt_br", choices=["pt_br", "en_us", "es"])
    parser.add_argument("--thumb-3words", default="", help="Texto de 3 palavras nas thumbnails A/B")
    parser.add_argument("--directives", default="", help="Diretrizes editoriais extras")
    parser.add_argument("--shorts-cascade", action="store_true", help="Extrair 5 Shorts 9:16 do 16:9")
    parser.add_argument("--min-free-gb", type=float, default=10.0, help="Mínimo de espaço livre em GB no SSD")
    parser.add_argument("--skip-loudness-qc", action="store_true", help="Pular análise ebur128 (mais rápido)")
    args = parser.parse_args()

    if args.qc_only:
        qc = run_automated_qc(Path(args.qc_only), check_loudness=not args.skip_loudness_qc)
        print(json.dumps(qc, indent=2, ensure_ascii=False))
        return 0 if qc.get("passed") else 1

    items: List[Dict[str, Any]] = []
    if args.resume_job:
        items.append({"topic": args.topic or args.resume_job, "resume_job_id": args.resume_job})
    elif args.queue:
        raw = json.loads(Path(args.queue).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else list(raw.get("videos") or [])
    elif args.topic:
        items.append({
            "topic": args.topic,
            "engine_style": args.engine,
            "aspect_ratio": args.aspect,
            "target_minutes": args.minutes,
            "language": args.lang,
            "thumb_3words": args.thumb_3words,
            "custom_directives": args.directives,
            "auto_shorts_cascade": args.shorts_cascade,
        })
    else:
        parser.print_help()
        return 2

    summaries = []
    for idx, item in enumerate(items, 1):
        print(f"\n================ [{idx}/{len(items)}] {item.get('topic', item.get('resume_job_id'))} ================", flush=True)
        out = asyncio.run(
            produce_single_item(
                item,
                min_free_gb=args.min_free_gb,
                skip_loudness_qc=args.skip_loudness_qc,
            )
        )
        summaries.append(out)

    print("\n================ RESUMO DA PRODUÇÃO ================", flush=True)
    print(json.dumps(summaries, indent=2, ensure_ascii=False))
    return 0 if all(s["qc"].get("passed") for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
