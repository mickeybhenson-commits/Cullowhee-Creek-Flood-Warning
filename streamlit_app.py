"""
NOAH: Cullowhee Creek Flood Warning Dashboard
Nautilus Technologies — Jackson County, NC — Watershed Monitoring System

Precipitation source chain (priority order):
  1.  Live sensor array     custom_json / weathercom_pws  (deploy target)
  1.5 Ambient Weather PWS   rt.ambientweather.net API     (~1 min lag)
  2.  Iowa Mesonet ASOS     KRHP / KAND / KAVL            (~5 min lag, no key)
  3.  Open-Meteo forecast   best_match w/ past_days       (~1 hr lag,  no key)
  4.  NWS grid QPE          forecastGridData reuse        (~15 min lag, no key)
  5.  ERA5 archive          last resort                   (1-2 day lag, no key)
"""

import math
import json
import time
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

import requests
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

log = logging.getLogger("NOAH.precip")

# ═══════════════════════════════════════════════════════════════════════════════
#  1. CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
ET_TZ    = ZoneInfo("America/New_York")
UTC_TZ   = ZoneInfo("UTC")
REQ_TIMEOUT = 12

# ── Tier 1: deployed sensor endpoints (fill when sensors are live) ────────────
REALTIME_RAIN_STATIONS = [
    {"name": "Primary Basin Rain",   "type": "custom_json",    "weight": 1.0,
     "current_url": "", "history_url": ""},
    {"name": "Secondary Basin Rain", "type": "custom_json",    "weight": 1.0,
     "current_url": "", "history_url": ""},
    {"name": "Cullowhee PWS",        "type": "weathercom_pws", "weight": 1.0,
     "station_id": "KNCCULLO7",  "api_key": ""},
    {"name": "Sylva PWS",            "type": "weathercom_pws", "weight": 1.0,
     "station_id": "KNCSYLVA86", "api_key": ""},
]

# ── Tier 1.5: NWS Observed Data — Jackson County Airport K24A ────────────────
# Official AWOS III P/T observations, ~1 mile from WCU/watershed.
# Same api.weather.gov endpoint NOAH already uses for alerts — no key needed.
# Hourly precip measured directly, updated every 20 min. Most authoritative
# local observed precip available without any credentials.

# ── Tier 2: AWOS/ASOS stations — Jackson County Airport primary ───────────────
# 24A = Jackson County Airport, Cullowhee (~1 mi from WCU, AWOS III P/T w/ precip)
# RHP = Andrews-Murphy Airport, Andrews NC (~18 mi, precip sensor unreliable)
# AVL = Asheville Regional (~35 mi, reliable fallback)
ASOS_STATIONS = ["24A", "RHP", "AVL"]

# ── Watershed constants ───────────────────────────────────────────────────────
# ── Southern Blue Ridge soil hydraulic properties ────────────────────────────
# Source: SSURGO Map Units for Jackson County NC (FIPS 37099)
# Dominant series in Cullowhee Creek watershed:
#   Evard-Cowee complex (45%) — fine-loamy, mixed, mesic Typic Hapludults
#   Tuckasegee (20%)          — fine-loamy, mixed, mesic Fluventic Humudepts
#   Saunook (15%)             — fine-loamy, mixed, mesic Humic Hapludults
#   Codorus-Rosman (10%)      — floodplain Inceptisols / Entisols
#
# Values are depth-weighted averages for 0-28 cm profile (top two ERA5 layers)
# SSURGO Ksat, theta_s, theta_fc, theta_wp from Web Soil Survey bulk query.
# These replace the prior generic loam values which underestimated porosity.
SOIL_POROSITY  = 0.485   # theta_s  — saturated VWC (m³/m³); SSURGO wtd avg
SOIL_FIELD_CAP = 0.310   # theta_fc — field capacity; ~33 kPa matric potential
SOIL_WILT_PT   = 0.138   # theta_wp — wilting point; ~1500 kPa matric potential
# Available water capacity: 0.310 - 0.138 = 0.172 m³/m³  (SSURGO: 0.16-0.19)
# Total pore space in 0-28 cm profile: 0.485 × 11.024 in = 5.35 in

# ── Hydraulic geometry — Henson et al. (2014) Ecoregion 66 regional curves ────
# Qbkf = 57.8 * DA^0.779   Dbkf = 1.26 * DA^0.325
# Rating curve: D = (Q / A)^(1/B)  →  A recomputed so D(Qbkf) = Dbkf exactly.
# B exponents (channel shape) unchanged; option (c) — regional equations used
# until site-specific cross-section surveys are available for Cullowhee Creek.
# ── Reference gage: USGS 03508050 Tuckasegee River at SR 1172 nr Cullowhee ────
# DA=147 sq mi, elevation 2111 ft. No gage exists on Cullowhee Creek itself.
# Baseflow derived by drainage-area ratio scaling from Tuckasegee 25th-pctile
# low-flow discharge (234 cfs / 147 sq mi = 1.592 cfs/sq mi).
# Recession coefficient K=0.046/day from USGS StreamStats NC Blue Ridge RI=50d.
USGS_TUCK_SITE  = "03508050"   # live reference gage — added to NOAH display
USGS_TUCK_DA    = 147.0        # sq mi

# CN values: NLCD 2019 land cover × SSURGO HSG C (Evard-Cowee Ultisols)
#   Lower: 73% forest(C=70) + 15% pasture(C=79) + 8% developed(C=85) + 4% water = 73.7→72
#   Upper: 85% forest(C=70) + 10% pasture(C=79) + 4% developed(C=85) + 1% water = 71.8→70
#   Prior values (68/62) underestimated runoff by assuming HSG B soils.
# Tc values from TR-55 velocity method for forested mountain channel (0.58 ft/s):
#   Consistent with stored values — keeping 2.5h / 1.2h.
LO_AREA_ACRES = 6200;  LO_DA_SQMI = 9.688;  LO_TC_HRS = 2.5;   LO_CN_II = 72
LO_RATING_A   = 36.4;  LO_RATING_B = 2.30;  LO_BASEFLOW = 15.4  # 1.592 * 9.688
LO_BANKFULL   = 2.64;  LO_BANKFULL_Q = 339.0   # Henson 2014: 57.8*9.688^0.779

UP_AREA_ACRES = 2480;  UP_DA_SQMI = 3.875;  UP_TC_HRS = 1.2;   UP_CN_II = 70
UP_RATING_A   = 39.1;  UP_RATING_B = 2.15;  UP_BASEFLOW = 6.2   # 1.592 * 3.875
UP_BANKFULL   = 1.96;  UP_BANKFULL_Q = 166.0   # Henson 2014: 57.8*3.875^0.779

RECESSION_K     = 0.046   # per day — USGS StreamStats NC Blue Ridge RI=50d

FLOOD_TRAVEL_MIN = 65

_USDM_IMPLIED_SAT = {1: 55.0, 2: 40.0, 3: 27.0, 4: 17.0, 5: 8.0}
# _USDM_CEILING removed — was incorrectly hard-capping saturation during
# active storms. USDM drought classifications reflect prior-week conditions
# and must not suppress soil saturation estimates during flood events.

