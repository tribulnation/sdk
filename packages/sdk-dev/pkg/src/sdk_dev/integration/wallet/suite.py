"""Live conformance tests for wallet implementations."""

import pytest

from .support import WalletResult


def test_deposit_methods_can_be_fetched(wallet_result: WalletResult):
  """Fetch deposit methods without an implementation or transport error."""
  if wallet_result.deposit_failure is not None:
    pytest.fail(wallet_result.deposit_failure, pytrace=False)


def test_deposit_methods_not_empty(wallet_result: WalletResult):
  """Return at least one deposit method."""
  if wallet_result.deposit_failure is not None:
    pytest.skip('Deposit-method fetch test failed for this account')
  assert wallet_result.deposit_methods, 'No deposit methods found'


def test_withdrawal_methods_can_be_fetched(wallet_result: WalletResult):
  """Fetch withdrawal methods without an implementation or transport error."""
  if wallet_result.withdrawal_failure is not None:
    pytest.fail(wallet_result.withdrawal_failure, pytrace=False)


def test_withdrawal_methods_not_empty(wallet_result: WalletResult):
  """Return at least one withdrawal method."""
  if wallet_result.withdrawal_failure is not None:
    pytest.skip('Withdrawal-method fetch test failed for this account')
  assert wallet_result.withdrawal_methods, 'No withdrawal methods found'
