"""Venue-row mappings, checked against figures observed on testnet."""

from datetime import datetime, timezone
from decimal import Decimal
from typing_extensions import Any, cast

import pytest
from typed_lighter.api.account.get import DetailedAccount
from typed_lighter.api.markets.order_book_details import PerpsOrderBookDetail
from typed_lighter.schemas import AccountPosition, SimpleOrder, Trade as TradeRow

from tribulnation.lighter.core import ClientIndexes
from tribulnation.lighter.market import account, books, history
from tribulnation.lighter.market.common import parse_trade
from tribulnation.sdk.core import ApiError

ACCOUNT = 476
TIME = datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc)


def trade(**fields: Any) -> TradeRow:
  """A trade row with the fields the mappings read."""
  row: dict[str, Any] = {
    'trade_id_str': '1',
    'market_id': 4098,
    'timestamp': TIME,
    'size': Decimal('0.0050'),
    'price': Decimal('2500.00'),
    'usd_amount': Decimal('12.500000'),
  }
  row.update(fields)
  return cast(TradeRow, row)


def test_perp_taker_fee_is_the_tick_on_usdc_notional():
  """A premium taker fill (280 ppm) matched the account's USDC balance change exactly."""
  row = trade(
    market_id=4095,
    usd_amount=Decimal('27.193100'),
    price=Decimal('2719.31'),
    size=Decimal('0.0100'),
    ask_account_id=279,
    bid_account_id=ACCOUNT,
    is_maker_ask=True,
    taker_fee=280,
  )
  fee = history.perp_fee(row, ACCOUNT)
  assert fee.asset == '3' and fee.amount == Decimal('0.007614068')
  fill = parse_trade(row, ACCOUNT, fee)
  assert fill.qty == Decimal('0.0100') and not fill.maker


def spot_fee(t: TradeRow, account_index: int):
  """ETH/USDC: base asset 1, quote asset 3."""
  return history.spot_fee(lambda _: 1, lambda _: 3)(t, account_index)


def test_spot_sell_pays_in_the_quote_asset():
  """Selling delivers USDC, so the fee is the tick on the quote amount."""
  row = trade(
    ask_account_id=ACCOUNT, bid_account_id=9, is_maker_ask=False, taker_fee=280
  )
  fee = spot_fee(row, ACCOUNT)
  assert (fee.asset, fee.amount) == ('3', Decimal('0.0035'))
  assert parse_trade(row, ACCOUNT, fee).qty == Decimal('-0.0050')


def test_spot_maker_buy_pays_in_the_base_asset():
  """Buying delivers ETH, so the fee is the tick on the base size."""
  row = trade(
    ask_account_id=9, bid_account_id=ACCOUNT, is_maker_ask=False, maker_fee=40
  )
  fee = spot_fee(row, ACCOUNT)
  assert (fee.asset, fee.amount) == ('1', Decimal('2.000E-7'))
  assert parse_trade(row, ACCOUNT, fee).maker


def test_absent_fee_tick_is_zero():
  """The venue omits zero fee fields."""
  row = trade(ask_account_id=ACCOUNT, bid_account_id=9, is_maker_ask=True)
  assert spot_fee(row, ACCOUNT).amount == 0


def order(price: str, qty: str) -> SimpleOrder:
  """A resting order."""
  return cast(
    SimpleOrder, {'price': Decimal(price), 'remaining_base_amount': Decimal(qty)}
  )


def test_book_levels_sum_orders_and_drop_a_full_sides_last_level():
  """A side at the request limit may be missing orders at its last price."""
  orders = [order('10', '1'), order('10', '2'), order('9', '1')]
  assert [(e.price, e.qty) for e in books.aggregate(orders, full=False)] == [
    (Decimal(10), Decimal(3)),
    (Decimal(9), Decimal(1)),
  ]
  assert len(books.aggregate(orders, full=True)) == 1


