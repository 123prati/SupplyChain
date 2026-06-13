from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename


APP_NAME = "Supply Chain Intelligence Agent"
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
SAMPLE_DATASET = DATA_FOLDER / "supply_chain_data.csv"
ALLOWED_EXTENSIONS = {"csv"}

WRITABLE_DIR = Path(os.environ.get("SUPPLY_CHAIN_WRITABLE_DIR", "/tmp/supply_chain" if os.environ.get("VERCEL") else BASE_DIR))
DATABASE = WRITABLE_DIR / "supply_chain.db"
UPLOAD_FOLDER = WRITABLE_DIR / "uploads"
REPORT_FOLDER = WRITABLE_DIR / "reports"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

for folder in (WRITABLE_DIR, UPLOAD_FOLDER, REPORT_FOLDER, DATA_FOLDER):
    folder.mkdir(exist_ok=True)


EXPECTED_COLUMNS = [
    "Product_ID",
    "Product_Name",
    "Category",
    "Supplier_Name",
    "Supplier_Rating",
    "Warehouse",
    "Inventory_Level",
    "Reorder_Point",
    "Safety_Stock",
    "Purchase_Cost",
    "Selling_Price",
    "Order_Quantity",
    "Lead_Time_Days",
    "Transportation_Cost",
    "Demand",
    "Monthly_Sales",
    "Fulfillment_Rate",
    "Delivery_Status",
]

NUMERIC_COLUMNS = {
    "Supplier_Rating",
    "Inventory_Level",
    "Reorder_Point",
    "Safety_Stock",
    "Purchase_Cost",
    "Selling_Price",
    "Order_Quantity",
    "Lead_Time_Days",
    "Transportation_Cost",
    "Demand",
    "Monthly_Sales",
    "Fulfillment_Rate",
}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            columns_json TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dataset_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            row_json TEXT NOT NULL,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            analysis_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            recommendations_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


@app.before_request
def before_request() -> None:
    init_db()
    ensure_sample_dataset()
    ensure_default_dataset()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_sample_dataset() -> None:
    if SAMPLE_DATASET.exists():
        return
    rows = [
        ["P-1001", "Industrial Sensor Kit", "Electronics", "Northstar Components", 94, "Chicago DC", 145, 80, 45, 32.5, 58.0, 120, 8, 980, 132, 118, 96, "Delivered"],
        ["P-1002", "Retail Shipping Carton", "Packaging", "Urban Retail Packs", 88, "Phoenix FC", 2400, 600, 300, 1.1, 2.35, 1500, 5, 540, 1650, 1580, 98, "Delivered"],
        ["P-1003", "Hydraulic Pump Assembly", "Industrial", "Global Freight Parts", 72, "Savannah Hub", 14, 20, 10, 241, 389, 35, 16, 1450, 27, 32, 82, "Delayed"],
        ["P-1004", "Temperature Logger", "Electronics", "Northstar Components", 94, "Chicago DC", 63, 70, 35, 19.5, 42.0, 80, 9, 710, 75, 69, 91, "Delivered"],
        ["P-1005", "Medical Grade Gloves", "Healthcare", "PrimeCare Supplies", 91, "Newark WH", 890, 500, 220, 4.2, 7.8, 650, 7, 620, 720, 690, 95, "Delivered"],
        ["P-1006", "Cold Chain Container", "Logistics", "ArcticMove", 78, "Dallas Hub", 28, 35, 15, 86, 142, 45, 13, 1320, 41, 38, 86, "In Transit"],
        ["P-1007", "Barcode Label Roll", "Packaging", "Urban Retail Packs", 88, "Phoenix FC", 5200, 1000, 450, 0.38, 0.82, 2100, 4, 260, 1800, 1550, 97, "Delivered"],
        ["P-1008", "Smart Pallet Tracker", "Electronics", "Metro IoT Systems", 83, "Chicago DC", 37, 55, 25, 52, 89, 70, 11, 1080, 64, 59, 89, "Delayed"],
        ["P-1009", "Forklift Battery", "Warehouse", "PowerGrid Industrial", 80, "Savannah Hub", 19, 12, 6, 310, 475, 15, 12, 860, 13, 15, 93, "Delivered"],
        ["P-1010", "Safety Helmet", "Safety", "PrimeCare Supplies", 91, "Newark WH", 310, 180, 80, 9.5, 18, 260, 6, 430, 285, 275, 96, "Delivered"],
        ["P-1011", "Conveyor Belt Motor", "Warehouse", "Global Freight Parts", 72, "Dallas Hub", 6, 10, 5, 420, 680, 12, 18, 1550, 11, 9, 79, "Delayed"],
        ["P-1012", "Reusable Pallet", "Logistics", "ArcticMove", 78, "Savannah Hub", 760, 300, 120, 14, 26, 520, 10, 1240, 480, 455, 90, "In Transit"],
    ]
    with SAMPLE_DATASET.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(EXPECTED_COLUMNS)
        writer.writerows(rows)


