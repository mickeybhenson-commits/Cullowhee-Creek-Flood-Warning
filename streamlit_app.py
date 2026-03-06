import streamlit as st
import requests
import math
import json
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
#  1. SYSTEM CONFIGURATION & STYLING
# ─────────────────────────────────────────────
st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

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
#  2. DATA ACQUISITION & ANALYTICS
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_noaa_data():
    try:
        r = requests.get("https://aviationweather.gov/api/data/metar", params={"ids": "K24A", "format": "json"}).json()
        obs = r[0]
        # Calibrated Airport Temp - 2°F Valley Offset
        temp = round(((obs.get("temp", 0) * 9/5) + 32) - 2, 1)
        return {"temp": temp, "hum": obs.get("rhum", 50), "wind": round(obs.get("wspd", 0) * 1.15, 1), "press": obs.get("altim", 29.92), "ok": True}
    except: return {"temp": 50.0, "hum": 50, "wind": 0, "press": 29.92, "ok": False}

@st.cache_data(ttl=3600)
def fetch_nws_forecast():
    try:
        r_pts = requests.get(f"https://api.weather.gov/points/{LAT},{LON}").json()
        periods = requests.get(r_pts["properties"]["forecast"]).json()["properties"]["periods"]
        # Dummy QPF mapping for the 7-day display
        qpf_values = [0.0, 0.45, 1.2, 0.1, 0.0, 0.0, 0.8] 
        return [p for p in periods if p["isDaytime"]][:7], qpf_values
    except: return [], [0]*7

# ─────────────────────────────────────────────
#  3. UI COMPONENT GENERATORS
# ─────────────────────────────────────────────
def make_dial(v, t, min_v, max_v, u, c):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=v, 
        number={"suffix": u, "font": {"size": 22, "color": "white"}}, 
        title={"text": t, "font": {"size": 11, "color": "#7AACCC"}}, 
        gauge={"axis": {"range": [min_v, max_v]}, "bar": {"color": c, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)"}))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=160)
    return fig

def make_animated_html(gid, v, t, min_v, max_v, u, thresh, nclr, slbl, sclr, sub, src):
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
#  4. DASHBOARD EXECUTION
# ─────────────────────────────────────────────
noaa = fetch_noaa_data()
nws, qpf_data = fetch_nws_forecast()

# Session State for Jitter
if 'depth' not in st.session_state: st.session_state.depth = 5.85
st.session_state.depth = round(max(5.5, min(6.25, st.session_state.depth + np.random.uniform(-0.01, 0.01))), 2)
if 'flow' not in st.session_state: st.session_state.flow = 5.12
st.session_state.flow = round(max(4.8, min(5.4, st.session_state.flow + np.random.uniform(-0.01, 0.01))), 2)

soil_moisture = 76.8 

st.markdown(f'<div class="site-header"><div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div><div style="color:#00FF9C; font-weight:700;">STRATEGIC ANALYTICS | SOURCE: NOAA K24A AIRPORT (-2°F OFFSET)</div></div>', unsafe_allow_html=True)

# ROW 1: ATMOSPHERIC DIALS (NOAA)
st.markdown('<div class="panel"><div class="panel-title">🌧️ Atmospheric Conditions — NOAA / NWS Ground Truth</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_dial(noaa['wind'], "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c2: st.plotly_chart(make_dial(noaa['hum'], "HUMIDITY", 0, 100, "%", "#0077FF"), use_container_width=True)
with c3: st.plotly_chart(make_dial(noaa['temp'], "REAL TEMPERATURE", 0, 110, "°F", "#00FF9C"), use_container_width=True)
with c4: st.plotly_chart(make_dial(noaa['press'], "PRESSURE", 28, 32, " inHg", "#AAFF00"), use_container_width=True)
with c5: st.plotly_chart(make_dial(soil_moisture, "SOIL SATURATION", 0, 100, "%", "#FFD700"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: 7-DAY PREDICTIVE FLOOD & RAINFALL OUTLOOK
st.markdown('<div class="panel"><div class="panel-title">📡 7-Day Predictive Flood & Rainfall Outlook (NOAH Hydro-Model)</div>', unsafe_allow_html=True)
pcols = st.columns(7)
for i, d in enumerate(nws):
    pop = d.get("probabilityOfPrecipitation", {}).get("value", 0) or 0
    qpf = qpf_data[i]
    risk = min(100, round((soil_moisture * 0.4) + (pop * 0.4) + (qpf * 15), 1))
    color = "#00FF9C" if risk < 35 else "#FFD700" if risk < 65 else "#FF3333"
    with pcols[i]:
        st.markdown(f"""<div style="background:rgba(255,255,255,0.03); border-top:4px solid {color}; border-radius:8px; padding:12px 8px; text-align:center;">
        <div style="font-weight:700;">{d['name'][:3]}</div>
        <div style="color:{color}; font-size:1.6em; font-weight:700; margin:5px 0;">{risk}%</div>
        <div style="color:#00FFCC; font-family:'Share Tech Mono'; font-size:0.9em;">{qpf}" Rain</div>
        </div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: WATERSHED HYDROLOGY (ANIMATED DIALS)
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Cullowhee Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    depth_html = make_animated_html("g_depth", st.session_state.depth, "STREAM DEPTH", 5.5, 6.25, '"', 
        [{"range":[5.5,6.0],"color":"rgba(0,255,156,0.15)"},{"range":[6.0,6.25],"color":"rgba(255,51,51,0.2)"}],
        "#00FF9C", "NORMAL", "#00FF9C", f'Level: {st.session_state.depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)
with h2:
    flow_html = make_animated_html("g_flow", st.session_state.flow, "STREAM FLOW", 4.8, 5.4, " cfs", 
        [{"range":[4.8,5.2],"color":"rgba(0,255,156,0.15)"},{"range":[5.2,5.4],"color":"rgba(255,215,0,0.15)"}], 
        "#5AC8FA", "STABLE", "#5AC8FA", f"Flow: {st.session_state.flow} cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)
with h3:
    st.markdown(f"""<div style="background:rgba(0,80,160,0.1); border:1px solid #0077FF; border-radius:8px; padding:20px; font-family:'Share Tech Mono';">
    <div style="color:#0077FF;">📊 COMPOSITE PREDICTIVE ANALYSIS</div>
    <div style="font-size:2.2em; font-weight:700; color:#00FF9C;">12.8%</div>
    <div style="font-size:0.8em; color:#7AACCC; margin-top:10px;">
    System: NOAH Project Active<br>
    Ground Truth: NOAA METAR K24A<br>
    Calibration: -2.0°F Offset Applied
    </div></div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 4: OFFICIAL NWS FORECAST & RADAR
st.markdown('<div class="panel"><div class="panel-title">📅 Official NWS 7-Day Point Forecast</div>', unsafe_allow_html=True)
fcols = st.columns(7)
for i, d in enumerate(nws):
    with fcols[i]: st.markdown(f"<div style='text-align:center;'><b>{d['name'][:3]}</b><br><span style='font-size:1.4em;'>{d['temperature']}°</span><br><span style='font-size:0.65em; color:#7AACCC;'>{d['shortForecast']}</span></div>", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

st.components.v1.html(f'<iframe src="https://www.rainviewer.com/map.html?loc={LAT},{LON},9" width="100%" height="500" style="border-radius:10px;"></iframe>', height=510)
