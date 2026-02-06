from typing_extensions import Protocol
from .instruments import Instruments

class Earn(Instruments, Protocol):
  ...