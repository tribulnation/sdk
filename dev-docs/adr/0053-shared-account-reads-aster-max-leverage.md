# ADR 0053: Shared account reads, and Aster orders at the symbol's maximum leverage

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified; decision 2's hard-coded TTLs
   amended by [0054](0054-caller-chosen-read-staleness.md)
2. Date: 2026-10-26

## Context

A gateway runs one SDK for every task of an engine. Several venues answer every
market's position and collateral from one account-wide request: Lighter's `/account`,
Hyperliquid's `clearinghouseState` and `spotClearinghouseState`, and Aster's
`positionRisk` and futures account, which were read per symbol. With a few dozen
makers, their hedgers, rebalancers and collateral managers reading back to back, the
gateway sent the same request many times a second. In a live run, Lighter's WAF
answered hundreds of these reads with 405 "Human Verification", Hyperliquid and Aster
answered 429, and Aster then banned the IP for a while.

Lighter's `market_stats` snapshots (tickers, perpetual stats, next funding) subscribe to
a channel for their first frame. Two concurrent readers of the same selector on one
connection failed with "Already subscribed".

Aster lowered the maximum leverage of some symbols below the account's setting. From
then on it refused every order on them with `-2027`, hedges included, until someone
changed the setting by hand.

## Decision

1. `tribulnation.sdk.core.SharedReads` shares a read between concurrent callers
   (single-flight) and reuses a successful answer for a short TTL counted from when
   its request started. Failures are not kept. A caller's cancellation never cancels
   the shared request. `forget(key)` drops a key after a write that changes it.
2. Each venue's `Shared` owns one `SharedReads`, keyed per account, never shared
   between accounts:
   - Lighter: `/account` (`ACCOUNT_TTL` = 1 s) and the `*market_stats` snapshots per
     selector (`STATS_TTL` = 5 s).
   - Hyperliquid: `clearinghouseState` per dex and `spotClearinghouseState` (1 s), and
     `userAbstraction` (60 s). Cross collateral takes the collateral token from the
     cached perpetual meta.
   - Aster: one all-symbol `positionRisk`, filtered per symbol, and the futures
     account (1 s). A symbol missing from the all-symbol answer is read alone.
   Position and collateral reads may therefore be up to the TTL plus a request's
   latency old. Reads that ask for fresh data (`leverage(refetch=True)`) skip a stored
   answer, but still join a request already in flight.
3. Aster perpetual orders run at the symbol's highest allowed leverage. Before a
   symbol's first order in a `Shared`'s lifetime, `place_order` reads its leverage
   brackets and sets the leverage to bracket 1's `initialLeverage` when it differs. A
   per-symbol lock keeps concurrent first orders from setting it twice. If that check
   fails, the order is sent anyway and the check is not repeated on every order. On a
   `-2027` refusal the leverage is set again (at most once every 10 s) and the order is
   resent once. If it cannot be set, the original `OrderRejected` is raised.

## Alternatives considered

- **Throttle or retry in the strategies.** Each task would back off on its own while
  the gateway kept sending duplicates, and tasks in different processes cannot see
  each other's reads. Only the gateway's SDK sees every caller.
- **Account streams instead of polling.** They are the better long-term source, but
  not every venue's stream carries positions and collateral in the shape the SDK
  returns. A short-lived shared answer fixes the volume now without changing what
  callers receive.
- **Raise `-2027` to the caller, who adjusts the leverage.** Every caller (makers,
  hedgers, rebalancers) would need the same venue-specific handling, and a hedge
  refused in the meantime leaves a position unhedged.
- **A leverage setting the caller chooses.** No caller asked for anything but the
  maximum, and the SDK has no method to set leverage. That can come with one.

## Consequences

- One request per account read and TTL, whatever the number of markets and tasks.
- A caller reading a position right after its own fill may see the state before it,
  as with any venue whose reads lag its fill stream. Callers that combine fills and
  reads must not let a read older than a fill undo it.
- An Aster account's per-symbol leverage is changed to the maximum on the first order.
  Collateral needed per notional falls, and so does the liquidation distance. A caller
  that caches leverage sees the new value on its next refetch.
- Each Aster symbol's first order per `Shared` waits about one extra round trip.
- The venue packages import `SharedReads`: their releases need a `tribulnation-sdk`
  release first, with their floors raised.
