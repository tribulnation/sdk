"""Report snapshots and history mapped from the sub-account's rows."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typing_extensions import Any

import pytest
from typed_core import PaginatedResponse

from tribulnation.extended import Report
from tribulnation.extended.report import fill, operation, position
from tribulnation.sdk.reporting import (
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  FeeLeg,
  Funding,
  FuturePositionSummary,
  FutureTrade,
  InternalTransfer,
  SpotTrade,
)

T = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
NAMES = {1: 'USD'}
MARKETS: dict[str, Any] = {
  'ETH-USD': {
    'name': 'ETH-USD',
    'type': 'PERPETUAL',
    'assetName': 'ETH',
    'collateralAssetName': 'USD',
  },
  'BTCSPOT-USD': {
    'name': 'BTCSPOT-USD',
    'type': 'SPOT',
    'assetName': 'BTCSPOT',
    'collateralAssetName': 'USD',
  },
}


def op(kind: str, amount: str, status: str = 'COMPLETED', **extra: Any) -> Any:
  """An asset operation of the key's sub-account 3880."""
  return {
    'id': '2112523545589317632',
    'type': kind,
    'status': status,
    'amount': Decimal(amount),
    'fee': Decimal(0),
    'asset': 1,
    'time': T,
    'accountId': 3880,
    **extra,
  }


def test_transfers_take_their_direction_from_the_sign():
  """`accountId` is always the key's sub-account; the sign says which way funds went,
  and a charged fee is its own leg."""
  (incoming,) = operation(op('TRANSFER', '10', counterpartyAccountId=3881), NAMES)
  outgoing, fee = operation(
    op('TRANSFER', '-10', counterpartyAccountId=3881, fee=Decimal('0.1')), NAMES
  )
  assert isinstance(incoming, InternalTransfer) and isinstance(
    outgoing, InternalTransfer
  )
  assert (incoming.src_account, incoming.dst_account, incoming.amount) == (
    '3881',
    '3880',
    Decimal('10'),
  )
  assert (outgoing.src_account, outgoing.dst_account, outgoing.amount) == (
    '3880',
    '3881',
    Decimal('10'),
  )
  assert isinstance(fee, FeeLeg) and fee.amount == Decimal('0.1')
  assert incoming.subaccount == '3880' and incoming.asset == 'USD'


def test_deposits_claims_and_withdrawals():
  """Completed deposits and claims count; a withdrawal counts once created, unless
  rejected; pending transfers and deposits do not."""
  (deposit,) = operation(
    op('DEPOSIT', '50', chain='ETH', transactionHash='0xab'), NAMES
  )
  (claim,) = operation(op('CLAIM', '1000'), NAMES)
  (withdrawal,) = operation(op('SLOW_WITHDRAWAL', '-5', status='IN_PROGRESS'), NAMES)
  assert isinstance(deposit, CryptoDeposit) and deposit.tx_id == '0xab'
  assert isinstance(claim, Bonus) and claim.amount == Decimal('1000')
  assert isinstance(withdrawal, CryptoWithdrawal) and withdrawal.amount == Decimal('-5')
  assert operation(op('WITHDRAWAL', '-5', status='REJECTED'), NAMES) == []
  assert operation(op('DEPOSIT', '5', status='IN_PROGRESS'), NAMES) == []
  assert operation(op('TRANSFER', '5', status='CREATED'), NAMES) == []


def trade(market: str, side: str = 'SELL', **extra: Any) -> Any:
  """A fill of the sub-account."""
  return {
    'id': 7,
    'accountId': 3880,
    'market': market,
    'orderId': 9,
    'side': side,
    'price': Decimal('2400'),
    'qty': Decimal('0.5'),
    'value': Decimal('1200'),
    'fee': Decimal('0.3'),
    'tradeType': 'TRADE',
    'createdTime': T,
    'isTaker': True,
    **extra,
  }


def test_fills_by_market_type():
  """Perpetual fills are `FutureTrade`s and spot fills `SpotTrade`s, sells negative,
  the fee in the collateral; a builder fee is not guessed at."""
  perp = fill(trade('ETH-USD'), MARKETS)
  spot = fill(trade('BTCSPOT-USD', 'BUY'), MARKETS)
  assert isinstance(perp, FutureTrade) and isinstance(spot, SpotTrade)
  assert (perp.size, perp.instrument, perp.settle) == (
    Decimal('-0.5'),
    'ETH-USD',
    'USD',
  )
  assert perp.fee is not None and (perp.fee.amount, perp.fee.asset) == (
    Decimal('0.3'),
    'USD',
  )
  assert (spot.size, spot.pair, spot.base) == (Decimal('0.5'), 'BTCSPOT-USD', 'BTCSPOT')
  with pytest.raises(NotImplementedError, match='builder'):
    fill(trade('ETH-USD', builderFee=Decimal('0.01')), MARKETS)


def test_closed_positions_carry_the_pnl_breakdown():
  """`tradePnl` is the realized PnL; the venue's negative fees become positive fees."""
  summary = position(
    {
      'id': 3,
      'accountId': 3880,
      'market': 'ETH-USD',
      'side': 'LONG',
      'leverage': Decimal(10),
      'size': Decimal('0.001'),
      'maxPositionSize': Decimal('0.001'),
      'openPrice': Decimal('2435.18'),
      'exitPrice': Decimal('2332.63'),
      'realisedPnl': Decimal('-0.104933'),
      'realisedPnlBreakdown': {
        'tradePnl': Decimal('-0.10255'),
        'fundingFees': Decimal('0'),
        'openFees': Decimal('-0.001217'),
        'closeFees': Decimal('-0.001166'),
      },
      'createdTime': T - HOUR,
      'closedTime': T,
    },
    MARKETS,
  )
  assert isinstance(summary, FuturePositionSummary)
  assert (summary.realized_pnl, summary.opening_fee, summary.total_fee) == (
    Decimal('-0.10255'),
    Decimal('0.001217'),
    Decimal('0.002383'),
  )
  assert summary.position_pnl == Decimal('-0.104933')


