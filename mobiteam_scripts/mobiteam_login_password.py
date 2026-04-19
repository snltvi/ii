"""
Скрипт для получения показаний одометра через Mobiteam GPS API
с авторизацией через логин и пароль
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import time


class MobiteamAPI:
    """Класс для работы с Mobiteam GPS API"""
    
    def __init__(self, base_url: str, username: str, password: str):
        """
        Инициализация подключения к API
        
        Args:
            base_url: Базовый URL сервера (например: https://gps.mobiteam.com.ua)
            username: abvprom
            password: 29328
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.authenticated = False
        
    def login(self) -> bool:
        """
        Авторизация в системе
        
        Returns:
            True если авторизация успешна
        """
        try:
            # Пробуем метод авторизации через API
            url = f"{self.base_url}/api/integration/v1/login"
            
            payload = {
                "username": self.username,
                "password": self.password
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get('result', '')
                
                if result == 'Ok' or result == 'OK':
                    self.authenticated = True
                    print("✓ Успешная авторизация в Mobiteam")
                    return True
                else:
                    print(f"✗ Ошибка авторизации: {result}")
                    
                    # Пробуем альтернативный метод
                    return self._try_alternative_login()
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return self._try_alternative_login()
                
        except Exception as e:
            print(f"✗ Ошибка при авторизации: {e}")
            return self._try_alternative_login()
    
    def _try_alternative_login(self) -> bool:
        """Альтернативный метод авторизации через веб-форму"""
        try:
            print("⚙ Пробуем альтернативный метод авторизации...")
            
            # Метод 1: Через стандартную форму логина
            url = f"{self.base_url}/Account/Login"
            
            payload = {
                "UserName": self.username,
                "Password": self.password,
                "RememberMe": "false"
            }
            
            response = self.session.post(url, data=payload, allow_redirects=True)
            
            # Проверяем, что получили Cookie
            if self.session.cookies:
                print("✓ Получены Cookie авторизации")
                self.authenticated = True
                return True
            
            # Метод 2: Basic Auth
            print("⚙ Пробуем Basic Authentication...")
            self.session.auth = (self.username, self.password)
            
            # Тестовый запрос
            test_url = f"{self.base_url}/api/integration/v1/objsensorslist"
            response = self.session.get(test_url, params={'oid': 1})
            
            if response.status_code == 200:
                data = response.json()
                if data.get('result') != 'PermissionsNotEnough':
                    print("✓ Basic Authentication работает")
                    self.authenticated = True
                    return True
            
            print("✗ Не удалось авторизоваться альтернативными методами")
            return False
            
        except Exception as e:
            print(f"✗ Ошибка альтернативной авторизации: {e}")
            return False
    
    def get_objects_list(self) -> List[Dict]:
        """
        Получение списка объектов (транспортных средств)
        
        Returns:
            Список объектов
        """
        if not self.authenticated:
            print("✗ Требуется авторизация")
            return []
        
        try:
            url = f"{self.base_url}/api/integration/v1/objectslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('result') == 'Ok':
                    objects = data.get('objects', [])
                    return objects
                else:
                    print(f"✗ Ошибка API: {data.get('result')}")
                    return []
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
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
        if not self.authenticated:
            print("✗ Требуется авторизация")
            return []
        
        try:
            url = f"{self.base_url}/api/integration/v1/geozoneslist"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('result') == 'Ok':
                    geozones = data.get('geozones', [])
                    return geozones
                else:
                    print(f"✗ Ошибка API: {data.get('result')}")
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
        if not self.authenticated:
            print("✗ Требуется авторизация")
            return []
        
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
                
                if data.get('result') == 'Ok':
                    track = data.get('track', [])
                    return track
                else:
                    print(f"✗ Ошибка API: {data.get('result')}")
                    return []
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"✗ Ошибка при получении трека: {e}")
            return []
    
    def get_objects_report(self, object_id: int, date_from: datetime, 
                          date_to: datetime) -> Optional[Dict]:
        """
        Получение отчета по объекту
        
        Args:
            object_id: ID объекта
            date_from: Начало периода
            date_to: Конец периода
            
        Returns:
            Данные отчета
        """
        if not self.authenticated:
            print("✗ Требуется авторизация")
            return None
        
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
                
                if data.get('result') == 'Ok':
                    return data
                else:
                    print(f"✗ Ошибка API: {data.get('result')}")
                    return None
            else:
                print(f"✗ Ошибка HTTP: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"✗ Ошибка при получении отчета: {e}")
            return None


def is_point_in_circle_geozone(lat: float, lon: float, geozone: Dict) -> bool:
    """
    Проверка, находится ли точка внутри круговой геозоны
    """
    from math import radians, sin, cos, sqrt, atan2
    
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
        return None, None
    
    print(f"✓ Получено {len(track)} точек трека")
    
    # Анализируем трек
    first_exit = None
    last_enter = None
    prev_in_garage = None
    
    for point in track:
        lat = point.get('lat', point.get('latitude', 0))
        lon = point.get('lon', point.get('longitude', 0))
        mileage = point.get('mileage', point.get('m', 0))
        dt = point.get('dt', point.get('time', ''))
        
        in_garage = is_point_in_circle_geozone(lat, lon, garage_geozone)
        
        if prev_in_garage is not None:
            if prev_in_garage and not in_garage and first_exit is None:
                first_exit = {
                    'time': dt,
                    'mileage': mileage,
                    'lat': lat,
                    'lon': lon
                }
                print(f"🚗 Выезд: {dt}, одометр: {mileage:.2f} км")
            
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
    print("=" * 60)
    
    # Настройки подключения (ЗАПОЛНИТЕ СВОИ ДАННЫЕ)
    BASE_URL = "https://gps.mobiteam.com.ua"
    USERNAME = "ваш_логин"  # Ваш логин для входа на сайт
    PASSWORD = "ваш_пароль"  # Ваш пароль для входа на сайт
    
    print(f"\n🔐 Авторизация в системе...")
    print(f"   Сервер: {BASE_URL}")
    print(f"   Пользователь: {USERNAME}")
    
    # Инициализация и авторизация
    api = MobiteamAPI(BASE_URL, USERNAME, PASSWORD)
    
    if not api.login():
        print("\n❌ Не удалось авторизоваться")
        print("\nПроверьте:")
        print("1. Правильность логина и пароля")
        print("2. Доступность сервера")
        print("3. Наличие прав доступа к API")
        return
    
    try:
        # Получение списка объектов
        print("\n📋 Загрузка списка транспортных средств...")
        objects = api.get_objects_list()
        
        if not objects:
            print("⚠ Объекты не найдены")
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
        
        # Получение списка геозон
        print("\n📍 Загрузка списка геозон...")
        geozones = api.get_geozones()
        
        if not geozones:
            print("⚠ Геозоны не найдены")
            return
        
        print(f"✓ Найдено геозон: {len(geozones)}")
        print("\nДоступные геозоны:")
        for i, gz in enumerate(geozones, 1):
            gz_id = gz.get('id', '')
            gz_name = gz.get('name', 'Без названия')
            print(f"  {i}. ID: {gz_id} - {gz_name}")
        
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
        
    except KeyboardInterrupt:
        print("\n\n⚠ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()
