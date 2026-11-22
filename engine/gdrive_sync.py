"""FrimeRise Google Drive Automatic Archiving & Local Storage Saver (engine/gdrive_sync.py).

Uploads finished FrimeRise jobs into cleanly named, separated folders inside Google Drive:
    FrimeRise / <Nome_do_Projeto>_<YYYY-MM-DD>_<job_short>/
        master.mp4
        thumb_A_mystery.jpg
        thumb_B_contrast.jpg
        thumb_C_zoom.jpg
        cover_9x16.png
        quality_report.json
        words.json
        timeline.otio
        shorts_cascade/ (when present)
        dubbed/ (when present)

Supports 3 transparent backends (auto-detected in priority order):
  1. `rclone` (MIT-licensed, resumable uploads for 100MB-1GB+ videos — recommended!)
  2. Direct Google Drive API v3 (`googleapiclient` + `google.oauth2`, using `data/gdrive_token.json`)
  3. Mounted Google Drive folder (GNOME Online Accounts GVFS `/run/user/<uid>/gvfs/google-drive:*`
     or custom local sync directory configured in Settings `gdrive_local_dir`).

Optional Storage Saver (`gdrive_prune_local = "1"`):
  - ONLY AFTER verifying 100% upload integrity on Google Drive, removes heavy local files
    (`_work/`, duplicate TikTok/Reels/Shorts variants, `capcut_project.zip`, and optionally `master.mp4`)
    while preserving lightweight `preview_540p.mp4` + thumbnails + `quality_report.json` so the
    local VIP Gallery remains instant and light on the Acer Aspire 5 SSD.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from database import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
GDRIVE_TOKEN_PATH = DATA_DIR / "gdrive_token.json"
GDRIVE_CREDS_PATH = DATA_DIR / "gdrive_credentials.json"

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Files/folders to upload for each completed project
UPLOAD_TOP_FILES = (
    "master.mp4",
    "master_tiktok.mp4",
    "master_reels.mp4",
    "master_shorts.mp4",
    "capcut_project.zip",
    "thumb_A_mystery.jpg",
    "thumb_B_contrast.jpg",
    "thumb_C_zoom.jpg",
    "cover_9x16.png",
    "preview_540p.mp4",
    "quality_report.json",
    "qc_report.json",
    "words.json",
    "script.json",
    "edl_timeline.json",
    "timeline.otio",
)
UPLOAD_SUBDIRS = ("shorts_cascade", "dubbed")

# Heavy local files safe to prune ONLY after confirmed Drive upload of that exact filename
# (always preserves lightweight preview_540p.mp4 + thumbnails + words.json + quality_report.json)
PRUNABLE_HEAVY_FILES = (
    "master_tiktok.mp4",
    "master_reels.mp4",
    "master_shorts.mp4",
    "capcut_project.zip",
    "master.mp4",
)


def _find_rclone_bin() -> Optional[str]:
    found = shutil.which("rclone")
    if found:
        return found
    for cand in (
        Path.home() / ".local" / "bin" / "rclone",
        BASE_DIR / ".venv" / "bin" / "rclone",
    ):
        if cand.exists() and cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def sanitize_folder_name(topic: str, job_id: str) -> str:
    """Create a clean, readable, filesystem- & Drive-safe folder name for a project."""
    raw = (topic or "Projeto_FrimeRise").strip()
    norm = unicodedata.normalize("NFKD", raw)
    ascii_txt = "".join(ch for ch in norm if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_txt).strip("_")[:48] or "Projeto_FrimeRise"
    date_tag = datetime.now().strftime("%Y-%m-%d")
    short_id = re.sub(r"[^A-Za-z0-9]", "", str(job_id or ""))[-6:] or "000000"
    return f"{slug}_{date_tag}_{short_id}"


def _detect_rclone_drive_remote(preferred: str = "") -> Optional[str]:
    rclone_bin = _find_rclone_bin()
    if not rclone_bin:
        return None
    try:
        proc = subprocess.run(
            [rclone_bin, "listremotes", "--long"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return None
        remotes: List[Tuple[str, str]] = []
        for line in proc.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                remotes.append((parts[0].rstrip(":"), parts[1].lower()))
        if preferred:
            pref_clean = preferred.strip().rstrip(":")
            for name, rtype in remotes:
                if name == pref_clean:
                    return name
        for name, rtype in remotes:
            if rtype == "drive":
                return name
        for name, _ in remotes:
            if "drive" in name.lower() or "gdrive" in name.lower():
                return name
    except Exception:
        pass
    return None


def _detect_gvfs_drive_mount() -> Optional[Path]:
    uid = os.getuid()
    gvfs_dir = Path(f"/run/user/{uid}/gvfs")
    if not gvfs_dir.exists():
        return None
    try:
        for entry in sorted(gvfs_dir.iterdir()):
            if "google-drive" in entry.name.lower() and entry.is_dir():
                return entry
    except Exception:
        pass
    return None


def _has_google_api_token() -> bool:
    if not GDRIVE_TOKEN_PATH.exists():
        return False
    try:
        import googleapiclient.discovery  # noqa: F401
        import google.oauth2.credentials  # noqa: F401

        data = json.loads(GDRIVE_TOKEN_PATH.read_text(encoding="utf-8"))
        return bool(data.get("refresh_token") or data.get("token"))
    except Exception:
        return False


def probe_gdrive_status() -> Dict[str, Any]:
    """Check whether any Google Drive archiving backend is currently ready."""
    settings = get_settings() or {}
    root_folder = (settings.get("gdrive_root_folder") or "FrimeRise").strip() or "FrimeRise"
    auto_upload = settings.get("gdrive_auto_upload", "1") == "1"
    prune_local = settings.get("gdrive_prune_local", "1") == "1"
    preferred_remote = (settings.get("gdrive_rclone_remote") or "").strip()
    custom_local = (settings.get("gdrive_local_dir") or "").strip()

    rclone_remote = _detect_rclone_drive_remote(preferred_remote)
    api_ready = _has_google_api_token()
    gvfs_mount = _detect_gvfs_drive_mount()
    local_sync_dir: Optional[Path] = None
    if custom_local:
        cand = Path(custom_local).expanduser()
        if cand.exists() and cand.is_dir():
            local_sync_dir = cand
    if local_sync_dir is None and gvfs_mount is not None:
        local_sync_dir = gvfs_mount

    backend = "none"
    detail = "Não conectado. Execute ./setup_gdrive.sh (rclone) ou monte o Google Drive no Ubuntu."
    if rclone_remote:
        backend = "rclone"
        detail = f"rclone conectado ({rclone_remote}:{root_folder}/)"
    elif api_ready:
        backend = "google_api"
        detail = f"Google Drive API v3 conectada ({root_folder}/)"
    elif local_sync_dir is not None:
        backend = "mounted_folder"
        detail = f"Pasta Google Drive montada ({local_sync_dir / root_folder})"

    return {
        "connected": backend != "none",
        "backend": backend,
        "detail": detail,
        "root_folder": root_folder,
        "auto_upload": auto_upload,
        "prune_local": prune_local,
        "rclone_installed": _find_rclone_bin() is not None,
        "rclone_remote": rclone_remote or "",
        "local_sync_dir": str(local_sync_dir) if local_sync_dir else "",
        "setup_command": "./setup_gdrive.sh",
    }


def _collect_project_files(job_dir: Path) -> List[Tuple[Path, str]]:
    """Return list of (abs_file_path, relative_path_inside_project_folder)."""
    items: List[Tuple[Path, str]] = []
    for fname in UPLOAD_TOP_FILES:
        p = job_dir / fname
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            items.append((p, fname))
    for sub in UPLOAD_SUBDIRS:
        sub_dir = job_dir / sub
        if sub_dir.exists() and sub_dir.is_dir():
            for f in sorted(sub_dir.rglob("*")):
                if f.is_file() and f.stat().st_size > 0:
                    items.append((f, str(f.relative_to(job_dir)).replace("\\", "/")))
    return items


def _upload_via_rclone(
    remote: str,
    root_folder: str,
    folder_name: str,
    job_dir: Path,
    files: List[Tuple[Path, str]],
) -> Dict[str, Any]:
    rclone_bin = _find_rclone_bin()
    if not rclone_bin:
        raise RuntimeError("rclone não encontrado")

    remote_base = f"{remote}:{root_folder}/{folder_name}"
    subprocess.run([rclone_bin, "mkdir", remote_base], check=True, capture_output=True, text=True, timeout=30)

    uploaded = 0
    total_bytes = 0
    uploaded_files: List[str] = []
    for src, rel in files:
        rel_dir = str(Path(rel).parent).replace("\\", "/")
        dest_dir = remote_base if rel_dir in ("", ".") else f"{remote_base}/{rel_dir}"
        proc = subprocess.run(
            [rclone_bin, "copy", str(src), dest_dir, "--transfers", "2", "--retries", "3"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode == 0:
            uploaded += 1
            total_bytes += src.stat().st_size
            uploaded_files.append(rel)

    # Try fetching shareable folder link (non-fatal if Drive permissions restrict)
    drive_url = ""
    try:
        lp = subprocess.run(
            [rclone_bin, "link", remote_base],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if lp.returncode == 0 and lp.stdout.strip().startswith("http"):
            drive_url = lp.stdout.strip()
    except Exception:
        pass

    return {
        "backend": "rclone",
        "remote_path": remote_base,
        "folder_name": folder_name,
        "drive_url": drive_url,
        "files_uploaded": uploaded,
        "uploaded_files": uploaded_files,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
    }


def _upload_via_google_api(
    root_folder: str,
    folder_name: str,
    files: List[Tuple[Path, str]],
) -> Dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_PATH), DRIVE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        GDRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _find_or_create_folder(name: str, parent_id: Optional[str] = None) -> str:
        safe_q = name.replace("'", "\\'")
        q = f"name = '{safe_q}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        res = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=5).execute()
        found = res.get("files") or []
        if found:
            return str(found[0]["id"])
        meta: Dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            meta["parents"] = [parent_id]
        created = service.files().create(body=meta, fields="id").execute()
        return str(created["id"])

    root_id = _find_or_create_folder(root_folder)
    proj_id = _find_or_create_folder(folder_name, parent_id=root_id)
    sub_cache: Dict[str, str] = {"": proj_id, ".": proj_id}

    uploaded = 0
    total_bytes = 0
    uploaded_files: List[str] = []
    for src, rel in files:
        parent_rel = str(Path(rel).parent).replace("\\", "/")
        if parent_rel not in sub_cache:
            cur_parent = proj_id
            for part in Path(parent_rel).parts:
                cur_parent = _find_or_create_folder(part, parent_id=cur_parent)
            sub_cache[parent_rel] = cur_parent
        target_parent = sub_cache[parent_rel]

        media = MediaFileUpload(str(src), resumable=True, chunksize=8 * 1024 * 1024)
        created_file = service.files().create(
            body={"name": src.name, "parents": [target_parent]},
            media_body=media,
            fields="id",
        ).execute()
        if isinstance(created_file, dict) and created_file.get("id"):
            uploaded += 1
            total_bytes += src.stat().st_size
            uploaded_files.append(rel)

    return {
        "backend": "google_api",
        "remote_path": f"{root_folder}/{folder_name}",
        "folder_name": folder_name,
        "folder_id": proj_id,
        "drive_url": f"https://drive.google.com/drive/folders/{proj_id}",
        "files_uploaded": uploaded,
        "uploaded_files": uploaded_files,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
    }


def _upload_via_mounted_folder(
    mount_dir: Path,
    root_folder: str,
    folder_name: str,
    files: List[Tuple[Path, str]],
) -> Dict[str, Any]:
    dest_root = mount_dir / root_folder / folder_name
    dest_root.mkdir(parents=True, exist_ok=True)
    uploaded = 0
    total_bytes = 0
    uploaded_files: List[str] = []
    for src, rel in files:
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        src_size = src.stat().st_size
        if target.exists() and target.stat().st_size == src_size:
            uploaded += 1
            total_bytes += src_size
            uploaded_files.append(rel)

    return {
        "backend": "mounted_folder",
        "remote_path": str(dest_root),
        "folder_name": folder_name,
        "drive_url": "",
        "files_uploaded": uploaded,
        "uploaded_files": uploaded_files,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
    }


def prune_local_heavy_files(
    job_dir: Path,
    *,
    remove_master: bool = False,
    uploaded_files: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Free local Acer Aspire 5 disk space ONLY for files confirmed uploaded to Google Drive.

    NEVER deletes any deliverable file unless its exact filename is present in `uploaded_files`
    (verified remote upload success). Preserves preview_540p.mp4, thumbnails, cover, and metadata.
    """
    confirmed: Set[str] = {
        str(item).replace("\\", "/").lstrip("./")
        for item in (uploaded_files or ())
        if str(item).strip()
    }
    freed_bytes = 0
    removed: List[str] = []
    pruned_files: List[str] = []

    if not confirmed:
        return {
            "freed_mb": 0.0,
            "removed": [],
            "pruned_files": [],
        }

    # Only delete scratch _work/ after master.mp4 itself is confirmed backed up on Drive
    work_dir = job_dir / "_work"
    if "master.mp4" in confirmed and work_dir.exists() and work_dir.is_dir():
        for f in work_dir.rglob("*"):
            if f.is_file():
                try:
                    freed_bytes += f.stat().st_size
                except Exception:
                    pass
        shutil.rmtree(work_dir, ignore_errors=True)
        removed.append("_work/")

    for fname in PRUNABLE_HEAVY_FILES:
        if fname == "master.mp4" and not remove_master:
            continue
        if fname not in confirmed:
            # Strict safety guard: never delete a file that was not confirmed uploaded!
            continue
        p = job_dir / fname
        if p.exists() and p.is_file():
            try:
                freed_bytes += p.stat().st_size
                p.unlink(missing_ok=True)
                removed.append(fname)
                pruned_files.append(fname)
            except Exception:
                pass

    # Also prune heavy video deliverables inside shorts_cascade/ and dubbed/ ONLY when confirmed uploaded
    for sub in UPLOAD_SUBDIRS:
        sub_dir = job_dir / sub
        if not (sub_dir.exists() and sub_dir.is_dir()):
            continue
        for f in sorted(sub_dir.rglob("*.mp4")):
            rel_sub = str(f.relative_to(job_dir)).replace("\\", "/")
            if rel_sub not in confirmed:
                continue
            try:
                freed_bytes += f.stat().st_size
                f.unlink(missing_ok=True)
                removed.append(rel_sub)
                pruned_files.append(rel_sub)
            except Exception:
                pass

    return {
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "removed": removed,
        "pruned_files": pruned_files,
    }


