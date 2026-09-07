# Bit2Me SDK

> Tribulnation SDK implementation for Bit2Me.

## Installation

```bash
pip install tribulnation-bit2me
```

## Surfaces

| Surface | Class | Credentials |
|---|---|---|
| Earn | `tribulnation.bit2me.Earn` | none — both endpoints are public |
| Market | `tribulnation.bit2me.Bit2MeMarket` | public for market data, keyed for orders and balances |
| Report | `tribulnation.bit2me.Report` | keyed |
| Wallet | `tribulnation.bit2me.Wallet` | keyed |

```python
from tribulnation.bit2me import Earn

async with Earn.new() as earn:
  for instrument in await earn.instruments(assets=['BTC', 'ETH']):
    print(instrument.asset, f'{instrument.apr:.2%}')
```

Bit2Me splits balances across three sub-products with no shared ledger — Trading Spot,
Earn, and Wallet pockets — so `Report.snapshot()` returns one subaccount per compartment
rather than a single merged balance.

Withdrawal fees are only ever quoted, never published: Bit2Me has no fee schedule, and
`POST /v1/wallet/transaction/proforma` prices one withdrawal to one destination. So
`Wallet` enumerates every asset and network unconditionally, and fills in fees for the
networks you give it an address for:

```python
from tribulnation.bit2me import Wallet

async with Wallet.new(
  quote_addresses={'tron': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'}
) as wallet:
  print(await wallet.withdrawal_methods(assets=['USDT'], networks=['tron']))
```

The address is never sent anything — a proforma is a quote, not a transfer.
