"""Internal transfer model validation tests."""

import pydantic
import pytest

from tribulnation.sdk.reporting import InternalTransfer


def test_internal_transfer_rejects_negative_amount() -> None:
  with pytest.raises(pydantic.ValidationError):
    InternalTransfer(asset='USDT', amount=-1)
