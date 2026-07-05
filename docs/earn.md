# Earn

> `Earn` lists yield-bearing instruments across venues.

- `instruments(tags=None, assets=None)` — filters match *any* given tag or asset, not all

`apr` is a fraction of 1, not a percentage (`0.01` = 1%).

**Example:**

```python
from tribulnation.sdk import EarnSDK, accounts
from dotenv import load_dotenv

load_dotenv()

earn = EarnSDK({
  'binance': accounts.Binance(),
  'mexc': accounts.Mexc()
})

for account, sdk in earn.all.items():
  print(f'[{account}]')
  instruments = await sdk.instruments()
  for instr in instruments[:10]:
    print(f'> {instr.asset} {instr.apr:.2%}')
  if len(instruments) > 10:
    print(f'> ... and {len(instruments) - 10} more instruments')
  print()
```
