# tribulnation-sdk 3.0.0

Funding payment amounts are now account cash flows: **positive means received,
negative means paid**. Zero remains zero. This applies to market-specific history
and exchange-wide history where supported. Funding rates, trading fee signs,
pagination, account scope and Report cash-flow signs are unchanged.

This is a breaking sign change from the previous release. Upgrade SDK >=3.0.0
together with Hyperliquid >=0.11.0, dYdX >=0.11.0, Bybit >=0.5.0, Aster >=0.5.0,
and Lighter >=0.4.0 for whichever adapters you use. Older published adapters do
not declare an SDK upper bound, so upgrading the SDK alone cannot enforce this
migration. Do not mix old and new adapter sign conventions.

For persisted funding history, refetch or negate records from the paid-positive
versions exactly once. Older Hyperliquid/dYdX records predating the exchange-wide
history sign change already used received-positive amounts; leave those alone.
Never apply this conversion to funding rates or Report observations.

Offline regression tests cover funding income, expense and zero, plus history
scope, filtering and page retry behavior. Release qualification uses the normal
read-only surfaces and consistency suites; it does not assert personal history
completeness. Deribit Report qualification is testnet-only under ADR 0012.

Qualification on 2026-10-05: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against Catalogue commit `1851660ac2bed8243dd9ce9c7297fe05c7130973`. Bit2Me's first
two attempts failed transient reads; only the subsequent fully passing fresh run
is committed. The existing Bit2Me native-ticker limitation remains visible.

All 1,303 repository unit tests pass, and the six release packages pass Ruff and
Pyright. The broader PoC check reports 22 pre-existing fee/type errors, reproduced
on the pre-change baseline. Updated funding example cells are marked not rerun
live; regression fixtures establish their new sign mapping.
