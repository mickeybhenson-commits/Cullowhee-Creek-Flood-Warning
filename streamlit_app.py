"""
NOAH: Cullowhee Creek Flood Warning Dashboard
Western Carolina University — NEMO River Energy Initiative
Jackson County, NC — Watershed Monitoring System

Architecture: Two-point sub-watershed model (pre-sensor)
  UPPER: Headwaters sub-basin (~2,480 ac | 3.875 mi² | CN=62 | Tc=1.2h)
  LOWER: Full watershed outlet at NCCAT (~6,200 ac | 9.688 mi² | CN=68 | Tc=2.5h)

Hydrologic engine: SCS TR-55 Type II peak flow (NRCS 1986)
  Replaces Rational Method (valid only ≤640 ac; discarded Tc entirely).
  TR-55 is the NRCS/NWS standard for 1–20 mi² humid Appalachian watersheds.
  Tc is now used correctly: upper (1.2h) vs lower (2.5h) gives physically
  distinct storm responses, especially for fast convective events vs slow frontal.

Hydraulic geometry baseline — ECOREGION 66 BLUE RIDGE COMPOSITE CURVES:
  Source: Henson et al. (2014) NC Mountain Streams + SCDNR Ecoregion 66 (May 2020)
  50 stable reference reaches across Southern Blue Ridge physiographic province.
  Regression forms:  Qbkf = 35.0 × DA^0.850  (cfs, DA in mi²)
                     Wbkf = 12.5 × DA^0.460  (ft)
                     Dbkf = 1.05 × DA^0.310  (ft, mean riffle depth)
  Applied to derive rating curve A, bankfull stage, and channel width for both sub-basins.
  K-correction (Q_obs/Q_mod) will supersede regional priors after 10–15 storm events.
  Caveat: Southern Blue Ridge hydraulic geometry is also influenced by watershed slope
    and local channel characteristics beyond drainage area alone (Carey et al. 2023,
    IJRBM — "Drainage area is not enough"). Individual reach scatter ≈ ±40-60%.

Data sources:
  - Atmospheric:   Open-Meteo HRRR/GFS (real-time, no API key)
  - Soil moisture: 3-SOURCE ENSEMBLE:
                     ERA5-Land volumetric (0-7cm, 7-28cm) — physics baseline, ~5 day lag
                     HRRR Antecedent Precip Index (5-day) — zero lag, real-time
                     USDA Drought Monitor (Jackson Co. FIPS 37099) — weekly expert synthesis
  - QPF / PoP:     NWS GSP Gridpoint API (Greenville-Spartanburg WFO)
  - Radar:         NEXRAD WSR-88D KGSP — same feed used by NWS operations and Jackson Co. EM

Version: 2026-03  |  Status: Pre-sensor (modeled)  |  Next: NCCAT Blues Notecard deployment
"""

import math
import streamlit as st
import requests
import json
import time
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_autorefresh import st_autorefresh


# ═══════════════════════════════════════════════════════════════════════════════
#  1. CONFIGURATION & STYLING
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746   # Cullowhee Creek / NCCAT vicinity

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
.upper-panel { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,180,100,0.25);
               border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.upper-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #00CC77;
               text-transform: uppercase; letter-spacing: 3px;
               border-bottom: 1px solid rgba(0,180,100,0.25); padding-bottom: 8px; margin-bottom: 14px; }
