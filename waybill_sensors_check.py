#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перевірка датчиків путевого листа по всіх авто
на 01.04.2026 та 14.04.2026.
Метод API: GET /api/integration/v1/getobjectsreport
Результат: waybill_sensors_check.html
"""

import requests, sys, os, webbrowser
from datetime import datetime, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ─────────────────────────────────────────────────────────────────
LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
TZ_HOURS = 3
FMT      = "%Y-%m-%d %H:%M:%S"
OUT_FILE = "waybill_sensors_check.html"

GROUP_NAMES = {2998: "Автопарк 1", 3129: "Автопарк 2"}
GROUP_ORDER = [2998, 3129]

# Дати перевірки (local time)
CHECK_DATES = [
    {"label": "01.04.2026", "from": datetime(2026, 4,  1,  0,  0, 0),
                             "to":  datetime(2026, 4,  1, 23, 59, 0)},
    {"label": "14.04.2026", "from": datetime(2026, 4, 14,  0,  0, 0),
                             "to":  datetime(2026, 4, 14, 23, 59, 0)},
]

# Параметри путевого листа
WAYBILL_PARAMS = [
    ("start_can_dist",  "CAN-одометр початок"),
    ("stop_can_dist",   "CAN-одометр кінець"),
    ("odo_dist",        "Одометр км"),
    ("start_fuel_level","Бак початок л"),
    ("stop_fuel_level", "Бак кінець л"),
    ("fuelings",        "Заправка л"),
    ("all_fuel",        "Витрата л"),
    ("run_time",        "Час руху с"),
    ("motohours",       "Моточаси с"),
    ("start_move_time", "Час виїзду"),
    ("stop_move_time",  "Час заїзду"),
    ("start_address",   "Адреса виїзду"),
    ("stop_address",    "Адреса заїзду"),
]
PARAM_KEYS = [p[0] for p in WAYBILL_PARAMS]

# ── Auth ───────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(
    f"{BASE_URL}/api/integration/v1/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": str(TZ_HOURS)},
    timeout=30,
)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
print(f"Авторизовано. SessionId: {sid[:12]}...")

# ── Get vehicle list with groups ───────────────────────────────────────────
print("Отримання списку авто...")
resp = requests.get(
    f"{BASE_URL}/api/integration/v1/getobjectslist",
    headers={"SessionId": sid}, timeout=30,
)
objects = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
print(f"Знайдено авто: {len(objects)}")

# ── Fetch report for each date ─────────────────────────────────────────────
# results[date_label][oid] = {param_key: value or None}
results = {}
method_used = "GET /api/integration/v1/getobjectsreport"
all_ids = ";".join(str(o["id"]) for o in objects)

for date_cfg in CHECK_DATES:
    label    = date_cfg["label"]
    df_utc   = date_cfg["from"] - timedelta(hours=TZ_HOURS)
    dt_utc   = date_cfg["to"]   - timedelta(hours=TZ_HOURS)

    print(f"\nЗапит за {label}  [{df_utc.strftime(FMT)} UTC → {dt_utc.strftime(FMT)} UTC]")
    print(f"  Метод: {method_used}")

    resp = requests.get(
        f"{BASE_URL}/api/integration/v1/getobjectsreport",
        headers={"SessionId": sid},
        params={
            "date_from": df_utc.strftime(FMT),
            "date_to":   dt_utc.strftime(FMT),
            "objuids":   all_ids,
            "split":     "none",
            "param":     ";".join(PARAM_KEYS),
        },
        timeout=90,
    )

    date_results = {}
    if resp.status_code == 200:
        for obj in resp.json():
            oid    = obj.get("oid")
            period = (obj.get("periods") or [{}])[0]
            prms   = {p["name"]: p["value"] for p in (period.get("prms") or [])}
            row    = {}
            for key in PARAM_KEYS:
                v = prms.get(key)
                row[key] = str(v).strip() if v not in (None, "", "0", "0.000", "0.0") else None
                # keep "0.0" for fuelings (valid zero)
                if key == "fuelings" and v is not None:
                    row[key] = str(v).strip()
            date_results[oid] = row
        print(f"  ✓ Отримано відповідь для {len(date_results)} авто")
    else:
        print(f"  ✗ HTTP {resp.status_code}")

    results[label] = date_results

# ── Console output ─────────────────────────────────────────────────────────
print()
W = 120
print("=" * W)
print("  ПІДСУМОК: які параметри знайдені / не знайдені")
print("=" * W)

for gid in GROUP_ORDER:
    group_objs = [o for o in objects if o.get("groupId") == gid]
    print(f"\n  ── {GROUP_NAMES.get(gid)} ({len(group_objs)} авто) ──")
    print(f"  {'Авто':<20} {'Параметр':<24} {'01.04.2026':^18} {'14.04.2026':^18}  Метод")
    print("  " + "-" * 95)

    for obj in group_objs:
        oid   = obj["id"]
        first = True
        for key, label_p in WAYBILL_PARAMS:
            v1 = (results.get("01.04.2026") or {}).get(oid, {}).get(key)
            v2 = (results.get("14.04.2026") or {}).get(oid, {}).get(key)

            def fmt_val(v, key):
                if v is None:
                    return "✗ немає"
                if key in ("start_can_dist","stop_can_dist","odo_dist"):
                    try: return f"✓ {float(v):,.1f} км".replace(",", " ")
                    except: pass
                if key in ("start_fuel_level","stop_fuel_level","fuelings","all_fuel"):
                    try: return f"✓ {float(v):.1f} л"
                    except: pass
                if key in ("run_time","motohours"):
                    try:
                        sec = int(float(v))
                        return f"✓ {sec//3600}г {(sec%3600)//60}хв"
                    except: pass
                return f"✓ {str(v)[:22]}"

            s1 = fmt_val(v1, key)
            s2 = fmt_val(v2, key)

            name_col = obj["name"] if first else ""
            method_col = method_used if first else ""
            first = False

            print(f"  {name_col:<20} {label_p:<24} {s1:<18} {s2:<18}  {method_col}")
        print()

# ── HTML output ────────────────────────────────────────────────────────────
print("Формування HTML...")

def cell(v, key):
    if v is None:
        return '<td class="no">✗</td>'
    if key in ("start_can_dist", "stop_can_dist", "odo_dist"):
        try:
            disp = f"{float(v):,.3f}".replace(",", " ")
            return f'<td class="ok num">{disp}</td>'
        except: pass
    if key in ("start_fuel_level","stop_fuel_level","fuelings","all_fuel"):
        try:
            return f'<td class="ok num">{float(v):.1f}</td>'
        except: pass
    if key in ("run_time","motohours"):
        try:
            sec = int(float(v))
            return f'<td class="ok num">{sec//3600}г {(sec%3600)//60}хв</td>'
        except: pass
    short = str(v)[:30] + ("…" if len(str(v)) > 30 else "")
    return f'<td class="ok">{short}</td>'

# Header: param × date
date_labels = [d["label"] for d in CHECK_DATES]

# Build header row
th_params = "".join(
    f'<th colspan="{len(date_labels)}">{lbl}</th>'
    for _, lbl in WAYBILL_PARAMS
)
th_dates = "".join(
    f'<th>{dl}</th>'
    for _ in WAYBILL_PARAMS
    for dl in date_labels
)

group_html = ""
for gid in GROUP_ORDER:
    group_objs = [o for o in objects if o.get("groupId") == gid]
    gname = GROUP_NAMES.get(gid, f"Група {gid}")

    # Stats
    found_counts = {}  # label → (found_1apr, found_14apr)
    for obj in group_objs:
        oid = obj["id"]
        for key, _ in WAYBILL_PARAMS:
            v1 = (results.get("01.04.2026") or {}).get(oid, {}).get(key)
            v2 = (results.get("14.04.2026") or {}).get(oid, {}).get(key)
            found_counts.setdefault(key, [0, 0])
            if v1 is not None: found_counts[key][0] += 1
            if v2 is not None: found_counts[key][1] += 1

    rows_html = ""
    for obj in group_objs:
        oid = obj["id"]
        data_cells = ""
        for key, _ in WAYBILL_PARAMS:
            for dl in date_labels:
                v = (results.get(dl) or {}).get(oid, {}).get(key)
                data_cells += cell(v, key)

        # method column
        any_found = any(
            (results.get(dl) or {}).get(oid, {}).get(key) is not None
            for key, _ in WAYBILL_PARAMS for dl in date_labels
        )
        method_badge = (
            '<span class="badge-ok">getobjectsreport</span>'
            if any_found else
            '<span class="badge-no">немає даних</span>'
        )

        rows_html += f"""
        <tr>
          <td class="vname"><strong>{obj["name"]}</strong><br>
            <span class="vid">ID: {oid}</span><br>{method_badge}</td>
          {data_cells}
        </tr>"""

    # Stats row
    stat_cells = ""
    for key, _ in WAYBILL_PARAMS:
        for i, dl in enumerate(date_labels):
            cnt = found_counts.get(key, [0, 0])[i]
            tot = len(group_objs)
            cls = "stat-ok" if cnt == tot else ("stat-part" if cnt > 0 else "stat-no")
            stat_cells += f'<td class="stat {cls}">{cnt}/{tot}</td>'

    group_html += f"""
  <section>
    <div class="g-header">
      <span class="g-name">{gname}</span>
      <span class="g-info">Авто: {len(group_objs)} &nbsp;|&nbsp;
        Метод: <code>{method_used}</code></span>
    </div>
    <div class="scroll-wrap">
    <table>
      <thead>
        <tr>
          <th rowspan="2" style="width:170px">Автомобіль</th>
          {th_params}
        </tr>
        <tr>{th_dates}</tr>
        <tr class="stat-row">
          <td class="stat-hdr">Знайдено авто:</td>
          {stat_cells}
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>
  </section>"""

generated_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
n_params = len(WAYBILL_PARAMS)
n_dates  = len(date_labels)

html = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<title>Перевірка датчиків путевого листа</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px;
       background: #eef0f4; color: #222; padding: 20px; }}
h1   {{ font-size: 18px; color: #1565c0; margin-bottom: 4px; }}
.sub {{ color: #888; font-size: 11px; margin-bottom: 20px; }}

section {{ margin-bottom: 36px; }}
.scroll-wrap {{ overflow-x: auto; }}

.g-header {{ display:flex; align-items:center; gap:20px;
             background:#1565c0; color:#fff; padding:9px 16px;
             border-radius:6px 6px 0 0; }}
.g-name {{ font-size:15px; font-weight:700; }}
.g-info {{ font-size:11px; opacity:.85; }}
.g-info code {{ background:rgba(255,255,255,.2); padding:1px 5px;
                border-radius:3px; font-size:11px; }}

table {{ border-collapse: collapse; background:#fff;
         box-shadow: 0 2px 8px rgba(0,0,0,.1);
         border-radius: 0 0 6px 6px; min-width:100%; }}
th {{ background:#1a237e; color:#fff; padding:6px 8px;
      font-size:10px; font-weight:700; text-align:center;
      white-space:nowrap; border:1px solid #283593; }}
td {{ padding:5px 7px; border:1px solid #e8e8e8;
      text-align:center; vertical-align:middle; font-size:11px; }}

.vname {{ text-align:left !important; padding:7px 10px;
          min-width:160px; vertical-align:top; background:#fafbfd; }}
.vid    {{ font-size:10px; color:#aaa; }}

/* Values */
td.ok    {{ background:#e8f5e9; color:#1b5e20; }}
td.ok.num {{ font-family:monospace; font-size:11px; }}
td.no    {{ background:#fce4ec; color:#b71c1c; font-size:13px; }}

/* Stats row */
tr.stat-row td {{ background:#f5f5f5; font-weight:700; font-size:10px; padding:4px 6px; }}
.stat-hdr  {{ text-align:left !important; font-size:10px; color:#666; background:#f5f5f5; }}
.stat-ok   {{ color:#2e7d32; }}
.stat-part {{ color:#e65100; }}
.stat-no   {{ color:#c62828; }}

/* Method badges */
.badge-ok {{ display:inline-block; background:#e8f5e9; color:#2e7d32;
             border:1px solid #a5d6a7; border-radius:3px;
             padding:1px 5px; font-size:10px; margin-top:3px; }}
.badge-no {{ display:inline-block; background:#fce4ec; color:#c62828;
             border:1px solid #ef9a9a; border-radius:3px;
             padding:1px 5px; font-size:10px; margin-top:3px; }}

/* Legend */
.legend {{ display:flex; gap:16px; flex-wrap:wrap;
           background:#fff; padding:9px 14px; border-radius:6px;
           box-shadow:0 1px 4px rgba(0,0,0,.08); margin-bottom:20px;
           font-size:11px; }}
.li {{ display:flex; align-items:center; gap:5px; }}
.sq-ok {{ width:12px;height:12px;background:#e8f5e9;border:1px solid #4caf50;border-radius:2px; }}
.sq-no {{ width:12px;height:12px;background:#fce4ec;border:1px solid #e57373;border-radius:2px; }}

@media print {{
  body {{ background:#fff; padding:4px; }}
  .g-header {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  th {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
}}
</style>
</head>
<body>
<h1>Перевірка датчиків путевого листа — Mobiteam GPS</h1>
<p class="sub">Сформовано: {generated_at} &nbsp;|&nbsp;
  Авто: {len(objects)} &nbsp;|&nbsp;
  Параметри ПЛ: {n_params} &nbsp;|&nbsp;
  Дати перевірки: {" / ".join(date_labels)} &nbsp;|&nbsp;
  Метод: <strong>{method_used}</strong></p>

<div class="legend">
  <div class="li"><div class="sq-ok"></div> Дані знайдено методом getobjectsreport</div>
  <div class="li"><div class="sq-no"></div> Даних немає (метод не повернув значення)</div>
</div>

{group_html}

</body>
</html>"""

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Готово → {os.path.abspath(OUT_FILE)}")
webbrowser.open(f"file:///{os.path.abspath(OUT_FILE).replace(os.sep, '/')}")
