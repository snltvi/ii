#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Показання датчиків пробігу для кожного авто на початок (01.04.2026) та кінець (14.04.2026) рейсу.

Кроки:
  1. objsensorslist  — список датчиків для кожного авто → зберігаємо у sensors_cache.json
                       (якщо файл є і нових авто немає — повторний запит не робимо)
  2. objdata         — значення датчика за добу
       sid > 0  → slist=s{sid}
       sid == 0 → slist=p{pid}
       01.04.2026 → ПЕРШЕ значення за день (початок рейсу)
       14.04.2026 → ОСТАННЄ значення за день (кінець рейсу)

Метод: GET /api/integration/v1/objdata
Результат: консоль
"""

import requests, sys, json, os
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ─────────────────────────────────────────────────────────────────
LOGIN      = "abvprom"
PASSWORD   = "29328"
BASE_URL   = "https://gps.mobiteam.com.ua/api/integration/v1"
CACHE_FILE = "sensors_cache.json"

GROUP_NAMES = {2998: "Автопарк 1", 3129: "Автопарк 2"}
GROUP_ORDER = [2998, 3129]

# Ключові слова для вибору датчиків пробігу
ODO_KEYWORDS = [
    "датчик накопленного пробега",
    "can абсолютный пробег",
    "абсолютный пробег",
]

# Дати: 01.04 — початок рейсу (перше значення), 14.04 — кінець рейсу (останнє значення)
DATE_START = {"label": "01.04.2026", "date": "2026-04-01", "take": "first"}
DATE_END   = {"label": "14.04.2026", "date": "2026-04-14", "take": "last"}

def sensor_is_odo(name: str) -> bool:
    lo = name.lower().strip()
    return any(kw in lo for kw in ODO_KEYWORDS)

# ── Auth ───────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(f"{BASE_URL}/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
    timeout=30)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
print(f"Авторизовано. SessionId: {sid[:12]}...")

HEADERS = {"SessionId": sid}

# ── Get vehicle list ────────────────────────────────────────────────────────
print("Отримання списку авто...")
resp = requests.get(f"{BASE_URL}/getobjectslist", headers=HEADERS, timeout=30)
objects = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
current_ids = {str(o["id"]) for o in objects}
print(f"  Знайдено: {len(objects)} авто")

# ── Load or build sensor cache ─────────────────────────────────────────────
cache = {}
cache_hit = False

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
    cached_ids = set(cache.get("vehicles", {}).keys())
    new_vehicles = current_ids - cached_ids
    if not new_vehicles:
        print(f"Кеш датчиків актуальний ({CACHE_FILE}), завантажую з файлу.")
        cache_hit = True
    else:
        print(f"Нові авто: {new_vehicles} — оновлюю кеш...")

if not cache_hit:
    print("Запит датчиків з API (objsensorslist)...")
    vehicles_cache = cache.get("vehicles", {})

    for obj in objects:
        oid  = str(obj["id"])
        name = obj["name"]
        if oid in vehicles_cache and oid not in (current_ids - set(vehicles_cache.keys())):
            pass  # already cached, skip API call
        print(f"  {name} (id={oid})...", end=" ", flush=True)
        s = requests.get(f"{BASE_URL}/objsensorslist",
                         headers=HEADERS, params={"oid": obj["id"]}, timeout=30)
        sensors = []
        if s.status_code == 200 and s.json().get("result") == "Ok":
            sensors = s.json().get("obj_sensors", [])
        vehicles_cache[oid] = {
            "name":    name,
            "groupId": obj.get("groupId"),
            "sensors": sensors,
        }
        print(f"{len(sensors)} датчиків")

    cache = {
        "updated":  datetime.now().isoformat(timespec="seconds"),
        "vehicles": vehicles_cache,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"Кеш збережено → {CACHE_FILE}")

vehicles_cache = cache["vehicles"]

# ── Filter odo sensors for each vehicle ───────────────────────────────────
# odo_sensors[oid] = [ {sid, pid, name, slist_param}, ... ]
odo_sensors = {}
for oid_str, vdata in vehicles_cache.items():
    found = []
    for s in vdata.get("sensors", []):
        if sensor_is_odo(s.get("name", "")):
            sid_val = s.get("sid", 0)
            pid_val = s.get("pid", 0)
            if sid_val > 0:
                slist = f"s{sid_val}"
                id_type = f"sid={sid_val}"
            elif pid_val > 0:
                slist = f"p{pid_val}"
                id_type = f"pid={pid_val}"
            else:
                continue
            found.append({
                "name":    s["name"].strip(),
                "sid":     sid_val,
                "pid":     pid_val,
                "slist":   slist,
                "id_type": id_type,
            })
    odo_sensors[oid_str] = found

# ── Query objdata ──────────────────────────────────────────────────────────
def query_objdata(oid: int, slist: str, date_str: str, take: str):
    """
    GET /api/integration/v1/objdata
      oid   = object id
      slist = s{sid} or p{pid}
      from  = "YYYY-MM-DD 00:00:00"  (local time)
      to    = "YYYY-MM-DD 23:59:59"  (local time)
    Returns (value, n_records, raw_response_status)
    """
    params = {
        "oid":   oid,
        "slist": slist,
        "from":  f"{date_str} 00:00:00",
        "to":    f"{date_str} 23:59:59",
        "compress": "true",
    }
    try:
        resp = requests.get(f"{BASE_URL}/objdata", headers=HEADERS, params=params, timeout=30)
        status = resp.status_code
        if status != 200:
            return None, 0, f"HTTP {status}"
        data = resp.json()
        if data.get("result") != "Ok":
            return None, 0, f"result={data.get('result')}"
        records = data.get("obj_data", {}).get("records", [])
        if not records:
            return None, 0, "0 записів"
        # extract numeric values
        values = []
        for rec in records:
            if len(rec) > 1 and rec[1] is not None:
                try:
                    values.append(float(str(rec[1]).strip()))
                except:
                    pass
        if not values:
            return None, len(records), "немає числових значень"
        val = values[0] if take == "first" else values[-1]
        return val, len(records), "OK"
    except Exception as e:
        return None, 0, str(e)[:40]

# ── Fetch readings ─────────────────────────────────────────────────────────
print(f"\nЗапит objdata для {DATE_START['label']} (перше значення) "
      f"та {DATE_END['label']} (останнє значення)...")
print()

# readings[oid_str][sensor_name] = {start_val, end_val, start_status, end_status}
readings = {}

for obj in objects:
    oid_str = str(obj["id"])
    sensors = odo_sensors.get(oid_str, [])
    readings[oid_str] = {}

    for s in sensors:
        v_start, n_start, st_start = query_objdata(
            obj["id"], s["slist"], DATE_START["date"], DATE_START["take"])
        v_end,   n_end,   st_end   = query_objdata(
            obj["id"], s["slist"], DATE_END["date"],   DATE_END["take"])
        readings[oid_str][s["name"]] = {
            "start_val":    v_start,
            "end_val":      v_end,
            "start_status": st_start,
            "end_status":   st_end,
            "n_start":      n_start,
            "n_end":        n_end,
            "id_type":      s["id_type"],
        }

# ── Console output ─────────────────────────────────────────────────────────
def fkm(v):
    if v is None: return "—"
    try: return f"{float(v):>14,.3f}".replace(",", " ")
    except: return str(v)

W = 110
print("=" * W)
print("  ПОКАЗАННЯ ДАТЧИКІВ ПРОБІГУ")
print(f"  Метод: GET /api/integration/v1/objdata")
print(f"  {'Початок рейсу':^30} {DATE_START['label']} (перше значення дня)")
print(f"  {'Кінець рейсу':^30} {DATE_END['label']} (останнє значення дня)")
print("=" * W)

for gid in GROUP_ORDER + [g for g in {o.get("groupId") for o in objects} if g not in GROUP_ORDER]:
    group_objs = [o for o in objects if o.get("groupId") == gid]
    if not group_objs:
        continue
    print(f"\n  ── {GROUP_NAMES.get(gid, f'Група {gid}')} ({len(group_objs)} авто) ──\n")
    print(f"  {'Авто':<20} {'ID':<6} {'Датчик':<36} "
          f"{'ID-тип':<12} "
          f"{'01.04 (перше)':>16}  {'14.04 (останнє)':>16}  Статус")
    print("  " + "-" * (W - 2))

    for obj in group_objs:
        oid_str  = str(obj["id"])
        sensors  = odo_sensors.get(oid_str, [])
        row_data = readings.get(oid_str, {})

        if not sensors:
            print(f"  {obj['name']:<20} {obj['id']:<6} "
                  f"{'⚠ датчик пробігу не знайдено в кеші':<36}")
            continue

        first = True
        for s in sensors:
            rd = row_data.get(s["name"], {})
            v_s  = rd.get("start_val")
            v_e  = rd.get("end_val")
            st_s = rd.get("start_status", "?")
            st_e = rd.get("end_status",   "?")

            status_str = ""
            if st_s != "OK": status_str += f"поч:{st_s} "
            if st_e != "OK": status_str += f"кін:{st_e}"
            if not status_str and v_s is not None and v_e is not None:
                status_str = f"✓ objdata  записів: {rd['n_start']}/{rd['n_end']}"

            name_col = obj["name"] if first else ""
            id_col   = str(obj["id"]) if first else ""
            first    = False

            print(f"  {name_col:<20} {id_col:<6} {s['name']:<36} "
                  f"{s['id_type']:<12} "
                  f"{fkm(v_s):>16}  {fkm(v_e):>16}  {status_str}")

        if len(sensors) > 1:
            # show difference for same-type sensors if both have values
            for s in sensors:
                rd = row_data.get(s["name"], {})
                v_s, v_e = rd.get("start_val"), rd.get("end_val")
                if v_s is not None and v_e is not None:
                    diff = v_e - v_s
                    print(f"  {'':20} {'':6} {'  → пробег за рейс:':36} "
                          f"{'':12} {'':>16}  {fkm(diff):>16} км")
        print()

print("=" * W)
print(f"  Кеш датчиків: {CACHE_FILE}  |  Оновлено: {cache.get('updated', '?')}")
print("=" * W)
