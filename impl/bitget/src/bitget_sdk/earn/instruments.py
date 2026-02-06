from datetime import timedelta
from decimal import Decimal
from typing_extensions import Sequence

from tribulnation.sdk.earn.instruments import (
	Fixed,
	Flexible,
	Instrument,
	Instruments as _Instruments,
	InstrumentType,
)
from bitget.earn.savings.products import Product
from bitget_sdk.core import SdkMixin

BITGET_SAVINGS_URL = 'https://www.bitget.com/earning/savings'

def _to_decimal(v: Decimal | str) -> Decimal:
	return v if isinstance(v, Decimal) else Decimal(str(v))

def _parse_product(raw: Product) -> Sequence[Instrument]:
	if raw['status'] != 'in_progress':
		return []
	coin = raw['coin']
	period_type = raw['periodType']
	apy_list = raw['apyList']
	# Savings products pay yield in the same coin; API has no separate yield_asset.
	yield_asset = coin
	period_days = int(raw['period']) if raw.get('period') else 0
	duration = timedelta(days=period_days) if period_type == 'fixed' else None

	out: list[Instrument] = []
	for tier in apy_list:
		apr = _to_decimal(tier['currentApy']) / 100
		min_qty = _to_decimal(tier['minStepVal'])
		max_qty = _to_decimal(tier['maxStepVal'])
		if period_type == 'flexible':
			out.append(Flexible(
				type='flexible',
				asset=coin,
				apr=apr,
				yield_asset=yield_asset,
				min_qty=min_qty,
				max_qty=max_qty,
				url=BITGET_SAVINGS_URL,
			))
		else:
			assert duration is not None
			out.append(Fixed(
				type='fixed',
				asset=coin,
				apr=apr,
				yield_asset=yield_asset,
				min_qty=min_qty,
				max_qty=max_qty,
				url=BITGET_SAVINGS_URL,
				duration=duration,
			))
	return out


class Instruments(SdkMixin, _Instruments):
	async def instruments(
		self, *, types: Sequence[InstrumentType] | None = None,
		assets: Sequence[str] | None = None,
	) -> Sequence[Instrument]:
		r = await self.client.earn.savings.products()
		parsed = [inst for p in r for inst in _parse_product(p)]
		if types is not None:
			types_set = set(types)
			parsed = [p for p in parsed if p.type in types_set]
		if assets is not None:
			assets_set = set(assets)
			parsed = [p for p in parsed if p.asset in assets_set]
		return parsed
