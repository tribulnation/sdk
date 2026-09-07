"""Binance deposit methods, one per coin and network."""

from typing_extensions import Collection, Sequence

from tribulnation.sdk.core import SDK
from tribulnation.sdk.wallet.deposit_methods import (
  DepositMethod,
  DepositMethods as _DepositMethods,
)
from typed_binance.spot.http.wallet.capital.config.get_all import CoinConfig

from tribulnation.binance.core import SdkMixin


def parse_coin(
  coin: CoinConfig, *, assets: Collection[str] | None = None
) -> list[DepositMethod]:
  """Map one coin's network list onto its enabled deposit methods.

  `fee` is always `None`: Binance charges nothing to deposit, and the response carries
  no deposit fee field.
  """
  if assets is not None and coin['coin'] not in assets:
    return []
  return [
    DepositMethod(
      asset=coin['coin'],
      network=network['network'],
      fee=None,
      contract_address=network.get('contractAddress'),
      min_confirmations=network['minConfirm'],
    )
    for network in coin['networkList']
    if network['depositEnable']
  ]


class DepositMethods(SdkMixin, _DepositMethods):
  """Binance deposit methods."""

  @SDK.method
  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """Fetch every enabled deposit coin/network pair.

    `capital.config.get_all` is the one call Binance exposes for per-network deposit
    configuration; it needs no pagination and takes no filters, so `assets` is applied
    client-side.
    """
    coins = await self.call_binance(
      lambda: self.client.spot.http.wallet.capital.config.get_all()
    )
    return [m for coin in coins for m in parse_coin(coin, assets=assets)]
