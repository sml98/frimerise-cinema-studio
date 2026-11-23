#!/usr/bin/env python3
"""
FrimeRise + Lemo-Opuscar — Runner Remoto para Google Colab CLI (`colab run`)
============================================================================
Sobe a GPU do Google Colab, carrega automaticamente suas chaves do Google Drive
(`Meu Drive/FrimeRise_Secrets/frimerise.db` ou `.env`), baixa fotos reais da
Wikimedia Commons / Pixabay / Pexels para cada cena, renderiza na GPU e salva o
MP4 pronto em `Meu Drive/FrimeRise_Exports/`. Ao terminar, `colab run` encerra
a VM automaticamente para economizar sua cota.

Exemplos de uso:
  # 1) Episódio Station 01 com fotos reais (Wikimedia + Pixabay + Pexels):
  colab run --gpu T4 colab_run_lemo.py -- --mode frimerise --spec data/episodio.json --output episodio_gpu.mp4

  # 2) Motor completo do FrimeRise (batch_produce.py):
  colab run --gpu T4 colab_run_lemo.py -- --mode batch --extra "--queue fila_videos.json"

  # 3) Estilo do Lemo-Opuscar (Molde Fechado):
  colab run --gpu T4 colab_run_lemo.py -- --mode lemo --style caption-news --project teste_doc
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional


USER_AGENT = "FrimeRiseCinemaStudio/3.0 (ColabRunner; https://github.com/sml98/frimerise-cinema-studio)"


def run(cmd: str | list[str], cwd: str | None = None, env: dict | None = None) -> None:
    shell = isinstance(cmd, str)
    print(f"[RUN] {cmd}")
    subprocess.run(cmd, cwd=cwd, env=env, shell=shell, check=True)


def mount_drive_if_available() -> tuple[Path, Optional[Path]]:
    export_dir = Path("/content/drive/MyDrive/FrimeRise_Exports")
    secrets_dir = Path("/content/drive/MyDrive/FrimeRise_Secrets")
    try:
        from google.colab import drive  # type: ignore

        if not Path("/content/drive/MyDrive").exists():
            drive.mount("/content/drive")
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir, (secrets_dir if secrets_dir.exists() else None)
    except Exception as exc:
        fallback = Path("/content/exports")
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"[AVISO] Drive não montado automaticamente ({exc}); salvando em {fallback}")
        return fallback, None


def sync_secrets_and_load_keys(repo_dir: Path, secrets_dir: Optional[Path]) -> Dict[str, str]:
    """
    Restaura `frimerise.db` e/ou `secrets.env` de `Meu Drive/FrimeRise_Secrets/`
    para o repositório no Colab e devolve um dicionário com as chaves ativas.
    """
    keys: Dict[str, str] = {}
    tracked = ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY")

    # 1) Variáveis já injetadas via `--env` do colab run
    for k in tracked:
        if os.environ.get(k):
            keys[k] = os.environ[k]

    data_dir = repo_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_target = data_dir / "frimerise.db"

    if secrets_dir:
        db_src = secrets_dir / "frimerise.db"
        if db_src.exists():
            shutil.copy2(db_src, db_target)
            print(f"[SECRETS] frimerise.db restaurado do Google Drive -> {db_target}")

        for env_name in ("secrets.env", ".env"):
            env_src = secrets_dir / env_name
            if env_src.exists():
                for line in env_src.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v:
                        keys.setdefault(k, v)
                        os.environ.setdefault(k, v)
                print(f"[SECRETS] Variáveis carregadas de {env_src.name}")

    # 2) Lê chaves salvas dentro da tabela settings do frimerise.db (se existir)
    if db_target.exists():
        try:
            conn = sqlite3.connect(str(db_target))
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tbl in tables:
                cols = [c[1].lower() for c in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if "key" in cols and "value" in cols:
                    for k, v in cur.execute(f"SELECT key, value FROM {tbl}").fetchall():
                        if k and v and str(k).upper() in tracked:
                            keys.setdefault(str(k).upper(), str(v))
                            os.environ.setdefault(str(k).upper(), str(v))
            conn.close()
        except Exception as exc:
            print(f"[AVISO] Não foi possível ler chaves do frimerise.db: {exc}")

    # Log seguro de diagnóstico (nunca imprime o valor da chave)
    print("[SECRETS] Status das chaves no Colab:")
    for k in tracked:
        status = "OK" if keys.get(k) else "AUSENTE"
        print(f"  - {k}: {status}")
    return keys


def _http_get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_file(url: str, dest: Path, timeout: int = 25) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
        return dest.exists() and dest.stat().st_size > 10_000
    except Exception:
        return False


def fetch_image_wikimedia(query: str, dest: Path) -> bool:
    """Busca imagem em domínio público/CC na Wikimedia Commons (>= 900px)."""
    try:
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": "6",
                "gsrlimit": "5",
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": "1600",
                "format": "json",
            }
        )
        data = _http_get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            w = int(info.get("width", 0) or 0)
            url = info.get("thumburl") or info.get("url")
            if url and mime in ("image/jpeg", "image/png", "image/webp") and w >= 800:
                if _download_file(url, dest):
                    time.sleep(0.45)  # evita HTTP 429 na Wikimedia
                    return True
    except Exception as exc:
        print(f"  [Wikimedia] Falha em '{query}': {exc}")
    return False


def fetch_image_pixabay(query: str, api_key: str, dest: Path) -> bool:
    if not api_key:
        return False
    try:
        params = urllib.parse.urlencode(
            {
                "key": api_key,
                "q": query[:95],
                "image_type": "photo",
                "orientation": "horizontal",
                "per_page": "5",
                "safesearch": "true",
            }
        )
        data = _http_get_json(f"https://pixabay.com/api/?{params}")
        for hit in data.get("hits", []):
            url = hit.get("largeImageURL") or hit.get("webformatURL")
            if url and _download_file(url, dest):
                return True
    except Exception as exc:
        print(f"  [Pixabay] Falha em '{query}': {exc}")
    return False


def fetch_video_pixabay(query: str, api_key: str, dest: Path) -> bool:
    """Busca clipe MP4 na API de Vídeos do Pixabay para fundo em movimento ou vídeo-sobre-vídeo."""
    if not api_key:
        return False
    try:
        params = urllib.parse.urlencode(
            {
                "key": api_key,
                "q": query[:95],
                "video_type": "film",
                "per_page": "5",
                "safesearch": "true",
            }
        )
        data = _http_get_json(f"https://pixabay.com/api/videos/?{params}")
        for hit in data.get("hits", []):
            vids = hit.get("videos") or {}
            chosen = vids.get("medium") or vids.get("large") or vids.get("small") or {}
            url = chosen.get("url")
            if url and _download_file(url, dest, timeout=45):
                return True
    except Exception as exc:
        print(f"  [Pixabay Video] Falha em '{query}': {exc}")
    return False


def fetch_image_pexels(query: str, api_key: str, dest: Path) -> bool:
    if not api_key:
        return False
    try:
        params = urllib.parse.urlencode({"query": query[:95], "orientation": "landscape", "per_page": "5"})
        data = _http_get_json(f"https://api.pexels.com/v1/search?{params}", headers={"Authorization": api_key})
        for photo in data.get("photos", []):
            url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
            if url and _download_file(url, dest):
                return True
    except Exception as exc:
        print(f"  [Pexels] Falha em '{query}': {exc}")
    return False


def hydrate_spec_media(spec_path: Path, repo_dir: Path, keys: Dict[str, str]) -> Path:
    """
    Para cada cena sem `media_path` válido, busca imagem real automaticamente:
      1) Wikimedia Commons (histórico / domínio público)
      2) Pixabay (usando PIXABAY_API_KEY do frimerise.db)
      3) Pexels (usando PEXELS_API_KEY do frimerise.db)
    """
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    cache_dir = repo_dir / "data" / "media_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    video_friendly_styles = {"caption_news", "broadcast_news_package", "live_countdown_split", "city_symphony"}
    pixabay_key = keys.get("PIXABAY_API_KEY", "")
    pexels_key = keys.get("PEXELS_API_KEY", "")
    changed = False

    for idx, sc in enumerate(data.get("scenes", [])):
        style = sc.get("style", "")
        want_video = sc.get("media_type") == "video" or (style in video_friendly_styles and bool(pixabay_key))

        cur_media = sc.get("media_path")
        if not (cur_media and Path(cur_media).exists()):
            query = (sc.get("media_query") or sc.get("headline") or sc.get("subline") or data.get("title") or "").strip()
            if query:
                hkey = hashlib.md5(f"{idx}:{query}".encode("utf-8")).hexdigest()[:12]
                vid_dest = cache_dir / f"scene_{idx:02d}_{hkey}.mp4"
                img_dest = cache_dir / f"scene_{idx:02d}_{hkey}.jpg"

                if want_video and (vid_dest.exists() or fetch_video_pixabay(query, pixabay_key, vid_dest)):
                    print(f"[MEDIA-VIDEO] Cena {idx:02d} Pixabay MP4 -> {vid_dest.name}")
                    sc["media_path"] = str(vid_dest)
                    changed = True
                elif img_dest.exists() or (
                    fetch_image_wikimedia(query, img_dest)
                    or fetch_image_pixabay(query, pixabay_key, img_dest)
                    or fetch_image_pexels(query, pexels_key, img_dest)
                ):
                    print(f"[MEDIA-IMG] Cena {idx:02d} -> {img_dest.name}")
                    sc["media_path"] = str(img_dest)
                    changed = True

        # Vídeo secundário (vídeo-sobre-vídeo / split-screen / PiP)
        sec_query = (sc.get("secondary_query") or (sc.get("subline") if style == "live_countdown_split" else "")).strip()
        if sec_query and pixabay_key and not sc.get("secondary_media"):
            shkey = hashlib.md5(f"sec:{idx}:{sec_query}".encode("utf-8")).hexdigest()[:12]
            sec_dest = cache_dir / f"scene_{idx:02d}_pip_{shkey}.mp4"
            if sec_dest.exists() or fetch_video_pixabay(sec_query, pixabay_key, sec_dest):
                print(f"[MEDIA-PIP] Cena {idx:02d} Vídeo-sobre-Vídeo -> {sec_dest.name}")
                sc["secondary_media"] = [str(sec_dest)]
                changed = True

    if not changed:
        return spec_path

    hydrated_path = spec_path.with_name(spec_path.stem + "_hydrated.json")
    hydrated_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return hydrated_path


NARRATION_VOICE = "Charon"
NARRATION_ACTING = (
    "Narre em português do Brasil com voz grave, investigativa e ritmo de documentário. "
    "Pausas curtas entre as frases, sem entonação publicitária e sem CTA."
)


def probe_audio_duration_s(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(out.strip())


def build_narration_track(repo_dir: Path, spec_path: Path, keys: Dict[str, str]) -> Optional[Path]:
    """
    Sintetiza a narração cena a cena com Gemini TTS e monta uma trilha contínua.
    Cada trecho é ajustado à duração EXATA da cena (`atempo` até 1.20x + `apad` + `atrim`),
    para o áudio nunca dessincronizar dos cards de fact-check.

    Retorna None (render segue sem áudio) quando o spec não tem `narration` ou a chave falta.
    """
    api_key = keys.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[NARR] GEMINI_API_KEY ausente — render segue sem narração")
        return None

    data = json.loads(spec_path.read_text(encoding="utf-8"))
    scenes = data.get("scenes", [])
    if not any(str(sc.get("narration", "")).strip() for sc in scenes):
        return None

    import sys

    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    run(["pip", "install", "-q", "httpx"])

    from engine.gemini_tts import normalize_narration_for_speech, synthesize_gemini_tts_line

    work_dir = Path("/content/narration")
    work_dir.mkdir(parents=True, exist_ok=True)
    silence = f"anullsrc=r=48000:cl=mono"
    segments: list[Path] = []

    for idx, sc in enumerate(scenes):
        scene_dur = float(sc.get("duration", 3.0))
        text = str(sc.get("narration", "")).strip()
        fitted = work_dir / f"seg_{idx:02d}.wav"

        if not text:
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", silence,
                 "-t", f"{scene_dur:.3f}", "-c:a", "pcm_s16le", str(fitted)])
            segments.append(fitted)
            continue

        raw = work_dir / f"seg_{idx:02d}_raw.wav"
        spoken = normalize_narration_for_speech(text, "pt_br")
        _, spoken_dur = synthesize_gemini_tts_line(
            spoken,
            raw,
            voice_name=NARRATION_VOICE,
            acting_direction=NARRATION_ACTING,
            api_key=api_key,
            lang="pt_br",
        )

        tempo = 1.0
        if spoken_dur > 0.1 and spoken_dur > scene_dur:
            tempo = min(1.20, max(1.0, spoken_dur / scene_dur))
        filters = []
        if tempo > 1.001:
            filters.append(f"atempo={tempo:.4f}")
        filters.append(f"apad=whole_dur={scene_dur:.3f}")
        filters.append(f"atrim=0:{scene_dur:.3f}")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", ",".join(filters),
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(fitted)])
        print(f"[NARR] cena {idx:02d}: {spoken_dur:.2f}s -> {scene_dur:.2f}s (tempo {tempo:.2f}x)")
        segments.append(fitted)

    listing = work_dir / "segments.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in segments), encoding="utf-8")
    track = work_dir / "narracao.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c:a", "pcm_s16le", str(track)])
    print(f"[NARR] trilha contínua -> {track} ({probe_audio_duration_s(track):.1f}s)")
    return track


def ensure_ffmpeg7() -> None:
    ver = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    if any(v in ver for v in ("version 4.", "version 5.", "version 6.")):
        run(
            "curl -L -s https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz "
            "| tar -xJ -C /tmp && cp /tmp/ffmpeg-*-amd64-static/ffmpeg /tmp/ffmpeg-*-amd64-static/ffprobe /usr/local/bin/"
        )


def prepare_frimerise_repo(repo_url: str, secrets_dir: Optional[Path]) -> tuple[Path, Dict[str, str]]:
    repo_dir = Path("/content/frimerise-cinema-studio")
    if repo_dir.exists():
        run(["git", "-C", str(repo_dir), "pull", "origin", "main"])
    else:
        run(["git", "clone", "--depth", "1", repo_url, str(repo_dir)])
    keys = sync_secrets_and_load_keys(repo_dir, secrets_dir)
    return repo_dir, keys


def run_frimerise(repo_url: str, spec_rel: str, output_name: str, export_dir: Path, secrets_dir: Optional[Path], fetch_media: bool) -> None:
    repo_dir, keys = prepare_frimerise_repo(repo_url, secrets_dir)
    run(["pip", "install", "-q", "pillow", "numpy"])
    engine = repo_dir / "engine" / "doc_station01_engine.py"
    local_out = Path("/content") / output_name
    cmd = ["python3", str(engine), "--output", str(local_out)]

    if spec_rel == "demo":
        cmd.append("--demo")
    else:
        spec_path = repo_dir / spec_rel
        if fetch_media:
            spec_path = hydrate_spec_media(spec_path, repo_dir, keys)
        try:
            narration = build_narration_track(repo_dir, spec_path, keys)
        except Exception as exc:  # nunca derruba o render por falha de TTS
            narration = None
            print(f"[NARR] desativada ({exc.__class__.__name__}: {exc}) — render segue sem áudio")
        if narration:
            cmd += ["--audio", str(narration)]
        cmd += ["--spec", str(spec_path)]

    run(cmd, cwd=str(repo_dir))
    dest = export_dir / output_name
    shutil.copy2(local_out, dest)
    print(f"[OK] Vídeo FrimeRise salvo em: {dest}")


def run_batch(repo_url: str, extra_args: str, export_dir: Path, secrets_dir: Optional[Path]) -> None:
    """Executa o `batch_produce.py` completo do FrimeRise na GPU do Colab."""
    repo_dir, _ = prepare_frimerise_repo(repo_url, secrets_dir)
    run(["pip", "install", "-q", "-r", str(repo_dir / "requirements.txt")])
    cmd = ["python3", str(repo_dir / "batch_produce.py")] + shlex.split(extra_args)
    run(cmd, cwd=str(repo_dir))
    for mp4 in sorted((repo_dir / "outputs").rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        shutil.copy2(mp4, export_dir / mp4.name)
        print(f"[OK] Exportado para o Drive: {export_dir / mp4.name}")


def run_lemo(style: str, project: str, export_dir: Path) -> None:
    ensure_ffmpeg7()
    lemo_dir = Path("/content/lemo-opuscar")
    if not lemo_dir.exists():
        run(["git", "clone", "--depth", "1", "https://github.com/lemomo-ai/lemo-opuscar.git", str(lemo_dir)])

    setup_sh = lemo_dir / "plugin" / "skills" / "lemo-opuscar" / "scripts" / "setup.sh"
    if setup_sh.exists():
        run(["sh", str(setup_sh), "deps", "voice"], cwd=str(lemo_dir))

    src_demo = lemo_dir / "styles" / style / "demo"
    dst_film = lemo_dir / "films" / project
    if not dst_film.exists():
        shutil.copytree(src_demo, dst_film)

    env = os.environ.copy()
    env["LIB"] = str(lemo_dir)
    run(["bash", str(dst_film / "build.sh")], cwd=str(dst_film), env=env)

    mp4s = sorted(dst_film.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        raise RuntimeError("Nenhum .mp4 gerado pelo build.sh")
    dest = export_dir / f"{project}_{style}.mp4"
    shutil.copy2(mp4s[0], dest)
    print(f"[OK] Vídeo Lemo-Opuscar salvo em: {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Runner remoto GPU para Google Colab CLI (encerra VM ao final)")
    parser.add_argument("--mode", choices=("frimerise", "batch", "lemo"), default="frimerise")
    parser.add_argument("--repo", default="https://github.com/sml98/frimerise-cinema-studio.git")
    parser.add_argument("--spec", default="demo", help="Caminho relativo do JSON ou 'demo' (modo frimerise)")
    parser.add_argument("--no-fetch-media", action="store_true", help="Não baixa fotos externas (usa só fundos locais)")
    parser.add_argument("--extra", default="", help="Argumentos extras para batch_produce.py (modo batch)")
    parser.add_argument("--style", default="caption-news", help="Estilo do Lemo-Opuscar (modo lemo)")
    parser.add_argument("--project", default="meu_video", help="Nome do projeto")
    parser.add_argument("--output", default="render_colab.mp4", help="Nome do MP4 final")
    args = parser.parse_args()

    export_dir, secrets_dir = mount_drive_if_available()
    if args.mode == "frimerise":
        run_frimerise(args.repo, args.spec, args.output, export_dir, secrets_dir, fetch_media=not args.no_fetch_media)
    elif args.mode == "batch":
        run_batch(args.repo, args.extra, export_dir, secrets_dir)
    else:
        run_lemo(args.style, args.project, export_dir)


if __name__ == "__main__":
    main()