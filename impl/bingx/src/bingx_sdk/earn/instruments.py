import os
import json
import math
import time
import uuid
import hashlib
from datetime import timedelta
from decimal import Decimal
from typing_extensions import Collection, Iterable, Sequence

import httpx
import pydantic

from trading_sdk.core import ApiError, NetworkError, ValidationError
from trading_sdk.earn.instruments import Instrument, Instruments as _Instruments

BINGX_EARN_URL = "https://bingx.com/en-us/wealth"
BINGX_APP_VERSION = os.environ.get("BINGX_APP_VERSION", "5.2.45")
BINGX_APP_ID = os.environ.get("BINGX_APP_ID", "30004")
BINGX_MAIN_APP_ID = os.environ.get("BINGX_MAIN_APP_ID", "10009")
BINGX_PLATFORM_ID = os.environ.get("BINGX_PLATFORM_ID", "30")
BINGX_APP_SITE_ID = os.environ.get("BINGX_APP_SITE_ID", "0")
BINGX_CHANNEL = os.environ.get("BINGX_CHANNEL", "official")

_ENCRYPTION_KEYS = {
	"p1": "95d65c73dc5c437",
	"p2": "0ae9018fb7",
	"p3": "f2eab69",
}


def _clean_object(obj: object) -> object:
	if isinstance(obj, dict):
		for k in list(obj.keys()):
			v = obj[k]
			if isinstance(v, (dict, list)):
				_clean_object(v)
			if v is None:
				obj.pop(k, None)
				continue
			if isinstance(v, float) and math.isnan(v):
				obj.pop(k, None)
				continue
			if isinstance(v, dict) and len(v) == 0:
				obj.pop(k, None)
		return obj
	if isinstance(obj, list):
		for v in obj:
			if isinstance(v, (dict, list)):
				_clean_object(v)
		return obj
	return obj


def _normalize_values(obj: object) -> object:
	if isinstance(obj, dict):
		return {k: _normalize_values(v) for k, v in obj.items()}
	if isinstance(obj, list):
		return [_normalize_values(v) for v in obj]
	if isinstance(obj, bool):
		return str(obj).lower()
	if isinstance(obj, (int, float)):
		return str(obj).upper()
	return obj


def _stable_json(obj: object) -> str:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _build_sign(*, timestamp: int, trace_id: str, device_id: str, platform_id: str, app_version: str,
	anti_device_id: str, payload: dict) -> str:
	payload_clean = _clean_object(payload or {})
	payload_clean = _normalize_values(payload_clean)
	payload_json = _stable_json(payload_clean) if payload_clean and payload_clean != {} else "{}"
	encryption = (
		f"{_ENCRYPTION_KEYS['p1']}{_ENCRYPTION_KEYS['p2']}{_ENCRYPTION_KEYS['p3']}"
		f"{timestamp}{trace_id}{device_id}{platform_id}{app_version}{anti_device_id}{payload_json}"
	)
	return hashlib.sha256(encryption.encode("utf-8")).hexdigest().upper()

