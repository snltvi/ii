import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
TARGET_ZONE_ID = 73627  
TIME_OFFSET = 2         

def get_sid():
    try:
        params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': str(TIME_OFFSET)}
        res = requests.get(f"{API_URL}/connect", params=params, timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_odo_value(session_id, oid, sid, time_str):
    if not time_str or time_str == "null" or time_str is None: return None
    try:
        url = f"{API_URL}/objdata"
        params = {'oid': oid, 'slist': f's{sid}', 'from': time_str, 'to': time_str, 'compress': 'true'}
        res = requests.get(url, headers={'SessionId': session_id}, params=params, timeout=10)
        data = res.json()
        if data.get('result') == 'Ok' and data.get('obj_data', {}).get('records'):
            return round(float(data['obj_data']['records'][0][1]), 2)
    except: pass
    return None

def main():
    print("=" * 80)
    print(f"📋 ЖУРНАЛ ПОСЕЩЕНИЙ ГЕОЗОНЫ ЗА ПЕРИОД (ID: {TARGET_ZONE_ID})")
    print("=" * 80)

    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл {TARGET_FILE} не найден!"); return

    df_input = pd.read_excel(TARGET_FILE)
    car_db = {int(row['ID_объекта'] if 'ID_объекта' in row else row['ID объекта']): row for _, row in df_input.iterrows() if pd.notna(row.get('ID объекта', row.get('ID_объекта')))}

    session_id = get_sid()
    if not session_id:
        print("❌ Ошибка авторизации"); return

    print("📅 Формат даты: ГГГГ-ММ-ДД")
    date_start = input("Введите дату НАЧАЛА: ").strip()
    date_end = input("Введите дату КОНЦА: ").strip()
    
    date_from_str = f"{date_start} 00:00:00"
    date_to_str = f"{date_end} 23:59:59"

    params = {
        'objects_ids': ",".join(map(str, car_db.keys())),
        'zones_ids': str(TARGET_ZONE_ID),
        'from': date_from_str,
        'to': date_to_str
    }
    
    print(f"📡 Загрузка данных из Mobiteam...")
    res_visits = requests.get(f"{API_URL}/zonesvisits", headers={'SessionId': session_id}, params=params)
    all_visits = res_visits.json().get('visits', [])

    final_results = []
    
    print(f"⚙️ Обработка событий ({len(all_visits)} шт.)...")
    
    for v in all_visits:
        oid = v.get('obj_id')
        row_data = car_db.get(oid)
        if row_data is None: continue

        sid_sensor = int(row_data['SID'])
        v_in = v.get('in_dt')
        v_out = v.get('out_dt')

        # Обработка времени (+2 часа)
        dt_in = pd.to_datetime(v_in) + pd.Timedelta(hours=TIME_OFFSET)
        dt_out = (pd.to_datetime(v_out) + pd.Timedelta(hours=TIME_OFFSET)) if v_out else None

        # Расчет длительности
        duration = "В зоне"
        if v_out:
            diff = dt_out - dt_in
            total_sec = int(diff.total_seconds())
            duration = f"{total_sec // 3600}ч {(total_sec % 3600) // 60}м"

        # Получаем одометры
        odo_in = get_odo_value(session_id, oid, sid_sensor, v_in)
        odo_out = get_odo_value(session_id, oid, sid_sensor, v_out) if v_out else None

        final_results.append({
            'Номер авто': str(row_data.get('Номер авто', '')),
            'Водитель': str(row_data.get('ФИО', '')),
            'Дата заезда': dt_in.strftime('%d.%m.%Y'),
            'Время заезда': dt_in.strftime('%H:%M:%S'),
            'Одометр заезд': odo_in,
            'Дата выезда': dt_out.strftime('%d.%m.%Y') if dt_out else "—",
            'Время выезда': dt_out.strftime('%H:%M:%S') if dt_out else "В зоне",
            'Одометр выезд': odo_out,
            'Время в зоне': duration,
            'Пробег в зоне': round(odo_out - odo_in, 2) if (odo_in and odo_out) else 0
        })

    if final_results:
        df_res = pd.DataFrame(final_results)
        # Сортировка: сначала по авто, потом по времени заезда
        df_res = df_res.sort_values(by=['Номер авто', 'Дата заезда', 'Время заезда'])
        
        output_name = f"Журнал_Гараж_{date_start}_по_{date_end}.xlsx"
        df_res.to_excel(output_name, index=False)
        
        print(f"\n✅ Готово! Файл сохранен: {output_name}")
        os.startfile(output_name)
    else:
        print("\n📭 За указанный период посещений не найдено.")

if __name__ == "__main__":
    main()