"""Personal Kraken rates preserve pair identity and flat-versus-split schedules."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_kraken import Kraken
from typed_kraken.spot.account.trade_volume import TradeVolumeEndpoint

from tribulnation.kraken.market.impl.mixin import Shared
from tribulnation.kraken.market.spot_market import SpotMarket
from tribulnation.sdk.market import Fees


@pytest.mark.parametrize('split', [True, False])
async def test_account_rate_uses_internal_response_key(
  split: bool, monkeypatch: pytest.MonkeyPatch
):
  """Requests use altname, responses use the catalogue's exact internal pair key."""
  response = {'fees': {'XXBTZUSD': {'fee': '0.04'}}}
  if split:
    response['fees_maker'] = {'XXBTZUSD': {'fee': '-0.01'}}
  request = AsyncMock(return_value=response)
  monkeypatch.setattr(TradeVolumeEndpoint, 'trade_volume', request)
  market = SpotMarket(
    shared=Shared(client=Kraken.new(public=True)),
    meta={
      'pair': {
        'key': 'XXBTZUSD',
        'symbol': 'BTC/USD',
        'info': {'altname': 'XBTUSD', 'fees_maker': [(0, 0.1)] if split else []},
      }
    },
  )
  assert await market.fees() == Fees.symmetric(
    maker=Decimal('-0.0001') if split else Decimal('0.0004'),
    taker=Decimal('0.0004'),
  )
  request.assert_awaited_once_with('XBTUSD')


async def test_account_rate_never_uses_an_unrelated_pair(
  monkeypatch: pytest.MonkeyPatch,
):
  """Selecting the first response row would silently assign another market's fees."""
  monkeypatch.setattr(
    TradeVolumeEndpoint,
    'trade_volume',
    AsyncMock(
      return_value={
        'fees': {'OTHER': {'fee': '0.04'}},
      }
    ),
  )
  market = SpotMarket(
    shared=Shared(client=Kraken.new(public=True)),
    meta={
      'pair': {
        'key': 'XXBTZUSD',
        'symbol': 'BTC/USD',
        'info': {'altname': 'XBTUSD'},
      }
    },
  )
  with pytest.raises(ValueError, match='requested pair'):
    await market.fees()
