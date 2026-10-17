# vendored from workspace/.agents/skills/diagnose-failing-account/scripts/nonce_bisect.py — do not edit; run `python scripts/sync.py agents`
"""Find the block where an EVM address's nonce first exceeds `n`, and the txs in it that consumed the nonce.

Usage: nonce_bisect.py <archive rpc url> <address> <n> <lo height> <hi height>
Prints the block and each tx in it sent by the address or carrying an EIP-7702 authorization, with
its status and gas used. Costs about log2(hi - lo) + a few archive reads. Standard library only.
"""

import json
import sys
import urllib.request
from typing_extensions import Any


def rpc(url: str, method: str, params: list[Any]) -> Any:
  """One JSON-RPC call."""
  body = json.dumps(
    {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
  ).encode()
  request = urllib.request.Request(
    url, body, {'content-type': 'application/json', 'user-agent': 'curl/8'}
  )
  answer = json.load(urllib.request.urlopen(request, timeout=30))
  if 'error' in answer:
    raise RuntimeError(f'{method}: {answer["error"]}')
  return answer['result']


def nonce_at(url: str, address: str, height: int) -> int:
  """The address's transaction count at a height."""
  return int(rpc(url, 'eth_getTransactionCount', [address, hex(height)]), 16)


def main():
  """Bisect the window, then print the consuming block's relevant txs."""
  url, address = sys.argv[1], sys.argv[2].lower()
  n, lo, hi = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
  first, last = nonce_at(url, address, lo), nonce_at(url, address, hi)
  if not first <= n < last:
    sys.exit(
      f'nonce {n} is not consumed in ({lo}, {hi}]: nonce {first} at lo, {last} at hi'
    )
  while hi - lo > 1:
    mid = (lo + hi) // 2
    if nonce_at(url, address, mid) > n:
      hi = mid
    else:
      lo = mid
  print('nonce', n, 'consumed in block', hi)
  block = rpc(url, 'eth_getBlockByNumber', [hex(hi), True])
  for tx in block['transactions']:
    auths = tx.get('authorizationList') or []
    if tx['from'].lower() != address and not auths:
      continue
    receipt = rpc(url, 'eth_getTransactionReceipt', [tx['hash']])
    print(json.dumps({
      'hash': tx['hash'], 'type': tx['type'], 'from': tx['from'], 'to': tx['to'], 'nonce': int(tx['nonce'], 16),
      'auths': [{k: a.get(k) for k in ('address', 'nonce', 'chainId')} for a in auths],
      'status': receipt['status'], 'gasUsed': receipt['gasUsed'], 'effectiveGasPrice': receipt.get('effectiveGasPrice'),
      'l1Fee': receipt.get('l1Fee'),
    }))  # fmt: skip


if __name__ == '__main__':
  main()
