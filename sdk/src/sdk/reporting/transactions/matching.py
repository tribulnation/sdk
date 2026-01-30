from typing_extensions import Sequence, Mapping, MutableMapping, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

from .types import Flow, Event, Transaction, D, D2

@dataclass
class EventMatcher:
  flows: Sequence[Flow]
  index: Mapping[str, Mapping[str, Mapping[datetime, MutableMapping[int, Flow]]]]
  max_time_window: timedelta = field(default=timedelta(hours=1), kw_only=True)

  @classmethod
  def of(cls, flows: Sequence[Flow], *, max_time_window: timedelta = timedelta(hours=1)):
    idx = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for i, f in enumerate(flows):
      idx[f.asset][f.label][f.time][i] = f
    return cls(flows, idx, max_time_window=max_time_window)

  def candidates(self, f_hat: Flow, *, time_window: timedelta | None = None) -> MutableMapping[int, Flow]:
    group = self.index[f_hat.asset][f_hat.label]
    if time_window is None:
      return group[f_hat.time]
    else:
      ts = [t for t in group.keys() if f_hat.time - time_window <= t <= f_hat.time + time_window]
    out: dict[int, Flow] = {}
    for t in ts:
      out.update(group[t])
    return out

  def use(self, key: int):
    f = self.flows[key]
    del self.index[f.asset][f.label][f.time][key]

  def insert(self, key: int):
    f = self.flows[key]
    self.index[f.asset][f.label][f.time][key] = f

  def match(self, flows: Iterable[Flow]) -> list[int] | None:
    """Match the flows to the flows in the matcher. The matched flows are removed from the matcher, preventing double-matching."""
    if (matches := self._match_impl(flows, time_window=None)) is not None:
      return matches
    time_window = timedelta(seconds=1)
    while time_window < self.max_time_window:
      if (matches := self._match_impl(flows, time_window=time_window)) is not None:
        return matches
      time_window *= 2

  def _match_impl(self, flows: Iterable[Flow], *, time_window: timedelta | None) -> list[int] | None:
    out = []
    for f_hat in flows:
      candidates = self.candidates(f_hat, time_window=time_window)
      if len(candidates) == 0:
        for k in out:
          self.insert(k) # restore the used flows
        return None
      elif len(candidates) == 1:
        k = next(iter(candidates.keys()))
      else:
        k = min(candidates.keys(), key=lambda i: abs(f_hat.change - candidates[i].change))
      self.use(k)
      out.append(k)
    return out


def match_transactions(
  flows: Sequence[Flow],
  events: Sequence[Event[D2]],
) -> tuple[list[Transaction[D|D2]], list[Flow]]:
  """Match the flows to the events. Returns `(matched_txs, unmatched_flows)`"""
  matcher = EventMatcher.of(flows)
  used = set[int]()
  transactions: list[Transaction] = []
  
  for e in events:
    if (matches := matcher.match(e.expected_flows)) is None:
      raise ValueError(f'Could not match the flows for the event: {e}')
    used.update(matches)
    transactions.append(Transaction(
      event=e,
      flows=[flows[i] for i in matches] + list(e.fixed_flows)
    ))

  unused = set(range(len(flows))) - used
  unmatched_flows = [flows[i] for i in unused]
  return transactions, unmatched_flows