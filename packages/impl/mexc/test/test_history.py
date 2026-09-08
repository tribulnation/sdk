"""Deterministic tests for MEXC's history parsers and sweeps.

The rows are MEXC's own documented sample payloads, run through the typed client's
validators so the parsers see exactly the `TypedDict`s a live call hands them. The
repo's test key lacks the scopes these endpoints need, so this is what pins the mapping
until `sdk-dev test report mexc` runs against a scoped key.
"""

from typing_extensions import Any, Sequence, cast
from dataclasses import dataclass, field
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pydantic
import pytest

from tribulnation.mexc.core import windows
from tribulnation.mexc.core.mixin import Cache
from tribulnation.mexc.reporting import history
from tribulnation.mexc.reporting.main import Report
from tribulnation.sdk.reporting import (
  CryptoDeposit,
  CryptoWithdrawal,
  Funding,
  SpotTrade,
)
from typed_core import PaginatedResponse
from typed_mexc.futures.http.account.funding_records import FundingRecordsItem
from typed_mexc.spot.http.account.trades import AccountTrade
from typed_mexc.spot.http.wallet.deposit_history import DepositHistoryItem
from typed_mexc.spot.http.wallet.withdraw_history import WithdrawHistoryItem

UTC = timezone.utc

TRADE: dict[str, Any] = {
  'symbol': 'BNBBTC',
  'id': 'fad2af9e942049b6adbda1a271f990c6',
  'orderId': 'bb41e5663e124046bd9497a3f5692f39',
  'orderListId': -1,
  'price': '4.00000100',
  'qty': '12.00000000',
  'quoteQty': '48.000012',
  'commission': '10.10000000',
  'commissionAsset': 'BNB',
  'time': 1499865549590,
  'isBuyer': True,
  'isMaker': False,
  'isBestMatch': True,
  'isSelfTrade': True,
  'clientOrderId': None,
}
"""`GET /api/v3/myTrades`'s documented sample row."""

DEPOSIT: dict[str, Any] = {
  'amount': '50000',
  'coin': 'EOS',
  'network': 'EOS',
  'status': 5,
  'address': '0x20b7cf77db93d6ef1ab979c49142ec168427fdee',
  'txId': '01391d1c1397ef0a3cbb3c7f99a90846f7c8c2a8dddcdcf84f46b530dede203e1bc804',
  'insertTime': 1659513342000,
  'unlockConfirm': '10',
  'confirmTimes': '241',
  'memo': 'xxyy1122',
}
"""`GET /api/v3/capital/deposit/hisrec`'s documented sample row."""

WITHDRAWAL: dict[str, Any] = {
  'id': 'bb17a2d452684f00a523c015d512a341',
  'txId': None,
  'coin': 'EOS',
  'network': 'EOS',
  'address': 'zzqqqqqqqqqq',
  'amount': '10',
  'transferType': 0,
  'status': 3,
  'transactionFee': '0',
  'confirmNo': None,
  'applyTime': 1665300874000,
  'remark': '',
  'memo': 'MX10086',
  'transHash': '0x0ced593b8b5adc9f600334d0d7335456a7ed772ea5547beda7ffc4f33a065c',
  'updateTime': 1712134082000,
  'coinId': '128f589271cb495b03e71e6323eb7be',
  'vcoinId': 'af42c6414b9a46c8869ce30fd51660f',
}
"""`GET /api/v3/capital/withdraw/history`'s documented sample row."""

FUNDING: dict[str, Any] = {
  'id': 7982,
  'symbol': 'BTC_USDT',
  'positionId': 1128,
  'positionType': 1,
  'positionValue': 106.7,
  'funding': -0.01623,
  'rate': 0.0001,
  'settleTime': 1700000000000,
}
"""One `funding_records` row in the shape the client declares (MEXC sends numbers)."""


def trade(**overrides: Any) -> AccountTrade:
  """The sample fill, validated the way the client validates a live one."""
  return pydantic.TypeAdapter(AccountTrade).validate_python({**TRADE, **overrides})


def deposit(**overrides: Any) -> DepositHistoryItem:
  """The sample deposit, validated like a live one."""
  return pydantic.TypeAdapter(DepositHistoryItem).validate_python(
    {**DEPOSIT, **overrides}
  )


def withdrawal(**overrides: Any) -> WithdrawHistoryItem:
  """The sample withdrawal, validated like a live one."""
  return pydantic.TypeAdapter(WithdrawHistoryItem).validate_python(
    {**WITHDRAWAL, **overrides}
  )


def funding(**overrides: Any) -> FundingRecordsItem:
  """The funding row, validated like a live one."""
  return pydantic.TypeAdapter(FundingRecordsItem).validate_python(
    {**FUNDING, **overrides}
  )


