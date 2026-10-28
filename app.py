import streamlit as st
import pandas as pd
from supabase import create_client
import io

# --- 1. PAGE CONFIG & CHOCOLATE THEME ---
st.set_page_config(page_title="HABITS Attendance", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #F9F7F3; }
    h1, h2, h3, h4, h5, h6, p, label, span { color: #5C3A21 !important; }
    
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        border: 1px solid #EADDCD !important;
        padding: 15px 30px !important;
        border-radius: 50px !important;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.04) !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.3s ease !important;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-4px) !important;
        box-shadow: 0 8px 16px rgba(92, 58, 33, 0.12) !important;
        border-color: #A99B8E !important;
    }
    div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
    }
    div[data-testid="stMetricValue"] > div {
        color: #5C3A21 !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='color: #5C3A21;'><b>HABITS</b> <span style='color: #A99B8E; font-size: 28px;'>Attendance & Time Tracking</span></h1>", unsafe_allow_html=True)

# --- 2. SUPABASE CONNECTION ---
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

# --- 3. LOAD DYNAMIC SHIFT SCHEDULES FROM SUPABASE ---
try:
    sched_res = supabase.table("shift_schedules").select("*").execute()
    sched_df = pd.DataFrame(sched_res.data)
    if not sched_df.empty:
        SHIFT_STARTS = dict(zip(sched_df['employee_name'], sched_df['start_hour']))
    else:
        SHIFT_STARTS = {}
except:
    SHIFT_STARTS = {}
    sched_df = pd.DataFrame(columns=["employee_name", "start_hour"])

# --- 4. FETCH & PROCESS DATA ---
@st.cache_data(ttl=600)
def load_data(_shift_starts_dict):
    response = supabase.table("attendance_logs").select("*").execute()
    if not response.data:
        return pd.DataFrame()
        
    df = pd.DataFrame(response.data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['Date'] = df['timestamp'].dt.date
    df['Month'] = df['timestamp'].dt.strftime('%B %Y')
    
    if 'Employee Name' not in df.columns:
        df['Employee Name'] = df.get('name', df['employee_id'])
        
    daily_summary = df.groupby(['employee_id', 'Employee Name', 'Date', 'Month']).agg(
        Check_In=('timestamp', 'min'),
        Check_Out=('timestamp', 'max')
    ).reset_index()

    def determine_status(row):
        if pd.isna(row['Check_In']) and pd.isna(row['Check_Out']):
            return "Absent", 0.0, "-", "-"
            
        if row['Check_In'] == row['Check_Out']:
            time_str = row['Check_In'].strftime('%H:%M')
            punch_hour = row['Check_In'].hour
            emp_name = row['Employee Name']
            
            # Checks the UI settings, defaults to 8 AM if not listed
            scheduled_start = _shift_starts_dict.get(emp_name, 8)
            
            if punch_hour < (scheduled_start + 4): 
                return "Incomplete (No Out)", 0.0, time_str, "MISSING OUT"
            else:
                return "Incomplete (No In)", 0.0, "MISSING IN", time_str
        
        hours = (row['Check_Out'] - row['Check_In']).total_seconds() / 3600
        in_str = row['Check_In'].strftime('%H:%M')
        out_str = row['Check_Out'].strftime('%H:%M')
        return "Complete", round(hours, 2), in_str, out_str

    status_data = daily_summary.apply(determine_status, axis=1, result_type='expand')
    daily_summary[['Status', 'Hours', 'Check In', 'Check Out']] = status_data
    daily_summary.rename(columns={'employee_id': 'ID'}, inplace=True)
    return daily_summary

df = load_data(SHIFT_STARTS)

# --- 5. TABS FOR DASHBOARD & SETTINGS ---
tab1, tab2 = st.tabs(["📊 Main Dashboard", "⚙️ Shift Settings"])

with tab2:
    st.markdown("### Manage Staff Shift Schedules")
    st.write("Use this table to set custom start times for staff members (use 24-hour format, e.g., 14 for 2:00 PM). **Anyone not listed here will automatically default to an 8:00 AM start.**")
    
    # Interactive UI for editing schedules
    if sched_df.empty:
        sched_df = pd.DataFrame([{"employee_name": "", "start_hour": 12}])
        
    edited_schedules = st.data_editor(
        sched_df, 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "employee_name": st.column_config.TextColumn("Employee Name", required=True),
            "start_hour": st.column_config.NumberColumn("Start Hour (0-23)", min_value=0, max_value=23, required=True)
        }
    )
    
    if st.button("💾 Save Schedules to System"):
        # Convert the UI table to data Supabase can read
        records_to_save = edited_schedules.dropna(subset=["employee_name"]).to_dict(orient="records")
        if records_to_save:
            supabase.table("shift_schedules").upsert(records_to_save).execute()
        st.success("Schedules updated successfully! The system will now use these times to calculate punches.")
        # Clears cache so the dashboard immediately updates with new logic
        load_data.clear()
        st.rerun()

with tab1:
    if df.empty:
        st.info("No records found.")
        st.stop()

    st.markdown("### DATA EXTRACTION & FILTERS")
    col1, col2, col3 = st.columns(3)

    months = df['Month'].dropna().unique().tolist()
    months.sort(key=lambda date: pd.to_datetime(date, format='%B %Y'), reverse=True)

    with col1:
        selected_month = st.selectbox("Select Month", ["All"] + months)
    with col2:
        employees = df['Employee Name'].unique().tolist()
        selected_employee = st.multiselect("Driver / Employee", employees)
    with col3:
        selected_date = st.date_input("Specific Date (Optional)", value=None)

    filtered_df = df.copy()
    if selected_month != "All":
        filtered_df = filtered_df[filtered_df['Month'] == selected_month]
    if selected_employee:
        filtered_df = filtered_df[filtered_df['Employee Name'].isin(selected_employee)]
    if selected_date:
        filtered_df = filtered_df[filtered_df['Date'] == selected_date]

    st.markdown("### SUMMARY STATISTICS")
    m1, m2, m3, m4 = st.columns(4)

    m1.metric("Total Logged Hours", f"{filtered_df['Hours'].sum():.1f}")
    m2.metric("Completed Shifts", len(filtered_df[filtered_df['Status'] == 'Complete']))
    m3.metric("Total Absences", len(filtered_df[filtered_df['Status'] == 'Absent']))
    m4.metric("Missing Punches", len(filtered_df[filtered_df['Status'].str.contains('Incomplete')]))

    st.divider()

    col_table1, col_table2 = st.columns([1, 3])

    with col_table1:
        st.markdown("##### EMPLOYEE TOTALS")
        totals = filtered_df.groupby('Employee Name')['Hours'].sum().reset_index()
        totals['Hours'] = totals['Hours'].map('{:.2f}'.format)
        st.dataframe(totals, use_container_width=True, hide_index=True)

    with col_table2:
        col_title, col_btn = st.columns([3, 1])
        with col_title:
            st.markdown("##### DAILY SHIFT TRACKER (ABSENCES & ERRORS)")
        with col_btn:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                filtered_df[['ID', 'Employee Name', 'Date', 'Check In', 'Check Out', 'Hours', 'Status']].to_excel(writer, index=False, sheet_name='Attendance')
            
            st.download_button(
                label="📥 Export to Excel",
                data=buffer,
                file_name="Habits_Attendance_Report.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )
        
        display_df = filtered_df[['ID', 'Employee Name', 'Date', 'Check In', 'Check Out', 'Hours', 'Status']].copy()
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