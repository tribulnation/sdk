# tribulnation-mexc 2.0.0

## SDK 2 compatibility

1. Requires tribulnation-sdk >=2.0.0 and the Typed dependency floors declared in this package.
2. Adds public linear perpetual candles, funding and statistics with contract-size conversion, spot history discovery and owned resource cleanup. Requested missing snapshot rows fail visibly.
3. Review the coherent implementation changes in [SDK 2](https://github.com/tribulnation/sdk/pull/19). This package release follows that source change; it does not change the agreed runtime contract again.

## Publication order

1. Publish typed-core 0.8.1 and the required Typed clients first, then tribulnation-sdk 2.0.0, then this implementation.
2. This PR is stacked on release/sdk so its own diff contains only this package's release handoff. After SDK #19 merges, retarget to main if GitHub has not done so automatically, refresh the branch and check CI before merging.
3. Merging release/mexc into main triggers publication of tribulnation-mexc 2.0.0. No merge or publication has occurred during PR preparation.
4. Fresh installed SDK/implementation regressions pass 418 tests; the full candidate source suite passes 496. Package-specific remote CI must be checked after prerequisites are available. Terminal/Catalogue work is separate.

