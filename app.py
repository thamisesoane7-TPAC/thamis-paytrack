import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
from fpdf import FPDF
from urllib.parse import quote
import re


# ============================================================
# CONFIGURATION
# ============================================================

DB_PATH = "paytrack_pro.db"
# ============================================================
# PAYMENT RISK MODEL CONFIGURATION
# ============================================================

RISK_MODEL_VERSION = "1.0"

RISK_THRESHOLDS = {
    "LOW RISK": 30,
    "MEDIUM RISK": 60
}

COLLECTION_PROBABILITY = {
    "LOW RISK": 0.95,
    "MEDIUM RISK": 0.75,
    "HIGH RISK": 0.45
}
st.set_page_config(
    page_title="PayTrack Pro",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# UI STYLING
# ============================================================

st.markdown(
    """
    <style>
        .main .block-container {
            max-width: 1400px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }

        .app-title {
            font-size: 2.25rem;
            font-weight: 800;
            margin-bottom: 0;
        }

        .app-subtitle {
            font-size: 1rem;
            color: #6b7280;
            margin-top: 0.1rem;
            margin-bottom: 1.5rem;
        }

        .section-card {
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 14px;
            padding: 18px;
            margin-bottom: 12px;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 15px;
            border-radius: 14px;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# DATABASE LAYER
# ============================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS business_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                business_name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                address TEXT,
                vat_number TEXT,
                bank_name TEXT,
                account_name TEXT,
                account_number TEXT,
                branch_code TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inv_number TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                issue_date TEXT NOT NULL,
                due_date TEXT NOT NULL,

                subtotal REAL NOT NULL,
                discount_pct REAL NOT NULL DEFAULT 0,
                discount_amount REAL NOT NULL DEFAULT 0,

                vat_rate REAL NOT NULL DEFAULT 0,
                vat_amount REAL NOT NULL DEFAULT 0,

                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'Unpaid',
                notes TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL,

                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                paid_on TEXT NOT NULL,
                payment_method TEXT,
                reference TEXT,
                created_at TEXT NOT NULL,

                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # -------------------------
        # SQL INDEXES
        # -------------------------

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_customer
            ON invoices(customer_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_issue_date
            ON invoices(issue_date)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_due_date
            ON invoices(due_date)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_invoice
            ON payments(invoice_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_customer_email
            ON customers(email)
        """)

        conn.commit()


# ============================================================
# BUSINESS PROFILE
# ============================================================

def get_business_profile():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM business_profile
            WHERE id = 1
        """).fetchone()

    return dict(row) if row else {}


def save_business_profile(data):
    with get_connection() as conn:

        conn.execute("""
            INSERT INTO business_profile (
                id,
                business_name,
                phone,
                email,
                address,
                vat_number,
                bank_name,
                account_name,
                account_number,
                branch_code,
                updated_at
            )
            VALUES (
                1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )

            ON CONFLICT(id)
            DO UPDATE SET

                business_name = excluded.business_name,
                phone = excluded.phone,
                email = excluded.email,
                address = excluded.address,
                vat_number = excluded.vat_number,
                bank_name = excluded.bank_name,
                account_name = excluded.account_name,
                account_number = excluded.account_number,
                branch_code = excluded.branch_code,
                updated_at = excluded.updated_at
        """, (
            data["business_name"],
            data["phone"],
            data["email"],
            data["address"],
            data["vat_number"],
            data["bank_name"],
            data["account_name"],
            data["account_number"],
            data["branch_code"],
            datetime.now().isoformat(timespec="seconds")
        ))

        conn.commit()


# ============================================================
# VALIDATION
# ============================================================

def valid_email(email):
    if not email:
        return True

    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email.strip()))


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_sa_phone(phone):
    digits = re.sub(r"\D", "", phone or "")

    if digits.startswith("0") and len(digits) == 10:
        digits = "27" + digits[1:]

    return digits


# ============================================================
# CUSTOMER MANAGEMENT
# ============================================================

def get_or_create_customer(conn, name, phone, email):

    name = clean_text(name)
    phone = clean_text(phone)
    email = clean_text(email).lower()

    customer = None

    if email:
        customer = conn.execute("""
            SELECT *
            FROM customers
            WHERE LOWER(email) = ?
            LIMIT 1
        """, (email,)).fetchone()

    if not customer and phone:
        customer = conn.execute("""
            SELECT *
            FROM customers
            WHERE phone = ?
            LIMIT 1
        """, (phone,)).fetchone()

    if customer:

        conn.execute("""
            UPDATE customers
            SET
                name = ?,
                phone = ?,
                email = ?
            WHERE id = ?
        """, (
            name,
            phone,
            email,
            customer["id"]
        ))

        return customer["id"]

    cursor = conn.execute("""
        INSERT INTO customers (
            name,
            phone,
            email,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        name,
        phone,
        email,
        datetime.now().isoformat(timespec="seconds")
    ))

    return cursor.lastrowid


# ============================================================
# INVOICE NUMBERING
# ============================================================

def get_next_invoice_number(conn):

    result = conn.execute("""
        SELECT
            COALESCE(
                MAX(
                    CAST(
                        SUBSTR(inv_number, 5)
                        AS INTEGER
                    )
                ),
                0
            ) + 1
        FROM invoices
        WHERE inv_number LIKE 'INV-%'
    """).fetchone()[0]

    return f"INV-{result:05d}"


# ============================================================
# AUDIT LOGGING
# ============================================================

def write_audit_log(
    conn,
    event_type,
    entity_type,
    entity_id,
    details
):
    conn.execute("""
        INSERT INTO audit_log (
            event_type,
            entity_type,
            entity_id,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        event_type,
        entity_type,
        entity_id,
        details,
        datetime.now().isoformat(timespec="seconds")
    ))


# ============================================================
# CREATE INVOICE
# ============================================================

def create_invoice_record(
    customer,
    issue_date,
    due_date,
    items,
    discount_pct,
    vat_rate,
    notes,
    initial_payment
):

    subtotal = sum(
        float(item["line_total"])
        for item in items
    )

    discount_amount = subtotal * (
        discount_pct / 100
    )

    taxable_amount = subtotal - discount_amount

    vat_amount = taxable_amount * (
        vat_rate / 100
    )

    total = taxable_amount + vat_amount

    conn = get_connection()

    try:
        # Prevent two simultaneous writers from creating
        # the same invoice number.
        conn.execute("BEGIN IMMEDIATE")

        customer_id = get_or_create_customer(
            conn,
            customer["name"],
            customer["phone"],
            customer["email"]
        )

        inv_number = get_next_invoice_number(conn)

        cursor = conn.execute("""
            INSERT INTO invoices (
                inv_number,
                customer_id,
                issue_date,
                due_date,
                subtotal,
                discount_pct,
                discount_amount,
                vat_rate,
                vat_amount,
                total,
                status,
                notes,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            inv_number,
            customer_id,
            issue_date,
            due_date,
            subtotal,
            discount_pct,
            discount_amount,
            vat_rate,
            vat_amount,
            total,
            "Unpaid",
            clean_text(notes),
            datetime.now().isoformat(timespec="seconds")
        ))

        invoice_id = cursor.lastrowid

        for item in items:

            conn.execute("""
                INSERT INTO invoice_items (
                    invoice_id,
                    description,
                    quantity,
                    unit_price,
                    line_total
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                invoice_id,
                clean_text(item["description"]),
                float(item["quantity"]),
                float(item["unit_price"]),
                float(item["line_total"])
            ))

        if initial_payment > 0:

            conn.execute("""
                INSERT INTO payments (
                    invoice_id,
                    amount,
                    paid_on,
                    payment_method,
                    reference,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                invoice_id,
                initial_payment,
                issue_date,
                "Initial Payment",
                "",
                datetime.now().isoformat(timespec="seconds")
            ))

        write_audit_log(
            conn,
            "CREATE_INVOICE",
            "invoice",
            invoice_id,
            f"Created {inv_number}"
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    refresh_invoice_statuses()

    return invoice_id, inv_number


# ============================================================
# PAYMENT MANAGEMENT
# ============================================================

def record_payment(
    invoice_id,
    amount,
    payment_date,
    method,
    reference
):

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO payments (
                invoice_id,
                amount,
                paid_on,
                payment_method,
                reference,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            invoice_id,
            amount,
            payment_date,
            method,
            clean_text(reference),
            datetime.now().isoformat(timespec="seconds")
        ))

        write_audit_log(
            conn,
            "RECORD_PAYMENT",
            "invoice",
            invoice_id,
            f"Payment received: R{amount:.2f}"
        )

        conn.commit()

    refresh_invoice_statuses()


