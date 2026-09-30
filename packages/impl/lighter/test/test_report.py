"""Snapshot mappings, checked against figures observed on mainnet accounts."""

from decimal import Decimal
from typing_extensions import Any, cast

import pytest
from typed_lighter.api.account.get import DetailedAccount

from tribulnation.lighter.report import (
  Report,
  account_snapshots,
  holdings,
  pool_claim,
  positions,
)
from tribulnation.sdk import ReportSDK
from tribulnation.sdk.impl.accounts import Lighter

LLP = 281474976710654


def asset(asset_id: int, **fields: Any) -> dict[str, Any]:
  """An account asset row."""
  row: dict[str, Any] = {
    'asset_id': asset_id,
    'symbol': str(asset_id),
    'balance': Decimal(0),
    'locked_balance': Decimal(0),
    'margin_mode': 'disabled',
    'margin_balance': Decimal(0),
  }
  row.update(fields)
  return row


def position(market_id: int, **fields: Any) -> dict[str, Any]:
  """A position row, flat and cross by default."""
  row: dict[str, Any] = {
    'market_id': market_id,
    'sign': 1,
    'position': Decimal(0),
    'avg_entry_price': Decimal(0),
    'unrealized_pnl': Decimal(0),
    'margin_mode': 0,
    'allocated_margin': Decimal(0),
  }
  row.update(fields)
  return row


def account(index: int, **fields: Any) -> DetailedAccount:
  """An account with the fields the snapshot reads."""
  row: dict[str, Any] = {
    'index': index,
    'assets': [],
    'positions': [],
    'shares': [],
    'pending_unlocks': [],
    'total_asset_value': Decimal(0),
  }
  row.update(fields)
  return cast(DetailedAccount, row)


UNIFIED_ISOLATED_SHORT = account(
  750345,
  assets=[
    asset(3, margin_mode='enabled', margin_balance=Decimal('103.570192359332')),
  ],
  positions=[
    position(
      215,
      sign=-1,
      position=Decimal('238.00'),
      avg_entry_price=Decimal('2.4250'),
      unrealized_pnl=Decimal('-20.632481'),
      margin_mode=1,
      allocated_margin=Decimal('392.908701'),
    ),
    position(1),
  ],
  total_asset_value=Decimal('475.84641100000005'),
)


def test_unified_balance_is_collateral_plus_isolated_margin():
  """USDC is cross collateral plus the isolated position's allocated margin; adding the
  position's unrealized PnL gives back the venue's `total_asset_value`."""
  balances = holdings(UNIFIED_ISOLATED_SHORT)
  assert balances == {'3': Decimal('496.478893359332')}
  assert balances['3'] + Decimal('-20.632481') == pytest.approx(
    UNIFIED_ISOLATED_SHORT['total_asset_value'], abs=Decimal('1e-5')
  )


def test_positions_are_signed_and_skip_flat_markets():
  """`position` is unsigned beside `sign`; markets traded before but flat are dropped."""
  assert {
    k: (p.size, p.avg_price) for k, p in positions(UNIFIED_ISOLATED_SHORT).items()
  } == {'215': (Decimal('-238.00'), Decimal('2.4250'))}


def test_classic_account_sums_spot_and_margin_balances():
  """Classic accounts keep spot USDC in `balance`, perps collateral in `margin_balance`."""
  classic = account(
    1000,
    assets=[
      asset(3, balance=Decimal('0.007751'), margin_balance=Decimal('0.608697623179')),
      asset(1, balance=Decimal('0.00070000')),
      asset(2),
    ],
  )
  assert holdings(classic) == {
    '3': Decimal('0.616448623179'),
    '1': Decimal('0.00070000'),
  }


def test_locked_balance_is_not_added_twice():
  """`balance` already includes the part locked by resting orders."""
  acct = account(
    1053,
    assets=[
      asset(2, balance=Decimal('4699.36744248'), locked_balance=Decimal('4699.36'))
    ],
  )
  assert holdings(acct) == {'2': Decimal('4699.36744248')}


