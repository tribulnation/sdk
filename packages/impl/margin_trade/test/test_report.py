"""Snapshot and history mapping, from rows the venue sent (testnet and mainnet)."""

from datetime import datetime, timezone
from decimal import Decimal

from typed_margin_trade.schemas import ClearinghouseState, Fill, MarginSummary
from typed_margin_trade.user.get_transfer_history import TransferHistoryItem
from tribulnation.margin_trade.report import (
  fill_observation,
  funding_observation,
  perp_state,
  transfer_observation,
)
from tribulnation.sdk.reporting import (
  Bonus,
  CryptoWithdrawal,
  FutureTrade,
  InternalTransfer,
  SpotTrade,
)

T = datetime(2026, 10, 21, 15, 26, 37, tzinfo=timezone.utc)


def fill(**changes: object) -> Fill:
  """A testnet closing BTC fill, with `changes` applied."""
  row: Fill = {
    'coin': 'BTC',
    'px': Decimal('84547.3'),
    'sz': Decimal('0.001'),
    'side': 'A',
    'time': T,
    'startPosition': Decimal('0'),
    'dir': 'Close Long',
    'closedPnl': Decimal('-0.025554'),
    'oid': 38549396356,
    'tid': 8996319250,
    'crossed': True,
    'isTaker': True,
    'fee': Decimal('0.008454'),
    'feeToken': 'USD',
  }
  return {**row, **changes}  # type: ignore[return-value]


def transfer(**changes: object) -> TransferHistoryItem:
  """A testnet transfer-history row, with `changes` applied."""
  row: TransferHistoryItem = {
    'from': '6dm8b7h4rPVuYTDzeo9uZQNRhKagAYBPBniCHiY7Dggx',
    'type': 'transfer',
    'status': 'Completed',
    'amount': Decimal('20'),
    'amountChange': Decimal('20'),
    'fee': Decimal('0'),
    'asset': 'USDC',
    'venue': 'spot',
    'to': '6dm8b7h4rPVuYTDzeo9uZQNRhKagAYBPBniCHiY7Dggx',
    'createdTime': T,
    'updatedTime': T,
  }
  return {**row, **changes}  # type: ignore[return-value]


def test_perp_fill_realized_pnl_excludes_the_fee():
  """`closedPnl` is net of the fee: (84547.3 - 84564.4) * 0.001 = -0.0171."""
  obs = fill_observation(fill())
  assert isinstance(obs, FutureTrade)
  assert obs.realized_pnl == Decimal('-0.017100')
  assert obs.size == Decimal('-0.001') and obs.instrument == 'BTC'
  assert obs.fee is not None and obs.fee.asset == 'USD'


def test_opening_fill_realizes_nothing():
  """An opening fill's `closedPnl` is exactly `-fee`."""
  obs = fill_observation(
    fill(
      side='B', dir='Open Long', closedPnl=Decimal('-0.008456'), fee=Decimal('0.008456')
    )
  )
  assert isinstance(obs, FutureTrade) and obs.realized_pnl == 0


def test_spot_fill():
  """A mainnet PRL/USDC maker sell, with its rebate."""
  obs = fill_observation(
    fill(
      coin='PRL/USDC',
      px=Decimal('3.0847'),
      sz=Decimal('7.05'),
      isTaker=False,
      fee=Decimal('-0.010874'),
      feeToken='USDC',
    )
  )
  assert isinstance(obs, SpotTrade)
  assert (obs.base, obs.quote, obs.size) == ('PRL', 'USDC', Decimal('-7.05'))
  assert obs.fee is not None and obs.fee.amount == Decimal('-0.010874')


def test_funding_is_received_positive():
  """A mainnet long XAU paying a positive rate."""
  obs = funding_observation(
    {
      'delta': {
        'type': 'funding',
        'coin': 'XAU',
        'fundingRate': Decimal('0.000042'),
        'szi': Decimal('0.03'),
        'usdc': Decimal('-0.005194'),
      },
      'hash': '90639e39-4371-4a6e-b647-710158199a3c',
      'time': T,
    }
  )
  assert obs.amount == Decimal('-0.005194') and obs.asset == 'USDC'
  assert obs.instrument == 'XAU'


def test_transfer_rows():
  """Perp/spot transfers, withdrawals (fee inside the debit) and faucet credits."""
  moved = transfer_observation(transfer())
  assert isinstance(moved, InternalTransfer)
  assert (moved.src_account, moved.dst_account) == ('perp', 'spot')
  withdrawn = transfer_observation(
    transfer(
      type='withdrawal',
      amount=Decimal('2'),
      amountChange=Decimal('-2'),
      fee=Decimal('1'),
      chain='solana',
      txHash='38X3GFN1',
    )
  )
  assert isinstance(withdrawn, CryptoWithdrawal)
  assert withdrawn.amount == Decimal('-2') and withdrawn.network == 'solana'
  assert withdrawn.fee is not None and withdrawn.fee.amount == Decimal('1')
  faucet = transfer_observation(
    transfer(
      type='deposit',
      venue='perp',
      amount=Decimal('100000'),
      amountChange=Decimal('100000'),
      txHash='faucet:6dm8b7h4rPVuYTDzeo9uZQNRhKagAYBPBniCHiY7Dggx:1792454400000',
      **{'from': ''},
    )
  )
  assert isinstance(faucet, Bonus) and faucet.category == 'faucet'


def test_perp_balance_excludes_unrealized_pnl():
  """`accountValue` 99998.027991 with a -0.0046 position leaves 99998.032591 cash."""
  summary: MarginSummary = {
    'accountValue': Decimal('99998.027991'),
    'totalMarginUsed': Decimal('84.5717'),
    'totalNtlPos': Decimal('84.5717'),
    'totalRawUsd': Decimal('99998.027991'),
  }
  state: ClearinghouseState = {
    'assetPositions': [
      {
        'type': 'oneWay',
        'position': {
          'coin': 'BTC',
          'szi': Decimal('0.001'),
          'entryPx': Decimal('84576.3'),
          'positionValue': Decimal('84.5717'),
          'unrealizedPnl': Decimal('-0.0046'),
          'returnOnEquity': Decimal('0'),
          'liquidationPx': None,
          'marginUsed': Decimal('84.5717'),
          'maxLeverage': 20,
          'leverage': {'type': 'cross', 'value': 1},
          'cumFunding': {
            'allTime': Decimal('0'),
            'sinceChange': Decimal('0'),
            'sinceOpen': Decimal('0'),
          },
        },
      }
    ],
    'crossMarginSummary': summary,
    'marginSummary': summary,
    'crossMaintenanceMarginUsed': Decimal('2.11'),
    'withdrawable': Decimal('99913'),
    'time': T,
  }
  sub = perp_state(state)
  assert sub.balances == {'USDC': Decimal('99998.032591')}
  assert sub.positions['BTC'].size == Decimal('0.001')
