# tribulnation-deribit 0.7.2

Requires SDK >=3.0.0 and typed-deribit >=0.3.0, unchanged.

Fixed:

1. Bulk `perp_stats()` makes one futures `public/get_book_summary_by_currency` request per quote currency (#401), not one `public/ticker` per perpetual. All 151 linear perpetuals quote in USDC, so that is 1 request instead of 151. The old path tripped Deribit's `10028 too_many_requests` limit. Index, mark and open interest mean the same as before: the index is the summary's `estimated_delivery_price`, which equals the ticker's `index_price` for every perpetual (checked on all 151). An instrument missing from the summaries, or one without that price, falls back to its own ticker. Single-market `index()` still reads the ticker.

Every other method is unchanged.

Release qualification on 2026-11-21 passed the read suites and market consistency,
including bulk `perp_stats`. Committed evidence under `release-evidence/deribit/`
was recorded with tribulnation-sdk 4.3.0 against pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`. Offline release verification passes.
