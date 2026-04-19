import requests
import pandas as pd
import os
import re
import webbrowser

# --- НАСТРОЙКИ ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = 'CAN_пробег_датчики_06_02_2026.xlsx'

def get_sid():
    """Подключение к API"""
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: 
        return None


def get_tank_volume(oid, sid):
    """
    Определяет объем бака из названия датчика через API
    Ищет числа 400-1500 л в названии датчика топлива
    """
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", 
                          params={'oid': oid}, 
                          headers={'SessionId': sid}, 
                          timeout=10)
        data = res.json()
        
        for sensor in data.get('obj_sensors', []):
            name = sensor.get('name', '').lower()
            
            # Проверяем что это датчик топлива
            if any(keyword in name for keyword in ['бак', 'lls', 'fuel', 'tank', 'топлив']):
                # Ищем числа от 100 до 2000 (реалистичный объем бака)
                volumes = re.findall(r'\b(\d{3,4})\b', name)
                
                if volumes:
                    # Берем самое большое число (обычно это объем)
                    possible_volumes = [int(v) for v in volumes if 100 <= int(v) <= 2000]
                    if possible_volumes:
                        return max(possible_volumes)
        
        # Если не нашли, пробуем по типу ТС из имени объекта
        obj_info = requests.get(f"{API_BASE_URL}/getobjectsstate",
                               params={'objuids': str(oid)},
                               headers={'SessionId': sid},
                               timeout=10).json()
        
        if obj_info:
            obj_name = obj_info[0].get('name', '').upper()
            
            # Эвристика по типу ТС
            if any(brand in obj_name for brand in ['DAF', 'MAN', 'SCANIA', 'VOLVO', 'MERCEDES']):
                return 800  # Грузовики обычно 600-1000 л
            elif any(brand in obj_name for brand in ['SPRINTER', 'IVECO']):
                return 100  # Фургоны ~100 л
            
    except Exception as e:
        print(f"      ⚠️  Ошибка определения бака для OID {oid}: {e}")
    
    # По умолчанию для грузовиков
    return 600


