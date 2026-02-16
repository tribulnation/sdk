from decimal import Decimal
from typing_extensions import Sequence

from trading_sdk.wallet.deposit_methods import (
	DepositMethod,
	DepositMethods as _DepositMethods,
)
from bitget_sdk.core import SdkMixin, wrap_exceptions
from bitget.spot.public.coins import CoinChain, CoinInfo


def _rechargeable(chain: CoinChain) -> bool:
	return chain["rechargeable"]


def _parse_coins_response_deposits(
	raw: list[CoinInfo],
	*,
	assets: Sequence[str] | None = None,
) -> list[DepositMethod]:
	assets_set = set(assets) if assets is not None else None
	out: list[DepositMethod] = []
	for coin_info in raw:
		coin = coin_info["coin"]
		if assets_set is not None and coin not in assets_set:
			continue
		chains = coin_info["chains"]
		for ch in chains:
			if not _rechargeable(ch):
				continue
			network = ch["chain"]
			fee = DepositMethod.Fee(asset=coin, amount=Decimal("0"))
			contract = ch.get("contractAddress")
			contract_address = str(contract) if contract is not None else None
			dep_confirm = ch.get("depositConfirm")
			min_confirmations: int | None = None
			if dep_confirm is not None:
				try:
					min_confirmations = int(dep_confirm)
				except (TypeError, ValueError):
					pass
			out.append(
				DepositMethod(
					asset=coin,
					network=network,
					fee=fee,
					contract_address=contract_address,
					min_confirmations=min_confirmations,
				)
			)
	return out


class DepositMethods(SdkMixin, _DepositMethods):
	@wrap_exceptions
	async def deposit_methods(
		self, *, assets: Sequence[str] | None = None,
	) -> Sequence[DepositMethod]:
		r = await self.client.spot.public.coins()
		return _parse_coins_response_deposits(r, assets=assets)
