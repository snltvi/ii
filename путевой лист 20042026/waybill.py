#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевой лист — веб-интерфейс
=============================================================================
Запуск: python waybill.py  →  открывается браузер на http://localhost:8080

Используемые методы API (https://gps.mobiteam.com.ua/api/integration/v1):
  GET /connect            — авторизация (login/password → SessionId)
  GET /getobjectslist     — список всех ТС
  GET /objsensorslist     — список датчиков ТС (кешируется в sensors_cache.json)
  GET /objdata            — значения датчиков за период (уровень топлива)
  GET /getobjectsreport   — сводной отчёт за период:
                              start_address  — адрес начала рейса
                              stop_address   — адрес окончания рейса
                              can_dist       — пробег по CAN (км), показания
                                              бортового компьютера, не зависит от GPS
                              fuelings       — объём заправок за период (л)
  GET /track              — GPS-трек (используется для определения
                              времени выезда и возврата)
  GET /stops              — список стоянок ТС за период с координатами
                              и длительностью; фильтрация по минимальному
                              времени стоянки задаётся пользователем
                              (по умолчанию 1440 мин = 24 часа)
  GET /getaddress         — обратное геокодирование (lat/lon → адрес)

Справочник водитель↔авто:
  Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx
  Колонки: [1]=ФИО, [2]=ID объекта

Форма ввода (браузер):
  • Выбор ТС — автоматически подставляет водителя из справочника
  • Даты рейса (начало / конец)
  • Минимальное время стоянки (мин), по умолчанию 1440 мин (24 ч)
  • № заявки, Название груза, Вес груза (т)

Путевой лист содержит:
  • Общие сведения (ТС, водитель, период)
  • Груз и заявка
  • Маршрут (адрес и время выезда / возврата)
  • Пробег по CAN за рейс
  • Топливо (уровень баков при выезде и возврате, заправлено за рейс)
  • Стоянки дольше заданного порога (адрес, начало, конец, длительность)
=============================================================================
"""

import requests, sys, json, os, webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGIN    = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
PORT     = 8080

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "sensors_cache.json")

# Справочник водитель → авто (ищем в корне проекта)
DRIVERS_EXCEL = os.path.join(os.path.dirname(SCRIPT_DIR),
                             "Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx")

STOP_MIN = 60

FUEL_COMBINED = ["топливо"]
FUEL_TANK     = ["бак"]
FUEL_EXCLUDE  = ["расход", "температур", "°t", "уровень", "%", "can уровень"]

ODO_KEYWORDS  = ["датчик накопленного пробега", "can абсолютный пробег", "абсолютный пробег"]

# ── Auth ──────────────────────────────────────────────────────────────────────
def connect():
    r = requests.get(f"{BASE_URL}/connect",
        params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
        timeout=30)
    sid = r.headers.get("sessionid") or r.headers.get("SessionId")
    if not sid:
        print("Помилка авторизації"); sys.exit(1)
    return sid

# ── Driver directory ──────────────────────────────────────────────────────────
def load_drivers():
    """Возвращает dict {oid_int: "ФИО"} из Excel-справочника."""
    if not os.path.exists(DRIVERS_EXCEL):
        print(f"  Справочник не знайдено: {DRIVERS_EXCEL}")
        return {}
    try:
        import pandas as pd
        df = pd.read_excel(DRIVERS_EXCEL)
        # Колонки по позиции: 1=ФИО, 2=ID объекта
        result = {}
        for _, row in df.iterrows():
            oid_v = row.iloc[2]
            fio   = str(row.iloc[1]).strip()
            if oid_v and fio and fio not in ("nan", "—", ""):
                try:
                    result[int(float(oid_v))] = fio
                except (ValueError, TypeError):
                    pass
        print(f"  Водіїв із справочника: {len(result)}")
        return result
    except Exception as e:
        print(f"  Помилка читання справочника: {e}")
        return {}

# ── Sensor cache ──────────────────────────────────────────────────────────────
def load_sensor_cache(headers, objects):
    current_ids = {str(o["id"]) for o in objects}
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        if not (current_ids - set(cache.get("vehicles", {}).keys())):
            return cache["vehicles"]
    vehicles_cache = cache.get("vehicles", {})
    for obj in objects:
        oid_s = str(obj["id"])
        r = requests.get(f"{BASE_URL}/objsensorslist",
                         headers=headers, params={"oid": obj["id"]}, timeout=30)
        sensors = []
        if r.status_code == 200 and r.json().get("result") == "Ok":
            sensors = r.json().get("obj_sensors", [])
        vehicles_cache[oid_s] = {"name": obj["name"], "sensors": sensors}
    cache = {"updated": datetime.now().isoformat(timespec="seconds"), "vehicles": vehicles_cache}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return vehicles_cache

def find_odo_sensor(sensors):
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in ODO_KEYWORDS):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return (f"s{sid_v}", s["name"].strip())
            if pid_v > 0: return (f"p{pid_v}", s["name"].strip())
    return None

def find_fuel_sensors(sensors):
    """Приоритет: единый 'Топливо' > Бак1+Бак2. Исключает температуру, расход, уровень%."""
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in FUEL_COMBINED) and not any(ex in lo for ex in FUEL_EXCLUDE):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0: return [(f"s{sid_v}", s["name"].strip())]
            if pid_v > 0: return [(f"p{pid_v}", s["name"].strip())]
    result = []
    for s in sensors:
        lo = s.get("name", "").lower().strip()
        if any(kw in lo for kw in FUEL_TANK) and not any(ex in lo for ex in FUEL_EXCLUDE):
            sid_v, pid_v = s.get("sid", 0), s.get("pid", 0)
            if sid_v > 0:   result.append((f"s{sid_v}", s["name"].strip()))
            elif pid_v > 0: result.append((f"p{pid_v}", s["name"].strip()))
    return result

# ── API helpers ───────────────────────────────────────────────────────────────
def query_objdata(headers, oid, slist, date_str, take="first"):
    try:
        r = requests.get(f"{BASE_URL}/objdata", headers=headers,
                         params={"oid": oid, "slist": slist, "compress": "true",
                                 "from": f"{date_str} 00:00:00", "to": f"{date_str} 23:59:59"},
                         timeout=30)
        if r.status_code != 200: return None
        data = r.json()
        if data.get("result") != "Ok": return None
        records = data.get("obj_data", {}).get("records", [])
        vals = [float(rec[1]) for rec in records
                if len(rec) > 1 and rec[1] is not None and str(rec[1]).strip()]
        if not vals: return None
        return vals[0] if take == "first" else vals[-1]
    except:
        return None

def get_track(headers, oid, dt_from, dt_to):
    try:
        r = requests.get(f"{BASE_URL}/track", headers=headers,
                         params={"oid": oid, "from": dt_from, "to": dt_to}, timeout=60)
        if r.status_code != 200: return []
        return r.json().get("track", [])
    except:
        return []

def get_address(headers, lat, lon):
    try:
        r = requests.get(f"{BASE_URL}/getaddress", headers=headers,
                         params={"lat": lat, "lon": lon}, timeout=15)
        return r.text.strip().strip('"') or "—"
    except:
        return "—"

def get_objects_report(headers, oid, dt_from, dt_to, params_str):
    """
    Один запит getobjectsreport, повертає dict {param_name: value}.
    params_str: наприклад "start_address;stop_address;can_dist;fuelings"
    """
    try:
        r = requests.get(f"{BASE_URL}/getobjectsreport", headers=headers,
                         params={"objuids": str(oid), "date_from": dt_from,
                                 "date_to": dt_to, "split": "none", "param": params_str},
                         timeout=30)
        if r.status_code != 200: return {}
        data = r.json()
        if not data or not isinstance(data, list): return {}
        periods = data[0].get("periods", [])
        if not periods: return {}
        prms = periods[0].get("prms", [])
        return {p["name"]: p.get("value") for p in prms if "name" in p}
    except Exception as e:
        print(f"    getobjectsreport помилка: {e}")
        return {}

def parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try: return datetime.strptime(s, fmt)
        except: pass
    return None

# ── Stops via /stops API ──────────────────────────────────────────────────────
def find_stops(headers, oid, dt_from, dt_to, min_minutes=1440):
    """
    Запрашивает стоянки через GET /stops.
    min_minutes — минимальная длительность стоянки в минутах (по умолчанию 1440 = 24 ч).
    API принимает фильтр в секундах (параметр time).
    Возвращает список dict: start, end, dur (мин), dur_str, addr.
    """
    min_seconds = min_minutes * 60
    # Запрашиваем у API стоянки >= 1 час, финальный фильтр делаем локально
    api_filter = min(min_seconds, 3600)
    try:
        r = requests.get(f"{BASE_URL}/stops", headers=headers,
                         params={"oid": oid, "from": dt_from, "to": dt_to,
                                 "time": api_filter},
                         timeout=30)
        if r.status_code != 200: return []
        data = r.json()
        if data.get("result") != "Ok": return []
        raw_stops = data.get("stops", [])
    except Exception as e:
        print(f"    /stops помилка: {e}")
        return []

    result = []
    for s in raw_stops:
        dur_sec = s.get("duration", 0)
        if dur_sec < min_seconds:
            continue

        lat = s.get("lat")
        lon = s.get("lon")
        addr = get_address(headers, lat, lon) if lat and lon else "—"

        stop_dt  = parse_dt(s.get("stop_time", ""))
        end_sec  = (stop_dt.timestamp() + dur_sec) if stop_dt else None
        end_str  = datetime.fromtimestamp(end_sec).strftime("%d.%m.%Y %H:%M") if end_sec else "—"

        dur_min  = dur_sec // 60
        d, h, m  = dur_min // 1440, (dur_min % 1440) // 60, dur_min % 60
        dur_str  = (f"{d}д " if d else "") + f"{h:02d}:{m:02d}"

        result.append({
            "start":   stop_dt.strftime("%d.%m.%Y %H:%M") if stop_dt else "—",
            "end":     end_str,
            "dur":     dur_min,
            "dur_str": dur_str,
            "addr":    addr,
        })
    return result

# ── Global state ──────────────────────────────────────────────────────────────
SID      = None
HEADERS  = {}
OBJECTS  = []
VEH_CACHE = {}
DRIVERS  = {}   # oid_int → "ФИО"

def init():
    global SID, HEADERS, OBJECTS, VEH_CACHE, DRIVERS
    print("Підключення до API...")
    SID = connect()
    HEADERS = {"SessionId": SID}
    print("Отримання списку авто...")
    resp = requests.get(f"{BASE_URL}/getobjectslist", headers=HEADERS, timeout=30)
    OBJECTS = sorted(resp.json().get("objects", []), key=lambda o: o["name"])
    print(f"  Авто: {len(OBJECTS)}")
    print("Завантаження кешу датчиків...")
    VEH_CACHE = load_sensor_cache(HEADERS, OBJECTS)
    print("Завантаження справочника водіїв...")
    DRIVERS = load_drivers()
    print(f"Готово → http://localhost:{PORT}\n")

# ── Formatting ────────────────────────────────────────────────────────────────
def fv(v, dec=1, unit=""):
    if v is None: return "—"
    try:
        s = f"{float(v):,.{dec}f}".replace(",", " ")
        return f"{s} {unit}".strip() if unit else s
    except:
        return str(v)

# ── CSS ───────────────────────────────────────────────────────────────────────
STYLE = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#eef2f7;padding:30px}
.card{background:#fff;padding:28px 32px;border-radius:12px;
      box-shadow:0 4px 18px rgba(0,0,0,.1);max-width:580px;margin:0 auto}
h2{text-align:center;margin-bottom:20px;color:#2c3e50}
label{display:block;margin:12px 0 4px;font-weight:600;font-size:14px;color:#555}
select,input{width:100%;padding:10px 12px;border:1px solid #ccc;border-radius:6px;
             font-size:14px;background:#fafafa}
select:focus,input:focus{border-color:#4a90d9;outline:none}
.row{display:flex;gap:12px}.row>div{flex:1}
.hint{font-size:12px;color:#888;margin-top:3px}
button[type=submit]{width:100%;margin-top:22px;padding:14px;background:#2563eb;
  color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer}
button[type=submit]:hover{background:#1d4ed8}
/* waybill */
.wb{max-width:840px;margin:0 auto;background:#fff;padding:40px;
    border-radius:12px;box-shadow:0 4px 18px rgba(0,0,0,.12);font-size:14px}
.wb h1{text-align:center;font-size:22px;margin-bottom:6px}
.wb .sub{text-align:center;color:#666;margin-bottom:24px}
.section{margin-bottom:18px}
.section h3{border-bottom:2px solid #2563eb;padding-bottom:6px;
            margin-bottom:10px;color:#1e3a5f;font-size:15px}
table{width:100%;border-collapse:collapse}
th,td{border:1px solid #d0d7e3;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f0f4fa;font-weight:600;white-space:nowrap}
td.num{text-align:right;font-family:monospace}
td.hi{font-weight:700;color:#1e3a5f}
.noprint{margin-top:20px;display:flex;gap:12px}
.noprint button{flex:1;padding:12px;border-radius:8px;font-size:15px;
                font-weight:600;cursor:pointer;border:none}
.btn-print{background:#16a34a;color:#fff}
.btn-back{background:#6b7280;color:#fff}
@media print{.noprint{display:none}}
</style>"""

# ── Form ──────────────────────────────────────────────────────────────────────
def form_html():
    opts = "".join(
        f"<option value='{o['id']}'>{o['name']}"
        f"{(' — ' + DRIVERS[o['id']]) if o['id'] in DRIVERS else ''}</option>"
        for o in OBJECTS
    )
    # JSON-карта oid → ФИО для JS автозаполнения
    drivers_js = json.dumps({str(o["id"]): DRIVERS.get(o["id"], "") for o in OBJECTS},
                            ensure_ascii=False)
    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путевой лист</title>{STYLE}</head><body>
<div class="card">
  <h2>Путевой лист</h2>
  <form action="/generate" method="POST">
    <label>Автомобиль</label>
    <select name="oid" id="oid_sel">{opts}</select>

    <label>Водитель</label>
    <input name="driver" id="driver_inp" placeholder="Фамилия И.О." required>
    <div class="hint">Заполняется автоматически из справочника</div>

    <div class="row">
      <div><label>Дата выезда</label>
           <input type="date" name="date_start" required></div>
      <div><label>Дата возврата</label>
           <input type="date" name="date_end" required></div>
    </div>

    <label>Минимальное время стоянки (мин)</label>
    <input name="stop_min" type="number" min="1" value="1440">
    <div class="hint">По умолчанию 1440 мин = 24 часа. Введите меньше чтобы видеть короткие стоянки.</div>

    <label>№ Заявки</label>
    <input name="order_num" placeholder="Номер заявки (необязательно)">

    <label>Название груза</label>
    <input name="cargo_name" placeholder="Наименование груза">

    <label>Вес груза, т</label>
    <input name="cargo_weight" type="number" step="0.01" min="0" placeholder="0.00">

    <button type="submit">Сформировать путевой лист</button>
  </form>
</div>
<script>
const DRV = {drivers_js};
const sel = document.getElementById('oid_sel');
const inp = document.getElementById('driver_inp');
function fillDriver(){{
  const d = DRV[sel.value] || '';
  inp.value = d;
}}
sel.addEventListener('change', fillDriver);
fillDriver();
</script>
</body></html>"""

# ── Waybill ───────────────────────────────────────────────────────────────────
def waybill_html(oid, vehicle_name, driver, date_start, date_end,
                 order_num, cargo_name, cargo_weight, stop_min=1440):
    ds, de = date_start, date_end
    dt_from = f"{ds} 00:00:00"
    dt_to   = f"{de} 23:59:59"
    ds_label = datetime.strptime(ds, "%Y-%m-%d").strftime("%d.%m.%Y")
    de_label = datetime.strptime(de, "%Y-%m-%d").strftime("%d.%m.%Y")
    period_label = ds_label if ds == de else f"{ds_label} — {de_label}"

    # ── getobjectsreport: адреса + пробег CAN + заправки ─────────────────────
    print(f"  getobjectsreport...")
    rpt = get_objects_report(HEADERS, oid, dt_from, dt_to,
                             "start_address;stop_address;can_dist;fuelings")
    addr_start  = rpt.get("start_address") or "—"
    addr_end    = rpt.get("stop_address")  or "—"
    can_dist    = rpt.get("can_dist")       # пробег по CAN за период (км)
    fuelings    = rpt.get("fuelings")       # объем заправок (л)

    # ── Время выезда/возврата — из трека ─────────────────────────────────────
    print(f"  Трек (час виїзду/повернення)...")
    tr_s = get_track(HEADERS, oid, f"{ds} 00:00:00", f"{ds} 23:59:59")
    tr_e = get_track(HEADERS, oid, f"{de} 00:00:00", f"{de} 23:59:59") if de != ds else tr_s

    def edge_point(track, last=False):
        pts = [p for p in track if p.get("lat") and p.get("lon")]
        return (pts[-1] if last else pts[0]) if pts else None

    fp = edge_point(tr_s, last=False)
    lp = edge_point(tr_e, last=True)
    time_start = parse_dt(fp["dt"]).strftime("%d.%m.%Y %H:%M") if fp else ds_label
    time_end   = parse_dt(lp["dt"]).strftime("%d.%m.%Y %H:%M") if lp else de_label

    # ── Одометр на начало/конец рейса ────────────────────────────────────────
    print(f"  Одометр...")
    sensors    = VEH_CACHE.get(str(oid), {}).get("sensors", [])
    odo_sensor = find_odo_sensor(sensors)
    if odo_sensor:
        odo_start = query_objdata(HEADERS, oid, odo_sensor[0], ds, "first")
        odo_end   = query_objdata(HEADERS, oid, odo_sensor[0], de, "last")
    else:
        odo_start = odo_end = None

    # ── Топливо — уровень баков на начало/конец ───────────────────────────────
    print(f"  Паливо (рівень баків)...")
    fuel_pairs = find_fuel_sensors(sensors)
    fuel_start_rows, fuel_end_rows = [], []
    for slist, fname in fuel_pairs:
        fuel_start_rows.append((fname, query_objdata(HEADERS, oid, slist, ds, "first")))
        fuel_end_rows.append((fname,   query_objdata(HEADERS, oid, slist, de, "last")))
    total_fs = sum(v for _, v in fuel_start_rows if v) or None
    total_fe = sum(v for _, v in fuel_end_rows   if v) or None

    # ── Стоянки (/stops API) ──────────────────────────────────────────────────
    print(f"  Стоянки >= {stop_min} хв (API /stops)...")
    stops = find_stops(HEADERS, oid, dt_from, dt_to, stop_min)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def fuel_td(rows, total):
        if not rows: return "<td>—</td>"
        lines = "".join(f"{n}: <b>{fv(v, 1)} л</b><br>" for n, v in rows)
        if len(rows) > 1 and total:
            lines += f"<hr style='margin:4px 0'>Итого: <b>{fv(total, 1)} л</b>"
        return f"<td>{lines}</td>"

    stops_rows = "".join(
        f"<tr><td>{s['start']}</td><td>{s['end']}</td>"
        f"<td class='num'>{s['dur_str']}</td><td>{s['addr']}</td></tr>"
        for s in stops
    ) or (f"<tr><td colspan='4' style='text-align:center;color:#888'>"
          f"Стоянок &gt;= {stop_min} мин не обнаружено</td></tr>")

    cargo_block = ""
    if order_num or cargo_name or cargo_weight:
        cargo_block = f"""
  <div class="section">
    <h3>Груз / Заявка</h3>
    <table>
      {"<tr><th width='200'>№ Заявки</th><td>" + order_num + "</td></tr>" if order_num else ""}
      {"<tr><th>Название груза</th><td>" + cargo_name + "</td></tr>" if cargo_name else ""}
      {"<tr><th>Вес груза</th><td class='num'>" + fv(cargo_weight, 2) + " т</td></tr>" if cargo_weight else ""}
    </table>
  </div>"""

    return f"""<!doctype html><html><head><meta charset="UTF-8">
<title>Путевой лист — {vehicle_name}</title>{STYLE}</head><body>
<div class="wb">
  <h1>ПУТЕВОЙ ЛИСТ</h1>
  <div class="sub">{period_label}</div>

  <div class="section">
    <h3>Общие сведения</h3>
    <table>
      <tr><th width="200">Автомобиль</th><td>{vehicle_name}</td></tr>
      <tr><th>Водитель</th><td>{driver}</td></tr>
      <tr><th>Период</th><td>{period_label}</td></tr>
    </table>
  </div>

  {cargo_block}

  <div class="section">
    <h3>Маршрут</h3>
    <table>
      <tr><th width="150">Этап</th><th width="155">Дата / Время</th><th>Адрес</th></tr>
      <tr><td><b>Выезд</b></td><td>{time_start}</td><td>{addr_start}</td></tr>
      <tr><td><b>Возврат</b></td><td>{time_end}</td><td>{addr_end}</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Пробег (CAN — показания бортового компьютера)</h3>
    <table>
      <tr><th width="200">Пробег за рейс</th>
          <td class="num hi">{fv(can_dist, 1)} км</td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Топливо</h3>
    <table>
      <tr><th width="200">Уровень при выезде</th>{fuel_td(fuel_start_rows, total_fs)}</tr>
      <tr><th>Уровень при возврате</th>{fuel_td(fuel_end_rows, total_fe)}</tr>
      <tr><th>Заправлено за рейс</th>
          <td class="num"><b>{fv(fuelings, 1)} л</b></td></tr>
    </table>
  </div>

  <div class="section">
    <h3>Стоянки более {stop_min} мин ({stop_min//60} ч {stop_min%60:02d} мин)</h3>
    <table>
      <tr><th width="145">Начало</th><th width="145">Конец</th>
          <th width="80">Длит.</th><th>Адрес</th></tr>
      {stops_rows}
    </table>
  </div>

  <div class="noprint">
    <button class="btn-print" onclick="window.print()">Печать / PDF</button>
    <button class="btn-back"  onclick="history.back()">Назад</button>
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
        body = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())

        oid          = int(body["oid"][0])
        driver       = body.get("driver",       ["—"])[0].strip() or "—"
        date_start   = body["date_start"][0]
        date_end     = body["date_end"][0]
        stop_min     = int(body.get("stop_min", ["1440"])[0] or 1440)
        order_num    = body.get("order_num",    [""])[0].strip()
        cargo_name   = body.get("cargo_name",   [""])[0].strip()
        cargo_weight = body.get("cargo_weight", [""])[0].strip()

        vname = next((o["name"] for o in OBJECTS if o["id"] == oid), str(oid))
        print(f"\nФормування путевого листа: {vname}  {date_start} — {date_end}  стоянки>={stop_min}хв")

        try:
            html = waybill_html(oid, vname, driver, date_start, date_end,
                                order_num, cargo_name, cargo_weight, stop_min)
            self.send_html(html)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(tb)
            self.send_html(f"<h3>Помилка: {e}</h3><pre>{tb}</pre>"
                           "<button onclick='history.back()'>Назад</button>")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init()
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
