"""Product-local discovery, public routing and account boundaries for Bitget futures."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typing_extensions import cast
from typed_bitget.classic.mix.market.contracts import MixContract

from tribulnation.bitget.market import BitgetMarket
from tribulnation.bitget.market.impl.parse import PERP_PRODUCTS, PerpProduct


def contract(product: PerpProduct, *, delivery: bool = False) -> MixContract:
  """Build distinct product metadata even when native symbols collide."""
  return cast(
    MixContract,
    {
      'symbol': 'DELIVERY' if delivery else 'SAME',
      'symbolType': 'delivery' if delivery else 'perpetual',
      'baseCoin': 'BTC',
      'quoteCoin': {
        'USDT-FUTURES': 'USDT',
        'USDC-FUTURES': 'USDC',
        'COIN-FUTURES': 'USD',
      }[product],
      'priceEndStep': 1,
      'pricePlace': 1,
      'sizeMultiplier': Decimal('0.001'),
      'minTradeNum': Decimal('0.001'),
      'minTradeUSDT': Decimal('5'),
      'maxOrderQty': 100,
      'sellLimitPriceRatio': Decimal('0.05'),
      'buyLimitPriceRatio': Decimal('0.05'),
      'feeRateUpRatio': Decimal('0'),
      'makerFeeRate': Decimal('0.0002'),
      'takerFeeRate': Decimal('0.0006'),
      'symbolStatus': 'normal',
    },
  )


@pytest.fixture
def venue(monkeypatch: pytest.MonkeyPatch) -> BitgetMarket:
  """Use the real venue and public client, replacing only the metadata request."""
  owner = BitgetMarket.new(public=True)

  async def contracts(product: PerpProduct, *, validate: bool):
    """Return one perpetual and one dated contract in each product line."""
    return [contract(product), contract(product, delivery=True)]

  monkeypatch.setattr(
    type(owner.client.classic.mix.market), 'contracts', AsyncMock(side_effect=contracts)
  )
  return owner


@pytest.mark.parametrize('exchange_id', ['perp', 'USDT-FUTURES', 'unknown'])
async def test_exchange_ids_have_no_implicit_aliases(
  venue: BitgetMarket, exchange_id: str
):
  """Public discovery IDs are the only accepted identities for futures products."""
  with pytest.raises(ValueError, match='Invalid exchange ID'):
    await venue.exchange(exchange_id)
  with pytest.raises(ValueError, match='Invalid perp exchange ID'):
    await venue.perp_exchange(exchange_id)


async def test_product_caches_are_independent(venue: BitgetMarket):
  """Shared transport must not let one product's symbol overwrite another's rules."""
  assert [item['id'] for item in await venue.exchanges()] == [
    'spot',
    'usdt',
    'usdc',
    'coin-classic',
  ]
  exchanges = [await venue.perp_exchange(id) for id in PERP_PRODUCTS]
  assert (
    await asyncio.gather(*(exchange.markets() for exchange in exchanges))
    == [['SAME']] * 3
  )
  for exchange, quote, fee_asset in zip(
    exchanges, ('USDT', 'USDC', 'USD'), ('USDT', 'USDC', 'BTC')
  ):
    market = await exchange.market('SAME')
    assert market.exchange_id == exchange.exchange_id
    assert market.product == exchange.product
    rules = await market.rules()
    assert rules.fee_asset == fee_asset
    assert rules.min_value == (Decimal(5) if quote == 'USDT' else None)
    with pytest.raises(ValueError, match='Unknown'):
      await exchange.market('DELIVERY')
  requests = cast(AsyncMock, venue.client.classic.mix.market.contracts)
  assert requests.await_count == 3
  await (await exchanges[1].market('SAME')).rules(refetch=True)
  assert requests.await_count == 4
  assert requests.await_args is not None and requests.await_args.args == (
    'USDC-FUTURES',
  )


async def test_uta_coin_is_explicitly_unsupported(venue: BitgetMarket):
  """Reserve UTA identity without advertising it or serving Classic data under it."""
  assert 'coin' not in {row['id'] for row in await venue.exchanges()}
  for resolve in (venue.exchange, venue.perp_exchange):
    with pytest.raises(NotImplementedError, match='issue #32'):
      await resolve('coin')


@pytest.mark.parametrize('exchange_id', ['usdt', 'usdc', 'coin-classic'])
async def test_public_requests_address_the_product(
  venue: BitgetMarket, exchange_id: str, monkeypatch: pytest.MonkeyPatch
):
  """Books, index and current funding must carry both native symbol and product."""
  exchange = await venue.perp_exchange(exchange_id)
  market = await exchange.market('SAME')
  api = venue.client.classic.mix.market
  book = AsyncMock(return_value={'bids': [(99, 1)], 'asks': [(101, 2)]})
  prices = AsyncMock(return_value=[{'indexPrice': Decimal(100)}])
  now = datetime.now(timezone.utc)
  funding = AsyncMock(
    return_value=[
      {
        'symbol': 'SAME',
        'fundingRate': Decimal('0.0001'),
        'nextUpdate': now,
        'fundingRateInterval': 8,
      }
    ]
  )
  monkeypatch.setattr(type(api), 'orderbook', book)
  monkeypatch.setattr(type(api), 'symbol_price', prices)
  monkeypatch.setattr(type(venue.client.uta.market.funding_rate), 'current', funding)
  assert (await market.depth(levels=1)).best_bid.price == 99
  assert await market.index() == 100
  assert (await market.next_funding()).interval == timedelta(hours=8)
  for endpoint in (book, prices):
    assert endpoint.await_args is not None
    assert endpoint.await_args.args == ('SAME',)
    assert endpoint.await_args.kwargs['product_type'] == market.product
  assert funding.await_args is not None
  assert funding.await_args.args == (market.product,)
  assert funding.await_args.kwargs['symbol'] == 'SAME'
  assert await exchange.tickers([]) == {}
  assert await exchange.perp_stats([]) == {}


@pytest.mark.parametrize('exchange_id', ['usdc', 'coin-classic'])
async def test_new_products_cannot_enter_account_adapters(
  venue: BitgetMarket, exchange_id: str, monkeypatch: pytest.MonkeyPatch
):
  """New product support makes no account-data guarantee and never tries account auth."""
  mode = AsyncMock(side_effect=AssertionError('account mode must not be queried'))
  monkeypatch.setattr(type(venue.account), 'is_uta', mode)
  exchange = await venue.perp_exchange(exchange_id)
  market = await exchange.market('SAME')
  for method in (
    market.fees,
    market.open_orders,
    market.perp_position,
    market.perp_collateral,
    market.available_notional,
    exchange.perp_collateral,
  ):
    with pytest.raises(NotImplementedError, match='public market data only'):
      await method()
  now = datetime.now(timezone.utc)
  with pytest.raises(NotImplementedError, match='public market data only'):
    await market.trades_history(now - timedelta(days=1), now)
  with pytest.raises(NotImplementedError, match='public market data only'):
    async with market.trades_stream():
      pass
  mode.assert_not_called()
