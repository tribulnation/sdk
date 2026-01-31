from decimal import Decimal
from typing_extensions import Sequence

from sdk.wallet.deposit_methods import (
	DepositMethod,
	DepositMethods as _DepositMethods,
)
from binance_sdk.core import SdkMixin


def _parse_coins_response_deposits(
	raw: list,
	*,
	assets: Sequence[str] | None = None,
) -> list[DepositMethod]:
	assets_set = set(assets) if assets is not None else None
	out: list[DepositMethod] = []
	for coin_info in raw:
		coin = coin_info["coin"]
		if assets_set is not None and coin not in assets_set:
			continue
		for net in coin_info.get("networkList") or []:
			if not net.get("depositEnable", False):
				continue
			network = net["network"]
			contract = net.get("contractAddress")
			contract_address = str(contract) if contract is not None else None
			min_conf = net.get("minConfirm")
			min_confirmations: int | None = int(min_conf) if min_conf is not None else None
			out.append(
				DepositMethod(
					asset=coin,
					network=network,
					fee=None,
					contract_address=contract_address,
					min_confirmations=min_confirmations,
				)
			)
	return out


class DepositMethods(SdkMixin, _DepositMethods):
	async def deposit_methods(
		self, *, assets: Sequence[str] | None = None,
	) -> Sequence[DepositMethod]:
		r = await self.client.wallet.capital.coins()
		return _parse_coins_response_deposits(r, assets=assets)
