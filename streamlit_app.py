"""
NOAH: Cullowhee Creek Flood Warning Dashboard
Western Carolina University — NEMO River Energy Initiative
Jackson County, NC — Watershed Monitoring System
"""

import math
import json
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

import requests
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh


# ═══════════════════════════════════════════════════════════════════════════════
#  1. CONFIGURATION & STYLING
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
ET_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

# -----------------------------------------------------------------------------
# REAL-TIME OBSERVED RAIN CONFIG
# -----------------------------------------------------------------------------
REALTIME_RAIN_STATIONS = [
    {
        "name": "Primary Basin Rain",
        "type": "custom_json",
        "weight": 1.0,
        "current_url": "",
        "history_url": "",
    },
    {
        "name": "Secondary Basin Rain",
        "type": "custom_json",
        "weight": 1.0,
        "current_url": "",
        "history_url": "",
    },
    {
        "name": "Cullowhee PWS",
        "type": "weathercom_pws",
        "weight": 1.0,
        "station_id": "KNCCULLO7",
        "api_key": "",
    },
    {
        "name": "Sylva PWS",
        "type": "weathercom_pws",
        "weight": 1.0,
        "station_id": "KNCSYLVA86",
        "api_key": "",
    },
]

REQUEST_TIMEOUT_SEC = 10

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');

html, body, .stApp {
    background-color: #04090F;
    color: #E0E8F0;
    font-family: 'Rajdhani', sans-serif;
}

.site-header {
    border-left: 6px solid #0077FF;
    padding: 14px 22px;
    margin-bottom: 20px;
    background: rgba(0,100,200,0.07);
    border-radius: 0 8px 8px 0;
}
.site-title  {
    font-size: 2.4em;
    font-weight: 700;
    color: #FFFFFF;
    margin: 0;
    letter-spacing: 2px;
}
.site-sub    {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.75em;
    color: #5AACD0;
    margin-top: 4px;
}

.panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,119,255,0.18);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.panel-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #0077FF;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,119,255,0.18);
    padding-bottom: 8px;
    margin-bottom: 14px;
}

.upper-panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,180,100,0.25);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.upper-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #00CC77;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,180,100,0.25);
    padding-bottom: 8px;
    margin-bottom: 14px;
}

.lower-panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,119,255,0.25);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.lower-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #0099FF;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,119,255,0.25);
    padding-bottom: 8px;
    margin-bottom: 14px;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. WATERSHED & SOIL CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SOIL_POROSITY  = 0.439
SOIL_FIELD_CAP = 0.286
SOIL_WILT_PT   = 0.151

LO_AREA_ACRES      = 6200
LO_DA_SQMI         = 9.688
LO_TC_HRS          = 2.5
LO_CN_II           = 68
LO_RATING_A        = 21.4
LO_RATING_B        = 2.30
LO_BASEFLOW        = 9.0
LO_BANKFULL        = 2.87
LO_BANKFULL_Q      = 241.2

UP_AREA_ACRES      = 2480
UP_DA_SQMI         = 3.875
UP_TC_HRS          = 1.2
UP_CN_II           = 62
UP_RATING_A        = 21.2
UP_RATING_B        = 2.15
UP_BASEFLOW        = 3.5
UP_BANKFULL        = 2.16
UP_BANKFULL_Q      = 110.7

FLOOD_TRAVEL_MIN   = 65

_USDM_IMPLIED_SAT = {1: 55.0, 2: 40.0, 3: 27.0, 4: 17.0, 5: 8.0}
_USDM_CEILING     = {0: 100, 1: 65, 2: 50, 3: 35, 4: 22, 5: 12}

_TR55_IAPRATIO = [0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50]
_TR55_C0       = [2.55323, 2.23537, 2.10304, 2.18219, 2.17339, 2.16251, 2.14583]
_TR55_C1       = [-0.61512, -0.50537, -0.51488, -0.50258, -0.48985, -0.47856, -0.46772]
_TR55_C2       = [-0.16403, -0.11657, -0.08648, -0.09057, -0.09084, -0.09303, -0.09373]


# ═══════════════════════════════════════════════════════════════════════════════
#  3. HIDDEN FORECAST ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def _hours_ahead(target_dt: datetime, now_dt: datetime) -> float:
    return (target_dt - now_dt).total_seconds() / 3600.0


def _choose_bucket(lead_hours: float) -> str:
    if lead_hours <= 18:
        return "short_range"
    elif lead_hours <= 48:
        return "mid_range"
    return "extended"


def _weighted_merge(a: dict, b: dict, wa: float, wb: float) -> dict:
    total = wa + wb
    return {
        "time": a["time"],
        "temp_f": (a["temp_f"] * wa + b["temp_f"] * wb) / total,
        "qpf_in": (a["qpf_in"] * wa + b["qpf_in"] * wb) / total,
        "pop":    (a["pop"] * wa + b["pop"] * wb) / total,
        "icon_txt": b.get("icon_txt", a.get("icon_txt", "")),
    }


@st.cache_data(ttl=900)
def _fetch_hidden_short_range_hourly():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "temperature_2m,precipitation,precipitation_probability",
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "forecast_days": 3,
            },
            timeout=15,
        ).json()

        times = r["hourly"]["time"]
        temp  = r["hourly"]["temperature_2m"]
        qpf   = r["hourly"]["precipitation"]
        pop   = r["hourly"].get("precipitation_probability", [0] * len(times))

        out = []
        for i, t in enumerate(times):
            try:
                ts = datetime.fromisoformat(t).replace(tzinfo=UTC_TZ).astimezone(ET_TZ)
                out.append({
                    "time": ts,
                    "temp_f": float(temp[i] or 0.0),
                    "qpf_in": float(qpf[i] or 0.0),
                    "pop": float(pop[i] or 0.0),
                    "icon_txt": "",
                })
            except Exception:
                continue
        return out
    except Exception:
        return []


@st.cache_data(ttl=1800)
def _fetch_hidden_daily_forecast():
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0"}
        pts = requests.get(
            f"https://api.weather.gov/points/{LAT},{LON}",
            headers=hdrs,
            timeout=10
        ).json()["properties"]

        periods = requests.get(
            pts["forecast"],
            headers=hdrs,
            timeout=10
        ).json()["properties"]["periods"]

        grid = requests.get(
            pts["forecastGridData"],
            headers=hdrs,
            timeout=15
        ).json()["properties"]

        qpf_by_date = defaultdict(float)
        for entry in grid.get("quantitativePrecipitation", {}).get("values", []):
            vt = entry["validTime"].split("/")[0]
            val = entry["value"] or 0.0
            try:
                d = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                qpf_by_date[d] += float(val) * 0.0393701
            except Exception:
                pass

        temp_by_date = {}
        for entry in grid.get("maxTemperature", {}).get("values", []):
            vt = entry["validTime"].split("/")[0]
            val = entry["value"]
            if val is None:
                continue
            try:
                d = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                tf = float(val) * 9 / 5 + 32
                if d not in temp_by_date or tf > temp_by_date[d]:
                    temp_by_date[d] = tf
            except Exception:
                pass

        out = []
        seen = set()
        for p in periods:
            if not p.get("isDaytime", False):
                continue
            try:
                dt = datetime.fromisoformat(p["startTime"]).astimezone(ET_TZ)
                dkey = dt.strftime("%Y-%m-%d")
                if dkey in seen:
                    continue
                seen.add(dkey)
                out.append({
                    "time": dt.replace(hour=12, minute=0, second=0, microsecond=0),
                    "date": dkey,
                    "short_name": dt.strftime("%a").upper(),
                    "date_label": dt.strftime("%m/%d"),
                    "temp_f": round(float(temp_by_date.get(dkey, p["temperature"])), 1),
                    "qpf_in": round(float(qpf_by_date.get(dkey, 0.0)), 2),
                    "pop": round(float((p.get("probabilityOfPrecipitation") or {}).get("value") or 0), 1),
                    "icon_txt": str(p.get("shortForecast", "")),
                })
            except Exception:
                continue

        return out[:7]
    except Exception:
        return []


def _build_unified_daily_forecast():
    now_et = datetime.now(ET_TZ)
    hourly = _fetch_hidden_short_range_hourly()
    daily  = _fetch_hidden_daily_forecast()

    hourly_by_day = defaultdict(list)
    for r in hourly:
        lead = _hours_ahead(r["time"], now_et)
        if -3 <= lead <= 60:
            hourly_by_day[r["time"].strftime("%Y-%m-%d")].append(r)

    short_daily = {}
    for dkey, rows in hourly_by_day.items():
        dt = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        short_daily[dkey] = {
            "time": dt,
            "date": dkey,
            "short_name": dt.strftime("%a").upper(),
            "date_label": dt.strftime("%m/%d"),
            "temp_f": round(max(r["temp_f"] for r in rows), 1),
            "qpf_in": round(sum(r["qpf_in"] for r in rows), 2),
            "pop": round(max(r["pop"] for r in rows), 1),
            "icon_txt": "",
        }

    daily_map = {r["date"]: r for r in daily}
    all_dates = sorted(set(short_daily) | set(daily_map))

    unified = []
    for dkey in all_dates:
        target = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        lead = _hours_ahead(target, now_et)

        short_rec = short_daily.get(dkey)
        daily_rec = daily_map.get(dkey)

        if 12 <= lead <= 18 and short_rec and daily_rec:
            wb = (lead - 12) / 6.0
            wa = 1.0 - wb
            merged = _weighted_merge(short_rec, daily_rec, wa, wb)
            merged.update({
                "date": dkey,
                "short_name": target.strftime("%a").upper(),
                "date_label": target.strftime("%m/%d"),
            })
            unified.append(merged)
        elif _choose_bucket(lead) == "short_range" and short_rec:
            unified.append(short_rec)
        elif daily_rec:
            unified.append(daily_rec)
        elif short_rec:
            unified.append(short_rec)

    return unified[:7]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. DATA ACQUISITION
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_current_conditions():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                           "wind_direction_10m,surface_pressure,precipitation,"
                           "weather_code,wind_gusts_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "forecast_days": 1,
            },
            timeout=10
        ).json()

        c = r["current"]
        return {
            "ok":        True,
            "temp":      round(float(c.get("temperature_2m", 50)), 1),
            "hum":       round(float(c.get("relative_humidity_2m", 50)), 1),
            "wind":      round(float(c.get("wind_speed_10m", 0)), 1),
            "wind_gust": round(float(c.get("wind_gusts_10m", 0)), 1),
            "wind_dir":  round(float(c.get("wind_direction_10m", 0)), 1),
            "press":     round(c.get("surface_pressure", 1013.25) * 0.02953, 2),
            "precip":    round(float(c.get("precipitation", 0)), 1),
            "wcode":     c.get("weather_code", 0),
        }
    except Exception:
        return {
            "ok": False, "temp": 50.0, "hum": 50.0, "wind": 0.0,
            "wind_gust": 0.0, "wind_dir": 0.0, "press": 29.92,
            "precip": 0.0, "wcode": 0
        }


@st.cache_data(ttl=1800)
def fetch_backup_precip_history():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "precipitation,snowfall",
                "precipitation_unit": "inch",
                "past_days": 14,
                "forecast_days": 1,
                "models": "best_match",
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
            s = (snow_h[i] or 0.0) * 0.0393701
            if age <= 14:
                t14d += p
            if age <= 7:
                t7d += p
                snow7d += s
            if age <= 5:
                t5d += p
            if age <= 1:
                t24h += p

        return {
            "ok": True,
            "rain_14d_in": round(t14d, 2),
            "rain_7d_in": round(t7d, 2),
            "rain_5d_in": round(t5d, 2),
            "rain_24h_in": round(t24h, 2),
            "snow_7d_in": round(snow7d, 2),
        }
    except Exception:
        return {
            "ok": False,
            "rain_14d_in": 2.10,
            "rain_7d_in": 0.50,
            "rain_5d_in": 0.50,
            "rain_24h_in": 0.00,
            "snow_7d_in": 0.00,
        }


