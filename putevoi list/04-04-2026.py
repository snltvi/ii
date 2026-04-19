#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПУТЕВОЙ ЛИСТ PRO — Flask Web App
Mobiteam GPS API  |  v2.0
---------------------------------------
Логика:
  1. Пользователь выбирает ТС, вводит дату + показание одометра начала и конца рейса
  2. По одометру ищем точное время выезда и возврата (API /objdata)
  3. Получаем уровень топлива в начале и конце (API /getobjectsfuelinfo)
  4. Получаем список заправок с временем и адресом (API /fuelings)
  5. Получаем стоянки > 1 часа (API /getobjectsreport, split=trip)
  6. Определяем адреса начала/конца/стоянок (API /getaddress)
  7. Рендерим и печатаем путевой лист
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import webbrowser
import threading
import time
from flask import Flask, render_template_string, request, jsonify

# ============================================================================
# НАСТРОЙКИ — измените при необходимости
# ============================================================================
API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
EXCEL_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
PORT       = 8080
STOP_MIN_MINUTES = 60   # стоянка считается если > 60 мин
TIMEZONE_OFFSET  = 3    # UTC+3

# ============================================================================
# API — вспомогательные функции
# ============================================================================

def connect_to_api():
    """Авторизация, возвращает session id"""
    try:
        res = requests.get(f"{API_URL}/connect",
                           params={'login': LOGIN, 'password': PASSWORD,
                                   'lang': 'ru-ru', 'timezone': str(TIMEZONE_OFFSET)},
                           timeout=15)
        return res.headers.get('sessionid') or res.headers.get('SessionId')
    except Exception as e:
        print(f"❌ connect_to_api: {e}")
        return None


def get_address(sid, lat, lon):
    """Обратное геокодирование через API"""
    if not lat or not lon:
        return "адрес не определён"
    try:
        res = requests.get(f"{API_URL}/getaddress",
                           headers={'SessionId': sid},
                           params={'lat': lat, 'lon': lon},
                           timeout=10)
        return res.text.strip().strip('"') or "адрес не определён"
    except:
        return "адрес не определён"


def get_coords_for_time(sid, oid, time_str):
    """Координаты в момент времени (ищем в окне ±30 мин)"""
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    for window_min in [2, 5, 10, 30]:
        try:
            t_from = (dt - timedelta(minutes=window_min)).strftime('%Y-%m-%d %H:%M:%S')
            t_to   = (dt + timedelta(minutes=window_min)).strftime('%Y-%m-%d %H:%M:%S')
            res = requests.get(f"{API_URL}/track",
                               headers={'SessionId': sid},
                               params={'oid': oid, 'from': t_from, 'to': t_to},
                               timeout=10).json()
            pts = res.get('track', [])
            if pts:
                best = min(pts, key=lambda p: abs(
                    datetime.strptime(p['dt'], '%Y-%m-%d %H:%M:%S') - dt))
                return best.get('lat'), best.get('lon')
        except:
            continue
    return None, None


