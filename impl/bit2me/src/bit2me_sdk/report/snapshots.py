from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import asyncio
from collections import Counter

from trading_sdk.core import SDK
from trading_sdk.reporting import Snapshots as _Snapshots, Snapshot
from bit2me_sdk.core import wrap_exceptions
from bit2me import Bit2Me

@dataclass
class Snapshots(_Snapshots):
  client: Bit2Me

  @classmethod
  def new(
    cls, api_key: str | None = None, api_secret: str | None = None, *,
    validate: bool = True
  ):
    return cls(client=Bit2Me.new(api_key=api_key, api_secret=api_secret, validate=validate))

  @SDK.method
  @wrap_exceptions
  async def spot_balances(self) -> Counter:
    out = Counter()
    balances = await self.client.v1.trading.balance()
    for entry in balances:
      asset = entry['currency'] # type: ignore
      balance = Decimal(entry.get('balance', 0)) + Decimal(entry.get('blockedBalance', 0))
      out[asset] += balance # type: ignore
    return out

  @SDK.method
  @wrap_exceptions
  async def earn_balances(self) -> Counter:
    out = Counter()
    wallets = await self.client.v2.earn.wallets()
    for entry in wallets.get('data', []):
      out[entry['currency']] += Decimal(entry['balance']) # type: ignore
    return out

  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    c1, c2 = await asyncio.gather(
      self.spot_balances(),
      self.earn_balances(),
    )
    time = datetime.now()
    total = c1 + c2
    return [
      Snapshot(asset=asset, time=time, qty=Decimal(qty), kind='currency')
      for asset, qty in total.items()
    ]