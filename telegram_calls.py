#!/usr/bin/env python3
"""
Telegram Caller — Независимый скрипт для звонков через Telegram

Запуск:
    python telegram_calls.py

При первом запуске попросит ввести:
    - API ID и API Hash (получить на https://my.telegram.org)
    - Номер телефона для авторизации
    - Код подтверждения из Telegram

Далее можно вводить юзернеймы или ID пользователей для звонков.
"""

import asyncio
import hashlib
import os
import secrets
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

try:
    from telethon import TelegramClient, functions, types
    from telethon.errors import (
        SessionPasswordNeededError,
        PhoneCodeInvalidError,
        PhoneNumberInvalidError,
        FloodWaitError,
        UserPrivacyRestrictedError,
    )
except ImportError:
    print("❌ Telethon не установлен!")
    print("   Установите: pip install telethon")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════════════════════

SESSION_FILE = "caller_session"  # Имя файла сессии (без расширения)
DEFAULT_RING_DURATION = 5.0      # Длительность звонка по умолчанию (секунды)
CONFIG_FILE = "caller_config.txt"  # Файл для сохранения API credentials


# ═══════════════════════════════════════════════════════════════════════════════
# КЛАССЫ
# ═══════════════════════════════════════════════════════════════════════════════

class CallStatus(Enum):
    """Статусы звонка"""
    SUCCESS = "✅ Успешно"
    PRIVACY = "🔒 Приватность"
    NOT_FOUND = "❓ Не найден"
    FLOOD = "⏳ Flood wait"
    FAILED = "❌ Ошибка"


@dataclass
class CallResult:
    """Результат звонка"""
    username: str
    status: CallStatus
    message: str


