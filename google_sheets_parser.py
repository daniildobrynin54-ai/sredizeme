"""Парсер данных профилей из Google Sheets с вкладом из третьей страницы."""

import re
import requests
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT
from logger import get_logger

logger = get_logger("google_sheets")

# URL Google Sheets (публичный доступ)
# Страница с основными данными (Аркана, Звание, Последовательность)
SHEETS_URL_MAIN = "https://docs.google.com/spreadsheets/d/1sYvrBU9BPhcoxTnNJfx8TOutxwFrSiRm2mw_8s6rdZM/gviz/tq?tqx=out:csv&gid=1142214254"

# Страница с балансом (Остаток ОК)
SHEETS_URL_BALANCE = "https://docs.google.com/spreadsheets/d/1sYvrBU9BPhcoxTnNJfx8TOutxwFrSiRm2mw_8s6rdZM/gviz/tq?tqx=out:csv&gid=846561775"

# 🔧 НОВОЕ: Страница с вкладом (столбец Д - вклад)
SHEETS_URL_CONTRIBUTION = "https://docs.google.com/spreadsheets/d/1sYvrBU9BPhcoxTnNJfx8TOutxwFrSiRm2mw_8s6rdZM/gviz/tq?tqx=out:csv&gid=1749360341"


class GoogleSheetsParser:
    """Парсер профилей из Google Sheets с трёх страниц."""
    
    def __init__(self, proxy_manager=None, session=None):
        # 🔧 ИСПРАВЛЕНО: НЕ используем прокси для Google Sheets
        self.proxies = None
        # 🔧 НОВОЕ: Сохраняем session для парсинга nicknames
        self.session = session
        logger.info("Google Sheets parser работает БЕЗ прокси (прямое подключение)")
    
    def set_session(self, session) -> None:
        """🔧 НОВОЕ: Устанавливает session для парсинга nicknames."""
        self.session = session
        logger.info("Session установлена в Google Sheets parser")
    
    def fetch_sheet_data(self, url: str) -> Optional[str]:
        """Загружает CSV данные из Google Sheets."""
        try:
            logger.debug(f"Загрузка данных из Google Sheets...")
            
            # 🔧 БЕЗ ПРОКСИ
            response = requests.get(
                url,
                timeout=15
            )
            
            if response.status_code == 200:
                logger.debug("✅ Данные загружены успешно")
                return response.text
            else:
                logger.warning(f"Ошибка загрузки: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка загрузки Google Sheets: {e}")
            return None
    
    def _parse_csv_line(self, line: str) -> list:
        """Парсит строку CSV с учетом кавычек."""
        import csv
        import io
        
        reader = csv.reader(io.StringIO(line))
        return next(reader)
    
    def _clean_value(self, value: str) -> str:
        """Очищает значение от HYPERLINK и кавычек."""
        # Убираем HYPERLINK
        if 'HYPERLINK' in value:
            match = re.search(r';"([^"]+)"', value)
            if match:
                return match.group(1)
        
        # Убираем кавычки
        return value.strip('"')
    
    def _extract_user_id_from_hyperlink(self, cell: str) -> Optional[str]:
        """Извлекает user_id из HYPERLINK."""
        match = re.search(r'/users/(\d+)', cell)
        if match:
            return match.group(1)
        return None
    
    def _parse_nickname_from_mangabuff(self, user_id: str) -> Optional[str]:
        """
        🔧 НОВОЕ: Парсит реальный nickname с профиля MangaBuff.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Nickname или None
        """
        if not self.session:
            logger.warning("Session не установлена, невозможно парсить nickname")
            return None
        
        url = f"{BASE_URL}/users/{user_id}"
        
        try:
            logger.debug(f"Парсинг nickname для {user_id}...")
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Не удалось загрузить профиль {user_id}: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем никнейм
            selectors = [
                '.profile__name',
                '.profile-name',
                '[data-name]',
                'div.profile h1',
                'div.profile h2',
                '.user-name',
                '.username'
            ]
            
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    # Пробуем атрибут data-name
                    if element.has_attr('data-name'):
                        nickname = element.get('data-name', '').strip()
                        if nickname:
                            logger.debug(f"Найден nickname для {user_id}: {nickname}")
                            return nickname
                    
                    # Пробуем текст
                    nickname = element.get_text(strip=True)
                    if nickname:
                        logger.debug(f"Найден nickname для {user_id}: {nickname}")
                        return nickname
            
            logger.warning(f"Nickname не найден для {user_id}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка получения nickname для {user_id}: {e}")
            return None
    
    def parse_profile_main(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Парсит основные данные профиля из первой страницы.
        
        Args:
            user_id: ID пользователя MangaBuff
        
        Returns:
            Словарь с данными профиля или None
        """
        csv_data = self.fetch_sheet_data(SHEETS_URL_MAIN)
        
        if not csv_data:
            logger.warning("Не удалось загрузить основные данные из таблицы")
            return None
        
        logger.debug(f"Поиск профиля для user_id: {user_id}")
        
        # Парсим CSV
        lines = csv_data.strip().split('\n')
        
        if len(lines) < 2:
            logger.warning("Таблица пустая или некорректная")
            return None
        
        # Первая строка - заголовки
        headers_line = lines[0]
        headers = [h.strip('"') for h in headers_line.split(',')]
        
        logger.debug(f"Заголовки: {headers}")
        
        # Автоматический поиск столбца со ссылками
        link_column_index = None
        
        # Сначала пробуем найти по известным названиям
        possible_names = ['ссылка бафф', 'Ник', 'ник бафф', 'link', 'profile']
        for name in possible_names:
            try:
                link_column_index = headers.index(name)
                logger.info(f"Найден столбец '{name}' (индекс {link_column_index})")
                break
            except ValueError:
                continue
        
        # Если не нашли по названию - ищем автоматически по содержимому
        if link_column_index is None:
            logger.info("Столбец не найден по названию, ищем по содержимому...")
            if len(lines) > 1:
                first_data_line = lines[1]
                values = self._parse_csv_line(first_data_line)
                
                for i, value in enumerate(values):
                    if 'HYPERLINK' in value and '/users/' in value:
                        link_column_index = i
                        logger.info(f"✅ Найден столбец со ссылками автоматически (индекс {i})")
                        break
        
        if link_column_index is None:
            logger.error("❌ Столбец со ссылками на пользователей не найден в таблице")
            logger.error(f"Доступные заголовки: {headers}")
            return None
        
        # Ищем пользователя в строках
        for line in lines[1:]:
            values = self._parse_csv_line(line)
            
            if len(values) <= link_column_index:
                continue
            
            link_cell = values[link_column_index]
            
            # Извлекаем user_id из HYPERLINK
            found_user_id = self._extract_user_id_from_hyperlink(link_cell)
            
            if not found_user_id or found_user_id != user_id:
                continue
            
            logger.info(f"✅ Найден профиль для {user_id}")
            
            # 🔧 ИСПРАВЛЕНО: Парсим РЕАЛЬНЫЙ nickname с MangaBuff
            username = self._parse_nickname_from_mangabuff(user_id)
            
            # Если не удалось распарсить - используем из таблицы как fallback
            if not username:
                name_match = re.search(r';"([^"]+)"', link_cell)
                username = name_match.group(1) if name_match else f"User{user_id}"
                logger.warning(f"Используем nickname из таблицы: {username}")
            
            # Создаем словарь профиля
            profile = {
                'user_id': user_id,
                'username': username
            }
            
            # 🔧 НОВОЕ: Извлекаем инвентарь отдельно
            inventory_value = None
            
            # Добавляем остальные поля (кроме служебных)
            skip_fields = {
                'ссылка бафф',
                'Ник',
                'ник бафф',
                'ID',
                'id',
                'тг ник',
                'Telegram',
                'telegram_username',
                'Профиль',
                'профиль'
            }
            
            for i, header in enumerate(headers):
                # Пропускаем служебные поля
                if header in skip_fields:
                    continue
                
                # Пропускаем столбец со ссылками
                if i == link_column_index:
                    continue
                
                if i < len(values):
                    value = self._clean_value(values[i])
                    
                    # Пропускаем пустые значения и нули
                    if not value or value == '0':
                        continue
                    
                    # Пропускаем значения которые содержат User + ID
                    if value.startswith('User') and user_id in value:
                        continue
                    
                    # 🔧 НОВОЕ: Сохраняем инвентарь отдельно
                    if header.lower() in ['0', 'инвентарь', 'inventory']:
                        inventory_value = value
                        continue
                    
                    profile[header] = value
            
            # 🔧 НОВОЕ: Добавляем инвентарь в профиль
            if inventory_value:
                profile['Инвентарь'] = inventory_value
            
            logger.debug(f"Основной профиль: {profile}")
            return profile
        
        logger.warning(f"Профиль для {user_id} не найден в основной таблице")
        return None
    
    def parse_profile_balance(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Парсит данные баланса из второй страницы.
        
        Args:
            user_id: ID пользователя MangaBuff
        
        Returns:
            Словарь с данными баланса или None
        """
        csv_data = self.fetch_sheet_data(SHEETS_URL_BALANCE)
        
        if not csv_data:
            logger.warning("Не удалось загрузить данные баланса из таблицы")
            return None
        
        logger.debug(f"Поиск баланса для user_id: {user_id}")
        
        lines = csv_data.strip().split('\n')
        
        if len(lines) < 2:
            logger.warning("Таблица баланса пустая")
            return None
        
        headers_line = lines[0]
        headers = [h.strip('"') for h in headers_line.split(',')]
        
        logger.debug(f"Заголовки баланса: {headers}")
        
        # На странице баланса ссылки в столбце B (индекс 1)
        link_column_index = 1
        logger.info(f"Используем столбец B (индекс 1) для ссылок на странице баланса")
        
        # Ищем пользователя
        for line in lines[1:]:
            values = self._parse_csv_line(line)
            
            if len(values) <= link_column_index:
                continue
            
            link_cell = values[link_column_index]
            found_user_id = self._extract_user_id_from_hyperlink(link_cell)
            
            if not found_user_id or found_user_id != user_id:
                continue
            
            logger.info(f"✅ Найден баланс для {user_id}")
            
            # Извлекаем нужные поля
            balance_data = {}
            
            # Ищем столбцы по названиям (с разными вариантами написания)
            balance_fields = {
                'остаток ок': 'Баланс',
                'остаток': 'Баланс',
                'баланс': 'Баланс'
            }
            
            for i, header in enumerate(headers):
                # Пропускаем столбец со ссылками
                if i == link_column_index:
                    continue
                
                header_lower = header.lower().strip()
                header_lower = header_lower.replace('.', '').replace(':', '').strip()
                
                # Ищем совпадение с нужными полями
                for field_key, field_name in balance_fields.items():
                    if field_key in header_lower:
                        if i < len(values):
                            value = self._clean_value(values[i])
                            if value and value != '0':
                                # Если поле еще не добавлено
                                if field_name not in balance_data:
                                    # 🔧 ИСПРАВЛЕНО: Добавляем "ОК" к балансу
                                    if field_name == 'Баланс':
                                        balance_data[field_name] = f"{value} ОК"
                                    else:
                                        balance_data[field_name] = value
                                    logger.debug(f"Найдено поле '{field_name}' в столбце '{header}': {value}")
                                break
            
            logger.debug(f"Данные баланса: {balance_data}")
            return balance_data
        
        logger.warning(f"Баланс для {user_id} не найден")
        return None
    
    def parse_profile_contribution(self, user_id: str) -> Optional[Dict[str, Any]]:
    
        csv_data = self.fetch_sheet_data(SHEETS_URL_CONTRIBUTION)
    
        if not csv_data:
            logger.warning("Не удалось загрузить данные вклада из таблицы")
            return None
    
        logger.debug(f"Поиск вклада для user_id: {user_id}")
    
        lines = csv_data.strip().split('\n')
    
        if len(lines) < 2:
            logger.warning("Таблица вклада пустая")
            return None
    
        headers_line = lines[0]
        headers = [h.strip('"') for h in headers_line.split(',')]
    
        logger.debug(f"Заголовки вклада: {headers}")
    
        # Ссылки в столбце F (индекс 5)
        link_column_index = 5
        logger.info(f"Используем столбец F (индекс 5) для ссылок на странице вклада")
    
        # Вклад в столбце D (индекс 3)
        contribution_column_index = 3
        # 🔧 НОВОЕ: Начало в столбце X (нужно найти)
        start_column_index = None
        # 🔧 НОВОЕ: Конец в столбце I (индекс 8)
        end_column_index = 8
    
        # Ищем столбец "Начало" или "X"
        for i, header in enumerate(headers):
            header_lower = header.lower().strip()
            if header_lower in ['начало', 'start', 'x']:
                start_column_index = i
                logger.info(f"Найден столбец 'Начало': индекс {i}")
                break
    
        # Ищем пользователя
        for line in lines[1:]:
            values = self._parse_csv_line(line)
        
            if len(values) <= link_column_index:
                continue
        
            link_cell = values[link_column_index]
            found_user_id = self._extract_user_id_from_hyperlink(link_cell)
        
            if not found_user_id or found_user_id != user_id:
                continue
        
            logger.info(f"✅ Найден вклад для {user_id}")
        
            contribution_data = {}
        
            # Извлекаем вклад из столбца D
            if contribution_column_index < len(values):
                contribution_value = self._clean_value(values[contribution_column_index])
            
                if contribution_value and contribution_value != '0':
                    contribution_data['Вклад'] = contribution_value
                    logger.debug(f"Найден вклад: {contribution_value}")
        
            # 🔧 НОВОЕ: Извлекаем начало
            if start_column_index is not None and start_column_index < len(values):
                start_value = self._clean_value(values[start_column_index])
                if start_value and start_value != '0':
                    contribution_data['Начало'] = start_value
                    logger.debug(f"Найдено начало: {start_value}")
        
            # 🔧 НОВОЕ: Извлекаем конец из столбца I
            if end_column_index < len(values):
                end_value = self._clean_value(values[end_column_index])
                if end_value and end_value != '0':
                    contribution_data['Конец'] = end_value
                    logger.debug(f"Найден конец: {end_value}")
        
            return contribution_data
    
        logger.warning(f"Вклад для {user_id} не найден")
        return None
    
    def parse_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        🔧 ОБНОВЛЕНО: Парсит полный профиль пользователя из ТРЁХ таблиц.
        
        Args:
            user_id: ID пользователя MangaBuff
        
        Returns:
            Объединенный словарь с данными профиля или None
        """
        # Получаем основные данные
        main_data = self.parse_profile_main(user_id)
        
        if not main_data:
            logger.warning(f"Основные данные не найдены для {user_id}")
            return None
        
        # Получаем данные баланса
        balance_data = self.parse_profile_balance(user_id)
        
        if balance_data:
            main_data.update(balance_data)
            logger.info(f"✅ Добавлен баланс для {user_id}")
        else:
            logger.warning(f"Данные баланса не найдены для {user_id}")
        
        # 🔧 НОВОЕ: Получаем данные вклада
        contribution_data = self.parse_profile_contribution(user_id)
        
        if contribution_data:
            main_data.update(contribution_data)
            logger.info(f"✅ Добавлен вклад для {user_id}")
        else:
            logger.warning(f"Данные вклада не найдены для {user_id}")
        
        return main_data
    
    def format_profile_message(self, profile: Dict[str, Any]) -> str:
        """
        🔧 ОБНОВЛЕНО: Форматирует профиль с прогресс-баром вклада.
    
        Args:
            profile: Словарь с данными профиля
    
        Returns:
            HTML-форматированное сообщение
        """
        username = profile.get('username', 'Неизвестно')
        user_id = profile.get('user_id', '?')
    
        # 🔧 ИСПРАВЛЕНО: Инвентарь теперь отдельная строка
        inventory_value = profile.get('Инвентарь')
    
        # 🔧 ИСПРАВЛЕНО: Заголовок БЕЗ инвентаря
        lines = [
            f"<b>👤 Профиль: {username}</b>\n"
        ]
    
        # Поля которые нужно пропустить
        skip_fields = {
            'user_id',
            'username',
            'Ник',
            'ссылка бафф',
            'ник бафф',
            'ID',
            'id',
            'тг ник',
            'Telegram',
            'telegram_username',
            'Профиль',
            'профиль',
            'Инвентарь',
            '0',
            'инвентарь',
            'inventory',
            'Начало',  # 🔧 НОВОЕ: Пропускаем служебные поля прогресс-бара
            'начало',
            'Конец',
            'конец'
        }
        
        # Порядок отображения полей
        field_order = [
            'Аркана',
            'аркана',
            'Звание',
            'звание',
            'Последовательность',
            'последовательность',
            'посл.',
            'Баланс',
            'баланс',
            'Вклад',  # 🔧 НОВОЕ: Вклад обрабатывается отдельно с прогресс-баром
            'вклад'
        ]
        
        # Сначала выводим поля в нужном порядке
        added_fields = set()
        contribution_value = None
        contribution_start = None
        contribution_end = None
        
        for field_name in field_order:
            # Проверяем и обычное имя и lowercase
            for key in profile.keys():
                if key.lower() == field_name.lower() and key not in skip_fields:
                    if key not in added_fields:
                        value = str(profile[key]).strip()
                        if value and value != '0':
                            # Используем красивое имя из field_order
                            display_name = field_name
                            # Если это короткое название - используем полное
                            if field_name == 'посл.':
                                display_name = 'Последовательность'
                            elif field_name in ['аркана', 'звание', 'последовательность', 'баланс', 'вклад']:
                                display_name = field_name.capitalize()
                            
                            # 🔧 ИСПРАВЛЕНО: Убираем ": ?" из значений
                            value = value.replace(': ?', '').strip()
                            
                            # 🔧 НОВОЕ: Для вклада сохраняем значение для прогресс-бара
                            if field_name.lower() == 'вклад':
                                try:
                                    contribution_value = int(value)
                                except ValueError:
                                    contribution_value = None
                            else:
                                lines.append(f"<b>{display_name}:</b> {value}")
                            
                            added_fields.add(key)
        
        # 🔧 НОВОЕ: Получаем значения начала и конца для прогресс-бара
        for key, value in profile.items():
            key_lower = key.lower().strip()
            if key_lower in ['начало', 'start', 'x']:
                try:
                    contribution_start = int(str(value).strip())
                except (ValueError, AttributeError):
                    pass
            elif key_lower in ['конец', 'end', 'i']:
                try:
                    contribution_end = int(str(value).strip())
                except (ValueError, AttributeError):
                    pass
        
        # 🔧 НОВОЕ: Добавляем вклад с прогресс-баром
        if contribution_value is not None:
            contribution_line = f"<b>Вклад:</b> {contribution_value}"
            
            # Если есть данные для прогресс-бара
            if contribution_start is not None and contribution_end is not None:
                # Вычисляем процент и оставшееся
                total = contribution_end - contribution_start
                current_progress = contribution_value - contribution_start
                remaining = contribution_end - contribution_value
                
                if total > 0:
                    percentage = min(100, max(0, (current_progress / total) * 100))
                    
                    # Создаем прогресс-бар (15 блоков)
                    filled_blocks = int((percentage / 100) * 15)
                    empty_blocks = 15 - filled_blocks
                    
                    # Используем Unicode блоки для прогресс-бара
                    progress_bar = '█' * filled_blocks + '░' * empty_blocks
                    
                    contribution_line += f" (Осталось: {remaining})\n"
                    contribution_line += f"<code>[{progress_bar}] {percentage:.1f}%</code>"
                else:
                    contribution_line += f" (Осталось: {remaining})"
            
            lines.append(contribution_line)
        
        # 🔧 НОВОЕ: Добавляем инвентарь ОТДЕЛЬНОЙ строкой
        if inventory_value:
            lines.append(f"<b>Инвентарь:</b> {inventory_value}")
        
        # Затем выводим остальные поля
        for key, value in profile.items():
            if key in skip_fields or key in added_fields:
                continue
            
            # Пропускаем поля которые содержат только служебную информацию
            key_lower = key.lower()
            if key_lower.startswith('id ') or key_lower == 'id':
                continue
            
            # Пропускаем ссылки
            if key_lower in ['ссылка', 'link', 'url']:
                continue
            
            # Форматируем значение
            field_value = str(value).strip()
            
            # Пропускаем пустые значения и нули
            if not field_value or field_value == '0':
                continue
            
            # Пропускаем поля с User309607 и подобными
            if field_value.startswith('User') and user_id in field_value:
                logger.debug(f"Пропускаем поле '{key}' со значением '{field_value}'")
                continue
            
            # 🔧 ИСПРАВЛЕНО: Убираем ": ?" из значений
            field_value = field_value.replace(': ?', '').strip()
            
            # Форматируем название поля
            field_name = key.strip()
            
            lines.append(f"<b>{field_name}:</b> {field_value}")
        
        # Добавляем ссылку на профиль внизу
        lines.append(f"\n🔗 <a href='https://mangabuff.ru/users/{user_id}'>Перейти в профиль</a>")
        
        return "\n".join(lines)


# Глобальный экземпляр парсера
_sheets_parser: Optional[GoogleSheetsParser] = None


def get_sheets_parser(proxy_manager=None, session=None) -> GoogleSheetsParser:
    """Возвращает глобальный экземпляр парсера."""
    global _sheets_parser
    
    if _sheets_parser is None:
        # 🔧 НЕ передаем proxy_manager, но передаем session
        _sheets_parser = GoogleSheetsParser(None, session)
    elif session and not _sheets_parser.session:
        # Если парсер уже создан, но session не была установлена
        _sheets_parser.set_session(session)
    
    return _sheets_parser