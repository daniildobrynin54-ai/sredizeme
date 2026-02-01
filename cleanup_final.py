#!/usr/bin/env python3
"""
Финальный скрипт очистки от логгера и исправления ошибок.
Анализирует код, находит проблемы и исправляет их.
"""

import re
import os
import sys

class CodeCleaner:
    """Очистка кода от логгера и исправление ошибок."""
    
    def __init__(self):
        self.issues_found = []
        
    def remove_logger_imports(self, content: str) -> str:
        """Удаляет импорты логгера."""
        patterns = [
            r'^from logger import .*$\n?',
            r'^import logger.*$\n?',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content
    
    def remove_logger_initialization(self, content: str) -> str:
        """Удаляет инициализацию логгера."""
        patterns = [
            r'^logger = get_logger\(.*\)$\n?',
            r'^main_logger = setup_logger\(.*\)$\n?',
            r'^\s*logger = get_logger\(.*\)\s*$\n?',
            r'^\s*main_logger = setup_logger\(.*\)\s*$\n?',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content
    
    def remove_logger_calls(self, content: str) -> str:
        """Удаляет все вызовы логгера."""
        lines = content.split('\n')
        result = []
        skip_multiline = False
        paren_depth = 0
        
        for line in lines:
            # Проверяем начало вызова логгера
            if re.match(r'\s*(logger|main_logger)\.(debug|info|warning|error|critical|exception|section|success|failure)\(', line):
                # Считаем глубину скобок
                paren_depth = line.count('(') - line.count(')')
                if paren_depth > 0:
                    skip_multiline = True
                    continue
                else:
                    # Однострочный вызов - пропускаем
                    continue
            
            # Продолжаем пропускать строки многострочного вызова
            if skip_multiline:
                paren_depth += line.count('(') - line.count(')')
                if paren_depth <= 0:
                    skip_multiline = False
                continue
            
            result.append(line)
        
        return '\n'.join(result)
    
    def fix_inventory_sync_logic(self, content: str) -> str:
        """Исправляет логику в inventory.py - убирает пустые блоки после if."""
        
        # Находим проблемный блок и исправляем
        old_pattern = r'''if removed_from_inventory > 0:
            if self\.save_inventory\(inventory\):
            else:
                save_success = False
        else:
        if removed_from_parsed > 0:
            if self\.save_parsed_inventory\(parsed_inventory\):
            else:
                save_success = False
        else:'''
        
        new_code = '''if removed_from_inventory > 0:
            if not self.save_inventory(inventory):
                save_success = False
        
        if removed_from_parsed > 0:
            if not self.save_parsed_inventory(parsed_inventory):
                save_success = False'''
        
        content = re.sub(old_pattern, new_code, content, flags=re.MULTILINE)
        
        return content
    
    def fix_monitor_silent_checks(self, content: str) -> str:
        """Исправляет пустые проверки в monitor.py."""
        
        # Находим и удаляем пустые проверки
        patterns = [
            r'if check_count == 1 or check_count % MONITOR_STATUS_INTERVAL == 0:\s+timestamp = time\.strftime\(\'%H:%M:%S\'\)\s*\n',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content
    
    def fix_main_logging_calls(self, content: str) -> str:
        """Исправляет вызовы setup_logger в main.py."""
        
        # Удаляем строки с setup_logger
        patterns = [
            r'main_logger = setup_logger\([^)]*\)\s*\n',
            r'^\s*main_logger\..*\n',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content
    
    def remove_empty_conditionals(self, content: str) -> str:
        """Удаляет пустые условные блоки."""
        
        # Паттерны для пустых блоков
        patterns = [
            r'if .+:\s*\n\s*else:\s*\n',
            r'if .+:\s*\n\s*elif .+:\s*\n',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
        
        return content
    
    def cleanup_excessive_newlines(self, content: str) -> str:
        """Убирает лишние пустые строки (3+ подряд -> 2)."""
        return re.sub(r'\n\n\n+', '\n\n', content)
    
    def process_file(self, filepath: str) -> tuple[bool, list]:
        """Обрабатывает один файл."""
        issues = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original = content
            
            # Применяем все исправления
            content = self.remove_logger_imports(content)
            content = self.remove_logger_initialization(content)
            content = self.remove_logger_calls(content)
            
            # Специфичные исправления для файлов
            filename = os.path.basename(filepath)
            
            if filename == 'inventory.py':
                content = self.fix_inventory_sync_logic(content)
                issues.append("Исправлена логика sync_inventories")
            
            if filename == 'monitor.py':
                content = self.fix_monitor_silent_checks(content)
                issues.append("Удалены пустые проверки мониторинга")
            
            if filename == 'main.py':
                content = self.fix_main_logging_calls(content)
                issues.append("Удалены вызовы setup_logger")
            
            content = self.remove_empty_conditionals(content)
            content = self.cleanup_excessive_newlines(content)
            
            # Сохраняем только если были изменения
            if content != original:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True, issues
            else:
                return False, ["Изменений не требуется"]
            
        except Exception as e:
            return False, [f"Ошибка: {e}"]
    
    def analyze_code(self, filepath: str) -> list:
        """Анализирует код на наличие проблем."""
        issues = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Проверка на остатки логгера
            if re.search(r'from logger import', content):
                issues.append("❌ Найден импорт логгера")
            
            if re.search(r'\blogger\.|main_logger\.', content):
                issues.append("❌ Найдены вызовы логгера")
            
            # Проверка на пустые блоки
            if re.search(r'if .+:\s*\n\s*else:\s*\n', content):
                issues.append("⚠️  Найдены пустые условные блоки")
            
            # Проверка на лишние переносы
            if re.search(r'\n\n\n\n', content):
                issues.append("ℹ️  Найдены лишние пустые строки (4+)")
            
            return issues
            
        except Exception as e:
            return [f"Ошибка анализа: {e}"]


def main():
    print("=" * 70)
    print("ФИНАЛЬНАЯ ОЧИСТКА - Удаление логгера и исправление ошибок")
    print("=" * 70)
    print()
    
    # Файлы для обработки (только Python)
    files_to_process = [
        'auth.py',
        'blacklist.py',
        'boost.py',
        'card_replacement.py',
        'card_selector.py',
        'config.py',
        'daily_stats.py',
        'inventory.py',
        'main.py',
        'monitor.py',
        'owners_parser.py',
        'parsers.py',
        'proxy_manager.py',
        'rate_limiter.py',
        'trade.py',
        'utils.py',
    ]
    
    cleaner = CodeCleaner()
    
    print("📋 Фаза 1: Анализ кода")
    print("-" * 70)
    
    total_issues = 0
    files_with_issues = []
    
    for filename in files_to_process:
        if not os.path.exists(filename):
            print(f"⏭️  {filename:30} - файл не найден")
            continue
        
        issues = cleaner.analyze_code(filename)
        
        if issues:
            files_with_issues.append(filename)
            total_issues += len(issues)
            print(f"⚠️  {filename:30} - найдено проблем: {len(issues)}")
            for issue in issues:
                print(f"    {issue}")
        else:
            print(f"✅ {filename:30} - проблем не найдено")
    
    print()
    print(f"Всего найдено проблем: {total_issues} в {len(files_with_issues)} файлах")
    print()
    
    if not files_with_issues:
        print("🎉 Код чистый! Исправления не требуются.")
        return 0
    
    print("=" * 70)
    print()
    answer = input("Продолжить исправление? (y/n): ")
    
    if answer.lower() != 'y':
        print("Отменено пользователем")
        return 1
    
    print()
    print("📋 Фаза 2: Исправление")
    print("-" * 70)
    
    processed = 0
    modified = 0
    
    for filename in files_to_process:
        if not os.path.exists(filename):
            continue
        
        print(f"🔄 Обработка {filename}...", end=" ")
        
        success, issues = cleaner.process_file(filename)
        
        if success:
            modified += 1
            print(f"✅ Исправлен")
            for issue in issues:
                print(f"    {issue}")
        else:
            print(f"ℹ️  {issues[0]}")
        
        processed += 1
    
    print()
    print("=" * 70)
    print(f"Обработано файлов: {processed}")
    print(f"Изменено файлов: {modified}")
    print("=" * 70)
    print()
    
    # Финальная проверка
    print("📋 Фаза 3: Финальная проверка")
    print("-" * 70)
    
    remaining_issues = 0
    
    for filename in files_to_process:
        if not os.path.exists(filename):
            continue
        
        issues = cleaner.analyze_code(filename)
        
        if issues:
            remaining_issues += len(issues)
            print(f"⚠️  {filename:30} - осталось проблем: {len(issues)}")
            for issue in issues:
                print(f"    {issue}")
    
    print()
    
    if remaining_issues == 0:
        print("🎉 ВСЕ ПРОБЛЕМЫ ИСПРАВЛЕНЫ! Код чистый.")
        return 0
    else:
        print(f"⚠️  Осталось проблем: {remaining_issues}")
        print("Некоторые проблемы требуют ручного исправления.")
        return 1


if __name__ == '__main__':
    sys.exit(main())