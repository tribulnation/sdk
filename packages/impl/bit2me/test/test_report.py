"""Regression tests for defects found mapping the Bit2Me wallet-transaction history."""

from datetime import datetime, timezone
from decimal import Decimal

from typed_bit2me.v3.wallet.transactions import WalletTransaction

from tribulnation.bit2me.report.history.transactions import (
  parse_deposit,
  parse_withdrawal,
)

TIME = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

DEPOSIT: WalletTransaction = {
  'id': 'tx-1',
  'date': TIME,
  'status': 'completed',
  'origin': {'class': 'blockchain', 'currency': 'USDC'},
  'destination': {
    'class': 'pocket',
    'currency': 'USDC',
    'amount': Decimal('100'),
    'address': '0xpocket',
    'addressNetwork': 'binanceSmartChain',
  },
}

WITHDRAWAL: WalletTransaction = {
  'id': 'tx-2',
  'date': TIME,
  'status': 'completed',
  'origin': {'class': 'pocket', 'currency': 'USDC', 'amount': Decimal('50')},
  'destination': {
    'class': 'blockchain',
    'address': '0xdest',
    'addressNetwork': 'ethereum',
  },
}


def test_a_deposit_reads_its_network_off_the_destination():
  """Only the *pocket* side of a transfer carries `address`/`addressNetwork`.

  It is the pocket side in both directions, so a deposit's network has to be read off
  the destination -- reading it off the on-chain `origin`, which is the obvious side,
  returns `None` for every deposit this account has ever received. Confirmed against
  every `receive`/`send` row in 2025 and 2026.
  """
  observation = parse_deposit(DEPOSIT)
  assert observation is not None
  assert observation.network == 'binanceSmartChain'


def test_a_cancelled_withdrawal_is_dropped():
  """Cancelled withdrawals stay in the listing carrying the amount they would have sent.

  Reporting them credits the account with a transfer that never happened.
  """
  assert parse_withdrawal({**WITHDRAWAL, 'status': 'cancelled'}) is None
