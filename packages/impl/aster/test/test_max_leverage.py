"""Leverage lowered to a lowered maximum on refusal, and account reads shared between symbols."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
import asyncio

import pytest
from typing_extensions import Any
from typed_aster import BadRequest as ClientBadRequest
from typed_aster.futures.account.info_with_join_margin import InfoWithJoinMargin
from typed_aster.futures.account.leverage_brackets import LeverageBrackets
from typed_aster.futures.account.set_leverage import SetLeverage
from typed_aster.futures.position.risk import Risk
from typed_aster.futures.trade.place_order import PlaceOrder
from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Shared
from tribulnation.aster.market.markets import PerpMarket, leverage_above_max
from tribulnation.sdk.core import NetworkError, OrderRejected
from tribulnation.sdk.market import Order

SYMBOL = 'OPUSDT'
SECOND = timedelta(seconds=1)
MINUTE = timedelta(minutes=1)
ORDER: Order = {'type': 'POST_ONLY', 'qty': Decimal('1'), 'price': Decimal('0.75')}
ABOVE_MAX = ClientBadRequest(
  400,
  {
    'code': -2027,
    'msg': 'The current symbol’s leverage exceeds the maximum supported leverage.',
  },
)


def risk(symbol: str = SYMBOL, leverage: int = 20) -> dict[str, Any]:
  """A one-way, flat `positionRisk` row."""
  return {
    'symbol': symbol,
    'leverage': leverage,
    'marginType': 'cross',
    'positionSide': 'BOTH',
    'positionAmt': Decimal(0),
    'entryPrice': Decimal(0),
  }


def brackets(*levels: int) -> list[dict[str, Any]]:
  """The symbol's brackets, lowest notional first."""
  return [
    {
      'symbol': SYMBOL,
      'brackets': [
        {'bracket': i + 1, 'initialLeverage': level} for i, level in enumerate(levels)
      ],
    }
  ]


def placed(order_id: int = 1) -> dict[str, Any]:
  """A resting order's `RESULT` answer."""
  return {'orderId': order_id, 'status': 'NEW', 'executedQty': Decimal(0)}


def shared() -> Shared:
  """A testnet client's shared state; requests are patched per test."""
  return AsterMarket.new(public=True, mainnet=False).shared


def perp(s: Shared, symbol: str = SYMBOL) -> PerpMarket:
  """A perpetual over `s`."""
  return PerpMarket(shared=s, symbol=symbol)


