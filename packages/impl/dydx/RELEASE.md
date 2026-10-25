# tribulnation-dydx 0.19.0

Requires SDK >=2.17.0, typed-dydx >=3.7.0 and typed-core >=0.11.0, unchanged. Account
config `fill_source` and `fill_socket` still needs SDK >=2.21.0, which passes them on.
The indexer's WebSocket channels reconnect after a dropped connection, and `'fastest'`
rides a short indexer drop
([ADR 0052](../../../dev-docs/adr/0052-dydx-indexer-channels-reconnect.md), amending
ADR 0050). See "How indexer fills are read" in the dYdX docs.

New:

1. Settings field `indexer_reconnect_window` (seconds, default 3, `0` for at once): how
   long a `'fastest'` trades stream races on while the indexer's channel reconnects
   before it fails with `NetworkError`.

Changed:

1. `'fastest'` no longer ends when the indexer's WebSocket drops. The node and socket
   race on while the indexer reconnects (0.5 s backoff doubling to 8 s; usually about
   1.5 s), and the fills of the gap are then read from REST
   (`/v4/fills/parentSubaccountNumber`, with their orders) and deduplicated, so the drop
   skips no fill. Backfilled copies are not counted as leads. An indexer down for over
   `indexer_reconnect_window` seconds ends the stream with `NetworkError`. Before, any
   drop ended it.
2. Book streams (`depth_stream`) ride a drop: after the reconnection the new
   subscription's snapshot is delivered at once. Only a book channel down for 60 s ends
   them. Before, any drop ended every book stream with `NetworkError`.
3. Under `'fastest'`, each fill is recorded and logged once per client. When several
   `'fastest'` streams follow one market (e.g. a strategy's hedger and position
   tracker), only the oldest records and logs the race, and the next takes over when it
   leaves. The `dYdX fill race:` totals come from one client-wide task every 10 minutes.
   Before, each stream logged each fill and its own totals, so fills were logged and
   counted once per stream.

`'indexer'` (the default) is unchanged: a dropped connection ends the stream with
`NetworkError`, and the fills of the gap are not read. So is `subscribe_parent_subaccount`.
`'node'` and `'socket'` are unchanged.

Every other method is unchanged.
