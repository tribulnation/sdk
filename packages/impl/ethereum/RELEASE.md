# tribulnation-ethereum 0.6.0

## SDK 2 compatibility

1. Requires tribulnation-sdk >=2.0.0 and the Typed dependency floors declared in this package.
2. Uses typed-ethereum >=0.2.0 via typed_ethereum alongside the current Alchemy, Etherscan and Moralis clients. API-based portfolio history remains best-effort.
3. Review the coherent implementation changes in [SDK 2](https://github.com/tribulnation/sdk/pull/19). This package release follows that source change; it does not change the agreed runtime contract again.

## Publication order

1. Required Typed packages are already published and were used for qualification. Publish tribulnation-sdk 2.0.0 before this implementation.
2. This PR is stacked on release/sdk so its own diff contains only this package's release handoff. After SDK #19 merges, retarget to main if GitHub has not done so automatically, refresh the branch and check CI before merging.
3. Merging release/ethereum into main triggers publication of tribulnation-ethereum 0.6.0. No merge or publication has occurred during PR preparation.
4. Catalogue [#104](https://github.com/tribulnation/catalogue/pull/104) must merge before the offline evidence gate can pass against Catalogue main. Check remote CI and obtain explicit release approval before merging. Terminal rollout and exact Catalogue coverage remain separate.

## Qualification

1. Mainnet Report checks pass. API-based account history remains best-effort; this does not establish exhaustive transaction-history coverage.
2. Sanitized local results, content fingerprints and published dependency pins are committed under [release-evidence/ethereum](https://github.com/tribulnation/sdk/tree/release/sdk/release-evidence/ethereum). All 12 reports independently verify in a second clean environment.
3. The shared candidate passes 682 unit/regression tests; local type checking, lint and docs checks pass. Release CI verifies evidence again, and publication checks the exact merged commit.
