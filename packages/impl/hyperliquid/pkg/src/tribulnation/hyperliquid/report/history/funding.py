"""Perpetual funding payments."""
from typing_extensions import Iterable, Mapping
from decimal import Decimal

from tribulnation.sdk.reporting import Funding
from hyperliquid.info.perps.user_funding import UserFundingEntry

from ..subaccounts import UNIFIED
from .assets import settlement_token
from .window import parse_time


def parse_funding(entry: UserFundingEntry, *, settle: str) -> Funding:
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
    subaccount=UNIFIED,
    instrument=delta['coin'],
    asset=settle,
    amount=Decimal(str(delta['usdc'])),
  )


def parse_fundings(
  entries: Iterable[UserFundingEntry], *, settle: Mapping[str, str],
) -> list[Funding]:
  """Convert a funding stream into observations.

  Args:
    entries: Funding entries for the account.
    settle: Instrument to settlement-token-index map, covering every dex the
      account traded. Required rather than defaulted: an absent entry is a gap
      in the metadata, not a market that happens to settle in USDC.

  Raises:
    UnknownSettlementToken: If an instrument has no entry in `settle`.
  """
  return [
    parse_funding(entry, settle=settlement_token(settle, entry['delta']['coin']))
    for entry in entries
  ]
