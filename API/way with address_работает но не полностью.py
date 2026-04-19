import requests
import pandas as pd
import os
from datetime import datetime

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"

def get_sid():
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except:
        return None

def main():
    print("🚀 ГЕНЕРАЦИЯ ПУТЕВОГО ЛИСТА (СТАТУС 'В ПУТИ')")
    sid = get_sid()
    if not sid:
        print("❌ Ошибка авторизации!"); return

    df_input = pd.read_excel(TARGET_FILE)
    d_start = input("📅 Дата начала (ГГГГ-ММ-ДД): ").strip()
    d_end = input("📅 Дата конца (ГГГГ-ММ-ДД): ").strip()
    
    obj_ids = ";".join(df_input['ID объекта'].astype(str).tolist())
    
    # Добавляем параметры времени окончания движения
    params_list = "start_address;stop_address;start_can_dist;stop_can_dist;can_dist;odo_dist;stop_move_time"
    
    payload = {
        'date_from': f"{d_start} 00:00:00",
        'date_to': f"{d_end} 23:59:59",
        'objuids': obj_ids,
        'split': 'none',
        'param': params_list
    }

    res = requests.get(f"{API_URL}/getobjectsreport", headers={'SessionId': sid}, params=payload, timeout=60)
    report_data = res.json()
    results = []

    for obj_report in report_data:
        oid = obj_report.get('oid')
        original_row = df_input[df_input['ID объекта'] == oid].iloc[0]
        p_dict = {p['name']: p['value'] for p in obj_report.get('periods', [{}])[0].get('prms', [])}
        
        # --- ЛОГИКА ОПРЕДЕЛЕНИЯ "В ПУТИ" ---
        addr_end = p_dict.get('stop_address', 'Не определен')
        stop_time_str = p_dict.get('stop_move_time', '')
        
        if stop_time_str:
            try:
                # Если время последнего движения совпадает с концом запроса (23:59:59), значит машина едет
                stop_dt = datetime.strptime(stop_time_str, '%Y-%m-%d %H:%M:%S')
                if stop_dt.hour == 23 and stop_dt.minute >= 58:
                    addr_end = "В пути"
            except:
                pass

        # --- ОДОМЕТР (CAN или GPS) ---
        can_s = float(p_dict.get('start_can_dist', 0))
        can_e = float(p_dict.get('stop_can_dist', 0))
        dist = round(can_e - can_s, 2) if can_e > 0 else float(p_dict.get('odo_dist', 0))

        results.append({
            'Водитель': original_row.get('ФИО', '—'),
            'Номер авто': obj_report.get('obj_name'),
            'Дата': d_start,
            'Адрес начала': p_dict.get('start_address', 'Не определен'),
            'Одометр старт': can_s,
            'Адрес конца': addr_end,
            'Одометр конец': can_e,
            'Пробег (км)': dist
        })

    df_res = pd.DataFrame(results)
    out_name = f"Путевой_лист_Статус_{d_start}.xlsx"
    df_res.to_excel(out_name, index=False)
    print(f"\n✅ Готово! Файл: {out_name}")
    os.startfile(out_name)

if __name__ == "__main__":
    main()