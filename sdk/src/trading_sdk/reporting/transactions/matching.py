from typing_extensions import Sequence, Mapping, MutableMapping, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

from .types import Posting, Operation, Transaction, D, D2

@dataclass
class PostingMatcher:
  postings: Sequence[Posting]
  index: Mapping[str, Mapping[str, Mapping[datetime, MutableMapping[int, Posting]]]]
  max_time_window: timedelta = field(default=timedelta(hours=1), kw_only=True)

  @classmethod
  def of(cls, postings: Sequence[Posting], *, max_time_window: timedelta = timedelta(hours=1)):
    idx = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for i, p in enumerate(postings):
      idx[p.asset][p.type][p.time][i] = p
    return cls(postings, idx, max_time_window=max_time_window)

  def candidates(self, p_hat: Posting, *, time_window: timedelta | None = None) -> MutableMapping[int, Posting]:
    group = self.index[p_hat.asset][p_hat.type]
    if time_window is None:
      return group[p_hat.time]
    else:
      ts = [t for t in group.keys() if p_hat.time - time_window <= t <= p_hat.time + time_window]
    out: dict[int, Posting] = {}
    for t in ts:
      out.update(group[t])
    return out

  def use(self, key: int):
    p = self.postings[key]
    del self.index[p.asset][p.type][p.time][key]

  def insert(self, key: int):
    p = self.postings[key]
    self.index[p.asset][p.type][p.time][key] = p

  def match(self, postings: Iterable[Posting]) -> list[int] | None:
    """Match the postings to the postings in the matcher. The matched postings are removed from the matcher, preventing double-matching."""
    if (matches := self._match_impl(postings, time_window=None)) is not None:
      return matches
    time_window = timedelta(seconds=1)
    while time_window < self.max_time_window:
      if (matches := self._match_impl(postings, time_window=time_window)) is not None:
        return matches
      time_window *= 2

  def _match_impl(self, postings: Iterable[Posting], *, time_window: timedelta | None) -> list[int] | None:
    out = []
    for p_hat in postings:
      candidates = self.candidates(p_hat, time_window=time_window)
      if len(candidates) == 0:
        for k in out:
          self.insert(k) # restore the used postings
        return None
      elif len(candidates) == 1:
        k = next(iter(candidates.keys()))
      else:
        k = min(candidates.keys(), key=lambda i: abs(p_hat.change - candidates[i].change))
      self.use(k)
      out.append(k)
    return out


def match_transactions(
  postings: Sequence[Posting[D]],
  operations: Sequence[Operation[D2]],
) -> tuple[list[Transaction[D|D2]], list[Posting[D]]]:
  """Match the postings to the operations. Returns `(matched_txs, unmatched_postings)`"""
  matcher = PostingMatcher.of(postings)
  used = set[int]()
  transactions: list[Transaction[D]] = []
  
  for op in operations:
    if (matches := matcher.match(op.expected_postings)) is None:
      raise ValueError(f'Could not match the postings for the operation: {op}')
    used.update(matches)
    transactions.append(Transaction(
      operation=op,
      postings=[postings[i] for i in matches] + list(op.fixed_postings)
    ))

  unused = set(range(len(postings))) - used
  unmatched_postings = [postings[i] for i in unused]
  return transactions, unmatched_postings