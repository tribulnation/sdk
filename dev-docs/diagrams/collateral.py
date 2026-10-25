"""Generate the collateral diagrams in `docs/market/media/` (ADR 0051).

Run `.venv/bin/python dev-docs/diagrams/collateral.py` after editing, and commit the SVGs
it writes. They are plain images so GitHub and the docs site render them alike; each
carries its own light and dark palette, and stays 480 units wide to remain legible on a
phone.
"""

from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[2] / 'docs' / 'market' / 'media'
WIDTH = 480

STYLE = """
text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; fill: #1f2328; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13.5px; }
.title { font-size: 16px; font-weight: 600; }
.small { font-size: 13px; }
.muted { fill: #59636e; }
.bg { fill: #ffffff; stroke: #d0d7de; }
.market { fill: #f6f8fa; stroke: #8c959f; }
.spot { fill: #dafbe1; stroke: #1a7f37; }
.margin { fill: #fbefff; stroke: #8250df; }
.money { fill: #fff8c5; stroke: #9a6700; }
.shared { fill: #fff8c5; stroke: #9a6700; stroke-width: 2.5; }
.warn { fill: #fff1e5; stroke: #bc4c00; stroke-dasharray: 5 4; }
.link { stroke: #59636e; stroke-width: 1.5; fill: none; }
.head { fill: #59636e; }
.rule { stroke: #d0d7de; }
@media (prefers-color-scheme: dark) {
  text { fill: #f0f6fc; }
  .muted { fill: #9198a1; }
  .bg { fill: #0d1117; stroke: #3d444d; }
  .market { fill: #151b23; stroke: #656c76; }
  .spot { fill: #10261a; stroke: #3fb950; }
  .margin { fill: #221a33; stroke: #a371f7; }
  .money, .shared { fill: #2a2312; stroke: #d29922; }
  .warn { fill: #2b1a0f; stroke: #f0883e; }
  .link { stroke: #9198a1; }
  .head { fill: #9198a1; }
  .rule { stroke: #3d444d; }
}
"""


@dataclass
class Svg:
  """An SVG drawing built from boxes, text and arrows."""

  height: int
  title: str
  parts: list[str] = field(default_factory=list[str])

  def box(self, x: float, y: float, w: float, h: float, cls: str):
    """A rounded box."""
    self.parts.append(
      f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" class="{cls}"/>'
    )

  def text(self, x: float, y: float, s: str, cls: str = '', anchor: str = 'start'):
    """One line of text, `cls` being space-separated style classes."""
    self.parts.append(
      f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(s)}</text>'
    )

  def line(self, *points: tuple[float, float], arrow: bool = False):
    """A polyline, ending in an arrowhead when `arrow` is set."""
    coords = ' '.join(f'{x},{y}' for x, y in points)
    end = ' marker-end="url(#head)"' if arrow else ''
    self.parts.append(f'<polyline points="{coords}" class="link"{end}/>')

  def render(self) -> str:
    """The SVG document."""
    return (
      f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{self.height}" '
      f'viewBox="0 0 {WIDTH} {self.height}" role="img" aria-label="{escape(self.title)}">\n'
      f'<title>{escape(self.title)}</title>\n<style>{STYLE}</style>\n'
      '<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
      'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
      'class="head"/></marker></defs>\n'
      f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{self.height - 1}" rx="12" class="bg"/>\n'
      + '\n'.join(self.parts)
      + '\n</svg>\n'
    )


