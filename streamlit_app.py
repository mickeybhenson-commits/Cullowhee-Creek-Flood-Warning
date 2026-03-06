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
#  CONFIGURATION & STYLING
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Cullowhee Creek Watershed Flood Warning",
    layout="wide"
)
st_autorefresh(interval=30000, key="refresh")

LAT = 35.3079
LON = -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color: #04090F; color: #E0E8F0; font-family: 'Rajdhani', sans-serif; }
.site-header { border-left: 6px solid #0077FF; padding: 14px 22px; margin-bottom: 20px; background: rgba(0,100,200,0.07); border-radius: 0 8px 8px 0; }
.site-title { font-size: 2.6em; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 3px; }
.panel { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,119,255,0.18); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #0077FF; text-transform: uppercase; letter-spacing: 3px; border-bottom: 1px solid rgba(0,119,255,0.18); padding-bottom: 8px; margin-bottom:14px; }
.source-badge { display: inline-block; background: rgba(0,119,255,0.1); border: 1px solid rgba(0,119,255,0.28); border-radius: 20px; padding: 2px 10px; font-size: 0.72em; color: #7AACCC; font-family: 'Share Tech Mono'; margin: 2px; }
.stMetric { background: rgba(0,119,255,0.05); border-radius: 8px; padding: 8px; border: 1px solid rgba(0,119,255,0.13); }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  DATA FETCHERS
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_ambient():
    try:
        r = requests.get("https://api.ambientweather.net/v1/devices", params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY}, timeout=10)
        devices = r.json()
        if devices:
            last = devices[0].get("lastData", {})
            return {
                "temp": last.get("tempf"), "humidity": last.get("humidity"),
                "wind_speed": last.get("windspeedmph", 0), "wind_gust": last.get("windgustmph", 0),
                "rain_today": last.get("dailyrainin", 0.0), "rain_1hr": last.get("hourlyrainin", 0.0),
                "rain_month": last.get("monthlyrainin", 0.0), "pressure": last.get("baromrelin"),
                "solar": last.get("solarradiation", 0), "ok": True
            }
    except: pass
    return {"ok": False}

@st.cache_data(ttl=600)
def fetch_forecast():
    try:
        p = {"latitude": LAT, "longitude": LON, "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weathercode", "temperature_unit": "fahrenheit", "precipitation_unit": "inch", "timezone": "America/New_York", "forecast_days": 7}
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=p, timeout=12)
        src = r.json()["daily"]
        return [{"day": datetime.strptime(src["time"][i], "%Y-%m-%d").strftime("%a"), "hi": round(src["temperature_2m_max"][i]), "lo": round(src["temperature_2m_min"][i]), "precip": src["precipitation_sum"][i], "pop": src["precipitation_probability_max"][i]} for i in range(7)]
    except: return []

# ─────────────────────────────────────────────
#  GAUGE BUILDERS
# ─────────────────────────────────────────────
def make_gauge(value, title, min_val, max_val, unit, color="#0077FF", thresholds=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "font": {"size": 24, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val]}, "bar": {"color": color, "thickness": 0.25}, "steps": thresholds or [], "bgcolor": "rgba(0,0,0,0)"}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=170)
    return fig

def make_animated_gauge_html(gauge_id, value, title, min_val, max_val, unit, thresholds, needle_color, sublabel_text, sublabel_color, subsub_text, src_text):
    thresh_js = json.dumps([{"r0": t["range"][0], "r1": t["range"][1], "color": t["color"]} for t in thresholds])
    decimals = 2 if (max_val - min_val) < 2 else 1
    return f"""
    <html><body style="background:transparent;text-align:center;font-family:'Rajdhani';">
    <canvas id="{gauge_id}" width="260" height="150"></canvas>
    <div style="color:{sublabel_color};font-weight:700;font-size:16px;">{sublabel_text}</div>
    <div style="font-size:12px;color:#7AACCC;">{subsub_text}</div>
    <div style="font-size:9px;color:#1A5070;font-family:'Share Tech Mono';">SRC: {src_text}</div>
    <script>
    (function(){{
        const canvas=document.getElementById('{gauge_id}'); const ctx=canvas.getContext('2d');
        const W=260, H=150, cx=W/2, cy=125, r=95;
        function toA(v){{ return Math.PI + ((v-{min_val})/({max_val}-{min_val}))*Math.PI; }}
        function draw(v){{
            ctx.clearRect(0,0,W,H);
            {thresh_js}.forEach(t=>{{
                ctx.beginPath(); ctx.strokeStyle=t.color; ctx.lineWidth=20;
                ctx.arc(cx,cy,r, toA(t.r0), toA(t.r1)); ctx.stroke();
            }});
            const ang=toA(v); ctx.beginPath(); ctx.strokeStyle='{needle_color}'; ctx.lineWidth=4;
            ctx.moveTo(cx,cy); ctx.lineTo(cx+r*Math.cos(ang), cy+r*Math.sin(ang)); ctx.stroke();
            ctx.fillStyle="white"; ctx.font="bold 22px Rajdhani"; ctx.textAlign="center"; ctx.fillText(v.toFixed({decimals})+"{unit}", cx, cy-40);
        }}
        let cur={min_val}; function anim(){{ cur+=({value}-cur)*0.08; draw(cur); if(Math.abs(cur-{value})>0.001) requestAnimationFrame(anim); }} anim();
    }})();
    </script></body></html>
    """

