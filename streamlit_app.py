# ── PANEL 2: ATMOSPHERIC CONDITIONS ──────────────────────────────────────────
st.markdown('<div class="panel"><div class="panel-title">ATMOSPHERIC CONDITIONS</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.plotly_chart(make_dial(noaa["wind"],  "WIND SPEED",     0,  50, " mph", "#5AC8FA"), use_container_width=True)
with c2: st.plotly_chart(make_dial(travel_min, "WAVE TRAVEL", 15, 90, " min", _tw_clr, sub="UPPER → LOWER"), use_container_width=True)
with c3: st.plotly_chart(make_dial(noaa["temp"],  "TEMPERATURE",    0, 110, " F",   "#FF3333"), use_container_width=True)
with c4: st.plotly_chart(make_dial(rain_24h, "RAIN (24H)", 0, 10, '"', "#0077FF", sub="24-Hour Accumulation"), use_container_width=True)
with c5: st.plotly_chart(make_dial(soil_sat, "SOIL SATURATION", 0, 100, "%", "#0077FF", sub=f'{soil_stored:.2f}" Stored | ERA5-Land'), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 3: UPPER WATERSHED — HEADWATERS ────────────────────────────────────
# Gauge arc ranges now anchored to Ecoregion 66 bankfull stage (2.16 ft)
_up_bkf  = UP_BANKFULL
_up_max  = _up_bkf * 2.5

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
        "STREAM DEPTH", 0.0, _up_max, " ft",
        [{"range": [0.0,          _up_bkf * 0.60], "color": "rgba(0,255,156,0.15)"},
         {"range": [_up_bkf*0.60, _up_bkf * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [_up_bkf*0.95, _up_max],         "color": "rgba(255,51,51,0.25)"}],
        up_depth_clr, up_depth_lbl, up_depth_clr,
        f"Stage: {st.session_state.up_depth:.2f} ft  |  Bankfull: {UP_BANKFULL} ft  |  {up_bkf_pct:.0f}% bkf",
        "SCS TR-55 / E66"
    ), height=240)
with u2:
    _up_q_max = UP_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_up_flow", st.session_state.up_flow,
        "DISCHARGE", 0.0, _up_q_max, " cfs",
        [{"range": [0.0,                UP_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [UP_BANKFULL_Q*0.45, UP_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [UP_BANKFULL_Q*0.95, _up_q_max],            "color": "rgba(255,51,51,0.25)"}],
        up_flow_clr, up_flow_lbl, up_flow_clr,
        f"Q: {st.session_state.up_flow:.1f} cfs  |  Qbkf (E66): {UP_BANKFULL_Q:.0f} cfs",
        "SCS TR-55 / E66"
    ), height=240)
with u3:
    _era5_str  = f"{sm_sources['era5_pct']:.0f}%" if sm_sources['era5_pct'] is not None else "UNAVAIL"
    _api_str   = f"{sm_sources['api_pct']:.0f}%"
    _usdm_str  = f"{sm_sources['usdm_pct']:.0f}%" if sm_sources['usdm_pct'] is not None else "N/A"
    _usdm_clr  = "#FF8800" if usdm_level >= 3 else "#FFD700" if usdm_level == 2 else "#FFFF00" if usdm_level == 1 else "#00FF9C"
    _usdm_tag  = usdm_label if usdm_level >= 0 else "NO DATA"
    _era5_active = "✓" if sm_ok and sm_07 is not None else "✗"
    _usdm_active = "✓" if usdm_level >= 0 else "✗"
    st.markdown(f"""
<div style="background:rgba(0,50,30,0.18); border:1px solid rgba(0,180,100,0.22);
            border-radius:9px; padding:14px 16px; font-family:'Share Tech Mono',monospace;">
  <div style="font-size:0.72em; color:#00CC77; letter-spacing:3px; margin-bottom:10px;
              border-bottom:1px solid rgba(0,180,100,0.2); padding-bottom:6px;">
    SOIL SATURATION &mdash; 3-SOURCE ENSEMBLE
  </div>
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_up}; text-align:center;
              margin:6px 0 4px;">{soil_sat_up:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:8px;">
    stored: {soil_stored_up:.2f}&quot; &nbsp;|&nbsp; pore capacity
  </div>
  <div style="font-size:0.63em; color:#3A7050; text-align:center; margin-bottom:10px;
              font-style:italic;">
    watershed avg {soil_sat_lo:.1f}% &times; drain factor {_UP_DRAIN_FACTOR:.3f}
  </div>
  <div style="display:grid; grid-template-columns:auto 1fr auto; gap:3px 8px;
              font-size:0.68em; align-items:center;">
    <span style="color:#3A8050;">{_era5_active}</span>
    <span style="color:#7AACCC;">ERA5-Land &nbsp;<span style="color:#2A6050;font-size:0.85em;">w={sm_sources['w_era5']:.0%}</span></span>
    <span style="color:#AACCDD;">{_era5_str}</span>
    <span style="color:#3A8050;">&#x2713;</span>
    <span style="color:#7AACCC;">API/HRRR 5-day &nbsp;<span style="color:#2A6050;font-size:0.85em;">w={sm_sources['w_api']:.0%}</span></span>
    <span style="color:#AACCDD;">{_api_str}</span>
    <span style="color:#3A8050;">{_usdm_active}</span>
    <span style="color:#7AACCC;">USDM &nbsp;<span style="color:#2A6050;font-size:0.85em;">w={sm_sources['w_usdm']:.0%}</span></span>
    <span style="color:#AACCDD;">{_usdm_str}</span>
  </div>
  <div style="margin-top:10px; padding-top:7px; border-top:1px solid rgba(0,120,80,0.25);
              font-size:0.65em; color:{_usdm_clr}; letter-spacing:1px;">
    USDM: {_usdm_tag}
  </div>
  <div style="font-size:0.60em; color:#2A5040; margin-top:3px;">
    Jackson Co. NC (FIPS 37099) &nbsp;|&nbsp; {usdm_date if usdm_date != "---" else "no date"}
  </div>
  <div style="font-size:0.60em; color:#2A5040; margin-top:1px;">
    ERA5 valid: {sm_ts_str}
  </div>
  <div style="margin-top:10px; padding-top:7px; border-top:1px solid rgba(0,120,80,0.25);
              font-size:0.62em; color:#1E6040; letter-spacing:1px; line-height:1.5;">
    E66 BANKFULL: {UP_BANKFULL_Q:.0f} cfs &nbsp;|&nbsp; stage {UP_BANKFULL:.2f} ft
    &nbsp;|&nbsp; W={UP_WIDTH_FT:.0f} ft &nbsp;|&nbsp; A={UP_RATING_A:.1f}&middot;D^{UP_RATING_B}
    <br>DA={UP_DA_SQMI:.2f} mi² &nbsp;|&nbsp; Henson 2014 / SCDNR E66 2020
  </div>
</div>
""", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)


# ── PANEL 4: LOWER WATERSHED ─────────────────────────────────────────────────
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
        "SCS TR-55 / E66"
    ), height=240)
