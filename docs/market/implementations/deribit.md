<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Deribit Market

Public mainnet spot and linear perpetual data through `tribulnation-deribit`.
This capability is prepared for `tribulnation-sdk` 2.2.0 and
`tribulnation-deribit` 0.3.0; both releases are pending publication.

```python
from tribulnation.sdk import MarketSDK

async with MarketSDK() as sdk:
  book = await sdk.depth('deribit:perp:BTC_USDC-PERPETUAL', levels=5)
```

The built-in Deribit Market account needs no credentials. Market ignores private
credential settings and rejects testnet accounts. Existing Wallet/Earn/Report
capabilities retain their own scope.

Exchange IDs are `spot` and `perp`, with native instrument names such as `BTC_USDT`
and `BTC_USDC-PERPETUAL`. Perpetual discovery includes active linear contracts with
matching quote and settlement currencies. Inverse contracts, dated futures, options
and combinations are excluded. Unknown exchange and unsupported market IDs are rejected.
Canonical Catalogue market translations still need to be added.

| Method | Supported behavior |
| --- | --- |
| Discovery/tickers | All active supported markets or selected ticker IDs; native bid/ask/last and base volume |
| REST depth | 1–100 levels, default 20; quantities in base units |
| Depth stream | Shared public full snapshots, 1–20 levels, default 20; bounded subscriber queues |
| Candles | Native spot and linear perpetual trade prices; `1m`, `5m`, `15m`, `1h` |
| Index/statistics | Native index/mark and optional base-unit open interest for linear perpetuals |

Candles require aware `[start, end)` opening-time bounds and use public WebSocket
requests with 1000-open windows. They preserve native rows and optional volumes;
historical availability is not an archive completeness guarantee. `4h` is unavailable.
Native daily candles open at 08:00 UTC and are outside this implementation's supported
SDK intervals. Coinbase-routed spot instruments serve books/tickers but advertise no
candle intervals. Check `market.CANDLE_INTERVALS`; unsupported intervals raise
`ValueError` before a request. Discovery/routing metadata is cached within a venue
owner; create a fresh owner to refresh it.

Rules, account fees, private Market methods and trading raise `NotImplementedError`.
Deribit funding accrues continuously: hourly observations are not exposed as discrete
SDK payment rates, and no next-payment time is invented. `funding_rates` and
`next_funding` are unsupported; optional funding statistics remain unset.

<!-- next -->

---

← [Coinbase Market](coinbase.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
