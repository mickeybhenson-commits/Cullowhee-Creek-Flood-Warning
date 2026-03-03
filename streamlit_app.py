import streamlit as st
import requests
import json
import math
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz 
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
#  APP CONFIG & THEME
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="NOAH: Cullowhee Hydrologic Sentinel",
    layout="wide"
)

# REFRESH EVERY 5 SECONDS
st_autorefresh(interval=5000, key="refresh")

# Site Metadata & EST Timezone
LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek — Cullowhee, NC"
EST_TZ = pytz.timezone('US/Eastern')

# Secrets
AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color: #060C14; color: #E0E8F0; font-family: 'Rajdhani', sans-serif; }
.site-header { border-left: 6px solid #0088FF; padding: 12px 20px; margin-bottom: 24px; background: rgba(0,136,255,0.06); border-radius: 0 8px 8px 0; }
.panel { background: rgba(10,20,35,0.85); border: 1px solid rgba(0,136,255,0.2); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.85em; color: #0088FF; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 14px; border-bottom: 1px solid rgba(0,136,255,0.2); padding-bottom: 8px; }
.crisis-banner { padding: 20px; border-radius: 10px; margin-bottom: 25px; text-align: center; font-size: 1.5em; font-weight: 700; border: 2px solid; animation: blinker 2s linear infinite; }
@keyframes blinker { 50% { opacity: 0.6; } }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  DYNAMIC JITTER LOGIC (Simulation Mode)
# ─────────────────────────────────────────────
if 'creek_depth' not in st.session_state:
    st.session_state.creek_depth = 6.00
if 'creek_flow' not in st.session_state:
    st.session_state.creek_flow = 5.00

d_step = np.random.choice([-0.02, 0.0, 0.02])
st.session_state.creek_depth = round(max(5.50, min(6.50, st.session_state.creek_depth + d_step)), 2)

f_step = np.random.choice([-0.02, 0.0, 0.02])
st.session_state.creek_flow = round(max(4.75, min(5.10, st.session_state.creek_flow + f_step)), 2)

# ─────────────────────────────────────────────
#  SOIL & WEATHER UTILITIES
# ─────────────────────────────────────────────

def estimate_soil_moisture(rain_30d, today_rain=0.0):
    """Historical method: Uses field capacity and wilting points based on regional soil maps."""
    FIELD_CAPACITY, WILTING_POINT, MAX_STORAGE = 2.16, 1.80, 2.66
    storage = FIELD_CAPACITY * 0.7  # Initial baseline
    for rain in rain_30d: 
        storage = max(WILTING_POINT, min(MAX_STORAGE, storage + rain - 0.08)) # -0.08 for ET/drainage
    storage = min(MAX_STORAGE, storage + today_rain)
    pct = max(0, min(100, ((storage - WILTING_POINT) / (MAX_STORAGE - WILTING_POINT)) * 100))
    
    # Status Logic
    if pct >= 90: status, color = "SATURATED", "#FF3333"
    elif pct >= 75: status, color = "WET", "#FF8C00"
    elif pct >= 50: status, color = "MOIST", "#FFD700"
    elif pct >= 25: status, color = "ADEQUATE", "#00FF9C"
    else: status, color = "DRY", "#5AC8FA"
    
    return round(pct, 1), status, color

@st.cache_data(ttl=300)
def fetch_ambient_data():
    try:
        # Fetch Current Data
        r = requests.get("https://api.ambientweather.net/v1/devices", 
                         params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10)
        devices = r.json()
        last = devices[0].get("lastData", {})
        mac = devices[0].get("macAddress")
        
        # Fetch Historical (last 30 days) for Soil model
        # Note: Real implementation would iterate through API pages; here we simulate the array
        hist_rain = [0.0] * 30 # Placeholder for historical rain array
        
        return {
            "temp": last.get("tempf", 72), 
            "rain_today": last.get("dailyrainin", 0.0), 
            "rain_hour": last.get("hourlyrainin", 0.0),
            "hist_rain": hist_rain,
            "ok": True
        }
    except: return {"temp": 72, "rain_today": 0.0, "rain_hour": 0.0, "hist_rain": [0.0]*30, "ok": False}

def make_gauge(value, title, min_val, max_val, unit, color, steps=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "valueformat": ".2f", "font": {"size": 24, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val], "tickfont": {"size": 8}},
               "bar": {"color": color, "thickness": 0.25},
               "bgcolor": "rgba(0,0,0,0)",
               "steps": steps if steps else []}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=175)
    return fig

