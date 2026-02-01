"""Объединенный обработчик Telegram бота v2 - ИСПРАВЛЕНО."""

import threading
import time
import json
import requests
from typing import Optional, Callable
from telegram_users_db import get_users_db
from telegram_club_validator import create_club_validator
from google_sheets_parser import get_sheets_parser
from logger import get_logger

logger = get_logger("telegram_unified")


class TelegramUnifiedHandler:
    """Единый обработчик для команд и мониторинга ответов."""
    
    TRIGGER_KEYWORDS = [
        "смена карты",
        "смена",
        "заменить",
        "замени",
        "change card",
        "replace"
    ]
    
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        thread_id: Optional[int],
        on_replace_triggered: Optional[Callable] = None,
        proxy_manager=None,
        boost_url: Optional[str] = None,
        session=None
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.on_replace_triggered = on_replace_triggered
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.last_update_id = 0
        self.running = False
        self.thread = None
        self.users_db = get_users_db()
        self.bot_message_ids = set()
        
        self.sheets_parser = get_sheets_parser(None)
        self.user_states = {}
        
        # Валидатор клуба
        self.validator = None
        if boost_url and session:
            self.validator = create_club_validator(
                session=session,
                bot_token=bot_token,
                boost_url=boost_url,
                telegram_chat_id=chat_id,
                proxy_manager=proxy_manager
            )
            if self.validator:
                logger.info("✅ Валидатор клуба инициализирован")
        
        self.proxies = None
        logger.info("Telegram unified handler работает БЕЗ прокси")
        
        self._test_connection()
    
    def _test_connection(self) -> bool:
        """Тестирует подключение."""
        try:
            url = f"{self.api_url}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data.get('result', {})
                    bot_username = bot_info.get('username', 'Unknown')
                    logger.info(f"✅ Telegram бот подключен: @{bot_username}")
                    return True
            
            logger.error(f"❌ Ошибка подключения: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
            return False
    
    def register_bot_message(self, message_id: int) -> None:
        """Регистрирует ID сообщения бота."""
        self.bot_message_ids.add(message_id)
        logger.debug(f"Зарегистрировано сообщение бота: {message_id}")
    
    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[dict] = None
    ) -> bool:
        """Отправляет сообщение."""
        try:
            url = f"{self.api_url}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                logger.debug(f"Сообщение отправлено: {chat_id}")
                return True
            else:
                logger.warning(f"Ошибка отправки: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            return False
    
    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str = "",
        show_alert: bool = False
    ) -> bool:
        """Отвечает на callback query."""
        try:
            url = f"{self.api_url}/answerCallbackQuery"
            data = {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert
            }
            
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка ответа на callback: {e}")
            return False
    
    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[dict] = None
    ) -> bool:
        """Редактирует существующее сообщение."""
        try:
            url = f"{self.api_url}/editMessageText"
            data = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка редактирования сообщения: {e}")
            return False
    
    def _is_trigger_message(self, text: str) -> bool:
        """Проверяет триггерные слова."""
        if not text:
            return False
        
        text_lower = text.lower().strip()
        return any(keyword in text_lower for keyword in self.TRIGGER_KEYWORDS)
    
    def show_notifications_list(self, chat_id: int) -> None:
        """Показывает список уведомлений."""
        accounts = self.users_db.get_user_accounts(chat_id)
        
        if not accounts:
            self.send_message(
                chat_id,
                "❌ <b>У вас нет привязанных аккаунтов</b>\n\n"
                "Используйте /add для добавления аккаунта.\n\n"
                "<i>Например:</i>\n"
                "<code>/add https://mangabuff.ru/users/826513</code>"
            )
            return
        
        keyboard = {
            "inline_keyboard": []
        }
        
        for acc in accounts:
            username = acc['username']
            user_id = acc['user_id']
            notif_type = acc['notification_type']
            
            emoji = "📬" if notif_type == 'dm' else "🏷"
            
            keyboard["inline_keyboard"].append([{
                "text": f"{emoji} {username}",
                "callback_data": f"notif:{user_id}"
            }])
        
        text = "<b>⚙️ Настройки уведомлений:</b>\n\n"
        text += "Нажмите на аккаунт для выбора способа уведомлений:"
        
        self.send_message(chat_id, text, reply_markup=keyboard)
        logger.info(f"Показан список из {len(accounts)} аккаунтов для {chat_id}")
    
    def show_profile_list(self, chat_id: int) -> None:
        """Показывает список аккаунтов для просмотра профиля."""
        accounts = self.users_db.get_user_accounts(chat_id)
        
        if not accounts:
            self.send_message(
                chat_id,
                "❌ <b>У вас нет привязанных аккаунтов</b>\n\n"
                "Используйте /add для добавления аккаунта."
            )
            return
        
        keyboard = {
            "inline_keyboard": []
        }
        
        for acc in accounts:
            username = acc['username']
            user_id = acc['user_id']
            
            keyboard["inline_keyboard"].append([{
                "text": f"👤 {username}",
                "callback_data": f"profile:{user_id}"
            }])
        
        text = "<b>📋 Профиль какого своего аккаунта вы хотите посмотреть:</b>"
        
        self.send_message(chat_id, text, reply_markup=keyboard)
        logger.info(f"Показан список профилей для {chat_id}")
    
    def show_profile(self, chat_id: int, callback_query_id: str, user_id: str) -> None:
        """🔧 ИСПРАВЛЕНО: Показывает профиль из Google Sheets."""
        logger.info(f"📊 Загрузка профиля {user_id} для {chat_id}")
        
        # Загружаем профиль из таблицы
        profile = self.sheets_parser.parse_profile(user_id)
        
        if not profile:
            self.answer_callback_query(
                callback_query_id,
                "❌ Профиль не найден в таблице",
                show_alert=True
            )
            return
        
        # Форматируем сообщение
        message = self.sheets_parser.format_profile_message(profile)
        
        self.answer_callback_query(callback_query_id)
        self.send_message(chat_id, message)
        logger.info(f"✅ Профиль {user_id} отправлен")
    
    def show_notification_settings(
        self,
        chat_id: int,
        message_id: int,
        user_id: str
    ) -> None:
        """Показывает настройки уведомлений."""
        accounts = self.users_db.get_user_accounts(chat_id)
        
        account = None
        for acc in accounts:
            if acc['user_id'] == user_id:
                account = acc
                break
        
        if not account:
            return
        
        username = account['username']
        current_type = account['notification_type']
        
        current_text = "📬 Личные сообщения" if current_type == 'dm' else "🏷 Тег во вкладе"
        
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "📬 ЛС" + (" ✅" if current_type == 'dm' else ""),
                        "callback_data": f"set_notif:{user_id}:dm"
                    },
                    {
                        "text": "🏷 Тег" + (" ✅" if current_type == 'tag' else ""),
                        "callback_data": f"set_notif:{user_id}:tag"
                    }
                ],
                [
                    {
                        "text": "◀️ Назад к списку",
                        "callback_data": "back_to_notif"
                    }
                ]
            ]
        }
        
        text = (
            f"<b>⚙️ Настройки для {username}</b>\n\n"
            f"<b>Текущий способ:</b> {current_text}\n\n"
            f"Выберите способ уведомлений:"
        )
        
        self.edit_message(chat_id, message_id, text, reply_markup=keyboard)
        logger.info(f"Показаны настройки для {username} ({user_id})")
    
    def set_notification_type_via_button(
        self,
        chat_id: int,
        message_id: int,
        callback_query_id: str,
        user_id: str,
        notification_type: str
    ) -> None:
        """Устанавливает тип уведомлений через кнопку."""
        logger.info(f"🔧 Изменение типа: TG {chat_id} -> MB {user_id} -> {notification_type}")
        
        success, message = self.users_db.set_notification_type(
            chat_id,
            user_id,
            notification_type
        )
        
        if success:
            notif_text = "личные сообщения" if notification_type == 'dm' else "Тег во вкладе"
            self.answer_callback_query(
                callback_query_id,
                f"✅ Установлено: {notif_text}",
                show_alert=False
            )
            
            self.show_notification_settings(chat_id, message_id, user_id)
            
            logger.info(f"✅ Тип изменен: {user_id} -> {notification_type}")
        else:
            self.answer_callback_query(
                callback_query_id,
                f"❌ Ошибка: {message}",
                show_alert=True
            )
            logger.error(f"❌ Не удалось изменить тип: {message}")
    
    def ask_link_action(self, chat_id: int, url: str) -> None:
        """Спрашивает что делать с ссылкой."""
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "➕ Привязать аккаунт",
                        "callback_data": f"link_add:{url}"
                    }
                ],
                [
                    {
                        "text": "👁️ Посмотреть профиль",
                        "callback_data": f"link_view:{url}"
                    }
                ]
            ]
        }
        
        text = (
            "<b>🔗 Что вы хотите сделать?</b>\n\n"
            f"Ссылка: <code>{url}</code>"
        )
        
        self.send_message(chat_id, text, reply_markup=keyboard)
        logger.info(f"Запрос действия для ссылки: {url}")
    
    def process_link_add(
        self,
        chat_id: int,
        telegram_username: Optional[str],
        callback_query_id: str,
        url: str
    ) -> None:
        """Обрабатывает привязку через кнопку."""
        self.answer_callback_query(callback_query_id)
        
        # Валидация
        if self.validator:
            user_id = self.users_db.extract_id_from_url(url)
            
            if not user_id:
                self.send_message(
                    chat_id,
                    "❌ Неверный формат ссылки"
                )
                return
            
            logger.info(f"🔐 Проверка условий регистрации для {user_id}...")
            
            validation_ok, validation_message = self.validator.validate_user_registration(
                telegram_id=chat_id,
                mangabuff_user_id=user_id
            )
            
            if not validation_ok:
                logger.warning(f"❌ Валидация не пройдена")
                self.send_message(chat_id, validation_message)
                return
            
            logger.info(f"✅ Валидация пройдена для {user_id}")
        
        # Регистрация
        success, message = self.users_db.register_account(
            chat_id,
            telegram_username,
            url,
            mangabuff_username=None,
            notification_type='dm'
        )
        
        if success:
            message += (
                "\n\n<b>⚙️ Настройки уведомлений:</b>\n"
                "Используйте /notifications для выбора способа уведомлений"
            )
        
        self.send_message(chat_id, message)
        logger.info(f"{'✅' if success else '❌'} Регистрация через кнопку")
    
    def process_link_view(
        self,
        chat_id: int,
        callback_query_id: str,
        url: str
    ) -> None:
        """Показывает профиль по ссылке."""
        self.answer_callback_query(callback_query_id)
        
        user_id = self.users_db.extract_id_from_url(url)
        
        if not user_id:
            self.send_message(chat_id, "❌ Неверный формат ссылки")
            return
        
        # Загружаем профиль
        profile = self.sheets_parser.parse_profile(user_id)
        
        if not profile:
            self.send_message(
                chat_id,
                "❌ Профиль не найден в таблице"
            )
            return
        
        message = self.sheets_parser.format_profile_message(profile)
        self.send_message(chat_id, message)
        logger.info(f"✅ Профиль {user_id} показан")
    
    def process_callback_query(self, callback_query: dict) -> None:
        """Обрабатывает нажатия на inline кнопки."""
        callback_id = callback_query.get('id')
        callback_data = callback_query.get('data', '')
        
        from_user = callback_query.get('from', {})
        chat_id = from_user.get('id')
        telegram_username = from_user.get('username')
        
        message = callback_query.get('message', {})
        message_id = message.get('message_id')
        
        logger.info(f"📩 Callback от {chat_id}: {callback_data}")
        
        # Обновляем telegram username
        self.users_db.update_telegram_username(chat_id, telegram_username)
        
        # Обработка действий с ссылками
        if callback_data.startswith("link_add:"):
            url = callback_data.replace("link_add:", "")
            self.process_link_add(chat_id, telegram_username, callback_id, url)
        
        elif callback_data.startswith("link_view:"):
            url = callback_data.replace("link_view:", "")
            self.process_link_view(chat_id, callback_id, url)
        
        # Просмотр профиля
        elif callback_data.startswith("profile:"):
            user_id = callback_data.split(":", 1)[1]
            self.show_profile(chat_id, callback_id, user_id)
        
        # Назад к списку уведомлений
        elif callback_data == "back_to_notif":
            self.answer_callback_query(callback_id)
            self.show_notifications_list(chat_id)
        
        # Открыть настройки уведомлений
        elif callback_data.startswith("notif:"):
            user_id = callback_data.split(":", 1)[1]
            self.answer_callback_query(callback_id)
            self.show_notification_settings(chat_id, message_id, user_id)
        
        # Изменить тип уведомлений
        elif callback_data.startswith("set_notif:"):
            parts = callback_data.split(":")
            if len(parts) == 3:
                user_id = parts[1]
                notification_type = parts[2]
                
                self.set_notification_type_via_button(
                    chat_id,
                    message_id,
                    callback_id,
                    user_id,
                    notification_type
                )
    
    def process_command(
        self,
        chat_id: int,
        telegram_username: Optional[str],
        first_name: Optional[str],
        text: str
    ) -> None:
        """Обрабатывает команду от пользователя."""
        self.users_db.update_telegram_username(chat_id, telegram_username)
        
        text = text.strip()
        logger.info(f"📩 Команда от {telegram_username or first_name} ({chat_id}): {text[:50]}")
        
        # /start
        if text.startswith('/start'):
            self.send_message(
                chat_id,
                "👋 <b>Привет!</b>\n\n"
                "Я бот для уведомлений MangaBuff ClubTaro.\n\n"
                "<b>🎯 Зачем регистрироваться?</b>\n"
                "Когда в клубе появится новая карта и она есть у вас, "
                "я отправлю вам уведомление!\n\n"
                "<b>📝 Как зарегистрировать аккаунт:</b>\n"
                "Используйте команду:\n"
                "<code>/add https://mangabuff.ru/users/123456</code>\n\n"
                "<b>📋 Команды:</b>\n"
                "/add - Добавить аккаунт\n"
                "/notifications - Настройки уведомлений\n"
                "/profile - Просмотр профиля\n"
                "/remove - Удалить аккаунт\n"
                "/help - Помощь"
            )
        
        # /add
        elif text.startswith('/add'):
            parts = text.split(maxsplit=1)
            
            if len(parts) < 2:
                self.send_message(
                    chat_id,
                    "📝 <b>Добавление аккаунта</b>\n\n"
                    "<b>Использование:</b>\n"
                    "<code>/add https://mangabuff.ru/users/123456</code>\n"
                    "<code>/add 123456</code>\n\n"
                    "<i>❗ За раз можно добавить только один аккаунт</i>"
                )
                return
            
            url = parts[1].strip()
            
            # Валидация
            if self.validator:
                user_id = self.users_db.extract_id_from_url(url)
                
                if not user_id:
                    self.send_message(
                        chat_id,
                        "❌ <b>Неверный формат ссылки</b>\n\n"
                        "Примеры:\n"
                        "<code>/add https://mangabuff.ru/users/123456</code>\n"
                        "<code>/add 123456</code>"
                    )
                    return
                
                logger.info(f"🔐 Проверка условий регистрации для {user_id}...")
                
                validation_ok, validation_message = self.validator.validate_user_registration(
                    telegram_id=chat_id,
                    mangabuff_user_id=user_id
                )
                
                if not validation_ok:
                    logger.warning(f"❌ Валидация не пройдена: {telegram_username}")
                    self.send_message(chat_id, validation_message)
                    return
                
                logger.info(f"✅ Валидация пройдена для {user_id}")
            
            # Регистрация
            success, message = self.users_db.register_account(
                chat_id,
                telegram_username,
                url,
                mangabuff_username=None,
                notification_type='dm'
            )
            
            if success:
                message += (
                    "\n\n<b>⚙️ Настройки уведомлений:</b>\n"
                    "Используйте /notifications для выбора способа уведомлений"
                )
            
            self.send_message(chat_id, message)
            logger.info(f"{'✅' if success else '❌'} Регистрация: {telegram_username} -> {url[:50]}")
        
        # /notifications
        elif text.startswith('/notifications') or text.startswith('/list'):
            self.show_notifications_list(chat_id)
        
        # /profile
        elif text.startswith('/profile'):
            self.show_profile_list(chat_id)
        
        # /remove
        elif text.startswith('/remove'):
            parts = text.split()
            
            if len(parts) >= 2:
                user_id = parts[1].strip()
                success, message = self.users_db.unregister_account(chat_id, user_id)
                self.send_message(chat_id, message)
                logger.info(f"{'✅' if success else '❌'} Удаление: {chat_id} -> {user_id}")
            
            else:
                accounts = self.users_db.get_user_accounts(chat_id)
                
                if not accounts:
                    self.send_message(
                        chat_id,
                        "❌ <b>У вас нет привязанных аккаунтов</b>"
                    )
                    return
                
                lines = ["<b>🗑 Удаление аккаунтов</b>\n"]
                
                for acc in accounts:
                    lines.append(
                        f"• {acc['username']} (ID: {acc['user_id']})\n"
                        f"  <code>/remove {acc['user_id']}</code>"
                    )
                
                self.send_message(chat_id, "\n".join(lines))
        
        # /help
        elif text.startswith('/help'):
            self.send_message(
                chat_id,
                "<b>❓ Помощь</b>\n\n"
                "<b>🎯 Зачем регистрироваться?</b>\n"
                "Когда в клубе появится новая карта и она есть у вас, "
                "бот отправит уведомление.\n\n"
                "<b>📬 Типы уведомлений:</b>\n"
                "• <b>Личные сообщения (ЛС)</b> - бот пишет вам в личку\n"
                "• <b>Тег во вкладе</b> - бот тегает вас в общем сообщении\n\n"
                "<b>📝 Как добавить аккаунт?</b>\n"
                "1. Зайдите на свой профиль на mangabuff.ru\n"
                "2. Скопируйте ссылку или ID\n"
                "3. Отправьте команду:\n"
                "   <code>/add https://mangabuff.ru/users/123456</code>\n\n"
                "<b>📋 Команды:</b>\n"
                "/start - Приветствие\n"
                "/add - Добавить аккаунт\n"
                "/notifications - Настройки уведомлений\n"
                "/profile - Просмотр профиля\n"
                "/remove - Удалить аккаунт"
            )
        
        # Ссылка без команды
        elif not text.startswith('/'):
            user_id = self.users_db.extract_id_from_url(text)
            
            if user_id:
                self.ask_link_action(chat_id, text)
            else:
                self.send_message(
                    chat_id,
                    "❌ Неверный формат ссылки\n\n"
                    "Используйте /help для списка команд"
                )
        
        # Неизвестная команда
        else:
            self.send_message(
                chat_id,
                "❌ Неизвестная команда\n\n"
                "Используйте /help для списка команд"
            )
    
    def process_reply(
        self,
        chat_id: str,
        reply_to_id: int,
        text: str,
        from_user: dict
    ) -> None:
        """Обрабатывает ответ на сообщение бота."""
        if reply_to_id not in self.bot_message_ids:
            return
        
        if not self._is_trigger_message(text):
            return
        
        username = from_user.get('username', 'Unknown')
        first_name = from_user.get('first_name', 'User')
        
        logger.info(f"🔔 ТРИГГЕР ЗАМЕНЫ от {username or first_name}: '{text}'")
        print(f"\n🔔 ПОЛУЧЕНА КОМАНДА ЗАМЕНЫ КАРТЫ!")
        print(f"   От: {username or first_name}")
        print(f"   Текст: {text}\n")
        
        if self.on_replace_triggered:
            self.on_replace_triggered()
        
        self.bot_message_ids.discard(reply_to_id)
    
    def get_updates(self) -> list:
        """Получает обновления от Telegram."""
        try:
            url = f"{self.api_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            }
            
            response = requests.get(
                url,
                params=params,
                timeout=35
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    return data.get('result', [])
            
            return []
        except requests.Timeout:
            return []
        except Exception as e:
            logger.error(f"Ошибка getUpdates: {e}")
            return []
    
    def process_updates(self) -> None:
        """Обрабатывает полученные обновления."""
        updates = self.get_updates()
        
        if not updates:
            return
        
        logger.debug(f"Получено {len(updates)} обновлений")
        
        for update in updates:
            try:
                self.last_update_id = update.get('update_id', 0)
                
                callback_query = update.get('callback_query')
                if callback_query:
                    self.process_callback_query(callback_query)
                    continue
                
                message = update.get('message')
                if not message:
                    continue
                
                chat = message.get('chat', {})
                chat_id = chat.get('id')
                chat_id_str = str(chat_id)
                chat_type = chat.get('type')
                
                from_user = message.get('from', {})
                telegram_username = from_user.get('username')
                first_name = from_user.get('first_name', 'Unknown')
                text = message.get('text', '')
                
                if not chat_id or not text:
                    continue
                
                if chat_type == 'private':
                    self.process_command(chat_id, telegram_username, first_name, text)
                
                elif chat_id_str == self.chat_id:
                    if self.thread_id:
                        message_thread_id = message.get('message_thread_id')
                        if message_thread_id != self.thread_id:
                            continue
                    
                    reply_to = message.get('reply_to_message')
                    if reply_to:
                        replied_to_id = reply_to.get('message_id')
                        self.process_reply(chat_id_str, replied_to_id, text, from_user)
                
            except Exception as e:
                logger.error(f"Ошибка обработки обновления: {e}")
    
    def polling_loop(self) -> None:
        """Основной цикл получения обновлений."""
        logger.info("🤖 Telegram unified handler запущен")
        logger.info(f"👁️  Мониторинг триггеров: {', '.join(self.TRIGGER_KEYWORDS)}")
        logger.info("📱 Отправьте /start боту для регистрации")
        
        if self.validator:
            logger.info(f"🔐 Валидация клуба: {self.validator.required_club_slug}")
        
        consecutive_errors = 0
        max_errors = 5
        
        while self.running:
            try:
                self.process_updates()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Ошибка в цикле polling ({consecutive_errors}/{max_errors}): {e}")
                
                if consecutive_errors >= max_errors:
                    logger.error(f"Слишком много ошибок ({max_errors}), остановка")
                    self.running = False
                    break
                
                time.sleep(5)
    
    def start(self) -> None:
        """Запускает обработчик."""
        if self.running:
            logger.warning("Unified handler уже запущен")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self.polling_loop, daemon=True)
        self.thread.start()
        logger.info("✅ Unified handler запущен")
    
    def stop(self) -> None:
        """Останавливает обработчик."""
        if not self.running:
            return
        
        logger.info("🛑 Остановка unified handler...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("✅ Unified handler остановлен")


_unified_handler: Optional[TelegramUnifiedHandler] = None


def create_unified_handler(
    bot_token: str,
    chat_id: str,
    thread_id: Optional[int],
    on_replace_triggered: Optional[Callable] = None,
    proxy_manager=None,
    boost_url: Optional[str] = None,
    session=None
) -> TelegramUnifiedHandler:
    """Создает и запускает unified handler."""
    global _unified_handler
    
    if _unified_handler and _unified_handler.running:
        _unified_handler.stop()
    
    _unified_handler = TelegramUnifiedHandler(
        bot_token,
        chat_id,
        thread_id,
        on_replace_triggered,
        proxy_manager,
        boost_url,
        session
    )
    
    _unified_handler.start()
    return _unified_handler


def get_unified_handler() -> Optional[TelegramUnifiedHandler]:
    """Возвращает глобальный unified handler."""
    return _unified_handler


def stop_unified_handler() -> None:
    """Останавливает глобальный unified handler."""
    global _unified_handler
    
    if _unified_handler:
        _unified_handler.stop()
        _unified_handler = None