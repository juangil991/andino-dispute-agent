"""PreToolUse hook: bloquea imports que violan las fronteras de la arquitectura.

Art. 4 (dominio puro), Art. 6 (acceso al core solo vía MCP) y §3.2.2 (sin imports
entre dispute_agent y core_banking_mcp). Sale con código 2 y un mensaje en stderr
para bloquear la edición.
"""

import json
import re
import sys

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)

DOMAIN_FORBIDDEN = (
    "fastapi",
    "sqlalchemy",
    "pydantic",
    "anthropic",
    "mcp",
    "httpx",
    "uvicorn",
)


def violations(path: str, content: str) -> list[str]:
    path = path.replace("\\", "/")
    modules = IMPORT_RE.findall(content)
    found: list[str] = []

    in_agent = "/src/dispute_agent/" in path or path.startswith("src/dispute_agent/")
    in_core = "/src/core_banking_mcp/" in path or path.startswith("src/core_banking_mcp/")
    in_domain = "/domain/" in path

    for mod in modules:
        root = mod.split(".")[0]
        if in_agent and root == "core_banking_mcp":
            found.append(
                f"'{mod}': dispute_agent no puede importar core_banking_mcp (Art. 6, §3.2.2)"
            )
        if in_agent and root == "sqlalchemy":
            found.append(f"'{mod}': el agente no accede a la base del core (Art. 6)")
        if in_core and root == "dispute_agent":
            found.append(f"'{mod}': core_banking_mcp no puede importar dispute_agent (§3.2.2)")
        if in_domain and (
            root in DOMAIN_FORBIDDEN
            or ".application" in f".{mod}"
            or ".infrastructure" in f".{mod}"
        ):
            found.append(f"'{mod}': el dominio solo depende de la librería estándar (Art. 4)")
    return found


def main() -> int:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    path = tool_input.get("file_path", "")
    if not path.endswith(".py"):
        return 0
    content = tool_input.get("content") or tool_input.get("new_string") or ""
    found = violations(path, content)
    if found:
        print("Violación de fronteras de arquitectura:\n- " + "\n- ".join(found), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
