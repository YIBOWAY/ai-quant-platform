from fastapi import HTTPException

from quant_system.api.errors import provider_unavailable_400
from quant_system.data.provider_factory import DataProviderUnavailableError


def test_provider_unavailable_400_builds_standard_detail() -> None:
    exc = DataProviderUnavailableError("tiingo", "missing token")

    response = provider_unavailable_400(exc)

    assert isinstance(response, HTTPException)
    assert response.status_code == 400
    assert response.detail == {
        "code": "provider_unavailable",
        "provider": "tiingo",
        "message": "tiingo provider unavailable: missing token",
    }
