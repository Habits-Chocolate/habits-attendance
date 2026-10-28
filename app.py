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
        # Failsafe just in case columns aren't created yet
        if 'end_hour' not in sched_df.columns: sched_df['end_hour'] = 17
        if 'day_off' not in sched_df.columns: sched_df['day_off'] = 'None'
        SHIFT_CONFIGS = sched_df.set_index('employee_name').to_dict('index')
    else:
        SHIFT_CONFIGS = {}
except:
    SHIFT_CONFIGS = {}

# --- 4. FETCH & PROCESS DATA ---
@st.cache_data(ttl=600)
def load_data(_shift_configs):
    response = supabase.table("attendance_logs").select("*").execute()
    if not response.data:
        return pd.DataFrame()
        
    df = pd.DataFrame(response.data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['Date'] = df['timestamp'].dt.date
    
    if 'Employee Name' not in df.columns:
        df['Employee Name'] = df.get('name', df['employee_id'])
        
    # Group existing punches
    punches_summary = df.groupby(['employee_id', 'Employee Name', 'Date']).agg(
        Check_In=('timestamp', 'min'),
        Check_Out=('timestamp', 'max')
    ).reset_index()

    # GENERATE FULL CALENDAR (Ensures Absences and Days Off are tracked accurately)
    min_date = punches_summary['Date'].min()
    max_date = punches_summary['Date'].max()
    all_dates = pd.date_range(start=min_date, end=max_date).date
    
    unique_emps = punches_summary[['employee_id', 'Employee Name']].drop_duplicates()
    grid = unique_emps.assign(key=1).merge(pd.DataFrame({'Date': all_dates, 'key': 1}), on='key').drop('key', axis=1)
    
    # Merge real punches into the full calendar grid
    daily_summary = pd.merge(grid, punches_summary, on=['employee_id', 'Employee Name', 'Date'], how='left')
    daily_summary['Month'] = pd.to_datetime(daily_summary['Date']).dt.strftime('%B %Y')

    def determine_status(row):
        emp_name = row['Employee Name']
        day_name = row['Date'].strftime('%A')
        
        # Pull customized employee settings
        config = _shift_configs.get(emp_name, {})
        start_hr = config.get('start_hour', 8)
        end_hr = config.get('end_hour', 17)
        day_off = config.get('day_off', 'None')
        
        # Handled Days with no punches
        if pd.isna(row['Check_In']) and pd.isna(row['Check_Out']):
            if day_name == day_off:
                return "Day Off", 0.0, "-", "-"
            else:
                return "Absent", 0.0, "-", "-"
            
        # Handled Days with only 1 punch
        if row['Check_In'] == row['Check_Out']:
            time_str = row['Check_In'].strftime('%H:%M')
            punch_hour = row['Check_In'].hour
            
            # Smart Missing Punch Logic: compares distance to start vs end shift
            start_diff = abs(punch_hour - start_hr)
            end_diff = abs(punch_hour - end_hr)
            
            if start_diff <= end_diff: 
                return "Incomplete (No Out)", 0.0, time_str, "MISSING OUT"
            else:
                return "Incomplete (No In)", 0.0, "MISSING IN", time_str
        
        # Complete Shifts
        hours = (row['Check_Out'] - row['Check_In']).total_seconds() / 3600
        in_str = row['Check_In'].strftime('%H:%M')
        out_str = row['Check_Out'].strftime('%H:%M')
        return "Complete", round(hours, 2), in_str, out_str

    status_data = daily_summary.apply(determine_status, axis=1, result_type='expand')
    daily_summary[['Status', 'Hours', 'Check In', 'Check Out']] = status_data
    daily_summary.rename(columns={'employee_id': 'ID'}, inplace=True)
    
    return daily_summary

df = load_data(SHIFT_CONFIGS)

# --- 5. TABS FOR DASHBOARD & SETTINGS ---
tab1, tab2 = st.tabs(["📊 Main Dashboard", "⚙️ Shift Settings"])

with tab2:
    st.markdown("### Manage Staff Shift Schedules")
    st.write("Set start times, end times (24-hour format), and designated Days Off. Unscheduled days with no punches will be tracked as Absences.")
    
    if not df.empty:
        unique_staff = df['Employee Name'].dropna().unique()
        staff_schedules = []
        for staff in unique_staff:
            conf = SHIFT_CONFIGS.get(staff, {})
            staff_schedules.append({
                "employee_name": staff, 
                "start_hour": conf.get('start_hour', 8),
                "end_hour": conf.get('end_hour', 17),
                "day_off": conf.get('day_off', 'None')
            })
        ui_sched_df = pd.DataFrame(staff_schedules)
    else:
        ui_sched_df = pd.DataFrame(columns=["employee_name", "start_hour", "end_hour", "day_off"])
        
    edited_schedules = st.data_editor(
        ui_sched_df, 
        use_container_width=True,
        hide_index=True,
        column_config={
            "employee_name": st.column_config.TextColumn("Employee Name", disabled=True),
            "start_hour": st.column_config.NumberColumn("Start Hour (0-23)", min_value=0, max_value=23, required=True),
            "end_hour": st.column_config.NumberColumn("End Hour (0-23)", min_value=0, max_value=23, required=True),
            "day_off": st.column_config.SelectboxColumn(
                "Day Off",
                options=["None", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                required=True
            )
        }
    )
    
    if st.button("💾 Save Schedules to System"):
        records_to_save = edited_schedules.to_dict(orient="records")
        if records_to_save:
            supabase.table("shift_schedules").upsert(records_to_save).execute()
        st.success("Schedules updated! The attendance dashboard is recalculating punches and absences based on your new rules.")
        load_data.clear()
        st.rerun()

with tab1:
    if df.empty:
        st.info("No attendance records found.")
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
        
        # Formatting for the table presentation
        display_df['Date'] = pd.to_datetime(display_df['Date']).dt.strftime('%d/%m/%Y')
        display_df['Hours'] = display_df['Hours'].map(lambda x: f"{float(x):.2f}")

        def highlight_status(row):
            if row['Status'] == 'Absent':
                return ['background-color: #FFEAEE; color: #D32F2F'] * len(row)
            elif 'Incomplete' in row['Status']:
                return ['background-color: #FFF4E5; color: #ED6C02'] * len(row)
            elif row['Status'] == 'Day Off':
                return ['background-color: #F3F4F6; color: #6B7280'] * len(row) # Grey for day off
            else:
                return [''] * len(row)

        styled_tracker = display_df.style.apply(highlight_status, axis=1)
        st.dataframe(styled_tracker, use_container_width=True, hide_index=True)