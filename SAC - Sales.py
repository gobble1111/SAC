import streamlit as st
import pandas as pd
import altair as alt
import pytz

# -----------------------------
# Config and URLs
# -----------------------------
st.set_page_config(page_title="SAC Management View", layout="wide")

transactions_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=645688819"
items_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=824906690"
staff_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=1941399770"
customers_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=1921622491"
logs_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=316444388"

# -----------------------------
# Load Data
# -----------------------------
fact_engines = pd.read_csv(transactions_url)
items = pd.read_csv(items_url)
staff = pd.read_csv(staff_url, skiprows=3, usecols=[0, 1])
customers = pd.read_csv(customers_url)
logs = pd.read_csv(logs_url)

# Fix columns
items.columns = ['Item', 'Material Cost', 'RRP']
logs.columns = ['Timestamp_Logs', 'Player', 'Vehicle', 'Service', 'Price', 'Mechanic']

# Parse engine timestamps (assumed local/no timezone)
fact_engines["Timestamp"] = pd.to_datetime(fact_engines["Timestamp"], format="%m/%d/%Y %H:%M:%S", errors="coerce")

# -----------------------------
# Process Staff - add 'Blank' for missing staff names
# -----------------------------
fact_engines["Staff Name"] = fact_engines["Staff Name"].fillna("Blank")

# -----------------------------
# Prepare Engines DataFrame
# -----------------------------
engines_df = fact_engines.merge(items, on="Item", how="left")
engines_df = engines_df.merge(staff, on="Staff Name", how="left")
engines_df["Type"] = "Engines"
engines_df["RRP"] = engines_df["RRP"].replace('[\$,]', '', regex=True).astype(float)
engines_df["Material Cost"] = engines_df["Material Cost"].replace('[\$,]', '', regex=True).astype(float)
engines_df["Sales"] = engines_df["RRP"]
engines_df["Profit"] = engines_df["Sales"] - engines_df["Material Cost"]

# -----------------------------
# Process Logs (Mods)
# -----------------------------
logs_df = logs.merge(staff, left_on="Mechanic", right_on="Discord Name", how="left")
logs_df = logs_df.rename(columns={
    "Timestamp_Logs": "Timestamp",
    "Player": "Customer Name",
    "Service": "Item",
    "Price": "Sales"
})
logs_df["Staff Name"] = logs_df["Staff Name"].fillna("Blank")
logs_df["Timestamp"] = pd.to_datetime(logs_df["Timestamp"], utc=True, errors="coerce")
brisbane_tz = pytz.timezone("Australia/Brisbane")
logs_df["Timestamp"] = logs_df["Timestamp"].dt.tz_convert(brisbane_tz)
logs_df["Timestamp"] = logs_df["Timestamp"].dt.tz_localize(None)
logs_df["Sales"] = logs_df["Sales"].replace('[\$,]', '', regex=True).astype(float)
logs_df["Profit"] = logs_df["Sales"] * 0.10
logs_df["Material Cost"] = logs_df["Sales"] * 0.80
logs_df["Type"] = "Mods"

# -----------------------------
# Combine staff names for filter
# -----------------------------
all_staff_names = pd.Series(list(engines_df["Staff Name"].unique()) + list(logs_df["Staff Name"].unique())).unique()

# -----------------------------
# Sidebar Filters (Reordered: Date First)
# -----------------------------
st.sidebar.header("Filters")
st.sidebar.header("View")

data_source_option = st.sidebar.radio(
    "Select data to display:",
    options=["Engines", "Mods", "Both"],
    index=2,
)

# Combine data based on toggle (before date filter)
if data_source_option == "Engines":
    combined_df = engines_df.copy()
elif data_source_option == "Mods":
    combined_df = logs_df.copy()
else:
    combined_df = pd.concat([engines_df, logs_df], ignore_index=True)

# Determine min and max dates
min_date = combined_df["Timestamp"].min().date()
max_date = combined_df["Timestamp"].max().date()

# Show date filters
start_date = st.sidebar.date_input("Start Date", min_value=min_date, max_value=max_date, value=min_date)
end_date = st.sidebar.date_input("End Date", min_value=min_date, max_value=max_date, value=max_date)

# Filter staff list *after* date selection is applied
mask_date_sidebar = (combined_df["Timestamp"].dt.date >= start_date) & (combined_df["Timestamp"].dt.date <= end_date)
filtered_df_for_sidebar = combined_df.loc[mask_date_sidebar]

# Get staff names only from filtered date range
all_staff_names = pd.Series(filtered_df_for_sidebar["Staff Name"].fillna("Blank").unique()).sort_values().tolist()

# Staff filter
selected_staff = st.sidebar.multiselect("Select Staff Name(s)", options=all_staff_names, default=all_staff_names)


