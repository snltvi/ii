import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
TARGET_ZONE_ID = 73627  # ID гаража
TIME_OFFSET = 2         # Украина (+2)

def get_sid():
    try:
        params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': str(TIME_OFFSET)}
        res = requests.get(f"{API_URL}/connect", params=params, timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_odo_value(session_id, oid, sid, time_str):
    if not time_str or time_str == "null": return None
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
    print("=" * 75)
    print(f"📊 ОТЧЕТ ПО СТАТУСУ: ГАРАЖ (ID: {TARGET_ZONE_ID})")
    print("=" * 75)

    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл {TARGET_FILE} не найден!"); return

    df_input = pd.read_excel(TARGET_FILE)
    car_db = {int(row['ID объекта']): row for _, row in df_input.iterrows() if pd.notna(row['ID объекта'])}

    session_id = get_sid()
    if not session_id:
        print("❌ Ошибка авторизации"); return

    date_input = input("📅 Введите дату расчета (ГГГГ-ММ-ДД) или Enter для сегодня: ").strip()
    target_date = date_input if date_input else datetime.now().strftime('%Y-%m-%d')
    
    # Берем данные за последние 5 дней, чтобы точно поймать момент въезда долгостоящих авто
    date_to = f"{target_date} 23:59:59"
    date_from = (datetime.strptime(target_date, '%Y-%m-%d') - timedelta(days=5)).strftime('%Y-%m-%d 00:00:00')

    params = {
        'objects_ids': ",".join(map(str, car_db.keys())),
        'zones_ids': str(TARGET_ZONE_ID),
        'from': date_from,
        'to': date_to
    }
    
    print(f"📡 Анализ статусов на момент {target_date}...")
    res_visits = requests.get(f"{API_URL}/zonesvisits", headers={'SessionId': session_id}, params=params)
    all_visits = res_visits.json().get('visits', [])

    final_results = []
    
    for oid, row_data in car_db.items():
        sid_sensor = int(row_data['SID'])
        my_visits = [v for v in all_visits if v.get('obj_id') == oid]
        
        # По умолчанию считаем, что данных нет
        status = "Нет данных"
        event_date, event_time = "—", "—"
        odo_at_event = "—"
        duration = "—"

        if my_visits:
            last_v = my_visits[-1]
            is_in_zone = last_v.get('not_Ended')
            
            if is_in_zone:
                status = "В ГЕОЗОНЕ"
                raw_time = last_v.get('in_dt') # Время заезда
                # Считаем длительность от момента заезда до конца выбранного дня
                diff = (pd.to_datetime(date_to) - pd.to_datetime(raw_time))
                total_sec = int(diff.total_seconds())
                duration = f"{total_sec // 3600}ч {(total_sec % 3600) // 60}м"
            else:
                status = "Не в геозоне"
                raw_time = last_v.get('out_dt') # Время выезда
                duration = "—"

            # Форматируем время события (+2 часа)
            dt_event = pd.to_datetime(raw_time) + pd.Timedelta(hours=TIME_OFFSET)
            event_date = dt_event.strftime('%d.%m.%Y')
            event_time = dt_event.strftime('%H:%M:%S')
            
            # Получаем одометр именно на момент этого события
            print(f"🔍 Сбор данных: {row_data.get('Номер авто')} ({status})", end='\r')
            odo_at_event = get_odo_value(session_id, oid, sid_sensor, raw_time)

        final_results.append({
            'Номер авто': str(row_data.get('Номер авто', '')),
            'Водитель': str(row_data.get('ФИО', '')),
            'Статус': status,
            'Дата события': event_date,
            'Время события': event_time,
            'Одометр (въезд/выезд)': odo_at_event,
            'Время в зоне (для тех кто внутри)': duration
        })

    # Сохранение и сортировка
    df_res = pd.DataFrame(final_results).sort_values(by='Номер авто')
    output_name = f"Статус_Авто_{target_date}.xlsx"
    df_res.to_excel(output_name, index=False)
    
    print(f"\n\n✅ Отчет сформирован: {output_name}")
    os.startfile(output_name)

if __name__ == "__main__":
    main()