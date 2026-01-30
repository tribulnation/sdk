from typing_extensions import NamedTuple, Sequence
from dataclasses import dataclass
from decimal import Decimal
from collections import Counter
from datetime import datetime
import asyncio

from sdk.reporting import (
  Snapshot, Snapshots as SnapshotsTDK,
)

from bitget import Bitget
from bitget_sdk.core import SdkMixin

async def spot_balances(client: Bitget) -> Counter:
  balances = await client.spot.account.assets()
  counter = Counter()
  for balance in balances:
    counter[balance['coin']] += balance['available'] + balance['frozen'] + balance['locked'] # type: ignore
  return counter

async def futures_balances(client: Bitget) -> Counter:
  balances = Counter()
  for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
    accounts = await client.futures.account.account_list(asset_type)
    for a in accounts:
      balances[a['marginCoin']] += Decimal(a['available']) # type: ignore

  for k, v in list(balances.items()):
    if v == 0:
      del balances[k]

  return balances

class Position(NamedTuple):
  size: Decimal
  entry: Decimal

async def futures_positions(client: Bitget) -> dict[str, Position]:
  positions: dict[str, Position] = {}
  for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
    assets = await client.futures.position.all_positions(asset_type)
    for asset in assets:
      assert not asset['symbol'] in positions
      positions[asset['symbol']] = Position(
        size=asset['total'],
        entry=asset['openPriceAvg'],
      )
  
  return positions

async def earn_balances(client: Bitget) -> Counter:
  balances = await client.earn.account.assets()
  counter = Counter()
  for balance in balances:
    counter[balance['coin']] += balance['amount'] # type: ignore
  return counter

async def cross_margin_balances(client: Bitget) -> Counter:
  balances = await client.margin.cross.account.assets()
  counter = Counter()
  for balance in balances:
    counter[balance['coin']] += balance['net'] # type: ignore
  return counter

async def isolated_margin_balances(client: Bitget) -> Counter:
  balances = await client.margin.isolated.account.assets()
  counter = Counter()
  for balance in balances:
    counter[balance['coin']] += balance['net'] # type: ignore
  return counter

async def bot_balances(client: Bitget) -> Counter:
  counter = Counter()
  for account_type in ('spot', 'futures'):
    balances = await client.common.assets.bot(account_type)
    for balance in balances:
      if balance['equity']:
        total = balance['equity']
      else:
        total = balance['available'] + (balance['frozen'] or 0)
      counter[balance['coin']] += total # type: ignore
  return counter

async def funding_balances(client: Bitget) -> Counter:
  balances = await client.common.assets.funding()
  counter = Counter()
  for balance in balances:
    counter[balance['coin']] += balance['available'] + balance['frozen'] # type: ignore
  return counter

balance_functions = [
  spot_balances,
  futures_balances,
  earn_balances,
  cross_margin_balances,
  isolated_margin_balances,
  funding_balances,
]

async def all_balances(client: Bitget) -> Counter:
  balances = await asyncio.gather(*[fn(client) for fn in balance_functions])
  return sum(balances, start=Counter())

@dataclass(kw_only=True)
class Snapshots(SdkMixin, SnapshotsTDK):
  """Bitget Snapshots
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """
  raise_if_copy: bool = True
  """Raise an error if copy trading is detected (since it cannot be reflected in the balances, thus yielding incorrect results)"""

  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:

    if self.raise_if_copy:
      future_copy, spot_copy = await asyncio.gather(
        self.client.copy.futures.follower.my_traders(),
        self.client.copy.spot.follower.my_traders(),
      )
      spot_copy = spot_copy['resultList']
      if len(future_copy) > 0 or len(spot_copy) > 0:
        raise ValueError(f'{len(future_copy)} future copy traders and {len(spot_copy)} spot copy traders detected. Use with `raise_if_copy=False` to suppress this error at your own peril.')


    positions, balances, bot_assets = await asyncio.gather(
      futures_positions(self.client),
      all_balances(self.client),
      bot_balances(self.client),
    )
    
    time = datetime.now()
    return [
      Snapshot(asset=asset, time=time, qty=Decimal(qty), kind='currency')
      for asset, qty in balances.items()
    ] + [
      Snapshot(asset=asset, time=time, qty=p.size, avg_price=p.entry, kind='future')
      for asset, p in positions.items()
    ] + [
      Snapshot(asset=asset, time=time, qty=Decimal(qty), kind='strategy')
      for asset, qty in bot_assets.items()
    ]
