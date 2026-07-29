# vendored from workspace/.agents/check.py — do not edit; run `python scripts/sync.py agents`
"""
Verify that this repo's vendored agent configuration has not been hand-edited.

Reads `.vendored.json` next to this script, recomputes the sha256 of every listed
file with its vendoring marker stripped, and compares that against the canonical
hash recorded when the file was vendored. Uses only the standard library so it can
run in CI with no dependencies installed.

This module is also the shared authority on where a vendoring marker lives:
`scripts/agents.py` in the workspace imports `marker_offset` from here so that
insertion and stripping cannot drift apart.
"""
import hashlib
import json
import sys
from pathlib import Path

MARKER_SENTINEL = 'vendored from workspace/'
"""Substring that identifies a vendoring marker line."""
FRONTMATTER_FENCE = '---'
"""Delimiter of a YAML frontmatter block."""
MANIFEST_NAME = '.vendored.json'
"""Name of the manifest mapping vendored paths to canonical hashes."""

def marker_offset(text: str) -> int:
  """
  Character offset at which the vendoring marker line belongs in `text`.

  That is the very start of the file, except for files opening with a YAML
  frontmatter block, where it is the first line of the body: a comment above the
  frontmatter would break frontmatter parsing. The marker is always exactly one
  line plus its newline at this offset, which makes stripping unambiguous.

  Args:
    text: Contents of a canonical or vendored file.
  """
  if not text.startswith(FRONTMATTER_FENCE + '\n'):
    return 0
  offset = len(FRONTMATTER_FENCE) + 1
  while offset < len(text):
    end = text.find('\n', offset)
    if end < 0:
      return 0
    line = text[offset:end]
    offset = end + 1
    if line.strip() == FRONTMATTER_FENCE:
      return offset
  return 0

def strip_marker(text: str) -> str | None:
  """
  Remove the vendoring marker line from `text`, inverting its insertion.

  Args:
    text: Contents of a vendored file.

  Returns:
    The canonical contents, or `None` if no marker sits at the expected offset.
  """
  offset = marker_offset(text)
  end = text.find('\n', offset)
  if end < 0:
    return None
  if MARKER_SENTINEL not in text[offset:end]:
    return None
  return text[:offset] + text[end + 1:]

def check(agents_dir: Path) -> list[str]:
  """
  Compare every vendored file against the hash recorded in the manifest.

  Args:
    agents_dir: Directory holding the manifest and the vendored files.

  Returns:
    One description per problem found; empty when everything matches.
  """
  manifest_path = agents_dir / MANIFEST_NAME
  if not manifest_path.is_file():
    return [f'{MANIFEST_NAME}: missing; this repo has never been vendored']
  manifest: dict[str, str] = json.loads(manifest_path.read_bytes().decode('utf-8'))
  problems = []
  for rel in sorted(manifest):
    path = agents_dir / rel
    if not path.is_file():
      problems.append(f'{rel}: missing')
      continue
    stripped = strip_marker(path.read_bytes().decode('utf-8'))
    if stripped is None:
      problems.append(f'{rel}: vendoring marker missing or moved')
      continue
    if hashlib.sha256(stripped.encode('utf-8')).hexdigest() != manifest[rel]:
      problems.append(f'{rel}: modified by hand')
  return problems

def main() -> None:
  """Report any drift in this repo's vendored files and exit non-zero if found."""
  agents_dir = Path(__file__).resolve().parent
  problems = check(agents_dir)
  if problems:
    print('Vendored agent configuration has drifted:', file=sys.stderr)
    for problem in problems:
      print(f'  {problem}', file=sys.stderr)
    print('Restore it from the workspace with `python scripts/sync.py agents`.', file=sys.stderr)
    sys.exit(1)
  print(f'Vendored agent configuration is intact ({agents_dir}).')

if __name__ == '__main__':
  main()
