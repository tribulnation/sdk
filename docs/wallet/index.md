<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><a href="../market/index.md">Market</a></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><b>Wallet</b></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Wallet

> `Wallet` queries deposit/withdrawal details

Method reference: [Methods](methods.md).

## Example

```python
from tribulnation.sdk import WalletSDK, accounts
from dotenv import load_dotenv

load_dotenv()

wallet = WalletSDK({'binance': accounts.Binance(), 'bitget': accounts.Bitget()})

for account, sdk in wallet.all.items():
  print(f'[{account}]')
  methods = await sdk.withdrawal_methods()
  for method in methods[:10]:
    print(f'> {method.asset} -> {method.network} - {method.fee}')
  if len(methods) > 10:
    print(f'> ... and {len(methods) - 10} more methods')
  print()
```

<!-- next -->

---

← [Earn Methods](../earn/methods.md) · **Next:** [Methods](methods.md) →

<!-- /next -->
