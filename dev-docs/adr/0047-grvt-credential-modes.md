# ADR 0047: GRVT credential modes and definitive order refusals

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified
2. Date: 2026-10-22

## Context

GRVT authenticates every account call with a session opened from an API key; orders
are additionally signed (EIP-712) by the key's signer, whose private key is a separate
secret. An API key can be issued read-only, and the qualification account on mainnet
has only such a key. `typed-grvt` falls back to the `GRVT_*` environment variables when
it is given no secret.

ADR 0042 qualifies account reads by account mode (`address`, `token`, `private`), with a
`token` defined as a credential granting reads but not trading (Lighter's `ro:` tokens,
ADR 0040). ADR 0043 lets each venue opt into `OrderRejected` where its answer makes a
refusal certain. GRVT's gateway answers order validation synchronously, with a `4XX`
and a code (`2064` off-tick price, `2065` size off the step, `2066` below the minimum
notional, margin and reduce-only checks), before the order exists; refusals after
acceptance only show as a `REJECTED` order state.

## Decision

1. `accounts.Grvt` has `venue` (`grvt` or `grvt_testnet`), `api_key`, `private_key`,
   `trading_account_id`, `public` and `validate`. Omitted credentials default to the
   network's `GRVT_` or `GRVT_TESTNET_` variables, resolved by the account; the adapter
   is built with explicit arguments and never reads the environment itself.
2. Three modes: no API key is public (market data only); an API key alone serves every
   account read; the key's `private_key` adds placing orders. Cancellations are not
   signed and need only the API key. A private key without an API key is refused.
3. For release qualification an API key without a private key is a `token`: it reads
   and cannot trade. GRVT's `[qualification.market]` is `min_mode = "token"` with every
   account read in `token_methods`, so the read-only mainnet key qualifies.
4. `place_order` raises `OrderRejected` for a `BadRequest` carrying the venue's code,
   message and body. Excluded: `2012` (client order id overlaps an active order),
   since that order may be the caller's own earlier, accepted attempt; non-JSON errors
   and client-side checks, which carry no venue code; `5XX` (`ApiError`), auth and
   rate-limit errors, which keep their classes.

## Alternatives considered

1. `min_mode = "private"`: would require a trading key for read-only qualification,
   or would record a read-only key as `private`, a mode it cannot honour.
2. Letting `typed-grvt` read the environment when no key is configured: an account
   configured as public would silently authenticate with whatever key the environment
   holds, and could mix networks' variables with an explicit key.
3. Treating `2012` as a refusal: a caller retrying a timed-out placement with the same
   client order id would be told the order is dead while it rests.

## Consequences

The mainnet qualification account carries `GRVT_API_KEY` and
`GRVT_TRADING_ACCOUNT_ID` only. Testnet trading verification uses `grvt_testnet` with
the private key. `OrderRejected` mapping is covered by unit fixtures; the live testnet
round trip exercised `2064` and `2065` as refusals in the PoC, not through the adapter.
The isolated-margin bucket was unverified here, since `typed-grvt` 0.1.0 lacked
`set_position_config`; with 0.2.0 it is implemented and verified on testnet, and margin
types are still set on the venue, not through the SDK.
