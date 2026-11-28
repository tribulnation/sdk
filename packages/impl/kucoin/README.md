<p align="center">
  <a href="https://tribulnation.com/sdk/docs/support#kucoin">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://tribulnation.com/media/lockups/kucoin-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://tribulnation.com/media/lockups/kucoin-light.svg">
      <img alt="Tribulnation SDK KuCoin" src="https://tribulnation.com/media/lockups/kucoin-light.svg" width="520">
    </picture>
  </a>
</p>

<p align="center">
  <em>Tribulnation SDK implementation for KuCoin.</em>
</p>

Spot and linear perpetual Market data and trading on Classic accounts and Unified
Trading Accounts (UTA), read-only Classic spot-side reporting, wallet network methods
and simple Earn listings. Perpetual trading is verified live on a Unified Trading Account.

```python
from tribulnation.sdk import ReportSDK, accounts

reports = ReportSDK({'kucoin': accounts.Kucoin()})
async with reports.venue('kucoin') as report:
  async for record in report.history():
    print(record)
```

1. History discovers spot markets automatically; no holdings-based filter or caller
   market list is required. Per-symbol sweeps can
   require many requests. Omitted bounds select seven days of spot fills and 30 days
   for deposits/withdrawals; explicit bounds are preserved and rows are filtered locally.
2. History is best-effort. Retention, delisted symbols, dedicated margin activity,
   Earn accruals and other unsupported ledgers leave gaps for file ingestion.
3. Snapshots include Classic main/trade balances and paginated Earn holdings.
   Futures and legacy margin/isolated compartments are explicitly excluded, not
   reported as zero exposure. Neither history nor snapshots call futures endpoints.
   No Futures permission or scope configuration is needed. Rejected supported reads
   fail rather than claiming zero balances. Other user subaccounts remain unsupported.
   The underlying Typed futures APIs are unchanged.
4. `Wallet.new(public=True)` lists enabled chains with native `chainId` identifiers.
   Withdrawal fees are the published minimum, not a quote for a specific transfer.
5. Earn lists five simple savings/staking families. Structured dual investments are
   excluded because their contingent principal conversion is not a plain APR product.

## Public Market data

```python
from datetime import datetime, timedelta, timezone
from tribulnation.kucoin import KucoinMarket

async with KucoinMarket.new(public=True) as venue:
  spot = await venue.exchange('spot')
  print(await spot.tickers(['BTC-USDT']))
  market = await venue.perp_market('perp:XBTUSDTM')
  end = datetime.now(timezone.utc)
  candles = await market.candles('1h', end - timedelta(days=3), end)
  print(await market.next_funding())
```

- Discovery, native tickers, public rules, depth, trade candles and perpetual funding
  use public APIs. No account credentials or Futures permission are needed.
- Exchange IDs are `spot` and `perp`; full SDK IDs include
  `kucoin:spot:BTC-USDT` and `kucoin:perp:XBTUSDTM`. Native symbols are not renamed.
- Perpetual support covers open linear contracts. Inverse and dated contracts are
  excluded. Quantities use base units, converted from contract lots where necessary.
- REST depth accepts 1–100 levels (default 20); streams accept 1–5 (default 5).
  Streams share an upstream and honor SDK queue/overflow settings.
- Candles support `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, require aware `[start, end)`
  bounds, and page by time at 1,500 spot/200 futures rows. Gaps remain gaps; historical
  availability differs by product and interval and does not guarantee an archive.
- Funding history uses inclusive bounds; an omitted start walks earliest available
  settlements. Perpetual statistics expose index, mark and base-unit open interest;
  use `next_funding()` for the current cycle's rate, next settlement and interval.
- `rules().fees` is unknown; `fees()` reads the account's rates.

## Trading (unreleased)

```python
from decimal import Decimal
from tribulnation.sdk import MarketSDK, accounts

# Reads KUCOIN_API_KEY, KUCOIN_API_SECRET and KUCOIN_API_PASSPHRASE.
sdk = MarketSDK({'kucoin': accounts.Kucoin()})
market = await sdk.perp_market('kucoin:perp:XBTUSDTM')
print(await market.fees())  # maker rebates are negative rates
order = await market.place_order(
  {'type': 'POST_ONLY', 'qty': Decimal('0.001'), 'price': Decimal('60000')}
)
await market.cancel_order(order.id)
```

- Spot (HF orders, the `trade` account) and linear perpetuals (one-way, cross margin).
  Quantities are base units; futures orders must be whole contracts.
- `LIMIT` is GTC, `POST_ONLY` sets `postOnly`, `MARKET` is an IOC limit at the price.
- Orders are checked against the rules before sending (`ValueError`), refusals raise
  `OrderRejected`, missing orders `OrderNotFound`.
- Unified Trading Accounts: `accounts.Kucoin(mode='unified')`, or leave `mode` unset to
  detect it. Every account read, order and fill then uses the UTA API and private
  WebSocket; perpetuals margin from the one unified pool (`collateral_id` `<account>:perp`,
  USDC included). Verified live on a mainnet UTA on 2026-11-28: account reads on
  both lines, and perpetual post-only place, query, cancel and a minimum-size fill.
- See [the KuCoin Market page](../../../docs/market/implementations/kucoin.md) for
  collateral, leverage, fees, streams and history, and
  `scripts/live_trading.py` for the live check (not run in CI).

See the [qualification handoff](../../../dev-docs/kucoin-public-market.md) for observed
limits, Catalogue follow-up and release/version requirements.
