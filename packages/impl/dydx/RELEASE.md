# tribulnation-dydx 0.16.0

Requires SDK >=2.17.0, typed-dydx >=3.7.0 and typed-core >=0.11.0, unchanged. The
node fill feed refuses a full node that is behind the chain tip, and funding history
stops paging at its window. See ADR 0045 and "Fill sources" in the dYdX docs.

Behaviour changes:

1. Before every connection, the full-node fill feed (`trades_source` `'node'` and
   `'fastest'`) reads the node's CometBFT `/status`. If the node is catching up, or its
   latest block is more than 10 s old, the stream fails with `NetworkError` naming the
   reason and `trades_source='indexer'`, and the node stream is never opened. A node
   that block-syncs after an outage streams the blocks it replays as finalized, with
   no way to tell them from live ones: on 2026-10-15 a node about 8 hours behind fed a
   hedger 229 fills that had already been hedged. `'fastest'` now fails in that case
   instead of carrying on with the indexer alone (amends ADR 0044). A failing `/status`
   call is retried like any transport error. A node that falls behind while connected
   is not detected.
2. `funding_payments`, for a market and across the exchange, stops paging at the first
   page reaching before `start`. The indexer ignores `afterOrAt` and pages newest first
   through the whole history, so an account with a long funding history read every
   page: 23 pages of about 1.7 s each for one market on the qualification account,
   which passed the read suite's 60 s limit.

Every other method is unchanged.

The node check was run live, read-only, against a full node: it refused the node
while it was catching up (latest block 25 minutes old) in 0.1 s, before opening the
stream, and streamed normally once it was synced.

Release qualification on 2026-10-15 passed the read suites (27 checks passing, the
order lifecycle excluded) and market consistency (212 checks). Committed evidence
under `release-evidence/dydx/` matches pinned Catalogue
`1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release verification passes.
