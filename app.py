import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import requests
import calendar

# Streamlit layout
st.set_page_config(layout="wide")

# Supabase credentials
url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["anon_key"]
supabase: Client = create_client(url, key)

# Commodity tickers
commodities = {
    "Cocoa": "CC=F",
    "Coffee": "KC=F",
    "Corn": "ZC=F",
    "Cotton": "CT=F",
    "Soybean": "ZS=F"
}

# Load Supabase data
@st.cache_data
def load_supabase_data():
    prod_share_data = supabase.table("Production_share").select("*").execute().data
    prod_stage_data = supabase.table("Production_mapping").select("*").execute().data
    return pd.DataFrame(prod_share_data), pd.DataFrame(prod_stage_data)

df_share, df_mapping = load_supabase_data()

# Weather anomaly fetch function
def get_temperature_anomaly(lat, lon):
    try:
        url_hist = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}&start_date=2020-01-01&end_date=2020-12-31"
            f"&daily=temperature_2m_mean&timezone=UTC"
        )
        hist = requests.get(url_hist).json()

        url_now = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&daily=temperature_2m_mean&timezone=UTC"
        )
        now = requests.get(url_now).json()

        if "daily" in hist and "temperature_2m_mean" in hist["daily"]:
            hist_avg = sum(hist["daily"]["temperature_2m_mean"]) / len(hist["daily"]["temperature_2m_mean"])
            now_avg = sum(now["daily"]["temperature_2m_mean"]) / len(now["daily"]["temperature_2m_mean"])
            return round(now_avg - hist_avg, 2)
    except Exception as e:
        print(f"Error at {lat},{lon}: {e}")
        return None

def calculate_anomaly_for_commodity(df_commodity):
    anomalies = []
    for _, row in df_commodity.iterrows():
        lat, lon = row["Latitude"], row["Longitude"]
        if pd.notnull(lat) and pd.notnull(lon):
            anomaly = get_temperature_anomaly(lat, lon)
            anomalies.append(anomaly)
        else:
            anomalies.append(None)
    df_commodity["Temperature Anomaly"] = anomalies
    return df_commodity

def render_production_map(commodity, df_commodity):
    fig = px.scatter_geo(
        df_commodity,
        lat="Latitude",
        lon="Longitude",
        text="Country",
        size="Share of Global Production",
        color="Temperature Anomaly",
        color_continuous_scale="RdBu_r",
        projection="natural earth",
        title=f"{commodity} - Producers & Temp Anomalies",
        size_max=30,
        template="plotly_dark"
    )
    fig.update_traces(marker=dict(line=dict(width=1, color='white')))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0))
    return fig

# Load 3-month daily prices
@st.cache_data
def load_price_data():
    return {name: yf.Ticker(ticker).history(period="3mo", interval="1d")
            for name, ticker in commodities.items()}
data = load_price_data()

# UI - Title and Slicer
st.title("🌾 Agro Commodity Dashboard")
selected_commodities = st.multiselect("Select Commodities", list(commodities.keys()), default=list(commodities.keys()))

# Loop over selected commodities
for commodity in selected_commodities:
    st.markdown("---")
    st.subheader(f"📊 {commodity}")

    col1, col2, col3, col4 = st.columns([2, 1.5, 1.2, 2])

    # 1. Price Line Chart
    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data[commodity].index,
            y=data[commodity]['Close'],
            mode='lines',
            name=f'{commodity} Price',
            line=dict(color='orange')
        ))
        fig.update_layout(
            title="Price (USD)",
            xaxis_title="Date",
            yaxis_title="Price",
            height=300,
            margin=dict(t=30, b=20, l=10, r=10),
            template='plotly_white'
        )
        st.plotly_chart(fig, use_container_width=True)

    # 2. Production Share Pie Chart
    with col2:
        df_commodity_share = df_share[df_share["Commodity"] == commodity]
        pie = go.Figure(data=[go.Pie(
            labels=df_commodity_share["Country"],
            values=df_commodity_share["Share of Global Production"],
            hole=0.45,
            textinfo='label+percent'
        )])
        pie.update_layout(title="Production Share", height=300, margin=dict(t=30, b=0, l=0, r=0))
        st.plotly_chart(pie, use_container_width=True)

    # 3. Production Stage Summary
    with col3:
        st.markdown("**Stage Summary**")
        current_month = datetime.now().strftime("%B")
        df_stage = df_mapping[
            (df_mapping["Commodity"] == commodity) & 
            (df_mapping["Month"] == current_month)
        ]
        merged = pd.merge(df_stage, df_commodity_share, on=["Country", "Commodity"])
        stage_summary = merged.groupby("Production Stage")["Share of Global Production"].sum()

        if not stage_summary.empty:
            for stage, share in stage_summary.items():
                if pd.notnull(stage):
                    st.markdown(f"- **{stage}**: {round(share * 100, 1)}%")
        else:
            st.markdown("_No stage data available this month._")

    # 4. Temperature Anomaly Summary
    with col4:
        st.markdown("**🌡️ Temp Anomalies**")
        with st.spinner("Fetching anomalies..."):
            df_temp = calculate_anomaly_for_commodity(df_commodity_share.copy())
            df_temp["Weighted Anomaly"] = df_temp["Temperature Anomaly"] * df_temp["Share of Global Production"]

            if not df_temp["Weighted Anomaly"].isnull().all():
                weighted_anomaly = df_temp["Weighted Anomaly"].sum()
                emoji = "📈" if weighted_anomaly > 0 else "📉" if weighted_anomaly < 0 else "⚖️"
                st.markdown(f"**{calendar.month_name[datetime.now().month]}**: {weighted_anomaly:+.2f}°C {emoji}")

                # Interpret the anomaly
                if weighted_anomaly > 0.25:
                    st.info("⚠️ Hotter than usual. Lower yields may lead to higher prices.")
                elif weighted_anomaly < -0.25:
                    st.info("🌧️ Cooler temps might improve yields, easing prices.")
                else:
                    st.info("➖ Stable conditions. No major price impact expected.")
            else:
                st.markdown("_No anomaly data available._")

            st.plotly_chart(render_production_map(commodity, df_temp), use_container_width=True)
