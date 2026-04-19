"""
Скрипт для получения показаний одометра через Mobiteam GPS API
Рабочая версия с правильной авторизацией
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple


class MobiteamAPI:
    """Класс для работы с Mobiteam GPS API"""
    
    def __init__(self, base_url: str, login: str, password: str):
        """
        Инициализация подключения к API
        
        Args:
            base_url: Базовый URL сервера
            login: Логин пользователя
            password: Пароль пользователя
        """
        self.base_url = base_url.rstrip('/')
        self.login = login
        self.password = password
        self.session = requests.Session()
        self.session_id = None
        
    def connect(self) -> bool:
        """
        Авторизация и получение SessionId
        
        Returns:
            True если авторизация успешна
        """
        try:
            url = f"{self.base_url}/api/integration/v1/connect"
            
            params = {
                'login': self.login,
                'password': self.password,
                'lang': 'ru-ru',
                'timezone': '3'  # UTC+3 для Украины
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                result = response.text.strip('"')  # Убираем кавычки из "Ok"
                
                if result == 'Ok':
                    # Получаем SessionId из заголовков
                    self.session_id = response.headers.get('sessionid', response.headers.get('SessionId'))
                    
                    if self.session_id:
                        # Добавляем SessionId в заголовки для всех последующих запросов
                        self.session.headers.update({'SessionId': self.session_id})
                        print("✓ Успешная авторизация в Mobiteam")
                        print(f"  SessionId: {self.session_id[:20]}...")
                        return True
                    else:
                        print("✗ Ошибка: SessionId не получен")
                        return False
                else:
                    print(f"✗ Ошибка авторизации: {result}")
                    return False
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                print(f"  Ответ: {response.text}")
                return False
                
        except Exception as e:
            print(f"✗ Ошибка при авторизации: {e}")
            return False
    
    def disconnect(self):
        """Закрытие сессии"""
        try:
            if self.session_id:
                url = f"{self.base_url}/api/integration/v1/disconnect"
                self.session.get(url)
                print("✓ Сессия закрыта")
        except Exception as e:
            print(f"⚠ Предупреждение при закрытии сессии: {e}")
    
    def get_objects_list(self) -> List[Dict]:
        """
        Получение списка объектов (транспортных средств)
        
        Returns:
            Список объектов
        """
        try:
            url = f"{self.base_url}/api/integration/v1/objectslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                
                result = data.get('result', '')
                if result == 'Ok':
                    objects = data.get('objects', [])
                    return objects
                else:
                    print(f"✗ Ошибка API: {result}")
                    return []
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении объектов: {e}")
            return []
    
    def get_geozones_list(self) -> List[Dict]:
        """
        Получение списка геозон
        
        Returns:
            Список геозон
        """
        try:
            url = f"{self.base_url}/api/integration/v1/geozoneslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                
                result = data.get('result', '')
                if result == 'Ok':
                    geozones = data.get('geozones', [])
                    return geozones
                else:
                    print(f"✗ Ошибка API: {result}")
                    return []
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении геозон: {e}")
            return []
    
    def get_track(self, object_id: int, date_from: datetime, 
                  date_to: datetime) -> List[Dict]:
        """
        Получение трека движения объекта
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Список точек трека
        """
        try:
            url = f"{self.base_url}/api/integration/v1/track"
            
            params = {
                'oid': object_id,
                'sdt': date_from.strftime('%Y-%m-%d %H:%M:%S'),
                'edt': date_to.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                result = data.get('result', '')
                if result == 'Ok':
                    track = data.get('track', [])
                    return track
                else:
                    print(f"✗ Ошибка API: {result}")
                    return []
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении трека: {e}")
            return []
    
    def get_object_sensors(self, object_id: int) -> List[Dict]:
        """
        Получение списка датчиков объекта
        
        Args:
            object_id: ID объекта
            
        Returns:
            Список датчиков
        """
        try:
            url = f"{self.base_url}/api/integration/v1/objsensorslist"
            
            params = {
                'oid': object_id
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                result = data.get('result', '')
                if result == 'Ok':
                    sensors = data.get('obj_sensors', [])
                    return sensors
                else:
                    print(f"⚠ Ошибка получения датчиков: {result}")
                    return []
            else:
                print(f"⚠ Ошибка HTTP: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"⚠ Ошибка при получении датчиков: {e}")
            return []
    
    def get_objects_report(self, object_id: int, date_from: datetime, 
                          date_to: datetime) -> Optional[Dict]:
        """
        Получение отчета по объекту (может содержать пробег, время в движении и т.д.)
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Данные отчета
        """
        try:
            url = f"{self.base_url}/api/integration/v1/getobjectsreport"
            
            params = {
                'oid': object_id,
                'sdt': date_from.strftime('%Y-%m-%d %H:%M:%S'),
                'edt': date_to.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                result = data.get('result', '')
                if result == 'Ok':
                    return data
                else:
                    print(f"⚠ Отчет недоступен: {result}")
                    return None
            else:
                print(f"⚠ Ошибка HTTP: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"⚠ Ошибка при получении отчета: {e}")
            return None


def is_point_in_circle_geozone(lat: float, lon: float, geozone: Dict) -> bool:
    """
    Проверка, находится ли точка внутри круговой геозоны
    """
    from math import radians, sin, cos, sqrt, atan2
    
    # Разные варианты названий полей в API
    center_lat = geozone.get('lat', geozone.get('latitude', 0))
    center_lon = geozone.get('lon', geozone.get('longitude', 0))
    radius = geozone.get('r', geozone.get('radius', 0))
    
    if radius == 0:
        return False
    
    R = 6371000  # Радиус Земли в метрах
    
    lat1 = radians(lat)
    lon1 = radians(lon)
    lat2 = radians(center_lat)
    lon2 = radians(center_lon)
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    
    return distance <= radius


def find_garage_enter_exit(api: MobiteamAPI, object_id: int, 
                           garage_geozone: Dict, date: datetime) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Поиск событий выезда/въезда через анализ трека
    """
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n📅 Анализ данных за {date.strftime('%d.%m.%Y')}...")
    
    # Получаем трек
    track = api.get_track(object_id, date_from, date_to)
    
    if not track:
        print("⚠ Трек движения не найден")
        print("  Возможные причины:")
        print("  - Транспорт не выезжал в этот день")
        print("  - GPS терминал был выключен")
        print("  - Нет данных за этот период")
        return None, None
    
    print(f"✓ Получено {len(track)} точек трека")
    
    # Анализируем трек
    first_exit = None
    last_enter = None
    prev_in_garage = None
    
    for point in track:
        # Разные варианты названий полей
        lat = point.get('lat', point.get('latitude', 0))
        lon = point.get('lon', point.get('longitude', 0))
        mileage = point.get('m', point.get('mileage', point.get('odometer', 0)))
        dt = point.get('dt', point.get('time', point.get('timestamp', '')))
        
        in_garage = is_point_in_circle_geozone(lat, lon, garage_geozone)
        
        if prev_in_garage is not None:
            # Выезд из гаража
            if prev_in_garage and not in_garage and first_exit is None:
                first_exit = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🚗 Выезд: {dt}, одометр: {mileage:.2f} км")
            
            # Въезд в гараж
            elif not prev_in_garage and in_garage:
                last_enter = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🏠 Въезд: {dt}, одометр: {mileage:.2f} км")
        
        prev_in_garage = in_garage
    
    return first_exit, last_enter


