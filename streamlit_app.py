import streamlit as st
import requests
import math
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="Cullowhee Creek Watershed Flood Warning",
    layout="wide"
)
st_autorefresh(interval=300000, key="refresh")

LAT = 35.3079
LON = -83.1746
SITE = "Cullowhee Creek Watershed — Jackson County, NC"

AMBIENT_API_KEY = st.secrets.get("AMBIENT_API_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")
AMBIENT_APP_KEY = st.secrets.get("AMBIENT_APP_KEY", "9ed066cb260c42adbe8778e0afb09e747f8450a7dd20479791a18d692b722334")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp {
    background-color: #04090F;
    color: #E0E8F0;
    font-family: 'Rajdhani', sans-serif;
}
h1, h2, h3 { font-family: 'Rajdhani', sans-serif; letter-spacing: 2px; }
.stApp:before {
    content: "";
    position: fixed;
    inset: 0;
    background:
        radial-gradient(ellipse at 15% 20%, rgba(0,60,140,0.18) 0%, transparent 55%),
        radial-gradient(ellipse at 85% 75%, rgba(0,100,180,0.14) 0%, transparent 55%);
    z-index: 0;
    pointer-events: none;
}
section.main > div { position: relative; z-index: 1; }
.site-header {
    border-left: 6px solid #0077FF;
    padding: 14px 22px;
    margin-bottom: 20px;
    background: rgba(0,100,200,0.07);
    border-radius: 0 8px 8px 0;
}
.site-title {
    font-size: 2.6em; font-weight: 700; color: #FFFFFF;
    margin: 0; letter-spacing: 3px;
}
.site-sub {
    font-size: 1.0em; color: #7AACCC;
    text-transform: uppercase; font-family: 'Share Tech Mono', monospace;
}
.flood-alert-none {
    display:inline-block; background:rgba(0,255,156,0.10);
    border:1px solid rgba(0,255,156,0.35); border-radius:6px;
    padding:4px 16px; font-family:'Share Tech Mono',monospace;
    font-size:0.82em; color:#00FF9C; letter-spacing:2px; margin-top:8px;
}
.flood-alert-watch {
    display:inline-block; background:rgba(255,215,0,0.12);
    border:1px solid rgba(255,215,0,0.45); border-radius:6px;
    padding:4px 16px; font-family:'Share Tech Mono',monospace;
    font-size:0.82em; color:#FFD700; letter-spacing:2px; margin-top:8px;
}
.flood-alert-warning {
    display:inline-block; background:rgba(255,100,0,0.14);
    border:1px solid rgba(255,100,0,0.5); border-radius:6px;
    padding:4px 16px; font-family:'Share Tech Mono',monospace;
    font-size:0.82em; color:#FF6400; letter-spacing:2px; margin-top:8px;
}
.flood-alert-emergency {
    display:inline-block; background:rgba(255,30,30,0.15);
    border:2px solid rgba(255,30,30,0.7); border-radius:6px;
    padding:4px 16px; font-family:'Share Tech Mono',monospace;
    font-size:0.82em; color:#FF2222; letter-spacing:2px; margin-top:8px;
    animation: blink 1s step-start infinite;
}
@keyframes blink { 50% { opacity: 0.4; } }
.panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,119,255,0.18);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.panel-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em; color: #0077FF;
    text-transform: uppercase; letter-spacing: 3px;
    margin-bottom: 14px;
    border-bottom: 1px solid rgba(0,119,255,0.18);
    padding-bottom: 8px;
}
.source-badge {
    display: inline-block;
    background: rgba(0,119,255,0.10);
    border: 1px solid rgba(0,119,255,0.28);
    border-radius: 20px; padding: 2px 10px;
    font-size: 0.72em; color: #7AACCC;
    font-family: 'Share Tech Mono', monospace; margin: 2px;
}
.stMetric label {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.75em !important; color: #7AACCC !important;
}
.stMetric [data-testid="metric-container"] {
    background: rgba(0,119,255,0.05); border-radius: 8px;
    padding: 8px; border: 1px solid rgba(0,119,255,0.13);
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  HELPER FUNCTIONS
# ─────────────────────────────────────────────
def calc_feels_like(temp_f, humidity, wind_mph):
    if temp_f is None: return None
    humidity = humidity or 0
    wind_mph = wind_mph or 0
    if temp_f >= 80 and humidity >= 40:
        hi = (-42.379 + 2.04901523*temp_f + 10.14333127*humidity
              - 0.22475541*temp_f*humidity - 0.00683783*temp_f**2
              - 0.05481717*humidity**2 + 0.00122874*temp_f**2*humidity
              + 0.00085282*temp_f*humidity**2 - 0.00000199*temp_f**2*humidity**2)
        return round(hi, 1)
    elif temp_f <= 50 and wind_mph > 3:
        wc = 35.74 + 0.6215*temp_f - 35.75*(wind_mph**0.16) + 0.4275*temp_f*(wind_mph**0.16)
        return round(wc, 1)
    return round(temp_f, 1)

def calc_dewpoint_f(temp_f, humidity):
    if temp_f is None or humidity is None or humidity <= 0: return None
    temp_c = (temp_f - 32) * 5/9
    a, b = 17.625, 243.04
    try:
        alpha = math.log(humidity / 100.0) + (a * temp_c) / (b + temp_c)
        dp_c = (b * alpha) / (a - alpha)
        return round(dp_c * 9/5 + 32, 1)
    except:
        return None

# ─────────────────────────────────────────────
#  DATA FETCHERS
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_ambient():
    try:
        r = requests.get(
            "https://api.ambientweather.net/v1/devices",
            params={"apiKey": AMBIENT_API_KEY, "applicationKey": AMBIENT_APP_KEY},
            timeout=10
        )
        r.raise_for_status()
        devices = r.json()
        if devices:
            target = next(
                (d for d in devices if d.get("macAddress","").replace(":","").replace("-","").lower()
                 == "35c7b0accb75a84d7891d82f125001a8"),
                devices[0]
            )
            last = target.get("lastData", {})
            return {
                "temp":        last.get("tempf"),
                "humidity":    last.get("humidity"),
                "wind_speed":  last.get("windspeedmph", 0),
                "wind_dir":    last.get("winddir", 0),
                "wind_gust":   last.get("windgustmph", 0),
                "rain_today":  last.get("dailyrainin", 0.0),
                "rain_1hr":    last.get("hourlyrainin", 0.0),
                "rain_week":   last.get("weeklyrainin", 0.0),
                "rain_month":  last.get("monthlyrainin", 0.0),
                "pressure":    last.get("baromrelin"),
                "solar":       last.get("solarradiation", 0),
                "name":        target.get("info", {}).get("name", "Riverbend on the Tuckasegee"),
                "ok": True
            }
    except:
        pass
    return {"ok": False}

@st.cache_data(ttl=300)
def fetch_airport_metar():
    try:
        r = requests.get(
            "https://aviationweather.gov/api/data/metar",
            params={"ids": "K24A", "format": "json"},
            timeout=8
        )
        r.raise_for_status()
        data = r.json()
        if data:
            obs = data[0]
            return {
                "temp_f":   round(obs.get("temp", 0) * 9/5 + 32, 1) if obs.get("temp") is not None else None,
                "wind_mph": round(obs.get("wspd", 0) * 1.15078, 1) if obs.get("wspd") else None,
                "wind_dir": obs.get("wdir"),
                "altim":    obs.get("altim"),
                "precip":   obs.get("precip", 0.0),
                "cover":    obs.get("skyCondition", [{}])[0].get("skyCover", "CLR") if obs.get("skyCondition") else "CLR",
                "raw":      obs.get("rawOb", ""),
                "time":     obs.get("obsTime", ""),
                "ok": True
            }
    except:
        pass
    return {"ok": False}

@st.cache_data(ttl=300)
def fetch_usgs_rain():
    results = {}
    gauges = {
        "03439000": "Tuckasegee @ Cullowhee",
        "03460000": "Tuckasegee @ Bryson City"
    }
    for site_id, name in gauges.items():
        try:
            r = requests.get(
                "https://waterservices.usgs.gov/nwis/iv/",
                params={"format": "json", "sites": site_id, "parameterCd": "00045"},
                timeout=8
            )
            r.raise_for_status()
            data = r.json()
            val = float(data['value']['timeSeries'][0]['values'][0]['value'][0]['value'])
            results[site_id] = {"name": name, "value": val, "ok": True}
        except:
            results[site_id] = {"name": name, "value": 0.0, "ok": False}
    return results

@st.cache_data(ttl=600)
def fetch_multimodel_forecast():
    model_params = {"hrrr": "hrrr_conus", "gfs": "gfs_seamless"}
    base_params = {
        "latitude": LAT, "longitude": LON,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weathercode,windspeed_10m_max",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "windspeed_unit": "mph",
        "timezone": "America/New_York",
        "forecast_days": 7
    }
    forecasts = {}
    for model_key, model_str in model_params.items():
        try:
            p = {**base_params, "models": model_str}
            r = requests.get("https://api.open-meteo.com/v1/forecast", params=p, timeout=12)
            r.raise_for_status()
            forecasts[model_key] = r.json()["daily"]
        except:
            forecasts[model_key] = None

    days = []
    today = datetime.now()
    for i in range(7):
        date = today + timedelta(days=i)
        primary   = "hrrr" if i <= 1 else "gfs"
        secondary = "gfs"  if i <= 1 else "hrrr"
        src = forecasts.get(primary) or forecasts.get(secondary)
        model_label = primary.upper() if forecasts.get(primary) else secondary.upper()
        if src and i < len(src.get("time", [])):
            days.append({
                "date":   date.strftime("%a %m/%d"),
                "day":    date.strftime("%a"),
                "hi":     round(src["temperature_2m_max"][i] or 0),
                "lo":     round(src["temperature_2m_min"][i] or 0),
                "precip": round(src["precipitation_sum"][i] or 0, 2),
                "pop":    src["precipitation_probability_max"][i] or 0,
                "wind":   round(src["windspeed_10m_max"][i] or 0),
                "code":   src["weathercode"][i] or 0,
                "model":  model_label,
                "desc":   weather_desc(src["weathercode"][i] or 0)
            })
        else:
            days.append({"date": date.strftime("%a %m/%d"), "day": date.strftime("%a"),
                         "hi": 60, "lo": 40, "precip": 0.0, "pop": 10, "wind": 10,
                         "code": 0, "model": "N/A", "desc": "Unknown"})
    return days

@st.cache_data(ttl=3600)
def fetch_historical_rain_30d():
    try:
        end   = datetime.now()
        start = end - timedelta(days=30)
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT, "longitude": LON,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "timezone": "America/New_York",
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date":   end.strftime("%Y-%m-%d")
            },
            timeout=12
        )
        r.raise_for_status()
        vals = r.json()["daily"]["precipitation_sum"]
        return [v or 0.0 for v in vals]
    except:
        return [0.05] * 30

