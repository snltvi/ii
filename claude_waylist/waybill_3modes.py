#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПУТЕВОЙ ЛИСТ — 3 СЦЕНАРИЯ — веб-интерфейс (порт 8181)
=========================================================================
Запуск:
    python waybill_3modes.py
Откроется браузер: http://localhost:8181

Расширение waybill.py: на шаге 1 пользователь выбирает один из трёх
сценариев формирования рейса:

  СЦЕНАРИЙ 3 (как в waybill.py): выезд из гаража + въезд в гараж.
    Оба события выбираются вручную из dropdown'ов /zonesvisits.

  СЦЕНАРИЙ 1: дата выезда из гаража + одометр конца рейса.
    Старт = выбранный exit; финиш = поиск по /objdata вперёд от старта,
    пока |odo_record - odo_end| < ODO_TOLERANCE_KM (max ODO_SEARCH_DAYS дней).

  СЦЕНАРИЙ 2: одометр начала рейса + дата въезда в гараж.
    Финиш = выбранный entry; старт = поиск по /objdata назад от финиша,
    пока |odo_record - odo_start| < ODO_TOLERANCE_KM.
  4) По выбранному [start..end] вызывается /getobjectsreport со всеми
     полями (start_address, stop_address, can_dist, fuelings, all_fuel,
     start_fuel_level, stop_fuel_level, avg_dist_run_fuel, avg_all_fuel,
     drains, start_can_dist, stop_can_dist, odo_dist, stop_time,
     start_move_time, stop_move_time, start_coords, stop_coords).
     Дополнительно:
       /fuelings  — список заправок (дата, время, объём, координаты)
       /getaddress — реверс-геокодинг каждой заправки
       /stops?time=3600 — стоянки > 1 часа + реверс-геокодинг
       /objsensorslist + /objdata — уровень "Топливо"/"Бак" на старт/финиш
                                    (бак — резервный, если "Топливо" нет)

