from typing_extensions import Iterable, TypeVar, Callable
from collections import defaultdict
from decimal import Decimal
from web3.types import Wei, Gwei
from web3 import Web3

T = TypeVar('T')
K = TypeVar('K')

def same_address(a: str | bytes, b: str | bytes):
  return Web3.to_checksum_address(a) == Web3.to_checksum_address(b)

def wei2eth(wei: Decimal | int | Wei) -> Decimal:
  return wei / Decimal(10**18)

def gwei2eth(gwei: Decimal | int | Gwei) -> Decimal:
  return gwei / Decimal(10**9)

def group_by(xs: Iterable[T], key: Callable[[T], K]) -> dict[K, list[T]]:
  d = defaultdict(list)
  for x in xs:
    d[key(x)].append(x)
  return d