_TR55_IAPRATIO = [0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50]
_TR55_C0 = [2.55323, 2.23537, 2.10304, 2.18219, 2.17339, 2.16251, 2.14583]
_TR55_C1 = [-0.61512,-0.50537,-0.51488,-0.50258,-0.48985,-0.47856,-0.46772]
_TR55_C2 = [-0.16403,-0.11657,-0.08648,-0.09057,-0.09084,-0.09303,-0.09373]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. STYLING
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');
html, body, .stApp { background-color:#04090F; color:#E0E8F0; font-family:'Rajdhani',sans-serif; }
.site-header { border-left:6px solid #0077FF; padding:14px 22px; margin-bottom:20px;
               background:rgba(0,100,200,0.07); border-radius:0 8px 8px 0; }
.site-title  { font-size:2.4em; font-weight:700; color:#FFFFFF; margin:0; letter-spacing:2px; }
.site-sub    { font-family:'Share Tech Mono',monospace; font-size:0.75em; color:#5AACD0; margin-top:4px; }
.panel       { background:rgba(8,16,28,0.88); border:1px solid rgba(0,119,255,0.18);
               border-radius:10px; padding:18px 20px; margin-bottom:16px; }
.panel-title { font-family:'Share Tech Mono',monospace; font-size:0.78em; color:#0077FF;
               text-transform:uppercase; letter-spacing:3px;
               border-bottom:1px solid rgba(0,119,255,0.18); padding-bottom:8px; margin-bottom:14px; }
.upper-panel { background:rgba(8,16,28,0.88); border:1px solid rgba(0,180,100,0.25);
               border-radius:10px; padding:18px 20px; margin-bottom:16px; }
.upper-title { font-family:'Share Tech Mono',monospace; font-size:0.78em; color:#00CC77;
               text-transform:uppercase; letter-spacing:3px;
               border-bottom:1px solid rgba(0,180,100,0.25); padding-bottom:8px; margin-bottom:14px; }
.lower-panel { background:rgba(8,16,28,0.88); border:1px solid rgba(0,119,255,0.25);
               border-radius:10px; padding:18px 20px; margin-bottom:16px; }
.lower-title { font-family:'Share Tech Mono',monospace; font-size:0.78em; color:#0099FF;
               text-transform:uppercase; letter-spacing:3px;
               border-bottom:1px solid rgba(0,119,255,0.25); padding-bottom:8px; margin-bottom:14px; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. FORECAST ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def _hours_ahead(target_dt, now_dt):
    return (target_dt - now_dt).total_seconds() / 3600.0

def _choose_bucket(lead_hours):
    return "short_range" if lead_hours <= 18 else "mid_range" if lead_hours <= 48 else "extended"

def _weighted_merge(a, b, wa, wb):
    t = wa + wb
    return {"time": a["time"],
            "temp_f":   (a["temp_f"]  * wa + b["temp_f"]  * wb) / t,
            "qpf_in":   (a["qpf_in"] * wa + b["qpf_in"] * wb) / t,
            "pop":      (a["pop"]    * wa + b["pop"]    * wb) / t,
            "icon_txt": b.get("icon_txt", a.get("icon_txt", ""))}

@st.cache_data(ttl=900)
def _fetch_short_range_hourly():
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "temperature_2m,precipitation,precipitation_probability",
            "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
            "forecast_days": 3,
        }, timeout=15).json()
        out = []
        for i, t in enumerate(r["hourly"]["time"]):
            try:
                ts = datetime.fromisoformat(t).replace(tzinfo=UTC_TZ).astimezone(ET_TZ)
                out.append({"time": ts,
                            "temp_f":   float(r["hourly"]["temperature_2m"][i] or 0),
                            "qpf_in":   float(r["hourly"]["precipitation"][i]   or 0),
                            "pop":      float((r["hourly"].get("precipitation_probability") or [0]*len(r["hourly"]["time"]))[i] or 0),
                            "icon_txt": ""})
            except Exception:
                continue
        return out
    except Exception:
        return []

@st.cache_data(ttl=1800)
def _fetch_daily_forecast():
    """Fetches NWS grid; also stores grid props in session_state for QPE reuse."""
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0"}
        pts  = requests.get(f"https://api.weather.gov/points/{LAT},{LON}",
                            headers=hdrs, timeout=10).json()["properties"]
        periods = requests.get(pts["forecast"], headers=hdrs, timeout=10
                               ).json()["properties"]["periods"]
        grid = requests.get(pts["forecastGridData"], headers=hdrs, timeout=15
                            ).json()["properties"]
        try:
            st.session_state["_nws_grid_props"] = grid
        except Exception:
            pass

        qpf_by_date = defaultdict(float)
        for e in grid.get("quantitativePrecipitation", {}).get("values", []):
            vt = e["validTime"].split("/")[0]
            try:
                d = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                qpf_by_date[d] += float(e["value"] or 0) * 0.0393701
            except Exception:
                pass

        temp_by_date = {}
        for e in grid.get("maxTemperature", {}).get("values", []):
            vt, val = e["validTime"].split("/")[0], e["value"]
            if val is None:
                continue
            try:
                d  = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                tf = float(val) * 9 / 5 + 32
                if d not in temp_by_date or tf > temp_by_date[d]:
                    temp_by_date[d] = tf
            except Exception:
                pass

        out, seen = [], set()
        for p in periods:
            if not p.get("isDaytime", False):
                continue
            try:
                dt   = datetime.fromisoformat(p["startTime"]).astimezone(ET_TZ)
                dkey = dt.strftime("%Y-%m-%d")
                if dkey in seen:
                    continue
                seen.add(dkey)
                out.append({"time":       dt.replace(hour=12, minute=0, second=0, microsecond=0),
                            "date":       dkey,
                            "short_name": dt.strftime("%a").upper(),
                            "date_label": dt.strftime("%m/%d"),
                            "temp_f":     round(float(temp_by_date.get(dkey, p["temperature"])), 1),
                            "qpf_in":     round(float(qpf_by_date.get(dkey, 0.0)), 2),
                            "pop":        round(float((p.get("probabilityOfPrecipitation") or {}).get("value") or 0), 1),
                            "icon_txt":   str(p.get("shortForecast", ""))})
            except Exception:
                continue
        return out[:7]
    except Exception:
        return []

def _qpf_next_hours(n_hours=6):
    """
    Sum QPF for the next n_hours from the hourly forecast.
    This avoids double-counting rainfall already observed in rain_24h.
    TR-55 needs only the REMAINING storm precipitation for the forecast
    horizon, not the full 24h QPF window which overwraps observed rain.
    Returns inches.
    """
    hourly = _fetch_short_range_hourly()
    now_et = datetime.now(ET_TZ)
    total  = 0.0
    for r in hourly:
        lead = _hours_ahead(r["time"], now_et)
        if 0 < lead <= n_hours:
            total += float(r["qpf_in"] or 0.0)
    return round(total, 3)


def _build_unified_forecast():
    now_et = datetime.now(ET_TZ)
    hourly = _fetch_short_range_hourly()
    daily  = _fetch_daily_forecast()

    hourly_by_day = defaultdict(list)
    for r in hourly:
        lead = _hours_ahead(r["time"], now_et)
        if -3 <= lead <= 60:
            hourly_by_day[r["time"].strftime("%Y-%m-%d")].append(r)

    short_daily = {}
    for dkey, rows in hourly_by_day.items():
        dt = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        short_daily[dkey] = {"time": dt, "date": dkey,
                             "short_name": dt.strftime("%a").upper(),
                             "date_label": dt.strftime("%m/%d"),
                             "temp_f": round(max(r["temp_f"] for r in rows), 1),
                             "qpf_in": round(sum(r["qpf_in"] for r in rows), 2),
                             "pop":    round(max(r["pop"]    for r in rows), 1),
                             "icon_txt": ""}

    daily_map = {r["date"]: r for r in daily}
    unified   = []
    for dkey in sorted(set(short_daily) | set(daily_map)):
        target    = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        lead      = _hours_ahead(target, now_et)
        short_rec = short_daily.get(dkey)
        daily_rec = daily_map.get(dkey)
        if 12 <= lead <= 18 and short_rec and daily_rec:
            wb = (lead - 12) / 6.0
            merged = _weighted_merge(short_rec, daily_rec, 1.0 - wb, wb)
            merged.update({"date": dkey, "short_name": target.strftime("%a").upper(),
                           "date_label": target.strftime("%m/%d")})
            unified.append(merged)
        elif _choose_bucket(lead) == "short_range" and short_rec:
            unified.append(short_rec)
        elif daily_rec:
            unified.append(daily_rec)
        elif short_rec:
            unified.append(short_rec)
    return unified[:7]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. PRECIPITATION — MULTI-SOURCE FALLBACK CHAIN
# ═══════════════════════════════════════════════════════════════════════════════

def _cp(x, lo=0.0, hi=50.0):
    """Clean precip value — return float in [lo, hi] or None."""
    try:
        v = float(x)
        return None if (math.isnan(v) or v < lo or v > hi) else v
    except Exception:
        return None

def _sp(pairs, max_age_hr):
    """Sum (age_hr, precip_in) pairs where 0 <= age_hr <= max_age_hr."""
    return round(sum(p for a, p in pairs if 0 <= a <= max_age_hr), 3)


# ── Tier 1.5: NWS K24A Observed Hourly Precip (~20 min lag, no key) ──────────

@st.cache_data(ttl=1200)   # 20-min cache matches AWOS update cadence
def _fetch_nws_k24a() -> dict:
    """
    Pull up to 168 hourly observations from NWS station K24A
    (Jackson County Airport, Cullowhee NC — AWOS III P/T with precip sensor).

    Endpoint: GET https://api.weather.gov/stations/K24A/observations?limit=168
    No authentication required. Same api.weather.gov domain NOAH already uses.

    NWS observation fields:
      precipitationLastHour   — mm measured in the past hour
      precipitationLast3Hours — mm (reported at 3h synoptic times)
      precipitationLast6Hours — mm (reported at 6h synoptic times)
      temperature.value       — degrees C
      windSpeed.value         — km/h
      relativeHumidity.value  — %

    Strategy: sum precipitationLastHour across sliding windows to build
    rolling 1h / 24h / 3d / 5d / 7d totals. When 1h readings are null
    (station didn't report that hour), we skip without penalising the sum.
    """
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0 (Nautilus Technologies)"}
        r    = requests.get(
            "https://api.weather.gov/stations/K24A/observations",
            params={"limit": 288},   # 288 = ~12 days of hourly obs
            headers=hdrs,
            timeout=REQ_TIMEOUT,
        ).json()

        features = r.get("features", [])
        if not features:
            return {"ok": False, "source": "NWS-K24A", "reason": "no features"}

        now_et = datetime.now(ET_TZ)
        pairs  = []   # (age_hr, precip_in)
        latest = {}

        for feat in features:
            props = feat.get("properties", {})
            ts_str = props.get("timestamp", "")
            if not ts_str:
                continue
            try:
                ts_et  = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(ET_TZ)
                age_hr = (now_et - ts_et).total_seconds() / 3600.0
                if age_hr < 0:
                    continue
            except Exception:
                continue

            # precipitationLastHour is the primary field; mm → inches
            p_mm = (props.get("precipitationLastHour") or {}).get("value")
            if p_mm is not None:
                p_in = _cp(float(p_mm) * 0.0393701, 0, 5)
                if p_in is not None:
                    pairs.append((age_hr, p_in))

            # Grab latest atmospheric readings from most recent observation
            if not latest and age_hr < 2:
                t_c   = (props.get("temperature")       or {}).get("value")
                w_kph = (props.get("windSpeed")         or {}).get("value")
                h_pct = (props.get("relativeHumidity")  or {}).get("value")
                p_hpa = (props.get("seaLevelPressure")  or {}).get("value")
                gust_kph = (props.get("windGust")       or {}).get("value")
                latest = {
                    "tempf":       round(float(t_c) * 9/5 + 32, 1) if t_c is not None else None,
                    "windspeedmph":round(float(w_kph) * 0.621371, 1) if w_kph is not None else None,
                    "windgustmph": round(float(gust_kph) * 0.621371, 1) if gust_kph is not None else None,
                    "humidity":    round(float(h_pct), 1) if h_pct is not None else None,
                    "baromrelin":  round(float(p_hpa) * 0.02953, 2) if p_hpa is not None else None,
                }

        if not pairs:
            return {"ok": False, "source": "NWS-K24A", "reason": "no precip observations"}

        # Quality gate: ≥12 obs with all zeros = sensor likely not reporting
        n_obs  = len(pairs)
        r7     = _sp(pairs, 168)
        prcp_ok = not (n_obs >= 12 and r7 == 0.0)

        return {
            "ok":              True,
            "source":          "NWS-K24A",
            "rain_rate_in_hr": _sp(pairs, 1),
            "rain_1h_in":      _sp(pairs, 1)   if prcp_ok else None,
            "rain_24h_in":     _sp(pairs, 24)  if prcp_ok else None,
            "rain_3d_in":      _sp(pairs, 72)  if prcp_ok else None,
            "rain_5d_in":      _sp(pairs, 120) if prcp_ok else None,
            "rain_7d_in":      r7              if prcp_ok else None,
            "rain_14d_in":     None,
            "snow_7d_in":      None,
            **latest,
        }
    except Exception as exc:
        return {"ok": False, "source": "NWS-K24A", "reason": str(exc)}


def _fetch_ambient_weather() -> dict:
    """Thin wrapper — delegates to NWS K24A which replaced the AW approach."""
    return _fetch_nws_k24a()


# ── Tier 2: Iowa Mesonet ASOS (no key, ~5 min lag) ────────────────────────────

@st.cache_data(ttl=300)
def _fetch_asos(station="RHP"):
    try:
        now_utc   = datetime.now(UTC_TZ)
        start_utc = now_utc - timedelta(days=7, hours=2)
        r = requests.get("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py",
                         params={"station": station, "data": "p01i",
                                 "year1": start_utc.strftime("%Y"), "month1": start_utc.strftime("%m"),
                                 "day1":  start_utc.strftime("%d"), "hour1":  start_utc.strftime("%H"),
                                 "minute1": "00",
                                 "year2": now_utc.strftime("%Y"),   "month2": now_utc.strftime("%m"),
                                 "day2":  now_utc.strftime("%d"),   "hour2":  now_utc.strftime("%H"),
                                 "minute2": "00",
                                 "tz": "UTC", "format": "onlycomma", "latlon": "no",
                                 "missing": "M", "trace": "T", "direct": "no", "report_type": "3"},
                         timeout=REQ_TIMEOUT)
        r.raise_for_status()
        lines  = [l for l in r.text.strip().splitlines()
                  if l and not l.startswith("#") and not l.lower().startswith("station")]
        if not lines:
            return {"ok": False, "source": f"ASOS-{station}"}
        now_et = datetime.now(ET_TZ)
        pairs  = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < 3:
                continue
            raw_p = parts[2].strip()
            if raw_p.upper() == "T":
                raw_p = "0.001"
            p = _cp(raw_p, 0, 5)
            if p is None:
                continue
            try:
                obs = datetime.strptime(parts[1].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=UTC_TZ)
                pairs.append(((now_et - obs.astimezone(ET_TZ)).total_seconds() / 3600.0, p))
            except Exception:
                continue
        if not pairs:
            return {"ok": False, "source": f"ASOS-{station}"}
        # Quality gate: many small ASOS sites (e.g. RHP) have no rain gauge.
        # If we have 50+ hourly rows and the entire 7-day total is still 0.0,
        # the precip sensor is broken — return None so downstream sources win.
        r7        = _sp(pairs, 168)
        r24       = _sp(pairs, 24)
        n_obs     = len(pairs)
        prcp_ok   = not (n_obs >= 50 and r7 == 0.0)
        return {"ok": True, "source": f"ASOS-{station}",
                "rain_rate_in_hr": None,
                "rain_1h_in":  _sp(pairs, 1)   if prcp_ok else None,
                "rain_24h_in": r24              if prcp_ok else None,
                "rain_3d_in":  _sp(pairs, 72)  if prcp_ok else None,
                "rain_5d_in":  _sp(pairs, 120) if prcp_ok else None,
                "rain_7d_in":  r7              if prcp_ok else None,
                "rain_14d_in": None, "snow_7d_in": None,
                "_prcp_ok": prcp_ok, "_n_obs": n_obs}
    except Exception as exc:
        return {"ok": False, "source": f"ASOS-{station}", "reason": str(exc)}

def _fetch_asos_best():
    for s in ASOS_STATIONS:
        r = _fetch_asos(s)
        if r.get("ok"):
            return r
    return {"ok": False, "source": "ASOS-all-failed"}


# ── Tier 3: Open-Meteo forecast model w/ past_days (~1 hr lag) ────────────────

@st.cache_data(ttl=600)
def _fetch_openmeteo_recent():
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "precipitation,snowfall",
            "precipitation_unit": "inch",
            "past_days": 14, "forecast_days": 1, "models": "best_match",
        }, timeout=REQ_TIMEOUT).json()

        times    = r["hourly"]["time"]
        precip_h = r["hourly"].get("precipitation", [])
        snow_h   = r["hourly"].get("snowfall", [0] * len(times))
        now_et   = datetime.now(ET_TZ)
        pairs, snow_pairs = [], []

        for i, t in enumerate(times):
            try:
                dt_utc = datetime.fromisoformat(t).replace(tzinfo=UTC_TZ)
                age_hr = (now_et - dt_utc.astimezone(ET_TZ)).total_seconds() / 3600.0
                if age_hr < 0:
                    continue
            except Exception:
                continue
            p = (_cp(precip_h[i] if i < len(precip_h) else None, 0, 5) or 0.0)
            s = (_cp(snow_h[i]   if i < len(snow_h)   else None, 0, 30) or 0.0) * 0.0393701
            pairs.append((age_hr, p))
            snow_pairs.append((age_hr, s))

        if not pairs:
            return {"ok": False, "source": "OpenMeteo-forecast"}
        return {"ok": True, "source": "OpenMeteo-forecast",
                "rain_rate_in_hr": None,
                "rain_1h_in":  _sp(pairs, 1),   "rain_24h_in": _sp(pairs, 24),
                "rain_3d_in":  _sp(pairs, 72),  "rain_5d_in":  _sp(pairs, 120),
                "rain_7d_in":  _sp(pairs, 168), "rain_14d_in": _sp(pairs, 336),
                "snow_7d_in":  _sp(snow_pairs, 168)}
    except Exception as exc:
        return {"ok": False, "source": "OpenMeteo-forecast", "reason": str(exc)}


