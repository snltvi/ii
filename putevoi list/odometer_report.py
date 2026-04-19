#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Визначення показань одометра на початок/кінець періоду та пробігу.
Використовує /getobjectsreport (start_can_dist, stop_can_dist, can_dist).
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import json
import os
import webbrowser
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

# ════════════════════════════════════════════════════════
API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
PORT       = 8087
TZ_UA      = timedelta(hours=3)

_objects = []
# ════════════════════════════════════════════════════════


def now_ua():
    return datetime.now(timezone.utc).replace(tzinfo=None) + TZ_UA

def ds(d):  return d.strftime('%Y-%m-%d %H:%M:%S')
def dp(s):  return datetime.strptime(str(s).replace('T', ' ')[:19], '%Y-%m-%d %H:%M:%S')
def norm_dt(s):
    s = str(s).replace('T', ' ').strip()
    return s + ':00' if len(s) == 16 else s
def esc(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
def safe_float(v):
    try:
        s = str(v).replace(' ','').replace(',','.').replace('\xa0','')
        return float(s)
    except Exception:
        return None
def fmt(v, dec=1):
    if v is None: return '—'
    return f"{v:,.{dec}f}".replace(',', ' ')


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
                objs.append({'oid': n.get('real_id') or n.get('id'),
                             'name': n.get('name', '')})
            if n.get('children'):
                walk(n['children'])
    walk(r.json().get('children', []))
    return objs

def get_report(sid, oid, dt1_local, dt2_local):
    """Запит /getobjectsreport, повертає dict параметрів."""
    date_from = ds(dp(dt1_local) - TZ_UA)
    date_to   = ds(dp(dt2_local) - TZ_UA)
    params_req = (
        'start_can_dist;stop_can_dist;can_dist;odo_dist;dist;'
        'start_fuel_level;stop_fuel_level;all_fuel;fuelings;drains;'
        'start_address;stop_address;start_coords;stop_coords;'
        'start_move_time;stop_move_time;duration;run_time;stop_time;'
        'max_speed;avg_speed;driver'
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
            return None, f"HTTP {r.status_code}: {r.text[:300]}"
        data = r.json()
        if not data:
            return None, "Порожня відповідь від API"
        periods = data[0].get('periods', [])
        if not periods:
            return None, "Немає даних за вказаний період"
        row = next((p for p in periods if p.get('isTotal')), periods[0])
        result = {'obj_name': data[0].get('obj_name', '')}
        for prm in row.get('prms', []):
            result[prm['name']] = prm['value']
        return result, None
    except Exception as e:
        return None, str(e)

def sec_to_hm(sec):
    if not sec: return '—'
    try:
        s = int(float(sec))
        return f"{s//3600}г {(s%3600)//60}хв"
    except Exception:
        return '—'


# ════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif;
       background:linear-gradient(135deg,#1a237e,#4a148c);
       min-height:100vh; padding:28px 16px; }
.card { background:#fff; border-radius:16px;
        box-shadow:0 15px 50px rgba(0,0,0,.3);
        padding:36px; max-width:680px; margin:0 auto; }
.result { background:#fff; border-radius:16px;
          box-shadow:0 15px 50px rgba(0,0,0,.3);
          padding:40px; max-width:860px; margin:0 auto; }
h1 { font-size:22px; color:#333; margin-bottom:6px; }
h2 { font-size:18px; color:#1a237e; margin:28px 0 14px; }
.sub { color:#888; font-size:13px; margin-bottom:26px; }
label { display:block; font-weight:600; color:#444; margin:16px 0 5px; font-size:14px; }
select, input { width:100%; padding:11px 14px;
                border:2px solid #e0e0e0; border-radius:9px;
                font-size:14px; font-family:inherit; background:#fff; }
select:focus, input:focus { outline:none; border-color:#1a237e;
    box-shadow:0 0 0 3px rgba(26,35,126,.12); }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.btn { display:block; width:100%; padding:14px; margin-top:24px;
       background:linear-gradient(135deg,#1a237e,#4a148c); color:#fff;
       border:none; border-radius:10px; font-size:16px; font-weight:700;
       cursor:pointer; transition:.2s; }
.btn:hover { transform:translateY(-2px); box-shadow:0 8px 25px rgba(26,35,126,.4); }
.spinner-wrap { display:none; text-align:center; padding:24px; }
.spinner { display:inline-block; width:42px; height:42px;
           border:5px solid #ddd; border-top-color:#1a237e;
           border-radius:50%; animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }

/* ── Odo cards ── */
.odo-row { display:grid; grid-template-columns:1fr 40px 1fr; gap:16px;
           align-items:center; margin:20px 0; }
.odo-card { border:2px solid #e0e0e0; border-radius:12px; padding:20px;
            text-align:center; }
.odo-card.start { border-color:#1a237e; background:#e8eaf6; }
.odo-card.end   { border-color:#4a148c; background:#f3e5f5; }
.odo-label { font-size:11px; text-transform:uppercase; letter-spacing:1px;
             color:#888; margin-bottom:8px; font-weight:600; }
.odo-val { font-size:32px; font-weight:700; color:#1a237e; }
.odo-val.end { color:#4a148c; }
.odo-arrow { font-size:28px; color:#999; text-align:center; }

.big-dist { background:linear-gradient(135deg,#1a237e,#4a148c);
            border-radius:14px; padding:28px; text-align:center;
            color:#fff; margin:20px 0; }
.big-dist .val { font-size:52px; font-weight:700; margin:8px 0 4px; }
.big-dist .lbl { font-size:13px; opacity:.8; text-transform:uppercase; letter-spacing:1px; }

.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px; margin:20px 0; }
.stat  { border:1px solid #e0e0e0; border-radius:10px; padding:14px; text-align:center; }
.stat .v { font-size:20px; font-weight:700; color:#333; margin:6px 0 2px; }
.stat .l { font-size:11px; color:#888; text-transform:uppercase; letter-spacing:.5px; }

.addr-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:16px 0; }
.addr-box { border:1px solid #e0e0e0; border-radius:10px; padding:14px; font-size:13px; }
.addr-box .ah { font-size:11px; font-weight:700; text-transform:uppercase;
                color:#888; letter-spacing:.5px; margin-bottom:6px; }
.addr-box .av { color:#333; line-height:1.4; }

.fuel-row { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin:16px 0; }
.fuel-card { border-radius:10px; padding:16px; text-align:center; }
.fuel-card.f1 { border:2px solid #0277bd; background:#e3f2fd; }
.fuel-card.f2 { border:2px solid #2e7d32; background:#e8f5e9; }
.fuel-card.fc { border:2px solid #c62828; background:#ffebee; }
.fuel-val { font-size:24px; font-weight:700; margin:6px 0 2px; }
.fuel-lbl { font-size:11px; color:#777; text-transform:uppercase; letter-spacing:.5px; }

.warn { background:#fff8e1; border-left:4px solid #ffc107;
        padding:10px 14px; border-radius:6px; margin:12px 0; font-size:13px; }
.info { background:#e8eaf6; border-left:4px solid #1a237e;
        padding:10px 14px; border-radius:6px; margin:12px 0; font-size:13px; }
.tbtn { padding:10px 22px; border:none; border-radius:8px; font-size:14px;
        font-weight:600; cursor:pointer; transition:.2s; margin:4px; }
.tbtn:hover { transform:translateY(-1px); box-shadow:0 4px 12px rgba(0,0,0,.2); }
.toolbar { text-align:center; margin-bottom:20px; }
@media print {
  body { background:#fff; padding:0; }
  .result { box-shadow:none; }
  .toolbar,.no-print { display:none !important; }
}
"""


# ════════════════════════════════════════════════════════
#  СТОРІНКИ
# ════════════════════════════════════════════════════════

def page_form():
    opts = '<option value="">— оберіть авто —</option>\n'
    for obj in _objects:
        opts += f'<option value="{obj["oid"]}">{esc(obj["name"])}</option>\n'

    now  = now_ua()
    d1   = (now - timedelta(days=7)).strftime('%Y-%m-%dT00:00')
    d2   = now.strftime('%Y-%m-%dT23:59')

    return f"""<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Одометр за період</title><style>{CSS}</style></head><body>
<div class="card">
  <h1>🛣️ Одометр за період</h1>
  <p class="sub">Визначення показань одометра на початок/кінець та пробіг за CAN-даними</p>

  <form action="/result" method="get"
        onsubmit="document.getElementById('sp').style.display='block'">

    <label>🚗 Транспортний засіб</label>
    <select name="oid" required>
      {opts}
    </select>

    <div class="row2">
      <div>
        <label>📅 Дата початку</label>
        <input type="datetime-local" name="dt1" value="{d1}" required>
      </div>
      <div>
        <label>📅 Дата кінця</label>
        <input type="datetime-local" name="dt2" value="{d2}" required>
      </div>
    </div>

    <button class="btn" type="submit">🔍 Визначити пробіг →</button>
  </form>

  <div class="spinner-wrap" id="sp">
    <div class="spinner"></div>
    <p style="margin-top:14px;color:#555;font-weight:600">Запит до сервера…</p>
  </div>
</div></body></html>"""


def page_result(query):
    oid = int(query.get('oid', ['0'])[0])
    dt1 = norm_dt(query.get('dt1', [''])[0])
    dt2 = norm_dt(query.get('dt2', [''])[0])

    obj_name = next((o['name'] for o in _objects if o['oid'] == oid), str(oid))

    print(f"\n{'='*60}")
    print(f"  {obj_name}  OID={oid}")
    print(f"  {dt1}  →  {dt2}")

    sid = connect()
    if not sid:
        return error_page("Не вдалося підключитися до API")

    rep, err = get_report(sid, oid, dt1, dt2)
    if err:
        return error_page(f"Помилка API: {err}")

    print(f"  Відповідь: {json.dumps(rep, ensure_ascii=False)}")

    # ── Одометр ──
    odo_start = safe_float(rep.get('start_can_dist'))
    odo_end   = safe_float(rep.get('stop_can_dist'))
    can_dist  = safe_float(rep.get('can_dist'))
    gps_dist  = safe_float(rep.get('dist'))
    odo_dist  = safe_float(rep.get('odo_dist'))

    # Пробіг: CAN > одометр > GPS
    mileage = can_dist or odo_dist or gps_dist or 0.0

    # ── Паливо ──
    fuel_start = safe_float(rep.get('start_fuel_level'))
    fuel_end   = safe_float(rep.get('stop_fuel_level'))
    all_fuel   = safe_float(rep.get('all_fuel'))
    fuelings   = safe_float(rep.get('fuelings'))
    drains     = safe_float(rep.get('drains'))

    # ── Час ──
    start_time = rep.get('start_move_time', dt1)
    stop_time  = rep.get('stop_move_time',  dt2)
    duration   = rep.get('duration')
    run_time   = rep.get('run_time')
    stop_time_s= rep.get('stop_time')

    # ── Адреси ──
    start_addr = rep.get('start_address', '—')
    stop_addr  = rep.get('stop_address',  '—')

    # ── Швидкість ──
    max_spd = safe_float(rep.get('max_speed'))
    avg_spd = safe_float(rep.get('avg_speed'))

    driver = rep.get('driver', '')

    print(f"  odo_start={odo_start}  odo_end={odo_end}  can_dist={can_dist}")
    print(f"  fuel_start={fuel_start}  fuel_end={fuel_end}  all_fuel={all_fuel}")
    print(f"{'='*60}\n")

    # ── Попередження ──
    warns = ''
    if odo_start is None and odo_end is None:
        warns += '<div class="warn">⚠️ CAN-одометр недоступний. '
        if gps_dist:
            warns += f'Показано пробіг по GPS: {fmt(gps_dist)} км</div>'
        else:
            warns += 'Дані відсутні.</div>'
    if mileage == 0:
        warns += '<div class="warn">⚠️ Пробіг = 0. Можливо авто не рухалось у цей період.</div>'

    # ── Джерело пробігу ──
    if can_dist:
        dist_source = 'CAN-одометр'
    elif odo_dist:
        dist_source = 'Одометр ТЗ'
    else:
        dist_source = 'GPS'

    # ── Блок одометра ──
    if odo_start is not None or odo_end is not None:
        odo_block = f"""
<div class="odo-row">
  <div class="odo-card start">
    <div class="odo-label">📍 Одометр на початок</div>
    <div class="odo-val">{fmt(odo_start, 1)}</div>
    <div style="font-size:12px;color:#666;margin-top:6px">км</div>
    <div style="font-size:11px;color:#888;margin-top:4px">{esc(start_time)}</div>
  </div>
  <div class="odo-arrow">→</div>
  <div class="odo-card end">
    <div class="odo-label">🏁 Одометр на кінець</div>
    <div class="odo-val end">{fmt(odo_end, 1)}</div>
    <div style="font-size:12px;color:#666;margin-top:6px">км</div>
    <div style="font-size:11px;color:#888;margin-top:4px">{esc(stop_time)}</div>
  </div>
</div>"""
    else:
        odo_block = '<div class="info">ℹ️ Показання CAN-одометра на початок/кінець недоступні для цього авто</div>'

    # ── Блок палива ──
    if fuel_start is not None or all_fuel is not None:
        fuel_block = f"""
<h2>⛽ Паливо</h2>
<div class="fuel-row">
  <div class="fuel-card f1">
    <div class="fuel-val" style="color:#0277bd">{fmt(fuel_start)}</div>
    <div class="fuel-lbl">Бак на початку, л</div>
  </div>
  <div class="fuel-card f2">
    <div class="fuel-val" style="color:#2e7d32">{fmt(fuel_end)}</div>
    <div class="fuel-lbl">Бак в кінці, л</div>
  </div>
  <div class="fuel-card fc">
    <div class="fuel-val" style="color:#c62828">{fmt(all_fuel)}</div>
    <div class="fuel-lbl">Витрачено, л</div>
  </div>
</div>"""
        if fuelings:
            fuel_block += f'<div class="info">⛽ Заправок: <strong>{fmt(fuelings)} л</strong></div>'
        if drains:
            fuel_block += f'<div class="warn">🚨 Зливів: <strong>{fmt(drains)} л</strong></div>'
    else:
        fuel_block = ''

    # ── Адреси ──
    addr_block = f"""
<h2>📍 Маршрут</h2>
<div class="addr-row">
  <div class="addr-box">
    <div class="ah">▶ Початок руху</div>
    <div class="av">{esc(start_addr)}</div>
    <div style="font-size:11px;color:#999;margin-top:4px">{esc(start_time)}</div>
  </div>
  <div class="addr-box">
    <div class="ah">■ Кінець руху</div>
    <div class="av">{esc(stop_addr)}</div>
    <div style="font-size:11px;color:#999;margin-top:4px">{esc(stop_time)}</div>
  </div>
</div>"""

    now_str = now_ua().strftime('%d.%m.%Y %H:%M')

    return f"""<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Одометр — {esc(obj_name)}</title><style>{CSS}</style></head><body>
<div class="result">

  <div class="toolbar no-print">
    <button class="tbtn" style="background:#1a237e;color:#fff"
            onclick="window.print()">🖨️ Друк / PDF</button>
    <a href="/" style="text-decoration:none">
      <button class="tbtn" style="background:#9e9e9e;color:#fff">◀ Назад</button>
    </a>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
    <div>
      <h1 style="font-size:24px;color:#1a237e">🛣️ {esc(obj_name)}</h1>
      <div style="color:#888;font-size:13px;margin-top:4px">
        Період: <strong>{esc(dt1)}</strong> — <strong>{esc(dt2)}</strong>
      </div>
      {f'<div style="color:#555;font-size:13px;margin-top:2px">Водій: <strong>{esc(driver)}</strong></div>' if driver else ''}
    </div>
    <div style="font-size:12px;color:#bbb">Сформовано: {now_str}</div>
  </div>

  {warns}

  <!-- Одометр -->
  <h2>🔢 Одометр ({dist_source})</h2>
  {odo_block}

  <!-- Пробіг -->
  <div class="big-dist">
    <div class="lbl">Пробіг за період ({dist_source})</div>
    <div class="val">{fmt(mileage, 1)} км</div>
  </div>

  <!-- Статистика -->
  <div class="stats">
    <div class="stat">
      <div class="v">{sec_to_hm(duration)}</div>
      <div class="l">Тривалість</div>
    </div>
    <div class="stat">
      <div class="v">{sec_to_hm(run_time)}</div>
      <div class="l">Час руху</div>
    </div>
    <div class="stat">
      <div class="v">{sec_to_hm(stop_time_s)}</div>
      <div class="l">Час стоянок</div>
    </div>
    <div class="stat">
      <div class="v">{fmt(max_spd, 0)} км/г</div>
      <div class="l">Макс. швидкість</div>
    </div>
    <div class="stat">
      <div class="v">{fmt(avg_spd, 0)} км/г</div>
      <div class="l">Сер. швидкість</div>
    </div>
    <div class="stat">
      <div class="v">{fmt(all_fuel and mileage and all_fuel/mileage*100, 1)}</div>
      <div class="l">л / 100 км</div>
    </div>
  </div>

  {fuel_block}
  {addr_block}

</div></body></html>"""


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
        try:
            if path == '/':
                self.send_html(page_form())
            elif path == '/result':
                if not q.get('oid') or not q.get('dt1') or not q.get('dt2'):
                    self.send_html(error_page("Не передані параметри"))
                    return
                self.send_html(page_result(q))
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
    print("  ОДОМЕТР ЗА ПЕРІОД")
    print("=" * 60)

    print("\n[1] Підключення до API...")
    sid = connect()
    if not sid:
        print("❌ Не вдалося підключитися")
        input("\nEnter для виходу...")
        return
    print(f"    OK  sid={sid[:12]}...")

    print("[2] Завантаження списку ТЗ...")
    _objects = get_all_objects(sid)
    print(f"    OK: {len(_objects)} авто")

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
