from dataclasses import dataclass
from decimal import Decimal
import asyncio

from v4_proto.dydxprotocol.clob.clob_pair_pb2 import ClobPair
from tribulnation.sdk.market_v2.data import Rules as _Rules
from dydx_sdk.core import MarketMixin, IndexerDataMixin, AccountMixin, PublicNodeMixin, wrap_exceptions

@dataclass
class Rules(MarketMixin, IndexerDataMixin, AccountMixin, PublicNodeMixin, _Rules):
  @wrap_exceptions
  async def __call__(self) -> _Rules.Rules:
    market, fees = await asyncio.gather(
      self.indexer_data.get_market(self.market),
      self.public_node.get_user_fee_tier(self.address)
    )
    clob = await self.public_node.get_clob_pair(int(market['clobPairId']))
    base, quote = market['ticker'].split('-')
    return _Rules.Rules(
      base=base,
      quote=quote,
      fee_asset=quote,
      tick_size=Decimal(market['tickSize']),
      step_size=Decimal(market['stepSize']),
      maker_fee=fees.maker,
      taker_fee=fees.taker,
      api=clob.status == ClobPair.Status.STATUS_ACTIVE
    )