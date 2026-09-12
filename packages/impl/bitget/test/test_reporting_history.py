"""Classic history adapters use current Typed endpoints without private fixtures."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_bitget import Bitget
from typed_bitget.classic.margin.cross.order.fills import Fills as CrossFills
from typed_bitget.classic.margin.isolated.order.fills import Fills as IsolatedFills
from typed_bitget.classic.mix.order.fill_history import FillHistory
from typed_bitget.classic.spot.deposit.records import Records as DepositRecords
from typed_bitget.classic.spot.order.fills import Fills as SpotFills
from typed_bitget.classic.spot.symbols import Symbols
from typed_bitget.classic.spot.withdrawal.records import Records as WithdrawalRecords
from typed_bitget.classic.tax.margin_records import MarginRecords

from tribulnation.bitget.reporting.history.futures import FuturesHistory
from tribulnation.bitget.reporting.history.margin import MarginHistory
from tribulnation.bitget.reporting.history.spot import SpotHistory
from tribulnation.bitget.reporting.history.util import TimezoneMixin, id_pages, windows, require_range
from tribulnation.sdk.reporting import CryptoDeposit, CryptoWithdrawal, SpotTrade

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
  """Use a real client with symbol discovery stubbed at the endpoint boundary."""
  monkeypatch.setattr(
    Symbols,
    'symbols',
    AsyncMock(
      return_value=[
        {'symbol': 'BTCUSDT', 'baseCoin': 'BTC', 'quoteCoin': 'USDT'},
      ]
    ),
  )
  return Bitget.new(public=True)


async def test_spot_fill_namespace_cursor_and_decimals(
  client: Bitget,
  monkeypatch: pytest.MonkeyPatch,
):
  """Sweep a symbol, follow short nonempty pages, and parse string amounts."""
  row: dict[str, object] = {
    'tradeId': '20',
    'symbol': 'BTCUSDT',
    'orderId': 'order',
    'side': 'sell',
    'size': '2',
    'priceAvg': '3',
    'cTime': START,
    'feeDetail': {'totalFee': '-0.1', 'feeCoin': 'USDT'},
  }
  request = AsyncMock(side_effect=[[row], [{**row, 'tradeId': '10'}], []])
  monkeypatch.setattr(SpotFills, 'fills', request)
  records = [record async for record in SpotHistory(client=client).trades(START, END)]
  assert len(records) == 2
  trade = records[0].observations[0]
  assert isinstance(trade, SpotTrade)
  assert trade.size == Decimal(-2)
  assert trade.price == Decimal(3)
  assert trade.fee is not None and trade.fee.amount == Decimal('0.1')
  assert trade.time == START
  assert [call.kwargs['id_less_than'] for call in request.await_args_list] == [
    None,
    '20',
    '10',
  ]
  assert all(call.kwargs['symbol'] == 'BTCUSDT' for call in request.await_args_list)


@pytest.mark.parametrize('withdrawal', [False, True])
async def test_capital_uses_exchange_order_cursor(
  client: Bitget,
  monkeypatch: pytest.MonkeyPatch,
  withdrawal: bool,
):
  """Do not use a shared blockchain transaction ID as the pagination cursor."""
  row: dict[str, object] = {
    'orderId': '20',
    'tradeId': 'shared-chain-tx',
    'coin': 'BTC',
    'size': Decimal(2),
    'fee': Decimal('0.1'),
    'dest': 'on_chain',
    'status': 'success',
    'chain': 'BTC',
    'cTime': START,
    'toAddress': 'fixture',
  }
  request = AsyncMock(
    side_effect=[
      [row],
      [{**row, 'orderId': '10'}],
      [{**row, 'orderId': '5', 'status': 'pending'}],
      [],
    ]
  )
  monkeypatch.setattr(
    WithdrawalRecords if withdrawal else DepositRecords, 'records', request
  )
  history = SpotHistory(client=client)
  iterator = (
    history.withdrawals(START, END) if withdrawal else history.deposits(START, END)
  )
  records = [record async for record in iterator]
  assert len(records) == 2
  assert [call.kwargs['id_less_than'] for call in request.await_args_list] == [
    None,
    '20',
    '10',
    '5',
  ]
  observation = records[0].observations[0]
  assert isinstance(observation, (CryptoDeposit, CryptoWithdrawal))
  assert observation.amount == Decimal(-2 if withdrawal else 2)


@pytest.mark.parametrize('side,expected', [('buy', 2), ('sell', -2)])
async def test_futures_current_pager_and_direction(
  client: Bitget,
  monkeypatch: pytest.MonkeyPatch,
  side: str,
  expected: int,
):
  """The fill's transaction side supplies the sign, including hedge-mode closes."""
  row: dict[str, object] = {
    'tradeId': 'fill',
    'symbol': 'BTCUSDT',
    'orderId': 'order',
    'side': side,
    'tradeSide': 'close',
    'posMode': 'hedge_mode',
    'baseVolume': '2',
    'price': '3',
    'cTime': START,
    'feeDetail': [{'totalFee': '-0.1', 'feeCoin': 'USDT'}],
  }
  request = AsyncMock(
    side_effect=[
      {'fillList': [row], 'endId': 'cursor'},
      {'fillList': None, 'endId': None},
    ]
  )
  monkeypatch.setattr(FillHistory, 'fill_history', request)
  records = [
    record async for record in FuturesHistory(client=client).trades(START, END)
  ]
  trade = records[0].observations[0]
  assert isinstance(trade, SpotTrade)
  assert trade.size == Decimal(expected)
  assert trade.price == Decimal(3)
  assert request.await_args_list[1].kwargs['id_less_than'] == 'cursor'
  assert request.await_args_list[0].kwargs['product_type'] == 'USDT-FUTURES'