with l2:
    _lo_q_max = LO_BANKFULL_Q * 3.0
    st.components.v1.html(make_stream_gauge(
        "g_lo_flow", st.session_state.lo_flow,
        "DISCHARGE", 0.0, _lo_q_max, " cfs",
        [{"range": [0.0,                LO_BANKFULL_Q * 0.45], "color": "rgba(0,255,156,0.15)"},
         {"range": [LO_BANKFULL_Q*0.45, LO_BANKFULL_Q * 0.95], "color": "rgba(255,215,0,0.20)"},
         {"range": [LO_BANKFULL_Q*0.95, _lo_q_max],            "color": "rgba(255,51,51,0.25)"}],
        lo_flow_clr, lo_flow_lbl, lo_flow_clr,
        f"Q: {st.session_state.lo_flow:.1f} cfs  |  Qbkf (E66): {LO_BANKFULL_Q:.0f} cfs",
        "SCS TR-55 / E66"
    ), height=240)
with l3:
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
  <div style="font-size:2.5em; font-weight:700; color:{soil_color_lo}; text-align:center;
              margin:6px 0 4px;">{soil_sat_lo:.1f}%</div>
  <div style="font-size:0.7em; color:#5AACD0; text-align:center; margin-bottom:12px;">
    stored: {soil_stored_lo:.2f}&quot; &nbsp;|&nbsp; pore capacity
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
                letter-spacing:2px; margin-bottom:8px;">LOWER</div>
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
        risk  = min(100.0, round((soil_sat_lo * 0.35) + (d["pop"] * 0.35) + (d["qpf"] * 20), 2))
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
