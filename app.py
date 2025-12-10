import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime, timedelta

# =========================
# BASIC APP CONFIG & STYLE
# =========================

st.set_page_config(
    page_title="Welcome to Technique Iron Works",
    page_icon="👷‍♂️",
    layout="wide"
)

# Custom CSS for animated sidebar navigation
st.markdown("""
<style>
/* Default sidebar button */
.stButton > button {
    width: 100%;
    border-radius: 6px;
    background-color: #FA7F6B;
    color: white;
    font-weight: 600;
    gap: 0rem;
    border: 1px solid #D16B5A;
    margin: -20px 0 !important;
    transition: 0.25s ease;
    
}

/* Hover animation */
.stButton > button:hover {
    background-color: #D16B5A;
    transform: translateX(6px);
}

/* ACTIVE TAB BUTTON */
.active-tab > button {
    background-color: #fff !important;
    color: white !important;
    border: 1px solid #049E52 !important;
    transform: translateX(8px);
}
</style>
""", unsafe_allow_html=True)


st.markdown(
    """
    <style>
    .big-metric {
        font-size: 26px !important;
        font-weight: 700 !important;
    }
    .semi-bold {
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================
# DATABASE HELPERS (SQLite)
# =========================

DB_NAME = "hrms_accounts.db"


def dict_factory(cursor, row):
    """Return rows as dict instead of tuples."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


@st.cache_resource
def get_connection():
    """Create and cache a single DB connection for the app."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = dict_factory
    return conn


def init_db(conn):
    """Create tables if they do not exist."""
    cur = conn.cursor()

    # Workers master
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            join_date TEXT,
            daily_rate REAL NOT NULL,
            is_active INTEGER DEFAULT 1
        );
        """
    )

    # Daily attendance
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,      -- Present / Absent / Leave / Half-Day
            hours REAL,
            FOREIGN KEY(worker_id) REFERENCES workers(id)
        );
        """
    )

    # Transactions: purchases, expenses, income, etc.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,        -- INCOME / EXPENSE
            category TEXT NOT NULL,    -- Purchase / Expense / Other
            amount REAL NOT NULL,
            description TEXT
        );
        """
    )

    # Payments and Advances to workers
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,       -- PAYMENT / ADVANCE
            notes TEXT,
            FOREIGN KEY(worker_id) REFERENCES workers(id)
        );
        """
    )

    # Simple key-value Settings for thresholds, etc.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    conn.commit()


def run_query(conn, query, params=(), fetch: str = "none"):
    """
    Generic helper to run queries.
    fetch = "none" / "one" / "all"
    """
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()

    if fetch == "one":
        return cur.fetchone()
    elif fetch == "all":
        return cur.fetchall()
    return None


# =========================
# SETTINGS HELPERS
# =========================

def get_setting(conn, key, default=None):
    row = run_query(
        conn,
        "SELECT value FROM settings WHERE key = ?",
        (key,),
        fetch="one"
    )
    if row and "value" in row:
        try:
            return float(row["value"])
        except ValueError:
            return row["value"]
    return default


def set_setting(conn, key, value):
    run_query(
        conn,
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
        fetch="none"
    )


# =========================
# BUSINESS LOGIC FUNCTIONS
# =========================

def get_workers_df(conn, active_only=True):
    query = "SELECT * FROM workers"
    params = ()
    if active_only:
        query += " WHERE is_active = 1"
    rows = run_query(conn, query, params, fetch="all")
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def get_transactions_df(conn, start_date=None, end_date=None):
    """Load transactions as DataFrame with optional date filter."""
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if start_date:
        query += " AND date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date <= ?"
        params.append(end_date.isoformat())

    rows = run_query(conn, query, tuple(params), fetch="all")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df

def get_expense_totals(conn):
    """
    Return dict with expense totals:
    - today_expense
    - month_expense (current calendar month)
    - fy_expense (current financial year, assumed Apr 1 -> Mar 31)
    """
    today = date.today()
    # Today
    tx_today = get_transactions_df(conn, start_date=today, end_date=today)
    today_expense = float(tx_today[tx_today["type"] == "EXPENSE"]["amount"].sum()) if not tx_today.empty else 0.0

    # Current month start and end
    month_start = today.replace(day=1)
    month_end = today
    tx_month = get_transactions_df(conn, start_date=month_start, end_date=month_end)
    month_expense = float(tx_month[tx_month["type"] == "EXPENSE"]["amount"].sum()) if not tx_month.empty else 0.0

    # Financial year start (Apr 1) to today
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
    else:
        fy_start = date(today.year - 1, 4, 1)
    tx_fy = get_transactions_df(conn, start_date=fy_start, end_date=today)
    fy_expense = float(tx_fy[tx_fy["type"] == "EXPENSE"]["amount"].sum()) if not tx_fy.empty else 0.0

    return {
        "today_expense": round(today_expense, 2),
        "month_expense": round(month_expense, 2),
        "fy_expense": round(fy_expense, 2),
        "fy_start": fy_start
    }



def get_attendance_df(conn, for_date=None):
    query = """
        SELECT a.id, a.date, a.status, a.hours, w.name AS worker_name, w.role
        FROM attendance a
        JOIN workers w ON a.worker_id = w.id
        WHERE 1=1
    """
    params = []
    if for_date:
        query += " AND a.date = ?"
        params.append(for_date.isoformat())

    rows = run_query(conn, query, tuple(params), fetch="all")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_attendance_range_df(conn, start_date, end_date):
    """Attendance for a period, joined with worker data."""
    query = """
        SELECT a.id, a.worker_id, a.date, a.status, a.hours,
               w.name AS worker_name, w.role, w.daily_rate
        FROM attendance a
        JOIN workers w ON a.worker_id = w.id
        WHERE a.date >= ? AND a.date <= ?
    """
    params = (start_date.isoformat(), end_date.isoformat())
    rows = run_query(conn, query, params, fetch="all")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_worker_payments_df(conn, worker_id=None):
    query = """
        SELECT wp.*, w.name AS worker_name
        FROM worker_payments wp
        JOIN workers w ON wp.worker_id = w.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        query += " AND wp.worker_id = ?"
        params.append(worker_id)

    rows = run_query(conn, query, tuple(params), fetch="all")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_worker_payments_range_df(conn, start_date, end_date):
    """All worker payments in a period."""
    query = """
        SELECT wp.*, w.name AS worker_name
        FROM worker_payments wp
        JOIN workers w ON wp.worker_id = w.id
        WHERE wp.date >= ? AND wp.date <= ?
    """
    params = (start_date.isoformat(), end_date.isoformat())
    rows = run_query(conn, query, params, fetch="all")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def calculate_summary_metrics(conn):
    """Calculate KPIs for the dashboard."""
    today = date.today()
    start_of_month = today.replace(day=1)

    workers = get_workers_df(conn, active_only=True)
    total_workers = len(workers)

    # Today attendance
    att_today = get_attendance_df(conn, for_date=today)
    present_today = len(att_today[att_today["status"] == "Present"]) if not att_today.empty else 0
    absent_today = len(att_today[att_today["status"] == "Absent"]) if not att_today.empty else 0

    # Transactions for this month
    tx_month = get_transactions_df(conn, start_date=start_of_month, end_date=today)
    total_expense_month = 0.0
    total_income_month = 0.0

    if not tx_month.empty:
        total_expense_month = tx_month[tx_month["type"] == "EXPENSE"]["amount"].sum()
        total_income_month = tx_month[tx_month["type"] == "INCOME"]["amount"].sum()

    profit_month = total_income_month - total_expense_month

    return {
        "total_workers": total_workers,
        "present_today": present_today,
        "absent_today": absent_today,
        "total_expense_month": total_expense_month,
        "total_income_month": total_income_month,
        "profit_month": profit_month,
    }


