# ADR 0010: Defer Bitget UTA coin support

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-10
3. Amends: [ADR 0008](0008-bitget-classic-and-uta-coin.md)

## Decision

1. Defer UTA `coin` markets until further products or consumer needs justify a
   native quote-sized quantity contract. Keep the present base-unit SDK rules.
2. Reserve `coin` for UTA native `*_CM` instruments, but do not advertise it in SDK
   discovery. Explicit requests raise `NotImplementedError`, not a Classic alias.
3. Expose existing Classic coin support as `coin-classic`, with native `BTCUSD` IDs.
   Keep Classic live qualification mandatory. Do not infer retirement from this deferral.
4. Explicitly exclude Catalogue `(bitget, perp, coin)` rows from qualification;
   preserve them as visible exclusions rather than passing observations or coverage
   drift. Other unknown exchanges still fail. Do not delist active UTA Catalogue rows.
5. Keep Typed's valid UTA responses independently releasable. A Typed validation
   fix does not imply support for the corresponding high-level SDK contract.

## Rationale and follow-up

UTA coin order quantities are USD-sized. A native $1 increment is not a fixed BTC
increment, and converting to base then back can lose a native rounding boundary.
No exact base-size execution guarantee follows from an estimated price conversion.

[SDK issue #32](https://github.com/tribulnation/sdk/issues/32) records the evidence,
unit/rounding requirements, and conditions for revisiting support. No speculative
quantity abstraction, trading, account migration, merge or publication is included.
