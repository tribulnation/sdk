from decimal import Decimal
from typing_extensions import Sequence

from sdk.wallet.withdrawal_methods import (
	WithdrawalMethod,
	WithdrawalMethods as _WithdrawalMethods,
)
from binance_sdk.core import SdkMixin


def _to_decimal(v: Decimal | str) -> Decimal:
	return v if isinstance(v, Decimal) else Decimal(str(v))


def _parse_coins_response_withdrawals(
	raw: list,
	*,
	assets: Sequence[str] | None = None,
	networks: Sequence[str] | None = None,
) -> list[WithdrawalMethod]:
	assets_set = set(assets) if assets is not None else None
	networks_set = set(networks) if networks is not None else None
	out: list[WithdrawalMethod] = []
	for coin_info in raw:
		coin = coin_info["coin"]
		if assets_set is not None and coin not in assets_set:
			continue
		for net in coin_info.get("networkList") or []:
			if not net.get("withdrawEnable", False):
				continue
			network = net["network"]
			if networks_set is not None and network not in networks_set:
				continue
			fee_amount = _to_decimal(net["withdrawFee"])
			fee = WithdrawalMethod.Fee(asset=coin, amount=fee_amount)
			contract = net.get("contractAddress")
			contract_address = str(contract) if contract is not None else None
			out.append(
				WithdrawalMethod(
					asset=coin,
					contract_address=contract_address,
					network=network,
					fee=fee,
				)
			)
	return out


class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
	async def withdrawal_methods(
		self, *, assets: Sequence[str] | None = None,
		networks: Sequence[str] | None = None,
	) -> Sequence[WithdrawalMethod]:
		r = await self.client.wallet.capital.coins()
		return _parse_coins_response_withdrawals(r, assets=assets, networks=networks)
