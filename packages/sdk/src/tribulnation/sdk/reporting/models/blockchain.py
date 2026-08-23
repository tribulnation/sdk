from typing_extensions import Literal, Sequence
from decimal import Decimal
import pydantic

from .common import BaseObservation, Fee

class CryptoTransfer(pydantic.BaseModel):
  """A crypto asset transferred within a blockchain transaction."""
  asset: str
  """Raw asset identifier/address."""
  change: Decimal
  """Signed amount being transferred."""
  counterparty: str | None = None
  """Counterparty address, if known."""

class CryptoTransaction(BaseObservation):
  type: Literal['crypto_transaction'] = 'crypto_transaction'
  """Generic blockchain transaction observation."""
  tx_id: str | None = None
  """Blockchain transaction hash/identifier."""
  fee: Fee | None = None
  """Fee paid, if any."""
  transfers: Sequence[CryptoTransfer] = []
  """Transfers occured within the transaction."""