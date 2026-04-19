#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Веб-форма для формування путевого листа (Mobiteam GPS API)
Запуск:  python waybill_web.py
Браузер: http://localhost:5000
"""

import sys, subprocess

# Auto-install dependencies
for _pkg in ["flask", "requests"]:
    try:
        __import__(_pkg)
    except ImportError:
        print(f"Встановлення {_pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", _pkg, "-q"])

from flask import Flask, request, jsonify
import requests as http
import threading, webbrowser, json
from datetime import datetime, timedelta

app = Flask(__name__)

# ─── Config ────────────────────────────────────────────────────────────────
LOGIN    = "abvprom"
PASSWORD = "29328"
API_URL  = "https://gps.mobiteam.com.ua"
TZ_HOURS = 3   # UTC+3 (Україна)

VEHICLES = [
    {"id": 8666, "plate": "ВН5291РХ", "driver": "Стародуб Сергій Олександрович"},
    {"id": 7281, "plate": "ВН5651РВ", "driver": "Наривончик Олександр Васильович"},
    {"id": 7692, "plate": "ВН4721РН", "driver": "Димоглов Іван Петрович"},
    {"id": 8201, "plate": "ВН7532РС", "driver": "Турків Степан Дмитрович"},
    {"id": 8783, "plate": "ВН5290РХ", "driver": "Демченко Олексій Борисович"},
    {"id": 7312, "plate": "BH4492PT",  "driver": "Кузнецов Сергій Володимирович"},
    {"id": 7250, "plate": "ВН6394РВ", "driver": "Фесечко Олександр Миколайович"},
    {"id": 8124, "plate": "ВН8941РС", "driver": "Ковальчук Олег Петрович"},
    {"id": 8743, "plate": "ВН1575РК", "driver": "Варенчук Сергій Анатолійович"},
    {"id": 8200, "plate": "ВН5685РВ", "driver": "Піх Юрій Олексійович"},
    {"id": 7691, "plate": "ВН4723РН", "driver": "Єждін Олександр"},
    {"id": 7251, "plate": "ВН6395РВ", "driver": "Кирилов Ростислав Михайлович"},
    {"id": 7242, "plate": "ВН3194РС", "driver": ""},
    {"id": 7243, "plate": "ВН3198РС", "driver": ""},
    {"id": 7248, "plate": "ВН6396РВ", "driver": ""},
    {"id": 8123, "plate": "ВН6484РС", "driver": ""},
    {"id": 8161, "plate": "ВН9546РС", "driver": ""},
]

# ─── Session cache ─────────────────────────────────────────────────────────
_sid      = None
_sid_exp  = None
_sid_lock = threading.Lock()

def get_sid():
    global _sid, _sid_exp
    with _sid_lock:
        if _sid and _sid_exp and datetime.now() < _sid_exp:
            return _sid
        try:
            r = http.get(
                f"{API_URL}/api/integration/v1/connect",
                params={"login": LOGIN, "password": PASSWORD,
                        "lang": "ru-ru", "timezone": str(TZ_HOURS)},
                timeout=30,
            )
            if r.status_code == 200:
                sid = r.headers.get("sessionid") or r.headers.get("SessionId")
                if sid:
                    _sid, _sid_exp = sid, datetime.now() + timedelta(minutes=20)
                    return _sid
        except Exception as e:
            print(f"[Auth] {e}")
    return None

# ─── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return PAGE

@app.route("/api/report")
def report():
    df_local = request.args.get("date_from", "")
    dt_local = request.args.get("date_to",   "")
    objuid   = request.args.get("objuid",    "")

    if not (df_local and dt_local and objuid):
        return jsonify({"error": "Не вказані параметри"}), 400

    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        df_utc = datetime.strptime(df_local, fmt) - timedelta(hours=TZ_HOURS)
        dt_utc = datetime.strptime(dt_local, fmt) - timedelta(hours=TZ_HOURS)
    except ValueError as e:
        return jsonify({"error": f"Формат дати: {e}"}), 400

    sid = get_sid()
    if not sid:
        return jsonify({"error": "Помилка авторизації на сервері GPS"}), 500

    params_str = ";".join([
        "start_move_time", "stop_move_time",
        "start_address",   "stop_address",
        "start_can_dist",  "stop_can_dist", "can_dist", "odo_dist",
        "start_fuel_level", "stop_fuel_level", "all_fuel",
    ])
    try:
        r = http.get(
            f"{API_URL}/api/integration/v1/getobjectsreport",
            headers={"SessionId": sid},
            params={
                "date_from": df_utc.strftime(fmt),
                "date_to":   dt_utc.strftime(fmt),
                "objuids":   objuid,
                "split":     "none",
                "param":     params_str,
            },
            timeout=60,
        )
        return jsonify({"ok": True, "data": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── HTML ──────────────────────────────────────────────────────────────────

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Путевий лист</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px;
       background: #e8eaf0; color: #222; min-height: 100vh; }

/* ── FORM ── */
.form-panel { background: #fff; padding: 22px 32px 18px;
              box-shadow: 0 2px 8px rgba(0,0,0,.13); border-bottom: 3px solid #1565c0; }
.form-panel h2 { font-size: 17px; color: #1565c0; margin-bottom: 18px; letter-spacing: .3px; }
.form-row { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 14px; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; color: #777; font-weight: 700;
                    text-transform: uppercase; letter-spacing: .6px; }
select, input[type="date"], input[type="time"], input[type="text"] {
  border: 1px solid #ccc; border-radius: 6px; padding: 8px 11px;
  font-size: 14px; font-family: inherit; outline: none;
  transition: border-color .2s; background: #fff; }
select:focus, input:focus { border-color: #1565c0; }
select { min-width: 370px; cursor: pointer; }
input[type="date"] { min-width: 148px; }
input[type="time"] { min-width: 100px; }
input[readonly] { background: #f4f4f4; color: #999; cursor: default; }

.btn { padding: 9px 26px; border: none; border-radius: 6px; font-size: 14px;
       font-weight: 600; cursor: pointer; transition: background .2s, transform .1s; }
.btn:active { transform: scale(.97); }
.btn-primary   { background: #1565c0; color: #fff; }
.btn-primary:hover { background: #0d47a1; }
.btn-secondary { background: #607d8b; color: #fff; }
.btn-secondary:hover { background: #455a64; }
.btn-print     { background: #2e7d32; color: #fff; }
.btn-print:hover { background: #1b5e20; }

/* ── STATUS ── */
.status-area { padding: 14px 32px; }
.loading { color: #1565c0; font-weight: 600; display: flex; align-items: center; gap: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
.spinner { width: 18px; height: 18px; border: 3px solid #cce; border-top-color: #1565c0;
           border-radius: 50%; animation: spin .7s linear infinite; display: inline-block; }
.error-box { background: #ffebee; border-left: 4px solid #c62828;
             padding: 12px 16px; border-radius: 4px; color: #b71c1c; font-size: 13px; }

/* ── WAYBILL WRAPPER ── */
.waybill-wrapper { padding: 28px 32px 50px; }

/* ── WAYBILL DOC ── */
.waybill { background: #fff; box-shadow: 0 3px 16px rgba(0,0,0,.14);
           max-width: 920px; margin: 0 auto; border: 1px solid #ddd; }

/* Header */
.wb-header { text-align: center; padding: 22px 28px 14px; border-bottom: 2.5px solid #111; }
.wb-header h1 { font-size: 24px; font-weight: 800; letter-spacing: 4px;
                text-transform: uppercase; margin-bottom: 10px; }
.wb-meta { display: flex; justify-content: space-between; padding: 0 4px;
           font-size: 13px; color: #444; flex-wrap: wrap; gap: 6px; }
.wb-meta strong { color: #111; }

/* Section title */
.wb-sec { background: #1565c0; color: #fff; font-weight: 700; font-size: 11px;
          letter-spacing: 1.5px; text-transform: uppercase; padding: 6px 16px; }

/* Two-column move section */
.wb-twocol { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1px solid #d0d0d0; }
.wb-col { }
.wb-col:first-child { border-right: 1px solid #d0d0d0; }
.wb-col-hdr { background: #e3f2fd; color: #0d47a1; font-weight: 700; font-size: 12px;
              text-align: center; padding: 7px; border-bottom: 1px solid #bbdefb; }

/* Generic data row */
.wb-row { display: grid; grid-template-columns: 150px 1fr;
          border-bottom: 1px solid #ececec; min-height: 40px; }
.wb-row:last-child { border-bottom: none; }
.wb-lbl { padding: 8px 12px; font-size: 12px; color: #666; background: #fafafa;
          border-right: 1px solid #ececec; display: flex; align-items: center;
          line-height: 1.3; }

/* 4-column row override */
.wb-row-4 { grid-template-columns: 190px 1fr 190px 1fr; }
.wb-row-4 .wb-lbl:nth-child(3) { border-left: 1px solid #d0d0d0; }

/* Wide row (addresses) */
.wb-row-wide { display: grid; grid-template-columns: 160px 1fr;
               border-bottom: 1px solid #ececec; min-height: 40px; }
.wb-row-wide:last-child { border-bottom: none; }
.wb-row-wide .wb-lbl { border-right: 1px solid #ececec; }

/* Addresses & mileage & fuel blocks */
.wb-block { border-bottom: 1px solid #d0d0d0; }
.wb-block:last-child { border-bottom: none; }

/* Editable cell */
.wb-cell { display: flex; align-items: center; padding: 6px 10px;
           min-height: 40px; position: relative; cursor: pointer;
           transition: background .15s; user-select: none; }
.wb-cell:hover { background: #fffde7; }
.wb-cell:hover .edit-hint { opacity: 1; }
.wb-cell.editing { background: #e8f5e9; cursor: text; }
.cell-val { flex: 1; font-size: 14px; word-break: break-word; line-height: 1.35; }
.cell-val.empty { color: #aaa; font-style: italic; }
.cell-val.derived { color: #1565c0; font-weight: 700; }
.cell-unit { color: #888; font-size: 13px; margin-left: 2px; }
.edit-hint { font-size: 10px; color: #bbb; margin-left: 6px;
             opacity: 0; transition: opacity .2s; white-space: nowrap;
             pointer-events: none; }
.cell-input { flex: 1; border: none; outline: none; background: transparent;
              font-size: 14px; font-family: inherit; color: #111; min-width: 0; }

/* Footer */
.wb-footer { padding: 14px 24px; border-top: 2px solid #111;
             display: flex; justify-content: flex-end; gap: 10px; }

/* ── PRINT ── */
@media print {
  body { background: #fff; }
  .form-panel, .status-area, .waybill-wrapper > *, .wb-footer { display: none !important; }
  .waybill-wrapper { padding: 0; display: block !important; }
  .waybill { box-shadow: none; border: 1px solid #999; display: block !important; }
  .edit-hint { display: none !important; }
  .wb-cell { cursor: default; }
  .wb-cell:hover { background: transparent; }
}
</style>
</head>
<body>

<!-- ═══════════════════ FORM ═══════════════════ -->
<div class="form-panel">
  <h2>&#128203; Формування путевого листа</h2>
  <div class="form-row">
    <div class="form-group" style="flex:1;min-width:280px;">
      <label>Автомобіль / Водій</label>
      <select id="vehicleSelect">
        <option value="">&#8212; Оберіть автомобіль &#8212;</option>
      </select>
    </div>
    <div class="form-group">
      <label>ID об&#700;єкту (objuid)</label>
      <input type="text" id="objuidDisplay" readonly style="width:88px;">
    </div>
  </div>
  <div class="form-row">
    <div class="form-group">
      <label>Дата виїзду</label>
      <input type="date" id="dateFrom">
    </div>
    <div class="form-group">
      <label>Час виїзду</label>
      <input type="time" id="timeFrom" value="00:00">
    </div>
    <div class="form-group" style="margin-left:14px;">
      <label>Дата заїзду</label>
      <input type="date" id="dateTo">
    </div>
    <div class="form-group">
      <label>Час заїзду</label>
      <input type="time" id="timeTo" value="23:59">
    </div>
    <div class="form-group" style="justify-content:flex-end;">
      <label>&nbsp;</label>
      <button class="btn btn-primary" id="generateBtn">&#9658; Сформувати</button>
    </div>
  </div>
</div>

<!-- ═══════════════════ STATUS ═══════════════════ -->
<div class="status-area" id="statusArea" style="display:none;"></div>

<!-- ═══════════════════ WAYBILL ═══════════════════ -->
<div class="waybill-wrapper" id="waybillWrapper" style="display:none;">
  <div class="waybill">

    <!-- Header -->
    <div class="wb-header">
      <h1>Путевий лист</h1>
      <div class="wb-meta">
        <span>Автомобіль:&nbsp;<strong id="wbVehicle">&#8212;</strong></span>
        <span>Водій:&nbsp;<strong id="wbDriver">&#8212;</strong></span>
        <span>Період:&nbsp;<strong id="wbPeriod">&#8212;</strong></span>
      </div>
    </div>

    <!-- ── РУХ ── -->
    <div class="wb-sec">Рух</div>
    <div class="wb-twocol">
      <!-- ВИЇЗД -->
      <div class="wb-col">
        <div class="wb-col-hdr">ВИЇЗД</div>
        <div class="wb-row">
          <div class="wb-lbl">Дата виїзду</div>
          <div class="wb-cell" data-field="date_from">
            <span class="cell-val empty">&#8212;</span>
            <span class="edit-hint">&#9998; ред.</span>
          </div>
        </div>
        <div class="wb-row">
          <div class="wb-lbl">Час початку руху</div>
          <div class="wb-cell" data-field="start_move_time">
            <span class="cell-val empty">&#8212;</span>
            <span class="edit-hint">&#9998; ред.</span>
          </div>
        </div>
      </div>
      <!-- ЗАЇЗД -->
      <div class="wb-col">
        <div class="wb-col-hdr">ЗАЇЗД</div>
        <div class="wb-row">
          <div class="wb-lbl">Дата заїзду</div>
          <div class="wb-cell" data-field="date_to">
            <span class="cell-val empty">&#8212;</span>
            <span class="edit-hint">&#9998; ред.</span>
          </div>
        </div>
        <div class="wb-row">
          <div class="wb-lbl">Час кінця руху</div>
          <div class="wb-cell" data-field="stop_move_time">
            <span class="cell-val empty">&#8212;</span>
            <span class="edit-hint">&#9998; ред.</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Addresses -->
    <div class="wb-block">
      <div class="wb-row-wide">
        <div class="wb-lbl">Адреса виїзду</div>
        <div class="wb-cell" data-field="start_address">
          <span class="cell-val empty">&#8212;</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
      <div class="wb-row-wide">
        <div class="wb-lbl">Адреса заїзду</div>
        <div class="wb-cell" data-field="stop_address">
          <span class="cell-val empty">&#8212;</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
    </div>

    <!-- ── ПРОБІГ ── -->
    <div class="wb-sec">Пробіг</div>
    <div class="wb-block">
      <div class="wb-row wb-row-4">
        <div class="wb-lbl">CAN-пробіг (початок)</div>
        <div class="wb-cell" data-field="start_can_dist">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> км</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
        <div class="wb-lbl">CAN-пробіг (кінець)</div>
        <div class="wb-cell" data-field="stop_can_dist">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> км</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
      <div class="wb-row wb-row-4">
        <div class="wb-lbl">Пробіг за рейс (CAN)</div>
        <div class="wb-cell" data-field="can_dist">
          <span class="cell-val empty derived">&#8212;</span><span class="cell-unit"> км</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
        <div class="wb-lbl">Пробіг (одометр)</div>
        <div class="wb-cell" data-field="odo_dist">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> км</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
    </div>

    <!-- ── ПАЛИВО ── -->
    <div class="wb-sec">Паливо</div>
    <div class="wb-block">
      <div class="wb-row wb-row-4">
        <div class="wb-lbl">Рівень (початок)</div>
        <div class="wb-cell" data-field="start_fuel_level">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> л</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
        <div class="wb-lbl">Рівень (кінець)</div>
        <div class="wb-cell" data-field="stop_fuel_level">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> л</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
      <div class="wb-row">
        <div class="wb-lbl">Загальний витрата</div>
        <div class="wb-cell" data-field="all_fuel">
          <span class="cell-val empty">&#8212;</span><span class="cell-unit"> л</span>
          <span class="edit-hint">&#9998; ред.</span>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="wb-footer">
      <button class="btn btn-secondary" id="clearBtn">&#10005; Очистити</button>
      <button class="btn btn-print" onclick="window.print()">&#128438; Друк</button>
    </div>

  </div><!-- .waybill -->
</div><!-- .waybill-wrapper -->

<script>
'use strict';

const VEHICLES = VEHICLES_JSON_PLACEHOLDER;

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  date_from: '', date_to: '',
  start_move_time: '', stop_move_time: '',
  start_address: '', stop_address: '',
  start_can_dist: '', stop_can_dist: '', can_dist: '', odo_dist: '',
  start_fuel_level: '', stop_fuel_level: '', all_fuel: '',
};

// ── Boot ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Populate dropdown
  const sel = document.getElementById('vehicleSelect');
  VEHICLES.forEach(v => {
    const opt = document.createElement('option');
    opt.value          = v.id;
    opt.dataset.plate  = v.plate;
    opt.dataset.driver = v.driver;
    opt.textContent    = v.driver
      ? `DAF ${v.plate}  \u2014  ${v.driver}`
      : `DAF ${v.plate}`;
    sel.appendChild(opt);
  });

  // Default dates = today
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('dateFrom').value = today;
  document.getElementById('dateTo').value   = today;

  // Vehicle change → update objuid display
  sel.addEventListener('change', () => {
    document.getElementById('objuidDisplay').value = sel.value;
  });

  document.getElementById('generateBtn').addEventListener('click', generate);
  document.getElementById('clearBtn').addEventListener('click', () => {
    document.getElementById('waybillWrapper').style.display = 'none';
    document.getElementById('statusArea').style.display = 'none';
  });

  initCells();
});

// ── Generate ──────────────────────────────────────────────────────────────
async function generate() {
  const sel      = document.getElementById('vehicleSelect');
  const dateFrom = document.getElementById('dateFrom').value;
  const dateTo   = document.getElementById('dateTo').value;
  const timeFrom = document.getElementById('timeFrom').value || '00:00';
  const timeTo   = document.getElementById('timeTo').value   || '23:59';
  const objuid   = sel.value;

  if (!objuid)          { alert('Оберіть автомобіль!'); return; }
  if (!dateFrom || !dateTo) { alert('Вкажіть дати!');  return; }

  const dfLocal = `${dateFrom} ${timeFrom}:00`;
  const dtLocal = `${dateTo}   ${timeTo}:00`.replace(/\s+/, ' ');

  setStatus('<div class="loading"><span class="spinner"></span> Завантаження даних з GPS-сервера…</div>');

  try {
    const params = new URLSearchParams({ date_from: dfLocal, date_to: dtLocal, objuid });
    const resp   = await fetch(`/api/report?${params}`);
    const result = await resp.json();
    if (result.error) throw new Error(result.error);

    const parsed = parseApiResponse(result.data, dateFrom, dateTo);
    Object.assign(state, parsed);
    renderWaybill(sel);
    clearStatus();
  } catch (e) {
    setStatus(`<div class="error-box">&#9888; Помилка: ${e.message}</div>`);
  }
}

// ── Parse ─────────────────────────────────────────────────────────────────
function parseApiResponse(apiData, dateFrom, dateTo) {
  const res = {
    date_from: dateFrom, date_to: dateTo,
    start_move_time: '', stop_move_time: '',
    start_address: '', stop_address: '',
    start_can_dist: '', stop_can_dist: '', can_dist: '', odo_dist: '',
    start_fuel_level: '', stop_fuel_level: '', all_fuel: '',
  };

  if (!apiData || !apiData.length) return res;
  const period = (apiData[0].periods || [])[0];
  if (!period) return res;

  (period.prms || []).forEach(p => {
    if (p.name in res && p.value != null) res[p.name] = String(p.value);
  });

  // Keep only HH:MM from datetime strings
  res.start_move_time = toHHMM(res.start_move_time);
  res.stop_move_time  = toHHMM(res.stop_move_time);

  // Auto-calc can_dist if API didn't return it
  if (!res.can_dist) {
    const s = parseFloat(res.start_can_dist);
    const e = parseFloat(res.stop_can_dist);
    if (!isNaN(s) && !isNaN(e)) res.can_dist = (e - s).toFixed(3);
  }

  return res;
}

// ── Render ────────────────────────────────────────────────────────────────
function renderWaybill(sel) {
  const opt = sel.selectedOptions[0];
  document.getElementById('wbVehicle').textContent = `DAF ${opt.dataset.plate}`;
  document.getElementById('wbDriver').textContent  = opt.dataset.driver || '\u2014';
  document.getElementById('wbPeriod').textContent  =
    `${fmtDate(state.date_from)} \u2014 ${fmtDate(state.date_to)}`;

  document.querySelectorAll('.wb-cell[data-field]').forEach(cell => {
    const f = cell.dataset.field;
    setDisplay(cell, f, state[f] || '');
  });

  document.getElementById('waybillWrapper').style.display = 'block';
  document.getElementById('waybillWrapper').scrollIntoView({ behavior: 'smooth' });
}

function setDisplay(cell, field, value) {
  if (cell.classList.contains('editing')) return;
  const span = cell.querySelector('.cell-val');
  if (!span) return;

  const display = (field === 'date_from' || field === 'date_to') ? fmtDate(value) : value;
  span.textContent = display || '\u2014';
  span.classList.toggle('empty',   !display);
  span.classList.toggle('derived', field === 'can_dist');
}

// ── Editable cells ────────────────────────────────────────────────────────
function initCells() {
  document.querySelectorAll('.wb-cell[data-field]').forEach(cell => {
    cell.addEventListener('click', () => startEdit(cell));
  });
}

function startEdit(cell) {
  if (cell.classList.contains('editing')) return;
  cell.classList.add('editing');

  const field  = cell.dataset.field;
  const span   = cell.querySelector('.cell-val');
  const unit   = cell.querySelector('.cell-unit');
  const hint   = cell.querySelector('.edit-hint');
  const curVal = state[field] || '';

  const inp = document.createElement('input');
  inp.className   = 'cell-input';
  inp.type        = 'text';
  inp.value       = '';              // clear on edit — user starts fresh
  inp.placeholder = curVal || 'введіть значення';

  if (span) span.style.display = 'none';
  if (unit) unit.style.display = 'none';
  if (hint) hint.style.display = 'none';
  // Insert input before the hint (or at end if no hint)
  const anchor = hint || null;
  cell.insertBefore(inp, anchor);
  inp.focus();

  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    finishEdit(cell, field, inp.value.trim(), curVal);
  };

  inp.addEventListener('blur', finish);
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') { inp.value = ''; inp.blur(); }
  });
}

function finishEdit(cell, field, newVal, oldVal) {
  cell.classList.remove('editing');

  const inp  = cell.querySelector('.cell-input');
  const span = cell.querySelector('.cell-val');
  const unit = cell.querySelector('.cell-unit');
  const hint = cell.querySelector('.edit-hint');

  if (inp)  inp.remove();
  if (span) span.style.display = '';
  if (unit) unit.style.display = '';
  if (hint) hint.style.display = '';

  // Save non-empty value; keep old if user pressed Escape / left blank
  if (newVal !== '') state[field] = newVal;

  // Recalculate derived fields after any edit
  recalc();

  setDisplay(cell, field, state[field] || '');
}

function recalc() {
  // can_dist = stop_can_dist - start_can_dist (auto)
  const s = parseFloat(state.start_can_dist);
  const e = parseFloat(state.stop_can_dist);
  if (!isNaN(s) && !isNaN(e) && (state.start_can_dist || state.stop_can_dist)) {
    state.can_dist = (e - s).toFixed(3);
  }
  // Update can_dist cell on screen
  const cdCell = document.querySelector('[data-field="can_dist"]');
  if (cdCell && !cdCell.classList.contains('editing')) {
    setDisplay(cdCell, 'can_dist', state.can_dist);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────
function toHHMM(dt) {
  if (!dt) return '';
  const m = String(dt).match(/(\d{2}:\d{2})/);
  return m ? m[1] : dt;
}

function fmtDate(d) {
  if (!d) return '';
  const m = String(d).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : d;
}

function setStatus(html) {
  const el = document.getElementById('statusArea');
  el.innerHTML = html;
  el.style.display = 'block';
}

function clearStatus() {
  const el = document.getElementById('statusArea');
  el.innerHTML = '';
  el.style.display = 'none';
}
</script>
</body>
</html>"""

# Embed vehicles list into the page
PAGE = PAGE_TEMPLATE.replace(
    "VEHICLES_JSON_PLACEHOLDER",
    json.dumps(VEHICLES, ensure_ascii=False)
)

# ─── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = 5000
    print("=" * 55)
    print("  Сервер путевих листів")
    print(f"  Відкрийте: http://localhost:{port}")
    print("  Зупинка: Ctrl+C")
    print("=" * 55)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
