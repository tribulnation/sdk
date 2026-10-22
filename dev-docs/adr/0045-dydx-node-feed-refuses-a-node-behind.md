# ADR 0045: The dYdX node feed refuses a node behind the chain tip

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested with fake nodes; checked live read-only on
   2026-10-15: refused a node catching up (latest block 25 minutes old) before opening
   the stream, and streamed normally once it was synced. Amends [0044](0044-trades-stream-settings-dydx-node-fills.md)
   decision 4 and consequence 1. Decision 1 is amended for `'fastest'` by
   [0049](0049-dydx-fill-socket.md). Not release-verified.
2. Date: 2026-10-15

## Context

A dYdX full node that restarts after a long outage block-syncs from where it stopped.
While it does, `StreamOrderbookUpdates` streams every block it replays as finalized
updates (`exec_mode == 7`), the same as live ones, and the stream carries block heights
but no block times. Under ADR 0044 the node feed reconnected to such a node and emitted
the replayed fills as new: on 2026-10-15 a node about 8 hours behind fed a hedger 229
fills that had been hedged hours earlier from the indexer, and the hedger traded each
again. `'fastest'` did not help: its dedup drops a fill only once the indexer has
delivered a newer one on the same stream, and the indexer pushes only our own fills.

No message in the stream tells a replayed block from a live one. The node's CometBFT
`/status` does: `catching_up` while it block-syncs, and the height and time of its
latest block.

## Decision

1. Before every connection, the first and each reconnection, the node feed reads the
   node's `/status` (on `full_node_rpc`). If `catching_up` is true, or its latest block
   is more than `MAX_BLOCK_AGE` (10 s) older than the local clock, the feed fails with
   `NetworkError`, naming the reason and `trades_source='indexer'` as the remedy, and
   does not open the stream.
2. The failure reaches every subscriber: `'node'` streams fail, and so do `'fastest'`
   streams, rather than carrying on with the indexer alone. The caller sees it and
   chooses a source; the SDK does not switch sources on its own.
3. A failing `/status` call is a transport error like the stream's own, retried with
   the same backoff: it says nothing about the node's height.
4. The check runs at connection time only. A node that falls behind while connected is
   not detected.

## Alternatives considered

1. Gate every fill on a polled `/status` (latest block time, fill height near it),
   dropping stale fills and keeping `'fastest'` alive on the indexer. It also covers a
   node that falls behind while connected, but drops fills silently under `'node'` and
   adds a poller per client. Rejected for now in favour of failing loudly; it can be
   added if mid-stream lag shows up.
2. Infer replay from the stream: replayed blocks arrive far faster than live ones
   (about 28 against 1.8 blocks/s on 2026-10-15). Needs a per-block heartbeat (an
   oracle price subscription), takes seconds to judge, and misses a node lagging at
   normal speed. Rejected.
3. Check `catching_up` alone. It turns false when the node leaves block sync, not when
   it reaches the tip, and stays false if the node then lags in consensus. The block age
   costs nothing more, from the same response. Observed on 2026-10-15, `catching_up`
   turned false with the latest block 3.2 s old and 2 blocks behind the indexer, and
   synced blocks were 1.0 to 1.3 s old, so 10 s leaves margin both ways.

## Consequences

1. `'fastest'` no longer keeps delivering while the node is behind: it fails until the
   caller switches to `'indexer'` or the node is synced. It still keeps delivering while
   the node is unreachable.
2. The check needs the local clock to be close to block time (NTP); a clock more than
   10 s off makes a synced node read as behind.
3. A node that falls behind while connected still streams old blocks as new fills until
   the next reconnection; decision 4 bounds what this protects against.
