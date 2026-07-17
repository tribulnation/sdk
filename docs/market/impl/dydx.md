# dYdX Market

> Perpetuals only. `tribulnation-dydx`, venue name `dydx`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is dYdX-specific.

## Account configuration

`accounts.Dydx` (from `tribulnation.sdk`):

| Field | Default | Notes |
| --- | --- | --- |
| `venue` | `'dydx'` | `'dydx'` = mainnet, `'dydx_testnet'` = testnet. |
| `address` | `'$DYDX_ADDRESS'` | Account address (`dydx1…`). |
| `mnemonic` | `'$DYDX_MNEMONIC'` | Account mnemonic (12–24 words). Used to sign. |
| `parent_subaccount` | `0` | dYdX parent subaccount number (see below). |
| `public` | `False` | If `True`, missing credentials are tolerated (read-only). |

String fields of the form `$NAME` are resolved from the environment (`accounts.Dydx()`
reads `$DYDX_ADDRESS`/`$DYDX_MNEMONIC`); pass literals or other `$VAR` names to override.
Selecting testnet vs mainnet is driven purely by `venue` — `MarketSDK` builds the client
with `mainnet=(venue == 'dydx')`.

The built-in default account `dydx` is `accounts.Dydx(public=True)` (public/read-only).

**Either `address` or `mnemonic` must resolve to a value.** The address is required for all
indexer reads (subaccount, positions, orders, collateral). The mnemonic is only needed for
signing (placing/canceling orders). When both are provided, `address` is used directly;
when only `mnemonic` is given, the address is derived from it at construction time.

## Exchange & ID conventions

- The only exchange is `perp` (`exchange_id == 'perp'`); any other exchange ID raises.
- Market IDs are dYdX tickers: `<BASE>-USD`, e.g. `BTC-USD`, `ETH-USD`.
- Full SDK ID: `dydx:perp:BTC-USD` (or `<your-account-key>:perp:BTC-USD`).

### Subaccounts — the exchange qualifier

A dYdX subaccount is a margin/liquidation bucket, so it lives on the **exchange**, not on the
market ID. The exchange qualifier selects it:

| `exchange_id` | Selects |
| --- | --- |
| `perp` | the account's **parent** subaccount (`parent_subaccount`, the default cross pool). |
| `perp.<N>` | subaccount `<N>`, validated `N % 128 == parent_subaccount`. |

So `dydx:perp:BTC-USD` addresses the parent/cross pool and `dydx:perp.256:XAUT-USD` addresses
child subaccount `256` (isolated). Child subaccounts of parent `p` are `p, 128+p, 256+p, …`;
any `N` failing `N % 128 == p` raises. Markets **inherit** the subaccount from their exchange,
so every account-scoped method (`place_order`, `open_orders`, `query_order`, `perp_position`,
`available_notional`, `perp_collateral`) keys off the same bucket by construction.

> **Migration:** the old `<BASE>-USD:<N>` market-ID suffix (`parse_market_id`) has been
> **retired** in both `exchange.py` and `venue.py`. It was only half-wired — `place_order`/
> `cancel_order`/`available_notional` honored it while `open_orders`/`query_order`/
> `perp_position` ignored it and read the parent subaccount — and grep confirmed no callers
> used it. Move any `dydx:perp:BTC-USD:<N>` usage to `dydx:perp.<N>:BTC-USD`. The `.`-qualifier
> lives inside the exchange segment, so it does not disturb the top-level
> `<account>:<exchange>:<market>` colon split.

**Reads: aggregate vs scoped.** The bare `perp` (parent) exchange reads *parent-aggregate*
history across the parent's child subaccounts (coherent for additive reads like trades and
funding). A qualified `perp.<N>` exchange scopes those reads to exactly that child subaccount.
Collateral never aggregates — it is always scoped to the addressed subaccount's own bucket.

## Settings

`place_order` / `cancel_order` accept `settings={'dydx': {...}}`, typed by the dYdX
`Settings` TypedDict (`market/impl/mixin.py`). All keys are optional:

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `order_flags` | `'SHORT_TERM' \| 'LONG_TERM' \| 'CONDITIONAL'` | `'LONG_TERM'` | Order flags applied to all orders. |
| `limit_tif` | `TimeInForce` | `'GOOD_TIL_TIME'` | Time-in-force for `LIMIT` orders. |
| `market_tif` | `TimeInForce` | `'IMMEDIATE_OR_CANCEL'` | Time-in-force for `MARKET` orders. |
| `short_term_gtb` | `int` | — | GTB delta for short-term orders: good-til-block = `current_block + short_term_gtb`. Only applied when `order_flags == 'SHORT_TERM'`. |
| `long_term_gtbt` | `int` | — | GTBT delta (seconds) for long-term orders: good-til-block-time = `current_block_time + long_term_gtbt`. Only applied for `LONG_TERM`/`CONDITIONAL` flags. |
| `reduce_only` | `bool` | `False` | Place as reduce-only. |

Type mapping: `POST_ONLY` orders always use TIF `POST_ONLY`; `MARKET` uses `market_tif`;
`LIMIT` uses `limit_tif`.

## Venue-specific semantics

- **`available_notional`** = subaccount `freeCollateral` × the market's maximum leverage,
  where max leverage is `1 / effective_IMF` (the initial-margin fraction, adjusted upward
  by open-interest caps per the dYdX margining docs).
- **`perp_collateral`** returns the addressed subaccount's bucket. `equity` and
  `free_collateral` come straight from the indexer `get_subaccount` fields;
  `initial_margin` = `equity - free_collateral` (what dYdX's UI shows as "margin usage");
  `maintenance_margin` = Σ`|notional|·effective_mmf` and `leverage` = Σ`|notional|/equity`
  over the subaccount's open positions, priced at each market's `oraclePrice`. `margin_mode`
  is `'cross'` when the subaccount is `< 128` (parent) else `'isolated'` (child). dYdX
  exposes no per-market mode, so `Market.perp_collateral()` just delegates to its exchange.
  Maintenance margin is derived via `effective_mmf` — the base `maintenanceMarginFraction`
  scaled by the same open-interest factor as `effective_IMF`
  (`effective_imf · base_mmf / base_imf`), so it isn't understated at high OI.
- **`index`** returns the market's `oraclePrice`; it raises `ApiError` if unavailable.
- **`perp_position`** aggregates all open positions for the parent subaccount in that
  market into a single net size and average entry price.
- **`query_order`** is overridden to query the indexer directly, so it can return
  filled/canceled states — not just open ones.
- **`cancel_orders`** splits by flag: short-term orders (`order_flags == 0`) go through a
  batch cancel, long-term orders are cancelled one by one.
- Order IDs returned by the SDK are base64-encoded dYdX protocol `OrderId`s.

## Example: short-term IOC order

The `settings` payload maps directly onto dYdX order flags and expiry:

```python
import os
from tribulnation.sdk import MarketSDK, accounts
from dotenv import load_dotenv

load_dotenv()

market = MarketSDK({
  'dydx-account1': accounts.Dydx(),
})

await market.place_order('dydx-account1:perp:BTC-USD', {
  'price': 10,
  'qty': 0.00001,
  'type': 'LIMIT'
}, settings={
  'dydx': {
    'limit_tif': 'IMMEDIATE_OR_CANCEL',
    'order_flags': 'SHORT_TERM',
    'short_term_gtb': 2
  }
})
```
