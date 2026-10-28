import streamlit as st
import pandas as pd
from supabase import create_client, Client

st.set_page_config(page_title="Habits Attendance", page_icon="🍫", layout="wide")

# --- LIGHT CREAM & BROWN THEME CSS ---
st.markdown("""
    <style>
    [data-testid="stHeader"] { display: none !important; }
    footer { visibility: hidden !important; }
    .stApp { background-color: #F9F7F3 !important; }
    [data-testid="stSidebar"] { display: none !important; }
    h1, h2, h3, h4, h5, h6, p, label, .stMarkdown {
        color: #5C3A21 !important; 
        font-family: 'Segoe UI', Roboto, Helvetica, sans-serif;
    }
    h1 { font-weight: 800; font-size: 2rem !important; }
    h3 { font-size: 1.1rem !important; font-weight: 700; text-transform: uppercase; color: #8B5A2B !important; }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        background-color: #FFFFFF !important;
        border-radius: 12px !important;
        border: 1px solid #E5DDD5 !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        padding: 10px;
    }
    div[data-baseweb="select"] > div, input[type="text"] {
        background-color: #FDFBF9 !important;
        border: 1px solid #D7C9B8 !important;
        border-radius: 6px !important;
        color: #333333 !important;
    }
    [data-testid="stMetricValue"] {
        color: #8B5A2B !important;
        font-weight: bold;
    }
    [data-testid="stDataFrame"] {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #E5DDD5;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1>HABITS <span style='font-size: 1.2rem; font-weight: 400; color: #8B8378;'>Attendance & Time Tracking</span></h1>", unsafe_allow_html=True)

# --- LOAD DATA FROM SUPABASE ---
@st.cache_data(ttl=60) # Refreshes data automatically every 60 seconds
def load_data():
    try:
        # Connect to Supabase using secrets
        supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        response = supabase.table('attendance_logs').select("*").execute()
        
        if not response.data:
            return pd.DataFrame()
            
        df = pd.DataFrame(response.data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        df['month_year'] = df['timestamp'].dt.strftime('%B %Y')
        return df
    except Exception as e:
        st.error(f"Cloud Connection Error: {e}")
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.warning("No data found in Supabase. Please run the sync_data.py script to push records to the cloud.")
    st.stop()

# --- FILTER CARD ---
with st.container(border=True):
    st.markdown("### DATA EXTRACTION & FILTERS")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        selected_month = st.selectbox("Select Month", df['month_year'].unique())
    with col_f2:
        selected_emp = st.multiselect("Driver / Employee", df['name'].unique())
    with col_f3:
        selected_date = st.date_input("Specific Date (Optional)", value=None)

# --- ADVANCED SHIFT & ABSENCE LOGIC ---
month_df = df[df['month_year'] == selected_month]

# Determine "Work Days" by finding every unique date in the month where at least one person punched
work_days = sorted(month_df['date'].unique())
emps_to_check = selected_emp if selected_emp else df['name'].unique()

status_records = []

for emp in emps_to_check:
    emp_id = df[df['name'] == emp]['employee_id'].iloc[0] if not df[df['name'] == emp].empty else "Unknown"
    
    # Check this employee against every single active work day in the month
    for date in work_days:
        if selected_date and date != selected_date:
            continue
            
        day_data = month_df[(month_df['name'] == emp) & (month_df['date'] == date)]
        
        # ABSENT LOGIC
        if day_data.empty:
            status_records.append({
                'ID': emp_id, 'Employee Name': emp, 'Date': date.strftime('%d/%m/%Y'),
                'Check In': '-', 'Check Out': '-', 'Hours': 0.0, 'Status': 'Absent'
            })
        else:
            in_punches = day_data[day_data['punch_type'] == 'In']['timestamp']
            out_punches = day_data[day_data['punch_type'] == 'Out']['timestamp']
            
            first_in = in_punches.min() if not in_punches.empty else None
            last_out = out_punches.max() if not out_punches.empty else None
            
            # COMPLETE SHIFT LOGIC
            if first_in and last_out and last_out > first_in:
                hours = (last_out - first_in).total_seconds() / 3600
                status_records.append({
                    'ID': emp_id, 'Employee Name': emp, 'Date': date.strftime('%d/%m/%Y'),
                    'Check In': first_in.strftime('%H:%M'), 'Check Out': last_out.strftime('%H:%M'), 
                    'Hours': round(hours, 2), 'Status': 'Complete'
                })
            # MISSING PUNCH OUT LOGIC
            elif first_in and not last_out:
                status_records.append({
                    'ID': emp_id, 'Employee Name': emp, 'Date': date.strftime('%d/%m/%Y'),
                    'Check In': first_in.strftime('%H:%M'), 'Check Out': 'MISSING OUT', 
                    'Hours': 0.0, 'Status': 'Incomplete (No Out)'
                })
            # MISSING PUNCH IN LOGIC
            elif not first_in and last_out:
                status_records.append({
                    'ID': emp_id, 'Employee Name': emp, 'Date': date.strftime('%d/%m/%Y'),
                    'Check In': 'MISSING IN', 'Check Out': last_out.strftime('%H:%M'), 
                    'Hours': 0.0, 'Status': 'Incomplete (No In)'
                })

status_df = pd.DataFrame(status_records)

# Sort chronologically
if not status_df.empty:
    status_df['DateObj'] = pd.to_datetime(status_df['Date'], format='%d/%m/%Y')
    status_df = status_df.sort_values(by=['DateObj', 'Employee Name']).drop(columns=['DateObj'])

# --- METRICS ROW ---
if not status_df.empty:
    with st.container(border=True):
        total_hours_all = status_df['Hours'].sum()
        total_shifts = len(status_df[status_df['Status'] == 'Complete'])
        total_absences = len(status_df[status_df['Status'] == 'Absent'])
        total_errors = len(status_df[status_df['Status'].str.contains('Incomplete')])
        
        st.markdown("### SUMMARY STATISTICS")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Logged Hours", f"{total_hours_all:.1f}")
        m2.metric("Completed Shifts", total_shifts)
        m3.metric("Total Absences", total_absences)
        m4.metric("Missing Punches", total_errors)

# --- TABLES ROW ---
col_left, col_right = st.columns([1, 2.5])

with col_left:
    with st.container(border=True):
        st.markdown("### EMPLOYEE TOTALS")
        if not status_df.empty:
            summary = status_df.groupby(['Employee Name'])['Hours'].sum().reset_index()
            st.dataframe(summary.style.format({'Hours': '{:.2f}'}), use_container_width=True, hide_index=True)

with col_right:
    with st.container(border=True):
        # Header with EXCEL EXPORT BUTTON
        head_col1, head_col2 = st.columns([3, 1])
        head_col1.markdown("### DAILY SHIFT TRACKER (ABSENCES & ERRORS)")
        
        if not status_df.empty:
            # Excel CSV Export
            csv_data = status_df.to_csv(index=False).encode('utf-8')
            head_col2.download_button(
                label="📥 Export to Excel",
                data=csv_data,
                file_name=f"Habits_Attendance_{selected_month.replace(' ', '_')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # Row Highlighting Logic
            def highlight_status(row):
                if row['Status'] == 'Absent':
                    # Red background for Absences
                    return ['background-color: #FFEAE8; color: #D32F2F'] * len(row)
                elif 'Incomplete' in row['Status']:
                    # Orange background for Missing Punches
                    return ['background-color: #FFF4E5; color: #ED6C02'] * len(row)
                else:
                    return [''] * len(row)
            
            styled_tracker = status_df.style.apply(highlight_status, axis=1).format({'Hours': '{:.2f}'})
            st.dataframe(styled_tracker, use_container_width=True, hide_index=True)
        else:
            st.info("No records found.")