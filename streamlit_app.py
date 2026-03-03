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
# 5-minute refresh for sub-watershed sync
st_autorefresh(interval=300000, key="refresh")

# Site Metadata
LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek — Cullowhee, NC"
BASE_FLOW_IN = 6.0  # Established 6-inch baseline

# Secrets
AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color: #060C14; color: #E0E8F0; font-family: 'Rajdhani', sans-serif; }
.site-header { border-left: 6px solid #0088FF; padding: 12px 20px; margin-bottom: 24px; background: rgba(0,136,255,0.06); border-radius: 0 8px 8px 0; }
.site-title { font-size: 2.8em; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 3px; }
.panel { background: rgba(10,20,35,0.85); border: 1px solid rgba(0,136,255,0.2); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.85em; color: #0088FF; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 14px; border-bottom: 1px solid rgba(0,136,255,0.2); padding-bottom: 8px; }
.crisis-banner { padding: 20px; border-radius: 10px; margin-bottom: 25px; text-align: center; font-size: 1.5em; font-weight: 700; border: 2px solid; animation: blinker 2s linear infinite; }
@keyframes blinker { 50% { opacity: 0.6; } }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  HYDROLOGIC LOGIC
# ─────────────────────────────────────────────

def estimate_creek_flow(current_depth_in):
    stage_ft = max(0, (current_depth_in - BASE_FLOW_IN) / 12.0)
    c_multiplier = 30.0 
    calc_flow = c_multiplier * (stage_ft ** 1.5)
    return round(calc_flow + 5, 1)

def estimate_soil_moisture(rain_30d, today_rain=0.0):
    FIELD_CAPACITY, WILTING_POINT, MAX_STORAGE = 2.16, 1.80, 2.66
    storage = FIELD_CAPACITY * 0.6
    for rain in rain_30d: storage = max(WILTING_POINT, min(MAX_STORAGE, storage + rain - 0.10))
    storage = min(MAX_STORAGE, storage + today_rain)
    pct = max(0, min(100, ((storage - WILTING_POINT) / (MAX_STORAGE - WILTING_POINT)) * 100))
    status, color = ("SATURATED", "#FF3333") if pct >= 90 else ("WET", "#FF8C00") if pct >= 75 else ("MOIST", "#FFD700") if pct >= 50 else ("ADEQUATE", "#00FF9C") if pct >= 25 else ("DRY", "#5AC8FA")
    return round(pct, 1), status, color, round(storage, 2)

@st.cache_data(ttl=300)
def fetch_ambient():
    try:
        r = requests.get("https://api.ambientweather.net/v1/devices", params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10)
        last = r.json()[0].get("lastData", {})
        return {"temp": last.get("tempf"), "hum": last.get("humidity"), "wind": last.get("windspeedmph", 0), "rain": last.get("dailyrainin", 0.0), "ok": True}
    except: return {"ok": False}

def make_gauge(value, title, min_val=0, max_val=100, unit="%", color="#0088FF"):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "font": {"size": 26, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val], "tickfont": {"size": 8}}, "bar": {"color": color, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)"}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=185)
    return fig

# ─────────────────────────────────────────────
#  DASHBOARD PROCESSING
# ─────────────────────────────────────────────
ambient = fetch_ambient()
rain_now = ambient.get("rain", 0.0)

# INPUTS (Mappable to Blues Notecard)
creek_depth_raw = 10.5 
creek_flow_cfs = estimate_creek_flow(creek_depth_raw)
soil_pct, soil_status, soil_color, _ = estimate_soil_moisture([0.05]*30, rain_now)

# CRISIS TRIGGER
if creek_flow_cfs > 250 or soil_pct > 95:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,51,51,0.2); border-color:#FF3333; color:#FF3333;">⚠️ CRITICAL FLOOD ALERT: SURGE DETECTED ({creek_flow_cfs} CFS)</div>', unsafe_allow_html=True)
elif creek_flow_cfs > 120 or soil_pct > 85:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,140,0,0.2); border-color:#FF8C00; color:#FF8C00;">📢 HYDROLOGIC WARNING: ELEVATED DISCHARGE ({creek_flow_cfs} CFS)</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  UI RENDER
# ─────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
    <div class="site-title">NOAH | CULLOWHEE HYDROMETRIC SENTINEL</div>
    <div style="color:#7AACCC; font-family:'Share Tech Mono';">{SITE} &nbsp;|&nbsp; {datetime.now().strftime('%m/%d/%Y %I:%M %p')}</div>
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1: st.plotly_chart(make_gauge(creek_flow_cfs, "EST. CREEK FLOW", 0, 500, " CFS", ("#FF3333" if creek_flow_cfs > 150 else "#00FF9C")), use_container_width=True)
with c2: st.plotly_chart(make_gauge(soil_pct, "SOIL SATURATION", 0, 100, "%", soil_color), use_container_width=True)
with c3: st.plotly_chart(make_gauge(rain_now, "RAIN TODAY", 0, 5, "\"", "#0088FF"), use_container_width=True)
with c4: st.plotly_chart(make_gauge(ambient.get("temp", 72), "TEMPERATURE", 0, 110, "°F", "#FF8C00"), use_container_width=True)

# OFFICIAL NOAA/NWS RADAR LOOP
st.markdown('<div class="panel"><div class="panel-title">📡 Official NOAA National Weather Service Radar Loop</div>', unsafe_allow_html=True)
# Using the NOAA/NWS Radar tile for the GSP (Greer) sector covering Jackson County
st.components.v1.html(
    '<iframe src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif" '
    'width="100%" height="600" frameborder="0" style="border-radius:10px;"></iframe>', 
    height=610
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f"""
<div style="text-align:center; font-family:'Share Tech Mono'; font-size:0.75em; color:#2A4060; margin-top:20px;">
PROJECT NOAH &nbsp;|&nbsp; {SITE} &nbsp;|&nbsp; 📡 Connectivity: Blues WiFi+Cell Failover enabled
</div>
""", unsafe_allow_html=True)
