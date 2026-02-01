"""База данных пользователей Telegram v3 с автообновлением никнеймов."""

import json
import os
import re
import requests
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT
from logger import get_logger

logger = get_logger("telegram_users_db")

USERS_DB_FILE = "telegram_users.json"
NICKNAME_UPDATE_INTERVAL = 12  # часов


class TelegramUsersDB:
    """Управление базой данных пользователей Telegram с автообновлением."""
    
    def __init__(self, db_file: str = USERS_DB_FILE, session=None):
        self.db_file = db_file
        self.session = session  # 🔧 НОВОЕ: Для парсинга никнеймов
        self.users = self._load_db()
    
    def set_session(self, session) -> None:
        """🔧 НОВОЕ: Устанавливает сессию для парсинга."""
        self.session = session
        logger.info("Session установлена для парсинга никнеймов")
    
    def _load_db(self) -> Dict[str, Dict]:
        """
        Загружает базу данных из файла.
        
        Структура:
        {
          "telegram_id": {
            "telegram_username": "username",
            "last_username_update": "2025-01-19T12:00:00",
            "mangabuff_accounts": [
              {
                "user_id": "123456",
                "username": "RealNickname",
                "last_nickname_update": "2025-01-19T12:00:00",
                "notification_type": "dm"
              }
            ]
          }
        }
        """
        if not os.path.exists(self.db_file):
            logger.info("База данных не найдена, создаем новую")
            return {}
        
        try:
            with open(self.db_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Миграция старого формата
                migrated = self._migrate_to_v3(data)
                if migrated:
                    logger.info("Выполнена миграция базы данных v2 → v3")
                    self._save_db_direct(migrated)
                    return migrated
                
                logger.info(f"Загружено {len(data)} пользователей")
                return data
                
        except Exception as e:
            logger.error(f"Ошибка загрузки базы данных: {e}")
            return {}
    
    def _migrate_to_v3(self, old_data: Dict) -> Optional[Dict]:
        """🔧 НОВОЕ: Миграция v2 → v3 (добавляет метки времени)."""
        if not old_data:
            return None
        
        # Проверяем нужна ли миграция
        first_key = next(iter(old_data))
        first_user = old_data.get(first_key, {})
        
        # Если уже v3 - пропускаем
        if 'last_username_update' in first_user:
            return None
        
        logger.info("Миграция v2 → v3: добавление меток времени...")
        
        now = datetime.now().isoformat()
        
        for telegram_id, user_data in old_data.items():
            # Добавляем метку для telegram username
            if 'last_username_update' not in user_data:
                user_data['last_username_update'] = now
            
            # Добавляем метки для каждого аккаунта
            for account in user_data.get('mangabuff_accounts', []):
                if 'last_nickname_update' not in account:
                    account['last_nickname_update'] = now
        
        logger.info("Миграция v3 завершена")
        return old_data
    
    def _save_db_direct(self, data: Dict) -> bool:
        """Прямое сохранение данных."""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            return False
    
    def _save_db(self) -> bool:
        """Сохраняет базу данных."""
        return self._save_db_direct(self.users)
    
    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Извлекает user_id из URL."""
        if url.startswith('@'):
            return None
        
        match = re.search(r'/users/(\d+)', url)
        if match:
            return match.group(1)
        
        if url.strip().isdigit():
            return url.strip()
        
        return None
    
    def parse_mangabuff_nickname(self, user_id: str) -> Optional[str]:
        """
        🔧 НОВОЕ: Парсит nickname с профиля MangaBuff.
        
        Использует ту же функцию что и в boost.py
        """
        if not self.session:
            logger.warning("Session не установлена, невозможно парсить nickname")
            return None
        
        url = f"{BASE_URL}/users/{user_id}"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка загрузки профиля {user_id}: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Те же селекторы что в boost.py
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
                    if element.has_attr('data-name'):
                        nickname = element.get('data-name', '').strip()
                        if nickname:
                            logger.debug(f"Найден nickname для {user_id}: {nickname}")
                            return nickname
                    
                    nickname = element.get_text(strip=True)
                    if nickname:
                        logger.debug(f"Найден nickname для {user_id}: {nickname}")
                        return nickname
            
            logger.warning(f"Nickname не найден для {user_id}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга nickname для {user_id}: {e}")
            return None
    
    def should_update_nickname(self, last_update: Optional[str]) -> bool:
        """🔧 НОВОЕ: Проверяет нужно ли обновить nickname."""
        if not last_update:
            return True
        
        try:
            last_time = datetime.fromisoformat(last_update)
            elapsed = datetime.now() - last_time
            
            # Обновляем если прошло больше NICKNAME_UPDATE_INTERVAL часов
            return elapsed > timedelta(hours=NICKNAME_UPDATE_INTERVAL)
        except:
            return True
    
    def update_nickname_if_needed(
        self,
        telegram_id_str: str,
        user_id: str
    ) -> Optional[str]:
        """
        🔧 НОВОЕ: Обновляет nickname если прошло 12+ часов.
        
        Returns:
            Обновленный nickname или None
        """
        if telegram_id_str not in self.users:
            return None
        
        accounts = self.users[telegram_id_str]['mangabuff_accounts']
        
        for account in accounts:
            if account['user_id'] == user_id:
                last_update = account.get('last_nickname_update')
                
                if not self.should_update_nickname(last_update):
                    logger.debug(f"Nickname для {user_id} актуален")
                    return account['username']
                
                logger.info(f"🔄 Обновление nickname для {user_id}...")
                
                new_nickname = self.parse_mangabuff_nickname(user_id)
                
                if new_nickname:
                    old_nickname = account['username']
                    account['username'] = new_nickname
                    account['last_nickname_update'] = datetime.now().isoformat()
                    self._save_db()
                    
                    logger.info(f"✅ Nickname обновлен: {old_nickname} → {new_nickname}")
                    return new_nickname
                else:
                    logger.warning(f"Не удалось обновить nickname для {user_id}")
                    return account['username']
        
        return None
    
    def update_telegram_username(
        self,
        telegram_id: int,
        telegram_username: Optional[str]
    ) -> None:
        """
        🔧 НОВОЕ: Обновляет Telegram username при каждом взаимодействии.
        """
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str not in self.users:
            return
        
        old_username = self.users[telegram_id_str].get('telegram_username')
        
        # Обновляем только если изменился
        if old_username != telegram_username:
            self.users[telegram_id_str]['telegram_username'] = telegram_username
            self.users[telegram_id_str]['last_username_update'] = datetime.now().isoformat()
            self._save_db()
            
            logger.info(f"🔄 Telegram username обновлен: {old_username} → {telegram_username}")
    
    def register_account(
        self,
        telegram_id: int,
        telegram_username: Optional[str],
        mangabuff_url: str,
        mangabuff_username: Optional[str] = None,
        notification_type: str = 'dm'
    ) -> Tuple[bool, str]:
        """🔧 ОБНОВЛЕНО: Регистрация с автопарсингом nickname."""
        user_id = self.extract_id_from_url(mangabuff_url)
        
        if not user_id:
            return False, "❌ Не удалось извлечь ID из ссылки"
        
        telegram_id_str = str(telegram_id)
        now = datetime.now().isoformat()
        
        # 🔧 НОВОЕ: Парсим nickname если не указан
        if not mangabuff_username:
            logger.info(f"🔍 Парсинг nickname для {user_id}...")
            mangabuff_username = self.parse_mangabuff_nickname(user_id)
            
            if not mangabuff_username:
                logger.warning(f"Не удалось распарсить nickname, используем User{user_id}")
                mangabuff_username = f'User{user_id}'
        
        # Создаем запись если нет
        if telegram_id_str not in self.users:
            self.users[telegram_id_str] = {
                'telegram_username': telegram_username,
                'last_username_update': now,
                'mangabuff_accounts': []
            }
        else:
            # 🔧 НОВОЕ: Обновляем telegram username
            self.update_telegram_username(telegram_id, telegram_username)
        
        # Проверяем не добавлен ли уже этот аккаунт
        accounts = self.users[telegram_id_str]['mangabuff_accounts']
        for acc in accounts:
            if acc['user_id'] == user_id:
                # Обновляем существующий
                acc['username'] = mangabuff_username
                acc['last_nickname_update'] = now
                acc['notification_type'] = notification_type
                
                if self._save_db():
                    logger.info(f"Обновлен аккаунт: TG {telegram_id} → MB {user_id}")
                    return True, (
                        f"✅ Аккаунт обновлен!\n"
                        f"MangaBuff: {acc['username']} (ID: {user_id})\n"
                        f"Уведомления: {'Личные сообщения' if notification_type == 'dm' else 'Тег во вкладе'}"
                    )
                return False, "❌ Ошибка сохранения"
        
        # Добавляем новый аккаунт
        new_account = {
            'user_id': user_id,
            'username': mangabuff_username,
            'last_nickname_update': now,
            'notification_type': notification_type
        }
        
        accounts.append(new_account)
        
        if self._save_db():
            logger.info(f"Добавлен аккаунт: TG {telegram_id} → MB {user_id} ({mangabuff_username})")
            count = len(accounts)
            return True, (
                f"✅ Аккаунт добавлен!\n"
                f"MangaBuff: {new_account['username']} (ID: {user_id})\n"
                f"Уведомления: {'Личные сообщения' if notification_type == 'dm' else 'Тег во вкладе'}\n"
                f"\nВсего привязано аккаунтов: {count}"
            )
        
        return False, "❌ Ошибка сохранения"
    
    def unregister_account(
        self,
        telegram_id: int,
        mangabuff_user_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Удаляет привязку аккаунта."""
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str not in self.users:
            return False, "❌ У вас нет привязанных аккаунтов"
        
        accounts = self.users[telegram_id_str]['mangabuff_accounts']
        
        # Удалить конкретный аккаунт
        if mangabuff_user_id:
            for acc in accounts:
                if acc['user_id'] == mangabuff_user_id:
                    accounts.remove(acc)
                    
                    if not accounts:
                        del self.users[telegram_id_str]
                    
                    if self._save_db():
                        return True, f"✅ Аккаунт {acc['username']} удален"
                    return False, "❌ Ошибка сохранения"
            
            return False, f"❌ Аккаунт с ID {mangabuff_user_id} не найден"
        
        # Удалить все аккаунты
        del self.users[telegram_id_str]
        
        if self._save_db():
            return True, f"✅ Все привязки удалены ({len(accounts)} аккаунтов)"
        
        return False, "❌ Ошибка сохранения"
    
    def get_user_accounts(self, telegram_id: int) -> List[Dict]:
        """🔧 ОБНОВЛЕНО: Возвращает список с обновленными nicknames."""
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str not in self.users:
            return []
        
        accounts = self.users[telegram_id_str]['mangabuff_accounts']
        
        # 🔧 НОВОЕ: Проверяем и обновляем nicknames если нужно
        for account in accounts:
            user_id = account['user_id']
            self.update_nickname_if_needed(telegram_id_str, user_id)
        
        return accounts
    
    def get_notification_settings(
        self,
        mangabuff_user_ids: List[str]
    ) -> Dict[str, Dict]:
        """
        🔧 ОБНОВЛЕНО: Получает настройки с обновлением nicknames.
        
        Returns:
            {
              user_id: {
                telegram_id: int,
                username: str,
                notification_type: str
              }
            }
        """
        settings = {}
        
        for telegram_id_str, user_data in self.users.items():
            for account in user_data['mangabuff_accounts']:
                user_id = account['user_id']
                
                if user_id in mangabuff_user_ids:
                    # 🔧 НОВОЕ: Обновляем nickname если нужно
                    updated_nickname = self.update_nickname_if_needed(telegram_id_str, user_id)
                    
                    settings[user_id] = {
                        'telegram_id': int(telegram_id_str),
                        'username': updated_nickname or account['username'],
                        'notification_type': account['notification_type']
                    }
        
        return settings
    
    def get_user_info(self, telegram_id: int) -> Optional[str]:
        """Возвращает информацию о привязанных аккаунтах."""
        accounts = self.get_user_accounts(telegram_id)
        
        if not accounts:
            return None
        
        lines = ["📝 <b>Ваши аккаунты MangaBuff:</b>\n"]
        
        for i, acc in enumerate(accounts, 1):
            notif_type = "📬 ЛС" if acc['notification_type'] == 'dm' else "🏷 Тег"
            lines.append(
                f"{i}. <b>{acc['username']}</b>\n"
                f"   ID: <code>{acc['user_id']}</code>\n"
                f"   {notif_type}"
            )
        
        return "\n".join(lines)
    
    def get_all_users_count(self) -> int:
        """Количество Telegram пользователей."""
        return len(self.users)
    
    def get_all_accounts_count(self) -> int:
        """Общее количество привязанных MangaBuff аккаунтов."""
        total = 0
        for user_data in self.users.values():
            total += len(user_data['mangabuff_accounts'])
        return total
    
    def set_notification_type(
        self,
        telegram_id: int,
        mangabuff_user_id: str,
        notification_type: str
    ) -> Tuple[bool, str]:
        """Изменяет тип уведомлений."""
        if notification_type not in ['dm', 'tag']:
            logger.warning(f"Неверный тип: {notification_type}")
            return False, "❌ Неверный тип уведомлений (dm/tag)"
        
        telegram_id_str = str(telegram_id)
        
        logger.debug(f"🔍 Поиск аккаунта: TG {telegram_id_str} -> MB {mangabuff_user_id}")
        
        if telegram_id_str not in self.users:
            logger.warning(f"Telegram ID {telegram_id_str} не найден в базе")
            return False, "❌ У вас нет привязанных аккаунтов"
        
        accounts = self.users[telegram_id_str]['mangabuff_accounts']
        
        logger.debug(f"Найдено аккаунтов: {len(accounts)}")
        
        for acc in accounts:
            logger.debug(f"Проверка аккаунта: {acc['user_id']}")
            
            if acc['user_id'] == mangabuff_user_id:
                logger.info(f"✅ Аккаунт найден! Изменяем {acc['notification_type']} -> {notification_type}")
                
                acc['notification_type'] = notification_type
                
                if self._save_db():
                    notif_text = "личные сообщения" if notification_type == 'dm' else "тег во вкладе"
                    logger.info(f"✅ База данных сохранена")
                    return True, f"✅ Для {acc['username']}: {notif_text}"
                else:
                    logger.error(f"❌ Ошибка сохранения базы данных")
                    return False, "❌ Ошибка сохранения"
        
        logger.warning(f"Аккаунт {mangabuff_user_id} не найден среди {len(accounts)} аккаунтов")
        return False, f"❌ Аккаунт с ID {mangabuff_user_id} не найден"


# Глобальный экземпляр
_db_instance: Optional[TelegramUsersDB] = None


def get_users_db() -> TelegramUsersDB:
    """Возвращает глобальный экземпляр БД."""
    global _db_instance
    if _db_instance is None:
        _db_instance = TelegramUsersDB()
    return _db_instance