# ── Tier 4: NWS forecastGridData QPE (already fetched — free reuse) ───────────

def _parse_nws_qpe(grid_props):
    try:
        now_et  = datetime.now(ET_TZ)
        qp_vals = grid_props.get("quantitativePrecipitation", {}).get("values", [])
        if not qp_vals:
            return {"ok": False, "source": "NWS-grid-QPE"}
        pairs = []
        for e in qp_vals:
            try:
                vt_str, dur_str = e["validTime"].split("/")
                dt_et   = datetime.fromisoformat(vt_str).astimezone(ET_TZ)
                dur_hrs = float(dur_str[2:-1]) if dur_str.startswith("PT") and dur_str.endswith("H") else 24.0
                val_mm  = e.get("value")
                if val_mm is None:
                    continue
                hrly_in = float(val_mm) * 0.0393701 / max(dur_hrs, 1.0)
                for h in range(int(dur_hrs)):
                    age_hr = (now_et - (dt_et + timedelta(hours=h))).total_seconds() / 3600.0
                    if age_hr >= 0:
                        pairs.append((age_hr, hrly_in))
            except Exception:
                continue
        if not pairs:
            return {"ok": False, "source": "NWS-grid-QPE"}
        return {"ok": True, "source": "NWS-grid-QPE",
                "rain_rate_in_hr": None,
                "rain_1h_in":  _sp(pairs, 1),   "rain_24h_in": _sp(pairs, 24),
                "rain_3d_in":  _sp(pairs, 72),  "rain_5d_in":  _sp(pairs, 120),
                "rain_7d_in":  _sp(pairs, 168), "rain_14d_in": _sp(pairs, 336),
                "snow_7d_in":  None}
    except Exception:
        return {"ok": False, "source": "NWS-grid-QPE"}


# ── Tier 5: ERA5 archive (last resort, 1-2 day lag) ───────────────────────────

@st.cache_data(ttl=3600)
def _fetch_era5():
    try:
        end_dt   = date.today()
        start_dt = end_dt - timedelta(days=14)
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "precipitation,snowfall",
            "precipitation_unit": "inch", "models": "era5_land",
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date":   end_dt.strftime("%Y-%m-%d"),
        }, timeout=15).json()

        times    = r["hourly"]["time"]
        precip_h = r["hourly"].get("precipitation", [])
        snow_h   = r["hourly"].get("snowfall", [0] * len(times))
        now_et   = datetime.now(ET_TZ)
        pairs, snow_pairs = [], []
        for i, t in enumerate(times):
            try:
                dt_utc = datetime.fromisoformat(t).replace(tzinfo=UTC_TZ)
                age_hr = (now_et - dt_utc.astimezone(ET_TZ)).total_seconds() / 3600.0
                if age_hr < 0:
                    continue
            except Exception:
                continue
            p = (_cp(precip_h[i] if i < len(precip_h) else None, 0, 5) or 0.0)
            s = (_cp(snow_h[i]   if i < len(snow_h)   else None, 0, 30) or 0.0) * 0.0393701
            pairs.append((age_hr, p))
            snow_pairs.append((age_hr, s))
        if not pairs:
            raise ValueError("empty")
        return {"ok": True, "source": "ERA5-archive",
                "rain_rate_in_hr": None,
                "rain_1h_in":  _sp(pairs, 1),   "rain_24h_in": _sp(pairs, 24),
                "rain_3d_in":  _sp(pairs, 72),  "rain_5d_in":  _sp(pairs, 120),
                "rain_7d_in":  _sp(pairs, 168), "rain_14d_in": _sp(pairs, 336),
                "snow_7d_in":  _sp(snow_pairs, 168)}
    except Exception:
        return {"ok": False, "source": "ERA5-archive",
                "rain_rate_in_hr": None,
                "rain_1h_in": 0.0, "rain_24h_in": 0.0, "rain_3d_in": 0.0,
                "rain_5d_in": 0.5, "rain_7d_in":  0.5, "rain_14d_in": 2.0,
                "snow_7d_in": 0.0}


# ── Orchestrator ──────────────────────────────────────────────────────────────

def _fill(primary, secondary):
    """
    Merge two precip dicts.  Strategy:
      - rain_rate_in_hr : primary wins (most real-time source is already first)
      - all rain totals  : take the MAX across primary and secondary.
                          A broken sensor (0.0) must never beat a working one.
    """
    out = dict(primary)
    # Rain rate: fill None only — instantaneous reading from nearest source wins
    if out.get("rain_rate_in_hr") is None and secondary.get("rain_rate_in_hr") is not None:
        out["rain_rate_in_hr"] = secondary["rain_rate_in_hr"]
    # Accumulation totals: max wins — broken-zero sensor can't suppress real rain
    for k in ["rain_1h_in","rain_24h_in","rain_3d_in",
              "rain_5d_in","rain_7d_in","rain_14d_in","snow_7d_in"]:
        pv = out.get(k)
        sv = secondary.get(k)
        if pv is None and sv is not None:
            out[k] = sv
        elif pv is not None and sv is not None:
            out[k] = max(pv, sv)   # higher credible value always wins
    return out

def fetch_precip_best(nws_grid_props=None):
    results, best = [], None

    # 1.5 — Ambient Weather
    aw = _fetch_ambient_weather()
    if aw.get("ok"):
        results.append(aw); best = aw

    # 2 — ASOS
    asos = _fetch_asos_best()
    if asos.get("ok"):
        results.append(asos)
        best = _fill(best, asos) if best else asos

    # 3 — Open-Meteo forecast model
    om = _fetch_openmeteo_recent()
    if om.get("ok"):
        results.append(om)
        best = _fill(best, om) if best else om

    # 4 — NWS grid QPE (free reuse)
    if nws_grid_props:
        nws = _parse_nws_qpe(nws_grid_props)
        if nws.get("ok"):
            results.append(nws)
            best = _fill(best, nws) if best else nws

    # 5 — ERA5 archive (last resort)
    if best is None or best.get("rain_7d_in") is None:
        era5 = _fetch_era5()
        results.append(era5)
        best = _fill(best, era5) if best else era5

    if best is None:
        best = {"ok": False, "source": "ALL-FAILED",
                "rain_rate_in_hr": None, "rain_1h_in": 0.0, "rain_24h_in": 0.0,
                "rain_3d_in": 0.0, "rain_5d_in": 0.5, "rain_7d_in": 0.5,
                "rain_14d_in": 2.0, "snow_7d_in": 0.0}

    for k in ["rain_rate_in_hr","rain_1h_in","rain_24h_in","rain_3d_in",
              "rain_5d_in","rain_7d_in","rain_14d_in","snow_7d_in"]:
        if best.get(k) is None:
            best[k] = 0.0

    best["ok"]      = True
    best["sources"] = [r["source"] for r in results if r.get("ok")]
    return best

def _precip_badge(station_rain, backup):
    if station_rain.get("ok"):
        return f"{station_rain['count']} LIVE PWS", "#00FF9C"
    src = backup.get("source", "")
    if "NWS-K24A"       in src: return "NWS K24A OBSERVED",      "#00FF9C"
    if "AmbientWeather" in src: return "AMBIENT WEATHER PWS",    "#00FF9C"
    if "ASOS"           in src: return f"ASOS ({src.split('-')[-1]})", "#00FF9C"
    if "OpenMeteo"      in src: return "OPEN-METEO FCST MODEL",  "#FFD700"
    if "NWS"            in src: return "NWS GRID QPE",           "#FFD700"
    if "ERA5"           in src: return "ERA5 ARCHIVE ⚠ LAGGED",  "#FF3333"
    return "SOURCE UNKNOWN", "#FF8800"


# ═══════════════════════════════════════════════════════════════════════════════
#  5. ADDITIONAL DATA SOURCES
# ═══════════════════════════════════════════════════════════════════════════════

# ── USGS 03508050: Tuckasegee River at SR 1172 nr Cullowhee (live reference) ──

