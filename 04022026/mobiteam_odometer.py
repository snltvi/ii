"""
Скрипт для получения показаний одометра через Mobiteam GPS API
при выезде из геозоны гаража и возвращении
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import time


class MobiteamAPI:
    """Класс для работы с Mobiteam GPS API"""
    
    def __init__(self, base_url: str, api_key: str):
        """
        Инициализация подключения к API
        
        Args:
            base_url: Базовый URL сервера (например: https://gps.mobiteam.com.ua)
            api_key: API ключ для авторизации
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
        
    def test_connection(self) -> bool:
        """
        Проверка подключения к API
        
        Returns:
            True если подключение успешно
        """
        try:
            url = f"{self.base_url}/api/v1/objects"
            response = self.session.get(url)
            
            if response.status_code == 200:
                print("✓ Успешное подключение к Mobiteam API")
                return True
            else:
                print(f"✗ Ошибка подключения: {response.status_code}")
                print(f"  Ответ: {response.text}")
                return False
                
        except Exception as e:
            print(f"✗ Ошибка при подключении: {e}")
            return False
    
    def get_objects(self) -> List[Dict]:
        """
        Получение списка объектов (транспортных средств)
        
        Returns:
            Список объектов
        """
        try:
            url = f"{self.base_url}/api/v1/objects"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else data.get('objects', [])
            else:
                print(f"✗ Ошибка получения объектов: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении объектов: {e}")
            return []
    
    def get_geozones(self) -> List[Dict]:
        """
        Получение списка геозон
        
        Returns:
            Список геозон
        """
        try:
            url = f"{self.base_url}/api/v1/geozones"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else data.get('geozones', [])
            else:
                print(f"✗ Ошибка получения геозон: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении геозон: {e}")
            return []
    
    def get_object_report(self, object_id: int, date_from: datetime, 
                          date_to: datetime, report_type: str = "trips") -> Optional[Dict]:
        """
        Получение отчета по объекту
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            report_type: Тип отчета (trips, parkings, events, etc.)
            
        Returns:
            Данные отчета или None
        """
        try:
            url = f"{self.base_url}/api/v1/reports/{report_type}"
            
            params = {
                'objectId': object_id,
                'from': date_from.strftime('%Y-%m-%dT%H:%M:%S'),
                'to': date_to.strftime('%Y-%m-%dT%H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"✗ Ошибка получения отчета: {response.status_code}")
                print(f"  URL: {response.url}")
                print(f"  Ответ: {response.text}")
                return None
                
        except Exception as e:
            print(f"✗ Ошибка при получении отчета: {e}")
            return None
    
    def get_track(self, object_id: int, date_from: datetime, 
                  date_to: datetime) -> List[Dict]:
        """
        Получение трека движения объекта с точками
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Список точек трека
        """
        try:
            url = f"{self.base_url}/api/v1/track"
            
            params = {
                'objectId': object_id,
                'from': date_from.strftime('%Y-%m-%dT%H:%M:%S'),
                'to': date_to.strftime('%Y-%m-%dT%H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else data.get('track', [])
            else:
                print(f"✗ Ошибка получения трека: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении трека: {e}")
            return []
    
    def get_geozone_events(self, object_id: int, geozone_id: int, 
                          date_from: datetime, date_to: datetime) -> List[Dict]:
        """
        Получение событий входа/выхода из геозоны
        
        Args:
            object_id: ID объекта
            geozone_id: ID геозоны
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Список событий геозоны
        """
        try:
            url = f"{self.base_url}/api/v1/events/geozone"
            
            params = {
                'objectId': object_id,
                'geozoneId': geozone_id,
                'from': date_from.strftime('%Y-%m-%dT%H:%M:%S'),
                'to': date_to.strftime('%Y-%m-%dT%H:%M:%S')
            }
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else data.get('events', [])
            else:
                print(f"⚠ События геозоны не получены: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"⚠ Ошибка при получении событий геозоны: {e}")
            return []


def is_point_in_circle_geozone(lat: float, lon: float, geozone: Dict) -> bool:
    """
    Проверка, находится ли точка внутри круговой геозоны
    
    Args:
        lat: Широта точки
        lon: Долгота точки
        geozone: Данные геозоны
        
    Returns:
        True если точка внутри геозоны
    """
    # Для круговой геозоны
    center_lat = geozone.get('latitude', geozone.get('lat', 0))
    center_lon = geozone.get('longitude', geozone.get('lon', 0))
    radius = geozone.get('radius', 0)  # в метрах
    
    if radius == 0:
        return False
    
    # Формула Haversine для расчета расстояния
    from math import radians, sin, cos, sqrt, atan2
    
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


def find_garage_enter_exit_from_track(api: MobiteamAPI, object_id: int, 
                                      garage_geozone: Dict, date: datetime) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Поиск событий выезда/въезда через анализ трека
    
    Args:
        api: Экземпляр API
        object_id: ID объекта
        garage_geozone: Данные геозоны гаража
        date: Дата для поиска
        
    Returns:
        Кортеж (первый_выезд, последний_въезд)
    """
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n📅 Анализ трека за {date.strftime('%d.%m.%Y')}...")
    
    # Получаем трек
    track = api.get_track(object_id, date_from, date_to)
    
    if not track:
        print("⚠ Трек движения не найден")
        return None, None
    
    print(f"✓ Получено {len(track)} точек трека")
    
    # Анализируем трек
    first_exit = None
    last_enter = None
    prev_in_garage = None
    
    for point in track:
        # Разные API могут возвращать разные названия полей
        lat = point.get('latitude', point.get('lat', 0))
        lon = point.get('longitude', point.get('lon', 0))
        mileage = point.get('mileage', point.get('odometer', 0))
        timestamp = point.get('timestamp', point.get('time', point.get('dt', '')))
        
        in_garage = is_point_in_circle_geozone(lat, lon, garage_geozone)
        
        if prev_in_garage is not None:
            # Выезд из гаража
            if prev_in_garage and not in_garage and first_exit is None:
                first_exit = {
                    'time': timestamp,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🚗 Выезд: {timestamp}, одометр: {mileage:.2f} км")
            
            # Въезд в гараж
            elif not prev_in_garage and in_garage:
                last_enter = {
                    'time': timestamp,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🏠 Въезд: {timestamp}, одометр: {mileage:.2f} км")
        
        prev_in_garage = in_garage
    
    return first_exit, last_enter


def find_garage_enter_exit_from_events(api: MobiteamAPI, object_id: int, 
                                       geozone_id: int, date: datetime) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Поиск событий выезда/въезда через события геозоны
    
    Args:
        api: Экземпляр API
        object_id: ID объекта
        geozone_id: ID геозоны
        date: Дата для поиска
        
    Returns:
        Кортеж (первый_выезд, последний_въезд)
    """
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n📅 Получение событий геозоны за {date.strftime('%d.%m.%Y')}...")
    
    # Получаем события
    events = api.get_geozone_events(object_id, geozone_id, date_from, date_to)
    
    if not events:
        print("⚠ События геозоны не найдены, попробуем через трек")
        return None, None
    
    print(f"✓ Получено {len(events)} событий геозоны")
    
    first_exit = None
    last_enter = None
    
    for event in events:
        event_type = event.get('type', event.get('eventType', ''))
        timestamp = event.get('timestamp', event.get('time', ''))
        mileage = event.get('mileage', event.get('odometer', 0))
        
        # Выезд из геозоны (exit, leave, out)
        if 'exit' in event_type.lower() or 'leave' in event_type.lower() or 'out' in event_type.lower():
            if first_exit is None:
                first_exit = {
                    'time': timestamp,
                    'mileage': mileage
                }
                print(f"🚗 Выезд: {timestamp}, одометр: {mileage:.2f} км")
        
        # Въезд в геозону (enter, in)
        elif 'enter' in event_type.lower() or 'in' == event_type.lower():
            last_enter = {
                'time': timestamp,
                'mileage': mileage
            }
            print(f"🏠 Въезд: {timestamp}, одометр: {mileage:.2f} км")
    
    return first_exit, last_enter


def main():
    """Главная функция"""
    
    print("=" * 60)
    print("Mobiteam GPS - Получение показаний одометра")
    print("=" * 60)
    
    # Настройки подключения (ЗАПОЛНИТЕ СВОИ ДАННЫЕ)
    BASE_URL = "https://gps.mobiteam.com.ua"
    API_KEY = "ваш_api_ключ"  # Получите в личном кабинете Mobiteam
    
    # АЛЬТЕРНАТИВНЫЙ ВАРИАНТ: Логин/пароль (если API ключа нет)
    # В этом случае нужно будет добавить метод авторизации
    # USERNAME = "ваш_логин"
    # PASSWORD = "ваш_пароль"
    
    # Инициализация API
    api = MobiteamAPI(BASE_URL, API_KEY)
    
    # Проверка подключения
    if not api.test_connection():
        print("\n❌ Не удалось подключиться к API")
        print("\nПроверьте:")
        print("1. Правильность API ключа")
        print("2. Доступность сервера")
        print("3. Наличие прав доступа к API в вашем аккаунте")
        return
    
    try:
        # Получение списка объектов
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects()
        
        if not objects:
            print("⚠ Объекты не найдены")
            return
        
        print(f"✓ Найдено объектов: {len(objects)}")
        print("\nДоступные транспортные средства:")
        for i, obj in enumerate(objects, 1):
            obj_id = obj.get('id', obj.get('objectId', ''))
            obj_name = obj.get('name', obj.get('objectName', 'Без названия'))
            obj_plate = obj.get('plateNumber', obj.get('gos_num', obj.get('regNumber', '')))
            print(f"  {i}. ID: {obj_id} - {obj_name} ({obj_plate})")
        
        # Выбор объекта
        object_choice = int(input("\nВыберите номер транспортного средства: ")) - 1
        selected_object = objects[object_choice]
        object_id = selected_object.get('id', selected_object.get('objectId'))
        
        print(f"\n✓ Выбран объект: {selected_object.get('name', 'Без названия')}")
        
        # Получение списка геозон
        print("\n📍 Загрузка списка геозон...")
        geozones = api.get_geozones()
        
        if not geozones:
            print("⚠ Геозоны не найдены")
            return
        
        print(f"✓ Найдено геозон: {len(geozones)}")
        print("\nДоступные геозоны:")
        for i, gz in enumerate(geozones, 1):
            gz_id = gz.get('id', gz.get('geozoneId', ''))
            gz_name = gz.get('name', gz.get('geozoneName', 'Без названия'))
            print(f"  {i}. ID: {gz_id} - {gz_name}")
        
        # Выбор геозоны гаража
        geozone_choice = int(input("\nВыберите номер геозоны гаража: ")) - 1
        selected_geozone = geozones[geozone_choice]
        garage_geozone_id = selected_geozone.get('id', selected_geozone.get('geozoneId'))
        
        print(f"\n✓ Выбрана геозона: {selected_geozone.get('name', 'Без названия')}")
        
        # Выбор даты
        date_input = input("\nВведите дату (ДД.ММ.ГГГГ) или нажмите Enter для сегодняшнего дня: ").strip()
        
        if date_input:
            target_date = datetime.strptime(date_input, "%d.%m.%Y")
        else:
            target_date = datetime.now()
        
        # Пробуем получить данные через события геозоны
        first_exit, last_enter = find_garage_enter_exit_from_events(
            api, object_id, garage_geozone_id, target_date
        )
        
        # Если через события не получилось, пробуем через трек
        if first_exit is None and last_enter is None:
            print("\n⚠ События геозоны недоступны, анализируем трек движения...")
            first_exit, last_enter = find_garage_enter_exit_from_track(
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
        
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()