.lower-panel { background: rgba(8,16,28,0.88); border: 1px solid rgba(0,119,255,0.25);
               border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
.lower-title { font-family: 'Share Tech Mono', monospace; font-size: 0.78em; color: #0099FF;
               text-transform: uppercase; letter-spacing: 3px;
               border-bottom: 1px solid rgba(0,119,255,0.25); padding-bottom: 8px; margin-bottom: 14px; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. WATERSHED & SOIL CONSTANTS
#     Rating curve A coefficients and bankfull stage derived from Ecoregion 66
#     Blue Ridge regional curves (see Section 2.5 below).
#     B exponents remain Manning's-derived for cobble/gravel mountain channels.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Soil physics — WNC Ultisols (Evard-Cowee-Plott series, SSURGO) ────────────
SOIL_POROSITY  = 0.439   # m³/m³ — saturation point (all pores filled)
SOIL_FIELD_CAP = 0.286   # m³/m³ — field capacity (gravity drainage complete)
SOIL_WILT_PT   = 0.151   # m³/m³ — permanent wilting point (plant-unavailable)

# ── LOWER sub-watershed: Full outlet at NCCAT ─────────────────────────────────
# Drains entire Cullowhee Creek watershed. Sensor target: NCCAT bridge.
# Hydraulic geometry anchored to Ecoregion 66 composite curves:
#   DA = 6200 ac / 640 = 9.688 mi² →  Qbkf=241 cfs | Wbkf=35.5 ft | Dbkf_mean=2.12 ft
#   Bankfull stage (gauge) = Dbkf_mean × 1.35 (B/C cobble depth-ratio) = 2.87 ft
#   Rating A = Qbkf / stage^B = 241.2 / 2.87^2.30 = 21.4
LO_AREA_ACRES    = 6200      # Total watershed drainage area to NCCAT (ac)
LO_DA_SQMI       = 9.688     # Drainage area in square miles (6200/640)
LO_TC_HRS        = 2.5       # Time of concentration (hr) — Kirpich estimate
LO_CN_II         = 68        # SCS CN AMC-II: forested Ultisol, ~20% impervious
LO_RATING_A      = 21.4      # Rating curve Q = A·D^B — coefficient
                              #   Derived: Qbkf(E66) = 241.2 cfs @ bankfull stage 2.87 ft
LO_RATING_B      = 2.30      # Rating curve exponent (Manning's-derived, cobble channel)
LO_BASEFLOW      = 9.0       # Low-season baseflow estimate at NCCAT (cfs)
LO_BANKFULL      = 2.87      # Bankfull stage at NCCAT (ft) — Ecoregion 66 derived
LO_BANKFULL_Q    = 241.2     # Bankfull discharge (cfs) — Ecoregion 66 composite curve
LO_BANKFULL_MEAND = 2.12     # Bankfull mean riffle depth (ft) — Ecoregion 66 regression
LO_WIDTH_FT      = 35.5      # Bankfull channel width (ft) — Ecoregion 66 derived
LO_MANN_N        = 0.045     # Manning's n — natural cobble/gravel mountain stream

# ── UPPER sub-watershed: Headwaters above WCU campus ─────────────────────────
# Steeper, denser forest, higher elevation (~3,200 ft). Faster response time.
# Sensor target: upper Cullowhee Creek bridge near headwaters.
# Hydraulic geometry anchored to Ecoregion 66 composite curves:
#   DA = 2480 ac / 640 = 3.875 mi² →  Qbkf=111 cfs | Wbkf=23.3 ft | Dbkf_mean=1.60 ft
#   Bankfull stage (gauge) = 1.60 × 1.35 = 2.16 ft
#   Rating A = 110.7 / 2.16^2.15 = 21.2
UP_AREA_ACRES      = 2480    # Upper sub-basin drainage area (~40% of total) (ac)
UP_DA_SQMI         = 3.875   # Drainage area in square miles (2480/640)
UP_TC_HRS          = 1.2     # Shorter Tc — steeper gradient, smaller basin (hr)
UP_CN_II           = 62      # Lower CN — denser canopy, less development
UP_RATING_A        = 21.2    # Rating curve coefficient — Ecoregion 66 derived
                              #   Qbkf(E66) = 110.7 cfs @ bankfull stage 2.16 ft
UP_RATING_B        = 2.15    # Rating curve exponent (Manning's-derived, cobble channel)
UP_BASEFLOW        = 3.5     # Low-season baseflow estimate at headwaters (cfs)
UP_BANKFULL        = 2.16    # Bankfull stage at headwaters (ft) — Ecoregion 66 derived
UP_BANKFULL_Q      = 110.7   # Bankfull discharge (cfs) — Ecoregion 66 composite curve
UP_BANKFULL_MEAND  = 1.60    # Bankfull mean riffle depth (ft) — Ecoregion 66 regression
UP_WIDTH_FT        = 23.3    # Bankfull channel width (ft) — Ecoregion 66 derived
FLOOD_TRAVEL_MIN   = 65      # Flood wave travel time UPPER → NCCAT (min, pre-cal)


# ═══════════════════════════════════════════════════════════════════════════════
#  2.5  ECOREGION 66 BLUE RIDGE REGIONAL CURVES
#
#  Source: Henson et al. (2014) "Bankfull Regional Curves for NC Mountain Streams"
#          AWRA Conf. Water Resources in Extreme Environments, Anchorage AK.
#          Composite extended by SCDNR Ecoregion 66 Blue Ridge Summary (May 2020),
#          50 stable reference reaches across the Southern Blue Ridge province.
#
#  Power-law regression forms (DA in mi², outputs in cfs / ft / ft²):
#    Qbkf = 35.0 × DA^0.850   bankfull discharge          R² ≈ 0.87
#    Wbkf = 12.5 × DA^0.460   bankfull width              R² ≈ 0.88
#    Dbkf = 1.05 × DA^0.310   bankfull mean riffle depth  R² ≈ 0.82
#    Abkf = Wbkf × Dbkf       bankfull cross-section area
#
#  Depth-to-stage conversion:
#    For B/C type cobble mountain streams, bankfull STAGE (gauge reading from
#    thalweg datum) ≈ Dbkf_mean × 1.35.  This factor reflects the asymmetric
#    cross-section shape of riffle pools where thalweg depth exceeds mean depth.
#    Range in literature: 1.2–1.6 (Rosgen 1996; Henson et al. 2014).
#
#  Important caveats:
#    • Individual reach scatter: ±40–60% around the composite line.
#    • Post-Helene channel disturbance may shift reaches off the regional mean.
#    • Carey et al. (2023) show that watershed slope/relief also significantly
#      predict morphology in the Southern Blue Ridge beyond drainage area alone.
#    • K-correction (Q_obs / Q_mod) from first 10–15 storm events replaces
#      regional prior for each deployment point independently.
# ═══════════════════════════════════════════════════════════════════════════════

# Regression coefficients — Ecoregion 66 Blue Ridge composite
_E66_Q_COEF,  _E66_Q_EXP  = 35.0, 0.850   # bankfull discharge (cfs)
_E66_W_COEF,  _E66_W_EXP  = 12.5, 0.460   # bankfull width (ft)
_E66_D_COEF,  _E66_D_EXP  = 1.05, 0.310   # bankfull mean depth (ft)
_E66_DEPTH_STAGE_RATIO     = 1.35           # mean depth → gauge stage (B/C cobble)


def ecoregion66_bankfull(da_sqmi: float) -> dict:
    """
    Compute Ecoregion 66 Blue Ridge regional curve estimates for a given
    drainage area.

    Parameters
    ----------
    da_sqmi : float  — Drainage area in square miles.

    Returns
    -------
    dict with keys:
        qbkf         — bankfull discharge (cfs)
        wbkf         — bankfull channel width (ft)
        dbkf_mean    — bankfull mean riffle depth (ft)
        abkf         — bankfull cross-sectional area (ft²)
        dbkf_stage   — bankfull stage / gauge reading (ft), = dbkf_mean × 1.35
        rating_a     — rating curve A coeff for given B exponent (uses Manning B=2.30)
        da_sqmi      — echo of input for display
    """
    da = float(da_sqmi)
    qbkf       = _E66_Q_COEF * da ** _E66_Q_EXP
    wbkf       = _E66_W_COEF * da ** _E66_W_EXP
    dbkf_mean  = _E66_D_COEF * da ** _E66_D_EXP
    abkf       = wbkf * dbkf_mean
    dbkf_stage = dbkf_mean * _E66_DEPTH_STAGE_RATIO
    # Default A for B=2.30; callers may pass their own B
    rating_a_230 = qbkf / (dbkf_stage ** 2.30)
    return {
        "qbkf":       round(qbkf,      1),
        "wbkf":       round(wbkf,      1),
        "dbkf_mean":  round(dbkf_mean, 2),
        "abkf":       round(abkf,      1),
        "dbkf_stage": round(dbkf_stage,2),
        "rating_a":   round(rating_a_230, 1),
        "da_sqmi":    round(da, 3),
    }


# Pre-compute regional curve estimates for both sub-basins (used in panel display)
_E66_LO = ecoregion66_bankfull(LO_DA_SQMI)
_E66_UP = ecoregion66_bankfull(UP_DA_SQMI)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. DATA ACQUISITION
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_openmeteo_current():
    """Real-time atmospheric conditions — Open-Meteo HRRR/GFS, exact Cullowhee coords."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":           LAT,
                "longitude":          LON,
                "current":            "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                                      "wind_direction_10m,surface_pressure,precipitation,"
                                      "weather_code,wind_gusts_10m",
                "temperature_unit":   "fahrenheit",
                "wind_speed_unit":    "mph",
                "precipitation_unit": "inch",
                "forecast_days":      1,
            },
            timeout=10
        ).json()
        c = r["current"]
        return {
            "ok":        True,
            "temp":      round(float(c.get("temperature_2m",       50)), 2),
            "hum":       round(float(c.get("relative_humidity_2m", 50)), 2),
            "wind":      round(float(c.get("wind_speed_10m",        0)), 2),
            "wind_gust": round(float(c.get("wind_gusts_10m",        0)), 2),
            "wind_dir":  round(float(c.get("wind_direction_10m",    0)), 2),
            "press":     round(c.get("surface_pressure", 1013.25) * 0.02953, 2),
            "precip":    round(float(c.get("precipitation",         0)), 2),
            "wcode":     c.get("weather_code", 0),
        }
    except Exception:
        return {"ok": False, "temp": 50.0, "hum": 50.0, "wind": 0.0,
                "wind_gust": 0.0, "wind_dir": 0.0, "press": 29.92,
                "precip": 0.0, "wcode": 0}


@st.cache_data(ttl=1800)
def fetch_nws_forecast():
    """7-day QPF, PoP, high temp — NWS GSP Gridpoint API."""
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0 (WCU NEMO Project)"}
        pts  = requests.get(f"https://api.weather.gov/points/{LAT},{LON}",
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
            except Exception:
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
                except Exception:
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
            except Exception:
                continue
        return result, True, None
    except Exception as e:
        return [], False, str(e)


@st.cache_data(ttl=1800)
def fetch_precip_history():
    """
    HRRR/GFS hourly precip — no ERA5 latency.
    Returns 14d total, 7d total, 7d snow, 24h accumulation.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":           LAT,
                "longitude":          LON,
                "hourly":             "precipitation,snowfall",
                "precipitation_unit": "inch",
                "past_days":          14,
                "forecast_days":      1,
                "models":             "best_match",
            },
            timeout=10
        ).json()

        now      = datetime.utcnow()
        times    = r["hourly"]["time"]
        precip_h = r["hourly"]["precipitation"]
        snow_h   = r["hourly"].get("snowfall", [0] * len(times))

        t14d = t7d = t5d = t24h = snow7d = 0.0
        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t)
            except Exception:
                continue
            age = (now - dt).total_seconds() / 86400
            if age < 0:
                continue
            p = precip_h[i] or 0.0
            s = (snow_h[i] or 0.0) * 0.0393701   # cm → inch
            if age <= 14: t14d  += p
            if age <= 7:  t7d   += p; snow7d += s
            if age <= 5:  t5d   += p
            if age <= 1:  t24h  += p

        return round(t14d, 2), round(t7d, 2), round(snow7d, 2), round(t24h, 2), round(t5d, 2), True
    except Exception:
        return 2.10, 0.50, 0.00, 0.00, 0.50, False


@st.cache_data(ttl=3600)
def fetch_era5_soil_moisture():
    """
    ECMWF ERA5-Land volumetric soil moisture (m³/m³).
    Two depth layers — surface (0-7cm) and root zone (7-28cm).
    ERA5-Land lag: ~5 days. Fetches last 14 days, returns most recent valid pair.
    Falls back gracefully if archive API is unavailable.
    """
    try:
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

        for i in range(len(times) - 1, -1, -1):
            if sm_07[i] is not None and sm_728[i] is not None:
                return round(sm_07[i], 4), round(sm_728[i], 4), times[i], True

        return None, None, None, False
    except Exception:
        return None, None, None, False


