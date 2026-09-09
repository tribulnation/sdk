# Deribit SDK

Read-only ledger reporting, wallet network methods and reward-bearing balances.
The Market prototype is not yet a supported package surface.

```python
from tribulnation.sdk import ReportSDK, accounts

reports = ReportSDK({'deribit': accounts.Deribit()})
async with reports.venue('deribit') as report:
  snapshot = await report.snapshot()
  async for record in report.history():
    print(record)
```

1. Currency and subaccount lists are discovered automatically. Omitted history bounds
   select the last 30 days; explicit bounds are preserved. API history is best-effort,
   and assets removed from discovery may require file ingestion.
2. Deposits, withdrawals and transfers are classified. Trades, mixed PnL/funding
   settlements and other events remain `UnknownObservation` with their signed cash
   change; they are not mislabelled as futures fills or funding payments.
3. Snapshot balances are cash balances, not equity including the positions also listed.
   Position quantities use signed base units, and subaccounts use stable numeric ids.
4. `Wallet.new(public=True)` exposes published networks. Withdrawal fees and required
   confirmations are currency-level figures; token contract addresses are unavailable.
5. `Earn.new(public=True)` lists published seven-day SMA APRs on reward-bearing
   balances. These are not subscription products or account-eligibility guarantees.
6. Use `accounts.Deribit(venue='deribit_testnet')` for testnet. It selects separate
   hosts and `TEST_DERIBIT_CLIENT_ID` / `TEST_DERIBIT_CLIENT_SECRET` defaults; mainnet
   never falls back to those test credentials.
