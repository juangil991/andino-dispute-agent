"""Helper para devolver errores MCP estructurados (mcp-tools.md §7)."""

from typing import Any

from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
from mcp.types import CallToolResult, TextContent

from core_banking_mcp.infrastructure.inbound.mcp.schemas import ErrorCode, ToolErrorOut


class ErrorPassthroughMetadata(FuncMetadata):
    """Valida el éxito contra el esquema de salida pero no los resultados `isError=True`."""

    def convert_result(self, result: Any) -> Any:
        if isinstance(result, CallToolResult) and result.isError:
            return result
        return super().convert_result(result)


def tool_error(code: ErrorCode, message: str, *, retryable: bool) -> CallToolResult:
    """Construye un resultado de error con el sobre en `structuredContent` y en texto."""
    envelope = ToolErrorOut(code=code, message=message, retryable=retryable)
    return CallToolResult(
        isError=True,
        structuredContent=envelope.model_dump(mode="json"),
        content=[TextContent(type="text", text=envelope.model_dump_json())],
    )
