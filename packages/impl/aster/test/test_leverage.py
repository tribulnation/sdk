"""Account leverage from `positionRisk`, its cache, and the default available notional."""

from decimal import Decimal
from unittest.mock import AsyncMock
from typing_extensions import Any, cast

import pytest
from typed_aster.futures.position.risk import PositionRisk, Risk
from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Shared
from tribulnation.aster.market.markets import PerpMarket, position_leverage
from tribulnation.sdk.core import MissingData
from tribulnation.sdk.market import Collateral

SYMBOL = 'ASTERUSDT'


def risk(**fields: Any) -> PositionRisk:
  """A one-way, flat `positionRisk` row with the fields leverage reads."""
  row: dict[str, Any] = {
    'symbol': SYMBOL,
    'leverage': 5,
    'marginType': 'cross',
    'positionSide': 'BOTH',
    'positionAmt': Decimal(0),
    'entryPrice': Decimal(0),
  }
  row.update(fields)
  return cast(PositionRisk, row)


def market() -> PerpMarket:
  """A testnet perpetual over a public client; requests are patched per test."""
  return PerpMarket(
    shared=AsterMarket.new(public=True, mainnet=False).shared, symbol=SYMBOL
  )


def test_leverage_is_the_symbols_initial_leverage():
  """Rows of other symbols are ignored; hedge-mode sides use the lowest setting."""
  rows = [risk(symbol='BTCUSDT', leverage=20), risk(leverage=7)]
  assert position_leverage(rows, SYMBOL) == 7
  hedge = [
    risk(positionSide='LONG', leverage=10),
    risk(positionSide='SHORT', leverage=8),
  ]
  assert position_leverage(hedge, SYMBOL) == 8


def test_missing_symbol_is_missing_data():
  """The venue lists flat symbols too, so an absent row is not an unset leverage."""
  with pytest.raises(MissingData):
    position_leverage([risk(symbol='BTCUSDT')], SYMBOL)


async def test_leverage_is_cached_until_refetch(monkeypatch: pytest.MonkeyPatch):
  """One request per symbol; `refetch=True` reads the setting again."""
  endpoint = AsyncMock(side_effect=[[risk(leverage=5)], [risk(leverage=3)]])
  monkeypatch.setattr(Risk, 'risk', endpoint)
  m = market()
  assert await m.leverage() == 5
  assert await m.leverage() == 5
  assert endpoint.await_count == 1
  assert await m.leverage(refetch=True) == 3
  assert await m.leverage() == 3
  assert endpoint.await_count == 2


async def test_available_notional_is_free_cross_balance_times_leverage(
  monkeypatch: pytest.MonkeyPatch,
):
  """The SDK default: the cross bucket's free collateral times the leverage."""
  monkeypatch.setattr(Risk, 'risk', AsyncMock(return_value=[risk(leverage=4)]))
  collateral = Collateral(equity=Decimal(120), free_collateral=Decimal(100))
  monkeypatch.setattr(Shared, 'cross_collateral', AsyncMock(return_value=collateral))
  assert await market().available_notional() == Decimal(400)
