"""`remaining_position_limit` over many symbols: shared account reads and a paced allowance (ADR 0069)."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing_extensions import Any

import pytest
from typed_aster.futures.market.remaining_openable_notional_value import (
  RemainingOpenableNotionalValue,
)
from typed_aster.futures.position.risk import Risk
from tribulnation.aster import AsterMarket
from tribulnation.aster.market.markets import NativeMarket, PerpMarket
from tribulnation.sdk.core import ApiError, PositionLimitExceeded
from tribulnation.sdk.market import POSITION_LIMIT_TTL, RemainingPositionLimit

SYMBOLS = [f'S{i:02d}USDT' for i in range(22)]
"""As many symbols as production's strategies poll on one account."""


def row(symbol: str) -> dict[str, Any]:
  """A flat one-way `positionRisk` row at leverage 5 under a 2000 bracket cap."""
  return {
    'symbol': symbol,
    'leverage': 5,
    'marginType': 'cross',
    'positionSide': 'BOTH',
    'positionAmt': Decimal(0),
    'entryPrice': Decimal(0),
    'notional': Decimal(0),
    'maxNotionalValue': Decimal(2000),
  }


class Venue:
  """Counts the requests `remaining_position_limit` sends to the mocked venue."""

  def __init__(self, monkeypatch: pytest.MonkeyPatch, *, allowance: str = '500'):
    self.risk_calls = 0
    self.allowance_calls: list[str] = []
    self.fail_risk = 0
    """How many coming `positionRisk` requests fail."""
    self.release = asyncio.Event()
    self.release.set()
    self.allowance = Decimal(allowance)

    async def risk(_: Any, symbol: str | None = None, **kwargs: Any):
      """The all-symbol answer; a request for one symbol would be a per-symbol read."""
      assert symbol is None, 'per-symbol positionRisk read'
      self.risk_calls += 1
      await self.release.wait()
      if self.fail_risk:
        self.fail_risk -= 1
        raise ApiError('positionRisk failed')
      return [row(s) for s in SYMBOLS]

    async def remaining(_: Any, symbol: str, *, leverage: int, **kwargs: Any):
      """The symbol's open-interest allowance."""
      self.allowance_calls.append(symbol)
      return {'remainingOpenableNotionalValue': self.allowance}

    monkeypatch.setattr(Risk, 'risk', risk)
    monkeypatch.setattr(
      RemainingOpenableNotionalValue, 'remaining_openable_notional_value', remaining
    )

  @property
  def requests(self) -> int:
    """Every request sent so far."""
    return self.risk_calls + len(self.allowance_calls)


def markets() -> list[PerpMarket]:
  """One perpetual per symbol, all of one account's client."""
  shared = AsterMarket.new(public=True).shared
  return [PerpMarket(shared=shared, symbol=s) for s in SYMBOLS]


def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
  """The running loop's time, set by the test."""
  now = [1000.0]
  monkeypatch.setattr(asyncio.get_running_loop(), 'time', lambda: now[0])
  return now


async def poll(perps: list[PerpMarket], **kwargs: Any) -> list[RemainingPositionLimit]:
  """Every symbol's limit at once, as a strategy's round reads them."""
  return await asyncio.gather(*(m.remaining_position_limit(**kwargs) for m in perps))


async def test_symbols_within_the_ttl_share_one_position_read(
  monkeypatch: pytest.MonkeyPatch,
):
  """Concurrent and back-to-back reads of every symbol send one `positionRisk` request."""
  venue, now, perps = Venue(monkeypatch), clock(monkeypatch), markets()
  await poll(perps)
  for m in perps:
    now[0] += 1
    await m.remaining_position_limit()
  assert venue.risk_calls == 1


async def test_the_ttl_elapsed_reads_again(monkeypatch: pytest.MonkeyPatch):
  """An answer older than the caller's `ttl` (the default included) is read again."""
  venue, now, perps = Venue(monkeypatch), clock(monkeypatch), markets()
  await poll(perps)
  now[0] += POSITION_LIMIT_TTL.total_seconds()
  await poll(perps)
  assert venue.risk_calls == 2
  await poll(perps, ttl=timedelta(seconds=5))
  assert venue.risk_calls == 2
  now[0] += 5
  await poll(perps, ttl=timedelta(seconds=5))
  assert venue.risk_calls == 3
  await poll(perps[:1], ttl=None)
  assert venue.risk_calls == 4


