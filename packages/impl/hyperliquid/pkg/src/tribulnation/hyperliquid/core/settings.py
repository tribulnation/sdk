from typing_extensions import Literal, TypedDict

DepthSource = Literal['l2', 'fast', 'bbo']
"""Which Hyperliquid WebSocket feed backs `depth_stream`. See `Settings.depth_source`."""


class Settings(TypedDict, total=False):
  reduce_only: bool
  limit_tif: Literal['Alo', 'Ioc', 'Gtc']
  index_price: Literal['oracle', 'mark']
  tickers_fetch_depth: bool
  """Whether bulk tickers fetch order books for best bid and ask. Defaults to True."""
  tickers_depth_concurrent: int
  """Maximum concurrent order-book requests used to enrich bulk tickers. Defaults to 20."""
  depth_source: DepthSource
  """Which feed `depth_stream`/`depth` read. Defaults to `'l2'`.

  - `'l2'`: the `l2Book` channel, 20 levels per side, pushed every ~5.4 s.
  - `'fast'`: `l2Book` with `fast=True`, 5 levels per side, pushed every ~0.5 s. Held on
    a dedicated WebSocket connection, since Hyperliquid tags both `l2Book` variants
    identically and one connection cannot tell them apart.
  - `'bbo'`: the `bbo` channel, top of book only (best bid/ask with sizes), pushed
    on change: about every 100–150 ms on liquid markets, less often on quiet ones.

  The sources are different feeds and need not agree tick-for-tick; `'bbo'` usually
  leads the best level of `'l2'` by up to seconds. REST `depth` has no faster
  endpoint: it reads the `l2Book` snapshot for every source, trimmed to 5 levels for
  `'fast'` and 1 for `'bbo'` so its shape matches the stream's.
  """
