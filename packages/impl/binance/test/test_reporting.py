"""Regression tests for defects found mapping the Binance reporting sources."""

from tribulnation.binance.reporting.history.spot import TRANSFER_TYPES
from tribulnation.binance.reporting.util import split_transfer_type


def test_every_swept_transfer_type_resolves_to_two_compartments():
  """A direction the compartment map cannot split loses both account fields silently.

  `TRANSFER_TYPES` and `COMPARTMENTS` are two hand-written tables that have to agree:
  a direction present in the first but not derivable from the second still gets swept,
  and every `InternalTransfer` it yields carries `src_account=None, dst_account=None`
  instead of raising. Both supported Spot/Funding directions must resolve.
  """
  for type in TRANSFER_TYPES:
    assert split_transfer_type(type) != (None, None), type
