"""Coinbase's yield-bearing instruments, from the two sources that publish an APR.

Coinbase's App tier has no Earn product API -- no catalogue of subscribable
instruments, no subscribe/redeem endpoints -- so `instruments()` reads the only two
places an APR is actually published:

1. Coinbase Exchange's wrapped-asset catalogue (`CBETH`), which is browsable without
   holding anything and needs no credentials. It names only the wrapped asset, never
   the asset it is staked from, and `redeem_time_estimate_days` is an unwrap delay
   rather than a term, so `duration` stays unset.
2. The `rewards.apy` blob the App tier attaches to a held account's currency. It only
   appears on assets the caller already holds -- there is no way to list what is
   eligible ahead of holding it -- and carries no id, min/max or term.

Neither is the Binance/Bitget-style product list. Coinbase's [Staking
API](https://docs.cdp.coinbase.com/staking/staking-api/introduction/welcome) does
accept this tier's CDP API Key (verified live), but every one of its endpoints is
scoped to an externally-supplied onchain address and none reports APY or a catalogue
independent of one. [USDC Rewards](https://docs.cdp.coinbase.com/wallets/usdc-rewards)
is documented as non-custodial-wallet-only, with custodial support "coming soon".
"""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.core import SDK
from tribulnation.sdk.earn.instruments import (
  Instrument,
  InstrumentTag,
  Instruments as _Instruments,
)

from tribulnation.coinbase.core import Mixin

TAGS: Sequence[InstrumentTag] = ('staking', 'flexible')


@dataclass(frozen=True, kw_only=True)
class Instruments(Mixin, _Instruments):
  """Coinbase's yield-bearing instruments."""

  @SDK.method
  async def held_rewards(self) -> list[Instrument]:
    """Instruments inferred from the rewards blob on the account's own wallets."""
    out: list[Instrument] = []
    seen: set[str] = set()
    for account in await self.app.accounts.list_paged().via(self.call_app):
      currency = account['currency']
      rewards = currency.get('rewards')
      if rewards is None or currency['code'] in seen:
        continue
      seen.add(currency['code'])
      out.append(
        Instrument(tags=list(TAGS), asset=currency['code'], apr=rewards['apy'])
      )
    return out

  @SDK.method
  async def wrapped_assets(self) -> list[Instrument]:
    """Instruments from Coinbase Exchange's public wrapped-asset catalogue.

    The list route omits the per-asset detail the single-asset route carries, so the
    APR is read from `get(id)`; both are unauthenticated.
    """
    catalogue = await self.call_exchange(
      lambda: self.client.exchange.http.wrapped_assets.list()
    )
    out: list[Instrument] = []
    for entry in catalogue['wrapped_assets']:
      detail = await self.call_exchange(
        lambda: self.client.exchange.http.wrapped_assets.get(entry['id'])
      )
      if not detail['apy']:
        continue
      out.append(
        Instrument(
          tags=list(TAGS), asset=detail['id'], apr=detail['apy'], id=detail['id']
        )
      )
    return out

  @SDK.method
  async def instruments(
    self,
    *,
    tags: Collection[InstrumentTag] | None = None,
    assets: Collection[str] | None = None,
  ) -> Sequence[Instrument]:
    """Fetch Coinbase's yield-bearing instruments.

    Partial by construction -- see this module's docstring for what Coinbase does and
    does not publish.
    """
    held = await self.held_rewards()
    out = held + [
      instrument
      for instrument in await self.wrapped_assets()
      if instrument.asset not in {held_instrument.asset for held_instrument in held}
    ]
    if assets is not None:
      out = [instrument for instrument in out if instrument.asset in assets]
    if tags is not None:
      out = [instrument for instrument in out if set(instrument.tags) & set(tags)]
    return out
