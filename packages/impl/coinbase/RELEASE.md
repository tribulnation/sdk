# tribulnation-coinbase 0.2.0

## SDK 2 compatibility

1. Requires tribulnation-sdk >=2.0.0 and the Typed dependency floors declared in this package.
2. Distinguishes Advanced Trade spot and International Exchange perpetuals (`intx`, full native IDs), adds bid/ask enrichment, and uses public INTX funding history. SDK product discovery still requires Coinbase credentials; public INTX history does not grant private access.
3. Review the coherent implementation changes in [SDK 2](https://github.com/tribulnation/sdk/pull/19). This package release follows that source change; it does not change the agreed runtime contract again.

## Publication order

1. Required Typed packages are already published and were used for qualification. Publish tribulnation-sdk 2.0.0 before this implementation.
2. This PR is stacked on release/sdk so its own diff contains only this package's release handoff. After SDK #19 merges, retarget to main if GitHub has not done so automatically, refresh the branch and check CI before merging.
3. Merging release/coinbase into main triggers publication of tribulnation-coinbase 0.2.0. No merge or publication has occurred during PR preparation.
4. Catalogue #104 has merged. Fresh evidence under the stronger all-read-suite policy must pass before release; previous narrower evidence is insufficient.

## Qualification

1. ADR 0013 requires all supported read-only suites through sdk-dev test surfaces, plus sdk-dev test consistency for market implementations. The two reports cannot substitute for each other.
2. Record fresh evidence under release-evidence/coinbase/surfaces/ and, where applicable, consistency/. Historical reports directly under the venue directory do not qualify this release.
3. Fresh complete live qualification remains pending. Missing credentials, unexpected skips, failures and mismatched fingerprints block release. The approved Deribit mainnet-public/testnet-Report split is unchanged; it does not establish mainnet private-account behavior.
4. Obtain explicit approval before merging or publishing; passing CI alone is not authorization.
