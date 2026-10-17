"""Helper para devolver errores MCP estructurados (mcp-tools.md §7)."""

from mcp.types import CallToolResult, TextContent

from core_banking_mcp.infrastructure.inbound.mcp.schemas import ErrorCode, ToolErrorOut


def tool_error(code: ErrorCode, message: str, *, retryable: bool) -> CallToolResult:
    """Construye un resultado de error con el sobre en `structuredContent` y en texto."""
    envelope = ToolErrorOut(code=code, message=message, retryable=retryable)
    return CallToolResult(
        isError=True,
        structuredContent=envelope.model_dump(mode="json"),
        content=[TextContent(type="text", text=envelope.model_dump_json())],
    )