def market_types() -> Svg:
  """Market splits into SpotMarket and MarginMarket, each with its account reads."""
  svg = Svg(424, 'Market types: which account reads live where')
  svg.box(90, 16, 300, 62, 'market')
  svg.text(240, 42, 'Market', 'title', 'middle')
  svg.text(240, 64, 'books · trades · orders · rules · fees', 'muted', 'middle')
  svg.line((240, 78), (240, 98))
  svg.line((125, 98), (355, 98))
  svg.line((125, 98), (125, 118))
  svg.line((355, 98), (355, 118))

  svg.box(16, 118, 218, 180, 'spot')
  svg.text(32, 144, 'SpotMarket', 'title')
  svg.text(32, 163, "kind 'spot' · is_spot(m)", 'small muted')
  for i, s in enumerate(['balances()', 'collateral_ids()', 'rules() → SpotRules']):
    svg.text(32, 194 + 22 * i, s, 'mono')
  svg.text(32, 264, 'Balance(total, free) of', 'small muted')
  svg.text(32, 281, 'the base and quote assets', 'small muted')

  svg.box(246, 118, 218, 180, 'margin')
  svg.text(262, 144, 'MarginMarket', 'title')
  svg.text(262, 163, 'is_margin(m)', 'small muted')
  reads = [
    'position()',
    'collateral()',
    'leverage()',
    'available_notional()',
    'collateral_id()',
  ]
  for i, s in enumerate(reads):
    svg.text(262, 194 + 22 * i, s, 'mono')
  svg.line((355, 298), (355, 322))

  svg.box(246, 322, 218, 86, 'margin')
  svg.text(262, 348, 'PerpMarket', 'title')
  svg.text(262, 370, '+ funding · index', 'mono')
  svg.text(262, 392, "kind 'perp' · is_perp(m)", 'small muted')

  svg.box(16, 322, 218, 86, 'warn')
  svg.text(32, 346, 'market.position()?', 'mono')
  svg.text(32, 368, 'Not on Market: narrow with', 'small')
  svg.text(32, 386, 'is_perp(m), or fetch with', 'small')
  svg.text(32, 402, 'sdk.perp_market(id)', 'mono small')
  return svg


@dataclass(frozen=True)
class Panel:
  """One venue style: markets on the left, the money their IDs name on the right."""

  title: str
  subtitle: str
  markets: list[tuple[str, int, int]]
  """Label, first row and row span."""
  money: list[tuple[str, int, int, bool]]
  """Collateral ID, first row, row span and whether several markets share it."""
  arrows: list[tuple[int, str]]
  """Row and label of each arrow, drawn across from left to right."""
  footer: str


ROW = 40
BOX = 30


def draw_panel(svg: Svg, y: float, panel: Panel) -> float:
  """Draw `panel` from `y` down; returns where the next panel starts."""
  svg.text(16, y + 22, panel.title, 'title')
  svg.text(16, y + 41, panel.subtitle, 'small muted')
  top = y + 54

  def span(row: int, rows: int) -> tuple[float, float]:
    return top + ROW * row, ROW * (rows - 1) + BOX

  for label, row, rows in panel.markets:
    by, bh = span(row, rows)
    cls = 'spot' if label.startswith('spot') else 'margin'
    svg.box(16, by, 186, bh, cls)
    svg.text(28, by + bh / 2 + 5, label, 'mono')
  for label, row, rows, shared in panel.money:
    by, bh = span(row, rows)
    svg.box(278, by, 186, bh, 'shared' if shared else 'money')
    svg.text(290, by + bh / 2 + 5, label, 'mono')
  for row, label in panel.arrows:
    ay = top + ROW * row + BOX / 2
    svg.line((202, ay), (276, ay), arrow=True)
    if label:
      svg.text(236, ay - 5, label, 'small muted', 'middle')
  rows = max(row + rows for _, row, rows in panel.markets)
  foot = top + ROW * rows + 8
  svg.text(16, foot, panel.footer, 'small')
  return foot + 22


