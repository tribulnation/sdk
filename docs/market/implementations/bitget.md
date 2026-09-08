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

# Bitget Market

> Spot **and** USDT-margined perpetuals, read-only. `tribulnation-bitget`, venue name
> `bitget`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Bitget-specific.

## Account

`accounts.Bitget` takes an `access_key`, `secret_key` and `passphrase`. `uta` says whether
the account is a Unified Trading Account (`True`), a Classic account (`False`), or should
be auto-detected on the first account-scoped call (`None`, the default). `validate`
toggles pydantic validation of API responses. The built-in `bitget` account is
`accounts.Bitget(public=True)`: every public method works on it, every account-scoped
method raises `AuthError`.

## Exchanges & ID conventions

| `exchange_id` | Type | What it is |
| --- | --- | --- |
| `spot` | spot | Every spot pair. |
| `perp` | perp | Every USDT-margined perpetual contract (`USDT-FUTURES`). |

Market IDs are Bitget's concatenated symbols on both exchanges, e.g. `BTCUSDT`. Full SDK
ID: `bitget:spot:BTCUSDT` or `bitget:perp:BTCUSDT` (or `<your-account-key>:perp:BTCUSDT`).
`Exchange.markets()` returns the symbols of the public catalogue: every spot pair, and
every perpetual of the product line (delivery contracts, which pay no funding, are
dropped).

## Venue-specific semantics

- **Public data is mode-independent.** `markets`, `depth`, `depth_stream`, `tickers`,
  `rules`, `perp_stats`, `index`, `next_funding` and `funding_rates` read the venue's public
  endpoints, so they answer the same on a Classic account, a UTA account and the built-in
  public one. Account-scoped reads dispatch on the account's mode.
- **Trading is not implemented.** `place_order`, `cancel_order`, `cancel_orders` and
  `cancel_open_orders` raise `NotImplementedError`: Bitget is not a venue we trade on.
- **`rules`** come from the public symbol and contract catalogues, cached after the first
  call. Bitget publishes decimal-place counts rather than tick sizes, so `tick_size` and
  `step_size` are derived from them (`priceEndStep * 10 ** -pricePlace` on perps). The fee
  rates are the venue's default tier, not the account's. `min_value` is Bitget's
  USDT-denominated minimum notional, reported whatever the quote coin.
- **`depth`** on `spot` takes any `levels` (150 a side by default); on `perp` the venue
  serves a fixed depth of 1, 5, 15, 50 or 100 levels, so a request is served by the next
  size up and trimmed. **`depth_stream`** folds the `books` channel (a full snapshot, then
  deltas) into whole books; `levels` trims each delivered book.
- **`candles`** serves every `CandleInterval` (`CANDLE_INTERVALS` is the full set) on both
  exchanges, oldest page first; an open `start` buffers the whole backwards walk before
  the first page, since Bitget answers newest-first. `perp` reads the futures history
  endpoint in pages of 198 (two short of the 200-row cap the venue enforces, whatever the
  client declares, since Bitget counts a window's span in candle closes) back to the
  contract's listing. `spot` reads the recent endpoint in pages of 1000, which only
  keeps about two months of hourly candles (less at finer intervals): the spot history
  endpoint has no paged walk in the typed client yet, so a `start` past that horizon yields
  fewer candles than the window holds.
- **`perp_stats`** joins the futures ticker listing (index, mark, current rate, open
  interest) with the funding-rate listing (next settlement time and interval) -- two calls
  for the whole universe. Funding intervals vary per contract (1, 4 or 8 hours).
- **`funding_rates`** walks the venue's page-numbered history newest-first and stops once a
  page reaches back past `start`; a call with no `start` walks the whole history.
- **`funding_payments`** is not supported on either mode: Bitget publishes no closed set of
  futures ledger types (`businessType`, `futureTaxType`, `type` are all free text), so
  there is no documented settlement value to filter on.
- **`trades_history`** is served in 90-day windows, the widest the venue accepts. Classic
  spot and UTA fills reach back roughly 90 days and the venue rejects a window older than
  that (`43111` / `25200`); Classic futures fills reach further back. UTA's fill history has
  no symbol filter, so it is narrowed client-side.
- **`trades_stream`** subscribes to the private `fill` channel: per product line and symbol
  on Classic, one account-wide channel narrowed to the market on UTA.
- **`position`** on `spot` is the base-coin balance (available, frozen and locked on
  Classic; the unified pool's `balance` on UTA). **`perp_position`** nets a hedge-mode
  account's long and short rows into one signed size.
- **`collateral`** on a spot market is the quote-coin balance (`equity` = total,
  `free_collateral` = available); `available_notional` is that free part. The
  exchange-level pool (`collateral('bitget:spot')`) is the unified pool on UTA and
  unsupported on Classic, whose spot wallet has no pool-level figure.
- **`perp_collateral`** on UTA is the unified margin pool (`accountEquity`, `effEquity`,
  `imr`, `mmr`, `leverage`), with `margin_mode` read from the account's per-symbol
  settings (`cross` when the symbol has none, and always for the exchange-level pool).
  On Classic it is unsupported: the futures wallet reports no initial or maintenance
  margin. **`available_notional`** on `perp` is the free margin times the contract's
  maximum leverage (`available` of the futures wallet on Classic, `effEquity` on UTA).
- **Fees** on trades are reported the SDK's way, positive when charged: Classic signs a
  fee charged negative and is flipped, UTA already agrees. A fill charged in several
  coins reports the first coin only.
- `query_order` is the base implementation: it scans `open_orders()`.

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()

sdk = MarketSDK({'bg': accounts.Bitget()})

# public, works on the built-in `bitget` account too
book = await sdk.depth('bg:spot:BTCUSDT', levels=5)
tickers = await sdk.tickers('bg:spot')
stats = await sdk.perp_stats('bg:perp', markets=['BTCUSDT', 'ETHUSDT'])

# account-scoped, dispatched on the account's Classic/UTA mode
position = await sdk.perp_position('bg:perp:BTCUSDT')
```

<!-- next -->

---

← [MEXC Market](mexc.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
