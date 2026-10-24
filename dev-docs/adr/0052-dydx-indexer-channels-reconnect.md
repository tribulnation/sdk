# ADR 0052: dYdX indexer channels reconnect, and the fills of a gap are backfilled

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested with scripted channels and checked live
   by forcing drops of the indexer WebSocket. Not release-verified. Amends
   [0050](0050-dydx-fill-socket.md) decisions 5 and 6.
2. Date: 2026-10-24

## Context

Every indexer channel of a dYdX client (the parent subaccount's, and each book of
`depth_stream`) shares one WebSocket. The indexer drops that connection several times
an hour (`ConnectionClosedError: no close frame received or sent`), and each drop ended
every subscriber with `NetworkError`: every `trades_stream` (including `'fastest'`,
whose floor is the indexer, even while the node or socket kept delivering) and every
book stream. Callers restarted after their own backoff, losing state each time, and an
`'indexer'` stream silently skipped the fills of the gap.

Separately, `'fastest'` logged its statistics once per stream and each lead once per
stream of the market, so a process with several streams of one market (a hedger and a
position tracker, say) logged each fill several times and counted it several times.

## Decision

1. Each indexer channel reconnects on its own: when its items fail with `NetworkError`
   or end, it is released and reopened with exponential backoff (0.5 s doubling to 8 s),
   and its items go on from the new subscription. Subscribers see a gap, not an end.
   Connection errors and the indexer's REST rate limiting or failing on its side are
   retried; a rejected request is not. Only a channel down for 60 s ends its
   subscribers with the last error.
2. The parent subaccount channel backfills each gap from REST: the fills between the
   last block the channel reached and the new subscription's `blockHeight` (both
   included) are read from `/v4/fills/parentSubaccountNumber`, with their orders from
   `/v4/orders/{id}` for the SDK order ids, and delivered as one notification before
   the live ones. Fills are remembered by id for 100 blocks, so a fill the channel and
   the backfill both carry is delivered once. A failed backfill fails the reconnection,
   which is retried as in 1, so a gap is never skipped silently.
3. A book channel restarts from the new subscription's snapshot, delivered at once.
4. In `'fastest'`, the indexer is still the floor, but only its lasting failure (1)
   ends the stream; while it reconnects the other sources race on. Backfilled fills are
   deduplicated like any copy but not counted as leads, since their lateness measures
   the gap, not the source. (Amends 0050 decision 5.)
5. Each fill is recorded and logged once per client: among the `'fastest'` streams of
   one market, only the oldest records the race, and the next takes over when it
   leaves. The client logs its statistics every 10 minutes while any `'fastest'` stream
   is open, once, not once per stream. (Amends 0050 decision 6.)

## Consequences

1. An indexer drop no longer restarts every dYdX task; a hedger keeps its socket or
   node fills through it, and indexer-only streams lose no fill.
2. A reconnection costs one subscribe per channel plus, for the parent channel, one REST
   fills request per 1000 fills of the gap and one order request per order in it.
3. Backfilled fills carry no `eventId` or `transactionHash` (REST does not return them).
4. The backfill trusts REST to have every fill up to the subscription's height; an
   indexer serving REST from a lagging replica could miss the newest ones.
5. Over 1000 fills in one block of the gap is logged as a warning, and the rest of that
   block's fills are missed.