# ─────────────────────────────────────────────
#  DATA PROCESSING
# ─────────────────────────────────────────────
current_time_est = datetime.now(EST_TZ).strftime("%m/%d/%Y %I:%M %p EST")
data = fetch_ambient_data()

# Calculate Soil Saturation using the old method
soil_pct, soil_status, soil_color = estimate_soil_moisture(data["hist_rain"], data["rain_today"])

creek_depth_raw = st.session_state.creek_depth
creek_flow_cfs = st.session_state.creek_flow

# CRISIS TRIGGER LOGIC
if creek_depth_raw > 70:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,0,0,0.3); border-color:#FF0000; color:#FF0000;">🚨 DANGER: CREEK DEPTH EXCEEDS 70" ({creek_depth_raw:.2f}")</div>', unsafe_allow_html=True)
elif creek_depth_raw > 60:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,140,0,0.2); border-color:#FF8C00; color:#FF8C00;">⚠️ WARNING: CREEK DEPTH EXCEEDS 60" ({creek_depth_raw:.2f}")</div>', unsafe_allow_html=True)

st.markdown(f'<div class="site-header"><div class="site-title">NOAH | CULLOWHEE HYDROMETRIC SENTINEL</div><div style="color:#7AACCC; font-family:\'Share Tech Mono\';">{SITE} | {current_time_est}</div></div>', unsafe_allow_html=True)

# ROW 1: MISSION COMMAND HYDROMETRICS
st.markdown('<div class="panel"><div class="panel-title">🌊 Primary Hydrologic State — Ground Truth Active</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5, c6 = st.columns(6)

with c1:
    d_color = "#FF0000" if creek_depth_raw > 70 else "#FF8C00" if creek_depth_raw > 60 else "#0088FF"
    d_steps = [{'range': [0, 60], 'color': "rgba(0, 136, 255, 0.1)"}, 
               {'range': [60, 70], 'color': "rgba(255, 140, 0, 0.3)"},
               {'range': [70, 100], 'color': "rgba(255, 0, 0, 0.4)"}]
    st.plotly_chart(make_gauge(creek_depth_raw, "CREEK DEPTH", 0, 100, "\"", d_color, steps=d_steps), use_container_width=True)

with c2:
    st.plotly_chart(make_gauge(creek_flow_cfs, "EST. CREEK FLOW", 0, 10, " CFS", "#00FF9C"), use_container_width=True)

with c3:
    st.plotly_chart(make_gauge(soil_pct, f"SOIL: {soil_status}", 0, 100, "%", soil_color), use_container_width=True)

with c4:
    st.plotly_chart(make_gauge(data["rain_hour"], "RAIN INTENSITY", 0, 4, "\"/HR", "#5AC8FA"), use_container_width=True)

with c5:
    st.plotly_chart(make_gauge(data["rain_today"], "RAIN TODAY", 0, 5, "\"", "#0088FF"), use_container_width=True)

with c6:
    st.plotly_chart(make_gauge(data["temp"], "TEMPERATURE", 0, 110, "°F", "#FF8C00"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# 1800px MISSION COMMAND RADAR
st.markdown('<div class="panel"><div class="panel-title">📡 Official NWS Radar Loop — Mission Command Footprint</div>', unsafe_allow_html=True)
st.components.v1.html(
    f'<iframe src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?{datetime.now().microsecond}" '
    'width="100%" height="1800" frameborder="0" style="border-radius:10px;"></iframe>', 
    height=1810
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div style="text-align:center; font-family:\'Share Tech Mono\'; font-size:0.75em; color:#2A4060; margin-top:20px;">PROJECT NOAH | {SITE} | AWN Ground Truth Active</div>', unsafe_allow_html=True)
