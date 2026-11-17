# Flight to Stability

An ELT data pipeline built with Python, dbt (BigQuery) and Airflow. It collects crypto data every day and uses it to study how big drops in major crypto assets relate to trading volume in stablecoins.

## Research question

When the major crypto assets drop hard, do people move money into stablecoins (USDT and USDC)? How big is the move, how fast does it show up?

We break this into three questions that can be answered with numbers:

1. **Correlation.** What is the correlation between the daily return of the major crypto and the abnormal trading volume of stablecoins?
2. **Event effect.** On days when the crypto falls by more than a set threshold (a "drawdown event day"), how much higher is stablecoin abnormal volume than on normal days? Is the difference statistically significant?
3. **Lag and robustness.** Does the effect show up on the same day (t), the next day (t+1), or two days later (t+2)? Do the results stay the same with different thresholds?

## Data

- **Source:** [CoinGecko API](https://docs.coingecko.com/demo/reference/endpoint-overview)
- **Coins:** large non-stablecoins (wrapped and liquid staking tokens excluded), plus USDT and USDC.
- **Timezone:** all dates are in UTC.