def weather_desc(code):
    codes = {
        0:"Clear", 1:"Mainly Clear", 2:"Partly Cloudy", 3:"Overcast",
        45:"Foggy", 48:"Rime Fog", 51:"Lt Drizzle", 53:"Drizzle",
        55:"Heavy Drizzle", 61:"Lt Rain", 63:"Rain", 65:"Heavy Rain",
        71:"Lt Snow", 73:"Snow", 75:"Heavy Snow", 80:"Rain Showers",
        81:"Mod Showers", 82:"Heavy Showers", 95:"Thunderstorm",
        96:"Tstm+Hail", 99:"Tstm+Heavy Hail"
    }
    return codes.get(code, "Unknown")

def pop_color(pop):
    if pop < 20: return "#00FF9C"
    if pop < 40: return "#AAFF00"
    if pop < 60: return "#FFD700"
    if pop < 80: return "#FF8C00"
    return "#FF3333"

def estimate_soil_moisture(rain_30d, today_rain=0.0):
    FIELD_CAPACITY = 2.16
    WILTING_POINT  = 1.80
    MAX_STORAGE    = FIELD_CAPACITY + 0.5
    monthly_et = {1:0.04, 2:0.06, 3:0.10, 4:0.14, 5:0.17,
                  6:0.20, 7:0.21, 8:0.19, 9:0.14, 10:0.09,
                  11:0.05, 12:0.03}
    storage = FIELD_CAPACITY * 0.6
    today_month = datetime.now().month
    start_month = (today_month - 1) or 12
    for i, rain in enumerate(rain_30d):
        month    = start_month if i < 15 else today_month
        et_daily = monthly_et.get(month, 0.10)
        storage  = storage + rain - et_daily
        storage  = max(WILTING_POINT, min(MAX_STORAGE, storage))
    storage = min(MAX_STORAGE, storage + today_rain)
    pct = ((storage - WILTING_POINT) / (MAX_STORAGE - WILTING_POINT)) * 100
    pct = max(0, min(100, pct))
    if pct >= 90:   status, color = "SATURATED", "#FF3333"
    elif pct >= 75: status, color = "WET",        "#FF8C00"
    elif pct >= 50: status, color = "MOIST",      "#FFD700"
    elif pct >= 25: status, color = "ADEQUATE",   "#00FF9C"
    else:           status, color = "DRY",         "#5AC8FA"
    return round(pct, 1), status, color, round(storage, 2)

