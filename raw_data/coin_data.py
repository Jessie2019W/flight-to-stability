"""
Extract raw market_chart data for every coin in coin_list.csv.

Usage:
    uv run --env-file .env python raw_data/coin_data.py
"""

import csv
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE_URL = "https://api.coingecko.com/api/v3"
API_KEY_ENV = "AIRFLOW_VAR_COINGECKO_API_KEY"
TIMEOUT_SECONDS = 30
COIN_LIST_PATH = Path(__file__).parent / "coin_list.csv"

DEFAULT_DAYS = 3  # Demo API only serves ~365 days of history
MAX_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 30  # used when a 429 carries no Retry-After header
REQUEST_INTERVAL_SECONDS = 2  # stay well under the Demo rate limit


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set; see .env.example")
    return key


def load_coin_ids(path: Path = COIN_LIST_PATH) -> list[str]:
    with path.open(newline="", encoding="utf-8") as f:
        return [row["coin_id"] for row in csv.DictReader(f)]


def get_coin_data(session: requests.Session, coin_id: str, days: int) -> dict:
    params = {
        "vs_currency": "usd",
        "days": days,
        "interval": "daily",
    }
    url = f"{BASE_URL}/coins/{coin_id}/market_chart"
    for attempt in range(1, MAX_RETRIES + 1):
        response = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if response.status_code == 429 and attempt < MAX_RETRIES:
            wait = int(response.headers.get("Retry-After", DEFAULT_BACKOFF_SECONDS))
            print(
                f"{coin_id}: rate limited, retrying in {wait}s ({attempt}/{MAX_RETRIES})"
            )
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"{coin_id}: no response after {MAX_RETRIES} attempts")


def build_coin_data(coin_id: str, days: int, payload: dict) -> dict:
    """Wrap the untouched API response with the metadata the raw layer needs."""
    return {
        "coin_id": coin_id,
        "extracted_at": datetime.now(UTC).isoformat(),
        "request_params": {
            "vs_currency": "usd",
            "days": days,
            "interval": "daily",
        },  # same as get_coin_data params
        "payload": payload,
    }


def fetch_all(session: requests.Session, coin_ids: list[str], days: int) -> list[dict]:
    records = []
    for i, coin_id in enumerate(coin_ids):
        if i != 0:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        payload = get_coin_data(session, coin_id, days)
        records.append(build_coin_data(coin_id, days, payload))
        print(
            f"{coin_id}: {len(payload['prices'])} daily points. The last point is the real-time price CoinGecko API provides by default."
        )
    return records


def main() -> None:
    session = requests.Session()
    session.headers["x-cg-demo-api-key"] = get_api_key()
    records = fetch_all(session, load_coin_ids(), DEFAULT_DAYS)
    print(f"{len(records)} coins fetched.")


if __name__ == "__main__":
    main()
