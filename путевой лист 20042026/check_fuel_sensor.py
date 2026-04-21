#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка: у яких авто є датчик "Топливо" (загальний бак)"""

import requests, sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"

r = requests.get(f"{BASE_URL}/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
    timeout=30)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
HEADERS = {"SessionId": sid}

resp    = requests.get(f"{BASE_URL}/getobjectslist", headers=HEADERS, timeout=30)
objects = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
print(f"Авто: {len(objects)}\n")

has_fuel    = []
no_fuel     = []
has_tanks   = []  # є Бак1/Бак2 але немає загального "Топливо"

for obj in objects:
    oid  = obj["id"]
    name = obj["name"]
    print(f"  {name} ...", end=" ", flush=True)

    resp2 = requests.get(f"{BASE_URL}/fullobjinfo",
                         headers=HEADERS, params={"oid": oid}, timeout=30)
    data  = resp2.json()

    if data.get("result") != "Ok":
        no_fuel.append((name, "API error"))
        print("error")
        continue

    sensors    = data.get("sensors", [])
    names_low  = [s.get("name","").strip().lower() for s in sensors]

    fuel_sensor = next((s for s in sensors if "топливо" in s.get("name","").lower()
                        and "бак" not in s.get("name","").lower()
                        and "температур" not in s.get("name","").lower()
                        and "расход" not in s.get("name","").lower()
                        and "can уровень" not in s.get("name","").lower()), None)

    tank_sensors = [s for s in sensors if s.get("name","").strip().lower().startswith("бак")]

    if fuel_sensor:
        has_fuel.append((name, fuel_sensor.get("name","").strip(), fuel_sensor.get("val","—")))
        print(f"OK  →  {fuel_sensor.get('name','').strip()} = {fuel_sensor.get('val','')}")
    elif tank_sensors:
        tanks_str = ", ".join(f"{t.get('name','').strip()}={t.get('val','')}" for t in tank_sensors)
        has_tanks.append((name, tanks_str))
        print(f"Баки (без загального): {tanks_str}")
    else:
        no_fuel.append((name, "немає паливного датчика"))
        print("— немає")

# ── Summary ───────────────────────────────────────────────────────────────────
W = 70
print(f"\n{'='*W}")
print(f"  Є датчик 'Топливо' (загальний): {len(has_fuel)}")
print(f"{'='*W}")
for name, sname, val in has_fuel:
    print(f"  {name:<28}  {sname:<26}  {val}")

if has_tanks:
    print(f"\n{'='*W}")
    print(f"  Є тільки Бак1/Бак2 (без загального): {len(has_tanks)}")
    print(f"{'='*W}")
    for name, tanks in has_tanks:
        print(f"  {name:<28}  {tanks}")

if no_fuel:
    print(f"\n{'='*W}")
    print(f"  Немає паливних датчиків: {len(no_fuel)}")
    print(f"{'='*W}")
    for name, reason in no_fuel:
        print(f"  {name:<28}  {reason}")

print(f"\n{'='*W}")
print(f"  Всього авто: {len(objects)}  |  з Топливо: {len(has_fuel)}  |  тільки Баки: {len(has_tanks)}  |  без датчика: {len(no_fuel)}")
print(f"{'='*W}")
