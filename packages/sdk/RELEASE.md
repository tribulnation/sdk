# tribulnation-sdk 4.4.0

A minor release: KuCoin accounts trade through `MarketSDK`, on a Classic account or a
Unified Trading Account (UTA). Nothing is removed; the `kucoin` extra rises to
tribulnation-kucoin 0.9.0, released before it.

New:

1. `accounts.Kucoin.mode`: `'classic'`, `'unified'` (UTA) or `None` (the default), which
   lets the KuCoin Market surface detect the account mode once, on the first account
   read or trade. Needs tribulnation-kucoin >=0.9.0 when set.

Changed:

1. `MarketSDK` builds KuCoin's Market surface with the account's API key, secret and
   passphrase (and `mode` when set), so account reads and trading work through the
   root; a `public=True` account stays credential-free. Until 4.3.0 the root built the
   public surface only, whatever credentials the account held.
2. The `kucoin` extra rises to `tribulnation-kucoin>=0.9.0`: 0.7 releases take no
   credentials and 0.8 releases no `mode`.
3. The `extended` extra rises to `tribulnation-extended>=0.5.2`: earlier releases fail
   every market read once Extended reports the market status `REDUCE_ONLY_OI`.

The other adapters keep their current releases and floors.
