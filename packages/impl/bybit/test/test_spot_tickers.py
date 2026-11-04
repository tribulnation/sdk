"""Bulk spot tickers keep only the pairs Bybit lists as instruments."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Literal, cast
from typed_bybit.market.instruments import SpotInstrument
from typed_bybit.market.tickers import SpotTicker, SpotTickers, Tickers

from tribulnation.bybit.market.spot_exchange import SpotExchange


def ticker(
  symbol: str, *, bid: Literal[''] | Decimal, ask: Literal[''] | Decimal
) -> SpotTicker:
  """A spot ticker with only the fields that matter here set meaningfully."""
  return {
    'symbol': symbol,
    'bid1Price': bid,
    'bid1Size': '' if bid == '' else Decimal(1),
    'ask1Price': ask,
    'ask1Size': '' if ask == '' else Decimal(1),
    'lastPrice': Decimal(100),
    'prevPrice24h': Decimal(100),
    'price24hPcnt': Decimal(0),
    'highPrice24h': Decimal(100),
    'lowPrice24h': Decimal(100),
    'turnover24h': Decimal(0),
    'volume24h': Decimal(0),
  }


async def test_unlisted_ticker_symbols_are_dropped(monkeypatch: pytest.MonkeyPatch):
  """`SOLBRL` came back from the tickers endpoint while `instruments-info` did not list it."""
  response: SpotTickers = {
    'category': 'spot',
    'list': [
      ticker('BTCUSDT', bid=Decimal(99), ask=Decimal(101)),
      ticker('SOLBRL', bid='', ask=''),
    ],
  }
  monkeypatch.setattr(Tickers, 'tickers', AsyncMock(return_value=response))
  exchange = SpotExchange.new(public=True)
  exchange.cache.spot['BTCUSDT'] = cast(SpotInstrument, {'symbol': 'BTCUSDT'})
  assert set(await exchange.tickers()) == {'BTCUSDT'}
  assert set(await exchange.tickers(['SOLBRL'])) == set()
  assert (await exchange.tickers(['BTCUSDT']))['BTCUSDT'].bid == Decimal(99)
