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

# UPDATED: Set to 5000ms (5 seconds) per request
st_autorefresh(interval=5000, key="refresh")

# Site Metadata & EST Timezone
LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek — Cullowhee, NC"
BASE_FLOW_IN = 6.0  
EST_TZ = pytz.timezone('US/Eastern')

# Secrets
# (Keeping your provided keys, though usually these are in .streamlit/secrets.toml)
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

# Initialize Session State values if they don't exist
if 'creek_depth' not in st.session_state:
    st.session_state.creek_depth = 6.00
if 'creek_flow' not in st.session_state:
    st.session_state.creek_flow = 5.00

# Creek Depth Logic: Range 5.50 - 6.50, increment 0.02
depth_change = np.random.choice([-0.02, 0.0, 0.02])
st.session_state.creek_depth = round(max(5.50, min(6.50, st.session_state.creek_depth + depth_change)), 2)

# Creek Flow Logic: Range 4.75 - 5.10, increment 0.02
flow_change = np.random.choice([-0.02, 0.0, 0.02])
st.session_state.creek_flow = round(max(4.75, min(5.10, st.session_state.creek_flow + flow_change)), 2)

# ─────────────────────────────────────────────
#  HYDROLOGIC MODELS
# ─────────────────────────────────────────────

def estimate_soil_moisture(rain_30d, today_rain=0.0):
    FIELD_CAPACITY, WILTING_POINT, MAX_STORAGE = 2.16, 1.80, 2.66
    storage = FIELD_CAPACITY * 0.7 
    for rain in rain_30d: storage = max(WILTING_POINT, min(MAX_STORAGE, storage + rain - 0.08))
    storage = min(MAX_STORAGE, storage + today_rain)
    pct = max(0, min(100, ((storage - WILTING_POINT) / (MAX_STORAGE - WILTING_POINT)) * 100))
    status, color = ("SATURATED", "#FF3333") if pct >= 90 else ("WET", "#FF8C00") if pct >= 75 else ("MOIST", "#FFD700") if pct >= 50 else ("ADEQUATE", "#00FF9C") if pct >= 25 else ("DRY", "#5AC8FA")
    return round(pct, 1), status, color, round(storage, 2)

@st.cache_data(ttl=300)
def fetch_ambient():
    try:
        r = requests.get("https://api.ambientweather.net/v1/devices", params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10)
        last = r.json()[0].get("lastData", {})
        return {
            "temp": last.get("tempf"), 
            "hum": last.get("humidity"), 
            "wind": last.get("windspeedmph", 0), 
            "rain": last.get("dailyrainin", 0.0), 
            "hourly_rain": last.get("hourlyrainin", 0.0), 
            "ok": True
        }
    except: return {"ok": False}

def make_gauge(value, title, min_val=0, max_val=100, unit="%", color="#0088FF", steps=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "valueformat": ".2f", "font": {"size": 24, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val], "tickfont": {"size": 8}}, "bar": {"color": color, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)", "steps": steps if steps else []}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=175)
    return fig

# ─────────────────────────────────────────────
#  GROUND TRUTH PROCESSING (AWN)
# ─────────────────────────────────────────────
current_time_est = datetime.now(EST_TZ).strftime("%m/%d/%Y %I:%M %p EST")
ambient = fetch_ambient()
rain_total = ambient.get("rain", 0.0)
rain_intensity = ambient.get("hourly_rain", 0.0)

# Apply the simulated values
creek_depth_raw = st.session_state.creek_depth
creek_flow_cfs = st.session_state.creek_flow
soil_pct, soil_status, soil_color, _ = estimate_soil_moisture([0.0]*30, rain_total)

# CRISIS TRIGGER LOGIC
if creek_depth_raw > 60:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,51,51,0.2); border-color:#FF3333; color:#FF3333;">⚠️ CRITICAL: CREEK DEPTH EXCEEDS UPPER THRESHOLD ({creek_depth_raw}")</div>', unsafe_allow_html=True)
elif creek_depth_raw == 60:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,255,0,0.2); border-color:#FFFF00; color:#FFFF00;">📢 WARNING: CREEK AT CRITICAL LEVEL (60")</div>', unsafe_allow_html=True)

st.markdown(f'<div class="site-header"><div class="site-title">NOAH | CULLOWHEE HYDROMETRIC SENTINEL</div><div style="color:#7AACCC; font-family:\'Share Tech Mono\';">{SITE} | {current_time_est}</div></div>', unsafe_allow_html=True)

# ROW 1: MISSION COMMAND HYDROMETRICS
st.markdown('<div class="panel"><div class="panel-title">🌊 Primary Hydrologic State — Dynamic Simulation Active</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5, c6 = st.columns(6)

with c1:
    depth_color = "#FF3333" if creek_depth_raw > 60 else "#FFFF00" if creek_depth_raw == 60 else "#0088FF"
    depth_steps = [{'range': [0, 60], 'color': "rgba(0, 136, 255, 0.1)"}, {'range': [60, 100], 'color': "rgba(255, 51, 51, 0.3)"}]
    # Adjusted range of gauge for visibility of small changes
    st.plotly_chart(make_gauge(creek_depth_raw, "CREEK DEPTH", 5, 7, "\"", depth_color, steps=depth_steps), use_container_width=True)

with c2: 
    # Adjusted range of gauge for visibility of small changes
    st.plotly_chart(make_gauge(creek_flow_cfs, "EST. CREEK FLOW", 4, 6, " CFS", ("#FF3333" if creek_depth_raw > 60 else "#00FF9C")), use_container_width=True)

with c3: st.plotly_chart(make_gauge(soil_pct, "SOIL SATURATION", 0, 100, "%", soil_color), use_container_width=True)
with c4: st.plotly_chart(make_gauge(rain_intensity, "RAIN INTENSITY", 0, 4, "\"/HR", "#5AC8FA"), use_container_width=True)
with c5: st.plotly_chart(make_gauge(rain_total, "RAIN TODAY", 0, 5, "\"", "#0088FF"), use_container_width=True)
with c6: st.plotly_chart(make_gauge(ambient.get("temp", 72), "TEMPERATURE", 0, 110, "°F", "#FF8C00"), use_container_width=True)
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
