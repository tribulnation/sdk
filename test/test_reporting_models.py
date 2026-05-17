"""Reporting model validation tests."""

from decimal import Decimal

from tribulnation.sdk.reporting import Bonus, Record, Transfer


def test_transfer_observation_validates_through_record_union():
  record = Record.model_validate({
    'observations': [{
      'type': 'transfer',
      'id': 'funds-sent-1',
      'asset': 'USDC',
      'amount': '-12.50',
      'src_account': 'funding',
      'fee': {'asset': 'USDC', 'amount': '0.10'},
    }],
    'provenance': {'source': 'manual', 'label': 'mexc'},
  })

  transfer = record.observations[0]
  assert isinstance(transfer, Transfer)
  assert transfer.amount == Decimal('-12.50')
  assert transfer.src_account == 'funding'
  assert transfer.dst_account is None
  assert transfer.fee is not None
  assert transfer.fee.amount == Decimal('0.10')


def test_bonus_observation_validates_through_record_union():
  record = Record.model_validate({
    'observations': [{
      'type': 'bonus',
      'id': 'grant-1',
      'asset': 'USDT',
      'amount': '-5',
      'category': 'user_grants_recycle',
    }],
    'provenance': {'source': 'manual', 'label': 'bitget'},
  })

  bonus = record.observations[0]
  assert isinstance(bonus, Bonus)
  assert bonus.amount == Decimal('-5')
  assert bonus.category == 'user_grants_recycle'
