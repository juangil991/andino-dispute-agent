"""Hook de puerta: no se ofrece ni se crea un PR sin auditoría de cobertura de AC vigente.

§4.3 (trazabilidad spec ↔ tests) y §5.3: antes de abrir el PR de una feature, la skill
`verify-ac-coverage` debe haber dado veredicto `Cumple` después del último cambio en los
tests o en la spec.

La skill opera en dos fases: la primera auditoría es completa; si da `No cumple`, la
siguiente solo verifica las correcciones de ese informe (guardado aquí como línea base).

Modos:
- `record` (PostToolUse, matcher `Skill`): guarda veredicto, fase e informe de `verify-ac-coverage`
  cuando la skill corre en primer plano. Si corre en un subagente (`status: forked`), la respuesta
  de la herramienta es solo un aviso de lanzamiento: se ignora y el informe lo guarda `subagent`.
- `subagent` (SubagentStop): lee el informe final del subagente y, si es el de
  `verify-ac-coverage`, guarda veredicto, fase e informe.
- `gate` (PreToolUse): bloquea con código 2 la pregunta «Crear PR», `gh pr create` y
  `mcp__github__create_pull_request` si no hay veredicto `Cumple` vigente.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
STATE_DIR = ROOT / ".claude" / "state" / "ac-coverage"
SKILL = "verify-ac-coverage"

BRANCH_RE = re.compile(r"ref:\s*refs/heads/feature/(\d{3})-")
NNN_RE = re.compile(r"\b(\d{3})\b")
VERDICT_RE = re.compile(r"Veredicto\W*(No cumple|Cumple)", re.IGNORECASE)
PR_QUESTION_RE = re.compile(r"crear\s+(?:el\s+|un\s+)?pr\b|pull\s+request", re.IGNORECASE)
FORKED_RE = re.compile(r'status\\?"\s*:\s*\\?"forked')
REPORT_HEAD_RE = re.compile(r"Fase\s*[12]|Veredicto", re.IGNORECASE)
REPORT_FEATURE_RE = re.compile(r"feature\s+(\d{3})\b", re.IGNORECASE)
REPORT_HEAD_CHARS = 400


def feature_from_branch() -> str | None:
    try:
        head = (ROOT / ".git" / "HEAD").read_text(encoding="utf-8")
    except OSError:
        return None
    match = BRANCH_RE.search(head)
    return match.group(1) if match else None


def state_path(nnn: str) -> Path:
    return STATE_DIR / f"{nnn}.json"


def latest_change(nnn: str) -> float:
    paths = list((ROOT / "tests").rglob("*.py")) + list(ROOT.glob(f"specs/{nnn}-*/spec.md"))
    return max((p.stat().st_mtime for p in paths), default=0.0)


def read_state(nnn: str) -> dict[str, Any] | None:
    try:
        state = json.loads(state_path(nnn).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def is_phase_two(nnn: str, state: dict[str, Any]) -> bool:
    """Fase 2 si hay un informe real previo con «No cumple» y la spec no cambió desde entonces."""
    if state.get("verdict") != "No cumple" or not state.get("report_is_real"):
        return False
    specs = list(ROOT.glob(f"specs/{nnn}-*/spec.md"))
    spec_mtime = max((p.stat().st_mtime for p in specs), default=0.0)
    return spec_mtime <= state.get("checked_at", 0.0)


def save_report(nnn: str, report: str) -> None:
    """Guarda veredicto, fase e informe; en fase 2 conserva el de la fase 1 como línea base."""
    found = VERDICT_RE.search(report)
    # Sin veredicto reconocible se falla en modo cerrado.
    verdict = "Cumple" if found and found.group(1).lower() == "cumple" else "No cumple"
    previous = read_state(nnn)
    if previous is not None and is_phase_two(nnn, previous):
        state = {
            "verdict": verdict,
            "phase": 2,
            "baseline_report": previous.get("baseline_report") or previous.get("report", ""),
            "report": report,
        }
    else:
        state = {"verdict": verdict, "phase": 1, "report": report}
    state["report_is_real"] = True
    state["checked_at"] = time.time()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(nnn).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def record(data: dict[str, Any]) -> int:
    tool_input = data.get("tool_input", {})
    if str(tool_input.get("skill", "")).split(":")[-1] != SKILL:
        return 0
    args_match = NNN_RE.search(str(tool_input.get("args", "")))
    nnn = args_match.group(1) if args_match else feature_from_branch()
    if nnn is None:
        return 0
    response = data.get("tool_response", "")
    report = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    if FORKED_RE.search(report):
        # Skill en subagente: esto es solo el aviso de lanzamiento; el informe llega por `subagent`.
        return 0
    save_report(nnn, report)
    return 0


def last_assistant_text(transcript: Path) -> str:
    """Texto del último mensaje del asistente en un transcript JSONL (respaldo)."""
    text = ""
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except OSError:
        return text
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(str(b.get("text", "")) for b in blocks) or text
    return text


def subagent(data: dict[str, Any]) -> int:
    """SubagentStop: guarda el informe final si es el de `verify-ac-coverage`. Nunca bloquea."""
    report = str(data.get("last_assistant_message") or "")
    if not report and data.get("agent_transcript_path"):
        report = last_assistant_text(Path(str(data["agent_transcript_path"])))
    head = report[:REPORT_HEAD_CHARS]
    # Se reconoce por contenido: cabecera con la fase o el veredicto, y un veredicto en el texto.
    if not REPORT_HEAD_RE.search(head) or not VERDICT_RE.search(report):
        return 0
    feature = REPORT_FEATURE_RE.search(head)
    nnn = feature.group(1) if feature else feature_from_branch()
    if nnn is None:
        return 0
    save_report(nnn, report)
    return 0


def is_pr_attempt(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if tool_name == "mcp__github__create_pull_request":
        return True
    if tool_name in ("Bash", "PowerShell"):
        return "gh pr create" in str(tool_input.get("command", ""))
    if tool_name == "AskUserQuestion":
        texts: list[str] = []
        for question in tool_input.get("questions", []):
            texts.append(str(question.get("question", "")))
            texts.extend(str(option.get("label", "")) for option in question.get("options", []))
        return any(PR_QUESTION_RE.search(text) for text in texts)
    return False


def gate(data: dict[str, Any]) -> int:
    if not is_pr_attempt(data.get("tool_name", ""), data.get("tool_input", {})):
        return 0
    nnn = feature_from_branch()
    if nnn is None:
        return 0
    run = f"Ejecuta la skill `{SKILL}` con `{nnn}` antes de ofrecer o crear el PR (§4.3)."
    try:
        state = json.loads(state_path(nnn).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"No hay auditoría de cobertura de AC para la feature {nnn}. {run}", file=sys.stderr)
        return 2
    if state.get("checked_at", 0.0) < latest_change(nnn):
        print(
            f"La auditoría de cobertura de AC de {nnn} es anterior al último cambio en "
            f"tests/ o en la spec. {run}",
            file=sys.stderr,
        )
        return 2
    if state.get("verdict") != "Cumple":
        print(
            f"La auditoría de cobertura de AC de {nnn} dio «No cumple»: el PR queda bloqueado. "
            "Corrige los hallazgos (subagente task-implementer o /specify) y vuelve a "
            f"ejecutar `{SKILL}` para la verificación de correcciones.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    # En Windows la consola usa cp1252: sin esto los acentos del mensaje llegan corruptos.
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if mode == "record":
        return record(data)
    if mode == "subagent":
        return subagent(data)
    if mode == "gate":
        return gate(data)
    print(f"Modo desconocido: {mode!r} (usa record, subagent o gate)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
