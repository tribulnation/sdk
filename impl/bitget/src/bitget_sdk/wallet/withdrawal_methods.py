from decimal import Decimal
from typing_extensions import Sequence

from sdk.wallet.withdrawal_methods import (
	Network,
	WithdrawalMethod,
	WithdrawalMethods as _WithdrawalMethods,
)
from bitget_sdk.core import SdkMixin, parse_network
from bitget.spot.market.coins import CoinChain, CoinInfo


def _to_decimal(v: Decimal | str) -> Decimal:
	return v if isinstance(v, Decimal) else Decimal(str(v))


def _withdrawable(chain: CoinChain) -> bool:
	return chain['withdrawable']


def _parse_coins_response(raw: list[CoinInfo]) -> Sequence[WithdrawalMethod]:
	out: list[WithdrawalMethod] = []
	for coin_info in raw:
		coin = coin_info['coin']
		chains = coin_info['chains']
		for ch in chains:
			if not _withdrawable(ch):
				continue
			network = parse_network(ch['chain'])
			if network is None:
				continue
			fee_amount = _to_decimal(ch['withdrawFee'])
			fee = WithdrawalMethod.Fee(asset=coin, amount=fee_amount)
			contract = ch['contractAddress']
			if contract is not None:
				contract = str(contract)
			out.append(
				WithdrawalMethod(
					asset=coin,
					contract_address=contract,
					network=network,
					fee=fee,
				)
			)
	return out


class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
	async def withdrawal_methods(
		self,
		*,
		assets: Sequence[str] | None = None,
		networks: Sequence[Network] | None = None,
	) -> Sequence[WithdrawalMethod]:
		r = await self.client.spot.market.coins()
		parsed = _parse_coins_response(r)
		if assets is not None:
			assets_set = set(assets)
			parsed = [p for p in parsed if p.asset in assets_set]
		if networks is not None:
			networks_set = set(networks)
			parsed = [p for p in parsed if p.network in networks_set]
		return parsed
