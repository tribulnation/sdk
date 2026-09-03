<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><a href="../market/index.md">Market</a></td>
<td align="center"><b>Earn</b></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Earn

> `Earn` lists yield-bearing instruments across venues.

Method reference: [Methods](methods.md).

## Example

```python
from tribulnation.sdk import EarnSDK, accounts
from dotenv import load_dotenv

load_dotenv()

earn = EarnSDK({'binance': accounts.Binance(), 'mexc': accounts.Mexc()})

for account, sdk in earn.all.items():
  print(f'[{account}]')
  instruments = await sdk.instruments()
  for instr in instruments[:10]:
    print(f'> {instr.asset} {instr.apr:.2%}')
  if len(instruments) > 10:
    print(f'> ... and {len(instruments) - 10} more instruments')
  print()
```

<!-- next -->

---

← [MEXC Market](../market/implementations/mexc.md) · **Next:** [Methods](methods.md) →

<!-- /next -->
