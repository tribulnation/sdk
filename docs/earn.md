# Earn Interface

## Overview

`Earn` exposes earn products as typed instruments with APR, limits, and optional duration.

## Types

`Instrument`
- `tags`: `Sequence[InstrumentTag]`
- `asset`: subscription asset
- `apr`: annual percent rate as a fraction of 1 (0.01 = 1%)
- `yield_asset`: asset paid as yield (optional)
- `min_qty`, `max_qty`: quantity limits (optional)
- `url`: product URL (optional)
- `duration`: `timedelta` for fixed-term products (optional)
- `id`: exchange-specific identifier (optional)

`InstrumentTag`
- `flexible`, `fixed`, `one-time`, `new-users`, `staking`

## Methods

`instruments(tags: Collection[InstrumentTag] | None = None, assets: Collection[str] | None = None) -> Sequence[Instrument]`
- When filters are `None`, returns all instruments.
- When filters are provided, returns instruments matching any of the tags and/or the specified assets.

## Related

- `sdk/src/trading_sdk/earn/instruments.py`
