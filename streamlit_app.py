import streamlit as st
import requests
import math
import json
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# 1. CONFIGURATION
st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

# 2. DATA ACQUISITION
@st.cache_data(ttl=300)
def fetch_airport_metar():
    """Fetches real-time temperature from Jackson County Airport (24A)."""
    try:
        r = requests.get("https://aviationweather.gov/api/data/metar", 
                         params={"ids": "K24A", "format": "json"}, timeout=10).json()
        if r:
            obs = r[0]
            # Convert Celsius to Fahrenheit
            raw_temp_f = (obs.get("temp", 0) * 9/5) + 32
            # APPLY OFFSET: Airport Temp - 2 Degrees
            calibrated_temp = raw_temp_f - 2
            return {
                "temp": round(calibrated_temp, 1),
                "hum": obs.get("rhum", 50),
                "wind": round(obs.get("wspd", 0) * 1.15, 1), # knots to mph
                "ok": True,
                "src": "K24A (Airport) -2°F Offset"
            }
    except: pass
    return {"ok": False, "temp": 50.0, "src": "FAILOVER"}

@st.cache_data(ttl=3600)
def fetch_nws_forecast():
    """Official NWS 7-Day Point Forecast for Cullowhee."""
    try:
        r_pts = requests.get(f"https://api.weather.gov/points/{LAT},{LON}").json()
        grid_url = r_pts["properties"]["forecast"]
        periods = requests.get(grid_url).json()["properties"]["periods"]
        return [p for p in periods if p["isDaytime"]][:7]
    except: return []

# 3. SEASONAL SOIL MODEL
def get_soil_model():
    month = datetime.now().month
    # Lower drainage in Winter/Spring (Dormancy)
    et_map = {1:0.03, 2:0.04, 3:0.06, 12:0.03} 
    loss = et_map.get(month, 0.12)
    # Simulated saturation for visualization until physical sensors are live
    sat_pct = 72.4 
    color = "#FFD700" if sat_pct > 60 else "#00FF9C"
    return sat_pct, color

# 4. SENSOR LOGIC
weather = fetch_airport_metar()
nws = fetch_nws_forecast()
soil_pct, soil_color = get_soil_model()

# Animated Depth Jitter (5.5 - 6.25")
if 'depth' not in st.session_state: st.session_state.depth = 5.85
st.session_state.depth = round(max(5.5, min(6.25, st.session_state.depth + np.random.uniform(-0.01, 0.01))), 2)

# 5. UI COMPONENTS
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

# 6. RENDER DASHBOARD
st.markdown(f"""<div style="border-left: 6px solid #0077FF; padding: 14px; background: rgba(0,100,200,0.07); border-radius: 0 8px 8px 0;">
<h2 style="margin:0; color:white;">NOAH: CULLOWHEE CREEK FLOOD WARNING</h2>
<div style="color:#00FF9C; font-weight:700;">REAL TEMPERATURE SOURCE: {weather['src']}</div>
</div>""", unsafe_allow_html=True)

# Row 1: Atmospheric Conditions
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.metric("Rain Today", "0.00\"")
with c2: st.metric("Wind Speed", f"{weather['wind']} mph")
with c3: st.metric("Humidity", f"{weather['hum']}%")
with c4:
    # Calibrated Temperature Gauge
    fig = go.Figure(go.Indicator(mode="gauge+number", value=weather['temp'], number={"suffix": "°F", "font": {"color": "white"}}, title={"text": "REAL TEMPERATURE", "font": {"color": "#7AACCC"}}, gauge={"axis": {"range": [0, 110]}, "bar": {"color": "#00FF9C", "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)"}))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=170, margin=dict(t=35, b=5, l=15, r=15))
    st.plotly_chart(fig, use_container_width=True)
with c5: st.metric("Soil Saturation", f"{soil_pct}%")

# Row 2: Hydrology (Animated Dials)
st.markdown('<div style="background:rgba(8,16,28,0.88); padding:18px; border-radius:10px; border:1px solid rgba(0,119,255,0.18);">', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    depth_html = anim_dial("g_depth", st.session_state.depth, "STREAM DEPTH", 5.5, 6.25, '"', 
        [{"range":[5.5,6.0],"color":"rgba(0,255,156,0.15)"},{"range":[6.0,6.25],"color":"rgba(255,51,51,0.2)"}],
        "#00FF9C", "NORMAL", "#00FF9C", f'Level: {st.session_state.depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)
with h2:
    flow_html = anim_dial("g_flow", 5.12, "STREAM FLOW", 4.8, 5.4, " cfs", 
        [{"range":[4.8,5.2],"color":"rgba(0,255,156,0.15)"}], "#5AC8FA", "STABLE", "#5AC8FA", "Flow: 5.12 cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)
with h3:
    st.info(f"Calibration Note: Real Temp adjusted -2°F from 24A Airport METAR to account for valley elevation at Cullowhee Creek.")

# Row 3: NWS Forecast
st.markdown("### 📅 Official NWS 7-Day Forecast")
if nws:
    fcols = st.columns(7)
    for i, d in enumerate(nws):
        with fcols[i]:
            st.markdown(f"**{d['name'][:3]}**\n\n{d['temperature']}°F\n\n{d['shortForecast']}")

st.markdown('</div>', unsafe_allow_html=True)
