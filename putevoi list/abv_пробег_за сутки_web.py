#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расчет суточного пробега - ВЕБ-ВЕРСИЯ
Flask + Bootstrap интерфейс
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import webbrowser
from flask import Flask, render_template_string, request, send_file
from io import BytesIO

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
EXCEL_FILES = ['CAN_пробег_датчики_06_02_2026.xlsx', 'Датчики_CAN_пробег.xlsx']
PORT = 8080

app = Flask(__name__)
vehicles_df = None

# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def connect_to_api():
    """Подключение к API"""
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '+2'}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.headers.get('sessionid')
    except:
        return None


def get_mileage_from_report(session_id, oid, date_from_utc, date_to_utc):
    """Метод 1: getobjectsreport"""
    url = f"{API_BASE_URL}/getobjectsreport"
    
    params = {
        'date_from': date_from_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'date_to': date_to_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'objuids': str(oid),
        'split': 'none',
        'param': 'start_can_dist;stop_can_dist;can_dist'
    }
    
    headers = {'SessionId': session_id}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data or len(data) == 0:
            return None, None, None
        
        obj_data = data[0]
        periods = obj_data.get('periods', [])
        
        if len(periods) == 0:
            return None, None, None
        
        period = periods[0]
        prms = period.get('prms', [])
        
        start_can_dist = None
        stop_can_dist = None
        can_dist = None
        
        for prm in prms:
            name = prm.get('name')
            value = prm.get('value')
            
            if name == 'start_can_dist' and value:
                start_can_dist = float(value)
            elif name == 'stop_can_dist' and value:
                stop_can_dist = float(value)
            elif name == 'can_dist' and value:
                can_dist = float(value)
        
        if can_dist is not None and can_dist > 0:
            return start_can_dist, stop_can_dist, can_dist
        
        return None, None, None
        
    except:
        return None, None, None


def get_mileage_from_objdata(session_id, oid, sensor_id, date_from_str, date_to_str):
    """Метод 2: objdata"""
    url = f"{API_BASE_URL}/objdata"
    
    params = {
        'oid': oid,
        'slist': f's{sensor_id}',
        'from': date_from_str,
        'to': date_to_str
    }
    
    headers = {'SessionId': session_id}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get('result') != 'Ok':
            return None, None, None
        
        records = data.get('obj_data', {}).get('records', [])
        
        if not records:
            return None, None, None
        
        valid_records = [rec for rec in records if len(rec) >= 2 and rec[1] and str(rec[1]).strip()]
        
        if not valid_records:
            return None, None, None
        
        value_start = float(valid_records[0][1])
        value_end = float(valid_records[-1][1])
        mileage = value_end - value_start
        
        return value_start, value_end, mileage
        
    except:
        return None, None, None


def get_mileage_hybrid(session_id, oid, sensor_id, target_date):
    """Гибридный метод"""
    date_from_local = target_date.replace(hour=0, minute=0, second=0)
    date_to_local = target_date.replace(hour=23, minute=59, second=59)
    date_from_utc = date_from_local - timedelta(hours=2)
    date_to_utc = date_to_local - timedelta(hours=2)
    
    date_str = target_date.strftime('%Y-%m-%d')
    date_from_str = f"{date_str} 00:00:00"
    date_to_str = f"{date_str} 23:59:00"
    
    # Метод 1
    odo_start, odo_end, mileage = get_mileage_from_report(session_id, oid, date_from_utc, date_to_utc)
    
    if mileage is not None:
        return odo_start, odo_end, mileage, 'report'
    
    # Метод 2
    if sensor_id:
        odo_start, odo_end, mileage = get_mileage_from_objdata(
            session_id, oid, sensor_id, date_from_str, date_to_str
        )
        
        if mileage is not None:
            return odo_start, odo_end, mileage, 'objdata'
    
    return None, None, None, None


# ============================================================================
# HTML ШАБЛОНЫ
# ============================================================================

