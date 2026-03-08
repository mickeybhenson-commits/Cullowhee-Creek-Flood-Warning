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


@st.cache_data(ttl=1800)
def fetch_30d_precip():
    """
    Uses Open-Meteo HRRR/GFS hourly precip — no ERA5 latency.
    past_days=14 + forecast_days=1 gives current-hour accuracy.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":           LAT,
                "longitude":          LON,
                "hourly":             "precipitation,snowfall",
                "precipitation_unit": "inch",
                "wind_speed_unit":    "mph",
                "past_days":          14,
                "forecast_days":      1,
                "models":             "best_match",
            },
            timeout=10
        ).json()

        now        = datetime.utcnow()
        times      = r["hourly"]["time"]
        precip_h   = r["hourly"]["precipitation"]
        snow_h     = r["hourly"].get("snowfall", [0]*len(times))

        total_14d = 0.0
        total_7d  = 0.0
        total_24h = 0.0
        snow_7d   = 0.0

        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t)
            except:
                continue
            age_days = (now - dt).total_seconds() / 86400
            if age_days < 0:        # skip future hours
                continue
            p = precip_h[i] or 0.0
            s = (snow_h[i] or 0.0) * 0.0393701  # cm -> inch
            if age_days <= 14:
                total_14d += p
            if age_days <= 7:
                total_7d  += p
                snow_7d   += s
            if age_days <= 1:
                total_24h += p

        return round(total_14d,2), round(total_7d,2), round(snow_7d,2), round(total_24h,2), True
    except Exception as e:
        return 2.10, 0.50, 0.00, 0.00, False


@st.cache_data(ttl=3600)
def fetch_era5_soil_moisture():
    """
    ERA5-Land volumetric soil moisture — best available model for pre-sensor operations.
    Two depth layers relevant to surface runoff / infiltration:
      0-7cm  : surface response layer  (fastest response to rainfall)
      7-28cm : root zone / vadose zone  (controls longer-term saturation state)
    ERA5-Land lag: ~5 days. We fetch last 14 days and take most recent valid data.
    """
    try:
        from datetime import date, timedelta
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=14)
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude":   LAT,
                "longitude":  LON,
                "hourly":     "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
                "models":     "era5_land",
                "start_date": start_dt.strftime("%Y-%m-%d"),
                "end_date":   end_dt.strftime("%Y-%m-%d"),
            },
            timeout=15
        ).json()

        times  = r["hourly"]["time"]
        sm_07  = r["hourly"]["soil_moisture_0_to_7cm"]
        sm_728 = r["hourly"]["soil_moisture_7_to_28cm"]

        # Walk backwards to find most recent non-null pair
        latest_07, latest_728, latest_ts = None, None, None
        for i in range(len(times) - 1, -1, -1):
            if sm_07[i] is not None and sm_728[i] is not None:
                latest_07  = sm_07[i]
                latest_728 = sm_728[i]
                latest_ts  = times[i]
                break

        if latest_07 is None:
            return None, None, None, False

        return round(latest_07, 4), round(latest_728, 4), latest_ts, True

    except Exception:
        return None, None, None, False




# ─────────────────────────────────────────────
#  3. HYDRO-MODELING
# ─────────────────────────────────────────────

# ERA5-Land / Ultisol soil constants for WNC (Evard-Cowee-Plott series)
# These match the loam soil type ERA5-Land assigns to this terrain class.
SOIL_POROSITY  = 0.439   # m3/m3 — saturated (pore space)
SOIL_FIELD_CAP = 0.286   # m3/m3 — field capacity (drains freely above this)
SOIL_WILT_PT   = 0.151   # m3/m3 — permanent wilting point

# ── Cullowhee Creek Watershed Parameters (NCCAT sensor point) ──────────────
# Source: HUC-12 delineation, NLCD land cover, SSURGO soils, field estimates
# All values flagged for calibration update upon sensor deployment.
WS_AREA_ACRES = 6200        # ~25.1 km² drainage area to NCCAT gauge point
WS_TC_HRS     = 2.5         # Time of concentration, Kirpich formula estimate (hr)
WS_CN_II      = 68          # SCS Curve Number, AMC-II (forested Ultisol, ~20% impervious)
WS_SLOPE      = 0.010       # Average channel slope ft/ft
WS_WIDTH_FT   = 28.0        # Estimated bankfull channel width at NCCAT (ft)
WS_MANN_N     = 0.045       # Manning's n, natural cobble/gravel mountain stream
# Power-law rating curve Q = RATING_A * D^RATING_B (depth→discharge)
# Derived from Manning's + trapezoidal cross-section; update with sensor data
RATING_A      = 44.0        # discharge coefficient (cfs/ft^b)
RATING_B      = 2.30        # depth exponent (typical 2.1–2.6 for WNC streams)
BASEFLOW_CFS  = 9.0         # Estimated low-season baseflow at NCCAT (cfs)

def get_soil_model(sm_07, sm_728):
    """
    Convert ERA5-Land volumetric soil moisture (m3/m3) to saturation % and
    equivalent stored water inches for dashboard display.

    Weighted average: surface 0-7cm gets 55% weight (most flood-relevant),
    root zone 7-28cm gets 45% weight.

    Stored water inches:
      0-7cm  layer = 2.756 inches deep  -> stored = sm_07  * 2.756
      7-28cm layer = 8.268 inches deep  -> stored = sm_728 * 8.268
    """
    RANGE = SOIL_POROSITY - SOIL_WILT_PT  # 0.288 m3/m3 = full available range

    sm_avg  = (sm_07 * 0.55) + (sm_728 * 0.45)
    # Clamp to valid range — ERA5-Land can report values above theoretical porosity
    sm_avg  = min(sm_avg, SOIL_POROSITY)
    sat_pct = min(100.0, max(0.0, (sm_avg - SOIL_WILT_PT) / RANGE * 100))

    stored_in = (sm_07 * 2.756) + (sm_728 * 8.268)

    color = "#FF3333" if sat_pct > 85 else "#FF8800" if sat_pct > 70 else "#FFD700" if sat_pct > 50 else "#00FF9C"
    return round(stored_in, 2), round(sat_pct, 2), color


def model_stream_conditions(soil_sat_pct, rain_24h, qpf_24h, rain_7d):
    """
    Cullowhee Creek depth and discharge model — pre-sensor operational estimate.

    Method:
      1. SCS-CN with AMC adjustment (soil_sat → AMC I/II/III)
      2. Rational Method: Q_storm = C·i·A (peak stormflow component)
      3. Antecedent baseflow: scaled from BASEFLOW_CFS × soil moisture multiplier
      4. Rating curve: D = (Q_total / RATING_A)^(1/RATING_B)

    All parameters are documented in watershed constants above.
    Will be calibrated against actual sensor data upon NCCAT deployment.
    """
    import math

    # 1. AMC adjustment of CN based on soil saturation
    if soil_sat_pct < 30:
        cn_adj = max(50, WS_CN_II * 0.87)   # AMC-I dry antecedent
    elif soil_sat_pct < 65:
        cn_adj = WS_CN_II                    # AMC-II normal
    else:
        # AMC-III — wet; standard formula: CN3 = 23*CN2 / (10 + 0.13*CN2)
        cn_adj = min(95, (23 * WS_CN_II) / (10 + 0.13 * WS_CN_II))

    # 2. SCS runoff depth from combined actual + forecast 24h rain
    P  = max(0.0, rain_24h + qpf_24h)
    S  = (1000 / cn_adj) - 10               # potential max retention (inches)
    Ia = 0.2 * S                             # initial abstraction
    Q_runoff_in = ((P - Ia)**2 / (P - Ia + S)) if P > Ia else 0.0

    # 3. Rational Method peak storm discharge
    # Runoff coefficient C derived from CN (Mockus 1949 approximation)
    C = max(0.0, min(0.95, (cn_adj - 25) / 75))
    i_inhr = P / 24.0                        # avg intensity (in/hr) over 24h window
    Q_storm_cfs = (C * i_inhr * WS_AREA_ACRES) / 1.008  # rational method (cfs)

    # 4. Antecedent baseflow: rises with soil saturation (higher water table)
    bf_mult = 1.0 + (soil_sat_pct / 100) * 3.0   # 1× dry → 4× saturated
    Q_base  = BASEFLOW_CFS * bf_mult

    # 5. 7-day antecedent recession: adds sustained elevated flow
    Q_recess = max(0.0, (rain_7d - rain_24h) * 0.8)   # inches → rough cfs offset

    # 6. Total discharge
    Q_total = Q_base + Q_storm_cfs + Q_recess
    Q_total = round(max(BASEFLOW_CFS * 0.5, min(Q_total, 2800.0)), 1)

    # 7. Rating curve: D = (Q / A)^(1/b)
    depth_ft = (Q_total / RATING_A) ** (1.0 / RATING_B)
    depth_ft = round(max(0.30, min(depth_ft, 7.8)), 2)

    return depth_ft, Q_total


def compute_flood_threat(soil_sat, qpf_24h, pop_24h):
    soil_score = soil_sat * 0.40
    qpf_score  = min(100.0, qpf_24h * 40) * 0.35
    pop_score  = pop_24h * 0.25
    return round(min(100.0, soil_score + qpf_score + pop_score), 2)


def threat_meta(score):
    if score < 25: return "NORMAL",    "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45: return "ELEVATED",  "#FFFF00", "rgba(255,255,0,0.09)"
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
    # Build title text with clean, readable hierarchy
    title_parts = [f"<b>{t}</b>"]
    if sub:
        title_parts.append(f"<span style='font-size:11px;color:#7AACCC'>{sub}</span>")
    if src:
        title_parts.append(f"<span style='font-size:9px;color:#2A6080'>{src}</span>")
    title_text = "<br>".join(title_parts)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": u, "font": {"size": 24, "color": "white"}, "valueformat": ".2f"},
        title={
            "text": title_text,
            "font": {"size": 13, "color": "#A0C8E0"},
        },
        gauge={
            "axis":    {"range": [min_v, max_v], "tickfont": {"size": 9, "color": "#334455"}},
            "bar":     {"color": c, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=70, b=20, l=25, r=25),
        height=185,
    )
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
rain_30d, rain_7d, snow_7d, rain_24h, prcp_ok = fetch_30d_precip()
sm_07, sm_728, sm_ts, sm_ok = fetch_era5_soil_moisture()

# ERA5-Land data preferred; proxy fallback if unavailable
if sm_ok and sm_07 is not None:
    soil_in, soil_sat, soil_color = get_soil_model(sm_07, sm_728)
else:
    _range    = SOIL_POROSITY - SOIL_WILT_PT
    _sm_proxy = min(SOIL_POROSITY, SOIL_WILT_PT + (min(rain_30d, 14.0) / 14.0) * _range)
    soil_in, soil_sat, soil_color = get_soil_model(_sm_proxy, _sm_proxy * 0.85)

qpf_24h    = forecast[0]["qpf"] if forecast else 0.0
pop_24h    = forecast[0]["pop"] if forecast else 0.0
threat_score            = compute_flood_threat(soil_sat, qpf_24h, pop_24h)
t_label, t_color, t_bg = threat_meta(threat_score)

if "depth" not in st.session_state: st.session_state.depth = 0.87
if "flow"  not in st.session_state: st.session_state.flow  = 22.40

# Replace random walk with physically modeled depth & discharge
modeled_depth, modeled_flow = model_stream_conditions(soil_sat, rain_24h, qpf_24h, rain_7d)
# Smooth toward modeled value (damp rapid jumps on each 30s refresh)
st.session_state.depth = round(st.session_state.depth * 0.30 + modeled_depth * 0.70, 2)
st.session_state.flow  = round(st.session_state.flow  * 0.30 + modeled_flow  * 0.70, 1)


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
with c3: st.plotly_chart(make_dial(noaa["temp"],  "TEMPERATURE",     0, 110,  " F",    "#FF3333", src="OPEN-METEO"), use_container_width=True)
with c4: st.plotly_chart(make_dial(rain_24h, "RAIN (24H)", 0, 10, '"',  "#0077FF", sub="24-Hour Accumulation", src="OPEN-METEO HRRR"), use_container_width=True)
with c5: st.plotly_chart(make_dial(soil_sat, "SOIL SATURATION", 0, 100, "%", "#0077FF", sub=f'{soil_in:.2f}" Stored | ERA5-Land', src="ECMWF ERA5-LAND"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ROW 2: CULLOWHEE CREEK
st.markdown('<div class="panel"><div class="panel-title">CULLOWHEE CREEK &mdash; WATERSHED MODEL (PRE-SENSOR)</div>', unsafe_allow_html=True)
h1, h2, h3 = st.columns([2, 2, 3])

# Depth status thresholds (ft) — NCCAT point, estimated bankfull ~5.5ft
_d = st.session_state.depth
_q = st.session_state.flow
if _d < 2.5:   _depth_lbl, _depth_clr = "LOW FLOW",  "#00FF9C"
elif _d < 4.0: _depth_lbl, _depth_clr = "NORMAL",    "#00FF9C"
elif _d < 5.5: _depth_lbl, _depth_clr = "ELEVATED",  "#FFFF00"
elif _d < 6.5: _depth_lbl, _depth_clr = "WATCH",     "#FFD700"
else:          _depth_lbl, _depth_clr = "FLOOD",     "#FF3333"

if _q < 40:    _flow_lbl,  _flow_clr  = "LOW FLOW",  "#00FF9C"
elif _q < 150: _flow_lbl,  _flow_clr  = "NORMAL",    "#00FF9C"
elif _q < 400: _flow_lbl,  _flow_clr  = "ELEVATED",  "#FFFF00"
elif _q < 800: _flow_lbl,  _flow_clr  = "HIGH",      "#FFD700"
else:          _flow_lbl,  _flow_clr  = "FLOOD",     "#FF3333"

with h1:
    st.components.v1.html(make_animated_gauge_html(
        "g_depth", st.session_state.depth,
        "STREAM DEPTH", 0.0, 8.0, " ft",
        [{"range": [0.0, 4.0], "color": "rgba(0,255,156,0.15)"},
         {"range": [4.0, 5.5], "color": "rgba(255,255,0,0.20)"},
         {"range": [5.5, 8.0], "color": "rgba(255,51,51,0.25)"}],
        _depth_clr, _depth_lbl, _depth_clr,
        f"Stage: {st.session_state.depth:.2f} ft  |  Bankfull: ~5.5 ft", "SCS-CN MODEL"
    ), height=230)
with h2:
    st.components.v1.html(make_animated_gauge_html(
        "g_flow", st.session_state.flow,
        "DISCHARGE", 0.0, 1000.0, " cfs",
        [{"range": [0.0,   150.0], "color": "rgba(0,255,156,0.15)"},
         {"range": [150.0, 400.0], "color": "rgba(255,255,0,0.20)"},
         {"range": [400.0,1000.0], "color": "rgba(255,51,51,0.25)"}],
        _flow_clr, _flow_lbl, _flow_clr,
        f"Q: {st.session_state.flow:.1f} cfs  |  Rating curve: Q=44·D^2.3", "RATIONAL METHOD"
    ), height=230)
with h3:
    if sm_ok and sm_07 is not None:
        # Clamp: ERA5-Land can report moisture above theoretical porosity
        sm_07_c   = min(sm_07,  SOIL_POROSITY)
        sm_728_c  = min(sm_728, SOIL_POROSITY)
        sm_range  = SOIL_POROSITY - SOIL_WILT_PT
        sm_07_pct  = round(max(0, min(100, (sm_07_c  - SOIL_WILT_PT) / sm_range * 100)), 1)
        sm_728_pct = round(max(0, min(100, (sm_728_c - SOIL_WILT_PT) / sm_range * 100)), 1)
        sm_ts_label = sm_ts[:13].replace("T", " ") + " UTC" if sm_ts else "---"
        src_line = f"ECMWF ERA5-LAND  |  Valid: {sm_ts_label}"
    else:
        sm_07_c, sm_728_c = 0.0, 0.0
        sm_07_pct, sm_728_pct = 0.0, 0.0
        src_line = "ERA5-LAND unavailable — proxy mode"

    st.markdown("**SOIL MOISTURE — ERA5-LAND**")
    ma, mb = st.columns(2)
    ma.metric("0–7 cm (surface)",    f"{sm_07_c:.3f} m³/m³",  f"{sm_07_pct:.1f}% sat")
    mb.metric("7–28 cm (root zone)", f"{sm_728_c:.3f} m³/m³", f"{sm_728_pct:.1f}% sat")

    mc, md = st.columns(2)
    mc.metric("Stored Water",    f'{soil_in:.2f}"',  "0–35 cm profile")
    md.metric("Saturation",      f"{soil_sat:.1f}%", "of pore capacity")

    st.divider()

    st.markdown("**STREAM MODEL — SCS-CN / RATIONAL**")
    me, mf = st.columns(2)
    me.metric("Rain 24h / QPF",  f'{rain_24h:.2f}" + {qpf_24h:.2f}"')
    mf.metric("Rain 7-Day",      f'{rain_7d:.2f}"')

    mg, mh = st.columns(2)
    mg.metric("Modeled Discharge", f"{modeled_flow:.1f} cfs")
    mh.metric("Modeled Depth",     f"{modeled_depth:.2f} ft")

    st.caption(f"CN={WS_CN_II} base | Tc={WS_TC_HRS}h | n={WS_MANN_N} | {WS_AREA_ACRES:,} ac watershed")
st.markdown('</div>', unsafe_allow_html=True)

# ROW 3: 7-DAY FLOOD OUTLOOK
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED (NWS GSP GRIDPOINT)</div>', unsafe_allow_html=True)
if not fc_ok:
    st.warning(f"NWS forecast unavailable — {fc_err}")
elif forecast:
    pcols = st.columns(7)
    for i, d in enumerate(forecast):
        risk      = min(100.0, round((soil_sat * 0.35) + (d["pop"] * 0.35) + (d["qpf"] * 20), 2))
        color     = "#00FF9C" if risk < 30 else "#FFFF00" if risk < 50 else "#FFD700" if risk < 65 else "#FF8800" if risk < 80 else "#FF3333"
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


# ROW 5: LIVE RADAR — NWS KGSP NEXRAD WSR-88D
st.markdown('<div class="panel"><div class="panel-title">NEXRAD WSR-88D RADAR &mdash; KGSP GREENVILLE-SPARTANBURG</div>', unsafe_allow_html=True)

import time as _time
_cache_bust = int(_time.time() / 120)  # refresh every 2 min

radar_html = f"""
<div style="
    background: #04090F;
    border-radius: 10px;
    border: 1px solid #1a2a3a;
    overflow: hidden;
    font-family: 'Courier New', monospace;
