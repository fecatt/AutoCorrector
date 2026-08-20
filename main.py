"""
AutoCorrector — автоисправление текста через OpenRouter API.

Выделите текст в любом приложении → нажмите комбинацию клавиш →
программа скопирует текст, отправит на коррекцию и вставит исправленный
обратно.

Конфигурация хранится в config.yaml рядом со скриптом.
"""

__version__ = "1.0.0"

import os
import re
import sys
import signal
import time
import logging
import threading
import traceback
import ctypes
import ctypes.wintypes
import argparse
import winreg
from pathlib import Path

# Исправляем кодировку консоли Windows (cp1251 → utf-8)
# чтобы emoji и кириллица в print() не вызывали UnicodeEncodeError
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# =========================
# ПРОВЕРКА ЗАВИСИМОСТЕЙ
# =========================

_missing: list[str] = []
try:
    import requests  # noqa: F401
except ImportError:
    _missing.append("requests")
try:
    import yaml  # noqa: F401
except ImportError:
    _missing.append("pyyaml")
try:
    import pyperclip  # noqa: F401
except ImportError:
    _missing.append("pyperclip")
try:
    from win11toast import toast  # noqa: F401
except ImportError:
    _missing.append("win11toast")
# pysocks импортируется лениво — только при использовании SOCKS-прокси
socks = None

if _missing:
    print("Отсутствуют библиотеки: " + ", ".join(_missing))
    print("Попытка автоматической установки...")
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *_missing],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("Зависимости успешно установлены!")
        print("Пожалуйста, перезапустите программу.")
    except Exception as exc:
        print(
            "Не удалось установить зависимости автоматически.\n"
            f"Ошибка: {exc}\n\n"
            "Установите вручную:\n  pip install " + " ".join(_missing)
        )
        sys.exit(1)
    sys.exit(0)

# =========================
# КОНФИГУРАЦИЯ
# =========================

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _load_config() -> dict:
    """Загружает config.yaml рядом со скриптом и возвращает словарь."""
    if not CONFIG_PATH.exists():
        print(f"Файл конфигурации не найден: {CONFIG_PATH}")
        sys.exit(1)

    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        print(f"ОШИБКА: Не удалось распарсить config.yaml.\n  {exc}")
        sys.exit(1)
    if not isinstance(cfg, dict):
        print("ОШИБКА: config.yaml должен содержать словарь на верхнем уровне.")
        sys.exit(1)

    # Валидация обязательных полей
    api_cfg = cfg.get("api", {})
    if not api_cfg.get("key"):
        print("ОШИБКА: API ключ не задан. Откройте config.yaml и укажите поле api.key.")
        sys.exit(1)

    return cfg


_CFG = _load_config()

# ── Валидация конфигурации ────────────────────────────────────
def _validate_config(cfg: dict) -> None:
    """Проверяет корректность значений в конфигурации."""
    api_cfg = cfg.get("api", {})

    # Проверка API URL — только HTTPS
    url = api_cfg.get("url", "https://openrouter.ai/api/v1/chat/completions")
    if not url.startswith("https://"):
        print(
            f"ОШИБКА: API URL должен использовать HTTPS.\n"
            f"  Текущее значение: {url}\n"
            f"  Исправьте api.url в config.yaml."
        )
        sys.exit(1)

    # Проверка temperature — допустимый диапазон [0, 2]
    temp = api_cfg.get("temperature", 0)
    if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
        print(
            f"ОШИБКА: Температура должна быть числом от 0 до 2.\n"
            f"  Текущее значение: {temp}\n"
            f"  Исправьте api.temperature в config.yaml."
        )
        sys.exit(1)

    # Проверка timeout — положительное число
    timeout = api_cfg.get("timeout", 60)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        print(
            f"ОШИБКА: Таймаут должен быть положительным числом.\n"
            f"  Текущее значение: {timeout}\n"
            f"  Исправьте api.timeout в config.yaml."
        )
        sys.exit(1)

    # Проверка limits
    limits = cfg.get("limits", {})
    max_text = limits.get("max_text_length", 8000)
    if not isinstance(max_text, int) or max_text <= 0:
        print(
            f"ОШИБКА: max_text_length должен быть положительным целым числом.\n"
            f"  Текущее значение: {max_text}\n"
            f"  Исправьте limits.max_text_length в config.yaml."
        )
        sys.exit(1)

    max_retries = limits.get("max_retries", 3)
    if not isinstance(max_retries, int) or max_retries <= 0:
        print(
            f"ОШИБКА: max_retries должен быть положительным целым числом.\n"
            f"  Текущее значение: {max_retries}\n"
            f"  Исправьте limits.max_retries в config.yaml."
        )
        sys.exit(1)

    # Проверка proxy — если задан, должен быть валидным URL
    proxy = api_cfg.get("proxy", "")
    if proxy and not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
        print(
            f"ОШИБКА: Прокси-сервер должен начинаться с http://, https://, socks4:// или socks5://.\n"
            f"  Текущее значение: {proxy}\n"
            f"  Исправьте api.proxy в config.yaml."
        )
        sys.exit(1)

    # Проверка API ключа — уже выполнена в _load_config()
    # (дополнительная проверка на неполный ключ)
    key = api_cfg.get("key", "")
    if key.startswith("sk-or-v1-") and len(key) < 20:
        print("ОШИБКА: API ключ выглядит неполным. Проверьте значение api.key в config.yaml.")
        sys.exit(1)


