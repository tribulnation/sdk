from decimal import Decimal
from typing_extensions import Sequence

from trading_sdk.core import SDK
from trading_sdk.wallet.deposit_methods import (
    DepositMethod,
    DepositMethods as _DepositMethods,
)
from kraken_sdk.core import SdkMixin


def _parse_deposit_method(asset: str, raw: dict) -> DepositMethod:
    """Parse one Kraken deposit method result into DepositMethod."""
    network = raw.get("method") or ""
    fee_str = raw.get("fee") or raw.get("address-setup-fee") or "0"
    fee = DepositMethod.Fee(asset=asset, amount=Decimal(str(fee_str)))
    return DepositMethod(
        asset=asset,
        network=network,
        fee=fee,
        contract_address=None,
        min_confirmations=None,
    )


class DepositMethods(SdkMixin, _DepositMethods):
    @SDK.method
    async def _fetch_assets(self) -> dict:
        """Fetch asset info from Kraken. Returns raw API response."""
        return await self.client.public_get_assets()

    @SDK.method
    async def _fetch_deposit_methods_for_asset(self, asset: str) -> dict:
        """Fetch deposit methods for a single asset. Returns raw API response."""
        return await self.client.private_post_depositmethods({"asset": asset})

    async def deposit_methods(
        self,
        *,
        assets: Sequence[str] | None = None,
    ) -> Sequence[DepositMethod]:
        r = await self._fetch_assets()
        if r.get("error"):
            raise RuntimeError(f"Kraken API error: {r['error']}")
        result = r.get("result") or {}
        asset_codes = list(result.keys()) if isinstance(result, dict) else result
        if assets is not None:
            assets_set = set(assets)
            asset_codes = [a for a in asset_codes if a in assets_set]

        out: list[DepositMethod] = []
        for asset in asset_codes:
            dm_r = await self._fetch_deposit_methods_for_asset(asset)
            if dm_r.get("error"):
                continue
            items = dm_r.get("result") or []
            for item in items:
                if isinstance(item, dict):
                    out.append(_parse_deposit_method(asset, item))
        return out
