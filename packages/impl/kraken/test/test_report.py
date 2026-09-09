"""Unit tests for the Kraken ledger mapping, over `Ledgers` rows recorded from the live
venue on 2026-09-08."""

from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.reporting import (
  CryptoDeposit,
  FeeLeg,
  FiatDeposit,
  TradeLeg,
  UnknownObservation,
  Yield,
)
from tribulnation.kraken.report.history import parse_entry

from typed_kraken.spot.account.ledgers import LedgerEntry

TIME = datetime(2026, 8, 27, 14, 6, 15, 177869, tzinfo=timezone.utc)

QUOTE_LEG: LedgerEntry = {
  'refid': 'TSOH55-6XU77-SD3WPY',
  'time': TIME,
  'type': 'trade',
  'subtype': 'tradespot',
  'aclass': 'currency',
  'asset': 'USDC',
  'amount': Decimal('-4.78482000'),
  'fee': Decimal('0.03828000'),
  'balance': '5.17690000',
}

STAKING: LedgerEntry = {
  'refid': 'ELJUMND-AVQ6D-MBVJTJ',
  'time': TIME,
  'type': 'staking',
  'subtype': '',
  'asset': 'XXBT',
  'amount': Decimal('1.1E-9'),
  'fee': Decimal('0E-10'),
}

DEPOSIT: LedgerEntry = {
  'refid': 'FTCmumN-faghQBkeUHreU4KCzDhgnK',
  'time': TIME,
  'type': 'deposit',
  'subtype': '',
  'asset': 'USDC',
  'amount': Decimal('10.00000000'),
  'fee': Decimal('0E-8'),
}


def test_a_trade_row_is_one_leg_plus_its_fee():
  """A spot trade is two ledger rows sharing a `refid`; the quote leg carries the fee,
  which becomes a `FeeLeg` pointing at the row."""
  leg, fee = parse_entry('LNTMZJ-KWJM7-O6SEG5', QUOTE_LEG)
  assert isinstance(leg, TradeLeg)
  assert leg.asset == 'USDC' and leg.amount == Decimal('-4.78482000')
  assert leg.trade_id == 'TSOH55-6XU77-SD3WPY' and leg.label == 'tradespot'
  assert leg.event_type == 'spot_trade'
  assert isinstance(fee, FeeLeg)
  assert fee.amount == Decimal('0.03828000') and fee.asset == 'USDC'
  assert fee.event_id == 'LNTMZJ-KWJM7-O6SEG5' and fee.event_type == 'trade_leg'


def test_a_zero_fee_adds_no_fee_leg():
  """Every ledger row carries a `fee`, zero on most; only a non-zero one is a leg."""
  (observation,) = parse_entry('LWDFFQ-X5QNA-MBNXR7', STAKING)
  assert isinstance(observation, Yield)
  assert observation.asset == 'XXBT' and observation.amount == Decimal('1.1E-9')


def test_deposits_split_on_the_fiat_list():
  """The catalogue classes fiat and crypto alike, so the asset id decides."""
  (crypto,) = parse_entry('L1', DEPOSIT)
  assert isinstance(crypto, CryptoDeposit) and crypto.amount == Decimal('10')
  (fiat,) = parse_entry('L2', {**DEPOSIT, 'asset': 'ZEUR'})
  assert isinstance(fiat, FiatDeposit)


def test_an_uncommon_type_stays_unknown():
  """`margin`, `adjustment`, `rollover` and the rest are not guessed at."""
  (observation,) = parse_entry('L3', {**STAKING, 'type': 'adjustment'})
  assert isinstance(observation, UnknownObservation)
