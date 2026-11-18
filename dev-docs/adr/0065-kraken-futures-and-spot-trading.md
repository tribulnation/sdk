# ADR 0065: Kraken Futures and Spot trading

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified. Amends [0020](0020-kraken-public-perpetuals.md).
2. Date: 2026-11-17

## Context

ADR 0020 added Kraken's public linear perpetuals and kept private Futures methods,
account fees, trading, Futures WebSocket subscriptions and `next_funding`
unsupported. Spot kept its public and private reads, without trading, `balances` or
collateral IDs (ADR 0051).

typed-kraken 0.6.0 adds an authenticated Futures client (`typed_kraken.futures_trading`):
signed REST trading and account reads, and the WebSocket v1 feeds. Kraken issues
Futures API keys separately from Spot keys, and the two products settle against
separate wallets: Spot balances per asset, and the Futures multi-collateral (flex)
account.

## Decision

1. **Scope.** The Kraken Market surface trades both products, each with its own key:
   1. Perpetuals (the `PF_` contracts ADR 0020 admits) with a Futures API key:
      `futures_api_key` and `futures_private_key` on `accounts.Kraken`, defaulting to
      `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_PRIVATE_KEY`. Without them perpetuals
      stay public-only. Account reads (position, collateral, leverage, available
      notional, open orders, order status, fills, funding payments, fees) and orders
      (place, place several via `batchorder`, edit in place via `editorder`, cancel,
      cancel several) use REST. `depth_stream` folds the WebSocket `book` feed
      (snapshot plus deltas, sequence-checked; a gap fails the stream), and
      `trades_stream` is the private `fills` feed.
   2. Spot pairs with the Spot API key over REST: `AddOrder`, `AmendOrder` (same txid;
      Kraken's new total is the filled part plus the new size), `CancelOrder`,
      `QueryOrders`, and `balances` from `BalanceEx` (`balance`, and
      `balance - hold_trade` as free). `place_orders`, `cancel_orders` and
      `cancel_open_orders` use the per-order defaults, never the account-wide
      `CancelAll`. Spot collateral IDs are `<account>:spot:<internal asset id>`
      (`kraken:spot:ZUSD`); the Futures pool is `<account>:perp` (ADR 0051).
   3. `kraken_testnet` is Kraken's Futures demo environment, with its own Futures keys
      (`KRAKEN_FUTURES_TESTNET_*`) and no Spot.
   4. A Kraken account needs Spot keys only when it has no Futures keys; a
      Futures-only account builds a public Spot side.
2. **Order types.** `LIMIT` is a GTC limit, `POST_ONLY` a post-only limit, and `MARKET`
   an IOC limit bounded by the order price. Settings `kraken.time_in_force` (`lmt`,
   `post` or `ioc`) sends a `LIMIT` that way on both products. `kraken.reduce_only`
   applies to perpetuals; a Spot order asking for it raises `ValueError`. Spot orders ask for fees in the quote asset (`fciq`).
3. **`OrderRejected` (ADR 0043)** only where Kraken's answer means nothing was placed:
   1. Futures: a `sendStatus` (or batch status) other than `placed`/`edited` with no
      execution, for example `postWouldExecute`, `iocWouldNotExecute` or
      `insufficientAvailableFunds`. A post-only edit answered `postWouldExecute`, which
      cancels the order, is also `OrderRejected`.
   2. Spot: an `EOrder:*` error, or a request the translation layer classifies as a bad
      request (invalid arguments, tick size), unless the primary error is `Internal
      error`, `Unavailable`, `Busy` or `Timeout`. Those, rate limits and transport
      failures remain ambiguous and keep their classes.
4. **`OrderNotFound` (ADR 0059).** Futures: a cancel answered `notFound` or `filled`,
   an edit answered `orderForEditNotFound`, or a batch with no status for the order.
   Spot: a cancel answered `Unknown order` or `Invalid order`, or one that cancels
   nothing and has nothing pending. `replace_order` places afresh when the order is
   gone. An edit cannot change the side, so a replacement on the other side cancels
   and places (the ADR 0059 default). Any other edit refusal is `ApiError`, and the
   order still rests as it was.
5. **Leverage.** A market with a Kraken leverage preference trades isolated at that
   leverage. Otherwise it trades cross at the inverse of the first-tier retail initial
   margin: the instrument's `marginSchedules[<margin_schedule>].retail` when
   `accounts.Kraken.margin_schedule` names a platform the instrument publishes, else
   its `retailMarginLevels` (falling back to `marginLevels`). Many instruments
   publish no schedule for every platform, so a missing schedule is not an error.
   An instrument without any levels raises.
6. **Collateral and fees.** Perpetual collateral is the flex pool (`marginEquity`,
   `availableMargin`), with leverage at mark prices from public tickers. Fees are the
   instrument's fee-schedule tier for the account's 30-day volume.
7. **`next_funding`** is now supported. Amending ADR 0020 decision 6, it is the
   ticker's `relativeFundingRate`, settled at the next full hour. Historical funding is
   unchanged.
8. **Still unsupported:**
   1. Isolated-margin collateral: `collateral` raises `NotImplementedError` for a
      market with a leverage preference.
   2. Earn-allocated Spot balances (`.F`, `.B`, `.S` ids).
   3. Spot `filled_qty` on placement: `AddOrder` reports no execution, so it is `None`.
   4. Fees on perpetual `trades_history`: REST `fills` carries none.
   5. Perpetual maximum order size.
   6. Inverse, dated and tradfi contracts.
   7. Spot WebSocket trading.

## Alternatives considered

- One key for both products: Kraken issues and authenticates Futures keys separately.
- `CancelAll` for `cancel_open_orders`: it cancels across every pair on the account,
  wider than the method's market scope.
- Classify every non-`placed` Futures status as ambiguous: Kraken's synchronous status
  says whether the order entered the book, so refusing to classify it would hide
  certain refusals from strategies (ADR 0043).
- Fail leverage when the chosen platform has no schedule for an instrument: such
  instruments are common, and their published retail levels apply.

## Consequences

Kraken perpetuals and Spot pairs become tradeable through the SDK. `tribulnation-kraken`
requires typed-kraken 0.6.0 or newer. The `kraken` key joins the shared Market
`Settings`, and `kraken_testnet` joins the venue IDs and the gateway protocol schema.

Order placement, editing, cancellation and the private feeds are verified against
in-memory fakes of each venue (signed Futures REST, the Futures WebSocket feeds and
Spot REST). Kraken Spot has no testnet. Release still requires the change-scoped live
read-suite and consistency evidence (ADR 0033): Market reads for both products,
including the read-only account methods with a Futures key at `min_mode = "private"`
(ADR 0042). A Futures demo (`kraken_testnet`) trading run is the remaining live check
of order handling. This decision is not release-readiness evidence.
