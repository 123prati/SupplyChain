# Supply Chain Intelligence Application

A Flask, SQLite, Bootstrap, HTML, CSS, and JavaScript supply chain management system for inventory, suppliers, warehouses, purchase orders, shipments, and demand forecasting.

## Run Locally

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000`.

The SQLite database is created automatically as `supply_chain.db` and seeded with sample operating data.
