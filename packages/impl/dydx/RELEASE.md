# tribulnation-dydx 0.18.0

Requires SDK >=2.17.0, typed-dydx >=3.7.0 and typed-core >=0.11.0, unchanged. Account
config `fill_source` and `fill_socket` needs SDK >=2.21.0, which passes them on.
`trades_stream` can read fills from a local fill daemon, and `'fastest'` races every
configured source ([ADR 0050](../../../dev-docs/adr/0050-dydx-fill-socket.md),
amending ADRs 0044 and 0045). See "Fill sources" in the dYdX docs.

New:

1. `trades_source='socket'` reads fills from a fill daemon on this host: a WebSocket
   over the unix socket `fill_socket`, subprotocol `tribulnation-dydx-fills.v1`. Fills
   are built like node fills (synthetic `id`, `time=None`, `fee=None`).
   `details['level']` says whether a fill arrived when its block committed or earlier,
   at proposal time. A proposed fill whose proposal does not commit is followed by a
   reversing trade (`qty` negated, `id` suffixed `:revert`, `details['revert'] = True`).
   The connection reconnects with backoff and resubscribes from the last complete
   block; the daemon replays up to 300 blocks.
2. `DydxMarket.new` (and the SDK `[accounts.<id>]` config, from SDK 2.21.0) take
   `fill_source`, the account's default `trades_source`, and `fill_socket`. A per-call
   `trades_source` still overrides `fill_source`.

Changed:

1. `'fastest'` races the indexer against every configured source: the node when
   `full_node_grpc` and `full_node_rpc` are set, the socket when `fill_socket` is set.
   At least one is required. The indexer is the floor: a node or socket that fails or
   ends, including a node behind the chain tip as it connects, is dropped with a warning
   and the others race on. Before, a node behind the tip failed the whole stream.
2. Under `'fastest'`, each later copy of a fill logs at INFO which source was first and
   by how many milliseconds. The client keeps per-source and per-pair totals, which
   each `'fastest'` stream logs every 10 minutes.

`'indexer'` (the default) and `'node'` are unchanged. The socket source is verified by
unit fixtures against a fake daemon; the read suites do not open fill streams.

Every other method is unchanged.

Release qualification on 2026-10-24 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 2.21.0 publication.
