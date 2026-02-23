from dataclasses import dataclass as _dataclass

from mexc import MEXC

from trading_sdk.market import UserData as _UserData
from mexc_sdk.core import SpotMixin, Settings, StreamManager
from .balances import Balances
from .orders import Orders
from .position import Position
from .trades import Trades

@_dataclass(frozen=True)
class UserData(SpotMixin, _UserData):
  balances: Balances
  orders: Orders
  position: Position
  trades: Trades

  @classmethod
  def of(cls, meta: SpotMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      balances=Balances.of(meta=meta, client=client, settings=settings, streams=streams),
      orders=Orders.of(meta=meta, client=client, settings=settings, streams=streams),
      position=Position.of(meta=meta, client=client, settings=settings, streams=streams),
      trades=Trades.of(meta=meta, client=client, settings=settings, streams=streams),
    )