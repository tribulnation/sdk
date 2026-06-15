"""Governance-backed dYdX reporting history."""

from typing_extensions import Any
import asyncio
from datetime import datetime
from decimal import Decimal
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from tribulnation.sdk.reporting import Record, Yield, source_id
from dydx import Dydx
from dydx.chain.comet.types import BlockResultsResponse, Event
from .coins import asset_symbol, denom_quantums
from .comet import event_attributes
from .constants import COMMUNITY_TREASURY_PROPOSAL_HEIGHTS, GOVERNANCE_API_URL
from .time import in_window, parse_time

def proposal_amount(coin: dict[str, object]) -> tuple[str, Decimal] | None:
  """Convert a proposal coin object into asset and amount."""
  denom = coin.get('denom')
  amount = coin.get('amount')
  if denom is None or amount is None:
    return None
  denom_str = str(denom)
  return asset_symbol(denom_str), Decimal(str(amount)) / denom_quantums(denom_str)

class GovernanceHistory:
  """Governance-backed dYdX history methods."""
  address: str
  client: Dydx

  async def governance_community_treasury_distributions(
    self, *, start: datetime | None, end: datetime | None,
  ) -> list[Record]:
    """Collect Community Treasury distributions from governance proposals."""
    proposals = await self.governance_proposals()
    records: list[Record] = []
    for proposal in proposals:
      record = self.parse_governance_proposal(proposal, start=start, end=end)
      proposal_id = self.proposal_id(proposal)
      if record is not None and await self.confirm_governance_proposal(proposal_id):
        records.append(record)
    return records

  async def governance_proposals(self) -> list[dict[str, Any]]:
    """Fetch dYdX governance proposals from the public DAO REST API."""
    proposals: list[dict[str, Any]] = []
    next_key: str | None = None
    while True:
      params = {'pagination.limit': '100'}
      if next_key is not None:
        params['pagination.key'] = next_key
      payload = await self.governance_json('/cosmos/gov/v1/proposals', params=params)
      page = payload.get('proposals', [])
      if isinstance(page, list):
        proposals.extend([item for item in page if isinstance(item, dict)])
      pagination = payload.get('pagination')
      if not isinstance(pagination, dict):
        break
      raw_next_key = pagination.get('next_key')
      if not raw_next_key:
        break
      next_key = str(raw_next_key)
    return proposals

  async def governance_json(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
    """Fetch one governance REST JSON payload."""
    query = urlencode(params)
    url = f'{GOVERNANCE_API_URL}{path}?{query}'
    def fetch() -> dict[str, Any]:
      """Run the blocking REST call in a worker thread."""
      with urlopen(url) as response:
        payload = json.loads(response.read().decode())
      if not isinstance(payload, dict):
        raise ValueError(f'Expected governance JSON object from {url}.')
      return payload
    return await asyncio.to_thread(fetch)

  def parse_governance_proposal(
    self,
    proposal: dict[str, Any],
    *,
    start: datetime | None,
    end: datetime | None,
  ) -> Record | None:
    """Convert one governance proposal into a Community Treasury yield record."""
    status = proposal.get('status')
    if status not in {'PROPOSAL_STATUS_PASSED', '3'}:
      return None
    time = self.governance_proposal_time(proposal)
    if time is not None and not in_window(time, start=start, end=end):
      return None
    proposal_id = self.proposal_id(proposal)
    observations: list[Yield] = []
    for message_index, message in enumerate(self.proposal_messages(proposal)):
      if message.get('@type') != '/dydxprotocol.sending.MsgSendFromModuleToAccount':
        continue
      if message.get('sender_module_name') not in {'community_treasury', None}:
        continue
      if message.get('recipient') != self.address:
        continue
      for coin_index, coin in enumerate(self.message_coins(message)):
        parsed = proposal_amount(coin)
        if parsed is None:
          continue
        asset, amount = parsed
        observations.append(Yield(
          id=f'gov:{proposal_id}:{message_index}:{coin_index}',
          time=time,
          asset=asset,
          amount=amount,
        ))
    if not observations:
      return None
    return Record(
      observations=observations,
      provenance={'source': 'api', 'service': 'dydx', 'id': source_id('dydx')},
    )

  async def confirm_governance_proposal(self, proposal_id: str) -> bool:
    """Confirm known Community Treasury proposal execution with Comet block results."""
    height = COMMUNITY_TREASURY_PROPOSAL_HEIGHTS.get(proposal_id)
    if height is None:
      return True
    results = await self.client.chain.comet.block_results(height)
    return self.block_results_has_active_proposal(results, proposal_id=proposal_id)

  def block_results_has_active_proposal(
    self, results: BlockResultsResponse, *, proposal_id: str,
  ) -> bool:
    """Return whether block results include the active proposal execution event."""
    for event in self.block_result_events(results):
      if event['type'] != 'active_proposal':
        continue
      attributes = event_attributes(event)
      if attributes.get('proposal_id') == proposal_id:
        return True
    return False

  def block_result_events(self, results: BlockResultsResponse) -> list[Event]:
    """Return all events available in Comet block results."""
    events = list(results.get('finalize_block_events') or [])
    for tx_result in results.get('txs_results') or []:
      events.extend(tx_result.get('events', []))
    return events

  def governance_proposal_time(self, proposal: dict[str, Any]) -> datetime | None:
    """Return the best available execution proxy timestamp for a proposal."""
    for key in ('voting_end_time', 'submit_time'):
      value = proposal.get(key)
      if value is not None:
        return parse_time(str(value))
    return None

  def proposal_id(self, proposal: dict[str, Any]) -> str:
    """Return the stable proposal identifier."""
    return str(proposal.get('id') or proposal.get('proposal_id') or 'unknown')

  def proposal_messages(self, proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """Return proposal messages from either Cosmos gov response shape."""
    messages = proposal.get('messages')
    if isinstance(messages, list):
      return [item for item in messages if isinstance(item, dict)]
    content = proposal.get('content')
    if isinstance(content, dict):
      nested = content.get('messages')
      if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    return []

  def message_coins(self, message: dict[str, Any]) -> list[dict[str, object]]:
    """Return coin objects from a governance send message."""
    amount = message.get('amount') or message.get('coins') or message.get('coin')
    if isinstance(amount, list):
      return [item for item in amount if isinstance(item, dict)]
    if isinstance(amount, dict):
      return [amount]
    return []
