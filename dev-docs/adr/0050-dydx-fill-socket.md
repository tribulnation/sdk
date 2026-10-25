# ADR 0050: dYdX fills from a local fill socket, and `'fastest'` over every source

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested against a fake daemon on a real unix
   socket. Not release-verified. Amends
   [0044](0044-trades-stream-settings-dydx-node-fills.md) decisions 2 and 7 and
   [0045](0045-dydx-node-feed-refuses-a-node-behind.md) decision 1 for `'fastest'`.
   Decisions 5 and 6 amended by [0052](0052-dydx-indexer-channels-reconnect.md).
2. Date: 2026-10-22

## Context

Some deployments run a local process, one per host and outside the SDK, that publishes
dYdX fills on a unix socket ahead of the indexer. Callers need to read it like the full
node source, pick it per account rather than per call (a deployment knows what runs on
its host), and race it with whatever else is available, rather than exactly the node and
the indexer.

## Decision

1. `accounts.Dydx` gains `fill_socket` (the daemon's socket path, `$ENV_VAR` allowed)
   and `fill_source` (`'indexer' | 'node' | 'socket' | 'fastest'`), the account's
   default `trades_source`. A per-call `trades_source` overrides it; unset, the default
   stays `'indexer'`. Core passes them to the dYdX package only when set, so a dYdX
   package that predates them keeps working until an account uses them.
2. `trades_source='socket'` reads the daemon only: a WebSocket over the unix socket,
   subprotocol `tribulnation-dydx-fills.v1`, one JSON object per binary frame. Frames
   carry raw protocol fields; the SDK builds the same `NodeFill` a node would (same
   synthetic `id`, maker price, `time=None`, `fee=None`) with
   `details['source'] == 'socket'`. One connection per client, reconnecting forever and
   resubscribing from the last complete block, which the daemon replays from.
3. Whether fills are published at commit or earlier, at proposal time, is the daemon's
   setting, not the SDK's. Each trade carries `details['level']`. A proposal that does not
   commit is undone by a reversing trade (opposite `qty`, `id` suffixed `:revert`,
   `details['revert'] = True`), and in `'fastest'` its dedup copy is retracted so another
   source's copy of a real fill with the same key is still admitted.
4. `'fastest'` races the indexer against every configured source: the node (both
   endpoints set) and the socket (`fill_socket` set); at least one is required. The
   dedup key stays ADR 0044's (height, order or orderless subject, size, counted as a
   multiset), which every source can compute; a per-block fill index is not used because
   the indexer has no equivalent.
5. The indexer is the floor: its failure ends the stream. A node or socket source that
   fails or ends is dropped with a warning and the others race on. For a node this
   replaces 0045's failure of `'fastest'` when the node is behind the tip as it connects:
   the refusal still happens before anything is streamed, so no replayed fill is emitted.
6. The client keeps a `FillRace`: fills each source delivered first, and per pair of
   sources the lead in milliseconds (last 1000), logged by each `'fastest'` stream
   every 10 minutes. Each lead
   is also logged as it happens (INFO, which source was first and by how many
   milliseconds), so a deployment compares sources from its logs alone.

## Consequences

1. `fill_source = "fastest"` with only `fill_socket` races the daemon against the
   indexer, without a full node.
2. `'fastest'` callers that relied on a lagging node failing the stream now get indexer
   fills instead, with a warning in the log.
3. With a daemon publishing at proposal time, consumers must handle reversing trades.
4. A socket fill whose maker price the daemon could not resolve is skipped (other
   sources deliver it under `'fastest'`; with `'socket'` alone it is missed and must be
   reconciled from `trades_history`).
