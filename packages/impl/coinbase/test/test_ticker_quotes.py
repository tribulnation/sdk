"""Coinbase bulk tickers join native quotes by exact product ID."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typing_extensions import cast
from typed_coinbase.app.advanced_trade.http.products.best_bid_ask import BestBidAsk
from typed_coinbase.schemas import PriceBook, Product
from typed_core import exceptions as core

from tribulnation.coinbase import CoinbaseMarket
from tribulnation.coinbase.market import impl
from tribulnation.coinbase.market.impl.catalogue import QUOTE_BATCH_SIZE, tickers
from tribulnation.sdk.core import ApiError, Context, RateLimited


def product(identifier: str) -> Product:
  """Supply the catalogue fields read by the ticker parser."""
  return cast(
    Product,
    {
      'product_id': identifier,
      'price': Decimal('100'),
      'volume_24h': Decimal('9'),
      'best_bid_price': Decimal('1'),
      'best_ask_price': Decimal('999'),
    },
  )


def book(identifier: str) -> PriceBook:
  """Provide real quote prices and sizes distinct from catalogue placeholders."""
  return {
    'product_id': identifier,
    'bids': [{'price': Decimal('99'), 'size': Decimal('2')}],
    'asks': [{'price': Decimal('101'), 'size': Decimal('3')}],
  }


@pytest.mark.parametrize(
  'exchange_id,identifier', [('spot', 'BTC-USD'), ('intx', 'BTC-PERP-INTX')]
)
async def test_both_exchanges_enrich_only_selected_products(
  monkeypatch: pytest.MonkeyPatch,
  exchange_id: str,
  identifier: str,
):
  """Spot and INTX use the same quote join without mixing product identities."""
  monkeypatch.setattr(
    impl,
    'list_products',
    AsyncMock(return_value=[product(identifier), product('OTHER')]),
  )
  request = AsyncMock(return_value={'pricebooks': [book(identifier)]})
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with CoinbaseMarket.new(public=True) as sdk:
    exchange = await sdk.exchange(exchange_id)
    result = await exchange.tickers([identifier])
  assert list(result) == [identifier]
  ticker = result[identifier]
  assert (ticker.last, ticker.base_volume_24h) == (Decimal('100'), Decimal('9'))
  assert (ticker.bid, ticker.ask) == (Decimal('99'), Decimal('101'))
  assert (ticker.bid_qty, ticker.ask_qty) == (Decimal('2'), Decimal('3'))
  request.assert_awaited_once_with([identifier])


async def test_bounded_batches_and_response_order(monkeypatch: pytest.MonkeyPatch):
  """Large catalogues are chunked; response ordering does not define the join."""
  ids = [f'P{i}-USD' for i in range(QUOTE_BATCH_SIZE + 1)]
  request = AsyncMock(
    side_effect=[
      {'pricebooks': [book(identifier) for identifier in reversed(ids[:-1])]},
      {'pricebooks': [book(ids[-1])]},
    ]
  )
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with CoinbaseMarket.new(public=True) as sdk:
    result = await tickers(sdk, [product(identifier) for identifier in ids])
  assert list(result) == ids
  assert all(ticker.bid == Decimal('99') for ticker in result.values())
  assert [call.args[0] for call in request.await_args_list] == [ids[:-1], ids[-1:]]


async def test_missing_books_and_empty_sides_remain_unknown(
  monkeypatch: pytest.MonkeyPatch,
):
  """No stale catalogue fallback or invented zero quotes for inactive products."""
  partial = book('ONE')
  partial['asks'] = []
  request = AsyncMock(return_value={'pricebooks': [partial]})
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with CoinbaseMarket.new(public=True) as sdk:
    result = await tickers(sdk, [product('ONE'), product('MISSING')])
  assert result['ONE'].bid == Decimal('99')
  assert result['ONE'].ask is None and result['ONE'].ask_qty is None
  assert result['MISSING'].bid is None and result['MISSING'].ask is None
  assert result['MISSING'].last == Decimal('100')


async def test_empty_selection_does_not_fetch_quotes(monkeypatch: pytest.MonkeyPatch):
  """An explicitly empty product set never becomes an unfiltered quote sweep."""
  request = AsyncMock()
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with CoinbaseMarket.new(public=True) as sdk:
    assert await tickers(sdk, []) == {}
  request.assert_not_awaited()


@pytest.mark.parametrize('books', [[book('OTHER')], [book('ONE'), book('ONE')]])
async def test_wrong_or_duplicate_id_is_rejected(
  monkeypatch: pytest.MonkeyPatch, books: list[PriceBook]
):
  """Malformed identity never overwrites another product's quote."""
  monkeypatch.setattr(
    BestBidAsk, 'best_bid_ask', AsyncMock(return_value={'pricebooks': books})
  )
  async with CoinbaseMarket.new(public=True) as sdk:
    with pytest.raises(ApiError):
      await tickers(sdk, [product('ONE')])


async def test_quote_request_retries_without_replaying_prior_batch(
  monkeypatch: pytest.MonkeyPatch,
):
  """A translated rate limit retries just the failed native quote request."""
  ids = [f'P{i}' for i in range(QUOTE_BATCH_SIZE + 1)]
  request = AsyncMock(
    side_effect=[
      {'pricebooks': [book(identifier) for identifier in ids[:-1]]},
      core.RateLimited(429, 'cooldown'),
      {'pricebooks': [book(ids[-1])]},
    ]
  )
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with CoinbaseMarket.new(public=True) as sdk:
    with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
      assert len(
        await tickers(sdk, [product(identifier) for identifier in ids])
      ) == len(ids)
  assert [call.args[0] for call in request.await_args_list] == [
    ids[:-1],
    ids[-1:],
    ids[-1:],
  ]


async def test_quote_failure_is_not_hidden(monkeypatch: pytest.MonkeyPatch):
  """A failed quote endpoint cannot masquerade as a healthy catalogue-only run."""
  monkeypatch.setattr(
    BestBidAsk, 'best_bid_ask', AsyncMock(side_effect=core.ApiError(503, 'unavailable'))
  )
  async with CoinbaseMarket.new(public=True) as sdk:
    with pytest.raises(ApiError):
      await tickers(sdk, [product('ONE')])