_validate_config(_CFG)

# ── Глобальные настройки API (defaults) ──────────────────────
OPENROUTER_API_KEY: str = _CFG["api"]["key"]
API_URL: str = _CFG["api"].get("url", "https://openrouter.ai/api/v1/chat/completions")
API_MODEL: str = _CFG["api"].get("model", "google/gemma-4-31b-it")
API_TEMPERATURE: float = _CFG["api"].get("temperature", 0)
API_TIMEOUT: int = _CFG["api"].get("timeout", 60)
API_PROXY: str = _CFG["api"].get("proxy", "")
API_SYSTEM_PROMPT: str = _CFG["api"].get("system_prompt", (
    "You are a professional text proofreader and editor. "
    "Correct spelling, punctuation, grammar, and style errors in the text. "
    "Preserve the original meaning, tone, and structure. "
    "Do not add any explanations or commentary. "
    "Return only the corrected text."
))

MAX_TEXT_LENGTH: int = _CFG.get("limits", {}).get("max_text_length", 8000)
MAX_RETRIES: int = _CFG.get("limits", {}).get("max_retries", 3)

_log_cfg = _CFG.get("logging", {})
LOG_LEVEL: str = _log_cfg.get("level", "INFO")
LOG_FILE: str | None = _log_cfg.get("file")

# ── Уведомления ─────────────────────────────────────────────
# Отключать можно только информационные (системные) уведомления.
# Уведомления об ошибках и предупреждениях показываются всегда.
_notif_cfg = _CFG.get("notifications", {})

# Каждый тип информационного уведомления — отдельный флаг
NOTIF_CATEGORIES: dict[str, bool] = {
    "on_startup":          _notif_cfg.get("on_startup", True),
    "on_processing_start": _notif_cfg.get("on_processing_start", True),
    "on_success":          _notif_cfg.get("on_success", True),
    "on_no_changes":       _notif_cfg.get("on_no_changes", True),
}


def _is_notification_enabled(category: str) -> bool:
    """Проверяет, включены ли уведомления заданной категории.
    Ошибки и предупреждения всегда включены — категория не проверяется."""
    return NOTIF_CATEGORIES.get(category, True)

# ── Горячие клавиши ─────────────────────────────────────────
# Каждая горячая клавиша — dict с полями:
#   name, ctrl, alt, shift, win, key,
#   model (opt), temperature (opt), system_prompt (opt), max_text_length (opt)

def _parse_hotkeys() -> list[dict]:
    """
    Читает список hotkeys из конфига.
    Если hotkeys нет — создаёт одну запись из старого формата hotkey.
    """
    raw = _CFG.get("hotkeys")
    if raw and isinstance(raw, (list, dict)):
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    # Обратная совместимость: старый формат single hotkey
    old = _CFG.get("hotkey", {})
    return [{
        "name": "Коррекция",
        "ctrl": old.get("ctrl", True),
        "alt": old.get("alt", True),
        "shift": old.get("shift", False),
        "win": old.get("win", False),
        "key": old.get("key", "g"),
    }]


def _merge_hotkey(hk: dict) -> dict:
    """
    Объединяет настройки горячей клавиши с глобальными defaults.
    Возвращает полный конфиг для конкретной комбинации.
    Выбрасывает ValueError при отсутствии обязательного поля 'key'.
    """
    if not hk.get("key", "").strip():
        raise ValueError(
            f"Горячая клавиша [{hk.get('name', '?')}] не имеет поля 'key'. "
            f"Укажите ключ в config.yaml."
        )

    merged = {
        "model": hk.get("model", API_MODEL),
        "temperature": hk.get("temperature", API_TEMPERATURE),
        "system_prompt": hk.get("system_prompt", API_SYSTEM_PROMPT),
        "max_text_length": hk.get("max_text_length", MAX_TEXT_LENGTH),
        "max_retries": hk.get("max_retries", MAX_RETRIES),
        "name": hk.get("name", hk.get("key", "?")),
        "ctrl": hk.get("ctrl", False),
        "alt": hk.get("alt", False),
        "shift": hk.get("shift", False),
        "win": hk.get("win", False),
        "key": hk.get("key", "").strip(),
    }

    # Валидация переопределённых значений
    temp = merged["temperature"]
    if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
        raise ValueError(
            f"Горячая клавиша [{merged['name']}]: temperature={temp} вне диапазона [0, 2]"
        )
    mtl = merged["max_text_length"]
    if not isinstance(mtl, int) or mtl <= 0:
        raise ValueError(
            f"Горячая клавиша [{merged['name']}]: max_text_length={mtl} должно быть положительным целым"
        )
    mr = merged["max_retries"]
    if not isinstance(mr, int) or mr <= 0:
        raise ValueError(
            f"Горячая клавиша [{merged['name']}]: max_retries={mr} должно быть положительным целым"
        )

    return merged


try:
    HOTKEYS: list[dict] = [_merge_hotkey(h) for h in _parse_hotkeys()]
except ValueError as exc:
    print(f"ОШИБКА: {exc}")
    sys.exit(1)

# =========================
# ЛОГИРОВАНИЕ
# =========================

_handlers: list[logging.Handler] = [logging.StreamHandler()]
if LOG_FILE:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("autocorrector")