class TelegramCaller:
    """Класс для совершения звонков через Telegram"""
    
    # Стандартные DH параметры Telegram
    DH_PRIME = int(
        "C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F"
        "48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543AED44CCE7C37"
        "20FD51F69458705AC68CD4FE6B6B13ABDC9746512969328454F18FAF8C595F64"
        "2477FE96BB2A941D5BCD1D4AC8CC49880708FA9B378E3C4F3A9060BEE67CF9A4"
        "A4A695811051907E162753B56B0F6B410DBA74D8A84B2A14B3144E0EF1284754"
        "FD17ED950D5965B4B9DD46582DB1178D169C6BC465B0D6FF9CA3928FEF5B9AE4"
        "E418FC15E83EBEA0F87FA9FF5EED70050DED2849F47BF959D956850CE929851F"
        "0D8115F635B105EE2E4E15D04B2454BF6F4FADF034B10403119CD8E3B92FCC5B",
        16
    )
    DH_GENERATOR = 3
    
    def __init__(self, api_id: int, api_hash: str, session_name: str = SESSION_FILE):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self.me = None
    
    async def connect(self) -> bool:
        """Подключение и авторизация"""
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            return await self._authorize()
        
        self.me = await self.client.get_me()
        return True
    
    async def _authorize(self) -> bool:
        """Процесс авторизации"""
        print("\n📱 Авторизация в Telegram")
        print("─" * 40)
        
        while True:
            phone = input("Введите номер телефона (с +): ").strip()
            if not phone:
                continue
            
            try:
                await self.client.send_code_request(phone)
                break
            except PhoneNumberInvalidError:
                print("❌ Неверный формат номера. Попробуйте снова.")
            except FloodWaitError as e:
                print(f"⏳ Слишком много попыток. Подождите {e.seconds} секунд.")
                return False
        
        while True:
            code = input("Введите код из Telegram: ").strip()
            if not code:
                continue
            
            try:
                await self.client.sign_in(phone, code)
                break
            except PhoneCodeInvalidError:
                print("❌ Неверный код. Попробуйте снова.")
            except SessionPasswordNeededError:
                # Двухфакторная аутентификация
                print("\n🔐 Требуется пароль двухфакторной аутентификации")
                password = input("Введите пароль: ").strip()
                try:
                    await self.client.sign_in(password=password)
                    break
                except Exception as e:
                    print(f"❌ Ошибка: {e}")
                    return False
        
        self.me = await self.client.get_me()
        return True
    
    def _generate_dh_params(self) -> tuple[bytes, int]:
        """Генерация параметров Diffie-Hellman"""
        private_key = secrets.randbits(256)
        g_a = pow(self.DH_GENERATOR, private_key, self.DH_PRIME)
        g_a_bytes = g_a.to_bytes(256, byteorder='big')
        g_a_hash = hashlib.sha256(g_a_bytes).digest()
        return g_a_hash, g_a
    
    async def call(
        self,
        username: str,
        duration: float = DEFAULT_RING_DURATION,
        message: Optional[str] = None
    ) -> CallResult:
        """
        Совершить звонок пользователю
        
        Args:
            username: Username или ID пользователя
            duration: Длительность звонка (секунды)
            message: Сообщение перед звонком (опционально)
        """
        # Нормализуем username
        target = username.strip()
        if target.startswith("@"):
            target = target[1:]
        
        try:
            # Получаем пользователя
            try:
                if target.isdigit():
                    user = await self.client.get_entity(int(target))
                else:
                    user = await self.client.get_entity(target)
            except ValueError:
                return CallResult(username, CallStatus.NOT_FOUND, "Пользователь не найден")
            
            user_display = f"@{user.username}" if user.username else f"ID:{user.id}"
            
            # Отправляем сообщение если указано
            if message:
                await self.client.send_message(user, message)
                await asyncio.sleep(0.3)
            
            # Генерируем параметры DH
            g_a_hash, _ = self._generate_dh_params()
            
            # Инициируем звонок
            result = await self.client(functions.phone.RequestCallRequest(
                user_id=user,
                g_a_hash=g_a_hash,
                protocol=types.PhoneCallProtocol(
                    min_layer=92,
                    max_layer=92,
                    library_versions=['5.0.0', '6.0.0'],
                    udp_p2p=True,
                    udp_reflector=True
                ),
                video=False,
                random_id=secrets.randbelow(2**31)
            ))
            
            phone_call = result.phone_call
            call_id = phone_call.id
            access_hash = phone_call.access_hash
            
            print(f"   📞 Звоню {user_display}...", end="", flush=True)
            
            # Ждём указанное время
            await asyncio.sleep(duration)
            
            # Сбрасываем звонок
            try:
                await self.client(functions.phone.DiscardCallRequest(
                    peer=types.InputPhoneCall(id=call_id, access_hash=access_hash),
                    duration=0,
                    reason=types.PhoneCallDiscardReasonHangup(),
                    connection_id=0
                ))
            except Exception:
                pass  # Игнорируем ошибки при сбросе
            
            print(f" ✅ ({duration:.1f}с)")
            return CallResult(username, CallStatus.SUCCESS, f"Звонок {duration:.1f}с")
            
        except UserPrivacyRestrictedError:
            print(f"   🔒 {username} — приватность запрещает звонки")
            return CallResult(username, CallStatus.PRIVACY, "Звонки запрещены настройками приватности")
            
        except FloodWaitError as e:
            print(f"   ⏳ Flood wait: {e.seconds}с")
            return CallResult(username, CallStatus.FLOOD, f"Подождите {e.seconds}с")
            
        except Exception as e:
            error_msg = str(e)
            if "PRIVACY" in error_msg.upper():
                print(f"   🔒 {username} — приватность")
                return CallResult(username, CallStatus.PRIVACY, "Звонки запрещены")
            print(f"   ❌ {username} — ошибка: {error_msg[:50]}")
            return CallResult(username, CallStatus.FAILED, error_msg)
    
    async def call_multiple(
        self,
        usernames: list[str],
        duration: float = DEFAULT_RING_DURATION,
        delay: float = 1.0
    ) -> list[CallResult]:
        """Звонок нескольким пользователям"""
        results = []
        for i, username in enumerate(usernames, 1):
            print(f"\n[{i}/{len(usernames)}] {username}")
            result = await self.call(username, duration)
            results.append(result)
            if i < len(usernames):
                await asyncio.sleep(delay)
        return results
    
    async def disconnect(self):
        """Отключение"""
        if self.client:
            await self.client.disconnect()


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def load_config() -> tuple[Optional[int], Optional[str]]:
    """Загрузка сохранённых API credentials"""
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                lines = f.read().strip().split('\n')
                if len(lines) >= 2:
                    return int(lines[0]), lines[1]
        except Exception:
            pass
    return None, None


def save_config(api_id: int, api_hash: str):
    """Сохранение API credentials"""
    with open(CONFIG_FILE, 'w') as f:
        f.write(f"{api_id}\n{api_hash}\n")


def print_banner():
    """Вывод баннера"""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                    📞 TELEGRAM CALLER                         ║
║                                                               ║
║  Звонки через Telegram для уведомлений                        ║
╚═══════════════════════════════════════════════════════════════╝
    """)


def print_help():
    """Справка по командам"""
    print("""
