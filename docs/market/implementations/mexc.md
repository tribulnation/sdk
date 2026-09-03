<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# MEXC Market

> Spot only. `tribulnation-mexc`, venue name `mexc`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is MEXC-specific.

## Account

Mainnet only, no testnet. `validate` toggles pydantic validation of API responses. The
built-in `mexc` account is `accounts.Mexc(public=True)`, read-only.

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
await sdk.place_order(
  'mexc_account1:spot:BTCUSDT',
  {
    'type': 'LIMIT',
    'qty': 0.001,
    'price': 60_000,
  },
)
```

<!-- next -->

---

← [Hyperliquid Market](hyperliquid.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