@st.cache_data(ttl=300)
def fetch_usgs_tuck_gage() -> dict:
    """
    Live discharge and gage height from USGS 03508050 —
    Tuckasegee River at SR 1172 near Cullowhee, NC.

    This is the only USGS gage near Cullowhee Creek. No dedicated gage
    exists on Cullowhee Creek itself. The Tuckasegee at this location has
    DA=147 sq mi; Cullowhee Creek is a tributary ~6.6% of that area.

    Drainage-area scaling: Q_cullowhee ≈ Q_tuck × (9.688 / 147)
    Used in NOAH as:
      1. Live reference display (Panel 8 — Tuckasegee Reference Gage)
      2. Sanity check on modeled Cullowhee Creek flows

    USGS Instantaneous Values API — no authentication required.
    """
    try:
        r = requests.get(
            "https://waterservices.usgs.gov/nwis/iv/",
            params={
                "sites":       USGS_TUCK_SITE,
                "parameterCd": "00060,00065",   # discharge (cfs) + gage height (ft)
                "format":      "json",
                "siteStatus":  "active",
            },
            headers={"User-Agent": "NOAH-FloodWarning/1.0 (Nautilus Technologies)"},
            timeout=REQ_TIMEOUT,
        ).json()

        ts_list = r.get("value", {}).get("timeSeries", [])
        out = {"ok": False, "site": USGS_TUCK_SITE}

        for ts in ts_list:
            var_code = ts.get("variable", {}).get("variableCode", [{}])[0].get("value", "")
            values   = ts.get("values", [{}])[0].get("value", [])
            if not values:
                continue
            latest = values[-1]
            val    = _cp(latest.get("value"), -999, 999999)
            if val is None or val < 0:
                continue
            dt_str = latest.get("dateTime", "")
            try:
                obs_et = datetime.fromisoformat(
                    dt_str.replace("Z", "+00:00")).astimezone(ET_TZ)
                age_min = (datetime.now(ET_TZ) - obs_et).total_seconds() / 60.0
            except Exception:
                age_min = 999

            if var_code == "00060":
                out["discharge_cfs"]    = round(val, 1)
                out["discharge_age_min"]= round(age_min, 0)
                # Scale to Cullowhee Creek by drainage area ratio
                out["cullowhee_scaled_cfs"] = round(val * (LO_DA_SQMI / USGS_TUCK_DA), 1)
            elif var_code == "00065":
                out["gage_height_ft"]   = round(val, 2)

        if out.get("discharge_cfs") is not None:
            out["ok"] = True
        return out
    except Exception as exc:
        return {"ok": False, "site": USGS_TUCK_SITE, "reason": str(exc)}


@st.cache_data(ttl=300)
def fetch_current_conditions():
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                       "wind_direction_10m,surface_pressure,precipitation,weather_code,wind_gusts_10m",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
            "precipitation_unit": "inch", "forecast_days": 1,
        }, timeout=10).json()["current"]
        return {"ok": True,
                "temp":      round(float(r.get("temperature_2m", 50)), 1),
                "hum":       round(float(r.get("relative_humidity_2m", 50)), 1),
                "wind":      round(float(r.get("wind_speed_10m", 0)), 1),
                "wind_gust": round(float(r.get("wind_gusts_10m", 0)), 1),
                "wind_dir":  round(float(r.get("wind_direction_10m", 0)), 1),
                "press":     round(r.get("surface_pressure", 1013.25) * 0.02953, 2),
                "precip":    round(float(r.get("precipitation", 0)), 1),
                "wcode":     r.get("weather_code", 0)}
    except Exception:
        return {"ok": False, "temp": 50.0, "hum": 50.0, "wind": 0.0,
                "wind_gust": 0.0, "wind_dir": 0.0, "press": 29.92, "precip": 0.0, "wcode": 0}

@st.cache_data(ttl=600)   # 10-min cache — forecast model updates hourly
def fetch_era5_soil_moisture():
    """
    Soil moisture from Open-Meteo FORECAST model with past_days=7.
    Uses best_match (ERA5-Land initialized, NWP-corrected forward) — ~1 hr lag
    vs. the pure ERA5 archive which lags 1-2 days.

    Layers returned (m³/m³ volumetric water content):
      soil_moisture_0_to_7cm   — surface layer  (7 cm thick)
      soil_moisture_7_to_28cm  — shallow layer  (21 cm thick)
    These are the same variable names as the archive API.
    """
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
            "past_days":     7,
            "forecast_days": 1,
            "models":        "best_match",
        }, timeout=15).json()
        times  = r["hourly"]["time"]
        sm_07  = r["hourly"]["soil_moisture_0_to_7cm"]
        sm_728 = r["hourly"]["soil_moisture_7_to_28cm"]
        now_et = datetime.now(ET_TZ)
        # Walk backward to find the most recent non-null pair that is in the past
        for i in range(len(times) - 1, -1, -1):
            if sm_07[i] is None or sm_728[i] is None:
                continue
            try:
                dt_utc = datetime.fromisoformat(times[i]).replace(tzinfo=UTC_TZ)
                if dt_utc.astimezone(ET_TZ) > now_et:
                    continue   # skip future forecast hours
            except Exception:
                continue
            return round(sm_07[i], 4), round(sm_728[i], 4), times[i], True
        return None, None, None, False
    except Exception:
        return None, None, None, False

@st.cache_data(ttl=3600)
def fetch_usdm_drought():
    try:
        end_dt   = date.today()
        start_dt = end_dt - timedelta(days=21)
        r = requests.get(
            "https://usdmdataservices.unl.edu/api/CountyStatistics/"
            "GetDroughtSeverityStatisticsByAreaPercent",
            params={"aoi": "37099",
                    "startdate": start_dt.strftime("%m/%d/%Y"),
                    "enddate":   end_dt.strftime("%m/%d/%Y"),
                    "statisticsType": "1"},
            timeout=10).json()
        if not r:
            return -1, "NO DATA", "---"
        rec      = r[-1]
        map_date = rec.get("MapDate", "")[:10]
        for level, key in [(5,"D4"),(4,"D3"),(3,"D2"),(2,"D1"),(1,"D0")]:
            if float(rec.get(key, 0) or 0) >= 25.0:
                return level, {1:"D0 ABNORMALLY DRY",2:"D1 MODERATE DROUGHT",
                               3:"D2 SEVERE DROUGHT",4:"D3 EXTREME DROUGHT",
                               5:"D4 EXCEPTIONAL DROUGHT"}[level], map_date
        return 0, "NO DROUGHT", map_date
    except Exception:
        return -1, "API UNAVAILABLE", "---"

@st.cache_data(ttl=300)
def fetch_active_alerts():
    try:
        r = requests.get("https://api.weather.gov/alerts/active",
                         params={"point": f"{LAT},{LON}"},
                         headers={"User-Agent": "NOAH-FloodWarning/1.0"},
                         timeout=10).json()
        alerts = []
        for feat in r.get("features", []):
            p = feat.get("properties", {})
            event = str(p.get("event", "")).strip()
            if not event:
                continue
            desc = " ".join(str(p.get("description","")).split())
            if len(desc) > 180:
                desc = desc[:177] + "..."
            expires_local = ""
            try:
                dt = datetime.fromisoformat(str(p.get("expires","")).replace("Z","+00:00")).astimezone(ET_TZ)
                expires_local = dt.strftime("%b %d, %I:%M %p")
            except Exception:
                pass
            alerts.append({"event": event,
                           "headline":      str(p.get("headline","")).strip(),
                           "expires_local": expires_local,
                           "description":   desc})
        rank = {"flash flood warning":5,"flood warning":5,"tornado warning":5,
                "severe thunderstorm warning":4,"flash flood watch":3,"flood watch":3,
                "wind advisory":2,"flood advisory":2,"special weather statement":1}
        alerts.sort(key=lambda a: rank.get(a["event"].lower(), 0), reverse=True)
        return alerts
    except Exception:
        return []

@st.cache_data(ttl=900)
def fetch_hwo():
    import re
    from html import escape as he
    try:
        hdrs  = {"User-Agent": "NOAH-FloodWarning/1.0"}
        graph = requests.get("https://api.weather.gov/products/types/HWO/locations/GSP",
                             headers=hdrs, timeout=10).json().get("@graph", [])
        if not graph:
            return None
        prod = requests.get(f"https://api.weather.gov/products/{graph[0]['id']}",
                            headers=hdrs, timeout=10).json()
        raw  = prod.get("productText", "")
        if not raw:
            return None
        issued_str = ""
        try:
            dt = datetime.fromisoformat(prod.get("issuanceTime","").replace("Z","+00:00")).astimezone(ET_TZ)
            issued_str = dt.strftime("%b %d, %Y  %I:%M %p ET")
        except Exception:
            pass
        raw = raw.replace("\r\n","\n").replace("\r","\n")
        m   = re.search(r"(?m)^\.(DAY|DAYS|THIS)\b", raw, re.IGNORECASE)
        if not m:
            return None
        body = raw[m.start():]
        stop = re.compile(r"(?m)(^\.(SPOTTER INFORMATION STATEMENT)|^\$\$)", re.IGNORECASE)
        sm   = stop.search(body)
        if sm:
            body = body[:sm.start()]
        parts = re.split(r"(?m)(^\.[A-Z][A-Z0-9 ]+\.\.\.)", body)
        paras, i = [], 0
        if parts and not re.match(r"^\.[A-Z]", parts[0].strip()):
            i = 1
        while i < len(parts):
            hdr = parts[i].strip()
            bdy = re.sub(r"\n{3,}", "\n\n", (parts[i+1].strip() if i+1 < len(parts) else "")).strip()
            i  += 2
            if bdy:
                paras.append({"header": he(hdr), "body": he(bdy)})
        return {"issued": issued_str, "paragraphs": paras} if paras else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  6. TIER 1 LIVE SENSOR ADAPTERS  (unchanged from original)
# ═══════════════════════════════════════════════════════════════════════════════

def _crv(x, lo=0.0, hi=50.0):
    try:
        v = float(x)
        return None if (math.isnan(v) or v < lo or v > hi) else v
    except Exception:
        return None

def _fetch_custom_json(cfg):
    cur_url = cfg.get("current_url","").strip()
    his_url = cfg.get("history_url","").strip()
    if not cur_url and not his_url:
        return {"ok": False}
    out = {"ok": False}
    try:
        if cur_url:
            rc = requests.get(cur_url, timeout=REQ_TIMEOUT).json()
            out["rain_rate_in_hr"] = _crv(rc.get("rain_rate_in_hr"), 0, 15)
            out["rain_1h_in"]      = _crv(rc.get("rain_1h_in"),      0, 15)
            out["rain_24h_in"]     = _crv(rc.get("rain_24h_in"),     0, 30)
    except Exception:
        pass
    try:
        if his_url:
            rh = requests.get(his_url, timeout=REQ_TIMEOUT).json()
            out["rain_24h_in"] = _crv(rh.get("rain_24h_in", out.get("rain_24h_in")), 0, 30)
            out["rain_3d_in"]  = _crv(rh.get("rain_3d_in"),  0, 40)
            out["rain_5d_in"]  = _crv(rh.get("rain_5d_in"),  0, 50)
            out["rain_7d_in"]  = _crv(rh.get("rain_7d_in"),  0, 60)
            out["rain_14d_in"] = _crv(rh.get("rain_14d_in"), 0, 80)
    except Exception:
        pass
    out["ok"] = any(out.get(k) is not None for k in
                    ["rain_rate_in_hr","rain_1h_in","rain_24h_in","rain_3d_in","rain_5d_in","rain_7d_in","rain_14d_in"])
    return out

