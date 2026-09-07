"""Bit2Me implementation of the `withdrawal_methods` wallet endpoint."""

from typing_extensions import Any, Collection, Literal, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
import logging

from tribulnation.sdk.core import SDK, ApiError, AuthError
from tribulnation.sdk.wallet.withdrawal_methods import (
  WithdrawalMethod,
  WithdrawalMethods as _WithdrawalMethods,
)

from .networks import Networks

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class WithdrawalMethods(_WithdrawalMethods, Networks):
  """Bit2Me implementation of `WithdrawalMethods`.

  Bit2Me publishes no static withdrawal-fee schedule -- no asset or network field
  carries one, and no endpoint serves one. The only place a real fee appears is
  `POST /v1/wallet/transaction/proforma`, which quotes one withdrawal of a real
  amount to a real destination address. Even a `not-enough-funds` rejection still
  reports the fee it computed, so quoting does not need the account funded, but it
  does need an address on the target network, and nothing in the API vends one.

  So fees are opt-in: configure `quote_addresses` with one destination address per
  network and every method on those networks comes back with its real fee; leave it
  empty and the enumeration is still complete, with `fee=None` throughout. The fee is
  charged in the asset being withdrawn, not in the network's `feeCurrencyCode` gas
  token -- a USDT-on-BSC withdrawal is billed 0.3 USDT, not 0.3 BNB.

  Quoting needs an API key holding the wallet-withdrawal permission. A key without it
  gets `403 invalid credentials` from the proforma; that costs the fees, not the
  method list, and is reported through a warning naming the unquoted pairs.
  """

  quote_addresses: Mapping[str, str] = field(default_factory=dict[str, str])
  """Destination address to quote fees against, keyed by network id (`tron`,
  `binanceSmartChain`). It must be syntactically valid on that network but is never
  sent anything -- a proforma is a quote, not a transfer. Networks absent here are
  enumerated with `fee=None`."""
  quote_amounts: Mapping[str, str] = field(default_factory=dict[str, str])
  """Amount to quote with, keyed by asset. Only the amount's plausibility matters:
  a quote for more than the balance still reports the fee. Defaults to
  `default_quote_amount`."""
  default_quote_amount: str = '1'
  """Amount to quote with for an asset absent from `quote_amounts`."""

  @SDK.method
  async def withdrawal_fee(
    self, asset: str, *, network: str
  ) -> 'WithdrawalMethod.Fee | Literal["no-permission"] | None':
    """Quote one asset/network withdrawal fee with a proforma.

    Args:
      asset: Asset to withdraw.
      network: Network id to withdraw over.

    Returns:
      The fee; `'no-permission'` when the key may read the catalogues but not quote
      a proforma; `None` when no address for `network` is configured.

    Raises:
      ApiError: Bit2Me rejected the proforma for any reason other than the account
        being unable to cover it, which is the path that still reports a fee.
    """
    address = self.quote_addresses.get(network)
    if address is None:
      return None
    amount = self.quote_amounts.get(asset, self.default_quote_amount)
    try:
      proforma = await self.call_bit2me(
        lambda: self.client.v1.wallet.transactions.preview(
          amount=amount,
          currency=asset,
          destination={'address': address, 'network': network},
        )
      )
      quoted = (proforma.get('fee') or {}).get('network')
      if quoted is None:
        return None
      return WithdrawalMethod.Fee(
        asset=quoted['currency'], amount=Decimal(str(quoted['amount']))
      )
    except AuthError:
      # Caught before `ApiError`, which it subclasses. A 403 here means this key
      # reads both catalogues fine but lacks the wallet-withdrawal permission the
      # proforma needs -- the fee is unknown rather than absent from Bit2Me, so it
      # is reported as such instead of collapsing into an indistinguishable `None`.
      return 'no-permission'
    except ApiError as e:
      # Bit2Me's error bodies vary by endpoint, so the transport passes them through
      # untyped. A `not-enough-funds` body still carries the computed fee; anything
      # else is a real failure.
      if len(e.args) < 2:
        raise
      body: Any = e.args[1]
      data: Any = body.get('data', {}).get('data', {})
      if data.get('code') != 'not-enough-funds':
        raise
      return WithdrawalMethod.Fee(asset=asset, amount=Decimal(str(data['fee'])))

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    pairs = await self.asset_networks(assets=assets, networks=networks)
    out: list[WithdrawalMethod] = []
    unquoted: list[str] = []
    for pair in pairs:
      network = pair.network['id']
      fee = await self.withdrawal_fee(pair.asset, network=network)
      if fee == 'no-permission':
        unquoted.append(f'{pair.asset}/{network}')
        fee = None
      out.append(WithdrawalMethod(asset=pair.asset, network=network, fee=fee))
    if unquoted:
      logger.warning(
        'fee=None on %d/%d Bit2Me withdrawal methods: the proforma answered 403 '
        'invalid credentials, so this API key lacks the wallet-withdrawal permission '
        'a fee quote needs. Unquoted: %s',
        len(unquoted),
        len(out),
        ', '.join(unquoted),
      )
    return out
