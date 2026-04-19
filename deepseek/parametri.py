import requests
import pandas as pd
import json
from datetime import datetime
import time
from typing import List, Dict, Any
import warnings
warnings.filterwarnings('ignore')

class MonitoringAPI:
    def __init__(self, base_url: str, session_id: str = None, 
                 login: str = None, password: str = None):
        """
        Инициализация API клиента
        
        Args:
            base_url: Базовый URL API
            session_id: ID существующей сессии (если есть)
            login: Логин для авторизации
            password: Пароль для авторизации
        """
        self.base_url = base_url.rstrip('/')
        self.session_id = session_id
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Если нет session_id, но есть логин/пароль - создаем сессию
        if not self.session_id and login and password:
            self.session_id = self.connect(login, password)
        
        if self.session_id:
            self.headers['Session'] = self.session_id
    
    def connect(self, login: str, password: str) -> str:
        """
        Создание сессии
        
        Args:
            login: Логин пользователя
            password: Пароль пользователя
            
        Returns:
            Session ID
        """
        url = f"{self.base_url}/connect"
        params = {
            'login': login,
            'password': password
        }
        
        try:
            print(f"🔐 Авторизация пользователя: {login}")
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                session_id = data.get('session')
                print(f"✅ Сессия создана: {session_id[:10]}...")
                return session_id
            else:
                print(f"❌ Ошибка создания сессии: {data}")
                return None
                
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Ошибка подключения к серверу: {e}")
            return None
        except requests.exceptions.Timeout as e:
            print(f"❌ Таймаут подключения: {e}")
            return None
        except Exception as e:
            print(f"❌ Ошибка авторизации: {e}")
            return None
    
    def disconnect(self):
        """Закрытие сессии"""
        if self.session_id:
            url = f"{self.base_url}/disconnect"
            params = {'session': self.session_id}
            
            try:
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    print("✅ Сессия закрыта")
                else:
                    print(f"⚠️  Не удалось закрыть сессию: {response.status_code}")
            except Exception as e:
                print(f"⚠️  Ошибка при закрытии сессии: {e}")
    
    def get_objects_list(self) -> List[Dict]:
        """
        Получение списка объектов
        
        Returns:
            Список объектов
        """
        url = f"{self.base_url}/getobjectslist"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                objects = data.get('objects', [])
                print(f"📋 Получено объектов: {len(objects)}")
                return objects
            else:
                print(f"⚠️  Ответ API: {data.get('result', 'Unknown error')}")
                return []
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка запроса объектов: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return []
    
    def get_object_sensors(self, object_id: int) -> List[Dict]:
        """
        Получение списка датчиков объекта
        
        Args:
            object_id: ID объекта
            
        Returns:
            Список датчиков
        """
        url = f"{self.base_url}/objsensorslist"
        params = {'objectId': object_id}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                return data.get('obj_sensors', [])
            else:
                print(f"   ⚠️  Нет датчиков для объекта {object_id}")
                return []
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Ошибка запроса датчиков: {e}")
            return []
    
    def get_object_data(self, object_id: int, sensor_ids: List[int] = None) -> Dict:
        """
        Получение значений датчиков объекта
        
        Args:
            object_id: ID объекта
            sensor_ids: Список SID датчиков (если None - все датчики)
            
        Returns:
            Словарь с данными датчиков
        """
        url = f"{self.base_url}/objdata"
        params = {'objectId': object_id}
        
        if sensor_ids:
            params['sensorIds'] = ','.join(map(str, sensor_ids))
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                sensor_data = {}
                
                # Ищем данные в разных форматах ответа
                if 'sensor_data' in data:
                    for item in data['sensor_data']:
                        if 'sid' in item:
                            sensor_data[item['sid']] = item
                        elif 'sensorId' in item:
                            sensor_data[item['sensorId']] = item
                
                # Проверяем другие возможные форматы
                for key, value in data.items():
                    if key not in ['result', 'objectId', 'timestamp', 'session']:
                        if isinstance(value, dict) and ('value' in value or 'Value' in value):
                            sid = value.get('sid', value.get('sensorId', key))
                            sensor_data[sid] = value
                        elif isinstance(value, (int, float, str)):
                            sensor_data[key] = {'value': value}
                
                return sensor_data
            else:
                return {}
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Ошибка запроса данных: {e}")
            return {}
        except json.JSONDecodeError as e:
            print(f"   ❌ Ошибка JSON в ответе: {e}")
            return {}
    
    def get_objects_fuel_info(self, object_ids: List[int] = None) -> Dict:
        """
        Получение данных датчиков топлива по объектам
        
        Args:
            object_ids: Список ID объектов
            
        Returns:
            Данные по топливу
        """
        url = f"{self.base_url}/getobjectsfuelinfo"
        params = {}
        
        if object_ids:
            params['objectIds'] = ','.join(map(str, object_ids[:10]))  # Ограничиваем 10 объектами
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                return data
            else:
                return {}
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Ошибка запроса данных по топливу: {e}")
            return {}
    
    def get_tree(self) -> Dict:
        """
        Получение дерева объектов
        
        Returns:
            Дерево объектов
        """
        url = f"{self.base_url}/gettree"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('result') == 'Ok':
                return data
            else:
                return {}
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка запроса дерева: {e}")
            return {}


