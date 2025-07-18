import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, timedelta

# ------------------------------
# DB 연결 및 테이블 생성
# ------------------------------
conn = sqlite3.connect("gpu_admin.db", check_same_thread=False)
cursor = conn.cursor()

# GPU Pool 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS gpu_pool (
    gpu_type TEXT PRIMARY KEY,
    total INTEGER
)
""")

# Service Names 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS services (
    service_name TEXT PRIMARY KEY
)
""")

# GPU Usage 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS gpu_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    gpu_type TEXT NOT NULL,
    service_name TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    source TEXT NOT NULL
)
""")

# Reservations 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    gpu_type TEXT NOT NULL,
    service_name TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'pending',
    approvers TEXT DEFAULT ''
)
""")
conn.commit()

# ------------------------------
# 마이그레이션: count 컬럼 추가
# ------------------------------
for table in ["reservations", "gpu_usage"]:
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    if "count" not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN count INTEGER DEFAULT 1")
        conn.commit()

# ------------------------------
# Helper Functions
# ------------------------------
def get_gpu_pool():
    df = pd.read_sql_query("SELECT * FROM gpu_pool", conn)
    return dict(zip(df["gpu_type"], df["total"]))

def update_gpu_total(gpu_type, total):
    cursor.execute("""
        INSERT INTO gpu_pool (gpu_type, total)
        VALUES (?, ?)
        ON CONFLICT(gpu_type) DO UPDATE SET total=excluded.total
    """, (gpu_type, total))
    conn.commit()

def get_services():
    df = pd.read_sql_query("SELECT * FROM services", conn)
    return list(df["service_name"])

def add_service(service_name):
    cursor.execute("""
        INSERT OR IGNORE INTO services (service_name)
        VALUES (?)
    """, (service_name,))
    conn.commit()

def add_reservation(start_date, end_date, service, gpu_type, count):
    cursor.execute("""
        INSERT INTO reservations (start_date, end_date, service_name, gpu_type, count)
        VALUES (?, ?, ?, ?, ?)
    """, (start_date, end_date, service, gpu_type, count))
    conn.commit()

def get_reservations():
    df = pd.read_sql_query("SELECT * FROM reservations", conn)
    return df.to_dict("records")

def update_approvers(resv_id, approvers, status):
    cursor.execute("""
        UPDATE reservations
        SET approvers=?, status=?
        WHERE id=?
    """, (approvers, status, resv_id))
    conn.commit()

def delete_reservation(resv_id):
    cursor.execute("DELETE FROM reservations WHERE id=?", (resv_id,))
    conn.commit()

def get_usage_details():
    df = pd.read_sql_query("SELECT * FROM gpu_usage", conn)
    return df

# ------------------------------
# 세션 상태 초기화
# ------------------------------
if "admin_mode" not in st.session_state:
    st.session_state.admin_mode = False

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

# ------------------------------
# Admin 버튼
# ------------------------------
st.sidebar.header("🔧 Admin Control")
if st.sidebar.button("🔒 Admin"):
    st.session_state.admin_mode = True

# Admin 로그인
if st.session_state.admin_mode and not st.session_state.admin_authenticated:
    st.sidebar.subheader("🔑 Admin Login")
    admin_pw = st.sidebar.text_input("Enter admin password", type="password")
    if st.sidebar.button("Submit Admin Password"):
        if admin_pw == "abcd":
            st.session_state.admin_authenticated = True
            st.session_state.admin_mode = False
            st.sidebar.success("Admin authenticated.")
        else:
            st.sidebar.error("Invalid password.")
            st.session_state.admin_mode = False

# Admin 로그아웃
if st.session_state.admin_authenticated:
    if st.sidebar.button("🔓 Logout Admin"):
        st.session_state.admin_authenticated = False
        st.sidebar.success("Admin logged out.")

# ------------------------------
# GPU Admin Dashboard
# ------------------------------
st.title("🎛️ GPU Admin Dashboard")

# ------------------------------
# GPU Pool Status (snapshot)
# ------------------------------
st.header("📊 GPU Pool Status (Current Snapshot)")
gpu_pool = get_gpu_pool()
usage_df = get_usage_details()
current_usage = {gpu_type: 0 for gpu_type in gpu_pool.keys()}

for _, row in usage_df.iterrows():
    if row["gpu_type"] in current_usage:
        current_usage[row["gpu_type"]] += row["count"]

pool_df = pd.DataFrame([
    {
        "GPU Type": gpu_type,
        "Total": total,
        "Used": current_usage.get(gpu_type, 0),
        "Available": total - current_usage.get(gpu_type, 0)
    }
    for gpu_type, total in gpu_pool.items()
])

st.table(pool_df)

# ------------------------------
# GPU Usage Details (usage + reservations)
# ------------------------------
st.header("🔎 GPU Usage Details")

approved_df = pd.read_sql_query(
    "SELECT id, start_date, end_date, gpu_type, service_name, count, status "
    "FROM reservations WHERE status='approved'", conn
)
approved_df["source"] = "reservation"

