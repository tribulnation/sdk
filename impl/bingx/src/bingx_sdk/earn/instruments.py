import os
import json
import math
import time
import uuid
import hashlib
from datetime import timedelta
from decimal import Decimal
from typing_extensions import Sequence

import httpx

from tribulnation.sdk.earn.instruments import (
	Fixed,
	Flexible,
	Instrument,
	Instruments as _Instruments,
	InstrumentType,
)

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


def _to_decimal(v: str | int | Decimal) -> Decimal:
	if isinstance(v, Decimal):
		return v
	return Decimal(str(v))


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


async def _fetch_product_list() -> dict:
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
	async with httpx.AsyncClient(timeout=30.0) as client:
		r = await client.get(url, params=params, headers=headers)
		r.raise_for_status()
		return r.json()


def _parse_product_group(group: dict) -> list[Instrument]:
	asset = group.get("assetName") or ""
	out: list[Instrument] = []
	if not asset:
		return out
	for product in group.get("products", []) or []:
		if product.get("soldOut"):
			continue
		apy = product.get("apy") or "0"
		apr = _to_decimal(apy) / Decimal("100")
		duration = product.get("duration")
		duration_days = None
		if duration is not None:
			try:
				duration_days = int(duration)
			except (TypeError, ValueError):
				duration_days = None
		is_fixed = duration_days is not None and duration_days > 0
		tier_rules = (product.get("tieredApyRule") or {}).get("rules") or []
		if tier_rules and not is_fixed:
			for rule in tier_rules:
				rule_apr = _to_decimal(rule.get("apy") or "0") / Decimal("100")
				low = rule.get("low")
				high = rule.get("high")
				min_qty = _to_decimal(low) if low is not None else None
				max_qty = _to_decimal(high) if high is not None else None
				out.append(Flexible(
					type="flexible",
					asset=asset,
					apr=rule_apr,
					yield_asset=asset,
					min_qty=min_qty,
					max_qty=max_qty,
					url=BINGX_EARN_URL,
				))
			continue

		if is_fixed:
			out.append(Fixed(
				type="fixed",
				asset=asset,
				apr=apr,
				yield_asset=asset,
				min_qty=None,
				max_qty=None,
				url=BINGX_EARN_URL,
				duration=timedelta(days=duration_days),
			))
		else:
			out.append(Flexible(
				type="flexible",
				asset=asset,
				apr=apr,
				yield_asset=asset,
				min_qty=None,
				max_qty=None,
				url=BINGX_EARN_URL,
			))
	return out


class Instruments(_Instruments):
	async def instruments(
		self, *, types: Sequence[InstrumentType] | None = None,
		assets: Sequence[str] | None = None,
	) -> Sequence[Instrument]:
		data = await _fetch_product_list()
		if data.get("code") not in (0, "0"):
			raise RuntimeError(f"BingX API error: {data}")
		result = data.get("data", {}).get("result", []) or []
		parsed: list[Instrument] = []
		for group in result:
			parsed.extend(_parse_product_group(group))

		if types is not None:
			types_set = set(types)
			parsed = [p for p in parsed if p.type in types_set]
		if assets is not None:
			assets_set = set(assets)
			parsed = [p for p in parsed if p.asset in assets_set]
		return parsed
