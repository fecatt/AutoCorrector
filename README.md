# AutoCorrector

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.10+-yellow)

**Choose your language / Выберите язык:** [English](#english) | [Русский](#русский)

---

<a id="english"></a>

## English

> ℹ️ **The program interface is in Russian only.** This English section describes the same functionality for reference. All notifications, error messages, and console output will be in Russian.

> ⚠️ **Windows-only** — this application uses Windows API (RegisterHotKey, WinRT toast notifications, Windows Registry) and does not work on macOS or Linux.

### What is it

AutoCorrector is a system-wide text correction tool powered by AI (OpenRouter API). Select text in any application → press a hotkey → the program copies the text, sends it for correction, and pastes the corrected version back — replacing your selection in place.

**Features:**

- **System-wide hotkeys** — works in any application (Notepad, Word, browser, messengers…)
- **Multiple hotkey profiles** — each combination can use a different AI model, prompt, and temperature
- **Clipboard preservation** — restores your original clipboard content after correction
- **Clipboard history-safe** — corrected text is pasted without polluting Win+V history
- **Autostart** — can launch automatically at Windows login (background, no console window)
- **Windows toast notifications** — real-time status updates via native notifications

### Requirements

- Windows 10 or 11
- Python 3.10+
- An [OpenRouter](https://openrouter.ai) API key

### Quick Start

1. Clone the repository:
   ```
   git clone https://github.com/your-username/autocorrector.git
   cd autocorrector
   ```

2. Open [`config.yaml`](config.yaml) and enter your API key:
   ```yaml
   api:
     key: "sk-or-v1-..."
   ```

3. Double-click [`run.bat`](run.bat).

4. Select text in any window → press **Ctrl+Alt+G** → the text is corrected in place.

### Configuration

| Section | Description |
|---------|-------------|
| `api.*` | API key, URL, model, temperature, timeout, proxy, system prompt |
| `limits.*` | Max text length, max retries |
| `logging.*` | Log level, log file |
| `notifications.*` | Toggle individual notification types |
| `hotkeys[]` | List of hotkey combinations with per-profile overrides |

#### Hotkey Example

```yaml
hotkeys:
  # Text correction
  - name: "Correction"
    ctrl: true
    alt: true
    key: "g"              # → Ctrl+Alt+G

  # Rewrite
  - name: "Rewrite"
    ctrl: true
    alt: true
    shift: true
    key: "g"              # → Ctrl+Alt+Shift+G
    model: "anthropic/claude-3-haiku"
    temperature: 0.7
    system_prompt: |
      You are a rewriting assistant.
      Rephrase the text preserving meaning but changing style.
      Return only the rewritten text.

  # Translation
  - name: "Translate to English"
    ctrl: true
    alt: true
    key: "t"              # → Ctrl+Alt+T
    system_prompt: |
      Translate the text to English.
      Preserve style and meaning. Return only the translation.
```

#### Autostart

- **Install** — double-click [`run.bat`](run.bat) → select "Add to autostart" when prompted
- **Uninstall** — double-click [`run.bat`](run.bat) → select "Remove from autostart" when prompted

#### Getting an OpenRouter API Key

1. Go to [openrouter.ai](https://openrouter.ai)
2. Sign up / log in
3. Add credits: **Settings** → **Credits**
4. Go to **Keys** → **Create Key**
5. Copy the key into [`config.yaml`](config.yaml) → `api.key`

### How It Works (Step by Step)

1. **Select text** in any application (Notepad, Word, browser, messenger…)
2. **Press the hotkey** (default: Ctrl+Alt+G)
3. The program **copies** the selected text
4. Sends it to the **AI API** with the configured prompt
5. Receives the corrected text
6. **Pastes** it back, replacing the selection
7. **Restores** the original clipboard content

### Troubleshooting

All notifications are shown in Russian. Below are the actual messages with their meaning:

| Notification (Russian) | Meaning | Solution |
|------------------------|---------|----------|
| «❌ Горячая клавиша не зарегистрирована» | Hotkey combination is taken by another program | Change the combination in [`config.yaml`](config.yaml) |
| «⚠️ Превышен лимит текста» | Text is longer than `max_text_length` | Shorten the text or increase the limit |
| «❌ Не удалось скопировать текст» | Text is not selected or the app doesn't support copying | Make sure text is selected |
| «❌ Ошибка при обращении к API» | Internet issues or invalid API key | Check your connection and API key in [`config.yaml`](config.yaml) |
| «✅ Текст без ошибок» | Text has no errors | Everything is fine, no paste needed |
| «✅ Текст исправлен» | Text was corrected and pasted back | — |
| «❌ Ошибка буфера обмена» | Failed to paste corrected text to clipboard | Restart the program |
| «🚀 AutoCorrector готов к работе» | Program started successfully | — |

### File Structure

```
autocorrector/
├── main.py              # Main application code
├── config.yaml          # API and hotkey configuration
├── run.bat              # Launch script (run, autostart install/uninstall)
├── requirements.txt     # Python dependencies
├── LICENSE              # MIT License
├── .gitignore           # Git exclusions
└── README.md            # This file
```

### License

This project is licensed under the [MIT License](LICENSE).

---

<a id="русский"></a>

## Русский

> ⚠️ **Только Windows** — приложение использует Windows API (RegisterHotKey, WinRT toast-уведомления, реестр Windows) и не работает на macOS или Linux.

### Что это

AutoCorrector — программа для автоматического исправления текста через AI (OpenRouter API). Выделяете текст в любом приложении → нажимаете горячую клавишу → программа копирует текст, отправляет на коррекцию и вставляет исправленный обратно.

**Возможности:**

- **Горячие клавиши на уровне системы** — работает в любом приложении (Блокнот, Word, браузер, мессенджеры…)
- **Несколько профилей горячих клавиш** — каждая комбинация может использовать свою модель AI, промт и температуру
- **Сохранение буфера обмена** — исходное содержимое буфера восстанавливается после исправления
- **Без засорения истории** — исправленный текст вставляется без сохранения в историю Win+V
- **Автозагрузка** — может автоматически запускаться при входе в Windows (в фоне, без окна консоли)
- **Windows toast-уведомления** — уведомления о статусе через нативные уведомления Windows

### Требования

- Windows 10 или 11
- Python 3.10+
- API-ключ [OpenRouter](https://openrouter.ai)

### Быстрый старт

1. Клонируйте репозиторий:
   ```
   git clone https://github.com/your-username/autocorrector.git
   cd autocorrector
   ```

2. Откройте [`config.yaml`](config.yaml) и укажите ваш API-ключ:
   ```yaml
   api:
     key: "sk-or-v1-..."
   ```

3. Запустите [`run.bat`](run.bat).

4. Выделите текст в любом окне → нажмите **Ctrl+Alt+G** → текст исправится на месте.

### Конфигурация

| Секция | Описание |
|--------|----------|
| `api.*` | API-ключ, URL, модель, температура, таймаут, прокси, системный промт |
| `limits.*` | Макс. длина текста, макс. количество попыток |
| `logging.*` | Уровень логирования, файл логов |
| `notifications.*` | Включение/отключение отдельных типов уведомлений |
| `hotkeys[]` | Список комбинаций клавиш с индивидуальными настройками |

#### Пример горячей клавиши

```yaml
hotkeys:
  # Исправление ошибок
  - name: "Коррекция"
    ctrl: true
    alt: true
    key: "g"              # → Ctrl+Alt+G

  # Рерайт текста
  - name: "Рерайт"
    ctrl: true
    alt: true
    shift: true
    key: "g"              # → Ctrl+Alt+Shift+G
    model: "anthropic/claude-3-haiku"
    temperature: 0.7
    system_prompt: |
      Ты помощник по рерайтингу.
      Перефразируй текст, сохраняя смысл, но меняя стилистику.
      Не добавляй пояснений.

  # Перевод
  - name: "Перевод на английский"
    ctrl: true
    alt: true
    key: "t"              # → Ctrl+Alt+T
    system_prompt: |
      Переведи текст на английский язык.
      Сохрани стиль и смысл. Верни только перевод.
```

#### Автозагрузка

- **Установка** — запустите [`run.bat`](run.bat) → выберите «Добавить в автозагрузку»
- **Удаление** — запустите [`run.bat`](run.bat) → выберите «Убрать из автозагрузки»

#### Получение API-ключа OpenRouter

1. Зайдите на [openrouter.ai](https://openrouter.ai)
2. Зарегистрируйтесь / войдите
3. Пополните баланс: **Settings** → **Credits**
4. Перейдите в **Keys** → **Create Key**
5. Скопируйте ключ и вставьте в [`config.yaml`](config.yaml) → `api.key`

### Как это работает (пошагово)

1. **Выделите текст** в любом приложении (Блокнот, Word, браузер, мессенджер…)
2. **Нажмите горячую клавишу** (по умолчанию Ctrl+Alt+G)
3. Программа **копирует** выделенный текст
4. Отправляет его в **AI API** с настроенным промтом
5. Получает исправленный текст
6. **Вставляет** его обратно, заменяя выделение
7. **Восстанавливает** оригинальное содержимое буфера обмена

### Возможные ошибки

| Сообщение | Причина | Решение |
|-----------|---------|---------|
| «Не удалось зарегистрировать горячую клавишу» | Комбинация занята другой программой | Измените комбинацию в [`config.yaml`](config.yaml) |
| «Превышен допустимый лимит» | Текст длиннее `max_text_length` | Сократите текст или увеличьте лимит |
| «Не удалось скопировать выделенный текст» | Текст не выделен или приложение не поддерживает копирование | Убедитесь, что текст выделен |
| «Ошибка API» | Проблемы с интернетом или неверный ключ | Проверьте подключение и API-ключ |
| «Без изменений» | Текст не содержит ошибок | Всё в порядке, вставка не нужна |

### Структура файлов

```
autocorrector/
├── main.py              # Основной код приложения
├── config.yaml          # Конфигурация API и горячих клавиш
├── run.bat              # Скрипт запуска (запуск, автозагрузка)
├── requirements.txt     # Зависимости Python
├── LICENSE              # Лицензия MIT
├── .gitignore           # Исключения для git
└── README.md            # Этот файл
```

### Лицензия

Проект распространяется под лицензией [MIT](LICENSE).