def _fetch_weathercom_pws(cfg):
    sid = cfg.get("station_id","").strip()
    key = cfg.get("api_key","").strip()
    if not sid or not key:
        return {"ok": False}
    out = {"ok": False}
    try:
        obs = (requests.get("https://api.weather.com/v2/pws/observations/current",
                            params={"stationId":sid,"format":"json","units":"e",
                                    "numericPrecision":"decimal","apiKey":key},
                            timeout=REQ_TIMEOUT).json().get("observations") or [{}])[0].get("imperial", {})
        out["rain_rate_in_hr"] = _crv(obs.get("precipRate"),  0, 15)
        out["rain_1h_in"]      = _crv(obs.get("precipTotal"), 0, 15)
        out["rain_24h_in"]     = _crv(obs.get("precipTotal"), 0, 30)
    except Exception:
        pass
    try:
        rows   = requests.get("https://api.weather.com/v2/pws/observations/hourly/7day",
                              params={"stationId":sid,"format":"json","units":"e",
                                      "numericPrecision":"decimal","apiKey":key},
                              timeout=REQ_TIMEOUT).json().get("observations", [])
        now_et = datetime.now(ET_TZ)
        hourly = []
        for row in rows:
            try:
                age = (now_et - datetime.fromtimestamp(int(row["epoch"]),tz=UTC_TZ).astimezone(ET_TZ)).total_seconds()/3600.0
                if age < 0:
                    continue
                hourly.append((age, _crv(row.get("imperial",{}).get("precipTotal"),0,10) or 0.0))
            except Exception:
                continue
        if hourly:
            out["rain_24h_in"] = _crv(sum(p for a,p in hourly if a<=24),  0, 30)
            out["rain_3d_in"]  = _crv(sum(p for a,p in hourly if a<=72),  0, 40)
            out["rain_5d_in"]  = _crv(sum(p for a,p in hourly if a<=120), 0, 50)
            out["rain_7d_in"]  = _crv(sum(p for a,p in hourly if a<=168), 0, 60)
    except Exception:
        pass
    out["ok"] = any(out.get(k) is not None for k in
                    ["rain_rate_in_hr","rain_1h_in","rain_24h_in","rain_3d_in","rain_5d_in","rain_7d_in"])
    return out

@st.cache_data(ttl=300)
def fetch_realtime_stations():
    results = []
    for cfg in REALTIME_RAIN_STATIONS:
        t = cfg.get("type","").strip().lower()
        res = _fetch_custom_json(cfg) if t == "custom_json" else \
              _fetch_weathercom_pws(cfg) if t == "weathercom_pws" else {"ok": False}
        if res.get("ok"):
            res["weight"] = float(cfg.get("weight", 1.0))
            results.append(res)
    if not results:
        return {"ok": False, "count": 0}
    def wm(key):
        vals = [(r[key], r["weight"]) for r in results if r.get(key) is not None]
        if not vals:
            return None
        ws = sum(w for _,w in vals)
        return round(sum(v*w for v,w in vals)/ws, 2) if ws > 0 else None
    return {"ok": True, "count": len(results),
            "rain_rate_in_hr": wm("rain_rate_in_hr"), "rain_1h_in":  wm("rain_1h_in"),
            "rain_24h_in":     wm("rain_24h_in"),     "rain_3d_in":  wm("rain_3d_in"),
            "rain_5d_in":      wm("rain_5d_in"),      "rain_7d_in":  wm("rain_7d_in"),
            "rain_14d_in":     wm("rain_14d_in")}


# ═══════════════════════════════════════════════════════════════════════════════
#  7. HYDRO-MODELING
# ═══════════════════════════════════════════════════════════════════════════════

def calc_era5_sat_pct(sm_07, sm_728):
    sm_avg = min((min(sm_07,SOIL_POROSITY)*0.55)+(min(sm_728,SOIL_POROSITY)*0.45), SOIL_POROSITY)
    return round(min(100.0, max(0.0, (sm_avg - SOIL_WILT_PT) / (SOIL_POROSITY - SOIL_WILT_PT) * 100)), 1)

def calc_api_sat_pct(rain_5d):
    a = min(float(rain_5d), 5.0)
    if a < 0.30:   sat = 10.0 + a * 33.3
    elif a < 1.00: sat = 20.0 + (a-0.30)/0.70 * 18.0
    elif a < 2.10: sat = 38.0 + (a-1.00)/1.10 * 17.0
    elif a < 2.80: sat = 55.0 + (a-2.10)/0.70 * 13.0
    else:          sat = 68.0 + (a-2.80)/2.20 * 22.0
    return round(min(90.0, max(5.0, sat)), 1)

def calc_soil_sat_ensemble(sm_07, sm_728, sm_ok, rain_5d, usdm_level):
    """
    Weighted ensemble of three soil saturation estimators.

    Sources:
      era5_pct  — Open-Meteo forecast model volumetric water content (~1 hr lag)
      api_pct   — Antecedent Precipitation Index from observed 5-day rain total
      usdm_pct  — USDM drought classification implied saturation

    Weighting philosophy:
      - ERA5/forecast model is the most physically grounded when available
      - API is direct observed rainfall at the site — high weight always
      - USDM is a weekly drought product; useful context but NOT a ceiling.
        USDM was designed for drought monitoring, not flood prediction.
        A D0 "Abnormally Dry" classification from last week must not cap
        saturation during an active multi-hour rainfall event.

    The USDM ceiling (_USDM_CEILING) has been REMOVED. It was suppressing
    saturation estimates during exactly the storms that matter most.
    USDM only informs the ensemble weight — it never hard-caps the result.
    """
    api_pct  = calc_api_sat_pct(rain_5d)
    era5_pct = calc_era5_sat_pct(sm_07, sm_728) if (sm_ok and sm_07 is not None) else None
    # USDM: only use as a signal when drought is active (level >= 1)
    # Under no-drought (level 0 or -1) USDM adds no information
    usdm_pct = _USDM_IMPLIED_SAT.get(usdm_level) if usdm_level >= 1 else None

    # ERA5 dominant when fresh model data available; API always heavily weighted
    if usdm_level <= 0:   w_era5, w_api, w_usdm = 0.55, 0.45, 0.0
    elif usdm_level == 1: w_era5, w_api, w_usdm = 0.45, 0.45, 0.10
    elif usdm_level == 2: w_era5, w_api, w_usdm = 0.40, 0.45, 0.15
    else:                 w_era5, w_api, w_usdm = 0.35, 0.50, 0.15

    # Redistribute weight if ERA5 unavailable
    if era5_pct is None:
        w_api += w_era5
        w_era5  = 0.0
        era5_pct = api_pct   # placeholder (weight is 0, value irrelevant)

    # Redistribute weight if USDM not applicable
    if usdm_pct is None:
        w_api  += w_usdm
        w_usdm  = 0.0
        usdm_pct = api_pct   # placeholder

    sat_pct = (era5_pct * w_era5) + (api_pct * w_api) + (usdm_pct * w_usdm)
    # NO USDM CEILING — clamp only to physical limits [1, 100]
    sat_pct = round(min(100.0, max(1.0, sat_pct)), 1)

    # Stored water in inches: layer thickness × volumetric moisture
    # 0-7 cm layer  = 2.756 in depth;  7-28 cm layer = 8.268 in depth
    if sm_ok and sm_07 is not None:
        stored = round(
            (min(sm_07,  SOIL_POROSITY) * 2.756) +
            (min(sm_728, SOIL_POROSITY) * 8.268), 2)
    else:
        stored = round((sat_pct / 100.0) * (SOIL_POROSITY * 11.024), 2)

    color = "#FF3333" if sat_pct>85 else "#FF8800" if sat_pct>70 else "#FFD700" if sat_pct>50 else "#00FF9C"
    return sat_pct, stored, color

def _tr55_unit_peak(tc_hrs, ia_p):
    ia_p   = max(0.10, min(0.50, float(ia_p)))
    tc_hrs = max(0.10, min(10.0, float(tc_hrs)))
    lt     = math.log10(tc_hrs)
    tbl    = _TR55_IAPRATIO
    if   ia_p <= tbl[0]:  C0,C1,C2 = _TR55_C0[0], _TR55_C1[0], _TR55_C2[0]
    elif ia_p >= tbl[-1]: C0,C1,C2 = _TR55_C0[-1],_TR55_C1[-1],_TR55_C2[-1]
    else:
        for i in range(len(tbl)-1):
            if tbl[i] <= ia_p <= tbl[i+1]:
                t = (ia_p-tbl[i])/(tbl[i+1]-tbl[i])
                C0 = _TR55_C0[i]+t*(_TR55_C0[i+1]-_TR55_C0[i])
                C1 = _TR55_C1[i]+t*(_TR55_C1[i+1]-_TR55_C1[i])
                C2 = _TR55_C2[i]+t*(_TR55_C2[i+1]-_TR55_C2[i])
                break
    return 10.0**(C0 + C1*lt + C2*lt**2)

def model_stream(soil_sat_pct, rain_24h, qpf_24h, rain_7d,
                 da_sqmi, tc_hrs, cn_ii, baseflow, rating_a, rating_b, bankfull_q):
    if   soil_sat_pct < 30: cn_adj = max(50.0, cn_ii * 0.87)
    elif soil_sat_pct < 65: cn_adj = float(cn_ii)
    else:                   cn_adj = min(95.0, (23.0*cn_ii)/(10.0+0.13*cn_ii))
    P  = max(0.0, rain_24h + qpf_24h)
    S  = (1000.0/cn_adj) - 10.0
    Ia = 0.2 * S
    Q_runoff_in = (P-Ia)**2/(P-Ia+S) if P > Ia else 0.0
    Q_storm = (_tr55_unit_peak(tc_hrs, min(0.50,max(0.10,Ia/P))) * da_sqmi * Q_runoff_in
               if Q_runoff_in > 0 and P > 0 else 0.0)
    Q_base   = baseflow * (1.0 + (soil_sat_pct / 100.0) * 3.0)
    # Q_recess: antecedent precipitation contribution to current baseflow above normal.
    # Coefficient derived from USGS 03508050 Tuckasegee recession analysis:
    #   K = 0.046/day (StreamStats NC Blue Ridge RI=50d) × 5-day typical lag = 0.23
    #   rain_7d - rain_24h = inches of prior-week rain not counting today's event
    Q_recess = max(0.0, (rain_7d - rain_24h) * baseflow * RECESSION_K * 5.0)
    Q_total  = round(max(baseflow*0.5, min(Q_base+Q_storm+Q_recess, bankfull_q*3.0)), 1)
    depth_ft = round(max(0.20, min((Q_total/rating_a)**(1.0/rating_b), 9.0)), 2)
    return depth_ft, Q_total

def flood_threat_score(soil_sat, rain_24h, qpf_6h, pop_24h):
    """
    Composite flood threat score 0-100.

    Weights:
      40% — Soil saturation     (antecedent condition — what the ground can absorb)
      30% — Observed 24h rain   (what has already fallen — most direct flood driver)
      20% — QPF next 6h         (what is still coming)
      10% — Probability of precip (confidence in continued rainfall)

    rain_24h scaled: 1" = 30 pts, 2" = 60 pts, 3"+ = 90+ pts (caps at 100)
    qpf_6h  scaled:  0.5" = 20 pts cap (future rain is less certain)
    """
    rain_component = min(100.0, rain_24h * 30.0)
    qpf_component  = min(100.0, qpf_6h  * 40.0)
    return round(min(100.0,
        (soil_sat      * 0.40) +
        (rain_component * 0.30) +
        (qpf_component  * 0.20) +
        (pop_24h        * 0.10)
    ), 1)

def threat_meta(score):
    if score < 25: return "NORMAL",    "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45: return "ELEVATED",  "#FFFF00", "rgba(255,255,0,0.09)"
    if score < 65: return "WATCH",     "#FFD700", "rgba(255,215,0,0.09)"
    if score < 82: return "WARNING",   "#FF8800", "rgba(255,136,0,0.11)"
    return             "EMERGENCY",    "#FF3333", "rgba(255,51,51,0.14)"

def stage_status(depth_ft, bankfull_ft):
    r = depth_ft / bankfull_ft
    if r < 0.45: return "LOW FLOW",  "#00FF9C"
    if r < 0.65: return "NORMAL",    "#00FF9C"
    if r < 0.80: return "ELEVATED",  "#FFFF00"
    if r < 0.95: return "WATCH",     "#FFD700"
    return             "FLOOD",      "#FF3333"