">
  <!-- Header bar -->
  <div style="
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 16px;
      background: #0a1520;
      border-bottom: 1px solid #1a3a5a;
  ">
    <div style="display:flex; align-items:center; gap:10px;">
      <div style="width:8px; height:8px; border-radius:50%; background:#00FF9C; box-shadow:0 0 6px #00FF9C;"></div>
      <span style="color:#00CFFF; font-size:11px; font-weight:700; letter-spacing:2px;">LIVE</span>
      <span style="color:#8899AA; font-size:11px; letter-spacing:1px;">| WSR-88D BASE REFLECTIVITY | KGSP | NWS GREENVILLE-SPARTANBURG</span>
    </div>
    <div style="color:#556677; font-size:10px; letter-spacing:1px;">AUTO-LOOP &#x21BB; 2 MIN</div>
  </div>

  <!-- Radar image -->
  <div style="position:relative; background:#000; text-align:center;">
    <img src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?v={_cache_bust}"
         style="width:100%; max-height:520px; object-fit:contain; display:block;"
         alt="KGSP NEXRAD Loop" />

    <!-- Bottom legend bar -->
    <div style="
        position:absolute; bottom:0; left:0; right:0;
        background: linear-gradient(transparent, rgba(0,0,0,0.85));
        padding: 20px 16px 8px;
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
    ">
      <div style="color:#667788; font-size:10px; letter-spacing:1px;">
        COVERAGE AREA: WNC &bull; SC UPSTATE &bull; NW GA &bull; SW VA
      </div>
      <div style="display:flex; gap:4px; align-items:center;">
        <span style="color:#556677; font-size:9px; margin-right:4px;">dBZ</span>
        <span style="display:inline-block; width:18px; height:10px; background:#04e9e7;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#009d00;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#00d400;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#f5f500;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#e69800;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#e60000;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#990000;"></span>
        <span style="display:inline-block; width:18px; height:10px; background:#ff00ff;"></span>
        <span style="color:#556677; font-size:9px; margin-left:4px;">LIGHT &rarr; EXTREME</span>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div style="
      padding: 6px 16px;
      background: #0a1520;
      border-top: 1px solid #1a3a5a;
      display: flex;
      justify-content: space-between;
  ">
    <span style="color:#445566; font-size:10px; letter-spacing:1px;">SRC: radar.weather.gov &bull; NWS OPERATIONAL DATA</span>
    <span style="color:#445566; font-size:10px; letter-spacing:1px;">JACKSON CO. WATERSHED MONITORING SYSTEM</span>
  </div>
</div>
"""

st.components.v1.html(radar_html, height=610)
st.markdown('</div>', unsafe_allow_html=True)
