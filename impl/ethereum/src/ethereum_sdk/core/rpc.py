from dataclasses import dataclass

from ethereum.node_rpc import NodeRpc

@dataclass(kw_only=True)
class NodeRpcMixin:
  node: NodeRpc
  address: str
  ignore_bad_contracts: bool = True

  @classmethod
  def at(cls, rpc_url: str, *, address: str, ignore_bad_contracts: bool = True):
    node = NodeRpc.at(rpc_url)
    return cls(node=node, address=address, ignore_bad_contracts=ignore_bad_contracts)
  
  async def __aenter__(self):
    await self.node.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.node.__aexit__(exc_type, exc_value, traceback)