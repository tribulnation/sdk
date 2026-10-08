# tribulnation-sdk 2.12.0

Market, exchange and venue IDs are now scoped to the account they were opened
under, `venue_id` is the typed venue, and order books carry their exchange time.

This is a breaking change:

1. Every `TradingVenue`, `Exchange` and `Market` has an `account_id` (the root
   SDK account key), and `id` is built from it: a market opened under account
   `hl` is `hl::ETH`. `MarketSDK` passes the account key into each venue.
   Objects built directly, and accounts keyed by their venue slug, keep their
   current IDs. Persisted IDs opened under a custom account key change prefix.
2. `venue_id` is always the venue type, typed as `VenueId`. Testnets are separate
   venues: dYdX, Hyperliquid and Lighter testnets now report `dydx_testnet`,
   `hyperliquid_testnet` and `lighter_testnet` (Aster already reported
   `aster_testnet`).
3. Accounts are frozen dataclasses; trading accounts share
   `VenueAccount.venue: VenueId`.
4. Gateway request fields carrying the account key are renamed `venue_id` ->
   `account_id`, and proxies report the real venue type. Upgrade gateway servers
   and clients together.

New:

1. `Book.time`: the time of the latest exchange event reflected in the book, as an
   aware UTC datetime, or `None` when the venue provides no timestamp. Never a
   local receive time. Filled by Hyperliquid, Aster and Lighter (WebSocket).
2. `depth()` and `depth_stream()` take keyword-only, venue-keyed `settings`,
   forwarded through `TradingMarkets` and the gateway. Hyperliquid reads
   `depth_source` (`'l2'`, `'fast'`, `'bbo'`); other venues ignore it.
3. dYdX accounts accept a `private_key` as an alternative to a mnemonic, so dYdX
   API wallets work.

Every adapter except Ethereum implements the new abstract `account_id`, so this
release requires the matching adapter releases (Aster 0.6.0, Binance 0.6.0,
Bit2Me 0.8.0, Bitget 0.10.0, Bybit 0.6.0, Coinbase 0.4.0, Deribit 0.5.0, dYdX
0.12.0, Hyperliquid 0.12.0, Kraken 0.6.0, KuCoin 0.5.0, Lighter 0.5.0, MEXC
2.3.0). The SDK extras require them, and they require SDK >=2.12.0. Upgrade the
SDK and your adapters together. Ethereum 0.6.x is unaffected.

Qualification on 2026-10-08: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against the unchanged Catalogue pin `1851660ac2bed8243dd9ce9c7297fe05c7130973`.
The existing Bit2Me native-ticker limitation (ADR 0014) remains visible.

All 1,416 repository unit tests pass.
