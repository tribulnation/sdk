"""Renders a contract file's methods as markdown, for the `<!-- methods -->` marker in
`docs/<surface>/methods.md`. Every venue's example and notes are emitted, each wrapped in
a `<div data-venue="<slug>" data-venue-name="<name>">` closed by `</div><!-- /venue -->`,
which the docs site folds into one tab strip per method; without that (raw markdown,
GitHub) the blocks simply stack, each headed by its venue name. Examples show the
method's own lines only — the component's preamble is stated once on the page, not
repeated per method.
"""

from sdk_dev.contract import ContractFile
from sdk_dev.source import SourceMethod

METHODS_MARKER = '<!-- methods -->'


def render_methods_markdown(
  contract: ContractFile,
  *,
  rendered: dict,
  source: dict[str, SourceMethod],
  venue_names: dict[str, str],
) -> str:
  """
  Render every method of `contract` as a markdown section.

  Args:
    contract: The validated contract file.
    rendered: `render_contract_file`'s output for it — supplies each method's eligible
      venues and its per-venue `subsets`.
    source: `{method_name: SourceMethod}`, from `sdk_dev.source`.
    venue_names: `{slug: display name}`, from registry.toml.

  Returns:
    Markdown: one `### <group>` per group in first-appearance order (when any method has
    one), one heading per method beneath it with the signature, description, semantics,
    and a venue block per eligible venue.
  """
  grouped = any(m.group for m in contract.methods.values())
  method_heading = '####' if grouped else '###'
  out: list[str] = []
  current_group: str | None = None
  for name, method in contract.methods.items():
    if grouped and method.group != current_group:
      current_group = method.group
      out.append(f'### {current_group}\n')
    info = source[name]
    out.append(f'{method_heading} `{name}`\n')
    out.append(f'```python\n{info["signature"]}\n```\n')
    if info['description']:
      out.append(f'{info["description"]}\n')
    if info['semantics']:
      out.append(f'{info["semantics"]}\n')
    entry = rendered['methods'][name]
    for slug in entry['venues']:
      subset = entry['subsets'][slug]
      name = venue_names.get(slug, slug.capitalize())
      out.append(f'<div data-venue="{slug}" data-venue-name="{name}">\n')
      out.append(f'**{name}**\n')
      note = method.venues.get(slug)
      if note:
        out.append(f'{note.strip()}\n')
      out.append(f'```python\n{subset["snippet"]}\n```\n')
      out.append('```\n' + '\n'.join(subset['result']) + '\n```\n')
      out.append('</div><!-- /venue -->\n')
  return '\n'.join(out)
