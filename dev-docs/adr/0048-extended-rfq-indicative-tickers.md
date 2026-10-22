# ADR 0048: Extended RFQ depth from quotes, with indicative tickers as a visible limitation

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified
2. Date: 2026-10-22
3. Amends: [ADR 0014](0014-bit2me-native-ticker-limitation.md) and
   [ADR 0022](0022-bit2me-one-sided-ticker-limitation.md) (the native ticker limitation,
   until now Bit2Me spot only).

## Context

Most Extended perpetuals (295 of 343 listed on 2026-10-22) are RFQ markets
(`isRfq: true`): orders go through the RFQ endpoint and fill against market makers'
quotes, which the venue publishes only on the `orderbooks/rfq` stream. The REST order
book and `orderbooks` stream of an RFQ market, and the best bid and ask in its
`marketStats`, are the venue's indicative book, not prices an order can trade at.

The adapter maps `depth` and `depth_stream` of RFQ markets to the quotes, so a caller
sizing an order sees executable prices, and `tickers` to the native `marketStats`, one
bulk read for every market. The first live consistency run (2026-10-22) therefore
failed `ticker_depth` on the three deterministic RFQ samples (`1000BONK-USD`,
`1000PEPE-USD`, `1000SHIB-USD`): in every bracket the ticker sat inside the quotes'
spread, for example `0.003067`/`0.003068` against `0.003027`/`0.003105`. The order-book
reference market `BTC-USD` passed. The mapping is faithful on both sides; the two reads
describe different books.

## Decision

1. Keep `depth` and `depth_stream` on RFQ markets as the RFQ quotes, and keep ticker
   bid and ask as the venue's native, indicative figures. Do not derive tickers from the
   quotes: that would open one stream per RFQ market for a bulk read. Consumers needing
   executable prices on an RFQ market request `depth()`.
2. Extend the `limitation/native_ticker_quotes` eligibility of ADRs 0014 and 0022 to
   Extended `perp` quote checks of RFQ markets, with the same observation shape: three
   timely, exact-ID brackets whose comparisons all disagree, the same nonempty book-side
   inventory in all six depth snapshots, finite positive and uncrossed book prices, and
   ticker sides missing, zero or nonnegative finite.
3. The collector records the market's RFQ flag on the check (`rfq`), read from
   `rules().details['is_rfq']` only for a failed Extended comparison. The verifier
   requires `rfq: true` for the Extended limitation, and rejects the flag on any other
   venue or check. An unreadable flag leaves the comparison failing.
4. Extended order-book markets, every other venue and exchange, and every other failure
   shape (request errors, wrong IDs, slow brackets, invalid books) remain blocking.
   Tolerances and the deterministic samples are unchanged.
5. The payload stays at version 6: the flag is a new optional field, and a version-6
   report without it cannot claim the Extended limitation, so no earlier observation
   is relabeled.

## Alternatives considered

1. `depth` from the indicative book, with the quotes behind a `depth_source` setting
   as on Lighter: consistent with tickers, but the default book would quote prices no
   order on an RFQ market trades at.
2. Ticker bid and ask from the quotes stream: one connection per RFQ market for a bulk
   read, and a selected read would disagree with the bulk one.
3. Ticker bid and ask as `None` on RFQ markets: drops a native figure and still fails
   the comparison, which treats a missing side against a present book side as a mismatch.

## Consequences

Extended release evidence can qualify with RFQ samples recorded as limitations, never
passes; the summary lists them. The order-book reference market must still pass. The
change to shared qualification tooling makes every venue in a release scope need fresh
consistency evidence (ADR 0033). Acceptance is not release readiness.