def categorize_sensor(sensor_name: str) -> str:
    """
    Категоризация датчика по названию
    
    Args:
        sensor_name: Название датчика
        
    Returns:
        Категория
    """
    if not sensor_name:
        return 'Неизвестно'
    
    name_lower = sensor_name.lower()
    
    # Категория: Пробег
    mileage_keywords = ['пробег', 'пробіг', 'mileage', 'odometer', 'distance', 'абсолютный пробег', 'накопленного пробега', 'накопленный пробег']
    if any(keyword in name_lower for keyword in mileage_keywords):
        return 'Пробег'
    
    # Категория: Скорость
    speed_keywords = ['скорость', 'швидкість', 'speed', 'спид']
    if any(keyword in name_lower for keyword in speed_keywords):
        return 'Скорость'
    
    # Категория: Топливо (уровень)
    fuel_level_keywords = ['топливо', 'паливо', 'fuel', 'бак', 'tank', 'лс', 'lls', 'дут', 'уровень', 'рівень', 'level', 'литр', 'л.', 'литров', 'liters', 'л ', 'бенз', 'дизель', 'diesel', 'gas', 'бензин']
    if any(keyword in name_lower for keyword in fuel_level_keywords):
        if 'расход' in name_lower or 'витрата' in name_lower or 'consumption' in name_lower or 'used' in name_lower:
            return 'Расход топлива'
        return 'Уровень топлива'
    
    # Категория: Расход топлива
    fuel_consumption_keywords = ['расход', 'витрата', 'consumption', 'fuel used', 'used fuel', 'расход топлива']
    if any(keyword in name_lower for keyword in fuel_consumption_keywords):
        return 'Расход топлива'
    
    # Категория: Обороты
    rpm_keywords = ['оборот', 'rpm', 'обороты', 'engine rpm', 'обороти', 'revolution']
    if any(keyword in name_lower for keyword in rpm_keywords):
        return 'Обороты двигателя'
    
    # Категория: Температура
    temp_keywords = ['температура', 'temperature', 'temp', '°t', 'градус', '°c', '°f', 'нагрев', 'охлаждение']
    if any(keyword in name_lower for keyword in temp_keywords):
        return 'Температура'
    
    # Категория: Моточасы
    motohours_keywords = ['моточас', 'moto', 'час', 'часов', 'engine hours', 'hours', 'моточасов', 'рабочих часов']
    if any(keyword in name_lower for keyword in motohours_keywords):
        return 'Моточасы'
    
    # Категория: CAN параметры
    can_keywords = ['can', 'кан', 'lvc', 'lvcan', 'controller area network']
    if any(keyword in name_lower for keyword in can_keywords):
        return 'CAN параметры'
    
    return 'Другие датчики'


