"""
Load raw coin data records in GCS bucket.

Auth is ADC (gcloud auth application-default login --impersonate-service-account=...).

Usage:
    uv run --env-file .env python raw_data/load_to_gcs.py   # daily, 3 days
    uv run --env-file .env python raw_data/load_to_gcs.py --days 365 --run-type backfill
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

import google.auth
import requests
from coin_data import fetch_all, get_api_key, load_coin_ids
from google.api_core.exceptions import Forbidden, GoogleAPICallError, NotFound
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.auth.transport.requests import Request
from google.cloud import storage

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
BUCKET_NAME = os.environ.get("GCS_BUCKET", "your-dev-raw-bucket")

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
GCS_PREFIX = "coingecko/market_chart"
DAILY_DAYS = 3
MAX_UPLOAD_ATTEMPTS = 3


def check_gcp_access(client: storage.Client, bucket_name: str) -> None:
    """Fail fast, before any API call, if ADC is missing/expired or the bucket is not writable."""
    try:
        # impersonated ADC needs explicit scopes, otherwise generateAccessToken returns 400
        credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
        credentials.refresh(
            Request()
        )  # raises if ADC is expired/revoked or impersonation is denied
    except DefaultCredentialsError:
        sys.exit(
            "No ADC found. Run: gcloud auth application-default login --impersonate-service-account=<SERVICE_ACCOUNT_EMAIL>"
        )
    except RefreshError as e:
        sys.exit(
            f"Could not get a token from ADC ({e}). If it says invalid_grant, re-run the gcloud ADC "
            "login command; if 403, check Token Creator on the service account and that the "
            "IAM Service Account Credentials API is enabled."
        )

    try:
        granted = client.bucket(bucket_name).test_iam_permissions(
            ["storage.objects.create"]
        )
    except NotFound:
        sys.exit(
            f"Bucket '{bucket_name}' not found. Check GCS_BUCKET and GCP_PROJECT_ID."
        )
    except Forbidden as e:
        sys.exit(
            f"Cannot reach bucket '{bucket_name}' ({e}). Check the service account's IAM roles."
        )
    if "storage.objects.create" not in granted:
        sys.exit(
            f"No write permission on bucket '{bucket_name}'. Grant roles/storage.objectUser."
        )

    print(
        f"GCP access OK: identity={getattr(credentials, 'service_account_email', 'user')}"
    )


def build_blob_path(ingest_date: str, run_type: str, coin_id: str) -> str:
    return f"{GCS_PREFIX}/ingest_date={ingest_date}/run_type={run_type}/{coin_id}.json"


def upload_to_gcs(
    client: storage.Client, bucket_name: str, records: list[dict], run_type: str
) -> list[str]:
    """Write JSON file per coin; returns the gs:// URIs.

    Each upload is verified with exists() and retried up to MAX_UPLOAD_ATTEMPTS times.
    Re-running on the same day with the same run_type overwrites the same files.
    """
    ingest_date = datetime.now(UTC).date().isoformat()
    bucket = client.bucket(bucket_name)
    uris = []
    for record in records:
        blob_path = build_blob_path(ingest_date, run_type, record["coin_id"])
        uri = f"gs://{bucket_name}/{blob_path}"
        # _source_uri is stored in the file so a later BigQuery row can be traced back to it
        line = json.dumps({**record, "_source_uri": uri})
        blob = storage.Blob(bucket=bucket, name=blob_path)
        for attempt in range(1, MAX_UPLOAD_ATTEMPTS + 1):
            try:
                blob.upload_from_string(line, content_type="application/json")
                if blob.exists(client):
                    break  # upload verified, out of retry loop
                print(
                    f"{uri}: not found after upload ({attempt}/{MAX_UPLOAD_ATTEMPTS})"
                )
            except GoogleAPICallError as e:  # network or GCS service error
                print(f"{uri}: upload failed ({attempt}/{MAX_UPLOAD_ATTEMPTS}): {e}")
        else:  # failed all attempts
            raise RuntimeError(
                f"{uri}: upload not confirmed after {MAX_UPLOAD_ATTEMPTS} attempts"
            )
        uris.append(uri)
        print(f"Uploaded {uri}")
    return uris


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load raw coin data records in GCS bucket."
    )
    parser.add_argument(
        "--days", type=int, default=DAILY_DAYS, help="days of history to fetch"
    )
    parser.add_argument("--run-type", choices=["daily", "backfill"], default="daily")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    client = storage.Client(project=PROJECT_ID)
    check_gcp_access(client, BUCKET_NAME)

    session = requests.Session()
    session.headers["x-cg-demo-api-key"] = get_api_key()
    records = fetch_all(
        session, load_coin_ids(), args.days
    )  # get data from CoinGecko API
    print(
        f"Fetched data for {len(records)} coins from CoinGecko API for {args.days} days."
    )

    uris = upload_to_gcs(client, BUCKET_NAME, records, args.run_type)
    print(f"{len(uris)} files uploaded to gs://{BUCKET_NAME}/{GCS_PREFIX}/")


if __name__ == "__main__":
    main()
