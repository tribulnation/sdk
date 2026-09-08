"""Kraken implementation of the `withdrawal_methods` wallet endpoint."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.withdrawal_methods import (
  WithdrawalMethod,
  WithdrawalMethods as _WithdrawalMethods,
)
from tribulnation.kraken.core import Mixin

from typed_kraken.spot.funding.withdraw_methods import (
  WithdrawalMethod as KrakenWithdrawalMethod,
)


def parse_method(row: KrakenWithdrawalMethod) -> WithdrawalMethod | None:
  """Map one `WithdrawMethods` row onto a `WithdrawalMethod`, or skip one naming no
  asset.

  `network` is Kraken's display network name (`Bitcoin`, `Arbitrum One`, or a bank
  rail for fiat), falling back to the method name on a row without one. The fee is
  a flat amount in the row's own fee asset. No row carries a contract address.
  """
  asset = row.get('asset')
  if asset is None:
    return None
  network = row.get('network') or row.get('method')
  if network is None:
    return None
  fee = row['fee']
  return WithdrawalMethod(
    asset=asset,
    network=network,
    fee=WithdrawalMethod.Fee(asset=fee.get('asset') or asset, amount=fee['fee']),
  )


@dataclass(frozen=True, kw_only=True)
class WithdrawalMethods(_WithdrawalMethods, Mixin):
  """Kraken implementation of `WithdrawalMethods`.

  `WithdrawMethods` answers the whole catalogue in one request and takes at most
  one asset and one network as filters, so the SDK's plural filters fan out into
  one request per combination. Needs an API key with the `Funds permissions -
  Query` and `Funds permissions - Withdraw` permissions.
  """

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    out: list[WithdrawalMethod] = []
    for asset in list(assets) if assets is not None else [None]:
      for network in list(networks) if networks is not None else [None]:
        current_asset, current_network = asset, network
        rows = await self.call_kraken(
          lambda: self.client.spot.funding.withdraw_methods(
            asset=current_asset, network=current_network
          )
        )
        out.extend(method for row in rows if (method := parse_method(row)))
    return out
