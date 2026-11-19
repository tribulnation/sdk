# ADR 0069: Remaining position limits shared by default, from account-wide reads

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends [0054](0054-caller-chosen-read-staleness.md) (decision 1's
   default, for `remaining_position_limit` only) and the consequences of
   [0062](0062-remaining-position-limit-and-limit-refusals.md); implemented for Aster,
   Hyperliquid, Extended, GRVT, RISEx, Lighter and Nado, not release-verified
2. Date: 2026-11-19

## Context

A strategy engine reads `remaining_position_limit()` for every market of an account each
round (22 Aster symbols in production). Each call cost per-symbol requests:

1. Aster 0.15.0: the shared `positionRisk` and futures-account reads, plus one public
   `remainingOpenableNotionalValue` request per symbol (weight 50). A round of 22 symbols
   sent about 24 requests, and the engine's re-reads after refusals up to six rounds a
   minute: about 144 requests and 6,600 weight a minute. On 2026-11-17 a similar
   per-symbol poller had Aster ban a host's IP within a minute.
2. Hyperliquid 0.21.0: one `activeAssetData` (weight 20) per coin for its leverage
   setting, beside the shared `clearinghouseState` and `perpsAtOpenInterestCap`.
3. Extended read the market's row, positions and leverage per market; RISEx the market's
   live row per market; GRVT positions and a ticker per instrument; Lighter a
   `market_stats` subscription per market; Nado `all_products` and an archive price per
   call.

Production patched this with a request budget in its own SDK build (commit `ee3721ac`),
outside the released packages. Callers could pass a `ttl`, but under ADR 0054 the
default asks afresh, so a caller that does not is back to per-symbol requests; and even
with a `ttl`, the per-symbol requests were never shared.

## Decision

1. `MarginMarket.remaining_position_limit` and its routes (`TradingMarkets`,
   `TradingVenue`, `PerpExchange`, the gateway proxy) default `ttl` to
   `tribulnation.sdk.market.POSITION_LIMIT_TTL`, 30 seconds. Every other read keeps
   ADR 0054's `None` default. `ttl` keeps ADR 0054's meaning; `None` asks afresh.
2. Venues answer every market from account-wide (or all-market) reads shared through
   their `SharedReads` under the caller's `ttl`, filtered per market, wherever the venue
   offers one:
   1. Aster: the all-symbol `positionRisk` (`maxNotionalValue`, `notional`, `leverage`);
      the futures-account read is no longer used.
   2. Hyperliquid: `clearinghouseState` and `perpsAtOpenInterestCap` per dex. The
      leverage is the open position's; a flat coin is bounded at its `maxLeverage`, the
      tightest tier bound any setting has, instead of reading `activeAssetData` per
      coin. A flat coin set below its maximum may read less room than the venue allows,
      never more.
   3. Extended: all-market `markets`, `positions` and `leverage`.
   4. RISEx: all-market live rows (`markets.all(force_refresh)`) beside the shared
      positions.
   5. Lighter: the `all` `market_stats` snapshot.
   6. Nado: `all_products` and `perp_prices` of every listed perpetual; an uncapped
      product reads nothing.
   7. GRVT: all perpetual positions. GRVT has no all-instrument ticker, so a capped
      instrument's mark stays its own ticker, shared for `ttl`; an uncapped one reads
      none.
3. A per-symbol read with no batched form and slow-moving, market-wide content is reused
   longer than the caller's `ttl` and paced across symbols. Aster's
   `remainingOpenableNotionalValue` is shared per symbol and leverage for 15 minutes
   whatever the `ttl`, and the requests of all symbols of a client together are at
   least 30 s apart. A symbol whose answer is older keeps it until its turn; one never
   read has no open-interest bound (`None`) meanwhile. `available_notional` reads the
   allowance the same way.
4. An Aster `PositionLimitExceeded` refusal drops the shared `positionRisk` answer and
   marks the symbol's allowance for a new read at its next turn, keeping its value
   meanwhile.
5. Failures are not kept and concurrent callers join one request in flight, as
   `SharedReads` already guarantees.

## Alternatives considered

1. **Keep `None` as the default and ask callers to pass a `ttl`.** ADR 0054's rule, and
   right for reads acting on a fill. But this figure is a slow-moving cap that the venue
   enforces itself with typed refusals (ADR 0062), every caller polls it for every
   market, and the cost of a missed `ttl` is a banned IP rather than a stale size.
2. **A request budget in the caller (production's `ee3721ac`).** Every caller and
   process would need the same venue knowledge; only the venue package knows which
   reads batch.
3. **Port `ee3721ac`'s `RequestBudget` into `sdk.core`.** Only Aster has a per-symbol
   read left after batching; a fixed spacing kept in the venue package is enough, and
   the shared answers stay in `SharedReads` with the rest.
4. **Read `remainingOpenableNotionalValue` for every symbol on each refresh.** At 22
   symbols that is 1,100 weight at once, the burst this decision removes.
5. **Read Hyperliquid's `activeAssetData` only for flat coins.** Still one request per
   flat coin per `ttl`; the conservative bound needs none.

## Consequences

1. Polling 22 Aster symbols every 5 s at the default `ttl` sends at most 4 requests a
   minute: 2 `positionRisk` and 2 allowances, all 22 allowances read within 11 minutes
   and each refreshed every 15. A Hyperliquid dex costs 4 requests a minute, whatever the
   number of coins. Unit tests pin both budgets.
2. A limit read within 30 s of a fill may predate it. The venue still refuses an order
   past the limit with `PositionLimitExceeded`; callers needing a fresh figure pass
   `ttl=None`.
3. For about 11 minutes after start, some Aster symbols have no open-interest bound;
   their bracket bound still applies. Aster's open-interest caps are market-wide and
   most symbols are uncapped (`-1`).
4. The SDK's signatures change their default only; implementations import
   `POSITION_LIMIT_TTL`, so the venue releases need the SDK release first, with their
   `tribulnation-sdk` floors raised. A gateway older than its client receives the
   client's `ttl` and shares as asked; an older client sends `null` and asks afresh.
5. Changing live qualification inputs (Aster's bracket now from `positionRisk`) puts
   the affected venues in the next release's evidence scope (ADR 0033).
