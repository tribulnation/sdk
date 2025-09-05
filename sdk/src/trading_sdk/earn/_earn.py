from typing_extensions import Protocol
from .subscribe import Subscribe
from .redeem import Redeem
from .reward_history import RewardHistory

class Earn(Subscribe, Redeem, RewardHistory, Protocol):
  ...