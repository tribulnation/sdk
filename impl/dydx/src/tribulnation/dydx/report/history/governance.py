from typing_extensions import Any
from dataclasses import dataclass
import asyncio
from datetime import datetime
from decimal import Decimal
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from tribulnation.sdk.reporting import Record, Yield, source_id
from tribulnation.dydx.core import parse_denom_amount
from dydx import Dydx
from dydx.chain.comet.types import BlockResultsResponse, Event
from .window import in_window

GOVERNANCE_API_URL = 'https://dydx-dao-api.polkachu.com'

def proposal_amount(coin: dict) -> tuple[str, Decimal] | None:
  """Convert a proposal coin object into asset and amount."""
  denom = coin.get('denom')
  amount = coin.get('amount')
  if denom is None or amount is None:
    return None
  denom_str = str(denom)
  return parse_denom_amount(denom_str, int(amount))

@dataclass
class GovernanceHistory:
  """Governance-backed dYdX history methods."""
  address: str

  async def history(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> list[Record]:
    """Collect Community Treasury distributions from governance proposals."""
    proposals = await self.governance_proposals()
    records: list[Record] = []
    for proposal in proposals:
      record = self.parse_governance_proposal(proposal)
      if record is not None:
        observations = [
          observation
          for observation in record.observations
          if in_window(observation.time, start=start, end=end)
        ]
        if observations:
          records.append(record.model_copy(update={'observations': observations}))
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

  def parse_governance_proposal(self, proposal: dict[str, Any]) -> Record | None:
    """Convert one governance proposal into a Community Treasury yield record."""
    status = proposal.get('status')
    if status not in {'PROPOSAL_STATUS_PASSED', '3'}:
      return None
    time = self.governance_proposal_time(proposal)
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
        return datetime.fromisoformat(str(value))
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
