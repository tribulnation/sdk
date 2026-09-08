"""The RPC exception wrapper must not carry a provider credential out of the failure.

Alchemy puts its API key in the URL's final path segment and Etherscan in an `apikey`
query parameter, so `aiohttp.ClientResponseError.args` -- which is `(RequestInfo, history)`
and reprs the full URL -- cannot be forwarded verbatim.
"""

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy
import pytest
from yarl import URL

from tribulnation.ethereum.core.rpc.exc import wrap_exceptions
from tribulnation.sdk.core import ApiError, RateLimited

KEY = 'FAKE-KEY-abc123'


def response_error(status: int) -> aiohttp.ClientResponseError:
  """Build the error aiohttp raises for a failed Alchemy call."""
  url = URL(f'https://arb-mainnet.g.alchemy.invalid/v2/{KEY}')
  info = aiohttp.RequestInfo(
    url=url,
    method='POST',
    headers=CIMultiDictProxy(CIMultiDict[str]()),
    real_url=url,
  )
  return aiohttp.ClientResponseError(
    info, (), status=status, message='Too Many Requests'
  )


@pytest.mark.parametrize(('status', 'expected'), [(429, RateLimited), (500, ApiError)])
async def test_wrapped_response_error_keeps_the_key_out_of_the_message(
  status: int, expected: type[Exception]
):
  """The mapped error names the status and origin, never the path carrying the key."""

  @wrap_exceptions
  async def call():
    """Fail the way a rate-limited provider does."""
    raise response_error(status)

  with pytest.raises(expected) as raised:
    await call()

  message = f'{raised.value!r} {raised.value}'
  assert KEY not in message
  assert 'arb-mainnet.g.alchemy.invalid' in message
  assert str(status) in message
  # The original, with its full URL, stays reachable for local debugging.
  assert isinstance(raised.value.__cause__, aiohttp.ClientResponseError)
