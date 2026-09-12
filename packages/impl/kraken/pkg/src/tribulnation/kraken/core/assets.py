"""Kraken's two spellings of one asset, joined through the venue's own catalogue.

Every account endpoint (`Balance`, `Ledgers`, `TradesHistory`, `WithdrawMethods`) and
the default `AssetPairs`/`Assets` listing name assets by Kraken's internal id -- `XXBT`,
`XETH`, `ZUSD`, `USDC` -- and that is the one raw form this package emits. Two public
endpoints can be asked for display names instead (`assetVersion=1`: `BTC`, `ETH`,
`USD`), and `Earn/Strategies` only ever answers in them. `Assets` is served in both
spellings with the *same* `altname` on each row (`XBT` under both `XXBT` and `BTC`),
so the display-to-internal map is a join the venue supplies rather than a rename
invented here.
"""

from typing_extensions import Mapping
import asyncio

from typed_kraken import Kraken

AssetNames = Mapping[str, str]
"""Display name to internal id, e.g. `{'BTC': 'XXBT', 'USD': 'ZUSD', 'SOL': 'SOL'}`."""


async def internal_ids(client: Kraken) -> AssetNames:
  """Map every display asset name onto its internal id.

  Both listings carry the same assets and `altname` is unique across them (840 of
  840, checked live), so the join is exact. An asset missing from either side --
  none today -- is simply absent from the map.

  Args:
    client: The Kraken client to fetch both `Assets` listings with.
  """
  internal, display = await asyncio.gather(
    client.spot.market_data.assets(),
    client.spot.market_data.assets(asset_version=1),
  )
  by_altname = {
    altname: id for id, info in internal.items() if (altname := info.get('altname'))
  }
  return {
    name: id
    for name, info in display.items()
    if (altname := info.get('altname')) and (id := by_altname.get(altname))
  }
