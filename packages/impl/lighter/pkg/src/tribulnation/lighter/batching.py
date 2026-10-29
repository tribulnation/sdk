"""Order transactions sent together: what waits while one is in flight leaves as one `sendTxBatch`."""

from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import asyncio

from typing_extensions import AsyncIterator, Awaitable, Callable, Sequence
from typed_lighter import Lighter
from typed_lighter.core.exc import ApiError, BadRequest, NetworkError
from typed_lighter.core.signer.txs.base import SignedTx
from typed_lighter.schemas import SendTxResponse
from typed_lighter.tx.batch import SendTxBatchResponse

BATCH_LIMIT = 15
"""Most transactions per `sendTxBatch`. Lighter takes 50 over HTTP, but advises 15 or
fewer to stay within its CDN's request size."""


@dataclass(frozen=True)
class OrderTx:
  """One order transaction (create, modify or cancel), ready to go alone or in a batch."""

  send: Callable[[], Awaitable[SendTxResponse]]
  """Sign and submit it alone, through the client's nonce manager (`client.tx`)."""
  sign: Callable[[int, int], SignedTx]
  """Sign it for a batch, with an API key index and a nonce (`client.signer`)."""


@dataclass(frozen=True)
class Queued:
  """A submitted transaction and the caller waiting for its outcome."""

  tx: OrderTx
  result: asyncio.Future[SendTxResponse]


def member(response: SendTxBatchResponse, tx_hash: str) -> SendTxResponse:
  """One transaction's share of a batch's acceptance, shaped like a `sendTx` reply."""
  out = SendTxResponse(
    code=response['code'],
    tx_hash=tx_hash,
    predicted_execution_time_ms=response['predicted_execution_time_ms'],
  )
  if 'message' in response:
    out['message'] = response['message']
  if 'volume_quota_remaining' in response:
    out['volume_quota_remaining'] = response['volume_quota_remaining']
  return out


def batch_error(e: Exception) -> Exception:
  """What each transaction of a batch raises when the whole batch failed with `e`.

  A refusal (`BadRequest`) names no transaction, and Lighter doesn't document whether a
  refused batch places none of them. Each transaction gets an `ApiError` caused by it,
  so no create in the batch passes for a certain refusal (`OrderRejected`). Any other
  failure (a rate limit, a network error, a 5xx) is the same for every transaction.
  """
  if isinstance(e, BadRequest):
    error = ApiError(*e.args)
    error.__cause__ = e
    return error
  return e


@dataclass
class TxBatcher:
  """Send one client's order transactions one request at a time, batching what waits.

  A transaction submitted while none is in flight goes alone, through `sendTx`, as
  without batching. Those submitted while one is in flight, or in the same event-loop
  turn as another, wait for it and leave together, up to `BATCH_LIMIT` per
  `sendTxBatch`. The client's nonce manager already sends one API key's transactions
  one at a time, so waiting adds no latency: it saves requests, which a Standard
  account has 60 per minute of, `sendTx` included.

  A batch is signed with consecutive nonces of one key (`tx.reserve_nonces`). Its
  acceptance settles each transaction with its own hash; its failure fails them all
  (`batch_error`).
  """

  client: Lighter
  queue: list[Queued] = field(default_factory=list[Queued])
  """Transactions waiting to be sent, oldest first."""
  worker: asyncio.Task[None] | None = None
  """The task sending the queue, while it isn't empty."""

  async def submit(self, tx: OrderTx) -> SendTxResponse:
    """Send `tx`, alone or in a batch, and return its acceptance.

    Cancelling the call drops the transaction while it waits; once it is sent, its
    outcome is unknown, as for any cancelled submission.

    Raises:
      ApiError: The batch it went in was refused (see `batch_error`).
      NetworkError: The client closed before its outcome was known.
    """
    result = asyncio.get_running_loop().create_future()
    self.queue.append(Queued(tx=tx, result=result))
    if self.worker is None or self.worker.done():
      self.worker = asyncio.create_task(self.drain())
    return await result

  def take(self) -> list[Queued]:
    """The next transactions to send, oldest first; cancelled ones are dropped."""
    waiting = [q for q in self.queue if not q.result.done()]
    batch, self.queue = waiting[:BATCH_LIMIT], waiting[BATCH_LIMIT:]
    return batch

  async def drain(self):
    """Send the queue, one request at a time, until it is empty."""
    while batch := self.take():
      await self.send(batch)

  async def send(self, batch: list[Queued]):
    """Send `batch` (alone if it is one transaction) and settle every result."""
    try:
      if len(batch) == 1:
        responses = [await batch[0].tx.send()]
      else:
        responses = await self.send_batch([q.tx for q in batch])
    except asyncio.CancelledError:
      settle_errors(batch, NetworkError('The Lighter client closed while sending'))
      raise
    except Exception as e:
      settle_errors(batch, e if len(batch) == 1 else batch_error(e))
    else:
      for q, response in zip(batch, responses):
        if not q.result.done():
          q.result.set_result(response)

  async def send_batch(self, txs: Sequence[OrderTx]) -> list[SendTxResponse]:
    """Sign `txs` with consecutive nonces of one key and submit them as one `sendTxBatch`.

    Raises:
      ApiError: The reply's hashes don't match the transactions one to one.
    """
    async with self.client.tx.reserve_nonces(len(txs)) as reservation:
      signed = [
        tx.sign(reservation.api_key_index, nonce)
        for tx, nonce in zip(txs, reservation.nonces)
      ]
      response = await self.client.tx.batch(signed)
    hashes = response['tx_hash']
    if len(hashes) != len(txs):
      raise ApiError(
        f'sendTxBatch answered {len(hashes)} hashes for {len(txs)} transactions'
      )
    return [member(response, tx_hash) for tx_hash in hashes]

  @asynccontextmanager
  async def closing(self) -> AsyncIterator[None]:
    """On exit, stop sending: what still waits fails with `NetworkError`."""
    try:
      yield
    finally:
      if self.worker is not None and not self.worker.done():
        self.worker.cancel()
        with suppress(asyncio.CancelledError):
          await self.worker
      settle_errors(
        self.queue, NetworkError('The Lighter client closed before sending')
      )
      self.queue.clear()


def settle_errors(batch: Sequence[Queued], error: Exception):
  """Fail every unsettled result of `batch` with `error`."""
  for q in batch:
    if not q.result.done():
      q.result.set_exception(error)