# ============================================================
# STATUS ENGINE
# ============================================================

def refresh_invoice_statuses():

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT
                i.id,
                i.total,
                i.due_date,
                COALESCE(SUM(p.amount), 0) AS amount_paid
            FROM invoices i

            LEFT JOIN payments p
                ON p.invoice_id = i.id

            GROUP BY
                i.id,
                i.total,
                i.due_date
        """).fetchall()

        today = date.today()

        for row in rows:

            total = float(row["total"])
            paid = float(row["amount_paid"])

            remaining = max(total - paid, 0)

            due = datetime.strptime(
                row["due_date"],
                "%Y-%m-%d"
            ).date()

            if remaining <= 0.005:
                status = "Paid"

            elif due < today:
                status = "Overdue"

            elif paid > 0:
                status = "Partially Paid"

            else:
                status = "Unpaid"

            conn.execute("""
                UPDATE invoices
                SET status = ?
                WHERE id = ?
            """, (
                status,
                row["id"]
            ))

        conn.commit()


# ============================================================
# ANALYTICS QUERY
# ============================================================

def get_invoice_summary():

    refresh_invoice_statuses()

    query = """
        SELECT
            i.id AS invoice_id,
            i.inv_number,
            i.issue_date,
            i.due_date,
            c.name AS customer,
            c.phone,
            c.email,
            i.subtotal,
            i.discount_pct,
            i.discount_amount,
            i.vat_rate,
            i.vat_amount,
            i.total,

            COALESCE(
                SUM(p.amount),
                0
            ) AS amount_paid,

            CASE
                WHEN
                    i.total -
                    COALESCE(SUM(p.amount), 0) < 0
                THEN 0

                ELSE
                    i.total -
                    COALESCE(SUM(p.amount), 0)
            END AS balance,

            i.status

        FROM invoices i

        JOIN customers c
            ON c.id = i.customer_id

        LEFT JOIN payments p
            ON p.invoice_id = i.id

        GROUP BY
            i.id,
            i.inv_number,
            i.issue_date,
            i.due_date,
            c.name,
            c.phone,
            c.email,
            i.subtotal,
            i.discount_pct,
            i.discount_amount,
            i.vat_rate,
            i.vat_amount,
            i.total,
            i.status

        ORDER BY
            i.id DESC
    """

    with get_connection() as conn:
        return pd.read_sql_query(
            query,
            conn
        )
# ============================================================
# CUSTOMER PAYMENT HISTORY
# ============================================================

def get_customer_payment_history():
    """
    Builds historical payment behaviour at invoice level.

    Returns one row per invoice with:
    - total paid
    - balance
    - final payment date
    - days late
    - whether invoice was paid late
    """

    query = """
        WITH payment_summary AS (
            SELECT
                invoice_id,
                SUM(amount) AS total_paid,
                MAX(paid_on) AS last_payment_date
            FROM payments
            GROUP BY invoice_id
        )

        SELECT
            i.id AS invoice_id,
            i.customer_id,
            c.name AS customer,
            i.inv_number,
            i.issue_date,
            i.due_date,
            i.total,

            COALESCE(
                ps.total_paid,
                0
            ) AS amount_paid,

            CASE
                WHEN i.total - COALESCE(ps.total_paid, 0) < 0
                    THEN 0
                ELSE i.total - COALESCE(ps.total_paid, 0)
            END AS balance,

            ps.last_payment_date

        FROM invoices i

        JOIN customers c
            ON c.id = i.customer_id

        LEFT JOIN payment_summary ps
            ON ps.invoice_id = i.id
    """

    with get_connection() as conn:
        df = pd.read_sql_query(
            query,
            conn
        )

    if df.empty:
        return df

    df["issue_date"] = pd.to_datetime(
        df["issue_date"]
    )

    df["due_date"] = pd.to_datetime(
        df["due_date"]
    )

    df["last_payment_date"] = pd.to_datetime(
        df["last_payment_date"],
        errors="coerce"
    )

    # Fully paid?
    df["is_paid"] = (
        df["balance"] <= 0.005
    )

    # Days between due date and final payment.
    # Early/on-time payments become 0 days late.
    df["days_late"] = 0.0

    paid_mask = (
        df["is_paid"]
        &
        df["last_payment_date"].notna()
    )

    df.loc[
        paid_mask,
        "days_late"
    ] = (
        df.loc[
            paid_mask,
            "last_payment_date"
        ]
        -
        df.loc[
            paid_mask,
            "due_date"
        ]
    ).dt.days.clip(
        lower=0
    )

    df["was_late"] = (
        df["days_late"] > 0
    )

    return df
# ============================================================
# CUSTOMER RISK FEATURES
# ============================================================

def build_customer_risk_profiles():
    """
    Converts historical invoice/payment records into
    customer-level behavioural risk features.
    """

    history = get_customer_payment_history()

    if history.empty:
        return pd.DataFrame()

    customer_profiles = []

    for customer_id, group in history.groupby(
        "customer_id"
    ):

        paid_history = group[
            group["is_paid"]
        ]

        total_invoices = len(group)

        paid_invoices = int(
            group["is_paid"].sum()
        )

        unpaid_invoices = (
            total_invoices -
            paid_invoices
        )

        # -----------------------------------------
        # HISTORICAL LATE PAYMENT RATE
        # -----------------------------------------

        if not paid_history.empty:

            late_payment_rate = (
                paid_history[
                    "was_late"
                ].mean()
            )

            avg_payment_delay = (
                paid_history[
                    "days_late"
                ].mean()
            )

            max_payment_delay = (
                paid_history[
                    "days_late"
                ].max()
            )

        else:

            late_payment_rate = 0.0
            avg_payment_delay = 0.0
            max_payment_delay = 0.0

        unpaid_invoice_rate = (
            unpaid_invoices /
            total_invoices
            if total_invoices > 0
            else 0
        )

        total_invoiced = (
            group["total"].sum()
        )

        total_outstanding = (
            group["balance"].sum()
        )

        outstanding_ratio = (
            total_outstanding /
            total_invoiced
            if total_invoiced > 0
            else 0
        )

        customer_profiles.append({
            "customer_id":
                customer_id,

            "customer":
                group[
                    "customer"
                ].iloc[0],

            "total_invoices":
                total_invoices,

            "paid_invoices":
                paid_invoices,

            "unpaid_invoices":
                unpaid_invoices,

            "late_payment_rate":
                late_payment_rate,

            "avg_payment_delay":
                avg_payment_delay,

            "max_payment_delay":
                max_payment_delay,

            "unpaid_invoice_rate":
                unpaid_invoice_rate,

            "total_invoiced":
                total_invoiced,

            "total_outstanding":
                total_outstanding,

            "outstanding_ratio":
                outstanding_ratio
        })

    return pd.DataFrame(
        customer_profiles
    )
# ============================================================
# PAYMENT RISK MODEL
# ============================================================

def calculate_payment_risk():
    """
    Explainable rule-based payment risk model.

    Produces a risk score from 0-100 and assigns:
    LOW RISK
    MEDIUM RISK
    HIGH RISK
    """

    summary = get_invoice_summary()

    if summary.empty:
        return pd.DataFrame()

    customer_risk = build_customer_risk_profiles()

    # Retrieve customer_id for each invoice
    with get_connection() as conn:

        invoice_customers = pd.read_sql_query(
            """
            SELECT
                id AS invoice_id,
                customer_id
            FROM invoices
            """,
            conn
        )

    result = summary.merge(
        invoice_customers,
        on="invoice_id",
        how="left"
    )

    if not customer_risk.empty:

        result = result.merge(
            customer_risk,
            on="customer_id",
            how="left",
            suffixes=(
                "",
                "_history"
            )
        )

    # -----------------------------------------
    # DEFAULT VALUES FOR NEW CUSTOMERS
    # -----------------------------------------

    defaults = {
        "total_invoices": 1,
        "paid_invoices": 0,
        "unpaid_invoices": 1,
        "late_payment_rate": 0,
        "avg_payment_delay": 0,
        "max_payment_delay": 0,
        "unpaid_invoice_rate": 0,
        "outstanding_ratio": 0
    }

    for column, default in defaults.items():

        if column not in result.columns:
            result[column] = default

        result[column] = (
            result[column]
            .fillna(default)
        )

    # -----------------------------------------
    # CURRENT INVOICE FEATURES
    # -----------------------------------------

    today = pd.Timestamp(
        date.today()
    )

    result["due_date_dt"] = (
        pd.to_datetime(
            result["due_date"]
        )
    )

    result["days_overdue"] = (
        today -
        result["due_date_dt"]
    ).dt.days.clip(
        lower=0
    )

    result["invoice_unpaid_ratio"] = (
        result["balance"] /
        result["total"]
    ).fillna(
        0
    ).clip(
        0,
        1
    )

    # -----------------------------------------
    # RISK COMPONENT 1:
    # CURRENT OVERDUE STATUS
    # Maximum = 35 points
    # -----------------------------------------

    def overdue_score(days):

        if days <= 0:
            return 0

        if days <= 7:
            return 8

        if days <= 14:
            return 15

        if days <= 30:
            return 25

        return 35

    result[
        "overdue_score"
    ] = result[
        "days_overdue"
    ].apply(
        overdue_score
    )

    # -----------------------------------------
    # RISK COMPONENT 2:
    # HISTORICAL LATE RATE
    # Maximum = 25 points
    # -----------------------------------------

    result[
        "late_history_score"
    ] = (
        result[
            "late_payment_rate"
        ]
        .clip(
            0,
            1
        )
        * 25
    )

    # -----------------------------------------
    # RISK COMPONENT 3:
    # AVERAGE HISTORICAL DELAY
    # Maximum = 20 points
    # -----------------------------------------

    result[
        "delay_score"
    ] = (
        result[
            "avg_payment_delay"
        ]
        .clip(
            lower=0,
            upper=30
        )
        /
        30
        * 20
    )

    # -----------------------------------------
    # RISK COMPONENT 4:
    # UNPAID SHARE OF CURRENT INVOICE
    # Maximum = 10 points
    # -----------------------------------------

    result[
        "balance_score"
    ] = (
        result[
            "invoice_unpaid_ratio"
        ]
        * 10
    )

    # -----------------------------------------
    # RISK COMPONENT 5:
    # CUSTOMER'S HISTORICAL UNPAID RATE
    # Maximum = 10 points
    # -----------------------------------------

    result[
        "unpaid_history_score"
    ] = (
        result[
            "unpaid_invoice_rate"
        ]
        .clip(
            0,
            1
        )
        * 10
    )

    # -----------------------------------------
    # TOTAL SCORE
    # -----------------------------------------

    result[
        "risk_score"
    ] = (
        result[
            "overdue_score"
        ]
        +
        result[
            "late_history_score"
        ]
        +
        result[
            "delay_score"
        ]
        +
        result[
            "balance_score"
        ]
        +
        result[
            "unpaid_history_score"
        ]
    ).clip(
        0,
        100
    )

    result[
        "risk_score"
    ] = (
        result[
            "risk_score"
        ]
        .round(1)
    )

    # Fully paid invoices have no collection risk
    result.loc[
        result[
            "balance"
        ] <= 0.005,
        "risk_score"
    ] = 0

    # -----------------------------------------
    # RISK CLASSIFICATION
    # -----------------------------------------

    def risk_band(score):

        if score < 30:
            return "LOW RISK"

        if score < 60:
            return "MEDIUM RISK"

        return "HIGH RISK"

    result[
        "risk_level"
    ] = result[
        "risk_score"
    ].apply(
        risk_band
    )

    # -----------------------------------------
    # EXPLAINABILITY
    # -----------------------------------------

    def generate_reason(row):

        reasons = []

        if row["days_overdue"] > 30:
            reasons.append(
                f"{int(row['days_overdue'])} days overdue"
            )

        elif row["days_overdue"] > 0:
            reasons.append(
                f"{int(row['days_overdue'])} days overdue"
            )

        if (
            row["late_payment_rate"]
            >= 0.5
        ):
            reasons.append(
                "frequent historical late payments"
            )

        if (
            row["avg_payment_delay"]
            >= 14
        ):
            reasons.append(
                f"average payment delay "
                f"{row['avg_payment_delay']:.0f} days"
            )

        if (
            row["unpaid_invoice_rate"]
            >= 0.5
        ):
            reasons.append(
                "high proportion of unpaid invoices"
            )

        if (
            row["invoice_unpaid_ratio"]
            >= 0.75
        ):
            reasons.append(
                "most of invoice still outstanding"
            )

        if not reasons:

            reasons.append(
                "strong or limited negative payment history"
            )

        return "; ".join(
            reasons
        )

    result[
        "risk_reason"
    ] = result.apply(
        generate_reason,
        axis=1
    )

    return result
# ============================================================
# CASH FLOW FORECAST ENGINE
# ============================================================

def generate_cashflow_forecast():
    """
    Forecast outstanding cash collection using:
    - invoice due date
    - customer historical payment delay
    - payment risk
    """

    risk_df = calculate_payment_risk()

    if risk_df.empty:
        return pd.DataFrame()

    forecast = risk_df[
        risk_df["balance"] > 0.005
    ].copy()

    if forecast.empty:
        return forecast

    # -----------------------------------------
    # EXPECTED DELAY
    # -----------------------------------------

    forecast[
        "predicted_delay_days"
    ] = (
        forecast[
            "avg_payment_delay"
        ]
        .fillna(0)
        .clip(
            lower=0,
            upper=90
        )
        .round()
        .astype(int)
    )

    # High-risk invoices receive an extra
    # conservative delay buffer.
    forecast.loc[
        forecast[
            "risk_level"
        ] == "MEDIUM RISK",
        "predicted_delay_days"
    ] += 7

    forecast.loc[
        forecast[
            "risk_level"
        ] == "HIGH RISK",
        "predicted_delay_days"
    ] += 21

    forecast[
        "expected_collection_date"
    ] = (
        forecast[
            "due_date_dt"
        ]
        +
        pd.to_timedelta(
            forecast[
                "predicted_delay_days"
            ],
            unit="D"
        )
    )

    # Don't predict collection in the past.
    today_ts = pd.Timestamp(
        date.today()
    )

    forecast[
        "expected_collection_date"
    ] = forecast[
        "expected_collection_date"
    ].apply(
        lambda x:
            max(
                x,
                today_ts
            )
    )

    # -----------------------------------------
    # COLLECTION PROBABILITY
    # -----------------------------------------

    forecast[
        "collection_probability"
    ] = (
        forecast[
            "risk_level"
        ]
        .map(
            COLLECTION_PROBABILITY
        )
    )

    # -----------------------------------------
    # RISK-ADJUSTED CASH
    # -----------------------------------------

    forecast[
        "expected_cash"
    ] = (
        forecast[
            "balance"
        ]
        *
        forecast[
            "collection_probability"
        ]
    )

    forecast[
        "expected_cash"
    ] = (
        forecast[
            "expected_cash"
        ]
        .round(2)
    )

    return forecast
    


# ============================================================
# FULL INVOICE DATA
# ============================================================

def get_invoice_details(invoice_id):

    with get_connection() as conn:

        invoice = conn.execute("""
            SELECT
                i.*,
                c.name AS customer_name,
                c.phone AS customer_phone,
                c.email AS customer_email
            FROM invoices i

            JOIN customers c
                ON c.id = i.customer_id

            WHERE i.id = ?
        """, (invoice_id,)).fetchone()

        items = conn.execute("""
            SELECT *
            FROM invoice_items
            WHERE invoice_id = ?
            ORDER BY id
        """, (invoice_id,)).fetchall()

        payments = conn.execute("""
            SELECT *
            FROM payments
            WHERE invoice_id = ?
            ORDER BY paid_on
        """, (invoice_id,)).fetchall()

        business = conn.execute("""
            SELECT *
            FROM business_profile
            WHERE id = 1
        """).fetchone()

    return {
        "invoice": dict(invoice) if invoice else {},
        "items": [dict(row) for row in items],
        "payments": [dict(row) for row in payments],
        "business": dict(business) if business else {}
    }


# ============================================================
# PDF HELPERS
# ============================================================

def pdf_safe(value):
    text = str(value or "")

    return (
        text
        .encode(
            "latin-1",
            errors="replace"
        )
        .decode("latin-1")
    )


def create_pdf(invoice_id):

    data = get_invoice_details(invoice_id)

    invoice = data["invoice"]
    business = data["business"]
    items = data["items"]
    payments = data["payments"]

    paid = sum(
        float(p["amount"])
        for p in payments
    )

    balance = max(
        invoice["total"] - paid,
        0
    )

    pdf = FPDF()

    pdf.set_auto_page_break(
        auto=True,
        margin=15
    )

    pdf.add_page()

    # ---------------------------------
    # HEADER
    # ---------------------------------

    pdf.set_font(
        "Arial",
        "B",
        22
    )

    pdf.cell(
        190,
        12,
        "INVOICE",
        align="R",
        ln=True
    )

    pdf.set_font(
        "Arial",
        "B",
        16
    )

    pdf.cell(
        190,
        8,
        pdf_safe(
            business.get(
                "business_name",
                "PayTrack Business"
            )
        ),
        ln=True
    )

    pdf.set_font(
        "Arial",
        "",
        9
    )

    if business.get("address"):
        pdf.multi_cell(
            190,
            5,
            pdf_safe(
                business["address"]
            )
        )

    contact_text = (
        f"{business.get('phone', '')}"
        f"  |  "
        f"{business.get('email', '')}"
    )

    pdf.cell(
        190,
        5,
        pdf_safe(contact_text),
        ln=True
    )

    if business.get("vat_number"):
        pdf.cell(
            190,
            5,
            pdf_safe(
                f"VAT No: "
                f"{business['vat_number']}"
            ),
            ln=True
        )

    pdf.ln(8)

    # ---------------------------------
    # CUSTOMER / INVOICE INFO
    # ---------------------------------

    pdf.set_font(
        "Arial",
        "B",
        11
    )

    pdf.cell(
        95,
        7,
        "BILL TO"
    )

    pdf.cell(
        95,
        7,
        pdf_safe(
            invoice["inv_number"]
        ),
        align="R",
        ln=True
    )

    pdf.set_font(
        "Arial",
        "",
        9
    )

    pdf.cell(
        95,
        5,
        pdf_safe(
            invoice["customer_name"]
        )
    )

    pdf.cell(
        95,
        5,
        f"Issue Date: "
        f"{invoice['issue_date']}",
        align="R",
        ln=True
    )

    pdf.cell(
        95,
        5,
        pdf_safe(
            invoice["customer_email"]
        )
    )

    pdf.cell(
        95,
        5,
        f"Due Date: "
        f"{invoice['due_date']}",
        align="R",
        ln=True
    )

    pdf.cell(
        95,
        5,
        pdf_safe(
            invoice["customer_phone"]
        ),
        ln=True
    )

    pdf.ln(8)

    # ---------------------------------
    # ITEMS TABLE
    # ---------------------------------

    pdf.set_font(
        "Arial",
        "B",
        9
    )

    pdf.set_fill_color(
        225,
        225,
        225
    )

    pdf.cell(
        85,
        8,
        "Description",
        1,
        0,
        "L",
        True
    )

    pdf.cell(
        25,
        8,
        "Qty",
        1,
        0,
        "C",
        True
    )

    pdf.cell(
        40,
        8,
        "Unit Price",
        1,
        0,
        "R",
        True
    )

    pdf.cell(
        40,
        8,
        "Total",
        1,
        1,
        "R",
        True
    )

    pdf.set_font(
        "Arial",
        "",
        9
    )

    for item in items:

        pdf.cell(
            85,
            8,
            pdf_safe(
                item["description"]
            )[:48],
            1
        )

        pdf.cell(
            25,
            8,
            f"{item['quantity']:g}",
            1,
            0,
            "C"
        )

        pdf.cell(
            40,
            8,
            f"R {item['unit_price']:,.2f}",
            1,
            0,
            "R"
        )

        pdf.cell(
            40,
            8,
            f"R {item['line_total']:,.2f}",
            1,
            1,
            "R"
        )

    pdf.ln(5)

    # ---------------------------------
    # TOTALS
    # ---------------------------------

    summary = [
        (
            "Subtotal",
            invoice["subtotal"]
        ),
        (
            f"Discount "
            f"({invoice['discount_pct']:.1f}%)",
            -invoice["discount_amount"]
        ),
        (
            f"VAT "
            f"({invoice['vat_rate']:.1f}%)",
            invoice["vat_amount"]
        ),
        (
            "Total",
            invoice["total"]
        ),
        (
            "Amount Paid",
            paid
        ),
        (
            "Outstanding",
            balance
        )
    ]

    for label, amount in summary:

        pdf.set_font(
            "Arial",
            "B" if label in [
                "Total",
                "Outstanding"
            ] else "",
            10
        )

        pdf.cell(
            145,
            7,
            label,
            align="R"
        )

        pdf.cell(
            45,
            7,
            f"R {amount:,.2f}",
            align="R",
            ln=True
        )

    pdf.ln(5)

    pdf.set_font(
        "Arial",
        "B",
        11
    )

    pdf.cell(
        190,
        8,
        f"Status: "
        f"{invoice['status'].upper()}",
        align="R",
        ln=True
    )

    # ---------------------------------
    # BANK DETAILS
    # ---------------------------------

    if business.get("bank_name"):

        pdf.ln(8)

        pdf.set_font(
            "Arial",
            "B",
            10
        )

        pdf.cell(
            190,
            6,
            "PAYMENT DETAILS",
            ln=True
        )

        pdf.set_font(
            "Arial",
            "",
            9
        )

        banking = [
            (
                "Bank",
                business.get("bank_name")
            ),
            (
                "Account Name",
                business.get("account_name")
            ),
            (
                "Account Number",
                business.get("account_number")
            ),
            (
                "Branch Code",
                business.get("branch_code")
            ),
            (
                "Reference",
                invoice["inv_number"]
            )
        ]

        for label, value in banking:

            if value:
                pdf.cell(
                    45,
                    5,
                    f"{label}:"
                )

                pdf.cell(
                    145,
                    5,
                    pdf_safe(value),
                    ln=True
                )

    if invoice.get("notes"):

        pdf.ln(8)

        pdf.set_font(
            "Arial",
            "B",
            9
        )

        pdf.cell(
            190,
            5,
            "Notes",
            ln=True
        )

        pdf.set_font(
            "Arial",
            "",
            9
        )

        pdf.multi_cell(
            190,
            5,
            pdf_safe(
                invoice["notes"]
            )
        )

    result = pdf.output(
        dest="S"
    )

    if isinstance(
        result,
        str
    ):
        return result.encode(
            "latin-1"
        )

    return bytes(result)


# ============================================================
# WHATSAPP MESSAGE
# ============================================================

def build_whatsapp_message(row):

    message = (
        f"Hi {row['customer']}, "
        f"this is a friendly reminder regarding "
        f"invoice {row['inv_number']}.\n\n"
        f"Invoice total: R{row['total']:,.2f}\n"
        f"Paid: R{row['amount_paid']:,.2f}\n"
        f"Outstanding: R{row['balance']:,.2f}\n"
        f"Due date: {row['due_date']}\n\n"
        f"Thank you."
    )

    phone = normalize_sa_phone(
        row["phone"]
    )

    link = (
        f"https://wa.me/{phone}"
        f"?text={quote(message)}"
    )

    return message, link


# ============================================================
# APP INITIALISATION
# ============================================================

init_db()

refresh_invoice_statuses()

business = get_business_profile()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title("PayTrack Pro")

    st.caption(
        "SME Revenue Intelligence"
    )

    st.divider()

    with st.expander(
        "⚙️ Business Settings",
        expanded=not bool(business)
    ):

        with st.form(
            "business_profile_form"
        ):

            business_name = st.text_input(
                "Business Name",
                value=business.get(
                    "business_name",
                    ""
                )
            )

            business_phone = st.text_input(
                "Phone",
                value=business.get(
                    "phone",
                    ""
                )
            )

            business_email = st.text_input(
                "Email",
                value=business.get(
                    "email",
                    ""
                )
            )

            business_address = st.text_area(
                "Address",
                value=business.get(
                    "address",
                    ""
                )
            )

            vat_number = st.text_input(
                "VAT Number",
                value=business.get(
                    "vat_number",
                    ""
                )
            )

            st.markdown(
                "**Banking Details**"
            )

            bank_name = st.text_input(
                "Bank",
                value=business.get(
                    "bank_name",
                    ""
                )
            )

            account_name = st.text_input(
                "Account Name",
                value=business.get(
                    "account_name",
                    ""
                )
            )

            account_number = st.text_input(
                "Account Number",
                value=business.get(
                    "account_number",
                    ""
                )
            )

            branch_code = st.text_input(
                "Branch Code",
                value=business.get(
                    "branch_code",
                    ""
                )
            )

            save_profile = st.form_submit_button(
                "Save Business Profile",
                use_container_width=True
            )

            if save_profile:

                if not business_name.strip():

                    st.error(
                        "Business name is required."
                    )

                elif (
                    business_email and
                    not valid_email(
                        business_email
                    )
                ):

                    st.error(
                        "Please enter a valid email address."
                    )

                else:

                    save_business_profile({
                        "business_name":
                            business_name.strip(),

                        "phone":
                            business_phone.strip(),

                        "email":
                            business_email.strip(),

                        "address":
                            business_address.strip(),

                        "vat_number":
                            vat_number.strip(),

                        "bank_name":
                            bank_name.strip(),

                        "account_name":
                            account_name.strip(),

                        "account_number":
                            account_number.strip(),

                        "branch_code":
                            branch_code.strip()
                    })

                    st.success(
                        "Business profile saved."
                    )

                    st.rerun()


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<p class="app-title">PayTrack Pro</p>',
    unsafe_allow_html=True
)

st.markdown(
    """
    <p class="app-subtitle">
        Invoicing • Payment Tracking • Revenue Analytics • Debtor Intelligence
    </p>
    """,
    unsafe_allow_html=True
)


# ============================================================
# MAIN NAVIGATION
# ============================================================

tabs = st.tabs([
    "📊 Executive Dashboard",
    "➕ Create Invoice",
    "💰 Record Payment",
    "🧾 Invoice Explorer",
    "🧠 Risk & Forecast",
    "🗄️ Data & SQL"
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:

    summary = get_invoice_summary()

    if summary.empty:

        st.info(
            "Create your first invoice to activate the revenue dashboard."
        )

    else:

        total_invoiced = summary[
            "total"
        ].sum()

        total_collected = summary[
            "amount_paid"
        ].sum()

        outstanding = summary[
            "balance"
        ].sum()

        overdue_balance = summary.loc[
            summary["status"] == "Overdue",
            "balance"
        ].sum()

        collection_rate = (
            total_collected /
            total_invoiced * 100
            if total_invoiced
            else 0
        )

        k1, k2, k3, k4, k5 = st.columns(
            5
        )

        k1.metric(
            "Total Invoiced",
            f"R {total_invoiced:,.2f}"
        )

        k2.metric(
            "Collected",
            f"R {total_collected:,.2f}"
        )

        k3.metric(
            "Outstanding",
            f"R {outstanding:,.2f}"
        )

        k4.metric(
            "Overdue Exposure",
            f"R {overdue_balance:,.2f}"
        )

        k5.metric(
            "Collection Rate",
            f"{collection_rate:.1f}%"
        )

        st.divider()

        left, right = st.columns(
            [1.4, 1]
        )

        # ---------------------------------
        # MONTHLY REVENUE
        # ---------------------------------

        with left:

            st.subheader(
                "Revenue Performance"
            )

            monthly = summary.copy()

            monthly[
                "issue_date"
            ] = pd.to_datetime(
                monthly["issue_date"]
            )

            monthly["month"] = (
                monthly["issue_date"]
                .dt.to_period("M")
                .astype(str)
            )

            monthly = (
                monthly.groupby(
                    "month"
                )[
                    [
                        "total",
                        "amount_paid"
                    ]
                ]
                .sum()
                .rename(
                    columns={
                        "total":
                            "Invoiced",

                        "amount_paid":
                            "Collected"
                    }
                )
            )

            st.bar_chart(
                monthly
            )

        # ---------------------------------
        # STATUS DISTRIBUTION
        # ---------------------------------

        with right:

            st.subheader(
                "Invoice Status"
            )

            status_counts = (
                summary[
                    "status"
                ]
                .value_counts()
                .rename_axis(
                    "Status"
                )
                .to_frame(
                    "Invoices"
                )
            )

            st.bar_chart(
                status_counts
            )

        st.divider()

        # ---------------------------------
        # AGING ANALYSIS
        # ---------------------------------

        st.subheader(
            "Debtor Aging Analysis"
        )

        aging = summary[
            summary["balance"] > 0
        ].copy()

        if not aging.empty:

            aging[
                "due_date_dt"
            ] = pd.to_datetime(
                aging["due_date"]
            )

            today_ts = pd.Timestamp(
                date.today()
            )

            aging[
                "days_overdue"
            ] = (
                today_ts -
                aging[
                    "due_date_dt"
                ]
            ).dt.days

            def aging_bucket(days):

                if days <= 0:
                    return "Current"

                if days <= 30:
                    return "1-30 Days"

                if days <= 60:
                    return "31-60 Days"

                return "61+ Days"

            aging[
                "aging_bucket"
            ] = aging[
                "days_overdue"
            ].apply(
                aging_bucket
            )

            aging_summary = (
                aging.groupby(
                    "aging_bucket"
                )[
                    "balance"
                ]
                .sum()
                .reindex(
                    [
                        "Current",
                        "1-30 Days",
                        "31-60 Days",
                        "61+ Days"
                    ],
                    fill_value=0
                )
                .to_frame(
                    "Outstanding (R)"
                )
            )

            st.bar_chart(
                aging_summary
            )

            overdue_table = aging[
                [
                    "inv_number",
                    "customer",
                    "due_date",
                    "balance",
                    "days_overdue",
                    "status"
                ]
            ].sort_values(
                "days_overdue",
                ascending=False
            )

            st.dataframe(
                overdue_table,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "There are currently no outstanding invoices."
            )


# ============================================================
# CREATE INVOICE
# ============================================================

with tabs[1]:

    st.subheader(
        "Create New Invoice"
    )

    customer_col, invoice_col = st.columns(
        2
    )

    with customer_col:

        st.markdown(
            "### Customer"
        )

        customer_name = st.text_input(
            "Customer Name *"
        )

        customer_phone = st.text_input(
            "Customer Phone"
        )

        customer_email = st.text_input(
            "Customer Email"
        )

    with invoice_col:

        st.markdown(
            "### Invoice"
        )

        issue_date = st.date_input(
            "Issue Date",
            value=date.today()
        )

        due_date = st.date_input(
            "Due Date",
            value=date.today() +
            timedelta(days=14)
        )

        notes = st.text_area(
            "Invoice Notes"
        )

    st.divider()

    st.markdown(
        "### Items / Services"
    )

    if "invoice_items" not in st.session_state:

        st.session_state[
            "invoice_items"
        ] = pd.DataFrame([
            {
                "Description": "",
                "Quantity": 1.0,
                "Unit Price": 0.0
            }
        ])

    edited_items = st.data_editor(
        st.session_state[
            "invoice_items"
        ],

        num_rows="dynamic",

        use_container_width=True,

        hide_index=True,

        column_config={

            "Description":
                st.column_config.TextColumn(
                    "Description",
                    required=True
                ),

            "Quantity":
                st.column_config.NumberColumn(
                    "Quantity",
                    min_value=0.01,
                    step=1.0
                ),

            "Unit Price":
                st.column_config.NumberColumn(
                    "Unit Price (R)",
                    min_value=0.0,
                    format="R %.2f"
                )
        }
    )

    cleaned_items = []

    for _, row in edited_items.iterrows():

        description = clean_text(
            row.get(
                "Description",
                ""
            )
        )

        try:
            quantity = float(
                row.get(
                    "Quantity",
                    0
                )
            )

            unit_price = float(
                row.get(
                    "Unit Price",
                    0
                )
            )

        except (
            ValueError,
            TypeError
        ):
            continue

        if (
            description
            and quantity > 0
            and unit_price >= 0
        ):

            cleaned_items.append({
                "description":
                    description,

                "quantity":
                    quantity,

                "unit_price":
                    unit_price,

                "line_total":
                    quantity *
                    unit_price
            })

    subtotal = sum(
        item["line_total"]
        for item in cleaned_items
    )

    calc1, calc2, calc3 = st.columns(
        3
    )

    with calc1:

        discount_pct = st.number_input(
            "Discount %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=1.0
        )

    with calc2:

        apply_vat = st.checkbox(
            "Apply VAT"
        )

        vat_rate = (
            15.0
            if apply_vat
            else 0.0
        )

    discount_amount = (
        subtotal *
        discount_pct /
        100
    )

    taxable = (
        subtotal -
        discount_amount
    )

    vat_amount = (
        taxable *
        vat_rate /
        100
    )

    total = (
        taxable +
        vat_amount
    )

    with calc3:

        initial_payment = st.number_input(
            "Initial Payment (R)",
            min_value=0.0,
            max_value=float(
                max(total, 0)
            ),
            value=0.0,
            step=50.0
        )

    m1, m2, m3, m4 = st.columns(
        4
    )

    m1.metric(
        "Subtotal",
        f"R {subtotal:,.2f}"
    )

    m2.metric(
        "Discount",
        f"R {discount_amount:,.2f}"
    )

    m3.metric(
        "VAT",
        f"R {vat_amount:,.2f}"
    )

    m4.metric(
        "Invoice Total",
        f"R {total:,.2f}"
    )

    if st.button(
        "Generate & Save Invoice",
        type="primary",
        use_container_width=True
    ):

        errors = []

        if not customer_name.strip():
            errors.append(
                "Customer name is required."
            )

        if (
            customer_email and
            not valid_email(
                customer_email
            )
        ):
            errors.append(
                "Customer email is invalid."
            )

        if due_date < issue_date:
            errors.append(
                "Due date cannot be before issue date."
            )

        if not cleaned_items:
            errors.append(
                "Add at least one valid invoice item."
            )

        if total <= 0:
            errors.append(
                "Invoice total must be greater than zero."
            )

        if errors:

            for error in errors:
                st.error(error)

        else:

            invoice_id, inv_number = (
                create_invoice_record(
                    customer={
                        "name":
                            customer_name,

                        "phone":
                            customer_phone,

                        "email":
                            customer_email
                    },

                    issue_date=
                        issue_date.isoformat(),

                    due_date=
                        due_date.isoformat(),

                    items=
                        cleaned_items,

                    discount_pct=
                        discount_pct,

                    vat_rate=
                        vat_rate,

                    notes=
                        notes,

                    initial_payment=
                        initial_payment
                )
            )

            st.success(
                f"{inv_number} created successfully."
            )

            pdf_bytes = create_pdf(
                invoice_id
            )

            st.download_button(
                "📄 Download Invoice PDF",
                data=pdf_bytes,
                file_name=
                    f"{inv_number}.pdf",
                mime="application/pdf"
            )

            updated_summary = (
                get_invoice_summary()
            )

            invoice_row = (
                updated_summary[
                    updated_summary[
                        "invoice_id"
                    ] == invoice_id
                ].iloc[0]
            )

            message, wa_link = (
                build_whatsapp_message(
                    invoice_row
                )
            )

            st.markdown(
                f"### WhatsApp Message"
            )

            st.code(
                message
            )

            if customer_phone:

                st.link_button(
                    "📱 Open in WhatsApp",
                    wa_link
                )


# ============================================================
# RECORD PAYMENT
# ============================================================

with tabs[2]:

    st.subheader(
        "Record Customer Payment"
    )

    summary = get_invoice_summary()

    outstanding_df = summary[
        summary["balance"] > 0.005
    ].copy()

    if outstanding_df.empty:

        st.success(
            "There are no outstanding invoices."
        )

    else:

        outstanding_df[
            "label"
        ] = (
            outstanding_df[
                "inv_number"
            ]
            + " — "
            + outstanding_df[
                "customer"
            ]
            + " — R"
            + outstanding_df[
                "balance"
            ]
            .map(
                lambda x:
                f"{x:,.2f}"
            )
        )

        selected_label = st.selectbox(
            "Select Invoice",
            outstanding_df[
                "label"
            ]
        )

        selected = (
            outstanding_df[
                outstanding_df[
                    "label"
                ] == selected_label
            ].iloc[0]
        )

        p1, p2, p3 = st.columns(
            3
        )

        p1.metric(
            "Invoice Total",
            f"R {selected['total']:,.2f}"
        )

        p2.metric(
            "Already Paid",
            f"R {selected['amount_paid']:,.2f}"
        )

        p3.metric(
            "Outstanding",
            f"R {selected['balance']:,.2f}"
        )

        payment_amount = st.number_input(
            "Payment Amount (R)",
            min_value=0.01,
            max_value=float(
                selected[
                    "balance"
                ]
            ),
            value=float(
                selected[
                    "balance"
                ]
            ),
            step=50.0
        )

        payment_date = st.date_input(
            "Payment Date",
            value=date.today(),
            key="payment_date"
        )

        payment_method = st.selectbox(
            "Payment Method",
            [
                "EFT",
                "Cash",
                "Card",
                "Bank Deposit",
                "Other"
            ]
        )

        payment_reference = st.text_input(
            "Payment Reference"
        )

        if st.button(
            "Record Payment",
            type="primary"
        ):

            record_payment(
                int(
                    selected[
                        "invoice_id"
                    ]
                ),
                float(
                    payment_amount
                ),
                payment_date.isoformat(),
                payment_method,
                payment_reference
            )

            st.success(
                "Payment successfully recorded."
            )

            st.rerun()


# ============================================================
# INVOICE EXPLORER
# ============================================================

with tabs[3]:

    st.subheader(
        "Invoice Explorer"
    )

    summary = get_invoice_summary()

    if summary.empty:

        st.info(
            "No invoices available."
        )

    else:

        f1, f2 = st.columns(
            [1, 2]
        )

        status_filter = f1.multiselect(
            "Status",
            [
                "Paid",
                "Partially Paid",
                "Unpaid",
                "Overdue"
            ],
            default=[
                "Paid",
                "Partially Paid",
                "Unpaid",
                "Overdue"
            ]
        )

        customer_search = f2.text_input(
            "Search customer or invoice number"
        )

        filtered = summary[
            summary[
                "status"
            ].isin(
                status_filter
            )
        ].copy()

        if customer_search:

            search = (
                customer_search
                .lower()
                .strip()
            )

            filtered = filtered[
                filtered[
                    "customer"
                ]
                .str.lower()
                .str.contains(
                    search,
                    na=False
                )

                |

                filtered[
                    "inv_number"
                ]
                .str.lower()
                .str.contains(
                    search,
                    na=False
                )
            ]

        display = filtered[
            [
                "inv_number",
                "issue_date",
                "due_date",
                "customer",
                "total",
                "amount_paid",
                "balance",
                "status"
            ]
        ].copy()

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "⬇️ Export Invoice Data",
            data=filtered.to_csv(
                index=False
            ).encode(
                "utf-8"
            ),
            file_name=
                "paytrack_invoices.csv",
            mime="text/csv"
        )

        st.divider()

        if not filtered.empty:

            options = {
                (
                    f"{row.inv_number} — "
                    f"{row.customer}"
                ):
                int(
                    row.invoice_id
                )

                for row in filtered.itertuples()
            }

            selected_invoice = (
                st.selectbox(
                    "View Invoice",
                    list(
                        options.keys()
                    )
                )
            )

            invoice_id = options[
                selected_invoice
            ]

            data = get_invoice_details(
                invoice_id
            )

            inv = data["invoice"]

            i1, i2, i3 = st.columns(
                3
            )

            payments_total = sum(
                p["amount"]
                for p in data[
                    "payments"
                ]
            )

            i1.metric(
                "Total",
                f"R {inv['total']:,.2f}"
            )

            i2.metric(
                "Paid",
                f"R {payments_total:,.2f}"
            )

            i3.metric(
                "Balance",
                f"R {max(inv['total'] - payments_total, 0):,.2f}"
            )

            st.markdown(
                "#### Invoice Items"
            )

            st.dataframe(
                pd.DataFrame(
                    data["items"]
                )[
                    [
                        "description",
                        "quantity",
                        "unit_price",
                        "line_total"
                    ]
                ],

                use_container_width=True,

                hide_index=True
            )

            if data["payments"]:

                st.markdown(
                    "#### Payment History"
                )

                payments_df = pd.DataFrame(
                    data["payments"]
                )

                st.dataframe(
                    payments_df[
                        [
                            "paid_on",
                            "amount",
                            "payment_method",
                            "reference"
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True
                )

            pdf_bytes = create_pdf(
                invoice_id
            )

            st.download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=
                    f"{inv['inv_number']}.pdf",
                mime="application/pdf"
            )

# ============================================================
# PAYMENT RISK & CASH FLOW FORECAST
# ============================================================

with tabs[4]:

    st.subheader(
        "Payment Risk & Cash-Flow Intelligence"
    )

    st.caption(
        f"Explainable payment-risk model v{RISK_MODEL_VERSION}. "
        "Scores are generated from invoice behaviour, payment history, "
        "overdue exposure and outstanding balances."
    )

    risk_df = calculate_payment_risk()

    if risk_df.empty:

        st.info(
            "Create invoices and record payment history "
            "to activate the risk model."
        )

    else:

        open_risk = risk_df[
            risk_df[
                "balance"
            ] > 0.005
        ].copy()

        if open_risk.empty:

            st.success(
                "All invoices are currently fully paid."
            )

        else:

            # ----------------------------------------
            # RISK KPIs
            # ----------------------------------------

            high_risk = (
                open_risk[
                    "risk_level"
                ] == "HIGH RISK"
            ).sum()

            medium_risk = (
                open_risk[
                    "risk_level"
                ] == "MEDIUM RISK"
            ).sum()

            low_risk = (
                open_risk[
                    "risk_level"
                ] == "LOW RISK"
            ).sum()

            risk_exposure = (
                open_risk.loc[
                    open_risk[
                        "risk_level"
                    ] == "HIGH RISK",
                    "balance"
                ].sum()
            )

            r1, r2, r3, r4 = st.columns(
                4
            )

            r1.metric(
                "Low Risk",
                int(
                    low_risk
                )
            )

            r2.metric(
                "Medium Risk",
                int(
                    medium_risk
                )
            )

            r3.metric(
                "High Risk",
                int(
                    high_risk
                )
            )

            r4.metric(
                "High-Risk Exposure",
                f"R {risk_exposure:,.2f}"
            )

            st.divider()

            # ----------------------------------------
            # PORTFOLIO RISK DISTRIBUTION
            # ----------------------------------------

            left, right = st.columns(
                [1, 1.5]
            )

            with left:

                st.markdown(
                    "### Risk Distribution"
                )

                risk_distribution = (
                    open_risk[
                        "risk_level"
                    ]
                    .value_counts()
                    .reindex(
                        [
                            "LOW RISK",
                            "MEDIUM RISK",
                            "HIGH RISK"
                        ],
                        fill_value=0
                    )
                    .to_frame(
                        "Invoices"
                    )
                )

                st.bar_chart(
                    risk_distribution
                )

            with right:

                st.markdown(
                    "### Highest-Risk Invoices"
                )

                risk_table = (
                    open_risk[
                        [
                            "inv_number",
                            "customer",
                            "balance",
                            "days_overdue",
                            "avg_payment_delay",
                            "risk_score",
                            "risk_level",
                            "risk_reason"
                        ]
                    ]
                    .sort_values(
                        "risk_score",
                        ascending=False
                    )
                )

                st.dataframe(
                    risk_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={

                        "inv_number":
                            "Invoice",

                        "customer":
                            "Customer",

                        "balance":
                            st.column_config.NumberColumn(
                                "Outstanding",
                                format="R %.2f"
                            ),

                        "days_overdue":
                            "Days Overdue",

                        "avg_payment_delay":
                            st.column_config.NumberColumn(
                                "Avg Historic Delay",
                                format="%.1f days"
                            ),

                        "risk_score":
                            st.column_config.ProgressColumn(
                                "Risk Score",
                                min_value=0,
                                max_value=100,
                                format="%.1f"
                            ),

                        "risk_level":
                            "Risk Level",

                        "risk_reason":
                            "Risk Drivers"
                    }
                )

            st.divider()

            # =================================================
            # CASH FLOW FORECAST
            # =================================================

            st.markdown(
                "## Cash-Flow Forecast"
            )

            forecast = (
                generate_cashflow_forecast()
            )

            if not forecast.empty:

                today_ts = pd.Timestamp(
                    date.today()
                )

                seven_days = (
                    today_ts +
                    pd.Timedelta(
                        days=7
                    )
                )

                thirty_days = (
                    today_ts +
                    pd.Timedelta(
                        days=30
                    )
                )

                sixty_days = (
                    today_ts +
                    pd.Timedelta(
                        days=60
                    )
                )

                forecast_7 = (
                    forecast.loc[
                        forecast[
                            "expected_collection_date"
                        ] <= seven_days,
                        "expected_cash"
                    ].sum()
                )

                forecast_30 = (
                    forecast.loc[
                        forecast[
                            "expected_collection_date"
                        ] <= thirty_days,
                        "expected_cash"
                    ].sum()
                )

                forecast_60 = (
                    forecast.loc[
                        forecast[
                            "expected_collection_date"
                        ] <= sixty_days,
                        "expected_cash"
                    ].sum()
                )

                total_expected = (
                    forecast[
                        "expected_cash"
                    ].sum()
                )

                c1, c2, c3, c4 = (
                    st.columns(
                        4
                    )
                )

                c1.metric(
                    "Expected Next 7 Days",
                    f"R {forecast_7:,.2f}"
                )

                c2.metric(
                    "Expected Next 30 Days",
                    f"R {forecast_30:,.2f}"
                )

                c3.metric(
                    "Expected Next 60 Days",
                    f"R {forecast_60:,.2f}"
                )

                c4.metric(
                    "Risk-Adjusted Receivables",
                    f"R {total_expected:,.2f}"
                )

                # -----------------------------------------
                # FORECAST BY MONTH
                # -----------------------------------------

                forecast[
                    "forecast_month"
                ] = (
                    forecast[
                        "expected_collection_date"
                    ]
                    .dt.to_period(
                        "M"
                    )
                    .astype(str)
                )

                monthly_forecast = (
                    forecast.groupby(
                        "forecast_month"
                    )[
                        [
                            "balance",
                            "expected_cash"
                        ]
                    ]
                    .sum()
                    .rename(
                        columns={
                            "balance":
                                "Outstanding Receivables",

                            "expected_cash":
                                "Risk Adjusted Forecast"
                        }
                    )
                )

                st.markdown(
                    "### Forecasted Collections"
                )

                st.bar_chart(
                    monthly_forecast
                )

                # -----------------------------------------
                # FORECAST DETAIL
                # -----------------------------------------

                st.markdown(
                    "### Collection Forecast Detail"
                )

                forecast_display = (
                    forecast[
                        [
                            "inv_number",
                            "customer",
                            "balance",
                            "risk_level",
                            "risk_score",
                            "expected_collection_date",
                            "collection_probability",
                            "expected_cash"
                        ]
                    ]
                    .sort_values(
                        "expected_collection_date"
                    )
                )

                forecast_display[
                    "collection_probability"
                ] *= 100

                st.dataframe(
                    forecast_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={

                        "inv_number":
                            "Invoice",

                        "customer":
                            "Customer",

                        "balance":
                            st.column_config.NumberColumn(
                                "Outstanding",
                                format="R %.2f"
                            ),

                        "risk_level":
                            "Risk",

                        "risk_score":
                            st.column_config.ProgressColumn(
                                "Risk Score",
                                min_value=0,
                                max_value=100
                            ),

                        "expected_collection_date":
                            st.column_config.DateColumn(
                                "Predicted Collection Date"
                            ),

                        "collection_probability":
                            st.column_config.ProgressColumn(
                                "Collection Probability",
                                min_value=0,
                                max_value=100,
                                format="%.0f%%"
                            ),

                        "expected_cash":
                            st.column_config.NumberColumn(
                                "Expected Cash",
                                format="R %.2f"
                            )
                    }
                )

            st.divider()

            # -----------------------------------------
            # MODEL EXPLANATION
            # -----------------------------------------

            with st.expander(
                "How does the risk model work?"
            ):

                st.markdown(
                    """
                    **PayTrack Payment Risk Model**

                    The score ranges from **0 to 100**.

                    | Factor | Maximum contribution |
                    |---|---:|
                    | Current overdue period | 35 |
                    | Historical late-payment rate | 25 |
                    | Average historical payment delay | 20 |
                    | Current invoice outstanding ratio | 10 |
                    | Historical unpaid invoice rate | 10 |

                    **Risk classification**

                    - **LOW RISK:** 0–29
                    - **MEDIUM RISK:** 30–59
                    - **HIGH RISK:** 60–100

                    The model is deliberately explainable rather than
                    a black-box model. Each score can be traced back
                    to actual payment behaviour.

                    The cash-flow forecast then combines expected
                    payment timing with a risk-based collection
                    probability.
                    """
                )

# ============================================================
# DATA & SQL
# ============================================================

with tabs[5]:

    st.subheader(
        "Data Engineering & SQL Analytics"
    )

    st.caption(
        "This section demonstrates the relational data model and SQL analytics powering PayTrack Pro."
    )

    sql_query = """
