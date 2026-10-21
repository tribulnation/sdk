"""Order placement, price rounding and market metadata mapping, without network calls."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Callable

import pytest
from typed_margin_trade.exchange.cancel import Cancel
from typed_margin_trade.exchange.order import Order as OrderEndpoint
from typed_margin_trade.schemas import (
  ClearinghouseState,
  FilledOrder,
  L2Book,
  MarginSummary,
  PerpUniverseItem,
  SpotPair,
  SpotToken,
)
from tribulnation.margin_trade import MarginTradeMarket
from tribulnation.margin_trade.core import (
  Pair,
  order_state,
  parse_book,
  round_price,
  tick_size,
)
from tribulnation.margin_trade.market.collateral import cross_collateral
from tribulnation.margin_trade.market.markets import (
  PerpMarket,
  SpotMarket,
  next_settlement,
)
from tribulnation.sdk.core import ApiError, OrderRejected
from tribulnation.sdk.market import Order

BTC: PerpUniverseItem = {
  'name': 'BTC',
  'szDecimals': 5,
  'maxLeverage': 20,
  'takerFee': Decimal('0.0001'),
  'makerFee': Decimal('0.0002'),
  'category': 'Crypto',
  'index': 0,
}
PRL: SpotToken = {
  'name': 'PRL',
  'szDecimals': 2,
  'weiDecimals': 8,
  'index': 1,
  'tokenId': '0x1',
  'isCanonical': True,
  'evmContract': None,
  'fullName': None,
}
USDC: SpotToken = {**PRL, 'name': 'USDC', 'szDecimals': 6, 'weiDecimals': 6, 'index': 0}
PAIR: SpotPair = {
  'name': 'PRL/USDC',
  'tokens': [1, 0],
  'index': 0,
  'isCanonical': True,
  'takerFee': Decimal('0.0015'),
  'makerFee': Decimal('-0.0005'),
  'spotMinBuyQuoteAmount': Decimal('10'),
  'spotMinSellBaseQuantity': Decimal('10'),
}


def perp() -> PerpMarket:
  """A testnet BTC perpetual over a public client."""
  shared = MarginTradeMarket.new(mainnet=False).shared
  return PerpMarket(shared=shared, meta=BTC)


def spot() -> SpotMarket:
  """The testnet PRL/USDC pair over a public client."""
  shared = MarginTradeMarket.new(mainnet=False).shared
  return SpotMarket(shared=shared, meta=Pair(PAIR, PRL, USDC))


@pytest.mark.parametrize(
  ('price', 'decimals', 'expected'),
  [
    (Decimal('84512.37'), 1, Decimal('84512')),
    (Decimal('76041.5'), 1, Decimal('76042')),
    (Decimal('1.23456'), 6, Decimal('1.2346')),
    (Decimal('2.3714'), 4, Decimal('2.3714')),
    (Decimal('0.000123456'), 6, Decimal('0.000123')),
    (Decimal('40'), 1, Decimal('40')),
    (Decimal('4E+1'), 1, Decimal('40')),
  ],
)
def test_round_price(price: Decimal, decimals: int, expected: Decimal):
  """Five significant figures, the decimal cap, integers kept, positional form."""
  rounded = round_price(price, max_decimals=decimals)
  assert rounded == expected
  assert 'E' not in str(rounded)


def test_tick_size():
  """`10^-min(5, max - szDecimals)`, as observed on BTC and PRL/USDC."""
  assert tick_size(5, max_decimals=6) == Decimal('0.1')
  assert tick_size(2, max_decimals=8) == Decimal('0.00001')


def test_empty_book():
  """An empty book is `levels: []`, a one-sided one `[[...], []]`."""
  t = datetime(2026, 10, 21, tzinfo=timezone.utc)
  empty: L2Book = {'coin': 'PRL/USDC', 'time': t, 'levels': []}
  one_sided: L2Book = {
    'coin': 'PRL',
    'time': t,
    'levels': [[{'px': Decimal('2.35'), 'sz': Decimal('4'), 'n': 1}], []],
  }
  assert parse_book(empty).bids == [] and parse_book(empty).asks == []
  book = parse_book(one_sided)
  assert book.bids[0].price == Decimal('2.35') and book.asks == []


def test_order_state_is_signed():
  """Sells carry negative quantities; the filled part is `origSz - sz`."""
  state = order_state(
    {
      'coin': 'BTC',
      'side': 'A',
      'limitPx': Decimal('82655'),
      'sz': Decimal('0.0004'),
      'oid': 7,
      'timestamp': datetime(2026, 10, 21, tzinfo=timezone.utc),
      'origSz': Decimal('0.001'),
      'orderType': 'Limit',
      'reduceOnly': False,
      'isTrigger': False,
      'isPositionTpsl': False,
      'triggerCondition': 'N/A',
      'triggerPx': None,
    },
    active=True,
  )
  assert state.qty == Decimal('-0.001')
  assert state.filled_qty == Decimal('-0.0006')


def test_next_settlement():
  """Funding settles on the next full hour."""
  now = datetime(2026, 10, 21, 15, 26, 3, tzinfo=timezone.utc)
  assert next_settlement(now) == datetime(2026, 10, 21, 16, tzinfo=timezone.utc)


def test_cross_collateral():
  """The cross bucket with a 0.001 BTC position, as testnet reported it."""
  summary: MarginSummary = {
    'accountValue': Decimal('99998.090124'),
    'totalMarginUsed': Decimal('84.5638'),
    'totalNtlPos': Decimal('84.5638'),
    'totalRawUsd': Decimal('99998.090124'),
  }
  state: ClearinghouseState = {
    'assetPositions': [],
    'crossMarginSummary': summary,
    'marginSummary': summary,
    'crossMaintenanceMarginUsed': Decimal('2.114095'),
    'withdrawable': Decimal('99913.526324'),
    'time': datetime(2026, 10, 21, tzinfo=timezone.utc),
  }
  bucket = cross_collateral(state)
  assert bucket.free_collateral == Decimal('99913.526324')
  assert bucket.initial_margin == Decimal('84.5638')
  assert bucket.maintenance_margin == Decimal('2.114095')
  assert bucket.leverage == Decimal('84.5638') / Decimal('99998.090124')


@pytest.mark.parametrize(
  ('market', 'asset', 'price'),
  [(perp, 0, Decimal('76042')), (spot, 10000, Decimal('1.2346'))],
)
async def test_place_order_spec(
  market: Callable[[], PerpMarket | SpotMarket],
  asset: int,
  price: Decimal,
  monkeypatch: pytest.MonkeyPatch,
):
  """Asset index, side, rounded price, size, tif and `cloid` go on the wire."""
  endpoint = AsyncMock(return_value={'statuses': [{'resting': {'oid': 5}}]})
  monkeypatch.setattr(OrderEndpoint, 'order', endpoint)
  m = market()
  requested = Decimal('76041.5') if asset == 0 else Decimal('1.23456')
  order: Order = {
    'type': 'POST_ONLY',
    'qty': Decimal('-0.001'),
    'price': requested,
    'client_order_id': '0x' + '1f' * 16,
  }
  response = await m.place_order(order)
  (specs,), kwargs = endpoint.call_args.args, endpoint.call_args.kwargs
  assert specs == [
    {
      'a': asset,
      'b': False,
      'p': price,
      's': Decimal('0.001'),
      'r': False,
      't': {'limit': {'tif': 'Alo'}},
      'c': '0x' + '1f' * 16,
    }
  ]
  assert kwargs == {'grouping': 'na'}
  assert response.id == '5' and response.filled_qty is None


async def test_filled_order_reports_its_size(monkeypatch: pytest.MonkeyPatch):
  """A `filled` status reports `totalSz` as `filled_qty`."""
  filled: FilledOrder = {
    'oid': 9,
    'totalSz': Decimal('0.001'),
    'origSz': Decimal('0.001'),
    'avgPx': Decimal('84564.4'),
  }
  monkeypatch.setattr(
    OrderEndpoint, 'order', AsyncMock(return_value={'statuses': [{'filled': filled}]})
  )
  order: Order = {'type': 'MARKET', 'qty': Decimal('0.001'), 'price': Decimal('85418')}
  response = await perp().place_order(order)
  assert response.id == '9' and response.filled_qty == Decimal('0.001')


async def test_error_status_is_rejected(monkeypatch: pytest.MonkeyPatch):
  """An order's own error status (e.g. `slippage exceeded`) is a definitive refusal."""
  result = {'statuses': [{'error': 'slippage exceeded'}]}
  monkeypatch.setattr(OrderEndpoint, 'order', AsyncMock(return_value=result))
  order: Order = {'type': 'MARKET', 'qty': Decimal('0.001'), 'price': Decimal('101000')}
  with pytest.raises(OrderRejected):
    await perp().place_order(order)


