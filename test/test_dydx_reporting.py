"""dYdX reporting adapter tests."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tribulnation.dydx import Reporting
from tribulnation.dydx.report.history import account_label, in_window
from dydx.node import DYDX_MAINNET_USDC_DENOM
from dydx.protos.cosmos.bank import v1beta1 as bank_proto
from dydx.protos.cosmos.base import v1beta1 as coin_proto
from dydx.protos.cosmos.distribution import v1beta1 as distribution_proto
from dydx.protos.cosmos.staking import v1beta1 as staking_proto
from tribulnation.sdk.reporting import (
  Funding,
  FutureTrade,
  InternalTransfer,
  Pnl,
  Report,
  ReportSDK,
  UnknownObservation,
)

NOW = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
ADDRESS = 'dydx1nn42jj4kjcr26xl9fghc0ce34335x9f3wfjp2a'

class FakeComet:
  """Fake Comet client for chain-evidence conversion tests."""

  async def block(self, height: int, validate: bool | None = None):
    """Return a minimal block response."""
    return {'block': {'header': {'time': NOW}}}

class FakeChain:
  """Fake chain client carrying Comet helpers."""

  comet: FakeComet = FakeComet()

class FakeClient:
  """Fake dYdX client carrying chain helpers."""

  chain: FakeChain = FakeChain()

def reporting() -> Reporting:
  """Create a reporting adapter with fake transports."""
  return Reporting(address=ADDRESS, client=FakeClient()) # type: ignore

class FakeBank:
  """Fake chain bank module for snapshot tests."""

  async def denom_metadata(self, denom: str):
    """Return display metadata for test denoms."""
    return bank_proto.QueryDenomMetadataResponse(
      metadata=bank_proto.Metadata(
        base=denom,
        display='dydx' if denom == 'adydx' else 'usdc',
        symbol='DYDX' if denom == 'adydx' else 'USDC',
        denom_units=[
          bank_proto.DenomUnit(denom=denom),
          bank_proto.DenomUnit(denom='dydx' if denom == 'adydx' else 'usdc', exponent=18 if denom == 'adydx' else 6),
        ],
      ),
    )

  async def all_balances_paged(self, address: str):
    """Return liquid wallet balances."""
    return [
      coin_proto.Coin(denom='adydx', amount='1000000000000000000'),
      coin_proto.Coin(denom=DYDX_MAINNET_USDC_DENOM, amount='1250000'),
    ]

class FakeStaking:
  """Fake chain staking module for snapshot tests."""

  async def delegator_delegations_paged(self, address: str):
    """Return staked DYDX balances."""
    return [
      staking_proto.DelegationResponse(
        balance=coin_proto.Coin(denom='adydx', amount='2000000000000000000'),
      ),
    ]

class FakeDistribution:
  """Fake chain distribution module for snapshot tests."""

  async def delegation_total_rewards(self, address: str):
    """Return unclaimed staking rewards."""
    return distribution_proto.QueryDelegationTotalRewardsResponse(
      total=[coin_proto.DecCoin(denom='adydx', amount='3000000000000000000')],
    )

class FakeSnapshotChain(FakeChain):
  """Fake chain modules needed by complete snapshot balances."""
  bank: FakeBank = FakeBank()
  staking: FakeStaking = FakeStaking()
  distribution: FakeDistribution = FakeDistribution()

class FakeSnapshotClient:
  """Fake client carrying full snapshot chain helpers."""
  chain: FakeSnapshotChain = FakeSnapshotChain()

def test_parse_fill() -> None:
  """Convert a dYdX indexer fill into an SDK trade observation."""
  record = reporting().parse_fill({
    'id': 'fill-1',
    'side': 'BUY',
    'liquidity': 'MAKER',
    'type': 'LIMIT',
    'market': 'BTC-USD',
    'marketType': 'PERPETUAL',
    'price': Decimal('50000'),
    'size': Decimal('0.01'),
    'fee': Decimal('0.02'),
    'affiliateRevShare': Decimal('0'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'subaccountNumber': 0,
    'orderId': 'order-1',
  })

  trade = record.observations[0]
  assert isinstance(trade, FutureTrade)
  assert trade.market == 'BTC-USD'
  assert trade.size == Decimal('0.01')
  assert trade.collateral_asset == 'USDC'
  assert trade.subaccount == 0
  assert trade.fee is not None
  assert trade.fee.asset == 'USDC'
  assert trade.fee.amount == Decimal('0.02')

def test_parse_pnl() -> None:
  """Convert a dYdX historical PnL delta into a derived PnL observation."""
  record = reporting().parse_pnl({
    'blockHeight': '10',
    'blockTime': NOW,
    'createdAt': NOW,
    'equity': Decimal('20'),
    'totalPnl': Decimal('12'),
    'netTransfers': Decimal('0'),
  }, amount=Decimal('1.25'), subaccount=0)

  pnl = record.observations[0]
  assert isinstance(pnl, Pnl)
  assert pnl.asset == 'USDC'
  assert pnl.amount == Decimal('1.25')
  assert pnl.subaccount == 0
  assert record.provenance['source'] == 'derived'

@pytest.mark.asyncio
async def test_snapshot_balances_include_wallet_staking_and_collateral() -> None:
  """Build complete dYdX snapshot balances from subaccounts and chain state."""
  report = Reporting(address=ADDRESS, client=FakeSnapshotClient()) # type: ignore
  balances = await report.snapshot_balances(
    Decimal('47.185969'),
    {'BTC-USD': Decimal('0.01')},
    {'BTC-USD': Decimal('50000')},
  )

  assert balances['USDC'].qty == Decimal('48.435969')
  assert balances['DYDX'].qty == Decimal('1')
  assert balances['DYDX:staked'].qty == Decimal('2')
  assert balances['DYDX:rewards'].qty == Decimal('3')
  assert balances['BTC-USD'].kind == 'future'

def test_parse_funding_payment() -> None:
  """Convert a dYdX funding payment into an SDK funding observation."""
  record = reporting().parse_funding_payment({
    'createdAt': NOW,
    'createdAtHeight': '10',
    'perpetualId': '0',
    'ticker': 'BTC-USD',
    'oraclePrice': Decimal('50000'),
    'size': Decimal('0.01'),
    'side': 'LONG',
    'rate': Decimal('0.0001'),
    'payment': Decimal('-0.5'),
    'subaccountNumber': '0',
    'fundingIndex': Decimal('1'),
  })

  funding = record.observations[0]
  assert isinstance(funding, Funding)
  assert funding.asset == 'USDC'
  assert funding.amount == Decimal('-0.5')

def test_parse_subaccount_transfer() -> None:
  """Convert dYdX subaccount transfers into internal transfers."""
  record = reporting().parse_transfer({
    'id': 'transfer-1',
    'sender': {'address': ADDRESS},
    'recipient': {'address': ADDRESS, 'subaccountNumber': 0},
    'size': Decimal('12.5'),
    'createdAt': NOW,
    'createdAtHeight': '10',
    'symbol': 'USDC',
    'type': 'DEPOSIT',
    'transactionHash': 'ABC',
  }, subaccount=0)

  assert record is not None
  transfer = record.observations[0]
  assert isinstance(transfer, InternalTransfer)
  assert transfer.asset == 'USDC'
  assert transfer.amount == Decimal('12.5')
  assert transfer.src_account == ADDRESS
  assert transfer.dst_account == f'{ADDRESS}:0'

@pytest.mark.asyncio
async def test_parse_unmatched_chain_tx() -> None:
  """Represent unmatched Comet evidence without guessing economics."""
  record = await reporting().parse_chain_tx({
    'hash': 'ABC',
    'height': '100',
    'tx_result': {'events': []},
    'tx': '',
    'index': 0,
  }, start=None, end=None)

  assert record is not None
  observation = record.observations[0]
  assert isinstance(observation, UnknownObservation)
  assert observation.id == 'ABC'
  assert observation.time == NOW

def test_reporting_sdk_registers_dydx() -> None:
  """Expose dYdX through the generic reporting registry."""
  sdk = ReportSDK()
  assert 'dydx' in sdk.venues()
  assert isinstance(sdk.dydx(ADDRESS), Report)
  assert isinstance(sdk.venue('dydx', address=ADDRESS), Report)

def test_small_helpers() -> None:
  """Check dYdX reporting helper behavior."""
  assert in_window(NOW, start=None, end=None)
  assert account_label({'address': ADDRESS, 'subaccountNumber': 1}) == f'{ADDRESS}:1'
