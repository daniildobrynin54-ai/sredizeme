#!/usr/bin/env python3
"""
Финальный скрипт для копирования оставшихся файлов с удалением логгера.
Скопируйте содержимое оригинальных файлов и запустите этот скрипт.
"""

import re
import os

def remove_logger_completely(content):
    """Полностью удаляет все следы логгера из кода."""
    
    # 1. Удаляем импорты
    content = re.sub(r'^from logger import .*$\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^import logger.*$\n?', '', content, flags=re.MULTILINE)
    
    # 2. Удаляем создание логгера
    content = re.sub(r'^logger = get_logger\(.*\)$\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^main_logger = setup_logger\(.*\)$\n?', '', content, flags=re.MULTILINE)
    
    # 3. Удаляем однострочные вызовы
    patterns = [
        r'^\s*logger\.debug\([^)]*\)\s*$\n?',
        r'^\s*logger\.info\([^)]*\)\s*$\n?',
        r'^\s*logger\.warning\([^)]*\)\s*$\n?',
        r'^\s*logger\.error\([^)]*\)\s*$\n?',
        r'^\s*logger\.critical\([^)]*\)\s*$\n?',
        r'^\s*logger\.exception\([^)]*\)\s*$\n?',
        r'^\s*logger\.section\([^)]*\)\s*$\n?',
        r'^\s*logger\.success\([^)]*\)\s*$\n?',
        r'^\s*logger\.failure\([^)]*\)\s*$\n?',
        r'^\s*main_logger\..*\([^)]*\)\s*$\n?',
    ]
    
    for pattern in patterns:
        content = re.sub(pattern, '', content, flags=re.MULTILINE)
    
    # 4. Удаляем многострочные вызовы (сложнее)
    lines = content.split('\n')
    result = []
    skip_logger_call = False
    paren_depth = 0
    
    for line in lines:
        # Проверяем начало вызова логгера
        if re.match(r'\s*(logger|main_logger)\.(debug|info|warning|error|critical|exception|section|success|failure)\(', line):
            # Считаем глубину скобок
            paren_depth = line.count('(') - line.count(')')
            if paren_depth > 0:
                skip_logger_call = True
                continue
            else:
                # Однострочный вызов - пропускаем
                continue
        
        # Продолжаем пропускать строки многострочного вызова
        if skip_logger_call:
            paren_depth += line.count('(') - line.count(')')
            if paren_depth <= 0:
                skip_logger_call = False
            continue
        
        result.append(line)
    
    content = '\n'.join(result)
    
    # 5. Убираем лишние пустые строки (3+ подряд)
    content = re.sub(r'\n\n\n+', '\n\n', content)
    
    return content

def process_file(source_path, dest_path):
    """Обрабатывает один файл."""
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        clean_content = remove_logger_completely(content)
        
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        return True
    except Exception as e:
        print(f"❌ Ошибка обработки {source_path}: {e}")
        return False

def main():
    print("="  * 60)
    print("ФИНАЛЬНАЯ ОЧИСТКА - Удаление логгера из оставшихся файлов")
    print("=" * 60)
    print()
    
    # ИНСТРУКЦИЯ:
    # 1. Скопируйте оригинальные файлы в эту директорию
    # 2. Запустите скрипт: python finish_cleanup.py
    # 3. Файлы будут обработаны и очищены от логгера
    
    files_to_process = [
        'card_selector.py',
        'daily_stats.py',
        'inventory.py',
        'main.py',
        'monitor.py',
        'owners_parser.py',
        'proxy_manager.py',
        'rate_limiter.py',
        'trade.py'
    ]
    
    processed = 0
    skipped = 0
    
    for filename in files_to_process:
        if os.path.exists(filename):
            print(f"🔄 Обработка {filename}...")
            if process_file(filename, filename):
                processed += 1
                print(f"✅ {filename} - логгер удален")
            else:
                print(f"❌ {filename} - ошибка")
        else:
            print(f"⏭️  {filename} - файл не найден (скопируйте из оригинала)")
            skipped += 1
    
    print()
    print("=" * 60)
    print(f"Обработано: {processed}")
    print(f"Пропущено: {skipped}")
    print("=" * 60)
    
    if skipped > 0:
        print()
        print("⚠️  Некоторые файлы отсутствуют.")
        print("Скопируйте их из оригинальных документов и запустите скрипт снова.")

if __name__ == '__main__':
    main()