def pages(*rows: list[Any]) -> PaginatedResponse[Any, int]:
  """The given pages, in order."""

  async def fetch(state: int) -> tuple[list[Any], int | None]:
    return rows[state], state + 1 if state + 1 < len(rows) else None

  return PaginatedResponse(0, fetch)


def serve(
  report: Report, *, funding: list[Any] | None = None, interest: list[Any] | None = None
):
  """Replace every endpoint history reads with fixtures."""
  client = report.shared.client
  report.shared.markets.update(MARKETS)

  async def info() -> Any:
    return {'accountId': 3880, 'status': 'ACTIVE'}

  async def payments(accounts: list[int], *, interval: str) -> Any:
    return {'items': interest or []}

  async def assets(*, type: str) -> list[Any]:
    return [{'id': 1, 'name': 'USD'}]

  client.account.info = info  # type: ignore[method-assign]
  client.account.funding_history_paged = lambda **kw: pages(funding or [])  # type: ignore[method-assign]
  client.interest.payments = payments  # type: ignore[method-assign]
  client.info.assets = assets  # type: ignore[method-assign]
  client.account.asset_operations_paged = lambda **kw: pages(  # type: ignore[method-assign]
    [op('CLAIM', '1000'), op('TRANSFER', '1', status='CREATED')]
  )
  client.account.trades_paged = lambda *a, **kw: pages(  # type: ignore[method-assign]
    [trade('ETH-USD', createdTime=T + HOUR), trade('ETH-USD', id=8)],
    [trade('ETH-USD', id=9, createdTime=T - 10 * HOUR)],
    [trade('ETH-USD', id=10, createdTime=T - 20 * HOUR)],
  )
  client.account.positions_history_paged = lambda *a, **kw: pages(  # type: ignore[method-assign]
    [
      {
        'id': 4,
        'accountId': 3880,
        'market': 'ETH-USD',
        'side': 'LONG',
        'openPrice': Decimal(1),
        'realisedPnl': Decimal(0),
        'createdTime': T - HOUR,
        'closedTime': None,
      }
    ]
  )


async def test_history_streams_operations_fills_and_positions():
  """Rows inside the window, each with its venue row as provenance; fills stop at the
  first page reaching before `start`, and open positions are left out."""
  async with Report.new('key', network='testnet') as report:
    serve(report)
    records = [r async for r in report.history(T - 5 * HOUR, T)]
  assert [r.observations[0].id for r in records] == [
    'operation:2112523545589317632',
    'trade:8',
  ]
  assert {r.provenance.get('service') for r in records} == {'extended_testnet'}


async def test_history_refuses_unobserved_interest_signs():
  """A borrow-interest payment in the window raises before anything is yielded."""
  async with Report.new('key') as report:
    serve(report, interest=[{'timestamp': T}])
    with pytest.raises(NotImplementedError, match='sign'):
      [r async for r in report.history(T - HOUR, T + HOUR)]


def payment(id: int, paid: datetime, fee: str) -> Any:
  """A funding payment row of the key's sub-account; `fee` is the venue's `fundingFee`."""
  return {
    'id': id,
    'accountId': 3880,
    'market': 'ETH-USD',
    'positionId': 77,
    'side': 'LONG',
    'value': Decimal('3.07'),
    'markPrice': Decimal('2400'),
    'fundingFee': Decimal(fee),
    'fundingRate': Decimal('0.000013'),
    'paidTime': paid,
  }


async def test_history_yields_funding_payments():
  """Payments in the window are `Funding`, received-positive as `fundingFee` is (the
  testnet long paying a positive rate read `-0.000041`)."""
  async with Report.new('key') as report:
    serve(report, funding=[payment(1, T, '-0.000041'), payment(2, T + 2 * HOUR, '0.1')])
    records = [r async for r in report.history(T - HOUR, T + HOUR)]
  (paid,) = [o for r in records for o in r.observations if isinstance(o, Funding)]
  assert (paid.id, paid.amount, paid.asset, paid.subaccount) == (
    'funding:1',
    Decimal('-0.000041'),
    'USD',
    '3880',
  )
  assert (paid.instrument, paid.position_id, paid.time) == ('ETH-USD', '77', T)


async def test_snapshot_is_the_keys_sub_account():
  """One subaccount labelled by `accountId`: non-zero holdings and signed positions."""
  async with Report.new('key') as report:
    account = report.shared.client.account

    async def info() -> Any:
      return {'accountId': 3880}

    async def spot_balances() -> list[Any]:
      return [
        {'asset': 'USD', 'balance': Decimal('994.79')},
        {'asset': 'BTCSPOT', 'balance': Decimal('0')},
      ]

    async def positions() -> list[Any]:
      return [
        {
          'market': 'ETH-USD',
          'side': 'SHORT',
          'size': Decimal('2'),
          'openPrice': Decimal('2400'),
        }
      ]

    account.info = info  # type: ignore[method-assign]
    account.spot_balances = spot_balances  # type: ignore[method-assign]
    account.positions = positions  # type: ignore[method-assign]
    record = await report.snapshot()
  (sub,) = record.snapshot.subaccounts
  assert sub.subaccount == '3880' and sub.balances == {'USD': Decimal('994.79')}
  assert sub.positions['ETH-USD'].size == Decimal('-2')
  assert record.provenance.get('service') == 'extended'
