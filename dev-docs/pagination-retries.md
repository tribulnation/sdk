# Pagination retries

[Contributor guide](../CONTRIBUTING.md)

Every page request must run inside an async `@SDK.method` boundary. Translate
transport errors into SDK errors **inside** that boundary, so
`Context().retried(NetworkError)` can retry a failed page before its cursor advances.
Decorating only the outer history generator does not provide page retries: SDK retry
middleware operates on coroutine functions, and a failed async generator cannot resume.

For typed-client pagers, use `paging.via(self.call_venue)` for both `await paging`
and `async for` consumption. For manual cursor or time-window loops, use
`await self.call_venue(lambda: endpoint(...))` for each request. Advance cursors and
accumulate or yield rows only after the request succeeds. Keep the request inputs
stable during retries, and put exception translation beneath `@SDK.method`.

Regression tests should fail a later page with a typed-client `NetworkError`, then
consume the real adapter under an SDK retry context. Assert the request sequence
(e.g. `0, 1, 1, 2`) and, where rows are returned, that completed rows appear once.
Include empty pages with continuation tokens and both collected and streamed results.

## Issue #36 audit

The [issue #36](https://github.com/tribulnation/sdk/issues/36) audit covered production
implementations under `packages/impl/*/pkg/src`, including typed pagers, manual
cursor/offset loops, time windows, and provider-managed result pagination. PoC scripts
and live subscriptions are outside this pagination audit.

| Implementation | Pagination paths checked | Result |
| --- | --- | --- |
| Binance | Earn catalogues, Earn positions, candles, funding rates, spot fills, capital and transfer history | Existing per-request wrappers |
| Bit2Me | Candles, orders, fills, Earn wallets/rewards, wallet transactions | Existing per-request wrappers |
| Bitget | Market history/orders/candles; Classic spot, margin and futures reporting | Added report page wrappers, including the shared spot ID pager |
| Bybit | Instrument catalogues, positions, orders, candles, fills, funding, capital history | Existing per-request wrappers |
| Coinbase | Catalogues, accounts, Earn, orders, fills, funding, report transactions and snapshots | Existing per-request wrappers |
| Deribit | Transaction logs by account and currency | Existing per-request wrapper |
| dYdX | Market fills/candles/funding, indexer and Comet history, chain snapshots, governance, BigQuery | Added market fill, snapshot, governance and BigQuery result-page wrappers |
| Ethereum | Etherscan history, Moralis history/balances, Alchemy balances | Existing per-request wrappers |
| Hyperliquid | Candles, market fills/funding, report history | Added market fill and funding page wrappers |
| Kraken | Market fills and report ledger offsets | Existing per-request wrappers |
| KuCoin | Spot fills, capital history and Earn holdings | Existing per-request wrappers |
| MEXC | Candles, market funding, report trade windows, capital windows and funding pages | Added report capital-window and funding-page wrappers |

BigQuery's synchronous result iterator calls back into the async SDK request boundary;
its page request is retried before the iterator sees a failure. Retrying `next()` on
an already failed page generator would lose its continuation. Query submission stays
outside the result-page wrapper, so a recovered page failure does not submit another job.

Validation uses deterministic offline failures; no live account requests are needed to
verify retry placement. The configured retry limit still applies, and an exhausted
request propagates to its caller under the existing middleware behavior.
