import streamlit as st
import pandas as pd
import altair as alt
import pytz
import json

# -----------------------------
# Config and URLs
# -----------------------------
st.set_page_config(page_title="SAC Weekly Prize Draw", layout="wide")

logs_url = "https://docs.google.com/spreadsheets/d/1RkQTTAAizRMHTsn7hnClowbob5rYE0zM6riGguTK0Bs/export?format=csv&gid=316444388"

ENTRY_THRESHOLD = 25000
PRIZE_AMOUNT = "1,000,000"

# -----------------------------
# Load Data
# -----------------------------
logs = pd.read_csv(logs_url)
logs.columns = ['Timestamp', 'Player', 'Vehicle', 'Service', 'Price', 'Mechanic']

mods_df = logs.rename(columns={
    "Player": "Customer Name",
    "Service": "Item",
    "Price": "Sales"
})

# Timezone: UTC -> Brisbane
mods_df["Timestamp"] = pd.to_datetime(mods_df["Timestamp"], utc=True, errors="coerce")
brisbane_tz = pytz.timezone("Australia/Brisbane")
mods_df["Timestamp"] = mods_df["Timestamp"].dt.tz_convert(brisbane_tz).dt.tz_localize(None)

# Financials
mods_df["Sales"] = mods_df["Sales"].replace(r'[\$,]', '', regex=True).astype(float)

# -----------------------------
# Sidebar Filters
# -----------------------------
st.sidebar.header("Event Filters")

min_date = mods_df["Timestamp"].min().date()
max_date = mods_df["Timestamp"].max().date()

start_date = st.sidebar.date_input("Week Start", min_value=min_date, max_value=max_date, value=min_date)
end_date = st.sidebar.date_input("Week End", min_value=min_date, max_value=max_date, value=max_date)

date_mask = (mods_df["Timestamp"].dt.date >= start_date) & (mods_df["Timestamp"].dt.date <= end_date)
final_df = mods_df.loc[date_mask].copy()

# -----------------------------
# Calculate Entries per Customer (exclude employees)
# -----------------------------
staff_names = set(
    mods_df["Mechanic"].dropna().str.lower().str.strip().unique()
)

customer_spend = (
    final_df[~final_df["Customer Name"].str.lower().str.strip().isin(staff_names)]
    .groupby("Customer Name")["Sales"]
    .sum()
    .reset_index()
    .rename(columns={"Sales": "Total Spend"})
    .sort_values(by="Total Spend", ascending=False)
)

