#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Список датчиків по всіх авто:
  - групи з API (getobjectslist → groupId)
  - датчики з API (objsensorslist?oid=...)
  - датчики для путевого листа виділено окремо
Результат: sensors_report.html
"""

import requests, sys, json, os
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
OUT_FILE = "sensors_report.html"

# Назви груп (groupId → назва)
GROUP_NAMES = {
    2998: "Автопарк 1",
    3129: "Автопарк 2",
}
GROUP_ORDER = [2998, 3129]

# Датчики потрібні для путевого листа:
# ключове слово (lower) → параметр API путевого листа
WAYBILL_MAP = {
    "абсолютный пробег":        "start_can_dist / stop_can_dist (CAN-одометр)",
    "накопленного пробега":     "odo_dist (одометр)",
    "накопленный пробег":       "odo_dist (одометр)",
    "уровень топлива":          "start_fuel_level / stop_fuel_level / fuelings",
    "сумматор датчиков":        "start_fuel_level / stop_fuel_level / fuelings",
    "топливо (":                "start_fuel_level / stop_fuel_level / fuelings",
    "бак 1":                    "start_fuel_level / stop_fuel_level / fuelings (бак 1)",
    "бак 2":                    "start_fuel_level / stop_fuel_level / fuelings (бак 2)",
    "зажигание":                "run_time (час руху)",
    "моточасы":                 "motohours (моточаси)",
    "адрес":                    "start_address / stop_address",
    "can расход топлива":       "all_fuel (загальний витрата)",
    "расход топлива":           "all_fuel (загальний витрата)",
}

def waybill_label(sensor_name: str):
    """Повертає мітку путевого листа або None."""
    lo = sensor_name.lower().strip()
    for kw, label in WAYBILL_MAP.items():
        if kw in lo:
            return label
    return None

# ── Auth ──────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(
    f"{BASE_URL}/api/integration/v1/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
    timeout=30,
)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
print(f"Авторизовано. SessionId: {sid[:12]}...")

# ── Get objects list (with groupId) ───────────────────────────────────────
print("Отримання списку об'єктів...")
resp = requests.get(
    f"{BASE_URL}/api/integration/v1/getobjectslist",
    headers={"SessionId": sid}, timeout=30,
)
objects = resp.json().get("objects", [])
objects.sort(key=lambda o: o.get("name", ""))

# ── Get sensors for every object ──────────────────────────────────────────
print(f"Отримання датчиків для {len(objects)} авто...")
vehicle_sensors = {}   # oid → list of sensor dicts

for obj in objects:
    oid  = obj["id"]
    name = obj["name"]
    print(f"  {name} (id={oid})...", end=" ")
    s = requests.get(
        f"{BASE_URL}/api/integration/v1/objsensorslist",
        headers={"SessionId": sid},
        params={"oid": oid},
        timeout=30,
    )
    sensors = []
    if s.status_code == 200:
        data = s.json()
        if data.get("result") == "Ok":
            sensors = data.get("obj_sensors", [])
    vehicle_sensors[oid] = sensors
    print(f"{len(sensors)} датчиків")

# ── Build HTML ─────────────────────────────────────────────────────────────
print("Формування HTML-звіту...")

# Group objects
groups = {}
for gid in GROUP_ORDER:
    groups[gid] = [o for o in objects if o.get("groupId") == gid]
# Any unknown groups
for o in objects:
    gid = o.get("groupId")
    if gid not in groups:
        groups.setdefault(gid, []).append(o)

def build_group_table(group_objects):
    rows = []
    for obj in group_objects:
        oid      = obj["id"]
        sensors  = vehicle_sensors.get(oid, [])
        n_sensors = len(sensors)
        wb_sensors = [(s, waybill_label(s["name"])) for s in sensors if waybill_label(s["name"])]
        other      = [s for s in sensors if not waybill_label(s["name"])]

        row_start = True
        all_display = wb_sensors + [(s, None) for s in other]

        for idx, item in enumerate(all_display):
            if idx < len(wb_sensors):
                sensor, wb_label = item
            else:
                sensor, wb_label = item

            s_name = sensor["name"].strip()
            sid_val = sensor.get("sid", "")
            pid_val = sensor.get("pid", "")

            if wb_label:
                sensor_td = f'<td class="s-name wb-sensor">✅ {s_name}</td>'
                label_td  = f'<td class="wb-label">{wb_label}</td>'
            else:
                sensor_td = f'<td class="s-name">{s_name}</td>'
                label_td  = f'<td class="no-label">—</td>'

            if row_start:
                rowspan = n_sensors
                vehicle_td = (
                    f'<td class="v-name" rowspan="{rowspan}">'
                    f'<strong>{obj["name"]}</strong><br>'
                    f'<span class="v-id">ID: {oid}</span>'
                    f'</td>'
                    f'<td class="v-count" rowspan="{rowspan}">{n_sensors}<br>'
                    f'<small>({len(wb_sensors)} для ПЛ)</small></td>'
                )
                row_start = False
            else:
                vehicle_td = ""

            tr_class = "wb-row" if wb_label else ""
            rows.append(
                f'<tr class="{tr_class}">'
                f'{vehicle_td}'
                f'<td class="s-sid">{sid_val if sid_val else "—"}</td>'
                f'{sensor_td}'
                f'{label_td}'
                f'</tr>'
            )

        # separator between vehicles
        rows.append('<tr class="sep"><td colspan="5"></td></tr>')

    return "\n".join(rows)


group_sections = ""
for gid in list(GROUP_ORDER) + [g for g in groups if g not in GROUP_ORDER]:
    objs = groups.get(gid, [])
    if not objs:
        continue
    gname = GROUP_NAMES.get(gid, f"Група {gid}")
    total_sensors = sum(len(vehicle_sensors.get(o["id"], [])) for o in objs)
    wb_count = sum(
        sum(1 for s in vehicle_sensors.get(o["id"], []) if waybill_label(s["name"]))
        for o in objs
    )
    group_sections += f"""
    <section>
      <div class="group-header">
        <span class="group-name">{gname}</span>
        <span class="group-stats">
          Авто: {len(objs)} &nbsp;|&nbsp;
          Всього датчиків: {total_sensors} &nbsp;|&nbsp;
          Датчиків для путевого листа: {wb_count}
        </span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Автомобіль</th>
            <th style="width:60px">Датчиків</th>
            <th style="width:60px">SID</th>
            <th>Назва датчика</th>
            <th>Параметр путевого листа</th>
          </tr>
        </thead>
        <tbody>
          {build_group_table(objs)}
        </tbody>
      </table>
    </section>
