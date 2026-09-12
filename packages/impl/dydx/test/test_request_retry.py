"""The real dYdX request boundary participates in caller-owned retries."""

from typed_core import exceptions as core

from tribulnation.dydx.market.impl.mixin import ExchangeMixin
from tribulnation.sdk.core import Context, RateLimited


async def test_request_boundary_retries_translated_rate_limit():
  """A throttled page resumes without replaying previously successful pages."""
  attempts = 0

  async def read() -> str:
    """Emulate an indexer page throttled once."""
    nonlocal attempts
    attempts += 1
    if attempts == 1:
      raise core.ApiError(429, {'code': 429, 'msg': 'rate limited'})
    return 'page'

  async with ExchangeMixin.new() as exchange:
    with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
      assert await exchange.call_dydx(read) == 'page'
  assert attempts == 2