@st.cache_data(ttl=3600)
def fetch_usdm_drought():
    """
    USDA US Drought Monitor — Jackson County NC (FIPS 37099).
    Returns dominant drought level integer:
      -1 = API unavailable   0 = No drought
       1 = D0 Abnormally Dry  2 = D1 Moderate   3 = D2 Severe
       4 = D3 Extreme         5 = D4 Exceptional
    Uses NC DMAC rule: highest category covering ≥25% of county.
    Updated weekly (Thursdays). Source: droughtmonitor.unl.edu
    """
    try:
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=21)
        r = requests.get(
            "https://usdmdataservices.unl.edu/api/CountyStatistics/"
            "GetDroughtSeverityStatisticsByAreaPercent",
            params={
                "aoi":            "37099",
                "startdate":      start_dt.strftime("%m/%d/%Y"),
                "enddate":        end_dt.strftime("%m/%d/%Y"),
                "statisticsType": "1",
            },
            timeout=10
        ).json()

        if not r:
            return -1, "NO DATA", "---"

        rec      = r[-1]
        map_date = rec.get("MapDate", "")[:10]

        for level, key in [(5, "D4"), (4, "D3"), (3, "D2"), (2, "D1"), (1, "D0")]:
            if float(rec.get(key, 0) or 0) >= 25.0:
                labels = {1: "D0 ABNORMALLY DRY", 2: "D1 MODERATE DROUGHT",
                          3: "D2 SEVERE DROUGHT", 4: "D3 EXTREME DROUGHT",
                          5: "D4 EXCEPTIONAL DROUGHT"}
                return level, labels[level], map_date

        return 0, "NO DROUGHT", map_date

    except Exception:
        return -1, "API UNAVAILABLE", "---"


# ═══════════════════════════════════════════════════════════════════════════════
#  4. HYDRO-MODELING
# ═══════════════════════════════════════════════════════════════════════════════

def calc_era5_sat_pct(sm_07, sm_728):
    """ERA5-Land volumetric → saturation %. Clamp to valid range."""
    sm_07  = min(sm_07,  SOIL_POROSITY)
    sm_728 = min(sm_728, SOIL_POROSITY)
    sm_avg = min((sm_07 * 0.55) + (sm_728 * 0.45), SOIL_POROSITY)
    sat_range = SOIL_POROSITY - SOIL_WILT_PT
    return round(min(100.0, max(0.0, (sm_avg - SOIL_WILT_PT) / sat_range * 100)), 2)


def calc_api_sat_pct(rain_5d):
    """
    Antecedent Precipitation Index → soil saturation %.
    Uses SCS AMC thresholds for humid Appalachian climate (growing season).
    SCS AMC-I: < 2.1"  → dry   (~10-35%)
    SCS AMC-II: 2.1-2.8" → normal (~35-60%)
    SCS AMC-III: > 2.8" → wet   (~60-90%)
    No lag — directly from HRRR hourly precip.
    """
    a = min(float(rain_5d), 5.0)
    if a < 0.30:   sat = 10.0 + a * 33.3
    elif a < 1.00: sat = 20.0 + (a - 0.30) / 0.70 * 18.0
    elif a < 2.10: sat = 38.0 + (a - 1.00) / 1.10 * 17.0
    elif a < 2.80: sat = 55.0 + (a - 2.10) / 0.70 * 13.0
    else:          sat = 68.0 + (a - 2.80) / 2.20 * 22.0
    return round(min(90.0, max(5.0, sat)), 1)


# USDM drought level → expert-implied soil saturation anchor (%)
_USDM_IMPLIED_SAT = {1: 55.0, 2: 40.0, 3: 27.0, 4: 17.0, 5: 8.0}

# USDM level → hard ceiling on final sat % (can't be wetter than drought implies)
_USDM_CEILING = {0: 100, 1: 65, 2: 50, 3: 35, 4: 22, 5: 12}


def calc_soil_saturation_ensemble(sm_07, sm_728, sm_ok, rain_5d, usdm_level):
    """
    Three-source soil saturation ensemble (pre-sensor best estimate).

    Sources:
      ERA5-Land  — physics reanalysis, ~5 day lag, can drift post-Helene
      API        — HRRR antecedent precip index, zero lag, no deep memory
      USDM       — expert synthesis (40-50 indicators), weekly, authoritative
                   for drought conditions; Jackson Co. NC FIPS 37099

    Blending strategy:
      • No drought (usdm ≤ 0): ERA5 35% + API 65% (API more current)
      • D0 drought    (usdm=1): ERA5 20% + API 50% + USDM 30%
      • D1 drought    (usdm=2): ERA5 15% + API 40% + USDM 45%
      • D2+ drought   (usdm≥3): ERA5 10% + API 30% + USDM 60%
    USDM hard ceiling applied after blend.
    If ERA5 unavailable, its weight shifts to API.
    """
    api_pct  = calc_api_sat_pct(rain_5d)
    era5_pct = calc_era5_sat_pct(sm_07, sm_728) if (sm_ok and sm_07 is not None) else None
    usdm_pct = _USDM_IMPLIED_SAT.get(usdm_level)

    if usdm_level <= 0:
        w_era5, w_api, w_usdm = 0.35, 0.65, 0.0
    elif usdm_level == 1:
        w_era5, w_api, w_usdm = 0.20, 0.50, 0.30
    elif usdm_level == 2:
        w_era5, w_api, w_usdm = 0.15, 0.40, 0.45
    else:
        w_era5, w_api, w_usdm = 0.10, 0.30, 0.60

    if era5_pct is None:
        w_api   += w_era5
        w_era5   = 0.0
        era5_use = api_pct
    else:
        era5_use = era5_pct

    if usdm_pct is None:
        w_api   += w_usdm
        w_usdm   = 0.0
        usdm_use = api_pct
    else:
        usdm_use = usdm_pct

    sat_pct = (era5_use * w_era5) + (api_pct * w_api) + (usdm_use * w_usdm)

    ceiling = _USDM_CEILING.get(max(0, usdm_level), 100)
    sat_pct = min(sat_pct, ceiling)
    sat_pct = round(min(100.0, max(1.0, sat_pct)), 1)

    if sm_ok and sm_07 is not None:
        sm_07c     = min(sm_07,  SOIL_POROSITY)
        sm_728c    = min(sm_728, SOIL_POROSITY)
        stored_in  = round((sm_07c * 2.756) + (sm_728c * 8.268), 2)
    else:
        stored_in  = round((sat_pct / 100.0) * (SOIL_POROSITY * 11.024), 2)

    color = "#FF3333" if sat_pct > 85 else "#FF8800" if sat_pct > 70 else "#FFD700" if sat_pct > 50 else "#00FF9C"

    sources = {
        "era5_pct":  round(era5_use, 1) if era5_pct is not None else None,
        "api_pct":   api_pct,
        "usdm_pct":  usdm_pct,
        "w_era5":    round(w_era5, 2),
        "w_api":     round(w_api, 2),
        "w_usdm":    round(w_usdm, 2),
    }
    return sat_pct, stored_in, color, sources



# ── SCS TR-55 Type II storm — unit peak discharge coefficients (Exhibit 4-I) ──
# qu = 10^(C0 + C1·log10(Tc) + C2·log10(Tc)²)  units: csm/in (cfs/mi²/in)
# Tabulated by initial abstraction ratio Ia/P.  Tc must be in hours (0.1–10 h).
# Source: USDA NRCS TR-55 (1986), Table 4-1.  Type II storm distribution
#         is standard for humid East US including WNC / Southern Appalachians.
_TR55_IAPRATIO = [0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50]
_TR55_C0       = [2.55323, 2.23537, 2.10304, 2.18219, 2.17339, 2.16251, 2.14583]
_TR55_C1       = [-0.61512, -0.50537, -0.51488, -0.50258, -0.48985, -0.47856, -0.46772]
_TR55_C2       = [-0.16403, -0.11657, -0.08648, -0.09057, -0.09084, -0.09303, -0.09373]


