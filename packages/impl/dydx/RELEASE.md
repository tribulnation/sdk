# tribulnation-dydx 0.7.0

## SDK 2 compatibility

1. Requires tribulnation-sdk >=2.0.0 and the Typed dependency floors declared in this package.
2. Adopts bounded candles and exchange metadata, corrects unknown last-trade/volume semantics, and makes native requests participate in SDK retries.
3. Review the coherent implementation changes in [SDK 2](https://github.com/tribulnation/sdk/pull/19). This package release follows that source change; it does not change the agreed runtime contract again.
4. Block timestamp reads now share the existing four-request chain concurrency bound.
   Archive-backed history is retained; there is no pruning fallback or silent truncation.

## Publication order

1. Required Typed packages are already published and were used for qualification. Publish tribulnation-sdk 2.0.0 before this implementation.
2. This PR is stacked on release/sdk so its own diff contains only this package's release handoff. After SDK #19 merges, retarget to main if GitHub has not done so automatically, refresh the branch and check CI before merging.
3. Merging release/dydx into main triggers publication of tribulnation-dydx 0.7.0. No merge or publication has occurred during PR preparation.
4. Catalogue #104 has merged. Fresh evidence under the stronger all-read-suite policy must pass before release; previous narrower evidence is insufficient.

## Qualification

1. ADR 0013 requires all supported read-only suites through sdk-dev test surfaces, plus sdk-dev test consistency for market implementations. The two reports cannot substitute for each other.
2. Record fresh evidence under release-evidence/dydx/surfaces/ and, where applicable, consistency/. Historical reports directly under the venue directory do not qualify this release.
3. Fresh all-read and consistency qualification completed on mainnet on September 12,
   including Report snapshot and archive-backed history. Both reports verify against
   the reconstructed release candidate. All 725 candidate unit/regression tests pass.
   Missing credentials, unexpected skips, failures and mismatched fingerprints still
   block release; passing this selected account does not qualify every account/provider.
4. Obtain explicit approval before merging or publishing; passing CI alone is not authorization.
