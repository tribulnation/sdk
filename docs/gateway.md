<!-- github-only -->
<table><tr>
<td align="center"><b>Docs</b></td>
<td align="center"><a href="market/index.md">Market</a></td>
<td align="center"><a href="earn/index.md">Earn</a></td>
<td align="center"><a href="wallet/index.md">Wallet</a></td>
<td align="center"><a href="report/index.md">Report</a></td>
<td align="center"><a href="reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# SDK gateway

The optional gateway hosts SDK venue connections in a standalone process. Its
`ProxySDK` exposes the supported market operations over a local Unix socket.
It does not provide remote coverage of every SDK surface.

## Install and run

```sh
pip install 'tribulnation-sdk[gateway,hyperliquid]'
tn gateway --config sdk.toml
```

The `tn` launcher is supplied by `tribulnation-cli`. Install providers in the same
Python environment. `tn --help` discovers the gateway without importing it;
`tn gateway --help` does not load venue drivers. Running the command without the
`gateway` extra reports the installation command.

```toml
[gateway]
socket = "/tmp/tribulnation-sdk.sock"

[accounts.hl]
venue = "hyperliquid"
address = "$HYPERLIQUID_ADDRESS"
private_key = "$HYPERLIQUID_PRIVATE_KEY"
```

1. `--config/-c` defaults to `sdk.toml`; `.env` beside that file is loaded first.
   Accounts use the existing SDK `[accounts.<id>]` model and environment checks.
2. `--socket/-s` overrides `[gateway].socket`. The default is
   `/tmp/tribulnation-sdk.sock`.
3. `--verbose/-v` enables gateway debug logging; `-vv` enables all debug logging.
4. SIGINT/SIGTERM closes the gateway and SDK resources and removes the socket.

## Python API

```python
import asyncio
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.gateway.server import run_gateway

asyncio.run(run_gateway('/tmp/tribulnation-sdk.sock', MarketSDK.load('sdk.toml')))
```

`run_gateway(socket_path, sdk)` takes a `TradingMarkets` instance. `gateway_app(sdk)` returns an aiohttp application for embedding;
it owns the supplied SDK's async resource lifetime, so do not enter that SDK
separately. `Gateway` is the lower-level request handler.

```python
from tribulnation.sdk.gateway import ProxySDK

async def read_book():
    async with ProxySDK.at('unix:///tmp/tribulnation-sdk.sock') as sdk:
        market = await sdk.market('hl:perp:BTC')
        return await market.depth()
```

IDs given to `ProxySDK` are account-based addresses, and each proxy's `id` stays
that address: every later request (`depth`, `place_order`, ...) is routed with it.
As with the direct SDK, `account_id` is the address's account key and `venue_id` is
the venue the gateway-side object reports, so a market resolved as
`hl:perp:BTC` with the account above has `id == 'hl:perp:BTC'`,
`account_id == 'hl'` and `venue_id == 'hyperliquid'`.

1. `market`, `perp_market`, `exchange` and `perp_exchange` make one round trip,
   which resolves the exchange at the gateway and returns its product type and
   venue. `venue` makes one round trip (a `venue` request carrying the
   `account_id`) returning the venue.
2. Resolutions are cached per address for the lifetime of the `ProxySDK`; repeated
   calls make no further round trips. Failed resolutions are not cached.
3. Every request addressing a venue or exchange carries the account key as
   `account_id`; replies carry `venue_id` as a `VenueId`. Upgrade the client and
   the gateway together: older peers name the account field `venue_id`.

Clients need the `gateway` extra but do not need installed venue adapters or
credentials. The server needs the adapters and credentials for the accounts used.
The server binds a Unix socket and exposes `/debug/memory` diagnostics.
It does not configure authentication or a TCP listener. Treat access to the socket
as access to the configured accounts, including their trading operations.

## Preserved scope and compatibility

1. Binary JSON WebSocket frames, request tags and correlation IDs are unchanged,
   except for the added `venue` request, the `venue_id` on `exchange` replies, and
   the account field of venue and exchange requests, renamed from `venue_id` to
   `account_id`.
   Decimal/time serialization, error transport, bounded stream inboxes and
   reconnection behavior retain the existing implementation.
2. Supported calls include venue/exchange discovery, market rules, fees, books,
   tickers, statistics, candles, orders, positions, collateral and funding. Streams
   cover depth and trades. Wallet, Earn, Report, and newer exchange history methods
   are not added by this migration. Unsupported inherited SDK methods remain
   unsupported; this is not a general RPC adapter for arbitrary SDK methods.
3. Public gateway types are `ProxySDK`, `Gateway` and `GatewayError`.
4. Venue settings remain nested JSON objects, but the codec no longer imports
   dYdX/Hyperliquid (or mutates the SDK Settings module) to build its schema. It
   preserves Lighter and future venue settings too. Validation of venue-specific
   values belongs to the selected adapter; the transport validates the object
   shape. This intentionally removes the old codec's eager venue validation and
   unknown-key dropping.
5. This port does not add venue-native `random_client_order_id()` generation to
   proxy markets. Callers may supply an already-valid `Order.client_order_id`;
   the codec preserves it.
6. No new fan-out, book-integrity, rate-limit, retry, replay, or slow-client
   guarantees are introduced here. These remain properties of the existing
   implementation and selected venue adapters.

The ownership decision and release qualification boundaries are recorded in
[ADR 0032](../dev-docs/adr/0032-sdk-gateway.md).

<!-- next -->

---

← [Reference Context, Logging & Retries](reference/context.md)

<!-- /next -->
