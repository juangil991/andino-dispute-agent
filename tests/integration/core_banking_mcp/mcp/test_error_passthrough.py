"""`ErrorPassthroughMetadata`: errores `isError=true` pasan intactos; los éxitos se validan."""

from typing import Annotated

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import ErrorCode


class _Out(BaseModel):
    value: int


def _metadata() -> FuncMetadata:
    mcp = FastMCP("passthrough-test")

    @mcp.tool(name="probe")
    def probe() -> Annotated[CallToolResult, _Out]:
        return CallToolResult(content=[])

    registered = mcp._tool_manager.get_tool("probe")
    assert registered is not None
    return ErrorPassthroughMetadata(**dict(registered.fn_metadata))


# Invariante: Art. 10 — un error estructurado (isError=True) llega intacto al agente, sin
#   validarse contra outputSchema (plan §2).
# AC-002-03 · AC-002-16 · Art. 10
def test_error_passthrough_metadata_returns_error_results_untouched() -> None:
    """Invariante Art. 10: un resultado isError=True pasa intacto; un éxito sí se valida."""
    metadata = _metadata()
    error = tool_error(ErrorCode.INVALID_INPUT, "entrada no válida", retryable=False)

    assert metadata.convert_result(error) is error

    valid = CallToolResult(
        content=[TextContent(type="text", text="{}")], structuredContent={"value": 1}
    )
    assert metadata.convert_result(valid) is not None

    invalid = CallToolResult(
        content=[TextContent(type="text", text="{}")], structuredContent={"value": "x"}
    )
    with pytest.raises(Exception):  # noqa: B017, PT011
        metadata.convert_result(invalid)
