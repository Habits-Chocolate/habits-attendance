import streamlit as st
import pandas as pd
from supabase import create_client
import io

# --- 1. PAGE CONFIG & CHOCOLATE THEME ---
st.set_page_config(page_title="HABITS Attendance", layout="wide")

st.markdown("""
    <style>
    /* Light cream background and espresso brown text */
    .stApp {
        background-color: #F9F7F3;
    }
    h1, h2, h3, h4, h5, h6, p, label, span {
        color: #5C3A21 !important;
    }
    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #EADDCD;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-3px);
    }
    </style>
""", unsafe_allow_html=True)

st.title("HABITS Attendance & Time Tracking")

# --- 2. SUPABASE CONNECTION ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- 3. FETCH & PROCESS DATA ---
@st.cache_data(ttl=600) # Caches data for 10 minutes to load faster
def load_data():
    # Fetch all records (Supabase max rows is now 100,000)
    response = supabase.table("attendance_logs").select("*").execute()
    
    if not response.data:
        return pd.DataFrame()
        
    df = pd.DataFrame(response.data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['Date'] = df['timestamp'].dt.date
    df['Time'] = df['timestamp'].dt.time
    df['Month'] = df['timestamp'].dt.strftime('%B %Y')
    
    # Process check-ins and check-outs per employee per day
    daily_summary = df.groupby(['employee_id', 'Date']).agg(
        Check_In=('timestamp', 'min'),
        Check_Out=('timestamp', 'max')
    ).reset_index()

    # Calculate hours and determine status
    def determine_status(row):
        if pd.isna(row['Check_In']) and pd.isna(row['Check_Out']):
            return "Absent", 0.0, "-", "-"
        if row['Check_In'] == row['Check_Out']:
            time_str = row['Check_In'].strftime('%H:%M')
            if row['Check_In'].hour >= 12: # Assumes missing IN if only punch is in the afternoon
                return "Incomplete (No In)", 0.0, "MISSING IN", time_str
            else:
                return "Incomplete (No Out)", 0.0, time_str, "MISSING OUT"
        
        hours = (row['Check_Out'] - row['Check_In']).total_seconds() / 3600
        in_str = row['Check_In'].strftime('%H:%M')
        out_str = row['Check_Out'].strftime('%H:%M')
        return "Complete", round(hours, 2), in_str, out_str

    status_data = daily_summary.apply(determine_status, axis=1, result_type='expand')
    daily_summary[['Status', 'Hours', 'Check In', 'Check Out']] = status_data
    
    # Add dummy employee names (Replace with an actual mapping or database join later)
    daily_summary['Employee Name'] = "Emp " + daily_summary['employee_id'].astype(str)
    
    # Include month for filtering
    daily_summary['Month'] = pd.to_datetime(daily_summary['Date']).dt.strftime('%B %Y')
    
    return daily_summary

df = load_data()

if df.empty:
    st.info("No attendance records found in the cloud database.")
    st.stop()

# --- 4. FILTERS ---
st.markdown("### DATA EXTRACTION & FILTERS")
col1, col2, col3 = st.columns(3)

# Chronological Month Sorting
months = df['Month'].dropna().unique().tolist()
months.sort(key=lambda date: pd.to_datetime(date, format='%B %Y'), reverse=True)

with col1:
    selected_month = st.selectbox("Select Month", ["All"] + months)
with col2:
    employees = df['Employee Name'].unique().tolist()
    selected_employee = st.multiselect("Driver / Employee", employees)
with col3:
    selected_date = st.date_input("Specific Date (Optional)", value=None)

# Apply Filters
filtered_df = df.copy()
if selected_month != "All":
    filtered_df = filtered_df[filtered_df['Month'] == selected_month]
if selected_employee:
    filtered_df = filtered_df[filtered_df['Employee Name'].isin(selected_employee)]
if selected_date:
    filtered_df = filtered_df[filtered_df['Date'] == selected_date]

# --- 5. SUMMARY METRICS ---
st.markdown("### SUMMARY STATISTICS")
m1, m2, m3, m4 = st.columns(4)

total_hours = filtered_df['Hours'].sum()
completed_shifts = len(filtered_df[filtered_df['Status'] == 'Complete'])
total_absences = len(filtered_df[filtered_df['Status'] == 'Absent'])
missing_punches = len(filtered_df[filtered_df['Status'].str.contains('Incomplete')])

m1.metric("Total Logged Hours", f"{total_hours:.1f}")
m2.metric("Completed Shifts", completed_shifts)
m3.metric("Total Absences", total_absences)
m4.metric("Missing Punches", missing_punches)

st.divider()

# --- 6. DATAFRAME & HIGHLIGHTING ---
col_table1, col_table2 = st.columns([1, 3])

with col_table1:
    st.markdown("##### EMPLOYEE TOTALS")
    totals = filtered_df.groupby('Employee Name')['Hours'].sum().reset_index()
    totals['Hours'] = totals['Hours'].map('{:.2f}'.format)
    st.dataframe(totals, use_container_width=True, hide_index=True)

with col_table2:
    st.markdown("##### DAILY SHIFT TRACKER (ABSENCES & ERRORS)")
    
    display_df = filtered_df[['employee_id', 'Employee Name', 'Date', 'Check In', 'Check Out', 'Hours', 'Status']].copy()
    display_df['Date'] = pd.to_datetime(display_df['Date']).dt.strftime('%d/%m/%Y')
    display_df['Hours'] = display_df['Hours'].map('{:.2f}'.format)

    def highlight_status(row):
        if row['Status'] == 'Absent':
            return ['background-color: #FFEAEE; color: #D32F2F'] * len(row)
        elif 'Incomplete' in row['Status']:
            return ['background-color: #FFF4E5; color: #ED6C02'] * len(row)
        else:
            return [''] * len(row)

    styled_tracker = display_df.style.apply(highlight_status, axis=1)
    st.dataframe(styled_tracker, use_container_width=True, hide_index=True)
    
    # Excel Export
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        display_df.to_excel(writer, index=False, sheet_name='Attendance')
    
    st.download_button(
        label="📥 Export to Excel",
        data=buffer,
        file_name="Habits_Attendance_Report.xlsx",
        mime="application/vnd.ms-excel",
        use_container_width=True
    )