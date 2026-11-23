#!/usr/bin/env python3
"""FrimeRise Phase 2 Asset Auto-Provisioner.
Generates brand logo (Skia 512x512 PNG + SVG), downloads Google Fonts (OFL),
mathematically synthesizes 6 33x33x33 3D LUTs (.cube), 12 broadcast 48kHz WAV SFX,
4 loopable MP3 music beds, 2 transparent 9:16 overlays, and seeds data/frimerise.db.
100% permissive libraries (skia-python, numpy, scipy, httpx, ffmpeg).
"""
from __future__ import annotations

import math
import subprocess
import sys
import wave
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import httpx
import numpy as np
from scipy import signal
import skia

from database import init_db

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
BRAND_DIR = ASSETS_DIR / "brand"
FONTS_DIR = ASSETS_DIR / "fonts"
LUTS_DIR = ASSETS_DIR / "luts"
SFX_DIR = ASSETS_DIR / "sfx"
MUSIC_DIR = ASSETS_DIR / "music"
OVERLAYS_DIR = ASSETS_DIR / "overlays"

SAMPLE_RATE = 48000


def ensure_dirs() -> None:
    for d in (BRAND_DIR, FONTS_DIR, LUTS_DIR, SFX_DIR, MUSIC_DIR, OVERLAYS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Official FrimeRise Logo (512x512 Skia PNG + Crisp SVG)
# ---------------------------------------------------------------------------
def generate_brand_logo() -> None:
    png_path = BRAND_DIR / "frimerise_logo.png"
    svg_path = BRAND_DIR / "frimerise_logo.svg"

    size = 512
    surface = skia.Surface(size, size)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0, 0, 0, 0))

    # Rounded Obsidian Violet squircle background
    bg_rect = skia.Rect.MakeXYWH(18, 18, size - 36, size - 36)
    rrect = skia.RRect.MakeRectXY(bg_rect, 112, 112)

    bg_paint = skia.Paint(AntiAlias=True)
    bg_paint.setShader(
        skia.GradientShader.MakeLinear(
            points=[(18, 18), (size - 18, size - 18)],
            colors=[
                skia.ColorSetARGB(255, 22, 13, 42),
                skia.ColorSetARGB(255, 11, 7, 19),
            ],
        )
    )
    canvas.drawRRect(rrect, bg_paint)

    # Ambient cyber-luxury glow orbs clipped inside squircle
    canvas.save()
    canvas.clipRRect(rrect, doAntiAlias=True)

    orb1 = skia.Paint(AntiAlias=True)
    orb1.setShader(
        skia.GradientShader.MakeRadial(
            center=(120, 120),
            radius=240,
            colors=[skia.ColorSetARGB(120, 255, 46, 147), skia.ColorSetARGB(0, 255, 46, 147)],
        )
    )
    canvas.drawCircle(120, 120, 240, orb1)

    orb2 = skia.Paint(AntiAlias=True)
    orb2.setShader(
        skia.GradientShader.MakeRadial(
            center=(410, 400),
            radius=230,
            colors=[skia.ColorSetARGB(110, 179, 136, 255), skia.ColorSetARGB(0, 179, 136, 255)],
        )
    )
    canvas.drawCircle(410, 400, 230, orb2)
    canvas.restore()

    # Outer luminous Rosa -> Lilas border
    border_paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=8)
    border_paint.setShader(
        skia.GradientShader.MakeLinear(
            points=[(24, 24), (488, 488)],
            colors=[
                skia.ColorSetARGB(255, 255, 46, 147),   # #FF2E93 Rosa Frime
                skia.ColorSetARGB(255, 179, 136, 255),  # #B388FF Lilas
                skia.ColorSetARGB(255, 184, 255, 1),    # #B8FF01 Verde Lima
            ],
            positions=[0.0, 0.58, 1.0],
        )
    )
    canvas.drawRRect(rrect, border_paint)

    # Stylized rising "F" + Play Prism emblem
    f_path = skia.Path()
    f_path.moveTo(148, 376)
    f_path.lineTo(148, 132)
    f_path.lineTo(356, 132)
    f_path.lineTo(334, 192)
    f_path.lineTo(212, 192)
    f_path.lineTo(212, 238)
    f_path.lineTo(318, 238)
    f_path.lineTo(298, 294)
    f_path.lineTo(212, 294)
    f_path.lineTo(212, 376)
    f_path.close()

    f_paint = skia.Paint(AntiAlias=True)
    f_paint.setShader(
        skia.GradientShader.MakeLinear(
            points=[(148, 132), (356, 376)],
            colors=[
                skia.ColorSetARGB(255, 255, 46, 147),
                skia.ColorSetARGB(255, 179, 136, 255),
            ],
        )
    )
    f_paint.setImageFilter(
        skia.ImageFilters.DropShadow(0, 8, 18, 18, skia.ColorSetARGB(140, 255, 46, 147))
    )
    canvas.drawPath(f_path, f_paint)

    # Rising Lime Green Play-Arrow Bolt (signifying "Rise" + Video Render)
    bolt = skia.Path()
    bolt.moveTo(268, 376)
    bolt.lineTo(384, 294)
    bolt.lineTo(334, 294)
    bolt.lineTo(376, 224)
    bolt.lineTo(312, 266)
    bolt.lineTo(342, 266)
    bolt.close()

    # Clean Play Triangle + Rise Arrow in Lime Green (#B8FF01)
    play_arrow = skia.Path()
    play_arrow.moveTo(264, 372)
    play_arrow.lineTo(264, 314)
    play_arrow.lineTo(378, 314)
    play_arrow.lineTo(328, 372)
    play_arrow.close()

    rise_tri = skia.Path()
    rise_tri.moveTo(298, 376)
    rise_tri.lineTo(376, 296)
    rise_tri.lineTo(376, 376)
    rise_tri.close()

    lime_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 184, 255, 1))
    lime_paint.setImageFilter(
        skia.ImageFilters.DropShadow(0, 4, 14, 14, skia.ColorSetARGB(150, 184, 255, 1))
    )
    canvas.drawPath(rise_tri, lime_paint)

    # Golden Crown Spark (#FFD166) at top-right of F
    star = skia.Path()
    cx, cy = 376, 146
    for i in range(8):
        angle = i * math.pi / 4.0
        r = 34 if i % 2 == 0 else 12
        px = cx + r * math.cos(angle)
        py = cy + r * math.sin(angle)
        if i == 0:
            star.moveTo(px, py)
        else:
            star.lineTo(px, py)
    star.close()

    gold_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102))
    gold_paint.setImageFilter(
        skia.ImageFilters.DropShadow(0, 0, 12, 12, skia.ColorSetARGB(190, 255, 209, 102))
    )
    canvas.drawPath(star, gold_paint)

    image = surface.makeImageSnapshot()
    image.save(str(png_path), skia.kPNG)

    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#160D2A"/>
      <stop offset="100%" stop-color="#0B0713"/>
    </linearGradient>
    <linearGradient id="brand" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF2E93"/>
      <stop offset="100%" stop-color="#B388FF"/>
    </linearGradient>
    <linearGradient id="border" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF2E93"/>
      <stop offset="58%" stop-color="#B388FF"/>
      <stop offset="100%" stop-color="#B8FF01"/>
    </linearGradient>
  </defs>
  <rect x="18" y="18" width="476" height="476" rx="112" fill="url(#bg)" stroke="url(#border)" stroke-width="8"/>
  <path d="M148 376 L148 132 L356 132 L334 192 L212 192 L212 238 L318 238 L298 294 L212 294 L212 376 Z" fill="url(#brand)"/>
  <polygon points="298,376 376,296 376,376" fill="#B8FF01"/>
  <polygon points="376,112 384,138 410,146 384,154 376,180 368,154 342,146 368,138" fill="#FFD166"/>