def make_gauge(value, title, min_val=0, max_val=100, unit="%", thresholds=None, color=None):
    if thresholds is None:
        thresholds = [
            {"range":[0,25],   "color":"rgba(0,255,156,0.15)"},
            {"range":[25,50],  "color":"rgba(255,215,0,0.15)"},
            {"range":[50,75],  "color":"rgba(255,140,0,0.15)"},
            {"range":[75,100], "color":"rgba(255,51,51,0.15)"},
        ]
    if color is None:
        if value < 30:   color = "#00FF9C"
        elif value < 55: color = "#FFD700"
        elif value < 75: color = "#FF8C00"
        else:            color = "#FF3333"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": unit, "font": {"size": 26, "color": "#FFFFFF", "family": "Rajdhani"}},
        title={"text": title, "font": {"size": 11, "color": "#7AACCC", "family": "Share Tech Mono"}},
        gauge={
            "axis": {"range": [min_val, max_val], "tickwidth": 1, "tickcolor": "#1A3050",
                     "tickfont": {"color": "#4A6A8A", "size": 8}},
            "bar":  {"color": color, "thickness": 0.25},
            "bgcolor":     "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": thresholds,
            "threshold": {"line": {"color": color, "width": 3}, "thickness": 0.85, "value": value}
        }
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=35, b=5, l=15, r=15), height=185,
        font={"color": "#E0E8F0"}
    )
    return fig

def sublabel(text, color="#7AACCC"):
    return f"<div style='text-align:center;font-family:Rajdhani;font-size:1.2em;font-weight:700;color:{color};margin-top:2px;'>{text}</div>"

def subsub(text, color="#7AACCC"):
    return f"<div style='text-align:center;font-family:Rajdhani;font-size:0.85em;color:{color};'>{text}</div>"

def srctag(text):
    return f"<div style='text-align:center;font-family:Share Tech Mono,monospace;font-size:0.62em;color:#1A5070;margin-top:1px;'>SRC: {text}</div>"

# ─────────────────────────────────────────────
#  DYNAMIC JITTER LOGIC (Simulation Mode)
#  Depth : 5.50 – 6.50 inches
#  Flow  : 4.89 – 5.35 cfs
# ─────────────────────────────────────────────
DEPTH_MIN, DEPTH_MID, DEPTH_MAX = 5.50, 6.00, 6.50   # inches
FLOW_MIN,  FLOW_MID,  FLOW_MAX  = 4.89, 5.12, 5.35   # cfs