@pytest.fixture
def venue(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
  """Leverage at 20x, a 10x maximum, and orders that rest."""
  mocks = {
    'risk': AsyncMock(return_value=[risk()]),
    'brackets': AsyncMock(return_value=brackets(10, 5)),
    'set': AsyncMock(return_value={'symbol': SYMBOL, 'leverage': 10}),
    'place': AsyncMock(return_value=placed()),
  }
  monkeypatch.setattr(Risk, 'risk', mocks['risk'])
  monkeypatch.setattr(LeverageBrackets, 'leverage_brackets', mocks['brackets'])
  monkeypatch.setattr(SetLeverage, 'set_leverage', mocks['set'])
  monkeypatch.setattr(PlaceOrder, 'place_order', mocks['place'])
  return mocks


async def test_orders_never_touch_the_leverage(venue: dict[str, AsyncMock]):
  """Orders that are accepted read and set nothing, even at a setting below the maximum."""
  venue['risk'].return_value = [risk(leverage=3)]
  m = perp(shared())
  await asyncio.gather(m.place_order(ORDER), m.place_order(ORDER))
  assert venue['place'].await_count == 2
  assert venue['brackets'].await_count == 0
  assert venue['risk'].await_count == 0
  assert venue['set'].await_count == 0


async def test_a_refusal_lowers_the_leverage_and_resends(venue: dict[str, AsyncMock]):
  """A `-2027` at 20x under a 10x maximum lowers the setting to 10x and resends once."""
  s = shared()
  venue['place'].side_effect = [ABOVE_MAX, placed(2)]
  response = await perp(s).place_order(ORDER)
  call = venue['set'].await_args
  assert response.id == '2' and venue['place'].await_count == 2
  assert call is not None and (call.args, call.kwargs) == ((SYMBOL,), {'leverage': 10})
  venue['risk'].return_value = [risk(leverage=10)]
  assert await perp(s).leverage(ttl=MINUTE) == 10


async def test_a_refusal_never_raises_the_leverage(venue: dict[str, AsyncMock]):
  """At or below the maximum nothing is set, and the original refusal stands."""
  venue['risk'].return_value = [risk(leverage=5)]
  venue['place'].side_effect = [ABOVE_MAX]
  with pytest.raises(OrderRejected) as refused:
    await perp(shared()).place_order(ORDER)
  assert leverage_above_max(refused.value)
  assert venue['set'].await_count == 0
  assert venue['place'].await_count == 1


async def test_concurrent_refusals_share_one_fix(venue: dict[str, AsyncMock]):
  """Orders refused together lower the leverage once and are each resent."""
  venue['place'].side_effect = [ABOVE_MAX, ABOVE_MAX, placed(2), placed(3)]
  m = perp(shared())
  responses = await asyncio.gather(m.place_order(ORDER), m.place_order(ORDER))
  assert sorted(r.id for r in responses) == ['2', '3']
  assert venue['set'].await_count == 1
  assert venue['brackets'].await_count == 1
  assert venue['place'].await_count == 4


async def test_a_later_refusal_checks_again(
  venue: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
):
  """After `LEVERAGE_RECHECK`, a new `-2027` (a maximum lowered again) checks afresh."""
  s = shared()
  m = perp(s)
  venue['place'].side_effect = [ABOVE_MAX, placed(2)]
  await m.place_order(ORDER)
  loop = asyncio.get_running_loop()
  later = loop.time() + 60
  monkeypatch.setattr(loop, 'time', lambda: later)
  venue['risk'].return_value = [risk(leverage=10)]
  venue['brackets'].return_value = brackets(5)
  venue['set'].return_value = {'symbol': SYMBOL, 'leverage': 5}
  venue['place'].side_effect = [ABOVE_MAX, placed(3)]
  assert (await m.place_order(ORDER)).id == '3'
  call = venue['set'].await_args
  assert venue['set'].await_count == 2
  assert call is not None and call.kwargs == {'leverage': 5}


async def test_the_refusal_stands_when_the_leverage_cannot_be_lowered(
  venue: dict[str, AsyncMock],
):
  """If the leverage can't be lowered after a `-2027`, the original refusal is raised
  from the failure, and the order is not resent."""
  venue['set'].side_effect = NetworkError('down')
  venue['place'].side_effect = [ABOVE_MAX]
  with pytest.raises(OrderRejected) as refused:
    await perp(shared()).place_order(ORDER)
  assert isinstance(refused.value.__cause__, NetworkError)
  assert venue['place'].await_count == 1


async def test_symbols_share_one_position_risk_read(venue: dict[str, AsyncMock]):
  """Every symbol's position and leverage come from one all-symbol request per burst."""
  venue['risk'].return_value = [risk(), risk('BTCUSDT', leverage=5)]
  s = shared()
  leverage, btc, position = await asyncio.gather(
    perp(s).leverage(ttl=SECOND),
    perp(s, 'BTCUSDT').leverage(ttl=timedelta(0)),
    perp(s).perp_position(ttl=SECOND),
  )
  assert (leverage, btc, position.size) == (20, 5, 0)
  call = venue['risk'].await_args
  assert venue['risk'].await_count == 1
  assert call is not None and call.args == ()


async def test_fresh_position_reads_are_not_shared(venue: dict[str, AsyncMock]):
  """`ttl=None` reads each send a request; a later shared read reuses the newest."""
  venue['risk'].return_value = [risk(), risk('BTCUSDT')]
  s = shared()
  await asyncio.gather(perp(s).perp_position(), perp(s, 'BTCUSDT').perp_position())
  assert venue['risk'].await_count == 2
  await perp(s).leverage(ttl=MINUTE)
  assert venue['risk'].await_count == 2


async def test_a_symbol_missing_from_the_shared_read_is_read_alone(
  venue: dict[str, AsyncMock],
):
  """A symbol the all-symbol answer omits gets its own request."""
  venue['risk'].side_effect = [[risk('BTCUSDT')], [risk(leverage=7)]]
  assert await perp(shared()).leverage() == 7
  call = venue['risk'].await_args
  assert call is not None and call.args == (SYMBOL,)


async def test_symbols_share_one_account_read(monkeypatch: pytest.MonkeyPatch):
  """Concurrent collateral reads of the account send one request."""
  view = AsyncMock(return_value={'positions': []})
  monkeypatch.setattr(InfoWithJoinMargin, 'info_with_join_margin', view)
  s = shared()
  await asyncio.gather(s.futures_account(ttl=SECOND), s.futures_account(ttl=SECOND))
  assert view.await_count == 1
  await s.futures_account(ttl=None)
  assert view.await_count == 2
