#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевий лист v2 — веб-інтерфейс
=================================
Запуск: python app.py  →  http://localhost:8082

Крок 1: вибрати авто + задати довільний період
Крок 2: таблиця виїздів/в'їздів з геозони «Гараж» — клік мишею задає
         початок і кінець рейсу (рейси < 30 хв ігноруються)
Крок 3: путевий лист з усіма даними

Допоміжні дані (папка data/):
  company.json     — назва та місце складання компанії
  vehicles.json    — марка авто, держ. номер, причіп (доповнює Excel)
  sensors_cache.json — кеш датчиків (генерується автоматично)
"""

import requests, sys, json, os, webbrowser, time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────
API_URL      = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN        = "abvprom"
PASSWORD     = "29328"
UTC_OFFSET   = 2
PORT         = 8082
MIN_TRIP_MIN = 30   # рейси коротше ніж це — ігноруються

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(SCRIPT_DIR, "data")
CACHE_FILE    = os.path.join(DATA_DIR, "sensors_cache.json")
COMPANY_FILE  = os.path.join(DATA_DIR, "company.json")
VEHICLES_FILE = os.path.join(DATA_DIR, "vehicles.json")
DRIVERS_EXCEL = os.path.join(os.path.dirname(SCRIPT_DIR),
                             "Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx")

# ── Global state ──────────────────────────────────────────────────────────────
SID          = None
HEADERS      = {}
OBJECTS      = []      # [{id, name}, ...]
VEH_CACHE    = {}      # str(oid) → {name, sensors:[...]}
VEH_INFO     = {}      # int(oid) → {driver, plate, make, trailer}
COMPANY      = {}      # {name, place}
GARAGE_ZONES = []      # [{id, name}, ...]

ODO_KW   = ["датчик накопленного пробега", "can абсолютный пробег", "абсолютный пробег"]
FUEL_CMB = ["топливо"]
FUEL_TNK = ["бак"]
FUEL_EXC = ["расход", "температур", "°t", "уровень", "%", "can уровень"]

# ── Init ──────────────────────────────────────────────────────────────────────
def connect():
    r = requests.get(f"{API_URL}/connect",
                     params={"login": LOGIN, "password": PASSWORD,
                             "lang": "ru-ru", "timezone": str(UTC_OFFSET)},
                     timeout=15)
    sid = r.headers.get("sessionid") or r.json().get("sessionid")
    if not sid:
        raise RuntimeError("Помилка авторизації")
    return sid


def find_garage_zones(sid):
    r = requests.get(f"{API_URL}/getgeotree", headers={"SessionId": sid},
                     params={"all": "true"}, timeout=15)
    found = []
    def walk(nodes):
        for n in (nodes or []):
            if n.get("name", "").lower() == "гараж" and not n.get("IsGroup"):
                found.append({"id": n["real_id"], "name": n["name"]})
            walk(n.get("children") or [])
    walk(r.json().get("children", []))
    return found


def load_company():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(COMPANY_FILE):
        d = {"name": "ТОВ «Назва компанії»", "place": "м. Одеса"}
        with open(COMPANY_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return d
    with open(COMPANY_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_veh_info():
    veh = {}
    if os.path.exists(DRIVERS_EXCEL):
        try:
            import pandas as pd
            df = pd.read_excel(DRIVERS_EXCEL)
            for _, row in df.iterrows():
                try:
                    oid = int(float(row.iloc[2]))
                except Exception:
                    continue
                fio    = str(row.iloc[1]).strip()
                plate  = str(row.get("Номер авто",  row.iloc[0]) or "—").strip()
                trailer= str(row.get("Прицеп", "—") or "—").strip()
                make   = str(row.get("Марка",   "—") or "—").strip()
                veh[oid] = {
                    "driver":  fio  if fio  not in ("nan","") else "—",
                    "plate":   plate   if plate   not in ("nan","") else "—",
                    "trailer": trailer if trailer not in ("nan","") else "—",
                    "make":    make    if make    not in ("nan","") else "—",
                }
        except Exception as e:
            print(f"  Excel: {e}")

    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(VEHICLES_FILE):
        with open(VEHICLES_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    else:
        try:
            with open(VEHICLES_FILE, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    oid = int(k)
                    if oid not in veh:
                        veh[oid] = {"driver":"—","plate":"—","trailer":"—","make":"—"}
                    # vehicles.json може доповнити/перевизначити поля
                    veh[oid].update({kk: vv for kk, vv in v.items() if vv and vv != "—"})
        except Exception as e:
            print(f"  vehicles.json: {e}")
    return veh


def load_sensor_cache():
    global VEH_CACHE
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    vc      = cache.get("vehicles", {})
    missing = {str(o["id"]) for o in OBJECTS} - set(vc.keys())
    if missing:
        print(f"  Завантаження датчиків для {len(missing)} авто...")
        for o in OBJECTS:
            if str(o["id"]) not in missing:
                continue
            r = requests.get(f"{API_URL}/objsensorslist",
                             headers=HEADERS, params={"oid": o["id"]}, timeout=30)
            sensors = []
            if r.status_code == 200 and r.json().get("result") == "Ok":
                sensors = r.json().get("obj_sensors", [])
            vc[str(o["id"])] = {"name": o["name"], "sensors": sensors}
        cache = {"updated": datetime.now().isoformat(timespec="seconds"), "vehicles": vc}
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    VEH_CACHE = vc


def init():
    global SID, HEADERS, OBJECTS, VEH_INFO, COMPANY, GARAGE_ZONES
    print("Підключення до API...")
    SID = connect()
    HEADERS = {"SessionId": SID}
    print("Отримання списку авто...")
    r = requests.get(f"{API_URL}/getobjectslist", headers=HEADERS, timeout=30)
    OBJECTS = sorted(r.json().get("objects", []), key=lambda o: o["name"])
    print(f"  Авто: {len(OBJECTS)}")
    print("Пошук геозон «Гараж»...")
    GARAGE_ZONES = find_garage_zones(SID)
    print(f"  Геозони: {[z['name']+' ['+str(z['id'])+']' for z in GARAGE_ZONES]}")
    print("Кеш датчиків...")
    load_sensor_cache()
    print("Дані компанії та авто...")
    COMPANY  = load_company()
    VEH_INFO = load_veh_info()
    print(f"Готово → http://localhost:{PORT}\n")

# ── Sensor helpers ────────────────────────────────────────────────────────────
def find_odo_sensor(sensors):
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in ODO_KW):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return (f"s{sid_v}", s["name"].strip())
            if pid_v > 0: return (f"p{pid_v}", s["name"].strip())
    return None


def find_fuel_sensors(sensors):
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in FUEL_CMB) and not any(ex in lo for ex in FUEL_EXC):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return [(f"s{sid_v}", s["name"].strip())]
            if pid_v > 0: return [(f"p{pid_v}", s["name"].strip())]
    result = []
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in FUEL_TNK) and not any(ex in lo for ex in FUEL_EXC):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0:   result.append((f"s{sid_v}", s["name"].strip()))
            elif pid_v > 0: result.append((f"p{pid_v}", s["name"].strip()))
    return result


def query_sensor(oid, slist, dt_from, dt_to, take="first"):
    """Значення датчика в діапазоні UTC-datetime."""
    try:
        r = requests.get(f"{API_URL}/objdata", headers=HEADERS,
                         params={"oid": oid, "slist": slist, "compress": "true",
                                 "from": dt_from.strftime("%Y-%m-%d %H:%M:%S"),
                                 "to":   dt_to.strftime("%Y-%m-%d %H:%M:%S")},
                         timeout=30)
        if r.status_code != 200: return None
        data = r.json()
        if data.get("result") != "Ok": return None
        records = data.get("obj_data", {}).get("records", [])
        vals = [float(rec[1]) for rec in records
                if len(rec) > 1 and rec[1] is not None and str(rec[1]).strip()]
        if not vals: return None
        return vals[0] if take == "first" else vals[-1]
    except Exception:
        return None

# ── API call helpers ──────────────────────────────────────────────────────────
def parse_utc(s):
    if not s: return None
    return datetime.fromisoformat(s.replace("Z", ""))


def to_local(dt):
    return dt + timedelta(hours=UTC_OFFSET) if dt else None


def get_address(lat, lon):
    try:
        r = requests.get(f"{API_URL}/getaddress", headers=HEADERS,
                         params={"lat": lat, "lon": lon}, timeout=10)
        return r.text.strip().strip('"') or "—"
    except Exception:
        return "—"


def get_visits(oid, zone_ids, dt_from, dt_to):
    r = requests.get(f"{API_URL}/zonesvisits", headers=HEADERS,
                     params={"objects_ids": str(oid),
                             "zones_ids":   ",".join(map(str, zone_ids)),
                             "from":        dt_from,
                             "to":          dt_to,
                             "minDuration": 0},
                     timeout=30)
    return r.json().get("visits", [])


def get_fuelings(oid, dt_from, dt_to):
    """Повертає список {time_local, volume, address}."""
    try:
        r = requests.get(f"{API_URL}/fuelings", headers=HEADERS,
                         params={"oid":  oid,
                                 "from": dt_from.strftime("%Y-%m-%d %H:%M:%S"),
                                 "to":   dt_to.strftime("%Y-%m-%d %H:%M:%S")},
                         timeout=30)
        data = r.json()
        result = []
        for ev in data.get("fuelings", []):
            if ev.get("fuel_type") != "fueling":
                continue
            lat, lon = ev.get("lat"), ev.get("lon")
            addr = get_address(lat, lon) if lat and lon else "—"
            t_utc = parse_utc(ev.get("start_time", ""))
            t_loc = to_local(t_utc)
            result.append({
                "time_local": t_loc.strftime("%d.%m.%Y %H:%M") if t_loc else "—",
                "volume":     round(float(ev.get("volume", 0)), 1),
                "address":    addr,
            })
            time.sleep(0.05)
        return result
    except Exception as e:
        print(f"  /fuelings: {e}")
        return []


def get_objects_report(oid, dt_from, dt_to, params_str):
    try:
        r = requests.get(f"{API_URL}/getobjectsreport", headers=HEADERS,
                         params={"objuids":   str(oid),
                                 "date_from": dt_from.strftime("%Y-%m-%d %H:%M:%S"),
                                 "date_to":   dt_to.strftime("%Y-%m-%d %H:%M:%S"),
                                 "split":     "none",
                                 "param":     params_str},
                         timeout=30)
        if r.status_code != 200: return {}
        data = r.json()
        if not data or not isinstance(data, list): return {}
        periods = data[0].get("periods", [])
        if not periods: return {}
        return {p["name"]: p.get("value") for p in periods[0].get("prms", []) if "name" in p}
    except Exception as e:
        print(f"  getobjectsreport: {e}")
        return {}


def get_stops_list(oid, dt_from, dt_to, min_sec=3600):
    try:
        r = requests.get(f"{API_URL}/stops", headers=HEADERS,
                         params={"oid":  oid,
                                 "from": dt_from.strftime("%Y-%m-%d %H:%M:%S"),
                                 "to":   dt_to.strftime("%Y-%m-%d %H:%M:%S"),
                                 "time": min_sec},
                         timeout=30)
        if r.status_code != 200: return []
        data = r.json()
        if data.get("result") != "Ok": return []
        result = []
        for s in data.get("stops", []):
            if s.get("duration", 0) < min_sec:
                continue
            lat, lon = s.get("lat"), s.get("lon")
            addr = get_address(lat, lon) if lat and lon else "—"
            t_utc = parse_utc(s.get("stop_time", ""))
            t_loc = to_local(t_utc)
            dur   = s["duration"]
            d, h, m = dur // 86400, (dur % 86400) // 3600, (dur % 3600) // 60
            result.append({
                "start":   t_loc.strftime("%d.%m.%Y %H:%M") if t_loc else "—",
                "dur_str": (f"{d}д " if d else "") + f"{h:02d}:{m:02d}",
                "addr":    addr,
            })
        return result
    except Exception as e:
        print(f"  /stops: {e}")
        return []

# ── Build events from garage visits ──────────────────────────────────────────
def build_events(visits):
    """
    Перетворює список відвідувань гаражу на плоский список подій
    (EXIT / ENTRY), відсортований за часом.
    Поле 'short' = True якщо рейс між цим EXIT і наступним ENTRY < MIN_TRIP_MIN.
    """
    raw = []
    for v in visits:
        in_utc  = parse_utc(v.get("in_dt"))
        out_utc = parse_utc(v.get("out_dt")) if not v.get("not_Ended") else None
        if in_utc:
            raw.append({"type": "entry", "dt_utc": in_utc, "short": False})
        if out_utc:
            raw.append({"type": "exit",  "dt_utc": out_utc, "short": False})

    raw.sort(key=lambda e: e["dt_utc"])

    # Визначаємо «короткі» рейси
    for i, ev in enumerate(raw):
        if ev["type"] != "exit":
            continue
        next_entries = [e for e in raw[i+1:] if e["type"] == "entry"]
        if next_entries:
            gap_min = (next_entries[0]["dt_utc"] - ev["dt_utc"]).total_seconds() / 60
            ev["trip_min"] = round(gap_min)
            if gap_min < MIN_TRIP_MIN:
                ev["short"] = True
                next_entries[0]["short"] = True
        else:
            ev["trip_min"] = None   # виїхав, не повернувся

    for ev in raw:
        ev["dt_local"] = to_local(ev["dt_utc"])
        ev["iso_utc"]  = ev["dt_utc"].strftime("%Y-%m-%dT%H:%M:%S")
        ev["fmt"]      = ev["dt_local"].strftime("%d.%m.%Y %H:%M") if ev["dt_local"] else "—"
    return raw

# ── Formatting ────────────────────────────────────────────────────────────────
def fv(v, dec=1, unit=""):
    if v is None: return "—"
    try:
        s = f"{float(v):,.{dec}f}".replace(",", " ")
        return f"{s} {unit}".strip()
    except Exception:
        return str(v)


def trip_days(dt1, dt2):
    if not dt1 or not dt2: return "—"
    return str((dt2.date() - dt1.date()).days + 1)

# ── CSS ───────────────────────────────────────────────────────────────────────
STYLE = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#eef2f7;padding:24px}
.card{background:#fff;padding:26px 30px;border-radius:12px;
      box-shadow:0 4px 18px rgba(0,0,0,.1);max-width:600px;margin:0 auto 24px}
h2{text-align:center;margin-bottom:18px;color:#1e3a5f;font-size:19px}
h3{color:#1e3a5f;font-size:14px;margin-bottom:10px;
   border-bottom:2px solid #2563eb;padding-bottom:5px}
label{display:block;margin:10px 0 3px;font-weight:600;font-size:13px;color:#444}
select,input{width:100%;padding:9px 11px;border:1px solid #ccc;
             border-radius:6px;font-size:13px;background:#fafafa}
select:focus,input:focus{border-color:#2563eb;outline:none}
.row{display:flex;gap:10px}.row>div{flex:1}
.hint{font-size:11px;color:#888;margin-top:2px}
.btn{width:100%;margin-top:18px;padding:13px;border:none;border-radius:8px;
     font-size:15px;font-weight:700;cursor:pointer}
.btn-blue{background:#2563eb;color:#fff}.btn-blue:hover{background:#1d4ed8}
.btn-green{background:#16a34a;color:#fff}.btn-green:hover{background:#15803d}
.btn-green:disabled{background:#9ca3af;cursor:not-allowed}
.btn-gray{background:#6b7280;color:#fff}.btn-gray:hover{background:#4b5563}

/* events table */
.wrap{max-width:980px;margin:0 auto}
.ev-table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:18px}
.ev-table th{background:#f0f4fa;padding:8px 10px;text-align:left;
             border:1px solid #d0d7e3;white-space:nowrap;font-weight:600}
.ev-table td{padding:8px 10px;border:1px solid #d0d7e3;vertical-align:middle}
.ev-table tr.exit  td{background:#edfaf3}
.ev-table tr.entry td{background:#fff7ed}
.ev-table tr.short td{background:#f9fafb;color:#9ca3af}
.ev-table tr.exit:not(.short):hover  td{background:#c6f0d6;cursor:pointer}
.ev-table tr.entry:not(.short):hover td{background:#fed7aa;cursor:pointer}
.ev-table tr.sel-start td{background:#16a34a!important;color:#fff;font-weight:700}
.ev-table tr.sel-end   td{background:#dc2626!important;color:#fff;font-weight:700}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;
       font-size:11px;font-weight:700}
.b-exit {background:#16a34a;color:#fff}
.b-entry{background:#ea580c;color:#fff}
.b-short{background:#d1d5db;color:#6b7280}

/* summary box */
.sum-box{background:#f0f4fa;border-radius:8px;padding:14px 18px;margin-bottom:14px}
.sum-box table{width:100%;font-size:13px}
.sum-box th{text-align:left;width:180px;padding:3px 0;color:#555;font-weight:600}
.sum-box td{padding:3px 0;font-weight:700;color:#1e3a5f}

/* waybill print */
.wb{max-width:900px;margin:0 auto;background:#fff;padding:36px 40px;
    border-radius:12px;box-shadow:0 4px 18px rgba(0,0,0,.12);font-size:13px}
.wb-title{text-align:center;margin-bottom:4px}
.wb-title h1{font-size:20px;letter-spacing:1px}
.wb-title .sub{font-size:12px;color:#555;margin-top:2px}
.wb .section{margin-bottom:16px}
.wb .section h3{border-bottom:2px solid #2563eb;padding-bottom:5px;
                margin-bottom:8px;color:#1e3a5f;font-size:13px;letter-spacing:.3px}
.wb table{width:100%;border-collapse:collapse}
.wb th,.wb td{border:1px solid #c8d3e6;padding:6px 9px;text-align:left;vertical-align:top}
.wb th{background:#f0f4fa;font-weight:600;white-space:nowrap;width:200px}
.wb td.num{text-align:right;font-family:monospace}
.wb td.hi{font-weight:700;color:#1e3a5f}
.wb .noprint{margin-top:20px;display:flex;gap:10px}
.wb .noprint button,.wb .noprint a{flex:1;padding:11px;border-radius:8px;
  font-size:14px;font-weight:700;cursor:pointer;border:none;text-align:center;
  text-decoration:none;display:inline-block}
@media print{
  body{background:#fff;padding:0}
  .noprint,.noprint *{display:none!important}
  .wb{box-shadow:none;border-radius:0;padding:10px}
}
</style>"""