async def test_margin_discovers_symbols_from_tax_rows(
  client: Bitget,
  monkeypatch: pytest.MonkeyPatch,
):
  """Fill discovery does not depend on raw responses in public provenance."""
  monkeypatch.setattr(
    MarginRecords,
    'margin_records',
    AsyncMock(
      return_value=[
        {
          'id': 'tax',
          'symbol': 'BTCUSDT',
          'coin': 'BTC',
          'amount': Decimal(1),
          'fee': Decimal(0),
          'ts': START,
        }
      ]
    ),
  )
  row: dict[str, object] = {
    'tradeId': 'fill',
    'side': 'liquidation_sell',
    'size': Decimal(2),
    'cTime': START,
  }
  cross = AsyncMock(
    side_effect=[{'fills': [row], 'minId': 'cursor'}, {'fills': [], 'minId': '0'}]
  )
  isolated = AsyncMock(
    side_effect=[{'fills': [row], 'minId': 'cursor'}, {'fills': [], 'minId': None}]
  )
  monkeypatch.setattr(CrossFills, 'fills', cross)
  monkeypatch.setattr(IsolatedFills, 'fills', isolated)
  records = [
    record async for record in MarginHistory(client=client).history(START, END)
  ]
  trades = [o for r in records for o in r.observations if isinstance(o, SpotTrade)]
  assert len(trades) == 2
  assert all(
    t.size == Decimal(-2) and t.fee is None and t.order_id is None for t in trades
  )
  assert cross.await_args_list[0].kwargs['symbol'] == 'BTCUSDT'
  assert isolated.await_args_list[0].kwargs['symbol'] == 'BTCUSDT'


async def test_margin_missing_direction_is_unknown_not_sell(
  client: Bitget,
  monkeypatch: pytest.MonkeyPatch,
):
  """Optional response fields remain unknown instead of inventing values."""
  monkeypatch.setattr(
    CrossFills,
    'fills',
    AsyncMock(
      return_value={
        'fills': [{'size': Decimal(2)}],
        'minId': None,
      }
    ),
  )
  records = [
    r
    async for r in MarginHistory(client=client).symbol_trades(
      'crossed', 'BTCUSDT', START, END
    )
  ]
  trade = records[0].observations[0]
  assert isinstance(trade, SpotTrade)
  assert trade.size is None and trade.time is None and trade.fee is None


async def test_id_pager_stops_when_venue_repeats_page():
  """Best-effort paging neither loops forever nor raises a completeness error."""
  request = AsyncMock(side_effect=[['2', '1'], ['1', '0'], ['1', '0']])
  pages = [page async for page in id_pages(request, lambda row: str(row))]
  assert pages == [['2', '1'], ['0']]
  assert request.await_count == 3


def test_typed_aware_timestamps_keep_their_instant():
  """The old local-time option must not reinterpret already-aware Typed values."""
  converter = TimezoneMixin(tz=timezone(timedelta(hours=3)))
  assert converter.add_tz(START) == START
  assert converter.add_tz(START.replace(tzinfo=None)).utcoffset() == timedelta(hours=3)


def test_optional_history_bounds_choose_a_recent_window():
  """Legacy Bitget history must also honor the optional-bound SDK contract."""
  assert require_range(None, END) == (END - timedelta(days=30), END)
  before = datetime.now(timezone.utc)
  lower, upper = require_range(None, None)
  assert before <= upper <= datetime.now(timezone.utc)
  assert upper - lower == timedelta(days=30)
  assert require_range(START, END) == (START, END)


def test_history_windows_respect_tax_endpoint_limit():
  """Adjacent inclusive wire windows neither overlap nor exceed 30 days."""
  end = START + timedelta(days=65)
  result = list(windows(START, end))
  assert len(result) == 3 and result[0][0] == START and result[-1][1] == end
  assert all(upper - lower < timedelta(days=30) for lower, upper in result)
  assert all(
    right[0] - left[1] == timedelta(milliseconds=1)
    for left, right in zip(result, result[1:])
  )
