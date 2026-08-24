import pytest

from src.api.historical_client import HistoricalDataClient, HistoricalDataClientError


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, url: str, timeout: float) -> FakeResponse:
        del url, timeout
        return FakeResponse(self.text)


def test_historical_client_rejects_missing_required_columns() -> None:
    client = HistoricalDataClient(
        "https://example.test/data/",
        session=FakeSession("first_name,second_name\nMartin,Odegaard\n"),
    )

    with pytest.raises(HistoricalDataClientError):
        client.get_cleaned_players("2025-26")


def test_historical_client_rejects_invalid_season_path() -> None:
    client = HistoricalDataClient(
        "https://example.test/data/",
        session=FakeSession(""),
    )

    with pytest.raises(ValueError):
        client.get_cleaned_players("../../secret")