def main():
    print("=" * 70)
    print("⛽ ОТЧЁТ ПО ТОПЛИВУ С ОБЪЁМОМ БАКОВ")
    print("=" * 70)
    
    # Подключение
    sid = get_sid()
    if not sid: 
        print("❌ Ошибка авторизации")
        input("\nНажмите Enter...")
        return
    
    print("✓ Подключено к API")
    
    # Проверка файла
    if not os.path.exists(INPUT_FILE): 
        print(f"❌ Файл {INPUT_FILE} не найден")
        input("\nНажмите Enter...")
        return
    
    df_input = pd.read_excel(INPUT_FILE)
    print(f"✓ Загружено {len(df_input)} записей из {INPUT_FILE}")
    
    ids_list = df_input['ID объекта'].dropna().unique()
    
    # Сбор информации об объемах баков
    print(f"\n📡 Определение объёмов баков для {len(ids_list)} ТС...")
    tank_map = {}
    
    for i, oid in enumerate(ids_list, 1):
        oid = int(oid)
        print(f"\r   Обработка: {i}/{len(ids_list)}...", end='', flush=True)
        tank_map[oid] = get_tank_volume(oid, sid)
    
    print(f"\n✓ Объёмы баков определены")
    
    # Ввод периода
    print("\n" + "-" * 70)
    print("ПЕРИОД РЕЙСА")
    print("-" * 70)
    print("Формат: ГГГГ-ММ-ДД ЧЧ:ММ:СС")
    
    d_start = input("📅 НАЧАЛО: ").strip()
    d_end = input("📅 КОНЕЦ:  ").strip()
    
    # Запрос данных по топливу
    print(f"\n📊 Запрос данных по топливу за период...")
    
    ids_str = ";".join([str(int(x)) for x in ids_list])
    
    try:
        fuel_data = requests.get(
            f"{API_BASE_URL}/getobjectsfuelinfo", 
            params={'date_from': d_start, 'date_to': d_end, 'objuids': ids_str},
            headers={'SessionId': sid},
            timeout=60
        ).json()
        
        print(f"✓ Получены данные по {len(fuel_data)} ТС")
    
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
        input("\nНажмите Enter...")
        return
    
    # Создание карты водителей
    driver_map = pd.Series(df_input['ФИО'].values, index=df_input['ID объекта']).to_dict()
    
    # Обработка результатов
    results = []
    
    for obj in fuel_data:
        oid = obj.get('object_id')
        obj_name = obj.get('object_name', 'N/A')
        
        # Суммируем по всем датчикам топлива
        t_start, t_end = 0, 0
        
        for sensor in obj.get('sensors', []):
            sensor_name = sensor.get('sensor_name', '').lower()
            if any(keyword in sensor_name for keyword in ["бак", "lls", "fuel", "tank"]):
                t_start += sensor.get('beginLevel', 0)
                t_end += sensor.get('endLevel', 0)
        
        # Объем бака
        tank_volume = tank_map.get(oid, 600)
        
        # Разница (расход или заправка)
        diff = t_end - t_start
        
        # Процент заполнения
        if tank_volume > 0 and t_end > 0:
            fill_percent = min(100, int((t_end / tank_volume) * 100))
        else:
            fill_percent = 0
        
        results.append({
            'Водитель': driver_map.get(oid, "—"),
            'Автомобиль': obj_name,
            'Объём бака (л)': tank_volume,
            'Топливо начало (л)': round(t_start, 1),
            'Топливо конец (л)': round(t_end, 1),
            'Изменение (л)': round(diff, 1),
            'Заполнение (%)': fill_percent,
            'ID объекта': oid
        })
    
    # Создание DataFrame
    df_results = pd.DataFrame(results)
    
    # Сортировка по автомобилю
    df_results = df_results.sort_values('Автомобиль')
    
    # --- СОХРАНЕНИЕ В EXCEL ---
    excel_file = f"Отчёт_Топливо_{d_start.replace(':', '-').replace(' ', '_')}.xlsx"
    
    try:
        df_results.to_excel(excel_file, index=False)
        print(f"\n✓ Excel сохранён: {excel_file}")
    except Exception as e:
        print(f"\n⚠️  Ошибка сохранения Excel: {e}")
    
    # --- СОЗДАНИЕ HTML ---
    html = f"""
    <html>
    <head>
        <meta charset='UTF-8'>
        <style>
            body {{ 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px; 
                margin: 0;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .card {{ 
                background: white; 
                padding: 30px; 
                border-radius: 15px; 
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                margin-bottom: 20px;
            }}
            h2 {{
                color: #333;
                margin: 0 0 10px 0;
                font-size: 28px;
            }}
            .period {{
                color: #666;
                font-size: 14px;
                margin-bottom: 20px;
            }}
            table {{ 
                width: 100%; 
                border-collapse: collapse; 
                font-size: 14px;
            }}
            thead {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}
            th {{ 
                padding: 15px 10px; 
                text-align: left; 
                font-weight: 600;
                text-transform: uppercase;
                font-size: 12px;
                letter-spacing: 0.5px;
            }}
            td {{ 
                padding: 12px 10px; 
                border-bottom: 1px solid #f0f0f0; 
            }}
            tr:hover {{
                background: #f8f9ff;
            }}
            .tank-volume {{ 
                font-weight: bold; 
                color: #667eea;
                font-size: 16px;
            }}
            .fuel-change {{
                font-weight: bold;
            }}
            .fuel-change.positive {{
                color: #28a745;
            }}
            .fuel-change.negative {{
                color: #dc3545;
            }}
            .progress-bar {{ 
                background: #e9ecef; 
                width: 100px; 
                height: 12px; 
                border-radius: 6px; 
                display: inline-block;
                position: relative;
                overflow: hidden;
            }}
            .progress-fill {{ 
                background: linear-gradient(90deg, #28a745 0%, #20c997 100%);
                height: 100%; 
                border-radius: 6px;
                transition: width 0.3s ease;
            }}
            .progress-text {{
                margin-left: 10px;
                font-weight: 600;
                color: #495057;
            }}
            .stats {{
                display: flex;
                gap: 20px;
                margin-top: 20px;
                flex-wrap: wrap;
            }}
            .stat-card {{
                background: #f8f9ff;
                padding: 15px 20px;
                border-radius: 10px;
                flex: 1;
                min-width: 200px;
            }}
            .stat-value {{
                font-size: 24px;
                font-weight: bold;
                color: #667eea;
            }}
            .stat-label {{
                font-size: 12px;
                color: #666;
                text-transform: uppercase;
                margin-top: 5px;
            }}
        </style>
    </head>
    <body>
        <div class='container'>
            <div class='card'>
                <h2>⛽ Отчёт по топливу</h2>
                <div class='period'>Период: {d_start} — {d_end}</div>
                
                <table>
                    <thead>
                        <tr>
                            <th>Водитель</th>
                            <th>Автомобиль</th>
                            <th>📦 Объём бака</th>
                            <th>Начало</th>
                            <th>Конец</th>
                            <th>Изменение</th>
                            <th>Заполнение</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for _, row in df_results.iterrows():
        change_class = "positive" if row['Изменение (л)'] > 0 else "negative"
        change_sign = "+" if row['Изменение (л)'] > 0 else ""
        
        html += f"""
                        <tr>
                            <td>{row['Водитель']}</td>
                            <td>{row['Автомобиль']}</td>
                            <td class='tank-volume'>{row['Объём бака (л)']} л</td>
                            <td>{row['Топливо начало (л)']} л</td>
                            <td>{row['Топливо конец (л)']} л</td>
                            <td class='fuel-change {change_class}'>{change_sign}{row['Изменение (л)']} л</td>
                            <td>
                                <div class='progress-bar'>
                                    <div class='progress-fill' style='width:{row['Заполнение (%)']}%'></div>
                                </div>
                                <span class='progress-text'>{row['Заполнение (%)']}%</span>
                            </td>
                        </tr>
        """
    
    # Статистика
    total_vehicles = len(df_results)
    avg_tank = df_results['Объём бака (л)'].mean()
    total_fuel_start = df_results['Топливо начало (л)'].sum()
    total_fuel_end = df_results['Топливо конец (л)'].sum()
    total_change = df_results['Изменение (л)'].sum()
    
    html += f"""
                    </tbody>
                </table>
                
                <div class='stats'>
                    <div class='stat-card'>
                        <div class='stat-value'>{total_vehicles}</div>
                        <div class='stat-label'>Транспортных средств</div>
                    </div>
                    <div class='stat-card'>
                        <div class='stat-value'>{avg_tank:.0f} л</div>
                        <div class='stat-label'>Средний объём бака</div>
                    </div>
                    <div class='stat-card'>
                        <div class='stat-value'>{total_fuel_start:.1f} л</div>
                        <div class='stat-label'>Топливо в начале</div>
                    </div>
                    <div class='stat-card'>
                        <div class='stat-value'>{total_fuel_end:.1f} л</div>
                        <div class='stat-label'>Топливо в конце</div>
                    </div>
                    <div class='stat-card'>
                        <div class='stat-value' style='color: {"#28a745" if total_change > 0 else "#dc3545"}'>{total_change:+.1f} л</div>
                        <div class='stat-label'>Общее изменение</div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Сохранение HTML
    html_file = "Отчёт_Топливо.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✓ HTML сохранён: {html_file}")
    
    # Открытие в браузере
    try:
        webbrowser.open("file://" + os.path.abspath(html_file))
        print("\n📂 Отчёт открыт в браузере")
    except:
        print("\n⚠️  Откройте файл вручную")
    
    print("\n" + "=" * 70)
    print("✅ ГОТОВО!")
    print("=" * 70)
    
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
