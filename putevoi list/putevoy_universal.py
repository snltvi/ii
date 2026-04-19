#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевий лист — універсальний.
Авто: з API /gettree (без Excel).
Датчики: auto-detect за назвою → ручний вибір → кеш у sensor_cache.json.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import json
import os
import webbrowser
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse, urlencode

# ════════════════════════════════════════════════════════
API_URL      = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN        = "abvprom"
PASSWORD     = "29328"
PORT         = 8086
TZ_UA        = timedelta(hours=3)
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE   = os.path.join(SCRIPT_DIR, "sensor_cache.json")
SENSORS_XLSX = os.path.join(SCRIPT_DIR, "sensors_all_objects.xlsx")

ODO_KEYS  = ['can абсолютный пробег', 'одометр', 'пробег', 'can абс', 'абсолютн', 'odo', 'can_dist']
FUEL_KEYS = ['бак', 'lls', 'fuel', 'топлив', 'дут', 'дрт']

_objects     = []    # список всіх ТЗ з API
_sensors_df  = None  # DataFrame з sensors_all_objects.xlsx
# ════════════════════════════════════════════════════════


# ── Утиліти ─────────────────────────────────────────────

def now_ua():
    return datetime.now(timezone.utc).replace(tzinfo=None) + TZ_UA

def ds(d):  return d.strftime('%Y-%m-%d %H:%M:%S')
def dp(s):  return datetime.strptime(str(s).replace('T', ' ')[:19], '%Y-%m-%d %H:%M:%S')

def norm_dt(s):
    s = str(s).replace('T', ' ').strip()
    return s + ':00' if len(s) == 16 else s

def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;') \
                 .replace('>', '&gt;').replace('"', '&quot;')

def safe_float(v):
    try:
        s = str(v).replace(' ', '').replace(',', '.').replace('\xa0', '')
        for u in ['км', 'л', '%', 'об/мин', '°С', 'В', 'м', 'km', 'l']:
            s = s.replace(u, '')
        return float(s)
    except Exception:
        return None


# ── Кеш датчиків ────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def get_cached(oid):
    return load_cache().get(str(oid))

def set_cached(oid, odo_sid, odo_name, fuel_sid, fuel_name):
    cache = load_cache()
    cache[str(oid)] = {
        'odo_sid':   int(odo_sid),  'odo_name':  odo_name,
        'fuel_sid':  int(fuel_sid), 'fuel_name': fuel_name,
    }
    save_cache(cache)


# ── API ─────────────────────────────────────────────────

def connect():
    try:
        r = requests.get(f"{API_URL}/connect",
                         params={'login': LOGIN, 'password': PASSWORD,
                                 'lang': 'ru-ru', 'timezone': '3'},
                         timeout=10)
        return r.headers.get('sessionid') or r.json().get('sessionid')
    except Exception:
        return None

def get_all_objects(sid):
    r = requests.get(f"{API_URL}/gettree", headers={'SessionId': sid},
                     params={'all': 'true'}, timeout=30)
    r.raise_for_status()
    objs = []
    def walk(nodes):
        for n in nodes:
            if n.get('leaf'):
                objs.append({'oid':  n.get('real_id') or n.get('id'),
                             'name': n.get('name', '')})
            if n.get('children'):
                walk(n['children'])
    walk(r.json().get('children', []))
    return objs

def get_sensors_list(oid):
    """Повертає список датчиків для OID з локального Excel-файлу."""
    if _sensors_df is None:
        return []
    rows = _sensors_df[_sensors_df['OID'] == int(oid)]
    result = []
    for _, r in rows.iterrows():
        sid_v = int(r.get('SID') or 0)
        pid_v = int(r.get('PID') or 0)
        name  = str(r.get('Назва датчика') or '').strip()
        if name and name != '— датчики не знайдено —':
            result.append({'sid': sid_v, 'pid': pid_v, 'name': name})
    return result