MAIN_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Расчёт суточного пробега</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 40px 20px;
        }
        .card {
            border: none;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .card-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 20px 20px 0 0 !important;
            padding: 25px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            padding: 12px 30px;
            font-weight: bold;
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        .form-label {
            font-weight: 600;
            color: #495057;
        }
        .info-box {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container" style="max-width: 800px;">
        <div class="card">
            <div class="card-header">
                <h3 class="mb-0 text-center">📊 Расчёт суточного пробега</h3>
                <p class="mb-0 text-center" style="opacity: 0.9;">Mobiteam API - Гибридный метод</p>
            </div>
            <div class="card-body p-4">
                <form action="/calculate" method="POST">
                    <div class="mb-4">
                        <label for="date" class="form-label">📅 Дата для расчёта:</label>
                        <input type="date" class="form-control form-control-lg" id="date" name="date" 
                               value="{{ default_date }}" required>
                    </div>

                    <div class="info-box">
                        <h6>ℹ️ Информация:</h6>
                        <ul class="mb-0">
                            <li>Загружено <strong>{{ total_vehicles }}</strong> транспортных средств</li>
                            <li>Используется гибридный метод (report + objdata)</li>
                            <li>Результаты будут доступны для скачивания в Excel</li>
                        </ul>
                    </div>

                    <div class="d-grid mt-4">
                        <button type="submit" class="btn btn-primary btn-lg">
                            🚀 Рассчитать пробег
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

RESULTS_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Результаты расчёта</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 40px 20px;
        }
        .card {
            border: none;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .card-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 20px 20px 0 0 !important;
            padding: 25px;
        }
        .table-responsive {
            max-height: 500px;
            overflow-y: auto;
        }
        .stats-card {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 15px;
        }
        .stats-value {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
        }
        .stats-label {
            color: #6c757d;
            font-size: 14px;
        }
        .badge-method {
            font-size: 11px;
            padding: 4px 8px;
        }
        .btn-download {
            background: #28a745;
            color: white;
            border: none;
            padding: 12px 30px;
            font-weight: bold;
        }
        .btn-download:hover {
            background: #218838;
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="card-header">
                <h3 class="mb-0 text-center">✅ Результаты расчёта за {{ date }}</h3>
            </div>
            <div class="card-body p-4">
                <!-- Статистика -->
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="stats-card">
                            <div class="stats-value">{{ total }}</div>
                            <div class="stats-label">Всего ТС</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-card">
                            <div class="stats-value text-success">{{ success }}</div>
                            <div class="stats-label">Успешно</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-card">
                            <div class="stats-value text-danger">{{ failed }}</div>
                            <div class="stats-label">Нет данных</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-card">
                            <div class="stats-value">{{ total_mileage }}</div>
                            <div class="stats-label">Общий км</div>
                        </div>
                    </div>
                </div>

                <!-- Методы -->
                <div class="alert alert-info">
                    <strong>📊 Статистика методов:</strong>
                    <span class="badge bg-primary ms-2">report: {{ method_report }}</span>
                    <span class="badge bg-success ms-2">objdata: {{ method_objdata }}</span>
                </div>

                <!-- Таблица результатов -->
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead class="table-light">
                            <tr>
                                <th style="width: 50px;">№</th>
                                <th>Автомобиль</th>
                                <th>Водитель</th>
                                <th>Пробег, км</th>
                                <th>Метод</th>
                                <th>Статус</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in results %}
                            <tr>
                                <td>{{ loop.index }}</td>
                                <td><strong>{{ row['vehicle'] }}</strong></td>
                                <td>{{ row['driver'] }}</td>
                                <td>
                                    {% if row['mileage'] > 0 %}
                                        <span class="badge bg-success">{{ "%.1f"|format(row['mileage']) }} км</span>
                                    {% else %}
                                        <span class="text-muted">-</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if row['method'] == 'report' %}
                                        <span class="badge badge-method bg-primary">report</span>
                                    {% elif row['method'] == 'objdata' %}
                                        <span class="badge badge-method bg-success">objdata</span>
                                    {% else %}
                                        <span class="text-muted">-</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if row['status'] == 'OK' %}
                                        <span class="badge bg-success">✓ OK</span>
                                    {% elif row['status'] == 'Нет данных' %}
                                        <span class="badge bg-danger">✗ Нет данных</span>
                                    {% else %}
                                        <span class="badge bg-warning text-dark">⚠ {{ row['status'] }}</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <!-- Кнопки -->
                <div class="d-flex gap-2 mt-4">
                    <a href="/download/{{ filename }}" class="btn btn-download">
                        📥 Скачать Excel
                    </a>
                    <a href="/" class="btn btn-secondary">
                        ◀️ Назад
                    </a>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

PROCESSING_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Обработка...</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .processing-card {
            background: white;
            padding: 50px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
        }
        .spinner-border {
            width: 4rem;
            height: 4rem;
        }
    </style>
    <meta http-equiv="refresh" content="2;url=/status">
</head>
<body>
    <div class="processing-card">
        <div class="spinner-border text-primary mb-4" role="status"></div>
        <h4>⏳ Обработка данных...</h4>
        <p class="text-muted mb-0">Это может занять несколько секунд</p>
    </div>
