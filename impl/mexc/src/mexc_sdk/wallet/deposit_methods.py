from typing_extensions import Sequence
from decimal import Decimal

from sdk.wallet.deposit_methods import DepositMethod, DepositMethods as _DepositMethods

from mexc_sdk.core import SdkMixin, wrap_exceptions


class DepositMethods(_DepositMethods, SdkMixin):
	@wrap_exceptions
	async def deposit_methods(
		self, *, assets: Sequence[str] | None = None,
	) -> Sequence[DepositMethod]:
		currencies = await self.client.spot.currency_info()

		out: list[DepositMethod] = []
		for c in currencies:
			if assets is None or c["coin"] in assets:
				for m in c["networkList"]:
					if m["depositEnable"]:
						out.append(DepositMethod(
							asset=c["coin"],
							network=m["netWork"],
							fee=DepositMethod.Fee(
								asset=c["coin"],
								amount=Decimal("0"),
							),
							contract_address=m.get("contract"),
							min_confirmations=None,
						))
		return out