def extract_sensor_value(sensor_data: Dict, sid: int, pid: int, sensor_name: str = '') -> Dict:
    """
    Извлечение значения датчика из данных
    
    Args:
        sensor_data: Данные всех датчиков
        sid: SID датчика
        pid: PID датчика
        sensor_name: Название датчика (для отладки)
        
    Returns:
        Словарь со значением и метаданными
    """
    value_info = {
        'value': None,
        'units': '',
        'timestamp': '',
        'status': ''
    }
    
    if not sensor_data:
        return value_info
    
    # Пытаемся найти по SID
    search_keys = []
    if sid != 0:
        search_keys.extend([str(sid), sid])
    
    # Пытаемся найти по PID
    if pid != 0:
        search_keys.extend([str(pid), pid])
    
    # Поиск данных
    found_data = None
    for key in search_keys:
        if key in sensor_data:
            found_data = sensor_data[key]
            break
    
    # Если не нашли по ключам, ищем в значениях словаря
    if not found_data:
        for key, data in sensor_data.items():
            if isinstance(data, dict):
                data_sid = data.get('sid') or data.get('sensorId')
                data_pid = data.get('pid')
                if (sid != 0 and data_sid == sid) or (pid != 0 and data_pid == pid):
                    found_data = data
                    break
    
    # Извлекаем данные
    if found_data:
        if isinstance(found_data, dict):
            # Пробуем разные ключи для значения
            value_keys = ['value', 'Value', 'val', 'Val', 'data', 'Data']
            for vk in value_keys:
                if vk in found_data:
                    value_info['value'] = found_data[vk]
                    break
            
            # Единицы измерения
            unit_keys = ['units', 'Units', 'unit', 'Unit', 'ед', 'Ед']
            for uk in unit_keys:
                if uk in found_data:
                    value_info['units'] = found_data[uk]
                    break
            
            # Время
            time_keys = ['timestamp', 'Timestamp', 'time', 'Time', 'date', 'Date']
            for tk in time_keys:
                if tk in found_data:
                    value_info['timestamp'] = found_data[tk]
                    break
            
            # Статус
            status_keys = ['status', 'Status', 'state', 'State']
            for sk in status_keys:
                if sk in found_data:
                    value_info['status'] = found_data[sk]
                    break
        else:
            value_info['value'] = found_data
    
    return value_info


