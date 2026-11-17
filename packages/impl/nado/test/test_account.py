"""Healths, balances, leverage, positions, fills and funding history, and the report."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typing_extensions import Any

from tribulnation.nado.core import Shared
from tribulnation.nado.market.markets import NadoPerpMarket, NadoSpotMarket
from tribulnation.nado.report import Report

from .conftest import OWNER, SENDER, X18

T0 = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)


def btc(shared: Shared) -> NadoPerpMarket:
  """BTC-PERP over `shared`."""
  return NadoPerpMarket(shared=shared, symbol='BTC-PERP', product_id=2)


def health(value: str) -> Any:
  """One health entry."""
  return {'assets': 0, 'liabilities': 0, 'health': int(Decimal(value) * X18)}


def info(
  *,
  initial: str,
  maintenance: str,
  unweighted: str,
  usdt0: str,
  kbtc: str = '0',
  btc: str = '0',
  v_quote: str = '0',
) -> Any:
  """A `subaccount_info` with one perpetual and two spot balances."""
  state: dict[str, Any] = {
    'subaccount': SENDER,
    'exists': True,
    'healths': [health(initial), health(maintenance), health(unweighted)],
    'spot_balances': [
      {'product_id': 0, 'balance': {'amount': int(Decimal(usdt0) * X18)}},
      {'product_id': 1, 'balance': {'amount': int(Decimal(kbtc) * X18)}},
    ],
    'perp_balances': [
      {
        'product_id': 2,
        'balance': {
          'amount': int(Decimal(btc) * X18),
          'v_quote_balance': int(Decimal(v_quote) * X18),
          'last_cumulative_funding_x18': 0,
        },
      },
    ],
    'perp_products': [{'product_id': 2, 'oracle_price_x18': 60000 * X18}],
  }
  return state


def serve(fake: Any, state: Any, *, isolated: list[Any] | None = None):
  """Answer `subaccount_info` and `isolated_positions` with `state`."""

  async def subaccount_info(*, subaccount: str) -> Any:
    assert subaccount == SENDER
    return state

  async def isolated_positions(subaccount: str) -> Any:
    return {'isolated_positions': isolated or []}

  fake.gateway.subaccount_info = subaccount_info
  fake.gateway.isolated_positions = isolated_positions


async def test_cross_bucket_reads_the_three_healths(shared: Shared, fake: Any):
  """Equity is the unweighted health; margins its distance to the others; free is the
  initial health."""
  serve(
    fake, info(initial='4', maintenance='7', unweighted='10', usdt0='10', btc='0.001')
  )
  c = await btc(shared).perp_collateral()
  assert (c.equity, c.initial_margin, c.maintenance_margin, c.free_collateral) == (
    Decimal(10),
    Decimal(6),
    Decimal(3),
    Decimal(4),
  )
  assert c.leverage == Decimal(6) and c.margin_mode == 'cross'


async def test_free_usdt0_is_capped_at_the_initial_health(shared: Shared, fake: Any):
  """Orders hold nothing; USDT0 also margins positions, so its free part is at most
  the initial health. A borrowed balance is negative, with nothing free."""
  serve(
    fake, info(initial='4', maintenance='7', unweighted='10', usdt0='10', kbtc='-0.1')
  )
  b = await NadoSpotMarket(shared=shared, symbol='KBTC', product_id=1).balances()
  assert (b.quote.total, b.quote.free) == (Decimal(10), Decimal(4))
  assert (b.base.total, b.base.free) == (Decimal('-0.1'), Decimal(0))


async def test_leverage_is_the_initial_weight_margin(shared: Shared, fake: Any):
  """`0.98`/`1.02` initial weights leave 2% margin: 50x."""

  async def all_products() -> Any:
    reply: dict[str, Any] = {
      'spot_products': [],
      'perp_products': [
        {
          'product_id': 2,
          'risk': {
            'long_weight_initial_x18': 98 * X18 // 100,
            'short_weight_initial_x18': 102 * X18 // 100,
          },
        }
      ],
    }
    return reply

  fake.gateway.all_products = all_products
  assert await btc(shared).leverage() == 50


async def test_isolated_positions_are_not_supported(shared: Shared, fake: Any):
  """A market holding an isolated position refuses its account reads."""
  isolated: list[Any] = [
    {'base_balance': {'product_id': 2, 'balance': {'amount': X18}}}
  ]
  serve(
    fake,
    info(initial='4', maintenance='7', unweighted='10', usdt0='10'),
    isolated=isolated,
  )
  with pytest.raises(NotImplementedError):
    await btc(shared).perp_position()
  with pytest.raises(NotImplementedError):
    await btc(shared).perp_collateral()


def match(idx: int, base: str, quote: str, fee: str, *, taker: bool = True) -> Any:
  """A BTC-PERP match as `matches` sends it."""
  return {
    'digest': '0x' + f'{idx:064x}',
    'order': {},
    'base_filled': int(Decimal(base) * X18),
    'quote_filled': int(Decimal(quote) * X18),
    'fee': int(Decimal(fee) * X18),
    'submission_idx': idx,
    'is_taker': taker,
    'post_balance': {'base': {'perp': {'product_id': 2}}},
  }


async def test_fills_take_their_time_and_gross_price(shared: Shared, fake: Any):
  """Each match takes its transaction's time; the price is the quote before fees over
  the base (a recorded mainnet sell of 0.0017 at 65022); the walk stops before
  `start`."""
  pages: list[Any] = [
    {
      'matches': [match(9, '-0.0017', '110.49871191', '0.03868809')],
      'txs': [{'submission_idx': 9, 'timestamp': T0}],
    },
  ]

  async def matches(subaccounts: list[str], **kwargs: Any) -> Any:
    assert subaccounts == [SENDER] and kwargs['product_ids'] == [2]
    return pages.pop(0)

  fake.archive.matches = matches
  [t] = await btc(shared).trades_history(T0 - timedelta(days=1), T0)
  assert (t.price, t.qty, t.time, t.maker, t.order_id) == (
    Decimal(65022),
    Decimal('-0.0017'),
    T0,
    False,
    match(9, '0', '0', '0')['digest'],
  )
  assert t.fee is not None and (t.fee.amount, t.fee.asset) == (
    Decimal('0.03868809'),
    'USDT0',
  )


async def test_funding_payments_walk_back_to_start(shared: Shared, fake: Any):
  """Payments are already received-positive; the walk follows `next_idx`."""

  def payment(hours: int, amount: str) -> Any:
    return {
      'product_id': 2,
      'idx': hours,
      'timestamp': T0 - timedelta(hours=hours),
      'amount': int(Decimal(amount) * X18),
    }

  pages: list[Any] = [
    {
      'interest_payments': [],
      'funding_payments': [payment(0, '0.5'), payment(1, '-1')],
      'next_idx': 5,
    },
    {
      'interest_payments': [],
      'funding_payments': [payment(2, '2'), payment(30, '9')],
      'next_idx': 1,
    },
  ]
  seen: list[Any] = []

  async def interest_and_funding(sender: str, **kwargs: Any) -> Any:
    seen.append(kwargs['max_idx'])
    return pages.pop(0)

  fake.archive.interest_and_funding = interest_and_funding
  rows = await btc(shared).funding_payments(T0 - timedelta(hours=3), T0)
  assert [p.amount for p in rows] == [Decimal('0.5'), Decimal(-1), Decimal(2)]
  assert seen == [None, 5]


async def test_report_moves_unsettled_perp_cash_into_usdt0(fake: Any):
  """A position's value beyond `amount * (price - entry)` is USDT0 cash."""
  from .conftest import shared_of

  shared = shared_of(fake)
  state = info(
    initial='1', maintenance='1', unweighted='1', usdt0='10', btc='0.01', v_quote='-595'
  )

  async def subaccounts(*, address: str) -> Any:
    assert address == OWNER
    reply: dict[str, Any] = {
      'subaccounts': [
        {'subaccount': SENDER, 'subaccount_name': 'default', 'isolated': False}
      ]
    }
    return reply

  async def positions(sender: str, **kwargs: Any) -> Any:
    rows: list[Any] = [{'product_id': 2, 'average_entry_price': 60000 * X18}]
    return {'positions': rows}

  serve(fake, state)
  fake.archive.subaccounts = subaccounts
  fake.archive.positions = positions
  record = await Report(shared=shared).snapshot()
  [sub] = record.snapshot.subaccounts
  assert sub.subaccount == 'default'
  assert sub.balances == {'USDT0': Decimal(15)}
  assert (sub.positions['BTC-PERP'].size, sub.positions['BTC-PERP'].avg_price) == (
    Decimal('0.01'),
    Decimal(60000),
  )


async def test_report_counts_a_closed_positions_unsettled_quote(fake: Any):
  """A flat perpetual whose `v_quote_balance` is not yet settled is USDT0 cash."""
  from .conftest import shared_of

  shared = shared_of(fake)
  serve(
    fake,
    info(initial='1', maintenance='1', unweighted='1', usdt0='10', v_quote='-0.08'),
  )

  async def subaccounts(*, address: str) -> Any:
    rows: list[Any] = [
      {'subaccount': SENDER, 'subaccount_name': 'default', 'isolated': False}
    ]
    return {'subaccounts': rows}

  fake.archive.subaccounts = subaccounts
  [sub] = (await Report(shared=shared).snapshot()).snapshot.subaccounts
  assert sub.balances == {'USDT0': Decimal('9.92')} and sub.positions == {}