def test_a_buy_fill_is_a_positive_spot_trade_with_its_fee():
  """Signs, ids and the fee come straight from the row; base/quote from the caller."""
  t = history.parse_spot_trade(trade(), base='BNB', quote='BTC')
  assert isinstance(t, SpotTrade)
  assert (t.id, t.order_id, t.pair) == (TRADE['id'], TRADE['orderId'], 'BNBBTC')
  assert (t.base, t.quote) == ('BNB', 'BTC')
  assert t.size == Decimal('12.00000000')
  assert t.price == Decimal('4.00000100')
  assert t.time == datetime(2017, 7, 12, 13, 19, 9, 590000, tzinfo=UTC)
  assert t.fee is not None and (t.fee.amount, t.fee.asset) == (
    Decimal('10.10000000'),
    'BNB',
  )
  assert t.subaccount == 'spot'


def test_a_sell_fill_is_negative_and_a_zero_commission_is_reported():
  """`isBuyer=False` flips the size; a `0` commission is a real fee, not an absent one."""
  t = history.parse_spot_trade(trade(isBuyer=False, commission='0', id=42))
  assert t.size == Decimal('-12.00000000')
  assert t.id == '42'
  assert t.fee is not None and t.fee.amount == Decimal(0)


def test_a_deposit_is_keyed_by_its_transaction_hash():
  """MEXC reports no deposit id and no fee, so the hash is the id and the fee is absent."""
  d = history.parse_deposit(deposit())
  assert isinstance(d, CryptoDeposit)
  assert d.id == d.tx_id == DEPOSIT['txId']
  assert (d.asset, d.amount, d.network) == ('EOS', Decimal('50000'), 'EOS')
  assert d.dst_address == DEPOSIT['address']
  assert d.time == datetime(2022, 8, 3, 7, 55, 42, tzinfo=UTC)
  assert d.fee is None
  assert d.subaccount == 'spot'


def test_a_deposit_without_coin_or_amount_is_an_error_not_a_gap():
  """A row that cannot be accounted for must surface, not silently disappear."""
  with pytest.raises(ValueError):
    history.parse_deposit(deposit(coin=None))
  with pytest.raises(ValueError):
    history.parse_deposit(deposit(amount=None))


def test_a_withdrawal_is_timed_at_apply_and_reports_a_zero_fee():
  """The balance leaves at `applyTime`; `transactionFee = '0'` is a free withdrawal."""
  w = history.parse_withdrawal(withdrawal())
  assert isinstance(w, CryptoWithdrawal)
  assert w.id == WITHDRAWAL['id']
  assert (w.asset, w.amount) == ('EOS', Decimal('10'))
  assert w.balance_change == Decimal('-10')
  assert w.time == datetime(2022, 10, 9, 7, 34, 34, tzinfo=UTC)
  # `txId` is null in the sample; `transHash` carries the hash instead.
  assert w.tx_id == WITHDRAWAL['transHash']
  assert w.fee is not None and w.fee.amount == Decimal(0) and w.fee.asset == 'EOS'


def test_a_withdrawal_without_a_fee_field_has_no_fee():
  """Only a null `transactionFee` means no fee is known."""
  w = history.parse_withdrawal(withdrawal(transactionFee=None, id=None, txId='0xab'))
  assert w.fee is None
  assert w.id == '0xab'


def test_a_funding_settlement_keeps_the_venue_sign_and_digits():
  """`funding` arrives as a float; `str` keeps MEXC's digits, the sign is MEXC's own."""
  f = history.parse_funding(funding(), settle='USDT')
  assert isinstance(f, Funding)
  assert f.amount == Decimal('-0.01623')
  assert (f.asset, f.instrument, f.position_id) == ('USDT', 'BTC_USDT', '1128')
  assert f.id == '7982'
  assert f.time == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
  assert f.subaccount == 'futures'


def test_a_funding_row_without_a_position_id_maps_to_none():
  """`positionId` is `NotRequired`; its absence is not an error."""
  row = {k: v for k, v in FUNDING.items() if k != 'positionId'}
  r = pydantic.TypeAdapter(FundingRecordsItem).validate_python(row)
  f = history.parse_funding(r, settle='USDT')
  assert f.position_id is None


def test_windows_slice_a_wide_span_into_inclusive_capital_windows():
  """A 200-day span is three 90-day-capped windows that tile it with no overlap."""
  start = datetime(2025, 1, 1, tzinfo=UTC)
  end = start + timedelta(days=200)
  slices = list(windows(start, end, history.CAPITAL_WINDOW))
  assert len(slices) == 3
  assert slices[0] == (start, start + timedelta(days=90))
  assert slices[1][0] == slices[0][1] + timedelta(milliseconds=1)
  assert slices[-1][1] == end


