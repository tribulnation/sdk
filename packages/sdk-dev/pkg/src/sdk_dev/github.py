"""Renders the blocks that exist only for GitHub readers of `docs/`.

`docs/` is read in two places, and each reader is missing something the other has. On
GitHub there is no sidebar, so a page is a dead end unless it links onward, and no
method reference, since that is rendered from the source at sync time. On the site both
are there already. So both blocks are generated into the committed markdown — the
prev/next footer from `docs/docs.yml` (`sdk_dev.nav.reading_order`), and a pointer to
the rendered reference on pages carrying the methods marker — and the site's renderer
strips them again. Nothing here is ever hand-written, so nothing can fall out of step.
"""

from pathlib import Path
from typing_extensions import NamedTuple
import os
import re

from sdk_dev.nav import reading_order
from sdk_dev.reference import METHODS_MARKER

MARKER_START = '<!-- next -->'
MARKER_END = '<!-- /next -->'
BLOCK_RE = re.compile(
  rf'\n*{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}\n*', re.DOTALL
)
GITHUB_START = '<!-- github-only -->'
GITHUB_END = '<!-- /github-only -->'
NOTE_RE = re.compile(
  # The nav bar is a `github-only` block too, so the body may not span another block's
  # start: without that, this would match from the bar down to the note's own end.
  rf'\n*{re.escape(GITHUB_START)}(?:(?!{re.escape(GITHUB_START)}).)*?{re.escape(GITHUB_END)}'
  rf'\n*(?={re.escape(METHODS_MARKER)})',
  re.DOTALL,
)
NAV_RE = re.compile(
  rf'\A{re.escape(GITHUB_START)}.*?{re.escape(GITHUB_END)}\n*', re.DOTALL
)
HOME_LABEL = 'Docs'
"""Bar label for `docs/index.md`, whose own heading names the project rather than a
section."""
SUPPORT_LABEL = 'Support matrix'
"""The support matrix has no page in `docs/`; the bar links the site's."""
TITLE_RE = re.compile(r'^#\s+(.+?)\s*$', re.MULTILINE)
SITE_BASE = 'https://tribulnation.com/sdk/docs'
"""Where the rendered docs live, for the pointer left on GitHub."""


class Page(NamedTuple):
  """One page of the reading order, as a footer link."""

  path: Path
  """Path relative to `docs/`."""
  title: str
  """The page's `#` heading."""


def render_pages(docs_dir: Path) -> dict[Path, str]:
  """
  The full text every page under `docs_dir` should have, generated blocks included.

  Args:
    docs_dir: The sdk repo's `docs/` directory.

  Returns:
    `{path relative to docs_dir: text}`, in reading order.
  """
  pages = [Page(path, page_title(docs_dir / path)) for path in reading_order(docs_dir)]
  sections = nav_sections(pages)
  rendered: dict[Path, str] = {}
  for i, page in enumerate(pages):
    footer = render_footer(
      page,
      prev=pages[i - 1] if i > 0 else None,
      next=pages[i + 1] if i + 1 < len(pages) else None,
    )
    text = apply_note(
      BLOCK_RE.sub('\n\n', (docs_dir / page.path).read_text()), page.path
    )
    body = apply_nav(text, page.path, sections).rstrip()
    rendered[page.path] = f'{body}\n\n{footer}\n' if footer else f'{body}\n'
  return rendered


def stale_pages(docs_dir: Path) -> list[Path]:
  """Pages whose generated blocks are out of date, in reading order."""
  return [
    path
    for path, text in render_pages(docs_dir).items()
    if (docs_dir / path).read_text() != text
  ]


def write_pages(docs_dir: Path) -> list[Path]:
  """Rewrite every stale page under `docs_dir`. Returns the pages changed."""
  changed = []
  for path, text in render_pages(docs_dir).items():
    if (docs_dir / path).read_text() != text:
      (docs_dir / path).write_text(text)
      changed.append(path)
  return changed


def nav_sections(pages: list[Page]) -> list[Page]:
  """
  The bar's entries: the docs home, then each top-level section's index page.

  Labelled by that index page's own heading, so the bar follows `docs.yml` with no
  labels of its own to keep in step — only home is named here, its heading being the
  project's name rather than a section's.
  """
  entries = [Page(Path('index.md'), HOME_LABEL)]
  entries += [
    page for page in pages if page.path.name == 'index.md' and len(page.path.parts) == 2
  ]
  return entries


