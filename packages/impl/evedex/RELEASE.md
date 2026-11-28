# tribulnation-evedex 0.1.1

Requires SDK >=4.1.0 and typed-evedex >=0.1.0 (unchanged).

Changed:

1. `place_order` no longer reads the account's positions before every order (#412). It
   signs the leverage from the last stored positions answer, whatever its age
   (`account.ANY_AGE`), so only the first order reads it and every later order is one
   request: about 280 ms less per order from Asia, about 20 ms from Frankfurt.
   `set_leverage` drops the stored answer as before, and a refused order now drops it
   too, so a leverage changed by hand on the venue is read again on the next order.

Every other method is unchanged.

Release qualification on 2026-11-28 passed the read suites and market consistency on a
public account only, by policy ([ADR 0072](../../../dev-docs/adr/0072-public-only-release-qualification.md)):
account reads, orders and Report are NOT verified by release evidence; the order change
is unit-tested (`test_orders_reuse_the_stored_leverage`) and not verified live.
Committed evidence under `release-evidence/evedex/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
