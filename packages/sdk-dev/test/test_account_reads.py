"""Account modes and account-read checks, exercised with fakes and no network."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sdk_dev.integration.accounts import account_mode
from sdk_dev.integration.market import account as reads
from sdk_dev.integration.market.account import AccountCheckError, AccountResults
from sdk_dev.support import AccountMode
from tribulnation.sdk.impl.accounts import (
  Aster,
  Binance,
  Dydx,
  Hyperliquid,
  Kucoin,
  Lighter,
)
from tribulnation.sdk.market import (
  Collateral,
  Fees,
  FundingPayment,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Position,
  Rules,
  Trade,
)

END = datetime(2026, 10, 8, tzinfo=timezone.utc)
START = END - timedelta(days=30)
SECRET = Decimal('987654.321')
"""A recognizable account value that must never appear in a failure message."""


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
  """Remove every credential variable the derived modes could read."""
  for name in (
    'LIGHTER_API_PRIVATE_KEY',
    'LIGHTER_AUTH_TOKEN',
    'LIGHTER_ADDRESS',
    'LIGHTER_ACCOUNT_INDEX',
    'LIGHTER_API_KEY_INDEX',
    'ASTER_USER',
    'ASTER_SIGNER_PRIVATE_KEY',
    'HYPERLIQUID_ADDRESS',
    'HYPERLIQUID_PRIVATE_KEY',
    'BINANCE_API_KEY',
    'BINANCE_SECRET_KEY',
  ):
    monkeypatch.delenv(name, raising=False)
  return monkeypatch


def test_declared_modes_ignore_the_environment(clean_env: pytest.MonkeyPatch):
  """The tracked configuration's mode is a property of its fields alone."""
  assert account_mode(Binance(), resolve=False) == 'private'
  assert account_mode(Binance(public=True), resolve=False) == 'public'
  assert account_mode(Hyperliquid(address='', public=True), resolve=False) == 'public'
  assert account_mode(Hyperliquid(public=True), resolve=False) == 'address'
  assert (
    account_mode(Hyperliquid(address='$X', public=True), resolve=False) == 'address'
  )
  assert account_mode(Dydx(address='$X', public=True), resolve=False) == 'address'
  assert account_mode(Lighter(auth_token='$T'), resolve=False) == 'token'
  assert account_mode(Lighter(), resolve=False) == 'private'
  assert account_mode(Lighter(address='$A', public=True), resolve=False) == 'address'
  assert account_mode(Aster(), resolve=False) == 'private'
  assert account_mode(Aster(public=True), resolve=False) == 'public'


def test_resolved_modes_reflect_what_the_client_receives(clean_env: pytest.MonkeyPatch):
  """Missing variables lower the mode; present ones raise it as the client would."""
  assert account_mode(Binance()) == 'public'
  clean_env.setenv('BINANCE_API_KEY', 'k')
  clean_env.setenv('BINANCE_SECRET_KEY', 's')
  assert account_mode(Binance()) == 'private'
  assert account_mode(Kucoin(public=True)) == 'public'
  hl = Hyperliquid(address='$HYPERLIQUID_ADDRESS', public=True)
  assert account_mode(hl) == 'public'
  clean_env.setenv('HYPERLIQUID_ADDRESS', '0xabc')
  assert account_mode(hl) == 'address'
  clean_env.setenv('HYPERLIQUID_PRIVATE_KEY', '0xkey')
  assert account_mode(hl) == 'private'
  assert account_mode(Lighter(account_index=0, public=True)) == 'address'
  lighter = Lighter(address='$LIGHTER_ADDRESS', auth_token='$LIGHTER_AUTH_TOKEN')
  assert account_mode(lighter) == 'public'
  clean_env.setenv('LIGHTER_ADDRESS', '0xabc')
  assert account_mode(lighter) == 'address'
  clean_env.setenv('LIGHTER_AUTH_TOKEN', 'ro:token')
  assert account_mode(lighter) == 'token'
  # typed-lighter prefers an API key over the token (ADR 0040), so the mode does too.
  clean_env.setenv('LIGHTER_API_PRIVATE_KEY', 'key')
  assert account_mode(lighter) == 'private'
  aster = Aster()
  assert account_mode(aster) == 'public'
  clean_env.setenv('ASTER_USER', '0xuser')
  clean_env.setenv('ASTER_SIGNER_PRIVATE_KEY', '0xsigner')
  assert account_mode(aster) == 'private'


