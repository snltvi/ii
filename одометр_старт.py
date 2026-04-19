#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Зведена таблиця по всіх авто на 01.04.2026:
  - одометр CAN на початок і кінець дня
  - рівень бака на початок і кінець дня
  - об'єм заправки за день
"""

import requests, sys
from datetime import datetime, timedelta

# Windows terminal UTF-8 fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
TZ_HOURS = 3  # UTC+3

VEHICLES = [
    {"id": 8666, "plate": "ВН5291РХ", "driver": "Стародуб Сергій Олександрович"},
    {"id": 7281, "plate": "ВН5651РВ", "driver": "Наривончик Олександр Васильович"},
    {"id": 7692, "plate": "ВН4721РН", "driver": "Димоглов Іван Петрович"},
    {"id": 8201, "plate": "ВН7532РС", "driver": "Турків Степан Дмитрович"},
    {"id": 8783, "plate": "ВН5290РХ", "driver": "Демченко Олексій Борисович"},
    {"id": 7312, "plate": "BH4492PT",  "driver": "Кузнецов Сергій Володимирович"},
    {"id": 7250, "plate": "ВН6394РВ", "driver": "Фесечко Олександр Миколайович"},
    {"id": 8124, "plate": "ВН8941РС", "driver": "Ковальчук Олег Петрович"},
    {"id": 8743, "plate": "ВН1575РК", "driver": "Варенчук Сергій Анатолійович"},
    {"id": 8200, "plate": "ВН5685РВ", "driver": "Піх Юрій Олексійович"},
    {"id": 7691, "plate": "ВН4723РН", "driver": "Єждін Олександр"},
    {"id": 7251, "plate": "ВН6395РВ", "driver": "Кирилов Ростислав Михайлович"},
    {"id": 7242, "plate": "ВН3194РС", "driver": ""},
    {"id": 7243, "plate": "ВН3198РС", "driver": ""},
    {"id": 7248, "plate": "ВН6396РВ", "driver": ""},
    {"id": 8123, "plate": "ВН6484РС", "driver": ""},
    {"id": 8161, "plate": "ВН9546РС", "driver": ""},
]

# 01.04.2026  00:00 – 23:59 local → UTC
FMT           = "%Y-%m-%d %H:%M:%S"
DATE_FROM_UTC = datetime(2026, 4, 1,  0,  0, 0) - timedelta(hours=TZ_HOURS)
DATE_TO_UTC   = datetime(2026, 4, 1, 23, 59, 0) - timedelta(hours=TZ_HOURS)

# ── Auth ──────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(
    f"{BASE_URL}/api/integration/v1/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": str(TZ_HOURS)},
    timeout=30,
)
if r.status_code != 200:
    print(f"Помилка авторизації: HTTP {r.status_code}")
    exit(1)

sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Не отримано SessionId")
    exit(1)

print(f"Авторизовано. SessionId: {sid[:12]}...")

# ── Request ───────────────────────────────────────────────────────────────
all_ids    = ";".join(str(v["id"]) for v in VEHICLES)
param_list = "start_can_dist;stop_can_dist;start_fuel_level;stop_fuel_level;fuelings"

resp = requests.get(
    f"{BASE_URL}/api/integration/v1/getobjectsreport",
    headers={"SessionId": sid},
    params={
        "date_from": DATE_FROM_UTC.strftime(FMT),
        "date_to":   DATE_TO_UTC.strftime(FMT),
        "objuids":   all_ids,
        "split":     "none",
        "param":     param_list,
    },
    timeout=60,
)

if resp.status_code != 200:
    print(f"Помилка запиту: HTTP {resp.status_code}")
    exit(1)

# ── Parse ─────────────────────────────────────────────────────────────────
FIELDS = ["start_can_dist", "stop_can_dist", "start_fuel_level", "stop_fuel_level", "fuelings"]

results = {}
for obj in resp.json():
    oid    = obj.get("oid")
    period = (obj.get("periods") or [{}])[0]
    prms   = {p["name"]: p["value"] for p in (period.get("prms") or [])}
    results[oid] = {f: prms.get(f) for f in FIELDS}

# ── Helpers ───────────────────────────────────────────────────────────────
def fmt_km(val):
    if val is None:
        return f"{'—':>13}"
    try:
        return f"{float(val):>13,.3f}".replace(",", " ")
    except (ValueError, TypeError):
        return f"{str(val):>13}"

def fmt_l(val):
    if val is None:
        return f"{'—':>8}"
    try:
        return f"{float(val):>8.1f}"
    except (ValueError, TypeError):
        return f"{str(val):>8}"

# ── Print ─────────────────────────────────────────────────────────────────
W = 107
print()
print("=" * W)
print(f"  ЗВЕДЕНА ТАБЛИЦЯ на 01.04.2026 — всі автомобілі")
print("=" * W)
print(
    f"  {'№':<3} {'Номер':<11} "
    f"{'Одом.початок':>13}  {'Одом.кінець':>13}  "
    f"{'Бак поч.л':>9}  {'Бак кін.л':>9}  {'Заправка л':>10}  "
    f"Водій"
)
print("-" * W)

has_data = 0
for i, v in enumerate(VEHICLES, 1):
    r = results.get(v["id"], {})
    sc  = r.get("start_can_dist")
    ec  = r.get("stop_can_dist")
    sf  = r.get("start_fuel_level")
    ef  = r.get("stop_fuel_level")
    fl  = r.get("fuelings")

    if any(x is not None for x in [sc, ec, sf, ef, fl]):
        has_data += 1

    driver = v["driver"] or "—"
    print(
        f"  {i:<3} {v['plate']:<11} "
        f"{fmt_km(sc)}  {fmt_km(ec)}  "
        f"{fmt_l(sf)}  {fmt_l(ef)}  {fmt_l(fl):>10}  "
        f"{driver}"
    )

print("=" * W)
print(f"  Всього авто: {len(VEHICLES)}  |  З даними: {has_data}")
print("=" * W)