if 'creek_depth' not in st.session_state:
    st.session_state.creek_depth = DEPTH_MID
if 'creek_flow' not in st.session_state:
    st.session_state.creek_flow  = FLOW_MID

d_step = np.random.choice([-0.02, -0.01, 0.0, 0.01, 0.02])
st.session_state.creek_depth = round(
    max(DEPTH_MIN, min(DEPTH_MAX, st.session_state.creek_depth + d_step)), 2)

f_step = np.random.choice([-0.02, -0.01, 0.0, 0.01, 0.02])
st.session_state.creek_flow  = round(
    max(FLOW_MIN,  min(FLOW_MAX,  st.session_state.creek_flow  + f_step)), 2)

creek_depth = st.session_state.creek_depth   # inches
creek_flow  = st.session_state.creek_flow    # cfs

# ─────────────────────────────────────────────
#  FETCH ALL DATA
# ─────────────────────────────────────────────
with st.spinner("Syncing watershed data sources..."):
    ambient   = fetch_ambient()
    airport   = fetch_airport_metar()
    usgs      = fetch_usgs_rain()
    forecast  = fetch_multimodel_forecast()
    hist_rain = fetch_historical_rain_30d()

rain_today = 0.0
if ambient.get("ok"):
    rain_today = ambient.get("rain_today", 0.0) or 0.0
elif airport.get("ok") and airport.get("precip"):
    rain_today = airport["precip"]

rain_1hr       = ambient.get("rain_1hr", 0.0) or 0.0
rain_3d_fcst   = round(sum(d["precip"] for d in forecast[:3]), 2)
wind_now       = ambient.get("wind_speed", 0) or (airport.get("wind_mph") or 0)
pop_today      = forecast[0]["pop"] if forecast else 0
temp_now       = ambient.get("temp")    if ambient.get("ok") else None
hum_now        = ambient.get("humidity") if ambient.get("ok") else None

soil_pct, soil_status, soil_color, soil_storage = estimate_soil_moisture(hist_rain, rain_today)

# ── Derived values ──────────────────────────

# Rain Today Gauge (0–3" scale, red above 2")
rain_gauge_val = min(rain_today, 3.0)
rain_color = "#00FF9C" if rain_today < 0.5 else "#FFD700" if rain_today < 1.0 else "#FF8C00" if rain_today < 2.0 else "#FF3333"
rain_label = "TRACE"   if rain_today < 0.1 else "LIGHT"  if rain_today < 0.5 else "MODERATE" if rain_today < 1.0 else "HEAVY" if rain_today < 2.0 else "EXTREME"

# Rain 1-Hour Intensity (0–1" scale)
rain1hr_color = "#00FF9C" if rain_1hr < 0.1 else "#FFD700" if rain_1hr < 0.25 else "#FF8C00" if rain_1hr < 0.5 else "#FF3333"
rain1hr_label = "NONE"   if rain_1hr < 0.05 else "LIGHT"  if rain_1hr < 0.1 else "MODERATE" if rain_1hr < 0.25 else "HEAVY" if rain_1hr < 0.5 else "INTENSE"

# 3-Day Forecast Rain (0–4")
fcst3d_color = "#00FF9C" if rain_3d_fcst < 0.5 else "#FFD700" if rain_3d_fcst < 1.5 else "#FF8C00" if rain_3d_fcst < 3.0 else "#FF3333"
fcst3d_label = "DRY"     if rain_3d_fcst < 0.5 else "LIGHT"   if rain_3d_fcst < 1.5 else "MODERATE" if rain_3d_fcst < 3.0 else "SIGNIFICANT"

# Precip Probability
pop_color_val = "#00FF9C" if pop_today < 20 else "#AAFF00" if pop_today < 40 else "#FFD700" if pop_today < 60 else "#FF8C00" if pop_today < 80 else "#FF3333"
pop_label     = "DRY"    if pop_today < 20 else "SLIGHT"  if pop_today < 40 else "CHANCE"   if pop_today < 60 else "LIKELY"  if pop_today < 80 else "CERTAIN"

# Humidity
hum_val   = hum_now or 0
hum_color = "#5AC8FA" if hum_val < 40 else "#00FF9C" if hum_val < 65 else "#FFD700" if hum_val < 80 else "#FF8C00"
hum_label = "DRY" if hum_val < 40 else "COMFORTABLE" if hum_val < 65 else "HUMID" if hum_val < 80 else "SATURATED"

# Wind
w_color = "#00FF9C" if wind_now < 15 else "#FFD700" if wind_now < 25 else "#FF8C00" if wind_now < 35 else "#FF3333"
w_label = "CALM"   if wind_now < 15 else "BREEZY"   if wind_now < 25 else "STRONG"  if wind_now < 35 else "DANGEROUS"

