# tribulnation-sdk 2.8.0 release candidate

Report snapshots route to Aster and Lighter.

- `ReportSDK` routes `aster` accounts to `tribulnation.aster.Report`: mainnet
  snapshots signed by the trading agent (`user` and `signer`), with `perp`, `spot`
  and Aster Chain `staking` subaccounts. Testnet snapshots are unsupported.
- `ReportSDK` routes `lighter` accounts to `tribulnation.lighter.Report`: credential-free
  snapshots of every account of an L1 address, with pool shares as pro-rata pool
  holdings.
- `accounts.Lighter` gains an optional `address` (default `LIGHTER_ADDRESS`). Without
  one, reports resolve the address from `account_index`, so a `MarketSDK`
  configuration works unchanged.

Neither venue implements `history()`. Existing accounts and routes keep working. The
new routes need `tribulnation-aster>=0.4.0` and `tribulnation-lighter>=0.3.0`, released
after this version.

Publication requires fresh all-venue read-suite and applicable Market consistency
evidence against the pinned Catalogue snapshot.