def get_data_by_odo(sid, oid, sensor_id, target_odo, date_str):
    """
    Ищет по данным одометра ближайший момент времени.
    Возвращает {'dt': str, 'odo': float, 'lat': float, 'lon': float, 'addr': str} или None
    """
    print(f"  🔍 Поиск одометра {target_odo} км на {date_str}...")
    try:
        res = requests.get(f"{API_URL}/objdata",
                           headers={'SessionId': sid},
                           params={'oid': oid,
                                   'slist': f's{sensor_id}',
                                   'from': f"{date_str} 00:00:00",
                                   'to':   f"{date_str} 23:59:59"},
                           timeout=25).json()

        records = res.get('obj_data', {}).get('records', [])
        valid   = [r for r in records if len(r) > 1 and r[1] not in (None, '')]

        if not valid:
            # Fallback: getobjectsreport
            rpt = requests.get(f"{API_URL}/getobjectsreport",
                               headers={'SessionId': sid},
                               params={'date_from': f"{date_str} 00:00:00",
                                       'date_to':   f"{date_str} 23:59:59",
                                       'objuids': str(oid),
                                       'split': 'none',
                                       'param': 'start_can_dist;stop_can_dist;can_dist'},
                               timeout=25).json()
            if rpt and rpt[0].get('periods'):
                prms = rpt[0]['periods'][0].get('prms', [])
                start_val = next((float(p['value']) for p in prms if p['name'] == 'start_can_dist' and p.get('value')), None)
                stop_val  = next((float(p['value']) for p in prms if p['name'] == 'stop_can_dist'  and p.get('value')), None)
                # Выбираем ближайший
                candidates = []
                if start_val is not None:
                    candidates.append((start_val, f"{date_str} 00:01:00"))
                if stop_val is not None:
                    candidates.append((stop_val, f"{date_str} 23:58:00"))
                if candidates:
                    best = min(candidates, key=lambda c: abs(c[0] - float(target_odo)))
                    odo_found, dt_found = best
                    lat, lon = get_coords_for_time(sid, oid, dt_found)
                    addr = get_address(sid, lat, lon)
                    print(f"    ✅ fallback report: {odo_found} км в {dt_found}")
                    return {'dt': dt_found, 'odo': round(odo_found, 1), 'lat': lat, 'lon': lon, 'addr': addr}
            print("    ❌ нет данных одометра")
            return None

        best = min(valid, key=lambda r: abs(float(r[1]) - float(target_odo)))
        odo_found = float(best[1])
        dt_found  = best[0]
        diff = abs(odo_found - float(target_odo))
        print(f"    ✅ найдено {odo_found} км в {dt_found} (разница {diff:.1f} км)")

        lat, lon = get_coords_for_time(sid, oid, dt_found)
        addr = get_address(sid, lat, lon)
        return {'dt': dt_found, 'odo': round(odo_found, 1), 'lat': lat, 'lon': lon, 'addr': addr}

    except Exception as e:
        print(f"    ❌ get_data_by_odo: {e}")
        return None


def get_fuel_for_day(sid, oid, date_str):
    """
    Уровень топлива за дату.
    Возвращает {'begin': float, 'end': float, 'refueled': float}
    """
    try:
        res = requests.get(f"{API_URL}/getobjectsfuelinfo",
                           headers={'SessionId': sid},
                           params={'date_from': f"{date_str} 00:00:00",
                                   'date_to':   f"{date_str} 23:59:59",
                                   'objuids': str(oid)},
                           timeout=20).json()
        if not res:
            return None
        obj = res[0]
        begin = end = refueled = 0.0
        has = False
        for s in obj.get('sensors', []):
            nm = s.get('sensor_name', '').lower()
            if any(k in nm for k in ['бак', 'lls', 'fuel', 'tank', 'топлив']):
                begin    += float(s.get('beginLevel', 0))
                end      += float(s.get('endLevel', 0))
                refueled += float(s.get('summ_refuelings', 0) or s.get('refillsSum', 0) or 0)
                has = True
        if not has:
            begin    = float(obj.get('beginLevel', 0))
            end      = float(obj.get('endLevel', 0))
            refueled = float(obj.get('summ_refuelings', 0) or obj.get('refillsSum', 0) or 0)
        return {'begin': round(begin, 1), 'end': round(end, 1), 'refueled': round(refueled, 1)}
    except Exception as e:
        print(f"  ⚠️ get_fuel_for_day({date_str}): {e}")
        return None


