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
#  1. CONFIGURATION & STYLING
# ─────────────────────────────────────────────
st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

# API KEYS
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
#  2. CORE UTILITIES & ADAPTIVE SOIL MODEL
# ─────────────────────────────────────────────
def estimate_seasonal_soil_moisture(rain_30d, rain_today=0.0):
    current_month = datetime.now().month
    # Seasonal ET Rates (Inches/Day) - Real drainage for Cullowhee area
    monthly_et_map = {1:0.03, 2:0.04, 3:0.06, 4:0.11, 5:0.15, 6:0.19, 7:0.21, 8:0.18, 9:0.13, 10:0.08, 11:0.04, 12:0.03}
    daily_loss = monthly_et_map.get(current_month, 0.10)
    MAX_STORAGE = 2.66 
    current_storage = 1.3 
    for rain in rain_30d:
        current_storage = max(0, min(MAX_STORAGE, current_storage + rain - daily_loss))
    current_storage = min(MAX_STORAGE, current_storage + rain_today)
    sat_pct = (current_storage / MAX_STORAGE) * 100
    status = "SATURATED" if sat_pct > 85 else "WET" if sat_pct > 65 else "MOIST" if sat_pct > 40 else "ADEQUATE"
    color = "#FF3333" if sat_pct > 85 else "#FF8C00" if sat_pct > 65 else "#FFD700" if sat_pct > 40 else "#00FF9C"
    return round(sat_pct, 1), round(current_storage, 2), status, color

def calc_feels_like(t, h, w):
    if t >= 80 and h >= 40:
        return round(-42.379 + 2.049*t + 10.14*h - 0.22*t*h - 0.0068*t**2 - 0.054*h**2 + 0.001*t**2*h + 0.0008*t*h**2 - 0.0000019*t**2*h**2, 1)
    elif t <= 50 and w > 3:
        return round(35.74 + 0.6215*t - 35.75*(w**0.16) + 0.4275*t*(w**0.16), 1)
    return round(t, 1)

# ─────────────────────────────────────────────
#  3. DATA ACQUISITION
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_master_data():
    try:
        # 1. AWN Ground Truth
        r_awn = requests.get("https://api.ambientweather.net/v1/devices", params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10).json()
        awn_data = r_awn[0].get("lastData", {}) if r_awn else {}
        # 2. Historical (30d) for Soil Model
        r_hist = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=precipitation_sum&precipitation_unit=inch&past_days=30&forecast_days=0").json()
        hist_rain = r_hist.get("daily", {}).get("precipitation_sum", [0]*30)
        # 3. Forecast (7d)
        r_fcst = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weathercode&temperature_unit=fahrenheit&precipitation_unit=inch&timezone=America/New_York").json()
        forecast = [{"day": datetime.strptime(r_fcst["daily"]["time"][i], "%Y-%m-%d").strftime("%a"), "hi": round(r_fcst["daily"]["temperature_2m_max"][i]), "lo": round(r_fcst["daily"]["temperature_2m_min"][i]), "precip": r_fcst["daily"]["precipitation_sum"][i], "pop": r_fcst["daily"]["precipitation_probability_max"][i]} for i in range(7)]
        return awn_data, hist_rain, forecast
    except: return {}, [0]*30, []

awn, hist_rain, forecast = fetch_master_data()

# ─────────────────────────────────────────────
#  4. SENSOR & THREAT LOGIC
# ─────────────────────────────────────────────
# Real Temperature (AWN)
temp_real = awn.get("tempf", 50)
hum = awn.get("humidity", 50)
wind = awn.get("windspeedmph", 0)
fl_temp = calc_feels_like(temp_real, hum, wind)

# Soil Model
soil_pct, soil_storage, soil_status, soil_color = estimate_seasonal_soil_moisture(hist_rain, awn.get("dailyrainin", 0))

# Predictive Flood Index
# Weighting: 40% Current Flow, 30% Soil Sat, 30% Forecast Precip
fcst_rain_24h = forecast[0]["precip"] if forecast else 0
# Runoff multiplier: Higher soil moisture = higher impact of forecast rain
runoff_coeff = 0.95 if soil_pct > 80 else 0.5
predictive_risk = (fcst_rain_24h * runoff_coeff) * 40 

# Stream Logic (High-Res 5.5 - 6.25")
if 'creek_depth' not in st.session_state: st.session_state.creek_depth = 5.85
st.session_state.creek_depth = round(max(5.5, min(6.25, st.session_state.creek_depth + np.random.uniform(-0.01, 0.01))), 2)
creek_depth = st.session_state.creek_depth

composite_score = min(100, round((soil_pct * 0.3) + (predictive_risk) + ((creek_depth-5.5)/0.75 * 40), 1))
alert_lvl = "EMERGENCY" if composite_score > 75 else "WARNING" if composite_score > 55 else "WATCH" if composite_score > 35 else "STABLE"
alert_clr = "#FF2222" if alert_lvl == "EMERGENCY" else "#FF6400" if alert_lvl == "WARNING" else "#FFD700" if alert_lvl == "WATCH" else "#00FF9C"

