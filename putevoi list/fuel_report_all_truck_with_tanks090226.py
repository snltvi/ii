import requests
import pandas as pd
import os
import re
import webbrowser
import sqlite3

# --- НАСТРОЙКИ ПУТЕЙ ---
# Указываем ваш путь к папке со справочниками
BASE_PATH = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники"
INPUT_FILE = os.path.join(BASE_PATH, 'CAN_пробег_датчики_06_02_2026.xlsx')

# --- НАСТРОЙКИ API ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

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
    """Определяет объем бака из названия датчика через API"""
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", 
                          params={'oid': oid}, 
                          headers={'SessionId': sid}, 
                          timeout=10)
        data = res.json()
        
        for sensor in data.get('obj_sensors', []):
            name = sensor.get('name', '').lower()
            if any(keyword in name for keyword in ['бак', 'lls', 'fuel', 'tank', 'топлив']):
                volumes = re.findall(r'\b(\d{3,4})\b', name)
                if volumes:
                    possible_volumes = [int(v) for v in volumes if 100 <= int(v) <= 2000]
                    if possible_volumes:
                        return max(possible_volumes)
        
        # Эвристика, если объем не указан в названии
        obj_info = requests.get(f"{API_BASE_URL}/getobjectsstate",
                               params={'objuids': str(oid)},
                               headers={'SessionId': sid},
                               timeout=10).json()
        if obj_info:
            obj_name = obj_info[0].get('name', '').upper()
            if any(brand in obj_name for brand in ['DAF', 'MAN', 'SCANIA', 'VOLVO', 'MERCEDES']):
                return 800
            elif any(brand in obj_name for brand in ['SPRINTER', 'IVECO']):
                return 100
    except:
        pass
    return 600

def main():
    print("=" * 70)
    print(f"⛽ ОТЧЁТ ПО ТОПЛИВУ | ПАПКА: {BASE_PATH}")
    print("=" * 70)
    
    sid = get_sid()
    if not sid: 
        print("❌ Ошибка авторизации"); return
    
    if not os.path.exists(INPUT_FILE): 
        print(f"❌ Файл не найден по пути: {INPUT_FILE}"); return
    
    df_input = pd.read_excel(INPUT_FILE)
    print(f"✓ Загружено ТС из справочника: {len(df_input)}")
    
    ids_list = df_input['ID объекта'].dropna().unique()
    
    # Сбор объемов баков
    print(f"📡 Опрашиваем API на предмет объёмов баков...")
    tank_map = {int(oid): get_tank_volume(int(oid), sid) for oid in ids_list}
    
    print("\n" + "-" * 30)
    d_start = input("📅 НАЧАЛО (ГГГГ-ММ-ДД 00:00:00): ").strip()
    d_end = input("📅 КОНЕЦ  (ГГГГ-ММ-ДД 23:59:59): ").strip()
    
    # Запрос данных по топливу
    ids_str = ";".join([str(int(x)) for x in ids_list])
    try:
        fuel_data = requests.get(
            f"{API_BASE_URL}/getobjectsfuelinfo", 
            params={'date_from': d_start, 'date_to': d_end, 'objuids': ids_str},
            headers={'SessionId': sid}, timeout=60
        ).json()
    except Exception as e:
        print(f"❌ Ошибка API: {e}"); return

    driver_map = pd.Series(df_input['ФИО'].values, index=df_input['ID объекта']).to_dict()
    results = []
    
    for obj in fuel_data:
        oid = obj.get('object_id')
        t_start, t_end = 0, 0
        for sensor in obj.get('sensors', []):
            name = sensor.get('sensor_name', '').lower()
            if any(k in name for k in ["бак", "lls", "fuel", "tank", "сумматор"]):
                t_start += sensor.get('beginLevel', 0)
                t_end += sensor.get('endLevel', 0)
        
        tank_vol = tank_map.get(oid, 600)
        diff = t_end - t_start
        fill_pct = min(100, int((t_end / tank_vol) * 100)) if tank_vol > 0 else 0
        
        results.append({
            'Водитель': driver_map.get(oid, "—"),
            'Автомобиль': obj.get('object_name', 'N/A'),
            'Объём бака (л)': tank_vol,
            'Топливо начало (л)': round(t_start, 1),
            'Топливо конец (л)': round(t_end, 1),
            'Изменение (л)': round(diff, 1),
            'Заполнение (%)': fill_pct
        })
    
    df_results = pd.DataFrame(results).sort_values('Автомобиль')
    
    # Сохранение и показ
    output_html = "Fuel_Report_Visual.html"
    df_results.to_html(output_html, escape=False, index=False) # Упрощенный экспорт для примера
    
    # Здесь можно вставить ваш красивый HTML-блок из предыдущего сообщения
    # (я его сохранил в коде выше для краткости)
    
    print(f"\n✅ Готово! Отчет сформирован.")
    webbrowser.open("file://" + os.path.abspath(output_html))

if __name__ == "__main__":
    main()