Используемые методы API (https://gps.mobiteam.com.ua/api/integration/v1):
  GET /connect             — авторизация → SessionId
  GET /getobjectslist      — список ТС
  GET /getgeotree          — дерево геозон (ищем "Гараж")
  GET /zonesvisits         — события входа/выхода из зоны за период
  GET /getobjectsreport    — сводный отчёт (адреса, пробег, топливо, ...)
  GET /fuelings            — список заправок (start_time, volume, lat, lon)
  GET /stops               — список стоянок (фильтр: time=сек)
  GET /getaddress          — обратное геокодирование (lat, lon → адрес)
  GET /objsensorslist      — список датчиков ТС (кешируется)
  GET /objdata             — значения датчика за период (топливо)

Справочник:
  date/Сцепка_водитель-авто-прицеп.xlsx
    Колонки: №, ФИО, ID объекта, (модель), Тип авто, Номер авто,
             Номер прицепа, ...
  Колонка "Тип авто" — добавлена в этот файл, заполняется вручную
  (тягач, самосвал, фургон, и т.д.).

Кеш датчиков:
  date/sensors_cache.json — обновляется при появлении новых ТС.
=========================================================================
"""

import json
import os
import re
import sqlite3
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlparse

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ───────────────────────────────────────────────────────────────────
LOGIN      = "abvprom"
PASSWORD   = "29328"
BASE_URL   = "https://gps.mobiteam.com.ua/api/integration/v1"
PORT       = 8181
UTC_OFFSET = 3  # отображение времени (зміщено на 1 год назад від UTC+2)
MIN_GARAGE_STAY_HOURS = 24  # стоянки в гаражі менше — сірі/disabled у dropdown
MERGE_GAP_MINUTES     = 5   # сусідні візити з розривом < N хв об'єднуємо
                            # (фільтр GPS-«дрижання» на межі геозони)
ODO_TOLERANCE_KM = 2.0      # допуск пошуку дати по показанню одометра
ODO_SEARCH_DAYS  = 30       # макс. вікно пошуку (днів вперед/назад)

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(SCRIPT_DIR, "date")
CACHE_FILE    = os.path.join(DATA_DIR, "sensors_cache.json")
DB_FILE       = os.path.join(SCRIPT_DIR, "abv_doroga.db")
os.makedirs(DATA_DIR, exist_ok=True)

# Шукаємо xlsx-справочник у кількох можливих місцях
def _find_drivers_excel():
    candidates = [
        os.path.join(SCRIPT_DIR, "date", "Сцепка_водитель-авто-прицеп.xlsx"),
        os.path.join(SCRIPT_DIR, "data", "Сцепка_водитель-авто-прицеп.xlsx"),
        os.path.join(SCRIPT_DIR, "data",
                     "Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Останній шанс — будь-який *цепка*.xlsx у data/
    data_dir = os.path.join(SCRIPT_DIR, "data")
    if os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            if fn.lower().endswith(".xlsx") and "цепка" in fn.lower():
                return os.path.join(data_dir, fn)
    return candidates[0]  # для friendly error message

DRIVERS_EXCEL = _find_drivers_excel()

FUEL_COMBINED = ["топливо"]
FUEL_TANK     = ["бак"]
FUEL_EXCLUDE  = ["расход", "температур", "°t", "уровень", "%", "can уровень"]


# ── Database (abv_doroga) ────────────────────────────────────────────────────
DB_FIELDS = [
    "waybill_no", "waybill_date", "trip_start_iso", "trip_end_iso",
    "oid", "vname", "driver", "veh_type", "plate", "trailer", "scenario",
    "order_num", "cargo_name", "cargo_weight",
    "addr_start", "addr_end", "coords_start", "coords_end",
    "odo_s_val", "odo_e_val",
    "sf_lvl", "ef_lvl",
    "dist", "can_dist", "odo_dist",
    "can_dist_calc", "odo_dist_calc",
    "fuelings_v", "drains_v", "all_fuel",
    "avg100_run", "avg100_all",
    "start_mv", "stop_mv",
    "stop_secs", "stop_min",
    "total_fs", "total_fe",
    "fuel_start_rows_json", "fuel_end_rows_json",
    "fuels_json", "stops_json",
    "search_msg",
    "corr_odo_start", "corr_odo_end",
    "corr_fuel_start", "corr_fuel_end",
    "corr_fueling_total",
    "created_at", "updated_at",
]


def db_init():
    with sqlite3.connect(DB_FILE) as c:
        c.execute(f"""CREATE TABLE IF NOT EXISTS waybills (
            waybill_no TEXT PRIMARY KEY,
            waybill_date TEXT,
            trip_start_iso TEXT,
            trip_end_iso TEXT,
            oid INTEGER,
            vname TEXT,
            driver TEXT,
            veh_type TEXT,
            plate TEXT,
            trailer TEXT,
            scenario TEXT,
            order_num TEXT,
            cargo_name TEXT,
            cargo_weight TEXT,
            addr_start TEXT,
            addr_end TEXT,
            coords_start TEXT,
            coords_end TEXT,
            odo_s_val REAL,
            odo_e_val REAL,
            sf_lvl REAL,
            ef_lvl REAL,
            dist REAL,
            can_dist REAL,
            odo_dist REAL,
            can_dist_calc INTEGER,
            odo_dist_calc INTEGER,
            fuelings_v REAL,
            drains_v REAL,
            all_fuel REAL,
            avg100_run REAL,
            avg100_all REAL,
            start_mv TEXT,
            stop_mv TEXT,
            stop_secs INTEGER,
            stop_min INTEGER,
            total_fs REAL,
            total_fe REAL,
            fuel_start_rows_json TEXT,
            fuel_end_rows_json TEXT,
            fuels_json TEXT,
            stops_json TEXT,
            search_msg TEXT,
            corr_odo_start REAL,
            corr_odo_end REAL,
            corr_fuel_start REAL,
            corr_fuel_end REAL,
            corr_fueling_total REAL,
            created_at TEXT,
            updated_at TEXT
        )""")
        c.commit()


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def make_waybill_no(start_dt, plate):
    """ДДММГГ_PLATE — санітизуємо plate до [A-Za-z0-9А-Яа-яІіЇїЄєҐґ]."""
    safe = re.sub(r"[^A-Za-z0-9А-Яа-яІіЇїЄєҐґ]+", "", plate or "")
    return f"{start_dt.strftime('%d%m%y')}_{safe or 'NA'}"


def db_save_waybill(ctx):
    """Upsert ctx into waybills. Preserves existing corrections and created_at."""
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_FILE) as c:
        c.row_factory = sqlite3.Row
        existing = c.execute("SELECT * FROM waybills WHERE waybill_no=?",
                             (ctx["waybill_no"],)).fetchone()
        created = existing["created_at"] if existing else now
        # preserve corrections from existing row
        corr = {k: (existing[k] if existing else None) for k in
                ("corr_odo_start","corr_odo_end","corr_fuel_start",
                 "corr_fuel_end","corr_fueling_total")}

        row = {
            "waybill_no":   ctx["waybill_no"],
            "waybill_date": ctx["waybill_date"],
            "trip_start_iso": ctx["s_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            "trip_end_iso":   ctx["e_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            "oid":      int(ctx["oid"]),
            "vname":    ctx.get("vname",""),
            "driver":   ctx.get("driver",""),
            "veh_type": ctx.get("veh_type",""),
            "plate":    ctx.get("plate",""),
            "trailer":  ctx.get("trailer",""),
            "scenario": ctx.get("scenario","3"),
            "order_num":    ctx.get("order_num",""),
            "cargo_name":   ctx.get("cargo_n",""),
            "cargo_weight": str(ctx.get("cargo_w","")),
            "addr_start":   ctx.get("addr_start",""),
            "addr_end":     ctx.get("addr_end",""),
            "coords_start": ctx.get("coords_s",""),
            "coords_end":   ctx.get("coords_e",""),
            "odo_s_val": _to_float(ctx.get("odo_s_val")),
            "odo_e_val": _to_float(ctx.get("odo_e_val")),
            "sf_lvl":    _to_float(ctx.get("sf_lvl")),
            "ef_lvl":    _to_float(ctx.get("ef_lvl")),
            "dist":      _to_float(ctx.get("dist")),
            "can_dist":  _to_float(ctx.get("can_dist")),
            "odo_dist":  _to_float(ctx.get("odo_dist")),
            "can_dist_calc": 1 if ctx.get("can_dist_calc") else 0,
            "odo_dist_calc": 1 if ctx.get("odo_dist_calc") else 0,
            "fuelings_v": _to_float(ctx.get("fuelings_v")),
            "drains_v":   _to_float(ctx.get("drains_v")),
            "all_fuel":   _to_float(ctx.get("all_fuel")),
            "avg100_run": _to_float(ctx.get("avg100_run")),
            "avg100_all": _to_float(ctx.get("avg100_all")),
            "start_mv":   ctx.get("start_mv",""),
            "stop_mv":    ctx.get("stop_mv",""),
            "stop_secs":  int(ctx.get("stop_secs") or 0),
            "stop_min":   int(ctx.get("stop_min") or 60),
            "total_fs":   _to_float(ctx.get("total_fs")),
            "total_fe":   _to_float(ctx.get("total_fe")),
            "fuel_start_rows_json": json.dumps(ctx.get("fuel_start_rows", []),
                                               ensure_ascii=False),
            "fuel_end_rows_json":   json.dumps(ctx.get("fuel_end_rows", []),
                                               ensure_ascii=False),
            "fuels_json": json.dumps(ctx.get("fuels", []), ensure_ascii=False),
            "stops_json": json.dumps(ctx.get("stops", []), ensure_ascii=False),
            "search_msg": ctx.get("search_msg",""),
            "created_at": created,
            "updated_at": now,
            **corr,
        }
        cols = ",".join(row.keys())
        placeholders = ",".join("?" for _ in row)
        c.execute(f"INSERT OR REPLACE INTO waybills ({cols}) VALUES ({placeholders})",
                  tuple(row.values()))
        c.commit()


def db_load_waybill(waybill_no):
    """Returns ctx dict ready for _render_waybill, or None."""
    with sqlite3.connect(DB_FILE) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM waybills WHERE waybill_no=?",
                      (waybill_no,)).fetchone()
        if not r:
            return None
        ctx = {
            "waybill_no":   r["waybill_no"],
            "waybill_date": r["waybill_date"],
            "s_dt":     parse_dt(r["trip_start_iso"]),
            "e_dt":     parse_dt(r["trip_end_iso"]),
            "oid":      r["oid"],
            "vname":    r["vname"] or "",
            "driver":   r["driver"] or "—",
            "veh_type": r["veh_type"] or "—",
            "plate":    r["plate"] or "—",
            "trailer":  r["trailer"] or "—",
            "scenario": r["scenario"] or "3",
            "order_num":r["order_num"] or "",
            "cargo_n":  r["cargo_name"] or "",
            "cargo_w":  r["cargo_weight"] or "",
            "addr_start": r["addr_start"] or "—",
            "addr_end":   r["addr_end"] or "—",
            "coords_s":   r["coords_start"] or "",
            "coords_e":   r["coords_end"] or "",
            "odo_s_val":  r["odo_s_val"],
            "odo_e_val":  r["odo_e_val"],
            "sf_lvl":     r["sf_lvl"],
            "ef_lvl":     r["ef_lvl"],
            "dist":       r["dist"],
            "can_dist":   r["can_dist"],
            "odo_dist":   r["odo_dist"],
            "can_dist_calc": bool(r["can_dist_calc"]),
            "odo_dist_calc": bool(r["odo_dist_calc"]),
            "fuelings_v": r["fuelings_v"],
            "drains_v":   r["drains_v"],
            "all_fuel":   r["all_fuel"],
            "avg100_run": r["avg100_run"],
            "avg100_all": r["avg100_all"],
            "start_mv":   r["start_mv"] or "—",
            "stop_mv":    r["stop_mv"] or "—",
            "stop_secs":  r["stop_secs"] or 0,
            "stop_min":   r["stop_min"] or 60,
            "total_fs":   r["total_fs"],
            "total_fe":   r["total_fe"],
            "fuel_start_rows": json.loads(r["fuel_start_rows_json"] or "[]"),
            "fuel_end_rows":   json.loads(r["fuel_end_rows_json"] or "[]"),
            "fuels":      json.loads(r["fuels_json"] or "[]"),
            "stops":      json.loads(r["stops_json"] or "[]"),
            "search_msg": r["search_msg"] or "",
            "corr_odo_start":     r["corr_odo_start"],
            "corr_odo_end":       r["corr_odo_end"],
            "corr_fuel_start":    r["corr_fuel_start"],
            "corr_fuel_end":      r["corr_fuel_end"],
            "corr_fueling_total": r["corr_fueling_total"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        return ctx


def db_list_waybills(sort="date"):
    """sort: 'date' | 'driver' | 'plate'."""
    order = {
        "date":   "waybill_date DESC, waybill_no DESC",
        "driver": "driver COLLATE NOCASE ASC, waybill_date DESC",
        "plate":  "plate COLLATE NOCASE ASC, waybill_date DESC",
    }.get(sort, "waybill_date DESC")
    with sqlite3.connect(DB_FILE) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(f"""SELECT waybill_no, waybill_date, trip_start_iso,
                trip_end_iso, plate, driver, vname, order_num,
                dist, can_dist, fuelings_v, updated_at
            FROM waybills ORDER BY {order}""").fetchall()
        return [dict(r) for r in rows]


def db_update_corrections(waybill_no, fields):
    """fields: dict with optional keys corr_odo_start, corr_odo_end,
       corr_fuel_start, corr_fuel_end, corr_fueling_total. None = clear."""
    allowed = {"corr_odo_start","corr_odo_end","corr_fuel_start",
               "corr_fuel_end","corr_fueling_total"}
    set_parts, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        set_parts.append(f"{k}=?")
        vals.append(_to_float(v))
    if not set_parts:
        return
    set_parts.append("updated_at=?")
    vals.append(datetime.now().isoformat(timespec="seconds"))
    vals.append(waybill_no)
    with sqlite3.connect(DB_FILE) as c:
        c.execute(f"UPDATE waybills SET {','.join(set_parts)} WHERE waybill_no=?",
                  tuple(vals))
        c.commit()


def apply_corrections_to_ctx(ctx):
    """Overlay non-null corrections onto display fields. Recompute odo_dist
       if both odometer overrides are set."""
    if ctx.get("corr_odo_start") is not None:
        ctx["odo_s_val"] = ctx["corr_odo_start"]
    if ctx.get("corr_odo_end") is not None:
        ctx["odo_e_val"] = ctx["corr_odo_end"]
    if ctx.get("corr_odo_start") is not None and ctx.get("corr_odo_end") is not None:
        try:
            ctx["odo_dist"] = float(ctx["corr_odo_end"]) - float(ctx["corr_odo_start"])
            ctx["odo_dist_calc"] = True
        except (TypeError, ValueError):
            pass
    if ctx.get("corr_fuel_start") is not None:
        ctx["sf_lvl"] = ctx["corr_fuel_start"]
    if ctx.get("corr_fuel_end") is not None:
        ctx["ef_lvl"] = ctx["corr_fuel_end"]
    if ctx.get("corr_fueling_total") is not None:
        ctx["fuelings_v"] = ctx["corr_fueling_total"]


# ── HTTP / API ───────────────────────────────────────────────────────────────
def connect():
    r = requests.get(f"{BASE_URL}/connect",
                     params={"login": LOGIN, "password": PASSWORD,
                             "lang": "ru-ru", "timezone": str(UTC_OFFSET)},
                     timeout=30)
    sid = r.headers.get("sessionid") or r.headers.get("SessionId")
    if not sid:
        print("Помилка авторизації"); sys.exit(1)
    return sid


def api_get(path, params=None, timeout=30):
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=HEADERS,
                         params=params or {}, timeout=timeout)
        if r.status_code != 200:
            return None
        ct = r.headers.get("Content-Type", "")
        if "json" in ct:
            return r.json()
        return r.text
    except Exception as exc:
        print(f"  api_get {path} error: {exc}")
        return None


# ── Drivers/vehicles directory ───────────────────────────────────────────────
def load_drivers():
    """
    Зі справочника читаємо за позиціями колонок (реальна структура файлу
    Сцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx):
      [0]=№, [1]=ФИО, [2]=ID об'єкта, [3]=марка (тип авто),
      [4]=Номер авто, [5]=Номер прицепа.
    Повертаємо dict {oid_int: {fio, type, plate, trailer}}.
    """
    if not os.path.exists(DRIVERS_EXCEL):
        print(f"  Справочник не знайдено: {DRIVERS_EXCEL}")
        return {}
    try:
        import pandas as pd
        df = pd.read_excel(DRIVERS_EXCEL)
        out = {}
        for _, row in df.iterrows():
            try:
                oid = int(float(row.iloc[2]))
            except (ValueError, TypeError):
                continue
            def cell(idx):
                try:
                    v = row.iloc[idx]
                except IndexError:
                    return ""
                if v is None: return ""
                s = str(v).strip()
                return "" if s.lower() in ("nan", "none", "—", "-") else s
            out[oid] = {
                "fio":     cell(1),
                "type":    cell(3),
                "plate":   cell(4),
                "trailer": cell(5),
            }
        print(f"  Водіїв із справочника: {len(out)} (файл: {os.path.basename(DRIVERS_EXCEL)})")
        return out
    except Exception as exc:
        print(f"  Помилка читання справочника: {exc}")
        return {}


# ── Sensor cache ─────────────────────────────────────────────────────────────
def load_sensor_cache(objects):
    current = {str(o["id"]) for o in objects}
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        if not (current - set(cache.get("vehicles", {}).keys())):
            return cache["vehicles"]
    veh = cache.get("vehicles", {})
    for o in objects:
        oid_s = str(o["id"])
        if oid_s in veh:
            continue
        data = api_get("/objsensorslist", {"oid": o["id"]})
        sensors = data.get("obj_sensors", []) if (data and data.get("result") == "Ok") else []
        veh[oid_s] = {"name": o["name"], "sensors": sensors}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().isoformat(timespec="seconds"),
                   "vehicles": veh}, f, ensure_ascii=False, indent=2)
    return veh


def find_odo_sensor(sensors):
    keywords = ["датчик накопленного пробега", "can абсолютный пробег", "абсолютный пробег"]
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in keywords):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return (f"s{sid_v}", s["name"].strip())
            if pid_v > 0: return (f"p{pid_v}", s["name"].strip())
    return None


def find_fuel_sensors(sensors):
    """Сначала единый «Топливо», иначе список «Бак*». Без температур, расходов, %."""
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(k in lo for k in FUEL_COMBINED) and not any(e in lo for e in FUEL_EXCLUDE):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return [(f"s{sid_v}", s["name"].strip())]
            if pid_v > 0: return [(f"p{pid_v}", s["name"].strip())]
    res = []
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(k in lo for k in FUEL_TANK) and not any(e in lo for e in FUEL_EXCLUDE):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0:   res.append((f"s{sid_v}", s["name"].strip()))
            elif pid_v > 0: res.append((f"p{pid_v}", s["name"].strip()))
    return res


# ── API helpers ──────────────────────────────────────────────────────────────
def query_objdata_period(oid, slist, dt_from, dt_to, take="first"):
    data = api_get("/objdata", {"oid": oid, "slist": slist, "compress": "true",
                                "from": dt_from, "to": dt_to})
    if not data or data.get("result") != "Ok":
        return None
    records = data.get("obj_data", {}).get("records", [])
    vals = [float(rec[1]) for rec in records
            if len(rec) > 1 and rec[1] is not None and str(rec[1]).strip()]
    if not vals: return None
    return vals[0] if take == "first" else vals[-1]


def _parse_objdata_ts(ts):
    """rec[0] из /objdata: пробуем строку (через parse_dt) или unix-epoch."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.utcfromtimestamp(int(ts))
        except (ValueError, OSError):
            return None
    s = str(ts).strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return datetime.utcfromtimestamp(int(s))
        except (ValueError, OSError):
            return None
    return parse_dt(s)


def find_dt_by_odo(oid, slist, target_odo, base_dt_utc, direction="forward",
                   max_days=ODO_SEARCH_DAYS, tol_km=ODO_TOLERANCE_KM):
    """
    Поиск даты/времени (UTC) по показанию одометра.

    Args:
      oid          — id объекта.
      slist        — slist датчика одометра ('s{sid}' или 'p{pid}').
      target_odo   — искомое показание (км).
      base_dt_utc  — отправная точка (datetime, UTC).
      direction    — 'forward' (от base вперёд) или 'backward' (от base назад).
      max_days     — макс. кол-во суточных шагов.
      tol_km       — допуск, км.

    Returns:
      (datetime_utc, value_km) первой найденной записи, или (None, None).
    """
    sign = 1 if direction == "forward" else -1
    print(f"    find_dt_by_odo: target={target_odo} base={base_dt_utc} "
          f"dir={direction} tol={tol_km}km")
    for day_off in range(max_days):
        d_start = base_dt_utc + timedelta(days=sign * day_off if sign > 0
                                          else -day_off - 1)
        d_end   = d_start + timedelta(days=1)
        d_from  = d_start.strftime("%Y-%m-%d %H:%M:%S")
        d_to    = d_end.strftime("%Y-%m-%d %H:%M:%S")
        data = api_get("/objdata", {"oid": oid, "slist": slist,
                                    "compress": "false",
                                    "from": d_from, "to": d_to})
        if not data or data.get("result") != "Ok":
            continue
        records = data.get("obj_data", {}).get("records", [])
        if not records:
            continue
        # перебираем в порядке поиска: вперёд — с начала суток, назад — с конца
        iter_recs = records if sign > 0 else reversed(records)
        for rec in iter_recs:
            if len(rec) < 2 or rec[1] is None:
                continue
            try:
                val = float(str(rec[1]).strip())
            except (ValueError, TypeError):
                continue
            if abs(val - target_odo) < tol_km:
                dt = _parse_objdata_ts(rec[0])
                if dt:
                    print(f"    → найдено: {dt} UTC, value={val} км "
                          f"(diff={abs(val - target_odo):.2f} км, день +{sign*day_off})")
                    return dt, val
    print(f"    → не найдено за {max_days} дн.")
    return None, None


def get_address(lat, lon):
    if lat is None or lon is None:
        return "—"
    txt = api_get("/getaddress", {"lat": lat, "lon": lon}, timeout=15)
    if not txt: return "—"
    return str(txt).strip().strip('"') or "—"


def get_coords_around(oid, dt_utc, window_min=5):
    """
    Координати ТЗ біля моменту dt_utc. Через /getobjectsreport за вузьке вікно
    (param=start_coords;stop_coords). Повертає (lat, lon) або None.
    """
    d_from = (dt_utc - timedelta(minutes=window_min)).strftime("%Y-%m-%d %H:%M:%S")
    d_to   = (dt_utc + timedelta(minutes=window_min)).strftime("%Y-%m-%d %H:%M:%S")
    data = api_get("/getobjectsreport", {
        "objuids":   str(oid), "date_from": d_from, "date_to": d_to,
        "split":     "none", "param":     "start_coords;stop_coords",
    })
    if not isinstance(data, list) or not data:
        return None
    periods = data[0].get("periods") or []
    if not periods:
        return None
    prms = {p["name"]: p.get("value")
            for p in periods[0].get("prms", []) if "name" in p}
    for key in ("start_coords", "stop_coords"):
        v = prms.get(key)
        if v and isinstance(v, str) and ";" in v:
            try:
                lat, lon = v.split(";", 1)
                return float(lat.strip()), float(lon.strip())
            except (ValueError, TypeError):
                continue
    return None


def enrich_events_with_address(oid, events):
    """
    Для кожної події вкладає (lat, lon, addr). Кешує запити /getaddress
    у межах одного виклику, бо координати поряд можуть повторюватись.
    """
    addr_cache = {}
    for ev in events:
        coords = get_coords_around(oid, ev["dt_utc"], window_min=5)
        if not coords:
            coords = get_coords_around(oid, ev["dt_utc"], window_min=30)
        if coords:
            ev["lat"], ev["lon"] = coords
            key = (round(coords[0], 4), round(coords[1], 4))
            if key not in addr_cache:
                addr_cache[key] = get_address(coords[0], coords[1])
            ev["addr"] = addr_cache[key]
        else:
            ev["lat"] = ev["lon"] = None
            ev["addr"] = "—"
    return events


def get_objects_report(oid, dt_from, dt_to, params_str):
    data = api_get("/getobjectsreport",
                   {"objuids": str(oid), "date_from": dt_from, "date_to": dt_to,
                    "split": "none", "param": params_str})
    print(f"    [debug] /getobjectsreport raw type={type(data).__name__} "
          f"len={len(data) if hasattr(data,'__len__') else '-'}")
    if isinstance(data, list) and data:
        print(f"    [debug] data[0] keys: {list(data[0].keys())}")
        periods = data[0].get("periods", [])
        print(f"    [debug] periods count: {len(periods)}")
        if periods:
            print(f"    [debug] periods[0] keys: {list(periods[0].keys())}")
            prms = periods[0].get("prms", [])
            print(f"    [debug] prms names: {[p.get('name') for p in prms]}")
    else:
        print(f"    [debug] raw response: {repr(data)[:500]}")
    if not data or not isinstance(data, list) or not data:
        return {}
    periods = data[0].get("periods", [])
    if not periods: return {}
    prms = periods[0].get("prms", [])
    return {p["name"]: p.get("value") for p in prms if "name" in p}


def find_garage_zones():
    """
    Шукає в /getgeotree всі вузли name=='гараж' (не група).
    Дедуплікація: якщо для одного імені є і полігон, і точка — точку відкидаємо
    (полігон точніше описує реальне місце, точка часто — застарілий дубль,
    який все одно повертається з /getgeotree, навіть якщо show_on_map=false).
    """
    data = api_get("/getgeotree", {"all": "true"}, timeout=15)
    if not data: return []
    found = []
    def walk(nodes):
        for n in (nodes or []):
            if (n.get("name", "").lower() == "гараж") and not n.get("IsGroup"):
                found.append({
                    "id":       n["real_id"],
                    "name":     n.get("name", ""),
                    "geo_type": n.get("geo_type", ""),
                })
            walk(n.get("children") or [])
    walk(data.get("children", []))

    by_name = {}
    for z in found:
        by_name.setdefault(z["name"].lower(), []).append(z)
    deduped = []
    for name_low, zones in by_name.items():
        polygons = [z for z in zones if z.get("geo_type") == "polygon"]
        points   = [z for z in zones if z.get("geo_type") != "polygon"]
        if polygons and points:
            ids = ", ".join(str(z["id"]) for z in points)
            print(f"  • ігнорую дублікати-точки для '{name_low}': real_id={ids} "
                  f"(є полігон з тим же ім'ям)")
            deduped.extend(polygons)
        else:
            deduped.extend(zones)
    return deduped


def get_visits(oid, zone_ids, dt_from, dt_to):
    data = api_get("/zonesvisits",
                   {"objects_ids": str(oid),
                    "zones_ids":   ",".join(map(str, zone_ids)),
                    "from":        dt_from,
                    "to":          dt_to,
                    "minDuration": 0})
    raw = data.get("visits", []) if data else []
    return merge_short_gaps(raw, MERGE_GAP_MINUTES * 60)


def merge_short_gaps(visits, min_gap_sec):
    """
    Об'єднує сусідні візити в одну геозону, якщо розрив між
    out_dt попереднього і in_dt наступного < min_gap_sec.
    Використовується для фільтрації GPS-«дрижання» на межі геозони:
    коли координата на секунду стрибає за межу і назад,
    створюючи фантомний виїзд+в'їзд тривалістю кілька секунд / хвилин.
    """
    if not visits: return visits
    visits = sorted(visits, key=lambda v: v.get("in_dt") or "")
    merged = [dict(visits[0])]
    for v in visits[1:]:
        prev = merged[-1]
        prev_out = parse_dt(prev.get("out_dt"))
        cur_in   = parse_dt(v.get("in_dt"))
        if prev.get("not_Ended") or not prev_out or not cur_in:
            merged.append(dict(v))
            continue
        gap = (cur_in - prev_out).total_seconds()
        if gap < min_gap_sec:
            # розширюємо попередній візит
            prev["out_dt"]    = v.get("out_dt")
            prev["not_Ended"] = v.get("not_Ended", False)
        else:
            merged.append(dict(v))
    return merged


def get_fuelings(oid, dt_from, dt_to):
    data = api_get("/fuelings", {"oid": oid, "from": dt_from, "to": dt_to})
    if not data or data.get("result") != "Ok":
        return []
    out = []
    for ev in data.get("fuelings", []):
        if ev.get("fuel_type") and ev.get("fuel_type") != "fueling":
            continue
        # /fuelings повертає start_time у UTC — конвертуємо в LOCAL для відображення
        utc_dt   = parse_dt(ev.get("start_time", ""))
        local_dt = to_local(utc_dt)
        out.append({
            "time":   local_dt.strftime("%Y-%m-%d %H:%M:%S") if local_dt else "",
            "volume": float(ev.get("volume", 0) or 0),
            "lat":    ev.get("lat"),
            "lon":    ev.get("lon"),
        })
    return out


def find_stops(oid, dt_from, dt_to, min_minutes=60):
    """Стоянки длительностью >= min_minutes, с обратным геокодированием.
    /stops приймає і повертає UTC; час показуємо в LOCAL."""
    min_sec = min_minutes * 60
    api_filter = min(min_sec, 3600)  # API: 3600 = >= 1ч
    data = api_get("/stops", {"oid": oid, "from": dt_from, "to": dt_to,
                              "time": api_filter}, timeout=45)
    if not data or data.get("result") != "Ok":
        return []
    out = []
    for s in data.get("stops", []):
        dur = s.get("duration", 0) or 0
        if dur < min_sec: continue
        lat, lon = s.get("lat"), s.get("lon")
        addr = get_address(lat, lon) if (lat and lon) else "—"
        st_utc  = parse_dt(s.get("stop_time", ""))
        st_loc  = to_local(st_utc)
        end_loc = (st_loc + timedelta(seconds=dur)) if st_loc else None
        out.append({
            "start":   fmt_dt(st_loc),
            "end":     fmt_dt(end_loc),
            "dur_sec": dur,
            "dur_str": dur_str(dur),
            "addr":    addr,
        })
    return out


# ── Date helpers ─────────────────────────────────────────────────────────────
def parse_dt(s):
    if not s: return None
    s = str(s).replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try: return datetime.strptime(s, fmt)
        except ValueError: continue
    return None


def fmt_dt(dt):
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


def to_local(dt):
    return dt + timedelta(hours=UTC_OFFSET) if dt else None


def dur_str(secs):
    if secs is None or secs == "": return "—"
    try:
        s = int(float(secs))
    except (ValueError, TypeError):
        return "—"
    if s < 0: return "—"
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d}д " if d else "") + f"{h:02d}:{m:02d}"