def upload_job_to_gdrive(
    job_dir: Path,
    topic: str,
    job_id: str,
    *,
    prune_after_upload: Optional[bool] = None,
) -> Dict[str, Any]:
    """Archive a completed FrimeRise project into a named folder on Google Drive.

    Never raises fatally on missing Drive config; returns a clean status dict so
    video manufacturing always succeeds even before the user links Drive.
    """
    job_dir = Path(job_dir)
    status = probe_gdrive_status()
    folder_name = sanitize_folder_name(topic, job_id)

    if not status["connected"]:
        return {
            "status": "not_configured",
            "folder_name": folder_name,
            "detail": status["detail"],
            "setup_command": "./setup_gdrive.sh",
            "uploaded_files": [],
            "pruned_files": [],
        }

    files = _collect_project_files(job_dir)
    if not files:
        return {
            "status": "empty",
            "folder_name": folder_name,
            "detail": "Nenhum arquivo final encontrado para upload.",
            "uploaded_files": [],
            "pruned_files": [],
        }

    try:
        if status["backend"] == "rclone":
            res = _upload_via_rclone(status["rclone_remote"], status["root_folder"], folder_name, job_dir, files)
        elif status["backend"] == "google_api":
            res = _upload_via_google_api(status["root_folder"], folder_name, files)
        else:
            res = _upload_via_mounted_folder(Path(status["local_sync_dir"]), status["root_folder"], folder_name, files)
    except Exception as exc:
        return {
            "status": "error",
            "folder_name": folder_name,
            "detail": f"Erro ao enviar para o Google Drive: {str(exc)[:220]}",
            "uploaded_files": [],
            "pruned_files": [],
        }

    uploaded_files: List[str] = list(res.get("uploaded_files") or [])
    should_prune = status["prune_local"] if prune_after_upload is None else bool(prune_after_upload)
    prune_info: Dict[str, Any] = {"freed_mb": 0.0, "removed": [], "pruned_files": []}
    if should_prune and uploaded_files and res.get("files_uploaded", 0) > 0:
        prune_info = prune_local_heavy_files(
            job_dir,
            remove_master=True,
            uploaded_files=uploaded_files,
        )

    return {
        "status": "uploaded",
        **res,
        "uploaded_files": uploaded_files,
        "pruned_local": bool(should_prune and prune_info["removed"]),
        "freed_mb": prune_info["freed_mb"],
        "removed_local": prune_info["removed"],
        "pruned_files": prune_info["pruned_files"],
    }
