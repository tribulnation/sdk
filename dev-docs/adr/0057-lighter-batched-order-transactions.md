# ADR 0057: Lighter sends waiting order transactions as one `sendTxBatch`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-10-29

## Context

A Lighter Standard account has 60 requests per rolling minute, per L1 address and IP,
reads included. On Standard, `sendTx` and `sendTxBatch` come out of that same budget;
Premium and Plus accounts have a separate transaction bucket. A strategy that requotes
a few orders at once spends one request per order transaction: a cancel and a placement
per order, or one modify with `settings={'lighter': {'replaces': id}}`.

`sendTxBatch` takes up to 50 signed transactions in one request. Lighter advises 15 or
fewer over REST, to stay within its CDN's request size. The venue runs them back to back
with consecutive nonces of one API key. `typed-lighter` signs them in advance
(`client.signer`, `tx.reserve_nonces`) and submits them (`tx.batch`). It already sends one
key's transactions one at a time: the key's lock is held from signing through
submission.

Lighter documents neither how a batch counts against a Standard account's budget nor
what happens to the rest of a batch when it refuses one transaction. The reply carries
one code and a hash per accepted transaction.

The SDK's `place_orders` and `cancel_orders` gather single calls. `place_orders` takes one
`settings` for every order, so it cannot carry a `replaces` per order. The engine gateway
proxies only the SDK's methods, so a Lighter-only batch method would not reach
strategies behind it.

## Decision

1. Every Lighter create, modify and single-order cancel goes through one batcher per
   client (`tribulnation.lighter.batching.TxBatcher`), which sends one request at a time.
   A transaction submitted while nothing is in flight goes alone through `sendTx`,
   exactly as before.
2. Transactions submitted while one is in flight, or in the same event-loop turn, wait
   for it. They then leave together in one `sendTxBatch`, at most 15 per request, oldest
   first, signed with consecutive nonces of one key.
3. On acceptance, each transaction gets a `sendTx`-shaped reply with its own hash.
4. A refused batch (`BadRequest`) raises `ApiError` for each of its transactions,
   caused by the refusal. No create in a refused batch is reported as `OrderRejected`,
   because Lighter doesn't say which transaction it refused nor whether it placed the
   others. Every other failure (a rate limit, a network error, a 5xx) reaches every
   transaction unchanged.
5. A call cancelled while its transaction waits drops the transaction. Closing the client
   fails what is in flight or waiting with `NetworkError`.
6. Cancel-all and every non-order transaction keep their own `sendTx`.

## Alternatives considered

1. A core batch method (place, modify and cancel per order): a public contract change,
   and an SDK release before the adapter's. Every venue would have to implement it or
   reject it, for one venue's request budget.
2. Override `place_orders` and `cancel_orders` with one batch each: this cannot mix
   creates, modifies and cancels, nor carry a `replaces` per order.
3. A linger window that holds a lone transaction a few milliseconds in case another
   follows: this adds latency to every order, hedges included, to save requests only for
   callers that don't send concurrently.
4. Opt-in batching through an account setting: account settings live in the core SDK,
   and waiting transactions cost no extra latency, since one key's transactions already go
   one at a time.

## Consequences

1. Concurrent order transactions on one client spend one request per 15 instead of one
   each. A caller gets this by sending them concurrently (`asyncio.gather`, or
   `place_orders`/`cancel_orders`).
2. Transactions batched together share one fate: a refusal or a rate limit of the batch
   fails them all. A refused batch's creates are ambiguous (`ApiError`) rather than
   certain refusals. Callers already handle `ApiError` from a single `sendTx` (a 5xx).
3. The first transaction runs in the batcher's task, not the caller's. Middleware sees
   the caller's `call` around its wait.
4. Clients with several API keys no longer send concurrently on different keys. The SDK
   configures one key per account.
5. Verification still needed against the live venue:
   1. whether a batch counts as one request against a Standard account's 60;
   2. whether a refused batch places none of its transactions.
   If refusals turn out to be all-or-nothing, decision 4 can report `OrderRejected` again.