def collateral_ids() -> Svg:
  """How collateral IDs map markets to money on each style of venue."""
  panels = [
    Panel(
      'Separate wallets',
      'Aster, Margin Trade, classic Lighter (account mt)',
      markets=[('spot ETH/USDC', 0, 2), ('perp ETH', 2, 1)],
      money=[
        ('mt:spot:ETH', 0, 1, False),
        ('mt:spot:USDC', 1, 1, False),
        ('mt:perp', 2, 1, False),
      ],
      arrows=[(0, 'base'), (1, 'quote'), (2, '')],
      footer='Two USDC balances, two IDs: spot never spends perp margin.',
    ),
    Panel(
      'Unified account',
      'Hyperliquid, unified Lighter (account hl, USDC is token 0)',
      markets=[('spot UBTC/USDC', 0, 2), ('perp BTC', 2, 1), ('perp xyz:SILVER', 3, 1)],
      money=[('hl:spot:197', 0, 1, False), ('hl:spot:0', 1, 3, True)],
      arrows=[(0, 'base'), (1, 'quote'), (2, ''), (3, '')],
      footer='One USDC balance, one ID: spot and perps share a ledger.',
    ),
    Panel(
      'Subaccount pools',
      'dYdX: each subaccount is its own pool (account dydx)',
      markets=[
        ('perp BTC-USD', 0, 1),
        ('perp ETH-USD', 1, 1),
        ('perp.1 BTC-USD', 2, 1),
      ],
      money=[('dydx:perp', 0, 2, True), ('dydx:perp.1', 2, 1, False)],
      arrows=[(0, ''), (1, ''), (2, '')],
      footer='Each market draws on its own subaccount’s pool.',
    ),
  ]
  svg = Svg(0, 'Collateral IDs: which money each market’s orders spend')
  svg.text(
    16, 28, 'Arrows: collateral_ids() on spot, collateral_id() on perps', 'small muted'
  )
  y = 38.0
  for i, panel in enumerate(panels):
    if i:
      svg.parts.append(
        f'<line x1="16" y1="{y - 6}" x2="464" y2="{y - 6}" class="rule"/>'
      )
    y = draw_panel(svg, y, panel)
  svg.height = int(y)
  return svg


def perp_money() -> Svg:
  """`collateral_id()` funds new orders; `collateral()` is what liquidates."""
  svg = Svg(338, 'collateral_id() versus collateral() on one perpetual')
  svg.box(90, 16, 300, 54, 'margin')
  svg.text(240, 39, 'hl::BTC, isolated 10x', 'mono', 'middle')
  svg.text(240, 59, 'one perpetual, two questions', 'small muted', 'middle')
  svg.line((240, 70), (240, 84))
  svg.line((123, 84), (357, 84))
  columns = [
    (
      16,
      'collateral_id()',
      'What funds new orders?',
      'money',
      'hl:spot:0 (cross USDC)',
      ['sdk.collateral(id)', '.free_collateral', '× leverage()'],
      'sizing and reservations',
    ),
    (
      250,
      'collateral()',
      'How close to liquidation?',
      'margin',
      'BTC’s isolated bucket',
      ['PerpCollateral', '.maintenance_ratio', '.initial_ratio'],
      'also sdk.perp_collateral(id)',
    ),
  ]
  for x, call, question, cls, pool, reads, use in columns:
    cx = x + 107
    svg.line((cx, 84), (cx, 98), arrow=True)
    svg.text(x, 118, call, 'mono title')
    svg.text(x, 137, question, 'small muted')
    svg.box(x, 150, 214, 36, cls)
    svg.text(x + 12, 173, pool, 'small' if cls == 'margin' else 'mono')
    svg.line((cx, 186), (cx, 206), arrow=True)
    svg.box(x, 208, 214, 76, 'market')
    for i, s in enumerate(reads):
      svg.text(x + 12, 230 + 21 * i, s, 'mono')
    svg.text(x, 304, use, 'small muted')
  svg.text(
    16, 326, 'Cross margin: both name the same pool. Isolated: they differ.', 'small'
  )
  return svg


def main():
  """Write every diagram."""
  OUT.mkdir(parents=True, exist_ok=True)
  for name, make in [
    ('market-types', market_types),
    ('collateral-ids', collateral_ids),
    ('perp-collateral', perp_money),
  ]:
    (OUT / f'{name}.svg').write_text(make().render())


if __name__ == '__main__':
  main()