def check_notifications(conn):
    """Return notification messages for high usage / heavy flows."""
    msgs = []

    today = date.today()
    last_30 = today - timedelta(days=30)

    tx = get_transactions_df(conn, start_date=last_30, end_date=today)
    if tx.empty:
        return msgs

    # Today's expenses
    tx_today = tx[tx["date"].dt.date == today]
    today_expense = tx_today[tx_today["type"] == "EXPENSE"]["amount"].sum()

    # Average daily expense (last 30 days)
    if len(tx) > 0:
        daily_expenses = tx[tx["type"] == "EXPENSE"].groupby(tx["date"].dt.date)["amount"].sum()
        if len(daily_expenses) > 0:
            avg_daily_expense = daily_expenses.mean()
        else:
            avg_daily_expense = 0
    else:
        avg_daily_expense = 0

    expense_threshold = get_setting(conn, "expense_threshold", default=avg_daily_expense * 1.5 if avg_daily_expense else 0)

    if expense_threshold and today_expense > expense_threshold:
        msgs.append(
            f"High daily expense alert: Today's expenses ({today_expense:.2f}) are above the threshold ({expense_threshold:.2f})."
        )

    # Heavy fund flows = total IN + OUT today
    total_out_today = today_expense
    total_in_today = tx_today[tx_today["type"] == "INCOME"]["amount"].sum()
    total_flow_today = total_out_today + total_in_today

    flow_threshold = get_setting(conn, "fund_flow_threshold", default=(avg_daily_expense * 2) if avg_daily_expense else 0)

    if flow_threshold and total_flow_today > flow_threshold:
        msgs.append(
            f"Heavy fund flow alert: Today's total flow ({total_flow_today:.2f}) is above the threshold ({flow_threshold:.2f})."
        )

    return msgs


