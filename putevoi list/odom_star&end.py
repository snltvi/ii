import requests
import pandas as pd
import os
from datetime import datetime

# --- НАЛАШТУВАННЯ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"

def get_sid():
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'uk-ua', 'timezone': '3'},
                           timeout=10)
        # Пробуємо дістати SID з заголовків або тіла
        sid = res.headers.get('sessionid') or res.json().get('sessionid')
        return sid
    except:
        return None

def fetch_address(sid, lat, lon):
    try:
        res = requests.get(f"{API_URL}/getaddress", headers={'SessionId': sid}, 
                           params={'lat': lat, 'lon': lon}, timeout=10)
        return res.text.strip().strip('"')
    except:
        return "Не визначено"

def get_day_data(sid, oid, sid_param, date_str):
    """Отримує дані одометра на самий початок і самий кінець дня"""
    # Запитуємо дані за всю добу. s1 — це зазвичай одометр (згідно з вашим Excel)
    params = {
        'oid': oid,
        'slist': f's{int(sid_param)}', 
        'from': f"{date_str} 00:00:00",
        'to': f"{date_str} 23:59:59"
    }
    
    try:
        res = requests.get(f"{API_URL}/objdata", headers={'SessionId': sid}, params=params, timeout=30)
        data = res.json()
        records = data.get('obj_data', {}).get('records', [])
        
        if not records:
            return None

        # records[0] - перша точка дня, records[-1] - остання точка дня
        start_point = records[0]
        end_point = records[-1]
        
        return {
            'time_start': start_point[0],
            'odo_start': round(float(start_point[1]), 2),
            'time_end': end_point[0],
            'odo_end': round(float(end_point[1]), 2),
            # Якщо в records є 4-й і 5-й елементи (координати), можемо взяти їх
            'coords_start': (start_point[3], start_point[4]) if len(start_point) > 4 else None,
            'coords_end': (end_point[3], end_point[4]) if len(end_point) > 4 else None
        }
    except:
        return None

def main():
    print("📊 ЗВІТ: ПОКАЗНИКИ ОДОМЕТРА ЗА ДОБУ")
    sid = get_sid()
    if not sid:
        print("❌ Помилка авторизації!"); return

    df_input = pd.read_excel(TARGET_FILE)
    target_date = input("📅 Введіть дату (ГГГГ-ММ-ДД): ").strip()
    
    results = []

    for _, row in df_input.iterrows():
        oid = row['ID объекта']
        v_name = row['Номер авто']
        fio = row['ФИО']
        sid_p = row['SID'] # Номер сенсора одометра з вашого Excel
        
        print(f"🔎 Отримуємо дані: {v_name} ({fio})...")
        
        day_info = get_day_data(sid, oid, sid_p, target_date)
        
        if day_info:
            # Отримуємо адреси для першої та останньої точки
            addr_start = "Визначається..."
            addr_end = "Визначається..."
            
            if day_info['coords_start']:
                addr_start = fetch_address(sid, day_info['coords_start'][0], day_info['coords_start'][1])
            if day_info['coords_end']:
                addr_end = fetch_address(sid, day_info['coords_end'][0], day_info['coords_end'][1])

            results.append({
                'Водій': fio,
                'Номер авто': v_name,
                'Дата': target_date,
                'Час першої точки': day_info['time_start'],
                'Адреса (початок)': addr_start,
                'Одометр (00:00)': day_info['odo_start'],
                'Час останньої точки': day_info['time_end'],
                'Адреса (кінець)': addr_end,
                'Одометр (23:59)': day_info['odo_end'],
                'Пробіг за добу (км)': round(day_info['odo_end'] - day_info['odo_start'], 2)
            })
        else:
            print(f"⚠️ Немає даних для {v_name} за цю дату.")

    if results:
        df_res = pd.DataFrame(results)
        out_name = f"Одометр_Добовий_{target_date}.xlsx"
        df_res.to_excel(out_name, index=False)
        print(f"\n✅ Готово! Файл збережено: {out_name}")
        os.startfile(out_name)
    else:
        print("\n❌ Жодних даних не знайдено.")

if __name__ == "__main__":
    main()