class TierRule(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	low: Decimal | None = None
	high: Decimal | None = None
	apy: Decimal
	level: int | None = None

class TieredApyRule(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	rules: list[TierRule] = []

class ProductTag(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	tagId: int | None = None
	tagType: int | None = None
	tagDesc: str | None = None
	tagAlertMsg: str | None = None
	tagJumpUrl: str | None = None

class Product(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	productId: int | str
	productType: int | None = None
	duration: int | str | None = None
	productName: str | None = None
	apy: Decimal
	soldOut: int | bool = False
	tieredApyRule: TieredApyRule | None = None
	tags: list[ProductTag] | None = None

class ProductGroup(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	assetName: str
	products: list[Product] = []

class ProductListData(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	result: list[ProductGroup] = []
	searchResult: list[ProductGroup] | bool | None = None
	total: int | None = None

class ProductListResponse(pydantic.BaseModel):
	model_config = {"extra": "allow"}
	code: int
	timestamp: int | None = None
	msg: str | None = None
	data: ProductListData | None = None


async def _fetch_product_list() -> ProductListResponse:
	params = {"searchType": "", "dataType": "", "assetName": "", "orderBy": ""}
	trace_id = uuid.uuid4().hex
	device_id = os.environ.get("BINGX_DEVICE_ID", uuid.uuid4().hex)
	anti_device_id = os.environ.get("BINGX_ANTI_DEVICE_ID", uuid.uuid4().hex)
	stamp = int(time.time() * 1000)

	headers = {
		"accept": "application/json, text/plain, */*",
		"app_version": BINGX_APP_VERSION,
		"appid": BINGX_APP_ID,
		"mainappid": BINGX_MAIN_APP_ID,
		"platformid": BINGX_PLATFORM_ID,
		"appsiteid": BINGX_APP_SITE_ID,
		"channel": BINGX_CHANNEL,
		"reg_channel": BINGX_CHANNEL,
		"device_id": device_id,
		"antideviceid": anti_device_id,
		"traceid": trace_id,
		"timestamp": str(stamp),
	}
	headers["sign"] = _build_sign(
		timestamp=stamp,
		trace_id=trace_id,
		device_id=device_id,
		platform_id=BINGX_PLATFORM_ID,
		app_version=BINGX_APP_VERSION,
		anti_device_id=anti_device_id,
		payload=params,
	)

	url = "https://api-app.qq-os.com/api/wealth-sales-trading/v1/product/list"
	try:
		async with httpx.AsyncClient(timeout=30.0) as client:
			r = await client.get(url, params=params, headers=headers)
			r.raise_for_status()
	except httpx.HTTPError as e:
		raise NetworkError(*e.args) from e
	try:
		return ProductListResponse.model_validate(r.json())
	except pydantic.ValidationError as e:
		raise ValidationError(*e.args) from e


def _parse_duration(duration: int | str | None) -> timedelta | None:
	if duration is None:
		return None
	try:
		days = int(duration)
	except (TypeError, ValueError):
		return None
	if days <= 0:
		return None
	return timedelta(days=days)

def _extract_tags(product: Product) -> tuple[list[Instrument.Tag], bool]:
	tags: list[Instrument.Tag] = []
	is_vip = False
	for tag in (product.tags or []):
		desc = (tag.tagDesc or "").strip()
		if not desc:
			continue
		desc_lower = desc.lower()
		if desc_lower == "vip":
			is_vip = True
			continue
		if "new user" in desc_lower:
			tags.append("new-users")
		if "one-time" in desc_lower:
			tags.append("one-time")
	return tags, is_vip


def _parse_product_group(group: ProductGroup) -> Iterable[Instrument]:
	asset = group.assetName or ""
	out: list[Instrument] = []
	if not asset:
		return out
	for product in group.products:
		if bool(product.soldOut):
			continue
		extra_tags, is_vip = _extract_tags(product)
		if is_vip:
			continue
		apr = Decimal(str(product.apy)) / Decimal("100")
		duration = _parse_duration(product.duration)
		is_fixed = duration is not None
		tier_rules = (product.tieredApyRule.rules if product.tieredApyRule else [])
		if tier_rules and not is_fixed:
			for rule in tier_rules:
				rule_apr = Decimal(str(rule.apy)) / Decimal("100")
				min_qty = Decimal(str(rule.low)) if rule.low is not None else None
				max_qty = Decimal(str(rule.high)) if rule.high is not None else None
				out.append(
					Instrument(
						tags=["flexible", *extra_tags],
						asset=asset,
						apr=rule_apr,
						min_qty=min_qty,
						max_qty=max_qty,
						url=BINGX_EARN_URL,
						id=str(product.productId),
					)
				)
			continue

		if is_fixed:
			out.append(
				Instrument(
					tags=["fixed", *extra_tags],
					asset=asset,
					apr=apr,
					min_qty=None,
					max_qty=None,
					url=BINGX_EARN_URL,
					duration=duration,
					id=str(product.productId),
				)
			)
		else:
			out.append(
				Instrument(
					tags=["flexible", *extra_tags],
					asset=asset,
					apr=apr,
					min_qty=None,
					max_qty=None,
					url=BINGX_EARN_URL,
					id=str(product.productId),
				)
			)
	return out


class Instruments(_Instruments):
	async def instruments(
		self, *, tags: Collection[Instrument.Tag] | None = None,
		assets: Sequence[str] | None = None,
	) -> Sequence[Instrument]:
		data = await _fetch_product_list()
		if data.code != 0:
			raise ApiError(f"BingX API error: {data}")
		result = data.data.result if data.data else []
		parsed: list[Instrument] = []
		for group in result:
			parsed.extend(_parse_product_group(group))

		if tags is not None:
			tags_set = set(tags)
			parsed = [p for p in parsed if any(t in tags_set for t in p.tags)]
		if assets is not None:
			assets_set = set(assets)
			parsed = [p for p in parsed if p.asset in assets_set]
		return parsed
