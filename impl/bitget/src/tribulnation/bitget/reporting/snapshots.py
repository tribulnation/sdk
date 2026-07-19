from typing_extensions import Collection, Literal
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  Snapshot, SnapshotResult, SubaccountSnapshot, Snapshots as _Snapshots,
  source_id, Position, Balances
)

from tribulnation.bitget.core import SdkMixin, wrap_exceptions

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
  async def spot_balances(self) -> Balances:
    balances = await self.client.spot.account.assets()
    out = Balances()
    for balance in balances:
      out[balance['coin']] += Decimal(balance['available']) + Decimal(balance['frozen']) + Decimal(balance['locked'])
    return out

  @SDK.method
  @wrap_exceptions
  async def futures_balances(self) -> Balances:
    balances = Balances()
    for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
      accounts = await self.client.futures.account.account_list(asset_type)
      for a in accounts:
        balances[a['marginCoin']] += Decimal(a['available'])

    for k, v in list(balances.items()):
      if v == 0:
        del balances[k]

    return balances

  @SDK.method
  @wrap_exceptions
  async def futures_positions(self) -> dict[str, Position]:
    positions: dict[str, Position] = {}
    for asset_type in ('USDT-FUTURES', 'USDC-FUTURES', 'COIN-FUTURES'):
      assets = await self.client.futures.position.all_positions(asset_type)
      for asset in assets:
        assert not asset['symbol'] in positions
        positions[asset['symbol']] = Position(
          size=asset['total'],
          avg_price=asset['openPriceAvg'],
        )
    
    return positions

  @SDK.method
  @wrap_exceptions
  async def earn_balances(self) -> Balances:
    balances = await self.client.earn.account.assets()
    out = Balances()
    for balance in balances:
      out[balance['coin']] += Decimal(balance['amount'])
    return out

  @SDK.method
  @wrap_exceptions
  async def cross_margin_balances(self) -> Balances:
    balances = await self.client.margin.cross.account.assets()
    out = Balances()
    for balance in balances:
      out[balance['coin']] += Decimal(balance['net'])
    return out

  @SDK.method
  @wrap_exceptions
  async def isolated_margin_balances(self) -> Balances:
    balances = await self.client.margin.isolated.account.assets()
    out = Balances()
    for balance in balances:
      out[balance['coin']] += Decimal(balance['net'])
    return out

  @SDK.method
  @wrap_exceptions
  async def bot_balances(self, account_type: Literal['spot', 'futures']) -> Balances:
    out = Balances()
    balances = await self.client.common.assets.bot(account_type)
    for balance in balances:
      if balance['equity']:
        total = balance['equity']
      else:
        total = balance['available'] + (balance['frozen'] or 0)
      out[balance['coin']] += total
    return out

  @SDK.method
  @wrap_exceptions
  async def funding_balances(self) -> Balances:
    balances = await self.client.common.assets.funding()
    out = Balances()
    for balance in balances:
      out[balance['coin']] += balance['available'] + balance['frozen']
    return out


  @wrap_exceptions
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotResult:

    if self.raise_if_copy:
      future_copy, spot_copy = await asyncio.gather(
        self.client.copy.futures.follower.my_traders(),
        self.client.copy.spot.follower.my_traders(),
      )
      spot_copy = spot_copy['resultList']
      if len(future_copy) > 0 or len(spot_copy) > 0:
        raise ValueError(f'{len(future_copy)} future copy traders and {len(spot_copy)} spot copy traders detected. Use with `raise_if_copy=False` to suppress this error at your own peril.')


    (
      (positions, spot, futures, crossed_margin, isolated_margin),
      (earn, funding, spot_bot, futures_bot),
    ) = await asyncio.gather(
      asyncio.gather(
        self.futures_positions(),
        self.spot_balances(),
        self.futures_balances(),
        self.cross_margin_balances(),
        self.isolated_margin_balances(),
      ),
      asyncio.gather(
        self.earn_balances(),
        self.funding_balances(),
        self.bot_balances('spot'),
        self.bot_balances('futures'),
      ),
    )
    return SnapshotResult(
      snapshot=Snapshot(subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot),
        SubaccountSnapshot(
          subaccount='futures', balances=futures, positions=positions,
        ),
        SubaccountSnapshot(subaccount='earn', balances=earn),
        SubaccountSnapshot(subaccount='crossed_margin', balances=crossed_margin),
        SubaccountSnapshot(subaccount='isolated_margin', balances=isolated_margin),
        SubaccountSnapshot(subaccount='funding', balances=funding),
        SubaccountSnapshot(subaccount='spot_bot', balances=spot_bot),
        SubaccountSnapshot(subaccount='futures_bot', balances=futures_bot),
      ]),
      provenance={'source': 'api', 'service': 'bitget', 'id': source_id('bitget')},
    )
