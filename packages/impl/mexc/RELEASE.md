# tribulnation-mexc 2.0.1

Retry individual MEXC funding pages and deposit/withdrawal history windows through the SDK context.

Requires tribulnation-sdk >=2.0.1. The implementation and version bump are included in [SDK #41](https://github.com/tribulnation/sdk/pull/41); this release handoff publishes the implementation after SDK 2.0.1 is available.

The release workflow verifies current read-suite and market-consistency reports under `release-evidence/mexc/` before publishing. The live checks use read-only operations.
