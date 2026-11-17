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
    return {'positions': [window(2, '0.01', 60000)]}

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


def window(product_id: int, amount: str, entry: int) -> Any:
  """An open position window as `positions` sends it: absolute size and direction."""
  size = Decimal(amount)
  return {
    'product_id': product_id,
    'direction': size > 0,
    'amount': int(abs(size) * X18),
    'average_entry_price': entry * X18,
  }


def serve_windows(fake: Any, rows: list[Any]):
  """Answer `positions` with `rows`, of the product asked for when one is."""

  async def positions(sender: str, **kwargs: Any) -> Any:
    pid = kwargs.get('product_id')
    return {'positions': [r for r in rows if pid in (None, r['product_id'])]}

  fake.archive.positions = positions


def serve_subaccounts(fake: Any, *rows: Any):
  """Answer `subaccounts` with `rows` (the cross `default` when none)."""

  async def subaccounts(*, address: str) -> Any:
    found: list[Any] = list(rows) or [
      {'subaccount': SENDER, 'subaccount_name': 'default', 'isolated': False}
    ]
    return {'subaccounts': found}

  fake.archive.subaccounts = subaccounts


@pytest.mark.parametrize(
  'rows',
  [
    [],
    [window(2, '-0.01', 61000)],
    [window(2, '0.004', 61000)],
  ],
  ids=['not-indexed', 'flipped', 'resized'],
)
async def test_an_archive_behind_the_gateway_is_an_error(
  shared: Shared, fake: Any, rows: list[Any]
):
  """The archive indexes after the gateway: a window missing, of the other side or
  another size is not the position's, so its entry price is refused in both the
  market read and the report, rather than read as 0 or as the old window's."""
  from tribulnation.sdk.core import ApiError

  serve(
    fake, info(initial='1', maintenance='1', unweighted='1', usdt0='10', btc='0.01')
  )
  serve_windows(fake, rows)
  serve_subaccounts(fake)
  with pytest.raises(ApiError):
    await btc(shared).perp_position()
  with pytest.raises(ApiError):
    await Report(shared=shared).snapshot()


async def test_the_matching_window_prices_the_position(shared: Shared, fake: Any):
  """The open window of the same side and size gives the entry price."""
  serve(
    fake, info(initial='1', maintenance='1', unweighted='1', usdt0='10', btc='-0.01')
  )
  serve_windows(fake, [window(1, '0.5', 1), window(2, '-0.01', 61000)])
  p = await btc(shared).perp_position()
  assert (p.size, p.entry_price) == (Decimal('-0.01'), Decimal(61000))


async def test_flat_isolated_rows_count_the_same_everywhere(shared: Shared, fake: Any):
  """An isolated subaccount whose position is flat holds nothing: neither the market
  reads nor the report refuse the wallet for it."""
  flat: list[Any] = [{'base_balance': {'product_id': 2, 'balance': {'amount': 0}}}]
  serve(
    fake, info(initial='1', maintenance='1', unweighted='1', usdt0='10'), isolated=flat
  )
  serve_subaccounts(
    fake,
    {'subaccount': SENDER, 'subaccount_name': 'default', 'isolated': False},
    {'subaccount': SENDER[:-2] + '01', 'subaccount_name': 'iso', 'isolated': True},
  )
  assert (await btc(shared).perp_position()).size == 0
  [sub] = (await Report(shared=shared).snapshot()).snapshot.subaccounts
  assert sub.balances == {'USDT0': Decimal(10)}


async def test_fills_walk_full_pages_and_drop_the_boundary_repeats(
  shared: Shared, fake: Any, monkeypatch: pytest.MonkeyPatch
):
  """A full page asks again from its oldest `submission_idx` (inclusive): the repeated
  rows are dropped, and the walk stops at the first row before `start`."""
  from tribulnation.nado.market import history

  monkeypatch.setattr(history, 'MATCH_PAGE', 2)

  def tx(idx: int) -> Any:
    return {'submission_idx': idx, 'timestamp': T0 - timedelta(hours=10 - idx)}

  pages: dict[int | None, Any] = {
    None: {
      'matches': [match(9, '1', '-1', '0'), match(8, '1', '-1', '0')],
      'txs': [tx(9), tx(8)],
    },
    8: {
      'matches': [match(8, '1', '-1', '0'), match(7, '1', '-1', '0')],
      'txs': [tx(8), tx(7)],
    },
    7: {
      'matches': [match(7, '1', '-1', '0'), match(1, '1', '-1', '0')],
      'txs': [tx(7), tx(1)],
    },
  }
  asked: list[int | None] = []

  async def matches(subaccounts: list[str], **kwargs: Any) -> Any:
    asked.append(kwargs['idx'])
    return pages[kwargs['idx']]

  fake.archive.matches = matches
  rows = await btc(shared).trades_history(T0 - timedelta(hours=5), T0)
  assert [t.id for t in rows] == [
    f'{i}:{match(i, "0", "0", "0")["digest"]}' for i in (9, 8, 7)
  ]
  assert asked == [None, 8, 7]


async def test_exchange_history_names_each_market(shared: Shared, fake: Any):
  """Exchange-wide fills and funding carry their market's symbol; a product Nado no
  longer lists is left out."""
  from tribulnation.nado.market.exchanges import NadoPerpExchange

  gone = match(5, '1', '-1', '0')
  gone['post_balance'] = {'base': {'perp': {'product_id': 99}}}

  async def matches(subaccounts: list[str], **kwargs: Any) -> Any:
    assert sorted(kwargs['product_ids']) == [2, 4]
    reply: dict[str, Any] = {
      'matches': [match(6, '1', '-1', '0'), gone],
      'txs': [
        {'submission_idx': 6, 'timestamp': T0},
        {'submission_idx': 5, 'timestamp': T0},
      ],
    }
    return reply

  async def interest_and_funding(sender: str, **kwargs: Any) -> Any:
    rows: list[Any] = [
      {'product_id': 4, 'idx': 1, 'timestamp': T0, 'amount': X18},
      {'product_id': 99, 'idx': 0, 'timestamp': T0, 'amount': X18},
    ]
    return {'interest_payments': [], 'funding_payments': rows, 'next_idx': None}

  fake.archive.matches = matches
  fake.archive.interest_and_funding = interest_and_funding
  exchange = NadoPerpExchange(shared=shared)
  trades = await exchange.trades_history(None, T0 - timedelta(hours=1), T0)
  assert [t.market_id for t in trades] == ['BTC-PERP']
  payments = await exchange.funding_payments(None, T0 - timedelta(hours=1), T0)
  assert [(p.market_id, p.amount) for p in payments] == [('ETH-PERP', Decimal(1))]


async def test_fees_refetch_asks_afresh(shared: Shared, fake: Any):
  """`fees(refetch=True)` reads the rates again instead of the minute-old answer."""
  calls: list[int] = []

  async def fee_rates(sender: str) -> Any:
    calls.append(1)
    rate = len(calls) * 10**14
    return {'maker_fee_rates_x18': [0, 0, rate], 'taker_fee_rates_x18': [0, 0, rate]}

  fake.gateway.fee_rates = fee_rates
  assert (await btc(shared).fees()).maker_buy == Decimal('0.0001')
  assert (await btc(shared).fees(refetch=True)).maker_buy == Decimal('0.0002')
