"""Credential-free market reads use validated public endpoints and native quotes."""

from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter
from typed_coinbase.app.advanced_trade.http.products.public.list import (
  List,
  PublicProduct,
  PublicProductsPage,
)
from typed_coinbase.schemas import Product, ProductBookResponse
from typed_core import exceptions as core

from tribulnation.coinbase import CoinbaseMarket
from tribulnation.coinbase.market.impl.catalogue import tickers
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl import accounts
from tribulnation.sdk.core import ApiError, Context, RateLimited


def product(product_id: str = 'BTC-USD') -> Product:
  """Create a fully validated spot product with nonzero public rules."""
  row: Product = {
    'product_id': product_id,
    'price': Decimal('100'),
    'volume_24h': Decimal('9'),
    'price_percentage_change_24h': Decimal('1'),
    'volume_percentage_change_24h': Decimal('2'),
    'base_increment': Decimal('0.001'),
    'quote_increment': Decimal('0.01'),
    'quote_min_size': Decimal('1'),
    'quote_max_size': Decimal('10000'),
    'base_min_size': Decimal('0.001'),
    'base_max_size': Decimal('100'),
    'base_name': 'Bitcoin',
    'quote_name': 'US Dollar',
    'watched': False,
    'is_disabled': False,
    'new': False,
    'status': 'online',
    'cancel_only': False,
    'limit_only': False,
    'post_only': False,
    'trading_disabled': False,
    'auction_mode': False,
    'base_display_symbol': 'BTC',
    'quote_display_symbol': 'USD',
    'product_type': 'SPOT',
    'product_venue': 'CBE',
    'approximate_quote_24h_volume': Decimal('900'),
    'new_at': None,
  }
  return row


def page(row: Product) -> PublicProductsPage:
  """Wrap the product in a complete public response with schema validation."""
  return {
    'products': [
      TypeAdapter(PublicProduct).validate_json(TypeAdapter(Product).dump_json(row))
    ],
    'num_products': 1,
    'pagination': {'has_next': False, 'has_prev': False},
  }


async def test_public_router_reads_without_credentials(monkeypatch: pytest.MonkeyPatch):
  """Exercise real endpoint validation and auth guards through MarketSDK."""
  monkeypatch.delenv('COINBASE_API_KEY_NAME', raising=False)
  monkeypatch.delenv('COINBASE_PRIVATE_KEY', raising=False)
  row = product()
  identifier = row['product_id']
  catalogue = page(row)
  quote: ProductBookResponse = {
    'pricebook': {
      'product_id': identifier,
      'bids': [{'price': Decimal('98'), 'size': Decimal('2')}],
      'asks': [],
    }
  }
  paths: list[str] = []

  async def request(method: str, url: str, **kwargs: object) -> httpx.Response:
    """Serve only unsigned public paths, preserving typed response validation."""
    assert method == 'GET'
    path = httpx.URL(url).path
    paths.append(path)
    if path == '/api/v3/brokerage/market/products':
      content = TypeAdapter(PublicProductsPage).dump_json(catalogue)
    elif path == f'/api/v3/brokerage/market/products/{identifier}':
      content = TypeAdapter(Product).dump_json(row)
    elif path == '/api/v3/brokerage/market/product_book':
      assert kwargs['params'] == {'product_id': identifier, 'limit': 1}
      content = TypeAdapter(ProductBookResponse).dump_json(quote)
    else:
      raise AssertionError(f'Unexpected endpoint: {path}')
    return httpx.Response(200, content=content)

  async with MarketSDK(accounts={'coinbase': accounts.Coinbase(public=True)}) as sdk:
    venue = await sdk.venue('coinbase')
    assert isinstance(venue, CoinbaseMarket)
    assert venue.client.app_client.credentials is None
    monkeypatch.setattr(venue.client.app_client.http, 'request', request)
    exchange = await venue.exchange('spot')
    assert list(await exchange.markets()) == [identifier]
    ticker = (await exchange.tickers([identifier]))[identifier]
    assert (ticker.last, ticker.base_volume_24h) == (Decimal('100'), Decimal('9'))
    assert (ticker.bid, ticker.bid_qty) == (Decimal('98'), Decimal('2'))
    assert ticker.ask is None and ticker.ask_qty is None
    market = await exchange.market(identifier)
    rules = await market.rules()
    assert rules.tick_size == Decimal('0.01')
    assert rules.step_size == Decimal('0.001')
    assert rules.min_value == Decimal('1') and rules.max_qty == Decimal('100')
    assert rules.fees is None and rules.api
    await market.rules()
    assert paths.count(f'/api/v3/brokerage/market/products/{identifier}') == 1
    await market.rules(refetch=True)
    assert paths.count(f'/api/v3/brokerage/market/products/{identifier}') == 2


