"""FrimeRise Commercial Exporters:
1. Editable CapCut International Project (.zip) using vendor/pyCapCut
2. Linux Kdenlive / DaVinci Timeline (.otio) using OpenTimelineIO
3. 540p Watermarked WhatsApp Approval Preview ("PRÉVIA • FRIMERISE") via Skia + VAAPI
4. Dual-Hook A/B Export reusing 90% of already-rendered video via ffmpeg concat -c copy
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import opentimelineio as otio
import pycapcut as cc
from pycapcut import trange_seconds
import skia

from engine.intel_vaapi import build_video_encode_args, run_ffmpeg_safe
from engine.skia_compositor import _load_verified_typeface

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Editable CapCut International Project (.zip) via pyCapCut
# ---------------------------------------------------------------------------
def export_capcut_zip(
    project_name: str,
    master_video: Path,
    audio_path: Optional[Path],
    music_path: Optional[Path],
    words: List[Dict[str, Any]],
    duration_s: float,
    out_zip: Path,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Create a real CapCut International draft project with pyCapCut and bundle into .zip."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in project_name)[:40] or "FrimeRise_Project"

    with tempfile.TemporaryDirectory(prefix="frimerise_capcut_") as tmp:
        tmp_dir = Path(tmp)
        media_dir = tmp_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        vid_copy = media_dir / master_video.name
        shutil.copy2(master_video, vid_copy)

        draft_root = tmp_dir / "drafts"
        draft_root.mkdir(parents=True, exist_ok=True)
        df = cc.DraftFolder(str(draft_root))
        script = df.create_draft(safe_name, width, height, allow_replace=True)

        script.add_track(cc.TrackType.video)
        script.add_track(cc.TrackType.audio, "Narration")
        script.add_track(cc.TrackType.text, "Captions")

        v_mat = cc.VideoMaterial(str(vid_copy))
        safe_vid_us = min(v_mat.duration, max(1_000_000, int(duration_s * 1_000_000)))
        vid_seg = cc.VideoSegment(v_mat, cc.trange(0, safe_vid_us))
        script.add_segment(vid_seg)

        if audio_path and audio_path.exists():
            aud_copy = media_dir / audio_path.name
            shutil.copy2(audio_path, aud_copy)
            try:
                a_mat = cc.AudioMaterial(str(aud_copy))
                safe_aud_us = min(a_mat.duration, safe_vid_us)
                aud_seg = cc.AudioSegment(a_mat, cc.trange(0, safe_aud_us), volume=1.0)
                script.add_segment(aud_seg, "Narration")
            except Exception:
                pass

        # Group words into editable CapCut text segments
        chunk_words: List[Dict[str, Any]] = []
        chunks: List[Dict[str, Any]] = []
        for w in words:
            chunk_words.append(w)
            if len(chunk_words) >= 3 or str(w["word"]).endswith((".", "!", "?")):
                chunks.append(
                    {
                        "text": " ".join(x["word"] for x in chunk_words).upper(),
                        "start": float(chunk_words[0]["start"]),
                        "end": float(chunk_words[-1]["end"]),
                    }
                )
                chunk_words = []
        if chunk_words:
            chunks.append(
                {
                    "text": " ".join(x["word"] for x in chunk_words).upper(),
                    "start": float(chunk_words[0]["start"]),
                    "end": float(chunk_words[-1]["end"]),
                }
            )

        for idx, ch in enumerate(chunks[:120]):
            st = max(0.0, ch["start"])
            dur = max(0.25, ch["end"] - st)
            if st + dur > duration_s:
                dur = max(0.15, duration_s - st)
            if dur <= 0.05:
                continue
            color = (0.72, 1.0, 0.004) if idx % 2 == 0 else (1.0, 0.82, 0.4)  # Lime / Gold
            try:
                tseg = cc.TextSegment(
                    ch["text"],
                    trange_seconds(st, duration=dur),
                    style=cc.TextStyle(color=color, size=8.0),
                    clip_settings=cc.ClipSettings(transform_y=-0.52),
                )
                script.add_segment(tseg, "Captions")
            except Exception:
                continue

        script.save()

        # Package draft directory + bundled media into portable .zip
        with zipfile.ZipFile(str(out_zip), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            draft_project_dir = draft_root / safe_name
            for f in draft_project_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=f"{safe_name}/{f.relative_to(draft_project_dir)}")
            for f in media_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=f"{safe_name}/media/{f.name}")
            readme = (
                "FrimeRise — Projeto Editável CapCut Internacional\n"
                "1. Extraia esta pasta para a pasta de Drafts do CapCut Desktop.\n"
                "2. Abra o CapCut: a timeline 9:16, áudio e legendas editáveis aparecerão prontas.\n"
            )
            zf.writestr(f"{safe_name}/LEIA-ME_FRIMERISE.txt", readme)

    return out_zip


# ---------------------------------------------------------------------------
# 2. Linux Kdenlive / DaVinci Timeline (.otio) via OpenTimelineIO
# ---------------------------------------------------------------------------
def export_kdenlive_otio(
    project_name: str,
    master_video: Path,
    audio_path: Optional[Path],
    music_path: Optional[Path],
    words: List[Dict[str, Any]],
    duration_s: float,
    out_otio: Path,
    fps: float = 30.0,
) -> Path:
    """Export an OpenTimelineIO (.otio) timeline compatible with Kdenlive & DaVinci Resolve."""
    tl = otio.schema.Timeline(name=f"FrimeRise - {project_name}")

    v_track = otio.schema.Track(name="V1 - Master 9x16", kind=otio.schema.TrackKind.Video)
    tr = otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(0, fps),
        duration=otio.opentime.RationalTime(duration_s * fps, fps),
    )
    v_clip = otio.schema.Clip(
        name=master_video.stem,
        media_reference=otio.schema.ExternalReference(target_url=master_video.resolve().as_uri(), available_range=tr),
        source_range=tr,
    )
    # Add caption cues as timeline markers for instant navigation in Kdenlive
    for i in range(0, len(words), 3):
        grp = words[i : i + 3]
        if not grp:
            continue
        m_start = float(grp[0]["start"])
        m_dur = max(0.2, float(grp[-1]["end"]) - m_start)
        v_clip.markers.append(
            otio.schema.Marker(
                name=" ".join(x["word"] for x in grp),
                marked_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(m_start * fps, fps),
                    duration=otio.opentime.RationalTime(m_dur * fps, fps),
                ),
                color=otio.schema.MarkerColor.MAGENTA if (i // 3) % 2 == 0 else otio.schema.MarkerColor.GREEN,
            )
        )
    v_track.append(v_clip)
    tl.tracks.append(v_track)

    if audio_path and audio_path.exists():
        a_track = otio.schema.Track(name="A1 - Master Broadcast -14 LUFS", kind=otio.schema.TrackKind.Audio)
        a_track.append(
            otio.schema.Clip(
                name=audio_path.stem,
                media_reference=otio.schema.ExternalReference(target_url=audio_path.resolve().as_uri(), available_range=tr),
                source_range=tr,
            )
        )
        tl.tracks.append(a_track)

    if music_path and music_path.exists():
        m_track = otio.schema.Track(name="A2 - Trilha Musical", kind=otio.schema.TrackKind.Audio)
        m_track.append(
            otio.schema.Clip(
                name=music_path.stem,
                media_reference=otio.schema.ExternalReference(target_url=music_path.resolve().as_uri(), available_range=tr),
                source_range=tr,
            )
        )
        tl.tracks.append(m_track)

    out_otio.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(tl, str(out_otio))
    return out_otio


# ---------------------------------------------------------------------------
# 3. 540p WhatsApp Commercial Preview with Skia "PRÉVIA • FRIMERISE" Watermark
# ---------------------------------------------------------------------------
def _render_watermark_png(watermark_text: str, out_png: Path, w: int = 540, h: int = 960) -> Path:
    surf = skia.Surface(w, h)
    c = surf.getCanvas()
    c.clear(skia.Color4f(0, 0, 0, 0))
    tf, _ = _load_verified_typeface("Montserrat-Black.ttf", role="watermark")
    font = skia.Font(tf, 34)
    text = watermark_text.upper()

    # Tiled diagonal semi-transparent Cyber-Luxury watermark
    c.save()
    c.translate(w / 2.0, h / 2.0)
    c.rotate(-28.0)
    paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(82, 255, 255, 255))
    accent = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(72, 255, 46, 147))
    for row in range(-5, 6):
        y = row * 140.0
        for col in range(-2, 3):
            x = col * 420.0 + (row % 2) * 180.0
            c.drawString(text, x, y, font, accent if row % 2 else paint)
    c.restore()

    # Crisp bottom commercial ribbon
    ribbon = skia.Rect.MakeXYWH(28, h - 88, w - 56, 56)
    c.drawRoundRect(ribbon, 14, 14, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(195, 11, 7, 19)))
    c.drawRoundRect(ribbon, 14, 14, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0, Color=skia.ColorSetARGB(210, 255, 209, 102)))
    sfont = skia.Font(tf, 20)
    tw = sfont.measureText(text)
    c.drawString(text, (w - tw) / 2.0, h - 53, sfont, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102)))

    surf.makeImageSnapshot().save(str(out_png), skia.kPNG)
    return out_png


def export_whatsapp_preview_540p(
    master_video: Path,
    out_preview: Path,
    watermark_text: str = "PRÉVIA • FRIMERISE",
    aspect_ratio: str = "9:16",
) -> Path:
    """Create lightweight 540p WhatsApp approval MP4 with branded Skia watermark (9:16, 4:5, 1:1, or 16:9)."""
    dims = {"16:9": (960, 540), "4:5": (540, 676), "1:1": (540, 540), "9:16": (540, 960)}
    pw, ph = dims.get(aspect_ratio, (540, 960))
    wm_png = out_preview.with_suffix(".wm.png")
    _render_watermark_png(watermark_text, wm_png, w=pw, h=ph)
    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=26)

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        "-i",
        str(master_video),
        "-i",
        str(wm_png),
        "-filter_complex",
        f"[0:v]scale={pw}:{ph}:flags=lanczos[sc];[sc][1:v]overlay=0:0,{hw_suffix}[vout]",
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        *enc_args,
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(out_preview),
    ]
    run_ffmpeg_safe(cmd)
    wm_png.unlink(missing_ok=True)
    return out_preview


# ---------------------------------------------------------------------------
# 4. Dual-Hook A/B Export (Reuse 90% body via lossless ffmpeg concat -c copy)
# ---------------------------------------------------------------------------
def splice_dual_hook_b(
    master_hook_a: Path,
    hook_b_intro: Path,
    hook_split_s: float,
    out_hook_b: Path,
) -> Path:
    """Re-use the remaining 90% of master_hook_a cleanly with hook_b_intro using ffmpeg concat -c copy."""
    body_segment = out_hook_b.with_name(out_hook_b.stem + "_body.mp4")
    concat_list = out_hook_b.with_name(out_hook_b.stem + "_concat.txt")

    # Extract body starting from hook_split_s (stream copy if possible, else keyframe-aligned copy)
    run_ffmpeg_safe(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{hook_split_s:.3f}",
            "-i",
            str(master_hook_a),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(body_segment),
        ]
    )

    concat_list.write_text(
        f"file '{hook_b_intro.resolve()}'\nfile '{body_segment.resolve()}'\n",
        encoding="utf-8",
    )

    try:
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(out_hook_b),
            ]
        )
    except subprocess.CalledProcessError:
        # Fallback if codec parameters differ slightly on some edge clip
        pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
        run_ffmpeg_safe(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                *pre_args,
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-vf",
                hw_suffix,
                *enc_args,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(out_hook_b),
            ]
        )
    finally:
        body_segment.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)

    return out_hook_b
