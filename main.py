import argparse
import sys
import time
import os
import logging
from typing import Optional
from logger import setup_logger, get_logger

logger = get_logger("main")

from config import (
    OUTPUT_DIR,
    BOOST_CARD_FILE,
    WAIT_AFTER_ALL_OWNERS,
    WAIT_CHECK_INTERVAL,
    WAIT_MODE_CHECK_INTERVAL,
    WAIT_MODE_STATS_INTERVAL,
    HISTORY_CHECK_INTERVAL,
    TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_THREAD_ID
)
from auth import login
from inventory import get_user_inventory, InventoryManager
from boost import get_boost_card_info
from card_selector import select_trade_card
from owners_parser import process_owners_page_by_page, OwnersProcessor
from monitor import start_boost_monitor
from trade import (
    send_trade_to_owner,
    cancel_all_sent_trades,
    TradeHistoryMonitor
)
from card_replacement import check_and_replace_if_needed, force_replace_card
from daily_stats import create_stats_manager
from proxy_manager import create_proxy_manager
from rate_limiter import get_rate_limiter
from telegram_notifier import create_telegram_notifier
from telegram_unified_handler import create_unified_handler, stop_unified_handler
from utils import (
    ensure_dir_exists,
    save_json,
    load_json,
    format_card_info,
    print_section,
    print_success,
    print_error,
    print_warning,
    print_info
)