def fails(check: Callable[..., None], *args: object, **kwargs: object) -> str:
  """The fixed message a check raises, asserting it leaks no account value."""
  with pytest.raises(AccountCheckError) as error:
    check(*args, **kwargs)
  message = str(error.value)
  assert str(SECRET) not in message and 'SECRET' not in message
  return message


def trade(**update: object) -> Trade:
  """A valid fill, with fields replaced by `update`."""
  values: dict[str, object] = {
    'id': 'SECRET-FILL',
    'price': SECRET,
    'qty': Decimal('-1'),
    'time': END - timedelta(days=1),
    'maker': True,
    'fee': Trade.Fee(amount=Decimal('0.1'), asset='USDT'),
  }
  return Trade(**{**values, **update})  # type: ignore[arg-type]


def test_fees_check():
  """Rebates pass; non-finite, negative taker and whole-notional rates fail."""
  ok = Decimal('0.001')
  rebate = Fees(maker_buy=-ok, maker_sell=Decimal(0), taker_buy=ok, taker_sell=ok)
  reads.check_fees(rebate)
  fails(reads.check_fees, object())
  fails(reads.check_fees, Fees.symmetric(maker=ok, taker=Decimal('-0.001')))
  fails(reads.check_fees, Fees.symmetric(maker=Decimal(1), taker=ok))


def test_open_orders_check():
  """Empty passes; empty IDs, zero quantities and overfills fail."""
  reads.check_open_orders([])
  order = OrderState(
    id='SECRET-ID', price=SECRET, qty=Decimal(2), filled_qty=Decimal(1), active=True
  )
  reads.check_open_orders([order])
  for bad in (
    OrderState(id='', price=SECRET, qty=Decimal(2), filled_qty=Decimal(0), active=True),
    OrderState(
      id='x', price=-SECRET, qty=Decimal(2), filled_qty=Decimal(0), active=True
    ),
    OrderState(
      id='x', price=SECRET, qty=Decimal(0), filled_qty=Decimal(0), active=True
    ),
    OrderState(
      id='x', price=SECRET, qty=Decimal(2), filled_qty=Decimal(-1), active=True
    ),
    OrderState(
      id='x', price=SECRET, qty=Decimal(-2), filled_qty=Decimal(-3), active=True
    ),
  ):
    fails(reads.check_open_orders, [bad])
  fails(reads.check_open_orders, 'SECRET')
  fails(reads.check_open_orders, [SECRET])


def test_trades_check():
  """Window, prices, sides and the rules fee asset are enforced per fill."""
  reads.check_trades([], start=START, end=END, fee_asset='USDT')
  reads.check_trades([trade()], start=START, end=END, fee_asset='USDT')
  reads.check_trades([trade(fee=None)], start=START, end=END, fee_asset='USDT')
  reads.check_trades([trade()], start=START, end=END, fee_asset=None)
  for bad in (
    trade(time=END + timedelta(seconds=1)),
    trade(time=datetime(2026, 10, 1)),
    trade(price=Decimal(0)),
    trade(qty=Decimal(0)),
    trade(maker=1),
    trade(fee=Trade.Fee(amount=Decimal('NaN'), asset='USDT')),
    trade(fee=Trade.Fee(amount=SECRET, asset='')),
    trade(fee=Trade.Fee(amount=SECRET, asset='BNB')),
  ):
    fails(reads.check_trades, [bad], start=START, end=END, fee_asset='USDT')


def test_funding_payments_check():
  """Signed amounts pass inside the window; times outside it fail."""
  inside = FundingPayment(amount=-SECRET, time=END - timedelta(hours=1))
  reads.check_funding_payments([inside], start=START, end=END)
  outside = FundingPayment(amount=SECRET, time=START - timedelta(hours=1))
  fails(reads.check_funding_payments, [outside], start=START, end=END)
  fails(
    reads.check_funding_payments,
    [FundingPayment(amount=Decimal('Infinity'), time=END)],
    start=START,
    end=END,
  )


