# Сравнение Fort Monitor API и Mobiteam API

## Какой скрипт использовать?

### Если у вас **Mobiteam GPS** (gps.mobiteam.com.ua)
✅ Используйте: `mobiteam_odometer.py`
📖 Инструкция: `README_MOBITEAM.md`
⚙️ Конфигурация: `config_mobiteam_example.py`

### Если у вас **Fort Monitor** (web.fort-monitor.ru)
✅ Используйте: `fort_monitor_improved.py` или `fort_monitor_odometer.py`
📖 Инструкция: `README.md`
⚙️ Конфигурация: `config_example.py`

---

## Основные отличия систем

| Характеристика | Fort Monitor | Mobiteam |
|----------------|--------------|----------|
| **Провайдер** | Форт-Телеком (Россия) | MobiTeam (Украина) |
| **Сайт** | https://web.fort-monitor.ru | https://gps.mobiteam.com.ua |
| **Регион** | В основном РФ и СНГ | В основном Украина |
| **Авторизация API** | SessionId через connect | Bearer Token (API Key) |
| **Документация** | /help/api.html | /api/help/index |

---

## Сравнение API методов

### Авторизация

**Fort Monitor:**
```python
POST /api/integration/v1/connect
Body: {"userName": "user", "password": "pass"}
Response Headers: SessionId
```

**Mobiteam:**
```python
Headers: Authorization: Bearer {api_key}
# API ключ получается в личном кабинете
```

### Получение списка объектов

**Fort Monitor:**
```python
GET /api/integration/v1/objectslist
Response: {"objects": [...]}
```

**Mobiteam:**
```python
GET /api/v1/objects
Response: [{...}, {...}]
```

### Получение трека

**Fort Monitor:**
```python
GET /api/integration/v1/track
Params: objectId, from, to
Response: {"track": [...]}
```

**Mobiteam:**
```python
GET /api/v1/track
Params: objectId, from, to
Response: [{...}, {...}]
```

### События геозоны

**Fort Monitor:**
```python
# Через общий метод событий
GET /api/integration/v1/events
Filter: по типу события и геозоне
```

**Mobiteam:**
```python
GET /api/v1/events/geozone
Params: objectId, geozoneId, from, to
Response: [{eventType: "enter/exit", ...}]
```

---

## Названия полей в ответах API

### Объект (транспортное средство)

| Данные | Fort Monitor | Mobiteam |
|--------|--------------|----------|
| ID | `id` | `id` или `objectId` |
| Название | `name` | `name` или `objectName` |
| Гос. номер | `gos_num` | `plateNumber`, `regNumber` |

### Точка трека

| Данные | Fort Monitor | Mobiteam |
|--------|--------------|----------|
| Широта | `lat` | `latitude` или `lat` |
| Долгота | `lon` | `longitude` или `lon` |
| Одометр | `mileage` | `mileage` или `odometer` |
| Время | `dt` | `timestamp` или `time` |
| Скорость | `speed` | `speed` |

### Геозона

| Данные | Fort Monitor | Mobiteam |
|--------|--------------|----------|
| ID | `id` | `id` или `geozoneId` |
| Название | `name` | `name` или `geozoneName` |
| Тип | `geo_type` | `type` |
| Радиус | `geo_radius` | `radius` |
| Центр (широта) | `points[0].lat` | `latitude` или `lat` |
| Центр (долгота) | `points[0].lon` | `longitude` или `lon` |

---

## Особенности работы

### Fort Monitor

**Плюсы:**
- Подробная документация на русском
- Swagger UI для тестирования
- Поддержка множества типов терминалов
- Интеграция с 1С

**Минусы:**
- Требуется логин/пароль (нет токенов)
- SessionId нужно обновлять
- Сложнее структура данных для геозон

**Подходит для:**
- Российских компаний
- Крупных автопарков
- Интеграции с 1С

### Mobiteam

**Плюсы:**
- Простая авторизация через API ключ
- Более простая структура данных
- Удобные события геозон
- Европейские дата-центры (Tier 4)

**Минусы:**
- Меньше документации
- Может требовать активации API в аккаунте

**Подходит для:**
- Украинских компаний
- Средних и малых автопарков
- Быстрой интеграции

---

## Примеры кода

### Fort Monitor - Получение трека
```python
# 1. Авторизация
response = requests.post(
    "https://web.fort-monitor.ru/api/integration/v1/connect",
    json={"userName": "user", "password": "pass"}
)
session_id = response.headers.get('SessionId')

# 2. Запрос трека
response = requests.get(
    "https://web.fort-monitor.ru/api/integration/v1/track",
    headers={'SessionId': session_id},
    params={
        'objectId': 123,
        'from': '2025-02-05T00:00:00',
        'to': '2025-02-05T23:59:59'
    }
)
track = response.json()['track']
```

### Mobiteam - Получение трека
```python
# Запрос трека (авторизация через API ключ)
response = requests.get(
    "https://gps.mobiteam.com.ua/api/v1/track",
    headers={'Authorization': 'Bearer YOUR_API_KEY'},
    params={
        'objectId': 1234,
        'from': '2025-02-05T00:00:00',
        'to': '2025-02-05T23:59:59'
    }
)
track = response.json()
```

---

## Какую систему выбрать для новых проектов?

### Выбирайте Fort Monitor если:
- Работаете в России
- Нужна глубокая интеграция с 1С
- Требуется поддержка множества типов оборудования
- Есть опытные системные интеграторы
- Важна развитая экосистема и партнерская сеть

### Выбирайте Mobiteam если:
- Работаете в Украине
- Нужно быстро начать работу
- Важна простота API
- Предпочитаете европейские сервера
- Средний или малый автопарк

---

## Миграция между системами

Если вы переходите с одной системы на другую:

1. **Экспорт данных:**
   - Исторические треки
   - Настройки геозон
   - Информация об объектах

2. **Настройка новой системы:**
   - Создание геозон
   - Добавление объектов
   - Настройка событий

3. **Адаптация скриптов:**
   - Замена методов авторизации
   - Обновление названий полей
   - Тестирование на небольшом периоде

4. **Параллельная работа:**
   - Запустите обе системы параллельно
   - Сравните данные
   - Убедитесь в корректности

---

## Контакты техподдержки

### Fort Monitor
- Сайт: https://fort-monitor.ru
- Поддержка: https://support.fort-monitor.ru
- Email: обычно через форму на сайте

### Mobiteam
- Сайт: https://www.mobiteam.com.ua
- Поддержка: https://support.mobiteam.com.ua
- Телефон: +380 (48) 123-45-67 (пример, уточните актуальный)

---

## Заключение

Обе системы отлично подходят для GPS мониторинга транспорта. Выбор зависит от:
- Вашего географического положения
- Требований к интеграции
- Размера автопарка
- Технической экспертизы команды

Скрипты в этом проекте поддерживают обе системы, так что вы можете начать с той, которая у вас уже есть.
