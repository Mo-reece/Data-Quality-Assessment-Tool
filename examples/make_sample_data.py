"""Generate the synthetic sample files in examples/ (deterministic; no real people)."""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
rng = np.random.default_rng(7)

customers = pd.DataFrame({
    "customer_id": [f"C{i:04d}" for i in range(1, 201)],
    "region": rng.choice(["North", "South", "East", "West"], 200),
})

n = 1000
orders = pd.DataFrame({
    "order_id": np.arange(10001, 10001 + n),
    "customer_id": rng.choice(customers["customer_id"], n),
    "order_date": pd.date_range("2025-01-01", periods=n, freq="8h").strftime("%Y-%m-%d"),
    "email": [f"user{i}@example.com" for i in rng.integers(1, 400, n)],
    "quantity": rng.integers(1, 6, n),
    "unit_price": rng.gamma(2.0, 40.0, n).round(2),
    "status": rng.choice(["shipped", "pending", "delivered", "cancelled"], n, p=[.4, .2, .35, .05]),
})

# Inject the kinds of problems real exports have.
orders.loc[rng.choice(n, 60, replace=False), "email"] = np.nan
orders.loc[rng.choice(n, 15, replace=False), "email"] = "not-an-email"
orders.loc[rng.choice(n, 12, replace=False), "quantity"] = -1
orders.loc[rng.choice(n, 8, replace=False), "unit_price"] = 99999.0
orders.loc[rng.choice(n, 10, replace=False), "order_date"] = "31/02/2025"
orders.loc[rng.choice(n, 5, replace=False), "order_date"] = "2031-01-01"
orders.loc[rng.choice(n, 20, replace=False), "customer_id"] = "C9999"
orders.loc[rng.choice(n, 30, replace=False), "status"] = np.nan
orders = pd.concat([orders, orders.sample(25, random_state=1)], ignore_index=True)  # exact dupes
orders.loc[1010:1014, "order_id"] = orders.loc[0:4, "order_id"].to_numpy()  # reused keys

orders.to_csv(HERE / "orders.csv", index=False)
customers.to_csv(HERE / "customers.csv", index=False)
print(f"wrote {len(orders)} orders and {len(customers)} customers")
