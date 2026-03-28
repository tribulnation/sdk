from dataclasses import dataclass

from ethereum import NodeRpc

@dataclass(kw_only=True)
class Mixin:
  node: NodeRpc
  address: str

  @property
  def w3(self):
    return self.node.w3

  @classmethod
  def at(cls, rpc_url: str, *, address: str):
    node = NodeRpc.at(rpc_url)
    return cls(node=node, address=address)
  
  async def __aenter__(self):
    await self.node.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.node.__aexit__(exc_type, exc_value, traceback)