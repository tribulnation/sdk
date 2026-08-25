"""Perp and spot fills, with exact realized-PnL reconstruction.

`closedPnl` is a rounded frontend value, not the accounting basis — the
Hyperliquid docs say so explicitly, and reconciling an account with it leaves a
residual. Realized PnL is instead reconstructed by folding the fill stream,
carrying `(signed_position, entry_price)` per coin.

That fold needs the stream from the point a position was opened, so `start` is
applied as a client-side filter and fills are always replayed from the
beginning. Two API limits make the stream incomplete in ways that cannot be
worked around here, so both are detected rather than absorbed:

- `userFillsByTime` retains only the 10000 most recent fills;
- TWAP slices come from a separate endpoint capped at 2000 records.

Where the fold cannot see back to position open, `realized_pnl` is `None`. An
explicit unknown is correct; a fabricated number is not.
"""

from typing_extensions import Iterable, Mapping, Sequence, TypeAlias, Union
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import Fee, FutureTrade, SpotTrade
from typed_hyperliquid.info.user_fills_by_time import UserFill
from typed_hyperliquid.info.user_twap_slice_fills import TwapFill

AnyFill: TypeAlias = Union[UserFill, TwapFill]
"""A fill from either stream.

TWAP slices carry every field used here but are a distinct type — they lack
`builderFee` — so the two cannot be conflated. They must still be folded
together: the slices are real trades absent from `userFillsByTime`.
"""

from ..subaccounts import UNIFIED
from .assets import Assets, is_spot, settlement_token
from .window import parse_time

ZERO = Decimal(0)


def signed_size(fill: AnyFill) -> Decimal:
  """Return a fill's size, signed positive for a buy and negative for a sell."""
  size = Decimal(fill['sz'])
  return size if fill['side'] == 'B' else -size


def sort_key(fill: AnyFill) -> datetime:
  """Order fills by time only.

  Deliberately *not* a tiebreaker on `tid`. Many fills share a millisecond — up
  to 46 on a real account — and their order within it is meaningful: chaining
  `startPosition` only works in the order the API returned them. Python's sort
  is stable, so sorting on time alone preserves that order. Adding `tid` would
  reorder within a millisecond and break the chain. `tid` is not even unique:
  dust-conversion fills all carry a sentinel of 0.
  """
  return fill['time']


def fill_id(fill: AnyFill, occurrence: int) -> str:
  """Build a stable identifier for a fill.

  Neither `tid` nor `(time, hash)` is unique on Hyperliquid, so `occurrence`
  disambiguates fills sharing both. It counts within that group rather than
  across the whole stream, so an id does not change when earlier or later fills
  are added.
  """
  return f'fill:{fill["hash"]}:{fill["tid"]}:{occurrence}'


@dataclass
class Position:
  """Running position state for one perp coin."""

  size: Decimal = ZERO
  """Signed position size."""
  entry: Decimal | None = None
  """Average entry price, or None while flat."""
  complete: bool = True
  """Whether the fold has seen every fill back to position open."""


def realized_pnl(position: Position, size: Decimal, price: Decimal) -> Decimal | None:
  """Return realized PnL for a fill against the prior position state.

  Returns None when the prior cost basis is unknown, which happens if the fill
  stream does not reach back to when the position was opened.
  """
  if not position.complete:
    return None
  if position.size == ZERO:
    return ZERO
  if position.entry is None:
    return None
  if position.size * size >= ZERO:
    return ZERO
  closed = min(abs(position.size), abs(size))
  direction = Decimal(1) if position.size > ZERO else Decimal(-1)
  return closed * direction * (price - position.entry)


def advance(position: Position, size: Decimal, price: Decimal) -> Position:
  """Fold one fill into the running position state."""
  before = position.size
  after = before + size
  if before == ZERO or before * size > ZERO:
    # Opening or increasing: entry becomes the weighted average.
    if position.entry is None or before == ZERO:
      entry = price
    else:
      entry = (before * position.entry + size * price) / after
  elif abs(size) < abs(before):
    entry = position.entry  # Reducing: cost basis is unchanged.
  elif after == ZERO:
    entry = None  # Flat.
  else:
    entry = price  # Flipped: the remainder opens at this price.
  return Position(size=after, entry=entry, complete=position.complete)


