from typing_extensions import TypedDict, NotRequired, Any, Literal, Annotated
import pydantic

class BaseProvenance(TypedDict):
  id: str
  """Unique identifier for all records sharing a same provenance."""
  details: NotRequired[Any]

class TabularProvenance(BaseProvenance):
  source: Literal['tabular']
  row: int
  file: str

class ApiProvenance(BaseProvenance):
  source: Literal['api']
  service: str

class ManualProvenance(BaseProvenance):
  source: Literal['manual']

class DerivedProvenance(BaseProvenance):
  source: Literal['derived']

Provenance = Annotated[
  TabularProvenance | ApiProvenance | ManualProvenance | DerivedProvenance,
  pydantic.Discriminator('source')
]