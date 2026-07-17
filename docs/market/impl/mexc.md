# MEXC Market

> Spot only. `tribulnation-mexc`, venue name `mexc`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is MEXC-specific.

## Account configuration

`accounts.Mexc` (from `tribulnation.sdk`):

| Field | Default | Notes |
| --- | --- | --- |
| `venue` | `'mexc'` | Only mainnet; no testnet. |
| `api_key` | `'$MEXC_API_KEY'` | MEXC API key. |
| `api_secret` | `'$MEXC_API_SECRET'` | MEXC API secret. |
| `validate` | `True` | Type-validate incoming API responses (pydantic). |
| `public` | `False` | If `True`, missing credentials are tolerated (read-only). |

`$NAME` fields resolve from the environment (`accounts.Mexc()` reads
`$MEXC_API_KEY`/`$MEXC_API_SECRET`). `MarketSDK` builds the client with
`MexcMarket.new(api_key=…, api_secret=…, validate=account.validate)`.

The built-in default account `mexc` is `accounts.Mexc(public=True)` (public/read-only).

## Exchange & ID conventions

- The only exchange is `spot` (`exchange_id == 'spot'`); any other exchange ID raises.
- Market IDs are MEXC symbols, e.g. `BTCUSDT`, `ETHUSDT`.
- Full SDK ID: `mexc:spot:BTCUSDT` (or `<your-account-key>:spot:BTCUSDT`).
- `Exchange.markets()` returns the symbol keys from the venue's exchange-info.

## Venue-specific semantics

- Spot only — there is no `PerpMarket`/`PerpExchange`, so `perp_exchange`, `index`,
  `next_funding`, `funding_*`, and `perp_position` are unsupported for this venue.
- `available_notional` (spot) returns the free quote-token balance.
- `collateral` (spot) reports the quote-asset balance: `equity = free + locked`,
  `free_collateral = free`. There is no perp bucket, so only the base `Collateral` type
  applies (no `maintenance_margin`/`leverage`/`margin_mode`).
- `MARKET` order support follows the generic contract: where a native market order isn't
  used, an aggressive limit at the supplied `price` is placed instead.
- `place_order`/`cancel_order` take no MEXC-specific `settings` keys today (there is no
  MEXC entry in the shared `Settings` TypedDict).

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()

sdk = MarketSDK({'mexc_account1': accounts.Mexc()})

book = await sdk.depth('mexc_account1:spot:BTCUSDT')
await sdk.place_order('mexc_account1:spot:BTCUSDT', {
  'type': 'LIMIT', 'qty': 0.001, 'price': 60_000,
})
```
