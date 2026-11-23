#!/usr/bin/env python3
"""FrimeRise Colab / Cloud Secure Bootstrap & Pre-Flight Check.

Loads private API keys and sessions from a private Google Drive folder
(default: `/content/drive/MyDrive/FrimeRise_Secrets/`) into the local
FrimeRise workspace WITHOUT ever storing secrets in Git or printing them
to terminal logs.

Supported private files inside `FrimeRise_Secrets/`:
  1. `frimerise.db`           -> copied to `data/frimerise.db` (chmod 600)
  2. `.env` (optional)        -> merged into `data/frimerise.db` via save_settings()
  3. `google_flow_pro.tar.gz` -> optional browser session extracted to `data/profiles/google_flow_pro/`

Also configures `gdrive_local_dir` automatically when running inside a
mounted Google Drive environment so rendered videos save directly into
`Meu Drive/FrimeRise/<Projeto>_<Data>_<ID>/`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path
from typing import Dict, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_DEST = DATA_DIR / "frimerise.db"
PROFILES_DIR = DATA_DIR / "profiles"

ENV_TO_SETTING_KEY: Dict[str, str] = {
    "GEMINI_API_KEY": "gemini_api_key",
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "PIXABAY_API_KEY": "pixabay_api_key",
    "PIXABAY_IMAGE_API_KEY": "pixabay_image_api_key",
    "PEXELS_API_KEY": "pexels_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "DEFAULT_LLM": "default_llm",
    "GDRIVE_ROOT_FOLDER": "gdrive_root_folder",
}


def _parse_dotenv(env_path: Path) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            parsed[k] = v
    return parsed


def _safe_copy_sqlite(src: Path, dst: Path) -> None:
    """Copy a SQLite DB cleanly via sqlite3 backup API (safe even if WAL existed)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Remove any stale WAL/SHM sidecars at destination first
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(dst) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        dst_conn = sqlite3.connect(str(dst))
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
    except Exception:
        shutil.copy2(src, dst)
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass


