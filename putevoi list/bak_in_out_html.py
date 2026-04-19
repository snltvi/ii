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
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_tank_volume(oid, sid):
    """Вытягивает литраж из названия датчика через API"""
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", params={'oid': oid}, headers={'SessionId': sid}, timeout=10).json()
        for sensor in res.get('obj_sensors', []):
            name = sensor.get('name', '')
            # Ищем цифры (объем) в названии датчика
            volumes = re.findall(r'(\d{3,4})', name)
            if volumes: return int(max(volumes, key=len))
    except: pass
    return 600 # Если не нашли, ставим 600

def main():
    sid = get_sid()
    if not sid: print("❌ Ошибка авторизации"); return
    if not os.path.exists(INPUT_FILE): print(f"❌ Нет файла {INPUT_FILE}"); return

    df_input = pd.read_excel(INPUT_FILE)
    ids_list = df_input['ID объекта'].dropna().unique()

    # Сбор данных об объемах
    print("📡 Опрос датчиков объектов...")
    tank_map = {int(oid): get_tank_volume(int(oid), sid) for oid in ids_list}

    d_start = input("📅 НАЧАЛО (ГГГГ-ММ-ДД ЧЧ:ММ:СС): ").strip()
    d_end   = input("📅 КОНЕЦ  (ГГГГ-ММ-ДД ЧЧ:ММ:СС): ").strip()

    ids_str = ";".join([str(int(x)) for x in ids_list])
    fuel_data = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                             params={'date_from': d_start, 'date_to': d_end, 'objuids': ids_str},
                             headers={'SessionId': sid}).json()
    
    driver_map = pd.Series(df_input.ФИО.values, index=df_input['ID объекта']).to_dict()
    results = []

    for obj in fuel_data:
        oid = obj.get('object_id')
        t_start, t_end = 0, 0
        for s in obj.get('sensors', []):
            if any(w in s.get('sensor_name', '').lower() for w in ["бак", "lls", "fuel"]):
                t_start += s.get('beginLevel', 0)
                t_end += s.get('endLevel', 0)

        vol = tank_map.get(oid, 600)
        perc = min(100, int((t_end / vol) * 100)) if t_end > 0 else 0
        results.append({
            'driver': driver_map.get(oid, "—"),
            'car': obj.get('object_name', 'N/A'),
            'max_vol': vol,
            'start': round(t_start, 1),
            'end': round(t_end, 1),
            'diff': round(t_end - t_start, 1),
            'perc': perc
        })

    # --- HTML С КОЛОНКОЙ "ОБЪЕМ БАКА" ---
    html = f"""
    <html><head><meta charset='UTF-8'><style>
        body {{ font-family: sans-serif; background: #f0f2f5; padding: 20px; }}
        .card {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f8f9fa; padding: 12px; text-align: left; border-bottom: 2px solid #ddd; color: #666; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; }}
        .tank-size {{ font-weight: bold; color: #1a73e8; }}
        .bar-bg {{ background: #eee; width: 80px; height: 10px; border-radius: 5px; display: inline-block; }}
        .bar-fill {{ background: #28a745; height: 100%; border-radius: 5px; }}
    </style></head><body>
    <div class='card'>
        <h2>⛽ Отчет по бакам за рейс</h2>
        <p>Период: {d_start} — {d_end}</p>
        <table>
            <tr>
                <th>Водитель</th><th>Автомобиль</th>
                <th style='background:#eef6ff'>ОБЪЕМ БАКА</th>
                <th>Старт</th><th>Конец</th><th>Разница</th><th>Уровень</th>
            </tr>
    """
    for r in results:
        diff_color = "green" if r['diff'] > 0 else "red"
        html += f"""
            <tr>
                <td>{r['driver']}</td><td>{r['car']}</td>
                <td class='tank-size'>{r['max_vol']} л</td>
                <td>{r['start']} л</td><td>{r['end']} л</td>
                <td style='color:{diff_color}'><b>{r['diff']} л</b></td>
                <td><div class='bar-bg'><div class='bar-fill' style='width:{r['perc']}%'></div></div> {r['perc']}%</td>
            </tr>"""
    html += "</table></div></body></html>"

    with open("Fuel_Final.html", "w", encoding="utf-8") as f: f.write(html)
    webbrowser.open("file://" + os.path.abspath("Fuel_Final.html"))

if __name__ == "__main__": main()