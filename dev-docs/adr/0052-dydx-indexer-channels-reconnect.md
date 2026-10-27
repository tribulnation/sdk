# ADR 0052: dYdX indexer channels reconnect; `'fastest'` rides short drops, `'indexer'` ends

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested with scripted channels and checked live
   by forcing drops of the indexer WebSocket. Not release-verified. Amends
   [0050](0050-dydx-fill-socket.md) decisions 5 and 6.
2. Date: 2026-10-24; revised 2026-10-25 after review: `'indexer'` streams end on a
   drop, `'fastest'` only rides drops of up to `indexer_reconnect_window` seconds.

## Context

Every indexer channel of a dYdX client (the parent subaccount's, and each book of
`depth_stream`) shares one WebSocket. The indexer drops that connection several times
an hour (`ConnectionClosedError: no close frame received or sent`), and each drop ended
every subscriber with `NetworkError`: every `trades_stream` (including `'fastest'`,
whose floor is the indexer, even while the node or socket kept delivering) and every
book stream. Callers restarted after their own backoff, losing state each time, and an
`'indexer'` stream silently skipped the fills of the gap.

A hedger must be fast: a strategy whose fills come late or not at all should stop (its
hedger raising stops the maker) rather than trade on unhealthy. A drop of the indexer
alone, while the node or socket keeps delivering, is not unhealthy for `'fastest'` if
it is short; drops usually last about 1.5 s.

Separately, `'fastest'` logged its statistics once per stream and each lead once per
stream of the market, so a process with several streams of one market (a hedger and a
position tracker, say) logged each fill several times and counted it several times.

## Decision

1. Each indexer channel reconnects on its own: when its items fail with `NetworkError`
   or end, it is released and reopened with exponential backoff (0.5 s doubling to 8 s),
   and its items go on from the new subscription. The channel tells its subscribers
   (`Dropped`, then `Reconnected`), and each subscriber decides whether a gap ends it.
   Connection errors and the indexer's REST rate limiting or failing on its side are
   retried; a rejected request is not. A channel down for 60 s ends its remaining
   subscribers with the last error, and a channel nobody follows any more stops.
   One shared channel per parent subaccount is kept, since the indexer refuses a second
   subscription to the same channel on a connection.
2. An `'indexer'` trades stream (and `subscribe_parent_subaccount`) ends with
   `NetworkError` on `Dropped`, as before this ADR, and never sees backfilled fills.
3. The parent subaccount channel backfills each gap from REST for the streams that ride
   it (`'fastest'`): the fills between the last block the channel reached and the new
   subscription's `blockHeight` (both included) are read from
   `/v4/fills/parentSubaccountNumber`, with their orders from `/v4/orders/{id}` for the
   SDK order ids, and delivered as one notification before the live ones. Fills are remembered by id for 100 blocks, so a fill the channel and
   the backfill both carry is delivered once. A failed backfill fails the reconnection,
   which is retried as in 1, so a gap is never skipped silently.
4. A book channel rides a drop: its subscribers see only the gap, and it restarts from
   the new subscription's snapshot, delivered at once; only 60 s down ends it.
5. In `'fastest'`, the indexer is still the floor, but a drop ends the stream only once
   the indexer has been down for over `indexer_reconnect_window` seconds (a dYdX
   setting; default 3 s, which covers the usual reconnection; `0` ends it at the drop).
   While it reconnects the other sources race on. Backfilled fills are deduplicated like
   any copy but not counted as leads, since their lateness measures the gap, not the
   source. (Amends 0050 decision 5.)
6. Each fill is recorded and logged once per client: among the `'fastest'` streams of
   one market, only the oldest records the race, and the next takes over when it
   leaves. The client logs its statistics every 10 minutes while any `'fastest'` stream
   is open, once, not once per stream. (Amends 0050 decision 6.)

## Consequences

1. A short indexer drop no longer restarts `'fastest'` tasks: a hedger keeps its socket
   or node fills through it and loses no indexer fill. A longer one (over the window)
   ends them, as do all drops for `'indexer'` streams, which then restart as before and
   skip the fills of the gap (their caller's reconciliation covers them).
2. A reconnection costs one subscribe per channel plus, for the parent channel, one REST
   fills request per 1000 fills of the gap and one order request per order in it.
3. Backfilled fills carry no `eventId` or `transactionHash` (REST does not return them).
4. The backfill trusts REST to have every fill up to the subscription's height; an
   indexer serving REST from a lagging replica could miss the newest ones.
5. Over 1000 fills in one block of the gap is logged as a warning, and the rest of that
   block's fills are missed.
