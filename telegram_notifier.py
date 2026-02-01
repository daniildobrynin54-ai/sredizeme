"""Модуль для отправки уведомлений в Telegram с регистрацией message_id."""

import os
import json
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
from config import OUTPUT_DIR, SENT_CARDS_FILE
from logger import get_logger

logger = get_logger("telegram_notifier")

try:
    from telegram_users_db import get_users_db
    USERS_DB_AVAILABLE = True
except ImportError:
    USERS_DB_AVAILABLE = False
    logger.warning("База данных пользователей Telegram недоступна")


class TelegramNotifier:
    """Отправщик уведомлений в Telegram с регистрацией message_id."""
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        thread_id: Optional[int] = None,
        enabled: bool = True,
        proxy_manager=None,  # Оставляем для обратной совместимости, но не используем
        reply_monitor=None  # Unified handler вместо reply_monitor
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None
        self.sent_cards_file = os.path.join(OUTPUT_DIR, SENT_CARDS_FILE)
        self._sent_cards = self._load_sent_cards()
        self.reply_monitor = reply_monitor  # Unified handler
        
        # 🔧 ИСПРАВЛЕНО: НЕ используем прокси для Telegram
        self.proxies = None
        logger.info("Telegram notifier работает БЕЗ прокси (прямое подключение)")
    
    def _load_sent_cards(self) -> Dict[int, Dict[str, Any]]:
        try:
            if os.path.exists(self.sent_cards_file):
                with open(self.sent_cards_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки истории отправленных карт: {e}")
        
        return {}
    
    def _save_sent_cards(self) -> None:
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(self.sent_cards_file, 'w', encoding='utf-8') as f:
                json.dump(self._sent_cards, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Ошибка сохранения истории: {e}")
    
    def _is_card_already_sent(self, card_id: int) -> bool:
        card_id_str = str(card_id)
        
        if card_id_str not in self._sent_cards:
            return False
        
        sent_info = self._sent_cards[card_id_str]
        sent_date = sent_info.get('date', '')
        today = datetime.now().strftime('%Y-%m-%d')
        
        return sent_date == today
    
    def _mark_card_as_sent(self, card_id: int, card_name: str) -> None:
        card_id_str = str(card_id)
        
        self._sent_cards[card_id_str] = {
            'name': card_name,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat()
        }
        
        self._save_sent_cards()
    
    def is_enabled(self) -> bool:
        return self.enabled
    
    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
        thread_id: Optional[int] = None
    ) -> Optional[int]:
        """Отправляет текстовое сообщение и возвращает message_id."""
        if not self.enabled:
            return None
        
        try:
            url = f"{self.api_url}/sendMessage"
            
            data = {
                "chat_id": chat_id or self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview
            }
            
            if not chat_id and self.thread_id:
                data["message_thread_id"] = self.thread_id
            
            # 🔧 БЕЗ прокси
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json().get('result', {})
                message_id = result.get('message_id')
                return message_id
            else:
                logger.warning(f"Telegram API error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")
            return None
    
    def send_photo(
        self,
        photo_url: str,
        caption: str = "",
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML"
    ) -> Optional[int]:
        """Отправляет фото с подписью и возвращает message_id."""
        if not self.enabled:
            return None
        
        try:
            url = f"{self.api_url}/sendPhoto"
            
            data = {
                "chat_id": chat_id or self.chat_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": parse_mode
            }
            
            if not chat_id and self.thread_id:
                data["message_thread_id"] = self.thread_id
            
            # 🔧 БЕЗ прокси
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json().get('result', {})
                message_id = result.get('message_id')
                return message_id
            else:
                logger.warning(f"Telegram API error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")
            return None
    
    def send_dm_notification(
        self,
        telegram_id: int,
        username: str,
        card_info: Dict[str, Any]
    ) -> bool:
        card_name = card_info.get('name', 'Неизвестно')
        owners = card_info.get('owners_count', '?')
        wanters = card_info.get('wanters_count', '?')
        image_url = card_info.get('image_url')
        
        caption = (
            f"<b>{username}</b> у вас есть возможность внести карту <b>{card_name}</b>!\n"
            f"\n"
            f"👥 Владельцев: {owners} | Желающих: {wanters}"
        )
        
        logger.info(f"📬 Отправка ЛС → {username} (TG ID: {telegram_id})")
        logger.debug(f"Текст: {caption}")
        
        if image_url:
            message_id = self.send_photo(
                photo_url=image_url,
                caption=caption,
                chat_id=str(telegram_id),
                parse_mode="HTML"
            )
        else:
            message_id = self.send_message(
                text=caption,
                chat_id=str(telegram_id),
                parse_mode="HTML",
                disable_web_page_preview=False
            )
        
        success = message_id is not None
        
        if success:
            logger.info(f"✅ ЛС отправлено: {username}")
        else:
            logger.error(f"❌ Не удалось отправить ЛС: {username}")
        
        return success
    
    def send_thread_notification_with_tags(
        self,
        card_info: Dict[str, Any],
        boost_url: str,
        club_members: List[Dict[str, str]],
        notification_settings: Dict[str, Dict]
    ) -> bool:
        """Отправляет уведомление во вклад с тегами и регистрирует message_id."""
        card_id = card_info.get('card_id')
        card_name = card_info.get('name', 'Неизвестно')
        rank = card_info.get('rank', '?')
        owners = card_info.get('owners_count', '?')
        wanters = card_info.get('wanters_count', '?')
        image_url = card_info.get('image_url')
        
        current_time = datetime.now().strftime('%H:%M:%S')
        
        if club_members:
            usernames = [m['username'] for m in club_members]
            members_line = f"\nКарта есть у: {', '.join(usernames)}"
            logger.info(f"📋 Участники клуба: {', '.join(usernames)}")
        else:
            members_line = "\nКарты ни у кого из клуба нет"
            logger.info("ℹ️  Участников клуба с картой нет")
        
        tags = []
        for member in club_members:
            user_id = member['user_id']
            settings = notification_settings.get(user_id)
            
            if settings and settings['notification_type'] == 'tag':
                telegram_id = settings['telegram_id']
                tags.append(f'<a href="tg://user?id={telegram_id}">@{member["username"]}</a>')
                logger.debug(f"Тег добавлен: {member['username']}")
        
        tags_line = f"\n👤 {' '.join(tags)}" if tags else ""
        
        if tags:
            logger.info(f"✅ Добавлено {len(tags)} тегов")
        else:
            logger.info("ℹ️  Тег не добавлен (все выбрали ЛС или нет привязок)")
        
        message = (
            f"<b>🎴 Карта сменилась</b>\n"
            f"🕐 {current_time}\n"
            f"<a href='{boost_url}'>{boost_url}</a>\n"
            f"\n"
            f"📝 <b>{card_name}</b>\n"
            f"🆔 ID: {card_id} | Ранг: {rank}\n"
            f"👥 Владельцев: {owners} | Желающих: {wanters}"
            f"{members_line}"
            f"{tags_line}"
        )
        
        logger.info("📤 Отправка уведомления во вклад...")
        logger.debug(f"Текст сообщения:\n{message}")
        
        # Получаем message_id
        if image_url:
            message_id = self.send_photo(
                photo_url=image_url,
                caption=message,
                parse_mode="HTML"
            )
        else:
            message_id = self.send_message(
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
        
        success = message_id is not None
        
        # Регистрируем message_id в unified handler
        if success and message_id and self.reply_monitor:
            self.reply_monitor.register_bot_message(message_id)
            logger.debug(f"Message ID {message_id} зарегистрирован в unified handler")
        
        if success:
            logger.info("✅ Уведомление отправлено во вклад")
        else:
            logger.error("❌ Не удалось отправить уведомление во вклад")
        
        return success
    
    def notify_card_change(
        self,
        card_info: Dict[str, Any],
        boost_url: str,
        club_members: List[Dict[str, str]]
    ) -> bool:
        if not self.enabled:
            return False
        
        card_id = card_info.get('card_id')
        card_name = card_info.get('name', 'Неизвестно')
        
        if self._is_card_already_sent(card_id):
            logger.info(f"Карта {card_name} (ID: {card_id}) уже отправлялась сегодня")
            return False
        
        if not USERS_DB_AVAILABLE or not club_members:
            logger.info("База данных или участники недоступны, отправляем только во вклад")
            success = self.send_thread_notification_with_tags(
                card_info,
                boost_url,
                club_members,
                {}
            )
            
            if success:
                self._mark_card_as_sent(card_id, card_name)
            
            return success
        
        try:
            users_db = get_users_db()
            
            user_ids = [m['user_id'] for m in club_members]
            notification_settings = users_db.get_notification_settings(user_ids)
            
            logger.info(f"🔍 Найдено {len(notification_settings)} настроек уведомлений")
            
            dm_users = []
            tag_users = []
            
            for member in club_members:
                user_id = member['user_id']
                settings = notification_settings.get(user_id)
                
                if settings:
                    if settings['notification_type'] == 'dm':
                        dm_users.append({
                            'telegram_id': settings['telegram_id'],
                            'username': member['username'],
                            'user_id': user_id
                        })
                    else:
                        tag_users.append(member)
            
            logger.info(f"📊 Распределение: ЛС={len(dm_users)}, Тег={len(tag_users)}")
            
            dm_sent = 0
            for user in dm_users:
                success = self.send_dm_notification(
                    telegram_id=user['telegram_id'],
                    username=user['username'],
                    card_info=card_info
                )
                if success:
                    dm_sent += 1
                
                import time
                time.sleep(0.5)
            
            if dm_sent > 0:
                logger.info(f"✅ Отправлено {dm_sent} личных сообщений")
            
            thread_success = self.send_thread_notification_with_tags(
                card_info,
                boost_url,
                club_members,
                notification_settings
            )
            
            if dm_sent > 0 or thread_success:
                self._mark_card_as_sent(card_id, card_name)
                logger.info(f"✅ Уведомления отправлены: {card_name} (ID: {card_id})")
                return True
            else:
                logger.error("❌ Не удалось отправить ни одно уведомление")
                return False
            
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомлений: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_connection(self) -> bool:
        if not self.enabled:
            logger.warning("Telegram bot disabled")
            return False
        
        try:
            url = f"{self.api_url}/getMe"
            # 🔧 БЕЗ прокси
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data.get('result', {})
                    bot_name = bot_info.get('username', 'Unknown')
                    logger.info(f"Telegram bot connected: @{bot_name}")
                    return True
            
            logger.warning(f"Telegram bot test failed: {response.status_code}")
            return False
            
        except Exception as e:
            logger.warning(f"Telegram connection error: {e}")
            return False


def create_telegram_notifier(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    thread_id: Optional[int] = None,
    enabled: bool = True,
    proxy_manager=None,  # Игнорируем
    reply_monitor=None  # Unified handler
) -> TelegramNotifier:
    """Фабричная функция для создания Telegram notifier."""
    notifier = TelegramNotifier(
        bot_token,
        chat_id,
        thread_id,
        enabled,
        None,  # Не передаем proxy_manager
        reply_monitor
    )
    
    if notifier.is_enabled():
        notifier.test_connection()
    else:
        logger.info("Telegram notifications disabled")
    
    return notifier