#!/usr/bin/env python3
"""Heat Watch email report: 72-hour heat stress outlook for one site.

Writes report.json (subject, html, text) and chart.png into the output folder.
Same trigger rules and feels-like formula as heat-watch.html.
"""
import argparse, base64, json, math, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TZ = "Australia/Brisbane"
SITE_URL = "https://soheilheydari25.github.io/heat-watch/"
HOURS = 72
RULES = dict(caution=32, stop=35, humid_air=29, humid_rh=75, extreme=40, work_start=6, work_end=18, work_only=True)
LEVELS = ["No trigger", "Caution", "Stop-work trigger", "Extreme heat"]
SHORT = ["Normal", "Caution", "Stop-work", "Extreme"]
COL = ["#2F8F5B", "#E9B800", "#D2520E", "#A8132C"]
ON = ["#FFFFFF", "#16191B", "#FFFFFF", "#FFFFFF"]


def feels_like(t, rh, ws):
    if t is None or rh is None:
        return None
    e = rh / 100 * 6.105 * math.exp(17.27 * t / (237.7 + t))
    return t + 0.33 * e - 0.70 * (ws or 0) - 4.00


def in_shift(h):
    return RULES["work_start"] <= h < RULES["work_end"]


def raw_level(t, rh, fl):
    if t is None:
        return 0, []
    lvl, why = 0, []
    if fl is not None and fl >= RULES["caution"]:
        lvl = max(lvl, 1); why.append(f"Feels like {RULES['caution']}°C+")
    if rh is not None and t >= RULES["humid_air"] and rh >= RULES["humid_rh"]:
        lvl = max(lvl, 2); why.append(f"{RULES['humid_air']}°C+ with {RULES['humid_rh']}%+ humidity")
    if t >= RULES["stop"]:
        lvl = max(lvl, 2); why.append(f"Air {RULES['stop']}°C+")
    if t >= RULES["extreme"]:
        lvl = 3; why.append(f"Air {RULES['extreme']}°C+")
    return lvl, why


def fetch(lat, lon):
    base = "https://api.open-meteo.com/v1/forecast"
    params = dict(latitude=lat, longitude=lon, hourly="temperature_2m,relative_humidity_2m,wind_speed_10m",
                  wind_speed_unit="ms", timezone=TZ, forecast_days=4)
    last = None
    for model, label in [("bom_access_global", "BOM ACCESS-G model"), (None, "Open-Meteo best-match models (BOM ACCESS-G unavailable)")]:
        p = dict(params)
        if model:
            p["models"] = model
        try:
            r = None
            for attempt in range(4):
                try:
                    r = requests.get(base, params=p, timeout=30); break
                except requests.RequestException:
                    if attempt == 3: raise
                    import time; time.sleep(5 * (attempt + 1))
            j = r.json()
            if r.status_code != 200 or j.get("error"):
                raise RuntimeError(j.get("reason", r.status_code))
            h = j["hourly"]
            if sum(v is not None for v in h["temperature_2m"][:96]) < 60:
                raise RuntimeError("incomplete data")
            return h, label
        except Exception as e:  # try next model
            last = e
    raise SystemExit(f"Forecast fetch failed: {last}")


def hour_label(dt):
    h = dt.hour
    return "12 am" if h == 0 else f"{h} am" if h < 12 else "12 pm" if h == 12 else f"{h-12} pm"