def main():
    """Главная функция"""
    
    print("=" * 60)
    print("Mobiteam GPS - Получение показаний одометра")
    print("Версия 1.0 - Рабочая")
    print("=" * 60)
    
    # ========================================
    # ПОСТОЯННЫЕ НАСТРОЙКИ (уже заполнено)
    # ========================================
    
    BASE_URL = "https://gps.mobiteam.com.ua"
    LOGIN = "abvprom"
    PASSWORD = "29328"
    
    # ========================================
    
    print(f"\n🔐 Подключение к Mobiteam API...")
    print(f"   Сервер: {BASE_URL}")
    print(f"   Логин: {LOGIN}")
    
    # Инициализация и авторизация
    api = MobiteamAPI(BASE_URL, LOGIN, PASSWORD)
    
    if not api.connect():
        print("\n❌ Не удалось авторизоваться")
        print("\nПроверьте:")
        print("1. Правильность логина и пароля в скрипте")
        print("2. Доступность сервера gps.mobiteam.com.ua")
        print("3. Подключение к интернету")
        return
    
    try:
        # Получение списка объектов
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects_list()
        
        if not objects:
            print("⚠ Объекты не найдены")
            print("  Проверьте, что у вашего пользователя есть доступ к объектам")
            return
        
        print(f"✓ Найдено объектов: {len(objects)}")
        print("\nДоступные транспортные средства:")
        for i, obj in enumerate(objects, 1):
            obj_id = obj.get('id', obj.get('oid', ''))
            obj_name = obj.get('name', 'Без названия')
            obj_plate = obj.get('plate_num', obj.get('plate', ''))
            print(f"  {i}. ID: {obj_id} - {obj_name} ({obj_plate})")
        
        # Выбор объекта
        object_choice = int(input("\nВыберите номер транспортного средства: ")) - 1
        selected_object = objects[object_choice]
        object_id = selected_object.get('id', selected_object.get('oid'))
        
        print(f"\n✓ Выбран объект: {selected_object.get('name', 'Без названия')}")
        
        # Получение и вывод датчиков объекта
        print("\n🔧 Проверка доступных датчиков...")
        sensors = api.get_object_sensors(object_id)
        
        if sensors:
            print(f"✓ Найдено датчиков: {len(sensors)}")
            print("\nДатчики на транспортном средстве:")
            for sensor in sensors:
                sensor_id = sensor.get('sid', '')
                sensor_name = sensor.get('name', 'Без названия')
                print(f"  • {sensor_name} (ID: {sensor_id})")
        else:
            print("⚠ Датчики не найдены или недоступны")
        
        # Получение списка геозон
        print("\n📍 Загрузка списка геозон...")
        geozones = api.get_geozones_list()
        
        if not geozones:
            print("⚠ Геозоны не найдены")
            print("  Создайте геозоны в веб-интерфейсе Mobiteam")
            return
        
        print(f"✓ Найдено геозон: {len(geozones)}")
        print("\nДоступные геозоны:")
        for i, gz in enumerate(geozones, 1):
            gz_id = gz.get('id', '')
            gz_name = gz.get('name', 'Без названия')
            gz_type = gz.get('t', 0)  # 0 = круг, 1 = полигон
            gz_type_text = 'круг' if gz_type == 0 else 'полигон'
            print(f"  {i}. ID: {gz_id} - {gz_name} ({gz_type_text})")
        
        # Выбор геозоны гаража
        geozone_choice = int(input("\nВыберите номер геозоны гаража: ")) - 1
        selected_geozone = geozones[geozone_choice]
        
        print(f"\n✓ Выбрана геозона: {selected_geozone.get('name', 'Без названия')}")
        
        # Выбор даты
        date_input = input("\nВведите дату (ДД.ММ.ГГГГ) или нажмите Enter для сегодняшнего дня: ").strip()
        
        if date_input:
            target_date = datetime.strptime(date_input, "%d.%m.%Y")
        else:
            target_date = datetime.now()
        
        # Поиск событий
        first_exit, last_enter = find_garage_enter_exit(
            api, object_id, selected_geozone, target_date
        )
        
        # Вывод результатов
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТ")
        print("=" * 60)
        
        if first_exit:
            print(f"\n🚗 ВЫЕЗД ИЗ ГАРАЖА:")
            print(f"   Время: {first_exit['time']}")
            print(f"   Показание одометра: {first_exit['mileage']:.2f} км")
        else:
            print("\n⚠ Выезд из гаража не обнаружен")
        
        if last_enter:
            print(f"\n🏠 ВЪЕЗД В ГАРАЖ:")
            print(f"   Время: {last_enter['time']}")
            print(f"   Показание одометра: {last_enter['mileage']:.2f} км")
        else:
            print("\n⚠ Въезд в гараж не обнаружен")
        
        if first_exit and last_enter:
            daily_mileage = last_enter['mileage'] - first_exit['mileage']
            print(f"\n📊 ПРОБЕГ ЗА ДЕНЬ: {daily_mileage:.2f} км")
            
            # Дополнительная информация
            try:
                departure_time = datetime.strptime(first_exit['time'], '%Y-%m-%d %H:%M:%S')
                arrival_time = datetime.strptime(last_enter['time'], '%Y-%m-%d %H:%M:%S')
                duration = arrival_time - departure_time
                hours = duration.total_seconds() / 3600
                print(f"⏱  ВРЕМЯ В ПУТИ: {hours:.2f} часов")
            except:
                pass
        
    except KeyboardInterrupt:
        print("\n\n⚠ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем сессию
        api.disconnect()
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()