</svg>
"""
    svg_path.write_text(svg_content, encoding="utf-8")
    print(f"[Brand] Logo PNG (512x512) & SVG gerados em {BRAND_DIR}")


# ---------------------------------------------------------------------------
# 2. Google Fonts (OFL Commercial Free)
# ---------------------------------------------------------------------------
FONT_SOURCES: Dict[str, List[str]] = {
    "Anton-Regular.ttf": [
        "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    ],
    "Montserrat-Black.ttf": [
        "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Black.ttf",
    ],
    "Montserrat-ExtraBold.ttf": [
        "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-ExtraBold.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-ExtraBold.ttf",
    ],
    "BebasNeue-Regular.ttf": [
        "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    ],
    "PlusJakartaSans-ExtraBold.ttf": [
        "https://raw.githubusercontent.com/google/fonts/main/ofl/plusjakartasans/static/PlusJakartaSans-ExtraBold.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf",
    ],
}


def download_fonts() -> None:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    target_weights = {
        "Montserrat-Black.ttf": 900,
        "Montserrat-ExtraBold.ttf": 800,
        "PlusJakartaSans-ExtraBold.ttf": 800,
    }

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for filename, urls in FONT_SOURCES.items():
            dest = FONTS_DIR / filename
            need_dl = not (dest.exists() and dest.stat().st_size > 40_000)
            if not need_dl and filename in target_weights:
                tf = skia.Typeface.MakeFromFile(str(dest))
                if tf is None or tf.fontStyle().weight() < target_weights[filename] - 100:
                    need_dl = True

            if not need_dl:
                print(f"[Fonts] OK (cached): {filename}")
                continue
            ok = False
            for url in urls:
                try:
                    resp = client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 20_000:
                        dest.write_bytes(resp.content)
                        if filename in target_weights:
                            tt = TTFont(str(dest))
                            if "fvar" in tt:
                                inst = instantiateVariableFont(tt, {"wght": target_weights[filename]})
                                inst.save(str(dest))
                        tf = skia.Typeface.MakeFromFile(str(dest))
                        w_val = tf.fontStyle().weight() if tf else 0
                        print(f"[Fonts] Baixado: {filename} ({dest.stat().st_size//1024} KB, weight={w_val})")
                        ok = True
                        break
                except Exception as exc:
                    print(f"[Fonts] Aviso tentando {url}: {exc}")
            if not ok:
                sys_fonts = list(Path("/usr/share/fonts").rglob("*.ttf"))
                if sys_fonts:
                    dest.write_bytes(sys_fonts[0].read_bytes())
                    print(f"[Fonts] Fallback local aplicado para {filename}")


# ---------------------------------------------------------------------------
# 3. 6 Mathematical 33x33x33 3D LUTs (.cube) in NumPy
# ---------------------------------------------------------------------------
def _s_curve(x: np.ndarray, strength: float) -> np.ndarray:
    return np.clip(x + strength * np.sin(2.0 * np.pi * x) * (-0.5 / np.pi), 0.0, 1.0)


def _write_cube_lut(path: Path, title: str, transform: Callable[[np.ndarray, np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray, np.ndarray]], size: int = 33) -> None:
    grid = np.linspace(0.0, 1.0, size, dtype=np.float64)
    # Standard .cube order: R varies fastest, then G, then B
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")
    rf, gf, bf = transform(r.ravel(), g.ravel(), b.ravel())
    rf = np.clip(rf, 0.0, 1.0)
    gf = np.clip(gf, 0.0, 1.0)
    bf = np.clip(bf, 0.0, 1.0)

    lines = [
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    data = np.column_stack([rf, gf, bf])
    lines.extend(f"{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}" for row in data)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def generate_luts() -> None:
    def lut_frimerise(r, g, b):
        # Soft violet shadows + warm golden highlights + modern contrast
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sh = np.clip(1.0 - luma * 1.6, 0.0, 1.0) ** 2
        hi = np.clip((luma - 0.45) * 1.8, 0.0, 1.0) ** 1.6
        r2 = _s_curve(r, 0.22) + 0.045 * sh + 0.055 * hi
        g2 = _s_curve(g, 0.20) - 0.015 * sh + 0.032 * hi
        b2 = _s_curve(b, 0.22) + 0.085 * sh - 0.025 * hi
        return r2, g2, b2

    def lut_dark_wealth(r, g, b):
        # Deep cool crushed shadows + rich metallic gold highlights
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sh = np.clip(1.0 - luma * 1.8, 0.0, 1.0) ** 2
        hi = np.clip((luma - 0.5) * 2.0, 0.0, 1.0) ** 1.5
        sat = 0.90
        r2 = luma + (r - luma) * sat
        g2 = luma + (g - luma) * sat
        b2 = luma + (b - luma) * sat
        r2 = _s_curve(r2, 0.30) - 0.02 * sh + 0.075 * hi
        g2 = _s_curve(g2, 0.30) - 0.01 * sh + 0.048 * hi
        b2 = _s_curve(b2, 0.28) + 0.045 * sh - 0.045 * hi
        return r2, g2, b2

    def lut_teal_orange(r, g, b):
        # Classic cinema teal shadows + warm orange skin/highlights
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sh = np.clip(1.0 - luma * 1.7, 0.0, 1.0) ** 1.8
        hi = np.clip((luma - 0.35) * 1.5, 0.0, 1.0) ** 1.4
        r2 = _s_curve(r, 0.26) - 0.05 * sh + 0.085 * hi
        g2 = _s_curve(g, 0.24) + 0.035 * sh + 0.020 * hi
        b2 = _s_curve(b, 0.24) + 0.080 * sh - 0.070 * hi
        return r2, g2, b2

    def lut_crisp_commercial(r, g, b):
        # Clean whites + punchy saturation for clinics/stores/ads
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sat = 1.16
        r2 = luma + (r - luma) * sat
        g2 = luma + (g - luma) * sat
        b2 = luma + (b - luma) * sat
        r2 = _s_curve(np.clip(r2 * 1.03, 0, 1), 0.14)
        g2 = _s_curve(np.clip(g2 * 1.03, 0, 1), 0.14)
        b2 = _s_curve(np.clip(b2 * 1.04, 0, 1), 0.14)
        return r2, g2, b2

    def lut_cyber_neon(r, g, b):
        # Tech neon pink/lilac highlights & deep obsidian shadow
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sh = np.clip(1.0 - luma * 1.6, 0.0, 1.0) ** 1.8
        hi = np.clip((luma - 0.4) * 1.6, 0.0, 1.0) ** 1.4
        r2 = _s_curve(r, 0.32) + 0.03 * sh + 0.09 * hi
        g2 = _s_curve(g, 0.28) - 0.03 * sh - 0.02 * hi
        b2 = _s_curve(b, 0.30) + 0.10 * sh + 0.07 * hi
        return r2, g2, b2

    def lut_warm_storytime(r, g, b):
        # Cozy warm midtones & gentle filmic rolloff
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        mid = np.sin(np.pi * luma)
        r2 = _s_curve(r, 0.16) + 0.055 * mid + 0.02
        g2 = _s_curve(g, 0.16) + 0.022 * mid + 0.01
        b2 = _s_curve(b, 0.16) - 0.045 * mid
        return r2, g2, b2

    specs = [
        ("01_frimerise_signature.cube", "FrimeRise Signature", lut_frimerise),
        ("02_dark_wealth.cube", "Dark Wealth", lut_dark_wealth),
        ("03_teal_orange_cinema.cube", "Teal Orange Cinema", lut_teal_orange),
        ("04_crisp_commercial.cube", "Crisp Commercial", lut_crisp_commercial),
        ("05_cyber_neon.cube", "Cyber Neon", lut_cyber_neon),
        ("06_warm_storytime.cube", "Warm Storytime", lut_warm_storytime),
    ]
    for fname, title, fn in specs:
        dest = LUTS_DIR / fname
        _write_cube_lut(dest, title, fn, size=33)
        print(f"[LUT] Gerado 33x33x33: {fname}")


# ---------------------------------------------------------------------------
# 4. 12 Crystal-Clear 48kHz WAV SFX + 4 Loopable MP3 Music Tracks
# ---------------------------------------------------------------------------
def _save_wav(path: Path, samples: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    if samples.ndim == 1:
        stereo = np.column_stack([samples, samples])
    else:
        stereo = samples
    peak = np.max(np.abs(stereo)) + 1e-9
    norm = np.clip(stereo / peak * 0.88, -1.0, 1.0)
    pcm = (norm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    na = max(1, int(n * a))
    nd = max(1, int(n * d))
    nr = max(1, int(n * r))
    ns = max(0, n - na - nd - nr)
    env = np.concatenate([
        np.linspace(0.0, 1.0, na, endpoint=False),
        np.linspace(1.0, s, nd, endpoint=False),
        np.full(ns, s),
        np.linspace(s, 0.0, nr),
    ])
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env[:n]


def _bandpass(x: np.ndarray, low: float, high: float, sr: int = SAMPLE_RATE, order: int = 3) -> np.ndarray:
    nyq = 0.5 * sr
    sos = signal.butter(order, [max(20.0, low) / nyq, min(nyq - 100.0, high) / nyq], btype="band", output="sos")
    return signal.sosfilt(sos, x)


def generate_sfx() -> None:
    rng = np.random.default_rng(42)

    # 1. whoosh_fast.wav (0.45s resonant filtered noise sweep)
    t = np.linspace(0, 0.45, int(SAMPLE_RATE * 0.45), endpoint=False)
    noise = rng.standard_normal(len(t))
    w1 = _bandpass(noise, 350, 2200) * _adsr(len(t), 0.25, 0.25, 0.35, 0.45)
    w2 = _bandpass(noise, 1200, 6500) * np.sin(np.pi * t / 0.45) ** 2
    _save_wav(SFX_DIR / "whoosh_fast.wav", w1 * 0.7 + w2 * 0.6)

    # 2. whoosh_deep.wav (0.85s cinematic low whoosh)
    t = np.linspace(0, 0.85, int(SAMPLE_RATE * 0.85), endpoint=False)
    noise = rng.standard_normal(len(t))
    sub = np.sin(2 * np.pi * (95 - 55 * (t / 0.85)) * t)
    deep = _bandpass(noise, 120, 900) * (np.sin(np.pi * t / 0.85) ** 1.6) + sub * 0.55 * _adsr(len(t), 0.3, 0.2, 0.4, 0.5)
    _save_wav(SFX_DIR / "whoosh_deep.wav", deep)

    # 3. pop_bubble.wav (0.16s snappy upward pitch pop)
    t = np.linspace(0, 0.16, int(SAMPLE_RATE * 0.16), endpoint=False)
    f_pop = 260 * np.exp(12.0 * t)
    phase = 2 * np.pi * np.cumsum(f_pop) / SAMPLE_RATE
    pop = np.sin(phase) * np.exp(-26 * t) * _adsr(len(t), 0.04, 0.2, 0.2, 0.76)
    _save_wav(SFX_DIR / "pop_bubble.wav", pop)

    # 4. sub_boom.wav (1.4s 808 cinematic impact drop)
    t = np.linspace(0, 1.4, int(SAMPLE_RATE * 1.4), endpoint=False)
    freq = 120 * np.exp(-4.5 * t) + 34
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    boom = np.tanh(1.8 * np.sin(phase)) * np.exp(-2.6 * t) + _bandpass(rng.standard_normal(len(t)), 60, 450) * np.exp(-16 * t) * 0.5
    _save_wav(SFX_DIR / "sub_boom.wav", boom)

    # 5. riser_tension.wav (2.0s escalating synth + filtered noise)
    t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2.0), endpoint=False)
    frac = t / 2.0
    f_rise = 110 * (2 ** (3.2 * frac))
    phase = 2 * np.pi * np.cumsum(f_rise) / SAMPLE_RATE
    riser = (0.5 * np.sin(phase) + 0.25 * signal.sawtooth(phase * 0.5)) * (frac ** 2.1)
    riser += _bandpass(rng.standard_normal(len(t)), 600, 7000) * (frac ** 2.6) * 0.45
    riser *= np.clip((2.0 - t) / 0.08, 0.0, 1.0)
    _save_wav(SFX_DIR / "riser_tension.wav", riser)

    # 6. cash_chime.wav (0.9s metallic bell chord for financial metrics)
    t = np.linspace(0, 0.9, int(SAMPLE_RATE * 0.9), endpoint=False)
    chime = (
        np.sin(2 * np.pi * 1567.98 * t) * np.exp(-5.0 * t)
        + 0.8 * np.sin(2 * np.pi * 2093.00 * t) * np.exp(-4.0 * np.maximum(0, t - 0.06)) * (t >= 0.06)
        + 0.6 * np.sin(2 * np.pi * 3135.96 * t) * np.exp(-6.5 * np.maximum(0, t - 0.11)) * (t >= 0.11)
        + 0.3 * np.sin(2 * np.pi * 4186.00 * t) * np.exp(-8.0 * t)
    )
    _save_wav(SFX_DIR / "cash_chime.wav", chime)

    # 7. camera_shutter.wav (0.22s crisp mechanical dual-click)
    t = np.linspace(0, 0.22, int(SAMPLE_RATE * 0.22), endpoint=False)
    n1 = _bandpass(rng.standard_normal(len(t)), 1500, 9000) * np.exp(-85 * t)
    t2 = np.maximum(0, t - 0.075)
    n2 = _bandpass(rng.standard_normal(len(t)), 1200, 7500) * np.exp(-95 * t2) * (t >= 0.075)
    _save_wav(SFX_DIR / "camera_shutter.wav", n1 + 0.85 * n2)

    # 8. glitch_digital.wav (0.35s bitcrushed stutter)
    t = np.linspace(0, 0.35, int(SAMPLE_RATE * 0.35), endpoint=False)
    carrier = signal.square(2 * np.pi * (420 + 900 * np.sin(2 * np.pi * 28 * t)) * t)
    gate = (np.sin(2 * np.pi * 38 * t) > 0).astype(np.float64)
    glitch = np.round((carrier * gate + 0.3 * rng.standard_normal(len(t))) * 4) / 4
    glitch *= _adsr(len(t), 0.02, 0.2, 0.6, 0.2)
    _save_wav(SFX_DIR / "glitch_digital.wav", glitch)

    # 9. ui_click.wav (0.08s tactile glass click)
    t = np.linspace(0, 0.08, int(SAMPLE_RATE * 0.08), endpoint=False)
    click = np.sin(2 * np.pi * 1850 * t) * np.exp(-90 * t) + 0.4 * np.sin(2 * np.pi * 3700 * t) * np.exp(-120 * t)
    _save_wav(SFX_DIR / "ui_click.wav", click)

    # 10. heartbeat.wav (0.95s lub-dub tension pulse)
    t = np.linspace(0, 0.95, int(SAMPLE_RATE * 0.95), endpoint=False)
    lub = np.sin(2 * np.pi * (62 * np.exp(-4 * t) + 32) * t) * np.exp(-12 * t)
    td = np.maximum(0, t - 0.24)
    dub = np.sin(2 * np.pi * (54 * np.exp(-4 * td) + 28) * td) * np.exp(-15 * td) * (t >= 0.24)
    _save_wav(SFX_DIR / "heartbeat.wav", lub + 0.8 * dub)

    # 11. cinematic_hit.wav (1.6s trailer brass + sub slam)
    t = np.linspace(0, 1.6, int(SAMPLE_RATE * 1.6), endpoint=False)
    brass = sum(np.sin(2 * np.pi * f * t) for f in (65.41, 130.81, 196.0, 261.63)) / 4.0
    slam = np.tanh(2.2 * brass) * np.exp(-2.2 * t) + _bandpass(rng.standard_normal(len(t)), 250, 3200) * np.exp(-10 * t) * 0.7
    _save_wav(SFX_DIR / "cinematic_hit.wav", slam)

    # 12. typing_tick.wav (0.06s mechanical keycap tick)
    t = np.linspace(0, 0.06, int(SAMPLE_RATE * 0.06), endpoint=False)
    tick = _bandpass(rng.standard_normal(len(t)), 2200, 11000) * np.exp(-130 * t) + 0.5 * np.sin(2 * np.pi * 920 * t) * np.exp(-110 * t)
    _save_wav(SFX_DIR / "typing_tick.wav", tick)

    print(f"[SFX] 12 arquivos WAV 48kHz sintetizados em {SFX_DIR}")


def _synthesize_music_track(
    mp3_path: Path,
    bpm: float,
    chords: List[List[float]],
    bass_notes: List[float],
    style: str,
    bars: int = 8,
) -> None:
    beat_s = 60.0 / bpm
    bar_s = beat_s * 4.0
    total_s = bar_s * bars
    n = int(total_s * SAMPLE_RATE)
    t = np.linspace(0, total_s, n, endpoint=False)

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)

    bar_samples = int(bar_s * SAMPLE_RATE)
    beat_samples = int(beat_s * SAMPLE_RATE)

    for b_idx in range(bars):
        start = b_idx * bar_samples
        end = min(n, start + bar_samples)
        seg_t = np.linspace(0, (end - start) / SAMPLE_RATE, end - start, endpoint=False)
        chord = chords[b_idx % len(chords)]
        bass_f = bass_notes[b_idx % len(bass_notes)]

        # Warm stereo pad
        pad_l = np.zeros_like(seg_t)
        pad_r = np.zeros_like(seg_t)
        for i, freq in enumerate(chord):
            detune = 1.0 + (0.0022 if i % 2 == 0 else -0.0022)
            pad_l += np.sin(2 * np.pi * freq * seg_t) * 0.16
            pad_r += np.sin(2 * np.pi * freq * detune * seg_t) * 0.16
            if style in ("dark_pulse", "epic_doc"):
                pad_l += np.sin(2 * np.pi * (freq * 0.5) * seg_t) * 0.08
                pad_r += np.sin(2 * np.pi * (freq * 0.5) * seg_t) * 0.08
        pad_env = np.minimum(1.0, seg_t / 0.18) * np.minimum(1.0, (seg_t[-1] - seg_t + 1e-4) / 0.18)
        left[start:end] += pad_l * pad_env
        right[start:end] += pad_r * pad_env

        # Sub bass pulse
        if style == "dark_pulse":
            pulse = 0.5 + 0.5 * np.sin(2 * np.pi * (bpm / 60.0) * 2.0 * seg_t)
            bass = np.tanh(1.5 * np.sin(2 * np.pi * bass_f * seg_t)) * 0.28 * pulse
        elif style == "corporate_focus":
            arp_idx = (seg_t / (beat_s / 2.0)).astype(int) % len(chord)
            arp_freq = np.array([chord[k] * 2.0 for k in arp_idx])
            arp_phase = 2 * np.pi * np.cumsum(arp_freq) / SAMPLE_RATE
            arp_env = np.exp(-6.0 * (seg_t % (beat_s / 2.0)))
            arp = np.sin(arp_phase) * arp_env * 0.14
            left[start:end] += arp
            right[start:end] += arp * 0.9
            bass = np.sin(2 * np.pi * bass_f * seg_t) * 0.22
        elif style == "lo_fi_study":
            wobble = 1.0 + 0.003 * np.sin(2 * np.pi * 1.6 * seg_t)
            bass = np.sin(2 * np.pi * bass_f * wobble * seg_t) * 0.20 * np.exp(-0.5 * (seg_t % beat_s))
        else:  # epic_doc
            sw = 0.65 + 0.35 * np.sin(np.pi * seg_t / bar_s)
            bass = np.tanh(1.6 * np.sin(2 * np.pi * bass_f * seg_t)) * 0.30 * sw

        left[start:end] += bass
        right[start:end] += bass

    # Subtle percussive pulse on beats
    rng = np.random.default_rng(100 + len(style))
    total_beats = int(bars * 4)
    for bt in range(total_beats):
        pos = bt * beat_samples
        k_len = min(int(0.14 * SAMPLE_RATE), n - pos)
        if k_len <= 0:
            continue
        kt = np.linspace(0, k_len / SAMPLE_RATE, k_len, endpoint=False)
        if bt % 2 == 0:
            kick = np.sin(2 * np.pi * (110 * np.exp(-26 * kt) + 42) * kt) * np.exp(-16 * kt) * 0.26
            left[pos:pos + k_len] += kick
            right[pos:pos + k_len] += kick
        elif style != "epic_doc":
            hat = _bandpass(rng.standard_normal(k_len), 5000, 12000) * np.exp(-65 * kt) * 0.08
            left[pos:pos + k_len] += hat
            right[pos:pos + k_len] += hat

    # Smooth low-pass warmth
    nyq = 0.5 * SAMPLE_RATE
    cutoff = 4200.0 if style == "lo_fi_study" else 8500.0
    sos = signal.butter(2, cutoff / nyq, btype="low", output="sos")
    stereo = np.column_stack([signal.sosfilt(sos, left), signal.sosfilt(sos, right)])

    tmp_wav = mp3_path.with_suffix(".wav")
    _save_wav(tmp_wav, stereo)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(tmp_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_path)],
        check=True,
    )
    tmp_wav.unlink(missing_ok=True)
    print(f"[Music] Trilha loopável gerada: {mp3_path.name} ({total_s:.1f}s)")


def generate_music() -> None:
    tracks = [
        (
            "dark_pulse.mp3",
            116.0,
            [[146.83, 220.0, 261.63, 329.63], [130.81, 196.0, 246.94, 293.66], [116.54, 174.61, 220.0, 293.66], [110.0, 164.81, 220.0, 261.63]],
            [73.42, 65.41, 58.27, 55.0],
            "dark_pulse",
        ),
        (
            "corporate_focus.mp3",
            120.0,
            [[261.63, 329.63, 392.0, 493.88], [220.0, 261.63, 329.63, 392.0], [174.61, 220.0, 261.63, 329.63], [196.0, 246.94, 293.66, 392.0]],
            [130.81, 110.0, 87.31, 98.0],
            "corporate_focus",
        ),
        (
            "lo_fi_study.mp3",
            86.0,
            [[196.0, 246.94, 293.66, 369.99], [164.81, 196.0, 246.94, 293.66], [220.0, 261.63, 329.63, 392.0], [146.83, 185.0, 220.0, 261.63]],
            [98.0, 82.41, 110.0, 73.42],
            "lo_fi_study",
        ),
        (
            "epic_doc.mp3",
            96.0,
            [[130.81, 196.0, 233.08, 311.13], [116.54, 174.61, 233.08, 293.66], [103.83, 155.56, 207.65, 261.63], [98.0, 146.83, 196.0, 246.94]],
            [65.41, 58.27, 51.91, 49.0],
            "epic_doc",
        ),
    ]
    for fname, bpm, chords, bass, style in tracks:
        _synthesize_music_track(MUSIC_DIR / fname, bpm, chords, bass, style)


# ---------------------------------------------------------------------------
# 5. Transparent 9:16 Overlays (Skia)
# ---------------------------------------------------------------------------
def generate_overlays() -> None:
    w, h = 1080, 1920

    # vignette_9x16.png
    surf = skia.Surface(w, h)
    c = surf.getCanvas()
    c.clear(skia.Color4f(0, 0, 0, 0))
    vig = skia.Paint(AntiAlias=True)
    vig.setShader(
        skia.GradientShader.MakeRadial(
            center=(w / 2, h / 2),
            radius=h * 0.68,
            colors=[
                skia.ColorSetARGB(0, 11, 7, 19),
                skia.ColorSetARGB(40, 11, 7, 19),
                skia.ColorSetARGB(175, 11, 7, 19),
            ],
            positions=[0.45, 0.78, 1.0],
        )
    )
    c.drawRect(skia.Rect.MakeWH(w, h), vig)
    surf.makeImageSnapshot().save(str(OVERLAYS_DIR / "vignette_9x16.png"), skia.kPNG)

    # safe_scrim.png (top & bottom gradient for subtitle legibility)
    surf2 = skia.Surface(w, h)
    c2 = surf2.getCanvas()
    c2.clear(skia.Color4f(0, 0, 0, 0))
    scrim = skia.Paint(AntiAlias=True)
    scrim.setShader(
        skia.GradientShader.MakeLinear(
            points=[(0, 0), (0, h)],
            colors=[
                skia.ColorSetARGB(145, 11, 7, 19),
                skia.ColorSetARGB(0, 11, 7, 19),
                skia.ColorSetARGB(0, 11, 7, 19),
                skia.ColorSetARGB(195, 11, 7, 19),
            ],
            positions=[0.0, 0.16, 0.65, 1.0],
        )
    )
    c2.drawRect(skia.Rect.MakeWH(w, h), scrim)
    surf2.makeImageSnapshot().save(str(OVERLAYS_DIR / "safe_scrim.png"), skia.kPNG)
    print(f"[Overlays] vignette_9x16.png e safe_scrim.png gerados em {OVERLAYS_DIR}")


def main() -> None:
    print("=== FrimeRise Bootstrap de Assets & Presets ===")
    ensure_dirs()
    generate_brand_logo()
    download_fonts()
    generate_luts()
    generate_sfx()
    generate_music()
    generate_overlays()
    init_db()
    print("[DB] SQLite data/frimerise.db inicializado com 7 Presets Oficiais (FrimeRise Signature padrão).")
    print("=== Bootstrap FrimeRise concluído com 100% de sucesso! ===")


if __name__ == "__main__":
    main()