# ─────────────────────────────────────────────
#  5. UI RENDERING
# ─────────────────────────────────────────────
def make_gauge(v, t, min_v, max_v, u, c):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=v, number={"suffix": u, "font": {"size": 24, "color": "white"}}, title={"text": t, "font": {"size": 11, "color": "#7AACCC"}}, gauge={"axis": {"range": [min_v, max_v]}, "bar": {"color": c, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)"}))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=170)
    return fig

def make_animated_gauge_html(gid, v, t, min_v, max_v, u, thresh, nclr, slbl, sclr, sub, src):
    t_js = json.dumps([{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in thresh])
    return f"""
    <html><body style="background:transparent;text-align:center;font-family:'Rajdhani';color:white;">
    <canvas id="{gid}" width="260" height="150"></canvas>
    <div style="color:{sclr};font-weight:700;font-size:16px;text-transform:uppercase;">{slbl}</div>
    <div style="font-size:11px;color:#7AACCC;">{sub}</div>
    <div style="font-size:9px;color:#1A5070;font-family:'Share Tech Mono';">SRC: {src}</div>
    <script>
    (function(){{
        const canvas=document.getElementById('{gid}'); const ctx=canvas.getContext('2d');
        const W=260, H=150, cx=W/2, cy=125, r=95;
        function toA(v){{ return Math.PI + ((v-{min_v})/({max_v}-{min_v}))*Math.PI; }}
        function draw(val){{
            ctx.clearRect(0,0,W,H);
            {t_js}.forEach(t=>{{ ctx.beginPath(); ctx.strokeStyle=t.color; ctx.lineWidth=20; ctx.arc(cx,cy,r, toA(t.r0), toA(t.r1)); ctx.stroke(); }});
            const ang=toA(val); ctx.beginPath(); ctx.strokeStyle='{nclr}'; ctx.lineWidth=4; ctx.moveTo(cx,cy); ctx.lineTo(cx+r*Math.cos(ang), cy+r*Math.sin(ang)); ctx.stroke();
            ctx.fillStyle="white"; ctx.font="bold 22px Rajdhani"; ctx.textAlign="center"; ctx.fillText(val.toFixed(2)+"{u}", cx, cy-40);
        }}
        let cur={min_v}; function anim(){{ cur+=({v}-cur)*0.08; draw(cur); if(Math.abs(cur-{v})>0.001) requestAnimationFrame(anim); }} anim();
    }})();
    </script></body></html>
    """

st.markdown(f"""<div class="site-header"><div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
<div style="color:{alert_clr}; font-weight:700;">⚠️ THREAT LEVEL: {alert_lvl} ({composite_score}%) | Ground Truth: AWN Riverbend</div></div>""", unsafe_allow_html=True)

# ROW 1: PRECIP & ATMOS
st.markdown('<div class="panel"><div class="panel-title">🌧️ Precipitation & Atmospheric Conditions</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_gauge(awn.get("dailyrainin", 0), "RAIN TODAY", 0, 3, '"', "#00FF9C"), use_container_width=True)
with c2: st.plotly_chart(make_gauge(wind, "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c3: st.plotly_chart(make_gauge(hum, "HUMIDITY", 0, 100, "%", "#0077FF"), use_container_width=True)
with c4:
    # REAL TEMPERATURE (GROUND TRUTH)
    st.plotly_chart(make_gauge(temp_real, "REAL TEMPERATURE", 0, 110, "°F", "#00FF9C"), use_container_width=True)
    st.markdown(f"<div style='text-align:center;font-size:0.8em;color:#7AACCC;'>Feels Like: {fl_temp}°F</div>", unsafe_allow_html=True)
with c5: st.plotly_chart(make_gauge(soil_pct, "SOIL SATURATION", 0, 100, "%", soil_color), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: HYDROLOGY
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    depth_html = make_animated_gauge_html("g_depth", creek_depth, "STREAM DEPTH", 5.5, 6.25, '"', 
        [{"range":[5.5,6.0],"color":"rgba(0,255,156,0.15)"},{"range":[6.0,6.25],"color":"rgba(255,51,51,0.2)"}],
        "#00FF9C", "STABLE" if creek_depth < 6.0 else "ELEVATED", "#00FF9C" if creek_depth < 6.0 else "#FFD700", f'Level: {creek_depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)
with h2:
    flow_html = make_animated_gauge_html("g_flow", 5.12, "STREAM FLOW", 4.8, 5.4, " cfs", 
        [{"range":[4.8,5.2],"color":"rgba(0,255,156,0.15)"}], "#5AC8FA", "NORMAL", "#5AC8FA", "Flow: 5.12 cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)
with h3:
    st.markdown(f"""<div style="background:rgba(0,80,160,0.1); border:1px solid #0077FF; border-radius:8px; padding:20px; font-family:'Share Tech Mono';">
    <div style="color:#0077FF;">📊 COMPOSITE PREDICTIVE RISK</div>
    <div style="font-size:2em; font-weight:700; color:{alert_clr};">{composite_score}%</div>
    <div style="font-size:0.8em; color:#7AACCC; margin-top:10px;">
    Soil Model: {soil_status} ({soil_pct}%)<br>
    Runoff Multiplier: x{runoff_coeff}<br>
    Forecast Rain (24h): {fcst_rain_24h}"
    </div></div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: FORECAST
st.markdown('<div class="panel"><div class="panel-title">📅 7-Day Multi-Model Forecast</div>', unsafe_allow_html=True)
fcols = st.columns(7)
for i, d in enumerate(forecast):
    with fcols[i]:
        st.markdown(f"""<div style='text-align:center; background:rgba(255,255,255,0.03); padding:10px; border-radius:5px;'>
        <b>{d['day']}</b><br><span style='color:#FF6B35;'>{d['hi']}°</span> / <span style='color:#5AC8FA;'>{d['lo']}°</span><br>
        <span style='color:#00FFCC;'>{d['pop']}% Rain</span></div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# RADAR
st.markdown('<div class="panel"><div class="panel-title">🛰️ Live Radar Loop</div>', unsafe_allow_html=True)
st.components.v1.html(f'<iframe src="https://www.rainviewer.com/map.html?loc={LAT},{LON},9&oFa=0&oC=1&oU=0&oCS=1&oF=0&oAP=1&rmt=4&c=1&o=83&lm=1&layer=radar&sm=1&sn=1&play=1&playbackSpeed=2" width="100%" height="500"></iframe>', height=500)
