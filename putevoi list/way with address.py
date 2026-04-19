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

def fetch_address(sid, lat, lon):
    """Принудительное получение адреса по координатам"""
    try:
        res = requests.get(f"{API_URL}/getaddress", headers={'SessionId': sid}, 
                           params={'lat': lat, 'lon': lon}, timeout=10)
        return res.text.strip().strip('"')
    except:
        return "Не определен"

def main():
    print("🚀 ЗАПУСК УЛУЧШЕННОГО ОТЧЕТА (ПРОВЕРКА КУЗНЕЦОВА И ДЕМЧЕНКО)")
    sid = get_sid()
    if not sid:
        print("❌ Ошибка авторизации!"); return

    df_input = pd.read_excel(TARGET_FILE)
    d_start = input("📅 Дата начала (ГГГГ-ММ-ДД): ").strip()
    d_end = input("📅 Дата конца (ГГГГ-ММ-ДД): ").strip()
    
    obj_ids = ";".join(df_input['ID объекта'].astype(str).tolist())
    
    # Добавляем stop_coords (координаты конца), чтобы всегда иметь адрес
    params_list = "start_address;stop_address;start_can_dist;stop_can_dist;can_dist;odo_dist;start_move_time;stop_move_time;stop_coords;odo_full"
    
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
        v_name = obj_report.get('obj_name')
        print(f"🔎 Проверка {v_name}...", end='\r')
        
        periods = obj_report.get('periods', [])
        if not periods: continue
        p = {item['name']: item['value'] for item in periods[0].get('prms', [])}
        
        # 1. ИСПРАВЛЕНИЕ АДРЕСА (Для Демченко)
        addr_e = p.get('stop_address', 'Не определен')
        if addr_e == "Не определен" or not addr_e:
            coords = p.get('stop_coords')
            if coords and ',' in str(coords):
                lat, lon = str(coords).split(',')
                addr_e = fetch_address(sid, lat, lon)

        # 2. ИСПРАВЛЕНИЕ ОДОМЕТРА (Для Кузнецова)
        # Если CAN-одометр 0, пробуем взять общий системный одометр (odo_full)
        can_s = float(p.get('start_can_dist', 0))
        can_e = float(p.get('stop_can_dist', 0))
        
        if can_s == 0 and can_e == 0:
            # Пытаемся найти любые данные по пробегу, если CAN молчит
            dist_val = float(p.get('can_dist', 0)) or float(p.get('odo_dist', 0))
        else:
            dist_val = can_e - can_s if can_e > can_s else float(p.get('can_dist', 0))

        # Находим ФИО
        match = df_input[df_input['ID объекта'] == oid]
        fio = match.iloc[0]['ФИО'] if not match.empty else "—"

        results.append({
            'Водитель': fio,
            'Номер авто': v_name,
            'На2025-12-24чало рейса': p.get('start_move_time', '—'),
            'Адрес начала': p.get('start_address', 'Не определен'),
            'Одометр старт': can_s,
            'Конец рейса': p.get('stop_move_time', '—'),
            'Адрес конца': addr_e,
            'Одометр конец': can_e,
            'Пробег (км)': round(dist_val, 2)
        })

    df_res = pd.DataFrame(results)
    out_name = f"Путевой_лист_Корректный_{d_start}.xlsx"
    df_res.to_excel(out_name, index=False)
    
    print(f"\n✅ Готово! Проверьте данные по Кузнецову и Демченко в файле: {out_name}")
    os.startfile(out_name)

if __name__ == "__main__":
    main()