def get_period_report(sid, oid, dt1_local, dt2_local):
    """
    /getobjectsreport — повертає dict з показниками за період.
    Поля: start_can_dist, stop_can_dist, can_dist, dist,
          start_fuel_level, stop_fuel_level, all_fuel,
          start_address, stop_address, driver,
          start_move_time, stop_move_time
    """
    date_from = ds(dp(dt1_local) - TZ_UA)
    date_to   = ds(dp(dt2_local) - TZ_UA)
    params_req = (
        'start_can_dist;stop_can_dist;can_dist;odo_dist;dist;'
        'start_fuel_level;stop_fuel_level;all_fuel;fuelings;drains;'
        'start_address;stop_address;driver;'
        'start_move_time;stop_move_time;duration;run_time;stop_time'
    )
    try:
        r = requests.get(f"{API_URL}/getobjectsreport",
                         headers={'SessionId': sid},
                         params={'date_from': date_from,
                                 'date_to':   date_to,
                                 'objuids':   str(oid),
                                 'split':     'none',
                                 'param':     params_req},
                         timeout=30)
        if r.status_code != 200:
            print(f"  getobjectsreport error: {r.status_code} {r.text[:200]}")
            return {}
        data = r.json()
        if not data:
            return {}
        periods = data[0].get('periods', [])
        if not periods:
            return {}
        # Знаходимо підсумковий рядок (isTotal=True) або перший
        row = next((p for p in periods if p.get('isTotal')), periods[0])
        result = {}
        for prm in row.get('prms', []):
            result[prm['name']] = prm['value']
        return result
    except Exception as e:
        print(f"  getobjectsreport exception: {e}")
        return {}

def prm_float(report, key):
    """Читає числове значення з dict отчёта."""
    return safe_float(report.get(key))

def auto_detect(sensors_list):
    """Спроба знайти одометр і бак за ключовими словами у назві."""
    odo = fuel = None
    for s in sensors_list:
        nl    = (s.get('name') or '').lower()
        sid_v = s.get('sid', 0)
        name  = (s.get('name') or '').strip()
        if odo  is None and any(k in nl for k in ODO_KEYS):
            odo  = {'sid': sid_v, 'name': name}
        if fuel is None and any(k in nl for k in FUEL_KEYS):
            fuel = {'sid': sid_v, 'name': name}
    return odo, fuel


# ════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif;
       background:linear-gradient(135deg,#667eea,#764ba2);
       min-height:100vh; padding:28px 16px; }
.card { background:#fff; border-radius:16px;
        box-shadow:0 15px 50px rgba(0,0,0,.25);
        padding:36px; max-width:720px; margin:0 auto; }
.page { background:#fff; border-radius:16px;
        box-shadow:0 15px 50px rgba(0,0,0,.25);
        padding:48px; max-width:960px; margin:0 auto; }
