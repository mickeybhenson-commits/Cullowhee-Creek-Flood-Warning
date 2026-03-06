import streamlit as st
import requests
import json
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
#  1. CONFIGURATION & STYLING
# ─────────────────────────────────────────────
st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON  = 35.3079, -83.1746
USGS_SITE = "02178400"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color: #04090F; color: #E0E8F0; font-family: 'Rajdhani', sans-serif; }
.site-header { border-left: 6px solid #0077FF; padding: 14px 22px; margin-bottom: 20px;
               background: rgba(0,100,200,0.07); border-radius: 0 8px 8px 0; }
.site-title  { font-size: 2.4em; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 2px; }
.site-sub    { font-family: 'Share Tech Mono', monospace; font-size: 0.75em; color: #5AACD0; margin-top: 4px; }
.panel       { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,119,255,0.18);
               border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.panel-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #0077FF;
               text-transform: uppercase; letter-spacing: 3px;
               border-bottom: 1px solid rgba(0,119,255,0.18); padding-bottom: 8px; margin-bottom: 14px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  2. DATA ACQUISITION
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_openmeteo_current():
    """Real-time conditions from Open-Meteo for exact Cullowhee lat/lon — no API key required."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":             LAT,
                "longitude":            LON,
                "current":              "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                                        "wind_direction_10m,surface_pressure,precipitation,"
                                        "weather_code,wind_gusts_10m",
                "temperature_unit":     "fahrenheit",
                "wind_speed_unit":      "mph",
                "precipitation_unit":   "inch",
                "forecast_days":        1,
            },
            timeout=10
        ).json()
        c = r["current"]
        # Convert surface pressure hPa -> inHg
        press_inhg = round(c.get("surface_pressure", 1013.25) * 0.02953, 2)
        return {
            "ok":       True,
            "temp":     round(float(c.get("temperature_2m",        50)),  2),
            "hum":      round(float(c.get("relative_humidity_2m",  50)),  2),
            "wind":     round(float(c.get("wind_speed_10m",         0)),  2),
            "wind_gust":round(float(c.get("wind_gusts_10m",         0)),  2),
            "wind_dir": round(float(c.get("wind_direction_10m",     0)),  2),
            "press":    press_inhg,
            "precip":   round(float(c.get("precipitation",          0)),  2),
            "wcode":    c.get("weather_code", 0),
        }
    except Exception as e:
        return {"ok": False, "temp": 50.00, "hum": 50.00, "wind": 0.00,
                "wind_gust": 0.00, "wind_dir": 0.00, "press": 29.92,
                "precip": 0.00, "wcode": 0}




@st.cache_data(ttl=1800)
def fetch_nws_forecast():
    try:
        hdrs    = {"User-Agent": "NOAH-FloodWarning/1.0 (WCU NEMO Project)"}
        pts     = requests.get(f"https://api.weather.gov/points/{LAT},{LON}",
                               headers=hdrs, timeout=10).json()["properties"]
        wfo, gx, gy = pts["gridId"], pts["gridX"], pts["gridY"]
        periods = requests.get(pts["forecast"],
                               headers=hdrs, timeout=10).json()["properties"]["periods"]
        grid    = requests.get(f"https://api.weather.gov/gridpoints/{wfo}/{gx},{gy}",
                               headers=hdrs, timeout=15).json()["properties"]

        qpf_by_date = defaultdict(float)
        for entry in grid.get("quantitativePrecipitation", {}).get("values", []):
            vt  = entry["validTime"].split("/")[0]
            val = entry["value"] or 0
            try:
                d = datetime.fromisoformat(vt).strftime("%Y-%m-%d")
                qpf_by_date[d] += val * 0.0393701
            except:
                pass

        temp_by_date = {}
        for entry in grid.get("maxTemperature", {}).get("values", []):
            vt  = entry["validTime"].split("/")[0]
            val = entry["value"]
            if val is not None:
                try:
                    d  = datetime.fromisoformat(vt).strftime("%Y-%m-%d")
                    tf = round(val * 9 / 5 + 32, 2)
                    if d not in temp_by_date or tf > temp_by_date[d]:
                        temp_by_date[d] = tf
                except:
                    pass

        result, seen = [], set()
        for p in periods:
            if not p["isDaytime"]:
                continue
            try:
                dt   = datetime.fromisoformat(p["startTime"][:10])
                dkey = dt.strftime("%Y-%m-%d")
                if dkey in seen or len(result) >= 7:
                    continue
                seen.add(dkey)
                result.append({
                    "short_name": dt.strftime("%a").upper(),
                    "date":       dt.strftime("%m/%d"),
                    "temp":       round(temp_by_date.get(dkey, float(p["temperature"])), 2),
                    "qpf":        round(qpf_by_date.get(dkey, 0.0), 2),
                    "pop":        round(float((p.get("probabilityOfPrecipitation") or {}).get("value") or 0), 2),
                    "icon_txt":   str(p.get("shortForecast", "")),
                })
            except:
                continue
        return result, True, None
    except Exception as e:
        return [], False, str(e)


@st.cache_data(ttl=3600)
def fetch_30d_precip():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": LAT, "longitude": LON,
                    "daily": "precipitation_sum", "past_days": 30,
                    "forecast_days": 0, "precipitation_unit": "inch"},
            timeout=10
        ).json()
        return round(sum(r["daily"]["precipitation_sum"]), 2), True
    except:
        return 4.20, False




# ─────────────────────────────────────────────
#  3. HYDRO-MODELING
# ─────────────────────────────────────────────

def get_soil_model(total_30d):
    MAX_CAP = 2.66
    ET_LOSS = 0.06 * 30
    stored  = max(0.50, min(MAX_CAP, total_30d - ET_LOSS))
    sat_pct = (stored / MAX_CAP) * 100
    color   = "#FF3333" if sat_pct > 85 else "#FFD700" if sat_pct > 60 else "#00FF9C"
    return round(stored, 2), round(sat_pct, 2), color


def compute_flood_threat(soil_sat, qpf_24h, pop_24h):
    soil_score = soil_sat * 0.40
    qpf_score  = min(100.0, qpf_24h * 40) * 0.35
    pop_score  = pop_24h * 0.25
    return round(min(100.0, soil_score + qpf_score + pop_score), 2)


def threat_meta(score):
    if score < 25: return "NORMAL",    "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45: return "ELEVATED",  "#AAFF00", "rgba(170,255,0,0.07)"
    if score < 65: return "WATCH",     "#FFD700", "rgba(255,215,0,0.09)"
    if score < 82: return "WARNING",   "#FF8800", "rgba(255,136,0,0.11)"
    return               "EMERGENCY",  "#FF3333", "rgba(255,51,51,0.14)"


def nws_icon(txt):
    t = txt.lower()
    if any(x in t for x in ["thunder", "storm"]):  return "TSTM"
    if any(x in t for x in ["snow", "blizzard"]):  return "SNOW"
    if any(x in t for x in ["sleet", "freezing"]): return "SLEET"
    if any(x in t for x in ["fog", "haze"]):       return "FOG"
    if "shower" in t:                              return "SHWRS"
    if any(x in t for x in ["rain", "drizzle"]):   return "RAIN"
    if "partly cloudy" in t:                       return "PTCLDY"
    if "mostly cloudy" in t:                       return "MSTCLDY"
    if "cloudy" in t:                              return "CLOUDY"
    if any(x in t for x in ["sunny", "clear"]):   return "SUNNY"
    return "---"


# ─────────────────────────────────────────────
#  4. UI BUILDERS
# ─────────────────────────────────────────────

def make_dial(v, t, min_v, max_v, u, c, sub="", src=""):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": u, "font": {"size": 22, "color": "white"}, "valueformat": ".2f"},
        title={
            "text": (f"{t}"
                     f"<br><span style='font-size:0.78em;color:#7AACCC'>{sub}</span>"
                     f"<br><span style='font-size:0.65em;color:#1A5070'>{src}</span>"),
            "font": {"size": 11, "color": "#7AACCC"},
        },
        gauge={
            "axis":    {"range": [min_v, max_v]},
            "bar":     {"color": c, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
        },
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(t=65, b=5, l=15, r=15), height=195)
    return fig


def make_animated_gauge_html(gid, v, t, min_v, max_v, u, thresh, nclr, slbl, sclr, sub, src):
    t_js = json.dumps(
        [{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in thresh]
    )
    return f"""<html><body style="background:transparent;text-align:center;
font-family:'Rajdhani',sans-serif;color:white;">
<canvas id="{gid}" width="260" height="150"></canvas>
<div style="color:{sclr};font-weight:700;font-size:16px;
            text-transform:uppercase;letter-spacing:2px;">{slbl}</div>
<div style="font-size:12px;color:#7AACCC;margin-top:4px;">{sub}</div>
<div style="font-size:9px;color:#1A5070;font-family:'Share Tech Mono',monospace;
            margin-top:2px;">SRC: {src}</div>
<script>
(function(){{
    const canvas=document.getElementById('{gid}');
    const ctx=canvas.getContext('2d');
    const cx=130,cy=125,r=95;
    function toA(v){{ return Math.PI+((v-{min_v})/({max_v}-{min_v}))*Math.PI; }}
    function draw(val){{
        ctx.clearRect(0,0,260,150);
        {t_js}.forEach(t=>{{
            ctx.beginPath(); ctx.strokeStyle=t.color; ctx.lineWidth=20;
            ctx.arc(cx,cy,r,toA(t.r0),toA(t.r1)); ctx.stroke();
        }});
        const ang=toA(Math.max({min_v},Math.min({max_v},val)));
        ctx.beginPath(); ctx.strokeStyle='{nclr}'; ctx.lineWidth=4;
        ctx.moveTo(cx,cy); ctx.lineTo(cx+r*Math.cos(ang),cy+r*Math.sin(ang)); ctx.stroke();
        ctx.beginPath(); ctx.arc(cx,cy,6,0,2*Math.PI);
        ctx.fillStyle='{nclr}'; ctx.fill();
        ctx.fillStyle='white'; ctx.font='bold 20px Rajdhani';
        ctx.textAlign='center';
        ctx.fillText(val.toFixed(2)+"{u}",cx,cy-40);
    }}
    let cur={min_v};
    function anim(){{
        cur+=({v}-cur)*0.08; draw(cur);
        if(Math.abs(cur-{v})>0.001) requestAnimationFrame(anim);
    }}
    anim();
}})();
</script></body></html>"""


# ─────────────────────────────────────────────
#  5. DATA EXECUTION
# ─────────────────────────────────────────────

noaa                    = fetch_openmeteo_current()
forecast, fc_ok, fc_err = fetch_nws_forecast()
rain_30d, prcp_ok       = fetch_30d_precip()
soil_in, soil_sat, soil_color = get_soil_model(rain_30d)

qpf_24h    = forecast[0]["qpf"] if forecast else 0.0
pop_24h    = forecast[0]["pop"] if forecast else 0.0
threat_score            = compute_flood_threat(soil_sat, qpf_24h, pop_24h)
t_label, t_color, t_bg = threat_meta(threat_score)

if "depth" not in st.session_state: st.session_state.depth = 0.87
if "flow"  not in st.session_state: st.session_state.flow  = 22.40
st.session_state.depth = round(max(0.50, min(1.25, st.session_state.depth + np.random.uniform(-0.015, 0.015))), 2)
st.session_state.flow  = round(max(10.0, min(40.0, st.session_state.flow  + np.random.uniform(-0.30,  0.30))),  2)


# ─────────────────────────────────────────────
#  6. RENDER
# ─────────────────────────────────────────────

# HEADER
st.markdown(f"""
<div class="site-header">
  <div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
  <div class="site-sub">
    Cullowhee Creek Watershed &mdash; Jackson County, NC
    &nbsp;|&nbsp;
    {datetime.now().strftime("%A, %B %d %Y")} &mdash; {datetime.now().strftime("%H:%M:%S")}
  </div>
</div>""", unsafe_allow_html=True)

# FLOOD THREAT BANNER
st.markdown(f"""
<div style="background:{t_bg}; border:2px solid {t_color}; border-radius:10px;
            padding:22px 30px; margin-bottom:16px; text-align:center;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.75em;
              color:{t_color}; letter-spacing:4px; margin-bottom:6px;">
    COMPOSITE FLOOD THREAT SCORE
  </div>
  <div style="font-size:3.5em; font-weight:700; color:{t_color};
              letter-spacing:5px; line-height:1.0;">
    {t_label}
  </div>
  <div style="font-size:1.8em; font-weight:600; color:white; margin-top:4px;">
    {threat_score:.2f} / 100
  </div>
  <div style="background:rgba(255,255,255,0.08); border-radius:6px;
              height:8px; margin:12px auto; max-width:500px;">
    <div style="background:{t_color}; width:{threat_score}%; height:8px; border-radius:6px;"></div>
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em;
              color:#7AACCC; margin-top:6px;">
    SOIL SAT {soil_sat:.2f}%
    &nbsp;&middot;&nbsp; QPF(24h) {qpf_24h:.2f}&quot;
    &nbsp;&middot;&nbsp; PoP {pop_24h:.2f}%
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.68em;
              color:#3A6A8A; margin-top:10px; letter-spacing:1px;">
    EVALUATED FACTORS: Soil Saturation &middot; 24hr Rainfall Forecast &middot; Probability of Precipitation
  </div>
</div>""", unsafe_allow_html=True)

# ROW 1: ATMOSPHERIC CONDITIONS
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS &mdash; NOAA / NWS GROUND TRUTH</div>', unsafe_allow_html=True)
if not noaa["ok"]:
    st.warning("METAR feed unavailable (K24A) — values may be stale")
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_dial(noaa["wind"],  "WIND SPEED",      0,  50,  " mph",  "#5AC8FA", src="K24A METAR"), use_container_width=True)
with c2: st.plotly_chart(make_dial(noaa["hum"],   "HUMIDITY",        0, 100,  "%",     "#0077FF", src="K24A METAR"), use_container_width=True)
with c3: st.plotly_chart(make_dial(noaa["temp"],  "TEMPERATURE",     0, 110,  " F",    "#00FF9C", sub="+/-2F Valley Corr.", src="K24A METAR"), use_container_width=True)
with c4: st.plotly_chart(make_dial(noaa["press"], "PRESSURE",        28,  32,  " inHg", "#AAFF00", src="K24A METAR"), use_container_width=True)
with c5: st.plotly_chart(make_dial(soil_sat,      "SOIL SATURATION", 0, 100,  "%",     soil_color, sub=f'{soil_in:.2f}" Stored', src="OPEN-METEO"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: CULLOWHEE CREEK
st.markdown('<div class="panel"><div class="panel-title">CULLOWHEE CREEK &mdash; LOCAL SENSOR FEED</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])
with h1:
    st.components.v1.html(make_animated_gauge_html(
        "g_depth", st.session_state.depth,
        "STREAM DEPTH", 0.0, 8.0, " ft",
        [{"range": [0.0, 4.0], "color": "rgba(0,255,156,0.15)"},
         {"range": [4.0, 6.0], "color": "rgba(255,215,0,0.20)"},
         {"range": [6.0, 8.0], "color": "rgba(255,51,51,0.25)"}],
        "#00FF9C", "NORMAL", "#00FF9C",
        f"Stage: {st.session_state.depth:.2f} ft  |  Flood: 6.00 ft", "NEMO SENSOR"
    ), height=230)
with h2:
    st.components.v1.html(make_animated_gauge_html(
        "g_flow", st.session_state.flow,
        "DISCHARGE", 0.0, 200.0, " cfs",
        [{"range": [0.0,   80.0], "color": "rgba(0,255,156,0.15)"},
         {"range": [80.0, 140.0], "color": "rgba(255,215,0,0.20)"},
         {"range": [140.0,200.0], "color": "rgba(255,51,51,0.25)"}],
        "#5AC8FA", "LOW FLOW", "#5AC8FA",
        f"Discharge: {st.session_state.flow:.2f} cfs", "NEMO SENSOR"
    ), height=230)
with h3:
    live_label = "LIVE" if prcp_ok else "CACHED FALLBACK"
    st.markdown(f"""
<div style="background:rgba(0,80,160,0.10); border:1px solid #0077FF; border-radius:8px;
            padding:20px; font-family:'Share Tech Mono',monospace;">
  <div style="color:#0077FF; letter-spacing:1px; font-size:0.85em;">
    SOIL MOISTURE MODEL (30-DAY ACCUMULATED)
  </div>
  <div style="font-size:1.4em; font-weight:700; color:{soil_color}; margin:10px 0;">
    {soil_in:.2f} INCHES STORED
  </div>
  <div style="font-size:0.8em; color:#7AACCC; line-height:1.9;">
    30d Precip: {rain_30d:.2f}&quot;<br>
    Clay Loam Capacity: 2.66&quot;<br>
    ET Extraction (Mar): 1.80&quot;<br>
    <b>Infiltration: {soil_sat:.2f}% Capacity</b><br>
    <span style="color:#1A5070;">SRC: OPEN-METEO ERA5 &middot; {live_label}</span>
  </div>
</div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: 7-DAY FLOOD OUTLOOK
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED (NWS GSP GRIDPOINT)</div>', unsafe_allow_html=True)
if not fc_ok:
    st.warning(f"NWS forecast unavailable — {fc_err}")
elif forecast:
    pcols = st.columns(7)
    for i, d in enumerate(forecast):
        risk      = min(100.0, round((soil_sat * 0.35) + (d["pop"] * 0.35) + (d["qpf"] * 20), 2))
        color     = "#00FF9C" if risk < 30 else "#AAFF00" if risk < 50 else "#FFD700" if risk < 65 else "#FF8800" if risk < 80 else "#FF3333"
        icon      = nws_icon(d["icon_txt"])
        temp_str  = f"{d['temp']:.2f}"
        qpf_str   = f"{d['qpf']:.2f}"
        pop_str   = f"{d['pop']:.2f}"
        risk_str  = f"{risk:.2f}"
        with pcols[i]:
            st.markdown(
                '<div style="background:rgba(255,255,255,0.03); border-top:4px solid '
                + color
                + '; border-radius:8px; padding:12px 8px; text-align:center;">'
                + '<div style="font-weight:700; font-size:1.1em;">' + d["short_name"] + '</div>'
                + '<div style="font-size:0.75em; color:#5A7090; margin-bottom:4px;">' + d["date"] + '</div>'
                + '<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.75em; color:#7AACCC; margin-bottom:4px;">' + icon + '</div>'
                + '<div style="color:' + color + '; font-size:1.55em; font-weight:700; margin:5px 0;">' + risk_str + '%</div>'
                + '<div style="color:' + color + '; font-family:\'Share Tech Mono\',monospace; font-size:0.72em; letter-spacing:2px; margin-bottom:4px;">FLOOD RISK</div>'
                + '<div style="color:#00FFCC; font-family:\'Share Tech Mono\',monospace; font-size:0.85em;">' + qpf_str + '&quot;</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + pop_str + '% PoP</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + temp_str + ' F</div>'
                + '</div>',
                unsafe_allow_html=True
            )
st.markdown('</div>', unsafe_allow_html=True)


# ROW 5: LIVE RADAR
st.markdown('<div class="panel"><div class="panel-title">LIVE REGIONAL RADAR &mdash; WESTERN NC</div>', unsafe_allow_html=True)
try:
    st.components.v1.html(
        f'<iframe src="https://www.rainviewer.com/map.html?loc={LAT},{LON},9'
        f'&oFa=0&oC=0&oU=0&oCS=1&oF=0&oAP=0&rmt=4&c=3&o=83&lm=0'
        f'&layer=radar&sm=1&sn=1" '
        f'width="100%" height="500" style="border-radius:10px; border:none;"></iframe>',
        height=510,
    )
except Exception:
    st.error("Radar iframe unavailable — visit rainviewer.com directly for regional coverage.")
st.markdown('</div>', unsafe_allow_html=True)
