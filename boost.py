"""Работа с буст-картами клуба с парсингом никнеймов."""

import re
import time
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, MAX_CLUB_CARD_OWNERS
from parsers import count_owners, count_wants
from inventory import get_user_inventory
from utils import extract_card_data
from logger import get_logger


logger = get_logger("boost")


class ClubMemberParser:
    """Парсер участников клуба с буст-картой."""
    
    def __init__(self, session: requests.Session):
        self.session = session
    
    def extract_user_id_from_avatar(self, avatar_element) -> Optional[str]:
        """Извлекает ID пользователя из элемента аватара."""
        # Сначала проверяем сам элемент
        if avatar_element.name == 'a' and avatar_element.has_attr('href'):
            href = avatar_element.get('href', '')
            match = re.search(r'/users/(\d+)', href)
            if match:
                return match.group(1)
        
        # Ищем ссылку внутри
        link = avatar_element.find('a', href=True)
        if link:
            href = link.get('href', '')
            match = re.search(r'/users/(\d+)', href)
            if match:
                return match.group(1)
        
        return None
    
    def get_user_nickname(self, user_id: str) -> Optional[str]:
        """
        🔧 НОВОЕ: Получает никнейм пользователя со страницы профиля.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Никнейм или None
        """
        url = f"{BASE_URL}/users/{user_id}"
        
        try:
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
    
    def parse_club_members_with_card(self, boost_url: str) -> List[Dict[str, str]]:
        """
        🔧 ОБНОВЛЕНО: Парсит участников клуба с получением nickname.
        
        Args:
            boost_url: URL страницы буста
        
        Returns:
            Список словарей {user_id: str, username: str}
        """
        if not boost_url.startswith("http"):
            boost_url = f"{BASE_URL}{boost_url}"
        
        try:
            response = self.session.get(boost_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка загрузки страницы буста: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем аватары в секции "Могут внести"
            avatar_selectors = [
                '.club-boost__owners-list .club-boost__avatar',
                '.club-boost__owners-list a[href*="/users/"]',
                '.club-boost__user a[href*="/users/"]'
            ]
            
            avatars = []
            for selector in avatar_selectors:
                found = soup.select(selector)
                if found:
                    avatars.extend(found)
                    logger.debug(f"Найдено {len(found)} аватаров по селектору: {selector}")
                    break
            
            if not avatars:
                logger.info("Участников клуба с этой картой не найдено")
                return []
            
            members = []
            seen_ids = set()
            
            for avatar in avatars:
                user_id = self.extract_user_id_from_avatar(avatar)
                
                if not user_id or user_id in seen_ids:
                    continue
                
                seen_ids.add(user_id)
                
                # 🔧 НОВОЕ: Получаем nickname
                nickname = self.get_user_nickname(user_id)
                
                if nickname:
                    members.append({
                        'user_id': user_id,
                        'username': nickname
                    })
                    logger.debug(f"Найден участник: {nickname} (ID: {user_id})")
                else:
                    # Если не удалось получить nickname - все равно добавляем
                    members.append({
                        'user_id': user_id,
                        'username': f'User{user_id}'
                    })
                    logger.warning(f"Nickname не получен, используем User{user_id}")
                
                # Небольшая задержка между запросами
                time.sleep(0.3)
            
            logger.info(f"Найдено участников клуба с картой: {len(members)}")
            return members
            
        except requests.RequestException as e:
            logger.error(f"Ошибка сети при парсинге участников: {e}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при парсинге участников: {e}")
            import traceback
            traceback.print_exc()
            return []


class BoostCardExtractor:
    """Извлечение информации о буст-карте."""
    
    def __init__(self, session: requests.Session):
        self.session = session
        self.member_parser = ClubMemberParser(session)
    
    def extract_card_id_from_button(self, soup: BeautifulSoup) -> Optional[str]:
        """Извлекает ID карты из кнопки."""
        card_link = soup.select_one('a.button.button--block[href*="/cards/"]')
        
        if not card_link:
            return None
        
        href = card_link.get("href", "")
        match = re.search(r"/cards/(\d+)", href)
        
        return match.group(1) if match else None
    
    def extract_card_image_from_boost_page(self, soup: BeautifulSoup) -> Optional[str]:
        """Извлекает URL изображения карты."""
        img_elem = soup.select_one('.club-boost__image img')
        
        if img_elem:
            img_src = img_elem.get('src', '')
            if img_src:
                if img_src.startswith('/'):
                    return f"{BASE_URL}{img_src}"
                return img_src
        
        return None
    
    def get_first_page_owners(self, card_id: str) -> List[str]:
        """Получает список владельцев с первой страницы."""
        url = f"{BASE_URL}/cards/{card_id}/users"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Не удалось загрузить страницу владельцев: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            owner_links = soup.select('.card-show__owner[href*="/users/"]')
            
            owner_ids = []
            for link in owner_links:
                href = link.get('href', '')
                match = re.search(r'/users/(\d+)', href)
                if match:
                    owner_ids.append(match.group(1))
            
            logger.debug(f"Найдено {len(owner_ids)} владельцев на первой странице")
            return owner_ids
            
        except Exception as e:
            logger.warning(f"Ошибка получения владельцев: {e}")
            return []
    
    def fetch_card_info_from_owner_inventory(
        self,
        card_id: str
    ) -> tuple[str, str, int]:
        """Получает информацию о карте из инвентаря владельца."""
        try:
            logger.info(f"🔍 Поиск информации о карте {card_id} через инвентарь владельца...")
            
            owner_ids = self.get_first_page_owners(card_id)
            
            if not owner_ids:
                logger.warning("Нет владельцев на первой странице")
                return "", "", 0
            
            last_owner_id = owner_ids[-1]
            logger.debug(f"Используем инвентарь владельца ID: {last_owner_id}")
            
            owner_cards = get_user_inventory(self.session, last_owner_id)
            
            if not owner_cards:
                logger.warning(f"Не удалось загрузить инвентарь владельца {last_owner_id}")
                return "", "", 0
            
            logger.debug(f"Загружено {len(owner_cards)} карт из инвентаря")
            
            for card in owner_cards:
                card_data = extract_card_data(card)
                
                if not card_data:
                    continue
                
                if card_data["card_id"] == int(card_id):
                    name = card_data["name"]
                    rank = card_data["rank"]
                    instance_id = card_data["instance_id"]
                    
                    logger.info(f"✅ Найдено: {name} | Ранг: {rank} | Instance: {instance_id}")
                    
                    return name, rank, instance_id
            
            logger.warning(f"Карта {card_id} не найдена в инвентаре владельца {last_owner_id}")
            return "", "", 0
            
        except Exception as e:
            logger.error(f"Ошибка получения информации из инвентаря: {e}")
            import traceback
            traceback.print_exc()
            return "", "", 0
    
    def get_card_info(self, boost_url: str) -> Optional[Dict[str, Any]]:
        """Получение информации о карте."""
        if not boost_url.startswith("http"):
            boost_url = f"{BASE_URL}{boost_url}"
        
        try:
            logger.debug(f"Загрузка страницы буста: {boost_url}")
            response = self.session.get(boost_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.error(f"Ошибка загрузки страницы буста: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            card_id = self.extract_card_id_from_button(soup)
            
            if not card_id:
                logger.error("Не удалось извлечь card_id из страницы буста")
                return None
            
            logger.info(f"📝 Card ID: {card_id}")
            
            image_url = self.extract_card_image_from_boost_page(soup)
            
            logger.info("📦 Получение информации из инвентаря владельца...")
            card_name, card_rank, instance_id = self.fetch_card_info_from_owner_inventory(card_id)
            
            if not card_name or not card_rank:
                logger.warning("⚠️ Не удалось получить название/ранг из инвентаря")
                card_name = card_name or "Неизвестная карта"
                card_rank = card_rank or "?"
            
            # Параллельная загрузка владельцев и желающих
            owners_count = 0
            wants_count = 0
            
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_owners = executor.submit(count_owners, self.session, card_id, False)
                    future_wanters = executor.submit(count_wants, self.session, card_id, False)
                    
                    owners_count = future_owners.result(timeout=15)
                    wants_count = future_wanters.result(timeout=15)
                    
            except TimeoutError:
                logger.warning("Таймаут при параллельной загрузке данных карты")
                owners_count = count_owners(self.session, card_id, force_accurate=False)
                wants_count = count_wants(self.session, card_id, force_accurate=False)
            except Exception as e:
                logger.warning(f"Ошибка параллельной загрузки: {e}")
                owners_count = count_owners(self.session, card_id, force_accurate=False)
                wants_count = count_wants(self.session, card_id, force_accurate=False)
            
            logger.info(f"📊 Владельцев: {owners_count} | Желающих: {wants_count}")
            
            needs_replacement = owners_count > 0 and owners_count <= MAX_CLUB_CARD_OWNERS
            
            # 🔧 ОБНОВЛЕНО: Парсим участников клуба с никнеймами
            logger.debug("Парсинг участников клуба...")
            club_members = self.member_parser.parse_club_members_with_card(boost_url)
            
            if club_members:
                logger.info(f"✅ Найдено участников клуба с картой: {len(club_members)}")
                for member in club_members:
                    logger.info(f"   {member['username']} (ID: {member['user_id']})")
            else:
                logger.info("ℹ️  Участников клуба с картой не найдено")
            
            logger.info(f"✅ Информация о карте собрана: {card_name} (Ранг: {card_rank})")
            
            return {
                "name": card_name,
                "id": instance_id,
                "card_id": int(card_id),
                "rank": card_rank,
                "wanters_count": wants_count,
                "owners_count": owners_count,
                "card_url": f"{BASE_URL}/cards/{card_id}/users",
                "timestamp": time.time(),
                "needs_replacement": needs_replacement,
                "club_members": club_members,  # 🔧 Теперь с username
                "image_url": image_url
            }
            
        except requests.RequestException as e:
            logger.error(f"Ошибка сети при получении информации о карте: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении информации о карте: {e}")
            import traceback
            traceback.print_exc()
            return None


def get_boost_card_info(
    session: requests.Session,
    boost_url: str
) -> Optional[Dict[str, Any]]:
    """Удобная функция для получения информации о буст-карте."""
    extractor = BoostCardExtractor(session)
    return extractor.get_card_info(boost_url)


def replace_club_card(session: requests.Session) -> bool:
    """Заменяет карту в клубе через API."""
    url = f"{BASE_URL}/clubs/replace"
    csrf_token = session.headers.get('X-CSRF-TOKEN', '')
    
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-CSRF-Token": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": session.url if hasattr(session, 'url') else BASE_URL,
        "Origin": BASE_URL,
    }
    
    try:
        response = session.post(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        return response.status_code == 200
        
    except requests.RequestException:
        return False


def format_club_members_info(members: List[Dict[str, str]]) -> str:
    """
    🔧 ОБНОВЛЕНО: Форматирует информацию об участниках с никами.
    
    Args:
        members: Список словарей с user_id и username
    
    Returns:
        Отформатированная строка
    """
    if not members:
        return "В клубе ни у кого нет"
    
    if len(members) == 1:
        return f"В клубе имеется у: {members[0]['username']}"
    
    usernames = [m['username'] for m in members]
    return f"В клубе имеется у: {', '.join(usernames)}"