if not usage_df.empty:
    combined_df = pd.concat([usage_df, approved_df.rename(
        columns={"service_name": "service_name", "gpu_type": "gpu_type"})],
        ignore_index=True
    )
else:
    combined_df = approved_df

if not combined_df.empty:
    st.dataframe(combined_df)
else:
    st.write("No usage details available.")

# ------------------------------
# GPU Pool Status (timeline)
# ------------------------------
st.header("📅 GPU Pool Timeline")

# Timeline rows
timeline_rows = []

# usage
for _, row in usage_df.iterrows():
    start = pd.to_datetime(row["start_date"])
    end = pd.to_datetime(row["end_date"]) if row["end_date"] else start
    for single_date in pd.date_range(start, end):
        timeline_rows.append({
            "date": single_date.strftime("%Y-%m-%d"),
            "gpu_type": row["gpu_type"],
            "count": row["count"]
        })

# approved reservations
for _, row in approved_df.iterrows():
    start = pd.to_datetime(row["start_date"])
    end = pd.to_datetime(row["end_date"]) if row["end_date"] else start
    for single_date in pd.date_range(start, end):
        timeline_rows.append({
            "date": single_date.strftime("%Y-%m-%d"),
            "gpu_type": row["gpu_type"],
            "count": row["count"]
        })

timeline_df = pd.DataFrame(timeline_rows)

if not timeline_df.empty:
    daily_usage = timeline_df.groupby(["date", "gpu_type"]).sum().reset_index()
    daily_pivot = daily_usage.pivot(index="date", columns="gpu_type", values="count").fillna(0)

    # 총량에서 사용량 빼서 잔여
    for gpu_type, total in gpu_pool.items():
        daily_pivot[f"{gpu_type}_available"] = total - daily_pivot.get(gpu_type, 0)

    st.dataframe(daily_pivot)
else:
    st.write("No timeline usage data.")

# ------------------------------
# Reservation Form
# ------------------------------
st.header("📝 GPU Reservation")

services = get_services()
if services:
    with st.form("reserve_form"):
        start_date = st.date_input("Start Date", min_value=date.today(), max_value=date.today()+timedelta(days=90))
        end_date = st.date_input("End Date (Optional)", value=None)
        service = st.selectbox("Service Name", services)
        gpu_type = st.selectbox("GPU Type", list(gpu_pool.keys()))
        count = st.number_input("Count", min_value=1, step=1)
        submitted = st.form_submit_button("Reserve")

        if submitted:
            end_date_str = end_date.strftime("%Y-%m-%d") if end_date else None
            add_reservation(start_date.strftime("%Y-%m-%d"), end_date_str, service, gpu_type, count)
            st.success(f"{start_date} 예약 요청 완료.")
else:
    st.warning("서비스명이 등록되어 있지 않습니다. Admin에서 등록해주세요.")

# ------------------------------
# Reservation Status
# ------------------------------
st.header("📅 Reservation Status")

reservations = get_reservations()
for r in reservations:
    col1, col2, col3, col4 = st.columns([2, 2, 3, 3])
    with col1:
        st.write(f"**{r['start_date']} ~ {r['end_date'] or 'N/A'}**")
    with col2:
        st.write(f"{r['service_name']} ({r['gpu_type']}) x {r['count']}")
    with col3:
        st.write(f"Status: {r['status']}")
        st.write(f"Approvers: {r['approvers'] if r['approvers'] else 'None'}")
    with col4:
        if r["status"] != "approved":
            if st.button(f"Approve #{r['id']}"):
                approvers = r["approvers"].split(",") if r["approvers"] else []
                next_approver = f"member{len(approvers)+1}"
                if next_approver not in approvers:
                    approvers.append(next_approver)
                status = "approved" if len(approvers) >= 3 else "pending"
                update_approvers(r["id"], ",".join(approvers), status)
        if st.button(f"Cancel #{r['id']}"):
            delete_reservation(r["id"])

# ------------------------------
# Admin Management
# ------------------------------
if st.session_state.admin_authenticated:
    st.header("⚙️ Admin Management")

    # GPU Pool 관리
    st.subheader("GPU Pool Management")
    gpu_edit = st.selectbox("Select GPU Type to Edit", options=list(gpu_pool.keys()) + ["Add New"])
    if gpu_edit == "Add New":
        new_gpu = st.text_input("New GPU Type")
        new_total = st.number_input("Total Count", min_value=1, step=1)
        if st.button("Add GPU Type"):
            if new_gpu:
                update_gpu_total(new_gpu, int(new_total))
                st.success(f"{new_gpu} added with total {new_total}")
    else:
        edited_total = st.number_input("Edit Total Count", value=gpu_pool[gpu_edit], min_value=1, step=1)
        if st.button("Update Total"):
            update_gpu_total(gpu_edit, int(edited_total))
            st.success(f"{gpu_edit} total updated to {edited_total}")

    # Service Name 관리
    st.subheader("Service Name Management")
    new_service = st.text_input("Add New Service Name")
    if st.button("Add Service"):
        if new_service:
            add_service(new_service)
            st.success(f"Service {new_service} added.")
