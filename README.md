# Tribulnation SDK

[![PyPI](https://img.shields.io/pypi/v/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> Fully-typed, async Python SDK for crypto trading and data.

`Market`, `Wallet`, `Earn`, and `Report` are abstract interfaces implemented per exchange and chain. Code written against `MarketSDK` runs unchanged on dYdX, Hyperliquid, MEXC, or any other supported venue.

## Installation

```bash
pip install tribulnation-sdk[dydx,hyperliquid,mexc]
```

See the [support matrix](docs/support.md) for details on extras.

## Trading Quick Start

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv() # load credentials from .env file

sdk = MarketSDK({
  'mexc_account1': accounts.Mexc(api_key='$MEXC_API_KEY', api_secret='$MEXC_API_SECRET'),
  # 'dydx', 'hyperliquid', and 'mexc' are available by default, even without listing them here
})
mexc = await sdk.market('mexc_account1:spot:BTCUSDT')
dydx = await sdk.market('dydx:perp:BTC-USD')

async with mexc.trades_stream() as my_trades:
  async for my_trade in my_trades:
    print(f'Hedging {my_trade}')
    await dydx.place_order({
      'type': 'LIMIT',
      'qty': -my_trade.qty,
      'price': my_trade.price,
    })
```

`accounts.<Venue>()` reads credentials from environment variables named after each field (`accounts.Mexc()` reads `$MEXC_API_KEY`/`$MEXC_API_SECRET`) — pass explicit values or other `$VAR` names to override.

## Market IDs & Scoping

`<account_id>:<exchange_id>:<market_id>`, e.g. `mexc_account1:spot:BTCUSDT`. `account_id` is the key you registered in `accounts` — not necessarily the venue's own name — so you can run several accounts on one venue side by side. Equivalent ways to reach a market:

```python
await sdk.depth('mexc_account1:spot:BTCUSDT')

venue = await sdk.venue('mexc_account1')
await venue.depth('spot:BTCUSDT')

exchange = await venue.exchange('spot')
await exchange.depth('BTCUSDT')

market = await exchange.market('BTCUSDT')
await market.depth()
```

Hold a `Market` reference in hot loops; use the scoped one-shot calls otherwise.

## Market Interface

- Public data:
  - `depth() -> Book`
  - `depth_stream() -> AsyncContextManager[AsyncIterable[Book]]`
  - `rules() -> Rules`: tick/step size, fees, min/max, rounding helpers
- User data:
  - `query_order(id) -> OrderState | None`
  - `open_orders() -> Sequence[OrderState]`
  - `trades_history(start, end) -> AsyncIterable[Sequence[Trade]]`
  - `trades_stream() -> AsyncContextManager[AsyncIterable[Trade]]`
  - `position() -> Position`
  - `available_notional() -> Decimal`: max. notional you could open now
- Trading:
  - `place_order(order) -> OrderResponse`
  - `place_orders(orders) -> Sequence[OrderResponse]`
  - `cancel_order(id)`
  - `cancel_orders(ids)`
  - `cancel_open_orders()`
- Perpetual markets:
  - `index() -> Decimal`
  - `next_funding() -> FundingRate`
  - `funding_rates(start, end=None) -> AsyncIterable[Sequence[FundingRate]]`: market-wide rate history
  - `funding_payments(start, end) -> AsyncIterable[Sequence[FundingPayment]]`: your own settled cashflows
  - `perp_position() -> PerpPosition`: includes entry price

Full reference: [docs/market/index.md](docs/market/index.md), with per-venue notes for [dYdX](docs/market/impl/dydx.md), [Hyperliquid](docs/market/impl/hyperliquid.md), and [MEXC](docs/market/impl/mexc.md).

Mutating methods also take an optional `settings` dict for venue-specific options, keyed by venue:

```python
await dydx.place_order({
  'type': 'LIMIT', 'qty': 0.01, 'price': 60_000,
}, settings={'dydx': {'order_flags': 'SHORT_TERM', 'short_term_gtb': 2}})
```

## Other SDKs

Same account-mapping shape as `MarketSDK`:

- `WalletSDK`: deposit/withdrawal methods — [docs/wallet.md](docs/wallet.md)
- `EarnSDK`: yield instruments — [docs/earn.md](docs/earn.md)
- `ReportSDK`: balance/position history, with provenance — [docs/report.md](docs/report.md)

## Error Handling

All errors subclass `Error`: `NetworkError`, `ValidationError`, `ApiError` (`BadRequest`, `AuthError`, `RateLimited`), `LogicError`.

## Context, Logging & Retries

SDK calls are plain by default — no logging, no retries. Wrap them in a `Context` to add both:

```python
from tribulnation.sdk import Context, NetworkError, RateLimited

ctx = Context().retried(NetworkError, RateLimited, max_retries=5).logged()
with ctx.use():
  await sdk.place_order('mexc_account1:spot:BTCUSDT', {'type': 'LIMIT', 'qty': 0.01, 'price': 60_000})
```

Retries back off exponentially and only wrap plain async calls, not streams or paginated history. Nested SDK calls each re-apply the active context, so retries can compound across scoping layers. Details: [docs/context.md](docs/context.md).

## License

[MIT](LICENSE)
