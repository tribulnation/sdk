"""Unit tests for the Kraken wallet parsers, over `WithdrawMethods` rows recorded from
the live venue on 2026-09-08."""

from decimal import Decimal

from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod
from tribulnation.kraken.wallet.withdrawal_methods import parse_method

from typed_kraken.spot.funding.withdraw_methods import (
  WithdrawalMethod as KrakenWithdrawalMethod,
)

BITCOIN: KrakenWithdrawalMethod = {
  'asset': 'XXBT',
  'method': 'Bitcoin',
  'method_id': 'ee9d686d-aeb6-4e61-9d83-448e3a7511f3',
  'network': 'Bitcoin',
  'network_id': 'ee9d686d-aeb6-4e61-9d83-448e3a7511f3',
  'minimum': Decimal('0.0002'),
  'fee': {'aclass': 'currency', 'asset': 'XXBT', 'fee': Decimal('0.00001500')},
}

SWIFT: KrakenWithdrawalMethod = {
  'asset': 'ZUSD',
  'method': 'Bank Frick (SWIFT) Europe',
  'method_id': '6beeb907-ad8f-4338-9cb7-6995d1083446',
  'network_id': 'aaf24277-654a-42f4-bb59-5847806a8376',
  'minimum': Decimal('100.00'),
  'fee': {'aclass': 'currency', 'asset': 'ZUSD', 'fee': Decimal('14.00')},
}


def test_network_is_the_display_name_and_fee_is_flat():
  """Crypto rows carry `network`; the fee is a flat amount in the row's fee asset."""
  assert parse_method(BITCOIN) == WithdrawalMethod(
    asset='XXBT',
    network='Bitcoin',
    fee=WithdrawalMethod.Fee(asset='XXBT', amount=Decimal('0.00001500')),
  )


def test_a_fiat_rail_falls_back_to_the_method_name():
  """Fiat rows name no `network`; the bank rail under `method` is the way out."""
  method = parse_method(SWIFT)
  assert method is not None and method.network == 'Bank Frick (SWIFT) Europe'
  assert method.fee == WithdrawalMethod.Fee(asset='ZUSD', amount=Decimal('14.00'))


def test_a_row_naming_no_asset_is_skipped():
  """`asset` is optional on the declaration; a row without one cannot be placed."""
  assert parse_method({'fee': {'fee': Decimal(0)}}) is None