# -----------------------------
# Filter combined_df by date
# -----------------------------
mask_date = (combined_df["Timestamp"].dt.date >= start_date) & (combined_df["Timestamp"].dt.date <= end_date)
final_df = combined_df.loc[mask_date].copy()

# -----------------------------
# Format final dataframe for display
# -----------------------------
final_df["Sales"] = pd.to_numeric(final_df["Sales"], errors="coerce").fillna(0)
final_df["Sales_Display"] = final_df["Sales"].map("${:,.2f}".format)
final_df["Profit"] = final_df.apply(
    lambda r: r["Sales"] - r["Material Cost"] if r["Type"] == "Engines" else r["Sales"] * 0.10,
    axis=1,
)
final_df["Material Cost"] = pd.to_numeric(final_df["Material Cost"], errors="coerce").fillna(0)

# -----------------------------
# Dashboard Title and Logo
# -----------------------------
logo_url = "https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png"

col1, col2 = st.columns([4, 1])
with col1:
    st.markdown("""<div style='display: flex; align-items: center;'>
    <img src='https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png' width='200' style='margin-right: 20px'>
    <h2 style='color: #1e90ff;'>SAC Sales & Activity Dashboard</h2>
</div>
""", unsafe_allow_html=True)

# -----------------------------
# Summary Metrics
# -----------------------------
# -----------------------------
# Summary Metrics (Updated with Composition)
# -----------------------------
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    total_sales = final_df["Sales"].sum()
    st.metric("Total Sales (RRP)", f"${total_sales:,.2f}")

with col2:
    total_transactions = len(final_df)
    st.metric("Transactions", total_transactions)

with col3:
    if not final_df.empty and final_df["Staff Name"].notnull().any():
        top_staff = final_df.groupby("Staff Name")["Sales"].sum().idxmax()
        top_sales = final_df.groupby("Staff Name")["Sales"].sum().max()
    else:
        top_staff = "N/A"
        top_sales = 0
    st.metric("Top Seller", top_staff, f"${top_sales:,.2f}")

with col4:
    total_profit = final_df["Profit"].sum()
    st.metric("Total Profit", f"${total_profit:,.2f}")

with col5:
    # Composition of sales between Mods and Engines
    type_breakdown = final_df.groupby("Type")["Sales"].sum()
    mods_pct = (type_breakdown.get("Mods", 0) / total_sales) * 100 if total_sales else 0
    engines_pct = (type_breakdown.get("Engines", 0) / total_sales) * 100 if total_sales else 0
    comp_label = f"{engines_pct:.0f}% Engines | {mods_pct:.0f}% Mods"
    st.metric("Sales Composition", comp_label)

st.write("")

# -----------------------------
# Sales Over Time Line Chart
# -----------------------------
sales_by_date = final_df.groupby(final_df["Timestamp"].dt.date)["Sales"].sum().reset_index()
sales_by_date.rename(columns={"Timestamp": "Date"}, inplace=True)

line_chart = alt.Chart(sales_by_date).mark_line(point=True).encode(
    x=alt.X("Date:T", title=None, axis=alt.Axis(format="%d/%m")),
    y=alt.Y("Sales:Q", title="Total Sales", axis=alt.Axis(format="$,.0f")),
    tooltip=[
        alt.Tooltip("Date:T", title="Date", format="%d/%m"),
        alt.Tooltip("Sales:Q", title="Total Sales", format="$,.2f"),
    ],
).properties(height=400)

st.altair_chart(line_chart, use_container_width=True)
st.write("")

# -----------------------------
# Sales by Staff Bar Chart
# -----------------------------
st.subheader("Sales & Pay by Staff")

# Compute Sales and Pay
sales_pay_df = final_df.copy()
sales_pay_df["Pay"] = sales_pay_df.apply(lambda r: r["Sales"] * 0.30 if r["Type"] == "Engines" else r["Sales"] * 0.10, axis=1)

# Aggregate
staff_combined = (
    sales_pay_df.groupby("Staff Name")[["Sales", "Pay"]]
    .sum()
    .reset_index()
    .melt(id_vars="Staff Name", var_name="Metric", value_name="Amount")
)

# Sort by Sales for consistent order
sort_order = (
    staff_combined[staff_combined["Metric"] == "Sales"]
    .sort_values("Amount", ascending=False)["Staff Name"]
    .tolist()
)

