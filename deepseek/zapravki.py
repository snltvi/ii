import requests
import pandas as pd
import os

# --- 1. НАСТРОЙКИ ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = 'CAN_пробег_датчики_06_02_2026.xlsx'

def get_sid():
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
    try:
        res = requests.get(url, params=params, timeout=10)
        return res.headers.get('sessionid')
    except:
        return None

def main():
    print("🚀 Запуск формирования отчета по бакам...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл {INPUT_FILE} не найден!"); return

    # Читаем Excel и собираем ID
    df_input = pd.read_excel(INPUT_FILE)
    ids = [str(int(x)) for x in df_input['ID объекта'].dropna().unique()]
    ids_str = ";".join(ids) # Объединяем ID для запроса

    sid = get_sid()
    if not sid:
        print("❌ Ошибка авторизации"); return

    date_str = input("📅 Введите дату (ГГГГ-ММ-ДД): ").strip()
    
    # Формируем запрос к нужному методу
    url = f"{API_BASE_URL}/getobjectsfuelinfo"
    params = {
        'date_from': f"{date_str} 00:00:00",
        'date_to': f"{date_str} 23:59:59",
        'objuids': ids_str
    }
    headers = {'SessionId': sid, 'Accept': 'application/json'}

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        final_data = []

        # Обрабатываем каждую машину из ответа API
        for obj in data:
            obj_id = obj.get('object_id')
            obj_name = obj.get('object_name', 'N/A')
            
            total_start = 0
            total_end = 0
            has_tanks = False

            # Фильтруем датчики по Варианту Б (слово "Бак")
            for s in obj.get('sensors', []):
                if "бак" in s.get('sensor_name', '').lower():
                    total_start += s.get('beginLevel', 0)
                    total_end += s.get('endLevel', 0)
                    has_tanks = True
            
            final_data.append({
                'Номер авто': obj_name,
                'ID объекта': obj_id,
                'Бак на начало (л)': round(total_start, 2) if has_tanks else "—",
                'Бак на конец (л)': round(total_end, 2) if has_tanks else "—"
            })

        # Создаем таблицу и сохраняем
        df_res = pd.DataFrame(final_data)
        # Сортируем по номеру авто для удобства
        df_res = df_res.sort_values(by='Номер авто')
        
        output_name = f"Отчет_Баки_{date_str}.xlsx"
        df_res.to_excel(output_name, index=False)
        print(f"✅ Отчет готов: {output_name}")

    except Exception as e:
        print(f"❌ Ошибка при обработке: {e}")

if __name__ == "__main__":
    main()