class MangaBuffApp:
    """
    Главное приложение MangaBuff v2.6 - добавлена валидация клуба.
    """
    
    MAX_FAILED_CYCLES = 3
    
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session = None
        self.monitor = None
        self.history_monitor = None
        self.output_dir = OUTPUT_DIR
        self.inventory_manager = InventoryManager(self.output_dir)
        self.stats_manager = None
        self.processor = None
        self.proxy_manager = None
        self.rate_limiter = get_rate_limiter()
        self.telegram_notifier = None
        self.telegram_unified_handler = None
        self.replace_requested = False
        self.failed_cycles_count = 0
    
    def setup(self) -> bool:
        ensure_dir_exists(self.output_dir)
        
        self.proxy_manager = create_proxy_manager(
            proxy_url=self.args.proxy,
            proxy_file=self.args.proxy_file,
            auto_update_ip=True
        )
        
        print(f"⏱️  Rate Limiting: {self.rate_limiter.max_requests} req/min")
        
        print("\n🔐 Вход в аккаунт...")
        self.session = login(
            self.args.email,
            self.args.password,
            self.proxy_manager
        )
        
        if not self.session:
            print_error("Ошибка авторизации")
            return False
        
        print_success("Авторизация успешна\n")
        
        # 🔧 НОВОЕ: Устанавливаем session в БД для парсинга nicknames
        from telegram_users_db import get_users_db
        users_db = get_users_db()
        users_db.set_session(self.session)
        logger.info("✅ Session установлена в БД для парсинга nicknames")
        
        # 🔧 ПЕРЕМЕЩЕНО: Инициализируем Telegram ПОСЛЕ авторизации
        bot_token = self.args.telegram_token or TELEGRAM_BOT_TOKEN
        chat_id_str = self.args.telegram_chat_id or TELEGRAM_CHAT_ID
        thread_id_val = self.args.telegram_thread_id or TELEGRAM_THREAD_ID
        
        def on_replace_triggered():
            self.replace_requested = True
            logger.info("🔔 Установлен флаг replace_requested через Telegram")
        
        if bot_token and chat_id_str and (self.args.telegram_enabled if hasattr(self.args, 'telegram_enabled') else TELEGRAM_ENABLED):
            self.telegram_unified_handler = create_unified_handler(
                bot_token=bot_token,
                chat_id=chat_id_str,
                thread_id=thread_id_val,
                on_replace_triggered=on_replace_triggered,
                proxy_manager=self.proxy_manager,
                boost_url=self.args.boost_url,  # 🔧 НОВОЕ: Передаем boost_url
                session=self.session  # 🔧 НОВОЕ: Передаем session
            )
            print("🤖 Telegram бот запущен (команды + мониторинг + валидация)\n")
        
        self.telegram_notifier = create_telegram_notifier(
            bot_token=bot_token,
            chat_id=chat_id_str,
            thread_id=thread_id_val,
            enabled=self.args.telegram_enabled if hasattr(self.args, 'telegram_enabled') else TELEGRAM_ENABLED,
            proxy_manager=self.proxy_manager,
            reply_monitor=self.telegram_unified_handler
        )

        return True
    
    def init_stats_manager(self) -> bool:
        if not self.args.boost_url:
            print_warning("URL буста не указан")
            return False
        
        print("📊 Инициализация менеджера статистики...")
        self.stats_manager = create_stats_manager(
            self.session,
            self.args.boost_url
        )
        self.stats_manager.print_stats(force_refresh=True)
        return True
    
    def init_history_monitor(self) -> bool:
        print("📊 Инициализация монитора истории обменов...")
        
        self.history_monitor = TradeHistoryMonitor(
            session=self.session,
            user_id=int(self.args.user_id),
            inventory_manager=self.inventory_manager,
            debug=self.args.debug
        )
        
        self.history_monitor.start(check_interval=HISTORY_CHECK_INTERVAL)
        
        print_success(f"Монитор истории запущен (проверка каждые {HISTORY_CHECK_INTERVAL}с)\n")
        return True
    
    def init_processor(self) -> None:
        if not self.processor:
            self.processor = OwnersProcessor(
                session=self.session,
                select_card_func=select_trade_card,
                send_trade_func=send_trade_to_owner,
                dry_run=self.args.dry_run,
                debug=self.args.debug
            )
    
    def load_inventory(self) -> Optional[list]:
        if self.args.skip_inventory:
            return []
        
        print(f"📦 Загрузка инвентаря пользователя {self.args.user_id}...")
        inventory = get_user_inventory(self.session, self.args.user_id)
        
        print_success(f"Всего загружено: {len(inventory)} карточек")
        
        if self.inventory_manager.save_inventory(inventory):
            print(f"💾 Инвентарь сохранен")
        
        print(f"\n🔄 Синхронизация инвентаря с пропарсенными данными...")
        if self.inventory_manager.sync_inventories():
            print_success("Синхронизация завершена\n")
        else:
            print_warning("Ошибка синхронизации инвентаря\n")
        
        return inventory
    
    def load_boost_card(self) -> Optional[dict]:
        if not self.args.boost_url:
            return None
        
        boost_card = get_boost_card_info(self.session, self.args.boost_url)
        
        if not boost_card:
            print_error("Не удалось получить карту для буста")
            return None
        
        print_success("Карточка для вклада:")
        print(f"   {format_card_info(boost_card)}")
        
        if self.telegram_notifier and self.telegram_notifier.is_enabled():
            print("\n📱 Отправка уведомления о текущей карте в Telegram...")
            club_members = boost_card.get('club_members', [])
            success = self.telegram_notifier.notify_card_change(
                card_info=boost_card,
                boost_url=self.args.boost_url,
                club_members=club_members
            )
            if success:
                print_success("Уведомление отправлено в Telegram")
            else:
                print_warning("Не удалось отправить уведомление")
        
        if boost_card.get('needs_replacement', False):
            print_warning(f"\n⚠️  Карта требует замены!")
            
            new_card = check_and_replace_if_needed(
                self.session,
                self.args.boost_url,
                boost_card,
                self.stats_manager
            )
            
            if new_card:
                boost_card = new_card
        
        save_json(f"{self.output_dir}/{BOOST_CARD_FILE}", boost_card)
        print(f"💾 Карточка сохранена\n")
        
        return boost_card
    
    def start_monitoring(self, boost_card: dict):
        if not self.args.enable_monitor:
            return
        
        self.monitor = start_boost_monitor(
            self.session,
            self.args.boost_url,
            self.stats_manager,
            self.output_dir,
            self.telegram_notifier
        )
        
        self.monitor.current_card_id = boost_card['card_id']
    
    def wait_for_boost_or_timeout(
        self,
        card_id: int,
        timeout: int = WAIT_AFTER_ALL_OWNERS
    ) -> bool:
        if not self.monitor:
            return False
        
        print_section(
            f"⏳ ВСЕ ВЛАДЕЛЬЦЫ ОБРАБОТАНЫ - Ожидание {timeout // 60} мин",
            char="="
        )
        print(f"   Текущая карта: ID {card_id}")
        print(f"   Мониторинг продолжает работать...\n")
        
        start_time = time.time()
        check_count = 0
        
        while time.time() - start_time < timeout:
            check_count += 1
            
            if self.monitor.card_changed:
                elapsed = int(time.time() - start_time)
                print(f"\n✅ БУСТ ПРОИЗОШЕЛ через {elapsed}с!")
                return True
            
            if check_count % 15 == 0:
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed
                print(f"⏳ Ожидание: {elapsed}с / {remaining}с осталось")
            
            time.sleep(WAIT_CHECK_INTERVAL)
        
        print(f"\n⏱️  ТАЙМАУТ: {timeout // 60} минут")
        return False
    
    def enter_wait_mode(self, current_boost_card: dict) -> None:
        """
        🔧 ИСПРАВЛЕНО: Режим ожидания без спама логами.
        
        Только:
        1. Проверяет лимиты раз в 30 секунд
        2. Мониторинг работает (легковесная проверка card_id)
        3. Telegram бот активен
        4. История обменов обновляется
        
        Args:
            current_boost_card: Текущая карта для обработки команд замены
        """
        # Отменяем все обмены ПЕРЕД входом в режим ожидания
        if not self.args.dry_run and self.processor and self.processor.trade_manager:
            print("\n🔄 Отменяем все обмены перед режимом ожидания...")
            success = cancel_all_sent_trades(
                self.session,
                self.processor.trade_manager,
                self.history_monitor,
                self.args.debug
            )
            if success:
                print_success("✅ Обмены отменены")
            else:
                print_warning("⚠️  Не удалось отменить обмены")
        
        print_section("⏸️  РЕЖИМ ОЖИДАНИЯ", char="=")
        print("   ⛔ Достигнут лимит вкладов (50/50)")
        print("   🔄 Мониторинг карты: АКТИВЕН (легковесная проверка card_id)")
        print("   📱 Telegram уведомления: АКТИВНЫ")
        print(f"   📜 История обменов: проверка каждые {HISTORY_CHECK_INTERVAL}с")
        print(f"   ⏰ Проверка сброса лимитов: каждые {WAIT_MODE_CHECK_INTERVAL}с")
        print("   💡 Можно использовать команду замены в Telegram")
        print("   Нажмите Ctrl+C для завершения\n")
        
        self.stats_manager.print_stats(force_refresh=True)
        
        check_count = 0
        last_stats_time = time.time()
        
        while True:
            check_count += 1
            
            # 🔧 КРИТИЧНО: Проверяем только можем ли вкладывать
            if self.stats_manager.can_donate(force_refresh=True):
                print_success("\n✅ Лимит вкладов обновился! Возобновляем работу...")
                self.stats_manager.print_stats()
                return
            
            # Вывод статистики раз в 5 минут
            current_time = time.time()
            if current_time - last_stats_time >= WAIT_MODE_STATS_INTERVAL:
                print_section("📊 РЕЖИМ ОЖИДАНИЯ - Статистика", char="-")
                self.stats_manager.print_stats()
                last_stats_time = current_time
            
            # 🔧 ИСПРАВЛЕНО: Проверка смены карты через монитор (легковесная)
            # Мониторинг работает в фоне и сам проверяет card_id каждые 2 секунды
            if self.monitor and self.monitor.card_changed:
                logger.info("ℹ️  Карта в клубе изменилась (режим ожидания)")
                print_info("ℹ️  Карта в клубе изменилась (режим ожидания)")
                self.monitor.card_changed = False
                
                # 🔧 НОВОЕ: Обновляем текущую карту
                current_boost_card = self._load_current_boost_card(current_boost_card)
            
            # Проверка команды замены из Telegram
            if self.replace_requested:
                print_info("\n🔔 Получена команда замены из Telegram в режиме ожидания!")
                self.replace_requested = False
                
                new_card = self.attempt_auto_replacement(
                    current_boost_card,
                    reason="ЗАМЕНА ПО КОМАНДЕ ИЗ TELEGRAM (режим ожидания)"
                )
                
                if new_card:
                    print_success("✅ Карта заменена! Возвращаемся к работе...")
                    current_boost_card = new_card
                else:
                    print_warning("⚠️  Замена не удалась, продолжаем ожидание")
            
            # 🔧 ИСПРАВЛЕНО: Только одна строка в логах
            if check_count % 10 == 0:
                logger.debug(f"Режим ожидания: проверка #{check_count}")
            
            time.sleep(WAIT_MODE_CHECK_INTERVAL)
    
    def attempt_auto_replacement(self, current_boost_card: dict, reason: str = "АВТОЗАМЕНА ПОСЛЕ 3 НЕУДАЧНЫХ ЦИКЛОВ") -> Optional[dict]:
        if not self.stats_manager.can_replace(force_refresh=True):
            print_warning("⛔ Лимит замен достигнут!")
            self.stats_manager.print_stats()
            return None
        
        new_card = force_replace_card(
            self.session,
            self.args.boost_url,
            current_boost_card,
            self.stats_manager,
            reason=reason
        )
        
        if new_card:
            self.failed_cycles_count = 0
            print_success("✅ Замена выполнена! Счетчик неудачных циклов сброшен\n")
            return new_card
        else:
            print_warning("❌ Замена не удалась\n")
            return None
    
    def run_processing_mode(self, boost_card: dict):
        self.init_processor()
        
        while True:
            # 🔧 ИСПРАВЛЕНО: Проверяем лимит вкладов
            if not self.stats_manager.can_donate(force_refresh=True):
                print_warning("\n⛔ Лимит вкладов достигнут!")
                current_boost_card = self._load_current_boost_card(boost_card)
                self.enter_wait_mode(current_boost_card)
                # После выхода из режима ожидания продолжаем
                continue
            
            current_boost_card = self._load_current_boost_card(boost_card)
            current_card_id = current_boost_card['card_id']
            
            if self.replace_requested:
                print_section("🔔 ЗАМЕНА ПО КОМАНДЕ ИЗ TELEGRAM", char="=")
                self.replace_requested = False
                
                new_card = self.attempt_auto_replacement(
                    current_boost_card, 
                    reason="ЗАМЕНА ПО КОМАНДЕ ИЗ TELEGRAM"
                )
                
                if new_card:
                    current_boost_card = new_card
                    current_card_id = new_card['card_id']
                    
                    if self.monitor:
                        self.monitor.current_card_id = current_card_id
                    
                    self.processor.reset_state()
                    continue
                else:
                    print_info("ℹ️  Продолжаем работу с текущей картой")
            
            if self.failed_cycles_count >= self.MAX_FAILED_CYCLES:
                print_warning(f"\n⚠️  Достигнуто {self.MAX_FAILED_CYCLES} неудачных ПОЛНЫХ циклов!")
                
                new_card = self.attempt_auto_replacement(
                    current_boost_card,
                    reason="АВТОЗАМЕНА ПОСЛЕ 3 НЕУДАЧНЫХ ЦИКЛОВ"
                )
                
                if new_card:
                    current_boost_card = new_card
                    current_card_id = new_card['card_id']
                    
                    if self.monitor:
                        self.monitor.current_card_id = current_card_id
                    
                    self.processor.reset_state()
                    continue
                else:
                    self.failed_cycles_count = 0
                    print_info("ℹ️  Продолжаем работу с текущей картой")
            
            if current_boost_card.get('needs_replacement', False):
                if not self.stats_manager.can_replace(force_refresh=True):
                    print_warning(f"\n⚠️  Карта требует замены, но лимит замен исчерпан!")
                    self.stats_manager.print_stats()
                else:
                    print_warning(f"\n⚠️  Карта требует автозамены!")
                    
                    new_card = check_and_replace_if_needed(
                        self.session,
                        self.args.boost_url,
                        current_boost_card,
                        self.stats_manager
                    )
                    
                    if new_card:
                        current_boost_card = new_card
                        current_card_id = new_card['card_id']
                        
                        if self.monitor:
                            self.monitor.current_card_id = current_card_id
                        
                        self.processor.reset_state()
                        self.failed_cycles_count = 0
            
            if self.monitor:
                self.monitor.card_changed = False
                logger.info("🔄 Флаг card_changed сброшен - начинаем новую обработку")
            
            print(f"\n🎯 Обработка: {current_boost_card['name']} (ID: {current_card_id})")
            
            current_rate = self.rate_limiter.get_current_rate()
            print(f"📊 Текущий rate: {current_rate}/{self.rate_limiter.max_requests} req/min\n")
            
            # 🔧 ЕЩЕ РАЗ проверяем лимит перед обработкой
            if not self.stats_manager.can_donate(force_refresh=True):
                print_warning("⛔ Лимит вкладов достигнут!")
                self.enter_wait_mode(current_boost_card)
                continue
            
            boost_happened_this_cycle = False
            
            if self.replace_requested:
                print("\n⚠️  Получена команда замены! Прерываем обработку...")
                self.replace_requested = False
                
                if not self.args.dry_run and self.processor.trade_manager:
                    print("🔄 Отменяем обмены перед заменой...")
                    cancel_all_sent_trades(
                        self.session,
                        self.processor.trade_manager,
                        self.history_monitor,
                        self.args.debug
                    )
                
                new_card = self.attempt_auto_replacement(
                    current_boost_card,
                    reason="ЗАМЕНА ПО КОМАНДЕ ИЗ TELEGRAM"
                )
                
                if new_card:
                    current_boost_card = new_card
                    current_card_id = new_card['card_id']
                    
                    if self.monitor:
                        self.monitor.current_card_id = current_card_id
                    
                    self.processor.reset_state()
                    continue
                else:
                    print_info("ℹ️  Замена не удалась, продолжаем")
            
            total = process_owners_page_by_page(
                session=self.session,
                card_id=str(current_card_id),
                boost_card=current_boost_card,
                output_dir=self.output_dir,
                select_card_func=select_trade_card,
                send_trade_func=send_trade_to_owner,
                monitor_obj=self.monitor,
                processor=self.processor,
                dry_run=self.args.dry_run,
                debug=self.args.debug
            )
            
            if total > 0:
                print_success(f"Обработано {total} владельцев")
                
                if self.processor.trade_manager:
                    sent_count = len(self.processor.trade_manager.sent_trades)
                    print_success(f"✅ Отправлено обменов: {sent_count}")
            else:
                print_warning("Нет доступных владельцев")
            
            if self.replace_requested:
                print("\n⚠️  Получена команда замены после обработки владельцев!")
                self.replace_requested = False
                
                if not self.args.dry_run and self.processor.trade_manager:
                    print("🔄 Отменяем обмены перед заменой...")
                    cancel_all_sent_trades(
                        self.session,
                        self.processor.trade_manager,
                        self.history_monitor,
                        self.args.debug
                    )
                
                new_card = self.attempt_auto_replacement(
                    current_boost_card,
                    reason="ЗАМЕНА ПО КОМАНДЕ ИЗ TELEGRAM"
                )
                
                if new_card:
                    self.processor.reset_state()
                    self.failed_cycles_count = 0
                    self._prepare_restart()
                    time.sleep(1)
                    continue
                else:
                    print_info("ℹ️  Замена не удалась, продолжаем")
            
            if self._should_restart():
                boost_happened_this_cycle = True
                self.processor.reset_state()
                self.failed_cycles_count = 0
                print_success("✅ Буст произошел - счетчик неудачных циклов сброшен")
                self._prepare_restart()
                time.sleep(1)
                continue
            
            if self.monitor and self.monitor.is_running() and total > 0:
                boost_occurred = self.wait_for_boost_or_timeout(current_card_id)
                
                if boost_occurred:
                    boost_happened_this_cycle = True
                    self.processor.reset_state()
                    self.failed_cycles_count = 0
                    print_success("✅ Буст произошел - счетчик неудачных циклов сброшен")
                    self._prepare_restart()
                    time.sleep(1)
                    continue
                else:
                    print("🔄 Отменяем обмены...")
                    if not self.args.dry_run:
                        success = cancel_all_sent_trades(
                            self.session,
                            self.processor.trade_manager,
                            self.history_monitor,
                            self.args.debug
                        )
                        if success:
                            print_success("Обмены отменены, история проверена!")
                        else:
                            print_warning("Не удалось отменить")
                    
                    if not boost_happened_this_cycle:
                        self.failed_cycles_count += 1
                        print_warning(
                            f"⚠️  ПОЛНЫЙ цикл #{self.failed_cycles_count}/{self.MAX_FAILED_CYCLES} "
                            f"завершен БЕЗ вклада (таймаут ожидания)"
                        )
                    
                    print_section("🔄 ПЕРЕЗАПУСК с той же картой", char="=")
                    time.sleep(1)
                    continue
            
            if total == 0:
                self.failed_cycles_count += 1
                print_warning(
                    f"⚠️  ПОЛНЫЙ цикл #{self.failed_cycles_count}/{self.MAX_FAILED_CYCLES} "
                    f"завершен БЕЗ вклада (нет владельцев)"
                )
                print_section("🔄 ПЕРЕЗАПУСК с той же картой", char="=")
                time.sleep(1)
                continue
            
            break
    
    def _load_current_boost_card(self, default: dict) -> dict:
        path = f"{self.output_dir}/{BOOST_CARD_FILE}"
        current = load_json(path, default=default)
        return current if current else default
    
    def _should_restart(self) -> bool:
        return (
            self.monitor and
            self.monitor.is_running() and
            self.monitor.card_changed
        )
    
    def _prepare_restart(self):
        print_section("🔄 ПЕРЕЗАПУСК с новой картой", char="=")
    
    def wait_for_monitor(self):
        if not self.monitor or not self.monitor.is_running():
            return
        
        try:
            print_section("Мониторинг активен. Ctrl+C для выхода", char="=")
            
            while self.monitor.is_running():
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Прерывание...")
            self.monitor.stop()
            if self.history_monitor:
                self.history_monitor.stop()
    
    def run(self) -> int:
        if not self.setup():
            return 1
        
        if self.args.boost_url:
            if not self.init_stats_manager():
                print_warning("Работа без статистики")
        
        if not self.args.skip_inventory:
            self.init_history_monitor()
        
        inventory = self.load_inventory()
        boost_card = self.load_boost_card()
        
        if not boost_card:
            return 0
        
        self.start_monitoring(boost_card)
        
        if not self.args.only_list_owners:
            self.run_processing_mode(boost_card)
        
        self.wait_for_monitor()
        
        if self.history_monitor:
            self.history_monitor.stop()
        
        return 0


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MangaBuff v2.6 - добавлена валидация клуба"
    )
    
    parser.add_argument("--email", required=True, help="Email")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument("--user_id", required=True, help="ID пользователя")
    parser.add_argument("--boost_url", help="URL буста")
    
    parser.add_argument("--proxy", help="URL прокси")
    parser.add_argument("--proxy_file", help="Файл с прокси")
    
    parser.add_argument("--telegram_token", help="Telegram Bot Token")
    parser.add_argument("--telegram_chat_id", help="Telegram Chat ID")
    parser.add_argument("--telegram_thread_id", type=int, help="Telegram Thread ID")
    parser.add_argument("--telegram_enabled", action="store_true", default=None, help="Включить Telegram")
    parser.add_argument("--telegram_disabled", action="store_true", help="Отключить Telegram")
    
    parser.add_argument("--skip_inventory", action="store_true", help="Пропустить инвентарь")
    parser.add_argument("--only_list_owners", action="store_true", help="Только список владельцев")
    parser.add_argument("--enable_monitor", action="store_true", help="Включить мониторинг")
    parser.add_argument("--dry_run", action="store_true", help="Тестовый режим")
    parser.add_argument("--debug", action="store_true", help="Отладка")
    
    return parser