def test_llp_claim_adds_non_usdc_balances_to_usdc_equity():
  """The LLP's `total_asset_value` omits its ETH and XAUT, which the holder owns pro rata."""
  pool = account(
    LLP,
    assets=[
      asset(1, margin_mode='enabled', margin_balance=Decimal('366')),
      asset(3, margin_mode='enabled', margin_balance=Decimal('78956844.533769')),
      asset(11, margin_balance=Decimal('249')),
    ],
    total_asset_value=Decimal('79116465.78'),
    pool_info={'total_shares': 22575570344},
  )
  claim = pool_claim(pool, 22575570344 // 1000)
  assert claim['3'] == pytest.approx(Decimal('79116.46578'), rel=Decimal('1e-6'))
  assert claim['1'] == pytest.approx(Decimal('0.366'), rel=Decimal('1e-6'))
  assert claim['11'] == pytest.approx(Decimal('0.249'), rel=Decimal('1e-6'))


def test_staking_claim_is_pro_rata_lit():
  """The LIT staking pool holds spot LIT and reports no USDC value."""
  pool = account(
    281474976624800,
    assets=[asset(2, balance=Decimal('109749691.87307596'))],
    pool_info={'total_shares': 10471373514473},
  )
  claim = pool_claim(pool, 1778075477)
  assert set(claim) == {'2'}
  assert claim['2'] == pytest.approx(Decimal('18635.88'), abs=Decimal('0.01'))


def test_claim_on_a_non_pool_account_fails():
  """A share must point at a pool account."""
  with pytest.raises(ValueError):
    pool_claim(account(1), 1)


def test_operated_pool_counts_only_the_operator_shares():
  """An operated pool is listed under the operator's address, but only the operator's
  shares, which no account's `shares` lists, belong to it."""
  pool = account(
    281474976694250,
    assets=[asset(3, margin_balance=Decimal('900'))],
    positions=[position(1, position=Decimal('2'), avg_entry_price=Decimal('100'))],
    total_asset_value=Decimal('1000'),
    pool_info={'total_shares': 200, 'operator_shares': 10},
  )
  states = account_snapshots(pool, {})
  assert [(s.subaccount, s.balances, s.positions) for s in states] == [
    ('281474976694250:operator', {'3': Decimal('50')}, {})
  ]


def test_accounts_split_into_trading_pool_and_unlocking_compartments():
  """Each account is `<index>`, each pool it holds `<index>:pool:<pool>`, and LIT in its
  unstaking lockup `<index>:unlocking`."""
  holder = account(
    1060,
    assets=[asset(3, margin_balance=Decimal('1'))],
    shares=[{'public_pool_index': LLP, 'shares_amount': 10}],
    pending_unlocks=[
      {'asset_index': 2, 'amount': Decimal('5')},
      {'asset_index': 2, 'amount': Decimal('7')},
    ],
  )
  pool = account(LLP, total_asset_value=Decimal('100'), pool_info={'total_shares': 100})
  states = account_snapshots(holder, {LLP: pool})
  assert [(s.subaccount, s.balances) for s in states] == [
    ('1060', {'3': Decimal('1')}),
    (f'1060:pool:{LLP}', {'3': Decimal('10')}),
    ('1060:unlocking', {'2': Decimal('12')}),
  ]


async def test_owner_index_resolves_its_l1_address(monkeypatch: pytest.MonkeyPatch):
  """Given an account index, the report looks up its owner's address first."""
  looked_up: list[int] = []

  async def fake_account(self: Report, index: int) -> DetailedAccount:
    looked_up.append(index)
    return account(index, l1_address='0xabc')

  monkeypatch.setattr(Report, 'account', fake_account)
  assert await Report.new(750345).address() == '0xabc'
  assert await Report.new('0xdef').address() == '0xdef'
  assert looked_up == [750345]


def test_router_prefers_the_address_and_falls_back_to_the_index(
  monkeypatch: pytest.MonkeyPatch,
):
  """`ReportSDK` uses a configured address, else the market config's account index."""
  monkeypatch.delenv('LIGHTER_ADDRESS', raising=False)
  sdk = ReportSDK(
    accounts={
      'both': Lighter(address='0xabc', account_index=476, public=True),
      'index': Lighter(account_index=476, public=True),
      'neither': Lighter(public=True),
    }
  )
  for id, owner in (('both', '0xabc'), ('index', 476)):
    report = sdk.venue(id)
    assert isinstance(report, Report) and report.owner == owner
  with pytest.raises(ValueError):
    sdk.venue('neither')
