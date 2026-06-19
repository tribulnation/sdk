from typing_extensions import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Snapshots as _Snapshots, Snapshot,
  Balances, Position, Record, source_id
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
  async def perpetual_collateral_and_positions(self) -> tuple[Decimal, dict[str, Position]]:
    subaccounts = (await self.client.indexer.data.get_subaccounts(self.address))['subaccounts']
    equity = Decimal(0)
    unrealized = Decimal(0)

    positions_sizes = Balances()
    total_prices = Balances()

    for sub in subaccounts:
      equity += Decimal(sub['equity'])

      for position in sub['openPerpetualPositions'].values():
        if (pnl := position.get('unrealizedPnl')) is not None:
          unrealized += Decimal(pnl)

        positions_sizes[position['market']] += position['size']
        total_prices[position['market']] += position['size'] * position['entryPrice']

    collateral = equity - unrealized

    positions_sizes = Balances({ k: v for k, v in positions_sizes.items() if v })
    entry_prices = {
      market: total_prices[market] / positions_sizes[market]
      for market in positions_sizes
    }
    positions = {
      market: Position(size=positions_sizes[market], avg_price=entry_prices[market])
      for market in positions_sizes
    }

    return collateral, positions

  async def snapshots(self, assets: Sequence[str] | None = None) -> Record:
    bank, delegations, unbonding, unclaimed, (collateral, positions) = await asyncio.gather(
      self.bank_module_balances(),
      self.active_delegations(),
      self.unbonding_delegations(),
      self.unclaimed_delegation_rewards(),
      self.perpetual_collateral_and_positions(),
    )
    balances = bank + delegations + unbonding + unclaimed + Balances({USDC: collateral})
    return Record(
      snapshots=[Snapshot(
        time=datetime.now(timezone.utc),
        balances=balances,
        positions=positions,
      )],
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )