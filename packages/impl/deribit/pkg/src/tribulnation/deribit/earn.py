"""Public rates on Deribit's reward-bearing balances, not subscription products."""

from decimal import Decimal
from typing_extensions import Collection, Sequence
from tribulnation.sdk.earn import Earn as BaseEarn
from tribulnation.sdk.earn.instruments import Instrument
from .core import Mixin


class Earn(Mixin, BaseEarn):
  """Discover reward-bearing currencies from the venue's published APR field."""

  async def instruments(
    self,
    *,
    tags: Collection[Instrument.Tag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Report the public seven-day SMA, not account eligibility or guaranteed yield."""
    if tags is not None and 'flexible' not in tags:
      return []
    rows = await self.call(self.client.market_data.get_currencies)
    return [
      Instrument(
        asset=row['currency'], tags=['flexible'], apr=Decimal(str(row['apr'])) / 100
      )
      for row in rows
      if 'apr' in row and (assets is None or row['currency'] in assets)
    ]