@dataclass
class FakeSpotAccount:
  """A `myTrades` endpoint recording the windows it was asked for."""

  calls: list[tuple[str, datetime, datetime]] = field(
    default_factory=list[tuple[str, datetime, datetime]]
  )

  async def trades(self, **kwargs: Any) -> list[AccountTrade]:
    """One fill per call, stamped with the window's lower bound."""
    symbol = cast(str, kwargs['symbol'])
    lower = cast(datetime, kwargs['start_time'])
    upper = cast(datetime, kwargs['end_time'])
    self.calls.append((symbol, lower, upper))
    return [
      trade(symbol=symbol, id=len(self.calls), time=int(lower.timestamp() * 1000))
    ]


@dataclass
class FakeFuturesAccount:
  """A `funding_records` endpoint serving pages that are not sorted by time."""

  pages: list[list[dict[str, Any]]]
  requested: list[int] = field(default_factory=list[int])

  async def funding_records(self, symbol: str | None = None, **kwargs: Any) -> Any:
    """Serve page `page_num` in the envelope the client expects."""
    page_num = cast(int, kwargs['page_num'])
    self.requested.append(page_num)
    rows = self.pages[page_num - 1]
    return {
      'success': True,
      'code': 0,
      'data': {
        'pageSize': len(rows),
        'totalCount': sum(len(p) for p in self.pages),
        'totalPage': len(self.pages),
        'currentPage': page_num,
        'resultList': [funding(**r) for r in rows],
      },
    }

  def funding_records_paged(
    self, symbol: str | None = None, **kwargs: Any
  ) -> PaginatedResponse[FundingRecordsItem, int]:
    """The client's paged variant's stop rule -- `totalPage` reached -- over this fake."""

    async def next(page_num: int) -> tuple[Sequence[FundingRecordsItem], int | None]:
      response = await self.funding_records(symbol, page_num=page_num, **kwargs)
      rows = cast(list[FundingRecordsItem], response['data']['resultList'])
      total = cast(int, response['data']['totalPage'])
      return rows, None if page_num >= total else page_num + 1

    return PaginatedResponse(1, next)


def ms(t: datetime) -> int:
  """A datetime as MEXC's millisecond epoch."""
  return int(t.timestamp() * 1000)


def report(client: Any, **overrides: Any) -> Report:
  """A report wired to a fake client, with markets and contract info pre-cached."""
  cache = Cache()
  cache.spot_markets = {
    'BTCUSDT': cast(
      Any, {'symbol': 'BTCUSDT', 'baseAsset': 'BTC', 'quoteAsset': 'USDT'}
    )
  }
  cache.perp_markets = {
    'BTC_USDT': cast(Any, {'symbol': 'BTC_USDT', 'settleCoin': 'USDT'})
  }
  return Report(client=client, streams={}, cache=cache, **overrides)


async def test_spot_fills_are_swept_per_symbol_in_daily_windows():
  """Three daily slices tile a 3-day window; each is one call per symbol, and the base
  and quote come from the cached exchange info."""
  account = FakeSpotAccount()
  client = SimpleNamespace(spot=SimpleNamespace(http=SimpleNamespace(account=account)))
  start = datetime(2025, 3, 1, tzinfo=UTC)
  end = start + timedelta(days=3)
  records = [
    r async for r in history.spot_trades(report(client), ['BTCUSDT'], start, end)
  ]
  assert [c[0] for c in account.calls] == ['BTCUSDT'] * 3
  assert account.calls[0][1] == start and account.calls[-1][2] == end
  assert len(records) == 3
  first = records[0].observations[0]
  assert isinstance(first, SpotTrade) and (first.base, first.quote) == ('BTC', 'USDT')
  assert records[0].provenance['id'] == 'spot-trade-1'
  assert records[0].provenance['source'] == 'api'


async def test_funding_is_windowed_client_side_across_every_page():
  """Pages are read to the end and filtered here, since MEXC promises no page order;
  the settlement coin comes from the cached contract info."""
  start = datetime(2025, 3, 1, tzinfo=UTC)
  end = start + timedelta(days=1)
  account = FakeFuturesAccount(
    pages=[
      [{'id': 1, 'settleTime': ms(end + timedelta(hours=1))}],
      [{'id': 2, 'settleTime': ms(start + timedelta(hours=8))}],
      [{'id': 3, 'settleTime': ms(start - timedelta(hours=1))}],
    ]
  )
  client = SimpleNamespace(
    futures=SimpleNamespace(http=SimpleNamespace(account=account))
  )
  records = [r async for r in history.funding(report(client), start, end)]
  assert account.requested == [1, 2, 3]
  assert [r.provenance['id'] for r in records] == ['funding-2']
  settlement = records[0].observations[0]
  assert isinstance(settlement, Funding) and settlement.asset == 'USDT'


async def test_history_requires_a_start():
  """An open-ended window would be silently truncated, so it is refused outright."""
  with pytest.raises(ValueError):
    async for _ in history.history(report(cast(Any, None)), [], None, None):
      pass