WITH payment_summary AS (
    SELECT
        invoice_id,
        SUM(amount) AS total_collected
    FROM payments
    GROUP BY invoice_id
),

invoice_summary AS (
    SELECT
        i.id AS invoice_id,
        i.customer_id,
        i.total,

        COALESCE(
            p.total_collected,
            0
        ) AS total_collected

    FROM invoices i

    LEFT JOIN payment_summary p
        ON p.invoice_id = i.id
)

SELECT
    c.name AS customer,

    COUNT(
        i.invoice_id
    ) AS invoice_count,

    SUM(
        i.total
    ) AS total_invoiced,

    SUM(
        i.total_collected
    ) AS total_collected,

    SUM(
        i.total -
        i.total_collected
    ) AS outstanding

FROM customers c

JOIN invoice_summary i
    ON i.customer_id = c.id

GROUP BY
    c.id,
    c.name

ORDER BY
    total_invoiced DESC;
"""

    st.markdown(
        "### Customer Revenue SQL"
    )

    st.code(
        sql_query,
        language="sql"
    )

    with get_connection() as conn:

        customer_analytics = pd.read_sql_query(
            sql_query,
            conn
        )

    if not customer_analytics.empty:

        st.dataframe(
            customer_analytics,
            use_container_width=True,
            hide_index=True
        )

        top_customers = (
            customer_analytics
            .set_index("customer")[
                [
                    "total_invoiced",
                    "total_collected"
                ]
            ]
        )

        st.bar_chart(
            top_customers
        )

    st.divider()

    st.markdown(
        "### Database Health"
    )

    with get_connection() as conn:

        table_counts = {}

        for table in [
            "customers",
            "invoices",
            "invoice_items",
            "payments",
            "audit_log"
        ]:

            table_counts[table] = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {table}
                """
            ).fetchone()[0]

    database_metrics = st.columns(
        len(table_counts)
    )

    for metric, (table, count) in zip(
        database_metrics,
        table_counts.items()
    ):

        metric.metric(
            table.replace(
                "_",
                " "
            ).title(),
            count
        )

    st.divider()

    st.markdown(
        "### Audit Trail"
    )

    with get_connection() as conn:

        audit_df = pd.read_sql_query(
            """
            SELECT
                created_at,
                event_type,
                entity_type,
                entity_id,
                details

            FROM audit_log

            ORDER BY id DESC

            LIMIT 100
            """,
            conn
        )

    if not audit_df.empty:

        st.dataframe(
            audit_df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Audit events will appear here as the application is used."
        )