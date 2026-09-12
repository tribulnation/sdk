"""History pagination retries the failed page without replaying successful reads."""

from typed_core import PaginatedResponse
from typed_core.exceptions import RateLimited as ClientRateLimited

from tribulnation.hyperliquid.report.history.main import History
from tribulnation.sdk import Context, RateLimited


async def test_history_retries_only_failed_page():
  """A typed-client throttle is translated and resumes at the same page cursor."""
  calls: list[int] = []

  async def fetch(state: int) -> tuple[list[int], int | None]:
    """Fail the second page once without changing its cursor."""
    calls.append(state)
    if calls == [0, 1]:
      raise ClientRateLimited('rate limited')
    return [state], state + 1 if state < 2 else None

  history = History.http('0x0000000000000000000000000000000000000000')
  async with history:
    with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
      result = await PaginatedResponse(0, fetch).via(history.call)
  assert result == [0, 1, 2]
  assert calls == [0, 1, 1, 2]
