from typing_extensions import NamedTuple, Sequence
from dataclasses import dataclass
from decimal import Decimal
from collections import Counter
from datetime import datetime
import asyncio

from trading_sdk.core import SDK
from trading_sdk.reporting import (
  Snapshot, Snapshots as _Snapshots,
)

from bitget import Bitget
from bitget_sdk.core import SdkMixin, wrap_exceptions

@dataclass(kw_only=True)
class Snapshots(SdkMixin, _Snapshots):
  """Bitget Snapshots
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """
  raise_if_copy: bool = False
  """Raise an error if copy trading is detected (since it cannot be reflected in the balances, thus yielding incorrect results)"""

  @SDK.method
  @wrap_exceptions
  async def spot_balances(self) -> Counter:
    balances = await self.client.spot.account.assets()
    counter = Counter()
    for balance in balances:
      counter[balance['coin']] += balance['available'] + balance['frozen'] + balance['locked'] # type: ignore
    return counter

  @SDK.method
  @wrap_exceptions
  async def futures_balances(self) -> Counter:
    balances = Counter()
    for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
      accounts = await self.client.futures.account.account_list(asset_type)
      for a in accounts:
        balances[a['marginCoin']] += Decimal(a['available']) # type: ignore

    for k, v in list(balances.items()):
      if v == 0:
        del balances[k]

    return balances

  class Position(NamedTuple):
    size: Decimal
    entry: Decimal

  @SDK.method
  @wrap_exceptions
  async def futures_positions(self) -> dict[str, Position]:
    positions: dict[str, Snapshots.Position] = {}
    for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
      assets = await self.client.futures.position.all_positions(asset_type)
      for asset in assets:
        assert not asset['symbol'] in positions
        positions[asset['symbol']] = Snapshots.Position(
          size=asset['total'],
          entry=asset['openPriceAvg'],
        )
    
    return positions

  @SDK.method
  @wrap_exceptions
  async def earn_balances(self) -> Counter:
    balances = await self.client.earn.account.assets()
    counter = Counter()
    for balance in balances:
      counter[balance['coin']] += balance['amount'] # type: ignore
    return counter

  @SDK.method
  @wrap_exceptions
  async def cross_margin_balances(self) -> Counter:
    balances = await self.client.margin.cross.account.assets()
    counter = Counter()
    for balance in balances:
      counter[balance['coin']] += balance['net'] # type: ignore
    return counter

  @SDK.method
  @wrap_exceptions
  async def isolated_margin_balances(self) -> Counter:
    balances = await self.client.margin.isolated.account.assets()
    counter = Counter()
    for balance in balances:
      counter[balance['coin']] += balance['net'] # type: ignore
    return counter

  @SDK.method
  @wrap_exceptions
  async def bot_balances(self) -> Counter:
    counter = Counter()
    for account_type in ('spot', 'futures'):
      balances = await self.client.common.assets.bot(account_type)
      for balance in balances:
        if balance['equity']:
          total = balance['equity']
        else:
          total = balance['available'] + (balance['frozen'] or 0)
        counter[balance['coin']] += total # type: ignore
    return counter

  @SDK.method
  @wrap_exceptions
  async def funding_balances(self) -> Counter:
    balances = await self.client.common.assets.funding()
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

  @SDK.method
  @wrap_exceptions
  async def all_balances(self) -> Counter:
    balances = await asyncio.gather(*[fn(self) for fn in Snapshots.balance_functions])
    return sum(balances, start=Counter())


  @wrap_exceptions
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
      self.futures_positions(),
      self.all_balances(),
      self.bot_balances(),
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
