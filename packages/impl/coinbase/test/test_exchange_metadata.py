"""Coinbase product families have SDK-owned names without changing identities."""

from tribulnation.coinbase import CoinbaseMarket


async def test_exchange_names_keep_native_ids():
  """Discovery names Advanced Trade and International separately, without auth."""
  async with CoinbaseMarket.new(public=True) as sdk:
    assert await sdk.exchanges() == [
      {'id': 'spot', 'type': 'spot', 'name': 'Advanced Trade'},
      {'id': 'intx', 'type': 'perp', 'name': 'International Exchange'},
    ]
