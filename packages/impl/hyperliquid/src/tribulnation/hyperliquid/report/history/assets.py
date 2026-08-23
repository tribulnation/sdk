"""Asset identifier resolution for Hyperliquid reporting.

History and snapshots must agree on asset identifiers or they cannot be
reconciled. `Snapshots` keys balances by **numeric token index as a string**
(`'0'` is USDC, `'150'` is HYPE), so history does the same.

The API is inconsistent about which form it uses: spot pairs and perp collateral
are given as indices, but fill `feeToken` and ledger `token` are given as names.
Names are resolved back to indices here.
"""
from typing_extensions import Mapping
from dataclasses import dataclass

from hyperliquid.info import Info
from hyperliquid.info.spot.spot_meta import SpotMetaResponse

USDC = '0'
"""Token index of USDC, the default quote and margin asset."""

HYPE = '150'
"""Token index of HYPE, the native token. Matches `report/snapshots.py`."""


class AmbiguousTokenName(Exception):
  """Two tokens share a name, so names cannot be resolved to indices.

  Token names are labels; the true identifier is the index. Hyperliquid does not
  guarantee uniqueness, and a silent collision would merge two assets' balances
  into a single line. Failing here keeps that impossible.
  """


class UnknownSettlementToken(Exception):
  """A traded market is absent from the dex metadata.

  Falling back to USDC misattributes every realized-PnL and funding leg for the
  market to the wrong asset, and does it silently: the totals still balance in
  aggregate, so only a per-asset audit reveals it.
  """


def settlement_token(settle: Mapping[str, str], coin: str) -> str:
  """Resolve a market's settlement token index, refusing to guess.

  Raises:
    UnknownSettlementToken: If `coin` has no entry, which means the dex metadata
      it came from was never read.
  """
  if (token := settle.get(coin)) is None:
    raise UnknownSettlementToken(
      f'No settlement token for market {coin!r}. Its dex is missing from the '
      'metadata, so its denomination is unknown.'
    )
  return token


@dataclass(frozen=True)
class Assets:
  """Resolves Hyperliquid asset identifiers to canonical token indices."""
  by_name: Mapping[str, str]
  """Token name to token index, e.g. `'USDC' -> '0'`."""
  pairs: Mapping[int, tuple[str, str]]
  """Spot pair index to `(base, quote)` token indices."""
  pairs_by_name: Mapping[str, tuple[str, str]]
  """Canonical spot pair name to `(base, quote)` token indices, e.g. `'PURR/USDC'`."""

  @classmethod
  def of(cls, meta: SpotMetaResponse) -> 'Assets':
    """Build an index from a `spotMeta` response.

    Raises:
      AmbiguousTokenName: If two tokens share a name.
    """
    seen: dict[str, list[int]] = {}
    for token in meta['tokens']:
      seen.setdefault(token['name'], []).append(token['index'])
    if (dupes := {n: v for n, v in seen.items() if len(v) > 1}):
      raise AmbiguousTokenName(f'Token names are not unique: {dupes}')
    by_name = {name: str(idx[0]) for name, idx in seen.items()}

    pairs: dict[int, tuple[str, str]] = {}
    pairs_by_name: dict[str, tuple[str, str]] = {}
    for pair in meta['universe']:
      base, quote = pair['tokens'][0], pair['tokens'][1]
      entry = (str(base), str(quote))
      pairs[pair['index']] = entry
      pairs_by_name[pair['name']] = entry
    return cls(by_name=by_name, pairs=pairs, pairs_by_name=pairs_by_name)

  @classmethod
  async def fetch(cls, info: Info) -> 'Assets':
    """Build an index by fetching `spotMeta`."""
    return cls.of(await info.spot_meta())

  def token(self, name: str) -> str:
    """Resolve a token name to its index, falling back to the raw name.

    An unknown name is returned unchanged rather than dropped: it is better for a
    balance to appear under an odd identifier than to vanish.
    """
    return self.by_name.get(name, name)

  def pair(self, coin: str) -> tuple[str, str]:
    """Resolve a spot coin identifier to `(base, quote)` token indices.

    Handles both forms the API uses: the pair index (`'@142'`) and the canonical
    pair name (`'PURR/USDC'`).
    """
    if coin.startswith('@'):
      if (entry := self.pairs.get(int(coin[1:]))) is not None:
        return entry
    elif (entry := self.pairs_by_name.get(coin)) is not None:
      return entry
    if '/' in coin:
      base, quote = coin.split('/', 1)
      return self.token(base), self.token(quote)
    return self.token(coin), USDC


def is_spot(coin: str) -> bool:
  """Return whether a fill's coin identifier denotes a spot market."""
  return coin.startswith('@') or '/' in coin
