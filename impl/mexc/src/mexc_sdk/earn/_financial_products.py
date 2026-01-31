"""
Fetch MEXC financial products list (public API).

API: GET https://www.mexc.com/api/financialactivity/financial/products/list/V2
"""
from typing import Any, TypedDict

import httpx
from pydantic import BaseModel, Field

MEXC_FINANCIAL_PRODUCTS_LIST_V2_URL = "https://www.mexc.com/api/financialactivity/financial/products/list/V2"


# --- TypedDicts (API shape) ---


class TieredSubsidyAprDict(TypedDict):
	startQuantity: str
	endQuantity: str | None
	apr: str


class FinancialProductDict(TypedDict, total=False):
	financialId: str
	financialType: str
	investPeriodType: str
	fixedInvestPeriodType: int | None
	fixedInvestPeriodCount: int | None
	currencyId: str
	currency: str
	currencyIcon: str
	showApr: str
	showAprMaxTip: bool
	subsidyTieredFlag: bool
	baseApr: str
	subsidyApr: str
	tieredSubsidyApr: list[TieredSubsidyAprDict] | None
	financialState: int
	startTime: int
	endTime: int | None
	soldOut: bool
	sort: int
	memberType: str
	profitCurrency: str | None
	profitCurrencyId: str | None
	profitCurrencyIcon: str | None
	minPledgeQuantity: str
	perPledgeMaxQuantity: str
	userPledgeQuantityFull: bool
	shareUrl: str | None


class CurrencyGroupDict(TypedDict):
	currencyId: str
	currency: str
	currencyIcon: str
	minApr: str
	maxApr: str
	hasAprRange: bool
	investPeriodTypes: list[str]
	financialProductList: list[FinancialProductDict]
	sort: int


class FinancialProductsListV2ResponseDict(TypedDict):
	data: list[CurrencyGroupDict]
	code: int
	msg: str
	timestamp: int


# --- Pydantic models for validation ---


class TieredSubsidyApr(BaseModel):
	startQuantity: str
	endQuantity: str | None
	apr: str


class FinancialProduct(BaseModel):
	financialId: str
	financialType: str  # FLEXIBLE | FIXED | BLC_EARN
	investPeriodType: str  # FLEXIBLE | FIXED
	fixedInvestPeriodType: int | None = None  # 2 = days
	fixedInvestPeriodCount: int | None = None
	currencyId: str
	currency: str
	currencyIcon: str
	showApr: str
	showAprMaxTip: bool = False
	subsidyTieredFlag: bool = False
	baseApr: str
	subsidyApr: str
	tieredSubsidyApr: list[TieredSubsidyApr] | None = None
	financialState: int = Field(alias="financialState")
	startTime: int = Field(alias="startTime")
	endTime: int | None = Field(None, alias="endTime")
	soldOut: bool = False
	sort: int = Field(alias="sort")
	memberType: str = Field(alias="memberType")
	profitCurrency: str | None = None
	profitCurrencyId: str | None = None
	profitCurrencyIcon: str | None = None
	minPledgeQuantity: str
	perPledgeMaxQuantity: str  # "-1" means no max
	userPledgeQuantityFull: bool = False
	shareUrl: str | None = None

	model_config = {"populate_by_name": True}


class CurrencyGroup(BaseModel):
	currencyId: str
	currency: str
	currencyIcon: str
	minApr: str
	maxApr: str
	hasAprRange: bool = False
	investPeriodTypes: list[str] = Field(default_factory=list, alias="investPeriodTypes")
	financialProductList: list[FinancialProduct] = Field(default_factory=list, alias="financialProductList")
	sort: int = Field(alias="sort")

	model_config = {"populate_by_name": True}


class FinancialProductsListV2Response(BaseModel):
	data: list[CurrencyGroup]
	code: int = 0
	msg: str = ""
	timestamp: int = 0


async def fetch_financial_products_list_v2() -> list[CurrencyGroup]:
	"""Fetch MEXC financial products list (public, no auth). Returns validated 'data' list."""
	async with httpx.AsyncClient(timeout=30.0) as client:
		resp = await client.get(
			MEXC_FINANCIAL_PRODUCTS_LIST_V2_URL,
			headers={"User-Agent": "mexc-sdk/1.0"},
		)
		resp.raise_for_status()
		body: Any = resp.json()
	parsed = FinancialProductsListV2Response.model_validate(body)
	return parsed.data
