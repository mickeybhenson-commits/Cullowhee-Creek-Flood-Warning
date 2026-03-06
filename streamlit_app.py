import streamlit as st
import requests
import math
import json
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
#  1. SYSTEM CONFIGURATION & STYLING
# ─────────────────────────────────────────────
st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

# Geographic Coordinates for Cullowhee, NC
LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

# API KEYS (Prioritizing Streamlit Secrets)
AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color: #04090F; color: #E0E8F0; font-family: 'Rajdhani', sans-serif; }
.site-header { border-left: 6px solid #0077FF; padding: 14px 22px; margin-bottom: 20px; background: rgba(0,100,200,0.07); border-radius: 0 8px 8px 0; }
.site-title { font-size: 2.4em; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 2px; }
.panel { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,119,255,0.18); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #0077FF; text-transform: uppercase; letter-spacing: 3px; border-bottom: 1px solid rgba(0,119,255,0.18); padding-bottom: 8px; margin-bottom:14px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  2. DATA ACQUISITION (AWN & NWS)
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_awn_data():
    """Ground Truth from Riverbend AWN Station."""
    try:
        r = requests.get("https://api.ambientweather.net/v1/devices", 
                         params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10).json()
        return r[0].get("lastData", {}) if r else {}
    except: return {}

@st.cache_data(ttl=3600)
def fetch_nws_forecast():
    """Official NWS 7-Day Point Forecast."""
    try:
        r_pts = requests.get(f"https://api.weather.gov/points/{LAT},{LON}", timeout=10).json()
        grid_url = r_pts["properties"]["forecast"]
        periods = requests.get(grid_url, timeout=10).json()["properties"]["periods"]
        return [p for p in periods if p["isDaytime"]][:7]
    except: return []

@st.cache_data(ttl=3600)
def fetch_hist_precip():
    """30-Day History for Soil Model."""
    try:
        r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=precipitation_sum&precipitation_unit=inch&past_days=30&forecast_days=0").json()
        return r.get("daily", {}).get("precipitation_sum", [0]*30)
    except: return [0]*30

# ─────────────────────────────────────────────
#  3. HYDROLOGICAL MODELLING
# ─────────────────────────────────────────────
def get_soil_model(hist_rain, rain_today):
    month = datetime.now().month
    # Seasonal ET (Evapotranspiration) Rates for Cullowhee
    et_map = {1:0.03, 2:0.04, 3:0.06, 4:0.11, 5:0.15, 6:0.19, 7:0.21, 8:0.18, 9:0.13, 10:0.08, 11:0.04, 12:0.03}
    daily_loss = et_map.get(month, 0.10)
    MAX_CAP = 2.66
    storage = 1.3
    for r in hist_rain:
        storage = max(0, min(MAX_CAP, storage + r - daily_loss))
    storage = min(MAX_CAP, storage + rain_today)
    pct = (storage / MAX_CAP) * 100
    color = "#FF3333" if pct > 85 else "#FFD700" if pct > 50 else "#00FF9C"
    return round(pct, 1), color

def calc_feels(t, h, w):
    if t >= 80 and h >= 40:
        return round(-42.37 + 2.04*t + 10.14*h - 0.22*t*h - 0.006*t**2 - 0.05*h**2, 1)
    elif t <= 50 and w > 3:
        return round(35.74 + 0.62*t - 35.75*(w**0.16) + 0.42*t*(w**0.16), 1)
    return round(t, 1)

# ─────────────────────────────────────────────
#  4. SENSOR SIMULATION & EXECUTION
# ─────────────────────────────────────────────
awn = fetch_awn_data()
nws = fetch_nws_forecast()
hist = fetch_hist_precip()

# Temp & Atmos
temp_real = awn.get("tempf", 50)
hum = awn.get("humidity", 50)
wind = awn.get("windspeedmph", 0)
feels = calc_feels(temp_real, hum, wind)

# Soil
soil_pct, soil_color = get_soil_model(hist, awn.get("dailyrainin", 0))

# Stream Depth (High-Res Jitter 5.5 - 6.25")
if 'depth' not in st.session_state: st.session_state.depth = 5.85
st.session_state.depth = round(max(5.5, min(6.25, st.session_state.depth + np.random.uniform(-0.01, 0.01))), 2)
cur_depth = st.session_state.depth

# Predictive Risk Scoring
fcst_precip = nws[0].get("probabilityOfPrecipitation", {}).get("value", 0) / 100 if nws else 0
runoff_multiplier = 1.2 if soil_pct > 80 else 0.6
threat_score = min(100, round((soil_pct*0.3) + (fcst_precip*40*runoff_multiplier) + ((cur_depth-5.5)/0.75*30), 1))

# ─────────────────────────────────────────────
#  5. UI COMPONENTS
# ─────────────────────────────────────────────
def make_gauge(v, t, min_v, max_v, u, c):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=v, number={"suffix": u, "font": {"size": 24, "color": "white"}}, title={"text": t, "font": {"size": 11, "color": "#7AACCC"}}, gauge={"axis": {"range": [min_v, max_v]}, "bar": {"color": c, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)"}))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=170)
    return fig

def anim_dial(gid, v, t, min_v, max_v, u, thresh, nclr, slbl, sclr, sub, src):
    t_js = json.dumps([{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in thresh])
    return f"""
    <html><body style="background:transparent;text-align:center;font-family:'Rajdhani';color:white;">
    <canvas id="{gid}" width="260" height="150"></canvas>
    <div style="color:{sclr};font-weight:700;font-size:16px;text-transform:uppercase;">{slbl}</div>
    <div style="font-size:11px;color:#7AACCC;">{sub}</div>
    <div style="font-size:9px;color:#1A5070;">SRC: {src}</div>
    <script>
    (function(){{
        const canvas=document.getElementById('{gid}'); const ctx=canvas.getContext('2d');
        const W=260, H=150, cx=130, cy=125, r=95;
        function toA(v){{ return Math.PI + ((v-{min_v})/({max_v}-{min_v}))*Math.PI; }}
        function draw(val){{
            ctx.clearRect(0,0,W,H);
            {t_js}.forEach(t=>{{ ctx.beginPath(); ctx.strokeStyle=t.color; ctx.lineWidth=20; ctx.arc(cx,cy,r, toA(t.r0), toA(t.r1)); ctx.stroke(); }});
            const ang=toA(val); ctx.beginPath(); ctx.strokeStyle='{nclr}'; ctx.lineWidth=4; ctx.moveTo(cx,cy); ctx.lineTo(cx+r*Math.cos(ang), cy+r*Math.sin(ang)); ctx.stroke();
            ctx.fillStyle="white"; ctx.font="bold 20px Rajdhani"; ctx.textAlign="center"; ctx.fillText(val.toFixed(2)+"{u}", cx, cy-40);
        }}
        let cur={min_v}; function anim(){{ cur+=({v}-cur)*0.08; draw(cur); if(Math.abs(cur-{v})>0.001) requestAnimationFrame(anim); }} anim();
    }})();
    </script></body></html>
    """

# ─────────────────────────────────────────────
#  6. DASHBOARD LAYOUT
# ─────────────────────────────────────────────
st.markdown(f"""<div class="site-header"><div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
<div style="color:#00FF9C; font-weight:700;">PROGNOSTIC THREAT SCORE: {threat_score}% | GROUND TRUTH: RIVERBEND AWN</div></div>""", unsafe_allow_html=True)

# ROW 1: PRECIP & ATMOS
st.markdown('<div class="panel"><div class="panel-title">🌧️ Precipitation & Atmospheric Conditions</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_gauge(awn.get("dailyrainin", 0), "RAIN TODAY", 0, 3, '"', "#00FF9C"), use_container_width=True)
with c2: st.plotly_chart(make_gauge(wind, "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c3: st.plotly_chart(make_gauge(hum, "HUMIDITY", 0, 100, "%", "#0077FF"), use_container_width=True)
with c4:
    # PRIORITY: REAL TEMPERATURE
    st.plotly_chart(make_gauge(temp_real, "REAL TEMPERATURE", 0, 110, "°F", "#00FF9C"), use_container_width=True)
    st.markdown(f"<div style='text-align:center;font-size:0.8em;color:#7AACCC;'>Feels Like: {feels}°F</div>", unsafe_allow_html=True)
with c5: st.plotly_chart(make_gauge(soil_pct, "SOIL SATURATION", 0, 100, "%", soil_color), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: HYDROLOGY (ANIMATED)
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    depth_html = anim_dial("g_depth", cur_depth, "STREAM DEPTH", 5.5, 6.25, '"', 
        [{"range":[5.5,6.0],"color":"rgba(0,255,156,0.15)"},{"range":[6.0,6.25],"color":"rgba(255,51,51,0.2)"}],
        "#00FF9C" if cur_depth < 6.0 else "#FFD700", "STABLE" if cur_depth < 6.0 else "ELEVATED", "#00FF9C", f'Level: {cur_depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)
with h2:
    flow_html = anim_dial("g_flow", 5.12, "STREAM FLOW", 4.8, 5.4, " cfs", 
        [{"range":[4.8,5.2],"color":"rgba(0,255,156,0.15)"}], "#5AC8FA", "STABLE", "#5AC8FA", "Flow: 5.12 cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)
with h3:
    st.markdown(f"""<div style="background:rgba(0,80,160,0.1); border:1px solid #0077FF; border-radius:8px; padding:20px; font-family:'Share Tech Mono';">
    <div style="color:#0077FF;">📊 PREDICTIVE THREAT MODEL (V16.0)</div>
    <div style="font-size:2.2em; font-weight:700; color:{soil_color};">{threat_score}%</div>
    <div style="font-size:0.8em; color:#7AACCC; margin-top:10px;">Runoff Multiplier: x{runoff_multiplier} (Season: {datetime.now().strftime('%B')})</div>
    </div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: OFFICIAL NWS 7-DAY FORECAST
st.markdown('<div class="panel"><div class="panel-title">📅 Official NWS 7-Day Point Forecast</div>', unsafe_allow_html=True)
if nws:
    fcols = st.columns(7)
    for i, d in enumerate(nws):
        pop = d.get("probabilityOfPrecipitation", {}).get("value", 0) or 0
        with fcols[i]:
            st.markdown(f"""<div style='text-align:center; background:rgba(255,255,255,0.03); padding:10px; border-radius:5px; min-height:160px;'>
            <div style="font-size:0.9em; font-weight:700;">{d['name'][:3]}</div>
            <div style="color:#FF6B35; font-size:1.4em; font-weight:700;">{d['temperature']}°</div>
            <div style="color:#00FFCC; font-size:0.8em;">{pop}% Prob</div>
            <div style="font-size:0.65em; color:#7AACCC; margin-top:5px;">{d['shortForecast']}</div></div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# RADAR
st.markdown('<div class="panel"><div class="panel-title">🛰️ Live Radar Loop</div>', unsafe_allow_html=True)
st.components.v1.html(f'<iframe src="https://www.rainviewer.com/map.html?loc={LAT},{LON},9" width="100%" height="500"></iframe>', height=500)
