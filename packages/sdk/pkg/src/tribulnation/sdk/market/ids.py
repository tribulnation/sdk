"""Parse qualified exchange and market IDs, the strings `TradingMarkets` routes by.

A qualified exchange ID is `<account_id>:<exchange_id>` and a qualified market ID is
`<account_id>:<exchange_id>:<market_id>`. The exchange ID may be empty (a venue's
default exchange, e.g. `hl:` or `hl::BTC`), and the market ID may itself contain colons
(e.g. `hl:spot:PURR/USDC:0`).
"""

from dataclasses import dataclass

from typing_extensions import Self


@dataclass(frozen=True)
class QualifiedExchangeId:
  """An exchange ID qualified by the account it is opened under.

  Examples:
    >>> QualifiedExchangeId.parse('hl:spot').account_id
    'hl'
  """

  account_id: str
  """Account key, the first segment; never empty"""
  exchange_id: str
  """Exchange ID within the venue; empty for the venue's default exchange"""

  def __post_init__(self):
    """Reject an empty account or a colon in either segment."""
    if not self.account_id or ':' in self.account_id or ':' in self.exchange_id:
      raise ValueError(f'Expected "<account_id>:<exchange_id>", got {self.id!r}.')

  @classmethod
  def parse(cls, id: str, /) -> Self:
    """Split `<account_id>:<exchange_id>`.

    Raises:
      ValueError: The account segment is missing, or there are not exactly two
        segments.
    """
    parts = id.split(':')
    if len(parts) != 2:
      raise ValueError(f'Expected "<account_id>:<exchange_id>", got {id!r}.')
    account_id, exchange_id = parts
    return cls(account_id=account_id, exchange_id=exchange_id)

  @property
  def id(self) -> str:
    """The qualified ID, `<account_id>:<exchange_id>`."""
    return f'{self.account_id}:{self.exchange_id}'


@dataclass(frozen=True)
class QualifiedMarketId:
  """A market ID qualified by its account and exchange.

  Examples:
    >>> QualifiedMarketId.parse('hl:spot:PURR/USDC:0').market_id
    'PURR/USDC:0'
    >>> QualifiedMarketId.parse('hl::BTC').exchange.id
    'hl:'
  """

  account_id: str
  """Account key, the first segment; never empty"""
  exchange_id: str
  """Exchange ID within the venue; empty for the venue's default exchange"""
  market_id: str
  """Venue-native market ID, the rest of the ID; never empty, may contain colons"""

  def __post_init__(self):
    """Reject an empty account or market, or a colon in the account or exchange."""
    if (
      not self.account_id
      or not self.market_id
      or ':' in self.account_id
      or ':' in self.exchange_id
    ):
      raise ValueError(
        f'Expected "<account_id>:<exchange_id>:<market_id>", got {self.id!r}.'
      )

  @classmethod
  def parse(cls, id: str, /) -> Self:
    """Split `<account_id>:<exchange_id>:<market_id>` at its first two colons.

    Raises:
      ValueError: The account or market segment is missing.
    """
    parts = id.split(':', 2)
    if len(parts) != 3:
      raise ValueError(
        f'Expected "<account_id>:<exchange_id>:<market_id>", got {id!r}.'
      )
    account_id, exchange_id, market_id = parts
    return cls(account_id=account_id, exchange_id=exchange_id, market_id=market_id)

  @property
  def exchange(self) -> QualifiedExchangeId:
    """The market's exchange, `<account_id>:<exchange_id>`."""
    return QualifiedExchangeId(account_id=self.account_id, exchange_id=self.exchange_id)

  @property
  def id(self) -> str:
    """The qualified ID, `<account_id>:<exchange_id>:<market_id>`."""
    return f'{self.account_id}:{self.exchange_id}:{self.market_id}'
