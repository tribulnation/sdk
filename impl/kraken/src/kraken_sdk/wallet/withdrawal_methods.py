from decimal import Decimal
from typing_extensions import Sequence

from trading_sdk.core import SDK
from trading_sdk.wallet.withdrawal_methods import (
  WithdrawalMethod,
  WithdrawalMethods as _WithdrawalMethods,
)
from kraken_sdk.core import SdkMixin


def _parse_withdrawal_method(raw: dict) -> WithdrawalMethod:
  """Parse one Kraken withdraw method result into WithdrawalMethod."""
  asset = raw.get("asset") or ""
  network = raw.get("network") or raw.get("method") or ""
  fee_obj = raw.get("fee")
  if fee_obj and isinstance(fee_obj, dict):
    fee_asset = fee_obj.get("asset") or asset
    fee_str = fee_obj.get("fee") or "0"
    fee = WithdrawalMethod.Fee(asset=fee_asset, amount=Decimal(str(fee_str)))
  else:
    fee = WithdrawalMethod.Fee(asset=asset, amount=Decimal("0"))
  return WithdrawalMethod(
    asset=asset,
    contract_address=None,
    network=network,
    fee=fee,
  )


class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
  async def withdrawal_methods(
    self,
    *,
    assets: Sequence[str] | None = None,
    networks: Sequence[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    r = await self.client.private_post_withdrawmethods()
    if r.get("error"):
      raise RuntimeError(f"Kraken API error: {r['error']}")
    items = r.get("result") or []
    parsed: list[WithdrawalMethod] = []
    for item in items:
      if isinstance(item, dict):
        parsed.append(_parse_withdrawal_method(item))
    if assets is not None:
      assets_set = set(assets)
      parsed = [p for p in parsed if p.asset in assets_set]
    if networks is not None:
      networks_set = set(networks)
      parsed = [p for p in parsed if p.network in networks_set]
    return parsed