</body>
</html>
"""

# ============================================================================
# FLASK ROUTES
# ============================================================================

calculation_results = None

@app.route('/')
def index():
    """Главная страница"""
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(
        MAIN_PAGE,
        default_date=today,
        total_vehicles=len(vehicles_df) if vehicles_df is not None else 0
    )


@app.route('/calculate', methods=['POST'])
def calculate():
    """Запуск расчёта"""
    global calculation_results
    
    date_str = request.form['date']
    target_date = datetime.strptime(date_str, '%Y-%m-%d')
    
    # Подключение к API
    print(f"\n{'='*60}")
    print(f"РАСЧЁТ ПРОБЕГА ЗА {target_date.strftime('%d.%m.%Y')}")
    print(f"{'='*60}\n")
    
    session_id = connect_to_api()
    
    if not session_id:
        return "❌ Ошибка подключения к API", 500
    
    # Расчёт пробега
    results = []
    method_stats = {'report': 0, 'objdata': 0, 'failed': 0}
    
    for idx, row in vehicles_df.iterrows():
        oid = int(row['ID объекта'])
        sensor_id = int(row['SID']) if 'SID' in row and pd.notna(row['SID']) else None
        driver = row.get('ФИО', '')
        vehicle_number = row.get('Номер авто', '')
        
        print(f"  {idx+1}. {driver} ({vehicle_number})...", end=' ')
        
        try:
            odo_start, odo_end, mileage, method = get_mileage_hybrid(
                session_id, oid, sensor_id, target_date
            )
            
            if mileage is None:
                print("НЕТ ДАННЫХ")
                method_stats['failed'] += 1
                status = 'Нет данных'
                mileage_value = 0.0
            else:
                method_stats[method] += 1
                mileage_value = round(mileage, 1)
                
                if mileage < 0 or mileage > 2000:
                    print(f"⚠️ {mileage_value} км [{method}]")
                    status = 'Проверить'
                else:
                    print(f"✓ {mileage_value} км [{method}]")
                    status = 'OK'
            
            results.append({
                'vehicle': vehicle_number,
                'driver': driver,
                'mileage': mileage_value,
                'method': method,
                'status': status,
                'odo_start': round(odo_start, 2) if odo_start else None,
                'odo_end': round(odo_end, 2) if odo_end else None
            })
            
        except Exception as e:
            print(f"ОШИБКА: {e}")
            method_stats['failed'] += 1
            results.append({
                'vehicle': vehicle_number,
                'driver': driver,
                'mileage': 0.0,
                'method': None,
                'status': 'Ошибка'
            })
    
    print(f"\n{'='*60}\n")
    
    # Создание Excel файла
    output_file = f"Пробег_{date_str}.xlsx"
    
    # Подготовка данных для Excel
    excel_data = []
    for r in results:
        excel_data.append({
            'Номер авто': r['vehicle'],
            'ФИО': r['driver'],
            'Одометр начало (км)': r['odo_start'],
            'Одометр конец (км)': r['odo_end'],
            'Пробег (км)': r['mileage'],
            'Метод': r['method'],
            'Статус': r['status']
        })
    
    df_result = pd.DataFrame(excel_data)
    df_result.to_excel(output_file, index=False)
    
    # Сохраняем результаты
    calculation_results = {
        'date': date_str,
        'results': results,
        'stats': method_stats,
        'filename': output_file
    }
    
    # Статистика
    total_mileage = sum(r['mileage'] for r in results)
    
    return render_template_string(
        RESULTS_PAGE,
        date=target_date.strftime('%d.%m.%Y'),
        results=results,
        total=len(results),
        success=method_stats['report'] + method_stats['objdata'],
        failed=method_stats['failed'],
        total_mileage=f"{total_mileage:,.1f}",
        method_report=method_stats['report'],
        method_objdata=method_stats['objdata'],
        filename=output_file
    )


@app.route('/download/<filename>')
def download(filename):
    """Скачивание Excel файла"""
    if os.path.exists(filename):
        return send_file(
            filename,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    return "Файл не найден", 404


# ============================================================================
# MAIN
# ============================================================================

def main():
    global vehicles_df
    
    print("\n" + "="*70)
    print("  ╔════════════════════════════════════════════════════════════╗")
    print("  ║   РАСЧЁТ СУТОЧНОГО ПРОБЕГА - ВЕБ-ВЕРСИЯ                   ║")
    print("  ║   Flask + Bootstrap интерфейс                             ║")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print("="*70)
    
    # Поиск Excel файла
    excel_file = None
    for filename in EXCEL_FILES:
        if os.path.exists(filename):
            excel_file = filename
            break
    
    if not excel_file:
        print("\n✗ Excel файл не найден!")
        print(f"\nОжидаемые имена: {', '.join(EXCEL_FILES)}")
        return
    
    # Загрузка данных
    vehicles_df = pd.read_excel(excel_file)
    print(f"\n✓ Загружено {len(vehicles_df)} ТС из {excel_file}")
    
    # Запуск сервера
    print(f"\n🚀 Сервер запущен: http://localhost:{PORT}")
    print("\n💡 Нажмите Ctrl+C для остановки\n")
    
    webbrowser.open(f"http://localhost:{PORT}")
    
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\n\n⏹️  Сервер остановлен")


if __name__ == "__main__":
    main()