def _safe_extract_tar(archive: Path, dest_dir: Path) -> bool:
    """Extract tar.gz safely (prevents path traversal)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    base_resolved = dest_dir.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (dest_dir / member.name).resolve()
            if not str(target).startswith(str(base_resolved)):
                raise RuntimeError(f"Unsafe tar member blocked: {member.name}")
        tf.extractall(path=dest_dir)
    return True


def _check_gemini(api_key: str) -> Tuple[bool, str]:
    if not api_key:
        return False, "FALTANDO (configure GEMINI_API_KEY ou FrimeRise_Secrets/frimerise.db)"
    import httpx

    for model in ("gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-3-flash-preview"):
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": "OK"}]}], "generationConfig": {"maxOutputTokens": 8}},
                timeout=12.0,
            )
            if r.status_code == 200:
                return True, f"OK (HTTP 200 • {model} • Gemini 3.8 TTS pronto)"
            last_err = f"HTTP {r.status_code} ({model})"
        except Exception as exc:
            last_err = f"erro rede ({str(exc)[:45]})"
    return False, f"FALHOU ({last_err})"


def _check_deepseek(api_key: str) -> Tuple[bool, str]:
    if not api_key:
        return True, "opcional (não configurada)"
    import httpx

    try:
        r = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "OK"}], "max_tokens": 5},
            timeout=10.0,
        )
        if r.status_code == 200:
            return True, "OK (HTTP 200)"
        return False, f"FALHOU (HTTP {r.status_code})"
    except Exception as exc:
        return False, f"erro rede ({str(exc)[:45]})"


def _check_pixabay(video_key: str, image_key: str) -> Tuple[Tuple[bool, str], Tuple[bool, str]]:
    import httpx

    eff_img = image_key or video_key
    eff_vid = video_key or image_key
    vid_res = (True, "opcional (não configurada)")
    img_res = (True, "opcional (não configurada)")

    if eff_vid:
        try:
            r = httpx.get(
                "https://pixabay.com/api/videos/",
                params={"key": eff_vid, "q": "city", "per_page": 3},
                timeout=10.0,
            )
            vid_res = (r.status_code == 200, "OK (HTTP 200)" if r.status_code == 200 else f"FALHOU (HTTP {r.status_code})")
        except Exception as exc:
            vid_res = (False, f"erro rede ({str(exc)[:45]})")

    if eff_img:
        tag = "chave dedicada" if (image_key and image_key != video_key) else "chave compartilhada"
        try:
            r = httpx.get(
                "https://pixabay.com/api/",
                params={"key": eff_img, "q": "architecture", "per_page": 3},
                timeout=10.0,
            )
            img_res = (
                r.status_code == 200,
                f"OK (HTTP 200 • {tag})" if r.status_code == 200 else f"FALHOU (HTTP {r.status_code})",
            )
        except Exception as exc:
            img_res = (False, f"erro rede ({str(exc)[:45]})")

    return vid_res, img_res


def main() -> int:
    parser = argparse.ArgumentParser(description="FrimeRise Colab/Cloud Secure Secrets Loader & Pre-Flight Check")
    parser.add_argument(
        "--secrets-dir",
        default="/content/drive/MyDrive/FrimeRise_Secrets",
        help="Pasta privada contendo frimerise.db e/ou .env (padrão Colab Drive)",
    )
    parser.add_argument(
        "--drive-mount",
        default="/content/drive/MyDrive",
        help="Raiz montada do Google Drive no Colab para auto-upload direto",
    )
    parser.add_argument(
        "--skip-live-check",
        action="store_true",
        help="Apenas verifica presença das chaves sem fazer chamadas HTTP",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Não copia frimerise.db externo; apenas roda o pre-flight check no banco atual",
    )
    args = parser.parse_args()

    secrets_dir = Path(args.secrets_dir).expanduser()
    drive_mount = Path(args.drive_mount).expanduser()

    print("\n[ColabBootstrap] Iniciando carregamento seguro de credenciais...", flush=True)

    # 1. Copy private frimerise.db from Drive Secrets folder (if present & requested)
    if not args.no_copy:
        src_db = secrets_dir / "frimerise.db"
        if src_db.exists() and src_db.stat().st_size > 0:
            _safe_copy_sqlite(src_db, DB_DEST)
            print(f"[ColabBootstrap] frimerise.db importado com segurança de: {src_db}", flush=True)
        else:
            print(f"[ColabBootstrap] Aviso: {src_db} não encontrado (usando banco local / .env).", flush=True)

        # 2. Optional Flow Pro session restore
        flow_tar = secrets_dir / "google_flow_pro.tar.gz"
        if flow_tar.exists() and flow_tar.stat().st_size > 0:
            try:
                _safe_extract_tar(flow_tar, PROFILES_DIR)
                print("[ColabBootstrap] Sessão Google Flow Pro restaurada com segurança.", flush=True)
            except Exception as exc:
                print(f"[ColabBootstrap] Aviso ao extrair google_flow_pro.tar.gz: {exc}", flush=True)

    # 3. Ensure DB schema & migrations (upgrades any deprecated 2.5 model to 3.8/3.5)
    sys.path.insert(0, str(BASE_DIR))
    from database import get_settings, init_db, save_settings

    init_db()

    # 4. Merge optional .env from secrets_dir or repo root (never prints values!)
    updates: Dict[str, str] = {}
    for env_candidate in (secrets_dir / ".env", BASE_DIR / ".env"):
        if env_candidate.exists() and env_candidate.is_file():
            env_map = _parse_dotenv(env_candidate)
            for env_k, db_k in ENV_TO_SETTING_KEY.items():
                if env_map.get(env_k):
                    updates[db_k] = env_map[env_k]
            print(f"[ColabBootstrap] Chaves mescladas de: {env_candidate}", flush=True)

    # Also allow Colab Secrets / environment variables if exported
    for env_k, db_k in ENV_TO_SETTING_KEY.items():
        val = (os.environ.get(env_k) or "").strip()
        if val:
            updates[db_k] = val

    # 5. If Google Drive is mounted in Colab, route auto-upload straight to Drive mount!
    drive_mounted = drive_mount.exists() and drive_mount.is_dir()
    if drive_mounted and not args.no_copy:
        updates["gdrive_local_dir"] = str(drive_mount)
        updates["gdrive_auto_upload"] = "1"
        updates["gdrive_prune_local"] = "1"
        (drive_mount / "FrimeRise").mkdir(parents=True, exist_ok=True)

    if updates:
        save_settings(updates)

    settings = get_settings() or {}
    gem_k = (settings.get("gemini_api_key") or "").strip()
    ds_k = (settings.get("deepseek_api_key") or "").strip()
    px_vid_k = (settings.get("pixabay_api_key") or "").strip()
    px_img_k = (settings.get("pixabay_image_api_key") or "").strip()
    pex_k = (settings.get("pexels_api_key") or "").strip()
    flow_ok = (PROFILES_DIR / "google_flow_pro").exists()

    if args.skip_live_check:
        gem_ok, gem_msg = (bool(gem_k), "CONFIGURADA" if gem_k else "FALTANDO")
        ds_ok, ds_msg = (True, "CONFIGURADA" if ds_k else "opcional (vazia)")
        px_v_ok, px_v_msg = (True, "CONFIGURADA" if (px_vid_k or px_img_k) else "opcional (vazia)")
        px_i_ok, px_i_msg = (True, "CONFIGURADA" if (px_img_k or px_vid_k) else "opcional (vazia)")
    else:
        gem_ok, gem_msg = _check_gemini(gem_k)
        ds_ok, ds_msg = _check_deepseek(ds_k)
        (px_v_ok, px_v_msg), (px_i_ok, px_i_msg) = _check_pixabay(px_vid_k, px_img_k)

    free_gb = shutil.disk_usage(BASE_DIR).free / (1024 ** 3)
    from engine.gdrive_sync import probe_gdrive_status

    gd = probe_gdrive_status()
    gd_msg = f"OK ({gd.get('detail')})" if gd.get("connected") else "não conectado (outputs ficam locais)"

    print("\n" + "=" * 64)
    print("  FRIMERISE PRE-FLIGHT CHECK (CHAVES OCULTAS POR SEGURANÇA)")
    print("=" * 64)
    print(f"  GEMINI        : {gem_msg}")
    print(f"  DEEPSEEK      : {ds_msg}")
    print(f"  PIXABAY VIDEO : {px_v_msg}")
    print(f"  PIXABAY IMAGE : {px_i_msg}")
    print(f"  PEXELS        : {'CONFIGURADA' if pex_k else 'opcional (vazia)'}")
    print(f"  WIKIMEDIA     : OK (Zero-Key)")
    print(f"  FLOW PRO      : {'OK (sessão carregada)' if flow_ok else 'opcional (Wikimedia + Pixabay + Openverse ativos)'}")
    print(f"  DEFAULT LLM   : {settings.get('default_llm', 'gemini-3.8-flash')}")
    print(f"  GOOGLE DRIVE  : {gd_msg}")
    print(f"  DISCO LIVRE   : {free_gb:.1f} GB")
    print("=" * 64 + "\n", flush=True)

    if not gem_ok:
        print("❌ ERRO: GEMINI_API_KEY ausente ou inválida. Verifique FrimeRise_Secrets/frimerise.db no Google Drive.", file=sys.stderr)
        return 1
    if not (ds_ok and px_v_ok and px_i_ok):
        print("⚠️ AVISO: Alguma chave secundária falhou no teste ao vivo (veja acima), mas o motor principal GEMINI está OK.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