# ── Build garage events list ─────────────────────────────────────────────────
def build_events(visits):
    """
    Из ответа /zonesvisits формирует список событий, отсортированный по времени:
      {"type": "exit"|"entry", "iso_local": "2026-04-01T08:30:00", "label": "..."}
    in_dt → entry (вьезд), out_dt → exit (выезд).
    """
    events = []
    for v in visits:
        in_utc  = parse_dt(v.get("in_dt"))
        out_utc = parse_dt(v.get("out_dt")) if not v.get("not_Ended") else None
        if in_utc:
            loc = to_local(in_utc)
            events.append({"type": "entry", "dt_utc": in_utc, "dt_local": loc,
                           "iso_local": loc.strftime("%Y-%m-%dT%H:%M:%S"),
                           "label": f"В'їзд у гараж — {fmt_dt(loc)}"})
        if out_utc:
            loc = to_local(out_utc)
            events.append({"type": "exit", "dt_utc": out_utc, "dt_local": loc,
                           "iso_local": loc.strftime("%Y-%m-%dT%H:%M:%S"),
                           "label": f"Виїзд з гаражу — {fmt_dt(loc)}"})
    events.sort(key=lambda e: e["dt_utc"])
    return events


# ── Global state ─────────────────────────────────────────────────────────────
SID          = None
HEADERS      = {}
OBJECTS      = []
VEH_CACHE    = {}
DRIVERS      = {}
GARAGE_ZONES = []


