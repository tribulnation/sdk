"""Spot margin is a first-class market kind (ADR 0073): `kind`, discovery and interest."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from typing_extensions import Any, Mapping, Sequence, cast, get_args

from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.impl.accounts import VenueId
from tribulnation.sdk.market import (
  ExchangeDescription,
  InterestPayment,
  MarginExchange,
  MarginMarket,
  MarketKind,
  PerpExchange,
  PerpMarket,
  PerpStats,
  SpotExchange,
  Ticker,
  TradingMarkets,
  TradingVenue,
  is_margin,
  is_perp,
  is_spot,
)

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 21, tzinfo=timezone.utc)
PAYMENT = InterestPayment(time=END, asset='LIT', amount=Decimal('-0.02'))


class Ids:
  """Identity shared by the fake exchanges."""

  @property
  def venue_id(self) -> VenueId:
    return 'bitget'

  @property
  def account_id(self) -> str:
    return 'bitget'


class FakeMarginExchange(Ids, MarginExchange):
  """A spot-margin exchange with no markets."""

  @property
  def exchange_id(self) -> str:
    return 'margin'

  async def market(self, market_id: str, /) -> Any:
    raise NotImplementedError

  async def markets(self) -> Sequence[str]:
    return []

  async def tickers(
    self, markets: Any = None, *, settings: Any = {}, ttl: Any = None
  ) -> Mapping[str, Ticker]:
    return {}


class FakePerpExchange(FakeMarginExchange, PerpExchange):
  """A perpetual exchange with no markets."""

  @property
  def exchange_id(self) -> str:
    return 'usdt'

  async def perp_stats(
    self, markets: Any = None, *, settings: Any = {}, ttl: Any = None
  ) -> Mapping[str, PerpStats]:
    return {}


def test_margin_is_a_market_kind():
  """`MarketKind` and `ExchangeDescription.type` name the three kinds."""
  assert set(get_args(MarketKind)) == {'spot', 'margin', 'perp'}
  assert ExchangeDescription.__annotations__['type'] == MarketKind


def test_margin_exchanges_and_markets_say_margin():
  """A margin exchange or market is `'margin'`; a perpetual stays `'perp'` though it
  trades on margin too."""
  margin, perp = FakeMarginExchange(), FakePerpExchange()
  assert margin.kind == 'margin' and perp.kind == 'perp'
  assert is_margin(margin) and not is_perp(margin) and not is_spot(margin)
  assert is_margin(perp) and is_perp(perp)
  assert not issubclass(SpotExchange, MarginExchange)
  assert MarginMarket.kind.fget(cast(Any, None)) == 'margin'  # type: ignore[union-attr]
  assert PerpMarket.kind.fget(cast(Any, None)) == 'perp'  # type: ignore[union-attr]


def test_interest_defaults_to_not_implemented():
  """Venues without interest history refuse rather than answer empty."""
  market = SimpleNamespace(id='x:margin:BTCUSDT')
  with pytest.raises(NotImplementedError, match='Interest payments'):
    MarginMarket.interest_payments(cast(Any, market), START, END)


async def test_exchange_wide_interest_defaults_to_not_implemented():
  """`interest_payments(None, ...)` is venue-specific, like exchange-wide funding."""
  with pytest.raises(NotImplementedError, match='Exchange-wide interest'):
    await FakeMarginExchange().interest_payments(None, START, END)


def paged(*pages: Sequence[InterestPayment]) -> MagicMock:
  """A market whose `interest_payments` yields `pages`."""

  async def gen():
    for page in pages:
      yield page

  market = MagicMock()
  market.interest_payments = MagicMock(
    side_effect=lambda *_args: PaginatedResponse(gen())  # pyright: ignore[reportUnknownLambdaType]
  )
  return market


async def test_interest_routes_from_root_venue_and_exchange():
  """Root, venue and exchange reach the margin market's own history."""
  market = paged([PAYMENT])
  root = SimpleNamespace(margin_market=AsyncMock(return_value=market))
  venue = SimpleNamespace(margin_market=AsyncMock(return_value=market))
  exchange = SimpleNamespace(id='bitget:margin', market=AsyncMock(return_value=market))
  results = [
    await TradingMarkets.interest_payments(
      cast(Any, root), 'bitget:margin:LITUSDT', START, END
    ),
    await TradingVenue.interest_payments(
      cast(Any, venue), 'margin:LITUSDT', START, END
    ),
    await MarginExchange.interest_payments(cast(Any, exchange), 'LITUSDT', START, END),
  ]
  assert results == [[PAYMENT]] * 3
  root.margin_market.assert_awaited_once_with('bitget:margin:LITUSDT')
  venue.margin_market.assert_awaited_once_with('margin:LITUSDT')
  exchange.market.assert_awaited_once_with('LITUSDT')


async def test_venue_resolves_margin_exchanges_and_refuses_spot():
  """`margin_exchange` takes margin and perpetual exchanges, never spot."""
  margin, perp = FakeMarginExchange(), FakePerpExchange()
  exchanges: dict[str, Any] = {'margin': margin, 'usdt': perp, 'spot': object()}
  venue = SimpleNamespace(id='bitget', exchange=AsyncMock(side_effect=exchanges.get))
  stub = cast(Any, venue)
  assert await TradingVenue.margin_exchange(stub, 'margin') is margin
  assert await TradingVenue.margin_exchange(stub, 'usdt') is perp
  with pytest.raises(ValueError, match='not a margin or perpetual exchange'):
    await TradingVenue.margin_exchange(stub, 'spot')