def _tr55_unit_peak(tc_hrs: float, ia_p: float) -> float:
    """
    Interpolate TR-55 unit peak discharge qu (cfs/mi²/in).

    Parameters
    ----------
    tc_hrs : Time of concentration (hours).  Clamped to [0.1, 10.0].
    ia_p   : Initial abstraction ratio Ia/P.  Clamped to [0.10, 0.50].
    """
    ia_p   = max(0.10, min(0.50, float(ia_p)))
    tc_hrs = max(0.10, min(10.0, float(tc_hrs)))
    lt     = math.log10(tc_hrs)

    # Find bounding rows and interpolate coefficients
    tbl = _TR55_IAPRATIO
    if ia_p <= tbl[0]:
        C0, C1, C2 = _TR55_C0[0], _TR55_C1[0], _TR55_C2[0]
    elif ia_p >= tbl[-1]:
        C0, C1, C2 = _TR55_C0[-1], _TR55_C1[-1], _TR55_C2[-1]
    else:
        for i in range(len(tbl) - 1):
            if tbl[i] <= ia_p <= tbl[i + 1]:
                t = (ia_p - tbl[i]) / (tbl[i + 1] - tbl[i])
                C0 = _TR55_C0[i] + t * (_TR55_C0[i + 1] - _TR55_C0[i])
                C1 = _TR55_C1[i] + t * (_TR55_C1[i + 1] - _TR55_C1[i])
                C2 = _TR55_C2[i] + t * (_TR55_C2[i + 1] - _TR55_C2[i])
                break
    return 10.0 ** (C0 + C1 * lt + C2 * lt ** 2)


def model_stream(soil_sat_pct, rain_24h, qpf_24h, rain_7d,
                 da_sqmi, tc_hrs, cn_ii, baseflow,
                 rating_a, rating_b, bankfull_q):
    """
    SCS TR-55 peak flow + Ecoregion 66-anchored power-law rating curve.

    Replaces Rational Method, which is only valid up to ~200-640 acres.
    TR-55 is the NRCS standard for 1–20 mi² humid Appalachian catchments
    and is what NWS / FEMA use in WNC flood studies at this scale.

    Steps
    -----
    1. AMC-adjusted CN from soil saturation %
         Dry (<30%):     CN_I  = CN_II × 0.87
         Normal (30-65%): CN_II (no change)
         Wet  (>65%):    CN_III via standard SCS formula
    2. SCS-CN runoff depth (inches) from 24h observed + QPF
         Q_in = (P − Ia)² / (P − Ia + S),  Ia = 0.2·S
    3. TR-55 Type II unit peak discharge interpolation
         qu = 10^(C0 + C1·log10(Tc) + C2·log10(Tc)²)   [cfs/mi²/in]
         qp = qu × da_sqmi × Q_runoff_in                [cfs]
         This correctly uses Tc (which Rational Method discarded entirely).
    4. Antecedent baseflow: scales 1× (dry) → 4× (saturated)
    5. 7-day recession: dimensionally correct — scaled by baseflow level
         Q_recess = max(0, (rain_7d − rain_24h) × baseflow × 0.25)
         (previously was raw rainfall × 0.8 — dimensionally wrong)
    6. Total Q capped at 3× bankfull (floodplain flow; Manning invalid above)
    7. Rating curve: D = (Q / rating_a)^(1/rating_b)

    Post-sensor calibration: K = Q_obs / Q_mod applied after 10–15 storm events.
    """
    # 1. AMC-adjusted CN
    if soil_sat_pct < 30:
        cn_adj = max(50.0, cn_ii * 0.87)
    elif soil_sat_pct < 65:
        cn_adj = float(cn_ii)
    else:
        cn_adj = min(95.0, (23.0 * cn_ii) / (10.0 + 0.13 * cn_ii))

    # 2. SCS runoff depth (inches)
    P  = max(0.0, rain_24h + qpf_24h)
    S  = (1000.0 / cn_adj) - 10.0
    Ia = 0.2 * S
    if P > Ia:
        Q_runoff_in = (P - Ia) ** 2 / (P - Ia + S)
    else:
        Q_runoff_in = 0.0

    # 3. TR-55 peak storm discharge
    if Q_runoff_in > 0.0 and P > 0.0:
        ia_p      = min(0.50, max(0.10, Ia / P))
        qu        = _tr55_unit_peak(tc_hrs, ia_p)         # cfs/mi²/in
        Q_storm   = qu * da_sqmi * Q_runoff_in            # cfs — dimensionally correct
    else:
        Q_storm = 0.0

    # 4. Antecedent baseflow (moisture-scaled)
    Q_base = baseflow * (1.0 + (soil_sat_pct / 100.0) * 3.0)

    # 5. 7-day recession (dimensionally correct — scaled by baseflow)
    Q_recess = max(0.0, (rain_7d - rain_24h) * baseflow * 0.25)

    # 6. Total Q — cap at 3× bankfull
    Q_max   = bankfull_q * 3.0
    Q_total = round(max(baseflow * 0.5, min(Q_base + Q_storm + Q_recess, Q_max)), 1)

    # 7. Rating curve
    depth_ft = round(max(0.20, min((Q_total / rating_a) ** (1.0 / rating_b), 9.0)), 2)

    return depth_ft, Q_total


def flood_threat_score(soil_sat, qpf_24h, pop_24h):
    """Composite threat: soil saturation 40%, QPF 35%, PoP 25%."""
    return round(min(100.0,
        (soil_sat * 0.40) +
        (min(100.0, qpf_24h * 40) * 0.35) +
        (pop_24h * 0.25)
    ), 2)


def threat_meta(score):
    if score < 25: return "NORMAL",    "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45: return "ELEVATED",  "#FFFF00", "rgba(255,255,0,0.09)"
    if score < 65: return "WATCH",     "#FFD700", "rgba(255,215,0,0.09)"
    if score < 82: return "WARNING",   "#FF8800", "rgba(255,136,0,0.11)"
    return               "EMERGENCY",  "#FF3333", "rgba(255,51,51,0.14)"


def stage_status(depth_ft, bankfull_ft):
    """Convert depth to status label and color relative to Ecoregion 66 bankfull stage."""
    ratio = depth_ft / bankfull_ft
    if ratio < 0.45:  return "LOW FLOW",  "#00FF9C"
    if ratio < 0.65:  return "NORMAL",    "#00FF9C"
    if ratio < 0.80:  return "ELEVATED",  "#FFFF00"
    if ratio < 0.95:  return "WATCH",     "#FFD700"
    return                   "FLOOD",     "#FF3333"


def flow_status(q, bankfull_q):
    """Flow status relative to Ecoregion 66 bankfull discharge."""
    if q < bankfull_q * 0.15:  return "LOW FLOW",  "#00FF9C"
    if q < bankfull_q * 0.45:  return "NORMAL",    "#00FF9C"
    if q < bankfull_q * 0.85:  return "ELEVATED",  "#FFFF00"
    if q < bankfull_q * 1.00:  return "WATCH",     "#FFD700"
    return                             "FLOOD",     "#FF3333"


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


# ═══════════════════════════════════════════════════════════════════════════════
#  5. UI COMPONENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def make_dial(v, t, min_v, max_v, u, c, sub="", src=""):
    """Plotly gauge dial with clean 3-level typography hierarchy."""
    parts = [f"<b>{t}</b>"]
    if sub: parts.append(f"<span style='font-size:11px;color:#7AACCC'>{sub}</span>")
    if src: parts.append(f"<span style='font-size:9px;color:#2A6080'>{src}</span>")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": u, "font": {"size": 24, "color": "white"}, "valueformat": ".2f"},
        title={"text": "<br>".join(parts), "font": {"size": 13, "color": "#A0C8E0"}},
        gauge={
            "axis": {"range": [min_v, max_v], "tickfont": {"size": 9, "color": "#334455"}},
            "bar":  {"color": c, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
        },
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(t=70, b=20, l=25, r=25), height=185)
    return fig


