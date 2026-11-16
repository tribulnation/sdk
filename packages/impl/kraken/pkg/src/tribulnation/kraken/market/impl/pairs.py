"""The Spot pair catalogue: one row per market, keyed by REST altname."""

from typing_extensions import TypedDict

from typed_kraken.spot.market_data.asset_pairs import AssetPair


class PairInfo(TypedDict):
  """One market's catalogue rows, in every spelling the client needs."""

  key: str
  """The `AssetPairs` key, which `Ticker` and `Depth` key their answers by (`XXBTZUSD`)."""
  symbol: str
  """The WebSocket v2 symbol (`BTC/USD`)."""
  info: AssetPair


class Meta(TypedDict):
  """What a `SpotMarket` is constructed around."""

  pair: PairInfo


def join_pairs(
  internal: dict[str, AssetPair], display: dict[str, AssetPair]
) -> dict[str, PairInfo]:
  """Key the catalogue by altname, pairing each row with its WebSocket v2 symbol.

  `AssetPairs` answers under internal keys by default and under display keys with
  `assetVersion=1`; the display key *is* the WebSocket v2 symbol, and `altname` is
  carried unchanged on both, so the two listings join exactly (1446 of 1446, checked
  live).

  Args:
    internal: The default `AssetPairs` listing.
    display: The `assetVersion=1` listing.
  """
  symbols = {
    altname: symbol
    for symbol, info in display.items()
    if (altname := info.get('altname'))
  }
  out: dict[str, PairInfo] = {}
  for key, info in internal.items():
    altname = info.get('altname')
    if altname is None or (symbol := symbols.get(altname)) is None:
      continue
    out[altname] = {'key': key, 'symbol': symbol, 'info': info}
  return out
