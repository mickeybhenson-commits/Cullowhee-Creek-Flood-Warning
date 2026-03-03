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
LAT, LON = 35.3079, -83.1746
SITE = "Cullowhee Creek — Cullowhee, NC"
BASE_FLOW_IN = 6.0  # NCCAT primary baseline [cite: 2025-10-29]

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
#  HYDROLOGIC LOGIC (The "Dial-In" Engine)
# ─────────────────────────────────────────────

def estimate_creek_flow(current_depth_in):
    """ Power-law rating curve calibrated for Cullowhee Creek """
    stage_ft = max(0, (current_depth_in - BASE_FLOW_IN) / 12.0)
    c_multiplier = 30.0 
    calc_flow = c_multiplier * (stage_ft ** 1.5)
    return round(calc_flow + 5, 1)

def make_gauge(value, title, min_val=0, max_val=100, unit="%", color="#0088FF", steps=None):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": unit, "font": {"size": 26, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={"axis": {"range": [min_val, max_val], "tickfont": {"size": 8}}, "bar": {"color": color, "thickness": 0.25}, "bgcolor": "rgba(0,0,0,0)", "steps": steps if steps else []}
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=35, b=5, l=15, r=15), height=185)
    return fig

# ─────────────────────────────────────────────
#  STORM SENSING & ALERTING [cite: 2026-01-31]
# ─────────────────────────────────────────────

# INPUTS (Ready for Lab Calibration)
creek_depth_raw = 6.0  # Starting at Baseflow
creek_flow_cfs = estimate_creek_flow(creek_depth_raw)

# CRISIS TRIGGER: TRIGGERED BY UPPER LEVELS
if creek_depth_raw > 60:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,51,51,0.2); border-color:#FF3333; color:#FF3333;">⚠️ CRITICAL: CREEK DEPTH EXCEEDS UPPER THRESHOLD ({creek_depth_raw}")</div>', unsafe_allow_html=True)
elif creek_depth_raw == 60:
    st.markdown(f'<div class="crisis-banner" style="background:rgba(255,255,0,0.2); border-color:#FFFF00; color:#FFFF00;">📢 WARNING: CREEK AT CRITICAL LEVEL (60")</div>', unsafe_allow_html=True)

st.markdown(f'<div class="site-header"><div class="site-title">NOAH | CULLOWHEE HYDROMETRIC SENTINEL</div><div style="color:#7AACCC; font-family:\'Share Tech Mono\';">{SITE} | {datetime.now().strftime("%I:%M %p")}</div></div>', unsafe_allow_html=True)

# ROW 1: PRIMARY HYDROMETRICS
st.markdown('<div class="panel"><div class="panel-title">🌊 Primary Hydrologic State</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns([1,1,1]) # Wider gauges for clarity

with c1:
    depth_color = "#FF3333" if creek_depth_raw > 60 else "#FFFF00" if creek_depth_raw == 60 else "#0088FF"
    depth_steps = [{'range': [0, 60], 'color': "rgba(0, 136, 255, 0.1)"}, {'range': [60, 100], 'color': "rgba(255, 51, 51, 0.3)"}]
    st.plotly_chart(make_gauge(creek_depth_raw, "CREEK DEPTH", 0, 100, "\"", depth_color, steps=depth_steps), use_container_width=True)

with c2: st.plotly_chart(make_gauge(creek_flow_cfs, "EST. CREEK FLOW", 0, 1000, " CFS", ("#FF3333" if creek_depth_raw > 60 else "#00FF9C")), use_container_width=True)
with c3: st.metric("Watershed Status", "STABLE" if creek_depth_raw < 60 else "ACTIVE SURGE", delta="Baseflow" if creek_depth_raw == 6.0 else "Rising")

st.markdown('</div>', unsafe_allow_html=True)

# FULL-SCALE NWS RADAR FOOTPRINT
st.markdown('<div class="panel"><div class="panel-title">📡 Official NWS Radar Loop — Mission Command Footprint</div>', unsafe_allow_html=True)
st.components.v1.html(
    '<iframe src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif" '
    'width="100%" height="1800" frameborder="0" style="border-radius:10px;"></iframe>', 
    height=1810
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div style="text-align:center; font-family:\'Share Tech Mono\'; font-size:0.75em; color:#2A4060; margin-top:20px;">PROJECT NOAH | {SITE} | Baseline Calibration Active</div>', unsafe_allow_html=True)
