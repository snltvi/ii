#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сводный отчёт: номер авто, ФИО, одометр начало/конец, бак начало, заправки, бак конец.
Период: 01.04.2026 — 14.04.2026
"""

import requests, sys, json, os, math
import pandas as pd
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ──────────────────────────────────────────────────────────────────
LOGIN      = "abvprom"
PASSWORD   = "29328"
BASE_URL   = "https://gps.mobiteam.com.ua/api/integration/v1"
CACHE_FILE = "sensors_cache.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL      = os.path.join(SCRIPT_DIR, "putevoi list", "CAN_пробег_датчики_06_02_2026.xlsx")

DATE_START = {"label": "01.04.2026", "date": "2026-04-01", "take": "first"}
DATE_END   = {"label": "14.04.2026", "date": "2026-04-14", "take": "last"}
DT_FROM    = f"{DATE_START['date']} 00:00:00"
DT_TO      = f"{DATE_END['date']}   23:59:59"

ODO_KEYWORDS  = ["датчик накопленного пробега", "can абсолютный пробег", "абсолютный пробег"]
FUEL_KEYWORDS = ["уровень топлива", "датчик топлива", "датчик уровня топлива",
                 "can уровень топлива", "топливо", "рівень палива", "датчик палива",
                 "паливо", "бак", "fuel"]

# ── Auth ────────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(f"{BASE_URL}/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
    timeout=30)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
print(f"Авторизовано. SessionId: {sid[:12]}...")
HEADERS = {"SessionId": sid}

# ── Load vehicles from API ──────────────────────────────────────────────────
print("Отримання списку авто...")
resp    = requests.get(f"{BASE_URL}/getobjectslist", headers=HEADERS, timeout=30)
objects = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
oid_map = {str(o["id"]): o for o in objects}
print(f"  Знайдено: {len(objects)} авто")

# ── Load driver info from Excel ─────────────────────────────────────────────
drivers = {}   # oid_str → "ФИО"
if os.path.exists(EXCEL):
    try:
        df = pd.read_excel(EXCEL)
        for _, row in df.iterrows():
            oid_v = row.get("ID объекта")
            fio   = str(row.get("ФИО", "") or "").strip()
            if oid_v and fio:
                drivers[str(int(oid_v))] = fio
        print(f"  Водіїв з Excel: {len(drivers)}")
    except Exception as e:
        print(f"  Excel не завантажено: {e}")
else:
    print(f"  Excel не знайдено: {EXCEL}")

# ── Sensor cache ─────────────────────────────────────────────────────────────
cache     = {}
cache_hit = False
current_ids = {str(o["id"]) for o in objects}

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
    cached_ids = set(cache.get("vehicles", {}).keys())
    if not (current_ids - cached_ids):
        print(f"Кеш датчиків актуальний ({CACHE_FILE}).")
        cache_hit = True

if not cache_hit:
    print("Запит датчиків (objsensorslist)...")
    vehicles_cache = cache.get("vehicles", {})
    for obj in objects:
        oid_s = str(obj["id"])
        print(f"  {obj['name']} ...", end=" ", flush=True)
        s = requests.get(f"{BASE_URL}/objsensorslist",
                         headers=HEADERS, params={"oid": obj["id"]}, timeout=30)
        sensors = []
        if s.status_code == 200 and s.json().get("result") == "Ok":
            sensors = s.json().get("obj_sensors", [])
        vehicles_cache[oid_s] = {"name": obj["name"], "groupId": obj.get("groupId"), "sensors": sensors}
        print(f"{len(sensors)} датчиків")
    cache = {"updated": datetime.now().isoformat(timespec="seconds"), "vehicles": vehicles_cache}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

vehicles_cache = cache["vehicles"]

# ── Build sensor lists ────────────────────────────────────────────────────────
def find_sensor(sensors, keywords):
    for s in sensors:
        name = s.get("name", "").lower().strip()
        if any(kw in name for kw in keywords):
            sid_v = s.get("sid", 0)
            pid_v = s.get("pid", 0)
            if sid_v > 0:   return f"s{sid_v}"
            if pid_v > 0:   return f"p{pid_v}"
    return None

odo_slist  = {}   # oid_str → slist
fuel_slist = {}   # oid_str → slist

for oid_s, vdata in vehicles_cache.items():
    sens = vdata.get("sensors", [])
    odo_slist[oid_s]  = find_sensor(sens, ODO_KEYWORDS)
    fuel_slist[oid_s] = find_sensor(sens, FUEL_KEYWORDS)

# ── Query objdata (one sensor, one day) ───────────────────────────────────────
def query_val(oid: int, slist: str, date_str: str, take: str):
    params = {
        "oid": oid, "slist": slist, "compress": "true",
        "from": f"{date_str} 00:00:00",
        "to":   f"{date_str} 23:59:59",
    }
    try:
        r = requests.get(f"{BASE_URL}/objdata", headers=HEADERS, params=params, timeout=30)
        if r.status_code != 200: return None
        data = r.json()
        if data.get("result") != "Ok": return None
        records = data.get("obj_data", {}).get("records", [])
        vals = []
        for rec in records:
            if len(rec) > 1 and rec[1] is not None:
                try: vals.append(float(str(rec[1]).strip()))
                except: pass
        if not vals: return None
        return vals[0] if take == "first" else vals[-1]
    except:
        return None

# ── Query fuelings for the period ────────────────────────────────────────────
def query_fuelings(oid: int):
    try:
        r = requests.get(f"{BASE_URL}/fuelings",
                         headers=HEADERS,
                         params={"oid": oid, "from": DT_FROM, "to": DT_TO},
                         timeout=30)
        if r.status_code != 200 or r.json().get("result") != "Ok":
            return None
        total = sum(
            float(ev.get("volume", 0))
            for ev in r.json().get("fuelings", [])
            if ev.get("fuel_type") == "fueling"
        )
        return round(total, 1)
    except:
        return None

# ── Collect data ──────────────────────────────────────────────────────────────
print(f"\nЗбір даних за {DATE_START['label']} — {DATE_END['label']}...\n")

rows = []
for obj in objects:
    oid_s = str(obj["id"])
    oid_i = obj["id"]
    name  = obj["name"]

    print(f"  {name} ...", end=" ", flush=True)

    fio        = drivers.get(oid_s, "—")
    odo_s_list = odo_slist.get(oid_s)
    fu_s_list  = fuel_slist.get(oid_s)

    odo_start  = query_val(oid_i, odo_s_list,  DATE_START["date"], "first") if odo_s_list  else None
    odo_end    = query_val(oid_i, odo_s_list,  DATE_END["date"],   "last")  if odo_s_list  else None
    fuel_start = query_val(oid_i, fu_s_list,   DATE_START["date"], "first") if fu_s_list   else None
    fuel_end   = query_val(oid_i, fu_s_list,   DATE_END["date"],   "last")  if fu_s_list   else None
    fuelings   = query_fuelings(oid_i)

    rows.append({
        "name":        name,
        "fio":         fio,
        "odo_start":   odo_start,
        "odo_end":     odo_end,
        "fuel_start":  fuel_start,
        "fuelings":    fuelings,
        "fuel_end":    fuel_end,
    })
    print("OK")

# ── Print table ───────────────────────────────────────────────────────────────
def fv(v, decimals=1):
    if v is None: return "—"
    try:
        fmt = f"{{:,.{decimals}f}}".format(float(v))
        return fmt.replace(",", " ")
    except:
        return str(v)

C_NUM  = 14
C_FIO  = 26
C_ODO  = 14
C_FUEL = 12

HEADER = (
    f"{'Номер авто':<{C_NUM}}  "
    f"{'ФИО водителя':<{C_FIO}}  "
    f"{'Одометр нач':>{C_ODO}}  "
    f"{'Одометр кон':>{C_ODO}}  "
    f"{'Бак нач':>{C_FUEL}}  "
    f"{'Заправки':>{C_FUEL}}  "
    f"{'Бак кон':>{C_FUEL}}"
)
SEP = "-" * len(HEADER)

W = len(HEADER)
print()
print("=" * W)
print(f"  ЗВЕДЕНА ТАБЛИЦЯ  {DATE_START['label']} — {DATE_END['label']}")
print("=" * W)
print(HEADER)
print(SEP)

for r in rows:
    line = (
        f"{r['name']:<{C_NUM}}  "
        f"{r['fio']:<{C_FIO}}  "
        f"{fv(r['odo_start'], 0):>{C_ODO}}  "
        f"{fv(r['odo_end'],   0):>{C_ODO}}  "
        f"{fv(r['fuel_start']):>{C_FUEL}}  "
        f"{fv(r['fuelings']):>{C_FUEL}}  "
        f"{fv(r['fuel_end']):>{C_FUEL}}"
    )
    print(line)

print("=" * W)
print(f"  Одометр — км  |  Бак / Заправки — л  |  Кеш: {CACHE_FILE}")
print("=" * W)
