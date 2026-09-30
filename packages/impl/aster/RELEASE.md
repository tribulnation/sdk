# tribulnation-aster 0.4.0 release candidate

Report snapshots.

- `Report.snapshot()` reads mainnet, signed by the trading agent: a `perp` subaccount
  with the futures wallet balances (no unrealized PnL) and open positions by symbol
  with their entry prices, a `spot` subaccount with free plus locked balances, and a
  `staking` subaccount with ASTER staked on Aster Chain (active, pending and
  unstaking) plus unclaimed rewards. Hedge-mode legs merge into one net position.
- `ReportSDK` routes Aster accounts for snapshots.
- Testnet snapshots raise `NotImplementedError`: testnet spot account information
  omits funded balances. `history()` is unchanged and verified on testnet only.

Requires tribulnation-sdk >=2.8.0 (`ReportSDK` routing) and typed-aster >=0.2.0.

Release qualification records mainnet read suites, including the signed Report
snapshot of a funded account, and Market consistency against the pinned Catalogue
snapshot. The snapshot matched the address-only `aster_getBalance` wallets and its
implied entry price. The qualification account holds no spot balance or stake, so
those subaccounts were read empty. Account and trading methods remain verified on
testnet.
