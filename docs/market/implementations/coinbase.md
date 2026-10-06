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

# Coinbase Market

> Advanced Trade spot. Package: `tribulnation-coinbase`.

## Account configuration

Authenticated access is recommended, especially for `tickers()` over many markets:

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()  # COINBASE_API_KEY_NAME and COINBASE_PRIVATE_KEY

async with MarketSDK({'coinbase': accounts.Coinbase()}) as sdk:
    tickers = await sdk.tickers('coinbase:spot', markets=['BTC-USD', 'ETH-USD'])
```

`accounts.Coinbase(public=True)` is an explicit fallback when credentials are
unavailable. When credentials resolve from configuration or the environment, the
router still prefers authenticated access. With no credentials, it supports public
spot market data. Authentication failures on a configured private account remain
errors; they do not silently switch to public access. Balances and trading require
credentials.

## Ticker request cost

Authenticated `tickers()` uses the bulk best-bid/ask endpoint, in batches of up to
100 products. With `public=True` and no resolved credentials, the SDK reads one public order book per selected
product. For 925 products, that means 10 authenticated quote requests versus 925
public quote requests, in addition to catalogue reads.

Prefer authenticated access for full-exchange sweeps. With public access, select
the markets you need:

```python
from tribulnation.sdk import MarketSDK, accounts

async with MarketSDK({'coinbase': accounts.Coinbase(public=True)}) as sdk:
    tickers = await sdk.tickers('coinbase:spot', markets=['BTC-USD', 'ETH-USD'])
```

Both paths combine catalogue last prices and 24-hour base volumes with native
bid/ask prices and sizes. Empty book sides remain unknown (`None`), and failed
requests propagate. Catalogue and quote reads are separate observations, not an
atomic snapshot or a guarantee of equal freshness across endpoints.

## Exchanges and discovery

- `spot` uses Advanced Trade IDs such as `BTC-USD`.
- Public discovery requests the full default catalogue and checks completion
  metadata and unique IDs. If Coinbase reports another page or an inconsistent
  response, discovery fails rather than presenting a partial catalogue. Small-page
  spot sweeps were observed to omit and duplicate products on both endpoint families.
- Public rules do not fetch personal fee tiers, and account `fees()` is unsupported.
- INTX perpetuals are not supported: Coinbase retires them on the Advanced Trade API
  on 2026-10-01, moving international derivatives to a Deribit-powered gateway
  ([ADR 0031](https://github.com/tribulnation/sdk/blob/main/dev-docs/adr/0031-coinbase-drop-intx.md)).

<!-- next -->

---

← [Kraken Market](kraken.md) · **Next:** [Aster Market](aster.md) →

<!-- /next -->
