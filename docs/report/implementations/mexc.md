<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><a href="../../market/index.md">Market</a></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><b>Report</b></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# MEXC Report

> `tribulnation-mexc`, venue name `mexc`. Asset ids are MEXC coin names (`BTC`),
> spot market ids concatenated symbols (`BTCUSDT`), futures ids `BTC_USDT`.

The API key must carry MEXC's spot trade-read, wallet-read and futures-read scopes.
A key without them fails with `700007 No permission to access the endpoint` on the spot
side and `701`/`703` on the futures side; nothing in the SDK can widen a key's scope.

## Snapshots

Two `SubaccountSnapshot`s, `spot` and `futures`:

- `spot`: `GET /api/v3/account` — `free + locked` per asset.
- `futures`: `GET /api/v1/private/account/assets` — `availableBalance + positionMargin`
  per currency, plus `GET /api/v1/private/position/open_positions` for open positions,
  sized in base units through each contract's `contractSize`.

## History

`history(start=None, end=None)` defaults to the last 30 days ending now. Explicit bounds
are preserved; the API may not retain all requested data. Four sources, each row its own record with an
`ApiProvenance` (`service = 'mexc'`):

| Source | Endpoint | Observation | Limits |
|---|---|---|---|
| Spot fills | `GET /api/v3/myTrades` | `SpotTrade` (`subaccount='spot'`) | Automatically sweeps all symbols from exchange info, regardless of current holdings. Only the last month is served; one call per symbol per day with `limit=1000`. A full sweep can be expensive; delisted symbols absent from discovery and fills beyond a daily cap remain gaps for file ingestion. |
| Deposits | `GET /api/v3/capital/deposit/hisrec` (`status=5`, SUCCESS) | `CryptoDeposit` | At most seven days per query, distinct from the venue's 90-day history horizon. No deposit id: the transaction hash doubles as one. No fee field: MEXC charges none. |
| Withdrawals | `GET /api/v3/capital/withdraw/history` (`status=7`, SUCCESS) | `CryptoWithdrawal` | At most seven days per query, distinct from the 90-day history horizon. Timed at `applyTime`, when the balance left the account. `transactionFee` is reported as the fee, `0` included. |
| Funding | `GET /api/v1/private/position/funding_records` | `Funding` (`subaccount='futures'`) | Page-based, account-wide, no time filter and no documented page order, so every page is read and the window applied client-side. The settlement coin comes from the contract's `settleCoin`. `funding` is signed as MEXC signs it (positive credited); the client hands it over as a `float`, converted through `str`. |

Not covered, though MEXC exposes the endpoints: futures fills (`order_deals`, per
symbol) and closed positions, spot-futures and sub-account transfers, dust conversions
and affiliate rebates. Margin has no surface in the typed client at all.

## Example

```python
from tribulnation.sdk import ReportSDK, accounts
from datetime import datetime, timedelta, timezone

report = ReportSDK({'mexc': accounts.Mexc()})
end = datetime.now(timezone.utc)
async with report.venue('mexc') as mexc:
  async for record in mexc.history(end - timedelta(days=30), end):
    print(record.observations[0])
```

<!-- next -->

---

← [Ethereum Report](ethereum.md) · **Next:** [Kraken Report](kraken.md) →

<!-- /next -->
