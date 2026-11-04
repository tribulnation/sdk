# ADR 0060: Bitget qualifies with its UTA account

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; amends [ADR 0042](0042-read-only-account-method-qualification.md)
2. Date: 2026-11-04

## Context

Bitget release evidence was recorded with the tracked Classic account
(`bitget_classic`, `uta = false`), and ADR 0042 excluded its perpetual
`collateral`/`perp_collateral` reads as `bitget_classic`. That account has since been
upgraded to a Unified Trading Account, so it no longer exists as a Classic account and
cannot record evidence.

## Decision

1. `sdk.test.toml` tracks one mainnet Bitget account, `bitget_uta` (`uta = true`), and
   Bitget qualifies with `--account bitget_uta`. The `bitget_classic` account and its
   `BITGET_CLASSIC_*` variables leave the accounts file.
2. With a UTA account no case is excluded as `bitget_classic`: perpetual `collateral`
   and `perp_collateral` are observed like every other declared account read.
3. The `bitget_classic` exclusion of ADR 0042 decision 3 is unchanged and still applies
   to a report recorded with a Classic account. Keeping it leaves qualification tooling
   unchanged, so evidence of other venues stays valid (ADR 0033).

## Consequences

1. Release evidence now attests Bitget UTA behaviour and no longer Classic behaviour
   (ADR 0042 consequence 2). Classic accounts remain supported by the adapter but are
   unobserved by release evidence.
2. Bitget needs fresh surfaces and consistency reports recorded with `bitget_uta`.
   The adapter's UTA wallet and earn reads, which raised `NotImplementedError`, are
   implemented for it (tribulnation-bitget 0.13.0): deposit and withdrawal methods read
   the public coin list, which serves both modes, and earn instruments list the on-chain
   Elite products, the only earn products the UTA API lists. Nothing is declared
   unsupported.
3. The Classic proof-of-concept scripts (`packages/impl/bitget/poc/*/classic.py`) are
   removed with the account; their `uta.py` counterparts remain.
