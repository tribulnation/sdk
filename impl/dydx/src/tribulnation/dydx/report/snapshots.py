from typing_extensions import Collection
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from decimal import Decimal
import os

from tribulnation.dydx.core import wrap_exceptions
from tribulnation.sdk.reporting import Balance, Record, Snapshot, Snapshots as _Snapshots

from dydx import Dydx, Indexer
from dydx.node import DYDX_MAINNET_USDC_DENOM
from dydx.protos.cosmos.bank import v1beta1 as bank_proto
from dydx.protos.cosmos.base import v1beta1 as coin_proto

USDC = 'USDC'

@dataclass(frozen=True)
class Snapshots(_Snapshots):
  address: str
  client: Dydx = field(default_factory=lambda: Dydx.mainnet(public=True))

  @property
  def indexer(self) -> Indexer:
    """Return the indexer transport used for snapshot reads."""
    return self.client.indexer

  async def denom_metadata(self, denom: str) -> bank_proto.Metadata | None:
    """Fetch bank metadata for a denom, returning none when unavailable."""
    response = await self.client.chain.bank.denom_metadata(denom)
    return response.metadata

  async def coin_balance(self, coin: coin_proto.Coin) -> tuple[str, Decimal]:
    """Convert a chain coin into a display asset and quantity."""
    if coin.denom == DYDX_MAINNET_USDC_DENOM:
      return USDC, Decimal(coin.amount) / Decimal(1_000_000)
    metadata = await self.denom_metadata(coin.denom)
    if metadata is None:
      return coin.denom, Decimal(coin.amount)
    display = metadata.display or metadata.base or coin.denom
    exponent = next(
      (unit.exponent for unit in metadata.denom_units if unit.denom == display),
      0,
    )
    asset = (metadata.symbol or display).upper()
    return asset, Decimal(coin.amount) * (Decimal(10) ** -exponent)

  async def add_wallet_balances(self, balances: dict[str, Balance]):
    """Add liquid wallet-level Cosmos bank balances to a snapshot."""
    for coin in await self.client.chain.bank.all_balances_paged(self.address):
      asset, qty = await self.coin_balance(coin)
      current = balances.get(asset)
      balances[asset] = Balance(
        qty=qty + (current.qty if current is not None else Decimal(0)),
        kind='currency',
      )

  async def add_staking_balances(self, balances: dict[str, Balance]):
    """Add delegated and unclaimed staking balances to a snapshot."""
    delegations = await self.client.chain.staking.delegator_delegations_paged(self.address)
    for delegation in delegations:
      if delegation.balance is None:
        continue
      asset, qty = await self.coin_balance(delegation.balance)
      key = f'{asset}:staked'
      current = balances.get(key)
      balances[key] = Balance(
        qty=qty + (current.qty if current is not None else Decimal(0)),
        kind='strategy',
      )
    rewards = await self.client.chain.distribution.delegation_total_rewards(self.address)
    for reward in rewards.total:
      asset, qty = await self.coin_balance(coin_proto.Coin(denom=reward.denom, amount=reward.amount))
      key = f'{asset}:rewards'
      current = balances.get(key)
      balances[key] = Balance(
        qty=qty + (current.qty if current is not None else Decimal(0)),
        kind='strategy',
      )

  async def __aenter__(self):
    await self.client.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.client.__aexit__(exc_type, exc_value, traceback)

  @wrap_exceptions
  async def snapshots(self, assets: Collection[str] | None = None) -> Record:
    time = datetime.now().astimezone()
    subaccounts = (await self.indexer.data.get_subaccounts(self.address))['subaccounts']
    equity = Decimal(0)
    unrealized = Decimal(0)
    realized = Decimal(0)

    positions = defaultdict[str, Decimal](Decimal)
    total_prices = defaultdict[str, Decimal](Decimal)

    for sub in subaccounts:
      equity += Decimal(sub['equity'])

      for position in sub['openPerpetualPositions'].values():
        if (pnl := position.get('realizedPnl')) is not None:
          realized += Decimal(pnl)
        if (pnl := position.get('unrealizedPnl')) is not None:
          unrealized += Decimal(pnl)

        positions[position['market']] += position['size']
        total_prices[position['market']] += position['size'] * position['entryPrice']

    collateral = equity - unrealized
    entry_prices = {
      market: total_prices[market] / positions[market]
      for market in positions
    }

    return Record(
      snapshots=[Snapshot(
        time=time,
        balances=await self.snapshot_balances(collateral, positions, entry_prices),
      )],
      provenance={'source': 'api', 'service': 'dydx', 'endpoint': 'snapshots'},
    )

  async def snapshot_balances(
    self,
    collateral: Decimal,
    positions: dict[str, Decimal],
    entry_prices: dict[str, Decimal],
  ) -> dict[str, Balance]:
    """Build complete wallet, staking, collateral, and futures balances."""
    balances: dict[str, Balance] = {
      USDC: Balance(qty=collateral, kind='currency'),
      **{
        market: Balance(qty=positions[market], avg_price=entry_prices[market], kind='future')
        for market in positions
      },
    }
    await self.add_wallet_balances(balances)
    await self.add_staking_balances(balances)
    return balances
