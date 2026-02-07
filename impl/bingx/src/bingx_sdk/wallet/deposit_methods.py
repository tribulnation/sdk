from decimal import Decimal
from typing_extensions import Sequence

from tribulnation.sdk.wallet.deposit_methods import (
	DepositMethod,
	DepositMethods as _DepositMethods,
)
from bingx_sdk.core import SdkMixin


def _parse_deposit_methods(
	raw: dict,
	*,
	assets: Sequence[str] | None = None,
) -> list[DepositMethod]:
	assets_set = set(assets) if assets is not None else None
	data = raw.get("data") or []
	out: list[DepositMethod] = []
	for coin_info in data:
		asset = coin_info.get("coin") or ""
		if not asset:
			continue
		if assets_set is not None and asset not in assets_set:
			continue
		for net in coin_info.get("networkList") or []:
			if not net.get("depositEnable"):
				continue
			network = net.get("network") or net.get("name") or ""
			if not network:
				continue
			contract = net.get("contractAddress") or None
			min_confirm = net.get("minConfirm")
			min_confirmations: int | None = None
			if min_confirm is not None:
				try:
					min_confirmations = int(min_confirm)
				except (TypeError, ValueError):
					pass
			fee = DepositMethod.Fee(asset=asset, amount=Decimal("0"))
			out.append(
				DepositMethod(
					asset=asset,
					network=network,
					fee=fee,
					contract_address=contract,
					min_confirmations=min_confirmations,
				)
			)
	return out


class DepositMethods(SdkMixin, _DepositMethods):
	async def deposit_methods(
		self, *, assets: Sequence[str] | None = None,
	) -> Sequence[DepositMethod]:
		r = await self.client.wallets_v1_private_get_capital_config_getall()
		return _parse_deposit_methods(r, assets=assets)
