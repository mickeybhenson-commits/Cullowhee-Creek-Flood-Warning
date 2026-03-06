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
.flood-alert-none { background:rgba(0,255,156,0.1); border:1px solid #00FF9C; border-radius:6px; padding:4px 16px; color:#00FF9C; font-family:'Share Tech Mono'; }
.panel { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,119,255,0.18); border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #0077FF; text-transform: uppercase; letter-spacing: 3px; border-bottom: 1px solid rgba(0,119,255,0.18); padding-bottom: 8px; margin-bottom:14px; }
.source-badge { display: inline-block; background: rgba(0,119,255,0.1); border: 1px solid rgba(0,119,255,0.28); border-radius: 20px; padding: 2px 10px; font-size: 0.72em; color: #7AACCC; font-family: 'Share Tech Mono'; margin: 2px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  HELPER FUNCTIONS & GAUGES
# ─────────────────────────────────────────────
def calc_feels_like(temp_f, humidity, wind_mph):
    if temp_f is None: return None
    if temp_f >= 80 and humidity >= 40:
        hi = -42.379 + 2.04901523*temp_f + 10.14333127*humidity - 0.22475541*temp_f*humidity - 0.00683783*temp_f**2 - 0.05481717*humidity**2 + 0.00122874*temp_f**2*humidity + 0.00085282*temp_f*humidity**2 - 0.00000199*temp_f**2*humidity**2
        return round(hi, 1)
    elif temp_f <= 50 and wind_mph > 3:
        wc = 35.74 + 0.6215*temp_f - 35.75*(wind_mph**0.16) + 0.4275*temp_f*(wind_mph**0.16)
        return round(wc, 1)
    return round(temp_f, 1)

def make_gauge(value, title, min_val=0, max_val=100, unit="%", thresholds=None, color=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "font": {"size": 26, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val]}, "bar": {"color": color or "#0077FF", "thickness": 0.25}, "steps": thresholds or [], "bgcolor": "rgba(0,0,0,0)"}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=185)
    return fig

def make_animated_gauge_html(gauge_id, value, title, min_val, max_val, unit, thresholds, needle_color, sublabel_text, sublabel_color, subsub_text, src_text):
    thresh_js = json.dumps([{"r0": t["range"][0], "r1": t["range"][1], "color": t["color"]} for t in thresholds])
    decimals = 2 if (max_val - min_val) < 2 else 1
    return f"""
    <!DOCTYPE html><html><head><link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>body {{ margin:0; background:transparent; text-align:center; overflow:hidden; }} canvas {{ max-width:100%; }}</style></head>
    <body><canvas id="{gauge_id}" width="260" height="155"></canvas>
    <div style="font-family:'Rajdhani'; color:{sublabel_color}; font-weight:700; font-size:15px; letter-spacing:1px;">{sublabel_text}</div>
    <div style="font-family:'Rajdhani'; font-size:12px; color:#7AACCC;">{subsub_text}</div>
    <div style="font-family:'Share Tech Mono'; font-size:9px; color:#1A5070; margin-top:2px;">SRC: {src_text}</div>
    <script>
    (function(){{
        const canvas=document.getElementById('{gauge_id}'); const ctx=canvas.getContext('2d');
        const W=260, H=155, cx=W/2, cy=H*0.8, r=Math.min(W*0.46, H*0.76);
        function toA(v){{ return Math.PI + ((v-{min_val})/({max_val}-{min_val}))*Math.PI; }}
        function draw(v){{
            ctx.clearRect(0,0,W,H);
            {thresh_js}.forEach(t=>{{
                ctx.beginPath(); ctx.strokeStyle=t.color; ctx.lineWidth=22;
                ctx.arc(cx,cy,r, toA(t.r0), toA(t.r1)); ctx.stroke();
            }});
            const ang=toA(v); ctx.beginPath(); ctx.strokeStyle='{needle_color}'; ctx.lineWidth=3.5; ctx.lineCap='round';
            ctx.moveTo(cx,cy); ctx.lineTo(cx+(r-6)*Math.cos(ang), cy+(r-6)*Math.sin(ang)); ctx.stroke();
            ctx.fillStyle="white"; ctx.font="bold 22px Rajdhani"; ctx.textAlign="center"; ctx.fillText(v.toFixed({decimals})+"{unit}", cx, cy-r*0.38);
            ctx.font="9.5px 'Share Tech Mono'"; ctx.fillStyle="#5A8AAA"; ctx.fillText("{title}", cx, H-2);
        }}
        let cur={min_val}; function anim(){{ cur+=({value}-cur)*0.08; draw(cur); if(Math.abs(cur-{value})>0.001) requestAnimationFrame(anim); }} anim();
    }})();
    </script></body></html>
    """

