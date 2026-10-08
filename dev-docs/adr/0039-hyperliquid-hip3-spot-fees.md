# ADR 0039: Hyperliquid HIP-3 and spot fees via the official formula

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified; decision 7 (fee reads in the
   public suite) amended by [ADR 0042](0042-read-only-account-method-qualification.md)
2. Date: 2026-10-08
3. Amends: [ADR 0002](0002-combined-side-specific-fees.md) for Hyperliquid, and the
   Hyperliquid exclusion recorded in [ADR 0001](0001-public-rules-and-account-fees.md)

## Context

ADR 0001 recorded that Hyperliquid account rates omitted HIP-3 deployer and growth-mode
adjustments and quote-token adjustments. Under ADR 0002, which requires complete
rates, the adapter therefore supported only default-dex USDC perpetuals: HIP-3
perpetuals and every spot market raised `NotImplementedError`, and their public
`rules().fees` were `None`.

Hyperliquid publishes the formula its frontend uses ("Fee formula for developers" in
the [fees documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)).
Its inputs are the `userFees` rates (perpetual `userAddRate`/`userCrossRate`, spot
`userSpotAddRate`/`userSpotCrossRate`, staking already included), the active referral
discount, whether the pair is a stable pair (spot, ×0.2), the asset's
`deployerFeeScale` and growth mode (HIP-3 perpetuals), and whether the quote token is
an aligned quote token.

Two of those inputs were previously unavailable:

1. The per-asset `deployerFeeScale`, `growthMode` and `lastFeeScaleChangeTime` are
   returned live by `meta(dex)`, but `typed-hyperliquid` stripped them during validation.
   The dex-level `perpDexs[].deployerFeeScale` it does type is absent on every dex. The
   typed client now types the per-asset fields.
2. Aligned quote token status. `alignedQuoteTokenInfo` answers HTTP 422 on mainnet and
   testnet for every request shape. The fee documentation states that only AQAv1 aligned
   quote tokens change fees; AQAv2, which USDC joined on 2026-08-26, carries no fee
   benefit.

On 2026-10-08 a read-only comparison over thousands of public fills reproduced the
formula with the aligned flag off on: default-dex BTC; the USDC-collateral HIP-3 dexes
`xyz`, `para`, `mkts` and `io` (growth mode, scale 1.0); USDC-quoted spot; the USDT0/USDC
stable pair (×0.2); and HYPE/USDE. The same check through the SDK
(`packages/impl/hyperliquid/poc/fee_regression.py`) matched all 27,018 sampled fills on
BTC, `xyz:SILVER`, `para:VST`, UBTC/USDC, USDT0/USDC and HYPE/USDE within one unit of
the charged amount's precision. Earlier samples had a few mismatches on one market
(under 3% of its maker fills), consistent with, but not confirmed as, tier changes
inside the one-day window. Fill fee tokens also showed that spot
charges are paid in the token received (base on buys, quote on sells), while maker
rebates are credited in the token given.

Every HIP-3 dex with non-USDC collateral (USDH, USDE, USDT0) was fully delisted, and
USDH-quoted spot had almost no activity, so their aligned status could not be
confirmed from fills either.

## Decision

1. Port the official `feeRates` to `Decimal` once, shared by perpetuals and spot, with
   the aligned quote token flag fixed to false. The aligned branches are not ported.
2. Perpetuals with USDC collateral (token index 0), on the default dex or a HIP-3 dex,
   apply the asset's `deployerFeeScale` (0, scaling by 1, on the default dex) and growth
   mode. A HIP-3 asset without `deployerFeeScale` is unsupported, not scaled by 1.
3. Spot pairs quoted in USDC or USDE use the spot rates; a pair whose base is also a
   spot quote token (derived from `spotMeta.universe`) is a stable pair.
4. `fees()` applies the formula to the account's rates and referral discount;
   `rules().fees` applies it to the public standard schedule with no referral.
5. Other collateral or quote tokens (USDH, USDT0, ...) raise `NotImplementedError` from
   `fees()` and return `rules().fees=None`, until aligned status is readable from the
   API or otherwise verified. Only AQAv1 tokens are treated as aligned.
6. Perpetual `rules().fee_asset` is the collateral token's index, the same identifier as
   `Trade.fee.asset` and balances. Spot `rules().fee_asset` is `None` (ADR 0028);
   `Trade.fee.asset` names each fill's token.
7. The read-only market suite covers Hyperliquid `fees()` on its reference markets,
   which include a HIP-3 market (`xyz:SILVER`) and a USDC spot pair. It needs only an
   address, so it runs on public accounts with `HYPERLIQUID_ADDRESS` configured. Other
   venues' account fees still need private credentials and stay out of that suite.

## Alternatives considered

1. Keep HIP-3 and spot unsupported until `alignedQuoteTokenInfo` works. Rejected: for
   USDC and USDE the documented AQAv2 rule and the live fills agree, and USDC is the
   collateral of every live HIP-3 dex and the quote of 313 of 330 spot pairs.
2. Treat every quote token as non-aligned. Rejected: the aligned status of USDH and
   USDT0 is unknown and could not be checked against fills; a wrong guess would
   misstate rates silently.
3. Read the dex-level `perpDexs[].deployerFeeScale`. Rejected: it is absent live, and
   the scale is per asset (`para` lists 0.5 and 1.0 on the same dex).
4. Name the quote token as the spot fee asset. Rejected by ADR 0028's reasoning: it is
   wrong for every buy and for every maker rebate on a sell.

## Consequences

1. HIP-3 USDC perpetuals and USDC/USDE spot gain complete `fees()` and public rule fees.
   Consumers reading the perpetual `fee_asset` get `'0'` instead of `'USDC'`, and spot
   consumers get `None` instead of the quote index.
2. The adapter requires a `typed-hyperliquid` release with the per-asset fields; until
   then validation strips them and every HIP-3 asset is declined as missing its scale.
3. A Hyperliquid fee schedule change, a new aligned quote token, or an AQAv1 token
   gaining USDC-like status requires revisiting the supported token sets. The fill
   comparison script is the regression check for that.
4. The fees read and the HIP-3 reference market change live qualification, so every
   venue's read-suite evidence must be recaptured on the next release (ADR 0033).
5. Acceptance does not attest release readiness; release evidence remains separate.