@st.cache_data(ttl=3600)
def fetch_era5_soil_moisture():
    try:
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=14)
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
                "models": "era5_land",
                "start_date": start_dt.strftime("%Y-%m-%d"),
                "end_date": end_dt.strftime("%Y-%m-%d"),
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
    try:
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=21)
        r = requests.get(
            "https://usdmdataservices.unl.edu/api/CountyStatistics/"
            "GetDroughtSeverityStatisticsByAreaPercent",
            params={
                "aoi": "37099",
                "startdate": start_dt.strftime("%m/%d/%Y"),
                "enddate": end_dt.strftime("%m/%d/%Y"),
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


@st.cache_data(ttl=300)
def fetch_active_alerts():
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0"}
        r = requests.get(
            "https://api.weather.gov/alerts/active",
            params={"point": f"{LAT},{LON}"},
            headers=hdrs,
            timeout=10
        ).json()

        feats = r.get("features", [])
        alerts = []

        for feat in feats:
            props = feat.get("properties", {})
            event = str(props.get("event", "")).strip()
            headline = str(props.get("headline", "")).strip()
            expires = str(props.get("expires", "")).strip()
            desc = str(props.get("description", "")).strip()

            if not event:
                continue

            short_desc = " ".join(desc.split())
            if len(short_desc) > 180:
                short_desc = short_desc[:177] + "..."

            expires_local = ""
            if expires:
                try:
                    dt = datetime.fromisoformat(expires.replace("Z", "+00:00")).astimezone(ET_TZ)
                    expires_local = dt.strftime("%b %d, %I:%M %p")
                except Exception:
                    expires_local = ""

            alerts.append({
                "event": event,
                "headline": headline,
                "expires_local": expires_local,
                "description": short_desc,
            })

        severity_rank = {
            "flash flood warning": 5,
            "flood warning": 5,
            "severe thunderstorm warning": 4,
            "tornado warning": 5,
            "flash flood watch": 3,
            "flood watch": 3,
            "wind advisory": 2,
            "flood advisory": 2,
            "special weather statement": 1,
        }

        alerts.sort(key=lambda a: severity_rank.get(a["event"].lower(), 0), reverse=True)
        return alerts
    except Exception:
        return []


@st.cache_data(ttl=900)
def fetch_hazardous_weather_outlook():
    """
    Pulls the latest Hazardous Weather Outlook from the NWS Products API
    for the GSP (Greenville-Spartanburg) WFO.
    Returns dict with 'issued' (str) and 'paragraphs' (list of {header, body}),
    or None if unavailable.
    """
    import re
    from html import escape as html_escape

    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0 (WCU NEMO Project)"}

        # Step 1 — list recent HWO products from GSP
        index = requests.get(
            "https://api.weather.gov/products/types/HWO/locations/GSP",
            headers=hdrs,
            timeout=10,
        ).json()

        graph = index.get("@graph", [])
        if not graph:
            return None

        # Step 2 — fetch most recent product
        latest_id = graph[0].get("id", "")
        if not latest_id:
            return None

        prod = requests.get(
            f"https://api.weather.gov/products/{latest_id}",
            headers=hdrs,
            timeout=10,
        ).json()

        raw = prod.get("productText", "")
        if not raw:
            return None

        # Step 3 — parse issuance time from API metadata (clean, no scraping)
        issued_str = ""
        issued_raw = prod.get("issuanceTime", "")
        if issued_raw:
            try:
                dt = datetime.fromisoformat(
                    issued_raw.replace("Z", "+00:00")
                ).astimezone(ET_TZ)
                issued_str = dt.strftime("%b %d, %Y  %I:%M %p ET")
            except Exception:
                issued_str = issued_raw[:16]

        # Step 4 — normalise line endings
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")

        # Step 5 — skip EVERYTHING before the first .DAY / .DAYS / .THIS section
        #           marker. This discards the WMO bulletin header, AWIPS ID,
        #           product title, NWS office line, issue time, UGC zone string,
        #           expiration timestamp — all the preamble garbage.
        first_section = re.search(
            r"(?m)^\.(DAY|DAYS|THIS)\b", raw, re.IGNORECASE
        )
        if not first_section:
            return None   # no recognised section structure → skip
        body = raw[first_section.start():]

        # Step 6 — cut at spotter statement / $$
        stop_pat = re.compile(
            r"(?m)(^\.(SPOTTER INFORMATION STATEMENT)|^\$\$)",
            re.IGNORECASE
        )
        m = stop_pat.search(body)
        if m:
            body = body[: m.start()]

        # Step 7 — split on section markers (.DAY ONE..., .DAYS TWO THROUGH..., etc.)
        #           re.split with a capturing group keeps the delimiters in the list.
        parts = re.split(r"(?m)(^\.[A-Z][A-Z0-9 ]+\.\.\.)", body)
        # parts = [pre, header1, block1, header2, block2, ...]
        # The first element is any text before the first header (usually empty).

        paragraphs = []
        i = 0
        # skip any leading non-header text
        if parts and not re.match(r"^\.[A-Z]", parts[0].strip()):
            i = 1
        while i < len(parts):
            raw_header = parts[i].strip()
            raw_body   = parts[i + 1].strip() if i + 1 < len(parts) else ""
            i += 2

            # Clean up body: collapse runs of blank lines to one, strip leading/trailing
            raw_body = re.sub(r"\n{3,}", "\n\n", raw_body).strip()

            if not raw_body:
                continue

            # HTML-escape both header and body so special chars (<, >, &, etc.)
            # render as text, not as HTML tags
            paragraphs.append({
                "header": html_escape(raw_header),
                "body":   html_escape(raw_body),
            })

        if not paragraphs:
            return None

        return {
            "issued":     issued_str,
            "paragraphs": paragraphs,
        }

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  4B. OBSERVED RAIN ADAPTERS
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_rain_value(x, min_v=0.0, max_v=50.0):
    try:
        v = float(x)
        if math.isnan(v) or v < min_v or v > max_v:
            return None
        return v
    except Exception:
        return None


def _fetch_custom_json_station(station_cfg: dict) -> dict:
    current_url = station_cfg.get("current_url", "").strip()
    history_url = station_cfg.get("history_url", "").strip()

    if not current_url and not history_url:
        return {"ok": False}

    out = {"ok": False}

    try:
        if current_url:
            rc = requests.get(current_url, timeout=REQUEST_TIMEOUT_SEC).json()
            out["rain_rate_in_hr"] = _clean_rain_value(rc.get("rain_rate_in_hr"), 0, 15)
            out["rain_1h_in"]      = _clean_rain_value(rc.get("rain_1h_in"), 0, 15)
            out["rain_24h_in"]     = _clean_rain_value(rc.get("rain_24h_in"), 0, 30)
    except Exception:
        pass

    try:
        if history_url:
            rh = requests.get(history_url, timeout=REQUEST_TIMEOUT_SEC).json()
            out["rain_24h_in"] = _clean_rain_value(rh.get("rain_24h_in", out.get("rain_24h_in")), 0, 30)
            out["rain_3d_in"]  = _clean_rain_value(rh.get("rain_3d_in"), 0, 40)
            out["rain_5d_in"]  = _clean_rain_value(rh.get("rain_5d_in"), 0, 50)
            out["rain_7d_in"]  = _clean_rain_value(rh.get("rain_7d_in"), 0, 60)
            out["rain_14d_in"] = _clean_rain_value(rh.get("rain_14d_in"), 0, 80)
    except Exception:
        pass

    out["ok"] = any(out.get(k) is not None for k in [
        "rain_rate_in_hr", "rain_1h_in", "rain_24h_in", "rain_3d_in",
        "rain_5d_in", "rain_7d_in", "rain_14d_in"
    ])
    return out


def _fetch_weathercom_pws_station(station_cfg: dict) -> dict:
    station_id = station_cfg.get("station_id", "").strip()
    api_key    = station_cfg.get("api_key", "").strip()

    if not station_id or not api_key:
        return {"ok": False}

    out = {"ok": False}

    try:
        current = requests.get(
            "https://api.weather.com/v2/pws/observations/current",
            params={
                "stationId": station_id,
                "format": "json",
                "units": "e",
                "numericPrecision": "decimal",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT_SEC,
        ).json()

        obs = (current.get("observations") or [{}])[0]
        imperial = obs.get("imperial", {})
        out["rain_rate_in_hr"] = _clean_rain_value(imperial.get("precipRate"), 0, 15)
        out["rain_1h_in"]      = _clean_rain_value(imperial.get("precipTotal"), 0, 15)
        out["rain_24h_in"]     = _clean_rain_value(imperial.get("precipTotal"), 0, 30)
    except Exception:
        pass

    try:
        hist = requests.get(
            "https://api.weather.com/v2/pws/observations/hourly/7day",
            params={
                "stationId": station_id,
                "format": "json",
                "units": "e",
                "numericPrecision": "decimal",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT_SEC,
        ).json()

        rows = hist.get("observations", [])
        if rows:
            hourly = []
            now_et = datetime.now(ET_TZ)
            for row in rows:
                try:
                    ts_utc = datetime.fromtimestamp(int(row["epoch"]), tz=UTC_TZ)
                    ts_et = ts_utc.astimezone(ET_TZ)
                    age_hr = (now_et - ts_et).total_seconds() / 3600.0
                    if age_hr < 0:
                        continue
                    imperial = row.get("imperial", {})
                    p = _clean_rain_value(imperial.get("precipTotal"), 0, 10)
                    if p is None:
                        p = 0.0
                    hourly.append((age_hr, p))
                except Exception:
                    continue

            rain_24h = sum(p for age, p in hourly if age <= 24)
            rain_72h = sum(p for age, p in hourly if age <= 72)
            rain_5d  = sum(p for age, p in hourly if age <= 120)
            rain_7d  = sum(p for age, p in hourly if age <= 168)

            out["rain_24h_in"] = _clean_rain_value(rain_24h, 0, 30)
            out["rain_3d_in"]  = _clean_rain_value(rain_72h, 0, 40)
            out["rain_5d_in"]  = _clean_rain_value(rain_5d, 0, 50)
            out["rain_7d_in"]  = _clean_rain_value(rain_7d, 0, 60)
    except Exception:
        pass

    out["ok"] = any(out.get(k) is not None for k in [
        "rain_rate_in_hr", "rain_1h_in", "rain_24h_in", "rain_3d_in",
        "rain_5d_in", "rain_7d_in"
    ])
    return out


@st.cache_data(ttl=300)
def fetch_realtime_station_bundle():
    station_results = []

    for cfg in REALTIME_RAIN_STATIONS:
        stype = cfg.get("type", "").strip().lower()
        if stype == "custom_json":
            res = _fetch_custom_json_station(cfg)
        elif stype == "weathercom_pws":
            res = _fetch_weathercom_pws_station(cfg)
        else:
            res = {"ok": False}

        if res.get("ok", False):
            res["weight"] = float(cfg.get("weight", 1.0))
            station_results.append(res)

    if not station_results:
        return {"ok": False, "count": 0}

    def weighted_mean(key):
        vals = [(r[key], r["weight"]) for r in station_results if r.get(key) is not None]
        if not vals:
            return None
        wsum = sum(w for _, w in vals)
        if wsum <= 0:
            return None
        return round(sum(v * w for v, w in vals) / wsum, 2)

    return {
        "ok": True,
        "count": len(station_results),
        "rain_rate_in_hr": weighted_mean("rain_rate_in_hr"),
        "rain_1h_in": weighted_mean("rain_1h_in"),
        "rain_24h_in": weighted_mean("rain_24h_in"),
        "rain_3d_in": weighted_mean("rain_3d_in"),
        "rain_5d_in": weighted_mean("rain_5d_in"),
        "rain_7d_in": weighted_mean("rain_7d_in"),
        "rain_14d_in": weighted_mean("rain_14d_in"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  5. HYDRO-MODELING
# ═══════════════════════════════════════════════════════════════════════════════

def calc_era5_sat_pct(sm_07, sm_728):
    sm_07  = min(sm_07, SOIL_POROSITY)
    sm_728 = min(sm_728, SOIL_POROSITY)
    sm_avg = min((sm_07 * 0.55) + (sm_728 * 0.45), SOIL_POROSITY)
    sat_range = SOIL_POROSITY - SOIL_WILT_PT
    return round(min(100.0, max(0.0, (sm_avg - SOIL_WILT_PT) / sat_range * 100)), 1)


def calc_api_sat_pct(rain_5d):
    a = min(float(rain_5d), 5.0)
    if a < 0.30:
        sat = 10.0 + a * 33.3
    elif a < 1.00:
        sat = 20.0 + (a - 0.30) / 0.70 * 18.0
    elif a < 2.10:
        sat = 38.0 + (a - 1.00) / 1.10 * 17.0
    elif a < 2.80:
        sat = 55.0 + (a - 2.10) / 0.70 * 13.0
    else:
        sat = 68.0 + (a - 2.80) / 2.20 * 22.0
    return round(min(90.0, max(5.0, sat)), 1)


def calc_soil_saturation_ensemble(sm_07, sm_728, sm_ok, rain_5d, usdm_level):
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
        w_api += w_era5
        w_era5 = 0.0
        era5_use = api_pct
    else:
        era5_use = era5_pct

    if usdm_pct is None:
        w_api += w_usdm
        w_usdm = 0.0
        usdm_use = api_pct
    else:
        usdm_use = usdm_pct

    sat_pct = (era5_use * w_era5) + (api_pct * w_api) + (usdm_use * w_usdm)
    ceiling = _USDM_CEILING.get(max(0, usdm_level), 100)
    sat_pct = min(sat_pct, ceiling)
    sat_pct = round(min(100.0, max(1.0, sat_pct)), 1)

    if sm_ok and sm_07 is not None:
        sm_07c    = min(sm_07, SOIL_POROSITY)
        sm_728c   = min(sm_728, SOIL_POROSITY)
        stored_in = round((sm_07c * 2.756) + (sm_728c * 8.268), 2)
    else:
        stored_in = round((sat_pct / 100.0) * (SOIL_POROSITY * 11.024), 2)

    color = "#FF3333" if sat_pct > 85 else "#FF8800" if sat_pct > 70 else "#FFD700" if sat_pct > 50 else "#00FF9C"

    return sat_pct, stored_in, color


def _tr55_unit_peak(tc_hrs: float, ia_p: float) -> float:
    ia_p   = max(0.10, min(0.50, float(ia_p)))
    tc_hrs = max(0.10, min(10.0, float(tc_hrs)))
    lt     = math.log10(tc_hrs)

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
    if soil_sat_pct < 30:
        cn_adj = max(50.0, cn_ii * 0.87)
    elif soil_sat_pct < 65:
        cn_adj = float(cn_ii)
    else:
        cn_adj = min(95.0, (23.0 * cn_ii) / (10.0 + 0.13 * cn_ii))

    P  = max(0.0, rain_24h + qpf_24h)
    S  = (1000.0 / cn_adj) - 10.0
    Ia = 0.2 * S

    if P > Ia:
        Q_runoff_in = (P - Ia) ** 2 / (P - Ia + S)
    else:
        Q_runoff_in = 0.0

    if Q_runoff_in > 0.0 and P > 0.0:
        ia_p    = min(0.50, max(0.10, Ia / P))
        qu      = _tr55_unit_peak(tc_hrs, ia_p)
        Q_storm = qu * da_sqmi * Q_runoff_in
    else:
        Q_storm = 0.0

    Q_base   = baseflow * (1.0 + (soil_sat_pct / 100.0) * 3.0)
    Q_recess = max(0.0, (rain_7d - rain_24h) * baseflow * 0.25)
    Q_max    = bankfull_q * 3.0
    Q_total  = round(max(baseflow * 0.5, min(Q_base + Q_storm + Q_recess, Q_max)), 1)
    depth_ft = round(max(0.20, min((Q_total / rating_a) ** (1.0 / rating_b), 9.0)), 2)

    return depth_ft, Q_total


def flood_threat_score(soil_sat, qpf_24h, pop_24h):
    return round(min(100.0,
        (soil_sat * 0.40) +
        (min(100.0, qpf_24h * 40) * 0.35) +
        (pop_24h * 0.25)
    ), 1)


def threat_meta(score):
    if score < 25:
        return "NORMAL", "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45:
        return "ELEVATED", "#FFFF00", "rgba(255,255,0,0.09)"
    if score < 65:
        return "WATCH", "#FFD700", "rgba(255,215,0,0.09)"
    if score < 82:
        return "WARNING", "#FF8800", "rgba(255,136,0,0.11)"
    return "EMERGENCY", "#FF3333", "rgba(255,51,51,0.14)"


def stage_status(depth_ft, bankfull_ft):
    ratio = depth_ft / bankfull_ft
    if ratio < 0.45:
        return "LOW FLOW", "#00FF9C"
    if ratio < 0.65:
        return "NORMAL", "#00FF9C"
    if ratio < 0.80:
        return "ELEVATED", "#FFFF00"
    if ratio < 0.95:
        return "WATCH", "#FFD700"
    return "FLOOD", "#FF3333"


def flow_status(q, bankfull_q):
    if q < bankfull_q * 0.15:
        return "LOW FLOW", "#00FF9C"
    if q < bankfull_q * 0.45:
        return "NORMAL", "#00FF9C"
    if q < bankfull_q * 0.85:
        return "ELEVATED", "#FFFF00"
    if q < bankfull_q * 1.00:
        return "WATCH", "#FFD700"
    return "FLOOD", "#FF3333"


def forecast_icon(txt):
    t = str(txt).lower()
    if any(x in t for x in ["thunder", "storm"]):
        return "TSTM"
    if any(x in t for x in ["snow", "blizzard"]):
        return "SNOW"
    if any(x in t for x in ["sleet", "freezing"]):
        return "SLEET"
    if any(x in t for x in ["fog", "haze"]):
        return "FOG"
    if "shower" in t:
        return "SHWRS"
    if any(x in t for x in ["rain", "drizzle"]):
        return "RAIN"
    if "partly cloudy" in t:
        return "PTCLDY"
    if "mostly cloudy" in t:
        return "MSTCLDY"
    if "cloudy" in t:
        return "CLOUDY"
    if any(x in t for x in ["sunny", "clear"]):
        return "SUNNY"
    return "---"


# ═══════════════════════════════════════════════════════════════════════════════
#  6. UI COMPONENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def make_dial(v, t, min_v, max_v, u, c, sub=""):
    parts = [f"<b>{t}</b>"]
    if sub:
        parts.append(f"<span style='font-size:11px;color:#7AACCC'>{sub}</span>")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": u, "font": {"size": 24, "color": "white"}, "valueformat": ".1f"},
        title={"text": "<br>".join(parts), "font": {"size": 13, "color": "#A0C8E0"}},
        gauge={
            "axis": {"range": [min_v, max_v], "tickfont": {"size": 9, "color": "#334455"}},
            "bar": {"color": c, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=70, b=20, l=25, r=25),
        height=185
    )
    return fig


def make_stream_gauge(gid, v, min_v, max_v, unit, ranges, needle_clr,
                      status_lbl, status_clr, sub_line):
    t_js = json.dumps(
        [{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in ranges]
    )
    # Oscillation amplitude: 0.8% of total range — subtle but visible
    osc_amp = round((max_v - min_v) * 0.008, 4)
    # Arc pulse: dim ↔ bright cycle on the active arc segment
    return f"""<html><body style="background:transparent;text-align:center;
font-family:'Rajdhani',sans-serif;color:white;margin:0;padding:0;">
<canvas id="{gid}" width="260" height="150"></canvas>
<div id="{gid}_lbl" style="color:{status_clr};font-weight:700;font-size:16px;
     text-transform:uppercase;letter-spacing:2px;">{status_lbl}</div>
<div style="font-size:12px;color:#7AACCC;margin-top:4px;">{sub_line}</div>
<script>
(function(){{
    const canvas = document.getElementById('{gid}');
    const ctx    = canvas.getContext('2d');
    const cx=130, cy=125, r=95;
    const TARGET = {v};
    const MIN_V  = {min_v};
    const MAX_V  = {max_v};
    const AMP    = {osc_amp};        // sine oscillation amplitude
    const RANGES = {t_js};

    function toA(val){{
        return Math.PI + ((val - MIN_V) / (MAX_V - MIN_V)) * Math.PI;
    }}

    let cur      = MIN_V;            // start from zero → eases in
    let t0       = null;
    let phase    = Math.random() * Math.PI * 2;   // random start phase

    function draw(ts){{
        if(!t0) t0 = ts;
        const elapsed = (ts - t0) / 1000;   // seconds

        // 1. Ease cur → TARGET (fast at start, slows near target)
        cur += (TARGET - cur) * 0.06;

        // 2. Continuous micro-oscillation once near target
        const nearTarget = Math.abs(cur - TARGET) < AMP * 3;
        const osc = nearTarget
            ? AMP * Math.sin(elapsed * 0.8 + phase)          // slow ~0.8 rad/s
            : 0;
        const display = Math.max(MIN_V, Math.min(MAX_V, cur + osc));

        // 3. Arc pulse — alpha breathes between 0.55 and 1.0 at ~0.4 Hz
        const pulse = 0.775 + 0.225 * Math.sin(elapsed * 2.5 + phase);

        ctx.clearRect(0, 0, 260, 150);

        // Draw arc segments with breathing alpha
        RANGES.forEach(seg => {{
            ctx.beginPath();
            // Determine if needle is inside this segment (active = brighter)
            const active = display >= seg.r0 && display <= seg.r1;
            const base   = seg.color.replace(/[\d.]+\)$/, '');
            const alpha  = active ? pulse : 0.45;
            ctx.strokeStyle = seg.color.replace(
                /[\d.]+\)$/,
                alpha.toFixed(3) + ')'
            );
            ctx.lineWidth = 20;
            ctx.arc(cx, cy, r, toA(seg.r0), toA(seg.r1));
            ctx.stroke();
        }});

        // Needle glow
        const ang = toA(display);
        const nx  = cx + r * Math.cos(ang);
        const ny  = cy + r * Math.sin(ang);

        ctx.shadowColor  = '{needle_clr}';
        ctx.shadowBlur   = 8 + 4 * Math.sin(elapsed * 3 + phase);
        ctx.beginPath();
        ctx.strokeStyle = '{needle_clr}';
        ctx.lineWidth   = 3;
        ctx.moveTo(cx, cy);
        ctx.lineTo(nx, ny);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Pivot dot
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, 2*Math.PI);
        ctx.fillStyle = '{needle_clr}';
        ctx.fill();

        // Value readout (show real target value, not oscillated display)
        ctx.fillStyle   = 'white';
        ctx.font        = 'bold 20px Rajdhani';
        ctx.textAlign   = 'center';
        ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.fillText(TARGET.toFixed(2) + '{unit}', cx, cy - 40);

        requestAnimationFrame(draw);
    }}

    requestAnimationFrame(draw);
}})();
</script></body></html>"""


def _alert_style(event_name: str):
    e = event_name.lower()
    if "warning" in e:
        return {
            "border": "#FF3333",
            "text": "#FFCCCC",
            "title": "#FF6666",
            "bg": "rgba(255,51,51,0.10)",
        }
    if "watch" in e:
        return {
            "border": "#FF8800",
            "text": "#FFE0C2",
            "title": "#FFB066",
            "bg": "rgba(255,136,0,0.10)",
        }
    return {
        "border": "#FFD700",
        "text": "#FFF3B0",
        "title": "#FFE866",
        "bg": "rgba(255,215,0,0.10)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  7. DATA EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

current_conditions = fetch_current_conditions()
forecast           = _build_unified_daily_forecast()
backup_hist        = fetch_backup_precip_history()
station_rain       = fetch_realtime_station_bundle()
active_alerts      = fetch_active_alerts()
hwo_text           = fetch_hazardous_weather_outlook()

sm_07, sm_728, sm_ts, sm_ok       = fetch_era5_soil_moisture()
usdm_level, usdm_label, usdm_date = fetch_usdm_drought()

if station_rain.get("ok", False):
    rain_24h         = station_rain.get("rain_24h_in") or backup_hist["rain_24h_in"]
    rain_5d          = station_rain.get("rain_5d_in")  or backup_hist["rain_5d_in"]
    rain_7d          = station_rain.get("rain_7d_in")  or backup_hist["rain_7d_in"]
    rain_14d         = station_rain.get("rain_14d_in") or backup_hist["rain_14d_in"]
    display_rain_now = station_rain.get("rain_rate_in_hr")
    if display_rain_now is None:
        display_rain_now = current_conditions["precip"]
else:
    rain_24h         = backup_hist["rain_24h_in"]
    rain_5d          = backup_hist["rain_5d_in"]
    rain_7d          = backup_hist["rain_7d_in"]
    rain_14d         = backup_hist["rain_14d_in"]
    display_rain_now = current_conditions["precip"]

soil_sat, soil_stored, soil_color = calc_soil_saturation_ensemble(
    sm_07, sm_728, sm_ok, rain_5d, usdm_level
)

_UP_DRAIN_FACTOR = (((UP_TC_HRS / LO_TC_HRS) ** 0.5) * 0.60 +
                    (UP_CN_II / LO_CN_II) * 0.40)

soil_sat_lo = soil_sat
soil_sat_up = round(min(100.0, max(1.0, soil_sat * _UP_DRAIN_FACTOR)), 1)


def _sat_color(s):
    return "#FF3333" if s > 85 else "#FF8800" if s > 70 else "#FFD700" if s > 50 else "#00FF9C"


def _sat_stored(s):
    return round((s / 100.0) * (SOIL_POROSITY * 11.024), 2)


soil_color_lo  = _sat_color(soil_sat_lo)
soil_color_up  = _sat_color(soil_sat_up)
soil_stored_lo = soil_stored
soil_stored_up = _sat_stored(soil_sat_up)

qpf_24h = forecast[0]["qpf_in"] if forecast else 0.0
pop_24h  = forecast[0]["pop"]    if forecast else 0.0

threat          = flood_threat_score(soil_sat_lo, qpf_24h, pop_24h)
t_lbl, t_clr, t_bg = threat_meta(threat)

lo_depth, lo_flow = model_stream(
    soil_sat_lo, rain_24h, qpf_24h, rain_7d,
    LO_DA_SQMI, LO_TC_HRS, LO_CN_II, LO_BASEFLOW,
    LO_RATING_A, LO_RATING_B, LO_BANKFULL_Q
)

up_depth, up_flow = model_stream(
    soil_sat_up, rain_24h, qpf_24h, rain_7d,
    UP_DA_SQMI, UP_TC_HRS, UP_CN_II, UP_BASEFLOW,
    UP_RATING_A, UP_RATING_B, UP_BANKFULL_Q
)

if "lo_depth" not in st.session_state:
    st.session_state.lo_depth = lo_depth
if "lo_flow" not in st.session_state:
    st.session_state.lo_flow = lo_flow
if "up_depth" not in st.session_state:
    st.session_state.up_depth = up_depth
if "up_flow" not in st.session_state:
    st.session_state.up_flow = up_flow

st.session_state.lo_depth = round(st.session_state.lo_depth * 0.30 + lo_depth * 0.70, 2)
st.session_state.lo_flow  = round(st.session_state.lo_flow  * 0.30 + lo_flow  * 0.70, 1)
st.session_state.up_depth = round(st.session_state.up_depth * 0.30 + up_depth * 0.70, 2)
st.session_state.up_flow  = round(st.session_state.up_flow  * 0.30 + up_flow  * 0.70, 1)

lo_depth_lbl, lo_depth_clr = stage_status(st.session_state.lo_depth, LO_BANKFULL)
up_depth_lbl, up_depth_clr = stage_status(st.session_state.up_depth, UP_BANKFULL)
lo_flow_lbl,  lo_flow_clr  = flow_status(st.session_state.lo_flow,   LO_BANKFULL_Q)
up_flow_lbl,  up_flow_clr  = flow_status(st.session_state.up_flow,   UP_BANKFULL_Q)

lo_bkf_pct = round(min(100, st.session_state.lo_depth / LO_BANKFULL * 100), 1)
up_bkf_pct = round(min(100, st.session_state.up_depth / UP_BANKFULL * 100), 1)

_q_ref         = max(LO_BASEFLOW, st.session_state.lo_flow)
_wave_base     = FLOOD_TRAVEL_MIN
_travel_raw    = _wave_base * (LO_BASEFLOW / _q_ref) ** 0.40
_travel_ripple = (st.session_state.up_flow % 7.3) * 0.41 - 1.5
travel_min     = round(min(90.0, max(15.0, _travel_raw + _travel_ripple)), 1)

_tw_clr = ("#FF3333" if travel_min < 25 else
           "#FF8800" if travel_min < 35 else
           "#FFD700" if travel_min < 50 else "#00FF9C")


# ═══════════════════════════════════════════════════════════════════════════════
#  8. RENDER
# ═══════════════════════════════════════════════════════════════════════════════

now_et = datetime.now(ET_TZ)

# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
  <div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
  <div class="site-sub">
    Cullowhee Creek Watershed &mdash; Jackson County, NC
    &nbsp;|&nbsp;
    {now_et.strftime("%A, %B %d %Y")} &mdash; {now_et.strftime("%H:%M")}
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 1: FLOOD THREAT BANNER ─────────────────────────────────────────────
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
    SOIL SAT (LOWER) {soil_sat_lo:.1f}% &nbsp;&middot;&nbsp; (UPPER) {soil_sat_up:.1f}%
    &nbsp;&middot;&nbsp; QPF(24h) {qpf_24h:.2f}&quot;
    &nbsp;&middot;&nbsp; PoP {pop_24h:.0f}%
    &nbsp;&middot;&nbsp; LOWER {lo_bkf_pct:.0f}% of bankfull
    &nbsp;&middot;&nbsp; UPPER {up_bkf_pct:.0f}% of bankfull
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.68em;
              color:#3A6A8A; margin-top:10px; letter-spacing:1px;">
    EVALUATED FACTORS: Soil Saturation &middot; 24hr Rainfall Forecast &middot; Probability of Precipitation
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 1B: ACTIVE WEATHER ALERTS ──────────────────────────────────────────
if active_alerts:
    st.markdown('<div class="panel"><div class="panel-title">ACTIVE WEATHER ALERTS</div>', unsafe_allow_html=True)
    for a in active_alerts:
        style = _alert_style(a["event"])
        expires_line = f"Until {a['expires_local']}" if a["expires_local"] else ""
        summary = a["headline"] if a["headline"] else a["description"]
        if len(summary) > 220:
            summary = summary[:217] + "..."
        st.markdown(f"""
<div style="background:{style['bg']}; border-left:6px solid {style['border']};
            border-radius:8px; padding:14px 16px; margin-bottom:10px;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.78em; color:{style['title']};
              letter-spacing:2px; margin-bottom:6px;">
    {a['event'].upper()}
  </div>
  <div style="font-size:0.92em; color:{style['text']}; line-height:1.45;">
    {summary}
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.66em; color:#7AACCC; margin-top:8px;">
    {expires_line}
  </div>
</div>
""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 1C: HAZARDOUS WEATHER OUTLOOK ──────────────────────────────────────
if hwo_text:
    _hwo_border = "#FF8800"
    _hwo_bg     = "rgba(255,136,0,0.07)"
    _hwo_clr    = "#FFB066"
    _hwo_sub    = "#FFE0C2"

    # Build inner HTML for each paragraph section.
    # Body text is already HTML-escaped by the fetch function;
    # convert newlines to <br> for proper rendering.
    _para_html = ""
    for para in hwo_text["paragraphs"]:
        if para["header"]:
            _para_html += (
                f'<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.72em;'
                f' color:{_hwo_clr}; letter-spacing:2px; margin:14px 0 5px;">'
                f'{para["header"]}</div>'
            )
        body_html = para["body"].replace("\n\n", "<br><br>").replace("\n", " ")
        _para_html += (
            f'<div style="font-family:\'Rajdhani\',sans-serif; font-size:1.0em;'
            f' color:{_hwo_sub}; line-height:1.65; margin-bottom:4px;">'
            f'{body_html}</div>'
        )

    st.markdown(f"""
<div style="background:{_hwo_bg}; border:2px solid {_hwo_border}; border-radius:10px;
            padding:20px 28px; margin-bottom:16px;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em;
              color:{_hwo_clr}; letter-spacing:4px; margin-bottom:6px; text-align:center;">
    NWS ACTIVE PRODUCT
  </div>
  <div style="font-size:3.0em; font-weight:700; color:{_hwo_clr};
              letter-spacing:4px; line-height:1.0; text-align:center; margin-bottom:12px;">
    HAZARDOUS WEATHER OUTLOOK
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.65em;
              color:#7AACCC; letter-spacing:1px; margin-bottom:14px; text-align:center;
              border-bottom:1px solid rgba(255,136,0,0.25); padding-bottom:10px;">
    NWS GREENVILLE-SPARTANBURG (GSP) &nbsp;&middot;&nbsp; JACKSON COUNTY, NC
    &nbsp;&middot;&nbsp; ISSUED: {hwo_text['issued']}
  </div>
  {_para_html}
</div>
""", unsafe_allow_html=True)


# ── PANEL 2: ATMOSPHERIC CONDITIONS ──────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3)
with c1:
    st.plotly_chart(make_dial(current_conditions["wind"], "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c2:
    st.plotly_chart(make_dial(current_conditions["temp"], "TEMPERATURE", 0, 110, " F", "#FF3333"), use_container_width=True)
with c3:
    st.plotly_chart(make_dial(display_rain_now, "RAIN NOW", 0, 4, '" / hr', "#0077FF", sub="Current intensity"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 3: UPPER WATERSHED — HEADWATERS ────────────────────────────────────
_up_bkf = UP_BANKFULL
_up_max = _up_bkf * 2.5

st.markdown(
    f'<div class="upper-panel"><div class="upper-title">'
    f'UPPER CULLOWHEE CREEK '
    f'({UP_AREA_ACRES:,} AC | {UP_DA_SQMI:.2f} mi²)'
    f'</div>',
    unsafe_allow_html=True
)

u1, u2, u3 = st.columns([2, 2, 3])

with u1:
    st.components.v1.html(make_stream_gauge(
        "g_up_depth", st.session_state.up_depth,
        0.0, _up_max, " ft",
        [{"range": [0.0,          _up_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_up_bkf*0.60, _up_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_up_bkf*0.95, _up_max],         "color": "rgba(255,51,51,0.25)"}],
        up_depth_clr, up_depth_lbl, up_depth_clr,
        f"Stage: {st.session_state.up_depth:.2f} ft"
    ), height=240)

with u2:
    _up_q_max = UP_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_up_flow", st.session_state.up_flow,
        0.0, _up_q_max, " cfs",
        [{"range": [0.0,               UP_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [UP_BANKFULL_Q*0.45, UP_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [UP_BANKFULL_Q*0.95, _up_q_max],             "color": "rgba(255,51,51,0.25)"}],
        up_flow_clr, up_flow_lbl, up_flow_clr,
        f"Q: {st.session_state.up_flow:.1f} cfs"
    ), height=240)

with u3:
    st.markdown(f"""
<div style="background:rgba(0,50,30,0.18); border:1px solid rgba(0,180,100,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#00CC77; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,180,100,0.2); padding-bottom:6px;">
    SOIL SATURATION
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_up}; text-align:center;
              margin:6px 0 4px;">{soil_sat_up:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:8px;">
    stored: {soil_stored_up:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 4: LOWER WATERSHED ─────────────────────────────────────────────────
_lo_bkf = LO_BANKFULL
_lo_max = _lo_bkf * 2.5

st.markdown(
    f'<div class="lower-panel"><div class="lower-title">'
    f'LOWER CULLOWHEE CREEK ({LO_AREA_ACRES:,} AC | {LO_DA_SQMI:.2f} mi²)'
    f'</div>',
    unsafe_allow_html=True
)

l1, l2, l3 = st.columns([2, 2, 3])

with l1:
    st.components.v1.html(make_stream_gauge(
        "g_lo_depth", st.session_state.lo_depth,
        0.0, _lo_max, " ft",
        [{"range": [0.0,          _lo_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_lo_bkf*0.60, _lo_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_lo_bkf*0.95, _lo_max],         "color": "rgba(255,51,51,0.25)"}],
        lo_depth_clr, lo_depth_lbl, lo_depth_clr,
        f"Stage: {st.session_state.lo_depth:.2f} ft"
    ), height=240)

with l2:
    _lo_q_max = LO_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_lo_flow", st.session_state.lo_flow,
        0.0, _lo_q_max, " cfs",
        [{"range": [0.0,               LO_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [LO_BANKFULL_Q*0.45, LO_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [LO_BANKFULL_Q*0.95, _lo_q_max],             "color": "rgba(255,51,51,0.25)"}],
        lo_flow_clr, lo_flow_lbl, lo_flow_clr,
        f"Q: {st.session_state.lo_flow:.1f} cfs"
    ), height=240)

with l3:
    st.markdown(f"""
<div style="background:rgba(0,50,120,0.18); border:1px solid rgba(0,119,255,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#0077FF; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,119,255,0.2); padding-bottom:6px;">
    SOIL SATURATION
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_lo}; text-align:center;
              margin:6px 0 4px;">{soil_sat_lo:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:12px;">
    stored: {soil_stored_lo:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)


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
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.20);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0077FF;
                letter-spacing:2px; margin-bottom:8px;">DELTA (LOWER &minus; UPPER)</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">Watershed response amplification</div>
    <div style="font-size:2.2em; font-weight:700; color:#FFFF00;">{'+' if dd >= 0 else ''}{dd:.2f} ft</div>
    <div style="font-size:1.1em; color:#FFFF00; margin-bottom:8px;">{'+' if dq >= 0 else ''}{dq:.1f} cfs ({'+' if dq_pct >= 0 else ''}{dq_pct:.1f}%)</div>
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.25);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0099FF;
                letter-spacing:2px; margin-bottom:8px;">LOWER</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">{LO_AREA_ACRES:,} ac | CN={LO_CN_II} | Tc={LO_TC_HRS}h</div>
    <div style="font-size:2.2em; font-weight:700; color:{comp_clr_lo};">{st.session_state.lo_depth:.2f} ft</div>
    <div style="font-size:1.1em; color:{lo_flow_clr};">{st.session_state.lo_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:{comp_clr_lo};
                margin-top:6px; letter-spacing:2px;">{lo_depth_lbl}</div>
  </div>

</div>
""", unsafe_allow_html=True)

tw1, tw2, tw3 = st.columns([1, 2, 1])
with tw2:
    st.plotly_chart(
        make_dial(travel_min, "WAVE TRAVEL", 15, 90, " min", _tw_clr, sub="UPPER → LOWER"),
        use_container_width=True
    )

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 6: 7-DAY FLOOD OUTLOOK ─────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED</div>', unsafe_allow_html=True)

if not forecast:
    st.warning("Forecast unavailable.")
else:
    pcols = st.columns(7)
    for i, d in enumerate(forecast[:7]):
        risk  = min(100.0, round((soil_sat_lo * 0.35) + (d["pop"] * 0.35) + (d["qpf_in"] * 20), 1))
        color = "#00FF9C" if risk < 30 else "#FFFF00" if risk < 50 else "#FFD700" if risk < 65 else "#FF8800" if risk < 80 else "#FF3333"
        with pcols[i]:
            st.markdown(
                '<div style="background:rgba(255,255,255,0.03); border-top:4px solid '
                + color
                + '; border-radius:8px; padding:12px 8px; text-align:center;">'
                + '<div style="font-weight:700; font-size:1.1em;">' + d["short_name"] + '</div>'
                + '<div style="font-size:0.75em; color:#5A7090; margin-bottom:4px;">' + d["date_label"] + '</div>'
                + '<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.75em; color:#7AACCC; margin-bottom:4px;">' + forecast_icon(d.get("icon_txt", "")) + '</div>'
                + '<div style="color:' + color + '; font-size:1.55em; font-weight:700; margin:5px 0;">' + f'{risk:.1f}' + '%</div>'
                + '<div style="color:' + color + '; font-family:\'Share Tech Mono\',monospace; font-size:0.72em; letter-spacing:2px; margin-bottom:4px;">FLOOD RISK</div>'
                + '<div style="color:#00FFCC; font-family:\'Share Tech Mono\',monospace; font-size:0.85em;">' + f'{d["qpf_in"]:.2f}' + '&quot;</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["pop"]:.0f}' + '% PoP</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["temp_f"]:.0f}' + ' F</div>'
                + '</div>',
                unsafe_allow_html=True
            )

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 7: RADAR ───────────────────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">RADAR LOOP</div>', unsafe_allow_html=True)

_cb = int(time.time() / 120)
st.components.v1.html(f"""
<div style="background:#04090F; border-radius:10px; border:1px solid #1a2a3a; overflow:hidden; font-family:'Courier New',monospace;">
  <div style="display:flex; align-items:center; justify-content:space-between;
              padding:8px 16px; background:#0a1520; border-bottom:1px solid #1a3a5a;">
    <div style="display:flex; align-items:center; gap:10px;">
      <div style="width:8px; height:8px; border-radius:50%; background:#00FF9C; box-shadow:0 0 6px #00FF9C;"></div>
      <span style="color:#00CFFF; font-size:11px; font-weight:700; letter-spacing:2px;">LIVE</span>
    </div>
    <div style="color:#556677; font-size:10px; letter-spacing:1px;">AUTO-LOOP &#x21BB; 2 MIN</div>
  </div>
  <div style="position:relative; background:#000; text-align:center;">
    <img src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?v={_cb}"
         style="width:100%; max-height:520px; object-fit:contain; display:block;" alt="Radar Loop" />
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
      </div>
    </div>
  </div>
</div>
""", height=610)

st.markdown('</div>', unsafe_allow_html=True)"""
NOAH: Cullowhee Creek Flood Warning Dashboard
Western Carolina University — NEMO River Energy Initiative
Jackson County, NC — Watershed Monitoring System
"""

import math
import json
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

import requests
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh


# ═══════════════════════════════════════════════════════════════════════════════
#  1. CONFIGURATION & STYLING
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="NOAH: Cullowhee Flood Warning", layout="wide")
st_autorefresh(interval=30000, key="refresh")

LAT, LON = 35.3079, -83.1746
ET_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

# -----------------------------------------------------------------------------
# REAL-TIME OBSERVED RAIN CONFIG
# -----------------------------------------------------------------------------
REALTIME_RAIN_STATIONS = [
    {
        "name": "Primary Basin Rain",
        "type": "custom_json",
        "weight": 1.0,
        "current_url": "",
        "history_url": "",
    },
    {
        "name": "Secondary Basin Rain",
        "type": "custom_json",
        "weight": 1.0,
        "current_url": "",
        "history_url": "",
    },
    {
        "name": "Cullowhee PWS",
        "type": "weathercom_pws",
        "weight": 1.0,
        "station_id": "KNCCULLO7",
        "api_key": "",
    },
    {
        "name": "Sylva PWS",
        "type": "weathercom_pws",
        "weight": 1.0,
        "station_id": "KNCSYLVA86",
        "api_key": "",
    },
]

REQUEST_TIMEOUT_SEC = 10

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap');

html, body, .stApp {
    background-color: #04090F;
    color: #E0E8F0;
    font-family: 'Rajdhani', sans-serif;
}

.site-header {
    border-left: 6px solid #0077FF;
    padding: 14px 22px;
    margin-bottom: 20px;
    background: rgba(0,100,200,0.07);
    border-radius: 0 8px 8px 0;
}
.site-title  {
    font-size: 2.4em;
    font-weight: 700;
    color: #FFFFFF;
    margin: 0;
    letter-spacing: 2px;
}
.site-sub    {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.75em;
    color: #5AACD0;
    margin-top: 4px;
}

.panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,119,255,0.18);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.panel-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #0077FF;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,119,255,0.18);
    padding-bottom: 8px;
    margin-bottom: 14px;
}

.upper-panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,180,100,0.25);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.upper-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #00CC77;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,180,100,0.25);
    padding-bottom: 8px;
    margin-bottom: 14px;
}

.lower-panel {
    background: rgba(8,16,28,0.88);
    border: 1px solid rgba(0,119,255,0.25);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 16px;
}
.lower-title {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78em;
    color: #0099FF;
    text-transform: uppercase;
    letter-spacing: 3px;
    border-bottom: 1px solid rgba(0,119,255,0.25);
    padding-bottom: 8px;
    margin-bottom: 14px;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. WATERSHED & SOIL CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SOIL_POROSITY  = 0.439
SOIL_FIELD_CAP = 0.286
SOIL_WILT_PT   = 0.151

LO_AREA_ACRES      = 6200
LO_DA_SQMI         = 9.688
LO_TC_HRS          = 2.5
LO_CN_II           = 68
LO_RATING_A        = 21.4
LO_RATING_B        = 2.30
LO_BASEFLOW        = 9.0
LO_BANKFULL        = 2.87
LO_BANKFULL_Q      = 241.2

UP_AREA_ACRES      = 2480
UP_DA_SQMI         = 3.875
UP_TC_HRS          = 1.2
UP_CN_II           = 62
UP_RATING_A        = 21.2
UP_RATING_B        = 2.15
UP_BASEFLOW        = 3.5
UP_BANKFULL        = 2.16
UP_BANKFULL_Q      = 110.7

FLOOD_TRAVEL_MIN   = 65

_USDM_IMPLIED_SAT = {1: 55.0, 2: 40.0, 3: 27.0, 4: 17.0, 5: 8.0}
_USDM_CEILING     = {0: 100, 1: 65, 2: 50, 3: 35, 4: 22, 5: 12}

_TR55_IAPRATIO = [0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50]
_TR55_C0       = [2.55323, 2.23537, 2.10304, 2.18219, 2.17339, 2.16251, 2.14583]
_TR55_C1       = [-0.61512, -0.50537, -0.51488, -0.50258, -0.48985, -0.47856, -0.46772]
_TR55_C2       = [-0.16403, -0.11657, -0.08648, -0.09057, -0.09084, -0.09303, -0.09373]


# ═══════════════════════════════════════════════════════════════════════════════
#  3. HIDDEN FORECAST ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def _hours_ahead(target_dt: datetime, now_dt: datetime) -> float:
    return (target_dt - now_dt).total_seconds() / 3600.0


def _choose_bucket(lead_hours: float) -> str:
    if lead_hours <= 18:
        return "short_range"
    elif lead_hours <= 48:
        return "mid_range"
    return "extended"


def _weighted_merge(a: dict, b: dict, wa: float, wb: float) -> dict:
    total = wa + wb
    return {
        "time": a["time"],
        "temp_f": (a["temp_f"] * wa + b["temp_f"] * wb) / total,
        "qpf_in": (a["qpf_in"] * wa + b["qpf_in"] * wb) / total,
        "pop":    (a["pop"] * wa + b["pop"] * wb) / total,
        "icon_txt": b.get("icon_txt", a.get("icon_txt", "")),
    }


@st.cache_data(ttl=900)
def _fetch_hidden_short_range_hourly():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "temperature_2m,precipitation,precipitation_probability",
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "forecast_days": 3,
            },
            timeout=15,
        ).json()

        times = r["hourly"]["time"]
        temp  = r["hourly"]["temperature_2m"]
        qpf   = r["hourly"]["precipitation"]
        pop   = r["hourly"].get("precipitation_probability", [0] * len(times))

        out = []
        for i, t in enumerate(times):
            try:
                ts = datetime.fromisoformat(t).replace(tzinfo=UTC_TZ).astimezone(ET_TZ)
                out.append({
                    "time": ts,
                    "temp_f": float(temp[i] or 0.0),
                    "qpf_in": float(qpf[i] or 0.0),
                    "pop": float(pop[i] or 0.0),
                    "icon_txt": "",
                })
            except Exception:
                continue
        return out
    except Exception:
        return []


@st.cache_data(ttl=1800)
def _fetch_hidden_daily_forecast():
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0"}
        pts = requests.get(
            f"https://api.weather.gov/points/{LAT},{LON}",
            headers=hdrs,
            timeout=10
        ).json()["properties"]

        periods = requests.get(
            pts["forecast"],
            headers=hdrs,
            timeout=10
        ).json()["properties"]["periods"]

        grid = requests.get(
            pts["forecastGridData"],
            headers=hdrs,
            timeout=15
        ).json()["properties"]

        qpf_by_date = defaultdict(float)
        for entry in grid.get("quantitativePrecipitation", {}).get("values", []):
            vt = entry["validTime"].split("/")[0]
            val = entry["value"] or 0.0
            try:
                d = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                qpf_by_date[d] += float(val) * 0.0393701
            except Exception:
                pass

        temp_by_date = {}
        for entry in grid.get("maxTemperature", {}).get("values", []):
            vt = entry["validTime"].split("/")[0]
            val = entry["value"]
            if val is None:
                continue
            try:
                d = datetime.fromisoformat(vt).astimezone(ET_TZ).strftime("%Y-%m-%d")
                tf = float(val) * 9 / 5 + 32
                if d not in temp_by_date or tf > temp_by_date[d]:
                    temp_by_date[d] = tf
            except Exception:
                pass

        out = []
        seen = set()
        for p in periods:
            if not p.get("isDaytime", False):
                continue
            try:
                dt = datetime.fromisoformat(p["startTime"]).astimezone(ET_TZ)
                dkey = dt.strftime("%Y-%m-%d")
                if dkey in seen:
                    continue
                seen.add(dkey)
                out.append({
                    "time": dt.replace(hour=12, minute=0, second=0, microsecond=0),
                    "date": dkey,
                    "short_name": dt.strftime("%a").upper(),
                    "date_label": dt.strftime("%m/%d"),
                    "temp_f": round(float(temp_by_date.get(dkey, p["temperature"])), 1),
                    "qpf_in": round(float(qpf_by_date.get(dkey, 0.0)), 2),
                    "pop": round(float((p.get("probabilityOfPrecipitation") or {}).get("value") or 0), 1),
                    "icon_txt": str(p.get("shortForecast", "")),
                })
            except Exception:
                continue

        return out[:7]
    except Exception:
        return []


def _build_unified_daily_forecast():
    now_et = datetime.now(ET_TZ)
    hourly = _fetch_hidden_short_range_hourly()
    daily  = _fetch_hidden_daily_forecast()

    hourly_by_day = defaultdict(list)
    for r in hourly:
        lead = _hours_ahead(r["time"], now_et)
        if -3 <= lead <= 60:
            hourly_by_day[r["time"].strftime("%Y-%m-%d")].append(r)

    short_daily = {}
    for dkey, rows in hourly_by_day.items():
        dt = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        short_daily[dkey] = {
            "time": dt,
            "date": dkey,
            "short_name": dt.strftime("%a").upper(),
            "date_label": dt.strftime("%m/%d"),
            "temp_f": round(max(r["temp_f"] for r in rows), 1),
            "qpf_in": round(sum(r["qpf_in"] for r in rows), 2),
            "pop": round(max(r["pop"] for r in rows), 1),
            "icon_txt": "",
        }

    daily_map = {r["date"]: r for r in daily}
    all_dates = sorted(set(short_daily) | set(daily_map))

    unified = []
    for dkey in all_dates:
        target = datetime.strptime(dkey, "%Y-%m-%d").replace(tzinfo=ET_TZ, hour=12)
        lead = _hours_ahead(target, now_et)

        short_rec = short_daily.get(dkey)
        daily_rec = daily_map.get(dkey)

        if 12 <= lead <= 18 and short_rec and daily_rec:
            wb = (lead - 12) / 6.0
            wa = 1.0 - wb
            merged = _weighted_merge(short_rec, daily_rec, wa, wb)
            merged.update({
                "date": dkey,
                "short_name": target.strftime("%a").upper(),
                "date_label": target.strftime("%m/%d"),
            })
            unified.append(merged)
        elif _choose_bucket(lead) == "short_range" and short_rec:
            unified.append(short_rec)
        elif daily_rec:
            unified.append(daily_rec)
        elif short_rec:
            unified.append(short_rec)

    return unified[:7]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. DATA ACQUISITION
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_current_conditions():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                           "wind_direction_10m,surface_pressure,precipitation,"
                           "weather_code,wind_gusts_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "forecast_days": 1,
            },
            timeout=10
        ).json()

        c = r["current"]
        return {
            "ok":        True,
            "temp":      round(float(c.get("temperature_2m", 50)), 1),
            "hum":       round(float(c.get("relative_humidity_2m", 50)), 1),
            "wind":      round(float(c.get("wind_speed_10m", 0)), 1),
            "wind_gust": round(float(c.get("wind_gusts_10m", 0)), 1),
            "wind_dir":  round(float(c.get("wind_direction_10m", 0)), 1),
            "press":     round(c.get("surface_pressure", 1013.25) * 0.02953, 2),
            "precip":    round(float(c.get("precipitation", 0)), 1),
            "wcode":     c.get("weather_code", 0),
        }
    except Exception:
        return {
            "ok": False, "temp": 50.0, "hum": 50.0, "wind": 0.0,
            "wind_gust": 0.0, "wind_dir": 0.0, "press": 29.92,
            "precip": 0.0, "wcode": 0
        }


@st.cache_data(ttl=1800)
def fetch_backup_precip_history():
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "precipitation,snowfall",
                "precipitation_unit": "inch",
                "past_days": 14,
                "forecast_days": 1,
                "models": "best_match",
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
            s = (snow_h[i] or 0.0) * 0.0393701
            if age <= 14:
                t14d += p
            if age <= 7:
                t7d += p
                snow7d += s
            if age <= 5:
                t5d += p
            if age <= 1:
                t24h += p

        return {
            "ok": True,
            "rain_14d_in": round(t14d, 2),
            "rain_7d_in": round(t7d, 2),
            "rain_5d_in": round(t5d, 2),
            "rain_24h_in": round(t24h, 2),
            "snow_7d_in": round(snow7d, 2),
        }
    except Exception:
        return {
            "ok": False,
            "rain_14d_in": 2.10,
            "rain_7d_in": 0.50,
            "rain_5d_in": 0.50,
            "rain_24h_in": 0.00,
            "snow_7d_in": 0.00,
        }


@st.cache_data(ttl=3600)
def fetch_era5_soil_moisture():
    try:
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=14)
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": LAT,
                "longitude": LON,
                "hourly": "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
                "models": "era5_land",
                "start_date": start_dt.strftime("%Y-%m-%d"),
                "end_date": end_dt.strftime("%Y-%m-%d"),
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
    try:
        end_dt   = date.today()
        start_dt = date.today() - timedelta(days=21)
        r = requests.get(
            "https://usdmdataservices.unl.edu/api/CountyStatistics/"
            "GetDroughtSeverityStatisticsByAreaPercent",
            params={
                "aoi": "37099",
                "startdate": start_dt.strftime("%m/%d/%Y"),
                "enddate": end_dt.strftime("%m/%d/%Y"),
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


@st.cache_data(ttl=300)
def fetch_active_alerts():
    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0"}
        r = requests.get(
            "https://api.weather.gov/alerts/active",
            params={"point": f"{LAT},{LON}"},
            headers=hdrs,
            timeout=10
        ).json()

        feats = r.get("features", [])
        alerts = []

        for feat in feats:
            props = feat.get("properties", {})
            event = str(props.get("event", "")).strip()
            headline = str(props.get("headline", "")).strip()
            expires = str(props.get("expires", "")).strip()
            desc = str(props.get("description", "")).strip()

            if not event:
                continue

            short_desc = " ".join(desc.split())
            if len(short_desc) > 180:
                short_desc = short_desc[:177] + "..."

            expires_local = ""
            if expires:
                try:
                    dt = datetime.fromisoformat(expires.replace("Z", "+00:00")).astimezone(ET_TZ)
                    expires_local = dt.strftime("%b %d, %I:%M %p")
                except Exception:
                    expires_local = ""

            alerts.append({
                "event": event,
                "headline": headline,
                "expires_local": expires_local,
                "description": short_desc,
            })

        severity_rank = {
            "flash flood warning": 5,
            "flood warning": 5,
            "severe thunderstorm warning": 4,
            "tornado warning": 5,
            "flash flood watch": 3,
            "flood watch": 3,
            "wind advisory": 2,
            "flood advisory": 2,
            "special weather statement": 1,
        }

        alerts.sort(key=lambda a: severity_rank.get(a["event"].lower(), 0), reverse=True)
        return alerts
    except Exception:
        return []


@st.cache_data(ttl=900)
def fetch_hazardous_weather_outlook():
    """
    Pulls the latest Hazardous Weather Outlook from the NWS Products API
    for the GSP (Greenville-Spartanburg) WFO.
    Returns dict with 'issued' (str) and 'paragraphs' (list of {header, body}),
    or None if unavailable.
    """
    import re
    from html import escape as html_escape

    try:
        hdrs = {"User-Agent": "NOAH-FloodWarning/1.0 (WCU NEMO Project)"}

        # Step 1 — list recent HWO products from GSP
        index = requests.get(
            "https://api.weather.gov/products/types/HWO/locations/GSP",
            headers=hdrs,
            timeout=10,
        ).json()

        graph = index.get("@graph", [])
        if not graph:
            return None

        # Step 2 — fetch most recent product
        latest_id = graph[0].get("id", "")
        if not latest_id:
            return None

        prod = requests.get(
            f"https://api.weather.gov/products/{latest_id}",
            headers=hdrs,
            timeout=10,
        ).json()

        raw = prod.get("productText", "")
        if not raw:
            return None

        # Step 3 — parse issuance time from API metadata (clean, no scraping)
        issued_str = ""
        issued_raw = prod.get("issuanceTime", "")
        if issued_raw:
            try:
                dt = datetime.fromisoformat(
                    issued_raw.replace("Z", "+00:00")
                ).astimezone(ET_TZ)
                issued_str = dt.strftime("%b %d, %Y  %I:%M %p ET")
            except Exception:
                issued_str = issued_raw[:16]

        # Step 4 — normalise line endings
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")

        # Step 5 — skip EVERYTHING before the first .DAY / .DAYS / .THIS section
        #           marker. This discards the WMO bulletin header, AWIPS ID,
        #           product title, NWS office line, issue time, UGC zone string,
        #           expiration timestamp — all the preamble garbage.
        first_section = re.search(
            r"(?m)^\.(DAY|DAYS|THIS)\b", raw, re.IGNORECASE
        )
        if not first_section:
            return None   # no recognised section structure → skip
        body = raw[first_section.start():]

        # Step 6 — cut at spotter statement / $$
        stop_pat = re.compile(
            r"(?m)(^\.(SPOTTER INFORMATION STATEMENT)|^\$\$)",
            re.IGNORECASE
        )
        m = stop_pat.search(body)
        if m:
            body = body[: m.start()]

        # Step 7 — split on section markers (.DAY ONE..., .DAYS TWO THROUGH..., etc.)
        #           re.split with a capturing group keeps the delimiters in the list.
        parts = re.split(r"(?m)(^\.[A-Z][A-Z0-9 ]+\.\.\.)", body)
        # parts = [pre, header1, block1, header2, block2, ...]
        # The first element is any text before the first header (usually empty).

        paragraphs = []
        i = 0
        # skip any leading non-header text
        if parts and not re.match(r"^\.[A-Z]", parts[0].strip()):
            i = 1
        while i < len(parts):
            raw_header = parts[i].strip()
            raw_body   = parts[i + 1].strip() if i + 1 < len(parts) else ""
            i += 2

            # Clean up body: collapse runs of blank lines to one, strip leading/trailing
            raw_body = re.sub(r"\n{3,}", "\n\n", raw_body).strip()

            if not raw_body:
                continue

            # HTML-escape both header and body so special chars (<, >, &, etc.)
            # render as text, not as HTML tags
            paragraphs.append({
                "header": html_escape(raw_header),
                "body":   html_escape(raw_body),
            })

        if not paragraphs:
            return None

        return {
            "issued":     issued_str,
            "paragraphs": paragraphs,
        }

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  4B. OBSERVED RAIN ADAPTERS
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_rain_value(x, min_v=0.0, max_v=50.0):
    try:
        v = float(x)
        if math.isnan(v) or v < min_v or v > max_v:
            return None
        return v
    except Exception:
        return None


def _fetch_custom_json_station(station_cfg: dict) -> dict:
    current_url = station_cfg.get("current_url", "").strip()
    history_url = station_cfg.get("history_url", "").strip()

    if not current_url and not history_url:
        return {"ok": False}

    out = {"ok": False}

    try:
        if current_url:
            rc = requests.get(current_url, timeout=REQUEST_TIMEOUT_SEC).json()
            out["rain_rate_in_hr"] = _clean_rain_value(rc.get("rain_rate_in_hr"), 0, 15)
            out["rain_1h_in"]      = _clean_rain_value(rc.get("rain_1h_in"), 0, 15)
            out["rain_24h_in"]     = _clean_rain_value(rc.get("rain_24h_in"), 0, 30)
    except Exception:
        pass

    try:
        if history_url:
            rh = requests.get(history_url, timeout=REQUEST_TIMEOUT_SEC).json()
            out["rain_24h_in"] = _clean_rain_value(rh.get("rain_24h_in", out.get("rain_24h_in")), 0, 30)
            out["rain_3d_in"]  = _clean_rain_value(rh.get("rain_3d_in"), 0, 40)
            out["rain_5d_in"]  = _clean_rain_value(rh.get("rain_5d_in"), 0, 50)
            out["rain_7d_in"]  = _clean_rain_value(rh.get("rain_7d_in"), 0, 60)
            out["rain_14d_in"] = _clean_rain_value(rh.get("rain_14d_in"), 0, 80)
    except Exception:
        pass

    out["ok"] = any(out.get(k) is not None for k in [
        "rain_rate_in_hr", "rain_1h_in", "rain_24h_in", "rain_3d_in",
        "rain_5d_in", "rain_7d_in", "rain_14d_in"
    ])
    return out


def _fetch_weathercom_pws_station(station_cfg: dict) -> dict:
    station_id = station_cfg.get("station_id", "").strip()
    api_key    = station_cfg.get("api_key", "").strip()

    if not station_id or not api_key:
        return {"ok": False}

    out = {"ok": False}

    try:
        current = requests.get(
            "https://api.weather.com/v2/pws/observations/current",
            params={
                "stationId": station_id,
                "format": "json",
                "units": "e",
                "numericPrecision": "decimal",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT_SEC,
        ).json()

        obs = (current.get("observations") or [{}])[0]
        imperial = obs.get("imperial", {})
        out["rain_rate_in_hr"] = _clean_rain_value(imperial.get("precipRate"), 0, 15)
        out["rain_1h_in"]      = _clean_rain_value(imperial.get("precipTotal"), 0, 15)
        out["rain_24h_in"]     = _clean_rain_value(imperial.get("precipTotal"), 0, 30)
    except Exception:
        pass

    try:
        hist = requests.get(
            "https://api.weather.com/v2/pws/observations/hourly/7day",
            params={
                "stationId": station_id,
                "format": "json",
                "units": "e",
                "numericPrecision": "decimal",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT_SEC,
        ).json()

        rows = hist.get("observations", [])
        if rows:
            hourly = []
            now_et = datetime.now(ET_TZ)
            for row in rows:
                try:
                    ts_utc = datetime.fromtimestamp(int(row["epoch"]), tz=UTC_TZ)
                    ts_et = ts_utc.astimezone(ET_TZ)
                    age_hr = (now_et - ts_et).total_seconds() / 3600.0
                    if age_hr < 0:
                        continue
                    imperial = row.get("imperial", {})
                    p = _clean_rain_value(imperial.get("precipTotal"), 0, 10)
                    if p is None:
                        p = 0.0
                    hourly.append((age_hr, p))
                except Exception:
                    continue

            rain_24h = sum(p for age, p in hourly if age <= 24)
            rain_72h = sum(p for age, p in hourly if age <= 72)
            rain_5d  = sum(p for age, p in hourly if age <= 120)
            rain_7d  = sum(p for age, p in hourly if age <= 168)

            out["rain_24h_in"] = _clean_rain_value(rain_24h, 0, 30)
            out["rain_3d_in"]  = _clean_rain_value(rain_72h, 0, 40)
            out["rain_5d_in"]  = _clean_rain_value(rain_5d, 0, 50)
            out["rain_7d_in"]  = _clean_rain_value(rain_7d, 0, 60)
    except Exception:
        pass

    out["ok"] = any(out.get(k) is not None for k in [
        "rain_rate_in_hr", "rain_1h_in", "rain_24h_in", "rain_3d_in",
        "rain_5d_in", "rain_7d_in"
    ])
    return out


@st.cache_data(ttl=300)
def fetch_realtime_station_bundle():
    station_results = []

    for cfg in REALTIME_RAIN_STATIONS:
        stype = cfg.get("type", "").strip().lower()
        if stype == "custom_json":
            res = _fetch_custom_json_station(cfg)
        elif stype == "weathercom_pws":
            res = _fetch_weathercom_pws_station(cfg)
        else:
            res = {"ok": False}

        if res.get("ok", False):
            res["weight"] = float(cfg.get("weight", 1.0))
            station_results.append(res)

    if not station_results:
        return {"ok": False, "count": 0}

    def weighted_mean(key):
        vals = [(r[key], r["weight"]) for r in station_results if r.get(key) is not None]
        if not vals:
            return None
        wsum = sum(w for _, w in vals)
        if wsum <= 0:
            return None
        return round(sum(v * w for v, w in vals) / wsum, 2)

    return {
        "ok": True,
        "count": len(station_results),
        "rain_rate_in_hr": weighted_mean("rain_rate_in_hr"),
        "rain_1h_in": weighted_mean("rain_1h_in"),
        "rain_24h_in": weighted_mean("rain_24h_in"),
        "rain_3d_in": weighted_mean("rain_3d_in"),
        "rain_5d_in": weighted_mean("rain_5d_in"),
        "rain_7d_in": weighted_mean("rain_7d_in"),
        "rain_14d_in": weighted_mean("rain_14d_in"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  5. HYDRO-MODELING
# ═══════════════════════════════════════════════════════════════════════════════

def calc_era5_sat_pct(sm_07, sm_728):
    sm_07  = min(sm_07, SOIL_POROSITY)
    sm_728 = min(sm_728, SOIL_POROSITY)
    sm_avg = min((sm_07 * 0.55) + (sm_728 * 0.45), SOIL_POROSITY)
    sat_range = SOIL_POROSITY - SOIL_WILT_PT
    return round(min(100.0, max(0.0, (sm_avg - SOIL_WILT_PT) / sat_range * 100)), 1)


def calc_api_sat_pct(rain_5d):
    a = min(float(rain_5d), 5.0)
    if a < 0.30:
        sat = 10.0 + a * 33.3
    elif a < 1.00:
        sat = 20.0 + (a - 0.30) / 0.70 * 18.0
    elif a < 2.10:
        sat = 38.0 + (a - 1.00) / 1.10 * 17.0
    elif a < 2.80:
        sat = 55.0 + (a - 2.10) / 0.70 * 13.0
    else:
        sat = 68.0 + (a - 2.80) / 2.20 * 22.0
    return round(min(90.0, max(5.0, sat)), 1)


def calc_soil_saturation_ensemble(sm_07, sm_728, sm_ok, rain_5d, usdm_level):
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
        w_api += w_era5
        w_era5 = 0.0
        era5_use = api_pct
    else:
        era5_use = era5_pct

    if usdm_pct is None:
        w_api += w_usdm
        w_usdm = 0.0
        usdm_use = api_pct
    else:
        usdm_use = usdm_pct

    sat_pct = (era5_use * w_era5) + (api_pct * w_api) + (usdm_use * w_usdm)
    ceiling = _USDM_CEILING.get(max(0, usdm_level), 100)
    sat_pct = min(sat_pct, ceiling)
    sat_pct = round(min(100.0, max(1.0, sat_pct)), 1)

    if sm_ok and sm_07 is not None:
        sm_07c    = min(sm_07, SOIL_POROSITY)
        sm_728c   = min(sm_728, SOIL_POROSITY)
        stored_in = round((sm_07c * 2.756) + (sm_728c * 8.268), 2)
    else:
        stored_in = round((sat_pct / 100.0) * (SOIL_POROSITY * 11.024), 2)

    color = "#FF3333" if sat_pct > 85 else "#FF8800" if sat_pct > 70 else "#FFD700" if sat_pct > 50 else "#00FF9C"

    return sat_pct, stored_in, color


def _tr55_unit_peak(tc_hrs: float, ia_p: float) -> float:
    ia_p   = max(0.10, min(0.50, float(ia_p)))
    tc_hrs = max(0.10, min(10.0, float(tc_hrs)))
    lt     = math.log10(tc_hrs)

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
    if soil_sat_pct < 30:
        cn_adj = max(50.0, cn_ii * 0.87)
    elif soil_sat_pct < 65:
        cn_adj = float(cn_ii)
    else:
        cn_adj = min(95.0, (23.0 * cn_ii) / (10.0 + 0.13 * cn_ii))

    P  = max(0.0, rain_24h + qpf_24h)
    S  = (1000.0 / cn_adj) - 10.0
    Ia = 0.2 * S

    if P > Ia:
        Q_runoff_in = (P - Ia) ** 2 / (P - Ia + S)
    else:
        Q_runoff_in = 0.0

    if Q_runoff_in > 0.0 and P > 0.0:
        ia_p    = min(0.50, max(0.10, Ia / P))
        qu      = _tr55_unit_peak(tc_hrs, ia_p)
        Q_storm = qu * da_sqmi * Q_runoff_in
    else:
        Q_storm = 0.0

    Q_base   = baseflow * (1.0 + (soil_sat_pct / 100.0) * 3.0)
    Q_recess = max(0.0, (rain_7d - rain_24h) * baseflow * 0.25)
    Q_max    = bankfull_q * 3.0
    Q_total  = round(max(baseflow * 0.5, min(Q_base + Q_storm + Q_recess, Q_max)), 1)
    depth_ft = round(max(0.20, min((Q_total / rating_a) ** (1.0 / rating_b), 9.0)), 2)

    return depth_ft, Q_total


def flood_threat_score(soil_sat, qpf_24h, pop_24h):
    return round(min(100.0,
        (soil_sat * 0.40) +
        (min(100.0, qpf_24h * 40) * 0.35) +
        (pop_24h * 0.25)
    ), 1)


def threat_meta(score):
    if score < 25:
        return "NORMAL", "#00FF9C", "rgba(0,255,156,0.07)"
    if score < 45:
        return "ELEVATED", "#FFFF00", "rgba(255,255,0,0.09)"
    if score < 65:
        return "WATCH", "#FFD700", "rgba(255,215,0,0.09)"
    if score < 82:
        return "WARNING", "#FF8800", "rgba(255,136,0,0.11)"
    return "EMERGENCY", "#FF3333", "rgba(255,51,51,0.14)"


def stage_status(depth_ft, bankfull_ft):
    ratio = depth_ft / bankfull_ft
    if ratio < 0.45:
        return "LOW FLOW", "#00FF9C"
    if ratio < 0.65:
        return "NORMAL", "#00FF9C"
    if ratio < 0.80:
        return "ELEVATED", "#FFFF00"
    if ratio < 0.95:
        return "WATCH", "#FFD700"
    return "FLOOD", "#FF3333"


def flow_status(q, bankfull_q):
    if q < bankfull_q * 0.15:
        return "LOW FLOW", "#00FF9C"
    if q < bankfull_q * 0.45:
        return "NORMAL", "#00FF9C"
    if q < bankfull_q * 0.85:
        return "ELEVATED", "#FFFF00"
    if q < bankfull_q * 1.00:
        return "WATCH", "#FFD700"
    return "FLOOD", "#FF3333"


def forecast_icon(txt):
    t = str(txt).lower()
    if any(x in t for x in ["thunder", "storm"]):
        return "TSTM"
    if any(x in t for x in ["snow", "blizzard"]):
        return "SNOW"
    if any(x in t for x in ["sleet", "freezing"]):
        return "SLEET"
    if any(x in t for x in ["fog", "haze"]):
        return "FOG"
    if "shower" in t:
        return "SHWRS"
    if any(x in t for x in ["rain", "drizzle"]):
        return "RAIN"
    if "partly cloudy" in t:
        return "PTCLDY"
    if "mostly cloudy" in t:
        return "MSTCLDY"
    if "cloudy" in t:
        return "CLOUDY"
    if any(x in t for x in ["sunny", "clear"]):
        return "SUNNY"
    return "---"


# ═══════════════════════════════════════════════════════════════════════════════
#  6. UI COMPONENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def make_dial(v, t, min_v, max_v, u, c, sub=""):
    parts = [f"<b>{t}</b>"]
    if sub:
        parts.append(f"<span style='font-size:11px;color:#7AACCC'>{sub}</span>")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": u, "font": {"size": 24, "color": "white"}, "valueformat": ".1f"},
        title={"text": "<br>".join(parts), "font": {"size": 13, "color": "#A0C8E0"}},
        gauge={
            "axis": {"range": [min_v, max_v], "tickfont": {"size": 9, "color": "#334455"}},
            "bar": {"color": c, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=70, b=20, l=25, r=25),
        height=185
    )
    return fig


def make_stream_gauge(gid, v, min_v, max_v, unit, ranges, needle_clr,
                      status_lbl, status_clr, sub_line):
    t_js = json.dumps(
        [{"r0": x["range"][0], "r1": x["range"][1], "color": x["color"]} for x in ranges]
    )
    # Oscillation amplitude: 0.8% of total range — subtle but visible
    osc_amp = round((max_v - min_v) * 0.008, 4)
    # Arc pulse: dim ↔ bright cycle on the active arc segment
    return f"""<html><body style="background:transparent;text-align:center;
font-family:'Rajdhani',sans-serif;color:white;margin:0;padding:0;">
<canvas id="{gid}" width="260" height="150"></canvas>
<div id="{gid}_lbl" style="color:{status_clr};font-weight:700;font-size:16px;
     text-transform:uppercase;letter-spacing:2px;">{status_lbl}</div>
<div style="font-size:12px;color:#7AACCC;margin-top:4px;">{sub_line}</div>
<script>
(function(){{
    const canvas = document.getElementById('{gid}');
    const ctx    = canvas.getContext('2d');
    const cx=130, cy=125, r=95;
    const TARGET = {v};
    const MIN_V  = {min_v};
    const MAX_V  = {max_v};
    const AMP    = {osc_amp};        // sine oscillation amplitude
    const RANGES = {t_js};

    function toA(val){{
        return Math.PI + ((val - MIN_V) / (MAX_V - MIN_V)) * Math.PI;
    }}

    let cur      = MIN_V;            // start from zero → eases in
    let t0       = null;
    let phase    = Math.random() * Math.PI * 2;   // random start phase

    function draw(ts){{
        if(!t0) t0 = ts;
        const elapsed = (ts - t0) / 1000;   // seconds

        // 1. Ease cur → TARGET (fast at start, slows near target)
        cur += (TARGET - cur) * 0.06;

        // 2. Continuous micro-oscillation once near target
        const nearTarget = Math.abs(cur - TARGET) < AMP * 3;
        const osc = nearTarget
            ? AMP * Math.sin(elapsed * 0.8 + phase)          // slow ~0.8 rad/s
            : 0;
        const display = Math.max(MIN_V, Math.min(MAX_V, cur + osc));

        // 3. Arc pulse — alpha breathes between 0.55 and 1.0 at ~0.4 Hz
        const pulse = 0.775 + 0.225 * Math.sin(elapsed * 2.5 + phase);

        ctx.clearRect(0, 0, 260, 150);

        // Draw arc segments with breathing alpha
        RANGES.forEach(seg => {{
            ctx.beginPath();
            // Determine if needle is inside this segment (active = brighter)
            const active = display >= seg.r0 && display <= seg.r1;
            const base   = seg.color.replace(/[\d.]+\)$/, '');
            const alpha  = active ? pulse : 0.45;
            ctx.strokeStyle = seg.color.replace(
                /[\d.]+\)$/,
                alpha.toFixed(3) + ')'
            );
            ctx.lineWidth = 20;
            ctx.arc(cx, cy, r, toA(seg.r0), toA(seg.r1));
            ctx.stroke();
        }});

        // Needle glow
        const ang = toA(display);
        const nx  = cx + r * Math.cos(ang);
        const ny  = cy + r * Math.sin(ang);

        ctx.shadowColor  = '{needle_clr}';
        ctx.shadowBlur   = 8 + 4 * Math.sin(elapsed * 3 + phase);
        ctx.beginPath();
        ctx.strokeStyle = '{needle_clr}';
        ctx.lineWidth   = 3;
        ctx.moveTo(cx, cy);
        ctx.lineTo(nx, ny);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Pivot dot
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, 2*Math.PI);
        ctx.fillStyle = '{needle_clr}';
        ctx.fill();

        // Value readout (show real target value, not oscillated display)
        ctx.fillStyle   = 'white';
        ctx.font        = 'bold 20px Rajdhani';
        ctx.textAlign   = 'center';
        ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.fillText(TARGET.toFixed(2) + '{unit}', cx, cy - 40);

        requestAnimationFrame(draw);
    }}

    requestAnimationFrame(draw);
}})();
</script></body></html>"""


def _alert_style(event_name: str):
    e = event_name.lower()
    if "warning" in e:
        return {
            "border": "#FF3333",
            "text": "#FFCCCC",
            "title": "#FF6666",
            "bg": "rgba(255,51,51,0.10)",
        }
    if "watch" in e:
        return {
            "border": "#FF8800",
            "text": "#FFE0C2",
            "title": "#FFB066",
            "bg": "rgba(255,136,0,0.10)",
        }
    return {
        "border": "#FFD700",
        "text": "#FFF3B0",
        "title": "#FFE866",
        "bg": "rgba(255,215,0,0.10)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  7. DATA EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

current_conditions = fetch_current_conditions()
forecast           = _build_unified_daily_forecast()
backup_hist        = fetch_backup_precip_history()
station_rain       = fetch_realtime_station_bundle()
active_alerts      = fetch_active_alerts()
hwo_text           = fetch_hazardous_weather_outlook()

sm_07, sm_728, sm_ts, sm_ok       = fetch_era5_soil_moisture()
usdm_level, usdm_label, usdm_date = fetch_usdm_drought()

if station_rain.get("ok", False):
    rain_24h         = station_rain.get("rain_24h_in") or backup_hist["rain_24h_in"]
    rain_5d          = station_rain.get("rain_5d_in")  or backup_hist["rain_5d_in"]
    rain_7d          = station_rain.get("rain_7d_in")  or backup_hist["rain_7d_in"]
    rain_14d         = station_rain.get("rain_14d_in") or backup_hist["rain_14d_in"]
    display_rain_now = station_rain.get("rain_rate_in_hr")
    if display_rain_now is None:
        display_rain_now = current_conditions["precip"]
else:
    rain_24h         = backup_hist["rain_24h_in"]
    rain_5d          = backup_hist["rain_5d_in"]
    rain_7d          = backup_hist["rain_7d_in"]
    rain_14d         = backup_hist["rain_14d_in"]
    display_rain_now = current_conditions["precip"]

soil_sat, soil_stored, soil_color = calc_soil_saturation_ensemble(
    sm_07, sm_728, sm_ok, rain_5d, usdm_level
)

_UP_DRAIN_FACTOR = (((UP_TC_HRS / LO_TC_HRS) ** 0.5) * 0.60 +
                    (UP_CN_II / LO_CN_II) * 0.40)

soil_sat_lo = soil_sat
soil_sat_up = round(min(100.0, max(1.0, soil_sat * _UP_DRAIN_FACTOR)), 1)


def _sat_color(s):
    return "#FF3333" if s > 85 else "#FF8800" if s > 70 else "#FFD700" if s > 50 else "#00FF9C"


def _sat_stored(s):
    return round((s / 100.0) * (SOIL_POROSITY * 11.024), 2)


soil_color_lo  = _sat_color(soil_sat_lo)
soil_color_up  = _sat_color(soil_sat_up)
soil_stored_lo = soil_stored
soil_stored_up = _sat_stored(soil_sat_up)

qpf_24h = forecast[0]["qpf_in"] if forecast else 0.0
pop_24h  = forecast[0]["pop"]    if forecast else 0.0

threat          = flood_threat_score(soil_sat_lo, qpf_24h, pop_24h)
t_lbl, t_clr, t_bg = threat_meta(threat)

lo_depth, lo_flow = model_stream(
    soil_sat_lo, rain_24h, qpf_24h, rain_7d,
    LO_DA_SQMI, LO_TC_HRS, LO_CN_II, LO_BASEFLOW,
    LO_RATING_A, LO_RATING_B, LO_BANKFULL_Q
)

up_depth, up_flow = model_stream(
    soil_sat_up, rain_24h, qpf_24h, rain_7d,
    UP_DA_SQMI, UP_TC_HRS, UP_CN_II, UP_BASEFLOW,
    UP_RATING_A, UP_RATING_B, UP_BANKFULL_Q
)

if "lo_depth" not in st.session_state:
    st.session_state.lo_depth = lo_depth
if "lo_flow" not in st.session_state:
    st.session_state.lo_flow = lo_flow
if "up_depth" not in st.session_state:
    st.session_state.up_depth = up_depth
if "up_flow" not in st.session_state:
    st.session_state.up_flow = up_flow

st.session_state.lo_depth = round(st.session_state.lo_depth * 0.30 + lo_depth * 0.70, 2)
st.session_state.lo_flow  = round(st.session_state.lo_flow  * 0.30 + lo_flow  * 0.70, 1)
st.session_state.up_depth = round(st.session_state.up_depth * 0.30 + up_depth * 0.70, 2)
st.session_state.up_flow  = round(st.session_state.up_flow  * 0.30 + up_flow  * 0.70, 1)

lo_depth_lbl, lo_depth_clr = stage_status(st.session_state.lo_depth, LO_BANKFULL)
up_depth_lbl, up_depth_clr = stage_status(st.session_state.up_depth, UP_BANKFULL)
lo_flow_lbl,  lo_flow_clr  = flow_status(st.session_state.lo_flow,   LO_BANKFULL_Q)
up_flow_lbl,  up_flow_clr  = flow_status(st.session_state.up_flow,   UP_BANKFULL_Q)

lo_bkf_pct = round(min(100, st.session_state.lo_depth / LO_BANKFULL * 100), 1)
up_bkf_pct = round(min(100, st.session_state.up_depth / UP_BANKFULL * 100), 1)

_q_ref         = max(LO_BASEFLOW, st.session_state.lo_flow)
_wave_base     = FLOOD_TRAVEL_MIN
_travel_raw    = _wave_base * (LO_BASEFLOW / _q_ref) ** 0.40
_travel_ripple = (st.session_state.up_flow % 7.3) * 0.41 - 1.5
travel_min     = round(min(90.0, max(15.0, _travel_raw + _travel_ripple)), 1)

_tw_clr = ("#FF3333" if travel_min < 25 else
           "#FF8800" if travel_min < 35 else
           "#FFD700" if travel_min < 50 else "#00FF9C")


# ═══════════════════════════════════════════════════════════════════════════════
#  8. RENDER
# ═══════════════════════════════════════════════════════════════════════════════

now_et = datetime.now(ET_TZ)

# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="site-header">
  <div class="site-title">NOAH: CULLOWHEE CREEK FLOOD WARNING</div>
  <div class="site-sub">
    Cullowhee Creek Watershed &mdash; Jackson County, NC
    &nbsp;|&nbsp;
    {now_et.strftime("%A, %B %d %Y")} &mdash; {now_et.strftime("%H:%M")}
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 1: FLOOD THREAT BANNER ─────────────────────────────────────────────
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
    SOIL SAT (LOWER) {soil_sat_lo:.1f}% &nbsp;&middot;&nbsp; (UPPER) {soil_sat_up:.1f}%
    &nbsp;&middot;&nbsp; QPF(24h) {qpf_24h:.2f}&quot;
    &nbsp;&middot;&nbsp; PoP {pop_24h:.0f}%
    &nbsp;&middot;&nbsp; LOWER {lo_bkf_pct:.0f}% of bankfull
    &nbsp;&middot;&nbsp; UPPER {up_bkf_pct:.0f}% of bankfull
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.68em;
              color:#3A6A8A; margin-top:10px; letter-spacing:1px;">
    EVALUATED FACTORS: Soil Saturation &middot; 24hr Rainfall Forecast &middot; Probability of Precipitation
  </div>
</div>""", unsafe_allow_html=True)


# ── PANEL 1B: ACTIVE WEATHER ALERTS ──────────────────────────────────────────
if active_alerts:
    st.markdown('<div class="panel"><div class="panel-title">ACTIVE WEATHER ALERTS</div>', unsafe_allow_html=True)
    for a in active_alerts:
        style = _alert_style(a["event"])
        expires_line = f"Until {a['expires_local']}" if a["expires_local"] else ""
        summary = a["headline"] if a["headline"] else a["description"]
        if len(summary) > 220:
            summary = summary[:217] + "..."
        st.markdown(f"""
<div style="background:{style['bg']}; border-left:6px solid {style['border']};
            border-radius:8px; padding:14px 16px; margin-bottom:10px;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.78em; color:{style['title']};
              letter-spacing:2px; margin-bottom:6px;">
    {a['event'].upper()}
  </div>
  <div style="font-size:0.92em; color:{style['text']}; line-height:1.45;">
    {summary}
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.66em; color:#7AACCC; margin-top:8px;">
    {expires_line}
  </div>
</div>
""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 1C: HAZARDOUS WEATHER OUTLOOK ──────────────────────────────────────
if hwo_text:
    _hwo_border = "#FF8800"
    _hwo_bg     = "rgba(255,136,0,0.07)"
    _hwo_clr    = "#FFB066"
    _hwo_sub    = "#FFE0C2"

    # Build inner HTML for each paragraph section.
    # Body text is already HTML-escaped by the fetch function;
    # convert newlines to <br> for proper rendering.
    _para_html = ""
    for para in hwo_text["paragraphs"]:
        if para["header"]:
            _para_html += (
                f'<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.72em;'
                f' color:{_hwo_clr}; letter-spacing:2px; margin:14px 0 5px;">'
                f'{para["header"]}</div>'
            )
        body_html = para["body"].replace("\n\n", "<br><br>").replace("\n", " ")
        _para_html += (
            f'<div style="font-family:\'Rajdhani\',sans-serif; font-size:1.0em;'
            f' color:{_hwo_sub}; line-height:1.65; margin-bottom:4px;">'
            f'{body_html}</div>'
        )

    st.markdown(f"""
<div style="background:{_hwo_bg}; border:2px solid {_hwo_border}; border-radius:10px;
            padding:20px 28px; margin-bottom:16px;">
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em;
              color:{_hwo_clr}; letter-spacing:4px; margin-bottom:6px; text-align:center;">
    NWS ACTIVE PRODUCT
  </div>
  <div style="font-size:3.0em; font-weight:700; color:{_hwo_clr};
              letter-spacing:4px; line-height:1.0; text-align:center; margin-bottom:12px;">
    HAZARDOUS WEATHER OUTLOOK
  </div>
  <div style="font-family:'Share Tech Mono',monospace; font-size:0.65em;
              color:#7AACCC; letter-spacing:1px; margin-bottom:14px; text-align:center;
              border-bottom:1px solid rgba(255,136,0,0.25); padding-bottom:10px;">
    NWS GREENVILLE-SPARTANBURG (GSP) &nbsp;&middot;&nbsp; JACKSON COUNTY, NC
    &nbsp;&middot;&nbsp; ISSUED: {hwo_text['issued']}
  </div>
  {_para_html}
</div>
""", unsafe_allow_html=True)


# ── PANEL 2: ATMOSPHERIC CONDITIONS ──────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3)
with c1:
    st.plotly_chart(make_dial(current_conditions["wind"], "WIND SPEED", 0, 50, " mph", "#5AC8FA"), use_container_width=True)
with c2:
    st.plotly_chart(make_dial(current_conditions["temp"], "TEMPERATURE", 0, 110, " F", "#FF3333"), use_container_width=True)
with c3:
    st.plotly_chart(make_dial(display_rain_now, "RAIN NOW", 0, 4, '" / hr', "#0077FF", sub="Current intensity"), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 3: UPPER WATERSHED — HEADWATERS ────────────────────────────────────
_up_bkf = UP_BANKFULL
_up_max = _up_bkf * 2.5

st.markdown(
    f'<div class="upper-panel"><div class="upper-title">'
    f'UPPER CULLOWHEE CREEK '
    f'({UP_AREA_ACRES:,} AC | {UP_DA_SQMI:.2f} mi²)'
    f'</div>',
    unsafe_allow_html=True
)

u1, u2, u3 = st.columns([2, 2, 3])

with u1:
    st.components.v1.html(make_stream_gauge(
        "g_up_depth", st.session_state.up_depth,
        0.0, _up_max, " ft",
        [{"range": [0.0,          _up_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_up_bkf*0.60, _up_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_up_bkf*0.95, _up_max],         "color": "rgba(255,51,51,0.25)"}],
        up_depth_clr, up_depth_lbl, up_depth_clr,
        f"Stage: {st.session_state.up_depth:.2f} ft"
    ), height=240)

with u2:
    _up_q_max = UP_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_up_flow", st.session_state.up_flow,
        0.0, _up_q_max, " cfs",
        [{"range": [0.0,               UP_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [UP_BANKFULL_Q*0.45, UP_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [UP_BANKFULL_Q*0.95, _up_q_max],             "color": "rgba(255,51,51,0.25)"}],
        up_flow_clr, up_flow_lbl, up_flow_clr,
        f"Q: {st.session_state.up_flow:.1f} cfs"
    ), height=240)

with u3:
    st.markdown(f"""
<div style="background:rgba(0,50,30,0.18); border:1px solid rgba(0,180,100,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#00CC77; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,180,100,0.2); padding-bottom:6px;">
    SOIL SATURATION
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_up}; text-align:center;
              margin:6px 0 4px;">{soil_sat_up:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:8px;">
    stored: {soil_stored_up:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 4: LOWER WATERSHED ─────────────────────────────────────────────────
_lo_bkf = LO_BANKFULL
_lo_max = _lo_bkf * 2.5

st.markdown(
    f'<div class="lower-panel"><div class="lower-title">'
    f'LOWER CULLOWHEE CREEK ({LO_AREA_ACRES:,} AC | {LO_DA_SQMI:.2f} mi²)'
    f'</div>',
    unsafe_allow_html=True
)

l1, l2, l3 = st.columns([2, 2, 3])

with l1:
    st.components.v1.html(make_stream_gauge(
        "g_lo_depth", st.session_state.lo_depth,
        0.0, _lo_max, " ft",
        [{"range": [0.0,          _lo_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_lo_bkf*0.60, _lo_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_lo_bkf*0.95, _lo_max],         "color": "rgba(255,51,51,0.25)"}],
        lo_depth_clr, lo_depth_lbl, lo_depth_clr,
        f"Stage: {st.session_state.lo_depth:.2f} ft"
    ), height=240)

with l2:
    _lo_q_max = LO_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_lo_flow", st.session_state.lo_flow,
        0.0, _lo_q_max, " cfs",
        [{"range": [0.0,               LO_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [LO_BANKFULL_Q*0.45, LO_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [LO_BANKFULL_Q*0.95, _lo_q_max],             "color": "rgba(255,51,51,0.25)"}],
        lo_flow_clr, lo_flow_lbl, lo_flow_clr,
        f"Q: {st.session_state.lo_flow:.1f} cfs"
    ), height=240)

with l3:
    st.markdown(f"""
<div style="background:rgba(0,50,120,0.18); border:1px solid rgba(0,119,255,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#0077FF; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,119,255,0.2); padding-bottom:6px;">
    SOIL SATURATION
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_lo}; text-align:center;
              margin:6px 0 4px;">{soil_sat_lo:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:12px;">
    stored: {soil_stored_lo:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)


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
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.20);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0077FF;
                letter-spacing:2px; margin-bottom:8px;">DELTA (LOWER &minus; UPPER)</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">Watershed response amplification</div>
    <div style="font-size:2.2em; font-weight:700; color:#FFFF00;">{'+' if dd >= 0 else ''}{dd:.2f} ft</div>
    <div style="font-size:1.1em; color:#FFFF00; margin-bottom:8px;">{'+' if dq >= 0 else ''}{dq:.1f} cfs ({'+' if dq_pct >= 0 else ''}{dq_pct:.1f}%)</div>
  </div>

  <div style="background:rgba(0,100,200,0.07); border:1px solid rgba(0,119,255,0.25);
              border-radius:8px; padding:16px; text-align:center;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:#0099FF;
                letter-spacing:2px; margin-bottom:8px;">LOWER</div>
    <div style="font-size:0.75em; color:#7AACCC; margin-bottom:4px;">{LO_AREA_ACRES:,} ac | CN={LO_CN_II} | Tc={LO_TC_HRS}h</div>
    <div style="font-size:2.2em; font-weight:700; color:{comp_clr_lo};">{st.session_state.lo_depth:.2f} ft</div>
    <div style="font-size:1.1em; color:{lo_flow_clr};">{st.session_state.lo_flow:.1f} cfs</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.72em; color:{comp_clr_lo};
                margin-top:6px; letter-spacing:2px;">{lo_depth_lbl}</div>
  </div>

</div>
""", unsafe_allow_html=True)

tw1, tw2, tw3 = st.columns([1, 2, 1])
with tw2:
    st.plotly_chart(
        make_dial(travel_min, "WAVE TRAVEL", 15, 90, " min", _tw_clr, sub="UPPER → LOWER"),
        use_container_width=True
    )

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 6: 7-DAY FLOOD OUTLOOK ─────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">7-DAY FLOOD &amp; RAINFALL OUTLOOK &mdash; CULLOWHEE CREEK WATERSHED</div>', unsafe_allow_html=True)

if not forecast:
    st.warning("Forecast unavailable.")
else:
    pcols = st.columns(7)
    for i, d in enumerate(forecast[:7]):
        risk  = min(100.0, round((soil_sat_lo * 0.35) + (d["pop"] * 0.35) + (d["qpf_in"] * 20), 1))
        color = "#00FF9C" if risk < 30 else "#FFFF00" if risk < 50 else "#FFD700" if risk < 65 else "#FF8800" if risk < 80 else "#FF3333"
        with pcols[i]:
            st.markdown(
                '<div style="background:rgba(255,255,255,0.03); border-top:4px solid '
                + color
                + '; border-radius:8px; padding:12px 8px; text-align:center;">'
                + '<div style="font-weight:700; font-size:1.1em;">' + d["short_name"] + '</div>'
                + '<div style="font-size:0.75em; color:#5A7090; margin-bottom:4px;">' + d["date_label"] + '</div>'
                + '<div style="font-family:\'Share Tech Mono\',monospace; font-size:0.75em; color:#7AACCC; margin-bottom:4px;">' + forecast_icon(d.get("icon_txt", "")) + '</div>'
                + '<div style="color:' + color + '; font-size:1.55em; font-weight:700; margin:5px 0;">' + f'{risk:.1f}' + '%</div>'
                + '<div style="color:' + color + '; font-family:\'Share Tech Mono\',monospace; font-size:0.72em; letter-spacing:2px; margin-bottom:4px;">FLOOD RISK</div>'
                + '<div style="color:#00FFCC; font-family:\'Share Tech Mono\',monospace; font-size:0.85em;">' + f'{d["qpf_in"]:.2f}' + '&quot;</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["pop"]:.0f}' + '% PoP</div>'
                + '<div style="color:#7AACCC; font-size:0.75em;">' + f'{d["temp_f"]:.0f}' + ' F</div>'
                + '</div>',
                unsafe_allow_html=True
            )

st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 7: RADAR ───────────────────────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">RADAR LOOP</div>', unsafe_allow_html=True)

_cb = int(time.time() / 120)
st.components.v1.html(f"""
<div style="background:#04090F; border-radius:10px; border:1px solid #1a2a3a; overflow:hidden; font-family:'Courier New',monospace;">
  <div style="display:flex; align-items:center; justify-content:space-between;
              padding:8px 16px; background:#0a1520; border-bottom:1px solid #1a3a5a;">
    <div style="display:flex; align-items:center; gap:10px;">
      <div style="width:8px; height:8px; border-radius:50%; background:#00FF9C; box-shadow:0 0 6px #00FF9C;"></div>
      <span style="color:#00CFFF; font-size:11px; font-weight:700; letter-spacing:2px;">LIVE</span>
    </div>
    <div style="color:#556677; font-size:10px; letter-spacing:1px;">AUTO-LOOP &#x21BB; 2 MIN</div>
  </div>
  <div style="position:relative; background:#000; text-align:center;">
    <img src="https://radar.weather.gov/ridge/standard/KGSP_loop.gif?v={_cb}"
         style="width:100%; max-height:520px; object-fit:contain; display:block;" alt="Radar Loop" />
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
      </div>
    </div>
  </div>
</div>
""", height=610)

st.markdown('</div>', unsafe_allow_html=True)
