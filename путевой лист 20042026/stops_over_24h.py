# Скрипт запрашивает список стоянок выбранного авто за заданный период,
# фильтрует стоянки длительностью более 24 часов (>= 86400 сек) и
# возвращает адреса этих стоянок через метод GET /api/integration/v1/stops
# и обратное геокодирование через GET /api/integration/v1/getaddress.
# Авторизация — через GET /api/integration/v1/connect (login/password → SessionId).
# Результат сохраняется в Excel-файл.

import requests
import pandas as pd
import time
from datetime import datetime, timedelta

API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

MIN_STOP_SECONDS = 86400  # 24 часа


def connect_to_api():
    """Авторизация, возвращает SessionId."""
    try:
        res = requests.get(
            f"{API_URL}/connect",
            params={"login": LOGIN, "password": PASSWORD, "lang": "ru-ru", "timezone": "3"},
            timeout=10,
        )
        sid = res.headers.get("sessionid")
        return sid
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return None


def get_vehicles(sid):
    """Получает список объектов через gettree, возвращает список {id, name}."""
    try:
        res = requests.get(
            f"{API_URL}/gettree",
            headers={"SessionId": sid},
            timeout=15,
        )
        data = res.json()
        vehicles = []

        def extract(nodes):
            for node in nodes:
                if node.get("real_id"):
                    vehicles.append({
                        "id": node["real_id"],
                        "name": node.get("name", f"ID:{node['real_id']}"),
                    })
                if node.get("children"):
                    extract(node["children"])

        extract(data if isinstance(data, list) else data.get("items", []))
        return vehicles
    except Exception as e:
        print(f"Ошибка получения списка авто: {e}")
        return []


def get_stops(sid, oid, date_from, date_to, min_time=3600):
    """Запрашивает стоянки объекта за период. min_time — фильтр API (сек)."""
    try:
        res = requests.get(
            f"{API_URL}/stops",
            headers={"SessionId": sid},
            params={"oid": oid, "from": date_from, "to": date_to, "time": min_time},
            timeout=30,
        )
        data = res.json()
        if data.get("result") == "Ok":
            return data.get("stops", [])
        print(f"API вернул ошибку: {data.get('result')}")
        return []
    except Exception as e:
        print(f"Ошибка запроса стоянок: {e}")
        return []


def get_address(sid, lat, lon):
    """Обратное геокодирование координат в адрес."""
    try:
        res = requests.get(
            f"{API_URL}/getaddress",
            headers={"SessionId": sid},
            params={"lat": lat, "lon": lon},
            timeout=10,
        )
        return res.text.strip() if res.status_code == 200 else "Адрес не определён"
    except Exception:
        return "Ошибка геокодера"


def format_duration(seconds):
    """Форматирует секунды в строку 'Xд HH:MM'."""
    td = timedelta(seconds=seconds)
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}д {hours:02d}:{minutes:02d}"
    return f"{hours:02d}:{minutes:02d}"


def choose_vehicle(sid):
    """Интерактивный выбор авто из списка или ввод OID вручную."""
    vehicles = get_vehicles(sid)

    if vehicles:
        print("\nДоступные объекты:")
        for i, v in enumerate(vehicles, 1):
            print(f"  {i:3}. [{v['id']:>7}] {v['name']}")
        print()
        choice = input("Введите номер из списка или OID вручную: ").strip()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(vehicles):
                return vehicles[idx - 1]["id"], vehicles[idx - 1]["name"]
            # Если число вне диапазона — считаем прямым OID
            return idx, f"OID {idx}"
    else:
        print("Список объектов недоступен. Введите OID вручную.")
        oid_input = input("OID объекта: ").strip()
        return int(oid_input), f"OID {oid_input}"


def main():
    print("=== Стоянки авто более 24 часов ===\n")

    sid = connect_to_api()
    if not sid:
        print("Не удалось авторизоваться. Проверьте логин/пароль.")
        return

    print("Авторизация успешна.")

    oid, vehicle_name = choose_vehicle(sid)

    date_from = input("\nНачало периода (ГГГГ-ММ-ДД): ").strip()
    date_to = input("Конец периода   (ГГГГ-ММ-ДД): ").strip()

    date_from_dt = f"{date_from} 00:00:00"
    date_to_dt = f"{date_to} 23:59:59"

    print(f"\nЗапрос стоянок для [{vehicle_name}] с {date_from_dt} по {date_to_dt}...")

    # API-фильтр: запрашиваем все стоянки >= 1 ч, потом фильтруем на 24 ч локально
    stops = get_stops(sid, oid, date_from_dt, date_to_dt, min_time=3600)

    if not stops:
        print("Стоянок не найдено за указанный период.")
        return

    long_stops = [s for s in stops if s.get("duration", 0) >= MIN_STOP_SECONDS]

    if not long_stops:
        print(f"Стоянок длительностью >= 24 часов не обнаружено (всего стоянок: {len(stops)}).")
        return

    print(f"Найдено {len(long_stops)} стоянок >= 24 ч (из {len(stops)} всего). Получаю адреса...\n")

    results = []
    for i, stop in enumerate(long_stops, 1):
        lat = stop["lat"]
        lon = stop["lon"]
        duration = stop["duration"]
        stop_time = stop["stop_time"]

        address = get_address(sid, lat, lon)
        duration_str = format_duration(duration)

        print(f"  {i}/{len(long_stops)}  {stop_time}  {duration_str}  {address}")

        results.append({
            "Начало стоянки": stop_time,
            "Длительность": duration_str,
            "Длительность (сек)": duration,
            "Адрес": address,
            "Широта": lat,
            "Долгота": lon,
        })

        time.sleep(0.15)

    df = pd.DataFrame(results)

    out_name = f"Стоянки_24ч_{vehicle_name.replace(' ', '_')}_{date_from}_{date_to}.xlsx"
    df.to_excel(out_name, index=False)

    print(f"\nГотово! Файл сохранён: {out_name}")
    print(f"Итого стоянок >= 24 ч: {len(results)}")


if __name__ == "__main__":
    main()