def calculate_payroll(conn, start_date, end_date):
    """
    Calculate salary for each worker between start_date and end_date using hours + overtime logic.

    Rules:
    - Present: hours (default 8). Pay for up to 8 hours pro-rated from daily_rate,
      overtime for hours > 8 at rate = daily_rate / 8 per hour.
      So day_pay = min(hours,8)/8 * daily_rate + max(hours-8, 0) * (daily_rate/8)
    - Half-Day: day_pay = 0.5 * daily_rate (regardless of hours value)
    - Absent / Leave: day_pay = 0
    """
    workers_df = get_workers_df(conn, active_only=True)
    if workers_df.empty:
        return pd.DataFrame()

    # Attendance rows in period
    att_df = get_attendance_range_df(conn, start_date, end_date)
    # Payments (ADVANCE / PAYMENT) in period
    pay_df = get_worker_payments_range_df(conn, start_date, end_date)

    rows = []
    for _, w in workers_df.iterrows():
        wid = w["id"]
        w_name = w["name"]
        rate = float(w["daily_rate"])

        # Filter attendance for this worker
        w_att = att_df[att_df["worker_id"] == wid] if not att_df.empty else pd.DataFrame()

        gross_salary = 0.0
        days_present = 0
        half_days = 0
        overtime_hours_total = 0.0
        worked_days_equivalent = 0.0

        if not w_att.empty:
            # Iterate per day (in case multiple records per day, group by date and resolve)
            # We'll take the last attendance record per date if duplicates exist.
            w_att_by_day = (
                w_att.assign(att_day=w_att["date"].dt.date)
                    .sort_values("date")
                    .groupby("att_day")
                    .last()
                    .reset_index()
)


            for _, day_row in w_att_by_day.iterrows():
                status = day_row["status"]
                hours = float(day_row["hours"]) if day_row.get("hours") not in (None, "") else 8.0

                if status == "Present":
                    # default hours to 8 if user left it blank or zero
                    if hours <= 0:
                        hours = 8.0

                    base_hours = min(hours, 8.0)
                    overtime_hours = max(0.0, hours - 8.0)

                    base_pay = (base_hours / 8.0) * rate
                    overtime_pay = overtime_hours * (rate / 8.0)

                    day_pay = base_pay + overtime_pay

                    gross_salary += day_pay
                    days_present += 1 if base_hours > 0 else 0
                    overtime_hours_total += overtime_hours
                    worked_days_equivalent += (base_hours / 8.0) + (overtime_hours / 8.0)

                elif status == "Half-Day":
                    # Paid half of the daily rate
                    day_pay = 0.5 * rate
                    gross_salary += day_pay
                    half_days += 1
                    worked_days_equivalent += 0.5

                else:
                    # Absent or Leave => no pay
                    continue

        # Payments affecting salary period
        w_pay = pay_df[pay_df["worker_id"] == wid] if not pay_df.empty else pd.DataFrame()
        advances = float(w_pay[w_pay["type"] == "ADVANCE"]["amount"].sum()) if not w_pay.empty else 0.0
        payments = float(w_pay[w_pay["type"] == "PAYMENT"]["amount"].sum()) if not w_pay.empty else 0.0

        net_payable = gross_salary - advances - payments

        rows.append({
            "worker_id": wid,
            "worker_name": w_name,
            "daily_rate": rate,
            "days_present": days_present,
            "half_days": half_days,
            "overtime_hours": overtime_hours_total,
            "worked_days_equivalent": round(worked_days_equivalent, 3),
            "gross_salary": round(gross_salary, 2),
            "total_advance": round(advances, 2),
            "total_payment_done": round(payments, 2),
            "net_payable": round(net_payable, 2)
        })

    payroll_df = pd.DataFrame(rows)
    payroll_df = payroll_df.sort_values("worker_name")
    return payroll_df