def test_position_checks():
  """Spot balances are non-negative; perpetual sizes agree and carry entry prices."""
  reads.check_position(Position(size=-SECRET), spot=False)
  fails(reads.check_position, Position(size=-SECRET), spot=True)
  perp = PerpPosition(size=-SECRET, entry_price=SECRET)
  reads.check_perp_position(perp, Position(size=-SECRET))
  reads.check_perp_position(PerpPosition(), Position())
  fails(reads.check_perp_position, perp, Position(size=SECRET))
  fails(reads.check_perp_position, PerpPosition(size=SECRET), Position(size=SECRET))
  fails(reads.check_perp_position, perp, None)


def test_collateral_checks():
  """Free never exceeds equity; margins are ordered and modes known."""
  reads.check_collateral(
    Collateral(equity=SECRET, free_collateral=Decimal(0)), spot=True
  )
  reads.check_collateral(
    Collateral(equity=-SECRET, free_collateral=-SECRET), spot=False
  )
  fails(
    reads.check_collateral,
    Collateral(equity=-SECRET, free_collateral=-SECRET),
    spot=True,
  )
  fails(
    reads.check_collateral,
    Collateral(equity=Decimal(0), free_collateral=SECRET),
    spot=False,
  )

  def perp(**update: object) -> PerpCollateral:
    """A valid cross bucket with fields replaced by `update`."""
    values: dict[str, object] = {
      'equity': SECRET,
      'free_collateral': SECRET / 2,
      'initial_margin': Decimal(2),
      'maintenance_margin': Decimal(1),
      'leverage': Decimal(0),
      'margin_mode': 'cross',
    }
    return PerpCollateral(**{**values, **update})  # type: ignore[arg-type]

  reads.check_perp_collateral(perp())
  for bad in (
    perp(initial_margin=Decimal(-1)),
    perp(maintenance_margin=Decimal(3)),
    perp(leverage=Decimal(-1)),
    perp(margin_mode='portfolio'),
    perp(free_collateral=SECRET * 2),
  ):
    fails(reads.check_perp_collateral, bad)
  fails(reads.check_perp_collateral, Collateral(equity=SECRET, free_collateral=SECRET))


def test_leverage_and_available_notional_checks():
  """Leverage is positive; opening capacity is non-negative and may be capped."""
  reads.check_leverage(Decimal(5))
  for bad in (Decimal(0), Decimal('NaN'), 5):
    fails(reads.check_leverage, bad)
  reads.check_available_notional(Decimal(0))
  fails(reads.check_available_notional, -SECRET)


def test_trades_check_uses_the_collected_rules():
  """The dispatcher requires a rules read before judging fill fee assets."""
  result = AccountResults(spot=True, start=START, end=END)
  result.values['trades_history'] = [trade()]
  fails(reads.check, 'trades_history', result)
  result.values['rules'] = Rules(
    fee_asset='USDT', tick_size=Decimal(1), step_size=Decimal(1), api=True
  )
  reads.check('trades_history', result)


def test_exclusion_policy_order():
  """Static, perpetual-only, support, mode and Bitget Classic exclusions apply in order."""
  from sdk_dev.repo import repo_root
  from sdk_dev.support import load_impl_files

  impls = load_impl_files(repo_root() / 'packages/impl')

  def code(
    venue: str,
    exchange: str,
    method: str,
    mode: AccountMode = 'private',
    uta: bool | None = None,
  ) -> str | None:
    """The exclusion for one read."""
    return reads.account_exclusion(
      impls[venue],
      venue=venue,
      exchange_id=exchange,
      method=method,
      mode=mode,
      bitget_uta=uta,
    )

  assert code('lighter', 'perp', 'query_order') == 'order_lifecycle'
  assert code('lighter', 'spot', 'leverage') == 'perp_only'
  assert code('bit2me', 'spot', 'fees') == 'unsupported'
  assert code('mexc', 'perp', 'open_orders') == 'unsupported'
  assert code('lighter', 'perp', 'open_orders', 'address') == 'credential_mode'
  assert code('lighter', 'perp', 'position', 'address') is None
  assert code('aster', 'perp', 'fees', 'public') == 'credential_mode'
  assert code('bitget', 'usdt', 'perp_collateral', uta=False) == 'bitget_classic'
  assert code('bitget', 'usdt', 'perp_collateral', uta=True) is None
  assert code('bitget', 'usdt', 'perp_collateral', uta=None) is None