# =========================
# WINDOWS API
# =========================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_COPY    = 0x0301
WM_PASTE   = 0x0302
WM_COMMAND = 0x0111
IDM_COPY   = 0xE122
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

VK_CONTROL = 0x11
VK_MENU    = 0x12
VK_C       = 0x43
VK_V       = 0x56
VK_INSERT  = 0x2D

# Константы для RegisterHotKey
MOD_ALT     = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT   = 0x0004
MOD_WIN     = 0x0008
WM_HOTKEY   = 0x0312

# Константы для работы с буфером обмена
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Регистрируем специальный формат, запрещающий сохранение в историю
CanIncludeInClipboardHistory = user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
# Дополнительный формат для исключения из мониторинга (опционально)
ExcludeClipboardContentFromMonitorProcessing = user32.RegisterClipboardFormatW(
    "ExcludeClipboardContentFromMonitorProcessing"
)


class GUITHREADINFO(ctypes.Structure):
    """Структура Windows для получения информации о фокусе потока."""
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("flags",         ctypes.c_uint),
        ("hwndActive",    ctypes.wintypes.HWND),
        ("hwndFocus",     ctypes.wintypes.HWND),
        ("hwndCapture",   ctypes.wintypes.HWND),
        ("hwndMenuOwner", ctypes.wintypes.HWND),
        ("hwndMoveSize",  ctypes.wintypes.HWND),
        ("hwndCaret",     ctypes.wintypes.HWND),
        ("rcCaret",       ctypes.wintypes.RECT),
    ]


class MSG(ctypes.Structure):
    """Структура MSG для GetMessage."""
    _fields_ = [
        ("hwnd",   ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time",   ctypes.wintypes.DWORD),
        ("pt",     ctypes.wintypes.POINT),
    ]


# =========================
# СООБЩЕНИЯ ОТ WINDOWS (WinRT toast-уведомления)
# =========================

def notify_error(title: str, text: str) -> None:
    """Показать уведомление об ошибке (с звуком). Всегда показывается."""
    log.error("%s: %s", title, text)
    try:
        toast(title, text, app_id="AutoCorrector", audio="ms-winsoundevent:Notification.Looping.Alarm")
    except Exception as e:
        log.debug("Не удалось показать уведомление: %s", e)


def notify_warning(title: str, text: str) -> None:
    """Показать предупреждение (с звуком). Всегда показывается."""
    log.warning("%s: %s", title, text)
    try:
        toast(title, text, app_id="AutoCorrector", audio="ms-winsoundevent:Notification.Default")
    except Exception as e:
        log.debug("Не удалось показать уведомление: %s", e)


def notify_info(title: str, text: str, category: str = "") -> None:
    """Показать информационное уведомление (без звука).
    category — ключ из notifications.* для отдельного отключения."""
    log.info("%s: %s", title, text)
    if category and not _is_notification_enabled(category):
        return
    try:
        toast(title, text, app_id="AutoCorrector")
    except Exception as e:
        log.debug("Не удалось показать уведомление: %s", e)


# =========================
# УСТАНОВКА БУФЕРА БЕЗ ИСТОРИИ
# =========================

def _set_clipboard_raw(format_id: int, data: bytes) -> bool:
    """
    Выделяет память GlobalAlloc, заполняет data и передаёт в SetClipboardData.
    При успехе Windows берёт владение памятью (GlobalFree вызывать НЕЛЬЗЯ).
    При неудаче — память освобождается здесь.
    Возвращает True при успехе.
    """
    if format_id == 0:
        return False
    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h_mem:
        return False
    ptr = kernel32.GlobalLock(h_mem)
    if not ptr:
        kernel32.GlobalFree(h_mem)
        return False
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(h_mem)
    if not user32.SetClipboardData(format_id, h_mem):
        kernel32.GlobalFree(h_mem)
        return False
    # SetClipboardData succeeded — Windows owns h_mem, no GlobalFree
    return True


def set_clipboard_no_history(text: str) -> bool:
    """
    Устанавливает текст в буфер обмена с флагом, запрещающим сохранение в историю (Win+V).
    Возвращает True при успехе, иначе False.
    """
    if not user32.OpenClipboard(0):
        log.debug("Не удалось открыть буфер обмена")
        return False

    try:
        user32.EmptyClipboard()

        # Основной текст (UTF-16 LE, нуль-терминированный)
        wide = text.encode('utf-16le') + b'\x00\x00'
        if not _set_clipboard_raw(CF_UNICODETEXT, wide):
            log.debug("SetClipboardData (CF_UNICODETEXT) failed")
            return False

        # Флаги «не сохранять в историю»
        if CanIncludeInClipboardHistory == 0 or ExcludeClipboardContentFromMonitorProcessing == 0:
            log.warning(
                "Не удалось зарегистрировать форматы для запрета истории "
                "(CanIncludeInClipboardHistory=%d, ExcludeClipboardContentFromMonitorProcessing=%d), "
                "работаем без флагов",
                CanIncludeInClipboardHistory,
                ExcludeClipboardContentFromMonitorProcessing,
            )
        else:
            # CanIncludeInClipboardHistory = DWORD 0 (4 нуля)
            _set_clipboard_raw(CanIncludeInClipboardHistory, b'\x00\x00\x00\x00')
            # ExcludeClipboardContentFromMonitorProcessing = 1 байт
            _set_clipboard_raw(
                ExcludeClipboardContentFromMonitorProcessing,
                b'\x00',
            )

        return True

    except Exception as e:
        log.debug("Ошибка при установке буфера: %s", e)
        return False
    finally:
        user32.CloseClipboard()


# =========================
# ПРИМИТИВЫ КЛАВИАТУРЫ
# =========================

def _key_down(vk: int) -> None:
    """Нажать клавишу (hardware-level)."""
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)


