import requests
import pandas as pd
import os
import webbrowser
from datetime import datetime
from flask import Flask, render_template_string, request, send_file

# --- НАСТРОЙКИ ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = 'CAN_пробег_датчики_06_02_2026.xlsx'
PORT = 8080

app = Flask(__name__)

def get_sid():
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '2'}
    try:
        res = requests.get(url, params=params, timeout=10)
        return res.headers.get('sessionid')
    except: return None

# --- HTML ШАБЛОН (Улучшен под твой стиль) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Контрольный отчет ДУТ</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f4f7f6; padding: 20px; font-family: 'Segoe UI', sans-serif; }
        .card { border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border: none; }
        .table thead { background: linear-gradient(135deg, #1e293b, #334155); color: white; }
        .refill-row { color: #28a745; font-weight: bold; }
        .consumption-row { color: #dc3545; font-weight: bold; }
        .stat-box { background: white; padding: 15px; border-radius: 10px; text-align: center; border-left: 5px solid #0d6efd; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="card p-4 mb-4">
            <h2 class="text-center">⛽ Мониторинг топлива: ДУТ и Заправки</h2>
            <form action="/calculate" method="POST" class="row g-3 justify-content-center mt-3">
                <div class="col-auto"><input type="date" name="date" class="form-control form-control-lg" value="{{ date }}" required></div>
                <div class="col-auto"><button type="submit" class="btn btn-primary btn-lg">Сформировать отчет</button></div>
            </form>
        </div>

        {% if results %}
        <div class="row mb-4">
            <div class="col-md-4"><div class="stat-box"><h5>Всего заправлено</h5><h3 class="refill-row">{{ total_refills }} л</h3></div></div>
            <div class="col-md-4"><div class="stat-box"><h5>Общий расход</h5><h3 class="consumption-row">{{ total_cons }} л</h3></div></div>
            <div class="col-md-4"><div class="stat-box"><h5>Общий пробег</h5><h3>{{ total_mileage }} км</h3></div></div>
        </div>

        <div class="card p-3">
            <table class="table table-hover align-middle">
                <thead>
                    <tr>
                        <th>Транспорт</th>
                        <th class="text-end">Пробег (км)</th>
                        <th class="text-end">Начало (л)</th>
                        <th class="text-end">Конец (л)</th>
                        <th class="text-end">Заправки (л)</th>
                        <th class="text-end">Расход (л)</th>
                        <th class="text-end">Ср. расход</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in results %}
                    <tr>
                        <td><strong>{{ r.name }}</strong></td>
                        <td class="text-end">{{ r.mileage }}</td>
                        <td class="text-end">{{ r.start }}</td>
                        <td class="text-end">{{ r.end }}</td>
                        <td class="text-end refill-row">{% if r.refills > 0 %}+{{ r.refills }}{% else %}-{% endif %}</td>
                        <td class="text-end consumption-row">{{ r.consumption }}</td>
                        <td class="text-end"><span class="badge bg-dark">{{ r.avg }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/calculate', methods=['POST'])
def calculate():
    day = request.form['date']
    df_input = pd.read_excel(INPUT_FILE)
    ids_str = ";".join([str(int(x)) for x in df_input['ID объекта'].dropna().unique()])
    sid = get_sid()

    url = f"{API_BASE_URL}/getobjectsfuelinfo"
    params = {'date_from': f"{day} 00:00:00", 'date_to': f"{day} 23:59:59", 'objuids': ids_str}
    
    try:
        res = requests.get(url, params=params, headers={'SessionId': sid}).json()
        report = []
        t_refills, t_cons, t_mileage = 0, 0, 0

        for obj in res:
            s_list = obj.get('sensors', [])
            start, end, refills = 0, 0, 0
            
            # Поиск данных по всем типам датчиков топлива из твоего списка
            for s in s_list:
                name = s['sensor_name'].lower()
                # Включаем "Бак", "LLS", "Сумматор", "Топливо"
                if any(x in name for x in ["бак", "lls", "сумматор", "топливо"]) and not any(x in name for x in ["°", "temp", "заряд"]):
                    start += s.get('beginLevel', 0)
                    end += s.get('endLevel', 0)
                    # Проверяем все возможные ключи заправок
                    refills += s.get('refillsSum', 0) or s.get('refills_sum', 0) or 0

            # Дополнительная проверка заправок из общего поля объекта
            if refills == 0:
                refills = obj.get('refills_sum', 0) or obj.get('refillsSum', 0) or 0

            # SMART LOGIC: Если уровень вырос, а заправка не зафиксирована API
            diff = end - start
            if diff > 10 and refills < diff: # Порог 10 литров для DAF
                refills = diff

            consumption = (start - end) + refills
            if consumption < 0: consumption = 0
            
            mileage = obj.get('mileage', 0)
            avg = (consumption / mileage * 100) if mileage > 5 else 0
            
            # Итоги для шапки
            t_refills += refills
            t_cons += consumption
            t_mileage += mileage

            report.append({
                'name': obj.get('object_name'),
                'mileage': round(mileage, 1),
                'start': round(start, 1),
                'end': round(end, 1),
                'refills': round(refills, 1),
                'consumption': round(consumption, 1),
                'avg': round(avg, 1)
            })
        
        report.sort(key=lambda x: x['name'])
        return render_template_string(HTML_TEMPLATE, 
                                     results=report, 
                                     date=day,
                                     total_refills=round(t_refills, 1),
                                     total_cons=round(t_cons, 1),
                                     total_mileage=round(t_mileage, 1))
    except Exception as e:
        return f"Ошибка API: {e}"

if __name__ == "__main__":
    webbrowser.open(f"http://localhost:{PORT}")
    app.run(port=PORT)