"""Perpetual funding payments."""
from typing_extensions import Iterable
from decimal import Decimal

from tribulnation.sdk.reporting import Funding
from hyperliquid.info.perps.user_funding import UserFundingEntry

from .assets import USDC
from .window import parse_time


def parse_funding(entry: UserFundingEntry, *, settle: str = USDC) -> Funding:
  """Convert a funding entry into a funding observation.

  Funding pays every open position on the same millisecond, so `hash` is shared
  across an entire batch and cannot identify a row on its own. The coin
  disambiguates: a position is funded once per settlement, so `(time, coin)` is
  unique — verified as 3361 distinct keys across 3361 real entries.

  Deliberately not keyed on list position. A cached read returns entries in a
  different order than a fresh fetch, and a positional id would make the same
  payment appear under different identifiers depending on where it came from.
  """
  delta = entry['delta']
  return Funding(
    id=f'funding:{entry["time"]}:{delta["coin"]}',
    time=parse_time(entry['time']),
    instrument=delta['coin'],
    asset=settle,
    amount=Decimal(str(delta['usdc'])),
  )


def parse_fundings(
  entries: Iterable[UserFundingEntry], *, settle: dict[str, str] | None = None,
) -> list[Funding]:
  """Convert a funding stream into observations.

  Args:
    entries: Funding entries for the account.
    settle: Optional instrument to settlement-token-index map, for HIP-3 dexes
      whose collateral is not USDC. Defaults to USDC.
  """
  settle = settle or {}
  return [
    parse_funding(entry, settle=settle.get(entry['delta']['coin'], USDC))
    for entry in entries
  ]