"""

generated_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

html = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<title>Датчики авто — Mobiteam</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px;
       background: #f0f2f5; color: #222; padding: 24px; }}

h1 {{ font-size: 20px; color: #1565c0; margin-bottom: 6px; }}
.subtitle {{ color: #888; font-size: 12px; margin-bottom: 28px; }}

section {{ margin-bottom: 40px; }}

.group-header {{
  display: flex; align-items: center; gap: 20px;
  background: #1565c0; color: #fff;
  padding: 10px 18px; border-radius: 6px 6px 0 0;
}}
.group-name  {{ font-size: 16px; font-weight: 700; letter-spacing: .5px; }}
.group-stats {{ font-size: 12px; opacity: .85; }}

table {{
  width: 100%; border-collapse: collapse;
  background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.1);
  border-radius: 0 0 6px 6px; overflow: hidden;
}}
thead tr {{ background: #e3f2fd; }}
th {{ padding: 9px 12px; text-align: left; font-size: 12px;
     color: #0d47a1; font-weight: 700; letter-spacing: .4px;
     border-bottom: 2px solid #bbdefb; white-space: nowrap; }}
td {{ padding: 6px 12px; border-bottom: 1px solid #f0f0f0;
     vertical-align: middle; }}

tr.sep td {{ padding: 0; height: 6px; background: #f5f7fa;
             border-bottom: 2px solid #dce3ed; }}
tr:last-child td {{ border-bottom: none; }}

.v-name {{ font-size: 13px; background: #fafbfd;
           border-right: 2px solid #e0e7f0; min-width: 180px;
           vertical-align: top; padding-top: 10px; }}
.v-id   {{ font-size: 11px; color: #999; font-weight: normal; }}
.v-count {{ text-align: center; background: #fafbfd;
             border-right: 1px solid #e0e7f0; color: #555;
             font-weight: 700; font-size: 13px; vertical-align: top;
             padding-top: 10px; }}
.v-count small {{ font-size: 10px; color: #1565c0; font-weight: normal; display:block; }}
.s-sid  {{ color: #bbb; font-size: 11px; text-align: center; width: 60px; }}

/* Waybill sensors */
tr.wb-row {{ background: #f1f8e9; }}
.s-name.wb-sensor {{ color: #2e7d32; font-weight: 600; }}
.wb-label {{ color: #1b5e20; font-size: 12px; }}
.no-label {{ color: #ccc; }}

/* Legend */
.legend {{ display: flex; gap: 20px; margin-bottom: 18px;
           background: #fff; padding: 10px 16px; border-radius: 6px;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; }}
.dot-wb  {{ width: 12px; height: 12px; background: #f1f8e9;
             border: 1px solid #4caf50; border-radius: 2px; }}
.dot-reg {{ width: 12px; height: 12px; background: #fff;
             border: 1px solid #ddd; border-radius: 2px; }}

@media print {{
  body {{ background: #fff; padding: 8px; }}
  section {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>

<h1>Датчики автомобілів — Mobiteam GPS</h1>
<p class="subtitle">Сформовано: {generated_at} &nbsp;|&nbsp; Всього авто: {len(objects)}</p>

<div class="legend">
  <div class="legend-item"><div class="dot-wb"></div> Датчик необхідний для путевого листа</div>
  <div class="legend-item"><div class="dot-reg"></div> Інший датчик</div>
</div>

{group_sections}

</body>
</html>"""

# Write file
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nГотово! Відкрийте файл: {os.path.abspath(OUT_FILE)}")

# Console summary
print()
print("=" * 65)
print("  ЗВЕДЕННЯ ПО ГРУПАХ")
print("=" * 65)
for gid in list(GROUP_ORDER) + [g for g in groups if g not in GROUP_ORDER]:
    objs = groups.get(gid, [])
    if not objs:
        continue
    print(f"\n  {GROUP_NAMES.get(gid, f'Група {gid}')}  ({len(objs)} авто)")
    print(f"  {'Авто':<22} {'Всього':>7}  {'Для ПЛ':>7}  Датчики ПЛ")
    print("  " + "-" * 60)
    for obj in objs:
        oid = obj["id"]
        sensors = vehicle_sensors.get(oid, [])
        wb = [(s["name"].strip(), waybill_label(s["name"])) for s in sensors if waybill_label(s["name"])]
        wb_names = ", ".join(n.strip("✅ ").strip() for n, _ in wb[:3])
        if len(wb) > 3:
            wb_names += f" +{len(wb)-3}"
        print(f"  {obj['name']:<22} {len(sensors):>7}  {len(wb):>7}  {wb_names}")
print()
print("=" * 65)

# Open in browser
import webbrowser
webbrowser.open(f"file:///{os.path.abspath(OUT_FILE).replace(os.sep, '/')}")