@pytest.mark.parametrize('defect', ['next', 'cursor', 'metadata', 'duplicate', 'count'])
async def test_incomplete_public_catalogue_is_rejected(
  monkeypatch: pytest.MonkeyPatch, defect: str
):
  """Never report a partial or duplicate catalogue as successful discovery."""
  response = page(product())
  if defect == 'next':
    response['pagination'] = {'has_next': True, 'has_prev': False}
  elif defect == 'cursor':
    response['pagination'] = {
      'has_next': False,
      'has_prev': False,
      'next_cursor': 'next',
    }
  elif defect == 'metadata':
    del response['pagination']
  elif defect == 'duplicate':
    response['products'] *= 2
    response['num_products'] = 2
  else:
    response['num_products'] = 2
  request = AsyncMock(return_value=response)
  monkeypatch.setattr(List, 'list', request)
  async with CoinbaseMarket.new(public=True) as venue:
    exchange = await venue.exchange('spot')
    with pytest.raises(ApiError):
      await exchange.markets()
  request.assert_awaited_once_with(product_type='SPOT')


async def test_public_quotes_retry_only_the_failed_product(
  monkeypatch: pytest.MonkeyPatch,
):
  """One failing book does not replay successful prior product reads."""
  from typed_coinbase.app.advanced_trade.http.products.public.book import Book

  first = product()
  second = product('ETH-USD')
  request = AsyncMock(
    side_effect=[
      {'pricebook': {'product_id': first['product_id'], 'bids': [], 'asks': []}},
      core.RateLimited(429, 'cooldown'),
      {'pricebook': {'product_id': second['product_id'], 'bids': [], 'asks': []}},
    ]
  )
  monkeypatch.setattr(Book, 'book', request)
  async with CoinbaseMarket.new(public=True) as venue:
    with Context().retried(RateLimited, max_retries=1, base_delay=0).use():
      result = await tickers(venue, [first, second])
  assert len(result) == 2
  assert [call.args[0] for call in request.await_args_list] == [
    first['product_id'],
    second['product_id'],
    second['product_id'],
  ]


async def test_authenticated_product_lookup_stays_private(
  monkeypatch: pytest.MonkeyPatch,
):
  """Credentialed accounts retain the existing single-product endpoint."""
  from typed_coinbase.app.advanced_trade.http.products.get import Get

  request = AsyncMock(return_value=product())
  monkeypatch.setattr(Get, 'get', request)
  async with CoinbaseMarket.new(key_name='test', private_key='test') as venue:
    assert not venue.shared.public
    exchange = await venue.exchange('spot')
    market = await exchange.market('BTC-USD')
    await market.rules()
  request.assert_awaited_once_with('BTC-USD')


@pytest.mark.parametrize('failure', ['identity', 'request'])
async def test_public_quote_failures_are_not_hidden(
  monkeypatch: pytest.MonkeyPatch, failure: str
):
  """Wrong-product books and failed requests cannot produce plausible tickers."""
  from typed_coinbase.app.advanced_trade.http.products.public.book import Book

  request = AsyncMock(
    return_value={'pricebook': {'product_id': 'WRONG', 'bids': [], 'asks': []}}
  )
  if failure == 'request':
    request.side_effect = core.ApiError(503, 'unavailable')
  monkeypatch.setattr(Book, 'book', request)
  async with CoinbaseMarket.new(public=True) as venue:
    with pytest.raises(ApiError):
      await tickers(venue, [product()])


async def test_public_fallback_prefers_available_credentials(
  monkeypatch: pytest.MonkeyPatch,
):
  """Allowing public access must not discard available batched private access."""
  from typed_coinbase.app.advanced_trade.http.products.best_bid_ask import BestBidAsk

  monkeypatch.setenv('COINBASE_API_KEY_NAME', 'test')
  monkeypatch.setenv('COINBASE_PRIVATE_KEY', 'test')
  request = AsyncMock(return_value={'pricebooks': []})
  monkeypatch.setattr(BestBidAsk, 'best_bid_ask', request)
  async with MarketSDK(accounts={'coinbase': accounts.Coinbase(public=True)}) as sdk:
    venue = await sdk.venue('coinbase')
    assert isinstance(venue, CoinbaseMarket)
    assert not venue.shared.public
    await tickers(venue, [product()])
  request.assert_awaited_once_with(['BTC-USD'])
