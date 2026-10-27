# ADR 0054: Caller-chosen read staleness

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends decision 2 of [0053](0053-shared-account-reads-aster-max-leverage.md); implemented, not release-verified
2. Date: 2026-10-27

## Context

[ADR 0053](0053-shared-account-reads-aster-max-leverage.md) made a gateway's concurrent
account reads share one request (`SharedReads`) and reuse its answer for a TTL that each
venue hard-coded: 1 s for Lighter's `/account`, Hyperliquid's `clearinghouseState` and
`spotClearinghouseState` and Aster's `positionRisk` and futures account, 5 s for
Lighter's `*market_stats` snapshots and 60 s for Hyperliquid's `userAbstraction`. Only
`leverage(refetch=True)` could skip a stored answer, and even it joined a request
already in flight.

How stale an answer may be is the caller's call, not the venue's. A hedger reading its
position right after a fill needs an answer from after that fill: a stored one, or one
whose request was already in flight, may predate it and undo the hedge. A collateral
manager or rebalancer polling every market of an account is fine with a second-old
answer, and is the reader that floods the venue when it does not share. One hard-coded
number serves neither: it is too stale for the first and arbitrary for the second.

## Decision

1. The reads of changing account and snapshot data on the market interfaces take
   `ttl: timedelta | None = None`, how old an answer the caller accepts: `balances`,
   `balance`, `position`, `perp_position`, `collateral`, `perp_collateral`, `leverage`,
   `available_notional`, `next_funding`, `tickers` and `perp_stats`, on markets,
   exchanges, venues and `TradingMarkets` (whose `collateral(id)` passes it to the pool or
   balance it resolves). `leverage(refetch=...)` is replaced by `ttl`; `refetch=True` is
   `ttl=None`.
2. `ttl=None` asks afresh: the answer comes from a request started after the call. No
   stored answer is used and no request in flight is joined.
3. A `timedelta`, `timedelta(0)` included, shares: an answer whose request started less
   than `ttl` ago is used, else a request in flight is joined, else one is started. Every
   request, fresh ones included, stores its answer for later sharing callers if it is
   still the latest started for its key; callers with different `ttl`s share one key.
4. Keys stay account-wide, as in ADR 0053: one request serves every market of the
   account. Only the maximum age moves to the caller.
5. Lighter's `market_stats` snapshots stay single-flight whatever the `ttl`: a connection
   refuses a second subscription to an open channel ("Already subscribed"). There `None`
   only skips a stored snapshot; a subscription in flight is still joined.
6. Leverage reads that had their own forever cache (Lighter, Hyperliquid, Aster, Extended,
   GRVT, margin.trade) read through `SharedReads` with the caller's `ttl`; on Lighter and
   Aster leverage comes from the shared account read itself.
7. Venues without shared reads accept `ttl` and ignore it: every read asks the venue.
   dYdX's leverage keeps deriving from its cached market list.
8. Internal caches that callers never choose stay as they are: market metadata, and
   Hyperliquid's account mode (`userAbstraction`, reused for a minute; it changes only by
   hand and every collateral read checks it).
9. The gateway carries `ttl` on each of these requests (an ISO 8601 duration; absent or
   null is `None`), so the shared answers live in the gateway process and every task
   reading through it shares them.

## Alternatives considered

- **Keep the hard-coded TTLs (ADR 0053).** Protects the venue without callers changing,
  but a hedger cannot get an answer newer than its fill, and the numbers are a guess at
  every caller's tolerance made in the venue package.
- **A TTL per account in configuration (`sdk.toml` or the gateway's).** One number per
  account still cannot serve a hedger and a collateral manager on the same account, and
  it hides a correctness choice in deployment configuration far from the code that
  depends on it.
- **Default to sharing (e.g. `ttl=1s`) and let callers opt into fresh reads.** It keeps
  the protection for callers that never pass a `ttl`, but makes a stale answer the
  silent default for correctness-sensitive reads; a missed opt-out loses money, a missed
  opt-in costs requests.
- **`None` joins a request in flight (ADR 0053's `fresh`).** That request may have
  started before the fill the caller just saw.

## Consequences

- Breaking signature change: `leverage(refetch=...)` is gone and every venue
  implementation's read methods gain `ttl`, so it ships with SDK 3.0, whose interfaces
  already break, and the venue packages' floors rise with it.
- The default asks the venue every time, so the rate-limit protection of ADR 0053 now
  depends on callers passing a `ttl`. Polling readers (hedgers between fills,
  rebalancers, collateral managers, market selection) must pass one, e.g. one second
  for positions and collateral and longer for leverage and stats; a reader acting on a
  fill passes none.
- `leverage()` without a `ttl` reads the venue on each call, where it was cached forever;
  `available_notional()` without a `ttl` likewise. Callers that relied on that cache pass
  a long `ttl`.
- `SharedReads.read` takes `ttl: timedelta | None` instead of seconds.
- dYdX's leverage can only be refreshed through its market list (`rules(refetch=True)`,
  tickers or perpetual stats).