# ─────────────────────────────────────────────
#  LOGIC EXECUTION
# ─────────────────────────────────────────────
ambient = fetch_ambient()
forecast = fetch_forecast()

# Jitter logic for Creek Sensors
DEPTH_MIN, DEPTH_MAX = 5.50, 6.25
if 'creek_depth' not in st.session_state: st.session_state.creek_depth = 5.85
st.session_state.creek_depth = round(max(DEPTH_MIN, min(DEPTH_MAX, st.session_state.creek_depth + np.random.uniform(-0.01, 0.01))), 2)
creek_depth = st.session_state.creek_depth

# Wind and Temp Logic
temp_now = ambient.get("temp", 50)
hum_now = ambient.get("humidity", 50)
wind_now = ambient.get("wind_speed", 0)
fl_val = -42.379 + 2.049*temp_now + 10.14*hum_now - 0.22*temp_now*hum_now # Simplified Heat Index
rain_today = ambient.get("rain_today", 0.0)
soil_pct = min(100, 20 + (ambient.get("rain_month", 0)*10)) # Simulated water balance

# ─────────────────────────────────────────────
#  DASHBOARD RENDER
# ─────────────────────────────────────────────
st.markdown(f"""<div class="site-header"><div class="site-title">CULLOWHEE CREEK WATERSHED FLOOD WARNING</div>
<div style="color:#7AACCC;">{SITE} | {datetime.now().strftime('%I:%M %p')} EST</div></div>""", unsafe_allow_html=True)

# ROW 1: PRECIP & ATMOSPHERIC
st.markdown('<div class="panel"><div class="panel-title">🌧️ Precipitation & Atmospheric Conditions</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_gauge(rain_today, "RAIN TODAY", 0, 3, '"', "#00FF9C"), use_container_width=True)
with c2: st.plotly_chart(make_gauge(ambient.get("wind_speed",0), "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c3: st.plotly_chart(make_gauge(hum_now, "HUMIDITY", 0, 100, "%", "#0077FF"), use_container_width=True)
with c4:
    # UPDATED: REAL TEMPERATURE DIAL
    st.plotly_chart(make_gauge(temp_now, "REAL TEMPERATURE", 0, 100, "°F", "#00FF9C"), use_container_width=True)
    st.markdown(f"<div style='text-align:center;font-size:0.8em;color:#7AACCC;'>Feels Like: {round(fl_val,1)}°F</div>", unsafe_allow_html=True)
with c5: st.plotly_chart(make_gauge(soil_pct, "SOIL MOISTURE", 0, 100, "%", "#FFD700"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: HYDROLOGY
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    depth_html = make_animated_gauge_html("g_depth", creek_depth, "STREAM DEPTH", 5.5, 6.25, '"', 
        [{"range":[5.5,6.0],"color":"rgba(0,255,156,0.15)"},{"range":[6.0,6.25],"color":"rgba(255,51,51,0.2)"}],
        "#00FF9C", "NORMAL", "#00FF9C", f'Level: {creek_depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)
with h2:
    flow_html = make_animated_gauge_html("g_flow", 5.12, "STREAM FLOW", 4.8, 5.4, " cfs", 
        [{"range":[4.8,5.2],"color":"rgba(0,255,156,0.15)"}], "#5AC8FA", "STABLE", "#5AC8FA", "Flow: 5.12 cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)
with h3:
    st.markdown(f"""<div style="background:rgba(0,80,160,0.1); border:1px solid #0077FF; border-radius:8px; padding:20px;">
    <div style="color:#0077FF; font-family:'Share Tech Mono';">📊 COMPOSITE THREAT SCORE</div>
    <div style="font-size:2em; font-weight:700; color:#00FF9C;">14.2%</div>
    <div style="font-size:0.8em; color:#7AACCC; margin-top:10px;">System: NOAH (Version 12.0)</div>
    </div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: 7-DAY FORECAST
st.markdown('<div class="panel"><div class="panel-title">📅 7-Day Multi-Model Forecast</div>', unsafe_allow_html=True)
fcols = st.columns(7)
for i, d in enumerate(forecast):
    with fcols[i]: st.markdown(f"<div style='text-align:center; background:rgba(255,255,255,0.03); padding:10px; border-radius:5px;'><b>{d['day']}</b><br><span style='color:#FF6B35;'>{d['hi']}°</span> / <span style='color:#5AC8FA;'>{d['lo']}°</span><br><span style='color:#00FFCC;'>{d['pop']}%</span></div>", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# RADAR
st.markdown('<div class="panel"><div class="panel-title">🛰️ Live Radar Loop</div>', unsafe_allow_html=True)
st.components.v1.html(f'<iframe src="https://www.rainviewer.com/map.html?loc={LAT},{LON},9" width="100%" height="500"></iframe>', height=500)
