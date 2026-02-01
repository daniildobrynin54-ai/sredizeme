"""Система логирования с цветным выводом, сохранением в файлы по дням и автоматической ротацией."""

import os
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path
import threading


# Цветовые коды для консоли (ANSI)
class Colors:
    """Цветовые коды для терминала."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветным выводом в консоль."""
    
    LEVEL_COLORS = {
        'DEBUG': Colors.BRIGHT_BLACK,
        'INFO': Colors.BRIGHT_CYAN,
        'WARNING': Colors.BRIGHT_YELLOW,
        'ERROR': Colors.BRIGHT_RED,
        'CRITICAL': Colors.BG_RED + Colors.BRIGHT_WHITE,
    }
    
    LEVEL_EMOJI = {
        'DEBUG': '🔧',
        'INFO': 'ℹ️ ',
        'WARNING': '⚠️ ',
        'ERROR': '❌',
        'CRITICAL': '🔥',
    }
    
    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None, use_colors: bool = True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога с цветами."""
        if self.use_colors:
            level_color = self.LEVEL_COLORS.get(record.levelname, '')
            level_emoji = self.LEVEL_EMOJI.get(record.levelname, '')
            
            levelname = f"{level_color}{level_emoji}  {record.levelname}{Colors.RESET}"
            
            original_levelname = record.levelname
            record.levelname = levelname
            
            result = super().format(record)
            
            record.levelname = original_levelname
            
            return result
        else:
            return super().format(record)


class PlainFormatter(logging.Formatter):
    """Форматтер без цветов для файлов."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога без цветов."""
        return super().format(record)