def _key_up(vk: int) -> None:
    """Отпустить клавишу (hardware-level)."""
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def _ctrl_key(vk: int) -> None:
    """Нажать Ctrl + vk (комбинация)."""
    _key_down(VK_CONTROL)
    time.sleep(0.03)
    _key_down(vk)
    time.sleep(0.03)
    _key_up(vk)
    time.sleep(0.03)
    _key_up(VK_CONTROL)


# =========================
# БУФЕР ОБМЕНА (чтение)
# =========================

def _get_clip(retries: int = 3, delay: float = 0.1) -> str:
    """
    Возвращает содержимое системного буфера обмена.
    Делает retries попыток с паузой delay секунд между ними.
    """
    for attempt in range(1, retries + 1):
        try:
            val = pyperclip.paste()
            if val:  # не пустая строка
                return val
        except Exception as exc:
            log.debug("Буфер обмена (попытка %d/%d): %s", attempt, retries, exc)
        time.sleep(delay)
    return ""


# =========================
# ФОКУС ОКНА
# =========================

SW_RESTORE  = 9
SW_SHOW     = 5


def _bring_to_front(hwnd: int) -> bool:
    """Активирует окно hwnd без изменения позиции и размера."""
    if not hwnd:
        return False

    # Если окно свёрнуто — сначала разворачиваем
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)

    # Способ 1: AttachThreadInput + SetForegroundWindow
    try:
        cur_tid = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        attached = fg_tid != cur_tid
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            return True
    except Exception as e:
        log.debug("_bring_to_front (AttachThreadInput+SetForegroundWindow): %s", e)

    # Способ 2: Alt trick
    try:
        _key_down(VK_MENU)
        time.sleep(0.01)
        _key_up(VK_MENU)
        time.sleep(0.03)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            return True
    except Exception as e:
        log.debug("_bring_to_front (Alt trick): %s", e)

    return False


def _get_focused_control(hwnd: int) -> int:
    """Возвращает HWND контрола с фокусом внутри hwnd."""
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    gui = GUITHREADINFO()
    gui.cbSize = ctypes.sizeof(GUITHREADINFO)
    if user32.GetGUIThreadInfo(tid, ctypes.byref(gui)) and gui.hwndFocus:
        return gui.hwndFocus
    return hwnd


# =========================
# КОПИРОВАНИЕ ВЫДЕЛЕНИЯ
# =========================

def copy_selected(hwnd: int) -> str:
    """Копирует выделенный текст из окна hwnd."""
    if not hwnd:
        log.error("Некорректный дескриптор окна (hwnd=%s)", hwnd)
        return ""

    old_clip = _get_clip()
    target = _get_focused_control(hwnd)

    # 1) WM_COPY
    user32.SendMessageW(target, WM_COPY, 0, 0)
    time.sleep(0.25)
    new_clip = _get_clip()
    if new_clip and new_clip.strip() and new_clip != old_clip:
        log.info("Копия: WM_COPY")
        return new_clip

    # 2) WM_COMMAND + IDM_COPY
    user32.PostMessageW(target, WM_COMMAND, IDM_COPY, 0)
    time.sleep(0.25)
    new_clip = _get_clip()
    if new_clip and new_clip.strip() and new_clip != old_clip:
        log.info("Копия: WM_COMMAND")
        return new_clip

    # 3) Ctrl+C
    log.info("WM не сработали, пробую Ctrl+C...")
    if _bring_to_front(hwnd):
        for attempt in range(1, 3):
            time.sleep(0.15)
            _ctrl_key(VK_C)
            time.sleep(0.3)
            new_clip = _get_clip()
            if new_clip and new_clip.strip() and new_clip != old_clip:
                log.info("Копия: Ctrl+C (попытка %d)", attempt)
                return new_clip

    # 4) Ctrl+Insert
    log.info("Пробую Ctrl+Insert...")
    if _bring_to_front(hwnd):
        time.sleep(0.15)
        _ctrl_key(VK_INSERT)
        time.sleep(0.3)
        new_clip = _get_clip()
        if new_clip and new_clip.strip() and new_clip != old_clip:
            log.info("Копия: Ctrl+Insert")
            return new_clip

    log.warning("Не удалось скопировать выделенный текст")
    return ""


# =========================
# ВСТАВКА
# =========================

def paste_to(hwnd: int) -> None:
    """Вставляет текст из буфера обмена в окно hwnd.

    Используем только Ctrl+V — универсальный способ для большинства приложений.
    WM_PASTE не используется, т.к. он может не работать в нестандартных контролах,
    а совместное использование WM_PASTE + Ctrl+V приводит к двойной вставке.
    """
    time.sleep(0.15)
    try:
        if _bring_to_front(hwnd):
            time.sleep(0.15)
            _ctrl_key(VK_V)
            time.sleep(0.25)
    except Exception as e:
        log.debug("Ошибка вставки: %s", e)


# =========================
# API: КОРРЕКЦИЯ ТЕКСТА
# =========================

