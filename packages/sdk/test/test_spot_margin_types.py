"""Spot and margin market types, collateral IDs and their resolver (ADR 0051)."""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, Collection, Mapping, Sequence, cast

from tribulnation.sdk.impl.accounts import VenueId
from tribulnation.sdk.market import (
  Balance,
  Collateral,
  MarginMarket,
  Market,
  PerpExchange,
  PerpStats,
  Settings,
  SpotCollateralIds,
  SpotExchange,
  SpotMarket,
  SpotRules,
  Ticker,
  TradingMarkets,
  TradingVenue,
  is_margin,
  is_perp,
  is_spot,
)


class Ids:
  """The two identity properties every fake needs."""

  @property
  def venue_id(self) -> VenueId:
    return 'hyperliquid'

  @property
  def account_id(self) -> str:
    return 'hl'


@dataclass(frozen=True)
class FakeSpotExchange(Ids, SpotExchange):
  """A spot wallet holding 10 of every asset, 4 of them in orders."""

  @property
  def exchange_id(self) -> str:
    return 'spot'

  async def market(self, market_id: str, /) -> SpotMarket:
    raise NotImplementedError

  async def markets(self) -> Sequence[str]:
    return []

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    return {}

  async def balance(self, asset: str, /) -> Balance:
    return Balance(total=Decimal(10), free=Decimal(6))


@dataclass(frozen=True)
class FakePerpExchange(Ids, PerpExchange):
  """A perpetual exchange with no markets."""

  @property
  def exchange_id(self) -> str:
    return ''

  async def market(self, market_id: str, /) -> Any:
    raise NotImplementedError

  async def markets(self) -> Sequence[str]:
    return []

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    return {}

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    return {}


def venue_of(**exchanges: Any) -> Any:
  """A venue stub whose `exchange()` serves the given exchanges by ID."""
  stub = SimpleNamespace(id='hl')

  async def exchange(exchange_id: str) -> Any:
    return exchanges[exchange_id]

  async def spot_exchange(exchange_id: str) -> SpotExchange:
    return await TradingVenue.spot_exchange(cast(Any, stub), exchange_id)

  async def perp_exchange(exchange_id: str) -> PerpExchange:
    return await TradingVenue.perp_exchange(cast(Any, stub), exchange_id)

  stub.exchange = exchange
  stub.spot_exchange = spot_exchange
  stub.perp_exchange = perp_exchange
  return stub


def spot_rules() -> SpotRules:
  """UBTC/USDC rules, by token index."""
  return SpotRules(
    base='197',
    quote='0',
    fee_asset=None,
    tick_size=Decimal(1),
    step_size=Decimal(1),
    api=True,
  )


async def test_spot_collateral_ids_lead_with_the_account_and_exchange():
  """`<account>:<exchange>:<asset>` for the rules' base and quote."""
  market = SimpleNamespace(
    account_id='hl', exchange_id='spot', rules=AsyncMock(return_value=spot_rules())
  )
  assert await SpotMarket.collateral_ids(cast(Any, market)) == SpotCollateralIds(
    base='hl:spot:197', quote='hl:spot:0'
  )


async def test_margin_collateral_id_has_no_guessed_default():
  """A unified venue that forgets to override must not silently get a pool ID."""
  market = SimpleNamespace(id='x:perp:BTC')
  with pytest.raises(NotImplementedError, match='Collateral ID'):
    await MarginMarket.collateral_id(cast(Any, market))


async def test_venue_resolves_spot_assets_and_perp_pools():
  """Two segments name a spot asset, one a perpetual pool (`''` included)."""
  pool = Collateral(equity=Decimal(5), free_collateral=Decimal(1))
  perp = FakePerpExchange()
  object.__setattr__(perp, 'collateral', AsyncMock(return_value=pool))
  venue = venue_of(spot=FakeSpotExchange(), **{'': perp})
  assert await TradingVenue.collateral(venue, 'spot:0') == Collateral(
    equity=Decimal(10), free_collateral=Decimal(6)
  )
  assert await TradingVenue.collateral(venue, '') == pool


async def test_resolver_rejects_ids_naming_the_wrong_kind():
  """A spot exchange has no pool; a perpetual exchange has no assets."""
  venue = venue_of(spot=FakeSpotExchange(), perp=FakePerpExchange())
  with pytest.raises(ValueError, match='not a perpetual exchange'):
    await TradingVenue.collateral(venue, 'spot')
  with pytest.raises(ValueError, match='not a spot exchange'):
    await TradingVenue.collateral(venue, 'perp:USDC')


async def test_root_resolver_routes_by_account_key():
  """The account key picks the venue; the rest is the venue's collateral ID."""
  collateral = Collateral(equity=Decimal(1), free_collateral=Decimal(1))
  venue = SimpleNamespace(collateral=AsyncMock(return_value=collateral))
  root = SimpleNamespace(venue=AsyncMock(return_value=venue))
  assert await TradingMarkets.collateral(cast(Any, root), 'hl:spot:0') == collateral
  root.venue.assert_awaited_once_with('hl')
  venue.collateral.assert_awaited_once_with('spot:0')


async def test_root_routes_spot_and_margin_reads_by_kind():
  """Balances go through spot markets; margin reads through perpetual markets."""
  market = SimpleNamespace(
    balances=AsyncMock(return_value='balances'),
    collateral_ids=AsyncMock(return_value='ids'),
    collateral_id=AsyncMock(return_value='hl:spot:0'),
    position=AsyncMock(return_value='position'),
    available_notional=AsyncMock(return_value=Decimal(3)),
  )
  root = SimpleNamespace(
    spot_market=AsyncMock(return_value=market),
    perp_market=AsyncMock(return_value=market),
  )
  stub = cast(Any, root)
  assert await TradingMarkets.balances(stub, 'hl:spot:UBTC/USDC:142') == 'balances'
  assert await TradingMarkets.collateral_ids(stub, 'hl:spot:UBTC/USDC:142') == 'ids'
  assert root.spot_market.await_count == 2
  assert await TradingMarkets.collateral_id(stub, 'hl::ETH') == 'hl:spot:0'
  assert await TradingMarkets.position(stub, 'hl::ETH') == 'position'
  assert await TradingMarkets.available_notional(stub, 'hl::ETH') == 3
  assert root.perp_market.await_count == 3


def test_kinds_narrow_exchanges():
  """`is_spot`/`is_perp` and `kind` tell exchanges apart; markets alike."""
  spot, perp = FakeSpotExchange(), FakePerpExchange()
  assert is_spot(spot) and not is_perp(spot) and spot.kind == 'spot'
  assert is_perp(perp) and not is_spot(perp) and perp.kind == 'perp'
  assert issubclass(SpotMarket, Market) and not issubclass(SpotMarket, MarginMarket)
  assert is_margin(cast(Any, SimpleNamespace())) is False


def test_unmigrated_markets_have_no_kind():
  """A plain `Market` is neither kind: `kind` raises rather than guess."""
  market = SimpleNamespace(id='x:spot:BTCUSDT')
  with pytest.raises(NotImplementedError, match='kind'):
    Market.kind.fget(cast(Any, market))  # type: ignore[union-attr]
