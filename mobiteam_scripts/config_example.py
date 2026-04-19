# Пример файла конфигурации
# Скопируйте этот файл в config.py и заполните своими данными

# Настройки подключения к Fort Monitor
FORT_MONITOR_URL = "https://web.fort-monitor.ru"
FORT_MONITOR_USERNAME = "ваш_логин"
FORT_MONITOR_PASSWORD = "ваш_пароль"

# ID транспортного средства (можно узнать после первого запуска скрипта)
VEHICLE_ID = None  # Например: 123

# ID геозоны гаража (можно узнать после первого запуска скрипта)
GARAGE_GEOZONE_ID = None  # Например: 10

# Часовой пояс (для корректного отображения времени)
TIMEZONE = "Europe/Moscow"

# Настройки для путевого листа
WAYBILL_SETTINGS = {
    "organization": "ООО 'Ваша компания'",
    "department": "Транспортный отдел",
    "default_driver": "Иванов И.И."
}
