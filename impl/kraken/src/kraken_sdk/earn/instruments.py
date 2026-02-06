"""
Kraken earn strategies → SDK instruments.

Lock types:
- instant: Flexible (can deallocate without unbonding)
- flex: "Kraken rewards" on spot balances (account-wide, no manual allocate) → Flexible
- bonded: Fixed (has unbonding period) → Fixed
"""
from datetime import timedelta
from decimal import Decimal
from typing import Any
from typing_extensions import Sequence

from pydantic import BaseModel

from tribulnation.sdk.earn.instruments import (
    Fixed,
    Flexible,
    Instrument,
    Instruments as _Instruments,
    InstrumentType,
)
from kraken_sdk.core import SdkMixin

KRAKEN_EARN_URL = 'https://pro.kraken.com/app/earn'


def _to_decimal(v: Decimal | str | int | None) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


# --- Pydantic models for Kraken API response ---


class AprEstimate(BaseModel):
    low: str
    high: str


class EarnStrategyItem(BaseModel):
    id: str
    asset: str
    asset_class: str = "currency"
    lock_type: dict[str, Any]  # Validated dynamically
    apr_estimate: AprEstimate
    user_min_allocation: str | None = None
    user_cap: str | None = None
    allocation_fee: str = "0"
    deallocation_fee: str = "0"
    can_allocate: bool = True
    can_deallocate: bool = True


def _parse_lock_type(lock_type: dict[str, Any]) -> tuple[InstrumentType, timedelta | None]:
    """Return (type, duration). duration is only for fixed."""
    t = lock_type.get("type")
    if t == "instant" or t == "flex":
        return ("flexible", None)
    if t == "bonded":
        secs = lock_type.get("unbonding_period", 0) or 0
        return ("fixed", timedelta(seconds=secs))
    raise ValueError(f"Unknown lock_type: {lock_type}")


def _parse_strategy(raw: EarnStrategyItem) -> Instrument | None:
    inst_type, duration = _parse_lock_type(raw.lock_type)
    apr_low = _to_decimal(raw.apr_estimate.low) or Decimal("0")
    apr_high = _to_decimal(raw.apr_estimate.high) or Decimal("0")
    # Kraken returns percentage (e.g. 10 = 10%); convert to [0, 1] (0.1 = 10%)
    apr = (apr_low + apr_high) / 2 / 100
    min_qty = _to_decimal(raw.user_min_allocation)
    max_qty = _to_decimal(raw.user_cap)
    yield_asset = raw.asset  # Kraken pays yield in same asset

    if inst_type == "flexible":
        return Flexible(
            type="flexible",
            asset=raw.asset,
            apr=apr,
            yield_asset=yield_asset,
            min_qty=min_qty,
            max_qty=max_qty,
            url=KRAKEN_EARN_URL,
        )
    else:
        assert duration is not None
        return Fixed(
            type="fixed",
            asset=raw.asset,
            apr=apr,
            yield_asset=yield_asset,
            min_qty=min_qty,
            max_qty=max_qty,
            url=KRAKEN_EARN_URL,
            duration=duration,
        )


class Instruments(SdkMixin, _Instruments):
    async def instruments(
        self,
        *,
        types: Sequence[InstrumentType] | None = None,
        assets: Sequence[str] | None = None,
    ) -> Sequence[Instrument]:
        r = await self.client.private_post_earn_strategies()
        # Kraken returns {error: [], result: {items: [...], next_cursor: ...}}
        if r.get("error"):
            raise RuntimeError(f"Kraken API error: {r['error']}")
        result = r.get("result") or {}
        items = result.get("items") or []
        validated = [EarnStrategyItem.model_validate(x) for x in items]
        parsed: list[Instrument] = []
        for v in validated:
            try:
                inst = _parse_strategy(v)
                if inst is not None:
                    parsed.append(inst)
            except (ValueError, KeyError):
                continue  # Skip unknown lock types
        if types is not None:
            types_set = set(types)
            parsed = [p for p in parsed if p.type in types_set]
        if assets is not None:
            assets_set = set(assets)
            parsed = [p for p in parsed if p.asset in assets_set]
        return parsed
