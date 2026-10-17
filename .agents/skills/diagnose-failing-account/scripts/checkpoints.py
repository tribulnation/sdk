# vendored from workspace/.agents/skills/diagnose-failing-account/scripts/checkpoints.py — do not edit; run `python scripts/sync.py agents`
"""Summarise a unit's served verification: one line per failing (compartment, asset) series, with its delta trend.

Usage: checkpoints.py <verification.json | -> [--status failed|unassessable]
Input is the body of `GET /v1/<unit>/resources/{r}/verification` or its `state.payloads` row.
Standard library only.
"""

from collections import Counter
from decimal import Decimal
import json
import sys

PASSING = ('passed', 'accepted')
"""Checkpoint statuses that need no diagnosis (`accepted` = within tolerance)."""


def trend(deltas: list[Decimal]) -> str:
  """Classify a series of deltas as constant, growing, shrinking or erratic."""
  if len(deltas) < 2:
    return 'single'
  if all(d == deltas[0] for d in deltas):
    return 'constant'
  pairs = list(zip(deltas, deltas[1:]))
  if all(abs(b) >= abs(a) for a, b in pairs):
    return 'growing'
  if all(abs(b) <= abs(a) for a, b in pairs):
    return 'shrinking'
  return 'erratic'


def main():
  """Print the verdict, the non-passing intervals and one summary line per failing series."""
  args = sys.argv[1:]
  wanted = args[args.index('--status') + 1] if '--status' in args else None
  source = next((a for a in args if a != '--status' and a != wanted), '-')
  body = json.load(sys.stdin if source == '-' else open(source))
  checkpoints = sorted(body.get('checkpoints', []), key=lambda c: c['at'])
  print('status', body.get('status'), dict(Counter(c['status'] for c in checkpoints)))
  for interval in body.get('intervals', []):
    if interval['status'] not in PASSING:
      print(
        'interval', interval.get('from'), '->', interval.get('to'), interval['status']
      )
  series: dict[tuple[str, str], list[dict]] = {}
  for c in checkpoints:
    series.setdefault((c['compartment'], c['asset']), []).append(c)
  for (compartment, asset), rows in sorted(series.items()):
    failing = [
      c
      for c in rows
      if c['status'] not in PASSING and (wanted is None or c['status'] == wanted)
    ]
    if not failing:
      continue
    last = failing[-1]
    deltas = [Decimal(c['delta']) for c in rows if c.get('delta') is not None]
    shown = (
      [str(d) for d in deltas]
      if len(deltas) <= 4
      else [*map(str, deltas[:3]), '…', str(deltas[-1])]
    )
    manual = ' manual-snapshot' if not last.get('evidence') else ''
    print(
      f'{"/".join(sorted({c["status"] for c in failing}))} {compartment} {asset} n={len(failing)}/{len(rows)} '
      f'{failing[0]["at"]}..{last["at"]} expected={last["expected"]} observed={last["observed"]} '
      f'tol={last["tolerance"]} trend={trend(deltas)} deltas={shown}{manual} {last.get("reason", "")}'
    )
  print('detail keys', sorted(body.get('detail', {})))


if __name__ == '__main__':
  main()
