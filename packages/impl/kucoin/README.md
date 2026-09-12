# Kucoin SDK

Read-only Classic spot-side reporting, wallet network methods and simple Earn listings.
The Market prototype is not yet a supported package surface.

```python
from tribulnation.sdk import ReportSDK, accounts

reports = ReportSDK({'kucoin': accounts.Kucoin()})
async with reports.venue('kucoin') as report:
  async for record in report.history():
    print(record)
```

1. History discovers spot markets automatically; no holdings-based filter or caller
   market list is required. Per-symbol sweeps can
   require many requests. Omitted bounds select seven days of spot fills and 30 days
   for deposits/withdrawals; explicit bounds are preserved and rows are filtered locally.
2. History is best-effort. Retention, delisted symbols, dedicated margin activity,
   Earn accruals and other unsupported ledgers leave gaps for file ingestion.
3. Snapshots include Classic main/trade balances and paginated Earn holdings.
   Futures and legacy margin/isolated compartments are explicitly excluded, not
   reported as zero exposure. Neither history nor snapshots call futures endpoints.
   No Futures permission or scope configuration is needed. Rejected supported reads
   fail rather than claiming zero balances. Other user subaccounts remain unsupported.
   The underlying Typed futures APIs are unchanged.
4. `Wallet.new(public=True)` lists enabled chains with native `chainId` identifiers.
   Withdrawal fees are the published minimum, not a quote for a specific transfer.
5. Earn lists five simple savings/staking families. Structured dual investments are
   excluded because their contingent principal conversion is not a plain APR product.