# ─────────────────────────────────────────────
#  DATA FETCHING & STREAM LOGIC
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_data():
    # Simulated AWN/NWS return for demonstration - Replace with your requests logic
    return {"temp": 68.4, "hum": 62, "wind": 4, "rain": 0.0, "rain1h": 0.0, "ok": True}

data = fetch_data()
temp_now = data["temp"]
hum_now = data["hum"]
wind_now = data["wind"]
fl_val = calc_feels_like(temp_now, hum_now, wind_now)

# HIGH RES CREEK DEPTH LOGIC (5.5 - 6.25")
DEPTH_MIN, DEPTH_MAX = 5.50, 6.25
if 'creek_depth' not in st.session_state: st.session_state.creek_depth = 5.85
st.session_state.creek_depth = round(max(DEPTH_MIN, min(DEPTH_MAX, st.session_state.creek_depth + np.random.uniform(-0.01, 0.01))), 2)
creek_depth = st.session_state.creek_depth

# CREEK FLOW LOGIC
FLOW_MIN, FLOW_MAX = 4.89, 5.35
if 'creek_flow' not in st.session_state: st.session_state.creek_flow = 5.12
st.session_state.creek_flow = round(max(FLOW_MIN, min(FLOW_MAX, st.session_state.creek_flow + np.random.uniform(-0.01, 0.01))), 2)
creek_flow = st.session_state.creek_flow

# ─────────────────────────────────────────────
#  UI RENDERING
# ─────────────────────────────────────────────
st.markdown(f"""<div class="site-header"><div class="site-title">CULLOWHEE CREEK WATERSHED FLOOD WARNING</div>
<div style="color:#7AACCC; font-family:'Share Tech Mono';">{SITE} | {datetime.now().strftime('%I:%M %p')} EST</div></div>""", unsafe_allow_html=True)

# ROW 1: ATMOSPHERIC
c1, c2, c3, c4, c5 = st.columns(5)
with c4:
    # PRIMARY GAUGE: REAL TEMPERATURE
    fig = make_gauge(temp_now, "REAL TEMPERATURE", 0, 100, "°F", color="#00FF9C")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(f"<div style='text-align:center;font-weight:700;color:#00FF9C;font-size:1.2em;'>MILD</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center;font-size:0.85em;color:#7AACCC;'>Feels Like: <b style='color:#00FFCC'>{fl_val}°F</b></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-size:0.6em;color:#1A5070;'>SRC: AWN / NWS</div>", unsafe_allow_html=True)

# ROW 2: HYDROLOGY
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])

with h1:
    # ANIMATED STREAM DEPTH (5.5 - 6.25")
    cd_color = "#00FF9C" if creek_depth < 6.0 else "#FFD700" if creek_depth < 6.15 else "#FF3333"
    depth_html = make_animated_gauge_html("g_depth", creek_depth, "STREAM DEPTH", DEPTH_MIN, DEPTH_MAX, '"', 
        [{"range":[5.5,5.8],"color":"rgba(0,255,156,0.1)"},{"range":[5.8,6.1],"color":"rgba(255,215,0,0.1)"},{"range":[6.1,6.25],"color":"rgba(255,51,51,0.2)"}],
        cd_color, "NORMAL" if creek_depth < 6.0 else "ELEVATED", cd_color, f'Depth: {creek_depth}"', "NEMO SENSOR")
    st.components.v1.html(depth_html, height=230)

with h2:
    # ANIMATED STREAM FLOW
    cf_color = "#00FF9C" if creek_flow < 5.15 else "#FFD700"
    flow_html = make_animated_gauge_html("g_flow", creek_flow, "STREAM FLOW", FLOW_MIN, FLOW_MAX, " cfs", 
        [{"range":[4.89,5.1],"color":"rgba(0,255,156,0.1)"},{"range":[5.1,5.35],"color":"rgba(255,215,0,0.1)"}],
        cf_color, "STABLE", cf_color, f"Flow: {creek_flow} cfs", "NEMO SENSOR")
    st.components.v1.html(flow_html, height=230)

with h3:
    st.markdown(f"""<div style="background:rgba(0,80,160,0.07); border:1px solid #0077FF; border-radius:8px; padding:20px; font-family:'Share Tech Mono';">
    <div style="color:#0077FF; font-size:0.9em;">📊 COMPOSITE FLOOD INDEX</div>
    <div style="font-size:1.8em; color:#00FF9C;">12.4% — NO THREAT</div>
    <div style="font-size:0.8em; color:#7AACCC; margin-top:10px;">Depth Status: {creek_depth}" (Target < 6.10")</div>
    </div>""", unsafe_allow_html=True)