def make_stream_gauge(gid, v, title, min_v, max_v, unit, ranges, needle_clr,
                      status_lbl, status_clr, sub_line, src_line):
    """Animated canvas arc gauge for stream depth / discharge."""
    t_js = json.dumps(
        [{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in ranges]
    )
    return f"""<html><body style="background:transparent;text-align:center;
font-family:'Rajdhani',sans-serif;color:white;">
<canvas id="{gid}" width="260" height="150"></canvas>
<div style="color:{status_clr};font-weight:700;font-size:16px;
            text-transform:uppercase;letter-spacing:2px;">{status_lbl}</div>
<div style="font-size:12px;color:#7AACCC;margin-top:4px;">{sub_line}</div>
<div style="font-size:9px;color:#1A5070;font-family:'Share Tech Mono',monospace;
            margin-top:2px;">SRC: {src_line}</div>
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
        ctx.beginPath(); ctx.strokeStyle='{needle_clr}'; ctx.lineWidth=4;
        ctx.moveTo(cx,cy); ctx.lineTo(cx+r*Math.cos(ang),cy+r*Math.sin(ang)); ctx.stroke();
        ctx.beginPath(); ctx.arc(cx,cy,6,0,2*Math.PI);
        ctx.fillStyle='{needle_clr}'; ctx.fill();
        ctx.fillStyle='white'; ctx.font='bold 20px Rajdhani';
        ctx.textAlign='center';
        ctx.fillText(val.toFixed(2)+"{unit}",cx,cy-40);
    }}
    let cur={min_v};
    function anim(){{
        cur+=({v}-cur)*0.08; draw(cur);
        if(Math.abs(cur-{v})>0.001) requestAnimationFrame(anim);
    }}
    anim();
}})();
</script></body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
#  6. DATA EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

noaa                                              = fetch_openmeteo_current()
forecast, fc_ok, fc_err                           = fetch_nws_forecast()
rain_14d, rain_7d, snow_7d, rain_24h, rain_5d, _ = fetch_precip_history()
sm_07, sm_728, sm_ts, sm_ok                       = fetch_era5_soil_moisture()
usdm_level, usdm_label, usdm_date                 = fetch_usdm_drought()

# ── Soil saturation — 3-source ensemble ──────────────────────────────────────
soil_sat, soil_stored, soil_color, sm_sources = calc_soil_saturation_ensemble(
    sm_07, sm_728, sm_ok, rain_5d, usdm_level
)

# ERA5 layer percentages for display card (if available)
if sm_ok and sm_07 is not None:
    sm_range   = SOIL_POROSITY - SOIL_WILT_PT
    sm_07_c    = min(sm_07,  SOIL_POROSITY)
    sm_728_c   = min(sm_728, SOIL_POROSITY)
    sm_07_pct  = round(max(0, min(100, (sm_07_c  - SOIL_WILT_PT) / sm_range * 100)), 1)
    sm_728_pct = round(max(0, min(100, (sm_728_c - SOIL_WILT_PT) / sm_range * 100)), 1)
    sm_ts_str  = sm_ts[:13].replace("T", " ") + " UTC" if sm_ts else "---"
else:
    sm_07_c = sm_728_c = 0.0
    sm_07_pct = sm_728_pct = 0.0
    sm_ts_str = "ERA5 UNAVAILABLE"

# NWS forecast values
qpf_24h = forecast[0]["qpf"] if forecast else 0.0
pop_24h = forecast[0]["pop"] if forecast else 0.0

# Composite flood threat
threat      = flood_threat_score(soil_sat, qpf_24h, pop_24h)
t_lbl, t_clr, t_bg = threat_meta(threat)

# ── LOWER watershed model (full outlet, NCCAT) ────────────────────────────────
lo_depth, lo_flow = model_stream(
    soil_sat, rain_24h, qpf_24h, rain_7d,
    LO_DA_SQMI, LO_TC_HRS, LO_CN_II, LO_BASEFLOW, LO_RATING_A, LO_RATING_B, LO_BANKFULL_Q
)

# ── UPPER watershed model (headwaters sub-basin) ─────────────────────────────
up_depth, up_flow = model_stream(
    soil_sat, rain_24h, qpf_24h, rain_7d,
    UP_DA_SQMI, UP_TC_HRS, UP_CN_II, UP_BASEFLOW, UP_RATING_A, UP_RATING_B, UP_BANKFULL_Q
)

# Smoothed display values (damp 30s refresh jumps)
if "lo_depth" not in st.session_state: st.session_state.lo_depth = lo_depth
if "lo_flow"  not in st.session_state: st.session_state.lo_flow  = lo_flow
if "up_depth" not in st.session_state: st.session_state.up_depth = up_depth
if "up_flow"  not in st.session_state: st.session_state.up_flow  = up_flow

st.session_state.lo_depth = round(st.session_state.lo_depth * 0.30 + lo_depth * 0.70, 2)
st.session_state.lo_flow  = round(st.session_state.lo_flow  * 0.30 + lo_flow  * 0.70, 1)
st.session_state.up_depth = round(st.session_state.up_depth * 0.30 + up_depth * 0.70, 2)
st.session_state.up_flow  = round(st.session_state.up_flow  * 0.30 + up_flow  * 0.70, 1)

# Status labels — thresholds now tied to Ecoregion 66 bankfull values
lo_depth_lbl, lo_depth_clr = stage_status(st.session_state.lo_depth, LO_BANKFULL)
up_depth_lbl, up_depth_clr = stage_status(st.session_state.up_depth, UP_BANKFULL)
lo_flow_lbl,  lo_flow_clr  = flow_status(st.session_state.lo_flow,  LO_BANKFULL_Q)
up_flow_lbl,  up_flow_clr  = flow_status(st.session_state.up_flow,  UP_BANKFULL_Q)

# Fraction of bankfull for gauge arc display
lo_bkf_pct = round(min(100, st.session_state.lo_depth / LO_BANKFULL * 100), 1)
up_bkf_pct = round(min(100, st.session_state.up_depth / UP_BANKFULL * 100), 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  7. RENDER
# ═══════════════════════════════════════════════════════════════════════════════

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
  <div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
  <div class="site-sub">
    Cullowhee Creek Watershed &mdash; Jackson County, NC
    &nbsp;|&nbsp;
    {datetime.now().strftime("%A, %B %d %Y")} &mdash; {datetime.now().strftime("%H:%M:%S")}
    &nbsp;|&nbsp; TWO-POINT WATERSHED MODEL (PRE-SENSOR) &nbsp;|&nbsp;
    HYD. GEOMETRY: ECOREGION 66 BLUE RIDGE COMPOSITE
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 1: FLOOD THREAT BANNER ──────────────────────────────────────────────
st.markdown(f"""
<div style="background:{t_bg}; border:2px solid {t_clr}; border-radius:10px;
            padding:22px 30px; margin-bottom:16px; text-align:center;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.75em;
              color:{t_clr}; letter-spacing:4px; margin-bottom:6px;">
    COMPOSITE FLOOD THREAT SCORE
  </div>
  <div style="font-size:3.5em; font-weight:700; color:{t_clr};
              letter-spacing:5px; line-height:1.0;">
    {t_lbl}
  </div>
  <div style="background:rgba(255,255,255,0.08); border-radius:6px;
              height:8px; margin:12px auto; max-width:500px;">
    <div style="background:{t_clr}; width:{threat}%; height:8px; border-radius:6px;"></div>
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em;
              color:#7AACCC; margin-top:6px;">
    SOIL SAT {soil_sat:.1f}%
    &nbsp;&middot;&nbsp; QPF(24h) {qpf_24h:.2f}&quot;
    &nbsp;&middot;&nbsp; PoP {pop_24h:.0f}%
    &nbsp;&middot;&nbsp; LOWER {lo_bkf_pct:.0f}% of bankfull
    &nbsp;&middot;&nbsp; UPPER {up_bkf_pct:.0f}% of bankfull
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.68em;
              color:#3A6A8A; margin-top:10px; letter-spacing:1px;">
    EVALUATED FACTORS: Soil Saturation &middot; 24hr Rainfall Forecast &middot; Probability of Precipitation
    &nbsp;|&nbsp; BANKFULL REF: Ecoregion 66 Blue Ridge Composite (Henson et al. 2014 / SCDNR 2020)
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 2: ATMOSPHERIC CONDITIONS ──────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS &mdash; OPEN-METEO HRRR / ECMWF ERA5-LAND</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_dial(noaa["wind"],  "WIND SPEED",     0,  50, " mph", "#5AC8FA", src="OPEN-METEO"), use_container_width=True)
with c2: st.plotly_chart(make_dial(noaa["hum"],   "HUMIDITY",       0, 100, "%",    "#0077FF", src="OPEN-METEO"), use_container_width=True)
with c3: st.plotly_chart(make_dial(noaa["temp"],  "TEMPERATURE",    0, 110, " F",   "#FF3333", src="OPEN-METEO"), use_container_width=True)
with c4: st.plotly_chart(make_dial(rain_24h, "RAIN (24H)", 0, 10, '"', "#0077FF", sub="24-Hour Accumulation", src="HRRR BEST MATCH"), use_container_width=True)
with c5: st.plotly_chart(make_dial(soil_sat, "SOIL SATURATION", 0, 100, "%", "#0077FF", sub=f'{soil_stored:.2f}" Stored | ERA5-Land', src="ECMWF ERA5-LAND"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 3: UPPER WATERSHED — HEADWATERS ────────────────────────────────────
# Gauge arc ranges now anchored to Ecoregion 66 bankfull stage (2.16 ft)
_up_bkf  = UP_BANKFULL
_up_max  = _up_bkf * 2.5

st.markdown(
    f'<div class="upper-panel"><div class="upper-title">'
    f'UPPER CULLOWHEE CREEK &mdash; HEADWATERS SUB-BASIN '
    f'({UP_AREA_ACRES:,} AC | {UP_DA_SQMI:.2f} mi² | CN={UP_CN_II} | Tc={UP_TC_HRS}h) '
    f'&nbsp;|&nbsp; FLOOD LEAD TIME TO NCCAT: ~{FLOOD_TRAVEL_MIN} MIN'
    f'</div>',
    unsafe_allow_html=True
)
u1, u2, u3 = st.columns([2, 2, 3])
with u1:
    st.components.v1.html(make_stream_gauge(
        "g_up_depth", st.session_state.up_depth,
        "STREAM DEPTH", 0.0, _up_max, " ft",
        [{"range": [0.0,          _up_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_up_bkf*0.60, _up_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_up_bkf*0.95, _up_max],         "color": "rgba(255,51,51,0.25)"}],
        up_depth_clr, up_depth_lbl, up_depth_clr,
        f"Stage: {st.session_state.up_depth:.2f} ft  |  Bankfull: {UP_BANKFULL} ft  |  {up_bkf_pct:.0f}% bkf",
        "SCS-CN / RATIONAL METHOD / E66"
    ), height=240)
with u2:
    _up_q_max = UP_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_up_flow", st.session_state.up_flow,
        "DISCHARGE", 0.0, _up_q_max, " cfs",
        [{"range": [0.0,             UP_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [UP_BANKFULL_Q*0.45, UP_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [UP_BANKFULL_Q*0.95, _up_q_max],              "color": "rgba(255,51,51,0.25)"}],
        up_flow_clr, up_flow_lbl, up_flow_clr,
        f"Q: {st.session_state.up_flow:.1f} cfs  |  Qbkf (E66): {UP_BANKFULL_Q:.0f} cfs",
        "RATIONAL METHOD"
    ), height=240)
with u3:
    st.markdown('<div style="transform:scale(0.64); transform-origin:top left; width:156%;">', unsafe_allow_html=True)
    st.markdown("**UPPER SUB-WATERSHED PARAMETERS — ECOREGION 66 ANCHORED**")
    ua, ub = st.columns(2)
    ua.metric("Drainage Area",    f"{UP_AREA_ACRES:,} ac ({UP_DA_SQMI:.2f} mi²)", "~40% of total")
    ub.metric("Bankfull Q (E66)", f"{UP_BANKFULL_Q:.0f} cfs",                     "Henson 2014 / SCDNR 2020")
    uc, ud = st.columns(2)
    uc.metric("Bankfull Stage",   f"{UP_BANKFULL:.2f} ft",                         "E66 Dbkf_mean × 1.35")
    ud.metric("Width (E66)",      f"{UP_WIDTH_FT:.1f} ft",                          "Bankfull channel width")
    ue, uf = st.columns(2)
    ue.metric("Rating Curve A",   f"{UP_RATING_A:.1f}",                             f"B={UP_RATING_B} (Manning's)")
    uf.metric("Flood Lead Time",  f"~{FLOOD_TRAVEL_MIN} min",                       "to NCCAT outlet")
    st.caption(
        f"E66 composite: Qbkf=35.0×DA^0.850 | Wbkf=12.5×DA^0.460 | Dbkf=1.05×DA^0.310\n"
        f"Pre-calibration | K=Q_obs/Q_mod corrects after deployment | Reach scatter ±40-60%"
    )
    st.markdown('</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 4: LOWER WATERSHED — NCCAT OUTLET ──────────────────────────────────
# Gauge arc ranges anchored to Ecoregion 66 bankfull stage (2.87 ft)
_lo_bkf  = LO_BANKFULL
_lo_max  = _lo_bkf * 2.5

st.markdown(
    f'<div class="lower-panel"><div class="lower-title">'
    f'LOWER CULLOWHEE CREEK &mdash; FULL WATERSHED OUTLET AT NCCAT '
    f'({LO_AREA_ACRES:,} AC | {LO_DA_SQMI:.2f} mi² | CN={LO_CN_II} | Tc={LO_TC_HRS}h)'
    f'</div>',
    unsafe_allow_html=True
)
l1, l2, l3 = st.columns([2, 2, 3])
with l1:
    st.components.v1.html(make_stream_gauge(
        "g_lo_depth", st.session_state.lo_depth,
        "STREAM DEPTH", 0.0, _lo_max, " ft",
        [{"range": [0.0,          _lo_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_lo_bkf*0.60, _lo_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_lo_bkf*0.95, _lo_max],         "color": "rgba(255,51,51,0.25)"}],
        lo_depth_clr, lo_depth_lbl, lo_depth_clr,
        f"Stage: {st.session_state.lo_depth:.2f} ft  |  Bankfull: {LO_BANKFULL} ft  |  {lo_bkf_pct:.0f}% bkf",
        "SCS-CN / RATIONAL METHOD / E66"
    ), height=240)
with l2:
    _lo_q_max = LO_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_lo_flow", st.session_state.lo_flow,
        "DISCHARGE", 0.0, _lo_q_max, " cfs",
        [{"range": [0.0,             LO_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [LO_BANKFULL_Q*0.45, LO_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [LO_BANKFULL_Q*0.95, _lo_q_max],              "color": "rgba(255,51,51,0.25)"}],
        lo_flow_clr, lo_flow_lbl, lo_flow_clr,
        f"Q: {st.session_state.lo_flow:.1f} cfs  |  Qbkf (E66): {LO_BANKFULL_Q:.0f} cfs",
        "RATIONAL METHOD"
    ), height=240)
with l3:
    # Build source status strings
    _era5_str  = f"{sm_sources['era5_pct']:.0f}%" if sm_sources['era5_pct'] is not None else "UNAVAIL"
    _api_str   = f"{sm_sources['api_pct']:.0f}%"
    _usdm_str  = f"{sm_sources['usdm_pct']:.0f}%" if sm_sources['usdm_pct'] is not None else "N/A"
    _usdm_clr  = "#FF8800" if usdm_level >= 3 else "#FFD700" if usdm_level == 2 else "#FFFF00" if usdm_level == 1 else "#00FF9C"
    _usdm_tag  = usdm_label if usdm_level >= 0 else "NO DATA"
    _era5_active = "✓" if sm_ok and sm_07 is not None else "✗"
    _usdm_active = "✓" if usdm_level >= 0 else "✗"
    st.markdown(f"""
<div style="background:rgba(0,50,120,0.18); border:1px solid rgba(0,119,255,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#0077FF; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,119,255,0.2); padding-bottom:6px;">
    SOIL SATURATION — 3-SOURCE ENSEMBLE
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color}; text-align:center;
              margin:6px 0 4px;">{soil_sat:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:12px;">
    stored: {soil_stored:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
  <div style="display:grid; grid-template-columns:auto 1fr auto; gap:3px 8px;
              font-size:0.68em; align-items:center;">
    <span style="color:#3A8050;">{_era5_active}</span>
    <span style="color:#7AACCC;">ERA5-Land &nbsp;<span style="color:#2A5070;font-size:0.85em;">w={sm_sources['w_era5']:.0%}</span></span>
    <span style="color:#AACCDD;">{_era5_str}</span>
    <span style="color:#3A8050;">✓</span>
    <span style="color:#7AACCC;">API/HRRR 5-day &nbsp;<span style="color:#2A5070;font-size:0.85em;">w={sm_sources['w_api']:.0%}</span></span>
    <span style="color:#AACCDD;">{_api_str}</span>
    <span style="color:#3A8050;">{_usdm_active}</span>
    <span style="color:#7AACCC;">USDM &nbsp;<span style="color:#2A5070;font-size:0.85em;">w={sm_sources['w_usdm']:.0%}</span></span>
    <span style="color:#AACCDD;">{_usdm_str}</span>
  </div>
  <div style="margin-top:10px; padding-top:7px; border-top:1px solid rgba(0,80,160,0.25);
              font-size:0.65em; color:{_usdm_clr}; letter-spacing:1px;">
    USDM: {_usdm_tag}
  </div>
  <div style="font-size:0.60em; color:#2A4A60; margin-top:3px;">
    Jackson Co. NC (FIPS 37099) &nbsp;|&nbsp; {usdm_date if usdm_date != "---" else "no date"}
  </div>
  <div style="font-size:0.60em; color:#2A4A60; margin-top:1px;">
    ERA5 valid: {sm_ts_str}
  </div>
  <div style="margin-top:10px; padding-top:7px; border-top:1px solid rgba(0,80,160,0.25);
              font-size:0.62em; color:#1E5070; letter-spacing:1px; line-height:1.5;">
    E66 BANKFULL: {LO_BANKFULL_Q:.0f} cfs &nbsp;|&nbsp; stage {LO_BANKFULL:.2f} ft
    &nbsp;|&nbsp; W={LO_WIDTH_FT:.0f} ft &nbsp;|&nbsp; A={LO_RATING_A:.1f}·D^{LO_RATING_B}
    <br>DA={LO_DA_SQMI:.2f} mi² &nbsp;|&nbsp; Henson 2014 / SCDNR E66 2020
  </div>
</div>
""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 4B: ECOREGION 66 REGIONAL CURVE STATUS ─────────────────────────────
with st.expander("▶  ECOREGION 66 BLUE RIDGE REGIONAL CURVE DERIVATION", expanded=False):
    st.markdown(f"""
<div style="background:rgba(0,10,25,0.95); border:1px solid rgba(0,100,200,0.30);
            border-radius:9px; padding:18px 20px; font-family:'Share Tech Mono',monospace;">
  <div style="color:#0099FF; font-size:0.80em; letter-spacing:3px; margin-bottom:14px;
              border-bottom:1px solid rgba(0,100,200,0.25); padding-bottom:8px;">
    ECOREGION 66 (SOUTHERN BLUE RIDGE) COMPOSITE CURVES — DERIVATION AUDIT
  </div>
  <div style="font-size:0.70em; color:#3A7090; margin-bottom:12px; line-height:1.7;">
    Source: Henson et al. (2014) NC Mountain Streams + SCDNR Ecoregion 66 Blue Ridge Summary (May 2020)<br>
    50 stable reference reaches across Southern Blue Ridge physiographic province<br>
    Regression forms:
    &nbsp; Q<sub>bkf</sub> = 35.0 × DA<sup>0.850</sup> (cfs, R²≈0.87)
    &nbsp; W<sub>bkf</sub> = 12.5 × DA<sup>0.460</sup> (ft, R²≈0.88)
    &nbsp; D<sub>bkf</sub> = 1.05 × DA<sup>0.310</sup> (ft, mean riffle depth, R²≈0.82)<br>
    Bankfull stage = D<sub>bkf,mean</sub> × 1.35 (B/C cobble mountain stream depth ratio)
  </div>
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
    <div style="background:rgba(0,180,100,0.06); border:1px solid rgba(0,180,100,0.20);
                border-radius:7px; padding:12px;">
      <div style="color:#00CC77; font-size:0.72em; letter-spacing:2px; margin-bottom:8px;">UPPER — {UP_DA_SQMI:.3f} mi²</div>
      <div style="font-size:0.67em; color:#7AACCC; line-height:1.9;">
        Q<sub>bkf</sub> = 35.0 × {UP_DA_SQMI}^0.850 = <span style="color:#FFFFFF;">{_E66_UP['qbkf']:.1f} cfs</span><br>
        W<sub>bkf</sub> = 12.5 × {UP_DA_SQMI}^0.460 = <span style="color:#FFFFFF;">{_E66_UP['wbkf']:.1f} ft</span><br>
        D<sub>bkf,mean</sub> = 1.05 × {UP_DA_SQMI}^0.310 = <span style="color:#FFFFFF;">{_E66_UP['dbkf_mean']:.2f} ft</span><br>
        A<sub>bkf</sub> = {_E66_UP['wbkf']:.1f} × {_E66_UP['dbkf_mean']:.2f} = <span style="color:#FFFFFF;">{_E66_UP['abkf']:.1f} ft²</span><br>
        Stage<sub>bkf</sub> = {_E66_UP['dbkf_mean']:.2f} × 1.35 = <span style="color:#FFD700;">{_E66_UP['dbkf_stage']:.2f} ft</span><br>
        Rating A = {_E66_UP['qbkf']:.1f} / {_E66_UP['dbkf_stage']:.2f}^{UP_RATING_B} = <span style="color:#FFD700;">{UP_RATING_A:.1f}</span>
      </div>
    </div>
    <div style="background:rgba(0,100,200,0.06); border:1px solid rgba(0,119,255,0.20);
                border-radius:7px; padding:12px;">
      <div style="color:#0099FF; font-size:0.72em; letter-spacing:2px; margin-bottom:8px;">LOWER — {LO_DA_SQMI:.3f} mi²</div>
      <div style="font-size:0.67em; color:#7AACCC; line-height:1.9;">
        Q<sub>bkf</sub> = 35.0 × {LO_DA_SQMI}^0.850 = <span style="color:#FFFFFF;">{_E66_LO['qbkf']:.1f} cfs</span><br>
        W<sub>bkf</sub> = 12.5 × {LO_DA_SQMI}^0.460 = <span style="color:#FFFFFF;">{_E66_LO['wbkf']:.1f} ft</span><br>
        D<sub>bkf,mean</sub> = 1.05 × {LO_DA_SQMI}^0.310 = <span style="color:#FFFFFF;">{_E66_LO['dbkf_mean']:.2f} ft</span><br>
        A<sub>bkf</sub> = {_E66_LO['wbkf']:.1f} × {_E66_LO['dbkf_mean']:.2f} = <span style="color:#FFFFFF;">{_E66_LO['abkf']:.1f} ft²</span><br>
        Stage<sub>bkf</sub> = {_E66_LO['dbkf_mean']:.2f} × 1.35 = <span style="color:#FFD700;">{_E66_LO['dbkf_stage']:.2f} ft</span><br>
        Rating A = {_E66_LO['qbkf']:.1f} / {_E66_LO['dbkf_stage']:.2f}^{LO_RATING_B} = <span style="color:#FFD700;">{LO_RATING_A:.1f}</span>
      </div>
    </div>
  </div>
  <div style="margin-top:12px; padding-top:8px; border-top:1px solid rgba(0,80,160,0.25);
              font-size:0.62em; color:#2A5070; line-height:1.6; letter-spacing:0.5px;">
    ⚠ CAVEATS: Individual reach scatter ±40–60% around composite line. Post-Helene channel disturbance
    may shift Cullowhee Creek off regional mean. Carey et al. (2023) demonstrate that watershed slope
    and relief are significant additional predictors of channel morphology in the Southern Blue Ridge
    beyond drainage area alone (Int. J. River Basin Mgmt). K-correction from first 10–15 storm events
    will supersede these regional priors for each sensor point independently.
  </div>
</div>
""", unsafe_allow_html=True)


# ── PANEL 5: WATERSHED COMPARISON ────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">WATERSHED COMPARISON &mdash; UPPER vs LOWER SUB-BASIN | CULLOWHEE CREEK</div>', unsafe_allow_html=True)

dq     = round(st.session_state.lo_flow  - st.session_state.up_flow,  1)
dd     = round(st.session_state.lo_depth - st.session_state.up_depth, 2)
dq_pct = round((dq / st.session_state.up_flow * 100) if st.session_state.up_flow > 0 else 0, 1)

comp_clr_up = up_depth_clr
comp_clr_lo = lo_depth_clr

st.markdown(f"""
<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-bottom:8px;">

  <div style="background:rgba(0,180,100,0.07); border:1px solid rgba(0,180,100,0.25);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#00CC77;
                letter-spacing:2px; margin-bottom:8px;">UPPER — HEADWATERS</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">{UP_AREA_ACRES:,} ac | CN={UP_CN_II} | Tc={UP_TC_HRS}h</div>
    <div style="font-size:2.2em; font-weight:700; color:{comp_clr_up};">{st.session_state.up_depth:.2f} ft</div>
    <div style="font-size:1.1em; color:{up_flow_clr};">{st.session_state.up_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:{comp_clr_up};
                margin-top:6px; letter-spacing:2px;">{up_depth_lbl}</div>
    <div style="font-size:0.72em; color:#445566; margin-top:4px;">
      Bankfull: {UP_BANKFULL} ft &nbsp;|&nbsp; Q<sub>bkf</sub>: {UP_BANKFULL_Q:.0f} cfs
    </div>
    <div style="font-size:0.68em; color:#1A4A60; margin-top:2px;">
      {up_bkf_pct:.0f}% of bankfull &nbsp;|&nbsp; W={UP_WIDTH_FT:.0f} ft
    </div>
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.20);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0077FF;
                letter-spacing:2px; margin-bottom:8px;">DELTA (LOWER &minus; UPPER)</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">Watershed response amplification</div>
    <div style="font-size:2.2em; font-weight:700; color:#FFFF00;">{'+' if dd >= 0 else ''}{dd:.2f} ft</div>
    <div style="font-size:1.1em; color:#FFFF00;">{'+' if dq >= 0 else ''}{dq:.1f} cfs ({'+' if dq_pct >= 0 else ''}{dq_pct:.1f}%)</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.68em; color:#3A6A8A;
                margin-top:10px; line-height:1.6;">
      FLOOD TRAVEL TIME<br>
      <span style="color:#FFFF00; font-size:1.2em;">~{FLOOD_TRAVEL_MIN} MIN</span><br>
      UPPER &rarr; NCCAT
    </div>
    <div style="font-size:0.68em; color:#2A5070; margin-top:6px;">Pre-cal estimate | Will update on first event</div>
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.25);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0099FF;
                letter-spacing:2px; margin-bottom:8px;">LOWER — NCCAT OUTLET</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">{LO_AREA_ACRES:,} ac | CN={LO_CN_II} | Tc={LO_TC_HRS}h</div>
    <div style="font-size:2.2em; font-weight:700; color:{comp_clr_lo};">{st.session_state.lo_depth:.2f} ft</div>
    <div style="font-size:1.1em; color:{lo_flow_clr};">{st.session_state.lo_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:{comp_clr_lo};
                margin-top:6px; letter-spacing:2px;">{lo_depth_lbl}</div>
    <div style="font-size:0.72em; color:#445566; margin-top:4px;">
      Bankfull: {LO_BANKFULL} ft &nbsp;|&nbsp; Q<sub>bkf</sub>: {LO_BANKFULL_Q:.0f} cfs
    </div>
    <div style="font-size:0.68em; color:#1A4A60; margin-top:2px;">
      {lo_bkf_pct:.0f}% of bankfull &nbsp;|&nbsp; W={LO_WIDTH_FT:.0f} ft
    </div>
  </div>

</div>
<div style="font-family:'Share Tech Mono',monospace; font-size:0.68em; color:#2A5070;
            text-align:center; margin-top:6px; letter-spacing:1px;">
  MODEL: SCS TR-55 TYPE II PEAK FLOW + ECOREGION 66 RATING CURVE &middot;
  SOIL: ERA5-LAND + HRRR API + USDM ENSEMBLE &middot;
  CALIBRATION: K = Q<sub>obs</sub>/Q<sub>mod</sub> POST-SENSOR DEPLOYMENT
</div>
""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 6: 7-DAY FLOOD OUTLOOK ─────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED (NWS GSP GRIDPOINT)</div>', unsafe_allow_html=True)
if not fc_ok:
    st.warning(f"NWS forecast unavailable — {fc_err}")
elif forecast:
    pcols = st.columns(7)
    for i, d in enumerate(forecast):
        risk  = min(100.0, round((soil_sat * 0.35) + (d["pop"] * 0.35) + (d["qpf"] * 20), 2))
        color = "#00FF9C" if risk < 30 else "#FFFF00" if risk < 50 else "#FFD700" if risk < 65 else "#FF8800" if risk < 80 else "#FF3333"
        with pcols[i]:
            st.markdown(
                '<div style="background:rgba(255,255,255,0.03); border-top:4px solid '
                + color
                + '; border-radius:8px; padding:12px 8px; text-align:center;">'
                + '<div style="font-weight:700; font-size:1.1em;">' + d["short_name"] + '</div>'
                + '<div style="font-size:0.75em; color:#5A7090; margin-bottom:4px;">' + d["date"] + '</div>'
                + '<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.75em; color:#7AACCC; margin-bottom:4px;">' + nws_icon(d["icon_txt"]) + '</div>'
                + '<div style="color:' + color + '; font-size:1.55em; font-weight:700; margin:5px 0;">' + f'{risk:.1f}' + '%</div>'
                + '<div style="color:' + color + '; font-family:\'Share Tech Mono\',monospace; font-size:0.72em; letter-spacing:2px; margin-bottom:4px;">FLOOD RISK</div>'
                + '<div style="color:#00FFCC; font-family:\'Share Tech Mono\',monospace; font-size:0.85em;">' + f'{d["qpf"]:.2f}' + '&quot;</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["pop"]:.0f}' + '% PoP</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["temp"]:.0f}' + ' F</div>'
                + '</div>',
                unsafe_allow_html=True
            )
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 7: NEXRAD WSR-88D RADAR (KGSP) ─────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">NEXRAD WSR-88D RADAR &mdash; KGSP GREENVILLE-SPARTANBURG (NWS OPERATIONAL)</div>', unsafe_allow_html=True)
_cb = int(time.time() / 120)
st.components.v1.html(f"""
<div style="background:#04090F; border-radius:10px; border:1px solid #1a2a3a; overflow:hidden; font-family:'Courier New',monospace;">
  <div style="display:flex; align-items:center; justify-content:space-between;
              padding:8px 16px; background:#0a1520; border-bottom:1px solid #1a3a5a;">
    <div style="display:flex; align-items:center; gap:10px;">
      <div style="width:8px; height:8px; border-radius:50%; background:#00FF9C; box-shadow:0 0 6px #00FF9C;"></div>
      <span style="color:#00CFFF; font-size:11px; font-weight:700; letter-spacing:2px;">LIVE</span>
      <span style="color:#8899AA; font-size:11px; letter-spacing:1px;">| WSR-88D BASE REFLECTIVITY | KGSP | NWS GREENVILLE-SPARTANBURG</span>
    </div>
    <div style="color:#556677; font-size:10px; letter-spacing:1px;">AUTO-LOOP &#x21BB; 2 MIN</div>
  </div>
  <div style="position:relative; background:#000; text-align:center;">
    <img src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?v={_cb}"
         style="width:100%; max-height:520px; object-fit:contain; display:block;" alt="KGSP NEXRAD Loop" />
    <div style="position:absolute; bottom:0; left:0; right:0;
                background:linear-gradient(transparent,rgba(0,0,0,0.85));
                padding:20px 16px 8px; display:flex; justify-content:space-between; align-items:flex-end;">
      <div style="color:#667788; font-size:10px; letter-spacing:1px;">COVERAGE: WNC &bull; SC UPSTATE &bull; NW GA &bull; SW VA</div>
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
  <div style="padding:6px 16px; background:#0a1520; border-top:1px solid #1a3a5a;
              display:flex; justify-content:space-between;">
    <span style="color:#445566; font-size:10px; letter-spacing:1px;">SRC: radar.weather.gov &bull; NWS OPERATIONAL DATA</span>
    <span style="color:#445566; font-size:10px; letter-spacing:1px;">JACKSON CO. WATERSHED MONITORING SYSTEM &bull; NEMO / WCU</span>
  </div>
</div>
""", height=610)
st.markdown('</div>', unsafe_allow_html=True)
