"""
One-off script: generate the frozen coin list
Usage:
    uv run --env-file .env python raw_data/coin_list.py
"""

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE_URL = "https://api.coingecko.com/api/v3"
API_KEY_ENV = "AIRFLOW_VAR_COINGECKO_API_KEY"
TIMEOUT_SECONDS = 30

# category ids: confirmed against CoinGecko /coins/categories/list
EXCLUDED_CATEGORIES = [
    "stablecoins",
    "wrapped-tokens",
    "liquid-staking",
    "liquid-staking-tokens",
    "tokenized-products",
]
STABLECOINS = [("tether", "usdt"), ("usd-coin", "usdc")]
TOP_N = 10
OUTPUT_PATH = Path(__file__).parent / "coin_list.csv"


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set; see .env.example")
    return key


def get_coin_list(session: requests.Session, category: str | None = None) -> list[dict]:
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 50,
        "page": 1,
    }
    if category:
        params["category"] = category
    response = session.get(
        f"{BASE_URL}/coins/markets", params=params, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def build_coin_list(session: requests.Session) -> list[dict]:
    excluded_ids = set()
    for category in EXCLUDED_CATEGORIES:
        excluded_ids.update(coin["id"] for coin in get_coin_list(session, category))

    selected_at = datetime.now(UTC).date().isoformat()
    basis = "market cap rank on selected_at; excl. stablecoins, wrapped, liquid staking tokens"

    risk_coins = [
        coin for coin in get_coin_list(session) if coin["id"] not in excluded_ids
    ][:TOP_N]
    if len(risk_coins) < TOP_N:
        raise RuntimeError(
            f"Only {len(risk_coins)} coins left after exclusion, expected {TOP_N}. Please increase per_page at get_coin_list function or check excluded categories."
        )

    rows = [
        {
            "coin_id": coin["id"],
            "symbol": coin["symbol"],
            "asset_class": "risk",
            "selected_at": selected_at,
            "selection_basis": basis,
        }
        for coin in risk_coins
    ]
    rows += [
        {
            "coin_id": coin_id,
            "symbol": symbol,
            "asset_class": "stablecoin",
            "selected_at": selected_at,
            "selection_basis": "fixed: major stablecoins",
        }
        for coin_id, symbol in STABLECOINS
    ]
    return rows


def main() -> None:
    session = requests.Session()
    session.headers["x-cg-demo-api-key"] = get_api_key()
    rows = build_coin_list(session)
    print(f"{len(rows)} coins selected.\ncoins: {[row['symbol'] for row in rows]}")

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
