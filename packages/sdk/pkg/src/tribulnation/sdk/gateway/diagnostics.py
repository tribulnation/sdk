"""Runtime diagnostics for memory and task growth investigations."""

from pathlib import Path
from typing_extensions import Any
import asyncio
import os


def memory_snapshot(*, extra: dict[str, Any] | None = None):
  """Return JSON-serializable memory diagnostics for the current process."""
  status = proc_status()
  data: dict[str, Any] = {
    'pid': os.getpid(),
    'rss': status.get('VmRSS'),
    'rss_hwm': status.get('VmHWM'),
    'vms': status.get('VmSize'),
    'threads': status.get('Threads'),
    'fds': fd_count(),
    'asyncio_tasks': asyncio_task_count(),
    'smaps': smaps_rollup(),
  }
  if extra:
    data.update(extra)
  return data


def asyncio_task_count() -> int | None:
  """Count tasks in the current loop when one exists."""
  try:
    return len(asyncio.all_tasks())
  except RuntimeError:
    return None


def fd_count() -> int | None:
  """Count open file descriptors when procfs is available."""
  try:
    return len(list(Path('/proc/self/fd').iterdir()))
  except FileNotFoundError:
    return None


def proc_status() -> dict[str, int]:
  """Read process memory and thread counters from procfs."""
  try:
    text = Path('/proc/self/status').read_text()
  except FileNotFoundError:
    return {}

  status: dict[str, int] = {}
  for line in text.splitlines():
    key, _, value = line.partition(':')
    if key not in {'VmRSS', 'VmHWM', 'VmSize', 'Threads'}:
      continue
    parts = value.strip().split()
    if not parts:
      continue
    n = int(parts[0])
    status[key] = n * 1024 if len(parts) > 1 and parts[1] == 'kB' else n
  return status


def smaps_rollup() -> dict[str, int]:
  """Read aggregate process memory accounting from procfs."""
  try:
    text = Path('/proc/self/smaps_rollup').read_text()
  except FileNotFoundError:
    return {}

  keys = {
    'Rss',
    'Pss',
    'Shared_Clean',
    'Shared_Dirty',
    'Private_Clean',
    'Private_Dirty',
    'Referenced',
    'Anonymous',
    'LazyFree',
    'AnonHugePages',
    'ShmemPmdMapped',
    'FilePmdMapped',
    'Shared_Hugetlb',
    'Private_Hugetlb',
    'Swap',
    'SwapPss',
    'Locked',
  }
  result: dict[str, int] = {}
  for line in text.splitlines():
    key, _, value = line.partition(':')
    if key not in keys:
      continue
    parts = value.strip().split()
    if not parts:
      continue
    n = int(parts[0])
    result[key] = n * 1024 if len(parts) > 1 and parts[1] == 'kB' else n
  return result
