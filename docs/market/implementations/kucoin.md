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

# KuCoin Market

> Classic spot and linear perpetuals. `tribulnation-kucoin`, venue name `kucoin`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is KuCoin-specific.

## Account

A public `accounts.Kucoin(public=True)` account is enough for market data. Account
and trading methods need an API key with its secret and passphrase:

```toml
[accounts.kucoin]
venue = "kucoin"
api_key = "$KUCOIN_API_KEY"
api_secret = "$KUCOIN_API_SECRET"
api_passphrase = "$KUCOIN_API_PASSPHRASE"
```

These are the defaults, so `venue = "kucoin"` alone reads the three variables. One key
serves both KuCoin hosts (`api.kucoin.com` for spot, `api-futures.kucoin.com` for
futures) and both private WebSocket connections. A sub-account's own API key reads and
trades that sub-account. `validate` toggles response validation.

## Exchange & ID conventions

- Exchanges are `spot` and `perp`, with native symbols: `kucoin:spot:BTC-USDT`,
  `kucoin:perp:XBTUSDTM`. Perpetual discovery lists open linear contracts settled in
  their quote currency (USDT and USDC); inverse and dated contracts are excluded.
- Spot trades through KuCoin's high-frequency (HF) order API from the spot `trade`
  account; `balances()` reads that account (`total` the balance, `free` what is
  available). Funds in the `main` (funding) account are not tradable and not counted.
- Futures quantities are whole contracts of the contract's `multiplier` base units. The
  SDK side is always base units: rules, books, orders, positions and fills are
  converted, and an order that is not a whole number of contracts raises `ValueError`.

## Orders

- `LIMIT` rests (GTC), `POST_ONLY` sets `postOnly`, and `MARKET` is an IOC limit at the
  order's price, so the price stays a protection bound.
- Orders are checked against `rules()` before anything is sent: an off-grid price or
  quantity, a size below the minimum or above the maximum, or a spot order below the
  pair's minimum funds raises `ValueError`. Nothing is rounded.
- Spot orders are placed synchronously (`/api/v1/hf/orders/sync`): a post-only that
  would cross and an IOC that matched nothing raise `OrderRejected`, and `filled_qty`
  is what dealt at placement.
- Futures orders are acknowledged before matching. A `MARKET` order is read back once:
  done with nothing filled raises `OrderRejected`, done with fills reports them. A
  futures `POST_ONLY` that would cross is cancelled by KuCoin after the acknowledgement,
  so it comes back as an order ID and then shows as cancelled with nothing filled.
- `client_order_id` is sent as `clientOid`; without one a random 32-hex ID is sent.
  Stream fills report it.
- `place_orders` uses the native batch (20 per request) on both lines; `cancel_orders`
  the native futures batch cancel (10 per request); `cancel_open_orders` the native
  per-symbol cancel-all. `replace_order` cancels, then places.
- Definitive KuCoin refusals raise `OrderRejected` (`PositionLimitExceeded` for
  `126042`); internal errors, gateway timeouts and throttling stay ambiguous
  (`ApiError`, `RateLimited`). A cancel or query of a finished or unknown order raises
  `OrderNotFound` (or answers `None` from `query_order`).
- `RateLimited` carries KuCoin's `gw-ratelimit-reset`: `tribulnation.kucoin.retry_after(exc)`
  returns it as a `timedelta` (with typed-kucoin releases that attach it).

## Positions, collateral and leverage

- Perpetuals are one-way on cross margin. Orders send `marginMode=CROSS` and the
  symbol's cross leverage setting, which `leverage()` reads and `set_leverage()` changes
  (whole multiples).
- `perp_collateral()` is the cross pool of the contract's settlement currency: equity and
  free collateral from the futures account overview, initial margin its position plus
  order margin, maintenance margin the sum of the open cross positions' `posMaint`.
  An isolated position reports its own margin instead.
- `collateral_id()` is the USDT futures pool, `<account>:perp`, separate from spot
  (`<account>:spot:<asset>`). USDC-settled contracts raise `NotImplementedError`: their
  pool is a second futures balance the exchange ID cannot name.
- `fees()` reads the account's actual rates per symbol, VIP tier and market-maker program
  included: a maker rebate is a negative rate. A tax rate KuCoin reports is added.

## Fills and history

- `trades_stream` reads the private order channels (`/spotMarket/tradeOrdersV2`,
  `/contractMarket/tradeOrders`), one per line shared by every market. Fills carry the
  order and client order IDs and the liquidity role of the fee charged, but no fee:
  the pushes do not report one. A dropped connection fails the stream with
  `NetworkError`; subscribing again reconnects with a fresh bullet token.
- `trades_history` walks seven-day windows up to now (spot HF fills; futures trades,
  liquidations and ADL), keeping each fill once. `funding_payments` walks one-day windows.

## Verification

Public reads are verified on mainnet. Trading, the private streams and the account reads
are tested against fake responses only. `packages/impl/kucoin/scripts/live_trading.py`
reads every account method and, with `--place`, rests and cancels one minimum-size
post-only order per market.

<!-- next -->

---

← [GRVT Market](grvt.md) · **Next:** [Lighter Market](lighter.md) →

<!-- /next -->