# ── Step 1: select vehicle + period ──────────────────────────────────────────
def form_html():
    opts = "".join(
        f"<option value='{o['id']}'>"
        f"{o['name']}"
        f"{(' — ' + VEH_INFO[o['id']]['driver']) if o['id'] in VEH_INFO else ''}"
        f"</option>"
        for o in OBJECTS
    )
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путевий лист</title>{STYLE}</head><body>
<div class="card">
  <h2>Путевий лист — вибір авто та періоду</h2>
  <form action="/trips" method="POST">
    <label>Автомобіль</label>
    <select name="oid">{opts}</select>

    <div class="row">
      <div>
        <label>Початок періоду</label>
        <input type="date" name="date_from" required>
      </div>
      <div>
        <label>Кінець періоду</label>
        <input type="date" name="date_to" required>
      </div>
    </div>
    <div class="hint" style="margin-top:6px">
      Вкажіть довільний діапазон — у межах нього оберіть рейс мишею
    </div>

    <button type="submit" class="btn btn-blue">Показати рейси →</button>
  </form>
</div></body></html>"""

# ── Step 2: interactive trip selection ────────────────────────────────────────
def trips_html(oid, vname, events, date_from_str, date_to_str):
    if not events:
        return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Рейси</title>{STYLE}</head><body>
<div class="wrap"><div class="card" style="max-width:700px">
  <h2>{vname}</h2>
  <p style="text-align:center;color:#888;padding:20px">
    За вказаний період подій у геозоні «Гараж» не знайдено.
  </p>
  <a href="/" style="display:block;text-align:center;color:#2563eb">← Назад</a>
</div></div></body></html>"""

    rows = ""
    for i, ev in enumerate(events):
        short_cls  = " short" if ev["short"] else ""
        type_cls   = ev["type"]
        badge_cls  = "b-short" if ev["short"] else ("b-exit" if ev["type"] == "exit" else "b-entry")
        badge_text = ("Виїзд ↑" if ev["type"] == "exit" else "В'їзд ↓")
        if ev["short"]: badge_text += " (< 30 хв)"

        trip_info = ""
        if ev["type"] == "exit" and not ev["short"] and ev.get("trip_min") is not None:
            h, m = divmod(ev["trip_min"], 60)
            trip_info = f"{h}г {m:02d}хв у рейсі"
        elif ev["type"] == "exit" and not ev["short"] and ev.get("trip_min") is None:
            trip_info = "не повернувся"

        on_click = "" if ev["short"] else f"selectEv(this,'{ev['type']}','{ev['iso_utc']}')"
        rows += (
            f'<tr class="{type_cls}{short_cls}" onclick="{on_click}" id="ev{i}">'
            f'<td>{i+1}</td>'
            f'<td><span class="badge {badge_cls}">{badge_text}</span></td>'
            f'<td><b>{ev["fmt"]}</b></td>'
            f'<td style="color:#888;font-size:12px">{trip_info}</td>'
            f'<td class="action" style="font-size:12px">—</td>'
            f'</tr>\n'
        )

    vinfo = VEH_INFO.get(oid, {})
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Рейси — {vname}</title>{STYLE}</head><body>
<div class="wrap">
  <div class="card" style="max-width:980px">
    <h2>Авто: {vname} &nbsp;|&nbsp; Період: {date_from_str} — {date_to_str}</h2>

    <p style="font-size:13px;color:#555;margin-bottom:12px">
      Клікніть <b style="color:#16a34a">зелений рядок (Виїзд)</b> — початок рейсу.
      Потім <b style="color:#ea580c">помаранчевий рядок (В'їзд)</b> — кінець рейсу.
      Рейси менше {MIN_TRIP_MIN} хв позначені сірим і не обираються.<br>
      Або введіть дати вручну у полях нижче (UTC+2).
    </p>

    <table class="ev-table">
      <thead>
        <tr><th>#</th><th>Подія</th><th>Дата / Час (UTC+2)</th>
            <th>Тривалість рейсу</th><th>Вибір</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <!-- Manual fallback -->
    <div class="row" style="margin-bottom:12px">
      <div>
        <label>Початок рейсу (вручну, UTC+2)</label>
        <input type="datetime-local" id="start_manual" oninput="onManual('start')">
      </div>
      <div>
        <label>Кінець рейсу (вручну, UTC+2)</label>
        <input type="datetime-local" id="end_manual" oninput="onManual('end')">
      </div>
    </div>

    <!-- Summary -->
    <div class="sum-box" id="sum-box" style="display:none">
      <h3 style="margin-bottom:8px">Вибраний рейс</h3>
      <table>
        <tr><th>Виїзд з гаражу</th><td id="s-start">—</td></tr>
        <tr><th>В'їзд у гараж</th> <td id="s-end">—</td></tr>
        <tr><th>Тривалість</th>    <td id="s-dur">—</td></tr>
        <tr><th>Дні відрядження</th><td id="s-days" style="color:#dc2626;font-size:15px">—</td></tr>
      </table>
    </div>

    <!-- Cargo + generate form -->
    <form action="/waybill" method="POST">
      <input type="hidden" name="oid"        value="{oid}">
      <input type="hidden" name="date_from"  value="{date_from_str}">
      <input type="hidden" name="date_to"    value="{date_to_str}">
      <input type="hidden" name="start_utc"  id="start_utc">
      <input type="hidden" name="end_utc"    id="end_utc">

      <div class="row">
        <div>
          <label>№ Заявки</label>
          <input name="order_num" placeholder="необов'язково">
        </div>
        <div>
          <label>Вага вантажу, т</label>
          <input name="cargo_weight" type="number" step="0.01" min="0" placeholder="0.00">
        </div>
      </div>
      <label>Найменування вантажу</label>
      <input name="cargo_name" placeholder="Назва вантажу">

      <button type="submit" class="btn btn-green" id="gen-btn" disabled>
        Сформувати путевий лист
      </button>
    </form>

    <a href="/" style="display:block;text-align:center;margin-top:12px;
       color:#6b7280;font-size:13px">← Назад до вибору авто</a>
  </div>
</div>

<script>
const OFF = {UTC_OFFSET};  // UTC offset hours

function isoUtcToLocal(iso) {{
  // iso = "2026-04-01T06:00:00" (UTC)
  const d = new Date(iso + 'Z');
  const loc = new Date(d.getTime() + OFF * 3600000);
  return loc.toISOString().slice(0, 16);  // for datetime-local input
}}
function localToUtcIso(local) {{
  // local = "2026-04-01T08:00" (UTC+2)
  const d = new Date(local + ':00');  // JS parses as LOCAL, but we want to treat as UTC+2
  // We need: UTC = local - OFF hours
  const utc = new Date(d.getTime() - OFF * 3600000);
  return utc.toISOString().slice(0, 19);  // "2026-04-01T06:00:00"
}}
function fmtLocal(iso) {{
  const d = new Date(iso + 'Z');
  const loc = new Date(d.getTime() + OFF * 3600000);
  return loc.toLocaleDateString('uk-UA', {{day:'2-digit',month:'2-digit',year:'numeric'}})
    + ' ' + loc.toTimeString().slice(0,5);
}}
function durStr(ms) {{
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return (d ? d + 'д ' : '') + String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0');
}}
function tripDays(iso1, iso2) {{
  const d1 = new Date(iso1 + 'Z');
  const d2 = new Date(iso2 + 'Z');
  const loc1 = new Date(d1.getTime() + OFF * 3600000);
  const loc2 = new Date(d2.getTime() + OFF * 3600000);
  const date1 = new Date(loc1.toDateString());
  const date2 = new Date(loc2.toDateString());
  return Math.floor((date2 - date1) / 86400000) + 1;
}}

let selStartRow = null, selEndRow = null;

function selectEv(tr, type, isoUtc) {{
  if (type === 'exit') {{
    if (selStartRow) selStartRow.classList.remove('sel-start');
    selStartRow = tr;
    tr.classList.add('sel-start');
    tr.querySelector('.action').textContent = '▶ Початок';
    document.getElementById('start_utc').value = isoUtc;
    document.getElementById('start_manual').value = isoUtcToLocal(isoUtc);
  }} else {{
    if (selEndRow) selEndRow.classList.remove('sel-end');
    selEndRow = tr;
    tr.classList.add('sel-end');
    tr.querySelector('.action').textContent = '◀ Кінець';
    document.getElementById('end_utc').value = isoUtc;
    document.getElementById('end_manual').value = isoUtcToLocal(isoUtc);
  }}
  updateSummary();
}}

function onManual(which) {{
  const v = document.getElementById(which + '_manual').value;
  if (!v) return;
  const utc = localToUtcIso(v);
  document.getElementById(which + '_utc').value = utc;
  updateSummary();
}}

function updateSummary() {{
  const s = document.getElementById('start_utc').value;
  const e = document.getElementById('end_utc').value;
  if (!s || !e) return;
  const d1 = new Date(s + 'Z'), d2 = new Date(e + 'Z');
  if (d2 <= d1) return;
  document.getElementById('s-start').textContent  = fmtLocal(s);
  document.getElementById('s-end').textContent    = fmtLocal(e);
  document.getElementById('s-dur').textContent    = durStr(d2 - d1);
  document.getElementById('s-days').textContent   = tripDays(s, e) + ' дн.';
  document.getElementById('sum-box').style.display = 'block';
  const btn = document.getElementById('gen-btn');
  btn.disabled = false;
}}
</script>
</body></html>"""

# ── Step 3: waybill generation ────────────────────────────────────────────────
def waybill_html(oid, start_utc_str, end_utc_str, cargo):
    start_utc = datetime.fromisoformat(start_utc_str)
    end_utc   = datetime.fromisoformat(end_utc_str)
    start_loc = to_local(start_utc)
    end_loc   = to_local(end_utc)

    sensors      = VEH_CACHE.get(str(oid), {}).get("sensors", [])
    vinfo        = VEH_INFO.get(oid, {})
    obj_name     = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))
    today_str    = datetime.now().strftime("%d.%m.%Y")
    days_on_road = trip_days(start_loc, end_loc)

    # ── 1. getobjectsreport: адреси, CAN пробіг ─────────────────────────────
    print("  getobjectsreport...")
    rpt       = get_objects_report(oid, start_utc, end_utc,
                                   "start_address;stop_address;can_dist;fuelings")
    addr_start = rpt.get("start_address") or "—"
    addr_end   = rpt.get("stop_address")  or "—"
    can_dist   = rpt.get("can_dist")

    # ── 2. Одометр на початок і кінець рейсу ────────────────────────────────
    print("  Одометр...")
    odo_sensor = find_odo_sensor(sensors)
    if odo_sensor:
        odo_start = query_sensor(oid, odo_sensor[0],
                                 start_utc - timedelta(minutes=30),
                                 start_utc + timedelta(hours=2), "first")
        odo_end   = query_sensor(oid, odo_sensor[0],
                                 end_utc - timedelta(hours=2),
                                 end_utc + timedelta(minutes=30), "last")
        odo_diff  = round(odo_end - odo_start, 1) if (odo_start and odo_end) else None
    else:
        odo_start = odo_end = odo_diff = None

    # ── 3. Паливо на початок і кінець ────────────────────────────────────────
    print("  Паливо (баки)...")
    fuel_sensors = find_fuel_sensors(sensors)
    fuel_start_rows, fuel_end_rows = [], []
    for slist, fname in fuel_sensors:
        fs = query_sensor(oid, slist,
                          start_utc - timedelta(minutes=30),
                          start_utc + timedelta(hours=2), "first")
        fe = query_sensor(oid, slist,
                          end_utc - timedelta(hours=2),
                          end_utc + timedelta(minutes=30), "last")
        fuel_start_rows.append((fname, fs))
        fuel_end_rows.append((fname, fe))
    total_fs = sum(v for _, v in fuel_start_rows if v) or None
    total_fe = sum(v for _, v in fuel_end_rows   if v) or None

    # ── 4. Заправки з адресами ───────────────────────────────────────────────
    print("  Заправки...")
    fuelings     = get_fuelings(oid, start_utc, end_utc)
    total_fueled = round(sum(f["volume"] for f in fuelings), 1) if fuelings else None

    # ── 5. Стоянки > 1 год → коментарі ──────────────────────────────────────
    print("  Стоянки (> 1 год)...")
    stops = get_stops_list(oid, start_utc, end_utc, min_sec=3600)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def fuel_td(rows, total):
        if not rows: return "<td>—</td>"
        parts = " / ".join(
            f"{n}: <b>{fv(v, 1)} л</b>" for n, v in rows if v is not None
        )
        if not parts: return "<td>—</td>"
        if len(rows) > 1 and total:
            parts += f" | Разом: <b>{fv(total, 1)} л</b>"
        return f"<td>{parts}</td>"

    # Fueling rows
    if fuelings:
        fuel_rows_html = "".join(
            f"<tr><td>{i+1}</td><td>{f['time_local']}</td>"
            f"<td class='num'><b>{f['volume']} л</b></td>"
            f"<td>{f['address']}</td></tr>"
            for i, f in enumerate(fuelings)
        )
        fuel_total_row = (
            f"<tr><th colspan='2' style='text-align:right'>Всього заправлено:</th>"
            f"<td class='num hi'>{fv(total_fueled, 1)} л</td><td></td></tr>"
        )
    else:
        fuel_rows_html = "<tr><td colspan='4' style='text-align:center;color:#888'>Заправок не знайдено</td></tr>"
        fuel_total_row = ""

    # Stops → comments
    if stops:
        stops_list = "; ".join(
            f"{s['start']} ({s['dur_str']}) — {s['addr']}"
            for s in stops
        )
    else:
        stops_list = "Стоянок більше 1 год не виявлено"

    comments = stops_list
    if cargo.get("cargo_name"):
        comments = f"Вантаж: {cargo['cargo_name']}" + \
                   (f", {cargo['cargo_weight']} т" if cargo.get("cargo_weight") else "") + \
                   f". {comments}"
    if cargo.get("order_num"):
        comments = f"Заявка № {cargo['order_num']}. {comments}"

    start_fmt = start_loc.strftime("%d.%m.%Y %H:%M") if start_loc else "—"
    end_fmt   = end_loc.strftime("%d.%m.%Y %H:%M")   if end_loc   else "—"
    start_date = start_loc.strftime("%d.%m.%Y") if start_loc else "—"
    end_date   = end_loc.strftime("%d.%m.%Y")   if end_loc   else "—"

    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путевий лист — {obj_name}</title>{STYLE}</head><body>
<div class="wb">

  <div class="wb-title section">
    <h1>ПУТЕВИЙ ЛИСТ</h1>
    <div class="sub">
      {COMPANY.get('name','')} &nbsp;|&nbsp; {COMPANY.get('place','')}
      &nbsp;|&nbsp; Дата складання: {today_str}
    </div>
  </div>

  <div class="section">
    <h3>Загальні відомості</h3>
    <table>
      <tr><th>Автомобіль</th>
          <td><b>{obj_name}</b>
              {(' / ' + vinfo.get('make','')) if vinfo.get('make','') not in ('—','') else ''}
          </td></tr>
      <tr><th>Держ. номер</th>    <td>{vinfo.get('plate','—')}</td></tr>
      <tr><th>Причіп</th>         <td>{vinfo.get('trailer','—')}</td></tr>
      <tr><th>Водій</th>          <td><b>{vinfo.get('driver','—')}</b></td></tr>
      <tr><th>Підприємство</th>   <td>{COMPANY.get('name','—')}</td></tr>
      <tr><th>Місце складання</th><td>{COMPANY.get('place','—')}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Рейс</h3>
    <table>
      <tr><th>Виїзд</th>
          <td><b>{start_fmt}</b> ({start_date})</td></tr>
      <tr><th>Повернення</th>
          <td><b>{end_fmt}</b> ({end_date})</td></tr>
      <tr><th>Днів у відрядженні</th>
          <td class="hi" style="font-size:16px">{days_on_road}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Маршрут</h3>
    <table>
      <tr><th>Адреса виїзду</th> <td>{addr_start}</td></tr>
      <tr><th>Адреса прибуття</th><td>{addr_end}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Пробіг</h3>
    <table>
      <tr><th>Одометр на початок рейсу</th>
          <td class="num">{fv(odo_start, 1)} км</td></tr>
      <tr><th>Одометр на кінець рейсу</th>
          <td class="num">{fv(odo_end, 1)} км</td></tr>
      <tr><th>Пробіг за рейс (одометр)</th>
          <td class="num hi">{fv(odo_diff, 1)} км</td></tr>
      <tr><th>Пробіг за рейс (CAN)</th>
          <td class="num">{fv(can_dist, 1)} км</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Паливо</h3>
    <table>
      <tr><th>Рівень баку на початок рейсу</th>
          {fuel_td(fuel_start_rows, total_fs)}</tr>
      <tr><th>Рівень баку на кінець рейсу</th>
          {fuel_td(fuel_end_rows, total_fe)}</tr>
    </table>
  </div>

  <div class="section">
    <h3>Заправки за рейс</h3>
    <table>
      <thead>
        <tr><th style="width:40px">#</th><th>Дата / Час</th>
            <th style="width:110px">Обсяг</th><th>Адреса</th></tr>
      </thead>
      <tbody>{fuel_rows_html}</tbody>
      <tfoot>{fuel_total_row}</tfoot>
    </table>
  </div>

  <div class="section">
    <h3>Коментарі (стоянки &gt; 1 год; вантаж; заявка)</h3>
    <table>
      <tr><td style="padding:10px;line-height:1.6">{comments}</td></tr>
    </table>
  </div>

  <div class="noprint">
    <button class="btn-green" style="border-radius:8px;font-weight:700;
            padding:11px;cursor:pointer;border:none"
            onclick="window.print()">Друк / PDF</button>
    <a href="/trips" onclick="history.back();return false"
       class="btn-gray" style="border-radius:8px;font-weight:700;padding:11px">
       ← Змінити дати</a>
    <a href="/" class="btn-gray"
       style="border-radius:8px;font-weight:700;padding:11px">
       ⌂ Нове авто</a>
  </div>
</div></body></html>"""

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_html(self, body, code=200):
        enc = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(enc)))
        self.end_headers()
        self.wfile.write(enc)

    def do_GET(self):
        self.send_html(form_html())

    def do_POST(self):
        raw  = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        body = parse_qs(raw)

        def g(key, default=""):
            return body.get(key, [default])[0].strip()

        if self.path == "/trips":
            oid       = int(g("oid"))
            date_from = g("date_from")
            date_to   = g("date_to")
            vname     = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))

            api_from = f"{date_from} 00:00:00"
            api_to   = f"{date_to} 23:59:59"
            print(f"\nРейси: {vname}  {api_from} — {api_to}")

            zone_ids = [z["id"] for z in GARAGE_ZONES]
            visits   = get_visits(oid, zone_ids, api_from, api_to)
            events   = build_events(visits)
            print(f"  Подій: {len(events)}")
            self.send_html(trips_html(oid, vname, events, date_from, date_to))

        elif self.path == "/waybill":
            oid           = int(g("oid"))
            start_utc_str = g("start_utc")
            end_utc_str   = g("end_utc")

            if not start_utc_str or not end_utc_str:
                self.send_html(
                    "<h3 style='font-family:sans-serif;padding:30px;color:#dc2626'>"
                    "Не вибрано початок або кінець рейсу. "
                    "<a href='javascript:history.back()'>← Назад</a></h3>")
                return

            cargo = {
                "order_num":    g("order_num"),
                "cargo_name":   g("cargo_name"),
                "cargo_weight": g("cargo_weight"),
            }
            vname = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))
            print(f"\nПутевий лист: {vname}  {start_utc_str} → {end_utc_str}")
            try:
                html = waybill_html(oid, start_utc_str, end_utc_str, cargo)
                self.send_html(html)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print(tb)
                self.send_html(
                    f"<h3 style='font-family:sans-serif;padding:20px;color:#dc2626'>"
                    f"Помилка: {e}</h3><pre style='padding:20px'>{tb}</pre>"
                    f"<a href='javascript:history.back()' style='padding:20px;display:block'>"
                    f"← Назад</a>")
        else:
            self.send_html("<h3>404</h3>", 404)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init()
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
