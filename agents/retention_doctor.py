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

OPEN_LOOP_BRIDGES_PT = [
    "Mas espera: por que quase todo mundo erra exatamente no próximo passo?",
    "Só que ninguém esperava o que aconteceria logo em seguida — olha só:",
    "Mas aqui surge a pergunta que muda tudo: o que acontece quando você inverte essa regra?",
]

OPEN_LOOP_BRIDGES_EN = [
    "But wait: why does almost everyone miss what happens in the very next step?",
    "Yet nobody expected what was hiding right behind the scenes — look at this:",
    "And that raises the real question: what happens when you flip this rule upside down?",
]

OPEN_LOOP_BRIDGES_ES = [
    "Pero espera: ¿por qué casi todo el mundo falla exactamente en el siguiente paso?",
    "Sin embargo, nadie esperaba lo que ocurriría justo después — mira esto:",
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


def _estimate_line_seconds(text: str) -> float:
    words = len(str(text or "").split())
    return max(1.8, round(words / 2.65, 2))


def audit_viral_script_dict(script: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
    """Run Retention Doctor on a standard viral/documentary script dictionary.
    1. Purges all robotic AI clichés from hook_a, hook_b, body_lines, closing_line (PT-BR, EN-US, ES).
    2. Verifies an Open Loop exists every ~20s (15-25s window); injects a high-tension Open Loop if missing.
    """
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

    # Timeline Open-Loop Audit (every 15s to 25s window must have an unresolved question or tension loop)
    elapsed_s = _estimate_line_seconds(script.get("hook_a", ""))
    since_last_loop_s = 0.0
    if OPEN_LOOP_MARKERS_RE.search(str(script.get("hook_a", ""))):
        open_loops_found += 1

    audited_body: List[str] = []
    for idx, ln in enumerate(cleaned_body):
        dur = _estimate_line_seconds(ln)
        elapsed_s += dur
        since_last_loop_s += dur
        has_loop = bool(OPEN_LOOP_MARKERS_RE.search(ln))
        if has_loop:
            open_loops_found += 1
            since_last_loop_s = 0.0
        elif since_last_loop_s >= 15.0 or (idx == 0 and len(cleaned_body) <= 3 and open_loops_found == 0):
            bridge = bridges[open_loops_injected % len(bridges)]
            ln = f"{ln.rstrip('.!')} — {bridge}"
            open_loops_injected += 1
            open_loops_found += 1
            since_last_loop_s = 0.0
        audited_body.append(ln)

    script["body_lines"] = audited_body
    script["retention_audit"] = {
        "doctor": "RetentionDoctor v2",
        "passed": True,
        "lang": resolved_lang,
        "cliches_blocked": len(cliches_removed),
        "cliches_examples": cliches_removed[:5],
        "open_loops_total": open_loops_found,
        "open_loops_injected": open_loops_injected,
        "estimated_duration_s": round(elapsed_s + _estimate_line_seconds(script.get("closing_line", "")), 1),
        "interval_rule": "15-25s open_loop_enforced (~20s target)",
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
            elif since_last_loop_s >= 15.0:
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = f"{clean_txt.rstrip('.!')} {bridge}"
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0

            dl.line_pt = clean_txt

    # Ensure at least 1 Open Loop exists even in ultra-short <15s cartoons
    if open_loops_found == 0 and getattr(plan, "scenes", None) and plan.scenes[0].dialogue_lines:
        first_dl = plan.scenes[0].dialogue_lines[0]
        if "?" not in first_dl.line_pt:
            fallback_q = {
                "en_us": "— wait until you see what happened next!",
                "es": "— ¿pero sabes qué pasó justo después?",
            }.get(resolved_lang, "— mas tu sabe o que aconteceu logo depois?")
            first_dl.line_pt = f"{first_dl.line_pt.rstrip('.!')} {fallback_q}"
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
        "interval_rule": "15-25s open_loop_enforced (~20s target)",
    }
    return plan, report


def audit_netflix_doc_plan(plan: Any, lang: Optional[str] = None) -> Any:
    """Run Retention Doctor on a Netflix / MagnatesMedia Investigative Documentary Plan (`dict` or Pydantic object).
    1. Purges all robotic AI clichés in PT-BR, EN-US, and ES across cold_open, chapters, scenes, and narration lines.
    2. Enforces an investigative Open Loop every ~20s (15-25s window) so documentary retention never drops.
    3. Attaches `retention_audit` telemetry to the plan and returns the audited plan.
    """
    is_dict = isinstance(plan, dict)
    plan_dict: Dict[str, Any] = plan if is_dict else (plan.model_dump() if hasattr(plan, "model_dump") else dict(plan))

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

    # Collect text sample for language detection
    scenes = plan_dict.get("scenes") or plan_dict.get("chapters") or plan_dict.get("acts") or []
    sample_chunks: List[str] = [str(plan_dict.get("cold_open") or plan_dict.get("hook_a") or "")]
    narration_keys = ("narration", "text", "line_pt", "voiceover", "script_line", "script", "dialogue")
    for sc in scenes:
        if isinstance(sc, dict):
            for nk in narration_keys:
                if sc.get(nk):
                    sample_chunks.append(str(sc[nk]))
                    break
    for ln in plan_dict.get("body_lines") or []:
        sample_chunks.append(str(ln))

    resolved_lang = _detect_lang(" ".join(sample_chunks), lang or plan_dict.get("lang"))
    bridges = _pick_bridge_pool("netflix_doc", resolved_lang)

    # Check if cold_open / hook_a already starts with an open loop
    intro_txt = str(plan_dict.get("cold_open") or plan_dict.get("hook_a") or "")
    if intro_txt:
        intro_dur = _estimate_line_seconds(intro_txt)
        elapsed_s += intro_dur
        if OPEN_LOOP_MARKERS_RE.search(intro_txt):
            open_loops_found += 1
        else:
            since_last_loop_s += intro_dur

    # Audit scene-by-scene narration
    if isinstance(scenes, list) and scenes:
        for idx, sc in enumerate(scenes):
            if not isinstance(sc, dict):
                continue
            target_key = next((nk for nk in narration_keys if isinstance(sc.get(nk), str) and sc.get(nk).strip()), None)
            if not target_key:
                continue

            clean_txt, rem = sanitize_robotic_line(sc[target_key])
            cliches_removed.extend(rem)
            sc_dur = float(sc.get("duration_s") or _estimate_line_seconds(clean_txt))
            elapsed_s += sc_dur
            since_last_loop_s += sc_dur

            if OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif since_last_loop_s >= 15.0 or (idx == len(scenes) // 2 and open_loops_found == 0):
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = f"{clean_txt.rstrip('.!')} — {bridge}"
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0
                sc["duration_s"] = round(max(sc_dur, _estimate_line_seconds(clean_txt)), 2)

            sc[target_key] = clean_txt
            if not is_dict and hasattr(plan, "scenes") and idx < len(getattr(plan, "scenes", [])):
                obj_sc = plan.scenes[idx]
                if hasattr(obj_sc, target_key):
                    setattr(obj_sc, target_key, clean_txt)

    # Also audit body_lines if the plan includes viral-script-style body_lines
    if isinstance(plan_dict.get("body_lines"), list):
        new_body: List[str] = []
        for idx, ln in enumerate(plan_dict["body_lines"]):
            clean_txt, rem = sanitize_robotic_line(str(ln))
            cliches_removed.extend(rem)
            dur = _estimate_line_seconds(clean_txt)
            if not scenes:
                elapsed_s += dur
                since_last_loop_s += dur
            if OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif not scenes and (since_last_loop_s >= 15.0 or (idx == 0 and open_loops_found == 0)):
                bridge = bridges[open_loops_injected % len(bridges)]
                clean_txt = f"{clean_txt.rstrip('.!')} — {bridge}"
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0
            new_body.append(clean_txt)
        plan_dict["body_lines"] = new_body

    # Guarantee at least 1 open loop in short documentary plans
    if open_loops_found == 0 and isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
        t_key = next((nk for nk in narration_keys if isinstance(scenes[0].get(nk), str)), None)
        if t_key:
            bridge = bridges[0]
            scenes[0][t_key] = f"{scenes[0][t_key].rstrip('.!')} — {bridge}"
            open_loops_injected += 1
            open_loops_found += 1

    report = {
        "doctor": "RetentionDoctor v2",
        "engine_style": "netflix_doc",
        "passed": True,
        "lang": resolved_lang,
        "cliches_blocked": len(cliches_removed),
        "cliches_examples": cliches_removed[:5],
        "open_loops_total": open_loops_found,
        "open_loops_injected": open_loops_injected,
        "estimated_duration_s": round(max(1.0, elapsed_s), 1),
        "interval_rule": "15-25s open_loop_enforced (~20s target)",
    }
    plan_dict["retention_audit"] = report
    if not is_dict:
        try:
            setattr(plan, "retention_audit", report)
        except Exception:
            pass
        return plan
    return plan_dict
