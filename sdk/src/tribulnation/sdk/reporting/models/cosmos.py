from typing_extensions import Literal, ClassVar
import pydantic

from .common import BaseObservation

class CosmosAttrs(pydantic.BaseModel):
  attrs: dict[str, list[str]]

  def gets(self, key: str) -> list[str] | None:
    return self.attrs.get(key)

  def get(self, key: str) -> str | None:
    if (vals := self.attrs.get(key)):
      if len(vals) > 1:
        raise ValueError(f'Multiple values for key {key}')
      return vals[0]

class CosmosEvent(pydantic.BaseModel):
  model_config = {'ignored_types': (type,)}
  type: str
  idx: int | None = None
  attrs: CosmosAttrs

  Attrs = CosmosAttrs

  def gets(self, key: str):
    return self.attrs.gets(key)

  def get(self, key: str):
    return self.attrs.get(key)

  def __getitem__(self, key: str):
    value = self.attrs.get(key)
    if value is None:
      raise KeyError(key)
    return value
  
class CosmosMessage(pydantic.BaseModel):
  idx: int
  action: str | None = None
  sender: str | None = None
  module: str | None = None
  events: list[CosmosEvent]
    
class CosmosTx(BaseObservation):
  model_config = {'ignored_types': (type,)}
  type: Literal['cosmos_tx'] = 'cosmos_tx'
  tx_id: str
  height: int | None = None
  tx_events: list[CosmosEvent]
  messages: list[CosmosMessage]

  Message = CosmosMessage
  Event = CosmosEvent


class CosmosBlockEvents(BaseObservation):
  type: Literal['cosmos_block_events'] = 'cosmos_block_events'
  height: int
  events: list[CosmosEvent]

  Event: ClassVar = CosmosEvent