def read_csv_records(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def to_number(value: object, default: float = 0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_records(records: list[dict]) -> list[dict]:
    cleaned = []
    for raw in records:
        normalized = {str(key).strip().replace(" ", "_"): value for key, value in raw.items()}
        row = {}
        for column in EXPECTED_COLUMNS:
            if column in NUMERIC_COLUMNS:
                row[column] = to_number(normalized.get(column), 0)
            else:
                row[column] = str(normalized.get(column) or "Unknown").strip()
        for column, value in normalized.items():
            if column not in row:
                row[column] = value
        cleaned.append(row)
    return cleaned


def save_dataset(records: list[dict], name: str, filename: str, original_filename: str) -> int:
    rows = clean_records(records)
    db = get_db()
    now = datetime.utcnow().isoformat(timespec="seconds")
    cursor = db.execute(
        """
        INSERT INTO datasets (name, filename, original_filename, row_count, columns_json, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name, filename, original_filename, len(rows), json.dumps(list(rows[0].keys()) if rows else EXPECTED_COLUMNS), now),
    )
    dataset_id = int(cursor.lastrowid)
    db.executemany(
        "INSERT INTO dataset_rows (dataset_id, row_json) VALUES (?, ?)",
        [(dataset_id, json.dumps(row, default=str)) for row in rows],
    )
    db.commit()
    return dataset_id


def ensure_default_dataset() -> None:
    db = get_db()
    existing = db.execute("SELECT COUNT(*) AS total FROM datasets").fetchone()["total"]
    if existing:
        return
    dataset_id = save_dataset(read_csv_records(SAMPLE_DATASET), "Sample Supply Chain Dataset", SAMPLE_DATASET.name, SAMPLE_DATASET.name)
    save_analysis(dataset_id, "Initial Sample Analysis", analyze_dataset(load_dataset(dataset_id)))


def load_dataset(dataset_id: int | None = None) -> list[dict]:
    db = get_db()
    if dataset_id is None:
        row = db.execute("SELECT id FROM datasets ORDER BY uploaded_at DESC, id DESC LIMIT 1").fetchone()
        dataset_id = row["id"] if row else None
    if dataset_id is None:
        return []
    rows = db.execute("SELECT row_json FROM dataset_rows WHERE dataset_id = ? ORDER BY id", (dataset_id,)).fetchall()
    return clean_records([json.loads(row["row_json"]) for row in rows])


def latest_dataset() -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM datasets ORDER BY uploaded_at DESC, id DESC LIMIT 1").fetchone()


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def pct(amount: float) -> str:
    return f"{amount:.1f}%"


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def analyze_dataset(rows: list[dict]) -> dict:
    rows = clean_records(rows)
    if not rows:
        return empty_analysis()

    inventory = [row["Inventory_Level"] for row in rows]
    reorder = [row["Reorder_Point"] for row in rows]
    purchase_cost = [row["Purchase_Cost"] for row in rows]
    selling_price = [row["Selling_Price"] for row in rows]
    transport = [row["Transportation_Cost"] for row in rows]
    demand = [row["Demand"] for row in rows]
    monthly_sales = [row["Monthly_Sales"] for row in rows]
    fulfillment = [row["Fulfillment_Rate"] for row in rows]
    supplier_rating = [row["Supplier_Rating"] for row in rows]
    lead_time = [row["Lead_Time_Days"] for row in rows]

    inventory_value = sum(inv * cost for inv, cost in zip(inventory, purchase_cost))
    revenue_potential = sum(inv * price for inv, price in zip(inventory, selling_price))
    cogs = sum(sales * cost for sales, cost in zip(monthly_sales, purchase_cost))
    turnover = cogs / max(inventory_value, 1)
    stockout_pct = sum(1 for row in rows if row["Inventory_Level"] <= row["Reorder_Point"]) / len(rows) * 100
    carrying_cost = inventory_value * 0.22
    logistics_efficiency = max(0, 100 - (sum(transport) / max(revenue_potential, 1) * 100))
    warehouse_utilization = min(100, sum(inventory) / max(sum(inventory) + sum(reorder), 1) * 100)
    supplier_score = mean(supplier_rating)
    fulfillment_rate = mean(fulfillment)
    avg_lead = mean(lead_time)
    demand_coverage = sum(inventory) / max(sum(demand), 1) * 100
    health = mean([
        min(100, fulfillment_rate),
        min(100, supplier_score),
        max(0, 100 - stockout_pct),
        min(100, logistics_efficiency),
        min(100, turnover * 20),
    ])

    supplier_rank = supplier_ranking(rows)
    top_supplier = supplier_rank[0]["Supplier_Name"] if supplier_rank else "N/A"
    stock_shortage = [row for row in rows if row["Inventory_Level"] <= row["Reorder_Point"]]
    overstock = [row for row in rows if row["Inventory_Level"] > max(row["Demand"] * 2, 1)]
    slow_moving = [row for row in rows if row["Inventory_Level"] > row["Demand"] and row["Monthly_Sales"] < row["Demand"] * 0.75]
    recommendations = build_recommendations(supplier_rank, stock_shortage, overstock, slow_moving, health)

    metrics = {
        "Total Inventory": f"{int(sum(inventory)):,}",
        "Inventory Value": money(inventory_value),
        "Inventory Turnover Ratio": f"{turnover:.2f}x",
        "Average Lead Time": f"{avg_lead:.1f} days",
        "Order Fulfillment Rate": pct(fulfillment_rate),
        "Supplier Performance Score": pct(supplier_score),
        "Stockout Percentage": pct(stockout_pct),
        "Carrying Cost": money(carrying_cost),
        "Logistics Efficiency": pct(logistics_efficiency),
        "Warehouse Utilization": pct(warehouse_utilization),
        "Top Supplier": top_supplier,
        "Supply Chain Health Score": pct(health),
    }

    return {
        "metrics": metrics,
        "raw_metrics": {
            "health": health,
            "turnover": turnover,
            "stockout_pct": stockout_pct,
            "carrying_cost": carrying_cost,
            "demand_coverage": demand_coverage,
        },
        "recommendations": recommendations,
        "supplier_rank": supplier_rank,
        "stock_shortage": stock_shortage,
        "overstock": overstock,
        "slow_moving": slow_moving,
        "abc": abc_classification(rows),
        "forecast": demand_forecast(rows),
        "eoq": eoq_recommendations(rows),
        "summary": executive_summary(metrics, recommendations),
    }


def empty_analysis() -> dict:
    return {
        "metrics": {key: "N/A" for key in [
            "Total Inventory", "Inventory Value", "Inventory Turnover Ratio", "Average Lead Time",
            "Order Fulfillment Rate", "Supplier Performance Score", "Stockout Percentage", "Carrying Cost",
            "Logistics Efficiency", "Warehouse Utilization", "Top Supplier", "Supply Chain Health Score"
        ]},
        "raw_metrics": {},
        "recommendations": [],
        "supplier_rank": [],
        "stock_shortage": [],
        "overstock": [],
        "slow_moving": [],
        "abc": [],
        "forecast": [],
        "eoq": [],
        "summary": "No dataset is available for analysis.",
    }


def supplier_ranking(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["Supplier_Name"], []).append(row)
    ranked = []
    for supplier, items in grouped.items():
        performance = mean([
            row["Supplier_Rating"] * 0.5 + row["Fulfillment_Rate"] * 0.3 + max(30 - row["Lead_Time_Days"], 0) * 0.8
            for row in items
        ])
        ranked.append({
            "Supplier_Name": supplier,
            "performance_score": round(performance, 2),
            "avg_rating": round(mean([row["Supplier_Rating"] for row in items]), 2),
            "avg_lead_time": round(mean([row["Lead_Time_Days"] for row in items]), 2),
            "total_orders": round(sum(row["Order_Quantity"] for row in items), 2),
            "fulfillment": round(mean([row["Fulfillment_Rate"] for row in items]), 2),
        })
    return sorted(ranked, key=lambda item: item["performance_score"], reverse=True)


def abc_classification(rows: list[dict]) -> list[dict]:
    work = []
    for row in rows:
        annual_value = row["Monthly_Sales"] * row["Purchase_Cost"] * 12
        work.append({**row, "Annual_Value": annual_value})
    work.sort(key=lambda row: row["Annual_Value"], reverse=True)
    total = max(sum(row["Annual_Value"] for row in work), 1)
    cumulative = 0.0
    output = []
    for row in work:
        cumulative += row["Annual_Value"]
        cumulative_pct = cumulative / total * 100
        abc_class = "A" if cumulative_pct <= 80 else "B" if cumulative_pct <= 95 else "C"
        output.append({
            "Product_ID": row["Product_ID"],
            "Product_Name": row["Product_Name"],
            "Category": row["Category"],
            "Annual_Value": round(row["Annual_Value"], 2),
            "Cumulative_Percentage": round(cumulative_pct, 2),
            "ABC_Class": abc_class,
        })
    return output


def linear_forecast(history: list[float]) -> float:
    n = len(history)
    x_mean = (n - 1) / 2
    y_mean = mean(history)
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(history))
    denominator = sum((idx - x_mean) ** 2 for idx in range(n)) or 1
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean
    return max(intercept + slope * n, 0)


def demand_forecast(rows: list[dict]) -> list[dict]:
    forecasts = []
    for row in rows:
        history = [
            row["Monthly_Sales"] * 0.82,
            row["Monthly_Sales"] * 0.9,
            row["Monthly_Sales"] * 0.96,
            row["Monthly_Sales"],
            row["Demand"],
        ]
        next_period = linear_forecast(history)
        forecasts.append({
            "Product_ID": row["Product_ID"],
            "Product_Name": row["Product_Name"],
            "Current_Demand": round(row["Demand"], 2),
            "Forecast_Next_Period": round(next_period, 2),
            "Trend": "Increasing" if next_period > row["Demand"] else "Stable or Declining",
        })
    return forecasts


def eoq_recommendations(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        annual_demand = row["Demand"] * 12
        order_cost = max(row["Transportation_Cost"], 1)
        holding_cost = max(row["Purchase_Cost"] * 0.22, 0.01)
        output.append({
            "Product_ID": row["Product_ID"],
            "Product_Name": row["Product_Name"],
            "EOQ": round(math.sqrt((2 * annual_demand * order_cost) / holding_cost)),
            "Recommended_Safety_Stock": round((row["Demand"] / 30) * row["Lead_Time_Days"] * 0.5),
            "Recommended_Reorder_Point": round((row["Demand"] / 30) * row["Lead_Time_Days"] * 1.5),
        })
    return output


def build_recommendations(suppliers: list[dict], shortages: list[dict], overstock: list[dict], slow: list[dict], health: float) -> list[dict]:
    recommendations = []
    for row in shortages[:6]:
        gap = max(row["Reorder_Point"] - row["Inventory_Level"], 0)
        recommendations.append({
            "area": "Inventory Optimization",
            "priority": "High",
            "title": f"Replenish {row['Product_Name']}",
            "detail": f"Inventory is {row['Inventory_Level']:.0f} against reorder point {row['Reorder_Point']:.0f}. Place an order covering at least {gap + row['Safety_Stock']:.0f} units.",
        })
    for row in overstock[:4]:
        recommendations.append({
            "area": "Overstock Reduction",
            "priority": "Medium",
            "title": f"Reduce excess stock for {row['Product_Name']}",
            "detail": "Inventory is materially above demand. Review purchase quantities, promotions, and warehouse space allocation.",
        })
    for row in slow[:4]:
        recommendations.append({
            "area": "Slow-Moving Inventory",
            "priority": "Medium",
            "title": f"Investigate slow movement for {row['Product_Name']}",
            "detail": "Sales are below demand signal while inventory remains elevated. Check forecast quality, substitution risk, and aging stock.",
        })
    for row in [supplier for supplier in suppliers if supplier["performance_score"] < 75][:3]:
        recommendations.append({
            "area": "Supplier Risk Assessment",
            "priority": "High",
            "title": f"Mitigate supplier risk: {row['Supplier_Name']}",
            "detail": f"Performance score is {row['performance_score']:.1f}. Evaluate alternate suppliers, service-level clauses, and additional safety stock.",
        })
    if health < 75:
        recommendations.append({
            "area": "Executive Action",
            "priority": "High",
            "title": "Launch cross-functional recovery plan",
            "detail": "The supply chain health score is below target. Prioritize stockout recovery, lead-time reduction, and supplier performance reviews.",
        })
    if not recommendations:
        recommendations.append({
            "area": "Continuous Improvement",
            "priority": "Low",
            "title": "Maintain current operating cadence",
            "detail": "No critical exceptions detected. Continue monitoring reorder points, lead times, and fulfillment quality weekly.",
        })
    return recommendations


def executive_summary(metrics: dict, recommendations: list[dict]) -> str:
    high_count = sum(1 for item in recommendations if item["priority"] == "High")
    return (
        f"The current supply chain health score is {metrics['Supply Chain Health Score']} with "
        f"inventory value of {metrics['Inventory Value']} and fulfillment at {metrics['Order Fulfillment Rate']}. "
        f"Average supplier lead time is {metrics['Average Lead Time']}. "
        f"{high_count} high-priority actions require management attention."
    )


def save_analysis(dataset_id: int, analysis_type: str, analysis: dict) -> None:
    get_db().execute(
        """
        INSERT INTO analysis_history (dataset_id, analysis_type, summary, metrics_json, recommendations_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            analysis_type,
            analysis["summary"],
            json.dumps(analysis["metrics"]),
            json.dumps(analysis["recommendations"]),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    get_db().commit()


def page_context() -> dict:
    dataset = latest_dataset()
    rows = load_dataset(dataset["id"] if dataset else None)
    analysis = analyze_dataset(rows)
    return {"dataset": dataset, "df": rows, "analysis": analysis}


def table_records(rows: list[dict], limit: int | None = None) -> list[dict]:
    return rows[:limit] if limit else rows


@app.route("/")
def index():
    context = page_context()
    return render_template("index.html", app_name=APP_NAME, **context)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Choose a CSV file to upload.", "warning")
            return redirect(url_for("upload"))
        if not allowed_file(file.filename):
            flash("Only CSV files are supported.", "danger")
            return redirect(url_for("upload"))
        original = secure_filename(file.filename)
        stored = f"{uuid4().hex}_{original}"
        path = UPLOAD_FOLDER / stored
        file.save(path)
        try:
            records = read_csv_records(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            flash(f"Could not read CSV file: {exc}", "danger")
            return redirect(url_for("upload"))
        dataset_id = save_dataset(records, request.form.get("dataset_name") or original, stored, original)
        analysis = analyze_dataset(load_dataset(dataset_id))
        save_analysis(dataset_id, "Uploaded Dataset Analysis", analysis)
        flash("Dataset uploaded, cleaned, stored, and analyzed.", "success")
        return redirect(url_for("preview", dataset_id=dataset_id))
    datasets = get_db().execute("SELECT * FROM datasets ORDER BY uploaded_at DESC, id DESC").fetchall()
    return render_template("upload.html", app_name=APP_NAME, datasets=datasets)


@app.route("/preview")
@app.route("/preview/<int:dataset_id>")
def preview(dataset_id: int | None = None):
    dataset = latest_dataset() if dataset_id is None else get_db().execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not dataset:
        flash("No dataset found.", "warning")
        return redirect(url_for("upload"))
    rows = load_dataset(dataset["id"])
    detected_columns = list(rows[0].keys()) if rows else EXPECTED_COLUMNS
    missing_columns = [column for column in EXPECTED_COLUMNS if column not in detected_columns]
    return render_template(
        "preview.html",
        app_name=APP_NAME,
        dataset=dataset,
        records=table_records(rows, 50),
        columns=detected_columns,
        missing_columns=missing_columns,
    )


@app.route("/inventory")
def inventory():
    context = page_context()
    return render_template("inventory.html", app_name=APP_NAME, records=table_records(context["df"]), **context)


@app.route("/suppliers")
def suppliers():
    context = page_context()
    return render_template("suppliers.html", app_name=APP_NAME, **context)


@app.route("/procurement")
def procurement():
    context = page_context()
    procurement_rows = []
    for row in context["df"]:
        procurement_rows.append({
            **row,
            "Spend": row["Order_Quantity"] * row["Purchase_Cost"],
            "Margin": row["Selling_Price"] - row["Purchase_Cost"],
        })
    return render_template("procurement.html", app_name=APP_NAME, procurement=procurement_rows, **context)


@app.route("/logistics")
def logistics():
    context = page_context()
    logistics_rows = []
    for row in context["df"]:
        status = row["Delivery_Status"].lower()
        logistics_rows.append({
            **row,
            "Cost_Per_Unit": row["Transportation_Cost"] / row["Order_Quantity"] if row["Order_Quantity"] else 0,
            "Delivery_Risk": "High" if status in {"delayed", "late"} else "Managed",
        })
    return render_template("logistics.html", app_name=APP_NAME, logistics=logistics_rows, **context)


@app.route("/forecasting")
def forecasting():
    context = page_context()
    return render_template("forecasting.html", app_name=APP_NAME, **context)


@app.route("/insights")
def insights():
    context = page_context()
    return render_template("insights.html", app_name=APP_NAME, **context)


@app.route("/summary")
def summary():
    context = page_context()
    return render_template("summary.html", app_name=APP_NAME, **context)


@app.route("/reports")
def reports():
    context = page_context()
    history = get_db().execute(
        """
        SELECT h.*, d.name AS dataset_name
        FROM analysis_history h
        JOIN datasets d ON d.id = h.dataset_id
        ORDER BY h.created_at DESC, h.id DESC
        """
    ).fetchall()
    return render_template("reports.html", app_name=APP_NAME, history=history, **context)


@app.route("/export")
def export():
    context = page_context()
    return render_template("export.html", app_name=APP_NAME, **context)


@app.route("/export/report.csv")
def export_report():
    analysis = page_context()["analysis"]
    output = [["Section", "Metric", "Value"]]
    for key, val in analysis["metrics"].items():
        output.append(["KPI", key, val])
    for item in analysis["recommendations"]:
        output.append([item["area"], item["title"], item["detail"]])
    csv_text = "\n".join(",".join(f'"{str(cell).replace(chr(34), chr(34) + chr(34))}"' for cell in row) for row in output)
    filename = REPORT_FOLDER / f"supply_chain_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    filename.write_text(csv_text, encoding="utf-8")
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=supply_chain_report.csv"},
    )


@app.route("/export/dataset.csv")
def export_dataset():
    dataset = latest_dataset()
    if not dataset:
        flash("No dataset is available to export.", "warning")
        return redirect(url_for("export"))
    rows = load_dataset(dataset["id"])
    columns = list(rows[0].keys()) if rows else EXPECTED_COLUMNS
    lines = []
    writer_rows = [columns] + [[row.get(column, "") for column in columns] for row in rows]
    for row in writer_rows:
        lines.append(",".join(f'"{str(cell).replace(chr(34), chr(34) + chr(34))}"' for cell in row))
    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=clean_supply_chain_dataset.csv"},
    )


@app.template_filter("from_json")
def from_json(value_text: str):
    return json.loads(value_text)


@app.context_processor
def inject_globals():
    return {"app_name": APP_NAME}


if __name__ == "__main__":
    app.run(debug=True)