def flow_status(q, bankfull_q):
    if q < bankfull_q*0.15: return "LOW FLOW",  "#00FF9C"
    if q < bankfull_q*0.45: return "NORMAL",    "#00FF9C"
    if q < bankfull_q*0.85: return "ELEVATED",  "#FFFF00"
    if q < bankfull_q*1.00: return "WATCH",     "#FFD700"
    return                        "FLOOD",      "#FF3333"

def forecast_icon(txt):
    t = str(txt).lower()
    if any(x in t for x in ["thunder","storm"]): return "TSTM"
    if any(x in t for x in ["snow","blizzard"]):  return "SNOW"
    if any(x in t for x in ["sleet","freezing"]): return "SLEET"
    if any(x in t for x in ["fog","haze"]):       return "FOG"
    if "shower" in t:                             return "SHWRS"
    if any(x in t for x in ["rain","drizzle"]):   return "RAIN"
    if "partly cloudy" in t:                      return "PTCLDY"
    if "mostly cloudy" in t:                      return "MSTCLDY"
    if "cloudy" in t:                             return "CLOUDY"
    if any(x in t for x in ["sunny","clear"]):    return "SUNNY"
    return "---"


# ═══════════════════════════════════════════════════════════════════════════════
#  8. UI COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def make_dial(v, t, min_v, max_v, u, c):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v,
        number={"suffix": u, "font": {"size":26,"color":"white","family":"Rajdhani"},
                "valueformat": ".1f"},
        title={"text": f"<b>{t}</b>",
               "font": {"size":13,"color":"#A0C8E0","family":"Share Tech Mono"}},
        gauge={"axis":   {"range":[min_v,max_v],"tickfont":{"size":9,"color":"#334455"}},
               "bar":    {"color":c,"thickness":0.25},
               "bgcolor":"rgba(0,0,0,0)"}))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(t=60,b=10,l=30,r=30), height=190)
    return fig

def make_stream_gauge(gid, v, min_v, max_v, unit, ranges,
                      needle_clr, status_lbl, status_clr, sub_line):
    arc_data = []
    for x in ranges:
        base = x["color"]
        try:
            pfx    = base[:base.rfind(",")+1]
            dim    = pfx + "0.18)"
            bright = pfx + "0.80)"
        except Exception:
            dim = bright = base
        arc_data.append({"r0":x["range"][0],"r1":x["range"][1],"dim":dim,"bright":bright})
    arc_js  = json.dumps(arc_data)
    osc_amp = round((max_v-min_v)*0.008, 4)
    return f"""<html><body style="background:transparent;text-align:center;
font-family:'Rajdhani',sans-serif;color:white;margin:0;padding:0;">
<canvas id="{gid}" width="260" height="150"></canvas>
<div style="color:{status_clr};font-weight:700;font-size:16px;text-transform:uppercase;letter-spacing:2px;">{status_lbl}</div>
<div style="font-size:12px;color:#7AACCC;margin-top:4px;">{sub_line}</div>
<script>
(function(){{
var canvas=document.getElementById('{gid}'),ctx=canvas.getContext('2d');
var cx=130,cy=125,r=95,TARGET={v},MIN_V={min_v},MAX_V={max_v},AMP={osc_amp};
var ARCS={arc_js},phase=Math.random()*6.283,cur=MIN_V,t0=null;
function toA(val){{return Math.PI+((val-MIN_V)/(MAX_V-MIN_V))*Math.PI;}}
function draw(ts){{
  if(!t0)t0=ts;var e=(ts-t0)/1000;
  cur+=(TARGET-cur)*0.06;
  var near=Math.abs(cur-TARGET)<AMP*3,osc=near?AMP*Math.sin(e*0.8+phase):0;
  var disp=Math.max(MIN_V,Math.min(MAX_V,cur+osc));
  ctx.clearRect(0,0,260,150);
  for(var i=0;i<ARCS.length;i++){{
    var seg=ARCS[i],active=disp>=seg.r0&&disp<=seg.r1;
    ctx.beginPath();ctx.strokeStyle=active?seg.bright:seg.dim;
    ctx.lineWidth=20;ctx.arc(cx,cy,r,toA(seg.r0),toA(seg.r1));ctx.stroke();
  }}
  var ang=toA(disp),nx=cx+r*Math.cos(ang),ny=cy+r*Math.sin(ang);
  var glow=8+4*Math.sin(e*3+phase);
  ctx.shadowColor='{needle_clr}';ctx.shadowBlur=glow;
  ctx.beginPath();ctx.strokeStyle='{needle_clr}';ctx.lineWidth=3;
  ctx.moveTo(cx,cy);ctx.lineTo(nx,ny);ctx.stroke();ctx.shadowBlur=0;
  ctx.beginPath();ctx.arc(cx,cy,6,0,6.283);ctx.fillStyle='{needle_clr}';ctx.fill();
  ctx.fillStyle='white';ctx.font='bold 20px Rajdhani';ctx.textAlign='center';
  ctx.fillText(TARGET.toFixed(2)+'{unit}',cx,cy-40);
  requestAnimationFrame(draw);
}}
requestAnimationFrame(draw);
}})();
</script></body></html>"""

def _alert_style(event_name):
    e = event_name.lower()
    if "warning" in e: return {"border":"#FF3333","text":"#FFCCCC","title":"#FF6666","bg":"rgba(255,51,51,0.10)"}
    if "watch"   in e: return {"border":"#FF8800","text":"#FFE0C2","title":"#FFB066","bg":"rgba(255,136,0,0.10)"}
    return                    {"border":"#FFD700","text":"#FFF3B0","title":"#FFE866","bg":"rgba(255,215,0,0.10)"}


# ═══════════════════════════════════════════════════════════════════════════════
#  9. DATA EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

conditions    = fetch_current_conditions()
usgs_tuck     = fetch_usgs_tuck_gage()
forecast      = _build_unified_forecast()        # also caches _nws_grid_props
station_rain  = fetch_realtime_stations()
active_alerts = fetch_active_alerts()
hwo_text      = fetch_hwo()

sm_07, sm_728, sm_ts, sm_ok       = fetch_era5_soil_moisture()
usdm_level, usdm_label, usdm_date = fetch_usdm_drought()

# Precip — full fallback chain
_nws_grid   = st.session_state.get("_nws_grid_props")
backup_rain = fetch_precip_best(nws_grid_props=_nws_grid)

# Resolve final rain values: Tier 1 sensor wins; else best-available chain
if station_rain.get("ok"):
    rain_24h  = station_rain.get("rain_24h_in")  or backup_rain["rain_24h_in"]
    rain_5d   = station_rain.get("rain_5d_in")   or backup_rain["rain_5d_in"]
    rain_7d   = station_rain.get("rain_7d_in")   or backup_rain["rain_7d_in"]
    rain_now  = station_rain.get("rain_rate_in_hr") or conditions["precip"]
else:
    rain_24h  = backup_rain["rain_24h_in"]
    rain_5d   = backup_rain["rain_5d_in"]
    rain_7d   = backup_rain["rain_7d_in"]
    rain_now  = backup_rain.get("rain_rate_in_hr") or conditions["precip"]

soil_sat, soil_stored, soil_color = calc_soil_sat_ensemble(
    sm_07, sm_728, sm_ok, rain_5d, usdm_level)

# Both sub-basins receive the same antecedent soil saturation estimate.
# TR-55 already handles sub-basin hydrologic differences through separate
# CN values (LO_CN_II=68 vs UP_CN_II=62) and Tc (2.5h vs 1.2h).
# Applying an additional scalar correction on top is double-counting.
soil_sat_lo = soil_sat
soil_sat_up = soil_sat   # identical input; model output diverges via CN/Tc

def _sc(s): return "#FF3333" if s>85 else "#FF8800" if s>70 else "#FFD700" if s>50 else "#00FF9C"
def _ss(s): return round((s/100.0)*(SOIL_POROSITY*11.024), 2)

soil_color_lo  = _sc(soil_sat_lo);  soil_stored_lo = soil_stored
soil_color_up  = _sc(soil_sat_up);  soil_stored_up = _ss(soil_sat_up)

# QPF: use only NEXT 6 hours, not full 24h window.
# rain_24h already contains observed rainfall from the past 24h.
# Adding full 24h QPF on top double-counts rainfall currently falling.
# The 6h horizon is appropriate for TR-55 event-based runoff estimation.
qpf_6h   = _qpf_next_hours(6)
qpf_24h  = qpf_6h   # alias — model_stream signature unchanged
pop_24h  = forecast[0]["pop"] if forecast else 0.0

threat             = flood_threat_score(soil_sat_lo, rain_24h, qpf_6h, pop_24h)
t_lbl, t_clr, t_bg = threat_meta(threat)

lo_depth, lo_flow = model_stream(soil_sat_lo, rain_24h, qpf_24h, rain_7d,
    LO_DA_SQMI, LO_TC_HRS, LO_CN_II, LO_BASEFLOW, LO_RATING_A, LO_RATING_B, LO_BANKFULL_Q)
up_depth, up_flow = model_stream(soil_sat_up, rain_24h, qpf_24h, rain_7d,
    UP_DA_SQMI, UP_TC_HRS, UP_CN_II, UP_BASEFLOW, UP_RATING_A, UP_RATING_B, UP_BANKFULL_Q)

for k,v in [("lo_depth",lo_depth),("lo_flow",lo_flow),
            ("up_depth",up_depth),("up_flow",up_flow)]:
    if k not in st.session_state:
        st.session_state[k] = v

# Asymmetric smoothing — critical for flood warning:
#   Rising limb  (new > old): pass through immediately — never lag a warning
#   Falling limb (new < old): smooth slowly — avoid false all-clear signals
def _smooth(old, new, decimals):
    if new >= old:
        return round(new, decimals)                        # rising: instant
    return round(old * 0.85 + new * 0.15, decimals)       # falling: gradual

st.session_state.lo_depth = _smooth(st.session_state.lo_depth, lo_depth, 2)
st.session_state.lo_flow  = _smooth(st.session_state.lo_flow,  lo_flow,  1)
st.session_state.up_depth = _smooth(st.session_state.up_depth, up_depth, 2)
st.session_state.up_flow  = _smooth(st.session_state.up_flow,  up_flow,  1)

lo_depth_lbl, lo_depth_clr = stage_status(st.session_state.lo_depth, LO_BANKFULL)
up_depth_lbl, up_depth_clr = stage_status(st.session_state.up_depth, UP_BANKFULL)
lo_flow_lbl,  lo_flow_clr  = flow_status(st.session_state.lo_flow,   LO_BANKFULL_Q)
up_flow_lbl,  up_flow_clr  = flow_status(st.session_state.up_flow,   UP_BANKFULL_Q)

lo_bkf_pct = round(min(100, st.session_state.lo_depth/LO_BANKFULL*100), 1)
up_bkf_pct = round(min(100, st.session_state.up_depth/UP_BANKFULL*100), 1)

_q_ref      = max(LO_BASEFLOW, st.session_state.lo_flow)
# Flood wave travel time: power-law kinematic scaling
# t = t_ref * (Q_ref / Q)^0.40  (Manning's kinematic wave, natural channel)
# FLOOD_TRAVEL_MIN=65 calibrated to 4-mile reach at near-bankfull Q via Manning's.
# Previous formula had a modulo artifact (up_flow % 7.3) that created a
# physically meaningless sawtooth wave. Removed.
travel_min  = round(min(90.0, max(15.0,
    FLOOD_TRAVEL_MIN * (LO_BASEFLOW / _q_ref) ** 0.40)), 1)
