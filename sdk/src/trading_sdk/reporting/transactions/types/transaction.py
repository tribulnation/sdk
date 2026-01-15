from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime

from .operations import Operation
from .postings import Posting

@dataclass(kw_only=True)
class Transaction:
  id: str
  time: datetime
  operation: Operation
  postings: Sequence[Posting]