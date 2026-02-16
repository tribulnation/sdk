from typing_extensions import Collection, Sequence, Iterable
from datetime import timedelta

from trading_sdk.earn.instruments import Instrument, Instruments as _Instruments
from bitget.earn.savings.products import Product
from bitget_sdk.core import SdkMixin, wrap_exceptions

BITGET_SAVINGS_URL = 'https://www.bitget.com/earning/savings'

def parse_product(prod: Product) -> Iterable[Instrument]:
	if prod['status'] != 'in_progress':
		return []
	coin = prod['coin']
	period_type = prod['periodType']
	apy_list = prod['apyList']

	if period_type == 'fixed':
		duration = timedelta(days=int(prod['period']))
	else:
		duration = None

	for tier in apy_list:
		apr = tier['currentApy'] / 100
		min_qty = tier['minStepVal']
		max_qty = tier['maxStepVal']
		yield Instrument(
			tags=[period_type],
			asset=coin,
			apr=apr,
			min_qty=min_qty,
			max_qty=max_qty,
			duration=duration,
			url=BITGET_SAVINGS_URL,
		)


class Instruments(SdkMixin, _Instruments):
	@wrap_exceptions
	async def instruments(
		self, *, tags: Collection[Instrument.Tag] | None = None,
		assets: Sequence[str] | None = None,
	) -> Sequence[Instrument]:
		out: list[Instrument] = []
		r = await self.client.earn.savings.products()
		for prod in r:
			for inst in parse_product(prod):
				if (assets is None or inst.asset in assets) and (tags is None or set(inst.tags).issubset(tags)):
					out.append(inst)
		return out