def position(**fields: Any) -> AccountPosition:
  """A position entry."""
  row: dict[str, Any] = {
    'market_id': 4095,
    'sign': 1,
    'position': Decimal('0.0200'),
    'avg_entry_price': Decimal('2715.43'),
    'position_value': Decimal('54.279200'),
    'unrealized_pnl': Decimal('0.007500'),
    'initial_margin_fraction': Decimal('10.00'),
    'margin_mode': 1,
    'allocated_margin': Decimal('25.465340'),
  }
  row.update(fields)
  return cast(AccountPosition, row)


def detailed(**fields: Any) -> DetailedAccount:
  """An account with the fields the collateral mappings read."""
  row: dict[str, Any] = {
    'account_trading_mode': 1,
    'available_balance': Decimal('3977.094662'),
    'cross_asset_value': Decimal('3957.086742'),
    'cross_initial_margin_requirement': Decimal('0'),
    'cross_maintenance_margin_requirement': Decimal('0'),
    'positions': [position()],
    'assets': [],
  }
  row.update(fields)
  return cast(DetailedAccount, row)


DETAIL = cast(
  PerpsOrderBookDetail,
  {'maintenance_margin_fraction': 120, 'default_initial_margin_fraction': 500},
)


def test_isolated_bucket_from_allocated_margin_and_fractions():
  """Equity is allocation plus uPnL; requirements are the fractions of position value."""
  bucket = account.market_bucket(detailed(), 4095, DETAIL)
  assert bucket.margin_mode == 'isolated'
  assert bucket.equity == Decimal('25.472840')
  assert bucket.initial_margin == Decimal('5.42792')
  assert bucket.maintenance_margin == Decimal('0.6513504')
  assert bucket.free_collateral == bucket.equity - bucket.initial_margin


def test_cross_free_excludes_isolated_free_margin():
  """`available_balance` adds isolated free margin; the cross bucket must not."""
  bucket = account.cross_bucket(detailed())
  assert bucket.free_collateral == Decimal('3957.086742')
  assert bucket.leverage == 0


def test_available_notional_uses_the_configured_leverage():
  """Free cross collateral over the position's initial margin fraction (10x)."""
  acct = detailed()
  assert account.perp_available_notional(acct, 4095, DETAIL) == Decimal('39570.86742')
  assert account.perp_available_notional(acct, 4096, DETAIL) == Decimal('79141.73484')


def test_perp_position_is_signed():
  """`position` is unsigned beside `sign`."""
  acct = detailed(positions=[position(sign=-1)])
  assert account.perp_position(acct, 4095).size == Decimal('-0.0200')
  assert account.perp_position(acct, 1).size == 0


def usdc(**fields: Any) -> dict[str, Any]:
  """A USDC balance row."""
  row: dict[str, Any] = {
    'asset_id': 3,
    'balance': Decimal('0'),
    'locked_balance': Decimal('24'),
    'margin_mode': 'enabled',
    'margin_balance': Decimal('3987.38'),
  }
  row.update(fields)
  return row


def test_unified_spot_collateral_is_available_balance_net_of_locks():
  """Spot locks are not reflected in `available_balance`."""
  acct = detailed(available_balance=Decimal('3987.38'), assets=[usdc()])
  collateral = account.spot_collateral(acct, 3)
  assert collateral.equity == Decimal('3987.38')
  assert collateral.free_collateral == Decimal('3963.38')


def test_classic_accounts_are_unsupported_for_spot_collateral():
  """Spot collateral is qualified for unified accounts only."""
  with pytest.raises(ApiError):
    account.spot_collateral(detailed(account_trading_mode=0, assets=[usdc()]), 3)


def test_grid_start_rounds_up_to_the_interval():
  """Candles opening at or after the grid point are those at or after `start`."""
  width = history.candle_width('1h')
  assert history.grid_start(TIME, width) == TIME
  assert history.grid_start(TIME.replace(minute=1), width) == TIME.replace(hour=14)


def test_client_indexes_are_unique_under_bursts():
  """Placements in the same microsecond still get distinct, increasing indexes."""
  indexes = ClientIndexes()
  batch = [indexes.next() for _ in range(1000)]
  assert batch == sorted(set(batch)) and max(batch) < 2**48
