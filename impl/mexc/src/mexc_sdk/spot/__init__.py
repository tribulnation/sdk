from dataclasses import dataclass as _dataclass

from mexc import MEXC
from mexc.spot.market_data.exchange_info import Info

from tribulnation.sdk.core import UserError
from tribulnation.sdk import Market as _Market

from .data import MarketData
from .trade import Trading
from .user import UserData

@_dataclass(frozen=True)
class Market(_Market):
  data: MarketData
  trade: Trading
  user: UserData

  @classmethod
  def new(
    cls, instrument: Info, client: MEXC, *,
    validate: bool = True, recvWindow: int | None = None
  ):
    return cls(
      data=MarketData.new(instrument, client, validate=validate, recvWindow=recvWindow),
      trade=Trading.new(instrument, client, validate=validate, recvWindow=recvWindow),
      user=UserData.new(instrument, client, validate=validate, recvWindow=recvWindow)
    )

  @classmethod
  async def connect(
    cls, instrument: str, *,
    api_key: str | None = None, api_secret: str | None = None,
    validate: bool = True, recvWindow: int | None = None
  ):
    client = MEXC.new(api_key=api_key, api_secret=api_secret, validate=validate)
    infos = await client.spot.exchange_info(instrument)
    if (info := infos.get(instrument)) is None:
      raise UserError(f'Instrument "{instrument}" not found')
    return cls.new(info, client, validate=validate, recvWindow=recvWindow)