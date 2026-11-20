"""
Load raw coin data records in GCS bucket.

Auth: ADC holds your own user credentials (gcloud auth application-default login).
If INGEST_IMPERSONATE_SA is set, the script impersonates that service account;
if it is unset (e.g. on Cloud Composer), it uses the ADC identity directly.

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
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.auth.transport.requests import Request
from google.cloud import storage

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
BUCKET_NAME = os.environ.get("GCS_BUCKET", "your-dev-raw-bucket")
INGEST_IMPERSONATE_SA = os.environ.get("INGEST_IMPERSONATE_SA")

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
GCS_PREFIX = "coingecko/market_chart"
DAILY_DAYS = 3
MAX_UPLOAD_ATTEMPTS = 3


def get_credentials() -> Credentials:
    """Return ADC credentials, impersonating INGEST_IMPERSONATE_SA when it is set.

    Fails fast if ADC is missing/expired or impersonation is denied.
    """
    try:
        credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
        if INGEST_IMPERSONATE_SA:
            credentials = impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=INGEST_IMPERSONATE_SA,
                target_scopes=[CLOUD_PLATFORM_SCOPE],
            )
        # raises if ADC is expired/revoked or impersonation is denied
        credentials.refresh(Request())
    except DefaultCredentialsError:
        sys.exit("No ADC found. Run: gcloud auth application-default login")
    except RefreshError as e:
        sys.exit(
            f"Could not get a token ({e}). If it says invalid_grant, re-run "
            "'gcloud auth application-default login'; if 403, check that your account has "
            "Token Creator on INGEST_IMPERSONATE_SA and that the IAM Service Account "
            "Credentials API is enabled."
        )

    print(f"GCP identity: {getattr(credentials, 'service_account_email', 'ADC user')}")
    return credentials


def check_bucket_access(client: storage.Client, bucket_name: str) -> None:
    """Fail fast, before any API call, if the bucket is missing or not writable."""
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

    print(f"GCS access OK: bucket '{bucket_name}' is writable")


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

    client = storage.Client(project=PROJECT_ID, credentials=get_credentials())
    check_bucket_access(client, BUCKET_NAME)

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
