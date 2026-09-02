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