def apply_nav(text: str, path: Path, sections: list[Page]) -> str:
  """
  Put the section bar at the top of the page, above its heading.

  GitHub has no sidebar, so this is the only way across sections there — the prev/next
  footer only walks the reading order. A table renders as a bar rather than as a
  sentence, and the current section is bold rather than linked, which is about as much
  styling as GitHub's markdown sanitizer allows.
  """
  cells = [f'<td align="center">{nav_cell(path, section)}</td>' for section in sections]
  cells.append(
    f'<td align="center"><a href="{SITE_BASE}/support">{SUPPORT_LABEL}</a></td>'
  )
  bar = '<table><tr>\n' + '\n'.join(cells) + '\n</tr></table>'
  return f'{GITHUB_START}\n{bar}\n{GITHUB_END}\n\n{NAV_RE.sub("", text).lstrip()}'


def nav_cell(path: Path, section: Page) -> str:
  """One cell: bold for the section the page is in, a relative link otherwise."""
  if _section(path) == _section(section.path):
    return f'<b>{section.title}</b>'
  return f'<a href="{relative_href(path, section.path)}">{section.title}</a>'


def apply_note(text: str, path: Path) -> str:
  """
  Put the pointer to the rendered method reference in front of the methods marker.

  A page whose body is mostly `<!-- methods -->` reads as an empty stub on GitHub, where
  nothing expands it. Pages without the marker are left alone.
  """
  if METHODS_MARKER not in text:
    return text
  note = (
    f'{GITHUB_START}\n\n'
    '> The method reference is generated from the source, so it only appears on the docs\n'
    f'> site: [{site_url(path, scheme=False)}]({site_url(path)}).\n\n'
    f'{GITHUB_END}\n'
  )
  return NOTE_RE.sub('\n\n', text).replace(METHODS_MARKER, note + METHODS_MARKER, 1)


def site_url(path: Path, *, scheme: bool = True) -> str:
  """The page's URL on the docs site, from its path under `docs/`."""
  stem = path.with_suffix('')
  route = '' if stem.name == 'index' else f'/{stem.as_posix()}'
  base = SITE_BASE if scheme else SITE_BASE.removeprefix('https://')
  return f'{base}{route}'


def render_footer(page: Page, *, prev: Page | None, next: Page | None) -> str:
  """The footer block for one page, or `''` when it is the only page."""
  links = []
  if prev is not None:
    links.append(f'← [{link_title(page, prev)}]({relative_href(page.path, prev.path)})')
  if next is not None:
    links.append(
      f'**Next:** [{link_title(page, next)}]({relative_href(page.path, next.path)}) →'
    )
  if not links:
    return ''
  return f'{MARKER_START}\n\n---\n\n{" · ".join(links)}\n\n{MARKER_END}'


def link_title(page: Page, target: Page) -> str:
  """
  The target's own title, qualified by its section when the link leaves the current one.

  A bare "Methods" is meaningless as the last link of the Earn section, where the next
  page is Wallet's; "Earn Methods" is not. The docs site shows the same thing as the
  section kicker above each pager card.
  """
  section = _section(target.path)
  if section is None or section == _section(page.path):
    return target.title
  label = section.replace('-', ' ').title()
  return (
    target.title if label.lower() in target.title.lower() else f'{label} {target.title}'
  )


def _section(path: Path) -> str | None:
  """The top-level directory a page sits in, or `None` for a page at the root."""
  return path.parts[0] if len(path.parts) > 1 else None


def relative_href(source: Path, target: Path) -> str:
  """Link from one page to another, both relative to `docs/`."""
  return os.path.relpath(target, source.parent).replace(os.sep, '/')


def page_title(path: Path) -> str:
  """
  The page's `#` heading, falling back to its filename when it has none.

  Matches the docs site's own title extraction, so a footer link reads the same as the
  sidebar entry it points at.
  """
  match = TITLE_RE.search(path.read_text())
  if match:
    return match.group(1)
  stem = path.parent.name if path.stem == 'index' else path.stem
  return stem.replace('-', ' ').title()
