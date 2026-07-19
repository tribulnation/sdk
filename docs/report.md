# Report

> `Report` provides method to retrieve historical transactions and current balances/positions.

- `history(start?, end?)`: transaction history 
- `snapshot(assets?)`: current balances and positions with their provenance
- `records(start?, end?)` — `history(start, end)` plus a trailing snapshot record when `end=None`

`ReportSDK` has no built-in default accounts (unlike `MarketSDK`/`WalletSDK`/`EarnSDK`) — every account must be listed explicitly. Every `Record` carries a `Provenance` (api/tabular/manual/derived) tracing where it came from. `providers` (BigQuery/Alchemy/Etherscan/Moralis credentials) are only needed by chain-based venues that use them.

**Example:**

```python
from tribulnation.sdk import ReportSDK, accounts
from dotenv import load_dotenv

load_dotenv()

report = ReportSDK({
  'ethereum': accounts.Evm('ethereum'),
  'polygon': accounts.Evm('polygon'),
})

for account, sdk in report.all.items():
  result = await sdk.snapshot()
  snapshot = result.snapshot
  print(f'[{account}] ({snapshot.time:%Y-%m-%d %H:%M:%S}) from {result.provenance["source"]}')
  for subaccount in snapshot.subaccounts:
    print(f'> account: {subaccount.subaccount}')
    for asset, balance in subaccount.balances.items():
      print(f'> {asset}: {balance}')
    for instrument, position in subaccount.positions.items():
      print(f'> {instrument}: {position.size} @ {position.avg_price}')
  print()
```
