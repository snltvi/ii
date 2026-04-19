#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевой лист — веб-застосунок.
Форма: вибір авто, водія, дати початку/кінця рейсу.
Дані: /objectinfo на початок і кінець → одометр, бак.
Результат: редаговний путевий лист з перерахунком.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import os
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import webbrowser

# ═══════════════════════════════════════════════════════
API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL      = os.path.join(SCRIPT_DIR, "CAN_пробег_датчики_06_02_2026.xlsx")
PORT       = 8083
TZ_UA      = timedelta(hours=3)

# Ключові слова для пошуку датчиків одометра і бака
ODO_KEYS  = ['одометр', 'пробег', 'can абс', 'абсолютн', 'odo']
FUEL_KEYS = ['бак', 'lls', 'fuel', 'топлив', 'дут']

vehicles_df = None

# ═══════════════════════════════════════════════════════
#  УТИЛИТЫ
# ═══════════════════════════════════════════════════════

def now_ua():
    return datetime.now(timezone.utc).replace(tzinfo=None) + TZ_UA

def ds(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')

def dp(s):
    return datetime.strptime(str(s).replace('T', ' ')[:19], '%Y-%m-%d %H:%M:%S')

def norm_dt(s):
    s = str(s).replace('T', ' ').strip()
    return s + ':00' if len(s) == 16 else s

def esc(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def safe_float(v):
    try:
        s = str(v).replace(' ', '').replace(',', '.').replace('\xa0','')
        # прибираємо одиниці виміру (км, л, %)
        for unit in [' км', ' л', ' %', 'км', 'л', '%', ' об/мин', ' °С', ' В', ' м']:
            s = s.replace(unit, '')
        return float(s)
    except:
        return None

# ═══════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════

def connect():
    try:
        r = requests.get(f"{API_URL}/connect",
                         params={'login': LOGIN, 'password': PASSWORD,
                                 'lang': 'ru-ru', 'timezone': '3'},
                         timeout=10)
        return r.headers.get('sessionid') or r.json().get('sessionid')
    except:
        return None


def get_object_info(sid, oid, local_dt_str):
    """
    /objectinfo з dt (UTC).
    Повертає (obj_name, sensors[{sid,name,val,dt}]).
    """
    utc_dt = ds(dp(local_dt_str) - TZ_UA)
    try:
        r = requests.get(f"{API_URL}/objectinfo",
                         headers={'SessionId': sid},
                         params={'oid': oid, 'dt': utc_dt},
                         timeout=20)
        if r.status_code != 200:
            return None, []
        data = r.json()
        return data.get('Name', str(oid)), data.get('sensors', [])
    except Exception as e:
        print(f"  objectinfo error: {e}")
        return None, []


def extract_sensors(sensors, odo_sid_hint=None, fuel_sid_hint=None):
    """
    Знаходить одометр і бак у списку датчиків.
    Спочатку шукає за конкретним SID (з Excel), потім за ключовими словами.
    """
    result = dict(odo_val=None, odo_name='', odo_sid=None,
                  fuel_val=None, fuel_name='', fuel_sid=None,
                  sensor_dt='')

    def try_fill_odo(s):
        name  = (s.get('name') or '').strip()
        val   = (s.get('val')  or '').strip()
        sid_v = s.get('sid', 0)
        s_dt  = (s.get('dt')  or '').strip()
        v = safe_float(val)
        if v:
            result.update(odo_val=v, odo_name=name, odo_sid=sid_v, sensor_dt=s_dt)
            return True
        return False

    def try_fill_fuel(s):
        name  = (s.get('name') or '').strip()
        val   = (s.get('val')  or '').strip()
        sid_v = s.get('sid', 0)
        s_dt  = (s.get('dt')  or '').strip()
        v = safe_float(val)
        if v is not None:
            result.update(fuel_val=v, fuel_name=name, fuel_sid=sid_v)
            if not result['sensor_dt']:
                result['sensor_dt'] = s_dt
            return True
        return False

    # ── Прохід 1: точний SID з Excel ──
    for s in sensors:
        sid_v = s.get('sid', 0)
        if result['odo_val']  is None and odo_sid_hint  and sid_v == odo_sid_hint:
            try_fill_odo(s)
        if result['fuel_val'] is None and fuel_sid_hint and sid_v == fuel_sid_hint:
            try_fill_fuel(s)

    # ── Прохід 2: ключові слова (fallback) ──
    for s in sensors:
        name_l = (s.get('name') or '').lower()
        if result['odo_val']  is None and any(k in name_l for k in ODO_KEYS):
            try_fill_odo(s)
        if result['fuel_val'] is None and any(k in name_l for k in FUEL_KEYS):
            try_fill_fuel(s)

    return result

# ═══════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif;
       background:linear-gradient(135deg,#667eea,#764ba2);
       min-height:100vh; padding:28px 16px; }
.card { background:#fff; border-radius:16px;
        box-shadow:0 15px 50px rgba(0,0,0,.25);
        padding:36px; max-width:720px; margin:0 auto; }
h1 { font-size:22px; color:#333; margin-bottom:6px; }
.sub { color:#888; font-size:13px; margin-bottom:26px; }
label { display:block; font-weight:600; color:#444;
        margin:16px 0 5px; font-size:14px; }
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
/* ── Путевий лист ── */
.page  { background:#fff; border-radius:16px;
         box-shadow:0 15px 50px rgba(0,0,0,.25);
         padding:48px; max-width:900px; margin:0 auto; }
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
[contenteditable]:focus { outline:2px solid #667eea; border-radius:3px;
                          background:#f0f8ff; }
[contenteditable]:hover { background:#f9f9f9; }
.totals { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:14px; margin:24px 0; }
.total-card { border:2px solid #e0e0e0; border-radius:10px;
              padding:16px; text-align:center; }
.total-card.blue  { border-color:#2196f3; background:#e3f2fd; }
.total-card.green { border-color:#4caf50; background:#e8f5e9; }
.total-card.red   { border-color:#f44336; background:#ffebee; }
.total-card.purple{ border-color:#667eea; background:#f0f4ff; }
.total-val  { font-size:26px; font-weight:700; margin:8px 0 4px; }
.total-lbl  { font-size:11px; color:#777; text-transform:uppercase; letter-spacing:.5px; }
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
.info-box  { background:#f0f4ff; border-left:4px solid #667eea;
             padding:10px 14px; border-radius:6px; margin:8px 0; font-size:13px; }
.warn-box  { background:#fff8e1; border-left:4px solid #ffc107;
             padding:10px 14px; border-radius:6px; margin:8px 0; font-size:13px; }
@media print {
  body { background:#fff; padding:0; }
  .page { box-shadow:none; border-radius:0; }
  .toolbar,.hint,.no-print { display:none !important; }
}
"""

# ═══════════════════════════════════════════════════════
#  СТОРІНКА 1 — форма
# ═══════════════════════════════════════════════════════

def page_form():
    options = '<option value="">— оберіть авто —</option>\n'
    vlist   = []
    drivers = set()

    for i, row in vehicles_df.iterrows():
        oid    = str(row.get('ID объекта', ''))
        num    = str(row.get('Номер авто', f'ID_{oid}'))
        driver = str(row.get('ФИО', '') or '')
        options += f'<option value="{i}">{num}  —  {driver}</option>\n'
        vlist.append({'idx': i, 'num': num, 'driver': driver, 'oid': oid})
        if driver:
            drivers.add(driver)

    driver_opts = '<option value="">— або введіть вручну —</option>\n'
    for d in sorted(drivers):
        driver_opts += f'<option value="{esc(d)}">{esc(d)}</option>\n'

    now   = now_ua()
    week  = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')
    now_s = now.strftime('%Y-%m-%dT%H:%M')

    return f"""<!DOCTYPE html>
<html lang="uk"><head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Путевий лист</title>
  <style>{CSS}</style>
</head>
<body>
<div class="card">
  <h1>📋 Путевий лист</h1>
  <p class="sub">Оберіть авто, водія та вкажіть період рейсу</p>

  <form action="/report" method="get"
        onsubmit="document.getElementById('sp').style.display='block'">

    <label>🚗 Транспортний засіб</label>
    <select name="idx" id="idx" required onchange="onVehicle(this)">
      {options}
    </select>

    <div class="row2" style="margin-top:16px">
      <div>
        <label>👤 Водій</label>
        <select name="driver_sel" id="driver_sel" onchange="onDriverSel(this)">
          {driver_opts}
        </select>
      </div>
      <div>
        <label>&nbsp;</label>
        <input type="text" name="driver" id="driver_inp"
               placeholder="ПІБ водія" required>
      </div>
    </div>

    <div class="row2">
      <div>
        <label>📅 Початок рейсу</label>
        <input type="datetime-local" name="dt1" value="{week}" required>
      </div>
      <div>
        <label>📅 Кінець рейсу</label>
        <input type="datetime-local" name="dt2" value="{now_s}" required>
      </div>
    </div>

    <button class="btn" type="submit">📄 Сформувати путевий лист →</button>
  </form>

  <div class="spinner-wrap" id="sp">
    <div class="spinner"></div>
    <p style="margin-top:14px;color:#555;font-weight:600">
      Отримую дані з сервера…</p>
  </div>
</div>

<script>
const vlist = {json.dumps(vlist, ensure_ascii=False)};

function onVehicle(sel) {{
  const v = vlist.find(x => x.idx === parseInt(sel.value));
  if (v && v.driver) {{
    document.getElementById('driver_inp').value = v.driver;
    document.getElementById('driver_sel').value = v.driver;
  }}
}}

function onDriverSel(sel) {{
  if (sel.value)
    document.getElementById('driver_inp').value = sel.value;
}}
</script>
</body></html>"""

# ═══════════════════════════════════════════════════════
#  СТОРІНКА 2 — путевий лист
# ═══════════════════════════════════════════════════════

def page_report(query):
    idx    = int(query.get('idx', ['0'])[0])
    dt1    = norm_dt(query.get('dt1', [''])[0])
    dt2    = norm_dt(query.get('dt2', [''])[0])
    driver = query.get('driver', [''])[0] or '—'

    row    = vehicles_df.iloc[idx]
    oid    = int(row.get('ID объекта', 0))
    num    = str(row.get('Номер авто', f'ID_{oid}'))
    trailer= str(row.get('Номер прицепа', '') or '')

    # SID датчиків з Excel (якщо є)
    def _sid(col):
        try:
            v = row.get(col)
            return int(v) if v and str(v) not in ('nan', '') else None
        except:
            return None
    odo_sid_hint  = _sid('SID (одометр)')
    fuel_sid_hint = _sid('SID')

    print(f"\n{'='*60}")
    print(f"  Авто:  {num}  |  OID={oid}")
    print(f"  Водій: {driver}")
    print(f"  Рейс:  {dt1}  →  {dt2}")

    sid = connect()
    if not sid:
        return error_page("Не вдалося підключитися до API")

    # ── Датчики на початок ──
    print(f"\n  [1] Датчики на початок ({dt1})...")
    _, sensors1 = get_object_info(sid, oid, dt1)
    s1 = extract_sensors(sensors1, odo_sid_hint, fuel_sid_hint)
    print(f"      Одометр: {s1['odo_val']} ({s1['odo_name']})")
    print(f"      Бак:     {s1['fuel_val']} ({s1['fuel_name']})")
    print(f"      Час:     {s1['sensor_dt']}")

    # ── Датчики на кінець ──
    print(f"\n  [2] Датчики на кінець ({dt2})...")
    _, sensors2 = get_object_info(sid, oid, dt2)
    s2 = extract_sensors(sensors2, odo_sid_hint, fuel_sid_hint)
    print(f"      Одометр: {s2['odo_val']} ({s2['odo_name']})")
    print(f"      Бак:     {s2['fuel_val']} ({s2['fuel_name']})")
    print(f"      Час:     {s2['sensor_dt']}")
    print(f"{'='*60}\n")

    # ── Розрахунки ──
    odo1 = s1['odo_val'] or 0
    odo2 = s2['odo_val'] or 0
    fuel1= s1['fuel_val']
    fuel2= s2['fuel_val']

    mileage  = round(odo2 - odo1, 1) if odo1 and odo2 else 0
    consumed = round(fuel1 - fuel2, 1) if fuel1 is not None and fuel2 is not None else None
    per100   = round(consumed / mileage * 100, 1) if consumed and mileage > 0 else None

    # Попередження якщо дані не знайдено
    warn_odo  = '' if s1['odo_val'] and s2['odo_val'] else \
                '<div class="warn-box no-print">⚠️ Одометр не знайдено в датчиках — введіть вручну</div>'
    warn_fuel = '' if fuel1 is not None and fuel2 is not None else \
                '<div class="warn-box no-print">⚠️ Датчик бака не знайдено — введіть вручну</div>'

    def fmt(v, dec=1):
        if v is None: return '—'
        return f"{v:,.{dec}f}".replace(',', ' ')

    def editable(val, eid):
        v = fmt(val) if val is not None else '0'
        return f'<span contenteditable="true" data-num id="{eid}">{v}</span>'

    now_str = now_ua().strftime('%d.%m.%Y')
    trailer_row = (f'<div class="meta-row"><span class="meta-lbl">Прицеп:</span>'
                   f'<span contenteditable="true">{esc(trailer)}</span></div>') if trailer else ''

    html = f"""<!DOCTYPE html>
<html lang="uk"><head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Путевий лист — {esc(num)}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="page">

  <!-- Панель інструментів -->
  <div class="toolbar no-print">
    <button class="tbtn" style="background:#4caf50;color:#fff"
            onclick="window.print()">🖨️ Друк / PDF</button>
    <button class="tbtn" style="background:#667eea;color:#fff"
            onclick="recalc()">🔄 Перерахувати</button>
    <button class="tbtn" style="background:#9e9e9e;color:#fff"
            onclick="history.back()">◀ Назад</button>
    <a href="/" style="text-decoration:none">
      <button class="tbtn" style="background:#9e9e9e;color:#fff">🏠 Новий</button>
    </a>
  </div>
  <div class="hint no-print" id="hint">
    💡 Клікніть на будь-яке значення щоб редагувати.
    Після змін натисніть 🔄 Перерахувати
  </div>

  {warn_odo}
  {warn_fuel}

  <!-- Заголовок -->
  <div class="doc-title">ПУТЕВИЙ ЛИСТ</div>
  <div style="text-align:center;color:#888;font-size:13px;margin-bottom:24px">
    Дата формування: <strong>{now_str}</strong>
  </div>

  <!-- Мета -->
  <div class="meta-grid">
    <div class="meta-block">
      <h4>🚗 Транспортний засіб</h4>
      <div class="meta-row">
        <span class="meta-lbl">Держ. номер:</span>
        <span contenteditable="true">{esc(num)}</span>
      </div>
      {trailer_row}
    </div>
    <div class="meta-block">
      <h4>👤 Водій</h4>
      <div class="meta-row">
        <span class="meta-lbl">ПІБ:</span>
        <span contenteditable="true">{esc(driver)}</span>
      </div>
    </div>
  </div>

  <!-- Маршрут -->
  <h3 style="margin:24px 0 12px;font-size:15px">📍 Маршрут</h3>
  <table class="route-table">
    <thead><tr>
      <th>Подія</th><th>Дата і час</th>
      <th>Одометр (км)</th><th>Бак (л)</th>
      <th>Час датчика</th>
    </tr></thead>
    <tbody>
      <tr style="background:#e8f5e9">
        <td style="font-weight:700;color:#2e7d32">▶ Виїзд</td>
        <td contenteditable="true">{esc(dt1)}</td>
        <td style="font-weight:700">
          {editable(s1['odo_val'], 'f_odo1')} км
        </td>
        <td style="font-weight:700;color:#0277bd">
          {editable(s1['fuel_val'], 'f_fuel1')} л
        </td>
        <td style="font-size:12px;color:#888">{esc(s1['sensor_dt'])}</td>
      </tr>
      <tr style="background:#ffebee">
        <td style="font-weight:700;color:#c62828">■ Повернення</td>
        <td contenteditable="true">{esc(dt2)}</td>
        <td style="font-weight:700">
          {editable(s2['odo_val'], 'f_odo2')} км
        </td>
        <td style="font-weight:700;color:#0277bd">
          {editable(s2['fuel_val'], 'f_fuel2')} л
        </td>
        <td style="font-size:12px;color:#888">{esc(s2['sensor_dt'])}</td>
      </tr>
    </tbody>
  </table>

  <!-- Підсумки -->
  <h3 style="margin:24px 0 12px;font-size:15px">📊 Підсумки</h3>
  <div class="totals">
    <div class="total-card green">
      <div class="total-val" style="color:#2e7d32">
        {editable(mileage, 'f_mileage')}
      </div>
      <div class="total-lbl">Пробіг, км</div>
    </div>
    <div class="total-card blue">
      <div class="total-val" style="color:#0277bd">
        {editable(fuel1, 'f_fuel_begin')}
      </div>
      <div class="total-lbl">Бак на початку, л</div>
    </div>
    <div class="total-card blue">
      <div class="total-val" style="color:#0277bd">
        {editable(fuel2, 'f_fuel_end')}
      </div>
      <div class="total-lbl">Бак в кінці, л</div>
    </div>
    <div class="total-card red">
      <div class="total-val" style="color:#c62828">
        {editable(consumed, 'f_consumed')}
      </div>
      <div class="total-lbl">Витрачено, л</div>
    </div>
    <div class="total-card purple">
      <div class="total-val" style="color:#667eea">
        {editable(per100, 'f_per100')}
      </div>
      <div class="total-lbl">Витрата л/100км</div>
    </div>
  </div>

  <!-- Підписи -->
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
// ── Очищення при кліку ────────────────────────────────
document.querySelectorAll('[data-num]').forEach(el => {{
  el.addEventListener('focus', function() {{
    this._prev = this.textContent.trim();
    this.textContent = '';
  }});
  el.addEventListener('blur', function() {{
    if (!this.textContent.trim()) this.textContent = this._prev;
  }});
  el.addEventListener('keydown', function(e) {{
    const ok = ['Backspace','Delete','ArrowLeft','ArrowRight',
                'Tab','Enter','.'];
    if (!ok.includes(e.key) && !/^\\d$/.test(e.key)) e.preventDefault();
  }});
}});

// ── Читання/запис числових полів ─────────────────────
function num(id) {{
  const el = document.getElementById(id);
  return el ? parseFloat(el.textContent.replace(/[^\\d.]/g,'')) || 0 : 0;
}}
function set(id, v) {{
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = isFinite(v) ? v.toFixed(1) : '—';
  el.style.background = '#fffde7';
  setTimeout(() => el.style.background = '', 1200);
}}

// ── Перерахунок ───────────────────────────────────────
function recalc() {{
  const odo1  = num('f_odo1');
  const odo2  = num('f_odo2');
  const fuel1 = num('f_fuel_begin') || num('f_fuel1');
  const fuel2 = num('f_fuel_end')   || num('f_fuel2');

  const mileage  = Math.round((odo2 - odo1) * 10) / 10;
  const consumed = Math.round((fuel1 - fuel2) * 10) / 10;
  const per100   = mileage > 0 ? Math.round(consumed / mileage * 1000) / 10 : 0;

  set('f_mileage',    mileage);
  set('f_consumed',   consumed);
  set('f_per100',     per100);
  set('f_fuel_begin', fuel1);
  set('f_fuel_end',   fuel2);

  const hint = document.getElementById('hint');
  hint.textContent = `✅ Перераховано: пробіг ${{mileage}} км | витрата ${{consumed}} л | ${{per100}} л/100км`;
  hint.style.color = '#2e7d32';
  setTimeout(() => {{
    hint.textContent = '💡 Клікніть на будь-яке значення щоб редагувати. Після змін натисніть 🔄 Перерахувати';
    hint.style.color = '';
  }}, 4000);
}}
</script>
</body></html>"""

    return html


# ═══════════════════════════════════════════════════════
#  СТОРІНКА ПОМИЛКИ
# ═══════════════════════════════════════════════════════

def error_page(msg):
    return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="UTF-8">
<style>{CSS} .card{{max-width:460px;text-align:center}}</style></head>
<body><div class="card">
  <div style="font-size:56px;margin-bottom:16px">❌</div>
  <h2 style="color:#c62828;margin-bottom:12px">Помилка</h2>
  <p style="color:#555;margin-bottom:24px">{esc(msg)}</p>
  <a href="/"><button class="btn">◀ Назад</button></a>
</div></body></html>"""


# ═══════════════════════════════════════════════════════
#  HTTP СЕРВЕР
# ═══════════════════════════════════════════════════════

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
        query  = parse_qs(parsed.query)
        path   = parsed.path
        try:
            if path == '/':
                self.send_html(page_form())
            elif path == '/report':
                required = ['idx', 'dt1', 'dt2', 'driver']
                if not all(query.get(k) for k in required):
                    self.send_html(error_page("Не передані параметри"))
                    return
                self.send_html(page_report(query))
            else:
                self.send_html("<h1>404</h1>", 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_html(error_page(f"Внутрішня помилка: {e}"))


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    global vehicles_df

    print("\n" + "=" * 60)
    print("  ПУТЕВИЙ ЛИСТ — веб-застосунок")
    print("=" * 60)

    if not os.path.exists(EXCEL):
        print(f"\n❌ Файл не знайдено: {EXCEL}")
        input("\nEnter для виходу...")
        return

    vehicles_df = pd.read_excel(EXCEL)
    print(f"\n✓ Завантажено ТЗ: {len(vehicles_df)}")
    print(f"  Колонки: {list(vehicles_df.columns)}")

    url = f"http://localhost:{PORT}"
    print(f"\n🚀 Сервер: {url}")
    print("   Ctrl+C — зупинити\n")

    import threading
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    server = HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  Зупинено")


if __name__ == "__main__":
    main()