def get_fuelings_list(sid, oid, dt_from, dt_to):
    """
    Список заправок за период.
    Возвращает [{'dt': str, 'volume': float, 'lat': float, 'lon': float, 'addr': str}, ...]
    """
    result = []
    try:
        res = requests.get(f"{API_URL}/fuelings",
                           headers={'SessionId': sid},
                           params={'oid': oid,
                                   'from': dt_from,
                                   'to':   dt_to},
                           timeout=20).json()
        if res.get('result') != 'Ok':
            return result
        for ev in res.get('fuelings', []):
            if ev.get('fuel_type') == 'fueling':
                vol = float(ev.get('volume', 0))
                dt  = ev.get('dt', '')
                lat = ev.get('lat') or ev.get('latitude')
                lon = ev.get('lon') or ev.get('longitude')
                if not lat:
                    lat, lon = get_coords_for_time(sid, oid, dt) if dt else (None, None)
                addr = get_address(sid, lat, lon)
                result.append({'dt': dt, 'volume': round(vol, 1), 'lat': lat, 'lon': lon, 'addr': addr})
    except Exception as e:
        print(f"  ⚠️ get_fuelings_list: {e}")
    return result


def get_stops_long(sid, oid, dt_from_str, dt_to_str):
    """
    Стоянки > STOP_MIN_MINUTES за период.
    Пробуем /getobjectsreport?split=trip — пробелы между рейсами = стоянки.
    Возвращает [{'begin': str, 'end': str, 'duration_min': int, 'addr': str}, ...]
    """
    stops = []
    try:
        res = requests.get(f"{API_URL}/getobjectsreport",
                           headers={'SessionId': sid},
                           params={'date_from': dt_from_str,
                                   'date_to':   dt_to_str,
                                   'objuids': str(oid),
                                   'split': 'trip',
                                   'param': 'start_coord;stop_coord;start_time;stop_time'},
                           timeout=30).json()

        if not res or not res[0].get('periods'):
            raise ValueError("нет периодов в split=trip")

        periods = res[0]['periods']
        # Строим список концов рейсов → начал следующих
        trip_times = []
        for p in periods:
            prms = {x['name']: x.get('value') for x in p.get('prms', [])}
            t_start = prms.get('start_time')
            t_stop  = prms.get('stop_time')
            s_coord = prms.get('stop_coord')
            if t_start and t_stop:
                trip_times.append({'start': t_start, 'stop': t_stop, 'stop_coord': s_coord})

        for i in range(len(trip_times) - 1):
            stop_begin = trip_times[i]['stop']
            stop_end   = trip_times[i+1]['start']
            try:
                dt_b = datetime.strptime(stop_begin, '%Y-%m-%d %H:%M:%S')
                dt_e = datetime.strptime(stop_end,   '%Y-%m-%d %H:%M:%S')
                dur  = int((dt_e - dt_b).total_seconds() / 60)
            except:
                continue
            if dur >= STOP_MIN_MINUTES:
                coord = trip_times[i].get('stop_coord', '')
                lat = lon = None
                try:
                    lat, lon = [float(x) for x in str(coord).split(';')]
                except:
                    lat, lon = get_coords_for_time(sid, oid, stop_begin)
                addr = get_address(sid, lat, lon)
                stops.append({
                    'begin': stop_begin,
                    'end':   stop_end,
                    'duration_min': dur,
                    'addr': addr
                })
        print(f"  🅿️  стоянок > {STOP_MIN_MINUTES} мин: {len(stops)}")

    except Exception as e:
        print(f"  ⚠️ get_stops_long (split=trip): {e}. Пробуем parkevent...")
        # Fallback: parkevent
        try:
            res2 = requests.get(f"{API_URL}/parkevent",
                                headers={'SessionId': sid},
                                params={'oid': oid,
                                        'from': dt_from_str,
                                        'to':   dt_to_str},
                                timeout=20).json()
            for ev in (res2.get('parks') or res2 if isinstance(res2, list) else []):
                dur = int(float(ev.get('duration', ev.get('dur', 0))))  # минуты
                if dur >= STOP_MIN_MINUTES:
                    begin = ev.get('begin') or ev.get('dt_begin', '')
                    end   = ev.get('end')   or ev.get('dt_end', '')
                    lat   = ev.get('lat')
                    lon   = ev.get('lon')
                    addr  = get_address(sid, lat, lon)
                    stops.append({'begin': begin, 'end': end, 'duration_min': dur, 'addr': addr})
            print(f"  🅿️  (parkevent) стоянок > {STOP_MIN_MINUTES} мин: {len(stops)}")
        except Exception as e2:
            print(f"  ❌ parkevent: {e2}")

    return stops