# Feels Like (temperature context for snowmelt/ice contribution)
fl_val     = None
if temp_now is not None:
    fl_val = None
    if temp_now >= 80 and (hum_now or 0) >= 40:
        fl_val = -42.379 + 2.04901523*temp_now + 10.14333127*(hum_now or 0) \
                 - 0.22475541*temp_now*(hum_now or 0) - 0.00683783*temp_now**2 \
                 - 0.05481717*(hum_now or 0)**2 + 0.00122874*temp_now**2*(hum_now or 0) \
                 + 0.00085282*temp_now*(hum_now or 0)**2 - 0.00000199*temp_now**2*(hum_now or 0)**2
        fl_val = round(fl_val, 1)
    elif temp_now <= 50 and wind_now > 3:
        fl_val = 35.74 + 0.6215*temp_now - 35.75*(wind_now**0.16) + 0.4275*temp_now*(wind_now**0.16)
        fl_val = round(fl_val, 1)
    else:
        fl_val = round(temp_now, 1)
fl_display = max(0, min(120, fl_val)) if fl_val is not None else 50
fl_color   = "#5AC8FA" if (fl_val or 50) < 32 else "#00FFFF" if (fl_val or 50) < 50 else "#00FF9C" if (fl_val or 50) < 80 else "#FFD700" if (fl_val or 50) < 95 else "#FF3333"
fl_label   = "FREEZING"  if (fl_val or 50) < 32 else "COLD" if (fl_val or 50) < 50 else "MILD" if (fl_val or 50) < 80 else "HOT" if (fl_val or 50) < 95 else "VERY HOT"
# Snowmelt flag: freezing or near-freezing temps add melt runoff risk
melt_note = "❄️ Snowmelt/Ice Runoff Risk" if (fl_val or 50) < 38 else ("🌡️ Rain-on-Snow Possible" if (fl_val or 50) < 45 else "")

# Creek Depth (inches) — thresholds scaled across 5.50–6.50"
# Low < 5.65 | Normal 5.65–6.10 | Elevated 6.10–6.35 | Flood Risk > 6.35
cd_color = "#5AC8FA" if creek_depth < 5.65 else "#00FF9C" if creek_depth < 6.10 else "#FFD700" if creek_depth < 6.35 else "#FF3333"
cd_label  = "LOW"    if creek_depth < 5.65 else "NORMAL"  if creek_depth < 6.10 else "ELEVATED" if creek_depth < 6.35 else "FLOOD RISK"

# Creek Flow (cfs) — thresholds scaled across 4.89–5.35 cfs
# Low < 4.97 | Normal 4.97–5.15 | Elevated 5.15–5.26 | High > 5.26
cf_color = "#5AC8FA" if creek_flow < 4.97 else "#00FF9C" if creek_flow < 5.15 else "#FFD700" if creek_flow < 5.26 else "#FF3333"
cf_label  = "LOW"   if creek_flow < 4.97 else "NORMAL"   if creek_flow < 5.15 else "ELEVATED" if creek_flow < 5.26 else "HIGH"

# ── Composite Flood Threat Score (0–100) ─────────────────────────────────────
# Weights: soil saturation (30%), creek depth (25%), rain today (20%),
#          3-day forecast (15%), 1-hr intensity (10%)
soil_score  = soil_pct
depth_score = max(0, min(100, (creek_depth - DEPTH_MIN) / (DEPTH_MAX - DEPTH_MIN) * 100))
rain_score  = min(100, rain_today  / 3.0  * 100)
fcst_score  = min(100, rain_3d_fcst / 4.0 * 100)
hr1_score   = min(100, rain_1hr    / 1.0  * 100)

flood_threat = round(
    soil_score  * 0.30 +
    depth_score * 0.25 +
    rain_score  * 0.20 +
    fcst_score  * 0.15 +
    hr1_score   * 0.10,
    1
)
if flood_threat < 25:
    threat_color, threat_label, alert_class = "#00FF9C", "NO FLOOD THREAT",    "flood-alert-none"
elif flood_threat < 50:
    threat_color, threat_label, alert_class = "#FFD700", "FLOOD WATCH",        "flood-alert-watch"
elif flood_threat < 75:
    threat_color, threat_label, alert_class = "#FF6400", "FLOOD WARNING",      "flood-alert-warning"
else:
    threat_color, threat_label, alert_class = "#FF2222", "FLOOD EMERGENCY",    "flood-alert-emergency"

now = datetime.now(ZoneInfo("America/New_York"))

# ─────────────────────────────────────────────
#  RENDER
# ─────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
    <div class="site-title">🌊 CULLOWHEE CREEK WATERSHED FLOOD WARNING</div>
    <div class="site-sub">{SITE} &nbsp;|&nbsp;
        {now.strftime('%A, %B %d, %Y  %I:%M %p')} EST
    </div>
    <div style="margin-top:10px;">
        <span class="{alert_class}">⚠️ THREAT LEVEL: {threat_label} &nbsp;({flood_threat}%)</span>
    </div>
    <div style="margin-top:10px;">
        <span class="source-badge">📡 AWN: {'LIVE' if ambient.get('ok') else 'OFFLINE'}</span>
        <span class="source-badge">✈️ AIRPORT 24A: {'LIVE' if airport.get('ok') else 'OFFLINE'}</span>
        <span class="source-badge">💧 USGS: {'LIVE' if any(v['ok'] for v in usgs.values()) else 'OFFLINE'}</span>
        <span class="source-badge">🌊 CREEK: SIMULATION</span>
        <span class="source-badge">🌐 OPEN-METEO: LIVE</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── ROW 1: PRECIPITATION & ATMOSPHERIC CONDITIONS ──────────────────────────
