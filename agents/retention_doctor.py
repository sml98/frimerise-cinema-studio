"""FrimeRise Anti-Boredom Auditor ("Retention Doctor").
Automatically blocks and rewrites robotic AI clichés ("Em um mundo onde...", "Vamos mergulhar...",
"In a world where...", "Let's dive in...", "En un mundo donde...", etc.) in PT-BR, EN-US, and ES,
and enforces an Open Loop (unresolved question or narrative tension cliffhanger) every ~20 seconds
(15-25s window) across:
  1. Viral / B-Roll scripts (`audit_viral_script_dict`)
  2. 2D Cartoon Episode Plans (`audit_cartoon_episode_plan`)
  3. Netflix / MagnatesMedia Investigative Documentary Plans (`audit_netflix_doc_plan`)
Zero LLM tokens required (100% deterministic high-speed regex + structural pacing engine).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Robotic AI phrases forbidden in any FrimeRise production (PT-BR, EN-US, ES)
FORBIDDEN_AI_CLICHES: List[Tuple[re.Pattern[str], str]] = [
    # PT-BR
    (re.compile(r"\b(em|num)\s+um\s+mundo\s+onde\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Olha o que quase ninguém percebe: "),
    (re.compile(r"\bvamos\s+mergulhar(\s+fundo|\s+nisso|\s+nesse\s+tema)?\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Presta atenção neste detalhe: "),
    (re.compile(r"\bmergulhe\s+conosco\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Veja o que acontece na prática: "),
    (re.compile(r"\bem\s+resumo\b[,:]?\s*", re.IGNORECASE), "O ponto decisivo é simples: "),
    (re.compile(r"\bpara\s+concluir\b[,:]?\s*", re.IGNORECASE), "E o resultado final prova tudo: "),
    (re.compile(r"\bem\s+conclus[aã]o\b[,:]?\s*", re.IGNORECASE), "No fim das contas: "),
    (re.compile(r"\bvale\s+(ressaltar|destacar|lembrar)\s+que\b\s*", re.IGNORECASE), "O segredo é que "),
    (re.compile(r"\b[eé]\s+importante\s+(notar|lembrar|destacar|frisar)\s+que\b\s*", re.IGNORECASE), "Repare que "),
    (re.compile(r"\bsem\s+mais\s+delongas\b[,!.]?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bnos\s+dias\s+de\s+hoje\b[,:]?\s*", re.IGNORECASE), "Hoje, "),
    (re.compile(r"\bno\s+cen[aá]rio\s+atual\b[,:]?\s*", re.IGNORECASE), "Agora mesmo, "),
    (re.compile(r"\bneste\s+v[ií]deo\s+vamos\s+(explorar|descobrir|ver)\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Veja a prova real: "),
    (re.compile(r"\bprepare-se\s+para\s+descobrir\b\s*", re.IGNORECASE), "Veja como "),
    # EN-US
    (re.compile(r"\bin\s+a\s+world\s+where\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Here is what nobody tells you: "),
    (re.compile(r"\blet'?s\s+dive\s+(right\s+|deep\s+)?in(to)?\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Look closely at this: "),
    (re.compile(r"\b(let'?s\s+)?delve\s+into\b\s*", re.IGNORECASE), "Examine "),
    (re.compile(r"\bin\s+summary\b[,:]?\s*", re.IGNORECASE), "The real takeaway is simple: "),
    (re.compile(r"\bto\s+summarize\b[,:]?\s*", re.IGNORECASE), "Here is the bottom line: "),
    (re.compile(r"\bin\s+conclusion\b[,:]?\s*", re.IGNORECASE), "And the final proof changes everything: "),
    (re.compile(r"\bto\s+conclude\b[,:]?\s*", re.IGNORECASE), "Ultimately: "),
    (re.compile(r"\bit\s+is\s+important\s+to\s+(note|remember|highlight)\s+that\b\s*", re.IGNORECASE), "Notice how "),
    (re.compile(r"\bwithout\s+further\s+ado\b[,!.]?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bin\s+today'?s\s+(fast-paced\s+|digital\s+)?(world|age|landscape)\b[,:]?\s*", re.IGNORECASE), "Right now, "),
    (re.compile(r"\bbuckle\s+up\b[,!.]?\s*", re.IGNORECASE), "Watch closely: "),
    # ES
    (re.compile(r"\ben\s+un\s+mundo\s+donde\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Mira lo que casi nadie nota: "),
    (re.compile(r"\bvamos\s+a\s+sumergirnos(\s+en)?\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Fíjate en este detalle: "),
    (re.compile(r"\bsumerj[aá]monos\s+en\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Observa este dato clave: "),
    (re.compile(r"\ben\s+resumen\b[,:]?\s*", re.IGNORECASE), "La clave real es esta: "),
    (re.compile(r"\ben\s+conclusi[oó]n\b[,:]?\s*", re.IGNORECASE), "Al final, la prueba es clara: "),
    (re.compile(r"\bpara\s+concluir\b[,:]?\s*", re.IGNORECASE), "Y el resultado final lo demuestra: "),
    (re.compile(r"\bcabe\s+destacar\s+que\b\s*", re.IGNORECASE), "El secreto es que "),
    (re.compile(r"\bes\s+importante\s+(recordar|notar|destacar)\s+que\b\s*", re.IGNORECASE), "Fíjate que "),
    (re.compile(r"\bsin\s+m[aá]s\s+pre[aá]mbulos\b[,!.]?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bhoy\s+en\s+d[ií]a\b[,:]?\s*", re.IGNORECASE), "Hoy, "),
]

OPEN_LOOP_MARKERS_RE = re.compile(
    r"(\?|"
    r"\bmas\s+o\s+que\s+ningu[eé]m\s+esperava\b|"
    r"\bs[oó]\s+que\s+tem\s+um\s+detalhe\b|"
    r"\bmas\s+espera\s+at[eé]\s+ver\b|"
    r"\be\s+o\s+pior\s+ainda\s+estava\s+por\s+vir\b|"
    r"\bpor\s+que\s+isso\s+acontece\b|"
    r"\bqual\s+[eé]\s+o\s+verdadeiro\s+segredo\b|"
    r"\bat[eé]\s+que\s+um\s+documento\s+revelou\b|"
    r"\bmas\s+havia\s+uma\s+falha\s+fatal\b|"
    r"\bwait\s+until\s+you\s+see\b|"
    r"\bbut\s+what\s+nobody\s+expected\b|"
    r"\bhere\s+is\s+the\s+catch\b|"
    r"\bthe\s+worst\s+was\s+yet\s+to\s+come\b|"
    r"\bbut\s+there\s+was\s+one\s+fatal\s+flaw\b|"
    r"\bpero\s+nadie\s+esperaba\b|"
    r"\blo\s+peor\s+estaba\s+por\s+venir\b|"
    r"\bpero\s+hay\s+un\s+detalle\b)",
    re.IGNORECASE,
)

OPEN_LOOP_SPACING_S = 24.0
SPEECH_WORDS_PER_SEC = 2.05

# Forbidden YouTube ending CTAs banned in ACT_4_ABRUPT_ENDING (v3.0.0 zero-CTA rule)
FORBIDDEN_TRAILING_CTA_RE = re.compile(
    r"(?:"
    r"\b(?:n[aã]o\s+se\s+esque[cç]a\s+de\s+)?(?:deix[ae]r?\s+(?:(?:o|a)\s+)?(?:seu\s+)?like|"
    r"se\s+inscrev(?:a|er)\s+no\s+canal|inscreva-se\s+no\s+canal|"
    r"ativ[ae]r?\s+o\s+sininho|coment[ae]\s+(?:aqui\s+)?embaixo|"
    r"obrigado\s+por\s+assistir|at[eé]\s+o\s+pr[oó]ximo\s+v[ií]deo|"
    r"don'?t\s+forget\s+to\s+subscribe|hit\s+the\s+like\s+button|"
    r"subscribe\s+to\s+(?:the|our)\s+channel|ring\s+the\s+bell|"
    r"thanks\s+for\s+watching|see\s+you\s+in\s+the\s+next\s+video|"
    r"suscr[ií]bete\s+al\s+canal|dale\s+like|gracias\s+por\s+ver)"
    r")[^.!?]*[.!?]*",
    re.IGNORECASE,
)


def strip_abrupt_ending_ctas(text: str) -> Tuple[str, List[str]]:
    """Strip any YouTube outro CTAs from ACT_4_ABRUPT_ENDING narration so the film ends abruptly."""
    cleaned = str(text or "").strip()
    removed: List[str] = []
    for m in FORBIDDEN_TRAILING_CTA_RE.finditer(cleaned):
        hit = m.group(0).strip()
        if hit:
            removed.append(hit)
    if removed:
        cleaned = FORBIDDEN_TRAILING_CTA_RE.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, removed

OPEN_LOOP_BRIDGES_PT = [
    "Mas espera: por que quase todo mundo erra exatamente no próximo passo?",
    "Só que ninguém esperava o que aconteceria logo em seguida: olha só.",
    "Mas aqui surge a pergunta que muda tudo: o que acontece quando você inverte essa regra?",
]

OPEN_LOOP_BRIDGES_EN = [
    "But wait: why does almost everyone miss what happens in the very next step?",
    "Yet nobody expected what was hiding right behind the scenes: look at this.",
    "And that raises the real question: what happens when you flip this rule upside down?",
]

OPEN_LOOP_BRIDGES_ES = [
    "Pero espera: ¿por qué casi todo el mundo falla exactamente en el siguiente paso?",
    "Sin embargo, nadie esperaba lo que ocurriría justo después: mira esto.",
    "Y aquí surge la pregunta que lo cambia todo: ¿qué pasa cuando inviertes esta regla?",
]

OPEN_LOOP_BRIDGES_CARTOON_PT = [
    "Mas espera aí... tu acha mesmo que o problema parou por aí?",
    "Só que ninguém contava com o que ia aparecer bem na nossa frente agora!",
    "Agora me responde uma coisa: quem foi o gênio que teve essa ideia?",
]

OPEN_LOOP_BRIDGES_CARTOON_EN = [
    "Hold on a second... do you really think the trouble stopped there?",
    "Except nobody expected what was about to show up right in front of us!",
    "Now tell me one thing: whose bright idea was this in the first place?",
]

OPEN_LOOP_BRIDGES_CARTOON_ES = [
    "Pero espera un segundo... ¿de verdad crees que el problema terminó ahí?",
    "¡Solo que nadie contaba con lo que iba a aparecer justo frente a nosotros!",
    "Ahora respóndeme una cosa: ¿quién fue el genio que tuvo esta idea?",
]

OPEN_LOOP_BRIDGES_DOC_PT = [
    "Mas havia um detalhe sombrio escondido nos arquivos... por que ninguém fala disso até hoje?",
    "Só que os registros da época revelaram algo ainda mais perturbador: o que realmente aconteceu naquela noite?",
    "E o capítulo seguinte viraria toda essa história do avesso... como esse segredo sobreviveu por tantos séculos?",
]

OPEN_LOOP_BRIDGES_DOC_EN = [
    "Yet one chilling detail remained buried in the archives... why does almost nobody talk about it today?",
    "But period records uncovered something far darker: what really happened behind closed doors that night?",
    "And the next chapter turned the entire legend upside down... how did that secret survive for centuries?",
]

OPEN_LOOP_BRIDGES_DOC_ES = [
    "Pero había un detalle sombrío oculto en los archivos... ¿por qué casi nadie habla de esto hoy?",
    "Sin embargo, los registros de la época revelaron algo más oscuro: ¿qué ocurrió realmente aquella noche?",
    "Y el siguiente capítulo cambiaría toda la historia... ¿cómo sobrevivió ese secreto durante tantos siglos?",
]


def _detect_lang(text_sample: str, explicit_lang: Optional[str] = None) -> str:
    """Resolve language code ('pt_br', 'en_us', 'es') from explicit hint or text heuristics."""
    if explicit_lang:
        norm = explicit_lang.strip().lower().replace("-", "_")
        if norm.startswith("en"):
            return "en_us"
        if norm.startswith("es"):
            return "es"
        if norm.startswith("pt"):
            return "pt_br"

    low = f" {str(text_sample or '').lower()} "
    en_hits = sum(1 for w in (" the ", " and ", " with ", " from ", " that ", " billion ", " million ", " behind ") if w in low)
    es_hits = sum(1 for w in (" el ", " los ", " las ", " una ", " pero ", " para ", " millones ", " donde ") if w in low)
    pt_hits = sum(1 for w in (" que ", " não ", " com ", " para ", " uma ", " bilhão ", " milhões ", " quando ") if w in low)
    if en_hits > pt_hits and en_hits >= es_hits and en_hits >= 1:
        return "en_us"
    if es_hits > pt_hits and es_hits > en_hits and es_hits >= 1:
        return "es"
    return "pt_br"


def _pick_bridge_pool(mode: str, lang: str) -> List[str]:
    if mode == "cartoon":
        return {
            "en_us": OPEN_LOOP_BRIDGES_CARTOON_EN,
            "es": OPEN_LOOP_BRIDGES_CARTOON_ES,
        }.get(lang, OPEN_LOOP_BRIDGES_CARTOON_PT)
    if mode == "netflix_doc":
        return {
            "en_us": OPEN_LOOP_BRIDGES_DOC_EN,
            "es": OPEN_LOOP_BRIDGES_DOC_ES,
        }.get(lang, OPEN_LOOP_BRIDGES_DOC_PT)
    return {
        "en_us": OPEN_LOOP_BRIDGES_EN,
        "es": OPEN_LOOP_BRIDGES_ES,
    }.get(lang, OPEN_LOOP_BRIDGES_PT)


def sanitize_robotic_line(text: str) -> Tuple[str, List[str]]:
    """Strip or replace robotic AI clichés from a single line of text (PT-BR, EN-US, ES)."""
    cleaned = str(text or "").strip()
    removed: List[str] = []
    for pattern, replacement in FORBIDDEN_AI_CLICHES:
        m = pattern.search(cleaned)
        if m:
            removed.append(m.group(0).strip())
            cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned, removed


def _append_bridge(base_text: str, bridge: str) -> str:
    """Join a retention open-loop bridge as a proper new sentence (never ungrammatical ' — Capitalized')."""
    base = str(base_text or "").strip()
    b = str(bridge or "").strip()
    if not base:
        return b
    if not b:
        return base
    core = base.rstrip(" .!?…—–-:")
    if not core:
        return b
    return f"{core}. {b}"


def _estimate_line_seconds(text: str) -> float:
    words = len(str(text or "").split())
    return max(1.8, round(words / SPEECH_WORDS_PER_SEC, 2))


def audit_viral_script_dict(script: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
    """Run Retention Doctor on a standard viral/documentary script dictionary.
    1. Purges all robotic AI clichés from hook_a, hook_b, body_lines, closing_line (PT-BR, EN-US, ES).
    2. Verifies an Open Loop exists every ~24s window (skipping injection if natural '?' loops exist).
    """
    existing_audit = script.get("retention_audit") if isinstance(script.get("retention_audit"), dict) else None
    prev_injected = int(existing_audit.get("open_loops_injected", 0)) if existing_audit else 0
    prev_cliches = int(existing_audit.get("cliches_blocked", 0)) if existing_audit else 0
    prev_examples = list(existing_audit.get("cliches_examples") or []) if existing_audit else []

    cliches_removed: List[str] = []
    open_loops_injected = 0
    open_loops_found = 0

    for key in ("hook_a", "hook_b", "closing_line", "loop_bridge"):
        if script.get(key):
            clean_txt, rem = sanitize_robotic_line(str(script[key]))
            script[key] = clean_txt
            cliches_removed.extend(rem)

    raw_body = list(script.get("body_lines") or [])
    cleaned_body: List[str] = []
    for ln in raw_body:
        c_ln, rem = sanitize_robotic_line(str(ln))
        cliches_removed.extend(rem)
        if c_ln:
            cleaned_body.append(c_ln)

    sample_txt = " ".join([str(script.get("hook_a", "")), *cleaned_body])
    resolved_lang = _detect_lang(sample_txt, lang or script.get("lang"))
    bridges = _pick_bridge_pool("viral", resolved_lang)

    # Check whether the script already contains natural '?' open loops covering its duration
    hook_txt = str(script.get("hook_a", ""))
    all_texts = [hook_txt, *cleaned_body]
    natural_q_count = sum(1 for t in all_texts if "?" in t)
    plan_has_natural_loops = natural_q_count >= 1

    elapsed_s = _estimate_line_seconds(hook_txt) if hook_txt.strip() else 0.0
    since_last_loop_s = 0.0
    if OPEN_LOOP_MARKERS_RE.search(hook_txt):
        open_loops_found += 1
    else:
        since_last_loop_s += elapsed_s

    audited_body: List[str] = []
    for idx, ln in enumerate(cleaned_body):
        dur = _estimate_line_seconds(ln)
        elapsed_s += dur
        since_last_loop_s += dur
        has_loop = bool(OPEN_LOOP_MARKERS_RE.search(ln))
        is_last = len(cleaned_body) > 1 and idx == len(cleaned_body) - 1
        if has_loop:
            open_loops_found += 1
            since_last_loop_s = 0.0
        elif not plan_has_natural_loops and not is_last and (
            since_last_loop_s >= OPEN_LOOP_SPACING_S
            or (idx == 0 and len(cleaned_body) <= 3 and open_loops_found == 0 and natural_q_count == 0)
        ):
            bridge = bridges[open_loops_injected % len(bridges)]
            ln = _append_bridge(ln, bridge)
            open_loops_injected += 1
            open_loops_found += 1
            since_last_loop_s = 0.0
        audited_body.append(ln)

    script["body_lines"] = audited_body
    all_examples = list(dict.fromkeys([*prev_examples, *cliches_removed]))[:5]
    script["retention_audit"] = {
        "doctor": "RetentionDoctor v2",
        "passed": True,
        "lang": resolved_lang,
        "cliches_blocked": prev_cliches + len(cliches_removed),
        "cliches_examples": all_examples,
        "open_loops_total": max(
            open_loops_found,
            int(existing_audit.get("open_loops_total", 0)) if existing_audit else 0,
        ),
        "open_loops_injected": prev_injected + open_loops_injected,
        "estimated_duration_s": round(elapsed_s + (_estimate_line_seconds(script.get("closing_line", "")) if script.get("closing_line") else 0.0), 1),
        "interval_rule": "24s open_loop_spacing (natural-question preserving)",
    }
    return script


def audit_cartoon_episode_plan(plan: Any, lang: Optional[str] = None) -> Tuple[Any, Dict[str, Any]]:
    """Run Retention Doctor on a CartoonEpisodePlan Pydantic object."""
    cliches_removed: List[str] = []
    open_loops_found = 0
    open_loops_injected = 0
    elapsed_s = 0.0
    since_last_loop_s = 0.0

    sample_lines: List[str] = []
    for scene in getattr(plan, "scenes", []):
        for dl in getattr(scene, "dialogue_lines", []):
            sample_lines.append(str(getattr(dl, "line_pt", "")))
    resolved_lang = _detect_lang(" ".join(sample_lines), lang)
    bridges = _pick_bridge_pool("cartoon", resolved_lang)

    natural_q_count = sum(1 for t in sample_lines if "?" in t)
    plan_has_natural_loops = natural_q_count >= 1

    for scene in getattr(plan, "scenes", []):
        for dl in getattr(scene, "dialogue_lines", []):
            clean_txt, rem = sanitize_robotic_line(dl.line_pt)
            cliches_removed.extend(rem)
            dur = _estimate_line_seconds(clean_txt)
            elapsed_s += dur
            since_last_loop_s += dur

            if OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif not plan_has_natural_loops and since_last_loop_s >= OPEN_LOOP_SPACING_S:
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = _append_bridge(clean_txt, bridge)
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0

            dl.line_pt = clean_txt

    # Ensure at least 1 Open Loop exists even in ultra-short <24s cartoons with no natural questions
    if open_loops_found == 0 and natural_q_count == 0 and getattr(plan, "scenes", None) and plan.scenes[0].dialogue_lines:
        first_dl = plan.scenes[0].dialogue_lines[0]
        if "?" not in first_dl.line_pt:
            fallback_q = {
                "en_us": "Wait until you see what happened next!",
                "es": "¿Pero sabes qué pasó justo después?",
            }.get(resolved_lang, "Mas tu sabe o que aconteceu logo depois?")
            first_dl.line_pt = _append_bridge(first_dl.line_pt, fallback_q)
            open_loops_injected += 1
            open_loops_found += 1

    report = {
        "doctor": "RetentionDoctor v2",
        "passed": True,
        "lang": resolved_lang,
        "cliches_blocked": len(cliches_removed),
        "cliches_examples": cliches_removed[:5],
        "open_loops_total": open_loops_found,
        "open_loops_injected": open_loops_injected,
        "estimated_duration_s": round(elapsed_s, 1),
        "interval_rule": "24s open_loop_spacing (natural-question preserving)",
    }
    return plan, report


def audit_netflix_doc_plan(plan: Any, lang: Optional[str] = None) -> Any:
    """Run Retention Doctor on a Netflix / MagnatesMedia Investigative Documentary Plan (`dict` or Pydantic object).
    1. Purges all robotic AI clichés in PT-BR, EN-US, and ES across cold_open, chapters, scenes, and narration lines.
    2. Enforces an investigative Open Loop on >= 24.0s gaps ONLY when the scene/plan lacks natural '?' open loops,
       joining bridges as clean sentences (never ungrammatical ' — Capitalized').
    3. Attaches `retention_audit` telemetry without overwriting prior `open_loops_injected` / `cliches_blocked` on re-call.
    """
    is_dict = isinstance(plan, dict)
    plan_dict: Dict[str, Any] = plan if is_dict else (plan.model_dump() if hasattr(plan, "model_dump") else dict(plan))

    existing_audit = plan_dict.get("retention_audit")
    if not isinstance(existing_audit, dict) and not is_dict:
        existing_audit = getattr(plan, "retention_audit", None)
    if not isinstance(existing_audit, dict):
        existing_audit = None
    prev_injected = int(existing_audit.get("open_loops_injected", 0)) if existing_audit else 0
    prev_cliches = int(existing_audit.get("cliches_blocked", 0)) if existing_audit else 0
    prev_examples = list(existing_audit.get("cliches_examples") or []) if existing_audit else []

    cliches_removed: List[str] = []
    open_loops_found = 0
    open_loops_injected = 0
    elapsed_s = 0.0
    since_last_loop_s = 0.0

    # Sanitize top-level documentary text fields if present
    for top_key in ("cold_open", "hook_a", "hook_b", "closing_line", "loop_bridge", "synopsis", "summary"):
        if plan_dict.get(top_key) and isinstance(plan_dict[top_key], str):
            clean_txt, rem = sanitize_robotic_line(plan_dict[top_key])
            plan_dict[top_key] = clean_txt
            if not is_dict and hasattr(plan, top_key):
                setattr(plan, top_key, clean_txt)
            cliches_removed.extend(rem)

    # Collect text sample & count pre-existing natural '?' open loops across the plan
    scenes = plan_dict.get("scenes") or plan_dict.get("chapters") or plan_dict.get("acts") or []
    sample_chunks: List[str] = [str(plan_dict.get("cold_open") or plan_dict.get("hook_a") or "")]
    narration_keys = ("narration", "text", "line_pt", "voiceover", "script_line", "script", "dialogue")
    scene_texts: List[str] = []
    est_plan_dur = 0.0
    for sc in scenes:
        if isinstance(sc, dict):
            for nk in narration_keys:
                if sc.get(nk):
                    t_sc = str(sc[nk])
                    sample_chunks.append(t_sc)
                    scene_texts.append(t_sc)
                    est_plan_dur += float(sc.get("duration_s") or _estimate_line_seconds(t_sc))
                    break
    body_texts: List[str] = []
    for ln in plan_dict.get("body_lines") or []:
        t_ln = str(ln)
        sample_chunks.append(t_ln)
        body_texts.append(t_ln)
        if not scenes:
            est_plan_dur += _estimate_line_seconds(t_ln)

    resolved_lang = _detect_lang(" ".join(sample_chunks), lang or plan_dict.get("lang"))
    bridges = _pick_bridge_pool("netflix_doc", resolved_lang)

    intro_txt = str(plan_dict.get("cold_open") or plan_dict.get("hook_a") or "")
    if intro_txt:
        est_plan_dur += _estimate_line_seconds(intro_txt)
    all_plan_texts = [t for t in [intro_txt, *scene_texts, *body_texts] if t.strip()]
    natural_q_count = sum(1 for t in all_plan_texts if "?" in t)
    # Skip redundant boilerplate bridge injection when the plan already contains >= 1 natural '?' open loop
    plan_has_natural_loops = natural_q_count >= 1

    # Check if cold_open / hook_a already starts with an open loop
    if intro_txt:
        intro_dur = _estimate_line_seconds(intro_txt)
        elapsed_s += intro_dur
        if OPEN_LOOP_MARKERS_RE.search(intro_txt):
            open_loops_found += 1
        else:
            since_last_loop_s += intro_dur

    # Audit scene-by-scene narration
    ctas_removed: List[str] = []
    total_word_count = 0
    if isinstance(scenes, list) and scenes:
        n_scenes = len(scenes)
        for idx, sc in enumerate(scenes):
            if not isinstance(sc, dict):
                continue
            target_key = next((nk for nk in narration_keys if isinstance(sc.get(nk), str) and sc.get(nk).strip()), None)
            if not target_key:
                continue

            clean_txt, rem = sanitize_robotic_line(sc[target_key])
            cliches_removed.extend(rem)

            is_last_scene = n_scenes > 1 and idx == n_scenes - 1
            if is_last_scene or str(sc.get("act_id") or "") == "ACT_4_ABRUPT_ENDING":
                clean_txt, cta_rem = strip_abrupt_ending_ctas(clean_txt)
                ctas_removed.extend(cta_rem)
                cliches_removed.extend(cta_rem)

            sc_dur = float(sc.get("duration_s") or _estimate_line_seconds(clean_txt))
            elapsed_s += sc_dur
            since_last_loop_s += sc_dur

            if "?" in clean_txt or OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif not plan_has_natural_loops and not is_last_scene and since_last_loop_s >= OPEN_LOOP_SPACING_S:
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = _append_bridge(clean_txt, bridge)
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0
                new_sc_dur = round(max(sc_dur, _estimate_line_seconds(clean_txt)), 2)
                elapsed_s += max(0.0, new_sc_dur - sc_dur)
                sc["duration_s"] = new_sc_dur

            total_word_count += len(clean_txt.split())
            sc[target_key] = clean_txt
            if not is_dict and hasattr(plan, "scenes") and idx < len(getattr(plan, "scenes", [])):
                obj_sc = plan.scenes[idx]
                if hasattr(obj_sc, target_key):
                    setattr(obj_sc, target_key, clean_txt)

    # Also audit body_lines if the plan includes viral-script-style body_lines
    if isinstance(plan_dict.get("body_lines"), list):
        new_body: List[str] = []
        n_body = len(plan_dict["body_lines"])
        for idx, ln in enumerate(plan_dict["body_lines"]):
            clean_txt, rem = sanitize_robotic_line(str(ln))
            cliches_removed.extend(rem)
            dur = _estimate_line_seconds(clean_txt)
            if not scenes:
                elapsed_s += dur
                since_last_loop_s += dur
            is_last_body = n_body > 1 and idx == n_body - 1
            if "?" in clean_txt or OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif not scenes and not plan_has_natural_loops and not is_last_body and (
                since_last_loop_s >= OPEN_LOOP_SPACING_S
                or (idx == 0 and open_loops_found == 0 and natural_q_count == 0)
            ):
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = _append_bridge(clean_txt, bridge)
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0
            new_body.append(clean_txt)
        plan_dict["body_lines"] = new_body

    # Guarantee at least 1 open loop ONLY if the entire documentary has zero natural/marker open loops
    if open_loops_found == 0 and natural_q_count == 0 and isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
        t_key = next((nk for nk in narration_keys if isinstance(scenes[0].get(nk), str)), None)
        if t_key:
            bridge = bridges[0]
            scenes[0][t_key] = _append_bridge(scenes[0][t_key], bridge)
            if not is_dict and hasattr(plan, "scenes") and len(getattr(plan, "scenes", [])) > 0:
                obj_sc = plan.scenes[0]
                if hasattr(obj_sc, t_key):
                    setattr(obj_sc, t_key, scenes[0][t_key])
            open_loops_injected += 1
            open_loops_found += 1

    all_examples = list(dict.fromkeys([*prev_examples, *cliches_removed]))[:5]
    pi_triggers = [240, 480, 720] if elapsed_s >= 760.0 else ([t_pi for t_pi in (240, 480, 720) if elapsed_s >= t_pi + 30.0])
    report = {
        "doctor": "RetentionDoctor v3",
        "schema_version": "3.0.0",
        "engine_style": "netflix_doc",
        "passed": True,
        "lang": resolved_lang,
        "cliches_blocked": prev_cliches + len(cliches_removed),
        "cliches_examples": all_examples,
        "ctas_stripped": len(ctas_removed),
        "abrupt_ending_clean": True,
        "total_words": total_word_count,
        "open_loops_total": max(
            open_loops_found,
            int(existing_audit.get("open_loops_total", 0)) if existing_audit else 0,
        ),
        "open_loops_injected": prev_injected + open_loops_injected,
        "estimated_duration_s": round(max(1.0, elapsed_s), 1),
        "pattern_interrupt_triggers_s": pi_triggers,
        "interval_rule": "24s open_loop_spacing + 240s pattern_interrupts + zero-CTA abrupt ending",
    }
    plan_dict["retention_audit"] = report
    if not is_dict:
        try:
            setattr(plan, "retention_audit", report)
        except Exception:
            pass
        return plan
    return plan_dict
