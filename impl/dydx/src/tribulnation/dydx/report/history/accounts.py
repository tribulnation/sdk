"""Account label helpers for dYdX reporting history."""

from dydx.indexer.data.get_transfers import Account

def account_label(account: Account) -> str:
  """Format a dYdX account and optional subaccount number."""
  subaccount = account.get('subaccountNumber')
  if subaccount is None:
    return account['address']
  return f'{account["address"]}:{subaccount}'

def is_account(account: Account, *, address: str, subaccount: int) -> bool:
  """Return whether an indexer account points at the requested subaccount."""
  return account['address'] == address and account.get('subaccountNumber') == subaccount

def wallet_account(address: str) -> str:
  """Return a stable wallet account label for staking transfers."""
  return f'dydx:{address}:wallet'

def staking_account(address: str, *, validator: str | None) -> str:
  """Return a stable staking account label for staking transfers."""
  suffix = validator or 'unknown'
  return f'dydx:{address}:staking:{suffix}'

def subaccount_account(address: str, subaccount: str | int | None) -> str:
  """Return a stable subaccount label for chain-derived transfers."""
  suffix = subaccount if subaccount is not None else 'unknown'
  return f'dydx:{address}:{suffix}'

def megavault_account(address: str) -> str:
  """Return a stable Megavault allocation label."""
  return f'dydx:{address}:megavault'
