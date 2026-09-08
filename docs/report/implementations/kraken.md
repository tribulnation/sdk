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

# Kraken Report

> `tribulnation-kraken`, venue name `kraken`. Keyed: `Balance` needs `Funds permissions -
> Query`, `Ledgers` needs `Data - Query ledger entries`.

## Snapshot

`snapshot()` is one `Balance` call: every asset the account holds, keyed by Kraken's
internal asset id (`XXBT`, `XETH`, `ZUSD`, `USDC`), in a single unnamed subaccount. Funds
in Earn appear under suffixed ids of their own — `XXBT.F` for Kraken Rewards, `.B` for
bonded products — and are reported as the venue names them. Spot has no positions, so
none are reported.

## History

Kraken has no unified history endpoint, but its ledger is close: every balance-affecting
event is one `Ledgers` row per asset leg, which is the SDK's per-observation model.
`history()` pages the ledger newest first, 50 rows at a time, and yields one
`HistoryRecord` per row, its provenance id the ledger id.

| Ledger `type` | Observation |
|---|---|
| `trade` | `TradeLeg` (`event_type = spot_trade`, `trade_id` the row's `refid`, `label` its `subtype`) |
| `deposit` | `FiatDeposit` for a fiat asset, `CryptoDeposit` otherwise |
| `withdrawal` | `FiatWithdrawal` for a fiat asset, `CryptoWithdrawal` otherwise |
| `staking` | `Yield` |
| `transfer` | `Transfer` |
| `reward` | `Bonus` |
| anything else | `UnknownObservation` |

A row carrying a non-zero `fee` adds a `FeeLeg` in the same asset, pointing at the row.

Two things are transcribed rather than reconstructed:

- **Trades are legs, not trades.** A spot trade is two `trade` rows — the base leg and
  the quote leg — sharing a `refid`, and each is its own record. Joining them back into
  one `SpotTrade` would need `TradesHistory` for the price and side; the ledger row is
  what this surface reads.
- **Fiat is a fixed list.** Kraken's asset catalogue classes fiat and crypto alike as
  `currency`, so fiat deposits and withdrawals are told apart by the asset id
  (`ZUSD`, `ZEUR`, `ZGBP`, `ZCAD`, `ZJPY`, `ZAUD`, `ZKRW`, `CHF`, `MXN`, `BRL`).

## Example

```python
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from tribulnation.sdk import ReportSDK, accounts

load_dotenv()

report = ReportSDK({'kraken': accounts.Kraken()}).venue('kraken')
end = datetime.now(timezone.utc)
async with report:
  print((await report.snapshot()).snapshot.balances)
  async for record in report.history(end - timedelta(days=30), end):
    for observation in record.observations:
      print(observation)
```

<!-- next -->

---

← [Ethereum Report](ethereum.md) · **Next:** [Reference](../../reference/index.md) →

<!-- /next -->
