"""FrimeRise Anti-Boredom Auditor ("Retention Doctor").
Automatically blocks and rewrites robotic AI clichés ("Em um mundo onde...", "Vamos mergulhar...",
"Em resumo...", etc.) and enforces an Open Loop (unresolved question or narrative tension cliffhanger)
every 15 to 25 seconds of script across both Live-Action/Documentary scripts and 2D Cartoon Episode Plans.
Zero LLM tokens required (100% deterministic high-speed regex + structural pacing engine).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Robotic AI phrases forbidden in any FrimeRise production (PT-BR, EN-US, ES)
FORBIDDEN_AI_CLICHES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(em|num)\s+um\s+mundo\s+onde\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Olha o que quase ninguém percebe: "),
    (re.compile(r"\bvamos\s+mergulhar(\s+fundo|\s+nisso|\s+nesse\s+tema)?\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Presta atenção neste detalhe: "),
    (re.compile(r"\bmergulhe\s+conosco\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Veja o que acontece na prática: "),
    (re.compile(r"\bem\s+resumo\b[,:]?\s*", re.IGNORECASE), "O ponto decisivo é simples: "),
    (re.compile(r"\bpara\s+concluir\b[,:]?\s*", re.IGNORECASE), "E o resultado final prova tudo: "),
    (re.compile(r"\bem\s+conclus[aã]o\b[,:]?\s*", re.IGNORECASE), "No fim das contas: "),
    (re.compile(r"\bvale\s+ressaltar\s+que\b\s*", re.IGNORECASE), "O segredo é que "),
    (re.compile(r"\b[eé]\s+importante\s+(notar|lembrar|destacar)\s+que\b\s*", re.IGNORECASE), "Repare que "),
    (re.compile(r"\bsem\s+mais\s+delongas\b[,!.]?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bnos\s+dias\s+de\s+hoje\b[,:]?\s*", re.IGNORECASE), "Hoje, "),
    (re.compile(r"\bin\s+a\s+world\s+where\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Here is what nobody tells you: "),
    (re.compile(r"\blet'?s\s+dive\s+(right\s+)?in(to)?\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Look closely at this: "),
    (re.compile(r"\bin\s+summary\b[,:]?\s*", re.IGNORECASE), "The real takeaway is simple: "),
    (re.compile(r"\ben\s+un\s+mundo\s+donde\b[^,.!?]*[,:]?\s*", re.IGNORECASE), "Mira lo que casi nadie nota: "),
    (re.compile(r"\bvamos\s+a\s+sumergirnos\b[^,.!?]*[,!.]?\s*", re.IGNORECASE), "Fíjate en este detalle: "),
    (re.compile(r"\ben\s+resumen\b[,:]?\s*", re.IGNORECASE), "La clave real es esta: "),
]

OPEN_LOOP_MARKERS_RE = re.compile(
    r"(\?|"
    r"\bmas\s+o\s+que\s+ningu[eé]m\s+esperava\b|"
    r"\bs[oó]\s+que\s+tem\s+um\s+detalhe\b|"
    r"\bmas\s+espera\s+at[eé]\s+ver\b|"
    r"\be\s+o\s+pior\s+ainda\s+estava\s+por\s+vir\b|"
    r"\bpor\s+que\s+isso\s+acontece\b|"
    r"\bqual\s+[eé]\s+o\s+verdadeiro\s+segredo\b|"
    r"\bwait\s+until\s+you\s+see\b|"
    r"\bpero\s+nadie\s+esperaba\b)",
    re.IGNORECASE,
)

OPEN_LOOP_BRIDGES_PT = [
    "Mas espera: por que quase todo mundo erra exatamente no próximo passo?",
    "Só que ninguém esperava o que aconteceria logo em seguida — olha só:",
    "Mas aqui surge a pergunta que muda tudo: o que acontece quando você inverte essa regra?",
]

OPEN_LOOP_BRIDGES_CARTOON_PT = [
    "Mas espera aí... tu acha mesmo que o problema parou por aí?",
    "Só que ninguém contava com o que ia aparecer bem na nossa frente agora!",
    "Agora me responde uma coisa: quem foi o gênio que teve essa ideia?",
]


def sanitize_robotic_line(text: str) -> Tuple[str, List[str]]:
    """Strip or replace robotic AI clichés from a single line of text."""
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


def audit_viral_script_dict(script: Dict[str, Any]) -> Dict[str, Any]:
    """Run Retention Doctor on a standard viral/documentary script dictionary.
    1. Purges all robotic AI clichés from hook_a, hook_b, body_lines, closing_line.
    2. Verifies an Open Loop exists every 15-25s; injects a high-tension Open Loop if missing.
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
            # Inject an Open Loop right into this 15-25s window!
            bridge = OPEN_LOOP_BRIDGES_PT[open_loops_injected % len(OPEN_LOOP_BRIDGES_PT)]
            ln = f"{ln.rstrip('.!')} — {bridge}"
            open_loops_injected += 1
            open_loops_found += 1
            since_last_loop_s = 0.0
        audited_body.append(ln)

    script["body_lines"] = audited_body
    script["retention_audit"] = {
        "doctor": "RetentionDoctor v2",
        "passed": True,
        "cliches_blocked": len(cliches_removed),
        "cliches_examples": cliches_removed[:5],
        "open_loops_total": open_loops_found,
        "open_loops_injected": open_loops_injected,
        "estimated_duration_s": round(elapsed_s + _estimate_line_seconds(script.get("closing_line", "")), 1),
        "interval_rule": "15-25s open_loop_enforced",
    }
    return script


