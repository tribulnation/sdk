# ADR 0012: Deribit public mainnet and private testnet qualification

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-10
3. Amends: ADR 0006 for Deribit non-market release evidence only.

## Context

Only testnet private credentials are available for Deribit. Its packaged SDK
surfaces are Wallet, Earn and Report; Markets remains deferred. Wallet currency/
network metadata and Earn APRs use public mainnet endpoints. Report snapshots and
account history require credentials. These are different qualification scopes.

## Decision

1. Keep market discovery, IDs and price consistency mainnet-only for every venue.
   No testnet substitution is introduced into the market evidence runner.
2. Allow Deribit non-market qualification to combine mainnet Wallet/Earn tests
   with private testnet Report tests. Run both groups against their actual configured
   environments and record the network for every fixed test ID.
3. Require all six public mainnet checks and all six private testnet checks to pass
   without skips, with matching fingerprints. Reject network relabeling, incomplete
   groups and use of this exception by other implementations.
4. Expose this through `sdk-dev test surfaces deribit --testnet-account <alias>`.
   The primary account must remain mainnet. Without that option, normal all-mainnet
   qualification remains available. Non-market evidence uses payload version 2.
5. Evidence summaries and release notes must state that mainnet private-account
   behavior is unverified. Testnet functional success does not establish mainnet
   balances, permissions, history completeness, production behavior or trading safety.

## Alternatives and consequences

Rejecting testnet entirely would discard useful functional verification; pretending
it were mainnet would be false evidence. Explicitly separated results preserve both
the mainnet metadata requirement and the limitation of available credentials.
No SDK market implementation, trading, transfers, merge or publication is authorized
by this decision. Other venues retain the existing mainnet qualification policy.
