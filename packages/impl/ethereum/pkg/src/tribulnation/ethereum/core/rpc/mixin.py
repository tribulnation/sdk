from functools import cached_property
from .exc import wrap_exceptions
from typing_extensions import AsyncContextManager, Iterable
from dataclasses import dataclass

from typed_ethereum import NodeRpc

from tribulnation.sdk.core import ManagedResource
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

  @cached_property
  def node_resource(self) -> ManagedResource[object]:
    """Own node with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.node,
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.node_resource