def audit_cartoon_episode_plan(plan: Any) -> Tuple[Any, Dict[str, Any]]:
    """Run Retention Doctor on a CartoonEpisodePlan Pydantic object."""
    cliches_removed: List[str] = []
    open_loops_found = 0
    open_loops_injected = 0
    elapsed_s = 0.0
    since_last_loop_s = 0.0

    for s_idx, scene in enumerate(plan.scenes):
        for l_idx, dl in enumerate(scene.dialogue_lines):
            clean_txt, rem = sanitize_robotic_line(dl.line_pt)
            cliches_removed.extend(rem)
            dur = _estimate_line_seconds(clean_txt)
            elapsed_s += dur
            since_last_loop_s += dur

            if OPEN_LOOP_MARKERS_RE.search(clean_txt):
                open_loops_found += 1
                since_last_loop_s = 0.0
            elif since_last_loop_s >= 15.0:
                bridge = OPEN_LOOP_BRIDGES_CARTOON_PT[open_loops_injected % len(OPEN_LOOP_BRIDGES_CARTOON_PT)]
                clean_txt = f"{clean_txt.rstrip('.!')} {bridge}"
                open_loops_injected += 1
                open_loops_found += 1
                since_last_loop_s = 0.0

            dl.line_pt = clean_txt

    # Ensure at least 1 Open Loop exists even in ultra-short <15s cartoons
    if open_loops_found == 0 and plan.scenes and plan.scenes[0].dialogue_lines:
        first_dl = plan.scenes[0].dialogue_lines[0]
        if "?" not in first_dl.line_pt:
            first_dl.line_pt = f"{first_dl.line_pt.rstrip('.!')} — mas tu sabe o que aconteceu logo depois?"
            open_loops_injected += 1
            open_loops_found += 1

    report = {
        "doctor": "RetentionDoctor v2",
        "passed": True,
        "cliches_blocked": len(cliches_removed),
        "cliches_examples": cliches_removed[:5],
        "open_loops_total": open_loops_found,
        "open_loops_injected": open_loops_injected,
        "estimated_duration_s": round(elapsed_s, 1),
        "interval_rule": "15-25s open_loop_enforced",
    }
    return plan, report
