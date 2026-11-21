"""Borrow interest as a Bitget UTA margin pair's carry, and the margin exchange listed.

Interest rows are the UTA ledger's `INTEREST_SETTLEMENT_OUT` entries
(`/api/v3/account/financial-records`), signed negative as Bitget signs every `_OUT`
row (live: `ORDER_DEALT_FROZEN_OUT` -248.05 LIT, 2026-11-21).
"""

from typing_extensions import TYPE_CHECKING, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from tribulnation.bitget.market import BitgetMarket, MarginMarket
from tribulnation.bitget.market.margin_exchange import MarginExchange
from tribulnation.sdk.market import InterestPayment, is_margin

if TYPE_CHECKING:
  from conftest import FakeMargin

PAIR = 'LITUSDT'
START = datetime(2026, 11, 20, tzinfo=timezone.utc)
END = datetime(2026, 11, 21, tzinfo=timezone.utc)
HOUR_MS = 3_600_000
T0_MS = int(START.timestamp() * 1000)


def row(id: str, coin: str, amount: str, hour: int, category: str = 'MARGIN'):
  """One ledger interest row."""
  return {
    'category': category,
    'id': id,
    'symbol': '',
    'coin': coin,
    'type': 'INTEREST_SETTLEMENT_OUT',
    'amount': amount,
    'fee': '0',
    'balance': '0',
    'ts': str(T0_MS + hour * HOUR_MS),
  }


LEDGER = [
  row('1', 'LIT', '-0.0228', 1),
  row('2', 'USDT', '-0.0100', 1),
  row('3', 'LIT', '-0.0229', 2),
  # The same entry reported under another category is one charge, not two.
  row('3', 'LIT', '-0.0229', 2, category='SPOT'),
]


@pytest.fixture(autouse=True)
def ledger(margin_fake: 'FakeMargin') -> 'FakeMargin':
  """Serve `account/financial-records` from `LEDGER`, filtered like the venue; before
  any market is built on the fake, since its transport binds `handle` then."""
  handle = margin_fake.handle

  def with_ledger(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix('/api/v3/')
    if path != 'account/financial-records':
      return handle(request)
    params = dict(request.url.params)
    margin_fake.requests.append((request.method, path, params))
    rows = [
      r
      for r in LEDGER
      if r['category'] == params['category']
      and r['type'] == params.get('type', r['type'])
      and r['coin'] == params.get('coin', r['coin'])
      and int(params['startTime']) <= int(r['ts']) <= int(params['endTime'])
    ]
    return margin_fake.answer({'list': rows or None, 'cursor': None})

  object.__setattr__(margin_fake, 'handle', with_ledger)
  return margin_fake


def ledger_requests(fake: 'FakeMargin') -> list[dict[str, Any]]:
  """The query of every ledger request so far."""
  return [p for _, e, p in fake.requests if e == 'account/financial-records']


def venue_of(market: MarginMarket) -> BitgetMarket:
  """The venue sharing `market`'s account and caches."""
  return BitgetMarket(account=market.account, cache=market.cache)


async def test_a_pair_reads_the_interest_on_its_base_coin(
  ledger: 'FakeMargin', margin: MarginMarket
):
  """LIT interest only, each charge once, negative and in LIT."""
  payments = await margin.interest_payments(START, END)
  assert sorted(payments, key=lambda p: p.time) == [
    InterestPayment(
      time=START + timedelta(hours=1), asset='LIT', amount=Decimal('-0.0228')
    ),
    InterestPayment(
      time=START + timedelta(hours=2), asset='LIT', amount=Decimal('-0.0229')
    ),
  ]
  queries = ledger_requests(ledger)
  assert {q['category'] for q in queries} == {
    'MARGIN',
    'SPOT',
    'USDT-FUTURES',
    'USDC-FUTURES',
    'COIN-FUTURES',
  }
  assert all(
    q['coin'] == 'LIT' and q['type'] == 'INTEREST_SETTLEMENT_OUT' for q in queries
  )


async def test_the_exchange_reads_every_coin_the_pool_owes(
  ledger: 'FakeMargin', margin: MarginMarket
):
  """`interest_payments(None, ...)` adds the pool's USDT interest."""
  exchange = await venue_of(margin).exchange('margin')
  assert isinstance(exchange, MarginExchange)
  payments = await exchange.interest_payments(None, START, END)
  assert sorted((p.asset, p.amount) for p in payments) == [
    ('LIT', Decimal('-0.0229')),
    ('LIT', Decimal('-0.0228')),
    ('USDT', Decimal('-0.0100')),
  ]
  assert all('coin' not in q for q in ledger_requests(ledger))
  by_pair = await exchange.interest_payments(PAIR, START, END)
  assert {p.asset for p in by_pair} == {'LIT'}


async def test_a_long_window_is_read_in_month_windows(
  ledger: 'FakeMargin', margin: MarginMarket
):
  """Each ledger request spans at most 30 days."""
  await margin.interest_payments(END - timedelta(days=75), END)
  queries = [q for q in ledger_requests(ledger) if q['category'] == 'MARGIN']
  assert len(queries) == 3
  assert all(
    int(q['endTime']) - int(q['startTime']) <= 30 * 24 * HOUR_MS for q in queries
  )


async def test_a_classic_account_has_no_interest_history(
  ledger: 'FakeMargin', classic_margin: MarginMarket
):
  """Classic margin wallets are not read: refused before any ledger request."""
  with pytest.raises(NotImplementedError, match='Unified Trading Accounts'):
    await classic_margin.interest_payments(START, END)
  exchange = await venue_of(classic_margin).exchange('margin')
  with pytest.raises(NotImplementedError, match='Unified Trading Accounts'):
    await exchange.interest_payments(None, START, END)  # type: ignore[union-attr]
  assert ledger_requests(ledger) == []


async def test_the_margin_exchange_is_listed_as_its_own_kind(margin: MarginMarket):
  """Consumers enumerate `margin` from `exchanges()`, typed `'margin'`."""
  venue = venue_of(margin)
  listed = {d['id']: d['type'] for d in await venue.exchanges()}
  assert listed == {'spot': 'spot', 'margin': 'margin', 'usdt': 'perp', 'usdc': 'perp'}
  exchange = await venue.exchange('margin')
  assert exchange.kind == 'margin' and is_margin(exchange)
  assert await exchange.markets() == [PAIR]
  assert await venue.margin_market(f'margin:{PAIR}') is not None
