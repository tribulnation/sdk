# tribulnation-sdk 2.21.0

Book streams stop deep-copying the whole order book on every update, and dYdX accounts
can pick their default fill source.

New:

1. `Book.frozen()`: the book's current levels, unaffected by later `update`s. It copies
   the two level lists and shares the entries, for venue streams that hand out one book
   per update.
2. `detached_books(stream, levels=None)` (`tribulnation.sdk.market`): gives one
   subscriber its own copy of each shared book it reads, trimmed to `levels`. A book
   replaced unread in a `'latest'` inbox is never copied, and the stream keeps its
   `skipped` count ([ADR 0049](../../dev-docs/adr/0049-book-streams-copy-on-read.md)).
3. `accounts.Dydx` gains `fill_source` (`'indexer' | 'node' | 'socket' | 'fastest'`,
   the account's default `trades_source`) and `fill_socket` (a local fill daemon's unix
   socket, `$ENV_VAR` allowed). `MarketSDK` passes them to the dYdX package only when
   set; using either needs tribulnation-dydx 0.18.0
   ([ADR 0050](../../dev-docs/adr/0050-dydx-fill-socket.md)).

Changed:

1. `Book.copy()` builds new level lists and entries directly instead of calling
   `deepcopy`. The result is the same: an independent book, in the same order, sharing
   only the immutable prices, quantities and time. On a 500-level-a-side book it takes
   about 0.5 ms instead of 8 ms.

This release goes with tribulnation-bitget 0.11.1, -bybit 0.7.1, -coinbase 0.5.1,
-extended 0.1.1, -grvt 0.1.1, -kraken 0.7.2, -kucoin 0.6.1, -lighter 0.11.1 and
-mexc 2.4.1, which require SDK >=2.21.0, and tribulnation-dydx 0.18.0. Other adapters
are unaffected.
