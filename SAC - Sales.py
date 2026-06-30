import streamlit as st
import pandas as pd
import altair as alt
import pytz

# -----------------------------
# Config and URLs
# -----------------------------
st.set_page_config(page_title="SAC Mods Dashboard", layout="wide")

logs_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=316444388"

# -----------------------------
# Load Data
# -----------------------------
logs = pd.read_csv(logs_url)

logs.columns = ['Timestamp', 'Player', 'Vehicle', 'Service', 'Price', 'Mechanic']

# -----------------------------
# Process Mods Data
# -----------------------------
mods_df = logs.rename(columns={
    "Player": "Customer Name",
    "Service": "Item",
    "Price": "Sales"
})
mods_df["Mechanic"] = mods_df["Mechanic"].fillna("Blank")

# Timezone: UTC -> Brisbane
mods_df["Timestamp"] = pd.to_datetime(mods_df["Timestamp"], utc=True, errors="coerce")
brisbane_tz = pytz.timezone("Australia/Brisbane")
mods_df["Timestamp"] = mods_df["Timestamp"].dt.tz_convert(brisbane_tz).dt.tz_localize(None)

# Financials
# Commission rate tiers (Pay / Profit / Material):
#   Before 2026-06-01:        10% / 10% / 80%
#   2026-06-01 to 2026-06-20: 25% / 25% / 50%
#   From 2026-06-21:          15% / 10% / 75%
mods_df["Sales"] = mods_df["Sales"].replace(r'[\$,]', '', regex=True).astype(float)

ts = mods_df["Timestamp"]
tier_june = (ts >= pd.Timestamp("2026-06-01")) & (ts < pd.Timestamp("2026-06-21"))
tier_late_june = ts >= pd.Timestamp("2026-06-21")

pay_rate = pd.Series(0.10, index=mods_df.index)
pay_rate[tier_june] = 0.25
pay_rate[tier_late_june] = 0.15

profit_rate = pd.Series(0.10, index=mods_df.index)
profit_rate[tier_june] = 0.25
profit_rate[tier_late_june] = 0.10

material_rate = pd.Series(0.80, index=mods_df.index)
material_rate[tier_june] = 0.50
material_rate[tier_late_june] = 0.75

mods_df["Pay"] = mods_df["Sales"] * pay_rate
mods_df["Profit"] = mods_df["Sales"] * profit_rate
mods_df["Material Cost"] = mods_df["Sales"] * material_rate

# -----------------------------
# Sidebar Filters
# -----------------------------
st.sidebar.header("Filters")

min_date = mods_df["Timestamp"].min().date()
max_date = mods_df["Timestamp"].max().date()

start_date = st.sidebar.date_input("Start Date", min_value=min_date, max_value=max_date, value=min_date)
end_date = st.sidebar.date_input("End Date", min_value=min_date, max_value=max_date, value=max_date)

# Filter by date first, then populate staff filter from that range
date_mask = (mods_df["Timestamp"].dt.date >= start_date) & (mods_df["Timestamp"].dt.date <= end_date)
date_filtered_df = mods_df.loc[date_mask]

mechanic_names = sorted(date_filtered_df["Mechanic"].fillna("Blank").unique().tolist())
selected_mechanics = st.sidebar.multiselect("Select Mechanic(s)", options=mechanic_names, default=mechanic_names)

# Apply mechanic filter
final_df = date_filtered_df[date_filtered_df["Mechanic"].isin(selected_mechanics)].copy()

# -----------------------------
# Dashboard Title and Logo
# -----------------------------
logo_url = "https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png"

col1, col2 = st.columns([4, 1])
with col1:
    st.markdown("""<div style='display: flex; align-items: center;'>
    <img src='https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png' width='200' style='margin-right: 20px'>
    <h2 style='color: #1e90ff;'>SAC Mods Dashboard</h2>
</div>
""", unsafe_allow_html=True)

# -----------------------------
# Summary Metrics
# -----------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_sales = final_df["Sales"].sum()
    st.metric("Total Sales", f"${total_sales:,.2f}")

