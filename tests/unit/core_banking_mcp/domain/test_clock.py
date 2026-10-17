from datetime import UTC, date, datetime

import pytest

from core_banking_mcp.domain.clock import today_in_bogota


# Regla: RN-002-08 — "hoy" se evalúa en America/Bogota (UTC-5).
# AC-002-09 · Art. 3 (borde de las 03:00Z y las 05:00Z)
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 17, 15, 0, 0, tzinfo=UTC), date(2026, 10, 17)),
        (datetime(2026, 10, 18, 3, 0, 0, tzinfo=UTC), date(2026, 10, 17)),
        (datetime(2026, 10, 18, 4, 59, 59, tzinfo=UTC), date(2026, 10, 17)),
        (datetime(2026, 10, 18, 5, 0, 0, tzinfo=UTC), date(2026, 10, 18)),
    ],
    ids=["midday", "03:00Z", "04:59:59Z_last_second", "05:00Z_new_day"],
)
def test_ac_002_09_today_in_bogota_boundaries(now: datetime, expected: date) -> None:
    """AC-002-09: la fecha de hoy se calcula en America/Bogota."""
    assert today_in_bogota(now) == expected