def fmt_dur(minutes):
    h = minutes // 60
    m = minutes % 60
    if h > 0:
        return f"{h} ч {m:02d} мин"
    return f"{m} мин"


# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)
vehicles_df = None


# ---------- HTML шаблон формы ----------
FORM_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Путевой лист PRO</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;min-height:100vh;padding:30px 16px}
.wrap{max-width:700px;margin:0 auto}
h1{font-size:22px;font-weight:600;color:#1e293b;margin-bottom:4px}
.sub{font-size:13px;color:#64748b;margin-bottom:24px}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:24px;margin-bottom:16px}
.card h2{font-size:14px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.span2{grid-column:span 2}
label{display:block;font-size:12px;color:#64748b;margin-bottom:4px;font-weight:500}
input,select{width:100%;padding:9px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;color:#1e293b;background:#fff;transition:border .15s}
input:focus,select:focus{outline:none;border-color:#6366f1}
.btn{display:block;width:100%;padding:13px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s;margin-top:8px}
.btn:hover{background:#4f46e5}
.info{font-size:12px;color:#94a3b8;margin-top:8px;text-align:center}
.loader{display:none;text-align:center;padding:40px}
.spinner{width:40px;height:40px;border:4px solid #e0e7ff;border-top-color:#6366f1;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="wrap">
  <h1>🚗 Путевой лист PRO</h1>
  <p class="sub">Mobiteam GPS · Автоматическое заполнение по данным телематики</p>

  <form id="mainForm" action="/generate" method="POST">
    <div class="card">
      <h2>Транспортное средство</h2>
      <div class="grid2">
        <div class="span2">
          <label>Автомобиль / водитель</label>
          <select name="vehicle_idx" required>
            {% for v in vehicles %}
            <option value="{{ v.idx }}">{{ v.num }} — {{ v.fio }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Начало рейса</h2>
      <div class="grid3">
        <div class="span2">
          <label>Дата начала рейса</label>
          <input type="date" name="date_1" required value="{{ today }}">
        </div>
        <div>
          <label>Одометр начала (км)</label>
          <input type="number" name="odo_1" step="0.1" placeholder="100450" required>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Конец рейса</h2>
      <div class="grid3">
        <div class="span2">
          <label>Дата окончания рейса</label>
          <input type="date" name="date_2" required value="{{ today }}">
        </div>
        <div>
          <label>Одометр окончания (км)</label>
          <input type="number" name="odo_2" step="0.1" placeholder="100890" required>
        </div>
      </div>
    </div>

    <button type="submit" class="btn" onclick="showLoader()">⚡ Сформировать путевой лист</button>
    <p class="info">Запрос занимает 10–30 секунд</p>
  </form>

  <div class="loader" id="loader">
    <div class="spinner"></div>
    <p style="color:#6366f1;font-weight:600">Получаем данные из GPS-системы...</p>
    <p style="color:#94a3b8;font-size:13px;margin-top:8px">Поиск по одометру · Топливо · Заправки · Стоянки</p>
  </div>
</div>
<script>
function showLoader(){
  document.getElementById('mainForm').style.display='none';
  document.getElementById('loader').style.display='block';
}
</script>
</body>
</html>
"""


# ---------- HTML шаблон путевого листа ----------
WAYBILL_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Путевой лист — {{ vehicle }} — {{ date_1 }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;font-size:11pt;background:#f0f4f8;padding:24px 16px}
.page{background:#fff;max-width:900px;margin:0 auto;padding:32px 36px;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,.12)}
.noprint{margin-bottom:16px;display:flex;gap:10px}
.noprint button{padding:9px 22px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}
.btn-print{background:#16a34a;color:#fff}
.btn-back{background:#64748b;color:#fff}

/* --- Шапка --- */
.doc-title{text-align:center;margin-bottom:20px}
.doc-title .form-num{font-size:10pt;color:#666;margin-bottom:2px}
.doc-title h1{font-size:16pt;font-weight:700;letter-spacing:.03em}
.doc-title .subtitle{font-size:9pt;color:#888}

/* --- Блоки --- */
.section{margin-bottom:18px}
.section-title{font-size:9pt;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#475569;border-bottom:2px solid #1e293b;padding-bottom:3px;margin-bottom:10px}

/* --- Таблицы --- */
table{width:100%;border-collapse:collapse;font-size:10pt}
th,td{border:1px solid #94a3b8;padding:6px 9px;vertical-align:top}
th{background:#f1f5f9;font-weight:600;text-align:center}
td.lbl{background:#f8fafc;font-weight:600;width:40%;color:#374151}
td.val{color:#1e293b}

/* --- Цветовые акценты --- */
.green{color:#16a34a;font-weight:700}
.red{color:#dc2626;font-weight:700}
.blue{color:#2563eb;font-weight:700}
.yellow td{background:#fef9c3}
.orange td{background:#fff7ed}

/* --- Итоговая строка --- */
.total-row td{background:#1e293b;color:#fff;font-weight:700;font-size:11pt}

/* --- Подписи --- */
.signatures{display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px;margin-top:28px}
.sig{text-align:center}
.sig .line{border-top:1px solid #1e293b;margin-top:28px;padding-top:4px;font-size:9pt;color:#64748b}

@media print{
  body{background:#fff;padding:0}
  .page{box-shadow:none;padding:16px;max-width:100%;border-radius:0}
  .noprint{display:none!important}
  @page{margin:15mm 12mm}
}
</style>
</head>
<body>
<div class="page">

  <div class="noprint">
    <button class="btn-print" onclick="window.print()">🖨 Друкувати / Печать</button>
    <button class="btn-back"  onclick="history.back()">◀ Назад</button>
  </div>

  <!-- ===== ЗАГОЛОВОК ===== -->
  <div class="doc-title">
    <div class="form-num">Форма № 3</div>
    <h1>ПОДОРОЖНІЙ ЛИСТ ЛЕГКОВОГО АВТОМОБІЛЯ</h1>
    <div class="subtitle">Путевой лист легкового автомобиля</div>
  </div>

  <!-- ===== ТС и Водитель ===== -->
  <div class="section">
    <div class="section-title">Транспортний засіб та водій</div>
    <table>
      <tr>
        <td class="lbl">Автомобіль (марка, держ. номер)</td>
        <td class="val"><strong>{{ vehicle }}</strong></td>
        <td class="lbl">Водій (ФІО)</td>
        <td class="val"><strong>{{ driver }}</strong></td>
      </tr>
    </table>
  </div>

  <!-- ===== НАЧАЛО РЕЙСА ===== -->
  <div class="section">
    <div class="section-title">Початок рейсу — Виїзд</div>
    <table>
      <tr>
        <td class="lbl">Дата та час виїзду</td>
        <td class="val green">{{ p1.dt }}</td>
        <td class="lbl">Одометр при виїзді</td>
        <td class="val"><strong>{{ p1.odo }} км</strong></td>
      </tr>
      <tr>
        <td class="lbl">Адреса виїзду</td>
        <td class="val" colspan="3">{{ p1.addr }}</td>
      </tr>
      <tr>
        <td class="lbl">Рівень пального при виїзді</td>
        <td class="val blue">{{ fuel_start }} л</td>
        <td class="lbl">Заправлено за рейс</td>
        <td class="val green">{{ total_refueled }} л {% if total_refueled == 0 %}(заправок не было){% endif %}</td>
      </tr>
    </table>
  </div>

  <!-- ===== КОНЕЦ РЕЙСА ===== -->
  <div class="section">
    <div class="section-title">Кінець рейсу — Повернення</div>
    <table>
      <tr>
        <td class="lbl">Дата та час повернення</td>
        <td class="val red">{{ p2.dt }}</td>
        <td class="lbl">Одометр при поверненні</td>
        <td class="val"><strong>{{ p2.odo }} км</strong></td>
      </tr>
      <tr>
        <td class="lbl">Адреса повернення</td>
        <td class="val" colspan="3">{{ p2.addr }}</td>
      </tr>
      <tr>
        <td class="lbl">Рівень пального при поверненні</td>
        <td class="val blue">{{ fuel_end }} л</td>
        <td class="lbl"></td>
        <td class="val"></td>
      </tr>
    </table>
  </div>

  <!-- ===== ИТОГИ ===== -->
  <div class="section">
    <div class="section-title">Підсумки рейсу</div>
    <table>
      <tr class="yellow">
        <td class="lbl">📏 Пробіг за рейс</td>
        <td class="val" style="font-size:13pt"><strong>{{ mileage }} км</strong></td>
        <td class="lbl">📅 Тривалість рейсу</td>
        <td class="val">{{ duration_str }}</td>
      </tr>
      <tr>
        <td class="lbl">⛽ Пальне на початку</td>
        <td class="val">{{ fuel_start }} л</td>
        <td class="lbl">⛽ Заправлено</td>
        <td class="val green">+ {{ total_refueled }} л</td>
      </tr>
      <tr>
        <td class="lbl">⛽ Пальне в кінці</td>
        <td class="val">{{ fuel_end }} л</td>
        <td class="lbl">🔥 Витрата пального</td>
        <td class="val red">{{ consumption }} л</td>
      </tr>
      <tr class="orange">
        <td class="lbl">📊 Витрата на 100 км</td>
        <td class="val"><strong>{{ consumption_rate }} л/100км</strong></td>
        <td class="lbl">🅿️ Стоянок (&gt;1 год)</td>
        <td class="val">{{ stops|length }} шт.</td>
      </tr>
    </table>
  </div>

  <!-- ===== ЗАПРАВКИ ===== -->
  {% if fuelings %}
  <div class="section">
    <div class="section-title">Заправки за рейс</div>
    <table>
      <tr>
        <th style="width:30%">Дата та час</th>
        <th style="width:15%">Об'єм, л</th>
        <th>Адреса заправки</th>
      </tr>
      {% for f in fuelings %}
      <tr>
        <td>{{ f.dt }}</td>
        <td style="text-align:center" class="green">+{{ f.volume }} л</td>
        <td>{{ f.addr }}</td>
      </tr>
      {% endfor %}
      <tr class="total-row">
        <td>Всього заправлено</td>
        <td style="text-align:center">{{ total_refueled }} л</td>
        <td></td>
      </tr>
    </table>
  </div>
  {% endif %}

  <!-- ===== СТОЯНКИ > 1 ЧАСА ===== -->
  {% if stops %}
  <div class="section">
    <div class="section-title">Стоянки більше 1 години</div>
    <table>
      <tr>
        <th style="width:22%">Початок стоянки</th>
        <th style="width:22%">Кінець стоянки</th>
        <th style="width:15%">Тривалість</th>
        <th>Адреса</th>
      </tr>
      {% for s in stops %}
      <tr>
        <td>{{ s.begin }}</td>
        <td>{{ s.end }}</td>
        <td style="text-align:center"><strong>{{ s.dur_str }}</strong></td>
        <td>{{ s.addr }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% else %}
  <div class="section">
    <div class="section-title">Стоянки більше 1 години</div>
    <p style="color:#94a3b8;font-style:italic;padding:8px 0">Стоянок тривалістю більше 1 години не виявлено</p>
  </div>
  {% endif %}

  <!-- ===== ПОДПИСИ ===== -->
  <div class="signatures">
    <div class="sig">
      <div style="font-size:13px;color:#374151">{{ driver }}</div>
      <div class="line">Водій (підпис)</div>
    </div>
    <div class="sig">
      <div style="font-size:13px;color:#374151">&nbsp;</div>
      <div class="line">Механік (підпис)</div>
    </div>
    <div class="sig">
      <div style="font-size:13px;color:#374151">&nbsp;</div>
      <div class="line">Відповідальна особа</div>
    </div>
  </div>

  <p style="margin-top:24px;font-size:9pt;color:#94a3b8;text-align:right">
    Сформовано: {{ generated_at }} · GPS Mobiteam
  </p>

</div>
</body>
</html>
"""


ERROR_HTML = """
<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>Ошибка</title>
<style>body{font-family:Arial,sans-serif;background:#f0f4f8;padding:40px;text-align:center}
.box{background:#fff;max-width:500px;margin:0 auto;padding:36px;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,.1)}
h2{color:#dc2626;margin-bottom:12px}p{color:#64748b;margin-bottom:24px;font-size:14px}
a{display:inline-block;padding:10px 24px;background:#6366f1;color:#fff;border-radius:8px;text-decoration:none}</style>
</head><body><div class="box">
<h2>❌ {{ error }}</h2><p>{{ detail }}</p>
<a href="/">◀ Назад</a></div></body></html>
"""


# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    global vehicles_df
    vehicles = []
    if vehicles_df is not None:
        for i, row in vehicles_df.iterrows():
            num = str(row.get('Номер авто', '—'))
            fio = str(row.get('ФИО', '—'))
            vehicles.append({'idx': i, 'num': num, 'fio': fio})
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(FORM_HTML, vehicles=vehicles, today=today)


@app.route('/generate', methods=['POST'])
def generate():
    global vehicles_df

    # --- Входные данные ---
    v_idx = int(request.form['vehicle_idx'])
    date_1 = request.form['date_1']    # YYYY-MM-DD
    date_2 = request.form['date_2']
    odo_1  = float(request.form['odo_1'])
    odo_2  = float(request.form['odo_2'])

    car = vehicles_df.iloc[v_idx]
    oid        = int(car['ID объекта'])
    sensor_id  = int(car['SID']) if 'SID' in car and pd.notna(car.get('SID')) else None
    vehicle    = str(car.get('Номер авто', '—'))
    driver     = str(car.get('ФИО', '—'))

    print(f"\n{'='*60}")
    print(f"ПУТЕВОЙ ЛИСТ: {vehicle} | {driver}")
    print(f"Одометр: {odo_1} → {odo_2} км | {date_1} → {date_2}")
    print(f"{'='*60}")

    # --- Авторизация ---
    sid = connect_to_api()
    if not sid:
        return render_template_string(ERROR_HTML,
            error="Ошибка авторизации",
            detail="Не удалось подключиться к GPS API. Проверьте логин/пароль.")

    # --- Поиск по одометру ---
    print("\n[1/4] Поиск по одометру...")
    p1 = get_data_by_odo(sid, oid, sensor_id, odo_1, date_1)
    p2 = get_data_by_odo(sid, oid, sensor_id, odo_2, date_2)

    if not p1 or not p2:
        return render_template_string(ERROR_HTML,
            error="Данные одометра не найдены",
            detail=f"Показания {odo_1} или {odo_2} км не обнаружены в GPS-системе на указанные даты. "
                   f"Проверьте введённые значения и даты.")

    # --- Топливо ---
    print("\n[2/4] Получение уровней топлива...")
    fuel_d1 = get_fuel_for_day(sid, oid, date_1)
    fuel_d2 = get_fuel_for_day(sid, oid, date_2)

    fuel_start = fuel_d1['begin'] if fuel_d1 else 0.0
    fuel_end   = fuel_d2['end']   if fuel_d2 else 0.0
    print(f"  Топливо начало дня {date_1}: {fuel_start} л")
    print(f"  Топливо конец дня  {date_2}: {fuel_end} л")

    # --- Заправки ---
    print("\n[3/4] Получение заправок...")
    dt_from_full = f"{date_1} 00:00:00"
    dt_to_full   = f"{date_2} 23:59:59"
    fuelings_raw = get_fuelings_list(sid, oid, dt_from_full, dt_to_full)
    total_refueled = round(sum(f['volume'] for f in fuelings_raw), 1)
    print(f"  Заправок: {len(fuelings_raw)} шт на {total_refueled} л")

    # --- Стоянки ---
    print("\n[4/4] Получение стоянок > 1 ч...")
    stops_raw = get_stops_long(sid, oid, dt_from_full, dt_to_full)

    # --- Расчёты ---
    mileage = round(p2['odo'] - p1['odo'], 1)
    consumption = round(max(0, fuel_start + total_refueled - fuel_end), 1)
    consumption_rate = round(consumption / mileage * 100, 1) if mileage > 1 else 0.0

    try:
        dt1 = datetime.strptime(p1['dt'], '%Y-%m-%d %H:%M:%S')
        dt2 = datetime.strptime(p2['dt'], '%Y-%m-%d %H:%M:%S')
        delta = dt2 - dt1
        tot_min = int(delta.total_seconds() / 60)
        duration_str = fmt_dur(tot_min)
    except:
        duration_str = "—"

    # Обогащаем стоянки
    stops_enriched = []
    for s in stops_raw:
        stops_enriched.append({**s, 'dur_str': fmt_dur(s['duration_min'])})

    print(f"\n{'='*60}")
    print(f"Пробег:       {mileage} км")
    print(f"Топливо нач.: {fuel_start} л  |  конец: {fuel_end} л")
    print(f"Заправлено:   {total_refueled} л")
    print(f"Расход:       {consumption} л  ({consumption_rate} л/100км)")
    print(f"Стоянок >1ч:  {len(stops_enriched)}")
    print(f"{'='*60}\n")

    return render_template_string(
        WAYBILL_HTML,
        vehicle=vehicle,
        driver=driver,
        p1=p1,
        p2=p2,
        date_1=date_1,
        mileage=mileage,
        fuel_start=fuel_start,
        fuel_end=fuel_end,
        total_refueled=total_refueled,
        consumption=consumption,
        consumption_rate=consumption_rate,
        duration_str=duration_str,
        fuelings=fuelings_raw,
        stops=stops_enriched,
        generated_at=datetime.now().strftime('%d.%m.%Y %H:%M')
    )


# ============================================================================
# MAIN
# ============================================================================

def main():
    global vehicles_df

    print("\n" + "="*60)
    print("  ПУТЕВОЙ ЛИСТ PRO  |  Mobiteam GPS  |  v2.0")
    print("="*60)

    # Поиск Excel с машинами
    excel_candidates = [
        EXCEL_FILE,
        'CAN_пробег_датчики_06_02_2026.xlsx',
        'Датчики_CAN_пробег.xlsx',
    ]
    excel_path = next((f for f in excel_candidates if os.path.exists(f)), None)

    if not excel_path:
        print(f"\n❌ Excel файл не найден!")
        print(f"   Ожидаемые: {excel_candidates}")
        print(f"   Запустите скрипт из папки, где лежит файл.")
        input("Нажмите ENTER...")
        return

    vehicles_df = pd.read_excel(excel_path)
    print(f"\n✅ Загружено {len(vehicles_df)} ТС из «{excel_path}»")
    print(f"   Колонки: {list(vehicles_df.columns)}")

    # Открываем браузер через 1 секунду
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n🌍 Сервер запущен: http://localhost:{PORT}")
    print("   Нажмите Ctrl+C для остановки\n")

    try:
        app.run(host='localhost', port=PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n⏹  Сервер остановлен")


if __name__ == "__main__":
    main()