_tw_clr     = "#FF3333" if travel_min<25 else "#FF8800" if travel_min<35 else "#FFD700" if travel_min<50 else "#00FF9C"

_r7_clr     = "#FF3333" if rain_7d>5.0 else "#FF8800" if rain_7d>3.0 else "#FFD700" if rain_7d>1.5 else "#00FF9C"
_src_label, _src_color = _precip_badge(station_rain, backup_rain)


# ═══════════════════════════════════════════════════════════════════════════════
#  10. RENDER
# ═══════════════════════════════════════════════════════════════════════════════

now_et = datetime.now(ET_TZ)

# (no pre-render status check needed — NWS K24A is always authoritative)

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
  <div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
  <div class="site-sub">
    Cullowhee Creek Watershed &mdash; Jackson County, NC
    &nbsp;|&nbsp; {now_et.strftime("%A, %B %d %Y")} &mdash; {now_et.strftime("%H:%M")}
  </div>
</div>""", unsafe_allow_html=True)

# ── PANEL 1: FLOOD THREAT ─────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:{t_bg};border:2px solid {t_clr};border-radius:10px;
            padding:22px 30px;margin-bottom:16px;text-align:center;">
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.75em;
              color:{t_clr};letter-spacing:4px;margin-bottom:6px;">COMPOSITE FLOOD THREAT SCORE</div>
  <div style="font-size:3.5em;font-weight:700;color:{t_clr};letter-spacing:5px;line-height:1.0;">{t_lbl}</div>
  <div style="background:rgba(255,255,255,0.08);border-radius:6px;height:8px;margin:12px auto;max-width:500px;">
    <div style="background:{t_clr};width:{threat}%;height:8px;border-radius:6px;"></div></div>
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:#7AACCC;margin-top:6px;">
    RAIN(24h) {rain_24h:.2f}&quot; &nbsp;&middot;&nbsp; QPF(6h) {qpf_6h:.2f}&quot;
    &nbsp;&middot;&nbsp; SOIL SAT {soil_sat_lo:.0f}% &nbsp;&middot;&nbsp; PoP {pop_24h:.0f}%
    &nbsp;&middot;&nbsp; LOWER {lo_bkf_pct:.0f}% of bankfull
    &nbsp;&middot;&nbsp; UPPER {up_bkf_pct:.0f}% of bankfull
  </div>
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.68em;color:#3A6A8A;
              margin-top:10px;letter-spacing:1px;">
    EVALUATED FACTORS: Soil Saturation &middot; 24hr Rainfall Forecast &middot; Probability of Precipitation
  </div>
</div>""", unsafe_allow_html=True)

# ── PANEL 1B: ACTIVE ALERTS ───────────────────────────────────────────────────
if active_alerts:
    st.markdown('<div class="panel"><div class="panel-title">ACTIVE WEATHER ALERTS</div>', unsafe_allow_html=True)
    for a in active_alerts:
        sty  = _alert_style(a["event"])
        summ = a["headline"] if a["headline"] else a["description"]
        if len(summ) > 220: summ = summ[:217] + "..."
        st.markdown(f"""
<div style="background:{sty['bg']};border-left:6px solid {sty['border']};
            border-radius:8px;padding:14px 16px;margin-bottom:10px;">
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.78em;
              color:{sty['title']};letter-spacing:2px;margin-bottom:6px;">{a['event'].upper()}</div>
  <div style="font-size:0.92em;color:{sty['text']};line-height:1.45;">{summ}</div>
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.66em;color:#7AACCC;margin-top:8px;">
    {"Until " + a["expires_local"] if a["expires_local"] else ""}</div>
</div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 1C: HWO ─────────────────────────────────────────────────────────────
if hwo_text:
    _ph = ""
    for para in hwo_text["paragraphs"]:
        if para["header"]:
            _ph += (f'<div style="font-family:\'Share Tech Mono\',monospace;font-size:0.72em;'
                    f'color:#FFB066;letter-spacing:2px;margin:14px 0 5px;">{para["header"]}</div>')
        _ph += (f'<div style="font-size:1.0em;color:#FFE0C2;line-height:1.65;margin-bottom:4px;">'
                f'{para["body"].replace(chr(10)+chr(10),"<br><br>").replace(chr(10)," ")}</div>')
    st.markdown(f"""
<div style="background:rgba(255,136,0,0.07);border:2px solid #FF8800;border-radius:10px;
            padding:20px 28px;margin-bottom:16px;">
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:#FFB066;
              letter-spacing:4px;margin-bottom:6px;text-align:center;">NWS ACTIVE PRODUCT</div>
  <div style="font-size:3.0em;font-weight:700;color:#FFB066;letter-spacing:4px;
              line-height:1.0;text-align:center;margin-bottom:12px;">HAZARDOUS WEATHER OUTLOOK</div>
  <div style="font-family:'Share Tech Mono',monospace;font-size:0.65em;color:#7AACCC;
              letter-spacing:1px;margin-bottom:14px;text-align:center;
              border-bottom:1px solid rgba(255,136,0,0.25);padding-bottom:10px;">
    NWS GREENVILLE-SPARTANBURG (GSP) &nbsp;&middot;&nbsp; JACKSON COUNTY, NC
    &nbsp;&middot;&nbsp; ISSUED: {hwo_text['issued']}</div>
  {_ph}
</div>""", unsafe_allow_html=True)

# ── PANEL 2: ATMOSPHERIC CONDITIONS ──────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.plotly_chart(make_dial(conditions["wind"], "WIND SPEED",   0, 50,  " mph", "#5AC8FA"), use_container_width=True)
with c2:
    st.plotly_chart(make_dial(conditions["temp"], "TEMPERATURE",  0, 110, " F",   "#FF3333"), use_container_width=True)
with c3:
    st.plotly_chart(make_dial(rain_now,           "RAIN NOW",     0, 4,   '" / hr',"#0077FF"), use_container_width=True)
with c4:
    st.plotly_chart(make_dial(rain_7d,            "RAIN (7-DAY)", 0, 10,  '"',    _r7_clr),   use_container_width=True)
    st.markdown(
        f'<div style="text-align:center;font-family:\'Share Tech Mono\',monospace;'
        f'font-size:0.65em;color:{_src_color};letter-spacing:1px;margin-top:-8px;">'
        f'&#x1F4E1; {_src_label}</div>',
        unsafe_allow_html=True)
st.markdown(
    f'<div style="font-family:\'Share Tech Mono\',monospace;font-size:0.62em;color:#3A5A6A;'
    f'text-align:right;margin-top:2px;padding-right:4px;">'
    f'SOURCES: {" &middot; ".join(backup_rain.get("sources",[_src_label]))}</div>',
    unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 3: UPPER WATERSHED ─────────────────────────────────────────────────
_up_max = UP_BANKFULL * 2.5
st.markdown(f'<div class="upper-panel"><div class="upper-title">'
            f'UPPER CULLOWHEE CREEK ({UP_AREA_ACRES:,} AC | {UP_DA_SQMI:.2f} mi²)</div>',
            unsafe_allow_html=True)
u1, u2, u3 = st.columns([2, 2, 3])
with u1:
    st.components.v1.html(make_stream_gauge(
        "g_up_depth", st.session_state.up_depth, 0.0, _up_max, " ft",
        [{"range":[0.0,          UP_BANKFULL*0.60],"color":"rgba(0,255,156,0.15)"},
         {"range":[UP_BANKFULL*0.60,UP_BANKFULL*0.95],"color":"rgba(255,215,0,0.20)"},
         {"range":[UP_BANKFULL*0.95,_up_max],        "color":"rgba(255,51,51,0.25)"}],
        up_depth_clr, up_depth_lbl, up_depth_clr,
        f"Stage: {st.session_state.up_depth:.2f} ft"), height=240)
with u2:
    _up_q_max = UP_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_up_flow", st.session_state.up_flow, 0.0, _up_q_max, " cfs",
        [{"range":[0.0,             UP_BANKFULL_Q*0.45],"color":"rgba(0,255,156,0.15)"},
         {"range":[UP_BANKFULL_Q*0.45,UP_BANKFULL_Q*0.95],"color":"rgba(255,215,0,0.20)"},
         {"range":[UP_BANKFULL_Q*0.95,_up_q_max],         "color":"rgba(255,51,51,0.25)"}],
        up_flow_clr, up_flow_lbl, up_flow_clr,
        f"Q: {st.session_state.up_flow:.1f} cfs"), height=240)
with u3:
    st.markdown(f"""
<div style="background:rgba(0,50,30,0.18);border:1px solid rgba(0,180,100,0.22);
            border-radius:9px;padding:14px 16px;font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em;color:#00CC77;letter-spacing:3px;margin-bottom:10px;
              border-bottom:1px solid rgba(0,180,100,0.2);padding-bottom:6px;">SOIL SATURATION</div>
  <div style="font-size:2.5em;font-weight:700;color:{soil_color_up};text-align:center;
              margin:6px 0 4px;">{soil_sat_up:.1f}%</div>
  <div style="font-size:0.7em;color:#5AACD0;text-align:center;margin-bottom:8px;">
    stored: {soil_stored_up:.2f}&quot; &nbsp;|&nbsp; pore capacity</div>
</div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 4: LOWER WATERSHED ─────────────────────────────────────────────────
_lo_max = LO_BANKFULL * 2.5
st.markdown(f'<div class="lower-panel"><div class="lower-title">'
            f'LOWER CULLOWHEE CREEK ({LO_AREA_ACRES:,} AC | {LO_DA_SQMI:.2f} mi²)</div>',
            unsafe_allow_html=True)
l1, l2, l3 = st.columns([2, 2, 3])
with l1:
    st.components.v1.html(make_stream_gauge(
        "g_lo_depth", st.session_state.lo_depth, 0.0, _lo_max, " ft",
        [{"range":[0.0,          LO_BANKFULL*0.60],"color":"rgba(0,255,156,0.15)"},
         {"range":[LO_BANKFULL*0.60,LO_BANKFULL*0.95],"color":"rgba(255,215,0,0.20)"},
         {"range":[LO_BANKFULL*0.95,_lo_max],         "color":"rgba(255,51,51,0.25)"}],
        lo_depth_clr, lo_depth_lbl, lo_depth_clr,
        f"Stage: {st.session_state.lo_depth:.2f} ft"), height=240)
with l2:
    _lo_q_max = LO_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_lo_flow", st.session_state.lo_flow, 0.0, _lo_q_max, " cfs",
        [{"range":[0.0,             LO_BANKFULL_Q*0.45],"color":"rgba(0,255,156,0.15)"},
         {"range":[LO_BANKFULL_Q*0.45,LO_BANKFULL_Q*0.95],"color":"rgba(255,215,0,0.20)"},
         {"range":[LO_BANKFULL_Q*0.95,_lo_q_max],         "color":"rgba(255,51,51,0.25)"}],
        lo_flow_clr, lo_flow_lbl, lo_flow_clr,
        f"Q: {st.session_state.lo_flow:.1f} cfs"), height=240)