# Chart
combined_chart = alt.Chart(staff_combined).mark_bar().encode(
    x=alt.X("Amount:Q", title="Amount", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Staff Name:N", sort=sort_order, title="Staff Member"),
    color=alt.Color("Metric:N", scale=alt.Scale(domain=["Sales", "Pay"], range=["#1f77b4", "#ff7f0e"])),
    tooltip=[
        alt.Tooltip("Staff Name:N", title="Staff"),
        alt.Tooltip("Metric:N", title="Type"),
        alt.Tooltip("Amount:Q", title="Value", format="$,.2f"),
    ],
).properties(height=800)

st.altair_chart(combined_chart, use_container_width=True)
# -----------------------------
# Profit Margin by Item (Manually Color-Coded Red/Green)
# -----------------------------
st.subheader("Profit Margin")

# Label mods separately
final_df["Profit_Item"] = final_df.apply(lambda r: "Mods" if r["Type"] == "Mods" else r["Item"], axis=1)

profit_by_item = (
    final_df.groupby("Profit_Item")[["Profit", "Sales"]]
    .sum()
    .reset_index()
    .rename(columns={"Profit_Item": "Item"})
)

# Top 10 by absolute profit
top_profit_items = profit_by_item.reindex(
    profit_by_item["Profit"].abs().sort_values(ascending=False).index
).head(10)

# Add color column manually
top_profit_items["Color"] = top_profit_items["Profit"].apply(lambda x: "green" if x >= 0 else "red")

# Final bar chart with hard-coded color
profit_chart = alt.Chart(top_profit_items).mark_bar().encode(
    x=alt.X("Profit:Q", title="Total Profit", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Item:N", sort="-x", title="Item"),
    color=alt.Color("Color:N", scale=alt.Scale(domain=["green", "red"], range=["#3CB371", "#FF6347"]), legend=None),
    tooltip=[
        alt.Tooltip("Item", title="Item"),
        alt.Tooltip("Profit", title="Total Profit", format="$,.2f"),
    ]
).properties(height=400)

st.altair_chart(profit_chart, use_container_width=True)

# -----------------------------
# Staff Activity: Active Days and Hours
# -----------------------------
st.subheader("Staff Activity Overview")

# Extract day and hour
activity_df = final_df.copy()
activity_df["Date"] = activity_df["Timestamp"].dt.date
activity_df["Hour"] = activity_df["Timestamp"].dt.strftime("%Y-%m-%d %H")  # combines day + hour

# Count unique days per staff
days_active = activity_df.groupby("Staff Name")["Date"].nunique().reset_index().rename(columns={"Date": "Active Days"})

# Count unique hours per staff
hours_active = activity_df.groupby("Staff Name")["Hour"].nunique().reset_index().rename(columns={"Hour": "Active Hours"})

# Merge for alignment
activity_summary = pd.merge(days_active, hours_active, on="Staff Name")

# Charts side by side
col1, col2 = st.columns(2)

with col1:
    days_chart = alt.Chart(activity_summary).mark_bar().encode(
        x=alt.X("Active Days:Q", title="Days"),
        y=alt.Y("Staff Name:N", sort="-x", title="Staff"),
        tooltip=["Staff Name", "Active Days"]
    ).properties(height=400, title="🗓️ Active Days per Staff")
    st.altair_chart(days_chart, use_container_width=True)

with col2:
    hours_chart = alt.Chart(activity_summary).mark_bar().encode(
        x=alt.X("Active Hours:Q", title="Hours"),
        y=alt.Y("Staff Name:N", sort="-x", title="Staff"),
        tooltip=["Staff Name", "Active Hours"]
    ).properties(height=400, title="⏱️ Active Hours per Staff")
    st.altair_chart(hours_chart, use_container_width=True)

# -----------------------------
# Top 10 Customers
# -----------------------------
st.subheader("Top 10 Customers")

sales_by_customer = (
    final_df.groupby("Customer Name")["Sales"]
    .sum()
    .reset_index()
    .sort_values(by="Sales", ascending=False)
    .head(10)
)

max_sales_customer = sales_by_customer["Sales"].max() if not sales_by_customer.empty else 0
tick_step_customer = 100 if max_sales_customer < 2000 else 500

customer_chart = alt.Chart(sales_by_customer).mark_bar().encode(
    x=alt.X("Sales:Q", title="Total Sales", axis=alt.Axis(format="$,.0f", tickMinStep=tick_step_customer), scale=alt.Scale(domain=[0, max_sales_customer * 1.1])),
    y=alt.Y("Customer Name:N", sort="-x", title="Customer"),
    tooltip=["Customer Name", alt.Tooltip("Sales", format="$,.2f")],
).properties(height=400)

st.altair_chart(customer_chart, use_container_width=True)

# -----------------------------
# Transaction Table Display
# -----------------------------
final_df = final_df.sort_values(by="Timestamp", ascending=False)

display_cols = ["Timestamp", "Staff Name", "Item", "Customer Name", "Sales", "Type"]
display_df = final_df[display_cols].copy()
display_df["Timestamp"] = display_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("No Timestamp")
display_df["Sales"] = display_df["Sales"].map("${:,.2f}".format)

st.subheader("Transactions")
st.dataframe(display_df, use_container_width=True, hide_index=True)