customer_spend["Entries"] = (customer_spend["Total Spend"] // ENTRY_THRESHOLD).astype(int)
customer_spend["Progress to Next Entry"] = (
    (customer_spend["Total Spend"] % ENTRY_THRESHOLD) / ENTRY_THRESHOLD * 100
).round(1)

# Build the entries pool (one row per entry for the wheel)
entries_pool = customer_spend[customer_spend["Entries"] > 0].copy()
wheel_names = []
for _, row in entries_pool.iterrows():
    wheel_names.extend([row["Customer Name"]] * int(row["Entries"]))

# -----------------------------
# Dashboard Title and Logo
# -----------------------------
logo_url = "https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png"

st.markdown("""<div style='display: flex; align-items: center;'>
    <img src='https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png' width='200' style='margin-right: 20px'>
    <div>
        <h2 style='color: #1e90ff; margin-bottom: 0;'>SAC Weekly Prize Draw</h2>
        <p style='color: #888; margin-top: 5px; font-size: 1.1em;'>
            Spend $25,000 at SAC <svg width="18" height="12" viewBox="0 0 18 12" style="vertical-align: middle; margin: 0 4px;"><path d="M12 0l6 6-6 6-1.4-1.4L14.2 7H0V5h14.2L10.6 1.4z" fill="#888"/></svg> Earn 1 entry <svg width="18" height="12" viewBox="0 0 18 12" style="vertical-align: middle; margin: 0 4px;"><path d="M12 0l6 6-6 6-1.4-1.4L14.2 7H0V5h14.2L10.6 1.4z" fill="#888"/></svg> Win $1M weekly!
        </p>
    </div>
</div>
""", unsafe_allow_html=True)

st.write("")

# -----------------------------
# Summary Metrics
# -----------------------------
col1, col2, col3, col4 = st.columns(4)

total_spend = customer_spend["Total Spend"].sum()
total_customers = len(customer_spend)
total_entries = customer_spend["Entries"].sum()
customers_with_entries = len(entries_pool)

with col1:
    st.metric("Total Customer Spend", f"${total_spend:,.0f}")
with col2:
    st.metric("Unique Customers", total_customers)
with col3:
    st.metric("Total Entries", int(total_entries))
with col4:
    st.metric("Customers with Entries", customers_with_entries)

st.write("")

# -----------------------------
# Customer Entries Leaderboard
# -----------------------------
st.subheader("Customer Entries Leaderboard")

if not customer_spend.empty:
    # Chart: entries per customer (top 20)
    top_entries = customer_spend[customer_spend["Entries"] > 0].head(20)

    if not top_entries.empty:
        entries_chart = alt.Chart(top_entries).mark_bar().encode(
            x=alt.X("Entries:Q", title="Number of Entries", axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("Customer Name:N", sort="-x", title="Customer"),
            color=alt.value("#1e90ff"),
            tooltip=[
                alt.Tooltip("Customer Name:N", title="Customer"),
                alt.Tooltip("Total Spend:Q", title="Total Spend", format="$,.0f"),
                alt.Tooltip("Entries:Q", title="Entries"),
                alt.Tooltip("Progress to Next Entry:Q", title="Progress %", format=".1f"),
            ],
        ).properties(height=max(300, len(top_entries) * 35))

        st.altair_chart(entries_chart, use_container_width=True)

st.write("")

# -----------------------------
# Full Customer Spend & Entries Table
# -----------------------------
st.subheader("All Customer Spend & Entries")

search_text = st.text_input("Search customers", placeholder="Type a customer name...")

display_spend = customer_spend.copy()
if search_text:
    display_spend = display_spend[
        display_spend["Customer Name"].str.lower().str.contains(search_text.lower(), na=False)
    ]

st.caption(f"Showing {len(display_spend)} customers")

table_df = display_spend.copy()
table_df["Total Spend"] = table_df["Total Spend"].map("${:,.0f}".format)
table_df["Progress to Next Entry"] = table_df["Progress to Next Entry"].map("{:.1f}%".format)

st.dataframe(table_df, use_container_width=True, hide_index=True)

st.write("")

# -----------------------------
# Weekly Prize Wheel
# -----------------------------
st.subheader("Prize Wheel — Spin to Win $1M!")

if len(wheel_names) == 0:
    st.warning("No customers have earned entries yet for the selected date range.")
else:
    # Consolidate entries for the wheel display
    from collections import Counter
    name_counts = Counter(wheel_names)
    wheel_segments = list(name_counts.keys())
    wheel_weights = list(name_counts.values())

    # Pass data to the JS wheel
    wheel_data_json = json.dumps(
        [{"name": n, "entries": w} for n, w in zip(wheel_segments, wheel_weights)]
    )

    wheel_html = f"""
    <div style="display: flex; flex-direction: column; align-items: center; padding: 20px 0;">
        <canvas id="wheelCanvas" width="800" height="800"></canvas>
        <button id="spinBtn" style="
            margin-top: 20px;
            padding: 14px 48px;
            font-size: 20px;
            font-weight: bold;
            color: white;
            background: linear-gradient(135deg, #1e90ff, #0066cc);
            border: none;
            border-radius: 12px;
            cursor: pointer;
            box-shadow: 0 4px 15px rgba(30,144,255,0.4);
            transition: transform 0.15s;
        " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
            SPIN THE WHEEL
        </button>
        <div id="winnerDisplay" style="
            margin-top: 20px;
            font-size: 32px;
            font-weight: bold;
            color: #1e90ff;
            min-height: 50px;
            text-align: center;
        "></div>
    </div>

    <script>
    (function() {{
        const data = {wheel_data_json};
        const totalEntries = data.reduce((s, d) => s + d.entries, 0);
        const canvas = document.getElementById('wheelCanvas');
        const ctx = canvas.getContext('2d');
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = 360;

        // Color palette
        const colors = [
            '#1e90ff', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#e74c3c', '#bcbd22', '#17becf',
            '#ff6384', '#36a2eb', '#d4a017', '#4bc0c0', '#9966ff',
            '#ff9f40', '#6a5acd', '#c0392b', '#3498db', '#2ecc71',
            '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e'
        ];

        let currentAngle = 0;
        let spinning = false;
        const logoRadius = 65;

        // Preload logo
        const logo = new Image();
        logo.crossOrigin = 'anonymous';
        logo.src = 'https://i.ibb.co/LDb6pmJd/2023-logo-new-NO-SPARKS.png';
        let logoLoaded = false;
        logo.onload = function() {{
            logoLoaded = true;
            drawWheel(currentAngle);
        }};

        function drawWheel(rotation) {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Outer glow ring
            ctx.save();
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius + 18, 0, 2 * Math.PI);
            ctx.shadowColor = '#1e90ff';
            ctx.shadowBlur = 25;
            ctx.strokeStyle = '#1e90ff';
            ctx.lineWidth = 3;
            ctx.stroke();
            ctx.restore();

            // Outer metallic ring
            const outerGrad = ctx.createRadialGradient(centerX, centerY, radius + 4, centerX, centerY, radius + 16);
            outerGrad.addColorStop(0, '#2a2a3a');
            outerGrad.addColorStop(0.5, '#4a4a5a');
            outerGrad.addColorStop(1, '#1a1a2a');
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius + 16, 0, 2 * Math.PI);
            ctx.arc(centerX, centerY, radius + 4, 0, 2 * Math.PI, true);
            ctx.fillStyle = outerGrad;
            ctx.fill();

            // Tick marks on outer ring
            for (let t = 0; t < 60; t++) {{
                const tickAngle = (t / 60) * 2 * Math.PI;
                const inner = radius + 5;
                const outer = radius + 15;
                ctx.beginPath();
                ctx.moveTo(centerX + inner * Math.cos(tickAngle), centerY + inner * Math.sin(tickAngle));
                ctx.lineTo(centerX + outer * Math.cos(tickAngle), centerY + outer * Math.sin(tickAngle));
                ctx.strokeStyle = t % 5 === 0 ? '#1e90ff' : '#555';
                ctx.lineWidth = t % 5 === 0 ? 2 : 1;
                ctx.stroke();
            }}

            let startAngle = rotation;

            for (let i = 0; i < data.length; i++) {{
                const sliceAngle = (data[i].entries / totalEntries) * 2 * Math.PI;
                const endAngle = startAngle + sliceAngle;

                // Draw slice
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.arc(centerX, centerY, radius, startAngle, endAngle);
                ctx.closePath();
                ctx.fillStyle = colors[i % colors.length];
                ctx.fill();

                // Subtle inner bevel on each slice
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.arc(centerX, centerY, radius, startAngle, endAngle);
                ctx.closePath();
                ctx.strokeStyle = 'rgba(255,255,255,0.15)';
                ctx.lineWidth = 1;
                ctx.stroke();

                // Separator lines
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.lineTo(centerX + radius * Math.cos(startAngle), centerY + radius * Math.sin(startAngle));
                ctx.strokeStyle = 'rgba(0,0,0,0.4)';
                ctx.lineWidth = 2;
                ctx.stroke();

                // Draw label
                ctx.save();
                ctx.translate(centerX, centerY);
                ctx.rotate(startAngle + sliceAngle / 2);
                ctx.textAlign = 'right';
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 14px Arial';
                ctx.shadowColor = 'rgba(0,0,0,0.8)';
                ctx.shadowBlur = 4;
                ctx.shadowOffsetX = 1;
                ctx.shadowOffsetY = 1;

                const label = data[i].name.length > 18
                    ? data[i].name.substring(0, 17) + '...'
                    : data[i].name;
                ctx.fillText(label + ' (' + data[i].entries + ')', radius - 22, 5);
                ctx.restore();

                startAngle = endAngle;
            }}

            // Center hub - dark base
            ctx.save();
            ctx.beginPath();
            ctx.arc(centerX, centerY, logoRadius + 8, 0, 2 * Math.PI);
            ctx.fillStyle = '#0a0a14';
            ctx.shadowColor = 'rgba(0,0,0,0.8)';
            ctx.shadowBlur = 20;
            ctx.fill();
            ctx.restore();

            // Center hub - glowing ring
            ctx.save();
            ctx.beginPath();
            ctx.arc(centerX, centerY, logoRadius + 6, 0, 2 * Math.PI);
            ctx.strokeStyle = '#1e90ff';
            ctx.lineWidth = 3;
            ctx.shadowColor = '#1e90ff';
            ctx.shadowBlur = 15;
            ctx.stroke();
            ctx.restore();

            // Inner metallic ring
            const hubGrad = ctx.createRadialGradient(centerX, centerY, logoRadius - 2, centerX, centerY, logoRadius + 6);
            hubGrad.addColorStop(0, '#1a1a2e');
            hubGrad.addColorStop(0.5, '#2a2a4a');
            hubGrad.addColorStop(1, '#0a0a14');
            ctx.beginPath();
            ctx.arc(centerX, centerY, logoRadius + 5, 0, 2 * Math.PI);
            ctx.arc(centerX, centerY, logoRadius - 2, 0, 2 * Math.PI, true);
            ctx.fillStyle = hubGrad;
            ctx.fill();

            // Logo circle background
            ctx.beginPath();
            ctx.arc(centerX, centerY, logoRadius - 2, 0, 2 * Math.PI);
            ctx.fillStyle = '#0d1117';
            ctx.fill();

            // Draw logo image (or fallback text)
            if (logoLoaded) {{
                ctx.save();
                ctx.beginPath();
                ctx.arc(centerX, centerY, logoRadius - 5, 0, 2 * Math.PI);
                ctx.clip();
                const logoSize = (logoRadius - 5) * 2;
                ctx.drawImage(logo, centerX - logoSize / 2, centerY - logoSize / 2, logoSize, logoSize);
                ctx.restore();
            }} else {{
                ctx.fillStyle = '#1e90ff';
                ctx.font = 'bold 22px Arial';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('SAC', centerX, centerY);
            }}

            // Draw pointer (top) - bigger, more dramatic
            ctx.save();
            ctx.beginPath();
            ctx.moveTo(centerX - 20, 12);
            ctx.lineTo(centerX + 20, 12);
            ctx.lineTo(centerX, 58);
            ctx.closePath();
            const pointerGrad = ctx.createLinearGradient(centerX, 12, centerX, 58);
            pointerGrad.addColorStop(0, '#ff2222');
            pointerGrad.addColorStop(1, '#cc0000');
            ctx.fillStyle = pointerGrad;
            ctx.shadowColor = 'rgba(255,0,0,0.5)';
            ctx.shadowBlur = 10;
            ctx.fill();
            ctx.strokeStyle = '#880000';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.restore();

            // Pointer dot
            ctx.beginPath();
            ctx.arc(centerX, 18, 5, 0, 2 * Math.PI);
            ctx.fillStyle = '#fff';
            ctx.fill();
        }}

        function getWinner(finalAngle) {{
            // Pointer is at the top of the canvas = -PI/2 in canvas coords.
            // Slices are drawn starting from finalAngle (clockwise).
            // Find which slice the pointer sits in.
            let pointerOffset = (-Math.PI / 2 - finalAngle) % (2 * Math.PI);
            if (pointerOffset < 0) pointerOffset += 2 * Math.PI;

            let cumulative = 0;
            for (let i = 0; i < data.length; i++) {{
                const sliceAngle = (data[i].entries / totalEntries) * 2 * Math.PI;
                cumulative += sliceAngle;
                if (pointerOffset < cumulative) {{
                    return data[i].name;
                }}
            }}
            return data[data.length - 1].name;
        }}

        function spin() {{
            if (spinning) return;
            spinning = true;
            document.getElementById('winnerDisplay').innerHTML = '';

            const spinDuration = 40000 + Math.random() * 20000;
            const totalRotation = (30 + Math.random() * 20) * 2 * Math.PI;
            const startTime = performance.now();
            const startAngle = currentAngle;

            // Custom ease: fast start, very long dramatic slowdown
            function easeOut(t) {{
                if (t < 0.3) {{
                    // First 30% of time: fast, covers most rotation
                    return 0.7 * (t / 0.3);
                }} else {{
                    // Last 70% of time: slow crawl through final 30%
                    const t2 = (t - 0.3) / 0.7;
                    return 0.7 + 0.3 * (1 - Math.pow(1 - t2, 4));
                }}
            }}

            function animate(now) {{
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / spinDuration, 1);
                const easedProgress = easeOut(progress);

                currentAngle = startAngle + totalRotation * easedProgress;
                drawWheel(currentAngle);

                if (progress < 1) {{
                    requestAnimationFrame(animate);
                }} else {{
                    spinning = false;
                    const winner = getWinner(currentAngle);
                    const trophySvg = '<svg width="36" height="36" viewBox="0 0 24 24" style="vertical-align: middle; margin: 0 8px;"><path d="M5 3h14v2h-1v1a7 7 0 01-3.5 6.06A4.5 4.5 0 0116 16v1h1v2H7v-2h1v-1a4.5 4.5 0 011.5-3.94A7 7 0 016 6V5H5V3zm3 2v1a5 5 0 005 5 5 5 0 005-5V5H8z" fill="#ffd700"/><path d="M2 5h3v1H3v2a3 3 0 003 3v1a4 4 0 01-4-4V5zm17 0h3v3a4 4 0 01-4 4v-1a3 3 0 003-3V6h-2V5z" fill="#ffc107"/></svg>';
                    document.getElementById('winnerDisplay').innerHTML =
                        trophySvg + '<span style="color: #ffd700;">WINNER: ' + winner + '</span>' + trophySvg +
                        '<br><span style="font-size: 20px; color: #888;">Wins ${PRIZE_AMOUNT}!</span>';
                }}
            }}

            requestAnimationFrame(animate);
        }}

        drawWheel(currentAngle);
        document.getElementById('spinBtn').addEventListener('click', spin);
    }})();
    </script>
    """

    st.components.v1.html(wheel_html, height=960)

# -----------------------------
# Past Winners Log (Manual Tracking)
# -----------------------------
st.subheader("Past Winners")

if "winners" not in st.session_state:
    st.session_state.winners = []

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    winner_name = st.text_input("Winner Name", placeholder="Enter the winner's name...")
with col2:
    winner_date = st.date_input("Draw Date")
with col3:
    st.write("")
    st.write("")
    if st.button("Log Winner", type="primary"):
        if winner_name.strip():
            st.session_state.winners.append({
                "Winner": winner_name.strip(),
                "Date": str(winner_date),
                "Prize": f"${PRIZE_AMOUNT}"
            })
            st.success(f"Logged {winner_name.strip()} as winner!")

if st.session_state.winners:
    winners_df = pd.DataFrame(st.session_state.winners)
    st.dataframe(winners_df, use_container_width=True, hide_index=True)
else:
    st.info("No winners logged yet. Use the wheel above to draw a winner, then log them here.")
