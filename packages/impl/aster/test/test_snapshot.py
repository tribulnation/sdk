"""Snapshot mappings from the signed perp and spot wallets and the Aster Chain summary."""

from decimal import Decimal
from typing_extensions import cast

from typed_aster.chain.rpc.get_balance import ChainStakingSummary
from typed_aster.futures.account.balance import FuturesBalance
from typed_aster.futures.position.risk import PositionRisk
from typed_aster.schemas import AccountInfo

from tribulnation.aster.report import perp_state, spot_state, staking_state


def risk(symbol: str, amount: str, entry: str, side: str = 'BOTH') -> PositionRisk:
  """A position row with the fields the snapshot reads."""
  return cast(
    PositionRisk,
    {
      'symbol': symbol,
      'positionAmt': Decimal(amount),
      'entryPrice': Decimal(entry),
      'positionSide': side,
    },
  )


def balance(asset: str, amount: str) -> FuturesBalance:
  """A futures wallet row."""
  return cast(FuturesBalance, {'asset': asset, 'balance': Decimal(amount)})


def test_perp_keeps_negative_wallets_and_skips_flat_symbols():
  """Fees charged in USDT leave a negative wallet beside USDC collateral; flat symbols,
  which `position.risk` lists too, are dropped."""
  state = perp_state(
    [balance('USDC', '399.9'), balance('USDT', '-2.76679574'), balance('BTC', '0')],
    [risk('FOLKSUSDT', '241.3', '2.4204'), risk('BTCUSDT', '0', '0')],
  )
  assert state.subaccount == 'perp'
  assert state.balances == {'USDC': Decimal('399.9'), 'USDT': Decimal('-2.76679574')}
  assert {s: (p.size, p.avg_price) for s, p in state.positions.items()} == {
    'FOLKSUSDT': (Decimal('241.3'), Decimal('2.4204'))
  }


def test_hedge_mode_legs_merge_into_one_position():
  """A `LONG` and a `SHORT` leg on one symbol net out, weighted by size."""
  state = perp_state(
    [],
    [
      risk('ETHUSDT', '3', '2000', 'LONG'),
      risk('ETHUSDT', '-1', '2100', 'SHORT'),
    ],
  )
  position = state.positions['ETHUSDT']
  assert position.size == Decimal('2')
  assert position.avg_price == Decimal('1950')


def test_spot_adds_locked_to_free():
  """Resting orders lock part of a balance, which is still held."""
  info = cast(
    AccountInfo,
    {
      'balances': [
        {'asset': 'ASTER', 'free': Decimal('10'), 'locked': Decimal('5')},
        {'asset': 'USDT', 'free': Decimal('0'), 'locked': Decimal('0')},
      ]
    },
  )
  state = spot_state(info)
  assert (state.subaccount, state.balances) == ('spot', {'ASTER': Decimal('15')})


def test_staking_sums_every_owned_state_and_rewards():
  """Active, pending and unstaking ASTER are all owned; claimable rewards too."""
  state = staking_state(
    {
      'totalStakedAmount': Decimal('100'),
      'totalPendingStakeAmount': Decimal('5'),
      'totalPendingUnstakeAmount': Decimal('20'),
      'totalUnclaimedRewards': [{'asset': 'ASTER', 'amount': Decimal('1.5')}],
    }
  )
  assert (state.subaccount, state.balances) == ('staking', {'ASTER': Decimal('126.5')})


def test_staking_nulls_mean_nothing_staked():
  """The summary reports `null` for zero amounts, as the test account showed."""
  empty = {
    'totalStakedAmount': None,
    'totalUnclaimedRewards': None,
    'totalPendingStakeAmount': None,
    'totalPendingUnstakeAmount': None,
  }
  assert staking_state(cast(ChainStakingSummary, empty)).balances == {}
  assert staking_state(None).balances == {}
