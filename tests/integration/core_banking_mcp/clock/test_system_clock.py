"""Tests de integración del reloj del sistema (plan §3, Clock; AC-001-13)."""

from datetime import UTC, datetime, timedelta

from core_banking_mcp.infrastructure.outbound.clock.system_clock import SystemClock


# Regla: el reloj de producción entrega la hora UTC con zona horaria (plan §3, Clock).
# AC-001-13 · §5.3 (reloj inyectable)
def test_system_clock_returns_timezone_aware_utc() -> None:
    """Habilita AC-001-13: now() es aware y en UTC, cercano al tiempo real."""
    before = datetime.now(UTC)
    value = SystemClock().now()
    after = datetime.now(UTC)

    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert before <= value <= after
