"""Reporting model validation tests."""

from decimal import Decimal

from tribulnation.sdk import reporting
from tribulnation.sdk.reporting import (
  Bonus,
  Funding,
  FutureOrder,
  FuturePositionSummary,
  FutureTrade,
  RealizedPnl,
  Record,
  Transfer,
)


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


def test_future_position_summary_validates_through_record_union():
  record = Record.model_validate({
    'observations': [
      {
        'type': 'future_trade',
        'id': 'fill-1',
        'time': '2025-07-26T14:15:59Z',
        'instrument': 'BTCUSDT',
        'settle': 'USDT',
        'position_id': 'position-1',
        'size': '-0.0004',
        'price': '117825.8',
      },
      {
        'type': 'future_position_summary',
        'id': 'position-row-1',
        'time': '2025-07-26T14:15:59Z',
        'position_id': 'position-1',
        'instrument': 'BTCUSDT',
        'settle': 'USDT',
        'position_side': 'long',
        'opened_at': '2025-07-19T14:15:58Z',
        'closed_at': '2025-07-26T14:15:59Z',
        'opened_size': '0.0004',
        'closed_size': '0.0004',
        'closed_value': '47.13032',
        'avg_entry_price': '118151.9',
        'avg_close_price': '117825.8',
        'realized_pnl': '-0.13044',
        'funding': '-0.09720019016',
        'total_fee': '0.056634648',
        'opening_fee': '0.028356456',
        'closing_fee': '0.028278192',
        'position_pnl': '-0.28427483816',
      },
    ],
    'provenance': {'source': 'manual', 'label': 'bitget'},
  })

  trade = record.observations[0]
  summary = record.observations[1]
  assert isinstance(trade, FutureTrade)
  assert trade.position_id == 'position-1'
  assert isinstance(summary, FuturePositionSummary)
  assert summary.position_id == 'position-1'
  assert summary.total_fee == Decimal('0.056634648')
  assert summary.funding == Decimal('-0.09720019016')


def test_futures_scoped_position_id_fields_validate_and_export():
  assert reporting.FuturePositionSummary is FuturePositionSummary
  assert 'FuturePositionSummary' in reporting.__all__

  record = Record.model_validate({
    'observations': [
      {
        'type': 'future_order',
        'id': 'order-row-1',
        'position_id': 'position-1',
        'instrument': 'BTCUSDT',
      },
      {
        'type': 'realized_pnl',
        'id': 'pnl-row-1',
        'position_id': 'position-1',
        'instrument': 'BTCUSDT',
        'settle': 'USDT',
        'amount': '-0.13044',
      },
      {
        'type': 'funding',
        'id': 'funding-row-1',
        'position_id': 'position-1',
        'instrument': 'BTCUSDT',
        'settle': 'USDT',
        'asset': 'USDT',
        'amount': '-0.09720019016',
      },
    ],
    'provenance': {'source': 'manual', 'label': 'bitget'},
  })

  order = record.observations[0]
  pnl = record.observations[1]
  funding = record.observations[2]
  assert isinstance(order, FutureOrder)
  assert order.position_id == 'position-1'
  assert isinstance(pnl, RealizedPnl)
  assert pnl.position_id == 'position-1'
  assert isinstance(funding, Funding)
  assert funding.position_id == 'position-1'
