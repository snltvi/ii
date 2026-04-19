#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПУТЕВОЙ ЛИСТ — полная версия 
Шаг 1: выбор ТС + период  →  Шаг 2: проверка одометра из API (или ввод вручную)  →  Отчёт
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import time
import math
import os
import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse, urlencode
import webbrowser

# ═══════════════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL      = os.path.join(SCRIPT_DIR, "CAN_пробег_датчики_06_02_2026.xlsx")
PORT       = 8080

vehicles_df = None

# ═══════════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════

def dp(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')

def ds(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')

def norm_dt(s):
    """datetime-local (2026-04-01T08:30) → API format (2026-04-01 08:30:00)"""
    s = str(s).replace('T', ' ').strip()
    if len(s) == 16:
        s += ':00'
    return s

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

def fmt_dur(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h} ч {m:02d} мин"

def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def get_car(idx):
    return vehicles_df.iloc[int(idx)]

def safe_sid(car):
    try:
        v = car.get('SID')
        return int(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
    except:
        return None

# ═══════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════

def connect():
    try:
        r = requests.get(f"{API_URL}/connect",
                         params={'login': LOGIN, 'password': PASSWORD,
                                 'lang': 'ru-ru', 'timezone': '3'},
                         timeout=10)
        return r.headers.get('sessionid') or r.json().get('sessionid')
    except:
        return None


def get_address(sid, lat, lon):
    try:
        r = requests.get(f"{API_URL}/getaddress",
                         headers={'SessionId': sid},
                         params={'lat': lat, 'lon': lon}, timeout=10)
        addr = r.text.strip().strip('"')
        return addr if addr else "Адрес не определён"
    except:
        return "Ошибка геокодера"


def get_track(sid, oid, dt_from, dt_to):
    try:
        r = requests.get(f"{API_URL}/track",
                         headers={'SessionId': sid},
                         params={'oid': oid, 'from': dt_from, 'to': dt_to},
                         timeout=60)
        if r.status_code == 200:
            return r.json().get('track', [])
    except:
        pass
    return []


def get_odometer_at_time(sid, oid, sensor_id, target_str, window_h=4):
    """
    Поиск показания одометра ближайшего к target_str ± window_h часов.
    Возвращает (int_value, actual_time_str) или (None, None).
    """
    try:
        target = dp(target_str)
        r = requests.get(f"{API_URL}/objdata",
                         headers={'SessionId': sid},
                         params={
                             'oid': oid,
                             'slist': f's{sensor_id}',
                             'from': ds(target - timedelta(hours=window_h)),
                             'to':   ds(target + timedelta(hours=window_h)),
                         }, timeout=30)

        if r.status_code != 200:
            return None, None

        records = r.json().get('obj_data', {}).get('records', [])
        valid = []
        for rec in records:
            try:
                v = float(rec[1])
                if v > 0:
                    valid.append((rec[0], v))
            except:
                pass

        if not valid:
            return None, None

        target_ts = target.timestamp()
        best = min(valid, key=lambda x: abs(dp(x[0]).timestamp() - target_ts))
        return int(best[1]), best[0]

    except Exception as e:
        print(f"  Ошибка одометра: {e}")
        return None, None


def get_location_at_time(sid, oid, target_str):
    """
    Находит GPS-координаты, ближайшие к target_str, и возвращает адрес.
    Возвращает (lat, lon, address).
    """
    try:
        target = dp(target_str)
        for window_m in [5, 15, 30, 60, 120]:
            pts = [p for p in get_track(sid, oid,
                                        ds(target - timedelta(minutes=window_m)),
                                        ds(target + timedelta(minutes=window_m)))
                   if p.get('lat') and p.get('lon')]
            if pts:
                target_ts = target.timestamp()
                best = min(pts, key=lambda p: abs(dp(p['dt']).timestamp() - target_ts))
                lat, lon = best['lat'], best['lon']
                return lat, lon, get_address(sid, lat, lon)
    except Exception as e:
        print(f"  Ошибка локации: {e}")
    return None, None, "Нет GPS данных"


def get_fuelings_period(sid, oid, dt_from, dt_to):
    """Возвращает (total_vol_float, [{'time','volume','address'}])"""
    try:
        r = requests.get(f"{API_URL}/fuelings",
                         headers={'SessionId': sid},
                         params={'oid': oid, 'from': dt_from, 'to': dt_to},
                         timeout=30)
        if r.status_code != 200 or r.json().get('result') != 'Ok':
            return 0.0, []

        events, total = [], 0.0
        for ev in r.json().get('fuelings', []):
            if ev.get('fuel_type') == 'fueling':
                vol  = round(float(ev.get('volume', 0)), 1)
                lat, lon = ev.get('lat'), ev.get('lon')
                addr = get_address(sid, lat, lon) if lat and lon else "—"
                total += vol
                events.append({'time': ev.get('start_time', ''), 'volume': vol, 'address': addr})
                time.sleep(0.1)
        return round(total, 1), events
    except:
        return 0.0, []


def get_fuel_levels(sid, oid, dt_from, dt_to):
    """
    Возвращает (fuel_begin, fuel_end) для рейса dt_from → dt_to.
    Логика: /getobjectsfuelinfo за полный период, суммируем датчики
    с ключевыми словами 'бак'/'lls'/'fuel' — точно как в рабочем скрипте.
    """
    print(f"  Получаю топливо: {dt_from} — {dt_to}")
    try:
        r = requests.get(f"{API_URL}/getobjectsfuelinfo",
                         headers={'SessionId': sid},
                         params={'objuids': str(oid),
                                 'date_from': dt_from,
                                 'date_to':   dt_to},
                         timeout=30)
        if r.status_code != 200:
            print(f"  getobjectsfuelinfo HTTP {r.status_code}")
            return None, None

        data = r.json()
        if not isinstance(data, list) or not data:
            return None, None

        # Ищем нужный объект
        obj = next((o for o in data if o.get('object_id') == oid), data[0])

        t_start, t_end = 0.0, 0.0
        found = False
        print(f"  Датчики топлива ({len(obj.get('sensors', []))} шт):")
        for s in obj.get('sensors', []):
            name = s.get('sensor_name', '')
            b    = s.get('beginLevel', 0) or 0
            e    = s.get('endLevel',   0) or 0
            print(f"    • {name:35s}  begin={b}  end={e}")
            if any(w in name.lower() for w in ['бак', 'lls', 'fuel']):
                t_start += b
                t_end   += e
                found = True

        if not found:
            print("  Ключевые слова не найдены — берём все датчики")
            for s in obj.get('sensors', []):
                t_start += s.get('beginLevel', 0) or 0
                t_end   += s.get('endLevel',   0) or 0

        result = round(t_start, 1), round(t_end, 1)
        print(f"  ✓ Итого: начало={result[0]} л, конец={result[1]} л")
        return result

    except Exception as e:
        print(f"  Ошибка get_fuel_levels: {e}")
        return None, None


def find_stops(sid, oid, dt_from, dt_to, min_min=60, radius_m=200):
    """
    Находит остановки >= min_min минут по треку.
    Возвращает список {'start','end','dur_min','lat','lon','address'}.
    """
    print(f"  Получение трека {dt_from} — {dt_to}...")
    track = get_track(sid, oid, dt_from, dt_to)
    if not track:
        print("  Трек пустой")
        return []

    pts = [p for p in track if p.get('lat') and p.get('lon') and p.get('dt')]
    print(f"  Точек трека: {len(pts)}")

    stops = []
    i = 0
    while i < len(pts):
        alat, alon = pts[i]['lat'], pts[i]['lon']
        j = i + 1
        while j < len(pts):
            if haversine(alat, alon, pts[j]['lat'], pts[j]['lon']) > radius_m:
                break
            j += 1

        if j > i:
            try:
                dur = (dp(pts[j - 1]['dt']) - dp(pts[i]['dt'])).total_seconds() / 60
                if dur >= min_min:
                    stops.append({
                        'start':   pts[i]['dt'],
                        'end':     pts[j - 1]['dt'],
                        'dur_min': int(dur),
                        'lat':     alat,
                        'lon':     alon,
                        'address': None,
                    })
            except:
                pass

        i = j if j > i else i + 1

    print(f"  Остановок > {min_min} мин: {len(stops)}")
    for s in stops:
        s['address'] = get_address(sid, s['lat'], s['lon'])
        time.sleep(0.12)

    return stops


# ═══════════════════════════════════════════════════════════════
#  HTML — ОБЩИЙ СТИЛЬ
# ═══════════════════════════════════════════════════════════════

COMMON_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif; background:linear-gradient(135deg,#667eea,#764ba2);
       min-height:100vh; padding:30px 20px; }
.card { background:#fff; border-radius:16px; box-shadow:0 15px 50px rgba(0,0,0,.25);
        padding:36px; max-width:700px; margin:0 auto; }
h1 { font-size:24px; color:#333; margin-bottom:6px; }
.sub { color:#888; font-size:13px; margin-bottom:28px; }
label { display:block; font-weight:600; color:#444; margin:18px 0 6px; font-size:14px; }
input,select { width:100%; padding:11px 14px; border:2px solid #e0e0e0; border-radius:9px;
               font-size:14px; font-family:inherit; background:#fff; }
input:focus,select:focus { outline:none; border-color:#667eea;
                            box-shadow:0 0 0 3px rgba(102,126,234,.15); }
.btn { display:block; width:100%; padding:14px; margin-top:26px;
       background:linear-gradient(135deg,#667eea,#764ba2); color:#fff;
       border:none; border-radius:10px; font-size:16px; font-weight:700;
       cursor:pointer; transition:transform .2s,box-shadow .2s; }
.btn:hover { transform:translateY(-2px); box-shadow:0 8px 25px rgba(102,126,234,.4); }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.info-box { background:#f0f4ff; border-left:4px solid #667eea;
            padding:12px 16px; border-radius:8px; margin:10px 0; font-size:14px; }
.warn-box { background:#fff8e1; border-left:4px solid #ffc107;
            padding:12px 16px; border-radius:8px; margin:10px 0; font-size:14px; }
.ok-box   { background:#e8f5e9; border-left:4px solid #4caf50;
            padding:12px 16px; border-radius:8px; margin:10px 0; font-size:14px; }
"""


# ═══════════════════════════════════════════════════════════════
#  СТРАНИЦА 1 — форма выбора ТС и периода
# ═══════════════════════════════════════════════════════════════

def page_step1():
    vehicles_json = []
    options_html  = '<option value="">— выберите ТС —</option>\n'
    for i, row in vehicles_df.iterrows():
        oid     = str(row.get('ID объекта', ''))
        num     = str(row.get('Номер авто', f'ID_{oid}'))
        driver  = str(row.get('ФИО', ''))
        trailer = str(row.get('Номер прицепа', '') or '')
        sid_v   = row.get('SID')
        has_sid = sid_v is not None and not (isinstance(sid_v, float) and math.isnan(sid_v))
        options_html += f'<option value="{i}">{num}  —  {driver}</option>\n'
        vehicles_json.append({'idx': i, 'num': num, 'driver': driver,
                               'trailer': trailer, 'has_sid': has_sid})

    now     = datetime.now()
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')
    now_str  = now.strftime('%Y-%m-%dT%H:%M')

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Путевой лист — выбор периода</title>
  <style>
    {COMMON_CSS}
    .driver-info {{ font-size:13px; color:#667eea; margin-top:4px; min-height:18px; }}
    .step-bar {{ display:flex; gap:8px; margin-bottom:28px; }}
    .step {{ flex:1; padding:8px; border-radius:8px; text-align:center; font-size:13px;
             font-weight:600; background:#f0f4ff; color:#667eea; }}
    .step.active {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; }}
    .hint {{ font-size:12px; color:#aaa; margin-top:4px; }}
  </style>
</head>
<body>
<div class="card">
  <h1>📋 Путевой лист</h1>
  <p class="sub">Заполните данные рейса — система автоматически проверит одометр</p>

  <div class="step-bar">
    <div class="step active">1. Выбор ТС и периода</div>
    <div class="step">2. Проверка одометра</div>
    <div class="step">3. Путевой лист</div>
  </div>

  <form action="/check" method="get" id="frm">
    <label>🚗 Транспортное средство</label>
    <select name="idx" id="idx" required onchange="updateDriver()">
      {options_html}
    </select>
    <div class="driver-info" id="driverInfo">Выберите ТС для отображения водителя</div>

    <div class="row2">
      <div>
        <label>📅 Начало рейса</label>
        <input type="datetime-local" name="dt1" id="dt1" value="{week_ago}" required>
        <div class="hint">Дата и время выезда</div>
      </div>
      <div>
        <label>📅 Конец рейса</label>
        <input type="datetime-local" name="dt2" id="dt2" value="{now_str}" required>
        <div class="hint">Дата и время возврата</div>
      </div>
    </div>

    <button class="btn" type="submit">🔍 Проверить одометр →</button>
  </form>
</div>

<script>
const vehicles = {json.dumps(vehicles_json, ensure_ascii=False)};

function updateDriver() {{
  const sel = document.getElementById('idx');
  const idx = parseInt(sel.value);
  const di  = document.getElementById('driverInfo');
  if (isNaN(idx)) {{ di.textContent = 'Выберите ТС'; return; }}
  const v = vehicles.find(x => x.idx === idx);
  if (!v) {{ di.textContent = ''; return; }}
  let txt = '👤 Водитель: ' + (v.driver || 'не указан');
  if (v.trailer) txt += '  |  🔗 Прицеп: ' + v.trailer;
  if (!v.has_sid) txt += '  ⚠️ CAN-датчик не назначен (одометр — ручной ввод)';
  di.textContent = txt;
}}
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  СТРАНИЦА 2 — проверка одометра из API
# ═══════════════════════════════════════════════════════════════

def page_step2(query):
    idx = int(query.get('idx', ['0'])[0])
    dt1 = norm_dt(query.get('dt1', [''])[0])
    dt2 = norm_dt(query.get('dt2', [''])[0])

    car     = get_car(idx)
    oid     = int(car['ID объекта'])
    sid_s   = safe_sid(car)
    num     = str(car.get('Номер авто', f'ID_{oid}'))
    driver  = str(car.get('ФИО', ''))
    trailer = str(car.get('Номер прицепа', '') or '')

    print(f"\n{'='*60}")
    print(f"ШАГ 2: Проверка одометра")
    print(f"  ТС: {num}  |  Водитель: {driver}")
    print(f"  Период: {dt1} — {dt2}")

    sid_api = connect()

    odo1_val, odo1_time = (None, None)
    odo2_val, odo2_time = (None, None)

    if sid_api and sid_s:
        print(f"  Ищу одометр на {dt1}...")
        odo1_val, odo1_time = get_odometer_at_time(sid_api, oid, sid_s, dt1)
        print(f"  → {odo1_val} км ({odo1_time})" if odo1_val else "  → не найдено")

        print(f"  Ищу одометр на {dt2}...")
        odo2_val, odo2_time = get_odometer_at_time(sid_api, oid, sid_s, dt2)
        print(f"  → {odo2_val} км ({odo2_time})" if odo2_val else "  → не найдено")
    elif not sid_api:
        print("  ❌ Нет соединения с API")
    else:
        print("  ⚠️ CAN-датчик не назначен — ручной ввод")

    def odo_block(label, val, act_time, field_name, def_dt):
        if val is not None:
            return f"""
            <div class="ok-box">
              ✅ Найдено в API: <strong>{val:,} км</strong>
              <span style="color:#888; font-size:12px; margin-left:8px;">({act_time})</span>
            </div>
            <label>{label} (км)</label>
            <input type="number" name="{field_name}" value="{val}" required min="0">
            """
        else:
            msg = "CAN-датчик не назначен" if not sid_s else "Данные не найдены в API за ±4 часа"
            return f"""
            <div class="warn-box">
              ⚠️ {msg} — введите показание вручную
            </div>
            <label>{label} (км)</label>
            <input type="number" name="{field_name}" placeholder="Введите км вручную" required min="0">
            """

    block1 = odo_block("Одометр начала", odo1_val, odo1_time, "odo1", dt1)
    block2 = odo_block("Одометр конца",  odo2_val, odo2_time, "odo2", dt2)

    trailer_row = f'<tr><td>Прицеп</td><td>{esc(trailer)}</td></tr>' if trailer else ''

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Путевой лист — одометр</title>
  <style>
    {COMMON_CSS}
    .card {{ max-width:680px; }}
    .step-bar {{ display:flex; gap:8px; margin-bottom:28px; }}
    .step {{ flex:1; padding:8px; border-radius:8px; text-align:center; font-size:13px;
             font-weight:600; background:#f0f4ff; color:#667eea; }}
    .step.active {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; }}
    .step.done {{ background:#e8f5e9; color:#388e3c; }}
    .info-table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
    .info-table td {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; font-size:14px; }}
    .info-table td:first-child {{ font-weight:600; color:#555; width:140px; }}
    .loading-overlay {{ display:none; position:fixed; inset:0; background:rgba(255,255,255,.85);
                        z-index:100; align-items:center; justify-content:center;
                        flex-direction:column; gap:16px; }}
    .spinner {{ width:50px; height:50px; border:5px solid #e0e0e0;
                border-top-color:#667eea; border-radius:50%;
                animation:spin 1s linear infinite; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  </style>
</head>
<body>

<div class="loading-overlay" id="loading">
  <div class="spinner"></div>
  <p style="font-size:18px; font-weight:600; color:#555;">Формирую путевой лист…</p>
  <p style="font-size:13px; color:#888;">Получаю GPS-точки, остановки, заправки — это займёт 30–60 сек</p>
</div>

<div class="card">
  <h1>📋 Путевой лист</h1>
  <p class="sub">Проверьте или введите показания одометра</p>

  <div class="step-bar">
    <div class="step done">✓ 1. ТС и период</div>
    <div class="step active">2. Проверка одометра</div>
    <div class="step">3. Путевой лист</div>
  </div>

  <table class="info-table">
    <tr><td>Транспорт</td><td><strong>{esc(num)}</strong></td></tr>
    <tr><td>Водитель</td><td>{esc(driver)}</td></tr>
    {trailer_row}
    <tr><td>Начало рейса</td><td>{esc(dt1)}</td></tr>
    <tr><td>Конец рейса</td><td>{esc(dt2)}</td></tr>
  </table>

  <form action="/report" method="get" id="frm2"
        onsubmit="document.getElementById('loading').style.display='flex'">
    <input type="hidden" name="idx" value="{idx}">
    <input type="hidden" name="dt1" value="{esc(dt1)}">
    <input type="hidden" name="dt2" value="{esc(dt2)}">

    <div class="row2">
      <div>{block1}</div>
      <div>{block2}</div>
    </div>

    <button class="btn" type="submit">📄 Сформировать путевой лист →</button>
  </form>

  <div style="text-align:center; margin-top:16px;">
    <a href="/" style="color:#667eea; font-size:13px; text-decoration:none;">◀ Назад</a>
  </div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  СТРАНИЦА 3 — полный путевой лист
# ═══════════════════════════════════════════════════════════════

def page_report(query):
    idx  = int(query.get('idx',  ['0'])[0])
    dt1  = norm_dt(query.get('dt1',  [''])[0])
    dt2  = norm_dt(query.get('dt2',  [''])[0])
    odo1 = float(query.get('odo1', ['0'])[0])
    odo2 = float(query.get('odo2', ['0'])[0])

    car     = get_car(idx)
    oid     = int(car['ID объекта'])
    num     = str(car.get('Номер авто', f'ID_{oid}'))
    driver  = str(car.get('ФИО', ''))
    trailer = str(car.get('Номер прицепа', '') or '')

    print(f"\n{'='*60}")
    print(f"ШАГ 3: Формирование путевого листа")
    print(f"  ТС: {num}  |  Водитель: {driver}")
    print(f"  Период: {dt1} — {dt2}")
    print(f"  Одометр: {odo1} → {odo2} км")

    sid_api = connect()
    if not sid_api:
        return error_page("Не удалось подключиться к API. Проверьте интернет и повторите.")

    # — Начало и конец маршрута —
    print("\n  Определяю начальную точку...")
    lat1, lon1, addr1 = get_location_at_time(sid_api, oid, dt1)
    print(f"  → {addr1}")

    print("  Определяю конечную точку...")
    lat2, lon2, addr2 = get_location_at_time(sid_api, oid, dt2)
    print(f"  → {addr2}")

    # — Остановки > 1 час —
    print("\n  Ищу остановки > 1 часа...")
    stops = find_stops(sid_api, oid, dt1, dt2)

    # — Заправки —
    print("\n  Получаю заправки за период...")
    fuel_total, fuel_events = get_fuelings_period(sid_api, oid, dt1, dt2)
    print(f"  → {len(fuel_events)} заправок, {fuel_total} л")

    # — Уровни топлива —
    print("  Получаю уровни топлива...")
    fuel_begin, fuel_end = get_fuel_levels(sid_api, oid, dt1, dt2)
    print(f"  → начало: {fuel_begin} л, конец: {fuel_end} л")

    # — Расчёты —
    mileage = round(odo2 - odo1, 1)

    if fuel_begin is not None and fuel_end is not None:
        fuel_consumed  = round(fuel_begin + fuel_total - fuel_end, 1)
        fuel_per_100   = round(fuel_consumed / mileage * 100, 1) if mileage > 0 else 0.0
    else:
        fuel_consumed  = None
        fuel_per_100   = None

    days = (dp(dt2) - dp(dt1)).days + 1

    print(f"\n  Пробег: {mileage} км, Расход: {fuel_consumed} л, "
          f"Расход/100: {fuel_per_100} л/100км")
    print(f"{'='*60}\n")

    # ── HTML ────────────────────────────────────────────────────

    # Таблица остановок
    if stops:
        stops_rows = ""
        for i, s in enumerate(stops, 1):
            maps_url = f"https://www.google.com/maps?q={s['lat']},{s['lon']}"
            stops_rows += f"""
            <tr>
              <td style="text-align:center">{i}</td>
              <td contenteditable="true">{esc(s['address'])}</td>
              <td contenteditable="true">{esc(s['start'])}</td>
              <td contenteditable="true">{esc(s['end'])}</td>
              <td style="text-align:center; font-weight:600; color:#c0392b">
                {fmt_dur(s['dur_min'])}
              </td>
              <td style="text-align:center">
                <a href="{maps_url}" target="_blank" style="color:#1a73e8">📍</a>
              </td>
            </tr>"""
        stops_table = f"""
        <h3 style="margin:28px 0 12px">⏸ Остановки более 1 часа</h3>
        <table class="doc-table">
          <thead><tr>
            <th style="width:40px">#</th><th>Адрес</th>
            <th style="width:150px">Прибытие</th>
            <th style="width:150px">Отправление</th>
            <th style="width:110px">Длительность</th>
            <th style="width:50px">Карта</th>
          </tr></thead>
          <tbody>{stops_rows}</tbody>
        </table>"""
    else:
        stops_table = """
        <h3 style="margin:28px 0 12px">⏸ Остановки более 1 часа</h3>
        <p style="color:#888; font-size:14px; padding:12px 0">
          Остановок длительностью более 1 часа не обнаружено</p>"""

    # Таблица заправок
    if fuel_events:
        refuel_rows = ""
        for ev in fuel_events:
            refuel_rows += f"""
            <tr>
              <td contenteditable="true">{esc(ev['time'])}</td>
              <td contenteditable="true">{esc(ev['address'])}</td>
              <td style="text-align:right; font-weight:700; color:#0277bd">
                {ev['volume']} л
              </td>
            </tr>"""
        refuel_table = f"""
        <h3 style="margin:28px 0 12px">⛽ Заправки за период</h3>
        <table class="doc-table">
          <thead><tr>
            <th>Дата и время</th><th>Место заправки</th>
            <th style="width:90px;text-align:right">Объём</th>
          </tr></thead>
          <tbody>{refuel_rows}</tbody>
          <tfoot><tr style="background:#e3f2fd; font-weight:700">
            <td colspan="2" style="text-align:right">Итого заправлено:</td>
            <td style="text-align:right; color:#0277bd">{fuel_total} л</td>
          </tr></tfoot>
        </table>"""
    else:
        refuel_table = """
        <h3 style="margin:28px 0 12px">⛽ Заправки за период</h3>
        <p style="color:#888; font-size:14px; padding:12px 0">Заправок не зафиксировано</p>"""

    # Числовая ячейка с id для JS-пересчёта
    def num_cell(v, field_id, suffix="л"):
        val = v if v is not None else 0
        return f'<span contenteditable="true" data-num id="{field_id}">{val}</span> {suffix}'

    # Прицеп
    trailer_row_doc = (f'<tr><td>Прицеп</td>'
                       f'<td contenteditable="true">{esc(trailer)}</td></tr>'
                       if trailer else '')

    # Координаты для ссылок
    def map_link(lat, lon):
        if lat and lon:
            return f' <a href="https://www.google.com/maps?q={lat},{lon}" target="_blank" style="font-size:12px; color:#1a73e8">📍 карта</a>'
        return ''

    now_str = datetime.now().strftime('%d.%m.%Y')

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Путевой лист — {esc(num)}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Segoe UI',sans-serif; background:linear-gradient(135deg,#667eea,#764ba2);
           padding:30px 20px; }}
    .page {{ background:#fff; border-radius:16px; box-shadow:0 15px 50px rgba(0,0,0,.25);
             padding:50px; max-width:1000px; margin:0 auto; }}
    .doc-header {{ border-bottom:3px solid #000; padding-bottom:20px; margin-bottom:24px; }}
    .doc-title {{ font-size:26px; font-weight:700; text-align:center; letter-spacing:2px; }}
    .doc-num {{ text-align:center; color:#666; font-size:14px; margin-top:4px; }}
    .meta-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:20px 0; }}
    .meta-block {{ border:1px solid #ddd; border-radius:8px; padding:16px; }}
    .meta-block h4 {{ font-size:13px; text-transform:uppercase; color:#888;
                      letter-spacing:1px; margin-bottom:10px; }}
    .meta-row {{ display:flex; gap:8px; margin:6px 0; font-size:14px; }}
    .meta-label {{ color:#555; font-weight:600; min-width:100px; }}
    [contenteditable] {{ border-bottom:1px dashed #ccc; min-width:20px; cursor:text;
                         display:inline-block; }}
    [contenteditable]:focus {{ outline:2px solid #667eea; border-radius:3px; background:#f0f8ff; }}
    [contenteditable]:hover {{ background:#f9f9f9; }}
    .doc-table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    .doc-table th {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff;
                     padding:12px 10px; text-align:left; font-size:12px;
                     font-weight:600; text-transform:uppercase; letter-spacing:.5px; }}
    .doc-table td {{ padding:12px 10px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
    .doc-table tr:hover td {{ background:#f8f9ff; }}
    .doc-table tfoot td {{ border-top:2px solid #667eea; background:#f8f9ff; padding:12px 10px; }}
    h3 {{ font-size:16px; color:#333; }}
    .totals-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
                    gap:14px; margin:20px 0; }}
    .total-card {{ border:2px solid #e0e0e0; border-radius:10px; padding:16px; text-align:center; }}
    .total-card.primary {{ border-color:#667eea; background:#f0f4ff; }}
    .total-card.green   {{ border-color:#4caf50; background:#e8f5e9; }}
    .total-card.red     {{ border-color:#e53935; background:#ffebee; }}
    .total-card.blue    {{ border-color:#0277bd; background:#e3f2fd; }}
    .total-value {{ font-size:28px; font-weight:700; margin:8px 0 4px; }}
    .total-label {{ font-size:12px; color:#666; text-transform:uppercase; letter-spacing:.5px; }}
    .sig-row {{ display:flex; gap:40px; margin-top:50px; }}
    .sig-block {{ flex:1; border-top:1px solid #000; padding-top:8px;
                  font-size:13px; color:#555; text-align:center; }}
    .no-print {{ }}
    .tool-bar {{ display:flex; gap:12px; justify-content:center; margin-bottom:20px; }}
    .tbtn {{ padding:11px 28px; border:none; border-radius:8px; font-size:15px;
             font-weight:600; cursor:pointer; transition:.2s; }}
    .tbtn-green {{ background:#4caf50; color:#fff; }}
    .tbtn-grey  {{ background:#9e9e9e; color:#fff; }}
    .tbtn:hover {{ transform:translateY(-2px); box-shadow:0 4px 15px rgba(0,0,0,.2); }}
    .edit-hint {{ text-align:center; font-size:12px; color:#aaa; margin-bottom:14px; }}
    @media print {{
      body {{ background:#fff; padding:0; }}
      .page {{ box-shadow:none; border-radius:0; padding:20mm; }}
      .no-print {{ display:none !important; }}
      [contenteditable] {{ border-bottom:1px solid #999; }}
    }}
  </style>
</head>
<body>

<div class="page">

  <!-- Панель инструментов -->
  <div class="no-print tool-bar">
    <button class="tbtn tbtn-green" onclick="window.print()">🖨️ Печать / PDF</button>
    <button class="tbtn" style="background:#667eea;color:#fff" onclick="recalculate()">🔄 Перерахувати</button>
    <button class="tbtn tbtn-grey"  onclick="history.back()">◀ Назад</button>
    <a href="/" style="text-decoration:none">
      <button class="tbtn tbtn-grey">🏠 Новый лист</button>
    </a>
  </div>

  <div class="no-print edit-hint" id="editHint">
    💡 Клікніть на число — воно очиститься для вводу нового значення. Після змін натисніть 🔄 Перерахувати
  </div>

  <!-- Заголовок -->
  <div class="doc-header">
    <div class="doc-title">ПУТЕВИЙ ЛИСТ</div>
    <div class="doc-num">
      Дата формування: <strong>{now_str}</strong>
    </div>
  </div>

  <!-- Метаданные -->
  <div class="meta-grid">
    <div class="meta-block">
      <h4>🚗 Транспортний засіб</h4>
      <div class="meta-row">
        <span class="meta-label">Держ. номер:</span>
        <span contenteditable="true">{esc(num)}</span>
      </div>
      {f'<div class="meta-row"><span class="meta-label">Прицеп:</span><span contenteditable="true">{esc(trailer)}</span></div>' if trailer else ''}
    </div>
    <div class="meta-block">
      <h4>👤 Водій</h4>
      <div class="meta-row">
        <span class="meta-label">ПІБ:</span>
        <span contenteditable="true">{esc(driver)}</span>
      </div>
    </div>
  </div>

  <!-- Маршрут -->
  <h3 style="margin:28px 0 12px">📍 Маршрут рейсу</h3>
  <table class="doc-table">
    <thead>
      <tr>
        <th style="width:130px">Подія</th>
        <th>Дата і час</th>
        <th>Одометр</th>
        <th>Місце</th>
      </tr>
    </thead>
    <tbody>
      <tr style="background:#e8f5e9">
        <td style="font-weight:700; color:#2e7d32">▶ Виїзд</td>
        <td contenteditable="true">{esc(dt1)}</td>
        <td style="font-weight:700"><span contenteditable="true" data-num id="f_odo1">{int(odo1)}</span> км</td>
        <td contenteditable="true">{esc(addr1)}{map_link(lat1, lon1)}</td>
      </tr>
      <tr style="background:#ffebee">
        <td style="font-weight:700; color:#c62828">■ Повернення</td>
        <td contenteditable="true">{esc(dt2)}</td>
        <td style="font-weight:700"><span contenteditable="true" data-num id="f_odo2">{int(odo2)}</span> км</td>
        <td contenteditable="true">{esc(addr2)}{map_link(lat2, lon2)}</td>
      </tr>
    </tbody>
  </table>

  <!-- Итоги -->
  <h3 style="margin:28px 0 12px">📊 Підсумки рейсу</h3>
  <div class="totals-grid">
    <div class="total-card primary">
      <div class="total-value" style="color:#667eea">
        <span contenteditable="true" data-num id="f_days">{days}</span>
      </div>
      <div class="total-label">Днів у рейсі</div>
    </div>
    <div class="total-card green">
      <div class="total-value" style="color:#2e7d32">
        {num_cell(mileage, 'f_mileage', 'км')}
      </div>
      <div class="total-label">Пробіг</div>
    </div>
    <div class="total-card blue">
      <div class="total-value" style="color:#0277bd">
        {num_cell(fuel_begin, 'f_fuel_begin')}
      </div>
      <div class="total-label">Пальне на початку</div>
    </div>
    <div class="total-card blue">
      <div class="total-value" style="color:#0277bd">
        {num_cell(fuel_total, 'f_fuel_total')}
      </div>
      <div class="total-label">Заправлено</div>
    </div>
    <div class="total-card blue">
      <div class="total-value" style="color:#0277bd">
        {num_cell(fuel_end, 'f_fuel_end')}
      </div>
      <div class="total-label">Пальне в кінці</div>
    </div>
    <div class="total-card red">
      <div class="total-value" style="color:#c62828">
        {num_cell(fuel_consumed, 'f_consumed')}
      </div>
      <div class="total-label">Витрачено пального</div>
    </div>
    <div class="total-card" style="border-color:#ff6f00; background:#fff8e1">
      <div class="total-value" style="color:#e65100">
        {num_cell(fuel_per_100, 'f_per100', 'л/100км')}
      </div>
      <div class="total-label">Витрата на 100 км</div>
    </div>
  </div>

  <!-- Остановки -->
  {stops_table}

  <!-- Заправки -->
  {refuel_table}

  <!-- Подписи -->
  <div class="sig-row">
    <div class="sig-block">Водій: <span contenteditable="true">{esc(driver)}</span></div>
    <div class="sig-block">Диспетчер: <span contenteditable="true">___________________</span></div>
    <div class="sig-block">Механік: <span contenteditable="true">___________________</span></div>
  </div>

</div>

<script>
// ── Очищення числового поля при кліку ───────────────────────
document.querySelectorAll('[data-num]').forEach(function(el) {{
  el.addEventListener('focus', function() {{
    this._prev = this.textContent.trim();
    this.textContent = '';
  }});
  el.addEventListener('blur', function() {{
    if (this.textContent.trim() === '') {{
      this.textContent = this._prev;
    }}
  }});
  // Дозволяємо тільки цифри та крапку
  el.addEventListener('keydown', function(e) {{
    var allowed = ['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Enter','.'];
    if (!allowed.includes(e.key) && !/^\d$/.test(e.key)) e.preventDefault();
  }});
}});

// ── Перерахунок ─────────────────────────────────────────────
function numVal(id) {{
  var el = document.getElementById(id);
  return el ? parseFloat(el.textContent.replace(/[^\d.]/g, '')) || 0 : 0;
}}

function setVal(id, val) {{
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  el.style.transition = 'background .2s';
  el.style.background = '#fffde7';
  setTimeout(function() {{ el.style.background = ''; }}, 1200);
}}

function recalculate() {{
  var odo1      = numVal('f_odo1');
  var odo2      = numVal('f_odo2');
  var fBegin    = numVal('f_fuel_begin');
  var fTotal    = numVal('f_fuel_total');
  var fEnd      = numVal('f_fuel_end');

  var mileage   = Math.round((odo2 - odo1) * 10) / 10;
  var consumed  = Math.round((fBegin + fTotal - fEnd) * 10) / 10;
  var per100    = mileage > 0 ? Math.round(consumed / mileage * 1000) / 10 : 0;

  setVal('f_mileage',  mileage);
  setVal('f_consumed', consumed);
  setVal('f_per100',   per100);

  // Підказка
  var hint = document.getElementById('editHint');
  if (hint) {{
    hint.textContent = '✅ Перераховано: пробіг ' + mileage + ' км, витрата ' + consumed + ' л, ' + per100 + ' л/100км';
    hint.style.color = '#2e7d32';
    setTimeout(function() {{
      hint.textContent = '💡 Клікніть на число — воно очиститься для вводу нового значення. Після змін натисніть 🔄 Перерахувати';
      hint.style.color = '';
    }}, 4000);
  }}
}}
</script>

</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  СТРАНИЦА ОШИБКИ
# ═══════════════════════════════════════════════════════════════

def error_page(msg):
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <style>
    {COMMON_CSS}
    .card {{ max-width:500px; text-align:center; }}
  </style>
</head>
<body>
<div class="card">
  <div style="font-size:60px; margin-bottom:20px">❌</div>
  <h2 style="color:#c62828; margin-bottom:14px">Помилка</h2>
  <p style="color:#555; margin-bottom:28px">{esc(msg)}</p>
  <a href="/" style="text-decoration:none">
    <button class="btn">◀ На головну</button>
  </a>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  HTTP СЕРВЕР
# ═══════════════════════════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def send_html(self, html, status=200):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',   'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query  = parse_qs(parsed.query)
        path   = parsed.path

        try:
            if path == '/':
                self.send_html(page_step1())

            elif path == '/check':
                if not query.get('idx') or not query.get('dt1') or not query.get('dt2'):
                    self.send_html(error_page("Не передані параметри. Поверніться на головну."))
                    return
                self.send_html(page_step2(query))

            elif path == '/report':
                required = ['idx', 'dt1', 'dt2', 'odo1', 'odo2']
                if not all(query.get(k) for k in required):
                    self.send_html(error_page("Не передані параметри. Поверніться на головну."))
                    return
                self.send_html(page_report(query))

            else:
                self.send_html("<h1>404</h1>", 404)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_html(error_page(f"Внутрішня помилка: {e}"))


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global vehicles_df

    print("\n" + "=" * 65)
    print("  ПУТЕВОЙ ЛИСТ v2 — веб-приложение")
    print("=" * 65)

    if not os.path.exists(EXCEL):
        print(f"\n❌ Файл не найден: {EXCEL}")
        input("\nНажмите Enter для выхода...")
        return

    vehicles_df = pd.read_excel(EXCEL)
    print(f"\n✓ Загружено транспортных средств: {len(vehicles_df)}")
    print(f"  Колонки: {list(vehicles_df.columns)}")

    url = f"http://localhost:{PORT}"
    print(f"\n🚀 Сервер запущен: {url}")
    print("💡 Нажмите Ctrl+C для остановки\n")

    import threading
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    server = HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n⏹  Сервер остановлен")


if __name__ == "__main__":
    main()