with col2:
    total_transactions = len(final_df)
    st.metric("Transactions", total_transactions)

with col3:
    if not final_df.empty and final_df["Mechanic"].notnull().any():
        top_staff = final_df.groupby("Mechanic")["Sales"].sum().idxmax()
        top_sales = final_df.groupby("Mechanic")["Sales"].sum().max()
    else:
        top_staff = "N/A"
        top_sales = 0
    st.metric("Top Seller", top_staff, f"${top_sales:,.2f}")

with col4:
    total_profit = final_df["Profit"].sum()
    st.metric("Total Profit", f"${total_profit:,.2f}")

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
# Sales & Pay by Staff
# -----------------------------
st.subheader("Sales & Pay by Staff")

staff_combined = (
    final_df.groupby("Mechanic")[["Sales", "Pay"]]
    .sum()
    .reset_index()
    .melt(id_vars="Mechanic", var_name="Metric", value_name="Amount")
)

sort_order = (
    staff_combined[staff_combined["Metric"] == "Sales"]
    .sort_values("Amount", ascending=False)["Mechanic"]
    .tolist()
)

combined_chart = alt.Chart(staff_combined).mark_bar().encode(
    x=alt.X("Amount:Q", title="Amount", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Mechanic:N", sort=sort_order, title="Mechanic"),
    color=alt.Color("Metric:N", scale=alt.Scale(domain=["Sales", "Pay"], range=["#1f77b4", "#ff7f0e"])),
    tooltip=[
        alt.Tooltip("Mechanic:N", title="Mechanic"),
        alt.Tooltip("Metric:N", title="Type"),
        alt.Tooltip("Amount:Q", title="Value", format="$,.2f"),
    ],
).properties(height=800)

st.altair_chart(combined_chart, use_container_width=True)

# -----------------------------
# Pay Summary Table
# -----------------------------
st.subheader("Pay Summary")

staff_summary = (
    final_df.groupby("Mechanic")[["Sales", "Pay"]]
    .sum()
    .reset_index()
    .sort_values(by="Sales", ascending=False)
)

staff_summary["Sales"] = staff_summary["Sales"].map("${:,.2f}".format)
staff_summary["Pay"] = staff_summary["Pay"].map("${:,.2f}".format)

st.dataframe(staff_summary, use_container_width=True, hide_index=True)

# -----------------------------
# Profit Margin by Service
# -----------------------------
st.subheader("Profit Margin by Service")

profit_by_item = (
    final_df.groupby("Item")[["Profit", "Sales"]]
    .sum()
    .reset_index()
)

top_profit_items = profit_by_item.reindex(
    profit_by_item["Profit"].abs().sort_values(ascending=False).index
).head(10)

top_profit_items["Color"] = top_profit_items["Profit"].apply(lambda x: "green" if x >= 0 else "red")

profit_chart = alt.Chart(top_profit_items).mark_bar().encode(
    x=alt.X("Profit:Q", title="Total Profit", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Item:N", sort="-x", title="Service"),
    color=alt.Color("Color:N", scale=alt.Scale(domain=["green", "red"], range=["#3CB371", "#FF6347"]), legend=None),
    tooltip=[
        alt.Tooltip("Item", title="Service"),
        alt.Tooltip("Profit", title="Total Profit", format="$,.2f"),
    ]
).properties(height=400)

st.altair_chart(profit_chart, use_container_width=True)

# -----------------------------
# Staff Activity: Active Days and Hours
# -----------------------------
st.subheader("Staff Activity Overview")

activity_df = final_df.copy()
activity_df["Date"] = activity_df["Timestamp"].dt.date
activity_df["Hour"] = activity_df["Timestamp"].dt.strftime("%Y-%m-%d %H")

days_active = activity_df.groupby("Mechanic")["Date"].nunique().reset_index().rename(columns={"Date": "Active Days"})
hours_active = activity_df.groupby("Mechanic")["Hour"].nunique().reset_index().rename(columns={"Hour": "Active Hours"})
activity_summary = pd.merge(days_active, hours_active, on="Mechanic")

col1, col2 = st.columns(2)

with col1:
    days_chart = alt.Chart(activity_summary).mark_bar().encode(
        x=alt.X("Active Days:Q", title="Days"),
        y=alt.Y("Mechanic:N", sort="-x", title="Mechanic"),
        tooltip=["Mechanic", "Active Days"]
    ).properties(height=400, title="Active Days per Mechanic")
    st.altair_chart(days_chart, use_container_width=True)

with col2:
    hours_chart = alt.Chart(activity_summary).mark_bar().encode(
        x=alt.X("Active Hours:Q", title="Hours"),
        y=alt.Y("Mechanic:N", sort="-x", title="Mechanic"),
        tooltip=["Mechanic", "Active Hours"]
    ).properties(height=400, title="Active Hours per Mechanic")
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
# Transactions Table (with Search & Filters)
# -----------------------------
st.subheader("Transactions")

display_df = final_df[["Timestamp", "Mechanic", "Item", "Vehicle", "Customer Name", "Sales"]].copy()
display_df = display_df.sort_values(by="Timestamp", ascending=False)

# Search and filter controls
search_col1, search_col2, search_col3 = st.columns([2, 1, 1])

with search_col1:
    search_text = st.text_input("Search logs", placeholder="Search by mechanic, customer, vehicle, or service...")

with search_col2:
    vehicle_options = ["All"] + sorted(display_df["Vehicle"].dropna().unique().tolist())
    vehicle_filter = st.selectbox("Filter by Vehicle", options=vehicle_options)

with search_col3:
    service_options = ["All"] + sorted(display_df["Item"].dropna().unique().tolist())
    service_filter = st.selectbox("Filter by Service", options=service_options)

# Apply text search (case-insensitive across all text columns)
if search_text:
    mask = display_df.apply(
        lambda row: search_text.lower() in " ".join(row.astype(str).values).lower(),
        axis=1
    )
    display_df = display_df[mask]

# Apply dropdown filters
if vehicle_filter != "All":
    display_df = display_df[display_df["Vehicle"] == vehicle_filter]
if service_filter != "All":
    display_df = display_df[display_df["Item"] == service_filter]

st.caption(f"Showing {len(display_df)} transactions")

display_df["Timestamp"] = display_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("No Timestamp")
display_df["Sales"] = display_df["Sales"].map("${:,.2f}".format)

st.dataframe(display_df, use_container_width=True, hide_index=True)

# -----------------------------
# Revenue by Vehicle
# -----------------------------
st.subheader("Revenue by Vehicle")

sales_by_vehicle = (
    final_df.groupby("Vehicle")["Sales"]
    .sum()
    .reset_index()
    .sort_values(by="Sales", ascending=False)
    .head(15)
)

max_sales_vehicle = sales_by_vehicle["Sales"].max() if not sales_by_vehicle.empty else 0

vehicle_chart = alt.Chart(sales_by_vehicle).mark_bar().encode(
    x=alt.X("Sales:Q", title="Total Revenue", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Vehicle:N", sort="-x", title="Vehicle"),
    tooltip=["Vehicle", alt.Tooltip("Sales", format="$,.2f")],
).properties(height=500)

st.altair_chart(vehicle_chart, use_container_width=True)

# -----------------------------
# Activity Heatmap: Day of Week vs Hour
# -----------------------------
st.subheader("Activity Heatmap")

heatmap_df = final_df.copy()
heatmap_df["DayOfWeek"] = heatmap_df["Timestamp"].dt.day_name()
heatmap_df["HourOfDay"] = heatmap_df["Timestamp"].dt.hour

day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

heatmap_agg = (
    heatmap_df.groupby(["DayOfWeek", "HourOfDay"])
    .size()
    .reset_index(name="Transactions")
)

heatmap = alt.Chart(heatmap_agg).mark_rect().encode(
    x=alt.X("HourOfDay:O", title="Hour of Day"),
    y=alt.Y("DayOfWeek:N", sort=day_order, title="Day of Week"),
    color=alt.Color("Transactions:Q", scale=alt.Scale(scheme="blues"), title="Transactions"),
    tooltip=[
        alt.Tooltip("DayOfWeek:N", title="Day"),
        alt.Tooltip("HourOfDay:O", title="Hour"),
        alt.Tooltip("Transactions:Q", title="Transactions"),
    ]
).properties(height=300)

st.altair_chart(heatmap, use_container_width=True)

# -----------------------------
# Average Transaction Value by Mechanic
# -----------------------------
st.subheader("Average Transaction Value by Mechanic")

avg_by_mechanic = (
    final_df.groupby("Mechanic")["Sales"]
    .agg(["mean", "count"])
    .reset_index()
    .rename(columns={"mean": "Avg Transaction", "count": "Transactions"})
    .sort_values(by="Avg Transaction", ascending=False)
)

avg_chart = alt.Chart(avg_by_mechanic).mark_bar().encode(
    x=alt.X("Avg Transaction:Q", title="Avg Transaction Value", axis=alt.Axis(format="$,.0f")),
    y=alt.Y("Mechanic:N", sort="-x", title="Mechanic"),
    color=alt.Color("Transactions:Q", scale=alt.Scale(scheme="oranges"), title="# Transactions"),
    tooltip=[
        alt.Tooltip("Mechanic:N", title="Mechanic"),
        alt.Tooltip("Avg Transaction:Q", title="Avg Value", format="$,.2f"),
        alt.Tooltip("Transactions:Q", title="Transactions"),
    ],
).properties(height=400)

st.altair_chart(avg_chart, use_container_width=True)

# -----------------------------
# Cumulative Sales Over Time
# -----------------------------
st.subheader("Cumulative Sales Over Time")

cumulative_df = final_df.groupby(final_df["Timestamp"].dt.date)["Sales"].sum().reset_index()
cumulative_df.rename(columns={"Timestamp": "Date"}, inplace=True)
cumulative_df = cumulative_df.sort_values("Date")
cumulative_df["Cumulative Sales"] = cumulative_df["Sales"].cumsum()

area_chart = alt.Chart(cumulative_df).mark_area(
    line=True,
    opacity=0.4,
    color="#1e90ff"
).encode(
    x=alt.X("Date:T", title=None, axis=alt.Axis(format="%d/%m")),
    y=alt.Y("Cumulative Sales:Q", title="Cumulative Sales", axis=alt.Axis(format="$,.0f")),
    tooltip=[
        alt.Tooltip("Date:T", title="Date", format="%d/%m"),
        alt.Tooltip("Sales:Q", title="Daily Sales", format="$,.2f"),
        alt.Tooltip("Cumulative Sales:Q", title="Cumulative", format="$,.2f"),
    ],
).properties(height=400)

st.altair_chart(area_chart, use_container_width=True)

# -----------------------------
# Mechanic Leaderboard
# -----------------------------
st.subheader("Mechanic Leaderboard")

leaderboard = (
    final_df.groupby("Mechanic")
    .agg(
        Transactions=("Sales", "size"),
        Total_Sales=("Sales", "sum"),
        Avg_Per_Transaction=("Sales", "mean"),
    )
    .reset_index()
    .sort_values(by="Total_Sales", ascending=False)
    .reset_index(drop=True)
)

leaderboard.index = leaderboard.index + 1
leaderboard.index.name = "Rank"

# Merge in active days
lb_days = final_df.copy()
lb_days["Date"] = lb_days["Timestamp"].dt.date
days_per_mechanic = lb_days.groupby("Mechanic")["Date"].nunique().reset_index().rename(columns={"Date": "Active Days"})
leaderboard = leaderboard.merge(days_per_mechanic, on="Mechanic", how="left")

leaderboard["Total Sales"] = leaderboard["Total_Sales"].map("${:,.2f}".format)
leaderboard["Avg / Transaction"] = leaderboard["Avg_Per_Transaction"].map("${:,.2f}".format)
leaderboard = leaderboard[["Mechanic", "Transactions", "Total Sales", "Avg / Transaction", "Active Days"]]

st.dataframe(leaderboard, use_container_width=True)

# -----------------------------
# Customer Retention / Repeat Customers
# -----------------------------
st.subheader("Customer Retention")

visit_counts = (
    final_df.groupby("Customer Name")
    .size()
    .reset_index(name="Visits")
)

col1, col2 = st.columns(2)

with col1:
    st.caption("Visit Frequency Distribution")
    visit_hist = alt.Chart(visit_counts).mark_bar().encode(
        x=alt.X("Visits:Q", bin=alt.Bin(maxbins=20), title="Number of Visits"),
        y=alt.Y("count():Q", title="Number of Customers"),
        tooltip=[
            alt.Tooltip("Visits:Q", bin=alt.Bin(maxbins=20), title="Visits"),
            alt.Tooltip("count():Q", title="Customers"),
        ]
    ).properties(height=400)
    st.altair_chart(visit_hist, use_container_width=True)

with col2:
    st.caption("Top Repeat Customers")
    top_repeats = visit_counts.sort_values("Visits", ascending=False).head(15)
    repeat_chart = alt.Chart(top_repeats).mark_bar().encode(
        x=alt.X("Visits:Q", title="Total Visits"),
        y=alt.Y("Customer Name:N", sort="-x", title="Customer"),
        tooltip=["Customer Name", "Visits"],
    ).properties(height=400)
    st.altair_chart(repeat_chart, use_container_width=True)

# -----------------------------
# Self-Service Detection (Mechanic worked on own car)
# -----------------------------
st.subheader("Self-Service Detection")
st.caption("Transactions where the Mechanic name matches the Customer name")

self_service = final_df[
    final_df["Mechanic"].str.lower().str.strip()
    == final_df["Customer Name"].str.lower().str.strip()
].copy()

if self_service.empty:
    st.info("No self-service transactions found in the selected period.")
else:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Self-Service Transactions", len(self_service))
    with col2:
        self_revenue = self_service["Sales"].sum()
        st.metric("Self-Service Revenue", f"${self_revenue:,.2f}")
    with col3:
        pct = (len(self_service) / len(final_df)) * 100 if len(final_df) > 0 else 0
        st.metric("% of All Transactions", f"{pct:.1f}%")

    # Count by mechanic
    self_by_mechanic = (
        self_service.groupby("Mechanic")
        .agg(Count=("Sales", "size"), Revenue=("Sales", "sum"))
        .reset_index()
        .sort_values(by="Count", ascending=False)
    )

    self_chart = alt.Chart(self_by_mechanic).mark_bar().encode(
        x=alt.X("Count:Q", title="Self-Service Transactions"),
        y=alt.Y("Mechanic:N", sort="-x", title="Mechanic"),
        color=alt.value("#e74c3c"),
        tooltip=[
            alt.Tooltip("Mechanic:N", title="Mechanic"),
            alt.Tooltip("Count:Q", title="Transactions"),
            alt.Tooltip("Revenue:Q", title="Revenue", format="$,.2f"),
        ],
    ).properties(height=max(200, len(self_by_mechanic) * 40))

    st.altair_chart(self_chart, use_container_width=True)

    # Full transaction table
    st.caption("Transaction Detail")
    self_display = self_service[["Timestamp", "Mechanic", "Customer Name", "Vehicle", "Item", "Sales"]].copy()
    self_display = self_display.sort_values(by="Timestamp", ascending=False)
    self_display["Timestamp"] = self_display["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("No Timestamp")
    self_display["Sales"] = self_display["Sales"].map("${:,.2f}".format)
    st.dataframe(self_display, use_container_width=True, hide_index=True)

# -----------------------------
# Employee of the Month
# -----------------------------
st.markdown("---")
st.subheader("Employee of the Month")

# Exclude self-service transactions (mechanic working on own car)
customer_sales_df = final_df[
    final_df["Mechanic"].str.lower().str.strip()
    != final_df["Customer Name"].str.lower().str.strip()
].copy()

# Sales to customers (excluding own cars)
eom_sales = (
    customer_sales_df.groupby("Mechanic")["Sales"]
    .sum()
    .reset_index()
    .rename(columns={"Sales": "Customer Sales"})
)

# Active hours in shop
eom_hours_df = final_df.copy()
eom_hours_df["Hour"] = eom_hours_df["Timestamp"].dt.strftime("%Y-%m-%d %H")
eom_hours = (
    eom_hours_df.groupby("Mechanic")["Hour"]
    .nunique()
    .reset_index()
    .rename(columns={"Hour": "Active Hours"})
)

# Merge and score
eom = pd.merge(eom_sales, eom_hours, on="Mechanic", how="outer").fillna(0)

if not eom.empty and len(eom) > 0:
    # Normalize each metric to 0-100 scale
    max_sales = eom["Customer Sales"].max()
    max_hours = eom["Active Hours"].max()

    eom["Sales Score"] = (eom["Customer Sales"] / max_sales * 100) if max_sales > 0 else 0
    eom["Hours Score"] = (eom["Active Hours"] / max_hours * 100) if max_hours > 0 else 0

    # Weighted composite: 75% sales, 25% hours
    eom["Final Score"] = (eom["Sales Score"] * 0.75) + (eom["Hours Score"] * 0.25)
    eom = eom.sort_values("Final Score", ascending=False).reset_index(drop=True)

    winner = eom.iloc[0]

    # Trophy display
    st.markdown(
        f"""
        <div style='text-align: center; padding: 30px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
                    border-radius: 16px; border: 2px solid #e2b714; margin-bottom: 20px;'>
            <div style='font-size: 64px; margin-bottom: 10px;'>&#127942;</div>
            <div style='font-size: 32px; font-weight: bold; color: #e2b714;'>{winner["Mechanic"]}</div>
            <div style='font-size: 16px; color: #ccc; margin-top: 8px;'>
                Customer Sales: ${winner["Customer Sales"]:,.2f} &nbsp;|&nbsp; Active Hours: {int(winner["Active Hours"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Transparency: show full breakdown
    with st.expander("How was this determined?"):
        st.markdown("""
**Scoring Method**
- **75% weighting** — Customer Sales (self-service transactions excluded)
- **25% weighting** — Active Hours in Shop (unique hours with at least one transaction)

Each metric is normalized to a 0–100 scale (best performer = 100), then combined using the weights above.
Self-service transactions (where Mechanic = Customer) are excluded from the sales component to ensure the score reflects genuine customer work.
        """)

        # Show the scored table
        eom_display = eom.copy()
        eom_display.index = eom_display.index + 1
        eom_display.index.name = "Rank"
        eom_display["Customer Sales"] = eom_display["Customer Sales"].map("${:,.2f}".format)
        eom_display["Active Hours"] = eom_display["Active Hours"].astype(int)
        eom_display["Sales Score"] = eom_display["Sales Score"].map("{:.1f}".format)
        eom_display["Hours Score"] = eom_display["Hours Score"].map("{:.1f}".format)
        eom_display["Final Score"] = eom_display["Final Score"].map("{:.1f}".format)

        st.dataframe(eom_display, use_container_width=True)

        # Bar chart of final scores
        score_chart = alt.Chart(eom).mark_bar().encode(
            x=alt.X("Final Score:Q", title="Weighted Score (0–100)"),
            y=alt.Y("Mechanic:N", sort="-x", title="Mechanic"),
            color=alt.condition(
                alt.datum.Mechanic == winner["Mechanic"],
                alt.value("#e2b714"),
                alt.value("#1f77b4"),
            ),
            tooltip=[
                alt.Tooltip("Mechanic:N", title="Mechanic"),
                alt.Tooltip("Customer Sales:Q", title="Customer Sales", format="$,.2f"),
                alt.Tooltip("Active Hours:Q", title="Active Hours"),
                alt.Tooltip("Final Score:Q", title="Score", format=".1f"),
            ],
        ).properties(height=max(200, len(eom) * 40))

        st.altair_chart(score_chart, use_container_width=True)
else:
    st.info("Not enough data to determine Employee of the Month.")