╭─────────────────────────────────────────────────────────────────╮
│                        📋 КОМАНДЫ                               │
├─────────────────────────────────────────────────────────────────┤
│  @username           Позвонить пользователю (5 сек)             │
│  @user1 @user2       Позвонить нескольким (через пробел)        │
│  123456789           Позвонить по ID                            │
│                                                                 │
│  /time 10            Установить длительность звонка (сек)       │
│  /msg Привет!        Установить сообщение перед звонком         │
│  /msg off            Отключить сообщение                        │
│  /me                 Показать текущий аккаунт                   │
│  /status             Показать настройки                         │
│  /help               Показать эту справку                       │
│  /quit               Выход                                      │
╰─────────────────────────────────────────────────────────────────╯
    """)


async def interactive_mode(caller: TelegramCaller):
    """Интерактивный режим"""
    
    # Текущие настройки
    ring_duration = DEFAULT_RING_DURATION
    pre_message: Optional[str] = None
    
    print(f"\n✅ Подключено как: @{caller.me.username} ({caller.me.first_name})")
    print(f"   ID: {caller.me.id}")
    print_help()
    
    while True:
        try:
            print()
            user_input = input("📞 > ").strip()
            
            if not user_input:
                continue
            
            # Команды
            if user_input.startswith("/"):
                cmd_parts = user_input.split(maxsplit=1)
                cmd = cmd_parts[0].lower()
                arg = cmd_parts[1] if len(cmd_parts) > 1 else ""
                
                if cmd in ("/quit", "/exit", "/q"):
                    print("\n👋 До свидания!")
                    break
                
                elif cmd == "/help":
                    print_help()
                
                elif cmd == "/me":
                    print(f"\n👤 Аккаунт: @{caller.me.username}")
                    print(f"   Имя: {caller.me.first_name} {caller.me.last_name or ''}")
                    print(f"   ID: {caller.me.id}")
                
                elif cmd == "/time":
                    if arg:
                        try:
                            ring_duration = float(arg)
                            print(f"⏱️  Длительность звонка: {ring_duration} сек")
                        except ValueError:
                            print("❌ Укажите число секунд")
                    else:
                        print(f"⏱️  Текущая длительность: {ring_duration} сек")
                
                elif cmd == "/msg":
                    if arg.lower() == "off":
                        pre_message = None
                        print("💬 Сообщение перед звонком: отключено")
                    elif arg:
                        pre_message = arg
                        print(f"💬 Сообщение перед звонком: \"{pre_message}\"")
                    else:
                        if pre_message:
                            print(f"💬 Текущее сообщение: \"{pre_message}\"")
                        else:
                            print("💬 Сообщение не установлено")
                
                elif cmd == "/status":
                    print(f"\n📊 Текущие настройки:")
                    print(f"   ⏱️  Длительность: {ring_duration} сек")
                    print(f"   💬 Сообщение: {pre_message or '(нет)'}")
                    print(f"   👤 Аккаунт: @{caller.me.username}")
                
                else:
                    print(f"❓ Неизвестная команда: {cmd}")
                    print("   Введите /help для справки")
                
                continue
            
            # Звонки
            # Парсим юзернеймы (разделённые пробелами или запятыми)
            usernames = []
            for part in user_input.replace(",", " ").split():
                part = part.strip()
                if part:
                    usernames.append(part)
            
            if not usernames:
                continue
            
            if len(usernames) == 1:
                await caller.call(usernames[0], ring_duration, pre_message)
            else:
                print(f"\n📞 Звоню {len(usernames)} пользователям...")
                await caller.call_multiple(usernames, ring_duration)
                print(f"\n✅ Завершено")
        
        except KeyboardInterrupt:
            print("\n\n👋 Прервано. До свидания!")
            break
        except EOFError:
            break


async def main():
    """Главная функция"""
    print_banner()
    
    # Пробуем загрузить сохранённые credentials
    api_id, api_hash = load_config()
    
    if not api_id or not api_hash:
        print("🔧 Первоначальная настройка")
        print("─" * 40)
        print("Получите API ID и API Hash на: https://my.telegram.org")
        print()
        
        while True:
            try:
                api_id_input = input("API ID: ").strip()
                api_id = int(api_id_input)
                break
            except ValueError:
                print("❌ API ID должен быть числом")
        
        api_hash = input("API Hash: ").strip()
        
        # Сохраняем для будущих запусков
        save_config(api_id, api_hash)
        print("✅ Credentials сохранены")
    
    # Создаём клиент
    caller = TelegramCaller(api_id, api_hash)
    
    try:
        print("\n🔄 Подключение к Telegram...")
        if not await caller.connect():
            print("❌ Не удалось подключиться")
            return
        
        # Запускаем интерактивный режим
        await interactive_mode(caller)
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
    finally:
        await caller.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