with l3:
    st.markdown(f"""
<div style="background:rgba(0,50,120,0.18);border:1px solid rgba(0,119,255,0.22);
            border-radius:9px;padding:14px 16px;font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em;color:#0077FF;letter-spacing:3px;margin-bottom:10px;
              border-bottom:1px solid rgba(0,119,255,0.2);padding-bottom:6px;">SOIL SATURATION</div>
  <div style="font-size:2.5em;font-weight:700;color:{soil_color_lo};text-align:center;
              margin:6px 0 4px;">{soil_sat_lo:.1f}%</div>
  <div style="font-size:0.7em;color:#5AACD0;text-align:center;margin-bottom:12px;">
    stored: {soil_stored_lo:.2f}&quot; &nbsp;|&nbsp; pore capacity</div>
</div>""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 5: WATERSHED COMPARISON ────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">WATERSHED COMPARISON &mdash; UPPER vs LOWER SUB-BASIN | CULLOWHEE CREEK</div>',
            unsafe_allow_html=True)
dq     = round(st.session_state.lo_flow  - st.session_state.up_flow,  1)
dd     = round(st.session_state.lo_depth - st.session_state.up_depth, 2)
dq_pct = round((dq/st.session_state.up_flow*100) if st.session_state.up_flow > 0 else 0, 1)
st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:8px;">
  <div style="background:rgba(0,180,100,0.07);border:1px solid rgba(0,180,100,0.25);
              border-radius:8px;padding:16px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:#00CC77;
                letter-spacing:2px;margin-bottom:8px;">UPPER — HEADWATERS</div>
    <div style="font-size:0.75em;color:#7AACCC;margin-bottom:4px;">{UP_AREA_ACRES:,} ac | CN={UP_CN_II} | Tc={UP_TC_HRS}h</div>
    <div style="font-size:2.2em;font-weight:700;color:{up_depth_clr};">{st.session_state.up_depth:.2f} ft</div>
    <div style="font-size:1.1em;color:{up_flow_clr};">{st.session_state.up_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:{up_depth_clr};
                margin-top:6px;letter-spacing:2px;">{up_depth_lbl}</div>
  </div>
  <div style="background:rgba(0,100,200,0.07);border:1px solid rgba(0,119,255,0.20);
              border-radius:8px;padding:16px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:#0077FF;
                letter-spacing:2px;margin-bottom:8px;">DELTA (LOWER &minus; UPPER)</div>
    <div style="font-size:0.75em;color:#7AACCC;margin-bottom:4px;">Watershed response amplification</div>
    <div style="font-size:2.2em;font-weight:700;color:#FFFF00;">{'+' if dd>=0 else ''}{dd:.2f} ft</div>
    <div style="font-size:1.1em;color:#FFFF00;margin-bottom:8px;">{'+' if dq>=0 else ''}{dq:.1f} cfs ({'+' if dq_pct>=0 else ''}{dq_pct:.1f}%)</div>
  </div>
  <div style="background:rgba(0,100,200,0.07);border:1px solid rgba(0,119,255,0.25);
              border-radius:8px;padding:16px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:#0099FF;
                letter-spacing:2px;margin-bottom:8px;">LOWER</div>
    <div style="font-size:0.75em;color:#7AACCC;margin-bottom:4px;">{LO_AREA_ACRES:,} ac | CN={LO_CN_II} | Tc={LO_TC_HRS}h</div>
    <div style="font-size:2.2em;font-weight:700;color:{lo_depth_clr};">{st.session_state.lo_depth:.2f} ft</div>
    <div style="font-size:1.1em;color:{lo_flow_clr};">{st.session_state.lo_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.72em;color:{lo_depth_clr};
                margin-top:6px;letter-spacing:2px;">{lo_depth_lbl}</div>
  </div>
</div>""", unsafe_allow_html=True)
tw1, tw2, tw3 = st.columns([1, 2, 1])
with tw2:
    st.plotly_chart(make_dial(travel_min, "WAVE TRAVEL", 15, 90, " min", _tw_clr),
                    use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 5B: USGS TUCKASEGEE REFERENCE GAGE ─────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">USGS 03508050 — TUCKASEGEE RIVER AT SR 1172 NR CULLOWHEE &nbsp;|&nbsp; REFERENCE GAGE</div>', unsafe_allow_html=True)

if usgs_tuck.get("ok"):
    _tq    = usgs_tuck["discharge_cfs"]
    _tgh   = usgs_tuck.get("gage_height_ft", 0)
    _tscl  = usgs_tuck.get("cullowhee_scaled_cfs", 0)
    _tage  = int(usgs_tuck.get("discharge_age_min", 0))
    # Tuckasegee flood stage = 16 ft (NWS)
    _t_pct_flood = round(min(100, _tgh / 16.0 * 100), 1)
    _t_clr = ("#FF3333" if _tgh >= 14 else "#FF8800" if _tgh >= 10 else
              "#FFD700" if _tgh >= 7  else "#00FF9C")
    st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px;">
  <div style="background:rgba(0,100,200,0.08);border:1px solid rgba(0,119,255,0.25);
              border-radius:8px;padding:14px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.68em;color:#0077FF;
                letter-spacing:2px;margin-bottom:6px;">DISCHARGE</div>
    <div style="font-size:2.0em;font-weight:700;color:{_t_clr};">{_tq:.0f} cfs</div>
    <div style="font-size:0.7em;color:#5AACD0;">{_tage:.0f} min ago</div>
  </div>
  <div style="background:rgba(0,100,200,0.08);border:1px solid rgba(0,119,255,0.25);
              border-radius:8px;padding:14px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.68em;color:#0077FF;
                letter-spacing:2px;margin-bottom:6px;">GAGE HEIGHT</div>
    <div style="font-size:2.0em;font-weight:700;color:{_t_clr};">{_tgh:.2f} ft</div>
    <div style="font-size:0.7em;color:#5AACD0;">{_t_pct_flood:.0f}% of flood stage (16 ft)</div>
  </div>
  <div style="background:rgba(0,100,200,0.08);border:1px solid rgba(0,119,255,0.25);
              border-radius:8px;padding:14px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.68em;color:#0077FF;
                letter-spacing:2px;margin-bottom:6px;">CULLOWHEE SCALED</div>
    <div style="font-size:2.0em;font-weight:700;color:{_t_clr};">{_tscl:.1f} cfs</div>
    <div style="font-size:0.7em;color:#5AACD0;">DA ratio {LO_DA_SQMI:.2f}/{USGS_TUCK_DA:.0f} sq mi</div>
  </div>
  <div style="background:rgba(0,100,200,0.08);border:1px solid rgba(0,119,255,0.25);
              border-radius:8px;padding:14px;text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace;font-size:0.68em;color:#0077FF;
                letter-spacing:2px;margin-bottom:6px;">MODEL vs OBSERVED</div>
    <div style="font-size:1.5em;font-weight:700;color:#FFD700;">{st.session_state.lo_flow:.0f} cfs</div>
    <div style="font-size:0.7em;color:#5AACD0;">NOAH modeled lower Cullowhee</div>
    <div style="font-size:0.7em;color:#5AACD0;margin-top:4px;">scaled ref: {_tscl:.1f} cfs</div>
  </div>
</div>
<div style="font-family:'Share Tech Mono',monospace;font-size:0.62em;color:#3A5A6A;
            margin-top:10px;text-align:right;">
  USGS 03508050 &nbsp;&middot;&nbsp; DA=147 mi² (Cullowhee Creek = 6.6% of watershed)
  &nbsp;&middot;&nbsp; No gage exists on Cullowhee Creek — scaled for reference only
  &nbsp;&middot;&nbsp; Tuckasegee regulated by Duke Energy / Lake Glenville
</div>""", unsafe_allow_html=True)
else:
    st.markdown(
        '<div style="color:#FF8800;font-family:\'Share Tech Mono\',monospace;'
        'font-size:0.8em;">USGS 03508050 UNAVAILABLE</div>',
        unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 6: 7-DAY FLOOD OUTLOOK ─────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED</div>',
            unsafe_allow_html=True)
if not forecast:
    st.warning("Forecast unavailable.")
else:
    pcols = st.columns(7)
    for i, d in enumerate(forecast[:7]):
        # Day 0: weight observed rain heavily; future days: forecast-only
        _obs_weight = max(0.0, 1.0 - i * 0.25)   # fades from 1.0→0 over 4 days
        risk  = min(100.0, round(
            (soil_sat_lo * 0.35) +
            (min(100.0, rain_24h * 25) * _obs_weight * 0.20) +
            (d["pop"]    * (0.35 - _obs_weight * 0.10)) +
            (d["qpf_in"] * 18 * (1.0 - _obs_weight * 0.15)),
        1))
        color = "#00FF9C" if risk<30 else "#FFFF00" if risk<50 else "#FFD700" if risk<65 else "#FF8800" if risk<80 else "#FF3333"
        with pcols[i]:
            st.markdown(
                f'<div style="background:rgba(255,255,255,0.03);border-top:4px solid {color};'
                f'border-radius:8px;padding:12px 8px;text-align:center;">'
                f'<div style="font-weight:700;font-size:1.1em;">{d["short_name"]}</div>'
                f'<div style="font-size:0.75em;color:#5A7090;margin-bottom:4px;">{d["date_label"]}</div>'
                f'<div style="font-family:\'Share Tech Mono\',monospace;font-size:0.75em;color:#7AACCC;margin-bottom:4px;">{forecast_icon(d.get("icon_txt",""))}</div>'
                f'<div style="color:{color};font-size:1.55em;font-weight:700;margin:5px 0;">{risk:.1f}%</div>'
                f'<div style="color:{color};font-family:\'Share Tech Mono\',monospace;font-size:0.72em;letter-spacing:2px;margin-bottom:4px;">FLOOD RISK</div>'
                f'<div style="color:#00FFCC;font-family:\'Share Tech Mono\',monospace;font-size:0.85em;">{d["qpf_in"]:.2f}&quot;</div>'
                f'<div style="color:#7AACCC;font-size:0.75em;">{d["pop"]:.0f}% PoP</div>'
                f'<div style="color:#7AACCC;font-size:0.75em;">{d["temp_f"]:.0f} F</div>'
                f'</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ── PANEL 7: RADAR ───────────────────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">RADAR LOOP</div>', unsafe_allow_html=True)
_cb = int(time.time() / 120)
st.components.v1.html(f"""
<div style="background:#04090F;border-radius:10px;border:1px solid #1a2a3a;
            overflow:hidden;font-family:'Courier New',monospace;">
  <div style="display:flex;align-items:center;justify-content:space-between;
              padding:8px 16px;background:#0a1520;border-bottom:1px solid #1a3a5a;">
    <div style="display:flex;align-items:center;gap:10px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#00FF9C;box-shadow:0 0 6px #00FF9C;"></div>
      <span style="color:#00CFFF;font-size:11px;font-weight:700;letter-spacing:2px;">LIVE</span>
    </div>
    <div style="color:#556677;font-size:10px;letter-spacing:1px;">AUTO-LOOP &#x21BB; 2 MIN</div>
  </div>
  <div style="position:relative;background:#000;text-align:center;">
    <img src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?v={_cb}"
         style="width:100%;max-height:520px;object-fit:contain;display:block;" alt="Radar Loop"/>
    <div style="position:absolute;bottom:0;left:0;right:0;
                background:linear-gradient(transparent,rgba(0,0,0,0.85));
                padding:20px 16px 8px;display:flex;justify-content:space-between;align-items:flex-end;">
      <div style="color:#667788;font-size:10px;letter-spacing:1px;">COVERAGE: WNC &bull; SC UPSTATE &bull; NW GA &bull; SW VA</div>
      <div style="display:flex;gap:4px;align-items:center;">
        <span style="color:#556677;font-size:9px;margin-right:4px;">dBZ</span>
        <span style="display:inline-block;width:18px;height:10px;background:#04e9e7;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#009d00;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#00d400;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#f5f500;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#e69800;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#e60000;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#990000;"></span>
        <span style="display:inline-block;width:18px;height:10px;background:#ff00ff;"></span>
      </div>
    </div>
  </div>
</div>""", height=610)
st.markdown('</div>', unsafe_allow_html=True)