# =========================
# UI: DASHBOARD PAGE
# =========================

def render_dashboard(conn):
    st.title("Technique Iron Works SAP")

    # Notifications section
    notifications = check_notifications(conn)
    if notifications:
        for msg in notifications:
            st.warning("🔔 " + msg)

    metrics = calculate_summary_metrics(conn)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.caption("Total Active Workers")
        st.markdown(f"<div class='big-metric'>{metrics['total_workers']}</div>", unsafe_allow_html=True)
    with col2:
        st.caption("Present Today")
        st.markdown(f"<div class='big-metric'>{metrics['present_today']}</div>", unsafe_allow_html=True)
    with col3:
        st.caption("Absent Today")
        st.markdown(f"<div class='big-metric'>{metrics['absent_today']}</div>", unsafe_allow_html=True)
    with col4:
        st.caption("This Month Profit")
        st.markdown(f"<div class='big-metric'>{metrics['profit_month']:.2f}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # Charts: Income vs Expense monthly & category-wise expenses
    st.subheader("Income vs Expenses (Last 3 Months)")

    today = date.today()
    three_months_back = today - timedelta(days=90)
    tx = get_transactions_df(conn, start_date=three_months_back, end_date=today)

    if tx.empty:
        st.info("No transactions data available yet. Add some in the Accounts section.")
        return

    tx["month"] = tx["date"].dt.to_period("M").dt.to_timestamp()
    monthly = tx.groupby(["month", "type"])["amount"].sum().reset_index()
    monthly_pivot = monthly.pivot(index="month", columns="type", values="amount").fillna(0)

    st.line_chart(monthly_pivot)

    st.subheader("Expenses by Category (Last 30 Days)")
    last_30 = today - timedelta(days=30)
    tx_30 = tx[tx["date"].dt.date >= last_30]
    tx_30_exp = tx_30[tx_30["type"] == "EXPENSE"]

    if not tx_30_exp.empty:
        cat_exp = tx_30_exp.groupby("category")["amount"].sum().reset_index()
        cat_exp = cat_exp.set_index("category")
        st.bar_chart(cat_exp)
    else:
        st.info("No expense data in the last 30 days.")


# =========================
# UI: WORKERS PAGE
# =========================

def render_workers(conn):
    st.title("Workers Management")

    tab_add, tab_manage = st.tabs(["➕ Add Worker", "🛠 Manage Workers"])

    # ---- Add Worker ----
    with tab_add:
        st.subheader("Add New Worker")

        with st.form("add_worker_form"):
            st.subheader("Personal Details")
            name = st.text_input("Worker Name *")
            father_name = st.text_input("Father's Name")
            mobile = st.text_input("Mobile Number")
            role = st.text_input("Role / Designation")
            site_alloc = st.text_input("Site Allocation")
            join_date = st.date_input("Joining Date", value=date.today())

            st.subheader("Account Details")
            account_number = st.text_input("Account Number")
            bank_name = st.text_input("Bank Name")
            ifsc_code = st.text_input("IFSC Code")

            st.subheader("Salary Details")
            daily_rate = st.number_input("Per Day Rate (₹) *", min_value=0.0, step=50.0)
            is_active = st.checkbox("Active", value=True)

            submitted = st.form_submit_button("Add Worker")

        if submitted:
            if not name or daily_rate <= 0:
                st.error("Name and Per Day Rate are mandatory.")
            else:
                run_query(
                    conn,
                    """
                    INSERT INTO workers 
                    (name, father_name, mobile, role, site_allocation, join_date, daily_rate, 
                    account_number, bank_name, ifsc_code, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, father_name, mobile, role, site_alloc, join_date.isoformat(),
                        daily_rate, account_number, bank_name, ifsc_code, 
                        1 if is_active else 0
                    )
                )
                st.success(f"Worker '{name}' added successfully.")


    # ---- Manage Workers ----
    with tab_manage:
        st.subheader("Workers List & Update")

        workers_df = get_workers_df(conn, active_only=False)
        if workers_df.empty:
            st.info("No workers added yet.")
            return

        st.dataframe(
            workers_df[
                [
                "id", "name", "father_name", "mobile", "role", "site_allocation",
                "join_date", "daily_rate",
                "account_number", "bank_name", "ifsc_code",
                "is_active"
                ]
            ]
            ,
            use_container_width=True
        )

        st.markdown("### Update Worker Details")
        worker_options = {f"{row['name']} (ID: {row['id']})": row["id"] for _, row in workers_df.iterrows()}
        selected_label = st.selectbox("Select a worker to update", options=list(worker_options.keys()))
        selected_id = worker_options[selected_label]

        w_row = workers_df[workers_df["id"] == selected_id].iloc[0]

        with st.form("update_worker_form"):
            st.subheader("Personal Details")
            new_name = st.text_input("Name", value=w_row["name"])
            new_father = st.text_input("Father's Name", value=w_row.get("father_name", "") or "")
            new_mobile = st.text_input("Mobile Number", value=w_row.get("mobile", "") or "")
            new_role = st.text_input("Role / Designation", value=w_row.get("role", "") or "")
            new_site = st.text_input("Site Allocation", value=w_row.get("site_allocation", "") or "")

            jd = datetime.strptime(w_row["join_date"], "%Y-%m-%d").date() if w_row.get("join_date") else date.today()
            new_join_date = st.date_input("Joining Date", value=jd)

            st.subheader("Account Details")
            new_acc = st.text_input("Account Number", value=w_row.get("account_number", "") or "")
            new_bank = st.text_input("Bank Name", value=w_row.get("bank_name", "") or "")
            new_ifsc = st.text_input("IFSC Code", value=w_row.get("ifsc_code", "") or "")

            st.subheader("Salary Details")
            new_daily_rate = st.number_input("Per Day Rate (₹)", min_value=0.0, step=50.0,
                                            value=float(w_row["daily_rate"]))
            new_active = st.checkbox("Active", value=bool(w_row["is_active"]))

            col_save, col_remove = st.columns(2)
            save = col_save.form_submit_button("Save Changes")
            remove = col_remove.form_submit_button("Mark as Inactive")

        if save:
            run_query(
                conn,
                """
                UPDATE workers 
                SET name=?, father_name=?, mobile=?, role=?, site_allocation=?, 
                    join_date=?, daily_rate=?, account_number=?, bank_name=?, ifsc_code=?, is_active=?
                WHERE id=?
                """,
                (
                    new_name, new_father, new_mobile, new_role, new_site,
                    new_join_date.isoformat(), new_daily_rate,
                    new_acc, new_bank, new_ifsc,
                    1 if new_active else 0, selected_id
                )
            )
            st.success("Worker details updated.")



# =========================
# UI: ATTENDANCE PAGE
# =========================

def render_attendance(conn):
    st.title("Attendance Management")

    workers_df = get_workers_df(conn, active_only=True)
    if workers_df.empty:
        st.info("No active workers found. Please add workers first in the Workers section.")
        return

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.subheader("Mark Attendance")

        with st.form("attendance_form"):
            att_date = st.date_input("Date", value=date.today())
            worker_label = st.selectbox(
                "Worker",
                options=[f"{row['name']} (ID: {row['id']})" for _, row in workers_df.iterrows()]
            )
            worker_id = int(worker_label.split("ID:")[1].strip(") "))

            status = st.selectbox(
                "Status",
                options=["Present", "Absent", "Leave", "Half-Day"],
                index=0
            )
            hours = st.number_input("Hours Worked (optional)", min_value=0.0, step=0.5, value=8.0)

            submit_att = st.form_submit_button("Save Attendance")

        if submit_att:
            # Check if record already exists
            existing = run_query(
                conn,
                "SELECT id FROM attendance WHERE worker_id = ? AND date = ?",
                (worker_id, att_date.isoformat()),
                fetch="one"
            )
            if existing:
                run_query(
                    conn,
                    """
                    UPDATE attendance SET status = ?, hours = ?
                    WHERE id = ?
                    """,
                    (status, hours, existing["id"])
                )
                st.success("Attendance updated for selected worker and date.")
            else:
                run_query(
                    conn,
                    """
                    INSERT INTO attendance (worker_id, date, status, hours)
                    VALUES (?, ?, ?, ?)
                    """,
                    (worker_id, att_date.isoformat(), status, hours)
                )
                st.success("Attendance marked successfully.")

    with col_right:
        st.subheader("Attendance Overview")

        view_date = st.date_input("View date", value=date.today(), key="view_date_att")
        att_df = get_attendance_df(conn, for_date=view_date)

        if att_df.empty:
            st.info("No attendance records for selected date.")
        else:
            st.dataframe(att_df[["worker_name", "role", "date", "status", "hours"]], use_container_width=True)


# =========================
# UI: ACCOUNTS PAGE
# =========================

def render_accounts(conn):
    st.title("Accounts & Transactions")

    tab_tx, tab_pay = st.tabs(["💸 Business Transactions", "👷 Worker Payments & Advances"])

    # ---- Business Transactions ----
    with tab_tx:
        st.subheader("Add Transaction (Purchase / Expense / Income, etc.)")

        with st.form("tx_form"):
            tx_date = st.date_input("Date", value=date.today())
            tx_type = st.selectbox("Type", ["EXPENSE", "INCOME"])
            category = st.text_input("Category (e.g., Purchase, Rent, Material, Other)")
            amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
            description = st.text_area("Description / Notes", height=80)

            submit_tx = st.form_submit_button("Save Transaction")

        if submit_tx:
            if not category or amount <= 0:
                st.error("Category and positive Amount are required.")
            else:
                run_query(
                    conn,
                    """
                    INSERT INTO transactions (date, type, category, amount, description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tx_date.isoformat(), tx_type, category, amount, description)
                )
                st.success("Transaction saved successfully.")

        st.markdown("---")
        st.subheader("Recent Transactions")

        start = st.date_input("From", value=date.today() - timedelta(days=30), key="tx_from")
        end = st.date_input("To", value=date.today(), key="tx_to")

        tx_df = get_transactions_df(conn, start_date=start, end_date=end)
        if tx_df.empty:
            st.info("No transactions in selected period.")
        else:
            st.dataframe(
                tx_df[["date", "type", "category", "amount", "description"]],
                use_container_width=True
            )

            csv = tx_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Transactions as CSV",
                data=csv,
                file_name=f"transactions_{start}_to_{end}.csv",
                mime="text/csv"
            )

    # ---- Worker Payments & Advances ----
    with tab_pay:
        st.subheader("Record Worker Payment / Advance")

        workers_df = get_workers_df(conn, active_only=False)
        if workers_df.empty:
            st.info("No workers found.")
        else:
            worker_option = st.selectbox(
                "Worker",
                options=[f"{row['name']} (ID: {row['id']})" for _, row in workers_df.iterrows()],
                key="pay_worker"
            )
            worker_id = int(worker_option.split("ID:")[1].strip(") "))

            with st.form("pay_form"):
                pay_date = st.date_input("Date", value=date.today())
                pay_type = st.selectbox("Type", ["PAYMENT", "ADVANCE"])
                pay_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
                notes = st.text_area("Notes", height=70)

                submit_pay = st.form_submit_button("Save Payment")

            if submit_pay:
                if pay_amount <= 0:
                    st.error("Amount must be > 0.")
                else:
                    run_query(
                        conn,
                        """
                        INSERT INTO worker_payments (worker_id, date, amount, type, notes)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (worker_id, pay_date.isoformat(), pay_amount, pay_type, notes)
                    )
                    st.success("Worker payment record saved.")

            st.markdown("---")
            st.subheader("Payment History")

            wp_df = get_worker_payments_df(conn, worker_id=None)
            if wp_df.empty:
                st.info("No payment records yet.")
            else:
                st.dataframe(
                    wp_df[["date", "worker_name", "type", "amount", "notes"]],
                    use_container_width=True
                )


# =========================
# UI: PAYROLL PAGE
# =========================

def render_payroll(conn):
    st.title("Payroll (Salary Calculation)")

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("From", value=date.today().replace(day=1))
    with col2:
        end = st.date_input("To", value=date.today())

    payroll_df = calculate_payroll(conn, start, end)

    if payroll_df.empty:
        st.info("No payroll data. Ensure workers, attendance, and daily rates are added.")
        return

    # Totals / subtotals
    subtotal_gross = float(payroll_df["gross_salary"].sum())
    total_advances = float(payroll_df["total_advance"].sum())
    total_payments_done = float(payroll_df["total_payment_done"].sum())
    net_total_payable = float(payroll_df["net_payable"].sum())

    st.subheader("Payroll Summary")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.caption("Subtotal (Gross Salaries)")
        st.markdown(f"<div class='big-metric'>₹{subtotal_gross:.2f}</div>", unsafe_allow_html=True)
    with k2:
        st.caption("Total Advances")
        st.markdown(f"<div class='big-metric'>₹{total_advances:.2f}</div>", unsafe_allow_html=True)
    with k3:
        st.caption("Total Payments Done")
        st.markdown(f"<div class='big-metric'>₹{total_payments_done:.2f}</div>", unsafe_allow_html=True)
    with k4:
        st.caption("Net Total Payable")
        st.markdown(f"<div class='big-metric'>₹{net_total_payable:.2f}</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Calculated Payroll Details")

    display_cols = [
        "worker_name",
        "daily_rate",
        "days_present",
        "half_days",
        "overtime_hours",
        "worked_days_equivalent",
        "gross_salary",
        "total_advance",
        "total_payment_done",
        "net_payable",
    ]
    df_show = payroll_df[display_cols].rename(columns={
        "worker_name": "Worker",
        "daily_rate": "Per Day Rate",
        "days_present": "Full Present Days",
        "half_days": "Half Days",
        "overtime_hours": "Overtime Hours",
        "worked_days_equivalent": "Worked Days (Eq.)",
        "gross_salary": "Gross Salary",
        "total_advance": "Total Advances",
        "total_payment_done": "Payments Done",
        "net_payable": "Net Payable",
    })
    st.dataframe(df_show, use_container_width=True)

    # Export payroll summary
    csv = payroll_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇ Download Payroll Summary as CSV",
        data=csv,
        file_name=f"payroll_{start}_to_{end}.csv",
        mime="text/csv"
    )

    st.markdown("---")
    st.subheader("Record Salary Payment for a Worker")

    # Choose worker and auto-fill recommended salary
    worker_options = {
        f"{row['worker_name']} (Net: ₹{row['net_payable']:.2f})": row["worker_id"]
        for _, row in payroll_df.iterrows()
    }
    selected_label = st.selectbox("Select worker to pay", options=list(worker_options.keys()))
    selected_id = worker_options[selected_label]

    selected_row = payroll_df[payroll_df["worker_id"] == selected_id].iloc[0]
    suggested_amount = max(selected_row["net_payable"], 0.0)

    with st.form("payroll_payment_form"):
        pay_date = st.date_input("Payment Date", value=date.today(), key="payroll_pay_date")
        amount_to_pay = st.number_input(
            "Amount to pay (₹)",
            min_value=0.0,
            value=float(suggested_amount),
            step=100.0
        )
        notes = st.text_area(
            "Notes",
            value=f"Salary payment for period {start} to {end}",
            height=70
        )
        submit = st.form_submit_button("Record Salary Payment")

    if submit:
        if amount_to_pay <= 0:
            st.error("Payment amount must be greater than 0.")
        else:
            run_query(
                conn,
                """
                INSERT INTO worker_payments (worker_id, date, amount, type, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (selected_id, pay_date.isoformat(), amount_to_pay, "PAYMENT", notes)
            )
            st.success(
                f"Salary payment of ₹{amount_to_pay:.2f} recorded for {selected_row['worker_name']}."
            )



# =========================
# UI: REPORTS & INSIGHTS
# =========================

def render_reports(conn):
    st.title("Reports & Daily Insights")

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("Report From", value=date.today() - timedelta(days=7))
    with col2:
        end = st.date_input("Report To", value=date.today())

    # Transactions summary
    tx_df = get_transactions_df(conn, start_date=start, end_date=end)
    if tx_df.empty:
        st.info("No transactions in this period.")
        return

    total_income = tx_df[tx_df["type"] == "INCOME"]["amount"].sum()
    total_expense = tx_df[tx_df["type"] == "EXPENSE"]["amount"].sum()
    profit = total_income - total_expense

    col_k1, col_k2, col_k3 = st.columns(3)
    with col_k1:
        st.caption("Total Income")
        st.markdown(f"<div class='big-metric'>₹{total_income:.2f}</div>", unsafe_allow_html=True)
    with col_k2:
        st.caption("Total Expense")
        st.markdown(f"<div class='big-metric'>₹{total_expense:.2f}</div>", unsafe_allow_html=True)
    with col_k3:
        st.caption("Net Profit")
        st.markdown(f"<div class='big-metric'>₹{profit:.2f}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # Daily summary table
    tx_df["day"] = tx_df["date"].dt.date
    daily_summary = tx_df.pivot_table(
        index="day",
        columns="type",
        values="amount",
        aggfunc="sum"
    ).fillna(0)
    daily_summary["PROFIT"] = daily_summary.get("INCOME", 0) - daily_summary.get("EXPENSE", 0)

    st.subheader("Daily Profit & Loss")
    st.dataframe(daily_summary, use_container_width=True)

    # Export daily summary
    csv_daily = daily_summary.reset_index().to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Daily Summary as CSV",
        data=csv_daily,
        file_name=f"daily_summary_{start}_to_{end}.csv",
        mime="text/csv"
    )

    st.subheader("Daily Profit Trend")
    st.line_chart(daily_summary["PROFIT"])

    # Category-wise insight
    st.subheader("Top Expense Categories")
    exp = tx_df[tx_df["type"] == "EXPENSE"]
    if not exp.empty:
        cat = exp.groupby("category")["amount"].sum().sort_values(ascending=False)
        st.bar_chart(cat)
    else:
        st.info("No expense records in this period.")


# =========================
# UI: SETTINGS PAGE
# =========================

def render_settings(conn):
    st.title("Settings & Notifications Thresholds")

    st.subheader("Notification Thresholds")

    current_expense_th = get_setting(conn, "expense_threshold", default=0)
    current_flow_th = get_setting(conn, "fund_flow_threshold", default=0)

    with st.form("settings_form"):
        expense_th = st.number_input(
            "High Daily Expense Threshold (₹)",
            min_value=0.0,
            value=float(current_expense_th or 0),
            step=500.0,
            help="If total EXPENSES in a day cross this amount, you will see a warning on the Dashboard."
        )
        flow_th = st.number_input(
            "Heavy Fund Flow Threshold (₹)",
            min_value=0.0,
            value=float(current_flow_th or 0),
            step=1000.0,
            help="If IN + OUT for a day cross this amount, you will see a warning on the Dashboard."
        )

        save = st.form_submit_button("Save Settings")

    if save:
        set_setting(conn, "expense_threshold", expense_th)
        set_setting(conn, "fund_flow_threshold", flow_th)
        st.success("Settings updated successfully.")

#TABLE MODIFICATIONS
def upgrade_worker_table(conn):
    """Safely add new columns to workers table if they do not exist."""
    cur = conn.cursor()

    # Because row_factory returns dicts, extract using keys
    cur.execute("PRAGMA table_info(workers);")
    existing_cols = [c["name"] for c in cur.fetchall()]

    def add_col(column, col_type):
        if column not in existing_cols:
            cur.execute(f"ALTER TABLE workers ADD COLUMN {column} {col_type};")

    # Personal details
    add_col("father_name", "TEXT")
    add_col("mobile", "TEXT")
    add_col("site_allocation", "TEXT")

    # Account details
    add_col("account_number", "TEXT")
    add_col("bank_name", "TEXT")
    add_col("ifsc_code", "TEXT")

    conn.commit()



# =========================
# MAIN APP ENTRY
# =========================

def main():
    conn = get_connection()
    init_db(conn)
    upgrade_worker_table(conn)

    if "active_page" not in st.session_state:
        st.session_state.active_page = "Dashboard"

    st.sidebar.title("HRMS & Accounts")

    def nav_button(label):
        is_active = (st.session_state.active_page == label)

        # Create a container to apply active styling
        container = st.sidebar.container()

        # Apply class only if active
        if is_active:
            container.markdown("<div class='active-tab'>", unsafe_allow_html=True)
        else:
            container.markdown("<div>", unsafe_allow_html=True)

        # This button is the ONLY element shown → no duplicates
        if container.button(label):
            st.session_state.active_page = label

        container.markdown("</div>", unsafe_allow_html=True)


    nav_button("Dashboard")
    nav_button("Workers")
    nav_button("Attendance")
    nav_button("Accounts")
    nav_button("Payroll")
    nav_button("Reports & Insights")
    nav_button("Settings")


    st.markdown("<div class='fade-in'>", unsafe_allow_html=True)
    page = st.session_state.active_page

    if page == "Dashboard":
        render_dashboard(conn)
    elif page == "Workers":
        render_workers(conn)
    elif page == "Attendance":
        render_attendance(conn)
    elif page == "Accounts":
        render_accounts(conn)
    elif page == "Payroll":
        render_payroll(conn)
    elif page == "Reports & Insights":
        render_reports(conn)
    elif page == "Settings":
        render_settings(conn)

    st.markdown("</div>", unsafe_allow_html=True)






if __name__ == "__main__":
    main()