def create_excel_report(all_data: List[Dict], filename: str = None) -> str:
    """
    Создание Excel отчета
    
    Args:
        all_data: Собранные данные
        filename: Имя файла
        
    Returns:
        Путь к файлу
    """
    if not all_data:
        print("❌ Нет данных для создания отчета")
        return ""
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fuel_mileage_report_{timestamp}.xlsx"
    
    # Создаем DataFrame
    df = pd.DataFrame(all_data)
    
    # Переименовываем колонки
    column_mapping = {
        'object_id': 'ID объекта',
        'object_name': 'Название объекта',
        'category': 'Категория',
        'sensor_name': 'Название датчика',
        'sid': 'SID',
        'pid': 'PID',
        'value': 'Значение',
        'units': 'Единицы измерения',
        'timestamp': 'Время обновления',
        'status': 'Статус',
        'icon': 'Иконка'
    }
    
    # Оставляем только существующие колонки
    existing_columns = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=existing_columns)
    
    # Сортируем по объекту и категории
    sort_columns = []
    if 'Название объекта' in df.columns:
        sort_columns.append('Название объекта')
    if 'Категория' in df.columns:
        sort_columns.append('Категория')
    
    if sort_columns:
        df = df.sort_values(by=sort_columns)
    
    # Создаем Excel файл
    try:
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            # 1. Все данные
            df.to_excel(writer, sheet_name='Все данные', index=False)
            
            # Автонастройка ширины колонок
            worksheet = writer.sheets['Все данные']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        cell_value = str(cell.value)
                        if len(cell_value) > max_length:
                            max_length = len(cell_value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
            
            # 2. Сводка по объектам
            if 'Название объекта' in df.columns and 'Значение' in df.columns:
                try:
                    # Конвертируем значения в числа
                    df_numeric = df.copy()
                    df_numeric['Значение_num'] = pd.to_numeric(df_numeric['Значение'], errors='coerce')
                    
                    # Сводная таблица
                    pivot = pd.pivot_table(
                        df_numeric,
                        index=['Название объекта'],
                        columns='Категория',
                        values='Значение_num',
                        aggfunc='first',
                        fill_value=''
                    )
                    pivot.to_excel(writer, sheet_name='Сводка по объектам')
                except Exception as e:
                    print(f"⚠️  Не удалось создать сводку: {e}")
            
            # 3. Только пробег
            if 'Категория' in df.columns:
                mileage_df = df[df['Категория'] == 'Пробег']
                if not mileage_df.empty:
                    mileage_df.to_excel(writer, sheet_name='Пробег', index=False)
            
            # 4. Только топливо
            if 'Категория' in df.columns:
                fuel_df = df[df['Категория'].isin(['Уровень топлива', 'Расход топлива'])]
                if not fuel_df.empty:
                    fuel_df.to_excel(writer, sheet_name='Топливо', index=False)
            
            # 5. Статистика
            stats_data = []
            categories = df['Категория'].unique() if 'Категория' in df.columns else []
            
            for category in categories:
                cat_df = df[df['Категория'] == category]
                if 'Значение' in cat_df.columns:
                    try:
                        values = pd.to_numeric(cat_df['Значение'], errors='coerce')
                        valid_values = values.dropna()
                        
                        if not valid_values.empty:
                            stats_data.append({
                                'Категория': category,
                                'Количество датчиков': len(valid_values),
                                'Среднее': round(valid_values.mean(), 2),
                                'Минимум': round(valid_values.min(), 2),
                                'Максимум': round(valid_values.max(), 2),
                                'Сумма': round(valid_values.sum(), 2)
                            })
                    except:
                        pass
            
            if stats_data:
                stats_df = pd.DataFrame(stats_data)
                stats_df.to_excel(writer, sheet_name='Статистика', index=False)
        
        print(f"\n✅ Отчет сохранен: {filename}")
        print(f"📊 Всего записей: {len(all_data)}")
        print(f"📂 Размер файла: {round(len(all_data) * 0.1, 1)} КБ (примерно)")
        
        return filename
        
    except Exception as e:
        print(f"❌ Ошибка при создании Excel файла: {e}")
        # Сохраняем в CSV как резервный вариант
        try:
            csv_filename = filename.replace('.xlsx', '.csv')
            df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
            print(f"✅ Данные сохранены в CSV: {csv_filename}")
            return csv_filename
        except:
            print("❌ Не удалось сохранить данные в CSV")
            return ""


def main():
    """
    Основная функция сбора данных и создания отчета
    """
    print("=" * 60)
    print("🚀 СБОР ДАННЫХ ПО ДАТЧИКАМ ПРОБЕГА И ТОПЛИВА")
    print("=" * 60)
    
    # === НАСТРОЙКИ ===
    BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
    LOGIN = "abvprom"
    PASSWORD = "29328"
    
    print(f"\n🔗 Подключаемся к серверу: {BASE_URL}")
    print(f"👤 Пользователь: {LOGIN}")
    
    # === 1. ПОДКЛЮЧЕНИЕ К API ===
    start_time = time.time()
    api = MonitoringAPI(
        base_url=BASE_URL,
        login=LOGIN,
        password=PASSWORD
    )
    
    if not api.session_id:
        print("❌ Не удалось подключиться к API")
        print("Проверьте:")
        print("1. Доступ к интернету")
        print("2. Правильность логина и пароля")
        print("3. Доступность сервера")
        return
    
    try:
        # === 2. ПОЛУЧЕНИЕ СПИСКА ОБЪЕКТОВ ===
        print("\n🔍 Получаем список объектов...")
        objects = api.get_objects_list()
        
        if not objects:
            print("Попробуем получить через дерево объектов...")
            tree_data = api.get_tree()
            if tree_data and 'objects' in tree_data:
                objects = tree_data['objects']
        
        if not objects:
            print("❌ Объекты не найдены")
            print("Возможные причины:")
            print("1. Нет доступных объектов в аккаунте")
            print("2. Ограничения прав доступа")
            print("3. Проблема с API")
            return
        
        print(f"✅ Найдено объектов: {len(objects)}")
        
        # Ограничиваем количество объектов для тестирования (раскомментируйте для теста)
        # objects = objects[:5]  # Только первые 5 объектов
        # print(f"⚠️  ТЕСТОВЫЙ РЕЖИМ: обрабатываем только {len(objects)} объектов")
        
        all_data = []
        processed_objects = 0
        success_objects = 0
        
        # === 3. ОБРАБОТКА КАЖДОГО ОБЪЕКТА ===
        for obj in objects:
            # Определяем ID и имя объекта
            object_id = obj.get('id') or obj.get('objectId') or obj.get('uid')
            object_name = obj.get('name') or obj.get('title') or f'Объект {object_id}'
            
            if not object_id:
                continue
            
            processed_objects += 1
            print(f"\n[{processed_objects}/{len(objects)}] 📍 Объект: {object_name}")
            print(f"   🔢 ID: {object_id}")
            
            # Получаем список датчиков объекта
            sensors = api.get_object_sensors(object_id)
            
            if not sensors:
                print(f"   ⚠️  Нет данных о датчиках")
                continue
            
            print(f"   📊 Всего датчиков: {len(sensors)}")
            
            # Фильтруем датчики пробега и топлива
            fuel_mileage_sensors = []
            for sensor in sensors:
                sensor_name = sensor.get('name', '')
                category = categorize_sensor(sensor_name)
                
                # Выбираем только нужные категории
                target_categories = ['Пробег', 'Скорость', 'Уровень топлива', 
                                   'Расход топлива', 'Обороты двигателя', 
                                   'Температура', 'Моточасы', 'CAN параметры']
                
                if category in target_categories:
                    sensor['category'] = category
                    fuel_mileage_sensors.append(sensor)
            
            if not fuel_mileage_sensors:
                print(f"   ⚠️  Нет датчиков пробега/топлива")
                continue
            
            print(f"   🔍 Датчиков пробега/топлива: {len(fuel_mileage_sensors)}")
            
            # Получаем значения датчиков
            sensor_ids = [s['sid'] for s in fuel_mileage_sensors if s['sid'] != 0]
            sensor_data = api.get_object_data(object_id, sensor_ids)
            
            # Считаем сколько датчиков получили значения
            sensors_with_values = 0
            
            # Формируем данные для отчета
            for sensor in fuel_mileage_sensors:
                value_info = extract_sensor_value(
                    sensor_data, 
                    sensor['sid'], 
                    sensor['pid'],
                    sensor.get('name', '')
                )
                
                record = {
                    'object_id': object_id,
                    'object_name': object_name,
                    'category': sensor['category'],
                    'sensor_name': sensor.get('name', ''),
                    'sid': sensor.get('sid', ''),
                    'pid': sensor.get('pid', ''),
                    'icon': sensor.get('icon', ''),
                    'value': value_info['value'],
                    'units': value_info['units'],
                    'timestamp': value_info['timestamp'],
                    'status': value_info['status']
                }
                
                if value_info['value'] is not None:
                    sensors_with_values += 1
                
                all_data.append(record)
            
            if sensors_with_values > 0:
                success_objects += 1
                print(f"   ✅ Получено значений: {sensors_with_values}/{len(fuel_mileage_sensors)}")
            else:
                print(f"   ⚠️  Нет значений датчиков")
            
            # Пауза между запросами (чтобы не перегружать сервер)
            if processed_objects < len(objects):
                time.sleep(0.2)  # 200 мс пауза
        
        # === 4. ДОПОЛНИТЕЛЬНО: ПОЛУЧЕНИЕ ДАННЫХ ПО ТОПЛИВУ ===
        print("\n⛽ Получаем дополнительные данные по топливу...")
        try:
            object_ids = [obj.get('id') or obj.get('objectId') for obj in objects 
                         if obj.get('id') or obj.get('objectId')]
            fuel_data = api.get_objects_fuel_info(object_ids[:10])  # Ограничиваем 10 объектами
            
            if fuel_data and 'fuel_info' in fuel_data:
                fuel_info = fuel_data.get('fuel_info', [])
                print(f"   ✅ Получены данные по топливу для {len(fuel_info)} объектов")
                
                # Добавляем данные по топливу в отчет
                for fuel_item in fuel_info:
                    # Можно добавить дополнительную обработку данных по топливу
                    pass
        except Exception as e:
            print(f"   ⚠️  Не удалось получить данные по топливу: {e}")
        
        # === 5. СОЗДАНИЕ ОТЧЕТА ===
        elapsed_time = time.time() - start_time
        
        if all_data:
            print(f"\n📈 СБОР ДАННЫХ ЗАВЕРШЕН")
            print(f"⏱️  Время выполнения: {elapsed_time:.1f} сек.")
            print(f"✅ Успешно обработано объектов: {success_objects}/{processed_objects}")
            print(f"📊 Всего записей: {len(all_data)}")
            
            # Группировка по категориям
            categories_count = {}
            for record in all_data:
                category = record.get('category', 'Неизвестно')
                categories_count[category] = categories_count.get(category, 0) + 1
            
            print("\n📊 Статистика по категориям:")
            for category, count in sorted(categories_count.items()):
                print(f"   {category}: {count} датчиков")
            
            # Подсчет датчиков со значениями
            sensors_with_data = sum(1 for record in all_data if record.get('value') is not None)
            print(f"   Датчиков со значениями: {sensors_with_data}/{len(all_data)}")
            
            # Создаем отчет
            print("\n💾 Сохраняем данные в Excel...")
            filename = create_excel_report(all_data)
            
            if filename:
                # Выводим пример данных
                print("\n📋 Пример данных из отчета:")
                for i, record in enumerate(all_data[:5]):
                    value_str = str(record.get('value', 'N/A'))
                    if len(value_str) > 30:
                        value_str = value_str[:27] + "..."
                    
                    print(f"   {i+1}. {record.get('object_name')} - {record.get('sensor_name')}: {value_str} {record.get('units', '')}")
            
        else:
            print(f"\n❌ Не удалось собрать данные")
            print(f"⏱️  Время выполнения: {elapsed_time:.1f} сек.")
            print("Возможные причины:")
            print("1. У объектов нет датчиков пробега/топлива")
            print("2. Проблемы с доступом к данным датчиков")
            print("3. Ограничения прав доступа к API")
            print("4. Технические проблемы на сервере")
    
    finally:
        # === 6. ЗАКРЫТИЕ СЕССИИ ===
        print("\n🔒 Закрытие сессии...")
        api.disconnect()
    
    print("\n" + "=" * 60)
    print("✅ ПРОГРАММА ЗАВЕРШЕНА")
    print("=" * 60)


if __name__ == "__main__":
    main()