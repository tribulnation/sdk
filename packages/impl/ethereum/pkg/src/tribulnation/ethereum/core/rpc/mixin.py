from typing_extensions import AsyncContextManager, Iterable
from dataclasses import dataclass

from ethereum import NodeRpc

from tribulnation.sdk import SDK


@dataclass(kw_only=True)
class Mixin(SDK):
  node: NodeRpc
  address: str

  @property
  def w3(self):
    return self.node.w3

  @classmethod
  def rpc_at(cls, rpc_url: str, *, address: str):
    node = NodeRpc.at(rpc_url)
    return cls(node=node, address=address)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.node
