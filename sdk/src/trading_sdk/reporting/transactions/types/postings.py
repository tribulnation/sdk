from typing_extensions import Literal
from dataclasses import dataclass
from decimal import Decimal

@dataclass(kw_only=True)
class BasePosting:
  asset: str
  change: Decimal

  def __format__(self, fmt: str) -> str:
    s = '+' if self.change > 0 else ''
    return f'{s}{self.change:{fmt}} {self.asset}'

  def __str__(self) -> str:
    return f'{self}'

@dataclass(kw_only=True)
class CurrencyPosting(BasePosting):
  kind: Literal['currency'] = 'currency'

@dataclass(kw_only=True)
class FuturePosting(BasePosting):
  kind: Literal['future'] = 'future'
  price: Decimal

@dataclass(kw_only=True)
class StrategyPosting(BasePosting):
  kind: Literal['strategy'] = 'strategy'

Posting = CurrencyPosting | FuturePosting | StrategyPosting