async def test_concurrent_callers_join_the_request_in_flight(
  monkeypatch: pytest.MonkeyPatch,
):
  """Callers arriving while the request is out wait for it rather than sending another."""
  venue, perps = Venue(monkeypatch), markets()
  venue.release.clear()
  waiting = asyncio.ensure_future(poll(perps))
  await asyncio.sleep(0)
  await asyncio.sleep(0)
  venue.release.set()
  assert len(await waiting) == len(SYMBOLS)
  assert venue.risk_calls == 1


async def test_failures_are_not_kept(monkeypatch: pytest.MonkeyPatch):
  """Every caller of a failed request sees its error; the next read asks again."""
  venue, perps = Venue(monkeypatch), markets()
  venue.fail_risk = 1
  results = await asyncio.gather(
    *(m.remaining_position_limit() for m in perps), return_exceptions=True
  )
  assert all(isinstance(r, ApiError) for r in results)
  assert venue.risk_calls == 1
  assert len(await poll(perps)) == len(SYMBOLS)
  assert venue.risk_calls == 2


async def test_allowances_are_paced_and_reused(monkeypatch: pytest.MonkeyPatch):
  """One allowance request per 30 s for all symbols; one not read yet has no open-interest bound."""
  venue, now, perps = Venue(monkeypatch), clock(monkeypatch), markets()
  first = await poll(perps)
  assert venue.allowance_calls == [SYMBOLS[0]]
  assert first[0] == RemainingPositionLimit(long=Decimal(500), short=Decimal(500))
  assert first[1] == RemainingPositionLimit(long=Decimal(2000), short=Decimal(2000))
  now[0] += 30
  second = await poll(perps)
  assert venue.allowance_calls == SYMBOLS[:2]
  assert second[1] == first[0]


async def test_a_position_limit_refusal_reads_the_limits_again(
  monkeypatch: pytest.MonkeyPatch,
):
  """After `-5018` the positions are read again, and the allowance at its next turn, its last answer standing meanwhile."""
  venue, now, perps = Venue(monkeypatch), clock(monkeypatch), markets()
  await poll(perps[:1])
  shared = perps[0].shared
  shared.stale_limits(SYMBOLS[0])
  venue.allowance = Decimal(100)
  now[0] += 1
  limit = await perps[0].remaining_position_limit()
  assert venue.risk_calls == 2
  assert limit == RemainingPositionLimit(long=Decimal(500), short=Decimal(500))
  now[0] += 30
  limit = await perps[0].remaining_position_limit()
  assert limit == RemainingPositionLimit(long=Decimal(100), short=Decimal(100))
  assert venue.allowance_calls == [SYMBOLS[0]] * 2


async def test_place_order_refused_at_the_limit_marks_the_limits_stale(
  monkeypatch: pytest.MonkeyPatch,
):
  """`place_order` raising `PositionLimitExceeded` calls `Shared.stale_limits`."""
  perp = markets()[0]
  stale: list[str] = []

  def stale_limits(_: Any, symbol: str):
    """Record the symbol instead of marking its reads stale."""
    stale.append(symbol)

  monkeypatch.setattr(type(perp.shared), 'stale_limits', stale_limits)

  async def refuse(*args: Any, **kwargs: Any):
    raise PositionLimitExceeded('-5018')

  monkeypatch.setattr(NativeMarket, 'place_order', refuse)
  with pytest.raises(PositionLimitExceeded):
    await perp.place_order(object())  # type: ignore[arg-type]
  assert stale == [SYMBOLS[0]]


async def test_request_budget_of_a_minute_of_polling(monkeypatch: pytest.MonkeyPatch):
  """22 symbols polled every 5 s for a minute at the default `ttl` send at most 4 requests,
  and over 15 minutes every symbol gets its allowance at no more than 4 requests a minute."""
  venue, now, perps = Venue(monkeypatch), clock(monkeypatch), markets()
  start = now[0]
  for step in range(12):
    now[0] = start + 5 * step
    await poll(perps)
  assert venue.requests <= 4
  per_minute: list[int] = []
  for minute in range(1, 15):
    before = venue.requests
    for step in range(12):
      now[0] = start + 60 * minute + 5 * step
      await poll(perps)
    per_minute.append(venue.requests - before)
  assert max(per_minute) <= 4
  assert set(venue.allowance_calls) == set(SYMBOLS)
