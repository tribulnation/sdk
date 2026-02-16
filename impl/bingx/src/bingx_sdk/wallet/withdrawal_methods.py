from decimal import Decimal
from typing_extensions import Sequence

from trading_sdk.wallet.withdrawal_methods import (
	WithdrawalMethod,
	WithdrawalMethods as _WithdrawalMethods,
)
from bingx_sdk.core import SdkMixin


def _to_decimal(v: Decimal | str | int | None) -> Decimal:
	if v is None or v == "":
		return Decimal("0")
	if isinstance(v, Decimal):
		return v
	return Decimal(str(v))


def _parse_withdrawal_methods(raw: dict) -> list[WithdrawalMethod]:
	data = raw.get("data") or []
	out: list[WithdrawalMethod] = []
	for coin_info in data:
		asset = coin_info.get("coin") or ""
		if not asset:
			continue
		for net in coin_info.get("networkList") or []:
			if not net.get("withdrawEnable"):
				continue
			network = net.get("network") or net.get("name") or ""
			if not network:
				continue
			fee_amount = _to_decimal(net.get("withdrawFee"))
			fee = WithdrawalMethod.Fee(asset=asset, amount=fee_amount)
			contract = net.get("contractAddress") or None
			out.append(
				WithdrawalMethod(
					asset=asset,
					network=network,
					fee=fee,
					contract_address=contract,
				)
			)
	return out


class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
	async def withdrawal_methods(
		self,
		*,
		assets: Sequence[str] | None = None,
		networks: Sequence[str] | None = None,
	) -> Sequence[WithdrawalMethod]:
		r = await self.client.wallets_v1_private_get_capital_config_getall()
		parsed = _parse_withdrawal_methods(r)
		if assets is not None:
			assets_set = set(assets)
			parsed = [p for p in parsed if p.asset in assets_set]
		if networks is not None:
			networks_set = set(networks)
			parsed = [p for p in parsed if p.network in networks_set]
		return parsed