def main():
    main_logger = setup_logger(
        name="MangaBuff",
        base_dir="logs",
        level=logging.INFO,
        console_colors=True
    )
    
    main_logger.section("ЗАПУСК ПРИЛОЖЕНИЯ MANGABUFF", char="=")
    main_logger.info("Версия: 2.6 (добавлена валидация клуба)")
    main_logger.info(f"Время запуска: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if args.debug:
        main_logger.logger.setLevel(logging.DEBUG)
        main_logger.info("Режим отладки включен - уровень логирования: DEBUG")
    
    if not args.proxy and not args.proxy_file:
        args.proxy = os.getenv('PROXY_URL')
    
    if args.telegram_disabled:
        args.telegram_enabled = False
    elif args.telegram_enabled is None:
        args.telegram_enabled = TELEGRAM_ENABLED
    
    app = MangaBuffApp(args)
    
    try:
        exit_code = app.run()
        if exit_code == 0:
            main_logger.success("Приложение завершило работу успешно")
        else:
            main_logger.error(f"Приложение завершилось с кодом: {exit_code}")
        
        if app.telegram_unified_handler:
            stop_unified_handler()
        
        sys.exit(exit_code)
    except KeyboardInterrupt:
        main_logger.warning("\nПриложение прервано пользователем")
        
        if app.telegram_unified_handler:
            stop_unified_handler()
        
        sys.exit(0)
    except Exception as e:
        main_logger.exception(f"Критическая ошибка: {e}")
        
        if app.telegram_unified_handler:
            stop_unified_handler()
        
        sys.exit(1)


if __name__ == "__main__":
    main()