def parse_perp_fill(
  fill: AnyFill,
  *,
  index: int,
  pnl: Decimal | None,
  settle: str,
  assets: Assets,
) -> FutureTrade:
  """Convert a perp fill into a future trade observation."""
  return FutureTrade(
    id=fill_id(fill, index),
    time=parse_time(fill['time']),
    subaccount=UNIFIED,
    instrument=fill['coin'],
    settle=settle,
    size=signed_size(fill),
    price=Decimal(fill['px']),
    realized_pnl=pnl,
    order_id=str(fill['oid']),
    fee=Fee(asset=assets.token(fill['feeToken']), amount=Decimal(fill['fee'])),
  )


def parse_spot_fill(fill: AnyFill, *, index: int, assets: Assets) -> SpotTrade:
  """Convert a spot fill into a spot trade observation."""
  base, quote = assets.pair(fill['coin'])
  return SpotTrade(
    id=fill_id(fill, index),
    time=parse_time(fill['time']),
    subaccount=UNIFIED,
    base=base,
    quote=quote,
    pair=fill['coin'],
    size=signed_size(fill),
    price=Decimal(fill['px']),
    order_id=str(fill['oid']),
    fee=Fee(asset=assets.token(fill['feeToken']), amount=Decimal(fill['fee'])),
  )


def parse_fills(
  fills: Iterable[AnyFill],
  *,
  assets: Assets,
  settle: Mapping[str, str],
) -> tuple[list[FutureTrade | SpotTrade], dict[str, Position]]:
  """Convert a fill stream into trade observations with exact realized PnL.

  Fills must be the account's complete history, not a window: realized PnL is a
  fold, so a partial stream yields wrong cost basis. Filter by time afterwards.

  Args:
    fills: Every fill for the account, in any order.
    assets: Token index resolver.
    settle: Coin to settlement-token-index map, covering every dex the account
      traded. Required rather than defaulted: an absent entry is a gap in the
      metadata, not a market that happens to settle in USDC.

  Returns:
    The observations, and the final per-coin position state. A coin whose state
    has `complete=False` had fills missing before the first one seen, so its
    realized PnL is reported as None.

  Raises:
    UnknownSettlementToken: If a perp coin has no entry in `settle`.
  """
  ordered = sorted(fills, key=sort_key)
  positions: dict[str, Position] = {}
  seen: dict[tuple[str, int], int] = {}
  out: list[FutureTrade | SpotTrade] = []

  for fill in ordered:
    coin = fill['coin']
    group = (fill['hash'], fill['tid'])
    index = seen[group] = seen.get(group, -1) + 1
    if is_spot(coin):
      out.append(parse_spot_fill(fill, index=index, assets=assets))
      continue
    position = positions.get(coin)
    if position is None:
      # The first fill seen for this coin should open from flat. If it does not,
      # the stream is truncated and cost basis is unrecoverable.
      start = Decimal(fill['startPosition'])
      position = Position(size=start, entry=None, complete=start == ZERO)
    size, price = signed_size(fill), Decimal(fill['px'])
    pnl = realized_pnl(position, size, price)
    positions[coin] = advance(position, size, price)
    out.append(
      parse_perp_fill(
        fill,
        index=index,
        pnl=pnl,
        settle=settlement_token(settle, coin),
        assets=assets,
      )
    )
  return out, positions


def discontinuities(fills: Sequence[AnyFill]) -> dict[str, int]:
  """Count `startPosition` breaks per coin, as a fill-completeness audit.

  Every fill reports the position before it. Chaining them should be continuous;
  a break means fills are missing. This caught a client pagination bug that had
  silently dropped fills at page boundaries, so it is worth asserting on.
  """
  chains: dict[str, Decimal] = {}
  breaks: dict[str, int] = {}
  for fill in sorted(fills, key=sort_key):
    coin = fill['coin']
    if is_spot(coin):
      continue
    start = Decimal(fill['startPosition'])
    if (prev := chains.get(coin)) is not None and abs(start - prev) > Decimal('1e-9'):
      breaks[coin] = breaks.get(coin, 0) + 1
    chains[coin] = start + signed_size(fill)
  return breaks
