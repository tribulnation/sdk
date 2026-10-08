# tribulnation-sdk 2.13.1

Fix: `Book.update` removes levels crossed by an update. While the best ask is at
or below the best bid, a level the update sets removes the existing levels it
crosses, and within one update the larger quantity wins (an equal quantity keeps
the ask), as dYdX documents for its Indexer book. Crosses between two levels
already in the book are left until an update touches one of them. Zero-quantity
removals don't trigger uncrossing. Previously a dYdX book could keep crossed levels
for minutes. This applies to every venue that builds its book from a snapshot plus
incremental updates: Aster, dYdX, Lighter, Bybit, Bitget, Coinbase, Kraken and MEXC.

No contract changes; adapter floors stay at `>=2.13.0`.

Qualification on 2026-10-08: all 14 declared venues have passing, verified
read-suite evidence, and all 13 market venues have passing consistency evidence,
against the unchanged Catalogue pin `1851660ac2bed8243dd9ce9c7297fe05c7130973`.
The existing Bit2Me native-ticker limitation (ADR 0014) remains visible.

All 1,449 repository unit tests pass.
