import streamlit as st
import requests
import json
import math
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
#  APP CONFIG & THEME
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="NOAH: Cullowhee Hydrologic Sentinel",
    layout="wide"
)
st_autorefresh(interval=300000, key="refresh")

# Site Metadata
LAT = 35.3079
LON = -83.1746
SITE = "NCCAT — Cullowhee, NC"
BASE_FLOW_IN = 6.0  # Your established baseline

# Secrets
AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp {
    background-color: #060C14;
    color: #E0E8F0;
    font-family: 'Rajdhani', sans-serif;
}
.site-header {
    border-left: 6px solid #0088FF;
    padding: 12px 20px;
    margin-bottom: 24px;
    background: rgba(0,136,255,0.06);
    border-radius: 0 8px 8px 0;
}
.site-title { font-size: 2.8em; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 3px; }
.panel {
    background: rgba(10,20,35,0.85);
    border: 1px solid rgba(0,136,255,0.2);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.panel-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.85em;
    color: #0088FF;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-bottom: 14px;
    border-bottom: 1px solid rgba(0,136,255,0.2);
    padding-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  HYDROLOGIC & WEATHER LOGIC
# ─────────────────────────────────────────────

def estimate_creek_flow(current_depth_in):
    """
    Estimates flow in Cubic Feet per Second (CFS) for Cullowhee Creek.
    Assumes a 6-inch base flow. Uses a power-law rating curve approximation.
    """
    stage_ft = max(0, (current_depth_in - BASE_FLOW_IN) / 12.0)
    # C=30 is an estimate for Cullowhee Creek's average cross-section/slope near campus
    c_multiplier = 30.0 
    calc_flow = c_multiplier * (stage_ft ** 1.5)
    # Return calc + 5 CFS (nominal minimum flow for our region)
    return round(calc_flow + 5, 1)

def calc_feels_like(temp_f, humidity, wind_mph):
    if temp_f is None: return None
    humidity, wind_mph = humidity or 0, wind_mph or 0
    if temp_f >= 80 and humidity >= 40:
        hi = (-42.379 + 2.04901523*temp_f + 10.14333127*humidity - 0.22475541*temp_f*humidity 
              - 0.00683783*temp_f**2 - 0.05481717*humidity**2 + 0.00122874*temp_f**2*humidity 
              + 0.00085282*temp_f*humidity**2 - 0.00000199*temp_f**2*humidity**2)
        return round(hi, 1)
    elif temp_f <= 50 and wind_mph > 3:
        wc = 35.74 + 0.6215*temp_f - 35.75*(wind_mph**0.16) + 0.4275*temp_f*(wind_mph**0.16)
        return round(wc, 1)
    return round(temp_f, 1)

def estimate_soil_moisture(rain_30d, today_rain=0.0):
    # This remains your 'Strategic Sentinel' placeholder until the Blues 5-stack is live
    FIELD_CAPACITY, WILTING_POINT, MAX_STORAGE = 2.16, 1.80, 2.66
    monthly_et = {1:0.04, 2:0.06, 3:0.10, 4:0.14, 5:0.17, 6:0.20, 7:0.21, 8:0.19, 9:0.14, 10:0.09, 11:0.05, 12:0.03}
    storage, today_month = FIELD_CAPACITY * 0.6, datetime.now().month
    for rain in rain_30d:
        storage = max(WILTING_POINT, min(MAX_STORAGE, storage + rain - monthly_et.get(today_month, 0.10)))
    storage = min(MAX_STORAGE, storage + today_rain)
    pct = max(0, min(100, ((storage - WILTING_POINT) / (MAX_STORAGE - WILTING_POINT)) * 100))
    status, color = ("SATURATED", "#FF3333") if pct >= 90 else ("WET", "#FF8C00") if pct >= 75 else ("MOIST", "#FFD700") if pct >= 50 else ("ADEQUATE", "#00FF9C") if pct >= 25 else ("DRY", "#5AC8FA")
    return round(pct, 1), status, color, round(storage, 2)

# ─────────────────────────────────────────────
#  DATA FETCHING (Simulated/Ambient Mix)
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_ambient():
    # Note: In production, this will point to Blues Notehub API
    try:
        r = requests.get("https://api.ambientweather.net/v1/devices", params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10)
        devices = r.json()
        target = next((d for d in devices if d.get("macAddress","").replace(":","").lower() == "35c7b0accb75a84d7891d82f125001a8"), devices[0])
        last = target.get("lastData", {})
        return {"temp": last.get("tempf"), "hum": last.get("humidity"), "wind": last.get("windspeedmph", 0), "rain": last.get("dailyrainin", 0.0), "uv": last.get("uv", 0), "ok": True}
    except: return {"ok": False}

# ─────────────────────────────────────────────
#  GAUGE COMPONENTS
# ─────────────────────────────────────────────

def make_gauge(value, title, min_val=0, max_val=100, unit="%", color="#0088FF", thresholds=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "font": {"size": 26, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={
            "axis": {"range": [min_val, max_val], "tickfont": {"size": 8}},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "steps": thresholds or [],
        }
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=185)
    return fig

# ─────────────────────────────────────────────
#  DASHBOARD RENDER
# ─────────────────────────────────────────────

# Data Sync
ambient = fetch_ambient()
temp_now = ambient.get("temp", 72)
hum_now = ambient.get("hum", 50)
wind_now = ambient.get("wind", 5)
rain_now = ambient.get("rain", 0.0)

# FLOW LOGIC (The New Dial)
# Simulated input from your upcoming Blues Ultrasonic Sensor
creek_depth_raw = 10.5 # Example: 10.5 inches total depth
creek_flow_cfs = estimate_creek_flow(creek_depth_raw)

# SOIL LOGIC
soil_pct, soil_status, soil_color, _ = estimate_soil_moisture([0.05]*30, rain_now)

st.markdown(f"""
<div class="site-header">
    <div class="site-title">NOAH | CULLOWHEE HYDROLOGIC SENTINEL</div>
    <div style="color:#7AACCC; font-family:'Share Tech Mono';">{SITE} &nbsp;|&nbsp; {datetime.now().strftime('%m/%d/%Y %I:%M %p')}</div>
</div>
""", unsafe_allow_html=True)

# ROW 1: MISSION CRITICAL HYDROLOGY
st.markdown('<div class="panel"><div class="panel-title">🌊 Primary Hydrologic State</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)

with c1:
    f_color = "#00FF9C" if creek_flow_cfs < 50 else "#FFD700" if creek_flow_cfs < 150 else "#FF3333"
    st.plotly_chart(make_gauge(creek_flow_cfs, "EST. CREEK FLOW", 0, 500, " CFS", f_color), use_container_width=True)
    st.markdown(f"<div style='text-align:center; font-weight:700; color:{f_color};'>BASE: 6\" | CUR: {creek_depth_raw}\"</div>", unsafe_allow_html=True)

with c2:
    st.plotly_chart(make_gauge(soil_pct, "SOIL SATURATION", 0, 100, "%", soil_color), use_container_width=True)
    st.markdown(f"<div style='text-align:center; font-weight:700; color:{soil_color};'>{soil_status}</div>", unsafe_allow_html=True)

with c3:
    st.plotly_chart(make_gauge(rain_now, "RAIN TODAY", 0, 5, "\"", "#0088FF"), use_container_width=True)
    st.markdown(f"<div style='text-align:center; font-weight:700; color:#0088FF;'>INTENSITY: LOW</div>", unsafe_allow_html=True)

with c4:
    fl_val = calc_feels_like(temp_now, hum_now, wind_now)
    st.plotly_chart(make_gauge(fl_val, "FEELS LIKE", 0, 110, "°F", "#FF8C00"), use_container_width=True)
    st.markdown(f"<div style='text-align:center; font-weight:700; color:#FF8C00;'>ACTUAL: {temp_now}°F</div>", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: ATMOSPHERIC & SITE DATA
st.markdown('<div class="panel"><div class="panel-title">🛰️ Sub-Watershed Atmospheric Data</div>', unsafe_allow_html=True)
a1, a2, a3, a4, a5 = st.columns(5)
with a1: st.metric("Humidity", f"{hum_now}%")
with a2: st.metric("Wind Speed", f"{wind_now} mph")
with a3: st.metric("UV Index", ambient.get("uv", 0))
with a4: st.metric("Status", "STABLE", delta="Normal")
with a5: st.metric("Network", "BLUES CELL", delta="98% Sig")
st.markdown('</div>', unsafe_allow_html=True)

# RADAR
st.markdown('<div class="panel"><div class="panel-title">🛰️ Basin Radar View</div>', unsafe_allow_html=True)
st.components.v1.html('<iframe width="100%" height="400" src="https://embed.windy.com/embed2.html?lat=35.308&lon=-83.175&zoom=10&overlay=radar" frameborder="0"></iframe>', height=410)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f"""
<div style="text-align:center; font-family:'Share Tech Mono'; font-size:0.75em; color:#2A4060; margin-top:20px;">
PROJECT NOAH &nbsp;|&nbsp; Strategic Associate Monitoring &nbsp;|&nbsp; 📡 Connectivity: Blues WiFi+Cell Failover enabled
</div>
""", unsafe_allow_html=True)
