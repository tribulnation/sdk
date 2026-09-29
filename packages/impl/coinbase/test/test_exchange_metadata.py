"""Coinbase product families have SDK-owned names without changing identities."""

import pytest

from tribulnation.coinbase import CoinbaseMarket


async def test_exchange_names_keep_native_ids():
  """Discovery lists only Advanced Trade spot, without auth."""
  async with CoinbaseMarket.new(public=True) as sdk:
    assert await sdk.exchanges() == [
      {'id': 'spot', 'type': 'spot', 'name': 'Advanced Trade'},
    ]


async def test_retired_intx_exchange_is_rejected():
  """INTX perpetuals are retired: neither exchange lookup serves them."""
  async with CoinbaseMarket.new(public=True) as sdk:
    with pytest.raises(ValueError, match='Unknown Coinbase exchange "intx"'):
      await sdk.exchange('intx')
    with pytest.raises(NotImplementedError):
      await sdk.perp_exchange('intx')
