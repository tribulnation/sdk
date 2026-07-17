# Hyperliquid Market

> Spot **and** perpetuals. `tribulnation-hyperliquid`, venue name `hyperliquid`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Hyperliquid-specific.

## Account configuration

`accounts.Hyperliquid` (from `tribulnation.sdk`):

| Field | Default | Notes |
| --- | --- | --- |
| `venue` | `'hyperliquid'` | `'hyperliquid'` = mainnet, `'hyperliquid_testnet'` = testnet. |
| `address` | `'$HYPERLIQUID_ADDRESS'` | Wallet address (`0x…`). Read-only if no private key is given. |
| `private_key` | `'$HYPERLIQUID_PRIVATE_KEY'` | Wallet private key (`0x…`), used to sign. |
| `public` | `False` | If `True`, missing credentials are tolerated (read-only). |

`$NAME` fields resolve from the environment (`accounts.Hyperliquid()` reads
`$HYPERLIQUID_ADDRESS`/`$HYPERLIQUID_PRIVATE_KEY`). Mainnet vs testnet is driven by
`venue`; `MarketSDK` builds the HTTP client with `mainnet=(venue == 'hyperliquid')`.

The built-in default account `hyperliquid` is `accounts.Hyperliquid(public=True)`
(public/read-only).

## Exchanges & ID conventions

Hyperliquid exposes several exchanges under one venue. `exchanges()` reports:

| `exchange_id` | Type | What it is |
| --- | --- | --- |
| `spot` | spot | The spot exchange. |
| `''` (empty) | perp | The default perpetuals DEX. |
| `<dex-name>` | perp | A named builder-deployed perp DEX. |

For perps, **`exchange_id` is the DEX name**; the empty string means the default/no-DEX
universe. Under the hood `perp_exchange(dex)` treats `''` and `None` equivalently.

Market IDs by exchange:

- **Perp** — the asset name, e.g. `BTC`. Full ID: `hyperliquid::BTC` (empty exchange
  segment = default DEX) or `hyperliquid:<dex>:BTC`.
- **Spot** — canonical form `BASE/QUOTE:ASSET_IDX`, e.g. `BTC/USDC:0`. Full ID:
  `hyperliquid:spot:BTC/USDC:0`. The `ASSET_IDX` is Hyperliquid's `spotMeta.universe[].index`;
  `market()` cross-checks that the `BASE/QUOTE` names match that index and raises on
  mismatch. `Exchange.markets()` returns fully-formed `BASE/QUOTE:IDX` strings you can pass
  straight back in.

## Settings

`place_order` and `index` accept `settings={'hyperliquid': {...}}`, typed by the
`Settings` TypedDict (`core/settings.py`). All keys are optional:

| Key | Type | Applies to | Meaning |
| --- | --- | --- | --- |
| `reduce_only` | `bool` | `place_order` | Place as reduce-only. |
| `limit_tif` | `TimeInForce` | `place_order` | Time-in-force for limit orders. |
| `index_price` | `'oracle' \| 'mark'` | `index` (perp) | Which price `index()` returns; defaults to `'oracle'`. |

`index_price='mark'` returns the market's mark price, falling back to the oracle price when
mark is unavailable; the default `'oracle'` always returns the oracle price.

## Venue-specific semantics

- Spot and perp markets are separate objects (`SpotMarket` / `PerpMarket`) with their own
  rules and position logic. Only `PerpMarket` exposes funding and `index()`.
- Perp `available_notional`/leverage and spot balances are computed against
  Hyperliquid-native metadata (asset/collateral tokens, user fees), cached venue-wide and
  refreshed lazily.
- **`perp_collateral`** at the exchange level returns the account **cross** pool from
  `clearinghouse_state` (`equity=crossMarginSummary.accountValue`,
  `initial_margin=equity-withdrawable`, `maintenance_margin=crossMaintenanceMarginUsed`,
  `free_collateral=withdrawable`, `leverage=totalNtlPos/accountValue`,
  `margin_mode='cross'`). `Market.perp_collateral()` is **mode-aware**: it finds the asset in
  `assetPositions` and branches on the position's leverage type — a cross position reports the
  same cross pool, while an **isolated** position gets its own bucket from that position's
  `rawUsd + unrealizedPnl` (equity), `marginUsed` (= `initial_margin`), and
  `margin_mode='isolated'`. HL gives no isolated maintenance figure directly, so it is
  approximated as `positionValue / (2 · maxLeverage)` (half the initial-margin fraction at max
  leverage).
- **`collateral`** (spot) returns the quote-token balance (`equity=total`,
  `free_collateral=total-hold`).
- Builder-DEX perps use a DEX-scoped asset-id formula (`100000 + dex_idx*10000 + asset_idx`);
  default-DEX perps use the plain asset index. This only matters internally — you address
  markets by name.

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()

sdk = MarketSDK({'hl': accounts.Hyperliquid()})

# default-DEX perp
await sdk.index('hl::BTC')

# spot
book = await sdk.depth('hl:spot:BTC/USDC:0')

await sdk.place_order('hl::ETH', {
  'type': 'LIMIT', 'qty': 0.01, 'price': 1000,
}, settings={'hyperliquid': {'limit_tif': 'Alo', 'reduce_only': False}})
```
