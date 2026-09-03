<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><a href="../market/index.md">Market</a></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><b>Report</b></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Report

> `Report` provides method to retrieve historical transactions and current balances/positions.

Method reference: [Methods](methods.md). Per-venue specifics: [Implementations](implementations/index.md).

## Accounts & providers

`ReportSDK` has no built-in default accounts (unlike `MarketSDK`/`WalletSDK`/`EarnSDK`) — every account must be listed explicitly. Both record types carry a `Provenance` (api/tabular/manual/derived) tracing where they came from. `providers` (BigQuery/Alchemy/Etherscan/Moralis credentials) are only needed by chain-based venues that use them.

## Example

```python
from tribulnation.sdk import ReportSDK, accounts
from dotenv import load_dotenv

load_dotenv()

report = ReportSDK(
  {
    'ethereum': accounts.Evm('ethereum'),
    'polygon': accounts.Evm('polygon'),
    'hyperevm': accounts.Evm('hyperevm'),
  }
)

for account, sdk in report.all.items():
  async with sdk:
    result = await sdk.snapshot()
  snapshot = result.snapshot
  print(
    f'[{account}] ({snapshot.time:%Y-%m-%d %H:%M:%S}) from {result.provenance["source"]}'
  )
  for subaccount in snapshot.subaccounts:
    print(f'> account: {subaccount.subaccount}')
    for asset, balance in subaccount.balances.items():
      print(f'> {asset}: {balance}')
    for instrument, position in subaccount.positions.items():
      print(f'> {instrument}: {position.size} @ {position.avg_price}')
  print()
```

`report.all` is eager: it resolves every configured account at once, so a single
venue without reporting wired raises and you get nothing. Reach for
`report.venue(id)` when the workspace may contain one — see the
[support matrix](https://tribulnation.com/sdk/docs/support) for which venues are wired.

Reports own network clients, so use them as async context managers. Entering one
enters everything it owns and releases it on exit; see [Async Usage](../reference/async-usage.md).

<!-- next -->

---

← [Wallet Methods](../wallet/methods.md) · **Next:** [Methods](methods.md) →

<!-- /next -->
