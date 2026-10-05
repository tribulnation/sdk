# tribulnation-hyperliquid 0.11.0

Funding payment amounts are now account cash flows: **positive means received,
negative means paid**. Zero remains zero. This applies to market-specific history
and exchange-wide history where supported. Funding rates, trading fee signs,
pagination, account scope and Report cash-flow signs are unchanged.

This is a breaking sign change from the previous release. Upgrade SDK >=2.10.0
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
completeness.

Release qualification on 2026-10-05 passed: 25 read-suite cases, 6 declared
exclusions, and market consistency. Committed evidence under
`release-evidence/hyperliquid/` matches pinned Catalogue
`1851660ac2bed8243dd9ce9c7297fe05c7130973`. Offline release verification passes.
This adapter release follows SDK 2.10.0 publication.
