from typing_extensions import Collection
from dataclasses import dataclass, field
from decimal import Decimal
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Snapshots as _Snapshots, Snapshot, SnapshotResult, SubaccountSnapshot,
  Balances, Position, source_id
)
from tribulnation.dydx.core import (
  parse_coin, parse_dec_coin, parse_dydx_quantums,
  DYDX, USDC, wrap_exceptions
)
from dydx import Dydx, Indexer

@dataclass(frozen=True)
class Snapshots(_Snapshots):
  address: str
  client: Dydx = field(default_factory=lambda: Dydx.mainnet(public=True))

  @classmethod
  def of(cls, address: str, dydx: Dydx | None = None):
    if dydx is None:
      dydx = Dydx.mainnet(public=True)
    return cls(address=address, client=dydx)

  @property
  def indexer(self) -> Indexer:
    return self.client.indexer

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)

  @SDK.method
  @wrap_exceptions
  async def bank_module_balances(self) -> Balances:
    bank_balances = await self.client.chain.bank.all_balances_paged(self.address)
    balances = Balances()
    for coin in bank_balances:
      asset, amount = parse_coin(coin)
      balances[asset] += amount
    return balances


  @SDK.method
  @wrap_exceptions
  async def active_delegations(self) -> Balances:
    delegations = await self.client.chain.staking.delegator_delegations_paged(self.address)
    balances = Balances()
    for d in delegations:
      if d.balance is not None:
        asset, amount = parse_coin(d.balance)
        balances[asset] += amount
    return balances


  @SDK.method
  @wrap_exceptions
  async def unbonding_delegations(self) -> Balances:
    unbonding_delegations = await self.client.chain.staking.delegator_unbonding_delegations_paged(self.address)
    balances = Balances()
    for u in unbonding_delegations:
      for e in u.entries:
        balances[DYDX] += parse_dydx_quantums(e.balance)
    return balances
    
    
  @SDK.method
  @wrap_exceptions
  async def unclaimed_delegation_rewards(self) -> Balances:
    rewards = await self.client.chain.distribution.delegation_total_rewards(self.address)
    balances = Balances()
    for r in rewards.total:
      asset, amount = parse_dec_coin(r)
      balances[asset] += amount
    return balances


  @SDK.method
  @wrap_exceptions
  async def perpetual_subaccounts(self) -> list[SubaccountSnapshot]:
    subaccounts = (await self.client.indexer.data.get_subaccounts(self.address))['subaccounts']
    out: list[SubaccountSnapshot] = []
    for sub in subaccounts:
      unrealized = Decimal(0)
      positions: dict[str, Position] = {}
      for position in sub['openPerpetualPositions'].values():
        if (pnl := position.get('unrealizedPnl')) is not None:
          unrealized += Decimal(pnl)
        positions[position['market']] = Position(
          size=Decimal(position['size']),
          avg_price=Decimal(position['entryPrice']),
        )
      collateral = Decimal(sub['equity']) - unrealized
      out.append(SubaccountSnapshot(
        subaccount=str(sub['subaccountNumber']),
        balances=Balances({USDC: collateral}),
        positions=positions,
      ))
    return out

  @SDK.method
  @wrap_exceptions
  async def perpetual_collateral_and_positions(self) -> tuple[Decimal, dict[str, Position]]:
    """Return the aggregate perpetual state retained for direct SDK callers."""
    subaccounts = await self.perpetual_subaccounts()
    collateral = sum(
      (state.balances.get(USDC, Decimal(0)) for state in subaccounts),
      start=Decimal(0),
    )
    positions: dict[str, list[Position]] = {}
    for state in subaccounts:
      for instrument, position in state.positions.items():
        positions.setdefault(instrument, []).append(position)
    return collateral, {
      instrument: Position.merge(parts)
      for instrument, parts in positions.items()
    }

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotResult:
    bank, delegations, unbonding, unclaimed, perpetuals = await asyncio.gather(
      self.bank_module_balances(),
      self.active_delegations(),
      self.unbonding_delegations(),
      self.unclaimed_delegation_rewards(),
      self.perpetual_subaccounts(),
    )
    return SnapshotResult(
      snapshot=Snapshot(
        subaccounts=[
          SubaccountSnapshot(
            subaccount='chain',
            balances=bank + delegations + unbonding + unclaimed,
          ),
          *perpetuals,
        ],
      ),
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )
