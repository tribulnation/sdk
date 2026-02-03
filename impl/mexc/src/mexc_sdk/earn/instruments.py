from datetime import timedelta
from decimal import Decimal
from typing_extensions import Sequence

from sdk.earn.instruments import (
	Fixed,
	Flexible,
	Instrument,
	Instruments as _Instruments,
	InstrumentType,
)
from mexc_sdk.core import SdkMixin, wrap_exceptions
from mexc_sdk.earn._financial_products import (
	CurrencyGroup,
	FinancialProduct,
	fetch_financial_products_list_v2,
)


def _to_decimal(v: str | int | Decimal) -> Decimal:
	if isinstance(v, Decimal):
		return v
	return Decimal(str(v))


def _parse_product(currency: str, product: FinancialProduct) -> Instrument:
	asset = currency
	apr = _to_decimal(product.baseApr or product.showApr or "0")
	yield_asset = product.profitCurrency or asset
	min_qty = _to_decimal(product.minPledgeQuantity)
	per_max = product.perPledgeMaxQuantity
	max_qty = None if str(per_max) == "-1" else _to_decimal(per_max)
	invest_type = product.investPeriodType or product.financialType

	url = product.shareUrl or 'https://www.mexc.com/earn'

	if invest_type == "FIXED":
		days = product.fixedInvestPeriodCount
		duration = timedelta(days=int(days)) if days is not None else timedelta()
		return Fixed(
			type="fixed",
			asset=asset,
			apr=apr,
			yield_asset=yield_asset,
			min_qty=min_qty,
			max_qty=max_qty,
			url=url,
			duration=duration,
		)
	else:
		return Flexible(
			type="flexible",
			asset=asset,
			apr=apr,
			yield_asset=yield_asset,
			min_qty=min_qty,
			max_qty=max_qty,
			url=url,
		)


class Instruments(_Instruments, SdkMixin):
	@wrap_exceptions
	async def instruments(
		self, *, types: Sequence[InstrumentType] | None = None,
		assets: Sequence[str] | None = None,
	) -> Sequence[Instrument]:
		data = await fetch_financial_products_list_v2()
		types_set = set(types) if types is not None else None
		assets_set = set(assets) if assets is not None else None
		include_flexible = types_set is None or "flexible" in types_set
		include_fixed = types_set is None or "fixed" in types_set

		out: list[Instrument] = []
		for group in data:
			currency = group.currency
			if assets_set is not None and currency not in assets_set:
				continue
			for product in group.financialProductList:
				if product.soldOut:
					continue
				invest_type = product.investPeriodType or product.financialType
				if invest_type == "FIXED" and not include_fixed:
					continue
				if invest_type != "FIXED" and not include_flexible:
					continue
				inst = _parse_product(currency, product)
				out.append(inst)
		return out
