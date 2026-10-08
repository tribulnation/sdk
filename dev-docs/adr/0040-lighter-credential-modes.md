# ADR 0040: Lighter credential modes and public account reads

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-10-08

## Context

Lighter accounts are public: `/api/v1/account` and the account's trades answer
without credentials. Private reads (`accountLimits`, active and client-indexed
orders, `positionFunding` of master accounts, account streams) need an auth token;
transactions need an API key. Lighter also issues read-only `ro:` tokens, which
`typed-lighter` already accepts, so a user can grant reads without a signing key.

The Market adapter knew only API keys. Every account-scoped method resolved the
account from the client's credentials, so a `public = true` account failed all of
them, although most need no credentials, and a token holder could not configure one.

## Decision

1. `accounts.Lighter` gains an optional `auth_token`, defaulting to the network's
   `AUTH_TOKEN` variable. A private account needs an API key or a token. The token
   names its account, so `account_index` is optional with it.
2. Without credentials, public account reads (`position`, `collateral`,
   `perp_position`, `perp_collateral`, `leverage`, `available_notional`,
   `trades_history`) use the configured `account_index`, else the master account of
   the configured `address`. The master account is the address's account with
   `account_type` 0, as the venue reports it; it is resolved once per venue
   object. Sub-accounts are read only through an explicit `account_index`.
3. `fees`, `open_orders`, `query_order`, `funding_payments` and `trades_stream`
   need a token or an API key. `funding_payments` would answer for sub-accounts
   without one, but the venue rejects master accounts (`auth required for main
   accounts`), so it is token-only to keep one rule. Trading needs an API key.
   Each raises `AuthError` naming what is missing, before any request.

This is not an implicit account (ADR 0036): reads only use an account or address the
user configured, and an account without either raises `AuthError`.

## Alternatives considered

1. Keep account reads credential-only: simple, but forces a signing key or token on
   users who only need public figures the venue publishes.
2. Resolve `address` to every account and aggregate: Market methods are scoped to
   one account, and aggregation is Report's job (Report already snapshots every
   account of an address).
3. Resolve `address` to its first listed account: the order is not documented,
   whereas `account_type` names the master account.

## Consequences

`MarketSDK` builds Lighter from the new `auth_token` and `address` fields, so the
Lighter adapter requires the SDK release containing them. Public `trades_history` was
checked live on mainnet to carry the same rows, client order indexes included, as the
private read. On testnet, a read-only `ro:` token served every read above and
trading raised `AuthError`; unit tests cover the same paths.

`typed-lighter` falls back to the network's `API_KEY_INDEX`/`API_PRIVATE_KEY`
variables when no API key is passed, so an account configured with only a token
still signs when those variables are set. Token-only operation therefore needs them
unset; an opt-out belongs in `typed-lighter`.