h1 { font-size:22px; color:#333; margin-bottom:6px; }
.sub { color:#888; font-size:13px; margin-bottom:26px; }
label { display:block; font-weight:600; color:#444; margin:16px 0 5px; font-size:14px; }
input, select { width:100%; padding:11px 14px;
                border:2px solid #e0e0e0; border-radius:9px;
                font-size:14px; font-family:inherit; background:#fff; }
input:focus, select:focus { outline:none; border-color:#667eea;
    box-shadow:0 0 0 3px rgba(102,126,234,.15); }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.btn  { display:block; width:100%; padding:14px; margin-top:24px;
        background:linear-gradient(135deg,#667eea,#764ba2); color:#fff;
        border:none; border-radius:10px; font-size:16px; font-weight:700;
        cursor:pointer; transition:.2s; }
.btn:hover { transform:translateY(-2px); box-shadow:0 8px 25px rgba(102,126,234,.4); }
.spinner-wrap { display:none; text-align:center; padding:24px; }
.spinner { display:inline-block; width:42px; height:42px;
           border:5px solid #ddd; border-top-color:#667eea;
           border-radius:50%; animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
/* ── Sensor select ── */
.sensor-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr));
               gap:12px; margin:16px 0; max-height:60vh; overflow-y:auto;
               border:1px solid #eee; border-radius:10px; padding:12px; }
.sensor-card { border:2px solid #e0e0e0; border-radius:10px; padding:14px;
               cursor:pointer; transition:.15s; }
.sensor-card:hover { border-color:#667eea; background:#f0f4ff; }
.sensor-card.sel-odo  { border-color:#4caf50; background:#e8f5e9; }
.sensor-card.sel-fuel { border-color:#2196f3; background:#e3f2fd; }
.sname { font-weight:700; font-size:14px; color:#333; }
.ssid  { font-size:11px; color:#999; margin-top:3px; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px;
         font-size:11px; font-weight:700; margin-top:6px; }
.badge-odo  { background:#4caf50; color:#fff; }
.badge-fuel { background:#2196f3; color:#fff; }
.badge-auto { background:#ff9800; color:#fff; }
/* ── Report ── */
.doc-title { font-size:26px; font-weight:700; text-align:center;
             letter-spacing:2px; border-bottom:3px solid #000;
             padding-bottom:16px; margin-bottom:24px; }
.meta-grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:20px 0; }
.meta-block { border:1px solid #ddd; border-radius:8px; padding:16px; }
.meta-block h4 { font-size:12px; text-transform:uppercase; color:#999;
                 letter-spacing:1px; margin-bottom:10px; }
.meta-row { display:flex; gap:8px; margin:6px 0; font-size:14px; align-items:baseline; }
.meta-lbl { color:#666; font-weight:600; min-width:110px; font-size:13px; }
[contenteditable] { border-bottom:1px dashed #ccc; min-width:30px;
                    display:inline-block; cursor:text; padding:1px 3px; }
[contenteditable]:focus { outline:2px solid #667eea; border-radius:3px; background:#f0f8ff; }
[contenteditable]:hover { background:#f9f9f9; }
.totals { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:14px; margin:24px 0; }
.total-card { border:2px solid #e0e0e0; border-radius:10px; padding:16px; text-align:center; }
.total-card.green  { border-color:#4caf50; background:#e8f5e9; }
.total-card.blue   { border-color:#2196f3; background:#e3f2fd; }
.total-card.red    { border-color:#f44336; background:#ffebee; }
.total-card.purple { border-color:#667eea; background:#f0f4ff; }
.total-val { font-size:26px; font-weight:700; margin:8px 0 4px; }
.total-lbl { font-size:11px; color:#777; text-transform:uppercase; letter-spacing:.5px; }
.route-table { width:100%; border-collapse:collapse; font-size:14px; margin:16px 0; }
.route-table th { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff;
                  padding:10px 12px; text-align:left; font-size:12px;
                  font-weight:600; text-transform:uppercase; letter-spacing:.5px; }
.route-table td { padding:12px; border-bottom:1px solid #f0f0f0; vertical-align:top; }
.route-table tr:hover td { background:#f8f9ff; }
.toolbar { display:flex; gap:10px; justify-content:center; margin-bottom:20px; flex-wrap:wrap; }
.tbtn { padding:10px 24px; border:none; border-radius:8px;
        font-size:14px; font-weight:600; cursor:pointer; transition:.2s; }
.tbtn:hover { transform:translateY(-1px); box-shadow:0 4px 12px rgba(0,0,0,.2); }
.hint { text-align:center; font-size:12px; color:#aaa; margin-bottom:12px; }
.info-box { background:#f0f4ff; border-left:4px solid #667eea;
            padding:10px 14px; border-radius:6px; margin:8px 0; font-size:13px; }
.warn-box { background:#fff8e1; border-left:4px solid #ffc107;
            padding:10px 14px; border-radius:6px; margin:8px 0; font-size:13px; }
@media print {
  body { background:#fff; padding:0; }
  .page { box-shadow:none; border-radius:0; }
  .toolbar,.hint,.no-print { display:none !important; }
}
"""


# ════════════════════════════════════════════════════════
#  СТОРІНКА 1 — Форма вибору авто
# ════════════════════════════════════════════════════════

def page_form():
    cache = load_cache()
    opts  = '<option value="">— оберіть авто —</option>\n'
    for obj in _objects:
        oid      = str(obj['oid'])
        cached   = '✓ ' if oid in cache else ''
        opts    += f'<option value="{oid}">{cached}{esc(obj["name"])}</option>\n'

    now  = now_ua()
    week = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')
    nows = now.strftime('%Y-%m-%dT%H:%M')

    return f"""<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Путевий лист</title><style>{CSS}</style></head><body>
<div class="card">
  <h1>📋 Путевий лист</h1>
  <p class="sub">Авто завантажені з GPS-системи ({len(_objects)} одиниць).
     ✓ = датчики вже налаштовані</p>

  <form action="/report" method="get"
        onsubmit="document.getElementById('sp').style.display='block'">

    <label>🚗 Транспортний засіб</label>
    <select name="oid" required>
      {opts}
    </select>

    <label>👤 Водій</label>
    <input type="text" name="driver" placeholder="ПІБ водія" required>

    <div class="row2">
      <div>
        <label>📅 Початок рейсу</label>
        <input type="datetime-local" name="dt1" value="{week}" required>
      </div>
      <div>
        <label>📅 Кінець рейсу</label>
        <input type="datetime-local" name="dt2" value="{nows}" required>
      </div>
    </div>

    <button class="btn" type="submit">📄 Сформувати →</button>
  </form>

  <div class="spinner-wrap" id="sp">
    <div class="spinner"></div>
    <p style="margin-top:14px;color:#555;font-weight:600">Отримую дані…</p>
  </div>
</div></body></html>"""


# ════════════════════════════════════════════════════════
#  СТОРІНКА 2 — Вибір датчиків (якщо не знайдено авто)
# ════════════════════════════════════════════════════════

def page_sensor_select(oid, obj_name, sensors_list, dt1, dt2, driver, auto_odo, auto_fuel):
    cards = ''
    for s in sensors_list:
        sid_v = s.get('sid', 0)
        name  = (s.get('name') or '').strip()
        pid   = s.get('pid', 0)

        auto_badge = ''
        if auto_odo  and sid_v == auto_odo['sid']:
            auto_badge = '<span class="badge badge-auto">авто: одометр</span>'
        elif auto_fuel and sid_v == auto_fuel['sid']:
            auto_badge = '<span class="badge badge-auto">авто: бак</span>'

        cards += f"""
<div class="sensor-card" id="sc_{sid_v}"
     onclick="selectSensor({sid_v}, '{esc(name)}')">
  <div class="sname">{esc(name)}</div>
  <div class="ssid">SID={sid_v}  PID={pid}</div>
  {auto_badge}
  <div id="badge_{sid_v}"></div>
</div>"""

    a_odo_sid   = auto_odo['sid']  if auto_odo  else 0
    a_odo_name  = auto_odo['name'] if auto_odo  else ''
    a_fuel_sid  = auto_fuel['sid'] if auto_fuel else 0
    a_fuel_name = auto_fuel['name'] if auto_fuel else ''

    return f"""<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вибір датчиків</title><style>{CSS}</style></head><body>
<div class="card" style="max-width:860px">
  <h1>🔧 Налаштування датчиків</h1>
  <p class="sub">{esc(obj_name)} (OID={oid}) — оберіть датчик одометра і датчик бака</p>

  <div style="display:flex;gap:12px;margin:12px 0">
    <div class="info-box" style="flex:1">
      🟢 <strong>Одометр:</strong> <span id="lbl_odo">не обрано</span>
    </div>
    <div class="info-box" style="flex:1">
      🔵 <strong>Бак:</strong> <span id="lbl_fuel">не обрано</span>
    </div>
  </div>
  <div style="font-size:13px;color:#666;margin-bottom:8px">
    Клацніть датчик → <strong>1-й клік</strong>: одометр &nbsp;|&nbsp;
    <strong>2-й клік</strong>: бак &nbsp;|&nbsp; <strong>3-й</strong>: скасувати
  </div>

  <div class="sensor-grid">{cards}</div>

  <form action="/save-sensors" method="get" id="sf">
    <input type="hidden" name="oid"       value="{oid}">
    <input type="hidden" name="dt1"       value="{esc(dt1)}">
    <input type="hidden" name="dt2"       value="{esc(dt2)}">
    <input type="hidden" name="driver"    value="{esc(driver)}">
    <input type="hidden" name="odo_sid"   id="odo_sid"   value="{a_odo_sid}">
    <input type="hidden" name="odo_name"  id="odo_name"  value="{esc(a_odo_name)}">
    <input type="hidden" name="fuel_sid"  id="fuel_sid"  value="{a_fuel_sid}">
    <input type="hidden" name="fuel_name" id="fuel_name" value="{esc(a_fuel_name)}">
    <button class="btn" type="submit">💾 Зберегти і сформувати лист →</button>
  </form>
</div>

<script>
let odoSid=null, fuelSid=null;
const clicks={{}};

const aOdo  = {a_odo_sid};
const aFuel = {a_fuel_sid};
if (aOdo)  assignOdo(aOdo,   '{esc(a_odo_name)}');
if (aFuel) assignFuel(aFuel, '{esc(a_fuel_name)}');

function assignOdo(sid, name) {{
  if (odoSid) document.getElementById('sc_'+odoSid)?.classList.remove('sel-odo');
  odoSid=sid;
  document.getElementById('sc_'+sid)?.classList.add('sel-odo');
  document.getElementById('odo_sid').value  = sid;
  document.getElementById('odo_name').value = name;
  document.getElementById('lbl_odo').textContent = name+' (SID='+sid+')';
  refreshBadge(sid);
}}
function assignFuel(sid, name) {{
  if (fuelSid) document.getElementById('sc_'+fuelSid)?.classList.remove('sel-fuel');
  fuelSid=sid;
  document.getElementById('sc_'+sid)?.classList.add('sel-fuel');
  document.getElementById('fuel_sid').value  = sid;
  document.getElementById('fuel_name').value = name;
  document.getElementById('lbl_fuel').textContent = name+' (SID='+sid+')';
  refreshBadge(sid);
}}
function refreshBadge(sid) {{
  const el=document.getElementById('badge_'+sid);
  if (!el) return;
  let h='';
  if (odoSid  === sid) h+='<span class="badge badge-odo">ОДОМЕТР</span> ';
  if (fuelSid === sid) h+='<span class="badge badge-fuel">БАК</span>';
  el.innerHTML=h;
}}
function selectSensor(sid, name) {{
  clicks[sid] = ((clicks[sid]||0)+1) % 3;
  if (clicks[sid]===1)      assignOdo(sid, name);
  else if (clicks[sid]===2) assignFuel(sid, name);
  else {{
    if (odoSid ===sid) {{ odoSid=null;  document.getElementById('odo_sid').value='';
                          document.getElementById('lbl_odo').textContent='не обрано'; }}
    if (fuelSid===sid) {{ fuelSid=null; document.getElementById('fuel_sid').value='';
                          document.getElementById('lbl_fuel').textContent='не обрано'; }}
    document.getElementById('sc_'+sid)?.classList.remove('sel-odo','sel-fuel');
    document.getElementById('badge_'+sid).innerHTML='';
  }}
}}
</script>
</body></html>"""


# ════════════════════════════════════════════════════════
#  СТОРІНКА 3 — Путевий лист
# ════════════════════════════════════════════════════════

def page_report(oid, obj_name, odo_sid, fuel_sid, odo_name, fuel_name, dt1, dt2, driver):
    sid = connect()
    if not sid:
        return error_page("Не вдалося підключитися до API")

    print(f"\n{'='*60}")
    print(f"  {obj_name}  OID={oid}")
    print(f"  Одометр: {odo_name} (SID={odo_sid})")
    print(f"  Бак:     {fuel_name} (SID={fuel_sid})")
    print(f"  {dt1}  →  {dt2}")

    print(f"  Запит getobjectsreport...")
    rep = get_period_report(sid, oid, dt1, dt2)
    print(f"  Відповідь: {rep}")

    # CAN-одометр: start/stop_can_dist, fallback — GPS dist
    odo1 = prm_float(rep, 'start_can_dist')
    odo2 = prm_float(rep, 'stop_can_dist')
    if odo1 is None and odo2 is None:
        odo1 = 0.0
        odo2 = prm_float(rep, 'dist') or 0.0   # GPS пробіг

    # Бак
    fuel1 = prm_float(rep, 'start_fuel_level')
    fuel2 = prm_float(rep, 'stop_fuel_level')

    # Адреси і час із звіту
    start_addr = rep.get('start_address', '')
    stop_addr  = rep.get('stop_address', '')
    start_time = rep.get('start_move_time', dt1)
    stop_time  = rep.get('stop_move_time', dt2)
    api_driver = rep.get('driver', '')

    # Пробіг: CAN або GPS
    can_dist = prm_float(rep, 'can_dist')
    gps_dist = prm_float(rep, 'dist')
    mileage  = can_dist if can_dist else (gps_dist or 0.0)

    # Витрата
    all_fuel = prm_float(rep, 'all_fuel')
    consumed = all_fuel if all_fuel else (
        round(fuel1 - fuel2, 1) if fuel1 is not None and fuel2 is not None else None
    )
    per100 = round(consumed / mileage * 100, 1) if consumed and mileage > 0 else None

    print(f"  odo1={odo1}  odo2={odo2}  fuel1={fuel1}  fuel2={fuel2}")
    print(f"  mileage={mileage}  consumed={consumed}")
    print(f"{'='*60}\n")

    warn_odo  = '' if (odo1 or odo2) else \
        '<div class="warn-box no-print">⚠️ Одометр не отримано — введіть вручну</div>'
    warn_fuel = '' if fuel1 is not None else \
        '<div class="warn-box no-print">⚠️ Бак не отримано — введіть вручну</div>'

    change_url = '/report?' + urlencode({'oid': oid, 'dt1': dt1, 'dt2': dt2,
                                         'driver': driver, 'force': '1'})

    def fmt(v, dec=1):
        return f"{v:,.{dec}f}".replace(',', ' ') if v is not None else '—'

    def editable(val, eid):
        v = fmt(val) if val is not None else '0'
        return f'<span contenteditable="true" data-num id="{eid}">{v}</span>'

    now_str  = now_ua().strftime('%d.%m.%Y')
    if api_driver and driver in ('—', ''):
        driver = api_driver
    hint_txt = f'💡 Джерело: getobjectsreport | CAN одометр | бак із звіту'

    return f"""<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Путевий лист — {esc(obj_name)}</title><style>{CSS}</style></head><body>
<div class="page">

<div class="toolbar no-print">
  <button class="tbtn" style="background:#4caf50;color:#fff"
          onclick="window.print()">🖨️ Друк / PDF</button>
  <button class="tbtn" style="background:#667eea;color:#fff"
          onclick="recalc()">🔄 Перерахувати</button>
  <a href="{change_url}" style="text-decoration:none">
    <button class="tbtn" style="background:#ff9800;color:#fff">🔧 Змінити датчики</button>
  </a>
  <a href="/" style="text-decoration:none">
    <button class="tbtn" style="background:#9e9e9e;color:#fff">🏠 Новий лист</button>
  </a>
</div>
<div class="hint no-print" id="hint">{hint_txt}</div>

{warn_odo}
{warn_fuel}

<div class="doc-title">ПУТЕВИЙ ЛИСТ</div>
<div style="text-align:center;color:#888;font-size:13px;margin-bottom:24px">
  Дата формування: <strong>{now_str}</strong>
</div>

<div class="meta-grid">
  <div class="meta-block">
    <h4>🚗 Транспортний засіб</h4>
    <div class="meta-row">
      <span class="meta-lbl">Авто:</span>
      <span contenteditable="true">{esc(obj_name)}</span>
    </div>
  </div>
  <div class="meta-block">
    <h4>👤 Водій</h4>
    <div class="meta-row">
      <span class="meta-lbl">ПІБ:</span>
      <span contenteditable="true">{esc(driver)}</span>
    </div>
  </div>
</div>

<h3 style="margin:24px 0 12px;font-size:15px">📍 Маршрут</h3>
<table class="route-table">
  <thead><tr>
    <th>Подія</th><th>Дата і час</th>
    <th>Одометр (км)</th><th>Бак (л)</th><th>Адреса</th>
  </tr></thead>
  <tbody>
    <tr style="background:#e8f5e9">
      <td style="font-weight:700;color:#2e7d32">▶ Виїзд</td>
      <td contenteditable="true">{esc(start_time)}</td>
      <td style="font-weight:700">{editable(odo1, 'f_odo1')} км</td>
      <td style="font-weight:700;color:#0277bd">{editable(fuel1, 'f_fuel1')} л</td>
      <td style="font-size:12px;color:#888;max-width:200px">{esc(start_addr)}</td>
    </tr>
    <tr style="background:#ffebee">
      <td style="font-weight:700;color:#c62828">■ Повернення</td>
      <td contenteditable="true">{esc(stop_time)}</td>
      <td style="font-weight:700">{editable(odo2, 'f_odo2')} км</td>
      <td style="font-weight:700;color:#0277bd">{editable(fuel2, 'f_fuel2')} л</td>
      <td style="font-size:12px;color:#888;max-width:200px">{esc(stop_addr)}</td>
    </tr>
  </tbody>
</table>

<h3 style="margin:24px 0 12px;font-size:15px">📊 Підсумки</h3>
<div class="totals">
  <div class="total-card green">
    <div class="total-val" style="color:#2e7d32">{editable(mileage, 'f_mileage')}</div>
    <div class="total-lbl">Пробіг, км</div>
  </div>
  <div class="total-card blue">
    <div class="total-val" style="color:#0277bd">{editable(fuel1, 'f_fuel_begin')}</div>
    <div class="total-lbl">Бак на початку, л</div>
  </div>
  <div class="total-card blue">
    <div class="total-val" style="color:#0277bd">{editable(fuel2, 'f_fuel_end')}</div>
    <div class="total-lbl">Бак в кінці, л</div>
  </div>
  <div class="total-card red">
    <div class="total-val" style="color:#c62828">{editable(consumed, 'f_consumed')}</div>
    <div class="total-lbl">Витрачено, л</div>
  </div>
  <div class="total-card purple">
    <div class="total-val" style="color:#667eea">{editable(per100, 'f_per100')}</div>
    <div class="total-lbl">Витрата л/100км</div>
  </div>
</div>

<div style="display:flex;gap:40px;margin-top:50px">
  <div style="flex:1;border-top:1px solid #000;padding-top:8px;
              font-size:13px;color:#555;text-align:center">
    Водій: <span contenteditable="true">{esc(driver)}</span>
  </div>
  <div style="flex:1;border-top:1px solid #000;padding-top:8px;
              font-size:13px;color:#555;text-align:center">
    Диспетчер: <span contenteditable="true">___________________</span>
  </div>
  <div style="flex:1;border-top:1px solid #000;padding-top:8px;
              font-size:13px;color:#555;text-align:center">
    Механік: <span contenteditable="true">___________________</span>
  </div>
</div>

</div>
<script>
document.querySelectorAll('[data-num]').forEach(el => {{
  el.addEventListener('focus', function() {{
    this._prev = this.textContent.trim();
    this.textContent = '';
  }});
  el.addEventListener('blur', function() {{
    if (!this.textContent.trim()) this.textContent = this._prev;
  }});
  el.addEventListener('keydown', function(e) {{
    const ok=['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Enter','.'];
    if (!ok.includes(e.key) && !/^\\d$/.test(e.key)) e.preventDefault();
  }});
}});

function num(id) {{
  const el=document.getElementById(id);
  return el ? parseFloat(el.textContent.replace(/[^\\d.]/g,''))||0 : 0;
}}
function set(id, v) {{
  const el=document.getElementById(id);
  if (!el) return;
  el.textContent = isFinite(v) ? v.toFixed(1) : '—';
  el.style.background='#fffde7';
  setTimeout(()=>el.style.background='', 1200);
}}

function recalc() {{
  const odo1  = num('f_odo1');
  const odo2  = num('f_odo2');
  const fuel1 = num('f_fuel_begin') || num('f_fuel1');
  const fuel2 = num('f_fuel_end')   || num('f_fuel2');
  const mileage  = Math.round((odo2-odo1)*10)/10;
  const consumed = Math.round((fuel1-fuel2)*10)/10;
  const per100   = mileage>0 ? Math.round(consumed/mileage*1000)/10 : 0;
  set('f_mileage',  mileage);
  set('f_consumed', consumed);
  set('f_per100',   per100);
  set('f_fuel_begin', fuel1);
  set('f_fuel_end',   fuel2);
  const h = document.getElementById('hint');
  h.textContent = `✅ Перераховано: ${{mileage}} км | витрата ${{consumed}} л | ${{per100}} л/100км`;
  h.style.color = '#2e7d32';
  setTimeout(()=>{{ h.textContent='{hint_txt}'; h.style.color=''; }}, 4000);
}}
</script>
</body></html>"""


# ════════════════════════════════════════════════════════
#  ПОМИЛКА
# ════════════════════════════════════════════════════════

def error_page(msg):
    return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="UTF-8">
<style>{CSS} .card{{max-width:460px;text-align:center}}</style></head>
<body><div class="card">
  <div style="font-size:56px;margin-bottom:16px">❌</div>
  <h2 style="color:#c62828;margin-bottom:12px">Помилка</h2>
  <p style="color:#555;margin-bottom:24px">{esc(msg)}</p>
  <a href="/"><button class="btn">◀ Назад</button></a>
</div></body></html>"""


# ════════════════════════════════════════════════════════
#  HTTP СЕРВЕР
# ════════════════════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):

    def log_message(self, _format, *_args):
        pass

    def send_html(self, html, status=200):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        q      = parse_qs(parsed.query)
        path   = parsed.path

        def gp(k, default=''):
            v = q.get(k, [default])[0]
            return norm_dt(v) if k in ('dt1', 'dt2') else v

        try:
            # ── / — форма ───────────────────────────────
            if path == '/':
                self.send_html(page_form())

            # ── /report — перевірка кешу → звіт або вибір датчиків ──
            elif path == '/report':
                oid    = int(gp('oid') or 0)
                dt1    = gp('dt1')
                dt2    = gp('dt2')
                driver = gp('driver') or '—'
                force  = gp('force') == '1'

                obj_name = next((o['name'] for o in _objects if o['oid'] == oid), str(oid))
                cached   = get_cached(oid) if not force else None

                if cached:
                    self.send_html(page_report(
                        oid, obj_name,
                        cached['odo_sid'],  cached['fuel_sid'],
                        cached['odo_name'], cached['fuel_name'],
                        dt1, dt2, driver))
                    return

                # Запитуємо список датчиків
                sid = connect()
                if not sid:
                    self.send_html(error_page("Не вдалося підключитися до API"))
                    return

                sensors  = get_sensors_list(oid)
                auto_odo, auto_fuel = auto_detect(sensors)

                if auto_odo and auto_fuel and not force:
                    # Обидва знайдено — зберігаємо і одразу звіт
                    set_cached(oid, auto_odo['sid'],  auto_odo['name'],
                                    auto_fuel['sid'], auto_fuel['name'])
                    print(f"  Auto-detect: одометр={auto_odo['name']} | бак={auto_fuel['name']}")
                    self.send_html(page_report(
                        oid, obj_name,
                        auto_odo['sid'],  auto_fuel['sid'],
                        auto_odo['name'], auto_fuel['name'],
                        dt1, dt2, driver))
                else:
                    # Показуємо сторінку ручного вибору
                    self.send_html(page_sensor_select(
                        oid, obj_name, sensors,
                        dt1, dt2, driver, auto_odo, auto_fuel))

            # ── /save-sensors — зберегти вибір → звіт ───
            elif path == '/save-sensors':
                oid       = int(gp('oid') or 0)
                odo_sid   = int(gp('odo_sid')  or 0)
                fuel_sid  = int(gp('fuel_sid') or 0)
                odo_name  = gp('odo_name')
                fuel_name = gp('fuel_name')
                dt1       = gp('dt1')
                dt2       = gp('dt2')
                driver    = gp('driver') or '—'

                if not odo_sid or not fuel_sid:
                    self.send_html(error_page(
                        "Оберіть датчик одометра і датчик бака перед збереженням"))
                    return

                set_cached(oid, odo_sid, odo_name, fuel_sid, fuel_name)
                obj_name = next((o['name'] for o in _objects if o['oid'] == oid), str(oid))
                self.send_html(page_report(
                    oid, obj_name, odo_sid, fuel_sid, odo_name, fuel_name,
                    dt1, dt2, driver))

            else:
                self.send_html("<h1>404</h1>", 404)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_html(error_page(f"Внутрішня помилка: {e}"))


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

def main():
    global _objects

    print("\n" + "=" * 60)
    print("  ПУТЕВИЙ ЛИСТ — УНІВЕРСАЛЬНИЙ")
    print("=" * 60)

    print("\n[1] Підключення до API...")
    sid = connect()
    if not sid:
        print("❌ Не вдалося підключитися до API")
        input("\nEnter для виходу...")
        return
    print(f"    OK  sid={sid[:12]}...")

    print("[2] Завантаження довідника датчиків...")
    global _sensors_df
    if os.path.exists(SENSORS_XLSX):
        _sensors_df = pd.read_excel(SENSORS_XLSX)
        # нормалізуємо колонку OID до int
        _sensors_df['OID'] = pd.to_numeric(_sensors_df['OID'], errors='coerce').fillna(0).astype(int)
        print(f"    OK: {SENSORS_XLSX}")
        print(f"    Рядків: {len(_sensors_df)}  |  Авто: {_sensors_df['OID'].nunique()}")
    else:
        print(f"    ⚠️  Файл не знайдено: {SENSORS_XLSX}")
        print("       Запустіть export_sensors.py щоб створити довідник")

    print("[3] Завантаження списку ТЗ...")
    _objects = get_all_objects(sid)
    print(f"    OK: {len(_objects)} авто")

    cache = load_cache()
    print(f"    Налаштовано датчиків: {len(cache)} авто")

    url = f"http://localhost:{PORT}"
    print(f"\n🚀 Сервер: {url}")
    print("   Ctrl+C — зупинити\n")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server = HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  Зупинено")


if __name__ == "__main__":
    main()
