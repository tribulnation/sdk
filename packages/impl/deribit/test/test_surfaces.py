"""Deterministic reporting, discovery and public-metadata regressions for Deribit."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing_extensions import cast

import pytest
from typed_deribit import Deribit
from typed_deribit.account.get_transaction_log import TransactionLogEntry
from typed_deribit.schemas import Position as RawPosition
from tribulnation.deribit import Earn, Report, Wallet
from tribulnation.deribit.report import parse_entry, parse_position
from tribulnation.sdk.reporting import CryptoWithdrawal, UnknownObservation

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def entry(
  *, kind: str = 'settlement', id: int = 1, account: int = 10, currency: str = 'BTC'
) -> TransactionLogEntry:
  """A synthetic ledger row with a known signed cash change."""
  return {
    'id': id,
    'user_id': account,
    'user_seq': id,
    'type': kind,
    'currency': currency,
    'timestamp': NOW,
    'change': -0.25,
  }


@pytest.mark.parametrize(
  'kind', ['trade', 'settlement', 'delivery', 'options_settlement_summary', 'new_type']
)
def test_ambiguous_economics_are_not_guessed(kind: str):
  """Mixed settlements and option premiums are not labelled funding/futures trades."""
  observation = parse_entry(entry(kind=kind)).observations[0]
  assert isinstance(observation, UnknownObservation)
  assert observation.amount == Decimal('-0.25')
  assert observation.subaccount == '10'


def test_cash_withdrawal_keeps_the_native_id_and_sign():
  """Ordinary cash movements retain a useful structured observation."""
  observation = parse_entry(entry(kind='withdrawal')).observations[0]
  assert isinstance(observation, CryptoWithdrawal)
  assert observation.balance_change == Decimal('-0.25')


@pytest.mark.parametrize('quantity', [2.0, -2.0])
def test_short_positions_are_signed_once(quantity: float):
  """The direction field determines exposure even if the quantity is already signed."""
  row = cast(
    RawPosition,
    {
      'kind': 'future',
      'direction': 'sell',
      'size_currency': quantity,
      'size': 200,
      'average_price': 100,
    },
  )
  assert parse_position(row).size == -2


def test_future_without_base_units_is_not_misreported_as_coins():
  """USD contract quantities cannot be substituted for a missing base-unit size."""
  with pytest.raises(ValueError, match='base-unit'):
    parse_position(cast(RawPosition, {'kind': 'future', 'size': 200}))


async def test_history_discovers_currencies_subaccounts_and_walks_cursors(
  monkeypatch: pytest.MonkeyPatch,
):
  """No four-currency list, first-page truncation or duplicate boundary rows."""
  pause = AsyncMock()
  monkeypatch.setattr('tribulnation.deribit.report.sleep', pause)
  log = AsyncMock(
    side_effect=[
      {'logs': [entry()], 'continuation': 9},
      {'logs': [entry(), entry(id=2)], 'continuation': None},
      {'logs': [entry(currency='USDE')], 'continuation': None},
      {'logs': [entry(account=11)], 'continuation': None},
      {'logs': [], 'continuation': None},
    ]
  )
  client = cast(
    Deribit,
    SimpleNamespace(
      market_data=SimpleNamespace(
        get_currencies=AsyncMock(
          return_value=[{'currency': 'BTC'}, {'currency': 'USDE'}]
        )
      ),
      account=SimpleNamespace(
        get_subaccounts=AsyncMock(return_value=[{'id': 10}, {'id': 11}]),
        get_transaction_log=log,
      ),
    ),
  )
  rows = [row async for row in Report(client=client).history(end=NOW)]
  assert len(rows) == 4
  assert len({row.provenance['id'] for row in rows}) == 4
  assert log.await_count == 5
  assert pause.await_count == 4
  assert log.await_args_list[0].kwargs['start_timestamp'] == NOW - timedelta(days=30)
  assert log.await_args_list[1].kwargs['continuation'] == 9
  assert {call.kwargs['currency'] for call in log.await_args_list} == {'BTC', 'USDE'}
  assert {call.kwargs['subaccount_id'] for call in log.await_args_list} == {10, 11}


async def test_snapshot_uses_cash_not_equity_and_keeps_compartments():
  """Equity containing position PnL is not presented as a native cash balance."""
  client = cast(
    Deribit,
    SimpleNamespace(
      account=SimpleNamespace(
        get_subaccounts=AsyncMock(return_value=[{'id': 10}, {'id': 11}]),
        get_account_summaries=AsyncMock(
          return_value={'summaries': [{'currency': 'BTC', 'balance': 2, 'equity': 99}]}
        ),
        get_positions=AsyncMock(return_value=[]),
      )
    ),
  )
  result = await Report(client=client).snapshot()
  assert result.snapshot.balances == {'BTC': 4}
  assert [state.subaccount for state in result.snapshot.subaccounts] == ['10', '11']


async def test_public_wallet_and_reward_discovery():
  """Filter live-discovered reward currencies and networks without fixed asset lists."""
  client = cast(
    Deribit,
    SimpleNamespace(
      market_data=SimpleNamespace(
        get_currencies=AsyncMock(
          return_value=[
            {
              'currency': 'NEW',
              'coin_type': 'native',
              'min_confirmations': 3,
              'withdrawal_fee': 0.2,
              'apr': 4,
              'coinbase_networks': [
                {'display_name': 'network-a'},
                {'display_name': 'network-b'},
              ],
            }
          ]
        ),
      )
    ),
  )
  deposits = await Wallet(client=client).deposit_methods(assets=['NEW'])
  assert [row.network for row in deposits] == ['network-a', 'network-b']
  withdrawals = await Wallet(client=client).withdrawal_methods(networks=['network-b'])
  assert len(withdrawals) == 1 and withdrawals[0].fee is not None
  assert withdrawals[0].fee.amount == Decimal('0.2')
  rewards = await Earn(client=client).instruments()
  assert len(rewards) == 1 and rewards[0].apr == Decimal('0.04')
  assert await Earn(client=client).instruments(tags=[]) == []
