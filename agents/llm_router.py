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
    "gemini-3.8-flash": (0.15, 0.60),
    "gemini-3.5-flash-lite": (0.075, 0.30),
    "gemini-3-flash-preview": (0.15, 0.60),
    "gemini-flash-latest": (0.15, 0.60),
    "gemini-flash-lite-latest": (0.075, 0.30),
    "ollama": (0.0, 0.0),
    "local_template": (0.0, 0.0),
}

_LEGACY_GEMINI_ALIASES = {
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.5-flash": "gemini-3.8-flash",
}


def normalize_llm_model_name(model_name: Optional[str]) -> str:
    m = str(model_name or "gemini-3.8-flash").strip()
    return _LEGACY_GEMINI_ALIASES.get(m, m)

# Static prefix kept byte-identical across calls so DeepSeek / Gemini Context Caching hits >80%
CACHED_SYSTEM_PROMPT = (
    "Você é um Diretor Criativo Sênior de Vídeos Virais e Storytelling Cinematográfico. "
    "Escreva roteiros envolventes respeitando rigorosamente o IDIOMA, a DURAÇÃO ALVO e as DIRETRIZES CRIATIVAS "
    "informados pelo usuário (padrão 25-32s em Português-BR para TikTok, Reels e Shorts). "
    "PROIBIDO incluir termos técnicos, de sistema ou debug (nunca escreva 'Teste A/B', 'Gancho', 'Engine', 'Nicho:'). "
    "Sempre finalize com uma frase completa e conclusiva. Mantenha 'broll_queries' sempre em INGLÊS descritivo para busca de filmagens HD. "
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
    return p.read_text(encoding="utf-8")


def _extract_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("JSON não encontrado na resposta do LLM")
    return json.loads(m.group(0))


def _normalize_language(language: Optional[str]) -> str:
    norm = str(language or "pt_br").strip().lower().replace("-", "_")
    if norm.startswith("en"):
        return "en_us"
    if norm.startswith("es"):
        return "es"
    return "pt_br"


def _compute_duration_plan(target_duration_s: int) -> Tuple[int, int, int, int]:
    """Return (clamped_s, target_words, body_line_count, max_tokens)."""
    sec = max(10, min(1200, int(target_duration_s or 30)))
    target_words = max(28, int(round(sec * 2.55)))
    if sec <= 15:
        n_body = 1
    elif sec <= 22:
        n_body = 2
    elif sec <= 45:
        n_body = 3
    elif sec <= 75:
        n_body = 5
    elif sec <= 120:
        n_body = 7
    else:
        n_body = min(24, max(8, int(round(sec / 14.0))))
    max_tokens = min(3200, max(750, 480 + n_body * 78))
    return sec, target_words, n_body, max_tokens


def _topic_aware_broll_queries(topic: str, niche: str, custom_directives: str = "") -> List[str]:
    """Build descriptive English B-roll / photo queries matched to the user's brand-new topic."""
    blob = f"{topic} {niche} {custom_directives}".lower()
    if any(k in blob for k in ("ia", "ai", "intelig", "vídeo", "video", "algoritm", "tecnolog", "robô", "robo", "future", "2026", "cinema", "edição", "edicao")):
        return [
            "futuristic film editing studio monitors dark",
            "artificial intelligence glowing neural network",
            "cinema camera lens studio neon lighting",
            "creative director working laptop night",
            "digital technology server room lights",
            "modern city skyline neon night aerial",
            "smartphone video production creator hands",
            "holographic data screen futuristic office",
        ]
    if any(k in blob for k in ("natal", "christmas", "macabr", "terror", "horror", "mistér", "mister", "histór", "histor", "lenda", "crime", "sombri")):
        return [
            "dark snowy winter forest night fog",
            "vintage candlelight shadow gothic castle",
            "historic european old town snow night",
            "ancient library archives mystery books",
            "moonlight winter storm mountain shadows",
            "dark foggy street lanterns cinema",
            "old newspaper archive mystery desk",
            "cathedral stained glass dark moody",
        ]
    if any(k in blob for k in ("dinheir", "financ", "banco", "bilh", "milh", "venda", "negóc", "negoc", "mercado", "cripto", "invest", "stock", "money")):
        return [
            "city financial district skyline night aerial",
            "stock market trading monitors chart",
            "modern executive office glass skyscraper",
            "bank vault gold bars finance dark",
            "entrepreneur laptop luxury workspace",
            "economic growth graphs digital screen",
            "luxury architecture sunset aerial",
            "newspaper business headlines closeup",
        ]
    if any(k in blob for k in ("saúd", "saud", "treino", "fitness", "corpo", "mente", "psicolog", "sono", "hábit", "habit", "health", "brain")):
        return [
            "athlete running sunrise urban bridge",
            "human brain glowing neural synapses",
            "morning sunlight coffee calm workspace",
            "modern gym training dramatic lighting",
            "person meditating silhouette sunset",
            "medical laboratory microscope science",
            "healthy food kitchen preparation",
            "city park jogger morning mist",
        ]
    return [
        "city night aerial drone",
        "modern office laptop work",
        "financial growth chart business",
        "neon street cyberpunk night",
        "entrepreneur smartphone coffee",
        "luxury architecture sunset",
        "digital technology server lights",
        "creative film editing studio",
    ]


def _offline_viral_script(
    topic: str,
    skill_id: str,
    niche: str,
    seamless_loop: bool,
    target_duration_s: int = 30,
    language: str = "pt_br",
    custom_directives: str = "",
) -> Dict[str, Any]:
    """High-converting PT-BR / EN-US / ES viral script generator shaped by duration & user directives."""
    lang = _normalize_language(language)
    sec, _, n_body, _ = _compute_duration_plan(target_duration_s)
    clean_topic = topic.strip() or (
        "AI Video Automation" if lang == "en_us" else ("Automatización de Videos con IA" if lang == "es" else "Automação de Vídeos Virais com IA")
    )
    short_title = clean_topic[:42]
    clean_dir = " ".join(str(custom_directives or "").strip().split())

    if lang == "en_us":
        hooks_en = {
            "01_negative_hook": (
                f"Stop getting {clean_topic} wrong if you do not want to lose massive reach every single day!",
                f"97% of creators waste time on {clean_topic} because they miss this one critical shift!",
            ),
            "02_myth_buster": (
                f"Everything you were told about {clean_topic} is already completely outdated!",
                f"The biggest myth about {clean_topic} was just exposed by real numbers!",
            ),
            "03_billionaire_case": (
                f"How one simple move in {clean_topic} multiplied results in record time!",
                f"While competitors slept, this exact play in {clean_topic} took over the market!",
            ),
            "04_reverse_countdown": (
                f"3 secrets about {clean_topic} — and number 1 changes everything!",
                f"Master these 3 pillars of {clean_topic} before everyone else catches up!",
            ),
            "05_breaking_news": (
                f"Just in: this sudden shift in {clean_topic} rewrites the rules starting today!",
                f"Almost nobody noticed, yet {clean_topic} just entered an entirely new era!",
            ),
            "06_hypnotic_story": (
                f"In just 48 hours, one bold decision about {clean_topic} flipped a losing game!",
                f"Nobody believed what happened the moment {clean_topic} hit the screen!",
            ),
            "07_local_business_ad": (
                f"Stop overpaying for weak results when it comes to {clean_topic}!",
                f"The exact system filling schedules for anyone looking for {clean_topic} this week!",
            ),
            "08_seamless_loop": (
                f"...and that is exactly why almost nobody truly masters {clean_topic}!",
                f"...and once you unlock {clean_topic}, your results never look the same again!",
            ),
        }
        hook_a, hook_b = hooks_en.get(skill_id, hooks_en["01_negative_hook"])
        body_pool = [
            f"In the first three seconds, {clean_topic} decides whether viewers stay locked in or scroll past forever.",
            "When visual cuts shift every few seconds with dynamic storytelling, retention skyrockets.",
            f"Top studios already combine real footage, 2.5D depth, and sharp pacing to dominate {clean_topic}.",
            "And here is the catch: what actually separates viral winners from invisible channels?",
            "They cut out slow intros, anchor every claim with visual proof, and keep curiosity open until the final frame.",
            f"When you apply this structure to {clean_topic}, every single second earns attention instead of begging for it.",
            "Instead of relying on generic templates, layering multiple visual libraries builds instant cinema authority.",
            "Track which opening line holds viewers past second ten, and double down on what the audience rewards.",
        ]
        if clean_dir:
            body_pool[min(1, len(body_pool) - 1)] = f"Focus directly on this angle for {clean_topic}: {clean_dir[:110]}."
        closing_line = "Save this video now and put this exact structure to work on your very next upload."
        motion_cards = [
            {
                "type": "bar_chart",
                "title": f"RETENTION • {sec}S TARGET",
                "bars": [
                    {"label": "Basic", "value": 24},
                    {"label": "Edited", "value": 58},
                    {"label": "Cinema Mix", "value": 95},
                ],
            },
            {
                "type": "counter",
                "prefix": "+",
                "target": 340,
                "suffix": "%",
                "label": "RETENTION LIFT",
            },
        ]
        hashtags = ["#viral", "#shorts", "#reels", "#storytelling", "#videomarketing"]
    elif lang == "es":
        hooks_es = {
            "01_negative_hook": (
                f"¡Deja de cometer este error en {clean_topic} si no quieres perder alcance todos los días!",
                f"¡El 97% pierde tiempo en {clean_topic} por ignorar este único detalle clave!",
            ),
            "02_myth_buster": (
                f"¡Todo lo que te dijeron sobre {clean_topic} ya quedó completamente obsoleto!",
                f"¡El mayor mito sobre {clean_topic} acaba de quedar al descubierto con datos reales!",
            ),
            "03_billionaire_case": (
                f"¡Cómo una jugada simple en {clean_topic} multiplicó resultados en tiempo récord!",
                f"¡Mientras la competencia dormía, esta estrategia en {clean_topic} dominó el mercado!",
            ),
            "04_reverse_countdown": (
                f"¡3 secretos sobre {clean_topic} — y el número 1 lo cambia todo!",
                f"¡Domina estos 3 pilares de {clean_topic} y adelántate al 99% del mercado!",
            ),
            "05_breaking_news": (
                f"¡Última hora: este cambio en {clean_topic} redefine las reglas desde hoy!",
                f"¡Casi nadie lo notó, pero {clean_topic} acaba de entrar en una nueva era!",
            ),
            "06_hypnotic_story": (
                f"¡En solo 48 horas, esta decisión sobre {clean_topic} dio vuelta al juego!",
                f"¡Nadie creyó lo que ocurrió cuando {clean_topic} apareció en pantalla!",
            ),
            "07_local_business_ad": (
                f"¡Deja de pagar de más sin resultados cuando se trata de {clean_topic}!",
                f"¡El método que está llenando agendas para quienes buscan {clean_topic} esta semana!",
            ),
            "08_seamless_loop": (
                f"...y es exactamente por eso que casi nadie domina {clean_topic} de verdad!",
                f"...y cuando desbloqueas {clean_topic}, tus resultados nunca vuelven a ser iguales!",
            ),
        }
        hook_a, hook_b = hooks_es.get(skill_id, hooks_es["01_negative_hook"])
        body_pool = [
            f"En los primeros tres segundos, {clean_topic} decide si el algoritmo impulsa tu video o lo frena.",
            "Cuando cada corte cambia de ritmo con subtítulos dinámicos y capas visuales, la atención se dispara.",
            f"Los estudios líderes ya mezclan video real, profundidad 2.5D y gráficos para dominar {clean_topic}.",
            "Pero hay un detalle decisivo: ¿qué separa un video viral de uno que nadie termina de ver?",
            "Eliminar introducciones lentas, mostrar pruebas visuales en cada frase y mantener la tensión activa.",
            f"Al aplicar esta estructura en {clean_topic}, cada segundo retiene a la audiencia de forma natural.",
            "Combinar bibliotecas visuales distintas crea una sensación cinematográfica imposible de ignorar.",
            "Mide qué apertura supera los primeros diez segundos y escala el formato que más responde.",
        ]
        if clean_dir:
            body_pool[min(1, len(body_pool) - 1)] = f"Enfoque clave para {clean_topic}: {clean_dir[:110]}."
        closing_line = "Guarda este video ahora y aplica esta estructura exacta en tu próxima publicación."
        motion_cards = [
            {
                "type": "bar_chart",
                "title": f"RETENCIÓN • META {sec}S",
                "bars": [
                    {"label": "Común", "value": 24},
                    {"label": "Editado", "value": 58},
                    {"label": "Híbrido", "value": 95},
                ],
            },
            {
                "type": "counter",
                "prefix": "+",
                "target": 340,
                "suffix": "%",
                "label": "IMPACTO EN RETENCIÓN",
            },
        ]
        hashtags = ["#viral", "#shorts", "#reels", "#estrategia", "#videoia"]
    else:
        hooks_by_skill = {
            "01_negative_hook": (
                f"Pare agora de errar em {clean_topic} se não quiser perder alcance todos os dias!",
                f"97% das pessoas queimam tempo em {clean_topic} por causa deste único detalhe!",
            ),
            "02_myth_buster": (
                f"Tudo o que te contaram sobre {clean_topic} está completamente ultrapassado!",
                f"A maior mentira sobre {clean_topic} acabou de ser desmascarada com números reais!",
            ),
            "03_billionaire_case": (
                f"Como uma virada simples em {clean_topic} multiplicou os resultados em tempo recorde!",
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
        body_pool = [
            f"Nos primeiros segundos, {clean_topic} decide se o algoritmo entrega seu vídeo ou limita todo o alcance.",
            "Quando você mistura filmagens reais, fotos em 2.5D e ritmo preciso, o cérebro prende a atenção na hora.",
            f"É exatamente esse contraste cinematográfico que transforma {clean_topic} em uma máquina de retenção.",
            "Só que tem um detalhe decisivo: por que a maioria dos criadores trava logo antes da virada?",
            "Eles repetem modelos genéricos sem profundidade visual, enquanto quem domina o formato combina camadas reais e gráficas.",
            f"Ao estruturar {clean_topic} com cortes intencionais e dados visuais limpos, cada segundo sustenta o próximo.",
            "A combinação de trilha sob medida, áudio de estúdio e fotografia de cinema eleva a autoridade instantaneamente.",
            "Quem mede a retenção nos primeiros dez segundos e ajusta o gancho colhe alcance composto toda semana.",
        ]
        if clean_dir:
            body_pool[min(1, len(body_pool) - 1)] = f"Na prática sobre {clean_topic}, destaque exatamente isto: {clean_dir[:110]}."
        closing_line = (
            "Salve este vídeo agora e aplique essa estrutura no seu próximo conteúdo."
            if sec <= 22
            else "Salve este vídeo agora, teste esse mix visual hoje mesmo e veja sua retenção disparar."
        )
        motion_cards = [
            {
                "type": "bar_chart",
                "title": f"RETENÇÃO • ALVO {sec}S",
                "bars": [
                    {"label": "Comum", "value": 24},
                    {"label": "Editado", "value": 58},
                    {"label": "Mix Cinema", "value": 95},
                ],
            },
            {
                "type": "counter",
                "prefix": "+",
                "target": 340,
                "suffix": "%",
                "label": "GANHO DE RETENÇÃO",
            },
        ]
        hashtags = ["#viral", "#shorts", "#reels", "#tiktokbrasil", "#marketingdigital"]

    # Trim or expand body_lines cleanly to match target_duration_s
    body: List[str] = []
    for idx in range(n_body):
        body.append(body_pool[idx % len(body_pool)])

    if sec <= 18:
        # Keep short 15-18s scripts ultra-punchy (~36-46 words total -> ~15-19s audio)
        body = body[:1]

    return {
        "title": short_title,
        "hook_a": hook_a,
        "hook_b": hook_b,
        "body_lines": body,
        "loop_bridge": closing_line,
        "closing_line": closing_line,
        "broll_queries": _topic_aware_broll_queries(clean_topic, niche, clean_dir),
        "motion_cards": motion_cards,
        "hashtags": hashtags,
        "language": lang,
        "target_duration_s": sec,
        "custom_directives": clean_dir,
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
    target_duration_s: int = 30,
    language: str = "pt_br",
    custom_directives: str = "",
) -> Dict[str, Any]:
    """Generate a structured viral script shaped by target duration, language, and custom directives."""
    settings = get_settings()
    model_choice = normalize_llm_model_name(provider_override or settings.get("default_llm") or "gemini-3.8-flash")
    skill_md = load_skill_text(skill_id)
    lang = _normalize_language(language)
    sec, target_words, n_body, max_out_tokens = _compute_duration_plan(target_duration_s)
    clean_dir = " ".join(str(custom_directives or "").strip().split())

    lang_label = {
        "en_us": "English (US)",
        "es": "Español (Latinoamérica)",
    }.get(lang, "Português (Brasil)")

    # Retro-feedback: inject top performing skill insights from SQLite
    top_skills = get_top_performing_skills()[:2]
    feedback_hint = ""
    if top_skills:
        best = top_skills[0]
        feedback_hint = (
            f"\n[RETROALIMENTAÇÃO REAL]: A skill '{best['skill_id']}' lidera com média de "
            f"{int(best['avg_views'])} views e {best['avg_retention']:.1f}% de retenção."
        )

    pace_desc = (
        "ULTRA-CURTO E DIRETO (15-20s, frases curtíssimas de alto impacto)"
        if sec <= 20
        else ("DINÂMICO VIRAL (25-45s)" if sec <= 45 else ("PROFUNDO / STORYTELLING (60-90s)" if sec <= 90 else f"LONGO / DOCUMENTAL ({sec}s, múltiplos atos)"))
    )

    user_prompt = (
        f"TEMA: {topic}\n"
        f"NICHO: {niche}\n"
        f"IDIOMA OBRIGATÓRIO DO ROTEIRO: {lang_label} (escreva 100% de title, hook_a, hook_b, body_lines, closing_line e motion_cards em {lang_label}; mantenha broll_queries em Inglês)\n"
        f"DURAÇÃO ALVO: {sec} segundos — {pace_desc} (~{target_words} palavras no total; gere exatamente {n_body} frase(s) em body_lines e pelo menos {max(6, min(14, n_body + 4))} broll_queries variadas em inglês)\n"
        f"LOOP INFINITO: {'SIM' if seamless_loop else 'NÃO'}\n"
        f"SKILL ATIVA ({skill_id}):\n{skill_md}{feedback_hint}"
    )
    if clean_dir:
        user_prompt += f"\nDIRETRIZES CRIATIVAS DO USUÁRIO (OBEDEÇA RIGOROSAMENTE): {clean_dir[:600]}"
    if reference_transcript:
        user_prompt += f"\nREFERÊNCIA VIRAL (reescreva 100% original e superior):\n{reference_transcript[:900]}"

    def _finalize_script(data: Dict[str, Any]) -> Dict[str, Any]:
        # Guarantee topic-aware English broll_queries even if LLM returned sparse queries
        if not isinstance(data.get("broll_queries"), list) or len(data["broll_queries"]) < 4:
            data["broll_queries"] = _topic_aware_broll_queries(topic, niche, clean_dir)
        # Keep short target scripts compact if LLM over-generated
        if sec <= 20 and isinstance(data.get("body_lines"), list) and len(data["body_lines"]) > 2:
            data["body_lines"] = data["body_lines"][:2]
        data["language"] = lang
        data["target_duration_s"] = sec
        data["custom_directives"] = clean_dir
        return audit_viral_script_dict(data, lang=lang)

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
                    max_tokens=max_out_tokens,
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
                return _finalize_script(data)
            except Exception:
                continue

        if prov == "gemini" and gkey:
            raw_cands = (
                [model_choice, "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3-flash-preview"]
                if "gemini" in model_choice
                else ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3-flash-preview"]
            )
            candidates = list(dict.fromkeys(raw_cands))
            for gm in candidates:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gm}:generateContent"
                    payload = {
                        "system_instruction": {"parts": [{"text": CACHED_SYSTEM_PROMPT}]},
                        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": max_out_tokens, "responseMimeType": "application/json"},
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
                        return _finalize_script(data)
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
                    return _finalize_script(data)
            except Exception:
                continue

    # Deterministic Zero-Cost Local Viral Engine Fallback (Audited by Retention Doctor)
    return _finalize_script(
        _offline_viral_script(
            topic,
            skill_id,
            niche,
            seamless_loop,
            target_duration_s=sec,
            language=lang,
            custom_directives=clean_dir,
        )
    )
