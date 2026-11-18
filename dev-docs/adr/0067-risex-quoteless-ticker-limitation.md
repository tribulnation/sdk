# ADR 0067: RISEx tickers without a top of book, as a visible limitation

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-11-18
3. Amends: [ADR 0048](0048-extended-rfq-indicative-tickers.md) (the native ticker
   limitation, until now Bit2Me spot and Extended RFQ markets).

## Context

RISEx's market data (`markets.all`) carries a last price and a 24h quote volume per
market, but no best bid or ask. The adapter's tickers map it one to one, so their `bid`
and `ask` are `None`, as the RISEx `impl.toml` note and Market page state. The
consistency suite's `ticker_depth` comparison treats a missing ticker side against a
present book side as a mismatch, so every RISEx `perp` sample fails against a live
book, although both reads are faithful.

## Decision

1. Keep RISEx tickers without a bid or ask. Do not derive them from the book: that
   would be a book request per market for a bulk read. Consumers needing the top of
   book request `depth()`.
2. Extend the `limitation/native_ticker_quotes` eligibility of ADRs 0014, 0022 and 0048
   to RISEx `perp` quote checks, with the same observation shape (three timely,
   exact-ID brackets whose comparisons all disagree, the same nonempty book-side
   inventory in all six depth snapshots, finite positive and uncrossed book prices),
   and further requiring both ticker sides missing in every bracket. A RISEx ticker
   that does quote a side is compared, and a mismatch blocks.
3. Every other failure shape (request errors, wrong IDs, slow brackets, invalid books)
   remains blocking. Tolerances, the deterministic samples and the payload version are
   unchanged.

## Alternatives considered

1. Ticker bid and ask from one depth read per market: a bulk read would cost a request
   per market, and the figures would not be the venue's ticker.
2. Declare `tickers` unsupported for RISEx: drops the last price and volume the venue
   does publish.

## Consequences

RISEx release evidence can qualify with its quote samples recorded as limitations,
never passes; the summary lists them. The change to shared qualification tooling makes
every venue in a release scope need fresh consistency evidence (ADR 0033). Acceptance
is not release readiness.
