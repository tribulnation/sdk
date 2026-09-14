# tribulnation-hyperliquid 0.7.1

Retry individual market-history pages and require typed-hyperliquid >=2.1.1 for staking deposit and withdrawal validation.

Requires tribulnation-sdk >=2.0.1. The implementation and version bump are included in [SDK #41](https://github.com/tribulnation/sdk/pull/41); this release handoff publishes the implementation after SDK 2.0.1 is available.

The release workflow verifies current read-suite and market-consistency reports under `release-evidence/hyperliquid/` before publishing. The live checks use read-only operations.
