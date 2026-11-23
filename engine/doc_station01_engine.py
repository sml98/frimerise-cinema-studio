#!/usr/bin/env python3
"""
FrimeRise Cinema Studio — Station 01: Edit & Documentary Engine (Zero-Token)
============================================================================
Implementação determinística em Python dos 8 estilos documentais inspirados na
Estação 01 (Edit & Documentary) para uso em escala no FrimeRise Cinema Studio,
rodando leve em CPU (Intel Core i5 / 8 GB RAM) com pipe direto para FFmpeg +
Intel QuickSync VAAPI (fallback automático para libx264).

Estilos integrados (podem ser usados isoladamente ou misturados por Ato):
  1. caption_news          — Legenda gigante por chunks, destaque amarelo #FFC21A,
                             número rolando no hook, gradiente e source tag.
  2. visual_investigation  — Bancada investigativa 1920x1080 @ 30fps, cronômetro
                             compartilhado, grid de evidências, Freeze/Circle/Magnify
                             e fact-check Then vs. Record.
  3. newsreel_1920s        — Película 1920s (sépia/prata, flicker, riscos),
                             ident com holofotes, jornal girando e filtro de áudio rádio.
  4. constructivist_montage — Pôster construtivista (tinta/papel/vermelho), faixas
                             diagonais, contador rítmico e wipe vermelho.
  5. broadcast_news_package — Pacote de telejornal moderno (bug, lower-third com
                             barra vermelha + código de local, card OTS de dados).
  6. live_countdown_split  — Split-screen sincronizado com relógio regressivo ao vivo.
  7. sports_telestrator    — Freeze-frame tático com anéis pulsantes, setas
                             desenhadas ao vivo, spotlight e telemetria.
  8. city_symphony         — Montagem rítmica cinematográfica com carimbo de hora,
                             letterbox e cortes secos no beat.

Uso standalone:
  python3 doc_station01_engine.py --demo --output station01_showcase.mp4
  python3 doc_station01_engine.py --spec episodio.json --audio narracao.wav --output final.mp4
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

RGB = Tuple[int, int, int]

SUPPORTED_STYLES = (
    "caption_news",
    "visual_investigation",
    "newsreel_1920s",
    "constructivist_montage",
    "broadcast_news_package",
    "live_countdown_split",
    "sports_telestrator",
    "city_symphony",
)


# ---------------------------------------------------------------------------
# Schema JSON enxuto (gerado 1 vez pelo agents/llm_router.py — ~2k–4k tokens)
# ---------------------------------------------------------------------------

@dataclass
class DocSceneSpec:
    style: str
    duration: float = 3.0
    headline: str = ""
    subline: str = ""
    caption_chunks: List[str] = field(default_factory=list)  # use {palavra} para destaque
    source_tag: str = ""
    location_code: str = ""
    media_path: Optional[str] = None
    secondary_media: List[str] = field(default_factory=list)
    highlight_number: Optional[float] = None
    number_prefix: str = ""
    number_suffix: str = ""
    clock_start_sec: float = 0.0
    countdown_from_sec: Optional[float] = None
    fact_claim: str = ""
    fact_verdict: str = ""
    focus_point: Tuple[float, float] = (0.52, 0.46)
    target_point: Tuple[float, float] = (0.72, 0.36)
    accent_color: RGB = (255, 194, 26)
    transition_in: str = "cut"  # cut | flash | red_wipe | iris


@dataclass
class DocStation01Spec:
    title: str
    channel_bug: str = "FRIMERISE DOCS"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    scenes: List[DocSceneSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocStation01Spec":
        scenes: List[DocSceneSpec] = []
        for s in data.get("scenes", []):
            scenes.append(
                DocSceneSpec(
                    style=s.get("style", "visual_investigation"),
                    duration=float(s.get("duration", 3.0)),
                    headline=s.get("headline", ""),
                    subline=s.get("subline", ""),
                    caption_chunks=list(s.get("caption_chunks", [])),
                    source_tag=s.get("source_tag", ""),
                    location_code=s.get("location_code", ""),
                    media_path=s.get("media_path"),
                    secondary_media=list(s.get("secondary_media", [])),
                    highlight_number=s.get("highlight_number"),
                    number_prefix=s.get("number_prefix", ""),
                    number_suffix=s.get("number_suffix", ""),
                    clock_start_sec=float(s.get("clock_start_sec", 0.0)),
                    countdown_from_sec=s.get("countdown_from_sec"),
                    fact_claim=s.get("fact_claim", ""),
                    fact_verdict=s.get("fact_verdict", ""),
                    focus_point=tuple(s.get("focus_point", (0.52, 0.46))),
                    target_point=tuple(s.get("target_point", (0.72, 0.36))),
                    accent_color=tuple(s.get("accent_color", (255, 194, 26))),
                    transition_in=s.get("transition_in", "cut"),
                )
            )
        return cls(
            title=data.get("title", "Documentário"),
            channel_bug=data.get("channel_bug", "FRIMERISE DOCS"),
            width=int(data.get("width", 1920)),
            height=int(data.get("height", 1080)),
            fps=int(data.get("fps", 30)),
            scenes=scenes,
        )


# ---------------------------------------------------------------------------
# Helpers de tipografia, easing, mídia e filtros de áudio/vídeo
# ---------------------------------------------------------------------------

def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_back_out(t: float, overshoot: float = 1.6) -> float:
    t = clamp01(t)
    c3 = overshoot + 1.0
    return 1.0 + c3 * ((t - 1.0) ** 3) + overshoot * ((t - 1.0) ** 2)


def load_font(size: int, bold: bool = True, mono: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if mono:
        candidates = [
            "assets/fonts/CourierPrime-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    elif serif:
        candidates = [
            "assets/fonts/Cinzel-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ]
    elif bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=max(10, size))
            except OSError:
                continue
    return ImageFont.load_default()


def build_1920s_radio_audio_filter() -> str:
    """Filtro FFmpeg pronto para dar timbre de microfone/rádio dos anos 1920 ao TTS."""
    return (
        "highpass=f=320,lowpass=f=3100,"
        "acompressor=threshold=-18dB:ratio=4:attack=5:release=60,"
        "equalizer=f=1200:t=q:w=1.5:g=4,"
        "loudnorm=I=-14:TP=-1.0:LRA=7"
    )


def build_broadcast_audio_filter() -> str:
    """Padrão de masterização FrimeRise (-14.0 LUFS / <= -1.0 dBTP)."""
    return "loudnorm=I=-14:TP=-1.0:LRA=8"


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _fit_cover_pil(im: Image.Image, width: int, height: int) -> Image.Image:
    src_ratio = im.width / max(1, im.height)
    dst_ratio = width / max(1, height)
    if src_ratio > dst_ratio:
        new_w = int(im.height * dst_ratio)
        x0 = (im.width - new_w) // 2
        im = im.crop((x0, 0, x0 + new_w, im.height))
    else:
        new_h = int(im.width / dst_ratio)
        y0 = (im.height - new_h) // 2
        im = im.crop((0, y0, im.width, y0 + new_h))
    return im.resize((width, height), Image.Resampling.LANCZOS)


class MediaFrameReader:
    """Lê imagem estática ou faz streaming frame a frame de vídeo MP4 (com loop limpo e baixa RAM)."""

    def __init__(self, media_path: Optional[str], width: int, height: int, seed: int = 1, tone: RGB = (22, 29, 42)):
        self.width = width
        self.height = height
        self.cap = None
        self.static_img: Optional[Image.Image] = None

        if media_path and os.path.exists(media_path) and Path(media_path).suffix.lower() in VIDEO_EXTS and HAS_CV2:
            cap = cv2.VideoCapture(media_path)
            if cap.isOpened():
                self.cap = cap
            else:
                cap.release()

        if self.cap is None:
            self.static_img = load_or_synthesize_bg(media_path, width, height, seed=seed, tone=tone)

    def read(self) -> Image.Image:
        if self.cap is not None:
            ok, bgr = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, bgr = self.cap.read()
            if ok and bgr is not None:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                return _fit_cover_pil(Image.fromarray(rgb), self.width, self.height)
        assert self.static_img is not None
        return self.static_img

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def load_or_synthesize_bg(
    media_path: Optional[str],
    width: int,
    height: int,
    seed: int = 1,
    tone: RGB = (22, 29, 42),
) -> Image.Image:
    """
    Carrega foto/frame real do flow_vault.py / doc_media_engine.py com crop
    proporcional; se nenhum arquivo for passado, gera um fundo atmosférico
    procedural limpo para testes ou cards de dados.
    """
    if media_path and os.path.exists(media_path):
        im = Image.open(media_path).convert("RGB")
        src_ratio = im.width / max(1, im.height)
        dst_ratio = width / max(1, height)
        if src_ratio > dst_ratio:
            new_w = int(im.height * dst_ratio)
            x0 = (im.width - new_w) // 2
            im = im.crop((x0, 0, x0 + new_w, im.height))
        else:
            new_h = int(im.width / dst_ratio)
            y0 = (im.height - new_h) // 2
            im = im.crop((0, y0, im.width, y0 + new_h))
        return im.resize((width, height), Image.Resampling.LANCZOS)

    # Fundo editorial procedural leve (grade sutil + gradiente radial)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx / max(1, width - 1)) * 2.0 - 1.0
    ny = (yy / max(1, height - 1)) * 2.0 - 1.0
    rad = np.clip(1.0 - 0.42 * (nx * nx + ny * ny), 0.35, 1.05)

    rng = np.random.default_rng(seed)
    grain = rng.normal(0.0, 4.0, (height, width)).astype(np.float32)
    arr = np.empty((height, width, 3), dtype=np.float32)
    for c in range(3):
        arr[:, :, c] = np.clip(tone[c] * rad + grain, 0, 255)

    img = Image.fromarray(arr.astype(np.uint8))
    draw = ImageDraw.Draw(img, "RGBA")
    step = max(36, width // 24)
    for gx in range(0, width, step):
        draw.line([(gx, 0), (gx, height)], fill=(255, 255, 255, 10), width=1)
    for gy in range(0, height, step):
        draw.line([(0, gy), (width, gy)], fill=(255, 255, 255, 10), width=1)
    return img


def apply_grade(img: Image.Image, contrast: float = 1.07, sat: float = 0.92, bright: float = 0.98) -> Image.Image:
    out = ImageEnhance.Contrast(img).enhance(contrast)
    out = ImageEnhance.Color(out).enhance(sat)
    out = ImageEnhance.Brightness(out).enhance(bright)
    return out


def apply_ken_burns(img: Image.Image, t_norm: float, max_zoom: float = 1.08, target: Tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    w, h = img.size
    zoom = 1.0 + (max_zoom - 1.0) * ease_out_cubic(t_norm)
    cw, ch = int(w / zoom), int(h / zoom)
    cx, cy = int(target[0] * w), int(target[1] * h)
    x0 = max(0, min(w - cw, cx - cw // 2))
    y0 = max(0, min(h - ch, cy - ch // 2))
    return img.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), Image.Resampling.BICUBIC)


def draw_gradient_bar(img: Image.Image, y_start: int, y_end: int, max_alpha: int = 215, top_down: bool = False) -> None:
    w, h = img.size
    y0, y1 = max(0, min(h, y_start)), max(0, min(h, y_end))
    if y1 <= y0:
        return
    span = y1 - y0
    grad = np.linspace(max_alpha, 0, span, dtype=np.uint8) if top_down else np.linspace(0, max_alpha, span, dtype=np.uint8)
    alpha = np.repeat(grad[:, None], w, axis=1)
    overlay = np.zeros((span, w, 4), dtype=np.uint8)
    overlay[:, :, 3] = alpha
    ov_img = Image.fromarray(overlay, "RGBA")
    img.paste(ov_img, (0, y0), ov_img)


def format_clock(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = int(sec % 60)
    d = int((sec - int(sec)) * 10)
    return f"{m:02d}:{s:02d}.{d}"


# ---------------------------------------------------------------------------
# Renderizadores dedicados para cada um dos 8 estilos da Estação 01
# ---------------------------------------------------------------------------

class Station01Renderer:
    def __init__(self, spec: DocStation01Spec, prefer_vaapi: bool = True):
        self.spec = spec
        self.prefer_vaapi = prefer_vaapi
        h = spec.height
        self.f_giant = load_font(int(h * 0.072), bold=True)
        self.f_hero = load_font(int(h * 0.056), bold=True)
        self.f_h2 = load_font(int(h * 0.036), bold=True)
        self.f_body = load_font(int(h * 0.026), bold=False)
        self.f_mono = load_font(int(h * 0.022), bold=True, mono=True)
        self.f_clock = load_font(int(h * 0.034), bold=True, mono=True)
        self.f_serif = load_font(int(h * 0.052), bold=True, serif=True)
        self.f_serif_sm = load_font(int(h * 0.028), bold=True, serif=True)

    # 1) CAPTION NEWS -------------------------------------------------------
    def _render_caption_news(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        frame = apply_ken_burns(apply_grade(bg, 1.07, 0.92, 0.98), t / max(0.1, sc.duration), 1.06, sc.focus_point)
        draw_gradient_bar(frame, 0, int(h * 0.19), max_alpha=145, top_down=True)
        draw_gradient_bar(frame, int(h * 0.50), h, max_alpha=220, top_down=False)
        draw = ImageDraw.Draw(frame, "RGBA")

        # Bug superior esquerdo + source tag deslizando
        pad = int(w * 0.035)
        draw.rectangle([pad, pad, pad + int(w * 0.16), pad + int(h * 0.045)], fill=(255, 194, 26, 240))
        draw.text((pad + 12, pad + 8), self.spec.channel_bug[:16], fill=(14, 14, 12), font=self.f_mono)

        if sc.source_tag:
            slide = ease_out_cubic(t / 0.25)
            sx = int(w - pad - int(w * 0.24) * slide)
            if w - pad > sx + 4: draw.rectangle([sx, pad, w - pad, pad + int(h * 0.042)], fill=(15, 17, 22, 210))
            draw.text((sx + 12, pad + 8), f"FONTE: {sc.source_tag}", fill=(240, 238, 230), font=self.f_mono)

        # Hook numérico rolando já no frame 4 (~0.15s)
        if sc.highlight_number is not None:
            roll = ease_out_cubic((t - 0.10) / 0.75)
            val = sc.highlight_number * roll
            num_txt = f"{sc.number_prefix}{val:,.1f}{sc.number_suffix}" if sc.highlight_number % 1 else f"{sc.number_prefix}{int(round(val)):,}{sc.number_suffix}"
            draw.text((pad, int(h * 0.22)), num_txt, fill=(255, 194, 26), font=self.f_giant)
            if sc.subline:
                draw.text((pad, int(h * 0.31)), sc.subline, fill=(247, 245, 239), font=self.f_h2)

        # Legendas gigantes em chunks (com {palavra} no bloco amarelo-mel #FFC21A)
        chunks = sc.caption_chunks or ([sc.headline] if sc.headline else [])
        cur_y = int(h * 0.72)
        for idx, raw_chunk in enumerate(chunks[:2]):
            chunk_t = t - idx * 0.14
            if chunk_t < 0:
                continue
            scale_bump = 1.0 + 0.18 * (1.0 - clamp01(ease_back_out(chunk_t / 0.15)))
            # Parse simples de {keyword}
            parts = raw_chunk.split("{")
            cur_x = pad
            for p_idx, part in enumerate(parts):
                if "}" in part and p_idx > 0:
                    kw, rest = part.split("}", 1)
                    kb = draw.textbbox((0, 0), kw, font=self.f_hero)
                    kw_w, kw_h = kb[2] - kb[0], kb[3] - kb[1]
                    wipe = ease_out_cubic((chunk_t - 0.05) / 0.14)
                    draw.rectangle(
                        [cur_x - 8, cur_y - 4, cur_x + int((kw_w + 16) * wipe), cur_y + kw_h + 12],
                        fill=(255, 194, 26, 250),
                    )
                    draw.text((cur_x, cur_y), kw, fill=(14, 14, 12), font=self.f_hero)
                    cur_x += kw_w + 18
                    if rest:
                        draw.text((cur_x, cur_y), rest, fill=(247, 245, 239), font=self.f_hero)
                        rb = draw.textbbox((0, 0), rest, font=self.f_hero)
                        cur_x += rb[2] - rb[0]
                else:
                    y_off = int((scale_bump - 1.0) * 18)
                    draw.text((cur_x + 3, cur_y + 3 - y_off), part, fill=(0, 0, 0, 200), font=self.f_hero)
                    draw.text((cur_x, cur_y - y_off), part, fill=(247, 245, 239), font=self.f_hero)
                    pb = draw.textbbox((0, 0), part, font=self.f_hero)
                    cur_x += pb[2] - pb[0]
            cur_y += int(h * 0.088)

        return frame

    # 2) VISUAL INVESTIGATION -----------------------------------------------
    def _render_visual_investigation(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        frame = Image.new("RGB", (w, h), (13, 16, 21))
        draw = ImageDraw.Draw(frame, "RGBA")
        m = int(w * 0.032)  # ~60px em 1080p

        # Cabeçalho frio + cronômetro compartilhado sincronizado
        clock_str = f"T+ {format_clock(sc.clock_start_sec + t)}"
        draw.rectangle([m, m, m + 8, m + int(h * 0.055)], fill=(217, 56, 30))
        draw.text((m + 20, m + 2), sc.headline.upper() or "INVESTIGAÇÃO VISUAL", fill=(242, 244, 248), font=self.f_h2)
        if sc.location_code:
            draw.text((m + 20, m + int(h * 0.042)), sc.location_code, fill=(154, 164, 178), font=self.f_mono)

        cb = draw.textbbox((0, 0), clock_str, font=self.f_clock)
        cw = cb[2] - cb[0]
        draw.rectangle([w - m - cw - 28, m, w - m, m + int(h * 0.058)], fill=(26, 31, 40), outline=(217, 56, 30), width=1)
        draw.text((w - m - cw - 14, m + 8), clock_str, fill=(245, 246, 248), font=self.f_clock)

        # Painel principal esquerdo (evidência de imagem/vídeo com Freeze -> Circle -> Magnify)
        top_y = m + int(h * 0.095)
        bot_y = int(h * 0.84)
        left_w = int((w - 3 * m) * 0.62)
        panel_h = bot_y - top_y
        ev_img = apply_grade(bg.resize((left_w, panel_h), Image.Resampling.LANCZOS), 1.08, 0.78, 0.95)
        frame.paste(ev_img, (m, top_y))
        draw.rectangle([m, top_y, m + left_w, bot_y], outline=(110, 120, 136), width=1)

        # Source tag curta (chip vermelho + mono <= 12 chars)
        tag = (sc.source_tag or "ARQ · PROVA")[:18]
        draw.rectangle([m, top_y - 26, m + 8, top_y - 10], fill=(217, 56, 30))
        draw.text((m + 14, top_y - 28), tag, fill=(195, 203, 214), font=self.f_mono)

        # Freeze -> Circle -> Magnify sobre o ponto de foco
        fx = m + int(left_w * sc.focus_point[0])
        fy = top_y + int(panel_h * sc.focus_point[1])
        circ_p = ease_out_cubic((t - 0.35) / 0.45)
        if circ_p > 0.02:
            rad = int(min(left_w, panel_h) * 0.11 * (1.25 - 0.25 * circ_p))
            draw.ellipse([fx - rad, fy - rad, fx + rad, fy + rad], outline=(224, 58, 42, 240), width=3)

        # Painel direito: Then vs. Record ou Quadro de Evidências com link vermelho tracejado
        rx0 = m * 2 + left_w
        rx1 = w - m
        draw.rectangle([rx0, top_y, rx1, bot_y], fill=(20, 24, 31), outline=(90, 100, 116), width=1)

        # Link vermelho tracejado ligando o círculo ao painel de prova
        if circ_p > 0.5:
            steps = 12
            lx0, ly0 = fx + int(min(left_w, panel_h) * 0.11), fy
            lx1, ly1 = rx0 + 18, top_y + int(panel_h * 0.32)
            for s in range(0, steps, 2):
                p0, p1 = s / steps, min(1.0, (s + 1) / steps)
                draw.line(
                    [
                        (lx0 + (lx1 - lx0) * p0, ly0 + (ly1 - ly0) * p0),
                        (lx0 + (lx1 - lx0) * p1, ly0 + (ly1 - ly0) * p1),
                    ],
                    fill=(224, 58, 42, 230),
                    width=2,
                )

        # Conteúdo do painel direito (Then vs. Record)
        px = rx0 + 24
        draw.text((px, top_y + 22), "DECLARAÇÃO OFICIAL", fill=(154, 164, 178), font=self.f_mono)
        claim = sc.fact_claim or sc.subline or "Registro inicial sem anomalias reportadas."
        draw.text((px, top_y + 56), claim[:44], fill=(228, 232, 238), font=self.f_body)
        # Risca a declaração quando o fact-check entra
        strike_p = ease_out_cubic((t - 1.0) / 0.35)
        if strike_p > 0.02:
            draw.line(
                [(px, top_y + 72), (px + int((rx1 - rx0 - 52) * strike_p), top_y + 72)],
                fill=(224, 58, 42),
                width=4,
            )

        draw.text((px, top_y + int(panel_h * 0.44)), "REGISTRO VERIFICADO", fill=(224, 58, 42), font=self.f_mono)
        verdict = sc.fact_verdict or "5 fontes independentes convergem no mesmo ponto."
        draw.text((px, top_y + int(panel_h * 0.51)), verdict[:44], fill=(246, 248, 250), font=self.f_body)

        # Faixa inferior limpa para legenda
        if sc.caption_chunks:
            cap = sc.caption_chunks[0].replace("{", "").replace("}", "")
            cb2 = draw.textbbox((0, 0), cap, font=self.f_h2)
            draw.text(((w - (cb2[2] - cb2[0])) // 2, int(h * 0.895)), cap, fill=(242, 244, 248), font=self.f_h2)

        return frame

    # 3) 1920s NEWSREEL -----------------------------------------------------
    def _render_newsreel_1920s(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        # Passagem de película prateada/sépia + gate weave leve
        rng = np.random.default_rng(fidx * 19 + 3)
        gray = bg.convert("L")
        arr = np.asarray(gray, dtype=np.float32)
        flicker = 1.0 + float(rng.uniform(-0.045, 0.045))
        arr = np.clip((arr - 128.0) * 1.18 + 126.0, 12, 242) * flicker

        sepia = np.empty((h, w, 3), dtype=np.uint8)
        sepia[:, :, 0] = np.clip(arr * 1.04, 0, 255).astype(np.uint8)
        sepia[:, :, 1] = np.clip(arr * 0.99, 0, 255).astype(np.uint8)
        sepia[:, :, 2] = np.clip(arr * 0.87, 0, 255).astype(np.uint8)
        frame = Image.fromarray(sepia)
        draw = ImageDraw.Draw(frame, "RGBA")

        # Holofotes girando nos primeiros 0.9s (ident anos 20)
        if t < 0.95:
            ang = math.sin(t * 4.2) * 0.42
            for sx in (int(w * 0.2), int(w * 0.8)):
                dx = int(math.sin(ang) * w * 0.35)
                poly = [(sx, h), (sx + dx - 90, 0), (sx + dx + 90, 0)]
                draw.polygon(poly, fill=(248, 240, 215, 42))

        # Jornal girando (spinning newspaper) entrando com rotação e escala
        spin_p = ease_out_cubic(t / 0.65)
        nw, nh = int(w * 0.56), int(h * 0.44)
        paper = Image.new("RGBA", (nw, nh), (235, 224, 198, 248))
        pd = ImageDraw.Draw(paper)
        pd.rectangle([10, 10, nw - 10, nh - 10], outline=(38, 32, 26), width=4)
        pd.rectangle([18, 18, nw - 18, nh - 18], outline=(38, 32, 26), width=1)
        pd.text((34, 28), "EXTRA • CINEJORNAL", fill=(32, 27, 22), font=self.f_serif_sm)
        pd.line([(28, 72), (nw - 28, 72)], fill=(32, 27, 22), width=3)
        pd.text((34, 96), (sc.headline or "MANCHETE HISTÓRICA")[:28], fill=(24, 20, 16), font=self.f_serif)
        if sc.subline:
            pd.text((34, 178), sc.subline[:46], fill=(54, 46, 38), font=self.f_body)

        rot_deg = (1.0 - spin_p) * 360.0
        scale = 0.25 + 0.75 * spin_p
        paper_t = paper.resize((max(16, int(nw * scale)), max(16, int(nh * scale))), Image.Resampling.BICUBIC).rotate(
            rot_deg, expand=True, resample=Image.Resampling.BICUBIC
        )
        frame.paste(paper_t, ((w - paper_t.width) // 2, (h - paper_t.height) // 2), paper_t)

        # Riscos verticais aleatórios de película antiga
        for _ in range(3):
            if rng.random() < 0.65:
                rx = int(rng.integers(0, w))
                col = (245, 240, 225, 95) if rng.random() > 0.4 else (22, 18, 15, 110)
                draw.line([(rx, 0), (rx + int(rng.integers(-2, 3)), h)], fill=col, width=1)

        # Moldura de projeção 4:3 sutil com cantos escuros
        draw.rectangle([0, 0, w - 1, h - 1], outline=(16, 14, 12), width=max(12, w // 90))
        return frame

    # 4) CONSTRUCTIVIST MONTAGE ---------------------------------------------
    def _render_constructivist(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        # Base papel creme + foto em alto contraste preto/papel
        gray = ImageEnhance.Contrast(bg.convert("L")).enhance(1.65)
        arr = np.asarray(gray, dtype=np.float32)
        poster = np.empty((h, w, 3), dtype=np.uint8)
        poster[:, :, 0] = np.clip(arr * 0.96 + 8, 16, 242).astype(np.uint8)
        poster[:, :, 1] = np.clip(arr * 0.93 + 5, 16, 234).astype(np.uint8)
        poster[:, :, 2] = np.clip(arr * 0.85 + 2, 16, 218).astype(np.uint8)
        frame = Image.fromarray(poster)
        draw = ImageDraw.Draw(frame, "RGBA")

        # Faixa diagonal vermelha característica (-20 graus) entrando com slam
        slam = ease_out_cubic(t / 0.18)
        shake = int(math.sin(t * 70.0) * 8.0 * math.exp(-12.0 * t)) if t < 0.35 else 0
        off_x = int((1.0 - slam) * w * 0.6) + shake
        band = [
            (-80 + off_x, int(h * 0.62)),
            (w + 80 + off_x, int(h * 0.34)),
            (w + 80 + off_x, int(h * 0.50)),
            (-80 + off_x, int(h * 0.78)),
        ]
        draw.polygon(band, fill=(214, 40, 40, 238))

        # Bloco preto estrutural + contador rítmico
        draw.rectangle([int(w * 0.05), int(h * 0.08), int(w * 0.44), int(h * 0.24)], fill=(18, 18, 18, 245))
        draw.text((int(w * 0.07), int(h * 0.11)), (sc.headline or "MONTAGEM RÍTMICA").upper()[:24], fill=(244, 238, 224), font=self.f_h2)

        if sc.highlight_number is not None:
            cnt = int(sc.highlight_number * ease_out_cubic(t / max(0.4, sc.duration * 0.65)))
            draw.rectangle([int(w * 0.64), int(h * 0.72), int(w * 0.94), int(h * 0.90)], fill=(18, 18, 18, 245))
            draw.text(
                (int(w * 0.67), int(h * 0.75)),
                f"{sc.number_prefix}{cnt:,}{sc.number_suffix}",
                fill=(214, 40, 40),
                font=self.f_giant,
            )

        if sc.subline:
            draw.text((int(w * 0.08) + shake, int(h * 0.62)), sc.subline.upper()[:34], fill=(248, 244, 232), font=self.f_h2)

        return frame

    # 5) BROADCAST NEWS PACKAGE ---------------------------------------------
    def _render_broadcast_package(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        frame = apply_ken_burns(apply_grade(bg, 1.05, 0.98, 1.0), t / max(0.1, sc.duration), 1.05, sc.focus_point)
        draw = ImageDraw.Draw(frame, "RGBA")
        pad = int(w * 0.04)

        # Bug ao vivo no canto superior esquerdo
        draw.rectangle([pad, pad, pad + 88, pad + 38], fill=(204, 34, 34, 245))
        draw.text((pad + 14, pad + 8), "LIVE", fill=(255, 255, 255), font=self.f_mono)
        draw.rectangle([pad + 88, pad, pad + 290, pad + 38], fill=(18, 26, 42, 235))
        draw.text((pad + 102, pad + 8), (sc.location_code or "REDAÇÃO CENTRAL")[:16], fill=(240, 244, 248), font=self.f_mono)

        # Card OTS (over-the-shoulder) de dados à direita
        if sc.highlight_number is not None:
            ots_p = ease_out_cubic(t / 0.30)
            ox0 = int(w - pad - int(w * 0.27) * ots_p)
            if w - pad > ox0 + 4: draw.rectangle([ox0, int(h * 0.16), w - pad, int(h * 0.44)], fill=(15, 22, 36, 228), outline=(204, 34, 34), width=2)
            draw.text((ox0 + 18, int(h * 0.18)), (sc.source_tag or "DADO OFICIAL").upper(), fill=(204, 34, 34), font=self.f_mono)
            draw.text(
                (ox0 + 18, int(h * 0.24)),
                f"{sc.number_prefix}{sc.highlight_number:g}{sc.number_suffix}",
                fill=(255, 255, 255),
                font=self.f_hero,
            )

        # Lower-third limpa estilo telejornal (sem ticker rolante poluído)
        lt_p = ease_out_cubic(t / 0.28)
        lt_w = max(12, int((w - 2 * pad) * lt_p))
        ly0 = int(h * 0.80)
        draw.rectangle([pad, ly0, pad + 10, ly0 + int(h * 0.12)], fill=(204, 34, 34, 250))
        draw.rectangle([pad + 10, ly0, pad + lt_w, ly0 + int(h * 0.068)], fill=(16, 24, 40, 240))
        draw.rectangle([pad + 10, ly0 + int(h * 0.068), pad + lt_w, ly0 + int(h * 0.12)], fill=(242, 244, 248, 242))
        if lt_p > 0.4:
            draw.text((pad + 28, ly0 + 14), (sc.headline or "BOLETIM ESPECIAL").upper()[:44], fill=(255, 255, 255), font=self.f_h2)
            draw.text((pad + 28, ly0 + int(h * 0.078)), (sc.subline or sc.source_tag)[:62], fill=(20, 26, 36), font=self.f_body)

        return frame

    # 6) LIVE COUNTDOWN SPLIT-SCREEN ----------------------------------------
    def _render_countdown_split(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        frame = Image.new("RGB", (w, h), (10, 12, 16))
        gap = 8
        half_w = (w - gap) // 2

        left_im = apply_grade(bg.resize((half_w, h), Image.Resampling.LANCZOS), 1.1, 0.88, 0.92)
        right_src = (
            self._active_sec_frame
            if getattr(self, "_active_sec_frame", None) is not None
            else load_or_synthesize_bg(sc.secondary_media[0] if sc.secondary_media else None, half_w, h, seed=fidx // 30 + 99, tone=(36, 24, 26))
        )
        right_im = apply_grade(right_src, 1.1, 0.88, 0.92)

        frame.paste(left_im, (0, 0))
        frame.paste(right_im, (half_w + gap, 0))
        draw = ImageDraw.Draw(frame, "RGBA")

        # Relógio regressivo central ao vivo
        rem = (sc.countdown_from_sec if sc.countdown_from_sec is not None else 60.0) - t
        clk = f"T- {format_clock(max(0.0, rem))}"
        cb = draw.textbbox((0, 0), clk, font=self.f_giant)
        cw, ch = cb[2] - cb[0], cb[3] - cb[1]
        bx0, by0 = (w - cw) // 2 - 32, int(h * 0.08)
        draw.rectangle([bx0, by0, bx0 + cw + 64, by0 + ch + 28], fill=(12, 14, 18, 235), outline=(235, 58, 42), width=3)
        draw.text((bx0 + 32, by0 + 10), clk, fill=(248, 248, 250), font=self.f_giant)

        # Rótulos das duas câmeras
        draw.text((28, h - 72), f"CAM A · {(sc.headline or 'LOCAL 01').upper()[:22]}", fill=(242, 244, 248), font=self.f_mono)
        draw.text((half_w + gap + 28, h - 72), f"CAM B · {(sc.subline or 'LOCAL 02').upper()[:22]}", fill=(242, 244, 248), font=self.f_mono)

        # Barra de tensão na base
        prog = clamp01(t / max(0.1, sc.duration))
        draw.rectangle([0, h - 8, int(w * prog), h], fill=(235, 58, 42))
        return frame

    # 7) SPORTS TELESTRATOR -------------------------------------------------
    def _render_telestrator(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        # Freeze-frame com escurecimento tático fora do spotlight
        frame = apply_grade(bg, 1.05, 0.85, 0.72)
        draw = ImageDraw.Draw(frame, "RGBA")

        fx, fy = int(sc.focus_point[0] * w), int(sc.focus_point[1] * h)
        tx, ty = int(sc.target_point[0] * w), int(sc.target_point[1] * h)

        # Anel pulsante no ponto de origem
        pulse = 1.0 + 0.08 * math.sin(t * 9.0)
        r = int(min(w, h) * 0.075 * pulse)
        draw.ellipse([fx - r, fy - r, fx + r, fy + r], outline=(255, 210, 40, 245), width=5)
        draw.ellipse([fx - r - 10, fy - r - 10, fx + r + 10, fy + r + 10], outline=(255, 210, 40, 120), width=2)

        # Seta tática animada desenhada ao vivo até o alvo
        arrow_p = ease_out_cubic((t - 0.25) / 0.60)
        if arrow_p > 0.02:
            ax = int(fx + (tx - fx) * arrow_p)
            ay = int(fy + (ty - fy) * arrow_p)
            draw.line([(fx, fy), (ax, ay)], fill=(255, 210, 40, 245), width=6)
            ang = math.atan2(ty - fy, tx - fx)
            head = 22
            p1 = (ax - head * math.cos(ang - 0.45), ay - head * math.sin(ang - 0.45))
            p2 = (ax - head * math.cos(ang + 0.45), ay - head * math.sin(ang + 0.45))
            draw.polygon([(ax, ay), p1, p2], fill=(255, 210, 40, 245))

        # Callout de telemetria
        draw.rectangle([42, 42, 460, 118], fill=(14, 18, 26, 225), outline=(255, 210, 40), width=2)
        draw.text((58, 52), (sc.headline or "ANÁLISE TÁTICA").upper()[:24], fill=(255, 210, 40), font=self.f_mono)
        draw.text((58, 82), (sc.subline or "FREEZE FRAME · TRAJETÓRIA")[:34], fill=(245, 246, 248), font=self.f_body)
        return frame

    # 8) CITY SYMPHONY ------------------------------------------------------
    def _render_city_symphony(self, sc: DocSceneSpec, bg: Image.Image, t: float, fidx: int) -> Image.Image:
        w, h = self.spec.width, self.spec.height
        frame = apply_ken_burns(apply_grade(bg, 1.12, 0.86, 0.96), t / max(0.1, sc.duration), 1.10, sc.focus_point)
        draw = ImageDraw.Draw(frame, "RGBA")

        # Letterbox cinematográfico 2.39:1
        bar = int(h * 0.115)
        draw.rectangle([0, 0, w, bar], fill=(8, 9, 11))
        draw.rectangle([0, h - bar, w, h], fill=(8, 9, 11))

        # Carimbo minimalista de hora / capítulo
        stamp = sc.location_code or f"{format_clock(sc.clock_start_sec + t)}"
        draw.text((int(w * 0.045), bar + 24), stamp, fill=(240, 236, 226, 230), font=self.f_mono)
        if sc.headline:
            draw.text((int(w * 0.045), h - bar - 64), sc.headline, fill=(244, 242, 236, 240), font=self.f_h2)
        return frame

    # Transições nativas (sem dissolve digital) -----------------------------
    def _apply_transition(self, prev_rgb: np.ndarray, cur_rgb: np.ndarray, kind: str, progress: float) -> np.ndarray:
        p = clamp01(progress)
        if kind == "flash":
            alpha = math.sin(p * math.pi) * 0.85
            base = cur_rgb if p >= 0.5 else prev_rgb
            return np.clip(base.astype(np.float32) * (1.0 - alpha) + 248.0 * alpha, 0, 255).astype(np.uint8)
        if kind == "red_wipe":
            h, w, _ = cur_rgb.shape
            seam = int(w * ease_out_cubic(p))
            out = prev_rgb.copy()
            out[:, :seam, :] = cur_rgb[:, :seam, :]
            bw = max(18, int(w * 0.06))
            b0, b1 = max(0, seam - bw), min(w, seam + bw // 2)
            out[:, b0:b1, :] = (214, 40, 40)
            return out
        if kind == "iris":
            h, w, _ = cur_rgb.shape
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            dist = np.sqrt((xx - w / 2) ** 2 + (yy - h / 2) ** 2)
            rad = math.hypot(w / 2, h / 2) * ease_out_cubic(p)
            mask = (dist <= rad)[:, :, None]
            return np.where(mask, cur_rgb, prev_rgb)
        return cur_rgb

    # Renderização em streaming direto para FFmpeg --------------------------
    def render(self, output_path: str, audio_path: Optional[str] = None) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        has_nvenc = False
        if os.path.exists("/dev/nvidia0"):
            try:
                encs = subprocess.check_output(["ffmpeg", "-hide_banner", "-encoders"], text=True, stderr=subprocess.DEVNULL)
                has_nvenc = "h264_nvenc" in encs
            except Exception:
                has_nvenc = False
        vaapi_dev = "/dev/dri/renderD128" if (not has_nvenc and self.prefer_vaapi and os.path.exists("/dev/dri/renderD128")) else None

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{self.spec.width}x{self.spec.height}",
            "-r",
            str(self.spec.fps),
            "-i",
            "-",
        ]
        if audio_path and os.path.exists(audio_path):
            cmd += ["-i", audio_path, "-af", build_broadcast_audio_filter(), "-c:a", "aac", "-b:a", "192k", "-shortest"]

        if has_nvenc:
            print("[Station01Renderer] Encoder ativo: NVIDIA GPU (h264_nvenc)")
            cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "20", "-pix_fmt", "yuv420p"]
        elif vaapi_dev:
            print("[Station01Renderer] Encoder ativo: Intel QuickSync VAAPI (h264_vaapi)")
            cmd += ["-vaapi_device", vaapi_dev, "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "20"]
        else:
            print("[Station01Renderer] Encoder ativo: CPU (libx264)")
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
        cmd += ["-movflags", "+faststart", output_path]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert proc.stdin is not None

        dispatch = {
            "caption_news": self._render_caption_news,
            "visual_investigation": self._render_visual_investigation,
            "newsreel_1920s": self._render_newsreel_1920s,
            "constructivist_montage": self._render_constructivist,
            "broadcast_news_package": self._render_broadcast_package,
            "live_countdown_split": self._render_countdown_split,
            "sports_telestrator": self._render_telestrator,
            "city_symphony": self._render_city_symphony,
        }

        global_f = 0
        trans_frames = max(1, int(0.24 * self.spec.fps))
        last_frame: Optional[np.ndarray] = None

        try:
            for s_idx, sc in enumerate(self.spec.scenes):
                fn = dispatch.get(sc.style, self._render_visual_investigation)
                bg_reader = MediaFrameReader(sc.media_path, self.spec.width, self.spec.height, seed=s_idx * 17 + 5)
                sec_path = sc.secondary_media[0] if sc.secondary_media else None
                sec_w = (self.spec.width - 8) // 2 if sc.style == "live_countdown_split" else int(self.spec.width * 0.30)
                sec_h = self.spec.height if sc.style == "live_countdown_split" else int(self.spec.height * 0.30)
                sec_reader = MediaFrameReader(sec_path, sec_w, sec_h, seed=s_idx * 31 + 99, tone=(36, 24, 26)) if (sec_path or sc.style == "live_countdown_split") else None
                self._active_sec_frame = None
                total_f = max(1, int(round(sc.duration * self.spec.fps)))
                try:
                    for f in range(total_f):
                        t = f / self.spec.fps
                        bg = bg_reader.read()
                        self._active_sec_frame = sec_reader.read() if sec_reader is not None else None
                        img = fn(sc, bg, t, global_f)
                        # Vídeo-sobre-vídeo PiP automático quando há secondary_media fora do split-screen
                        if sec_path and sc.style != "live_countdown_split" and self._active_sec_frame is not None:
                            pip = self._active_sec_frame
                            px = self.spec.width - pip.width - int(self.spec.width * 0.035)
                            py = int(self.spec.height * 0.14)
                            d_pip = ImageDraw.Draw(img, "RGBA")
                            d_pip.rectangle([px - 4, py - 4, px + pip.width + 4, py + pip.height + 4], fill=(12, 14, 18, 230), outline=(255, 194, 26, 235), width=2)
                            img.paste(pip, (px, py))
                        arr = np.asarray(img, dtype=np.uint8)
                        if s_idx > 0 and last_frame is not None and sc.transition_in != "cut" and f < trans_frames:
                            arr = self._apply_transition(last_frame, arr, sc.transition_in, (f + 1) / trans_frames)
                        proc.stdin.write(arr.tobytes())
                        global_f += 1
                        if f == total_f - 1:
                            last_frame = arr
                finally:
                    bg_reader.close()
                    if sec_reader is not None:
                        sec_reader.close()
                    self._active_sec_frame = None
                gc.collect()
        finally:
            proc.stdin.close()
            ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"FFmpeg encerrou com código {ret}")

        return output_path


# ---------------------------------------------------------------------------
# Showcase embutido com todos os 8 estilos da Estação 01 (0 tokens)
# ---------------------------------------------------------------------------

def build_station01_demo(width: int = 1280, height: int = 720, fps: int = 30) -> DocStation01Spec:
    return DocStation01Spec(
        title="Station 01 Showcase — Edit & Documentary",
        width=width,
        height=height,
        fps=fps,
        scenes=[
            DocSceneSpec(
                style="caption_news",
                duration=1.6,
                highlight_number=1.3,
                number_suffix=" MILHÃO",
                subline="colmeias perdidas — mas o total subiu 6%",
                caption_chunks=["O dado que {ninguém} explicou", "está no relatório original"],
                source_tag="USDA 2025",
            ),
            DocSceneSpec(
                style="visual_investigation",
                duration=1.8,
                headline="Hindenburg · 4 Minutos e 32 Segundos",
                location_code="LAKEHURST · NJ · 1937-05-06",
                source_tag="NARA · 1937",
                clock_start_sec=272.0,
                fact_claim="Relatório inicial apontou falha externa.",
                fact_verdict="5 fontes apontam ignição na célula 4.",
                caption_chunks=["Cinco registros sincronizados no mesmo relógio."],
                transition_in="flash",
            ),
            DocSceneSpec(
                style="newsreel_1920s",
                duration=1.5,
                headline="ALERTA DO CHARLESTON!",
                subline="Jornais de 1926 dizem que a dança ameaça os joelhos",
                transition_in="iris",
            ),
            DocSceneSpec(
                style="constructivist_montage",
                duration=1.4,
                headline="410 DIAS DE OBRA",
                subline="UM ANDAR A CADA QUATRO DIAS",
                highlight_number=102,
                number_suffix=" ANDARES",
                transition_in="red_wipe",
            ),
            DocSceneSpec(
                style="broadcast_news_package",
                duration=1.4,
                headline="A SEMANA EM INTELIGÊNCIA ARTIFICIAL",
                subline="Modelos abertos aceleram estúdios locais em CPU",
                location_code="SÃO PAULO · BR",
                source_tag="RELATÓRIO Q4",
                highlight_number=91.1,
                number_suffix="%",
                transition_in="cut",
            ),
            DocSceneSpec(
                style="live_countdown_split",
                duration=1.4,
                headline="TORRE DE CONTROLE",
                subline="PLATAFORMA 39A",
                countdown_from_sec=10.0,
                transition_in="flash",
            ),
            DocSceneSpec(
                style="sports_telestrator",
                duration=1.4,
                headline="FREEZE FRAME · ÂNGULO DE IMPACTO",
                subline="Deslocamento lateral de 4,2 m em 0,8 s",
                focus_point=(0.35, 0.58),
                target_point=(0.74, 0.36),
                transition_in="cut",
            ),
            DocSceneSpec(
                style="city_symphony",
                duration=1.4,
                headline="06:14 — A cidade acorda em ritmo próprio",
                location_code="06:14 AM · MANHATTAN",
                transition_in="cut",
            ),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="FrimeRise Station 01: Edit & Documentary Engine")
    parser.add_argument("--spec", type=str, help="JSON de episódio (DocStation01Spec)")
    parser.add_argument("--audio", type=str, default=None, help="Áudio de narração/mix opcional")
    parser.add_argument("--output", type=str, default="station01_out.mp4", help="Arquivo MP4 final")
    parser.add_argument("--demo", action="store_true", help="Renderiza showcase com os 8 estilos em 720p")
    parser.add_argument("--no-vaapi", action="store_true", help="Força libx264 em CPU")
    args = parser.parse_args()

    if args.demo or not args.spec:
        spec = build_station01_demo()
    else:
        with open(args.spec, "r", encoding="utf-8") as fh:
            spec = DocStation01Spec.from_dict(json.load(fh))

    out = Station01Renderer(spec, prefer_vaapi=not args.no_vaapi).render(args.output, audio_path=args.audio)
    print(f"[Station01Renderer] Concluído ({len(spec.scenes)} cenas): {out}")


if __name__ == "__main__":
    main()