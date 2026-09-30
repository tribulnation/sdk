# tribulnation-lighter 0.3.0 release candidate

Report snapshots.

- `Report.new(owner)` snapshots every account (master and sub-accounts) of an L1
  address, credential-free; given an account index instead, it looks up that
  account's address first. `ReportSDK` uses the account's `address`, else its
  `account_index`.
- Each account is a `<index>` subaccount: spot plus margin balances and the margin
  allocated to isolated positions (no unrealized PnL), and signed positions by
  `market_id`.
- Pool shares (public pools, the LLP, LIT staking) are `<index>:pool:<pool>`
  subaccounts holding the pro-rata part of the pool's USDC equity and other balances.
  A pool the address operates contributes only the operator's shares
  (`<pool>:operator`); LIT in its unstaking lockup is `<index>:unlocking`.
- `history()` raises `NotImplementedError`.

Requires tribulnation-sdk >=2.8.0 (`ReportSDK` routing and `accounts.Lighter.address`)
and typed-lighter >=0.2.0.

Release qualification records mainnet read suites, including the Report snapshot of a
funded account, and Market consistency against the pinned Catalogue snapshot. Pool
claims were checked live on public accounts against the venue's PnL chart; the
qualification account holds no pool shares. Account and trading methods remain
verified on testnet.
