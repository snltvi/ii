#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Усі датчики для кожного авто — актуальні дані (fullobjinfo)
Таблиця: sid | назва | значення | дата датчика
"""

import requests, sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"

# ── Auth ─────────────────────────────────────────────────────────────────────
print("Підключення до API...")
r = requests.get(f"{BASE_URL}/connect",
    params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
    timeout=30)
sid = r.headers.get("sessionid") or r.headers.get("SessionId")
if not sid:
    print("Помилка авторизації"); exit(1)
print(f"Авторизовано. SessionId: {sid[:12]}...\n")
HEADERS = {"SessionId": sid}

# ── Vehicles ─────────────────────────────────────────────────────────────────
resp    = requests.get(f"{BASE_URL}/getobjectslist", headers=HEADERS, timeout=30)
objects = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
print(f"Знайдено авто: {len(objects)}\n")

# ── Layout ────────────────────────────────────────────────────────────────────
C_SID  = 9
C_NAME = 40
C_VAL  = 22
C_DT   = 19
TOTAL  = C_SID + C_NAME + C_VAL + C_DT + 8

def table_sep(char="-"):
    print(char * TOTAL)

def table_header():
    print(
        f"{'sid':<{C_SID}}  "
        f"{'Назва датчика':<{C_NAME}}  "
        f"{'Значення':>{C_VAL}}  "
        f"{'Дата датчика':<{C_DT}}"
    )
    table_sep()

# ── Per vehicle ───────────────────────────────────────────────────────────────
for obj in objects:
    oid  = obj["id"]
    name = obj["name"]

    table_sep("=")
    print(f"  {name}  (oid={oid})")
    table_sep("=")

    try:
        resp2 = requests.get(
            f"{BASE_URL}/fullobjinfo",
            headers=HEADERS,
            params={"oid": oid},
            timeout=30,
        )
        data = resp2.json()
    except Exception as e:
        print(f"  Помилка запиту: {e}\n")
        continue

    if data.get("result") != "Ok":
        print(f"  result={data.get('result')}  {data.get('error_text','')}\n")
        continue

    sensors = data.get("sensors", [])

    if not sensors:
        print("  Датчики відсутні\n")
        continue

    table_header()
    for s in sensors:
        s_sid  = s.get("sid", "—")
        s_name = (s.get("name") or "—").strip()
        s_val  = (s.get("val")  or "—").strip()   # поле "val", вже з одиницями
        s_dt   = (s.get("dt")   or "—")

        # пропускаємо "нульову" дату датчика
        if s_dt.startswith("0001"):
            s_dt = "—"

        print(
            f"{str(s_sid):<{C_SID}}  "
            f"{s_name:<{C_NAME}}  "
            f"{s_val:>{C_VAL}}  "
            f"{s_dt:<{C_DT}}"
        )

    table_sep()
    print(f"  Всього датчиків: {len(sensors)}\n")

print("Готово.")
