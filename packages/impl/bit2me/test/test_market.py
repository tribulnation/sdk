"""Regression tests for defects found mapping the Bit2Me market surface."""

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

from tribulnation.sdk.market import Book
from tribulnation.bit2me.market.impl.depth import parse_levels
from tribulnation.bit2me.market.impl.rules import standard_fees
from tribulnation.bit2me.market.impl.mixin import Shared
from tribulnation.bit2me.market.spot_exchange import SpotExchange


def test_a_three_element_level_is_read_by_index():
  """Some order-book rows are `[price, amount, notional]`, not a pair.

  Unpacking such a row raises `ValueError`. Which shape arrives is not a property of
  the market: `B2M/EUR` has been seen serving triples over REST while pushing pairs
  over the socket in the same minute, so only the row's own length decides. The three
  majors any live check would reach send pairs, so the fault never shows up there.
  """
  levels = parse_levels([(0.0052283, 76289.74336778, 398.86566524976416)])
  assert levels == [
    Book.Entry(price=Decimal('0.0052283'), qty=Decimal('76289.74336778'))
  ]


def test_standard_fees_distinguish_documented_pair_classes():
  """Stable-base markets have a separate fee tier; unknown classes stay unknown."""
  crypto = standard_fees('BTC', 'EUR')
  stable = standard_fees('USDC', 'EUR')
  assert crypto is not None and stable is not None
  assert crypto.maker_buy == crypto.maker_sell == Decimal('0.005')
  assert crypto.taker_buy == crypto.taker_sell == Decimal('0.006')
  assert stable.maker_buy == stable.maker_sell == Decimal(0)
  assert stable.taker_buy == stable.taker_sell == Decimal('0.0001')
  assert standard_fees('UNCLASSIFIED', 'EUR') is None


async def test_selected_tickers_use_symbol_specific_quotes():
  """Explicit selections do not read the independently stale upstream bulk cache."""
  client = Mock()
  client.v2.trading.tickers = AsyncMock(
    return_value=[{'symbol': '1INCH/EUR', 'bid': 0.0787, 'ask': 0.0823}]
  )
  exchange = SpotExchange(shared=Shared(client=client))
  tickers = await exchange.tickers(['1INCH/EUR', '1INCH/EUR'])
  client.v2.trading.tickers.assert_awaited_once_with(symbol='1INCH/EUR')
  assert tickers['1INCH/EUR'].ask == Decimal('0.0823')


async def test_bulk_tickers_still_use_one_unfiltered_request():
  """All-market discovery does not become a per-symbol sweep."""
  client = Mock()
  client.v2.trading.tickers = AsyncMock(return_value=[])
  exchange = SpotExchange(shared=Shared(client=client))
  assert await exchange.tickers() == {}
  client.v2.trading.tickers.assert_awaited_once_with()


async def test_empty_ticker_selection_does_not_fetch():
  """An empty selection remains empty without calling any upstream endpoint."""
  client = Mock()
  client.v2.trading.tickers = AsyncMock()
  exchange = SpotExchange(shared=Shared(client=client))
  assert await exchange.tickers([]) == {}
  client.v2.trading.tickers.assert_not_awaited()
