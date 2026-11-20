"""FrimeRise 2D Cartoon / Paint Explainer Animation Studio (100% CPU Skia C++ + QuickSync iHD).
Features:
  - Pydantic CartoonEpisodePlan schema (multi-character cast, voices, rigs, scenes, camera shots)
  - Modular expressive 2D Vector Puppet Rigging (StrokeWidth=8, articulated arms, head Squash & Stretch,
    3.2s natural eye blinking, 6 emotional eye/eyebrow states, automatic accessories)
  - Real-time 6-Viseme Lip-Sync driven by 33ms numpy RMS audio envelope + vowel phoneme alignment
  - Illustrated 2D Backgrounds (Pollinations zero-key cache + instant animated Skia vector backdrops:
    rocking boat, sinusoidal ocean waves, rain, lightning, giant whale, desert sun, palace, office, street)
  - Supports BOTH Vertical 9:16 (1080x1920 Shorts/TikTok/Reels) and Horizontal 16:9 (1920x1080 YouTube)
  - Distinct multi-character PT-BR voices (edge-tts with per-character pitch/rate + kokoro-onnx)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import subprocess
import urllib.parse
import wave
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import edge_tts
import httpx
import numpy as np
from pydantic import BaseModel, Field
import skia

from agents.llm_router import _extract_json, get_settings, record_token_usage
from agents.retention_doctor import audit_cartoon_episode_plan
from engine.audio_dsp import _estimate_word_timestamps, master_broadcast_audio
from engine.cartoon_v2_renderer import (
    draw_cartoon_puppet_v2,
    draw_comic_speed_lines,
    draw_foreground_boat_v2,
    draw_parallax_scenery_v2,
)
from engine.gemini_tts import has_valid_gemini_key, synthesize_gemini_tts_line
from engine.intel_vaapi import (
    build_video_encode_args,
    get_vaapi_env,
    nice_preexec,
    run_ffmpeg_safe,
    thermal_guard_wait,
)
from engine.rhubarb_lipsync import extract_rhubarb_visemes
from engine.skia_compositor import (
    ACTIVE_PILL_PALETTE,
    _load_verified_typeface,
    group_words_into_chunks,
    hex_to_skia,
)

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
CARTOON_BG_CACHE = BASE_DIR / "data" / "cartoon_bgs"
CARTOON_BG_CACHE.mkdir(parents=True, exist_ok=True)
SKILLS_DIR = BASE_DIR / "skills"


# ---------------------------------------------------------------------------
# 1. Pydantic Schema: CartoonEpisodePlan
# ---------------------------------------------------------------------------
OutfitType = Literal["robe_biblical", "king_crown", "modern_hoodie", "suit_boss", "sailor"]
AccessoryType = Literal["none", "crown", "beard_staff", "tie", "cap", "halo", "sword", "clipboard"]
EmotionType = Literal["neutral", "angry", "shocked", "laughing", "crying", "smug"]
CameraShotType = Literal["wide_two_shot", "closeup_speaker", "shake_panic"]
SceneEnvType = Literal["sea_storm", "boat_whale", "desert", "palace", "office", "street"]


class VoicePreset(BaseModel):
    engine: Literal["edge", "kokoro"] = "edge"
    voice_id: str = "pt-BR-AntonioNeural"
    pitch: str = "+0Hz"
    rate: str = "+8%"
    kokoro_voice: str = "pm_alex"


class VisualRig(BaseModel):
    skin_color: str = "#F5C6A5"
    outfit: OutfitType = "modern_hoodie"
    accessory: AccessoryType = "none"
    primary_color: str = "#FF2E93"
    secondary_color: str = "#B388FF"
    hair_color: str = "#2A1B12"
    pill_color_index: int = 0


class CartoonCharacter(BaseModel):
    char_id: str
    name: str
    voice_preset: VoicePreset
    visual_rig: VisualRig


class DialogueLine(BaseModel):
    speaker_id: str
    emotion: EmotionType = "neutral"
    line_pt: str


class CartoonScene(BaseModel):
    background_prompt_en: str = "stormy ocean cartoon sea waves wooden boat"
    scene_type: SceneEnvType = "boat_whale"
    camera_shot: CameraShotType = "wide_two_shot"
    weather_fx: List[str] = Field(default_factory=lambda: ["waves", "rain"])
    dialogue_lines: List[DialogueLine]


class CartoonEpisodePlan(BaseModel):
    title: str
    tone: str = "Comédia Nordestina/BR"
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    characters: List[CartoonCharacter]
    scenes: List[CartoonScene]
    hashtags: List[str] = Field(default_factory=lambda: ["#animacao", "#comedia", "#cartoon", "#shorts"])


# ---------------------------------------------------------------------------
# 2. Multi-Character Episode Scriptwriter (LLM + Built-in High-Craft Comedy)
# ---------------------------------------------------------------------------
def _default_comedy_episode(
    topic: str,
    tone: str = "Comédia Nordestina/BR",
    aspect_ratio: Literal["9:16", "16:9"] = "9:16",
    reference_transcript: str = "",
) -> CartoonEpisodePlan:
    """Create a punchy ~25s 2-character dialogue episode guaranteed to hit
    neutral -> shocked -> angry -> laughing/smug with distinct voices & animated scenes.
    """
    t_low = f"{topic} {reference_transcript}".lower()
    is_biblical = any(k in t_low for k in ("jonas", "baleia", "peixe", "bíblia", "biblia", "noé", "noe", "arca", "davi", "golias", "moisés", "moises", "salomão", "rei"))
    is_business = any(k in t_low for k in ("chefe", "dinheiro", "empresa", "venda", "cliente", "trabalho", "finança", "salário", "mercado", "escritório"))

    if is_biblical or not is_business:
        # Viral @animabible7-inspired comedy dialogue (Jonah & the Captain on the rocking boat!)
        clean_title = topic.strip()[:42] if topic.strip() else "Jonas Tentando Fugir de Barco"
        if tone == "Sério Épico":
            lines_s1 = [
                DialogueLine(speaker_id="cap", emotion="neutral", line_pt="O mar estava calmo até você subir nesse navio, forasteiro."),
                DialogueLine(speaker_id="jonas", emotion="smug", line_pt="Relaxa, capitão. Isso é só uma brisa passageira de fim de tarde."),
            ]
            lines_s2 = [
                DialogueLine(speaker_id="cap", emotion="shocked", line_pt="Brisa?! Tem um peixe do tamanho de uma ilha rodeando o casco agora!"),
                DialogueLine(speaker_id="jonas", emotion="angry", line_pt="Tá bom, eu confesso! Eu fugi da missão, mas não precisa gritar comigo!"),
            ]
            lines_s3 = [
                DialogueLine(speaker_id="cap", emotion="angry", line_pt="Então pode ir arrumando as malas porque sua próxima parada é lá embaixo!"),
                DialogueLine(speaker_id="jonas", emotion="laughing", line_pt="Calma aí, capitão! Pelo menos o peixe tem Wi-Fi grátis lá dentro?"),
            ]
        elif tone == "Explicativo Ácido":
            lines_s1 = [
                DialogueLine(speaker_id="cap", emotion="neutral", line_pt="Deixa eu ver se entendi: você comprou passagem pro lado oposto da sua obrigação?"),
                DialogueLine(speaker_id="jonas", emotion="smug", line_pt="Tecnicamente, eu estou fazendo uma gestão estratégica de adiamento."),
            ]
            lines_s2 = [
                DialogueLine(speaker_id="cap", emotion="shocked", line_pt="Cara, o céu abriu um raio e apareceu uma baleia olhando direto pra você!"),
                DialogueLine(speaker_id="jonas", emotion="angry", line_pt="Que exagero! A gente não pode nem tirar férias em paz nesse oceano!"),
            ]
            lines_s3 = [
                DialogueLine(speaker_id="cap", emotion="angry", line_pt="Você vai virar entrega expressa de baleia em três, dois, um!"),
                DialogueLine(speaker_id="jonas", emotion="laughing", line_pt="Beleza, mas vou dar uma estrela pra essa viagem no aplicativo!"),
            ]
        else:  # Comédia Nordestina/BR
            lines_s1 = [
                DialogueLine(speaker_id="cap", emotion="neutral", line_pt="Rapaz, tu tem certeza que essa viagem de barco era mesmo uma boa ideia?"),
                DialogueLine(speaker_id="jonas", emotion="smug", line_pt="Oxe, relaxa capitão! Eu só tô tirando umas férias bem longe de problema."),
            ]
            lines_s2 = [
                DialogueLine(speaker_id="cap", emotion="shocked", line_pt="Eita gota! Olha o tamanho do peixe gigante encarando o nosso barco agora!"),
                DialogueLine(speaker_id="jonas", emotion="angry", line_pt="Ei, para de me olhar assim! Eu já disse que não quero conversa com peixe hoje!"),
            ]
            lines_s3 = [
                DialogueLine(speaker_id="cap", emotion="angry", line_pt="Bora, pula logo na água antes que esse bicho engula o barco inteiro!"),
                DialogueLine(speaker_id="jonas", emotion="laughing", line_pt="Calma homem! Se eu entrar aí dentro, pelo menos o aluguel sai de graça!"),
            ]

        return CartoonEpisodePlan(
            title=clean_title,
            tone=tone,
            aspect_ratio=aspect_ratio,
            characters=[
                CartoonCharacter(
                    char_id="jonas",
                    name="Jonas",
                    voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="+18Hz", rate="+12%", kokoro_voice="pm_alex"),
                    visual_rig=VisualRig(
                        skin_color="#F1C29B",
                        outfit="robe_biblical",
                        accessory="beard_staff",
                        primary_color="#FF2E93",
                        secondary_color="#FFD166",
                        hair_color="#3A2314",
                        pill_color_index=0,
                    ),
                ),
                CartoonCharacter(
                    char_id="cap",
                    name="Capitão",
                    voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="-12Hz", rate="+8%", kokoro_voice="pm_santa"),
                    visual_rig=VisualRig(
                        skin_color="#E6B08A",
                        outfit="sailor",
                        accessory="cap",
                        primary_color="#2563EB",
                        secondary_color="#FFFFFF",
                        hair_color="#1F2937",
                        pill_color_index=1,
                    ),
                ),
            ],
            scenes=[
                CartoonScene(
                    background_prompt_en="sunny turquoise ocean cartoon sea gentle waves",
                    scene_type="boat_whale",
                    camera_shot="wide_two_shot",
                    weather_fx=["waves"],
                    dialogue_lines=lines_s1,
                ),
                CartoonScene(
                    background_prompt_en="dramatic stormy dark ocean lightning storm waves cartoon",
                    scene_type="boat_whale",
                    camera_shot="shake_panic",
                    weather_fx=["waves", "rain", "lightning", "whale_pass"],
                    dialogue_lines=lines_s2,
                ),
                CartoonScene(
                    background_prompt_en="stormy ocean giant whale tail splash cartoon sky",
                    scene_type="boat_whale",
                    camera_shot="closeup_speaker",
                    weather_fx=["waves", "rain", "whale_pass"],
                    dialogue_lines=lines_s3,
                ),
            ],
            hashtags=["#animacao", "#comedia", "#cartoon", "#humorbr", "#shorts"],
        )

    # Business / Modern Office Comedy Dialogue
    clean_title = topic.strip()[:42] or "Reunião de Segunda-Feira"
    return CartoonEpisodePlan(
        title=clean_title,
        tone=tone,
        aspect_ratio=aspect_ratio,
        characters=[
            CartoonCharacter(
                char_id="dev",
                name="Lucas",
                voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-JulioNeural", pitch="+15Hz", rate="+10%", kokoro_voice="pm_alex"),
                visual_rig=VisualRig(
                    skin_color="#F2C6A0",
                    outfit="modern_hoodie",
                    accessory="cap",
                    primary_color="#B388FF",
                    secondary_color="#B8FF01",
                    hair_color="#231815",
                    pill_color_index=0,
                ),
            ),
            CartoonCharacter(
                char_id="boss",
                name="Chefe",
                voice_preset=VoicePreset(engine="edge", voice_id="pt-BR-AntonioNeural", pitch="-12Hz", rate="+8%", kokoro_voice="pm_santa"),
                visual_rig=VisualRig(
                    skin_color="#E8B892",
                    outfit="suit_boss",
                    accessory="tie",
                    primary_color="#1E1B4B",
                    secondary_color="#FF2E93",
                    hair_color="#4B5563",
                    pill_color_index=1,
                ),
            ),
        ],
        scenes=[
            CartoonScene(
                background_prompt_en="modern colorful startup office desk window city view cartoon",
                scene_type="office",
                camera_shot="wide_two_shot",
                weather_fx=[],
                dialogue_lines=[
                    DialogueLine(speaker_id="boss", emotion="neutral", line_pt=f"Lucas, precisamos resolver {clean_title} ainda hoje sem gastar um centavo."),
                    DialogueLine(speaker_id="dev", emotion="shocked", line_pt="Oxe chefe! Você quer resultado de multinacional com orçamento de pastel e caldo de cana?!"),
                ],
            ),
            CartoonScene(
                background_prompt_en="modern office red alert chaotic desk papers flying cartoon",
                scene_type="office",
                camera_shot="shake_panic",
                weather_fx=["lightning"],
                dialogue_lines=[
                    DialogueLine(speaker_id="boss", emotion="angry", line_pt="Não começa com drama! Eu já prometi pro cliente que sai antes do almoço!"),
                    DialogueLine(speaker_id="dev", emotion="smug", line_pt="Calma aí, chefe. Se eu automatizar tudo em cinco minutos, o café fica por sua conta."),
                ],
            ),
            CartoonScene(
                background_prompt_en="bright sunny modern office celebration success window cartoon",
                scene_type="office",
                camera_shot="closeup_speaker",
                weather_fx=[],
                dialogue_lines=[
                    DialogueLine(speaker_id="boss", emotion="laughing", line_pt="Fechado! Salva esse vídeo agora antes que o concorrente copie essa ideia!"),
                ],
            ),
        ],
        hashtags=["#animacao", "#comedia", "#escritorio", "#negocios", "#shorts"],
    )


def generate_cartoon_episode_plan(
    topic: str,
    tone: str = "Comédia Nordestina/BR",
    aspect_ratio: Literal["9:16", "16:9"] = "9:16",
    reference_transcript: str = "",
) -> Tuple[CartoonEpisodePlan, Dict[str, Any]]:
    """Generate a validated CartoonEpisodePlan via LLM (if key configured) or high-craft built-in comedy."""
    settings = get_settings()
    model_choice = settings.get("default_llm") or "gemini-3.5-flash-lite"
    skill_path = SKILLS_DIR / "09_cartoon_comedy_dialogue.md"
    skill_md = skill_path.read_text(encoding="utf-8")[:1200] if skill_path.exists() else ""

    sys_prompt = (
        "Você é roteirista de Animação 2D Cartoon viral no Brasil (estilo @animabible7 e OverSimplified). "
        "Crie um episódio curto (22-32s, 2 personagens, 3 cenas, 5-6 falas engraçadas no total). "
        "Use emoções variadas (neutral, shocked, angry, smug, laughing, crying) e finalize com frase completa. "
        "Responda APENAS JSON válido seguindo exatamente o schema:\n"
        + json.dumps(CartoonEpisodePlan.model_json_schema(), ensure_ascii=False)[:1800]
    )
    user_prompt = (
        f"TEMA: {topic}\nTOM: {tone}\nFORMATO: {aspect_ratio}\n{skill_md}\n"
        + (f"REFERÊNCIA CLONADA (reconte original):\n{reference_transcript[:700]}" if reference_transcript else "")
    )

    gkey = (settings.get("gemini_api_key") or "").strip()
    dkey = (settings.get("deepseek_api_key") or "").strip()
    order = ["deepseek", "gemini"] if "deepseek" in model_choice else ["gemini", "deepseek"]

    for prov in order:
        if prov == "gemini" and gkey:
            for gm in (model_choice, "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
                if "gemini" not in gm:
                    continue
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                    r = httpx.post(
                        url,
                        headers={"x-goog-api-key": gkey},
                        json={
                            "system_instruction": {"parts": [{"text": sys_prompt}]},
                            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 1200, "responseMimeType": "application/json"},
                        },
                        timeout=22.0,
                    )
                    if r.status_code == 200:
                        j = r.json()
                        txt = j["candidates"][0]["content"]["parts"][0]["text"]
                        plan, doc_rep = audit_cartoon_episode_plan(CartoonEpisodePlan.model_validate(_extract_json(txt)))
                        plan.aspect_ratio = aspect_ratio
                        meta = j.get("usageMetadata", {})
                        pt = int(meta.get("promptTokenCount", 700))
                        ct = int(meta.get("candidatesTokenCount", 450))
                        record_token_usage("gemini", gm, pt, ct, 0, 0.0002)
                        return plan, {"provider": gm, "tokens_used": pt + ct, "cost_usd": 0.0002, "retention_audit": doc_rep}
                except Exception:
                    continue

        if prov == "deepseek" and dkey:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=dkey, base_url="https://api.deepseek.com")
                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                    temperature=0.8,
                    max_tokens=1100,
                    response_format={"type": "json_object"},
                )
                plan, doc_rep = audit_cartoon_episode_plan(CartoonEpisodePlan.model_validate(_extract_json(resp.choices[0].message.content or "{}")))
                plan.aspect_ratio = aspect_ratio
                u = resp.usage
                pt = int(getattr(u, "prompt_tokens", 700))
                ct = int(getattr(u, "completion_tokens", 450))
                record_token_usage("deepseek", "deepseek-flash", pt, ct, 0, 0.0002)
                return plan, {"provider": "deepseek-flash", "tokens_used": pt + ct, "cost_usd": 0.0002, "retention_audit": doc_rep}
            except Exception:
                continue

    plan, doc_rep = audit_cartoon_episode_plan(_default_comedy_episode(topic, tone=tone, aspect_ratio=aspect_ratio, reference_transcript=reference_transcript))
    return plan, {"provider": "cartoon_comedy_engine", "tokens_used": 0, "cost_usd": 0.0, "retention_audit": doc_rep}


# ---------------------------------------------------------------------------
# 3. Multi-Character TTS Synthesis (Gemini Expressive TTS + Edge-TTS Fallback)
# ---------------------------------------------------------------------------
_EMOTION_ACTING_HINTS = {
    "shocked": "with startled, comic panic and energetic Brazilian Portuguese inflection",
    "angry": "with dramatic, outraged, humorous cartoon anger in Brazilian Portuguese",
    "laughing": "cheerfully with an amused, warm, playful Brazilian Portuguese tone",
    "smug": "with sarcastic, confident, witty Brazilian Portuguese comedic timing",
    "crying": "with exaggerated dramatic whiny comedy emotion in Brazilian Portuguese",
    "neutral": "with lively, natural, expressive Brazilian Portuguese storytelling energy",
}


def _pick_gemini_voice_for_character(voice_preset: VoicePreset, speaker_slot: int = 0) -> str:
    vid = (voice_preset.voice_id or "").lower()
    if any(k in vid for k in ("francisca", "thalita", "dora", "kore", "aoede", "zephyr", "leda")):
        return "Kore" if speaker_slot % 2 == 0 else "Aoede"
    pitch_str = str(voice_preset.pitch or "+0Hz")
    if pitch_str.startswith("-"):
        return "Charon"
    if speaker_slot % 2 == 0:
        return "Puck"
    return "Fenrir"


async def _synthesize_character_line(
    text: str,
    voice_preset: VoicePreset,
    work_dir: Path,
    tag: str,
    voice_engine: str = "edge",
    emotion: str = "neutral",
    speaker_slot: int = 0,
) -> Tuple[Path, List[Dict[str, Any]], float]:
    """Synthesize a single character dialogue line using Google Gemini Expressive TTS (when selected & valid)
    or Edge-TTS with custom pitch/rate and exact WordBoundary timing.
    """
    mp3_path = work_dir / f"{tag}.mp3"
    wav_path = work_dir / f"{tag}.wav"
    words: List[Dict[str, Any]] = []

    if voice_engine == "gemini_tts":
        has_gkey, gkey = has_valid_gemini_key()
        if has_gkey:
            try:
                g_voice = _pick_gemini_voice_for_character(voice_preset, speaker_slot=speaker_slot)
                acting = _EMOTION_ACTING_HINTS.get(emotion, _EMOTION_ACTING_HINTS["neutral"])
                _, dur_s = await asyncio.to_thread(
                    synthesize_gemini_tts_line,
                    text,
                    wav_path,
                    g_voice,
                    acting,
                    gkey,
                )
                words = _estimate_word_timestamps(text, dur_s)
                return wav_path, words, round(dur_s, 3)
            except Exception as exc:
                print(f"[Cartoon2D] Gemini TTS fallback para Edge-TTS ({tag}): {str(exc)[:100]}", flush=True)

    active_voices = [voice_preset.voice_id, "pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"]
    synthesized = False
    for v_try in active_voices:
        try:
            words = []
            comm = edge_tts.Communicate(
                text=text,
                voice=v_try,
                rate=voice_preset.rate or "+8%",
                pitch=voice_preset.pitch or "+0Hz",
                boundary="WordBoundary",
            )
            chunks = bytearray()
            async for ch in comm.stream():
                if ch.get("type") == "audio":
                    chunks.extend(ch["data"])
                elif ch.get("type") == "WordBoundary":
                    st = float(ch["offset"]) / 10_000_000.0
                    dur = float(ch["duration"]) / 10_000_000.0
                    words.append({"word": str(ch["text"]).strip(), "start": round(st, 3), "end": round(st + max(0.06, dur), 3)})
            if chunks:
                mp3_path.write_bytes(bytes(chunks))
                run_ffmpeg_safe(["ffmpeg", "-y", "-v", "error", "-i", str(mp3_path), "-ac", "2", "-ar", "48000", str(wav_path)])
                synthesized = True
                break
        except Exception:
            continue

    if not synthesized:
        raise RuntimeError(f"Não foi possível sintetizar a fala via Edge-TTS: {text[:40]}")

    with wave.open(str(wav_path), "rb") as wf:
        dur_s = wf.getnframes() / float(wf.getframerate())

    if not words:
        words = _estimate_word_timestamps(text, dur_s)

    return wav_path, words, round(dur_s, 3)


def _compute_visemes_for_wav(
    wav_path: Path,
    words: List[Dict[str, Any]],
    emotion: str,
    fps: int = 30,
) -> Tuple[List[str], List[float]]:
    """Analyze 33ms RMS windows via numpy + active word vowel phonemes to return
    per-frame 6-viseme labels AND normalized speech energy (0..1) for head Squash & Stretch.
    6 Visemes:
      - fechada_neutra
      - fechada_sorriso
      - aberta_media_E
      - aberta_grande_A_com_lingua
      - bico_O_U
      - dentes_raiva
    """
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1)

    win = max(1, int(round(sr / float(fps))))  # 33.3ms window at 30fps
    n_frames = max(1, int(math.ceil(len(pcm) / float(win))))
    rms_vals = np.zeros(n_frames, dtype=np.float32)
    for fi in range(n_frames):
        seg = pcm[fi * win : (fi + 1) * win]
        if len(seg) > 0:
            rms_vals[fi] = float(np.sqrt(np.mean(seg * seg)))

    peak = max(0.05, float(np.percentile(rms_vals, 95)))
    norm_e = np.clip(rms_vals / peak, 0.0, 1.0)

    visemes: List[str] = []
    energies: List[float] = []
    for fi in range(n_frames):
        t = fi / float(fps)
        e = float(norm_e[fi])
        energies.append(e)

        # Find current spoken word & active character inside the word for vowel shape
        active_ch = ""
        for w in words:
            if w["start"] <= t <= w["end"]:
                wd = re.sub(r"[^a-záéíóúâêôãõç]", "", w["word"].lower())
                if wd:
                    frac = (t - w["start"]) / max(0.05, w["end"] - w["start"])
                    active_ch = wd[min(len(wd) - 1, int(frac * len(wd)))]
                break

        if e < 0.14:
            if emotion in ("laughing", "smug"):
                visemes.append("fechada_sorriso")
            elif emotion == "angry":
                visemes.append("dentes_raiva")
            else:
                visemes.append("fechada_neutra")
        elif emotion == "angry" and e < 0.52 and fi % 3 == 0:
            visemes.append("dentes_raiva")
        elif active_ch in ("o", "ó", "ô", "õ", "u", "ú"):
            visemes.append("bico_O_U")
        elif e >= 0.56 or active_ch in ("a", "á", "â", "ã"):
            visemes.append("aberta_grande_A_com_lingua")
        elif e >= 0.28 or active_ch in ("e", "é", "ê", "i", "í"):
            visemes.append("aberta_media_E")
        else:
            visemes.append("fechada_sorriso" if emotion == "laughing" else "aberta_media_E")

    return visemes, energies


# ---------------------------------------------------------------------------
# 4. Illustrated 2D Backgrounds (Pollinations Cache + Rich Skia Vector Art)
# ---------------------------------------------------------------------------
def _fetch_pollinations_bg(prompt_en: str, w: int, h: int) -> Optional[skia.Image]:
    """Fetch a free zero-key 2D flat cartoon illustration from Pollinations.ai with disk cache."""
    key = hashlib.sha256(f"{prompt_en}:{w}x{h}".encode("utf-8")).hexdigest()[:16]
    cache_path = CARTOON_BG_CACHE / f"bg_{w}x{h}_{key}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 15_000:
        try:
            return skia.Image.open(str(cache_path))
        except Exception:
            cache_path.unlink(missing_ok=True)

    enc = urllib.parse.quote(f"{prompt_en} 2d flat cartoon background vector art no text")
    url = f"https://image.pollinations.ai/prompt/{enc}?width={w}&height={h}&nologo=true"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code == 200 and len(r.content) > 15_000 and r.headers.get("content-type", "").startswith("image"):
                cache_path.write_bytes(r.content)
                return skia.Image.open(str(cache_path))
    except Exception:
        pass
    return None


def _draw_vector_scenery(
    canvas: skia.Canvas,
    w: int,
    h: int,
    scene_type: str,
    weather_fx: List[str],
    t: float,
    bg_img: Optional[skia.Image],
) -> None:
    """Draw 2D cartoon scenery (illustrated backdrop OR crisp Skia flat vector art) + live weather/props."""
    is_storm = ("rain" in weather_fx) or ("lightning" in weather_fx) or scene_type == "sea_storm"

    if bg_img is not None:
        canvas.drawImageRect(bg_img, skia.Rect.MakeWH(w, h))
        # Subtle atmospheric tint so foreground cartoon puppets always pop cleanly
        tint = skia.ColorSetARGB(75 if is_storm else 32, 12, 10, 28)
        canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=tint))
    else:
        # Crisp Paint-Explainer / Cartoon 2D Vector Backdrop
        sky = skia.Paint()
        if scene_type in ("boat_whale", "sea_storm"):
            c_top = skia.ColorSetARGB(255, 19, 25, 54) if is_storm else skia.ColorSetARGB(255, 56, 189, 248)
            c_bot = skia.ColorSetARGB(255, 45, 55, 92) if is_storm else skia.ColorSetARGB(255, 186, 230, 253)
            sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, h * 0.68)], [c_top, c_bot]))
            canvas.drawRect(skia.Rect.MakeWH(w, h), sky)

            # Cartoon clouds drifting across sky
            cloud_c = skia.ColorSetARGB(235, 72, 82, 118) if is_storm else skia.ColorSetARGB(245, 255, 255, 255)
            cp = skia.Paint(AntiAlias=True, Color=cloud_c)
            cst = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6, Color=skia.ColorSetARGB(255, 18, 16, 30))
            for ci in range(4):
                cx = ((ci * w * 0.34 + t * (24 + ci * 7)) % (w + 260)) - 130
                cy = h * (0.12 + 0.06 * (ci % 2))
                for dx, dy, rad in ((-55, 12, 46), (0, -8, 62), (60, 12, 48)):
                    canvas.drawCircle(cx + dx, cy + dy, rad, cp)
                    canvas.drawCircle(cx + dx, cy + dy, rad, cst)

            # Sun when sunny
            if not is_storm:
                sun_x, sun_y = w * 0.80, h * 0.16
                canvas.drawCircle(sun_x, sun_y, 76, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102)))
                canvas.drawCircle(sun_x, sun_y, 76, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorSetARGB(255, 15, 12, 24)))

        elif scene_type == "desert":
            sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, h * 0.6)], [skia.ColorSetARGB(255, 251, 146, 60), skia.ColorSetARGB(255, 254, 240, 138)]))
            canvas.drawRect(skia.Rect.MakeWH(w, h), sky)
            # Layered golden dunes
            for idx, (y_frac, col) in enumerate([(0.56, (234, 179, 8)), (0.68, (217, 119, 6))]):
                dp = skia.Path()
                dp.moveTo(0, h)
                dp.lineTo(0, h * y_frac)
                for x in range(0, w + 40, 40):
                    dp.lineTo(x, h * y_frac + 48 * math.sin(x * 0.005 + idx * 1.8))
                dp.lineTo(w, h)
                dp.close()
                canvas.drawPath(dp, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, *col)))
                canvas.drawPath(dp, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorSetARGB(255, 30, 18, 10)))

        elif scene_type == "palace":
            sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, h)], [skia.ColorSetARGB(255, 49, 26, 86), skia.ColorSetARGB(255, 26, 14, 48)]))
            canvas.drawRect(skia.Rect.MakeWH(w, h), sky)
            # Marble pillars
            pil_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 232, 222, 200))
            out_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorSetARGB(255, 18, 12, 28))
            for px in (w * 0.08, w * 0.84):
                r = skia.Rect.MakeXYWH(px, h * 0.12, w * 0.09, h * 0.62)
                canvas.drawRect(r, pil_p)
                canvas.drawRect(r, out_p)
            # Royal carpet floor
            floor_r = skia.Rect.MakeXYWH(0, h * 0.72, w, h * 0.28)
            canvas.drawRect(floor_r, skia.Paint(Color=skia.ColorSetARGB(255, 159, 18, 57)))
            canvas.drawLine(0, h * 0.72, w, h * 0.72, out_p)

        elif scene_type == "office":
            canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.ColorSetARGB(255, 224, 231, 255)))
            # Large panoramic window
            win = skia.Rect.MakeXYWH(w * 0.10, h * 0.14, w * 0.80, h * 0.40)
            wp = skia.Paint()
            wp.setShader(skia.GradientShader.MakeLinear([(0, h * 0.14), (0, h * 0.54)], [skia.ColorSetARGB(255, 96, 165, 250), skia.ColorSetARGB(255, 219, 234, 254)]))
            canvas.drawRoundRect(win, 18, 18, wp)
            out_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=8, Color=skia.ColorSetARGB(255, 30, 27, 75))
            canvas.drawRoundRect(win, 18, 18, out_p)
            # Office desk horizon
            desk = skia.Rect.MakeXYWH(0, h * 0.72, w, h * 0.28)
            canvas.drawRect(desk, skia.Paint(Color=skia.ColorSetARGB(255, 146, 98, 60)))
            canvas.drawLine(0, h * 0.72, w, h * 0.72, out_p)

        else:  # street
            sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, h * 0.7)], [skia.ColorSetARGB(255, 30, 27, 75), skia.ColorSetARGB(255, 91, 33, 182)]))
            canvas.drawRect(skia.Rect.MakeWH(w, h), sky)
            out_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorSetARGB(255, 11, 7, 19))
            for bx, bw, bh, col in [(0.04, 0.24, 0.42, (55, 48, 163)), (0.30, 0.26, 0.50, (76, 29, 149)), (0.60, 0.34, 0.44, (49, 46, 129))]:
                rr = skia.Rect.MakeXYWH(w * bx, h * (0.72 - bh), w * bw, h * bh)
                canvas.drawRect(rr, skia.Paint(Color=skia.ColorSetARGB(255, *col)))
                canvas.drawRect(rr, out_p)
            canvas.drawRect(skia.Rect.MakeXYWH(0, h * 0.72, w, h * 0.28), skia.Paint(Color=skia.ColorSetARGB(255, 31, 41, 55)))
            canvas.drawLine(0, h * 0.72, w, h * 0.72, out_p)

    # Animated Ocean, Giant Whale & Rocking Boat for maritime scenes
    if scene_type in ("boat_whale", "sea_storm") or "waves" in weather_fx:
        sea_y = h * 0.67
        # Back ocean wave layer
        back_wave = skia.Path()
        back_wave.moveTo(0, h)
        back_wave.lineTo(0, sea_y)
        for x in range(0, w + 32, 32):
            wy = sea_y + 22 * math.sin(x * 0.012 + t * 3.8)
            back_wave.lineTo(x, wy)
        back_wave.lineTo(w, h)
        back_wave.close()
        sea_dark = skia.ColorSetARGB(255, 15, 76, 129) if is_storm else skia.ColorSetARGB(255, 2, 132, 199)
        canvas.drawPath(back_wave, skia.Paint(AntiAlias=True, Color=sea_dark))
        canvas.drawPath(back_wave, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorSetARGB(255, 10, 15, 32)))

        # Giant cartoon whale / fish rising in the background!
        if "whale_pass" in weather_fx:
            wx = w * 0.78 + 45 * math.sin(t * 1.4)
            wy = sea_y - 40 + 26 * math.sin(t * 2.6)
            canvas.save()
            canvas.translate(wx, wy)
            canvas.rotate(-10 + 7 * math.sin(t * 2.2))
            whale_body = skia.Rect.MakeXYWH(-190, -110, 380, 220)
            canvas.drawOval(whale_body, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 30, 64, 175)))
            canvas.drawOval(whale_body, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=8, Color=skia.ColorSetARGB(255, 10, 14, 28)))
            # Giant cartoon whale eye looking straight at the boat!
            canvas.drawCircle(-95, -24, 28, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            canvas.drawCircle(-95, -24, 28, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6, Color=skia.ColorBLACK))
            canvas.drawCircle(-104, -22, 11, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
            # Big mischievous whale grin
            smile = skia.Path()
            smile.moveTo(-168, 24)
            smile.quadTo(-110, 66, -42, 34)
            canvas.drawPath(smile, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=7, Color=skia.ColorBLACK))
            canvas.restore()

    # Dramatic Lightning flash & diagonal cartoon rain
    if "lightning" in weather_fx and (int(t * 4) % 11 == 0):
        canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.ColorSetARGB(95, 255, 255, 240)))
        bolt = skia.Path()
        bx = w * 0.74
        bolt.moveTo(bx, 0)
        bolt.lineTo(bx - 65, h * 0.16)
        bolt.lineTo(bx + 15, h * 0.19)
        bolt.lineTo(bx - 80, h * 0.38)
        canvas.drawPath(bolt, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=14, Color=skia.ColorSetARGB(255, 255, 245, 130)))

    if "rain" in weather_fx:
        rain_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorSetARGB(145, 186, 230, 253))
        for ri in range(36):
            rx = (ri * 97 + int(t * 520)) % (w + 120) - 60
            ry = (ri * 173 + int(t * 1450)) % (h + 120) - 60
            canvas.drawLine(rx, ry, rx - 18, ry + 54, rain_p)


def _draw_foreground_boat_and_waves(canvas: skia.Canvas, w: int, h: int, scene_type: str, weather_fx: List[str], t: float) -> None:
    """Draw rocking wooden boat hull & front ocean waves IN FRONT of puppet lower torso."""
    if scene_type not in ("boat_whale", "sea_storm") and "waves" not in weather_fx:
        return
    is_storm = ("rain" in weather_fx) or ("lightning" in weather_fx) or scene_type == "sea_storm"
    sea_y = h * 0.67
    rock_deg = math.sin(t * (4.2 if is_storm else 2.2)) * (6.0 if is_storm else 2.5)
    bob_y = math.cos(t * (4.2 if is_storm else 2.2)) * (16.0 if is_storm else 7.0)

    # Rocking wooden boat hull
    canvas.save()
    canvas.translate(w * 0.5, sea_y + 18 + bob_y)
    canvas.rotate(rock_deg)
    hull = skia.Path()
    bw = w * 0.44
    hull.moveTo(-bw, -30)
    hull.lineTo(bw, -30)
    hull.lineTo(bw * 0.78, 130)
    hull.lineTo(-bw * 0.78, 130)
    hull.close()
    canvas.drawPath(hull, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 146, 64, 14)))
    canvas.drawPath(hull, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=9, Color=skia.ColorSetARGB(255, 18, 12, 24)))
    # Horizontal wooden planks
    plank_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=5, Color=skia.ColorSetARGB(180, 78, 34, 8))
    canvas.drawLine(-bw * 0.92, 25, bw * 0.92, 25, plank_p)
    canvas.drawLine(-bw * 0.85, 76, bw * 0.85, 76, plank_p)
    canvas.restore()

    # Front ocean waves overlapping boat bottom
    front_wave = skia.Path()
    front_wave.moveTo(0, h)
    front_wave.lineTo(0, sea_y + 85)
    for x in range(0, w + 28, 28):
        wy = sea_y + 85 + 26 * math.sin(x * 0.015 - t * 4.6)
        front_wave.lineTo(x, wy)
    front_wave.lineTo(w, h)
    front_wave.close()
    sea_front = skia.ColorSetARGB(240, 12, 58, 108) if is_storm else skia.ColorSetARGB(235, 3, 105, 161)
    canvas.drawPath(front_wave, skia.Paint(AntiAlias=True, Color=sea_front))
    canvas.drawPath(front_wave, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=8, Color=skia.ColorSetARGB(255, 10, 15, 32)))


# ---------------------------------------------------------------------------
# 5. Modular 2D Cartoon Puppet Renderer (StrokeWidth=8, 6 Emotions, 6 Visemes)
# ---------------------------------------------------------------------------
def _draw_mouth_viseme(canvas: skia.Canvas, viseme: str, stroke_p: skia.Paint) -> None:
    """Draw one of the 6 cartoon mouth visemes centered at (0, 0) in head coordinates."""
    dark_in = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 74, 14, 28))
    tongue_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 107, 157))
    teeth_p = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)

    if viseme == "fechada_neutra":
        p = skia.Path()
        p.moveTo(-26, 2)
        p.quadTo(0, 10, 26, 0)
        canvas.drawPath(p, stroke_p)

    elif viseme == "fechada_sorriso":
        p = skia.Path()
        p.moveTo(-36, -6)
        p.quadTo(0, 26, 36, -6)
        canvas.drawPath(p, stroke_p)

    elif viseme == "aberta_media_E":
        r = skia.Rect.MakeXYWH(-32, -16, 64, 34)
        canvas.drawRoundRect(r, 16, 16, dark_in)
        # Upper teeth strip
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-24, -14, 48, 10), 4, 4, teeth_p)
        canvas.drawRoundRect(r, 16, 16, stroke_p)

    elif viseme == "aberta_grande_A_com_lingua":
        r = skia.Rect.MakeXYWH(-38, -22, 76, 56)
        canvas.drawRoundRect(r, 26, 26, dark_in)
        # Upper teeth + cute pink cartoon tongue at bottom
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-28, -20, 56, 12), 4, 4, teeth_p)
        canvas.drawOval(skia.Rect.MakeXYWH(-24, 8, 48, 24), tongue_p)
        canvas.drawRoundRect(r, 26, 26, stroke_p)

    elif viseme == "bico_O_U":
        r = skia.Rect.MakeXYWH(-20, -18, 40, 42)
        canvas.drawOval(r, dark_in)
        canvas.drawOval(r, stroke_p)

    else:  # dentes_raiva
        r = skia.Rect.MakeXYWH(-38, -16, 76, 34)
        canvas.drawRoundRect(r, 10, 10, teeth_p)
        canvas.drawRoundRect(r, 10, 10, stroke_p)
        thin = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorBLACK)
        canvas.drawLine(-36, 1, 36, 1, thin)
        for tx in (-18, 0, 18):
            canvas.drawLine(tx, -15, tx, 17, thin)


def _draw_cartoon_puppet(
    canvas: skia.Canvas,
    char: CartoonCharacter,
    cx: float,
    cy: float,
    scale: float,
    facing: int,  # +1 facing right, -1 facing left
    emotion: str,
    viseme: str,
    speech_energy: float,
    is_speaking: bool,
    t: float,
    blink_offset: float = 0.0,
) -> None:
    """Render an articulated, expressive 2D vector cartoon character with StrokeWidth=8."""
    rig = char.visual_rig
    outline = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=8.0,
        StrokeJoin=skia.Paint.kRound_Join,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=skia.ColorSetARGB(255, 16, 12, 24),
    )
    skin_p = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.skin_color))
    prim_p = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.primary_color))
    sec_p = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.secondary_color))
    hair_p = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.hair_color))

    # Idle breathing + speaking energy bounce
    breath = math.sin(t * 2.8 + blink_offset) * 5.0
    speak_bob = -10.0 * speech_energy if is_speaking else 0.0

    canvas.save()
    canvas.translate(cx, cy + breath + speak_bob)
    canvas.scale(scale, scale)

    # 1. Optional Royal Cape behind torso for king_crown
    if rig.outfit == "king_crown":
        cape = skia.Path()
        cape.moveTo(-78, 25)
        cape.lineTo(-125, 250)
        cape.lineTo(125, 250)
        cape.lineTo(78, 25)
        cape.close()
        canvas.drawPath(cape, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 190, 18, 60)))
        canvas.drawPath(cape, outline)

    # 2. Torso (rounded expressive cartoon body)
    torso = skia.Rect.MakeXYWH(-86, 18, 172, 232)
    canvas.drawRoundRect(torso, 56, 56, prim_p)

    # Outfit details clipped nicely over torso
    if rig.outfit == "robe_biblical":
        sash = skia.Path()
        sash.moveTo(-66, 24)
        sash.lineTo(-18, 24)
        sash.lineTo(76, 224)
        sash.lineTo(30, 224)
        sash.close()
        canvas.drawPath(sash, sec_p)
        canvas.drawPath(sash, outline)
    elif rig.outfit == "sailor":
        for sy in (68, 112, 156, 200):
            canvas.drawRect(skia.Rect.MakeXYWH(-80, sy, 160, 18), sec_p)
    elif rig.outfit == "suit_boss":
        # Crisp white V-shirt + bold tie
        shirt = skia.Path()
        shirt.moveTo(-36, 20)
        shirt.lineTo(36, 20)
        shirt.lineTo(0, 128)
        shirt.close()
        canvas.drawPath(shirt, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        canvas.drawPath(shirt, outline)
        tie = skia.Path()
        tie.moveTo(-12, 34)
        tie.lineTo(12, 34)
        tie.lineTo(18, 152)
        tie.lineTo(0, 176)
        tie.lineTo(-18, 152)
        tie.close()
        canvas.drawPath(tie, sec_p)
        canvas.drawPath(tie, outline)
    elif rig.outfit == "modern_hoodie":
        # Hoodie pocket + drawstrings
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-50, 158, 100, 56), 18, 18, sec_p)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-50, 158, 100, 56), 18, 18, outline)
        canvas.drawLine(-20, 32, -20, 108, outline)
        canvas.drawLine(20, 32, 20, 108, outline)

    canvas.drawRoundRect(torso, 56, 56, outline)

    # 3. Articulated Arms + Hands + Props
    def _draw_arm(side: int) -> None:
        # side: -1 left, +1 right
        sx, sy = side * 78.0, 62.0
        if emotion == "shocked":
            ex = side * 124.0
            ey = -22.0 + math.sin(t * 22.0 + side) * 10.0
        elif emotion == "angry":
            ex = side * 136.0
            ey = -10.0 + math.sin(t * 18.0 + side) * 16.0
        elif is_speaking and side == facing:
            ex = side * (138.0 + 22.0 * math.sin(t * 11.0))
            ey = 38.0 - 44.0 * speech_energy + 18.0 * math.cos(t * 9.0)
        elif emotion == "laughing":
            ex = side * 118.0
            ey = 48.0 + math.sin(t * 14.0) * 14.0
        else:
            ex = side * 110.0
            ey = 148.0 + math.sin(t * 2.5 + side) * 6.0

        arm_p = skia.Path()
        arm_p.moveTo(sx, sy)
        arm_p.quadTo(side * 126.0, (sy + ey) * 0.5 + 18.0, ex, ey)
        arm_stroke = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=24.0,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=hex_to_skia(rig.primary_color),
        )
        arm_out = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=38.0,
            StrokeCap=skia.Paint.kRound_Cap,
            Color=skia.ColorSetARGB(255, 16, 12, 24),
        )
        canvas.drawPath(arm_p, arm_out)
        canvas.drawPath(arm_p, arm_stroke)
        # Cartoon hand circle
        canvas.drawCircle(ex, ey, 22, skin_p)
        canvas.drawCircle(ex, ey, 22, outline)

        # Held props on primary side
        if side == -facing and rig.accessory == "beard_staff":
            canvas.drawLine(ex, ey - 180, ex, ey + 140, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=14, StrokeCap=skia.Paint.kRound_Cap, Color=skia.ColorSetARGB(255, 120, 68, 32)))
            canvas.drawLine(ex, ey - 180, ex, ey + 140, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorBLACK))
        elif side == -facing and rig.accessory == "clipboard":
            cb = skia.Rect.MakeXYWH(ex - 26, ey - 46, 52, 68)
            canvas.drawRoundRect(cb, 8, 8, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 245, 158, 11)))
            canvas.drawRoundRect(cb, 8, 8, outline)
        elif side == -facing and rig.accessory == "sword":
            canvas.drawLine(ex, ey, ex + side * 20, ey - 150, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=16, Color=skia.ColorSetARGB(255, 203, 213, 225)))
            canvas.drawLine(ex, ey, ex + side * 20, ey - 150, outline)

    _draw_arm(-1)
    _draw_arm(1)

    # 4. Head with Squash & Stretch on strong speaking syllables (1.06x vertical / 0.96x horizontal)
    sq_y = 1.0 + (0.06 * speech_energy if is_speaking else 0.0)
    sq_x = 1.0 - (0.035 * speech_energy if is_speaking else 0.0)
    head_tilt = (math.sin(t * 7.5) * 4.5 * speech_energy) if is_speaking else (math.sin(t * 1.8) * 1.5)

    canvas.save()
    canvas.translate(0.0, -78.0)
    canvas.rotate(head_tilt)
    canvas.scale(sq_x, sq_y)

    # Floating Halo above head if accessory == halo
    if rig.accessory == "halo":
        halo_r = skia.Rect.MakeXYWH(-68, -158 + math.sin(t * 4) * 5, 136, 30)
        canvas.drawOval(halo_r, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=12, Color=skia.ColorSetARGB(255, 255, 209, 102)))

    # Cartoon Head Circle
    head_r = 104.0
    canvas.drawCircle(0, 0, head_r, skin_p)
    canvas.drawCircle(0, 0, head_r, outline)

    # Hair tuft or biblical hair
    hair_path = skia.Path()
    hair_path.moveTo(-98, -26)
    hair_path.quadTo(-78, -118, 0, -112)
    hair_path.quadTo(82, -118, 98, -26)
    hair_path.quadTo(44, -68, 0, -64)
    hair_path.quadTo(-44, -68, -98, -26)
    hair_path.close()
    canvas.drawPath(hair_path, hair_p)
    canvas.drawPath(hair_path, outline)

    # Beard for biblical rig
    if rig.outfit == "robe_biblical" or rig.accessory == "beard_staff":
        beard = skia.Path()
        beard.moveTo(-88, 22)
        beard.quadTo(-72, 118, 0, 122)
        beard.quadTo(72, 118, 88, 22)
        beard.quadTo(40, 62, 0, 58)
        beard.quadTo(-40, 62, -88, 22)
        beard.close()
        canvas.drawPath(beard, hair_p)
        canvas.drawPath(beard, outline)

    # Headgear: Crown / Baseball Cap / Sailor Hat
    if rig.outfit == "king_crown" or rig.accessory == "crown":
        crown = skia.Path()
        crown.moveTo(-74, -84)
        crown.lineTo(-84, -152)
        crown.lineTo(-32, -116)
        crown.lineTo(0, -166)
        crown.lineTo(32, -116)
        crown.lineTo(84, -152)
        crown.lineTo(74, -84)
        crown.close()
        canvas.drawPath(crown, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102)))
        canvas.drawPath(crown, outline)
        canvas.drawCircle(0, -114, 10, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 46, 147)))
    elif rig.outfit == "sailor":
        # Classic white cartoon sailor cap
        cap_r = skia.Rect.MakeXYWH(-72, -138, 144, 58)
        canvas.drawRoundRect(cap_r, 26, 26, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        canvas.drawRoundRect(cap_r, 26, 26, outline)
        canvas.drawRect(skia.Rect.MakeXYWH(-70, -96, 140, 18), skia.Paint(Color=skia.ColorSetARGB(255, 37, 99, 235)))
        canvas.drawRect(skia.Rect.MakeXYWH(-70, -96, 140, 18), outline)
    elif rig.accessory == "cap":
        cap_r = skia.Rect.MakeXYWH(-86, -124, 172, 54)
        canvas.drawRoundRect(cap_r, 28, 28, sec_p)
        canvas.drawRoundRect(cap_r, 28, 28, outline)
        visor = skia.Rect.MakeXYWH(facing * 10 - 16, -84, 96, 18) if facing > 0 else skia.Rect.MakeXYWH(-96, -84, 96, 18)
        canvas.drawRoundRect(visor, 9, 9, prim_p)
        canvas.drawRoundRect(visor, 9, 9, outline)

    # 5. Living Eyes + Automatic 3.2s Blink + 6 Emotional Eyebrow States
    look_x = facing * 12.0
    is_blinking = ((t + blink_offset) % 3.2) < 0.13
    eye_y = -14.0
    eye_xs = (-36.0 + look_x * 0.4, 36.0 + look_x * 0.4)

    for idx_e, ex in enumerate(eye_xs):
        if emotion == "laughing":
            arc = skia.Path()
            arc.moveTo(ex - 20, eye_y + 4)
            arc.quadTo(ex, eye_y - 22, ex + 20, eye_y + 4)
            canvas.drawPath(arc, outline)
        elif is_blinking:
            canvas.drawLine(ex - 20, eye_y, ex + 20, eye_y, outline)
        else:
            er = 23.0 if emotion == "shocked" else 20.0
            canvas.drawCircle(ex, eye_y, er, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            canvas.drawCircle(ex, eye_y, er, outline)
            pr = 6.5 if emotion == "shocked" else 10.5
            px = ex + facing * 6.0
            canvas.drawCircle(px, eye_y, pr, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
            # Cute white eye highlight sparkle
            canvas.drawCircle(px - 3, eye_y - 4, 3.5, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            # Half-closed smug eyelid
            if emotion == "smug":
                lid = skia.Rect.MakeXYWH(ex - er, eye_y - er, er * 2, er * 0.95)
                canvas.drawRect(lid, skin_p)
                canvas.drawLine(ex - er, eye_y - 1, ex + er, eye_y - 1, outline)

            # Animated cartoon crying tears
            if emotion == "crying":
                tear_y = eye_y + 24 + ((t * 110 + idx_e * 25) % 52)
                canvas.drawOval(skia.Rect.MakeXYWH(ex - 7, tear_y, 14, 24), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(230, 56, 189, 248)))

    # Expressive Eyebrows
    brow_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=9.0, StrokeCap=skia.Paint.kRound_Cap, Color=skia.ColorSetARGB(255, 20, 14, 28))
    lx, rx = eye_xs
    if emotion == "angry":
        canvas.drawLine(lx - 24, eye_y - 36, lx + 20, eye_y - 18, brow_p)
        canvas.drawLine(rx - 20, eye_y - 18, rx + 24, eye_y - 36, brow_p)
        # Classic comic pulsing anger mark on forehead
        am_p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=6, Color=skia.ColorSetARGB(255, 255, 46, 100))
        canvas.drawLine(54, -68, 66, -54, am_p)
        canvas.drawLine(76, -68, 64, -54, am_p)
    elif emotion == "shocked":
        canvas.drawLine(lx - 20, eye_y - 44, lx + 20, eye_y - 48, brow_p)
        canvas.drawLine(rx - 20, eye_y - 48, rx + 20, eye_y - 44, brow_p)
        # Sliding blue cartoon sweat drop on temple
        sw_y = -58 + ((t * 50) % 24)
        drop = skia.Path()
        drop.moveTo(-82, sw_y - 18)
        drop.quadTo(-66, sw_y + 12, -82, sw_y + 18)
        drop.quadTo(-98, sw_y + 12, -82, sw_y - 18)
        drop.close()
        canvas.drawPath(drop, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 56, 189, 248)))
        canvas.drawPath(drop, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4, Color=skia.ColorBLACK))
    elif emotion == "crying":
        canvas.drawLine(lx - 22, eye_y - 24, lx + 18, eye_y - 40, brow_p)
        canvas.drawLine(rx - 18, eye_y - 40, rx + 22, eye_y - 24, brow_p)
    elif emotion == "smug":
        canvas.drawLine(lx - 20, eye_y - 26, lx + 20, eye_y - 26, brow_p)
        canvas.drawLine(rx - 20, eye_y - 36, rx + 22, eye_y - 44, brow_p)
    else:
        canvas.drawLine(lx - 20, eye_y - 32, lx + 20, eye_y - 34, brow_p)
        canvas.drawLine(rx - 20, eye_y - 34, rx + 20, eye_y - 32, brow_p)

    # 6. Lip-Sync Mouth (6 Visemes)
    canvas.save()
    canvas.translate(look_x * 0.45, 42.0)
    _draw_mouth_viseme(canvas, viseme, outline)
    canvas.restore()

    canvas.restore()  # end head
    canvas.restore()  # end puppet


# ---------------------------------------------------------------------------
# 6. Complete Cartoon 2D Episode Render Pipeline
# ---------------------------------------------------------------------------
async def render_cartoon_episode(
    plan: CartoonEpisodePlan,
    work_dir: Path,
    out_master_mp4: Path,
    music_mp3: Optional[Path] = None,
    fps: int = 30,
    voice_engine: str = "gemini_tts",
    thermal_limit_c: float = 85.0,
    progress_cb=None,
) -> Dict[str, Any]:
    """Synthesize all multi-character dialogue voices (Gemini Expressive TTS or Edge-TTS),
    compute Rhubarb v1.14 9-viseme phonetic lip-sync, render 30/60fps Cartoon Studio v2
    (8fps hand-drawn line boil, cel-shading, 2-segment IK arms, 2.5D parallax, speed-lines)
    in C++ Skia, and encode via Intel QuickSync iHD.
    """
    fps = 60 if int(fps) >= 60 else 30
    work_dir.mkdir(parents=True, exist_ok=True)
    w, h = (1920, 1080) if plan.aspect_ratio == "16:9" else (1080, 1920)
    char_map = {c.char_id: c for c in plan.characters}
    char_slot_map = {c.char_id: idx for idx, c in enumerate(plan.characters)}
    if len(plan.characters) < 2:
        raise ValueError("CartoonEpisodePlan precisa de ao menos 2 personagens.")

    # 1. Synthesize each dialogue line with its own distinct expressive character voice
    timeline_events: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    audio_parts: List[Path] = []
    sfx_events: List[Tuple[Path, float, float]] = []
    sfx_dir = ASSETS_DIR / "sfx"

    cursor_t = 0.0
    pause_gap_s = 0.22
    gap_wav = work_dir / "_gap.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{pause_gap_s:.2f}", str(gap_wav)]
    )

    lipsync_engine = "rhubarb_v1.14_phonetic_9visemes"
    line_idx = 0
    for s_idx, scene in enumerate(plan.scenes):
        if s_idx > 0:
            sfx_events.append((sfx_dir / "whoosh_fast.wav", max(0.0, cursor_t - 0.08), 0.34))
        for dl in scene.dialogue_lines:
            char = char_map.get(dl.speaker_id, plan.characters[0])
            sp_slot = char_slot_map.get(char.char_id, 0)
            wav_p, words, dur = await _synthesize_character_line(
                dl.line_pt,
                char.voice_preset,
                work_dir,
                f"dlg_{line_idx:03d}_{char.char_id}",
                voice_engine=voice_engine,
                emotion=dl.emotion,
                speaker_slot=sp_slot,
            )
            visemes, energies, lipsync_engine = await asyncio.to_thread(
                extract_rhubarb_visemes, wav_p, fps, dl.emotion
            )

            # Offset word timestamps onto master timeline
            for wd in words:
                all_words.append(
                    {
                        "word": wd["word"],
                        "start": round(cursor_t + wd["start"], 3),
                        "end": round(cursor_t + wd["end"], 3),
                        "speaker_pill": char.visual_rig.pill_color_index,
                    }
                )

            if dl.emotion in ("shocked", "angry"):
                sfx_events.append((sfx_dir / "pop_bubble.wav", cursor_t + 0.03, 0.32))
            if scene.camera_shot == "shake_panic" and dl.emotion == "shocked":
                sfx_events.append((sfx_dir / "sub_boom.wav", cursor_t + 0.05, 0.36))

            timeline_events.append(
                {
                    "scene_idx": s_idx,
                    "scene": scene,
                    "speaker_id": char.char_id,
                    "emotion": dl.emotion,
                    "start": cursor_t,
                    "end": cursor_t + dur + pause_gap_s,
                    "speech_end": cursor_t + dur,
                    "visemes": visemes,
                    "energies": energies,
                }
            )
            audio_parts.append(wav_p)
            audio_parts.append(gap_wav)
            cursor_t += dur + pause_gap_s
            line_idx += 1

    # Concatenate all character WAV tracks cleanly
    concat_txt = work_dir / "dialogue_concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in audio_parts), encoding="utf-8")
    raw_dialogue_wav = work_dir / "dialogue_full.wav"
    run_ffmpeg_safe(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(raw_dialogue_wav)]
    )

    if progress_cb:
        progress_cb(38, f"Vozes ({voice_engine}) + Rhubarb 9-Visemas prontos ({cursor_t:.1f}s @ {fps}fps)")

    # 2. Master Broadcast Audio (-14 LUFS + 0.40s clean tail + smooth fadeout)
    master_audio = work_dir / "cartoon_master.m4a"
    master_audio, final_dur = await asyncio.to_thread(
        master_broadcast_audio,
        raw_dialogue_wav,
        music_mp3,
        sfx_events,
        master_audio,
        cursor_t,
        0.15,
        0.40,
    )

    if progress_cb:
        progress_cb(52, f"Animando Cartoon Studio v2 (Line Boil 8fps + Paralaxe 2.5D | {w}x{h} @ {fps}fps + QuickSync iHD)...")

    # 4. Render 30fps Cartoon 2D Animation in C++ Skia -> BGRA Pipe -> FFmpeg QuickSync iHD
    caption_tf, font_info = _load_verified_typeface("Montserrat-Black.ttf", role="cartoon_caption")
    chunks = group_words_into_chunks(all_words, max_words=3)
    surface = skia.Surface(w, h)
    total_frames = max(1, int(math.ceil(final_dur * fps)))

    pre_args, enc_args, hw_suffix = build_video_encode_args(qp=19)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        *pre_args,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(master_audio),
        "-vf",
        hw_suffix,
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-t",
        f"{final_dur:.3f}",
        *enc_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out_master_mp4),
    ]

    thermal_guard_wait(limit_c=thermal_limit_c)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=get_vaapi_env(),
        preexec_fn=nice_preexec,
    )
    assert proc.stdin is not None

    left_char = plan.characters[0]
    right_char = plan.characters[1]
    base_caption_size = 76.0 if plan.aspect_ratio == "9:16" else 64.0
    caption_font = skia.Font(caption_tf, base_caption_size)
    space_w = max(28.0, float(caption_font.measureText(" ")) * 1.45)
    fm = caption_font.getMetrics()
    ascent = abs(float(fm.fAscent))
    descent = abs(float(fm.fDescent))

    try:
        for fi in range(total_frames):
            t = fi / float(fps)
            # Identify active dialogue event
            ev = timeline_events[-1]
            for cand in timeline_events:
                if cand["start"] <= t <= cand["end"]:
                    ev = cand
                    break

            scene: CartoonScene = ev["scene"]
            s_idx = ev["scene_idx"]
            speaker_id = ev["speaker_id"]
            is_within_speech = t <= ev["speech_end"]
            rel_f = int((t - ev["start"]) * fps)
            if is_within_speech and 0 <= rel_f < len(ev["visemes"]):
                active_viseme = ev["visemes"][rel_f]
                active_energy = ev["energies"][rel_f]
            else:
                active_viseme = "fechada_sorriso" if ev["emotion"] in ("laughing", "smug") else "fechada_neutra"
                active_energy = 0.0

            # Reactive emotion for the listening character
            listener_emotion = "neutral"
            if ev["emotion"] == "angry":
                listener_emotion = "shocked"
            elif ev["emotion"] == "shocked":
                listener_emotion = "shocked"
            elif ev["emotion"] == "laughing":
                listener_emotion = "smug"

            c = surface.getCanvas()
            c.clear(skia.ColorSetARGB(255, 11, 7, 19))

            # Camera rig: wide_two_shot / closeup_speaker / shake_panic
            c.save()
            if scene.camera_shot == "shake_panic":
                sx = math.sin(t * 48.0) * 14.0
                sy = math.cos(t * 53.0) * 10.0
                c.translate(w * 0.5 + sx, h * 0.5 + sy)
                c.scale(1.06, 1.06)
                c.translate(-w * 0.5, -h * 0.5)
            elif scene.camera_shot == "closeup_speaker":
                # Keep zoomed camera strictly inside [0..w] canvas bounds (zero edge bars!)
                zoom = 1.24
                max_shift_x = w * (zoom - 1.0) / (2.0 * zoom)
                desired_shift_x = w * (-0.18 if speaker_id == left_char.char_id else 0.18)
                shift_x = max(-max_shift_x, min(max_shift_x, desired_shift_x))
                c.translate(w * 0.5, h * 0.5)
                c.scale(zoom, zoom)
                c.translate(-(w * 0.5 + shift_x), -h * 0.52)

            # 1. Cartoon Studio v2 2.5D Parallax Cel-Shaded Scenery (8fps Line Boil + Weather)
            cam_pan_x = math.sin(t * 0.75) * 42.0 + (-55.0 if speaker_id == left_char.char_id else 55.0) * 0.35
            is_storm_scene = ("rain" in scene.weather_fx) or ("lightning" in scene.weather_fx) or scene.scene_type in ("sea_storm", "storm_closeup")
            draw_parallax_scenery_v2(c, 0, 0, w, h, scene.scene_type, scene.weather_fx, t, cam_pan_x=cam_pan_x)

            # 2. Both 2D Puppets v2 (Organic Bean Head, 2-Tone Cel-Shading, 2-Segment IK Arms, Legs, Rhubarb 9-Visemes!)
            puppet_scale = 1.20 if plan.aspect_ratio == "9:16" else 1.12
            py = h * (0.555 if plan.aspect_ratio == "9:16" else 0.585)
            lx = w * (0.28 if plan.aspect_ratio == "9:16" else 0.30)
            rx = w * (0.72 if plan.aspect_ratio == "9:16" else 0.70)

            boat_bob = math.cos(t * 4.2) * 12.0 if scene.scene_type in ("boat_whale", "sea_storm", "boat_deck") else 0.0
            left_is_sp = (speaker_id == left_char.char_id) and is_within_speech
            right_is_sp = (speaker_id == right_char.char_id) and is_within_speech

            draw_cartoon_puppet_v2(
                c, left_char, lx, py + boat_bob, puppet_scale, +1,
                emotion=ev["emotion"] if speaker_id == left_char.char_id else listener_emotion,
                viseme=active_viseme if left_is_sp else "X",
                speech_energy=active_energy if left_is_sp else 0.0,
                is_speaking=left_is_sp,
                t=t,
                blink_offset=0.0,
                pose="standing",
                dark_storm_lighting=is_storm_scene,
            )
            draw_cartoon_puppet_v2(
                c, right_char, rx, py + boat_bob, puppet_scale, -1,
                emotion=ev["emotion"] if speaker_id == right_char.char_id else listener_emotion,
                viseme=active_viseme if right_is_sp else "X",
                speech_energy=active_energy if right_is_sp else 0.0,
                is_speaking=right_is_sp,
                t=t,
                blink_offset=1.45,
                pose="standing",
                dark_storm_lighting=is_storm_scene,
            )

            # 3. Foreground rocking boat & foaming crest waves (1.25x parallax) + Comic Speed Lines!
            draw_foreground_boat_v2(c, 0, 0, w, h, scene.scene_type, scene.weather_fx, t)
            if scene.camera_shot == "shake_panic" or (ev["emotion"] in ("shocked", "angry") and active_energy > 0.45):
                draw_comic_speed_lines(c, w, h, t, intensity=0.65 if scene.camera_shot == "shake_panic" else 0.42)
            c.restore()

            # 4. Subtle lower-third contrast scrim for floating captions
            scrim = skia.Paint()
            scrim.setShader(
                skia.GradientShader.MakeLinear(
                    [(0, h * 0.72), (0, h)],
                    [skia.ColorSetARGB(0, 11, 7, 19), skia.ColorSetARGB(185, 11, 7, 19)],
                )
            )
            c.drawRect(skia.Rect.MakeXYWH(0, h * 0.72, w, h * 0.28), scrim)

            # 5. Top slim progress bar
            bar_w = max(8.0, w * (t / max(0.01, final_dur)))
            bar_p = skia.Paint(AntiAlias=True)
            bar_p.setShader(skia.GradientShader.MakeLinear([(0, 0), (w, 0)], [hex_to_skia("#FF2E93"), hex_to_skia("#B388FF"), hex_to_skia("#B8FF01")]))
            c.drawRoundRect(skia.Rect.MakeXYWH(0, 0, bar_w, 10), 5, 5, bar_p)

            # 6. Floating Hormozi/Cartoon Captions (ZERO black bar, ZERO overlap, strictly ONE active word pill)
            for ch in chunks:
                if ch["start"] <= t <= ch["end"]:
                    w_list = ch["words"]
                    active_wd = next((wd for wd in reversed(w_list) if wd["start"] <= t <= (wd["end"] + 0.04)), None)
                    pad_x, pad_y = 26.0, 12.0
                    toks = []
                    tot_w = 0.0
                    for wd in w_list:
                        txt = str(wd["word"]).strip().upper()
                        if not txt:
                            continue
                        is_act = wd is active_wd
                        sc = 1.12 if is_act else 1.0
                        tw = float(caption_font.measureText(txt))
                        sw = (tw + pad_x * 2.0) * sc if is_act else tw
                        toks.append({"txt": txt, "w": tw, "sw": sw, "act": is_act, "sc": sc, "pidx": int(wd.get("g_idx", 0))})
                        tot_w += sw
                    if toks:
                        tot_w += space_w * (len(toks) - 1)
                        max_line_w = w * 0.86
                        lscale = min(1.0, max_line_w / max(1.0, tot_w))
                        cap_y = h * (0.83 if plan.aspect_ratio == "9:16" else 0.89)
                        c.save()
                        c.translate(w / 2.0, cap_y)
                        c.scale(lscale, lscale)
                        cx_pos = -tot_w / 2.0
                        pos_map = {}
                        for tk in toks:
                            pos_map[id(tk)] = cx_pos + tk["sw"] / 2.0
                            cx_pos += tk["sw"] + space_w
                        for tk in [x for x in toks if not x["act"]] + [x for x in toks if x["act"]]:
                            c.save()
                            c.translate(pos_map[id(tk)], 0.0)
                            if tk["act"]:
                                c.scale(tk["sc"], tk["sc"])
                                pbg, ptx, (gr, gg, gb, ga) = ACTIVE_PILL_PALETTE[tk["pidx"] % len(ACTIVE_PILL_PALETTE)]
                                pr = skia.Rect.MakeXYWH(-tk["w"] / 2.0 - pad_x, -ascent - pad_y, tk["w"] + pad_x * 2.0, ascent + descent + pad_y * 2.0)
                                pp = skia.Paint(AntiAlias=True, Color=hex_to_skia(pbg))
                                pp.setImageFilter(skia.ImageFilters.DropShadow(0, 6, 16, 16, skia.ColorSetARGB(ga, gr, gg, gb)))
                                c.drawRoundRect(pr, 20, 20, pp)
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, caption_font, skia.Paint(AntiAlias=True, Color=hex_to_skia(ptx)))
                            else:
                                stp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=11.0, StrokeJoin=skia.Paint.kRound_Join, Color=skia.ColorSetARGB(255, 8, 5, 14))
                                stp.setImageFilter(skia.ImageFilters.DropShadow(0, 6, 12, 12, skia.ColorSetARGB(210, 0, 0, 0)))
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, caption_font, stp)
                                c.drawString(tk["txt"], -tk["w"] / 2.0, 0.0, caption_font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                            c.restore()
                        c.restore()
                    break

            proc.stdin.write(surface.makeImageSnapshot().tobytes())
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    stderr = proc.stderr.read() if proc.stderr else b""
    proc.wait(timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"Cartoon2D Skia/FFmpeg encode failed: {stderr.decode(errors='ignore')}")

    return {
        "master_mp4": str(out_master_mp4),
        "master_audio": str(master_audio),
        "words": all_words,
        "duration_s": round(final_dur, 2),
        "aspect_ratio": plan.aspect_ratio,
        "width": w,
        "height": h,
        "fps": fps,
        "voice_engine": voice_engine,
        "lipsync_engine": lipsync_engine,
        "cartoon_engine": "cartoon_studio_v2_line_boil_2.5d",
        "font_verified": font_info,
        "characters_count": len(plan.characters),
        "scenes_count": len(plan.scenes),
    }
