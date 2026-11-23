"""Intel QuickSync (iHD) Hardware Encoder & Acer Aspire 5 Thermal Guardian.
- Targets /dev/dri/renderD128 with LIBVA_DRIVER_NAME=iHD
- Caps CPU threads to max(2, cpu_count - 2) and applies os.nice(10)
- Auto-pauses heavy encoding if Core i5 package temp exceeds thermal_limit_c (default 85°C)
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
SYSLIBS_DIR = BASE_DIR / "vendor" / "syslibs" / "usr" / "lib" / "x86_64-linux-gnu"
SYSLIBS_DRI = SYSLIBS_DIR / "dri"

_VAAPI_STATUS_CACHE: Optional[Dict[str, object]] = None


def get_vaapi_env() -> Dict[str, str]:
    """Build environment dict ensuring Intel iHD VAAPI driver & libmediainfo are found."""
    env = os.environ.copy()
    env["LIBVA_DRIVER_NAME"] = "iHD"
    dri_paths = [str(SYSLIBS_DRI)] if SYSLIBS_DRI.exists() else []
    if env.get("LIBVA_DRIVERS_PATH"):
        dri_paths.append(env["LIBVA_DRIVERS_PATH"])
    dri_paths.append("/usr/lib/x86_64-linux-gnu/dri")
    env["LIBVA_DRIVERS_PATH"] = ":".join(dri_paths)

    ld_paths = [str(SYSLIBS_DIR)] if SYSLIBS_DIR.exists() else []
    if env.get("LD_LIBRARY_PATH"):
        ld_paths.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(ld_paths)
    return env


def safe_thread_count() -> int:
    return max(2, (os.cpu_count() or 4) - 2)


def nice_preexec():
    try:
        os.nice(10)
    except OSError:
        pass


def read_cpu_temperature_c() -> float:
    """Read Intel Core i5 package temperature from Linux thermal sysfs."""
    temps: List[Tuple[int, float]] = []
    thermal_root = Path("/sys/class/thermal")
    if thermal_root.exists():
        for zone in thermal_root.glob("thermal_zone*"):
            try:
                ztype = (zone / "type").read_text().strip().lower()
                raw = int((zone / "temp").read_text().strip())
                c = raw / 1000.0 if raw > 200 else float(raw)
                if 15.0 <= c <= 115.0:
                    priority = 0
                    if "x86_pkg_temp" in ztype:
                        priority = 3
                    elif "tcpu" in ztype or "core" in ztype:
                        priority = 2
                    elif "acpitz" in ztype:
                        priority = 1
                    temps.append((priority, c))
            except Exception:
                continue
    if not temps:
        return 48.0
    max_prio = max(p for p, _ in temps)
    best = [c for p, c in temps if p == max_prio]
    return round(max(best), 1)


def thermal_guard_wait(limit_c: float = 85.0, cooldown_c: float = 76.0, max_wait_s: int = 90) -> float:
    """Pause if Core i5 exceeds thermal limit (>85°C) until cooled."""
    temp = read_cpu_temperature_c()
    if temp < limit_c:
        return temp
    waited = 0
    while temp >= cooldown_c and waited < max_wait_s:
        time.sleep(3)
        waited += 3
        temp = read_cpu_temperature_c()
    return temp


def probe_quicksync(force: bool = False) -> Dict[str, object]:
    """Verify real /dev/dri/renderD128 Intel iHD h264_vaapi encoding."""
    global _VAAPI_STATUS_CACHE
    if _VAAPI_STATUS_CACHE is not None and not force:
        return dict(_VAAPI_STATUS_CACHE)

    device = "/dev/dri/renderD128"
    available = False
    detail = "CPU fallback (libx264)"
    if Path(device).exists() and os.access(device, os.R_OK | os.W_OK):
        try:
            res = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=256x256:d=0.2:r=30",
                    "-vaapi_device",
                    device,
                    "-vf",
                    "format=nv12,hwupload",
                    "-c:v",
                    "h264_vaapi",
                    "-rc_mode",
                    "CQP",
                    "-qp",
                    "19",
                    "-bf",
                    "2",
                    "-profile:v",
                    "high",
                    "-f",
                    "null",
                    "-",
                ],
                env=get_vaapi_env(),
                capture_output=True,
                timeout=10,
            )
            if res.returncode == 0:
                available = True
                detail = "Intel QuickSync iHD (h264_vaapi)"
            else:
                detail = f"VAAPI indisponível: {res.stderr.decode(errors='ignore')[:80]}"
        except Exception as exc:
            detail = f"VAAPI erro: {exc}"

    _VAAPI_STATUS_CACHE = {
        "quicksync_on": available,
        "driver": "iHD" if available else "software",
        "device": device if available else "cpu",
        "detail": detail,
        "threads": safe_thread_count(),
    }
    return dict(_VAAPI_STATUS_CACHE)


def build_video_encode_args(qp: int = 19, use_vaapi: Optional[bool] = None) -> Tuple[List[str], List[str], str]:
    """Return (pre_input_args, post_filter_encode_args, hw_filter_suffix).
    Caller appends hw_filter_suffix to its video filtergraph if non-empty.
    """
    if use_vaapi is None:
        use_vaapi = bool(probe_quicksync()["quicksync_on"])

    threads = str(safe_thread_count())
    if use_vaapi:
        return (
            ["-vaapi_device", "/dev/dri/renderD128"],
            [
                "-threads",
                threads,
                "-c:v",
                "h264_vaapi",
                "-rc_mode",
                "CQP",
                "-qp",
                str(qp),
                "-bf",
                "2",
                "-profile:v",
                "high",
            ],
            "format=nv12,hwupload",
        )
    return (
        [],
        [
            "-threads",
            threads,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(qp),
            "-bf",
            "2",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
        ],
        "format=yuv420p",
    )


def run_ffmpeg_safe(cmd: List[str], thermal_limit_c: float = 85.0, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute FFmpeg with Intel VAAPI env, os.nice(10), and Core i5 Thermal Guard."""
    thermal_guard_wait(limit_c=thermal_limit_c)
    return subprocess.run(
        cmd,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
        capture_output=True,
        timeout=timeout,
        check=True,
    )
