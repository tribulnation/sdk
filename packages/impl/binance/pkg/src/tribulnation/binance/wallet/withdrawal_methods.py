"""Binance withdrawal methods, one per coin and network."""

from typing_extensions import Collection, Sequence

from tribulnation.sdk.core import SDK
from tribulnation.sdk.wallet.withdrawal_methods import (
  WithdrawalMethod,
  WithdrawalMethods as _WithdrawalMethods,
)
from typed_binance.spot.http.wallet.capital.config.get_all import CoinConfig

from tribulnation.binance.core import SdkMixin


def parse_coin(
  coin: CoinConfig,
  *,
  assets: Collection[str] | None = None,
  networks: Collection[str] | None = None,
) -> list[WithdrawalMethod]:
  """Map one coin's network list onto its enabled withdrawal methods."""
  if assets is not None and coin['coin'] not in assets:
    return []
  return [
    WithdrawalMethod(
      asset=coin['coin'],
      network=network['network'],
      fee=WithdrawalMethod.Fee(asset=coin['coin'], amount=network['withdrawFee']),
      contract_address=network.get('contractAddress'),
    )
    for network in coin['networkList']
    if network['withdrawEnable']
    and (networks is None or network['network'] in networks)
  ]


class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
  """Binance withdrawal methods."""

  @SDK.method
  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    """Fetch every enabled withdrawal coin/network pair, with its network fee.

    `capital.config.get_all` is the one call Binance exposes for per-network withdrawal
    configuration; it needs no pagination and takes no filters, so `assets`/`networks`
    are applied client-side.
    """
    coins = await self.call_binance(
      lambda: self.client.spot.http.wallet.capital.config.get_all()
    )
    return [
      m for coin in coins for m in parse_coin(coin, assets=assets, networks=networks)
    ]
