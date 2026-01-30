from dataclasses import dataclass, field
from .core import SdkMixin
from .earn import Earn
from .reporting import Reporting
from .wallet import Wallet

@dataclass
class Bitget(SdkMixin):
  earn: Earn = field(init=False)
  reporting: Reporting = field(init=False)
  wallet: Wallet = field(init=False)

  def __post_init__(self):
    self.earn = Earn(self.client, validate=self.validate)
    self.reporting = Reporting(self.client, validate=self.validate)
    self.wallet = Wallet(self.client, validate=self.validate)