def correct_text(
    text: str,
    *,
    model: str = API_MODEL,
    system_prompt: str = API_SYSTEM_PROMPT,
    temperature: float = API_TEMPERATURE,
    max_retries: int = MAX_RETRIES,
) -> str:
    """Отправляет текст на коррекцию через OpenRouter API."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": temperature,
    }

    log.info("API: модель=%s, длина=%d, температура=%.2f", model, len(text), temperature)

    for attempt in range(1, max_retries + 1):
        try:
            proxies = None
            if API_PROXY:
                if API_PROXY.startswith(("socks4://", "socks5://")):
                    global socks
                    if socks is None:
                        try:
                            import socks as _socks
                            socks = _socks
                        except ImportError:
                            raise ImportError(
                                "Для работы через SOCKS-прокси необходима библиотека pysocks.\n"
                                "Установите: pip install pysocks"
                            )
                proxies = {"https": API_PROXY, "http": API_PROXY}
            response = requests.post(
                API_URL, headers=headers, json=data, timeout=API_TIMEOUT,
                verify=True,  # Принудительная проверка SSL-сертификата
                proxies=proxies,
            )
            response.raise_for_status()
            result = response.json()

            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content")
            )
            if content is None:
                raise ValueError("API вернул пустой ответ (content=None)")

            return content.strip()

        except Exception as exc:
            log.warning(
                "Ошибка API (попытка %d/%d): %s", attempt, max_retries, exc,
            )
            if attempt == max_retries:
                raise
            time.sleep(2 ** attempt)

    raise RuntimeError("Не удалось получить ответ от API")


# =========================
# ГЛАВНАЯ ЛОГИКА
# =========================

_processing = False
_processing_lock = threading.Lock()


def fix_selected_text(hwnd: int, hk_cfg: dict) -> None:
    """
    Исправляет выделенный текст.

    hk_cfg — полный конфиг горячей клавиши (model, system_prompt,
    temperature, max_text_length и т.д.).
    """
    global _processing

    with _processing_lock:
        if _processing:
            log.info("Уже идёт обработка, пропускаю")
            return
        _processing = True
        # Сохраняем исходный буфер — только если это текст (CF_UNICODETEXT)
        initial_clip = ""
        try:
            if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                initial_clip = pyperclip.paste()
        except Exception as e:
            log.warning("Не удалось сохранить буфер обмена: %s", e)
            initial_clip = ""

    hk_limit = hk_cfg.get("max_text_length", MAX_TEXT_LENGTH)

    try:
        hk_name = hk_cfg.get("name", "?")
        log.info(">>> Коррекция [%s] (HWND=%s)", hk_name, hwnd)
        notify_info(
            "⚙️ Коррекция текста",
            f"Обработка [{hk_name}]…\nПодождите, пока текст будет исправлен.",
            category="on_processing_start",
        )

        text = copy_selected(hwnd)
        if not text:
            notify_error(
                "❌ Не удалось скопировать текст",
                "Не удалось скопировать выделенный текст.\n"
                "Убедитесь, что текст выделен, и попробуйте снова.",
            )
            return

        # Пустой или пробельный текст — не отправляем в API
        if not text.strip():
            log.info("Выделенный текст пуст или содержит только пробелы, пропускаю")
            return

        # Проверка лимита символов — текст НЕ отправляется, если превышен
        if len(text) > hk_limit:
            notify_warning(
                "⚠️ Превышен лимит текста",
                f"Выделенный текст: {len(text)} символов.\n"
                f"Допустимый лимит: {hk_limit} символов.\n\n"
                f"Сообщение не отправлено в API.\n"
                f"Сократите текст и попробуйте снова.",
            )
            return

        log.info("Текст (%d символов): %.20s", len(text), text)

        try:
            corrected = correct_text(
                text,
                model=hk_cfg["model"],
                system_prompt=hk_cfg["system_prompt"],
                temperature=hk_cfg["temperature"],
                max_retries=hk_cfg.get("max_retries", MAX_RETRIES),
            )
        except Exception as exc:
            # Полный текст ошибки — в лог (для диагностики)
            log.error("Полная ошибка API: %s", exc)
            # Санитизация: не раскрываем внутренние детали пользователю
            safe_msg = str(exc)
            safe_msg = re.sub(r'https?://\S+', '[URL]', safe_msg)
            safe_msg = re.sub(r'[A-Za-z]:\\[^\s"\']+', '[path]', safe_msg)
            safe_msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[ip]', safe_msg)
            notify_error(
                "❌ Ошибка при обращении к API",
                f"Не удалось получить ответ от API.\n\n"
                f"Ошибка: {safe_msg}\n\n"
                f"Проверьте подключение к интернету и настройки API в config.yaml.",
            )
            return

        if not corrected:
            notify_warning(
                "⚠️ Пустой ответ от API",
                "API вернул пустой текст. Вставка не выполняется.",
            )
            return

        if corrected.strip() == text.strip():
            notify_info(
                "✅ Текст без ошибок",
                "Текст не содержит ошибок — вставка не требуется.",
                category="on_no_changes",
            )
            return

        log.info("Исправлено (%d символов): %.20s", len(corrected), corrected)

        # Устанавливаем исправленный текст в буфер БЕЗ сохранения в историю
        if not set_clipboard_no_history(corrected):
            notify_error(
                "❌ Ошибка буфера обмена",
                "Не удалось установить исправленный текст в буфер обмена.",
            )
            return
        time.sleep(0.15)
        paste_to(hwnd)
        log.info(">>> Готово")
        notify_info(
            "✅ Текст исправлен",
            f"Исправлено: {len(corrected) - len(text):+d} символов\n"
            f"Исправленный текст вставлен в окно.",
            category="on_success",
        )

    finally:
        # Восстанавливаем исходный буфер (только если он был текстовым)
        if initial_clip:
            if not set_clipboard_no_history(initial_clip):
                log.warning("Не удалось восстановить буфер без истории, пробую обычный способ")
                try:
                    pyperclip.copy(initial_clip)
                except Exception as e:
                    log.error("Не удалось восстановить буфер обмена вообще: %s", e)
        with _processing_lock:
            _processing = False


# =========================
# ГОРЯЧАЯ КЛАВИША (RegisterHotKey)
# =========================

# Полная карта VK-кодов для всех поддерживаемых клавиш
_VK_MAP: dict[str, int] = {
    # Буквы
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,
    # Цифры
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    # Функциональные клавиши
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F,
    "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
    "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
    # Пробел и спецклавиши
    "space":     0x20,
    "enter":     0x0D,
    "return":    0x0D,
    "tab":       0x09,
    "escape":    0x1B,
    "esc":       0x1B,
    "backspace": 0x08,
    "delete":    0x2E,
    "del":       0x2E,
    "insert":    0x2D,
    "ins":       0x2D,
    "home":      0x24,
    "end":       0x23,
    "pageup":    0x21,
    "pgup":      0x21,
    "pagedown":  0x22,
    "pgdn":      0x22,
    # Стрелки
    "left":      0x25,
    "right":     0x27,
    "up":        0x26,
    "down":      0x28,
    # Символьные клавиши
    "plus":      0xBB,
    "minus":     0xBD,
    "comma":     0xBC,
    "period":    0xBE,
    "semicolon": 0xBA,
    "slash":     0xBF,
    "backslash": 0xDC,
    "quote":     0xDE,
    "backtick":  0xC0,
    "lbracket":  0xDB,
    "rbracket":  0xDD,
}


def _resolve_vk(key_name: str) -> int:
    """Резолвит имя клавиши в VK-код. Регистронезависимо."""
    vk = _VK_MAP.get(key_name.lower())
    if vk is None:
        raise ValueError(
            f"Неизвестная клавиша '{key_name}'. "
            f"Доступные клавиши: {', '.join(sorted(_VK_MAP.keys()))}"
        )
    return vk


def _build_modifiers(hk: dict) -> int:
    """Собирает флаги модификаторов из конфига горячей клавиши."""
    mod = 0
    if hk.get("ctrl", False):
        mod |= MOD_CONTROL
    if hk.get("alt", False):
        mod |= MOD_ALT
    if hk.get("shift", False):
        mod |= MOD_SHIFT
    if hk.get("win", False):
        mod |= MOD_WIN
    return mod


def _build_hotkey_description(hk: dict) -> str:
    """Формирует читаемое описание горячей клавиши."""
    parts = []
    if hk.get("ctrl", False):
        parts.append("Ctrl")
    if hk.get("alt", False):
        parts.append("Alt")
    if hk.get("shift", False):
        parts.append("Shift")
    if hk.get("win", False):
        parts.append("Win")
    parts.append(hk.get("key", "?").upper())
    return "+".join(parts)


# =========================
# ЗАПУСК
# =========================

def _kill_previous_instance() -> bool:
    """
    Обнаруживает предыдущий экземпляр AutoCorrector и завершает его.
    Возвращает True если предыдущий экземпляр был найден и завершён.
    """
    import subprocess

    PID_FILE = Path(__file__).resolve().parent / ".autocorrector.pid"

    # 1) Пробуем по PID-файлу — самый надёжный способ
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {old_pid}"],
                capture_output=True, text=True, encoding="cp866", errors="replace",
            )
            if str(old_pid) in result.stdout:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(old_pid)],
                    capture_output=True,
                )
                time.sleep(0.5)
                log.info("Завершён предыдущий экземпляр (PID %d)", old_pid)
                return True
        except (ValueError, OSError):
            pass

    # 2) Ищем по имени процесса: только AutoCorrector.exe (безопасно)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AutoCorrector.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="cp866", errors="replace",
        )
        for line in result.stdout.strip().splitlines():
            parts = line.replace('"', '').split(",")
            if len(parts) >= 2:
                pid = int(parts[1])
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                time.sleep(0.5)
                log.info("Завершён предыдущий AutoCorrector.exe (PID %d)", pid)
                return True
    except (ValueError, OSError):
        pass

    return False


def main() -> None:
    """Точка входа. Регистрирует все горячие клавиши и запускает цикл сообщений."""
    MUTEX_NAME = "Global\\AutoCorrector_SingleInstance"
    ERROR_ALREADY_EXISTS = 183
    PID_FILE = Path(__file__).resolve().parent / ".autocorrector.pid"

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if handle:
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            # Предыдущий экземпляр найден — завершаем его автоматически
            kernel32.CloseHandle(handle)
            log.info("Обнаружен предыдущий экземпляр, завершаю...")
            if _kill_previous_instance():
                print("Предыдущий экземпляр AutoCorrector завершён.")
            # Повторно создаём мьютекс
            handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if handle:
                last_error = kernel32.GetLastError()
                if last_error == ERROR_ALREADY_EXISTS:
                    kernel32.CloseHandle(handle)
                    print("Не удалось завершить предыдущий экземпляр. Попробуйте вручную.")
                    sys.exit(1)
        # Мьютекс наш — сохраняем PID
        try:
            PID_FILE.write_text(str(os.getpid()))
        except OSError:
            pass
    else:
        log.warning("Не удалось создать мьютекс, продолжаем без проверки одиночного экземпляра")

    if not HOTKEYS:
        print("ОШИБКА: Нет настроенных горячих клавиш. Откройте config.yaml.")
        sys.exit(1)

    # ── Карта: hotkey_id → hotkey_cfg ────────────────────────
    hotkey_id_map: dict[int, dict] = {}
    registered_ids: list[int] = []

    WM_QUIT = 0x0012

    for idx, hk in enumerate(HOTKEYS):
        hotkey_id = idx + 1  # IDs начинаются с 1
        hk_vk = _resolve_vk(hk["key"])
        hk_mod = _build_modifiers(hk)
        hk_desc = _build_hotkey_description(hk)

        if not user32.RegisterHotKey(None, hotkey_id, hk_mod, hk_vk):
            notify_error(
                "❌ Горячая клавиша не зарегистрирована",
                f"Не удалось зарегистрировать горячую клавишу: {hk_desc}\n\n"
                f"Возможно, она уже занята другой программой.\n"
                f"Измените комбинацию в config.yaml и перезапустите программу.",
            )
            time.sleep(1.0)  # даём времени показать уведомление
            # Отменяем уже зарегистрированные
            for rid in registered_ids:
                user32.UnregisterHotKey(None, rid)
            sys.exit(1)

        hotkey_id_map[hotkey_id] = hk
        registered_ids.append(hotkey_id)
        log.info(
            "Зарегистрирована [%s]: %s (модель: %s, темп: %.2f, лимит: %d)",
            hk.get("name", "?"), hk_desc, hk["model"], hk["temperature"],
            hk.get("max_text_length", MAX_TEXT_LENGTH),
        )

    # Обработчики SIGINT / SIGTERM — отправляем WM_QUIT
    def _signal_shutdown(signum, frame):
        log.info("Получен сигнал %d, завершаю...", signum)
        user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), WM_QUIT, 0, 0)

    signal.signal(signal.SIGINT, _signal_shutdown)
    signal.signal(signal.SIGTERM, _signal_shutdown)

    log.info("AutoCorrector v%s запущен. Зарегистрировано горячих клавиш: %d", __version__, len(registered_ids))
    log.info("Выделите текст → нажмите комбинацию клавиш")
    hotkey_names = ", ".join(
        _build_hotkey_description(hk) for hk in HOTKEYS
    )
    notify_info(
        f"🚀 AutoCorrector v{__version__} готов к работе",
        f"Горячие клавиши: {hotkey_names}\n"
        f"Выделите текст → нажмите комбинацию клавиш.",
        category="on_startup",
    )

    # Цикл сообщений Windows — блокирующий, работает в основном потоке
    msg = MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                hk_cfg = hotkey_id_map.get(msg.wParam)
                if hk_cfg is not None:
                    hwnd = user32.GetForegroundWindow()
                    hk_desc = _build_hotkey_description(hk_cfg)
                    log.info(">>> Горячая клавиша %s [%s] (HWND=%s)", hk_desc, hk_cfg.get("name", "?"), hwnd)
                    threading.Thread(
                        target=fix_selected_text, args=(hwnd, hk_cfg), daemon=True,
                    ).start()
    finally:
        for rid in registered_ids:
            user32.UnregisterHotKey(None, rid)
        # Удаляем PID-файл при завершении
        try:
            PID_FILE = Path(__file__).resolve().parent / ".autocorrector.pid"
            if PID_FILE.exists():
                PID_FILE.unlink()
        except OSError:
            pass
        log.info("AutoCorrector остановлен.")


# =========================
# АВТОЗАГРУЗКА (реестр Windows)
# =========================

AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "AutoCorrector"


def _is_autostart_active() -> bool:
    """Проверяет, есть ли AutoCorrector в автозагрузке Windows."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REG_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def _get_pythonw_path() -> Path:
    """Возвращает путь к pythonw.exe (без окна консоли)."""
    return Path(sys.executable).parent / "pythonw.exe"


