"""FrimeRise Ultra-Low-Token LLM Router (< 1,800 tokens/video with Context Caching).
Supports:
- deepseek-flash (DeepSeek API)
- gemini-3.8-flash / gemini-3.5-flash-lite (Google Gemini API)
- ollama (Local Ollama server)
- Instant PT-BR Viral Script Synthesizer fallback when no API key is configured yet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import OpenAI

from agents.retention_doctor import audit_viral_script_dict
from database import get_settings, get_top_performing_skills, record_token_usage

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"

# Approximate USD per 1M tokens (input, output)
MODEL_PRICING = {
    "deepseek-flash": (0.14, 0.28),
    "deepseek-chat": (0.14, 0.28),
    "gemini-3.8-flash": (0.10, 0.40),
    "gemini-3.5-flash-lite": (0.05, 0.20),
    "ollama": (0.0, 0.0),
    "local_template": (0.0, 0.0),
}

# Static prefix kept byte-identical across calls so DeepSeek / Gemini Context Caching hits >80%
CACHED_SYSTEM_PROMPT = (
    "Você é um Diretor Criativo Sênior de Vídeos Curtos Virais. Escreva roteiros curtos (20-32s) "
    "em Português-BR para TikTok, Reels e Shorts. PROIBIDO incluir termos técnicos, de sistema ou debug "
    "(nunca escreva 'Teste A/B', 'Gancho', 'Engine', 'Nicho:'). Sempre finalize com uma frase completa e conclusiva. "
    "Responda EXCLUSIVAMENTE em JSON válido no esquema:\n"
    '{"title":"Título editorial curto","hook_a":"Frase de abertura A (0-3s)","hook_b":"Frase de abertura alternativa B (0-3s)",'
    '"body_lines":["Frase curta 1.","Frase curta 2.","Frase curta 3."],"closing_line":"Frase final completa e forte.",'
    '"broll_queries":["city night aerial drone","business executive laptop office","stock market trading chart","modern architecture timelapse","smartphone social media hands","creative studio lighting"],'
    '"motion_cards":[{"type":"headline","tag":"DADO REAL","title":"RETENÇÃO 3X MAIOR","subtitle":"Nos primeiros 3 segundos"},'
    '{"type":"bar_chart","title":"IMPACTO NA RETENÇÃO","bars":[{"label":"Comum","value":24},{"label":"Editado","value":56},{"label":"Otimizado","value":94}]},'
    '{"type":"counter","prefix":"+","target":340,"suffix":"%","label":"ALCANCE ORGÂNICO"}],'
    '"hashtags":["#viral","#negocios","#estrategia"]}'
)


def list_skills() -> List[Dict[str, str]]:
    skills = []
    for p in sorted(SKILLS_DIR.glob("*.md")):
        first_line = p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        skills.append({"id": p.stem, "name": first_line, "file": p.name})
    return skills


def load_skill_text(skill_id: str) -> str:
    p = SKILLS_DIR / f"{skill_id}.md"
    if not p.exists():
        p = SKILLS_DIR / "01_negative_hook.md"
    return p.read_text(encoding="utf-8")[:1400]


def _extract_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("JSON não encontrado na resposta do LLM")
    return json.loads(m.group(0))


def _offline_viral_script(topic: str, skill_id: str, niche: str, seamless_loop: bool) -> Dict[str, Any]:
    """High-converting PT-BR viral script generator when user has not entered an LLM key yet."""
    clean_topic = topic.strip() or "Automação de Vídeos Virais com IA"
    short_title = clean_topic[:36]

    hooks_by_skill = {
        "01_negative_hook": (
            f"Pare agora de errar em {clean_topic} se não quiser perder alcance todos os dias!",
            f"97% das pessoas queimam tempo e dinheiro em {clean_topic} por causa deste único detalhe!",
        ),
        "02_myth_buster": (
            f"Tudo o que te contaram sobre {clean_topic} está completamente ultrapassado!",
            f"A maior mentira sobre {clean_topic} acabou de ser desmascarada com números reais!",
        ),
        "03_billionaire_case": (
            f"Como uma virada simples em {clean_topic} multiplicou o faturamento em tempo recorde!",
            f"Enquanto a concorrência dormia, essa estratégia em {clean_topic} dominou o mercado!",
        ),
        "04_reverse_countdown": (
            f"3 segredos sobre {clean_topic} — e o número 1 muda completamente o seu jogo!",
            f"Domine estes 3 pilares de {clean_topic} e saia na frente de 99% do mercado!",
        ),
        "05_breaking_news": (
            f"Acabou de sair: essa mudança em {clean_topic} redefine tudo a partir de hoje!",
            f"Pouca gente percebeu, mas {clean_topic} entrou em uma nova era agora mesmo!",
        ),
        "06_hypnotic_story": (
            f"Em apenas 48 horas, essa decisão sobre {clean_topic} virou um jogo perdido!",
            f"Ninguém acreditou quando o resultado de {clean_topic} apareceu na tela!",
        ),
        "07_local_business_ad": (
            f"Atenção: pare de pagar caro sem resultado quando o assunto é {clean_topic}!",
            f"O método que está lotando a agenda de quem busca {clean_topic} esta semana!",
        ),
        "08_seamless_loop": (
            f"...é exatamente por isso que quase ninguém domina {clean_topic} de verdade!",
            f"...e quando você destrava {clean_topic}, seus resultados nunca mais são os mesmos!",
        ),
    }
    hook_a, hook_b = hooks_by_skill.get(skill_id, hooks_by_skill["01_negative_hook"])

    body = [
        "Nos primeiros três segundos, o algoritmo decide se entrega seu vídeo ou limita todo o alcance.",
        "Quando cada corte muda de cena a cada três segundos com legendas dinâmicas, o cérebro prende a atenção.",
        "É exatamente esse ritmo cinematográfico que transforma vídeos comuns em máquinas de visualizações.",
    ]
    closing_line = (
        "Salve este vídeo agora e aplique essa estrutura no seu próximo conteúdo."
    )

    return {
        "title": short_title,
        "hook_a": hook_a,
        "hook_b": hook_b,
        "body_lines": body,
        "loop_bridge": closing_line,
        "closing_line": closing_line,
        "broll_queries": [
            "city night aerial drone",
            "modern office laptop work",
            "financial growth chart business",
            "neon street cyberpunk night",
            "entrepreneur smartphone coffee",
            "luxury architecture sunset",
            "digital technology server lights",
            "creative film editing studio",
        ],
        "motion_cards": [
            {
                "type": "bar_chart",
                "title": "RETENÇÃO EM 15 SEGUNDOS",
                "bars": [
                    {"label": "Comum", "value": 24},
                    {"label": "Editado", "value": 58},
                    {"label": "Dinâmico", "value": 95},
                ],
            },
            {
                "type": "counter",
                "prefix": "+",
                "target": 340,
                "suffix": "%",
                "label": "GANHO DE RETENÇÃO",
            },
        ],
        "hashtags": ["#viral", "#shorts", "#reels", "#tiktokbrasil", "#marketingdigital"],
        "provider_used": "local_template",
        "tokens_used": 0,
        "cost_usd": 0.0,
    }


def _estimate_cost(model: str, prompt_toks: int, comp_toks: int, cached_toks: int = 0) -> float:
    in_p, out_p = MODEL_PRICING.get(model, (0.10, 0.30))
    billable_in = max(0, prompt_toks - cached_toks) + cached_toks * 0.25
    return round((billable_in / 1_000_000.0) * in_p + (comp_toks / 1_000_000.0) * out_p, 6)


def generate_viral_script(
    topic: str,
    skill_id: str = "01_negative_hook",
    niche: str = "Negócios & IA",
    seamless_loop: bool = True,
    provider_override: Optional[str] = None,
    reference_transcript: str = "",
) -> Dict[str, Any]:
    """Generate a compact structured viral script (<1,800 tokens) with auto-caching & cost tracking."""
    settings = get_settings()
    model_choice = provider_override or settings.get("default_llm") or "gemini-3.5-flash-lite"
    skill_md = load_skill_text(skill_id)

    # Retro-feedback: inject top performing skill insights from SQLite
    top_skills = get_top_performing_skills()[:2]
    feedback_hint = ""
    if top_skills:
        best = top_skills[0]
        feedback_hint = (
            f"\n[RETROALIMENTAÇÃO REAL]: A skill '{best['skill_id']}' lidera com média de "
            f"{int(best['avg_views'])} views e {best['avg_retention']:.1f}% de retenção."
        )

    user_prompt = (
        f"TEMA: {topic}\nNICHO: {niche}\nLOOP INFINITO: {'SIM' if seamless_loop else 'NÃO'}\n"
        f"SKILL ATIVA ({skill_id}):\n{skill_md}{feedback_hint}"
    )
    if reference_transcript:
        user_prompt += f"\nREFERÊNCIA VIRAL (reescreva 100% original e superior):\n{reference_transcript[:900]}"

    # Automatic failover order: preferred provider first, then any other configured key!
    gkey = (settings.get("gemini_api_key") or "").strip()
    dkey = (settings.get("deepseek_api_key") or "").strip()
    order = ["deepseek", "gemini", "ollama"] if "deepseek" in model_choice else (["ollama", "deepseek", "gemini"] if "ollama" in model_choice else ["gemini", "deepseek", "ollama"])

    for prov in order:
        if prov == "deepseek" and dkey:
            try:
                client = OpenAI(api_key=dkey, base_url="https://api.deepseek.com")
                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": CACHED_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                    max_tokens=700,
                    response_format={"type": "json_object"},
                )
                data = _extract_json(resp.choices[0].message.content or "{}")
                u = resp.usage
                pt = int(getattr(u, "prompt_tokens", 600))
                ct = int(getattr(u, "completion_tokens", 350))
                cached = int(getattr(u, "prompt_cache_hit_tokens", 0) or 0)
                cost = _estimate_cost("deepseek-flash", pt, ct, cached)
                record_token_usage("deepseek", "deepseek-flash", pt, ct, cached, cost)
                data.update({"provider_used": "deepseek-flash", "tokens_used": pt + ct, "cost_usd": cost})
                return audit_viral_script_dict(data)
            except Exception:
                continue

        if prov == "gemini" and gkey:
            candidates = [model_choice, "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"] if "gemini" in model_choice else ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
            for gm in candidates:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                    payload = {
                        "system_instruction": {"parts": [{"text": CACHED_SYSTEM_PROMPT}]},
                        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 750, "responseMimeType": "application/json"},
                    }
                    r = httpx.post(url, json=payload, headers={"x-goog-api-key": gkey}, timeout=20.0)
                    if r.status_code == 200:
                        j = r.json()
                        txt = j["candidates"][0]["content"]["parts"][0]["text"]
                        data = _extract_json(txt)
                        meta = j.get("usageMetadata", {})
                        pt = int(meta.get("promptTokenCount", 600))
                        ct = int(meta.get("candidatesTokenCount", 350))
                        cached = int(meta.get("cachedContentTokenCount", 0))
                        cost = _estimate_cost(model_choice, pt, ct, cached)
                        record_token_usage("gemini", gm, pt, ct, cached, cost)
                        data.update({"provider_used": gm, "tokens_used": pt + ct, "cost_usd": cost})
                        return audit_viral_script_dict(data)
                except Exception:
                    continue

        if prov == "ollama":
            ollama_url = (settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
            try:
                r = httpx.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": "llama3.2",
                        "stream": False,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": CACHED_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                    timeout=10.0,
                )
                if r.status_code == 200:
                    j = r.json()
                    data = _extract_json(j["message"]["content"])
                    pt = int(j.get("prompt_eval_count", 500))
                    ct = int(j.get("eval_count", 300))
                    record_token_usage("ollama", "ollama-local", pt, ct, 0, 0.0)
                    data.update({"provider_used": "ollama-local", "tokens_used": pt + ct, "cost_usd": 0.0})
                    return audit_viral_script_dict(data)
            except Exception:
                continue

    # Deterministic Zero-Cost Local Viral Engine Fallback (Audited by Retention Doctor)
    return audit_viral_script_dict(_offline_viral_script(topic, skill_id, niche, seamless_loop))
