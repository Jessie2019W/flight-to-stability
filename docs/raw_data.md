# Raw Data

This part of the project gets daily data from the CoinGecko API and load it in GCS & BigQuery, so it can be cleaned and modeled later in dbt.

For each coin, we collect three daily values: price, market cap and trading volume.

## Flow

1. **Pick the coins.** Take the top 10 non-stablecoins by market cap (wrapped and liquid staking tokens excluded) labled as "risk", then add USDT and USDC, labled as "stablecoin". This is done once, and the list is saved as `coin_list.csv`.
2. **Get the data.** Call CoinGecko for each coin. A daily run pulls the last 3 days, because CoinGecko can revise recent data. A backfill pulls 365 days, the most the Demo API gives. 
3. **Save to GCS.** Each coin is saved as one JSON file, organized by ingest date and run type. Running again on the same day overwrites the same files.
4. **Read in BigQuery.** An external table in `raw_dev` reads the GCS files directly, so BigQuery can query the raw data without copying it.

Once `coin_list.csv` exists, running `load_to_gcs.py` is enough. It gets the data from CoinGecko and loads it to GCS. The data can then be queried through the external table in the BigQuery dataset `raw_dev`.

```
CoinGecko API -> GCS (JSON files) -> BigQuery external table
```