def _get_main_py_path() -> Path:
    """Возвращает абсолютный путь к main.py."""
    return Path(__file__).resolve()


def register_autostart() -> None:
    """Регистрирует AutoCorrector в автозагрузке Windows через реестр.

    Команда в реестре: "<pythonw.exe>" "<main.py>" --silent
    pythonw.exe — Python без окна консоли.
    --silent — чтобы не спрашивать про автозагрузку при автозапуске.
    """
    pythonw = _get_pythonw_path()
    main_py = _get_main_py_path()

    if not pythonw.exists():
        print(
            f"ОШИБКА: pythonw.exe не найден: {pythonw}\n"
            f"Убедитесь, что Python установлен корректно."
        )
        sys.exit(1)

    # Полные абсолютные пути — не зависят от рабочей директории
    value = f'"{pythonw}" "{main_py}" --silent'

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        AUTOSTART_REG_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, value)

    log.info("AutoCorrector добавлен в автозагрузку: %s", value)
    print(f"✅ AutoCorrector добавлен в автозагрузку.")
    print(f"\n   Для работы в фоне перезагрузите компьютер.")
    print(f"   После перезагрузки программа запустится автоматически.")


def unregister_autostart() -> None:
    """Удаляет AutoCorrector из автозагрузки Windows."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        print("⚠️ AutoCorrector не был зарегистрирован в автозагрузке.")
        return

    print("✅ AutoCorrector удалён из автозагрузки.")


def _setup_cli() -> None:
    """Обработка CLI-аргументов для управления автозагрузкой.

    Если передан --install или --uninstall — выполняет действие и выходит.
    Если аргументов нет — проверяет реестр и спрашивает пользователя.
    """
    parser = argparse.ArgumentParser(
        description="AutoCorrector — автоисправление текста через OpenRouter API",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Добавить AutoCorrector в автозагрузку Windows",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Убрать AutoCorrector из автозагрузки Windows",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Запуск без вопросов (без проверки автозагрузки)",
    )
    args = parser.parse_args()

    # Явные команды — выполняем и выходим
    if args.install:
        register_autostart()
        sys.exit(0)
    elif args.uninstall:
        unregister_autostart()
        sys.exit(0)

    # Тихий режим — пропускаем проверку автозагрузки
    if args.silent:
        return

    # Интерактивная проверка автозагрузки (только если есть консоль)
    if not sys.stdin or not sys.stdin.isatty():
        return

    if _is_autostart_active():
        print("\n⚠️  AutoCorrector уже добавлен в автозагрузку Windows.")
        try:
            answer = input("   Убрать из автозагрузки? (Да/Нет): ").strip().lower()
        except (EOFError, OSError):
            return
        if answer in ("y", "д", "да", "yes"):
            unregister_autostart()
            print()
        else:
            print("   Автозагрузка оставлена без изменений.\n")
    else:
        print("\nℹ️  AutoCorrector НЕ добавлен в автозагрузку Windows.")
        try:
            answer = input("   Добавить в автозагрузку? (Да/Нет): ").strip().lower()
        except (EOFError, OSError):
            return
        if answer in ("y", "д", "да", "yes"):
            register_autostart()
            print()
        else:
            print("   Автозагрузка не настроена.\n")


# =========================
# ОБРАБОТЧИК НЕПЕРЕХВАЧЕННЫХ ОШИБОК
# =========================

# Лог-файл рядом со скриптом — используется при автозапуске (pythonw.exe)
CRASH_LOG = Path(__file__).resolve().parent / "autocorrector_crash.log"


def _setup_crash_handler() -> None:
    """Устанавливает глобальный обработчик ошибок, пишет в crash-лог."""
    _original_excepthook = sys.excepthook

    def _crash_hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(CRASH_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"\n{'='*60}\n")
                fh.write(f"CRASH: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                fh.write(msg)
                fh.write(f"{'='*60}\n")
        except Exception:
            pass
        # Также выводим в консоль (если она есть)
        _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_hook

    # Обработчик ошибок в потоках (threading.Thread)
    _original_thread_hook = threading.excepthook if hasattr(threading, 'excepthook') else None

    def _thread_crash_hook(args):
        msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        try:
            with open(CRASH_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"\n{'='*60}\n")
                fh.write(f"THREAD CRASH: {time.strftime('%Y-%m-%d %H:%M:%S')} "
                         f"[thread={args.thread.name}]\n")
                fh.write(msg)
                fh.write(f"{'='*60}\n")
        except Exception:
            pass
        log.error("Ошибка в потоке %s: %s", args.thread.name, msg)
        if _original_thread_hook:
            _original_thread_hook(args)

    threading.excepthook = _thread_crash_hook


# =========================
# ПРОВЕРКА ОБНОВЛЕНИЙ
# =========================

_GITHUB_RAW_URL = "https://raw.githubusercontent.com/fecatt/AutoCorrector/main/main.py"


def _check_for_updates() -> None:
    """Проверяет наличие обновлений на GitHub и показывает уведомление."""
    if not _notif_cfg.get("check_updates", True):
        return
    try:
        response = requests.get(_GITHUB_RAW_URL, timeout=5)
        response.raise_for_status()
        # Извлекаем __version__ из удалённого файла
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', response.text)
        if not match:
            return
        remote_version = match.group(1)
        if remote_version != __version__:
            try:
                toast(
                    "🔄 Доступно обновление",
                    f"Текущая версия: v{__version__}\n"
                    f"Новая версия: v{remote_version}\n\n"
                    f"Нажмите на это уведомление для скачивания.",
                    app_id="AutoCorrector",
                    arguments="https://github.com/fecatt/AutoCorrector",
                )
            except Exception:
                notify_info(
                    "🔄 Доступно обновление",
                    f"Текущая версия: v{__version__}\n"
                    f"Новая версия: v{remote_version}\n\n"
                    f"Скачайте: https://github.com/fecatt/AutoCorrector",
                )
    except Exception as e:
        log.debug("Не удалось проверить обновления: %s", e)


if __name__ == "__main__":
    _setup_crash_handler()
    _setup_cli()
    # Проверка обновлений в отдельном потоке, чтобы не блокировать запуск
    threading.Thread(target=_check_for_updates, daemon=True).start()
    main()