async def test_failed_cancel_raises(monkeypatch: pytest.MonkeyPatch):
  """A cancel answered with anything but `success` raises."""
  monkeypatch.setattr(
    Cancel, 'cancel', AsyncMock(return_value={'statuses': ['order not found']})
  )
  with pytest.raises(ApiError):
    await perp().cancel_order('1')


async def test_rules_use_the_markets_own_fees(monkeypatch: pytest.MonkeyPatch):
  """Perpetual fees are the universe item's, charged in USD; spot names no fee asset."""
  m = perp()
  m.shared.perps['BTC'] = BTC
  rules = await m.rules()
  assert rules.fees is not None and rules.fees.taker_buy == Decimal('0.0001')
  assert rules.fees.maker_sell == Decimal('0.0002')
  assert rules.fee_asset == 'USD' and rules.tick_size == Decimal('0.1')
  s = spot()
  s.shared.pairs['PRL/USDC'] = Pair(PAIR, PRL, USDC)
  spot_rules = await s.rules()
  assert spot_rules.fee_asset is None
  assert spot_rules.fees is not None and spot_rules.fees.maker_buy == Decimal('-0.0005')


async def test_unsupported_methods_raise():
  """Account fee rates and funding-rate history are not served by the venue."""
  with pytest.raises(NotImplementedError):
    await perp().fees()
  with pytest.raises(NotImplementedError):
    perp().funding_rates()