def init():
    global SID, HEADERS, OBJECTS, VEH_CACHE, DRIVERS, GARAGE_ZONES
    print("Ініціалізація БД abv_doroga...")
    db_init()
    print(f"  БД: {DB_FILE}")
    print("Підключення до API...")
    SID = connect()
    HEADERS = {"SessionId": SID}
    print("Отримання списку авто...")
    data = api_get("/getobjectslist")
    OBJECTS = sorted(data.get("objects", []), key=lambda o: o["name"]) if data else []
    print(f"  Авто: {len(OBJECTS)}")
    print("Завантаження кешу датчиків...")
    VEH_CACHE = load_sensor_cache(OBJECTS)
    print("Завантаження справочника...")
    DRIVERS = load_drivers()
    print("Пошук геозон «Гараж»...")
    GARAGE_ZONES = find_garage_zones()
    print(f"  Геозон: {len(GARAGE_ZONES)}")
    for z in GARAGE_ZONES:
        print(f"    • [{z['id']}] {z['name']}")
    print(f"\nГотово → http://localhost:{PORT}\n")


# ── Format helpers ───────────────────────────────────────────────────────────
def fv(v, dec=1, unit=""):
    if v is None or v == "":
        return "—"
    try:
        s = f"{float(v):,.{dec}f}".replace(",", " ")
        return f"{s} {unit}".strip() if unit else s
    except (ValueError, TypeError):
        return str(v)


def fdt_api(s):
    """API возвращает 'YYYY-MM-DD HH:MM:SS' (UTC?). Парсим и форматируем."""
    dt = parse_dt(s)
    return fmt_dt(dt) if dt else (s or "—")


# ── CSS ──────────────────────────────────────────────────────────────────────
STYLE = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#eef2f7;padding:30px;color:#222}
.card{background:#fff;padding:28px 32px;border-radius:12px;
      box-shadow:0 4px 18px rgba(0,0,0,.1);max-width:640px;margin:0 auto}
