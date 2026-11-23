#!/usr/bin/env python3
"""
Disparo One-Shot no Google Colab via Google Colab CLI (`colab run`)
===================================================================
Como funciona:
  colab run --gpu T4 --high-mem colab_run_lemo.py -- --mode frimerise --spec data/episodio.json
  colab run --gpu T4 --high-mem colab_run_lemo.py -- --mode lemo --style caption-news --project teste_doc

Quando o script termina, o `colab run` encerra a VM GPU automaticamente
para economizar sua cota (só mantém ligada se você passar `--keep`).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def run(cmd: str | list[str], cwd: str | None = None, env: dict | None = None) -> None:
    shell = isinstance(cmd, str)
    print(f"[RUN] {cmd}")
    subprocess.run(cmd, cwd=cwd, env=env, shell=shell, check=True)


def mount_drive_if_available() -> Path:
    export_dir = Path("/content/drive/MyDrive/FrimeRise_Exports")
    try:
        from google.colab import drive  # type: ignore

        if not Path("/content/drive/MyDrive").exists():
            drive.mount("/content/drive")
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir
    except Exception as exc:
        fallback = Path("/content/exports")
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"[AVISO] Drive não montado automaticamente ({exc}); salvando em {fallback}")
        return fallback


def ensure_ffmpeg7() -> None:
    ver = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    if any(v in ver for v in ("version 4.", "version 5.", "version 6.")):
        run(
            "curl -L -s https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz "
            "| tar -xJ -C /tmp && cp /tmp/ffmpeg-*-amd64-static/ffmpeg /tmp/ffmpeg-*-amd64-static/ffprobe /usr/local/bin/"
        )


def run_frimerise(repo_url: str, spec_rel: str, output_name: str, export_dir: Path) -> None:
    repo_dir = Path("/content/frimerise-cinema-studio")
    if repo_dir.exists():
        run(["git", "-C", str(repo_dir), "pull", "origin", "main"])
    else:
        run(["git", "clone", "--depth", "1", repo_url, str(repo_dir)])

    run(["pip", "install", "-q", "pillow", "numpy"])
    engine = repo_dir / "engine" / "doc_station01_engine.py"
    local_out = Path("/content") / output_name
    cmd = ["python3", str(engine), "--no-vaapi", "--output", str(local_out)]

    if spec_rel == "demo":
        cmd.append("--demo")
    else:
        cmd += ["--spec", str(repo_dir / spec_rel)]

    run(cmd, cwd=str(repo_dir))
    dest = export_dir / output_name
    shutil.copy2(local_out, dest)
    print(f"[OK] Vídeo FrimeRise salvo em: {dest}")


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
    parser = argparse.ArgumentParser(description="Runner remoto para Google Colab CLI (encerra VM ao final)")
    parser.add_argument("--mode", choices=("frimerise", "lemo"), default="frimerise")
    parser.add_argument("--repo", default="https://github.com/sml98/frimerise-cinema-studio.git")
    parser.add_argument("--spec", default="demo", help="Caminho relativo do JSON ou 'demo' (modo frimerise)")
    parser.add_argument("--style", default="caption-news", help="Estilo do Lemo-Opuscar (modo lemo)")
    parser.add_argument("--project", default="meu_video", help="Nome do projeto")
    parser.add_argument("--output", default="render_colab.mp4", help="Nome do MP4 final")
    args = parser.parse_args()

    export_dir = mount_drive_if_available()
    if args.mode == "frimerise":
        run_frimerise(args.repo, args.spec, args.output, export_dir)
    else:
        run_lemo(args.style, args.project, export_dir)


if __name__ == "__main__":
    main()