def day_label(dt):
    return f"{dt:%a} {dt.day} {dt:%b}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Marlborough")
    ap.add_argument("--address", default="Marlborough, Queensland, Australia")
    ap.add_argument("--lat", type=float, default=-22.8135)
    ap.add_argument("--lon", type=float, default=149.8895)
    ap.add_argument("--out", default="heat_out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    h, source = fetch(a.lat, a.lon)
    tz = ZoneInfo(TZ)
    now = datetime.now(tz).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    times = [datetime.fromisoformat(s) for s in h["time"]]
    start = next((i for i, t in enumerate(times) if t >= now), 0)
    sl = slice(start, start + HOURS)
    T, RH, WS = h["temperature_2m"][sl], h["relative_humidity_2m"][sl], h["wind_speed_10m"][sl]
    times = times[sl]
    FL = [feels_like(t, rh, ws) for t, rh, ws in zip(T, RH, WS)]
    A = []
    for i, dt in enumerate(times):
        lvl, why = raw_level(T[i], RH[i], FL[i])
        counted = (not RULES["work_only"]) or in_shift(dt.hour)
        A.append(dict(lvl=lvl if counted else 0, raw=lvl, why=why))

    # trigger periods
    events, cur = [], None
    for i, a_ in enumerate(A):
        if a_["lvl"] >= 1:
            if cur is None:
                cur = dict(start=i, end=i, peak=0, why=[], maxT=-99, maxFl=-99, rh=None)
            cur["end"] = i; cur["peak"] = max(cur["peak"], a_["lvl"])
            for w in a_["why"]:
                if w not in cur["why"]:
                    cur["why"].append(w)
            if T[i] is not None and T[i] > cur["maxT"]:
                cur["maxT"], cur["rh"] = T[i], RH[i]
            if FL[i] is not None and FL[i] > cur["maxFl"]:
                cur["maxFl"] = FL[i]
        elif cur:
            events.append(cur); cur = None
    if cur:
        events.append(cur)

    r0 = lambda v: "–" if v is None else str(round(v))
    dur = lambda n: "1 hour" if n == 1 else f"{n} hours"

    # daily outlook
    days = []
    for d in sorted({t.date() for t in times}):
        idx = [i for i, t in enumerate(times) if t.date() == d]
        tv = [(T[i], i) for i in idx if T[i] is not None]
        mx, mi = max(tv) if tv else (None, None)
        mf = max((FL[i] for i in idx if FL[i] is not None), default=None)
        lv = max(A[i]["lvl"] for i in idx)
        al = [i for i in idx if A[i]["lvl"] >= 1]
        days.append(dict(day=day_label(times[idx[0]]), part=len(idx) < 24, n=len(idx), mx=mx, mf=mf,
                         rh=RH[mi] if mi is not None else None, lvl=lv, hours=len(al),
                         st=hour_label(times[al[0]]) if al else "–",
                         fin=hour_label(times[al[-1]] + timedelta(hours=1)) if al else "–"))

    # chart
    fig, ax = plt.subplots(figsize=(9, 3.3), dpi=100)
    x = list(range(len(times)))
    for i, t in enumerate(times):
        if not in_shift(t.hour):
            ax.axvspan(i - .5, i + .5, color="#16191B", alpha=.05, lw=0)
        if A[i]["lvl"]:
            ax.axvspan(i - .5, i + .5, ymin=0, ymax=.035, color=COL[A[i]["lvl"]], lw=0)
    for v, c, lab in [(RULES["caution"], COL[1], "Caution, feels like"), (RULES["stop"], COL[2], "Stop-work"), (RULES["extreme"], COL[3], "Extreme")]:
        ax.axhline(v, color=c, ls="--", lw=1.2)
        ax.text(len(x) - .5, v + .3, f"{lab} {v}°", color=c, ha="right", va="bottom", fontsize=8, fontweight="bold")
    ax.plot(x, [v if v is not None else float("nan") for v in T], color="#16191B", lw=2.2, label="Air temp")
    ax.plot(x, [v if v is not None else float("nan") for v in FL], color=COL[2], lw=1.8, ls=(0, (5, 3)), label="Feels like")
    ax2 = ax.twinx()
    ax2.plot(x, [v if v is not None else float("nan") for v in RH], color="#3B7FB8", lw=1.2, alpha=.7, label="Humidity")
    ax2.set_ylim(0, 100); ax2.set_ylabel("Humidity %", color="#7A8388", fontsize=8)
    lo = min([v for v in T + FL if v is not None] + [15]); hi = max([v for v in T + FL if v is not None] + [RULES["extreme"]])
    ax.set_ylim(math.floor(lo / 5) * 5, math.ceil((hi + 2) / 5) * 5)
    ticks = [i for i, t in enumerate(times) if t.hour % 6 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([day_label(times[i]) if times[i].hour == 0 else hour_label(times[i]) for i in ticks], fontsize=8)
    ax.set_xlim(-.5, len(x) - .5)
    ax.set_ylabel("°C", color="#7A8388", fontsize=8)
    for s in ("top",):
        ax.spines[s].set_visible(False); ax2.spines[s].set_visible(False)
    ax.grid(axis="y", color="#D6DBD8", lw=.6)
    ax.tick_params(colors="#4A5256", labelsize=8); ax2.tick_params(colors="#4A5256", labelsize=8)
    l1, n1 = ax.get_legend_handles_labels(); l2, n2 = ax2.get_legend_handles_labels()
    ax.legend(l1 + l2, n1 + n2, loc="upper left", fontsize=8, frameon=False, ncol=3)
    fig.tight_layout()
    chart = os.path.join(a.out, "chart.png")
    fig.savefig(chart); plt.close(fig)
    try:  # shrink the PNG so it embeds easily in the email
        from PIL import Image
        Image.open(chart).convert("RGB").quantize(colors=24).save(chart, optimize=True)
    except Exception:
        pass

    # headline
    issued = datetime.now(tz)
    if events:
        w = sorted(events, key=lambda e: (-e["peak"], e["start"]))[0]
        fin = times[w["end"]] + timedelta(hours=1)
        head = f"{LEVELS[w['peak']]}: {day_label(times[w['start']])}, {hour_label(times[w['start']])} to {hour_label(fin)}"
        subject = f"Heat Watch {a.name}: {SHORT[w['peak']]} {day_label(times[w['start']])} {hour_label(times[w['start']])}–{hour_label(fin)}"
        lvl_top = w["peak"]
    else:
        head = "No heat triggers in the next 72 hours"
        subject = f"Heat Watch {a.name}: no heat triggers next 72 hours"
        lvl_top = 0
    issued_txt = issued.strftime("%I:%M %p").lstrip("0").lower()
    subject += f" (issued {issued_txt} {day_label(issued)})"

    BG = ["#CFE2D5", COL[1], COL[2], COL[3]]; FG = ["#16191B", ON[1], ON[2], ON[3]]
    badge = lambda l: (f'<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:12px;'
                       f'font-weight:600;background:{BG[l]};color:{FG[l]}">{SHORT[l]}</span>')
    th = 'style="text-align:left;padding:7px 10px;border-bottom:1px solid #C3C9C6;font-size:12px;color:#4A5256;white-space:nowrap"'
    td = 'style="padding:7px 10px;border-bottom:1px solid #D6DBD8;font-size:13px;white-space:nowrap"'
    tdw = 'style="padding:7px 10px;border-bottom:1px solid #D6DBD8;font-size:13px"'
    tbl = 'style="border-collapse:collapse;width:100%"'
    h3 = 'style="margin:18px 0 6px;font-size:16px"'

    ev_rows = "".join(
        f"<tr><td {td}><b>{day_label(times[e['start']])}</b></td><td {td}>{badge(e['peak'])}</td>"
        f"<td {td}>{r0(e['maxT'])}°C</td><td {td}>{r0(e['maxFl'])}°C</td><td {td}>{r0(e['rh'])}%</td>"
        f"<td {tdw}>{', '.join(e['why'])}</td><td {td}>{dur(e['end']-e['start']+1)}</td>"
        f"<td {td}>{hour_label(times[e['start']])}</td><td {td}>{hour_label(times[e['end']] + timedelta(hours=1))}</td></tr>"
        for e in events) or f'<tr><td {tdw} colspan="9">No triggers in the next 72 hours during work hours.</td></tr>'
    day_rows = "".join(
        f"<tr><td {td}><b>{d['day']}</b>{' <span style="color:#7A8388">(' + str(d['n']) + ' h of forecast)</span>' if d['part'] else ''}</td>"
        f"<td {td}>{r0(d['mx'])}°C</td><td {td}>{r0(d['mf'])}°C</td><td {td}>{r0(d['rh'])}%</td><td {td}>{badge(d['lvl'])}</td>"
        f"<td {td}>{dur(d['hours']) if d['hours'] else '–'}</td><td {td}>{d['st']}</td><td {td}>{d['fin']}</td></tr>"
        for d in days)

    greet = "Good morning" if issued.hour < 12 else "Good afternoon"
    if lvl_top >= 2:
        care = "A stop-work level heat trigger is forecast, so please plan the work around the hottest hours and check in with your crews often."
    elif lvl_top == 1:
        care = "It is going to be warm out there, so please keep the water flowing, take breaks in the shade and keep an eye on your mates."
    else:
        care = "No heat triggers are forecast, but it is still worth keeping water handy and looking out for each other."
    btn = (f'<a href="{SITE_URL}" style="display:inline-block;background:#BC2225;color:#FFFFFF;text-decoration:none;'
           f'font-weight:600;font-size:14px;padding:9px 16px;border-radius:4px">Open the Heat Watch website</a>')
    html = f"""<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#16191B;max-width:820px">
<p style="font-size:14px;margin:0 0 10px">{greet} team,</p>
<p style="font-size:14px;margin:0 0 10px">Here is your Heat Watch update for {a.name}. {care}</p>
<p style="font-size:14px;margin:0 0 6px">For the live map, the hour-by-hour forecast and more detail, visit the Heat Watch website:</p>
<p style="margin:0 0 6px">{btn}</p>
<p style="font-size:12px;color:#7A8388;margin:0 0 16px"><a href="{SITE_URL}" style="color:#7A8388">{SITE_URL}</a></p>
<div style="border-left:8px solid {COL[lvl_top]};padding:12px 16px;background:#F6F7F5;border-radius:6px">
<div style="font-size:13px;color:#4A5256"><b style="color:#16191B">Heat Watch</b>&nbsp; 72-hour heat stress outlook for <b>{a.name}</b> ({a.address})</div>
<div style="font-size:22px;font-weight:700;margin-top:6px">{head}</div>
<div style="font-size:12px;color:#7A8388;margin-top:6px">Issued {issued_txt} {day_label(issued)} Brisbane time. Forecast from the {source}.</div></div>
<p style="font-size:13px;color:#4A5256;margin:12px 0 0">The hourly chart is attached as <b>heat-watch-chart.png</b> (air temp, feels like and humidity for the next 72 hours; shaded hours are outside the {RULES['work_start']} am to {RULES['work_end']-12} pm shift, and coloured marks along the bottom show trigger hours).</p>
<h3 {h3}>Trigger log</h3>
<table {tbl}><tr><th {th}>Date</th><th {th}>Level</th><th {th}>Peak air</th><th {th}>Peak feels like</th><th {th}>Humidity at peak</th><th {th}>Triggered by</th><th {th}>Duration</th><th {th}>Start</th><th {th}>Finish</th></tr>{ev_rows}</table>
<h3 {h3}>Daily outlook</h3>
<table {tbl}><tr><th {th}>Day</th><th {th}>Max air</th><th {th}>Max feels like</th><th {th}>Humidity at max</th><th {th}>Worst level</th><th {th}>Hours on alert</th><th {th}>Alert start</th><th {th}>Alert finish</th></tr>{day_rows}</table>
<p style="font-size:12px;color:#4A5256;margin-top:16px">Trigger rules: Caution at feels like {RULES['caution']}°C+; Stop-work at air {RULES['stop']}°C+, or {RULES['humid_air']}°C+ with {RULES['humid_rh']}%+ humidity; Extreme at air {RULES['extreme']}°C+. Counted during work hours only.
Plan early starts, extra rest breaks, shade and water when triggers are forecast.</p>
<p style="font-size:11px;color:#7A8388">Forecast guidance only. Work decisions follow CMC's heat management plan, the project's EBA and on-site checks such as the WHSQ heat stress calculator. Feels like uses the Bureau of Meteorology apparent temperature formula. Weather data by Open-Meteo.com (CC BY 4.0).</p>
<p style="font-size:14px;margin:16px 0 4px">More information, including the live map and rain forecast, is on the <a href="{SITE_URL}" style="color:#BC2225;font-weight:600">Heat Watch website</a>.</p>
<p style="font-size:14px;margin:12px 0 0">Stay safe and stay cool,<br><b>Heat Watch</b></p></div>"""

    lines = [f"{greet} team,", "", f"Here is your Heat Watch update for {a.name}. {care}", "",
             f"Live map, hourly forecast and more detail: {SITE_URL}", "",
             f"Heat Watch: {a.name} ({a.address})", head, f"Issued {issued_txt} {day_label(issued)} Brisbane time.", "", "Trigger log:"]
    lines += [f"- {day_label(times[e['start']])}: {SHORT[e['peak']]}, {hour_label(times[e['start']])} to {hour_label(times[e['end']] + timedelta(hours=1))} "
              f"({dur(e['end']-e['start']+1)}). Peak {r0(e['maxT'])}°C, feels like {r0(e['maxFl'])}°C. {', '.join(e['why'])}." for e in events] or ["- No triggers in the next 72 hours."]
    lines += ["", "The hourly chart is attached as heat-watch-chart.png.", f"More information is on the Heat Watch website: {SITE_URL}",
              "Forecast guidance only. Confirm on site with the WHSQ heat stress calculator.", "", "Stay safe and stay cool,", "Heat Watch"]

    with open(chart, "rb") as f:
        png_b64 = base64.b64encode(f.read()).decode()
    out = dict(subject=subject, html=html, text="\n".join(lines), chart_png_base64_file=os.path.join(a.out, "chart.b64"))
    with open(out["chart_png_base64_file"], "w") as f:
        f.write(png_b64)
    with open(os.path.join(a.out, "report.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(dict(subject=subject, events=len(events), source=source, out=a.out)))


if __name__ == "__main__":
    main()