h2{text-align:center;margin-bottom:18px;color:#2c3e50}
h3{color:#1e3a5f;font-size:15px;margin-bottom:10px;
   border-bottom:2px solid #2563eb;padding-bottom:6px}
label{display:block;margin:12px 0 4px;font-weight:600;font-size:14px;color:#555}
select,input,textarea{width:100%;padding:10px 12px;border:1px solid #ccc;
                     border-radius:6px;font-size:14px;background:#fafafa;
                     font-family:inherit}
select:focus,input:focus,textarea:focus{border-color:#4a90d9;outline:none}
.row{display:flex;gap:12px}.row>div{flex:1}
.hint{font-size:12px;color:#888;margin-top:3px}
button[type=submit]{width:100%;margin-top:22px;padding:14px;background:#2563eb;
  color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer}
button[type=submit]:hover{background:#1d4ed8}
.btn-back{display:inline-block;padding:10px 22px;background:#6b7280;color:#fff;
          border-radius:8px;font-size:14px;font-weight:600;text-decoration:none;
          border:none;cursor:pointer;margin-right:8px}
.btn-print{padding:10px 22px;background:#16a34a;color:#fff;
           border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
/* waybill */
.wb{max-width:880px;margin:0 auto;background:#fff;padding:40px;
    border-radius:12px;box-shadow:0 4px 18px rgba(0,0,0,.12);font-size:14px}
.wb h1{text-align:center;font-size:22px;margin-bottom:6px}
.wb .sub{text-align:center;color:#666;margin-bottom:24px}
.section{margin-bottom:18px}
.section h3{margin-bottom:10px}
table{width:100%;border-collapse:collapse}
th,td{border:1px solid #d0d7e3;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f0f4fa;font-weight:600;white-space:nowrap}
td.num{text-align:right;font-family:monospace}
td.hi{font-weight:700;color:#1e3a5f}
.noprint{margin-top:20px;display:flex;gap:12px}
@media print{
  @page{size:A4 portrait;margin:8mm 10mm}
  .noprint,.btn-back,.btn-print{display:none}
  body{background:#fff;padding:0;font-size:9.5pt;line-height:1.25}
  .wb{box-shadow:none;padding:0;max-width:none;font-size:9.5pt;border-radius:0}
  .wb h1{font-size:14pt;margin-bottom:2px}
  .wb .sub{margin-bottom:6px;font-size:9pt}
  .section{margin-bottom:6px;page-break-inside:avoid}
  .section h3{font-size:10pt;margin-bottom:3px;padding-bottom:2px;border-bottom-width:1px}
  table{page-break-inside:avoid}
  th,td{padding:2px 5px;font-size:9pt;line-height:1.2}
  h2{font-size:13pt;margin-bottom:6px}
}
</style>"""


# ── Step 1: form (vehicle + period + manual fields) ──────────────────────────
def form_html():
    # Сортуємо: спочатку рядки зі справочника (є plate+fio), потім решта.
    def sort_key(o):
        d = DRIVERS.get(o["id"], {})
        has_data = bool(d.get("plate") or d.get("fio"))
        label = (d.get("plate") or o["name"]).lower()
        return (0 if has_data else 1, label)
    opts = []
    for o in sorted(OBJECTS, key=sort_key):
        d = DRIVERS.get(o["id"], {})
        plate = d.get("plate") or ""
        fio   = d.get("fio") or ""
        # Формат: «{номер авто} — {ФИО}  ·  {системна назва}»
        # Якщо plate чи fio немає — показуємо лише системну назву.
        if plate and fio:
            label = f"{plate} — {fio}  ·  {o['name']}"
        elif plate:
            label = f"{plate}  ·  {o['name']}"
        elif fio:
            label = f"{o['name']} — {fio}"
        else:
            label = o["name"]
        opts.append(f"<option value='{o['id']}'>{label}</option>")
    drivers_js = json.dumps({str(o["id"]): DRIVERS.get(o["id"], {}) for o in OBJECTS},
                            ensure_ascii=False)
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путевой лист (3 сценарії) — крок 1</title>{STYLE}
<style>
.scn{{display:flex;flex-direction:column;gap:8px;margin-top:6px}}
.scn label{{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;
   border:1px solid #ddd;border-radius:8px;cursor:pointer;margin:0;
   font-weight:500;font-size:14px;background:#fafafa}}
.scn label:hover{{border-color:#2563eb;background:#f0f7ff}}
.scn input[type=radio]{{width:auto;margin-top:3px;flex:none}}
.scn .sd{{font-size:12px;color:#666;font-weight:400;display:block;margin-top:2px}}
</style></head><body>
<div class="card">
  <h2>Путевой лист (3 сценарії) — крок 1</h2>
  <form action="/events" method="POST">
    <label>Сценарій формування</label>
    <div class="scn">
      <label><input type="radio" name="scenario" value="3" checked>
        <span><b>3. Виїзд + В'їзд у гараж</b>
        <span class="sd">Обидві події вибираються вручну з dropdown'ів /zonesvisits</span></span></label>
      <label><input type="radio" name="scenario" value="1">
        <span><b>1. Дата виїзду + одометр кінця</b>
        <span class="sd">Старт — exit з dropdown; фініш — пошук по /objdata вперед, поки |odo - X| &lt; {ODO_TOLERANCE_KM} км</span></span></label>
      <label><input type="radio" name="scenario" value="2">
        <span><b>2. Одометр початку + дата в'їзду</b>
        <span class="sd">Фініш — entry з dropdown; старт — пошук по /objdata назад, поки |odo - X| &lt; {ODO_TOLERANCE_KM} км</span></span></label>
      <label><input type="radio" name="scenario" value="4">
        <span><b>4. Перегляд бази</b>
        <span class="sd">Відкрити список усіх збережених путьових листів (БД abv_doroga) — без нового запиту до GPS API</span></span></label>
    </div>

    <div id="trip_fields">
    <label>Автомобіль</label>
    <select name="oid" id="oid_sel">{"".join(opts)}</select>

    <div class="row">
      <div><label>Тип авто</label>
           <input name="type" id="type_inp" placeholder="тягач / самосвал / ..."></div>
      <div><label>Номер авто</label>
           <input name="plate" id="plate_inp" placeholder="—"></div>
      <div><label>Номер прицепа</label>
           <input name="trailer" id="trailer_inp" placeholder="—"></div>
    </div>

    <label>Водій</label>
    <input name="driver" id="driver_inp" placeholder="ФИО" required>
    <div class="hint">Заповнюється автоматично зі справочника</div>

    <div class="row">
      <div><label>Початок періоду пошуку</label>
           <input type="date" name="date_from" id="df_inp" required></div>
      <div><label>Кінець періоду пошуку</label>
           <input type="date" name="date_to" id="dt_inp" required></div>
    </div>
    <div class="hint">У межах періоду буде показано всі виїзди/в'їзди в гараж — оберіть з них точні дати рейсу.</div>
    </div>

    <button type="submit" id="submit_btn">Далі — обрати дати рейсу</button>
  </form>
</div>
<script>
const DRV = {drivers_js};
const sel  = document.getElementById('oid_sel');
const fio  = document.getElementById('driver_inp');
const tp   = document.getElementById('type_inp');
const pl   = document.getElementById('plate_inp');
const tr   = document.getElementById('trailer_inp');
function fill() {{
  const d = DRV[sel.value] || {{}};
  fio.value = d.fio || '';
  tp.value  = d.type || '';
  pl.value  = d.plate || '';
  tr.value  = d.trailer || '';
}}
sel.addEventListener('change', fill);
fill();

// Scenario 4 — приховуємо поля авто/період і переключаємо submit на /saved
const trip = document.getElementById('trip_fields');
const btn  = document.getElementById('submit_btn');
const dr   = document.getElementById('driver_inp');
const df   = document.getElementById('df_inp');
const dt   = document.getElementById('dt_inp');
function onScn() {{
  const v = document.querySelector('input[name=scenario]:checked').value;
  if (v === '4') {{
    trip.style.display = 'none';
    dr.required = false; df.required = false; dt.required = false;
    btn.textContent = 'Перейти до бази збережених листів';
  }} else {{
    trip.style.display = '';
    dr.required = true;  df.required = true;  dt.required = true;
    btn.textContent = 'Далі — обрати дати рейсу';
  }}
}}
document.querySelectorAll('input[name=scenario]').forEach(r =>
  r.addEventListener('change', onScn));
onScn();
</script>
</body></html>"""


# ── Step 2: garage events → choose start/end ─────────────────────────────────
def events_html(form_state, events):
    """form_state — dict с oid, type, plate, trailer, driver, date_from, date_to."""
    if not events:
        return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Рейс не знайдено</title>{STYLE}</head><body>
<div class="card">
  <h2>{form_state.get('vname','—')}</h2>
  <p style="text-align:center;color:#666;padding:20px 0">
    За вказаний період подій у геозоні «Гараж» не знайдено.</p>
  <a class="btn-back" href="/">← Назад</a>
</div></body></html>"""

    # Розрахунок тривалості перебування в гаражі: entry → наступний exit.
    # Якщо стоянка < MIN_GARAGE_STAY_HOURS — обидві події (entry та наступний exit)
    # робимо неактивними (сірий + disabled).
    short_idx = set()
    stay_hours_for_entry = {}  # idx (entry) → години стоянки до наступного exit
    for i, ev in enumerate(events):
        if ev["type"] != "entry":
            continue
        for j in range(i + 1, len(events)):
            if events[j]["type"] == "exit":
                hrs = (events[j]["dt_utc"] - ev["dt_utc"]).total_seconds() / 3600
                stay_hours_for_entry[i] = hrs
                if hrs < MIN_GARAGE_STAY_HOURS:
                    short_idx.add(i)
                    short_idx.add(j)
                break

    # Подія підозріла, якщо адреса НЕ містить "усатов" чи "гараж"
    # (тобто за фактом ТЗ був не в гаражі — це фейк від /zonesvisits).
    def is_suspect(ev):
        a = (ev.get("addr") or "").lower()
        if not a or a == "—":
            return False
        return ("усатов" not in a) and ("гараж" not in a)

    # Опції dropdown'а — можна фільтрувати за типом події (exit/entry/None)
    def build_options(only_type=None):
        opts = ["<option value=''>— оберіть подію —</option>"]
        for i, ev in enumerate(events):
            if only_type and ev["type"] != only_type:
                continue
            kind = "Виїзд з гаражу" if ev["type"] == "exit" else "В'їзд у гараж"
            ts   = fmt_dt(ev["dt_local"])
            addr = ev.get("addr") or "—"
            addr_short = addr if len(addr) <= 70 else addr[:67] + "…"
            tail = ""
            if ev["type"] == "entry" and i in stay_hours_for_entry:
                hrs = stay_hours_for_entry[i]
                tail = f"  (у гаражі: {hrs:.1f} год)"
            suspect = is_suspect(ev)
            warn = " ⚠" if suspect else ""
            disabled = " disabled" if i in short_idx else ""
            if i in short_idx:
                style = " style='color:#aaa;background:#eee'"
            elif suspect:
                style = " style='color:#b91c1c;background:#fef2f2'"
            else:
                style = ""
            value    = f"{ev['type']}|{ev['iso_local']}"
            opts.append(f"<option value='{value}'{disabled}{style}>"
                        f"{warn} {kind} — {ts}  ·  {addr_short}{tail}</option>")
        return "".join(opts)

    scenario = form_state.get("scenario", "3")

    # Залежно від сценарію — різні поля для старту/фінішу.
    if scenario == "1":
        # Дата виїзду (exit-only) + одометр кінця
        exits_html = build_options(only_type="exit")
        trip_block = f"""
    <label>Початок рейсу (виїзд з гаражу)</label>
    <select name="trip_start" required>{exits_html}</select>

    <label>Одометр на кінець рейсу, км</label>
    <input name="odo_end_input" type="number" step="0.1" min="0" required
           placeholder="напр. 124356.0">
    <div class="hint">Дата фінішу буде знайдена автоматично: пошук по /objdata вперед від старту,
      поки |показання − введене| &lt; {ODO_TOLERANCE_KM} км (вікно до {ODO_SEARCH_DAYS} днів).</div>"""
    elif scenario == "2":
        # Одометр початку + дата в'їзду (entry-only)
        entries_html = build_options(only_type="entry")
        trip_block = f"""
    <label>Одометр на початок рейсу, км</label>
    <input name="odo_start_input" type="number" step="0.1" min="0" required
           placeholder="напр. 123730.5">
    <div class="hint">Дата старту буде знайдена автоматично: пошук по /objdata назад від фінішу,
      поки |показання − введене| &lt; {ODO_TOLERANCE_KM} км (вікно до {ODO_SEARCH_DAYS} днів).</div>

    <label>Кінець рейсу (в'їзд у гараж)</label>
    <select name="trip_end" required>{entries_html}</select>"""
    else:
        # Сценарій 3 — обидві події з dropdown
        options_html = build_options()
        trip_block = f"""
    <label>Початок рейсу (зазвичай — виїзд з гаражу)</label>
    <select name="trip_start" required>{options_html}</select>

    <label>Кінець рейсу (зазвичай — в'їзд у гараж)</label>
    <select name="trip_end" required>{options_html}</select>"""

    scn_titles = {"1": "Сценарій 1 — Дата виїзду + одометр кінця",
                  "2": "Сценарій 2 — Одометр початку + дата в'їзду",
                  "3": "Сценарій 3 — Виїзд + В'їзд у гараж"}
    scn_title = scn_titles.get(scenario, scn_titles["3"])

    # форму крок-2 завжди надсилаємо POST → /waybill зі всіма полями
    hidden = "".join(
        f"<input type='hidden' name='{k}' value='{(v or '').replace(chr(34),'&quot;')}'>"
        for k, v in form_state.items()
    )
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Рейс — обрати дати</title>{STYLE}</head><body>
<div class="card">
  <h2>Крок 2 — оберіть дати рейсу</h2>
  <p class="hint" style="text-align:center;font-weight:600;color:#2563eb">
    {scn_title}
  </p>
  <p class="hint" style="text-align:center">
    Авто: <b>{form_state.get('vname','—')}</b> &nbsp;|&nbsp;
    Період: {form_state['date_from']} — {form_state['date_to']}
  </p>
  <p class="hint" style="text-align:center">
    Події у хронологічному порядку. Сірі (неактивні) — стоянка в гаражі &lt; {MIN_GARAGE_STAY_HOURS} год.
    <br>⚠ червоні — координати події не в Усатовому/Гаражі (ймовірний фейк /zonesvisits — не обирай).
  </p>
  <form action="/waybill" method="POST">
    {hidden}
    {trip_block}

    <h3 style="margin-top:24px">Додаткові дані</h3>

    <label>№ Заявки</label>
    <input name="order_num" placeholder="(необов'язково)">

    <label>Найменування вантажу</label>
    <input name="cargo_name" placeholder="(необов'язково)">

    <label>Вага вантажу, т</label>
    <input name="cargo_weight" type="number" step="0.01" min="0" placeholder="0.00">

    <label>Мінімальна тривалість стоянки (хв)</label>
    <input name="stop_min" type="number" min="1" value="60">
    <div class="hint">За замовчуванням 60 хв (1 год). У коментарях друкуються адреси усіх стоянок ≥ цього часу.</div>

    <button type="submit">Сформувати путьовий лист</button>
  </form>
  <div style="margin-top:14px"><a class="btn-back" href="/">← Назад</a></div>
</div></body></html>"""


# ── Step 3: full waybill ─────────────────────────────────────────────────────
REPORT_PARAMS = (
    "start_address;stop_address;"
    "dist;can_dist;odo_dist;start_can_dist;stop_can_dist;"
    "all_fuel;fuelings;drains;start_fuel_level;stop_fuel_level;"
    "avg_dist_run_fuel;avg_all_fuel;"
    "start_move_time;stop_move_time;stop_time;"
    "start_coords;stop_coords"
)


def _build_waybill_ctx(state):
    """Heavy: API calls, parsing. Returns ctx dict, or {"error_html": "..."}."""
    oid       = int(state["oid"])
    vname     = state["vname"]
    driver    = state.get("driver", "—") or "—"
    veh_type  = state.get("type", "") or "—"
    plate     = state.get("plate", "") or "—"
    trailer   = state.get("trailer", "") or "—"
    scenario  = state.get("scenario", "3") or "3"
    # значення приходять у форматі "exit|YYYY-MM-DDTHH:MM:SS" або "entry|YYYY-MM-DDTHH:MM:SS"
    trip_s_raw = state.get("trip_start", "") or ""
    trip_e_raw = state.get("trip_end", "") or ""
    trip_s = trip_s_raw.split("|", 1)[-1] if trip_s_raw else ""
    trip_e = trip_e_raw.split("|", 1)[-1] if trip_e_raw else ""
    stop_min  = int(state.get("stop_min") or 60)
    order_num = state.get("order_num", "") or ""
    cargo_n   = state.get("cargo_name", "") or ""
    cargo_w   = state.get("cargo_weight", "") or ""

    s_dt = parse_dt(trip_s.replace("T", " ")) if trip_s else None
    e_dt = parse_dt(trip_e.replace("T", " ")) if trip_e else None

    # ── Сценарії 1/2: знайти відсутню дату через find_dt_by_odo ───────────────
    search_msg = ""
    if scenario in ("1", "2"):
        sensors  = VEH_CACHE.get(str(oid), {}).get("sensors", [])
        odo_pair = find_odo_sensor(sensors)
        if not odo_pair:
            return ("<h3>Помилка: для цього ТЗ не знайдено датчик одометра.</h3>"
                    "<a href='/'>← Назад</a>")

    if scenario == "1":
        try:
            odo_target = float((state.get("odo_end_input") or "").replace(",", "."))
        except ValueError:
            odo_target = 0
        if not s_dt or odo_target <= 0:
            return ("<h3>Помилка: вкажіть виїзд з гаражу та одометр кінця.</h3>"
                    "<a href='/'>← Назад</a>")
        base_utc = s_dt - timedelta(hours=UTC_OFFSET)
        print(f"\nСценарій 1: пошук дати фінішу за одометром {odo_target} км "
              f"(від {fmt_dt(s_dt)} вперед)...")
        found_utc, found_val = find_dt_by_odo(oid, odo_pair[0], odo_target,
                                              base_utc, "forward")
        if not found_utc:
            return (f"<h3>Не знайдено: одометр {odo_target} км (±{ODO_TOLERANCE_KM}) "
                    f"не зустрічається у наступних {ODO_SEARCH_DAYS} днях від старту.</h3>"
                    "<a href='/'>← Назад</a>")
        e_dt = found_utc + timedelta(hours=UTC_OFFSET)
        search_msg = (f"Дату фінішу знайдено по одометру: ціль {odo_target} км → "
                      f"{fmt_dt(e_dt)} (фактично {found_val:.1f} км)")

    elif scenario == "2":
        try:
            odo_target = float((state.get("odo_start_input") or "").replace(",", "."))
        except ValueError:
            odo_target = 0
        if not e_dt or odo_target <= 0:
            return ("<h3>Помилка: вкажіть в'їзд у гараж та одометр початку.</h3>"
                    "<a href='/'>← Назад</a>")
        base_utc = e_dt - timedelta(hours=UTC_OFFSET)
        print(f"\nСценарій 2: пошук дати старту за одометром {odo_target} км "
              f"(від {fmt_dt(e_dt)} назад)...")
        found_utc, found_val = find_dt_by_odo(oid, odo_pair[0], odo_target,
                                              base_utc, "backward")
        if not found_utc:
            return (f"<h3>Не знайдено: одометр {odo_target} км (±{ODO_TOLERANCE_KM}) "
                    f"не зустрічається у попередніх {ODO_SEARCH_DAYS} днях до фінішу.</h3>"
                    "<a href='/'>← Назад</a>")
        s_dt = found_utc + timedelta(hours=UTC_OFFSET)
        search_msg = (f"Дату старту знайдено по одометру: ціль {odo_target} км → "
                      f"{fmt_dt(s_dt)} (фактично {found_val:.1f} км)")

    if not s_dt or not e_dt or e_dt <= s_dt:
        return ("<h3>Помилка: невірно обрано дати рейсу.</h3>"
                "<a href='/'>← Назад</a>")

    # s_dt/e_dt — LOCAL-час, обраний з dropdown (out_dt/in_dt + UTC_OFFSET).
    # ВСІ ендпоїнти (/getobjectsreport, /fuelings, /stops, /objdata) приймають
    # параметри від/до як UTC (перевірено емпірично — параметр timezone у /connect
    # на них не діє). Конвертуємо LOCAL→UTC перед запитами; час подій,
    # які API повертає у UTC, конвертуємо назад у LOCAL для відображення.
    dt_from_local = s_dt.strftime("%Y-%m-%d %H:%M:%S")
    dt_to_local   = e_dt.strftime("%Y-%m-%d %H:%M:%S")
    dt_from_utc   = (s_dt - timedelta(hours=UTC_OFFSET)).strftime("%Y-%m-%d %H:%M:%S")
    dt_to_utc     = (e_dt - timedelta(hours=UTC_OFFSET)).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\nФормування путьового листа: {vname} {dt_from_local} — {dt_to_local} LOC")

    # ── /getobjectsreport ────────────────────────────────────────────────────
    print("  /getobjectsreport (utc)...")
    rpt = get_objects_report(oid, dt_from_utc, dt_to_utc, REPORT_PARAMS)

    # ── /fuelings (UTC, с адресами) ──────────────────────────────────────────
    print("  /fuelings (utc)...")
    fuels = get_fuelings(oid, dt_from_utc, dt_to_utc)
    for f in fuels:
        f["addr"] = get_address(f["lat"], f["lon"])

    # ── /stops >= stop_min хв (UTC, з адресами) ──────────────────────────────
    print(f"  /stops >= {stop_min} хв (utc)...")
    stops = find_stops(oid, dt_from_utc, dt_to_utc, stop_min)

    # ── уровень топлива на начало/конец рейса (objdata) ──────────────────────
    print("  Рівень палива (objdata)...")
    sensors = VEH_CACHE.get(str(oid), {}).get("sensors", [])
    fuel_pairs = find_fuel_sensors(sensors)
    fuel_start_rows, fuel_end_rows = [], []
    for slist, fname in fuel_pairs:
        v_s = query_objdata_period(oid, slist, dt_from_utc, dt_to_utc, "first")
        v_e = query_objdata_period(oid, slist, dt_from_utc, dt_to_utc, "last")
        fuel_start_rows.append((fname, v_s))
        fuel_end_rows.append((fname, v_e))
    total_fs = sum(v for _, v in fuel_start_rows if v) or None
    total_fe = sum(v for _, v in fuel_end_rows   if v) or None

    # одометр (резервно — если в getobjectsreport нет start_can_dist)
    odo_pair = find_odo_sensor(sensors)
    odo_start = odo_end = None
    if odo_pair:
        odo_start = query_objdata_period(oid, odo_pair[0], dt_from_utc, dt_to_utc, "first")
        odo_end   = query_objdata_period(oid, odo_pair[0], dt_from_utc, dt_to_utc, "last")

    # ── derived ──────────────────────────────────────────────────────────────
    addr_start = rpt.get("start_address") or "—"
    addr_end   = rpt.get("stop_address")  or "—"
    dist       = rpt.get("dist")
    can_dist   = rpt.get("can_dist")
    odo_dist   = rpt.get("odo_dist")
    start_can  = rpt.get("start_can_dist")
    stop_can   = rpt.get("stop_can_dist")

    # Fallback: якщо API не повернув can_dist/odo_dist — рахуємо як різницю
    # показань на старт/фініш. Mobiteam агрегує can_dist посуточно і при
    # довгих періодах або розривах даних може повернути null.
    can_dist_calc = False
    if (can_dist in (None, "")) and start_can not in (None, "") and stop_can not in (None, ""):
        try:
            can_dist = float(stop_can) - float(start_can)
            can_dist_calc = True
        except (TypeError, ValueError):
            pass

    odo_dist_calc = False
    if (odo_dist in (None, "")) and odo_start is not None and odo_end is not None:
        try:
            odo_dist = float(odo_end) - float(odo_start)
            odo_dist_calc = True
        except (TypeError, ValueError):
            pass
    all_fuel   = rpt.get("all_fuel")
    fuelings_v = rpt.get("fuelings")
    drains_v   = rpt.get("drains")
    sf_lvl     = rpt.get("start_fuel_level")
    ef_lvl     = rpt.get("stop_fuel_level")
    avg100_run = rpt.get("avg_dist_run_fuel")
    avg100_all = rpt.get("avg_all_fuel")
    start_mv   = fdt_api(rpt.get("start_move_time"))
    stop_mv    = fdt_api(rpt.get("stop_move_time"))
    stop_secs  = rpt.get("stop_time") or 0
    coords_s   = rpt.get("start_coords") or ""
    coords_e   = rpt.get("stop_coords")  or ""

    # путьовий лист: номер = ДДММГГ_PLATE (дата СТАРТУ рейсу + санітизований plate)
    waybill_no   = make_waybill_no(s_dt, plate)
    # waybill_date — дата старту рейсу (для індексу/сортування у списку)
    waybill_date = s_dt.strftime("%Y-%m-%d")

    # одометр на старт/конец: предпочитаем CAN из отчёта, иначе datchik
    odo_s_val = start_can if start_can not in (None, "") else odo_start
    odo_e_val = stop_can  if stop_can  not in (None, "") else odo_end

    return {
        "waybill_no":   waybill_no,
        "waybill_date": waybill_date,
        "s_dt": s_dt, "e_dt": e_dt,
        "oid": oid, "vname": vname,
        "driver": driver, "veh_type": veh_type,
        "plate": plate, "trailer": trailer,
        "scenario": scenario,
        "order_num": order_num,
        "cargo_n": cargo_n, "cargo_w": cargo_w,
        "addr_start": addr_start, "addr_end": addr_end,
        "coords_s": coords_s, "coords_e": coords_e,
        "odo_s_val": odo_s_val, "odo_e_val": odo_e_val,
        "sf_lvl": sf_lvl, "ef_lvl": ef_lvl,
        "dist": dist, "can_dist": can_dist, "odo_dist": odo_dist,
        "can_dist_calc": can_dist_calc, "odo_dist_calc": odo_dist_calc,
        "fuelings_v": fuelings_v, "drains_v": drains_v, "all_fuel": all_fuel,
        "avg100_run": avg100_run, "avg100_all": avg100_all,
        "start_mv": start_mv, "stop_mv": stop_mv,
        "stop_secs": stop_secs, "stop_min": stop_min,
        "total_fs": total_fs, "total_fe": total_fe,
        "fuel_start_rows": fuel_start_rows,
        "fuel_end_rows":   fuel_end_rows,
        "fuels": fuels, "stops": stops,
        "search_msg": search_msg,
        # корекції: ще не існують для свіжого розрахунку
        "corr_odo_start": None, "corr_odo_end": None,
        "corr_fuel_start": None, "corr_fuel_end": None,
        "corr_fueling_total": None,
    }


def _render_waybill(ctx, with_corrections_form=True):
    """Render waybill HTML from ctx dict (computed live or loaded from DB)."""
    waybill_no = ctx["waybill_no"]
    waybill_date = ctx["waybill_date"]
    # display: дата старту у форматі ДД.ММ.РРРР
    display_date = ctx["s_dt"].strftime("%d.%m.%Y") if ctx.get("s_dt") else waybill_date

    vname    = ctx.get("vname","—")
    oid      = ctx.get("oid","")
    driver   = ctx.get("driver","—")
    plate    = ctx.get("plate","—")
    trailer  = ctx.get("trailer","—")
    veh_type = ctx.get("veh_type","—")
    order_num = ctx.get("order_num","")
    cargo_n  = ctx.get("cargo_n","")
    cargo_w  = ctx.get("cargo_w","")
    s_dt = ctx.get("s_dt"); e_dt = ctx.get("e_dt")
    addr_start = ctx.get("addr_start","—")
    addr_end   = ctx.get("addr_end","—")
    coords_s   = ctx.get("coords_s","")
    coords_e   = ctx.get("coords_e","")
    odo_s_val  = ctx.get("odo_s_val")
    odo_e_val  = ctx.get("odo_e_val")
    sf_lvl     = ctx.get("sf_lvl")
    ef_lvl     = ctx.get("ef_lvl")
    dist       = ctx.get("dist")
    can_dist   = ctx.get("can_dist")
    odo_dist   = ctx.get("odo_dist")
    can_dist_calc = ctx.get("can_dist_calc", False)
    odo_dist_calc = ctx.get("odo_dist_calc", False)
    fuelings_v = ctx.get("fuelings_v")
    drains_v   = ctx.get("drains_v")
    all_fuel   = ctx.get("all_fuel")
    avg100_run = ctx.get("avg100_run")
    avg100_all = ctx.get("avg100_all")
    start_mv   = ctx.get("start_mv","—")
    stop_mv    = ctx.get("stop_mv","—")
    stop_secs  = ctx.get("stop_secs",0)
    stop_min   = ctx.get("stop_min",60)
    total_fs   = ctx.get("total_fs")
    total_fe   = ctx.get("total_fe")
    fuel_start_rows = ctx.get("fuel_start_rows", [])
    fuel_end_rows   = ctx.get("fuel_end_rows", [])
    fuels = ctx.get("fuels", [])
    stops = ctx.get("stops", [])
    search_msg = ctx.get("search_msg","")

    # Підказка, якщо є корекції
    has_corr = any(ctx.get(k) is not None for k in
                   ("corr_odo_start","corr_odo_end","corr_fuel_start",
                    "corr_fuel_end","corr_fueling_total"))

    def fuel_td(rows, total):
        if not rows or all(v is None for _, v in rows):
            return "<td>—</td>"
        lines = "".join(f"{n}: <b>{fv(v, 1)} л</b><br>" for n, v in rows)
        if len(rows) > 1 and total:
            lines += f"<hr style='margin:4px 0'>Разом: <b>{fv(total, 1)} л</b>"
        return f"<td>{lines}</td>"

    fuels_total = sum(f["volume"] for f in fuels) if fuels else 0
    if fuels:
        fuels_rows = "".join(
            f"<tr><td>{i+1}</td><td>{fdt_api(f['time'])}</td>"
            f"<td class='num'>{fv(f['volume'],1)} л</td>"
            f"<td>{f['addr']}</td></tr>"
            for i, f in enumerate(fuels)
        )
        fuels_rows += (f"<tr><th colspan='2' style='text-align:right'>Разом:</th>"
                       f"<th class='num'>{fv(fuels_total,1)} л</th><th></th></tr>")
    else:
        fuels_rows = "<tr><td colspan='4' style='text-align:center;color:#888'>Заправок не знайдено</td></tr>"

    if stops:
        stops_rows = "".join(
            f"<tr><td>{s['start']}</td><td>{s['end']}</td>"
            f"<td class='num'>{s['dur_str']}</td><td>{s['addr']}</td></tr>"
            for s in stops
        )
    else:
        stops_rows = (f"<tr><td colspan='4' style='text-align:center;color:#888'>"
                      f"Стоянок ≥ {stop_min} хв не знайдено</td></tr>")

    cargo_block = ""
    if order_num or cargo_n or cargo_w:
        cargo_rows = ""
        if order_num: cargo_rows += f"<tr><th width='220'>№ Заявки</th><td>{order_num}</td></tr>"
        if cargo_n:   cargo_rows += f"<tr><th>Найменування вантажу</th><td>{cargo_n}</td></tr>"
        if cargo_w:   cargo_rows += f"<tr><th>Вага вантажу</th><td class='num'>{fv(cargo_w,2)} т</td></tr>"
        cargo_block = f"""
  <div class="section">
    <h3>Вантаж / Заявка</h3>
    <table>{cargo_rows}</table>
  </div>"""

    # ── Форма корекцій ─────────────────────────────────────────────────────
    def _vi(x):
        if x is None or x == "":
            return ""
        try:
            return f"{float(x):.2f}"
        except (TypeError, ValueError):
            return str(x)

    corrections_block = ""
    if with_corrections_form:
        corr_badge = ("<span style='background:#fef3c7;color:#92400e;"
                      "padding:2px 8px;border-radius:4px;font-size:12px;"
                      "margin-left:8px'>застосовано корекції</span>") if has_corr else ""
        corrections_block = f"""
  <div class="noprint section" style="background:#f8fafc;padding:14px 18px;border:1px solid #cbd5e1;border-radius:8px;margin-top:18px">
    <h3 style="border-color:#64748b">Корекції значень{corr_badge}</h3>
    <p class="hint" style="margin-bottom:10px">
      Введіть точні значення (якщо потрібно скоригувати дані з GPS). Порожнє поле = залишити автоматичне.
      Дані запишуться в БД <b>abv_doroga</b> і відобразяться у листі вище.
    </p>
    <form action="/correct" method="POST">
      <input type="hidden" name="waybill_no" value="{waybill_no}">
      <div class="row">
        <div><label>Одометр старт, км</label>
             <input name="corr_odo_start" type="number" step="0.1" min="0"
                    value="{_vi(ctx.get('corr_odo_start'))}"
                    placeholder="{_vi(odo_s_val)}"></div>
        <div><label>Одометр фініш, км</label>
             <input name="corr_odo_end" type="number" step="0.1" min="0"
                    value="{_vi(ctx.get('corr_odo_end'))}"
                    placeholder="{_vi(odo_e_val)}"></div>
      </div>
      <div class="row">
        <div><label>Рівень палива старт, л</label>
             <input name="corr_fuel_start" type="number" step="0.1" min="0"
                    value="{_vi(ctx.get('corr_fuel_start'))}"
                    placeholder="{_vi(sf_lvl)}"></div>
        <div><label>Рівень палива фініш, л</label>
             <input name="corr_fuel_end" type="number" step="0.1" min="0"
                    value="{_vi(ctx.get('corr_fuel_end'))}"
                    placeholder="{_vi(ef_lvl)}"></div>
      </div>
      <label>Об'єм заправок за рейс, л</label>
      <input name="corr_fueling_total" type="number" step="0.1" min="0"
             value="{_vi(ctx.get('corr_fueling_total'))}"
             placeholder="{_vi(fuelings_v)}">
      <button type="submit">Зберегти корекції</button>
    </form>
  </div>"""

    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путьовий лист {waybill_no} — {vname}</title>{STYLE}</head><body>
<div class="wb">
  <h1>ПУТЬОВИЙ ЛИСТ № {waybill_no}</h1>
  <div class="sub">від {display_date}{(' &nbsp;|&nbsp; № заявки: ' + order_num) if order_num else ''}</div>
  {f'<div class="sub" style="background:#fffbe6;border:1px solid #f0c674;padding:8px 12px;border-radius:6px;color:#8a6d3b">{search_msg}</div>' if search_msg else ''}

  <div class="section">
    <h3>Загальні відомості</h3>
    <table>
      <tr><th width="220">№ путьового листа</th><td class="hi">{waybill_no}</td></tr>
      <tr><th>Дата путьового листа</th><td>{display_date}</td></tr>
      <tr><th>Водій</th><td>{driver}</td></tr>
      <tr><th>Номер авто</th><td>{plate}</td></tr>
      <tr><th>Номер причепа</th><td>{trailer}</td></tr>
      <tr><th>Об'єкт у системі</th><td>{vname} (id={oid})</td></tr>
    </table>
  </div>

  {cargo_block}

  <div class="section">
    <h3>Початок рейсу (виїзд з гаражу)</h3>
    <table>
      <tr><th width="220">Дата / час</th><td class="hi">{fmt_dt(s_dt)}</td></tr>
      <tr><th>Адреса</th><td>{addr_start}</td></tr>
      <tr><th>Координати</th><td>{coords_s or '—'}</td></tr>
      <tr><th>Одометр (CAN), км</th><td class="num">{fv(odo_s_val, 1)}</td></tr>
      <tr><th>Рівень палива на старт</th>{fuel_td(fuel_start_rows, total_fs)}</tr>
      <tr><th>start_fuel_level (з звіту)</th><td class="num">{fv(sf_lvl,1)} л</td></tr>
      <tr><th>Час початку руху</th><td>{start_mv}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Кінець рейсу (в'їзд у гараж)</h3>
    <table>
      <tr><th width="220">Дата / час</th><td class="hi">{fmt_dt(e_dt)}</td></tr>
      <tr><th>Адреса</th><td>{addr_end}</td></tr>
      <tr><th>Координати</th><td>{coords_e or '—'}</td></tr>
      <tr><th>Одометр (CAN), км</th><td class="num">{fv(odo_e_val, 1)}</td></tr>
      <tr><th>Рівень палива на фініш</th>{fuel_td(fuel_end_rows, total_fe)}</tr>
      <tr><th>stop_fuel_level (з звіту)</th><td class="num">{fv(ef_lvl,1)} л</td></tr>
      <tr><th>Час кінця руху</th><td>{stop_mv}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Підсумки рейсу</h3>
    <table>
      <tr><th width="220">Пробіг GPS (dist)</th><td class="num hi">{fv(dist,1)} км</td></tr>
      <tr><th>Пробіг CAN за рейс</th><td class="num hi">{fv(can_dist,1)} км{' <span style="color:#888;font-weight:400;font-size:11px">(різниця stop−start)</span>' if can_dist_calc else ''}</td></tr>
      <tr><th>Пробіг по одометру</th><td class="num">{fv(odo_dist,1)} км{' <span style="color:#888;font-weight:400;font-size:11px">(різниця stop−start)</span>' if odo_dist_calc else ''}</td></tr>
      <tr><th>Заправлено за рейс (звіт)</th><td class="num"><b>{fv(fuelings_v,1)} л</b></td></tr>
      <tr><th>Зливи</th><td class="num">{fv(drains_v,1)} л</td></tr>
      <tr><th>Загальна витрата (all_fuel)</th><td class="num">{fv(all_fuel,1)} л</td></tr>
      <tr><th>Середня витрата на 100 км руху</th><td class="num">{fv(avg100_run,2)} л/100 км</td></tr>
      <tr><th>Середня витрата на 100 км (з холостим)</th><td class="num">{fv(avg100_all,2)} л/100 км</td></tr>
      <tr><th>Загальний час стоянок</th><td>{dur_str(stop_secs)}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Заправки за період ({len(fuels)})</h3>
    <table>
      <tr><th width="40">#</th><th width="155">Дата / час</th>
          <th width="110">Об'єм</th><th>Адреса</th></tr>
      {fuels_rows}
    </table>
  </div>

  <div class="section">
    <h3>Стоянки ≥ {stop_min} хв ({len(stops)})</h3>
    <table>
      <tr><th width="155">Початок</th><th width="155">Кінець</th>
          <th width="80">Тривал.</th><th>Адреса</th></tr>
      {stops_rows}
    </table>
  </div>

  {corrections_block}

  <div class="noprint" style="margin-top:18px">
    <button class="btn-print" onclick="window.print()">Друк / PDF</button>
    <a class="btn-back" href="/">← Новий лист</a>
    <a class="btn-back" href="/saved" style="background:#0e7490">База путьових листів →</a>
  </div>
</div></body></html>"""


def waybill_html(state):
    """Live path: build ctx via API, save to DB, apply corrections, render."""
    ctx_or_err = _build_waybill_ctx(state)
    if isinstance(ctx_or_err, str):
        return ctx_or_err  # error HTML
    ctx = ctx_or_err
    try:
        db_save_waybill(ctx)
    except Exception as exc:
        print(f"  [db_save_waybill] {exc}")
    # завантажити свіжі корекції (можуть бути з попереднього збереження того ж wb_no)
    saved = db_load_waybill(ctx["waybill_no"])
    if saved:
        for k in ("corr_odo_start","corr_odo_end","corr_fuel_start",
                  "corr_fuel_end","corr_fueling_total"):
            ctx[k] = saved.get(k)
    apply_corrections_to_ctx(ctx)
    return _render_waybill(ctx)


def view_saved_html(waybill_no):
    """Render saved waybill from DB (no API calls)."""
    ctx = db_load_waybill(waybill_no)
    if not ctx:
        return (f"<h3>Путьовий лист «{waybill_no}» не знайдено в БД.</h3>"
                "<a href='/saved'>← Назад до списку</a>")
    apply_corrections_to_ctx(ctx)
    return _render_waybill(ctx)


# ── Saved waybills list (scenario 4) ─────────────────────────────────────────
def saved_list_html(sort="date"):
    rows = db_list_waybills(sort)
    if not rows:
        body = ("<p style='text-align:center;color:#888;padding:24px 0'>"
                "База порожня — поки що жодного путьового листа не збережено.</p>")
    else:
        body_rows = "".join(
            (lambda url: f"<tr>"
            f"<td><a href='{url}'>{r['waybill_no']}</a></td>"
            f"<td>{r['waybill_date'] or '—'}</td>"
            f"<td>{r['plate'] or '—'}</td>"
            f"<td>{r['driver'] or '—'}</td>"
            f"<td>{r['vname'] or '—'}</td>"
            f"<td>{r['order_num'] or '—'}</td>"
            f"<td class='num'>{fv(r['can_dist'],1) if r['can_dist'] is not None else '—'} км</td>"
            f"<td class='num'>{fv(r['fuelings_v'],1) if r['fuelings_v'] is not None else '—'} л</td>"
            f"<td><a href='{url}' style='color:#2563eb'>відкрити →</a></td>"
            f"</tr>")(f"/view?wb_no={quote(r['waybill_no'], safe='')}")
            for r in rows
        )
        body = f"""
        <table>
          <tr>
            <th><a href='/saved?sort=date' style='color:#1e3a5f;text-decoration:none'>№ листа ▾</a></th>
            <th><a href='/saved?sort=date' style='color:#1e3a5f;text-decoration:none'>Дата ▾</a></th>
            <th><a href='/saved?sort=plate' style='color:#1e3a5f;text-decoration:none'>Номер авто ▾</a></th>
            <th><a href='/saved?sort=driver' style='color:#1e3a5f;text-decoration:none'>ФІО ▾</a></th>
            <th>Об'єкт</th>
            <th>№ заявки</th>
            <th>Пробіг CAN</th>
            <th>Заправлено</th>
            <th></th>
          </tr>
          {body_rows}
        </table>"""

    sort_labels = {"date":"датою","driver":"ФІО","plate":"номером авто"}
    cur = sort_labels.get(sort, sort)
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>База путьових листів — abv_doroga</title>{STYLE}
<style>.wb table a:hover{{text-decoration:underline}}</style>
</head><body>
<div class="wb" style="max-width:1200px">
  <h1>Путьові листи в базі (abv_doroga)</h1>
  <div class="sub">Сортування: <b>{cur}</b> &nbsp;|&nbsp; Всього: <b>{len(rows)}</b></div>

  <div class="section" style="text-align:center;margin-bottom:14px">
    <a class="btn-back" href="/saved?sort=date"  style="background:{'#2563eb' if sort=='date' else '#6b7280'}">за датою</a>
    <a class="btn-back" href="/saved?sort=driver" style="background:{'#2563eb' if sort=='driver' else '#6b7280'}">за ФІО</a>
    <a class="btn-back" href="/saved?sort=plate"  style="background:{'#2563eb' if sort=='plate' else '#6b7280'}">за номером авто</a>
  </div>

  {body}

  <div class="noprint" style="margin-top:18px">
    <a class="btn-back" href="/">← Назад до головної</a>
  </div>
</div></body></html>"""


# ── HTTP handler ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_html(self, body, code=200):
        enc = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(enc)))
        self.end_headers()
        self.wfile.write(enc)

    def _read_form(self):
        n = int(self.headers.get("Content-Length", 0))
        return parse_qs(self.rfile.read(n).decode())

    def _val(self, body, key, default=""):
        return (body.get(key, [default])[0] or default).strip()

    def send_redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index", "/index.html"):
            self.send_html(form_html())
            return
        if path == "/saved":
            sort = (qs.get("sort", ["date"])[0] or "date").strip()
            self.send_html(saved_list_html(sort))
            return
        if path == "/view":
            wb_no = (qs.get("wb_no", [""])[0] or "").strip()
            self.send_html(view_saved_html(wb_no))
            return
        self.send_html("<h3>404</h3>", 404)

    def do_POST(self):
        body = self._read_form()
        try:
            if self.path == "/events":
                scenario = self._val(body, "scenario", "3")
                # Сценарій 4 — не шукаємо подій, відправляємо в /saved
                if scenario == "4":
                    self.send_redirect("/saved?sort=date")
                    return

                state = {
                    "oid":       self._val(body, "oid"),
                    "type":      self._val(body, "type"),
                    "plate":     self._val(body, "plate"),
                    "trailer":   self._val(body, "trailer"),
                    "driver":    self._val(body, "driver"),
                    "date_from": self._val(body, "date_from"),
                    "date_to":   self._val(body, "date_to"),
                    "scenario":  scenario,
                }
                oid = int(state["oid"])
                state["vname"] = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))

                api_from = f"{state['date_from']} 00:00:00"
                api_to   = f"{state['date_to']} 23:59:59"
                print(f"\nПошук подій гаражу: {state['vname']} {api_from} — {api_to}")
                zones = [z["id"] for z in GARAGE_ZONES]
                visits = get_visits(oid, zones, api_from, api_to)
                events = build_events(visits)
                print(f"  Подій: {len(events)}, отримую адреси...")
                enrich_events_with_address(oid, events)
                self.send_html(events_html(state, events))
                return

            if self.path == "/waybill":
                state = {k: self._val(body, k) for k in (
                    "oid","type","plate","trailer","driver","date_from","date_to",
                    "trip_start","trip_end","order_num","cargo_name","cargo_weight",
                    "stop_min","scenario","odo_start_input","odo_end_input")}
                oid = int(state["oid"])
                state["vname"] = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))
                self.send_html(waybill_html(state))
                return

            if self.path == "/correct":
                wb_no = self._val(body, "waybill_no")
                if not wb_no:
                    self.send_html("<h3>Помилка: відсутній номер листа.</h3>"
                                   "<a href='/saved'>← Назад</a>")
                    return
                fields = {}
                for k in ("corr_odo_start","corr_odo_end","corr_fuel_start",
                          "corr_fuel_end","corr_fueling_total"):
                    raw = (body.get(k, [""])[0] or "").strip().replace(",", ".")
                    if raw == "":
                        fields[k] = None  # очистити корекцію
                    else:
                        try:
                            fields[k] = float(raw)
                        except ValueError:
                            fields[k] = None
                db_update_corrections(wb_no, fields)
                print(f"  /correct {wb_no}: {fields}")
                self.send_redirect(f"/view?wb_no={quote(wb_no, safe='')}")
                return

            self.send_html("<h3>404</h3>", 404)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(tb)
            self.send_html(f"<h3>Помилка: {exc}</h3><pre>{tb}</pre>"
                           "<a href='/'>← Назад</a>")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init()
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
