#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перше рушення авто на задану дату.
1. /track      — знаходимо першу точку з speed > 0
2. /getaddress — адреса за координатами
3. /objectinfo — показання датчиків (одометр, бак) на момент першого руху
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import math
import os
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import webbrowser

# ═══════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════
API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL      = os.path.join(SCRIPT_DIR, "CAN_пробег_датчики_06_02_2026.xlsx")
PORT       = 8082

TZ_UA = timedelta(hours=3)   # Україна UTC+3

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

def local_to_utc(s):
    """Локальний час UA → UTC рядок для API."""
    return ds(dp(s) - TZ_UA)

def utc_str_to_local(s):
    """UTC рядок → локальний час UA."""
    return ds(dp(s) + TZ_UA)

def esc(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def safe_int(v):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return int(v)
    except:
        return None

def safe_sid_odo(row):
    return safe_int(row.get('SID (одометр)')) or safe_int(row.get('SID'))

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


def get_track(sid, oid, local_from, local_to):
    """
    Запит /track.
    Вхід: локальний час UA → конвертуємо в UTC для API.
    Відповідь: coords[{tm(local UA), lat, lon, speed, ...}]
    Повертає список точок з полем dt = локальний час.
    """
    try:
        utc_from = local_to_utc(local_from)
        utc_to   = local_to_utc(local_to)
        print(f"    GET /track  UTC: {utc_from} → {utc_to}")
        r = requests.get(f"{API_URL}/track",
                         headers={'SessionId': sid},
                         params={'oid': oid, 'from': utc_from, 'to': utc_to},
                         timeout=60)
        print(f"    HTTP {r.status_code}")
        if r.status_code != 200:
            return []
        coords = r.json().get('coords', [])
        # tm у відповіді вже в локальному часі UA (session timezone=3)
        for pt in coords:
            if pt.get('tm'):
                pt['dt'] = str(pt['tm']).replace('T', ' ')[:19]
        return coords
    except Exception as e:
        print(f"    get_track error: {e}")
        return []


def get_address(sid, lat, lon):
    try:
        r = requests.get(f"{API_URL}/getaddress",
                         headers={'SessionId': sid},
                         params={'lat': lat, 'lon': lon}, timeout=10)
        addr = r.text.strip().strip('"')
        return addr if addr else "Адреса не визначена"
    except:
        return "Помилка геокодера"


def get_sensors_at_time(sid, oid, local_dt_str):
    """
    /objectinfo з параметром dt (UTC) — повертає показання всіх датчиків
    на момент першого руху.
    Повертає список {sid, name, val} або [].
    """
    try:
        utc_dt = local_to_utc(local_dt_str)
        print(f"    GET /objectinfo  dt(UTC)={utc_dt}")
        r = requests.get(f"{API_URL}/objectinfo",
                         headers={'SessionId': sid},
                         params={'oid': oid, 'dt': utc_dt},
                         timeout=20)
        print(f"    HTTP {r.status_code}")
        if r.status_code != 200:
            return []
        return r.json().get('sensors', [])
    except Exception as e:
        print(f"    get_sensors_at_time error: {e}")
        return []


def parse_sensors(sensors):
    """
    З масиву датчиків витягує одометр і рівень бака.
    Повертає (odo_val, odo_name, fuel_val, fuel_name).
    """
    ODO_KEYS  = ['одометр', 'пробег', 'can абс', 'абсолютн', 'odo', 'can_dist']
    FUEL_KEYS = ['бак', 'lls', 'fuel', 'топлив', 'дут', 'дрт']

    odo_val = odo_name = fuel_val = fuel_name = None

    print(f"    Датчики ({len(sensors)} шт):")
    for s in sensors:
        name = s.get('name', '')
        val  = s.get('val',  '')
        print(f"      {name!r:40s} = {val!r}")

        name_l = name.lower()
        if odo_val is None and any(k in name_l for k in ODO_KEYS):
            try:
                odo_val  = float(str(val).replace(' ', '').replace(',', '.'))
                odo_name = name
            except:
                pass

        if fuel_val is None and any(k in name_l for k in FUEL_KEYS):
            try:
                fuel_val  = float(str(val).replace(' ', '').replace(',', '.'))
                fuel_name = name
            except:
                pass

    return odo_val, odo_name, fuel_val, fuel_name


def find_first_movement(sid, oid, date_str):
    """
    Шукає першу точку з speed > 0 за заданою датою (00:00–23:59 UA).
    Повертає dict {dt, lat, lon, speed} або None.
    """
    day_start = f"{date_str} 00:00:00"
    day_end   = f"{date_str} 23:59:59"

    print(f"  Запит треку: {day_start} → {day_end} (local UA)")
    track = get_track(sid, oid, day_start, day_end)
    print(f"  Точок у треку: {len(track)}")

    if not track:
        return None

    print(f"  Перші 3 точки: {track[:3]}")

    for pt in track:
        if (pt.get('speed') or 0) > 0 and pt.get('lat') and pt.get('lon') and pt.get('dt'):
            return pt

    # Fallback: рух по зміщенню координат якщо speed=0 скрізь
    print("  speed=0 скрізь — шукаю по зміщенню координат...")
    prev = None
    for pt in track:
        if not (pt.get('lat') and pt.get('lon') and pt.get('dt')):
            continue
        if prev is not None:
            if abs(float(pt['lat']) - float(prev['lat'])) > 0.0001 or \
               abs(float(pt['lon']) - float(prev['lon'])) > 0.0001:
                return pt
        prev = pt

    return None

# ═══════════════════════════════════════════════════════
#  HTML
# ═══════════════════════════════════════════════════════

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif;
       background:linear-gradient(135deg,#1e3c72,#2a5298);
       min-height:100vh; padding:30px 20px; }
.card { background:#fff; border-radius:16px;
        box-shadow:0 15px 50px rgba(0,0,0,.3);
        padding:36px; max-width:680px; margin:0 auto; }
h1 { font-size:22px; color:#1e3c72; margin-bottom:6px; }
.sub { color:#888; font-size:13px; margin-bottom:28px; }
label { display:block; font-weight:600; color:#444; margin:16px 0 5px; font-size:14px; }
input, select { width:100%; padding:11px 14px; border:2px solid #ddd; border-radius:9px;
                font-size:14px; font-family:inherit; }
input:focus, select:focus { outline:none; border-color:#2a5298;
                             box-shadow:0 0 0 3px rgba(42,82,152,.12); }
.btn { display:block; width:100%; padding:14px; margin-top:26px;
       background:linear-gradient(135deg,#1e3c72,#2a5298); color:#fff;
       border:none; border-radius:10px; font-size:16px; font-weight:700;
       cursor:pointer; transition:.2s; }
.btn:hover { transform:translateY(-2px); box-shadow:0 8px 25px rgba(30,60,114,.4); }
.block { border-radius:12px; padding:20px 22px; margin-top:16px; }
.block.green { background:#e8f5e9; border:2px solid #4caf50; }
.block.warn  { background:#fff8e1; border:2px solid #ffc107; }
.row { display:flex; gap:8px; margin:8px 0; font-size:14px; align-items:baseline; }
.lbl { color:#666; font-weight:600; min-width:140px; font-size:13px; }
.val { font-weight:700; color:#1e3c72; font-size:15px; }
.spinner-wrap { display:none; text-align:center; padding:30px 0; }
.spinner { display:inline-block; width:44px; height:44px; border:5px solid #ddd;
           border-top-color:#2a5298; border-radius:50%;
           animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
"""


def page_form():
    options = '<option value="">— оберіть ТЗ —</option>\n'
    vlist   = []
    for i, row in vehicles_df.iterrows():
        oid = str(row.get('ID объекта', ''))
        num = str(row.get('Номер авто', f'ID_{oid}'))
        drv = str(row.get('ФИО', ''))
        has = safe_sid_odo(row) is not None
        options += f'<option value="{i}">{num}  —  {drv}</option>\n'
        vlist.append({'idx': i, 'num': num, 'driver': drv, 'has_sid': has})

    today = now_ua().strftime('%Y-%m-%d')

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Перше рушення авто</title>
  <style>{CSS}</style>
</head>
<body>
<div class="card">
  <h1>🚦 Перше рушення авто</h1>
  <p class="sub">Час, місце, одометр та рівень бака на момент першого руху</p>

  <form action="/find" method="get"
        onsubmit="document.getElementById('sp').style.display='block'">
    <label>🚗 Транспортний засіб</label>
    <select name="idx" required onchange="upd(this)">
      {options}
    </select>
    <div id="dinfo" style="font-size:13px;color:#2a5298;margin-top:5px;min-height:18px"></div>

    <label>📅 Дата</label>
    <input type="date" name="date" value="{today}" required>

    <button class="btn" type="submit">🔍 Знайти перше рушення</button>
  </form>

  <div class="spinner-wrap" id="sp">
    <div class="spinner"></div>
    <p style="margin-top:14px;color:#555;font-weight:600">Отримую дані…</p>
  </div>
</div>
<script>
const vlist = {json.dumps(vlist, ensure_ascii=False)};
function upd(sel) {{
  const v = vlist.find(x => x.idx === parseInt(sel.value));
  const d = document.getElementById('dinfo');
  if (!v) {{ d.textContent=''; return; }}
  let t = '👤 ' + (v.driver || 'не вказано');
  if (!v.has_sid) t += '  ⚠️ CAN-датчик не призначений';
  d.textContent = t;
}}
</script>
</body>
</html>"""


def page_result(query):
    idx      = int(query.get('idx',  ['0'])[0])
    date_str = query.get('date', [''])[0]

    if not date_str:
        return page_error("Дата не вказана")

    row    = vehicles_df.iloc[idx]
    oid    = int(row.get('ID объекта') or row.get("ID об'єкта", 0))
    num    = str(row.get('Номер авто', f'ID_{oid}'))
    driver = str(row.get('ФИО', ''))

    print(f"\n{'='*55}")
    print(f"  Авто : {num}")
    print(f"  Водій: {driver}")
    print(f"  Дата : {date_str}  (OID={oid})")

    sid = connect()
    if not sid:
        return page_error("Не вдалося підключитися до API")

    # ── 1. Перше рушення через /track ──
    print("\n  [1] Шукаю перше рушення...")
    pt = find_first_movement(sid, oid, date_str)

    if not pt:
        return _wrap(num, driver, date_str, f"""
        <div class="block warn">
          <div style="font-size:16px;font-weight:700;margin-bottom:8px">⚠️ Рух не знайдено</div>
          <p style="color:#666">Авто <strong>{esc(num)}</strong>
             не рухалося {esc(date_str)}</p>
        </div>""")

    fm_dt  = pt['dt']
    fm_lat = pt.get('lat')
    fm_lon = pt.get('lon')
    fm_spd = pt.get('speed', 0)
    print(f"  → Перше рушення: {fm_dt}  speed={fm_spd} км/год")

    # ── 2. Адреса ──
    print("\n  [2] Отримую адресу...")
    addr = get_address(sid, fm_lat, fm_lon) if fm_lat and fm_lon else "Немає GPS"
    print(f"  → {addr}")

    # ── 3. Показання датчиків через /objectinfo ──
    print("\n  [3] Отримую показання датчиків...")
    sensors = get_sensors_at_time(sid, oid, fm_dt)
    odo_val, odo_name, fuel_val, fuel_name = parse_sensors(sensors)
    print(f"  → Одометр: {odo_val} ({odo_name})")
    print(f"  → Бак:     {fuel_val} ({fuel_name})")
    print(f"{'='*55}\n")

    odo_str  = f"{odo_val:,.0f} км" if odo_val else "—"
    fuel_str = f"{fuel_val:.1f} л"  if fuel_val is not None else "—"
    maps_url = (f"https://www.google.com/maps?q={fm_lat},{fm_lon}"
                if fm_lat and fm_lon else "#")

    content = f"""
    <div class="block green">
      <div style="font-size:16px;font-weight:700;margin-bottom:14px">
        ✅ Перше рушення — {esc(date_str)}
      </div>
      <div class="row">
        <span class="lbl">⏰ Час:</span>
        <span class="val">{esc(fm_dt)}</span>
      </div>
      <div class="row">
        <span class="lbl">📍 Адреса:</span>
        <span class="val">{esc(addr)}
          <a href="{maps_url}" target="_blank"
             style="font-size:12px;margin-left:8px;color:#1a73e8">📍 карта</a>
        </span>
      </div>
      <div class="row">
        <span class="lbl">🔢 Одометр:</span>
        <span class="val">{odo_str}</span>
      </div>
      <div class="row">
        <span class="lbl">⛽ Рівень бака:</span>
        <span class="val">{fuel_str}</span>
      </div>
      <div class="row">
        <span class="lbl">💨 Швидкість:</span>
        <span class="val">{fm_spd} км/год</span>
      </div>
    </div>"""

    return _wrap(num, driver, date_str, content)


def _wrap(num, driver, date_str, content):
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Перше рушення — {esc(num)}</title>
  <style>
    {CSS}
    .meta {{ display:flex; gap:20px; margin-bottom:4px; font-size:14px;
             color:#555; flex-wrap:wrap; }}
    .meta strong {{ color:#1e3c72; }}
  </style>
</head>
<body>
<div class="card">
  <h1>🚦 Перше рушення авто</h1>
  <div class="meta">
    <span>🚗 <strong>{esc(num)}</strong></span>
    <span>👤 <strong>{esc(driver)}</strong></span>
    <span>📅 <strong>{esc(date_str)}</strong></span>
  </div>
  {content}
  <div style="text-align:center;margin-top:22px">
    <a href="/" style="color:#2a5298;font-size:14px;text-decoration:none">◀ Новий пошук</a>
  </div>
</div>
</body>
</html>"""


def page_error(msg):
    return f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="UTF-8">
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

    def log_message(self, fmt, *args):
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
            elif path == '/find':
                if not query.get('idx') or not query.get('date'):
                    self.send_html(page_error("Не передані параметри"))
                    return
                self.send_html(page_result(query))
            else:
                self.send_html("<h1>404</h1>", 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_html(page_error(f"Внутрішня помилка: {e}"))


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    global vehicles_df

    print("\n" + "=" * 55)
    print("  ПЕРШЕ РУШЕННЯ АВТО")
    print("=" * 55)

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
