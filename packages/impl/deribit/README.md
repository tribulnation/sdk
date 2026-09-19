# Deribit SDK

Public mainnet spot and linear perpetual Market data, read-only ledger reporting,
wallet network methods and reward-bearing balances. The public Market expansion is
available in Deribit 0.3.0 with SDK >=2.2.0; see the [capability handoff](../../../dev-docs/deribit-public-market.md).

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

Public `MarketSDK()` discovery uses `spot` and `perp`, preserving native instrument
names. Books, tickers, streams, native index/mark and linear open interest require
no credentials. Trade candles support `1m`, `5m`, `15m`, `1h` through validated
WebSocket calls and aware half-open windows. Routed spot has no candles; `4h` and
native 08:00 UTC daily candles are unsupported. Rules, scheduled funding, private
Market methods and trading remain explicit gaps. Inverse/dated/option/combo products
are excluded. See [Deribit Market](../../../docs/market/implementations/deribit.md).
