from decimal import Decimal
import pydantic

class Fee(pydantic.BaseModel):
  amount: Decimal
  """Raw amount paid."""
  asset: str
  """Raw asset identifier, as provided by the source."""

  @property
  def balance_change(self) -> Decimal:
    return -abs(self.amount)

  def __str__(self) -> str:
    return f'Fee({self.amount} {self.asset})'

class BaseObservation(pydantic.BaseModel):
  id: str | None = None
  """Raw identifier, if provided by the source."""
  time: pydantic.AwareDatetime | None = None
  subaccount: str | None = None
  """Venue subaccount or compartment label, if the source row has a scoped account."""