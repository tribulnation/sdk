"""Renders the streaming-support table for `docs/market/streaming.md`.

Which venues stream natively is a real differentiator, and every
`packages/impl/*/impl.toml` already declares it: `support = "full"` covers both stream
methods (unless the contract scopes one to a kind of market the venue does not serve),
`partial` names whichever ones it implements. Generating the table from that is
what keeps it from drifting the way a hand-written list would.
"""

from typing_extensions import Mapping

from sdk_dev.support import ImplFile, MarketKind, method_universe

STREAMS_START = '<!-- streams -->'
STREAMS_END = '<!-- /streams -->'
STREAM_METHODS = ('depth_stream', 'trades_stream')
STREAMS_SURFACE = 'market'


def render_streams_markdown(
  impl_files: dict[str, ImplFile],
  *,
  kinds: Mapping[str, MarketKind | None],
  venue_names: dict[str, str],
) -> str:
  """
  Render the venue x stream-method table.

  Args:
    impl_files: `load_impl_files()`'s output.
    kinds: `load_method_kinds()` of the Market contract.
    venue_names: `{slug: display name}`, from registry.toml, whose order the rows follow.

  Returns:
    A markdown table, one row per venue with a Market implementation. Venues without one
    are left out rather than shown as empty rows: the page is about streaming within
    Market, and a venue with no Market at all is the support matrix's business.
  """
  serving = {
    method: set(
      method_universe(impl_files, STREAMS_SURFACE, method, kind=kinds[method])
    )
    for method in STREAM_METHODS
  }
  header = ' | '.join(f'`{method}`' for method in STREAM_METHODS)
  divider = ' | '.join(['---'] * (len(STREAM_METHODS) + 1))
  rows = [f'| Venue | {header} |', f'| {divider} |']
  for slug, name in venue_names.items():
    entry = impl_files.get(slug)
    market = entry.support.get(STREAMS_SURFACE) if entry else None
    if market is None or market.support == 'none':
      continue
    cells = ' | '.join(
      '✅' if slug in serving[method] else '—' for method in STREAM_METHODS
    )
    rows.append(f'| {name} | {cells} |')
  return '\n'.join(rows)
