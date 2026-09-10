"""Kucoin history discovery, paging, sign and contract regressions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing_extensions import AsyncIterator, cast

import pytest
from typed_kucoin import KuCoin
from typed_core.exceptions import AuthError as TypedAuthError
from tribulnation.sdk import AuthError
from typed_kucoin.schemas import HfFill
from tribulnation.kucoin import Report, Wallet
from tribulnation.kucoin.earn import Product, parse_product
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  HistoryRecord,
  SpotTrade,
  Transfer,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def fill(id: int, symbol: str) -> HfFill:
  """Synthetic fill including only fields read by this implementation."""
  return cast(
    HfFill,
    {
      'id': id,
      'tradeId': id,
      'symbol': symbol,
      'createdAt': NOW,
      'orderId': 'order',
      'side': 'sell',
      'size': Decimal('2'),
      'price': Decimal('10'),
      'fee': Decimal('0.1'),
      'feeCurrency': 'USDT',
    },
  )


async def test_spot_discovers_every_symbol_and_follows_last_id():
  """A market absent from holdings is still scanned; overlapping rows are emitted once."""
  request = AsyncMock(
    side_effect=[
      {'items': [fill(1, 'BTC-USDT')], 'lastId': 10},
      {'items': [fill(1, 'BTC-USDT'), fill(2, 'BTC-USDT')], 'lastId': 0},
      {'items': [fill(1, 'OLD-USDT')], 'lastId': 0},
    ]
  )
  client = cast(
    KuCoin,
    SimpleNamespace(
      spot=SimpleNamespace(
        all_symbols=AsyncMock(
          return_value=[{'symbol': 'BTC-USDT'}, {'symbol': 'OLD-USDT'}]
        ),
        orders_hf=SimpleNamespace(get_trade_history=request),
      )
    ),
  )
  rows = [
    row async for row in Report(client=client).spot_trades(NOW - timedelta(days=1), NOW)
  ]
  assert len(rows) == 3
  assert len({row.provenance['id'] for row in rows}) == 3
  assert request.await_args_list[1].kwargs['last_id'] == 10
  assert [call.kwargs['symbol'] for call in request.await_args_list] == [
    'BTC-USDT',
    'BTC-USDT',
    'OLD-USDT',
  ]
  observation = rows[0].observations[0]
  assert isinstance(observation, SpotTrade) and observation.size == -2


async def test_capital_pages_keep_direction_fees_and_internal_movements():
  """Page deposits and withdrawals without dropping internal movements or fees."""

  def movement(inner: bool) -> dict[str, object]:
    """Build a synthetic capital row with only consumed response fields."""
    return {
      'id': 'internal' if inner else 'external',
      'createdAt': NOW,
      'currency': 'USDT',
      'amount': Decimal('10'),
      'fee': Decimal('1'),
      'isInner': inner,
      'chain': 'network',
      'walletTxId': 'transaction',
      'address': 'destination',
    }

  def request() -> AsyncMock:
    """Return separate page responses for each capital endpoint."""
    return AsyncMock(
      side_effect=[
        {'items': [movement(False)], 'totalPage': 2},
        {'items': [movement(True)], 'totalPage': 2},
      ]
    )

  deposits, withdrawals = request(), request()
  client = cast(
    KuCoin,
    SimpleNamespace(
      account=SimpleNamespace(
        deposit=SimpleNamespace(history=deposits),
        withdrawals=SimpleNamespace(history=withdrawals),
      )
    ),
  )
  records = [row async for row in Report(client=client).capital(NOW, NOW)]
  assert len(records) == 4
  assert len({row.provenance['id'] for row in records}) == 4
  observations = [row.observations[0] for row in records]
  assert isinstance(observations[0], CryptoDeposit)
  assert isinstance(observations[1], Transfer)
  assert isinstance(observations[2], CryptoWithdrawal)
  assert isinstance(observations[3], Transfer)
  for row, change in zip(observations, [10, 10, -10, -10]):
    assert isinstance(row, (CryptoDeposit, CryptoWithdrawal, Transfer))
    assert row.balance_change == change
    assert row.fee is not None and row.fee.balance_change == -1
  assert deposits.await_args_list[1].kwargs['current_page'] == 2
  assert withdrawals.await_args_list[1].kwargs['current_page'] == 2


async def test_wide_fill_interval_is_not_repeated_as_retention_windows():
  """One requested interval per symbol preserves bounds and filters fallback rows."""
  start, end = NOW - timedelta(days=60), NOW - timedelta(days=30)
  outside = fill(1, 'BTC-USDT')
  inside = fill(2, 'BTC-USDT')
  inside['createdAt'] = start
  request = AsyncMock(return_value={'items': [outside, inside], 'lastId': 0})
  client = cast(
    KuCoin,
    SimpleNamespace(
      spot=SimpleNamespace(
        all_symbols=AsyncMock(return_value=[{'symbol': 'BTC-USDT'}]),
        orders_hf=SimpleNamespace(get_trade_history=request),
      )
    ),
  )
  rows = [row async for row in Report(client=client).spot_trades(start, end)]
  assert len(rows) == 1
  assert rows[0].observations[0].time == start
  request.assert_awaited_once_with(
    symbol='BTC-USDT',
    start_at=start,
    end_at=end,
    last_id=None,
    limit=100,
  )


async def test_history_defaults_preserve_each_sources_window(
  monkeypatch: pytest.MonkeyPatch,
):
  """Optional bounds resolve per source, not a venue-wide mandatory-start check."""
  captured: list[tuple[datetime, datetime]] = []

  async def source(
    self: Report, start: datetime, end: datetime
  ) -> AsyncIterator[HistoryRecord]:
    """Record orchestration without making requests."""
    captured.append((start, end))
    return
    yield  # pragma: no cover

  for name in ('spot_trades', 'capital'):
    monkeypatch.setattr(Report, name, source)
  report = Report(client=cast(KuCoin, None))
  assert [row async for row in report.history(end=NOW)] == []
  assert [upper - lower for lower, upper in captured] == [timedelta(days=30)] + [
    timedelta(days=7)
  ]
  captured.clear()
  start = NOW - timedelta(days=90)
  assert [row async for row in report.history(start, NOW)] == []
  assert captured == [(start, NOW)] * 2


def test_simple_earn_rate_and_duration_units():
  """APR fractions are not divided by 100 and fixed durations remain days."""
  product = cast(
    Product,
    {
      'type': 'TIME',
      'id': 'product',
      'currency': 'ETH',
      'returnRate': '0.04',
      'incomeCurrency': 'ETH',
      'userLowerLimit': '1',
      'userUpperLimit': '10',
      'duration': 14,
      'newUserOnly': 1,
    },
  )
  instrument = parse_product(product, staking=True)
  assert instrument.apr == Decimal('0.04') and instrument.duration == timedelta(days=14)
  assert instrument.tags == ['fixed', 'staking', 'new-users']


async def test_wallet_filters_enabled_chains():
  """Deposit and withdrawal enablement are independent; filters use chainId."""
  client = cast(
    KuCoin,
    SimpleNamespace(
      spot=SimpleNamespace(
        all_currencies=AsyncMock(
          return_value=[
            {
              'currency': 'TOKEN',
              'chains': [
                {
                  'chainId': 'a',
                  'isDepositEnabled': True,
                  'isWithdrawEnabled': False,
                  'contractAddress': '',
                  'confirms': 5,
                  'withdrawalMinFee': '1',
                },
                {
                  'chainId': 'b',
                  'isDepositEnabled': False,
                  'isWithdrawEnabled': True,
                  'contractAddress': 'contract',
                  'confirms': 5,
                  'withdrawalMinFee': '2',
                },
              ],
            }
          ]
        )
      )
    ),
  )
  wallet = Wallet(client=client)
  assert [row.network for row in await wallet.deposit_methods()] == ['a']
  withdrawals = await wallet.withdrawal_methods(networks=['b'])
  assert len(withdrawals) == 1 and withdrawals[0].fee is not None
  assert withdrawals[0].fee.amount == 2


async def test_snapshot_is_spot_side_and_filters_assets():
  """A client without futures surfaces serves main/trade and paginated Earn."""
  spot = AsyncMock(
    return_value=[
      {'type': 'main', 'currency': 'USDT', 'balance': Decimal(10)},
      {'type': 'trade', 'currency': 'USDT', 'balance': Decimal(2)},
      {'type': 'trade', 'currency': 'BTC', 'balance': Decimal(1)},
      {'type': 'margin', 'currency': 'USDT', 'balance': Decimal(99)},
      {'type': 'isolated', 'currency': 'USDT', 'balance': Decimal(99)},
    ]
  )
  earn = AsyncMock(
    side_effect=[
      {
        'items': [
          {'currency': 'USDT', 'holdAmount': Decimal(3), 'redeemingAmount': Decimal(1)}
        ],
        'totalPage': 2,
      },
      {
        'items': [
          {'currency': 'USDT', 'holdAmount': Decimal(2), 'redeemingAmount': Decimal(0)}
        ],
        'totalPage': 2,
      },
    ]
  )
  client = cast(
    KuCoin,
    SimpleNamespace(
      account=SimpleNamespace(spot_accounts=spot),
      earn=SimpleNamespace(account_holding=earn),
    ),
  )
  result = await Report(client=client).snapshot(assets=['USDT'])
  states = {state.subaccount: state for state in result.snapshot.subaccounts}
  assert set(states) == {'main', 'trade', 'earn'}
  assert states['main'].balances == {'USDT': 10}
  assert states['trade'].balances == {'USDT': 2}
  assert states['earn'].balances == {'USDT': 6}
  assert all(not state.positions for state in states.values())
  assert earn.await_args_list[1].kwargs['current_page'] == 2


async def test_rejected_spot_snapshot_is_not_zero():
  """The explicit scope must not hide authentication errors on supported reads."""
  client = cast(
    KuCoin,
    SimpleNamespace(
      account=SimpleNamespace(
        spot_accounts=AsyncMock(side_effect=TypedAuthError('fake rejection')),
      )
    ),
  )
  with pytest.raises(AuthError):
    await Report(client=client).snapshot()


async def test_history_runs_without_any_futures_surface():
  """Real history orchestration succeeds with only spot-side endpoints available."""
  client = cast(
    KuCoin,
    SimpleNamespace(
      account=SimpleNamespace(
        deposit=SimpleNamespace(
          history=AsyncMock(return_value={'items': [], 'totalPage': 0})
        ),
        withdrawals=SimpleNamespace(
          history=AsyncMock(return_value={'items': [], 'totalPage': 0})
        ),
      ),
      spot=SimpleNamespace(all_symbols=AsyncMock(return_value=[])),
    ),
  )
  assert [row async for row in Report(client=client).history(end=NOW)] == []
