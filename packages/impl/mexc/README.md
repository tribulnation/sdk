# MEXC SDK

> Tribulnation SDK implementation for MEXC.

## Installation

```bash
pip install tribulnation-mexc
```

## Report

`Report` covers `snapshot()` (spot balances, futures assets and open positions) and
`history()` (spot fills for the configured `spot_markets`, crypto deposits and
withdrawals, futures funding settlements). The API key needs MEXC's spot trade-read,
wallet-read and futures-read scopes. See
[docs/report/implementations/mexc.md](../../../docs/report/implementations/mexc.md).