st.markdown('<div class="panel"><div class="panel-title">🌧️ Precipitation & Atmospheric Conditions</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    fig = make_gauge(rain_gauge_val, "RAIN TODAY", min_val=0, max_val=3.0, unit='"', color=rain_color,
        thresholds=[{"range":[0,0.5],"color":"rgba(0,255,156,0.12)"},{"range":[0.5,1.0],"color":"rgba(255,215,0,0.12)"},
                    {"range":[1.0,2.0],"color":"rgba(255,140,0,0.12)"},{"range":[2.0,3.0],"color":"rgba(255,51,51,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(rain_label, rain_color), unsafe_allow_html=True)
    st.markdown(subsub(f"1-Hr: <b style='color:#00FFCC'>{rain_1hr}&quot;</b>"), unsafe_allow_html=True)
    st.markdown(srctag("AWN SENSOR"), unsafe_allow_html=True)

with c2:
    fig = make_gauge(min(rain_1hr, 1.0), "RAINFALL INTENSITY (1-HR)", min_val=0, max_val=1.0, unit='"', color=rain1hr_color,
        thresholds=[{"range":[0,0.1],"color":"rgba(0,255,156,0.12)"},{"range":[0.1,0.25],"color":"rgba(255,215,0,0.12)"},
                    {"range":[0.25,0.5],"color":"rgba(255,140,0,0.12)"},{"range":[0.5,1.0],"color":"rgba(255,51,51,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(rain1hr_label, rain1hr_color), unsafe_allow_html=True)
    st.markdown(subsub("Flash flood threshold: 0.5\"/hr"), unsafe_allow_html=True)
    st.markdown(srctag("AWN SENSOR"), unsafe_allow_html=True)

with c3:
    fig = make_gauge(min(rain_3d_fcst, 4.0), "3-DAY FORECAST RAIN", min_val=0, max_val=4.0, unit='"', color=fcst3d_color,
        thresholds=[{"range":[0,0.5],"color":"rgba(0,255,156,0.12)"},{"range":[0.5,1.5],"color":"rgba(255,215,0,0.12)"},
                    {"range":[1.5,3.0],"color":"rgba(255,140,0,0.12)"},{"range":[3.0,4.0],"color":"rgba(255,51,51,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(fcst3d_label, fcst3d_color), unsafe_allow_html=True)
    st.markdown(subsub(f"PoP Today: <b style='color:#00FFCC'>{pop_today}%</b>"), unsafe_allow_html=True)
    st.markdown(srctag("OPEN-METEO HRRR/GFS"), unsafe_allow_html=True)

with c4:
    fig = make_gauge(hum_val, "HUMIDITY", min_val=0, max_val=100, unit="%", color=hum_color,
        thresholds=[{"range":[0,40],"color":"rgba(90,200,250,0.12)"},{"range":[40,65],"color":"rgba(0,255,156,0.12)"},
                    {"range":[65,80],"color":"rgba(255,215,0,0.12)"},{"range":[80,100],"color":"rgba(255,140,0,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(hum_label, hum_color), unsafe_allow_html=True)
    dp_val = calc_dewpoint_f(temp_now, hum_now)
    dp_str = f"Dewpoint: <b style='color:#00FFCC'>{dp_val}&deg;F</b>" if dp_val else "Dewpoint: --"
    st.markdown(subsub(dp_str), unsafe_allow_html=True)
    st.markdown(srctag("AWN SENSOR"), unsafe_allow_html=True)

with c5:
    fig = make_gauge(fl_display, "TEMPERATURE / FEELS LIKE", min_val=0, max_val=100, unit="°F", color=fl_color,
        thresholds=[{"range":[0,32],"color":"rgba(90,200,250,0.12)"},{"range":[32,50],"color":"rgba(0,255,255,0.12)"},
                    {"range":[50,80],"color":"rgba(0,255,156,0.12)"},{"range":[80,100],"color":"rgba(255,140,0,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(fl_label, fl_color), unsafe_allow_html=True)
    actual_str = f"Actual: <b style='color:#00FFCC'>{temp_now}&deg;F</b>" if temp_now else "Actual: --"
    note_str = f"<b style='color:#FF8C00'>{melt_note}</b>" if melt_note else "&nbsp;"
    st.markdown(subsub(actual_str), unsafe_allow_html=True)
    st.markdown(subsub(note_str), unsafe_allow_html=True)
    st.markdown(srctag("AWN + CALC"), unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# ── ROW 2: WATERSHED HYDROLOGY ──────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">🌊 Watershed Hydrology — Tuckasegee Creek Monitoring</div>', unsafe_allow_html=True)
h1, h2, h3, h4 = st.columns([2, 2, 2, 3])

with h1:
    fig = make_gauge(soil_pct, "SOIL MOISTURE / RUNOFF RISK", color=soil_color,
        thresholds=[{"range":[0,25],"color":"rgba(90,200,250,0.12)"},{"range":[25,50],"color":"rgba(0,255,156,0.12)"},
                    {"range":[50,75],"color":"rgba(255,215,0,0.12)"},{"range":[75,100],"color":"rgba(255,51,51,0.12)"}])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(soil_status, soil_color), unsafe_allow_html=True)
    st.markdown(subsub(f"Storage: <b style='color:#00FFCC'>{soil_storage} in</b>"), unsafe_allow_html=True)
    st.markdown(srctag("WATER BALANCE MODEL"), unsafe_allow_html=True)

with h2:
    fig = make_gauge(creek_depth, "CREEK DEPTH", min_val=5.50, max_val=6.50, unit='"', color=cd_color,
        thresholds=[
            {"range":[5.50, 5.65], "color":"rgba(90,200,250,0.12)"},
            {"range":[5.65, 6.10], "color":"rgba(0,255,156,0.12)"},
            {"range":[6.10, 6.35], "color":"rgba(255,215,0,0.12)"},
            {"range":[6.35, 6.50], "color":"rgba(255,51,51,0.12)"},
        ])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(cd_label, cd_color), unsafe_allow_html=True)
    st.markdown(subsub(f"Depth: <b style='color:#00FFCC'>{creek_depth}&quot;</b>"), unsafe_allow_html=True)
    st.markdown(srctag("NEMO / SIMULATION"), unsafe_allow_html=True)

with h3:
    fig = make_gauge(creek_flow, "CREEK FLOW RATE", min_val=4.89, max_val=5.35, unit=" cfs", color=cf_color,
        thresholds=[
            {"range":[4.89, 4.97], "color":"rgba(90,200,250,0.12)"},
            {"range":[4.97, 5.15], "color":"rgba(0,255,156,0.12)"},
            {"range":[5.15, 5.26], "color":"rgba(255,215,0,0.12)"},
            {"range":[5.26, 5.35], "color":"rgba(255,51,51,0.12)"},
        ])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(sublabel(cf_label, cf_color), unsafe_allow_html=True)
    st.markdown(subsub(f"Flow: <b style='color:#00FFCC'>{creek_flow} cfs</b>"), unsafe_allow_html=True)
    st.markdown(srctag("NEMO / SIMULATION"), unsafe_allow_html=True)

with h4:
    st.markdown(f"""
    <div style="background:rgba(0,80,160,0.07);border:1px solid rgba(0,119,255,0.18);
                border-radius:8px;padding:18px 20px;font-family:'Share Tech Mono';
                font-size:0.77em;color:#7AACCC;line-height:2.0;">
        <div style="color:#0077FF;letter-spacing:2px;font-size:0.85em;margin-bottom:10px;
                    border-bottom:1px solid rgba(0,119,255,0.18);padding-bottom:6px;">
            📊 FLOOD THREAT SCORE — COMPOSITE INDEX
        </div>
        <div style="font-size:1.5em;font-weight:700;color:{threat_color};letter-spacing:2px;margin-bottom:8px;">
            {flood_threat}% &mdash; {threat_label}
        </div>
        <span style="color:#5AC8FA;font-weight:700;">CONTRIBUTING FACTORS</span><br>
        Soil Saturation &nbsp;&nbsp;&nbsp;→ <b style="color:#00FFCC">{soil_pct}%</b> ({soil_status}) — 30% weight<br>
        Creek Depth &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ <b style="color:#00FFCC">{creek_depth}&quot;</b> ({cd_label}) — 25% weight<br>
        Rain Today &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ <b style="color:#00FFCC">{rain_today}"</b> ({rain_label}) — 20% weight<br>
        3-Day Forecast &nbsp;&nbsp;→ <b style="color:#00FFCC">{rain_3d_fcst}"</b> ({fcst3d_label}) — 15% weight<br>
        1-Hr Intensity &nbsp;&nbsp;&nbsp;→ <b style="color:#00FFCC">{rain_1hr}"</b> ({rain1hr_label}) — 10% weight<br>
        <br>
        <div style="color:#1A5070;font-size:0.88em;">
            ⚙️ Creek sensors in NEMO simulation mode.
            Replace with live Blues Notecard / USGS feed at deployment.
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# ── 7-DAY FORECAST ──────────────────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">📅 7-Day Multi-Model Forecast</div>', unsafe_allow_html=True)
cols = st.columns(7)
for i, day in enumerate(forecast):
    pc = pop_color(day["pop"])
    with cols[i]:
        st.markdown(f"""
        <div style="background:rgba(0,80,160,0.06);border:1px solid rgba(0,119,255,0.18);
                    border-top:3px solid {pc};border-radius:8px;padding:10px 6px;text-align:center;">
            <div style="font-family:'Rajdhani';font-weight:700;color:#FFFFFF;font-size:1.1em;">{day['day']}</div>
            <div style="font-family:'Share Tech Mono';font-size:0.68em;color:#7AACCC;">{day['date'].split()[1]}</div>
            <div style="margin:6px 0;">
                <span style="color:#FF6B35;font-weight:700;font-size:1.2em;">{day['hi']}&deg;</span>
                <span style="color:#5AC8FA;font-size:0.95em;"> / {day['lo']}&deg;</span>
            </div>
            <div style="color:{pc};font-weight:700;font-size:0.95em;">{day['pop']}%</div>
            <div style="color:#00FFCC;font-size:0.82em;">{day['precip']}&quot;</div>
            <div style="font-size:0.65em;color:#7AACCC;margin-top:2px;">{day['desc']}</div>
            <div style="margin-top:6px;background:rgba(0,200,150,0.07);border:1px solid rgba(0,200,150,0.18);
                        border-radius:3px;padding:1px 4px;font-size:0.62em;color:#00FFB4;
                        font-family:'Share Tech Mono';">{day['model']}</div>
        </div>
        """, unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── DATA SOURCE PANELS ───────────────────────────────────────────────────────
live_panels = []
if ambient.get("ok"):    live_panels.append("ambient")
if airport.get("ok"):    live_panels.append("airport")
usgs_live = {k: v for k, v in usgs.items() if v["ok"]}
if usgs_live:            live_panels.append("usgs")
live_panels.append("soil")

if live_panels:
    panel_cols = st.columns(len(live_panels))
    for idx, panel_key in enumerate(live_panels):
        with panel_cols[idx]:
            if panel_key == "ambient":
                st.markdown('<div class="panel"><div class="panel-title">📡 Riverbend on the Tuckasegee (AWN)</div>', unsafe_allow_html=True)
                st.caption(f"Station: {ambient['name']}")
                c1, c2 = st.columns(2)
                c1.metric("Temperature",  f"{ambient['temp']}°F")
                c2.metric("Humidity",     f"{ambient['humidity']}%")
                c1.metric("Rain Today",   f"{ambient['rain_today']}\"")
                c2.metric("Rain / Hour",  f"{ambient['rain_1hr']}\"")
                c1.metric("Rain 7-Day",   f"{ambient['rain_week']}\"")
                c2.metric("Rain 30-Day",  f"{ambient['rain_month']}\"")
                c1.metric("Pressure",     f"{ambient['pressure']} inHg")
                c2.metric("Solar Rad",    f"{ambient['solar']} W/m²")
                st.markdown('</div>', unsafe_allow_html=True)

            elif panel_key == "airport":
                st.markdown('<div class="panel"><div class="panel-title">✈️ Jackson County Airport (24A)</div>', unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                c1.metric("Temperature",  f"{airport['temp_f']}°F" if airport.get('temp_f') else "--")
                c2.metric("Wind",         f"{airport['wind_mph']} mph" if airport.get('wind_mph') else "--")
                c1.metric("Wind Dir",     f"{airport['wind_dir']}°"   if airport.get('wind_dir') else "--")
                c2.metric("Altimeter",    f"{airport['altim']} inHg"  if airport.get('altim')   else "--")
                c1.metric("Sky Cover",    airport.get("cover", "--"))
                c2.metric("Precip",       f"{airport.get('precip', 0.0)}\"")
                st.caption(f"Raw METAR: `{airport.get('raw','')}`")
                st.caption(f"Obs Time: {airport.get('time','')}")
                st.markdown('</div>', unsafe_allow_html=True)

            elif panel_key == "usgs":
                st.markdown('<div class="panel"><div class="panel-title">💧 USGS Stream Gauges</div>', unsafe_allow_html=True)
                for site_id, info in usgs_live.items():
                    st.metric(f"🟢 {info['name']}", f"{info['value']}\" precip")
                st.markdown('</div>', unsafe_allow_html=True)

            elif panel_key == "soil":
                st.markdown('<div class="panel"><div class="panel-title">🌱 Soil Moisture Model</div>', unsafe_allow_html=True)
                rain_30d_total = round(sum(hist_rain), 2)
                st.markdown(f"""
                <div style="font-family:'Share Tech Mono';font-size:0.8em;color:#7AACCC;line-height:1.8;">
                <b style="color:#FFFFFF">Model:</b> Water Balance Bucket<br>
                <b style="color:#FFFFFF">Soil Type:</b> Mountain Clay Loam (Ultisol)<br>
                <b style="color:#FFFFFF">Root Zone:</b> 12 inches<br>
                <b style="color:#FFFFFF">Field Capacity:</b> 2.16 in storage<br>
                <b style="color:#FFFFFF">Current Storage:</b> {soil_storage} in<br>
                <b style="color:#FFFFFF">Saturation:</b>
                    <span style="color:{soil_color};font-weight:700;">{soil_pct}% &mdash; {soil_status}</span><br>
                <b style="color:#FFFFFF">30-Day Rain:</b> {rain_30d_total}&quot;
                </div>
                """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

# ── RADAR ────────────────────────────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">🛰️ Live Radar — Jackson County / Cullowhee Creek Watershed</div>', unsafe_allow_html=True)
st.components.v1.html(
    '<iframe width="100%" height="500" src="https://embed.windy.com/embed2.html?lat=35.308&lon=-83.175&zoom=9&overlay=radar&product=radar&level=surface" frameborder="0" style="border-radius:8px;"></iframe>',
    height=510
)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f"""
<div style="text-align:center;font-family:'Share Tech Mono';font-size:0.7em;color:#1A3050;margin-top:20px;">
CULLOWHEE CREEK WATERSHED FLOOD WARNING &nbsp;|&nbsp; {SITE} &nbsp;|&nbsp;
Sources: Riverbend AWN &middot; NOAA/24A &middot; USGS 03439000/03460000 &middot;
Open-Meteo (HRRR/GFS) &middot; NEMO Creek Simulation &nbsp;|&nbsp; Auto-refresh: 5 min
</div>
""", unsafe_allow_html=True)