class DailyRotatingFileHandler(logging.Handler):
    """
    🔧 ИСПРАВЛЕНО: Handler с автоматической ротацией БЕЗ deadlock.
    
    Создает новый файл при смене суток даже если приложение не перезапускалось.
    """
    
    def __init__(self, base_dir: str, level: int = logging.INFO):
        super().__init__(level)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.current_date = None
        self.current_handler = None
        # 🔧 ИСПРАВЛЕНО: Используем RLock вместо Lock для избежания deadlock
        self.lock = threading.RLock()
        
        # Форматтер для файлов
        file_format = '[%(asctime)s] %(levelname)-8s | %(name)s > %(message)s'
        self.formatter = PlainFormatter(
            fmt=file_format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        self._rotate_if_needed()
    
    def _get_current_date(self) -> str:
        """Возвращает текущую дату в формате YYYY-MM-DD."""
        return datetime.now().strftime('%Y-%m-%d')
    
    def _rotate_if_needed(self) -> None:
        """
        🔧 ИСПРАВЛЕНО: Проверяет и выполняет ротацию без блокировки в emit().
        """
        current_date = self._get_current_date()
        
        # 🔧 КРИТИЧНО: Проверка БЕЗ блокировки для быстрого выхода
        if current_date == self.current_date:
            return
        
        # Только если точно нужна ротация - берем блокировку
        with self.lock:
            # Двойная проверка после получения блокировки
            if current_date == self.current_date:
                return
            
            # Закрываем старый handler
            if self.current_handler:
                try:
                    self.current_handler.close()
                except Exception:
                    pass
            
            # Создаем новый файл
            log_file = self.base_dir / f"{current_date}.log"
            self.current_handler = logging.FileHandler(
                log_file,
                mode='a',
                encoding='utf-8'
            )
            self.current_handler.setFormatter(self.formatter)
            
            self.current_date = current_date
            
            # Логируем ротацию
            if self.current_handler:
                rotation_msg = f"=== Log rotation: new file created at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ==="
                record = logging.LogRecord(
                    name='logger',
                    level=logging.INFO,
                    pathname='',
                    lineno=0,
                    msg=rotation_msg,
                    args=(),
                    exc_info=None
                )
                try:
                    self.current_handler.emit(record)
                except Exception:
                    pass
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        🔧 ИСПРАВЛЕНО: Записывает лог БЕЗ блокировки при проверке ротации.
        """
        try:
            # 🔧 КРИТИЧНО: Проверка ротации БЕЗ блокировки
            self._rotate_if_needed()
            
            # Запись в handler (может быть одновременно из разных потоков)
            if self.current_handler:
                # FileHandler сам thread-safe, не нужна дополнительная блокировка
                self.current_handler.emit(record)
        except Exception:
            self.handleError(record)
    
    def close(self) -> None:
        """Закрывает handler."""
        with self.lock:
            if self.current_handler:
                try:
                    self.current_handler.close()
                except Exception:
                    pass
        super().close()


class AppLogger:
    """Главный класс для управления логированием с автоматической ротацией."""
    
    def __init__(
        self,
        name: str = "MangaBuff",
        base_dir: str = "logs",
        level: int = logging.INFO,
        console_colors: bool = True
    ):
        self.name = name
        self.base_dir = Path(base_dir)
        self.level = level
        self.console_colors = console_colors
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        self.logger.handlers.clear()
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Настраивает обработчики для консоли и файлов."""
        # === КОНСОЛЬНЫЙ ОБРАБОТЧИК ===
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.level)
        
        console_format = (
            f"{Colors.BRIGHT_BLACK}[%(asctime)s]{Colors.RESET} "
            f"%(levelname)s "
            f"{Colors.BRIGHT_BLACK}|{Colors.RESET} "
            f"{Colors.CYAN}%(name)s{Colors.RESET} "
            f"{Colors.BRIGHT_BLACK}>{Colors.RESET} "
            f"%(message)s"
        )
        
        console_formatter = ColoredFormatter(
            fmt=console_format,
            datefmt='%H:%M:%S',
            use_colors=self.console_colors
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # === 🔧 ИСПРАВЛЕНО: ФАЙЛОВЫЙ ОБРАБОТЧИК С РОТАЦИЕЙ БЕЗ DEADLOCK ===
        rotating_handler = DailyRotatingFileHandler(
            base_dir=str(self.base_dir),
            level=self.level
        )
        self.logger.addHandler(rotating_handler)
        
        # === ФАЙЛОВЫЙ ОБРАБОТЧИК (все ошибки) ===
        error_log_file = self.base_dir / "errors.log"
        
        error_handler = logging.FileHandler(
            error_log_file,
            mode='a',
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        
        file_format = '[%(asctime)s] %(levelname)-8s | %(name)s > %(message)s'
        file_formatter = PlainFormatter(
            fmt=file_format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        error_handler.setFormatter(file_formatter)
        self.logger.addHandler(error_handler)
    
    def debug(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня DEBUG."""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня INFO."""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня WARNING."""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня ERROR."""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня CRITICAL."""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """Логирует исключение с трассировкой."""
        self.logger.exception(message, *args, **kwargs)
    
    def section(self, title: str, char: str = "=", length: int = 60):
        """Выводит секцию с заголовком."""
        border = char * length
        self.info(border)
        self.info(f"  {title}")
        self.info(border)
    
    def success(self, message: str):
        """Выводит сообщение об успехе."""
        colored_msg = f"{Colors.BRIGHT_GREEN}✅ {message}{Colors.RESET}"
        self.logger.info(colored_msg)
    
    def failure(self, message: str):
        """Выводит сообщение об ошибке."""
        colored_msg = f"{Colors.BRIGHT_RED}❌ {message}{Colors.RESET}"
        self.logger.error(colored_msg)


class ModuleLogger:
    """Логгер для отдельного модуля."""
    
    def __init__(self, module_name: str, app_logger: AppLogger):
        self.module_name = module_name
        self.app_logger = app_logger
        self.logger = logging.getLogger(f"{app_logger.name}.{module_name}")
        self.logger.setLevel(app_logger.level)
    
    def debug(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня DEBUG."""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня INFO."""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня WARNING."""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня ERROR."""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """Логирует сообщение уровня CRITICAL."""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """Логирует исключение с трассировкой."""
        self.logger.exception(message, *args, **kwargs)
    
    def section(self, title: str, char: str = "=", length: int = 60):
        """Выводит секцию с заголовком."""
        self.app_logger.section(title, char, length)
    
    def success(self, message: str):
        """Выводит сообщение об успехе."""
        self.app_logger.success(message)
    
    def failure(self, message: str):
        """Выводит сообщение об ошибке."""
        self.app_logger.failure(message)


# Глобальный экземпляр логгера
_global_logger: Optional[AppLogger] = None


def setup_logger(
    name: str = "MangaBuff",
    base_dir: str = "logs",
    level: int = logging.INFO,
    console_colors: bool = True
) -> AppLogger:
    """Настраивает и возвращает главный логгер приложения."""
    global _global_logger
    _global_logger = AppLogger(
        name=name,
        base_dir=base_dir,
        level=level,
        console_colors=console_colors
    )
    return _global_logger


def get_logger(module_name: Optional[str] = None) -> AppLogger | ModuleLogger:
    """Возвращает логгер."""
    global _global_logger
    
    if _global_logger is None:
        setup_logger()
    
    if module_name:
        return ModuleLogger(module_name, _global_logger)
    
    return _global_logger


# Удобные функции для быстрого доступа
def debug(message: str, *args, **kwargs):
    """Логирует сообщение уровня DEBUG."""
    get_logger().debug(message, *args, **kwargs)


def info(message: str, *args, **kwargs):
    """Логирует сообщение уровня INFO."""
    get_logger().info(message, *args, **kwargs)


def warning(message: str, *args, **kwargs):
    """Логирует сообщение уровня WARNING."""
    get_logger().warning(message, *args, **kwargs)


def error(message: str, *args, **kwargs):
    """Логирует сообщение уровня ERROR."""
    get_logger().error(message, *args, **kwargs)


def critical(message: str, *args, **kwargs):
    """Логирует сообщение уровня CRITICAL."""
    get_logger().critical(message, *args, **kwargs)


def exception(message: str, *args, **kwargs):
    """Логирует исключение с трассировкой."""
    get_logger().exception(message, *args, **kwargs)


def section(title: str, char: str = "=", length: int = 60):
    """Выводит секцию с заголовком."""
    get_logger().section(title, char, length)


def success(message: str):
    """Выводит сообщение об успехе."""
    get_logger().success(message)


def failure(message: str):
    """Выводит сообщение об ошибке."""
    get_logger().failure(message)
