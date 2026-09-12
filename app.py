import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

# ==========================================================
# 0. АВТОЗАГРУЗКА .ENV И БЕЗОПАСНЫЙ ИМПОРТ БИБЛИОТЕК
# ==========================================================

env_file = Path(".env")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

try:
    import typst
    PY_TYPST_AVAILABLE = True
except ImportError:
    PY_TYPST_AVAILABLE = False

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================================
# 1. СИСТЕМНЫЕ НАСТРОЙКИ, ПАПКИ GOOGLE DRIVE И БЕНЧМАРКИ
# ==========================================================

st.set_page_config(
    page_title="PIN100 Analytics",
    page_icon="📍",
    layout="wide"
)

GDRIVE_FOLDERS = {
    "JSON": "1efm3iHSVvUPp50in3tfOGxd0xOACio2E",
    "PDF": "15kzKEaS76HAhx22FR-BTvifbaecH_wx8",
    "LETTERS": "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6",
}

GDRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии в РФ») и РБК Исследования рынков",
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК Исследования рынков («Российский рынок эстетической медицины и косметологии»)",
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Рынок частных медицинских услуг в РФ») и НАФИ",
    },
    "AUTOSERVICES": {
        "niche_name": "Автосервис / Техцентр",
        "niche_genitive": "автосервисов",
        "client_word": "клиент",
        "quality_phrase": "технического обслуживания и ремонта",
        "benchmark_leads": 110,
        "base_check": 7500,
        "ltv_months": 8,
        "benchmark_source": "Аналитика Автостат и ассоциации РАСТО («Рынок автосервисных услуг РФ»)",
    },
    "OTHER": {
        "niche_name": "Организация сферы услуг",
        "niche_genitive": "организаций",
        "client_word": "клиент",
        "quality_phrase": "стандартов сервиса и качества обслуживания",
        "benchmark_leads": 80,
        "base_check": 4200,
        "ltv_months": 9,
        "benchmark_source": "СберАналитика и Росстат («Потребительские расходы в секторе B2C-услуг»)",
    },
}

# ==========================================================
# 2. РЕЕСТР 41 КРИТЕРИЯ СКОРИНГА (DENTISTRY = 100 БАЛЛОВ)
# ==========================================================

CRITERIA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "CONV-48.1": {"title": "Доступность онлайн-записи на приём", "group": "Конверсия", "complexity": 2, "weight_dentistry": 6.0, "desc_default": "Отсутствие виджета онлайн-записи отсекает мобильный трафик.", "desc_dentistry": "Отсутствие прямой онлайн-записи (МИС) отсекает до 60% вечернего спроса. Пациент с острой болью запишется в один клик к соседям, не дожидаясь утра."},
    "CONV-48.2": {"title": "Витрина специалистов в профиле", "group": "Конверсия", "complexity": 2, "weight_dentistry": 5.0, "desc_default": "Обезличенная карточка снижает доверие клиентов.", "desc_dentistry": "В карточке не оцифрованы профили врачей (фото, стаж, специальности). В медицине выбор делают «на врача»: карточка проигрывает конкурентам с открытой командой."},
    "PROF-10.3": {"title": "Отсутствие перечня услуг в профиле", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 4.0, "desc_default": "В описании много эмоций, но нет структуры услуг.", "desc_dentistry": "В описании клиники много общих фраз, но нет структуры процедур. Пациент не видит нужного направления и уходит к соседям."},
    "PROF-11.1": {"title": "Наполненность витрины услуг (10+)", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 4.0, "desc_default": "Полупустой каталог услуг создает образ неполноценного сервиса.", "desc_dentistry": "В каталоге заполнено менее трети ключевых процедур. Алгоритмы ранжируют выше клиники с полным прейскурантом."},
    "CONV-49.1": {"title": "Уникальное торговое предложение (УТП)", "group": "Конверсия", "complexity": 2, "weight_dentistry": 4.0, "desc_default": "Общие рекламные фразы без цифр не работают.", "desc_dentistry": "Отсутствие твердого позиционирования (гарантии, методики) размывает ценность услуг клиники."},
    "REP-34.1": {"title": "Авторитетность авторов отзывов (Знатоки)", "group": "Репутация", "complexity": 4, "weight_dentistry": 4.0, "desc_default": "Отзывы пустых профилей хуже ранжируются.", "desc_dentistry": "Оценки авторов со статусом «Знаток города» имеют максимальный вес для ранжирования медицинской карточки."},
    "PROF-11.3": {"title": "Цены у товаров и услуг («от...»)", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 3.5, "desc_default": "Скрытые цены вызывают раздражение.", "desc_dentistry": "«Слепой» прайс отпугивает пациентов: люди боятся скрытых накруток в кресле и выбирают клинику с ценами «от...»."},
    "REP-32.2": {"title": "Культура диалога с пациентами", "group": "Репутация", "complexity": 4, "weight_dentistry": 3.5, "desc_default": "Споры в отзывах разрушают репутацию.", "desc_dentistry": "Первичный пациент выбирает клинику по уровню заботы — оборонительная позиция в отзывах отпугивает семьи к соседям."},
    "REP-29.1": {"title": "Регулярность свежих отзывов (<14 дней)", "group": "Репутация", "complexity": 4, "weight_dentistry": 3.0, "desc_default": "Отсутствие свежих оценок создает образ спада активности.", "desc_dentistry": "Паузы в новых отзывах сигнализируют системе о спаде спроса и снижают органическую видимость."},
    "REP-30.1": {"title": "Охват базы отзывов ответами (>90%)", "group": "Репутация", "complexity": 4, "weight_dentistry": 3.0, "desc_default": "Игнорирование обратной связи разрушает доверие.", "desc_dentistry": "Отсутствие регулярных официальных ответов клиники на отзывы снижает первичное доверие пациентов."},
    "PROF-11.2": {"title": "Фото у позиций каталога", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 3.0, "desc_default": "Покупка вслепую снижает интерес к услугам.", "desc_dentistry": "Отсутствие визуализации медицинских услуг снижает вовлеченность пациентов в просмотр профиля."},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Рейтинг ниже 4.5 приводит к отсечению фильтрами.", "desc_dentistry": "Рейтинг ниже 4.5 критичен: пациенты опасаются доверять здоровье клиникам с низкими оценками."},
    "REP-27.2": {"title": "Премиальный уровень рейтинга (4.8+)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Рейтинг 4.8+ автоматически снимает возражения.", "desc_dentistry": "Рейтинг 4.8+ обеспечивает максимальную конверсию, снимая 80% возражений пациента до первого визита."},
    "REP-30.2": {"title": "Оперативность ответов руководства (<=3 дней)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Задержка в ответах демонстрирует слабый сервис.", "desc_dentistry": "В медицине скорость реакции клиники на отзывы показывает уровень внимания к результатам лечения."},
    "REP-30.4": {"title": "Развернутые ответы руководства (>80 симв.)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Шаблонные отписки считываются как безразличие.", "desc_dentistry": "Персонализированные ответы формируют культуру заботы и насыщают карточку поисковыми запросами."},
    "REP-35.1": {"title": "Доля отзывов с реальными фото (>10%)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Отзывы без фото вызывают меньше доверия.", "desc_dentistry": "Фотографии реальных пациентов служат сильным социальным подтверждением безопасности лечения."},
    "SEO-19.2": {"title": "Упоминание услуг в тексте отзывов", "group": "SEO и Трафик", "complexity": 4, "weight_dentistry": 2.5, "desc_default": "Без услуг алгоритму сложнее ранжировать карточку.", "desc_dentistry": "Упоминание процедур в отзывах повышает позиции клиники в предметном поиске района."},
    "PROF-08.2": {"title": "Нишевые медицинские атрибуты", "group": "SEO и Трафик", "complexity": 1, "weight_dentistry": 2.5, "desc_default": "Проигнорированные детали исключают компанию из поиска.", "desc_dentistry": "Пациенты фильтруют клиники: «детский прием», «наличие КТ», «рассрочка». Без них карточка исключается из выдачи."},
    "PROF-09.1": {"title": "Информативность описания компании", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 2.5, "desc_default": "Слишком короткое описание — потеря площади ранжирования.", "desc_dentistry": "Качественный структурированный текст дает Яндексу максимум SEO-сигналов и знакомит пациента с клиникой."},
    "PROF-11.4": {"title": "Информативность карточек услуг", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 2.5, "desc_default": "Сухие названия без описаний ведут к ценовому демпингу.", "desc_dentistry": "Подробные описания услуг снимают страхи пациента еще до звонка администратору."},
    "CONT-42.1": {"title": "Видео (рилс/тур)", "group": "Контент и Визуал", "complexity": 3, "weight_dentistry": 2.0, "desc_default": "Видеоконтент удерживает внимание в 3 раза дольше.", "desc_dentistry": "Видеотуры увеличивают время просмотра карточки, что алгоритмы Яндекса считывают как сигнал качества."},
    "CONV-46.1": {"title": "Обложка ручная", "group": "Конверсия", "complexity": 3, "weight_dentistry": 2.0, "desc_default": "Стандартная панорама делает профиль безликим.", "desc_dentistry": "Кастомная обложка привлекает внимание и сразу транслирует клинический статус профиля."},
    "CONV-50.1": {"title": "Прямой диалог через чат Карт", "group": "Конверсия", "complexity": 1, "weight_dentistry": 2.0, "desc_default": "Отключенный чат отсекает текстовых клиентов.", "desc_dentistry": "Многие пациенты избегают звонков в рабочее время. Отключенный чат отсекает готовую записаться аудиторию."},
    "CONV-53.1": {"title": "Бейджи в витрине", "group": "Конверсия", "complexity": 2, "weight_dentistry": 2.0, "desc_default": "Без маркетинговых бейджей витрина монотонна.", "desc_dentistry": "Маркетинговые метки на услугах управляют вниманием пациента и ведут его к маржинальным процедурам."},
    "GEO-18.4": {"title": "Точная точка входа (Маркер двери)", "group": "SEO и Трафик", "complexity": 5, "weight_dentistry": 2.0, "desc_default": "Навигатор ведет клиента к глухому забору.", "desc_dentistry": "Неточный маркер входа приводит к блужданию пациентов вокруг здания и срыву графика приема."},
    "PROF-04.1": {"title": "Рабочая ссылка на сайт", "group": "Базовое заполнение", "complexity": 2, "weight_dentistry": 2.0, "desc_default": "Отсутствие сайта снижает статус организации.", "desc_dentistry": "Ссылка на сайт позволяет пациенту изучить лицензии, технологии и примеры работ врачей."},
    "PROF-05.1": {"title": "Основной телефон клиники", "group": "Базовое заполнение", "complexity": 2, "weight_dentistry": 2.0, "desc_default": "Карточка без телефона обрывает связь.", "desc_dentistry": "Телефон клиники должен быть кликабельным и вести на администратора с фиксацией в МИС."},
    "PROF-07.1": {"title": "Стандартный график работы 7 дней", "group": "Базовое заполнение", "complexity": 2, "weight_dentistry": 2.0, "desc_default": "Неполный график отсекает визиты в спорные окна.", "desc_dentistry": "Пациентам с острой болью критически важно видеть статус работы клиники в выходные и вечерние часы."},
    "PROF-13.1": {"title": "Указаны прямые мессенджеры", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 2.0, "desc_default": "Отсутствие мессенджеров отсекает текстовые лиды.", "desc_dentistry": "Мессенджеры позволяют пациенту отправить снимок для предварительной оценки и быстро записаться."},
    "REP-28.1": {"title": "Общий объем базы отзывов (50+)", "group": "Репутация", "complexity": 4, "weight_dentistry": 2.0, "desc_default": "Мало отзывов — нет социального доказательства.", "desc_dentistry": "Большой массив отзывов подтверждает устойчивый опыт врачебной практики клиники."},
    "SEO-18.3": {"title": "Топонимы и ориентиры в тексте", "group": "SEO и Трафик", "complexity": 4, "weight_dentistry": 2.0, "desc_default": "Без топонимов карточка проигрывает гео-поиск.", "desc_dentistry": "Названия станций метро, улиц и микрорайона прочно закрепляют клинику за локальной выдачей."},
    "CONT-38.1": {"title": "Фото интерьера", "group": "Контент и Визуал", "complexity": 3, "weight_dentistry": 1.5, "desc_default": "Презентабельный интерьер формирует доверие.", "desc_dentistry": "Отсутствие фото кабинетов ассоциируется с эконом-сегментом. Пациентам важна чистота и стерильность."},
    "CONV-52.1": {"title": "Блок FAQ заполнен", "group": "Конверсия", "complexity": 2, "weight_dentistry": 1.5, "desc_default": "Оставшиеся вопросы уводят клиента к конкурентам.", "desc_dentistry": "Блок FAQ закрывает страхи пациентов (болезненность, рассрочка, гарантии) прямо в профиле."},
    "PROF-03.2": {"title": "Полнота охвата смежных рубрик (3+)", "group": "SEO и Трафик", "complexity": 1.5, "weight_dentistry": 1.5, "desc_default": "Указана одна рубрика: срезается смежный трафик.", "desc_dentistry": "Отсутствие смежных рубрик (ортодонтия, детская стоматология) отсекает пациентов со специализированными запросами."},
    "PROF-08.1": {"title": "Базовые атрибуты комфорта", "group": "SEO и Трафик", "complexity": 1, "weight_dentistry": 1.5, "desc_default": "Незаполненные особенности исключают из поиска.", "desc_dentistry": "Пациенты часто фильтруют клиники по удобствам (парковка, доступность для МГН, безналичная оплата)."},
    "PROF-12.1": {"title": "Верификация «Синяя галочка»", "group": "Базовое заполнение", "complexity": 1.5, "weight_dentistry": 1.5, "desc_default": "Без верификации карточка лишена траста площадки.", "desc_dentistry": "Синяя галочка подтверждает официальный статус клиники, защищая профиль от недостоверных правок."},
    "PROF-01.1": {"title": "Название заполнено корректно", "group": "SEO и Трафик", "complexity": 1, "weight_dentistry": 1.0, "desc_default": "Некорректное название снижает доверие алгоритмов.", "desc_dentistry": "Чистое бренд-название обеспечивает корректную защиту брендового трафика клиники."},
    "PROF-01.2": {"title": "Нет спама в названии", "group": "SEO и Трафик", "complexity": 1, "weight_dentistry": 1.0, "desc_default": "Спам ключевиками ведет к санкциям модерации.", "desc_dentistry": "Отсутствие поискового спама в названии защищает карточку клиники от санкций и потери позиций."},
    "PROF-03.1": {"title": "Основная рубрика заполнена", "group": "SEO и Трафик", "complexity": 1, "weight_dentistry": 1.0, "desc_default": "Неверная рубрика исключает из выдачи.", "desc_dentistry": "Корректная базовая рубрика обеспечивает привязку к поисковому кластеру района."},
    "PROF-04.2": {"title": "UTM-разметка ссылок", "group": "Базовое заполнение", "complexity": 1, "weight_dentistry": 1.0, "desc_default": "Без аналитики руководство не видит отдачи от гео-трафика.", "desc_dentistry": "Отсутствие UTM-меток не позволяет руководству оценить реальную окупаемость профиля и поток первичных пациентов."},
    "PROF-15.1": {"title": "Юридические данные клиники", "group": "Базовое заполнение", "complexity": 2, "weight_dentistry": 1.0, "desc_default": "Отсутствие реквизитов вызывает сомнения в надежности.", "desc_dentistry": "Заполненные юридические данные и номер лицензии подтверждают правовой статус медицинской организации."},
}

# ==========================================================
# 3. ТЕРМИНАЛ ЛОГОВ И TELEGRAM
# ==========================================================

class TerminalLogger:
    """Управляет выводом консольного окна выполнения на экран Streamlit."""
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.logs: List[str] = []

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "[INFO]   ",
            "SUCCESS": "[SUCCESS]",
            "WARN": "[WARN]   ",
            "ERROR": "[ERROR]  ",
            "STEP": "[STEP]   "
        }.get(level, "[INFO]   ")
        formatted = f"{ts} {prefix} {msg}"
        self.logs.append(formatted)
        self.placeholder.code("\n".join(self.logs), language="bash")


def send_telegram_error(error_message: str, context: str = "") -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = (
        f"🚨 <b>PIN100 Analytics: Сбой в конвейере</b>\n\n"
        f"<b>Контекст:</b> {context}\n"
        f"<b>Причина:</b> <code>{error_message}</code>\n"
        f"<b>Время:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False

# ==========================================================
# 4. APIFY ПАРСЕР ПО ССЫЛКЕ
# ==========================================================

def fetch_profile_via_apify(target_url: str, logger: Optional[TerminalLogger] = None) -> Dict[str, Any]:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token:
        raise ValueError("В .env не найден APIFY_API_TOKEN. Укажите действующий токен Apify.")

    actor = os.getenv("APIFY_ACTOR_ID", "").strip()
    if not actor:
        raise ValueError("В .env не найден APIFY_ACTOR_ID. Укажите ID или имя актора (например: compass/yandex-maps-scraper).")

    actor_id_url = actor.replace("/", "~")
    run_url = f"https://api.apify.com/v2/acts/{actor_id_url}/run-sync-get-dataset-items?token={token}&timeout=70"

    if logger:
        logger.log(f"Запуск Apify Actor '{actor}'...", "STEP")

    payload = {
        "startUrls": [{"url": target_url.strip()}],
        "maxItems": 1,
        "maxReviews": 30,
        "includeReviews": True,
        "includePhotos": True
    }

    resp = requests.post(run_url, json=payload, timeout=80)
    if resp.status_code == 404:
        raise RuntimeError(f"Актор '{actor}' не найден в Apify (404). Проверьте APIFY_ACTOR_ID в .env.")
    if resp.status_code not in [200, 201]:
        raise RuntimeError(f"Ошибка Apify API (HTTP {resp.status_code}): {resp.text[:250]}")

    items = resp.json()
    if not items or not isinstance(items, list):
        raise ValueError(f"Apify вернул пустой набор данных для {target_url}")

    if logger:
        logger.log("Данные успешно получены из облака Apify", "SUCCESS")
    return items[0]

# ==========================================================
# 5. СКОРИНГ 41 КРИТЕРИЯ И РАСЧЕТ МЕТРИК
# ==========================================================

def evaluate_audit_scores(raw_scores: Dict[str, float], niche: str = "DENTISTRY", logger: Optional[TerminalLogger] = None) -> Tuple[float, List[Dict[str, Any]]]:
    is_dentistry = (niche == "DENTISTRY")
    total_score = 0.0
    gap_list = []

    for code, meta in CRITERIA_REGISTRY.items():
        max_w = meta["weight_dentistry"]
        cur_w = float(raw_scores.get(code, max_w))
        cur_w = min(max_w, max(0.0, cur_w))
        total_score += cur_w

        lost = max_w - cur_w
        if lost > 0.1:
            impact = lost * (6.0 - meta["complexity"])
            gap_list.append({
                "code": code,
                "title": meta["title"],
                "desc": meta["desc_dentistry"] if is_dentistry else meta["desc_default"],
                "lost": lost,
                "impact": impact
            })
            if logger:
                logger.log(f"[{code}] {meta['title']} -> Потеряно: -{lost:.1f} б.", "WARN")

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]

    while len(top_3) < 3:
        top_3.append({
            "code": "GEN-00",
            "title": "Техническая оптимизация карточки",
            "desc": "Рекомендуем поддерживать актуальность прейскуранта и регулярность официальных ответов на отзывы.",
            "lost": 0.0,
            "impact": 0.0
        })

    return round(total_score, 1), top_3


def parse_apify_or_raw_json(raw_input: Any, logger: Optional[TerminalLogger] = None) -> Dict[str, Any]:
    if isinstance(raw_input, list):
        if not raw_input:
            raise ValueError("Передан пустой список JSON.")
        data = raw_input[0]
    elif isinstance(raw_input, dict):
        if "items" in raw_input and isinstance(raw_input["items"], list):
            if not raw_input["items"]:
                raise ValueError("Ключ 'items' в файле пуст.")
            data = raw_input["items"][0]
        elif "data" in raw_input and isinstance(raw_input["data"], (dict, list)):
            return parse_apify_or_raw_json(raw_input["data"], logger)
        else:
            data = raw_input
    else:
        raise ValueError(f"Неподдерживаемый тип JSON: {type(raw_input).__name__}")

    title = data.get("title") or data.get("name") or data.get("companyName")
    if not title:
        raise ValueError("В структуре JSON отсутствует имя организации ('title' или 'name').")

    org_id = str(data.get("org_id") or data.get("id") or data.get("companyId") or "0000000000")
    rating = float(data.get("rating") or data.get("reviewsRating") or data.get("totalScore") or 5.0)

    if logger:
        logger.log(f"Организация: «{title}» (ID: {org_id}), Рейтинг: {rating}", "INFO")

    low_txt = (str(title) + " " + str(data.get("categories", "")) + " " + str(data.get("rubrics", ""))).lower()
    if any(k in low_txt for k in ["космет", "beauty", "эстет"]):
        niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["авто", "сервис", "мотор"]):
        niche = "AUTOSERVICES"
    elif any(k in low_txt for k in ["многопрофильн", "медцентр"]):
        niche = "GENERAL_MEDICINE"
    else:
        niche = "DENTISTRY"

    if logger:
        logger.log(f"Определена ниша: {NICHE_CONFIG[niche]['niche_name']}", "INFO")

    raw_scores: Dict[str, float] = {}

    # Сценарий 1: Уже готовые оценки критериев
    if "criteria_scores" in data and isinstance(data["criteria_scores"], dict):
        if logger:
            logger.log("Считывание готовой матрицы скоринга из criteria_scores...", "INFO")
        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(data["criteria_scores"].get(c_code, c_meta["weight_dentistry"]))
    elif "checks" in data and isinstance(data["checks"], dict):
        if logger:
            logger.log("Считывание чеклиста проверок из checks...", "INFO")
        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(data["checks"].get(c_code, c_meta["weight_dentistry"]))
    else:
        # Сценарий 2: Расчет по 41 правилу таблицы PIN100
        if logger:
            logger.log("Запуск полного скоринга по 41 правилу таблицы PIN100...", "STEP")

        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(c_meta["weight_dentistry"])

        features_str = str(data.get("features", [])).lower()
        site_str = str(data.get("website", "") or data.get("url", "")).lower()

        # 1. Онлайн-запись (CONV-48.1)
        has_booking = bool(
            data.get("bookingUrl") or data.get("isBookingAvailable") or data.get("booking") or
            "онлайн-запис" in features_str or "запись онлайн" in features_str or
            any(w in site_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "booking", "stoma"])
        )
        if not has_booking:
            raw_scores["CONV-48.1"] = 0.0

        # 2. Врачи / Специалисты (CONV-48.2)
        has_staff = bool(
            data.get("specialists") or data.get("doctors") or data.get("staff") or
            "врач" in features_str or "специалист" in features_str or "команда" in features_str
        )
        if not has_staff:
            raw_scores["CONV-48.2"] = 0.0

        # 3. Каталог услуг и цены (PROF-11.1, PROF-10.3, PROF-11.3)
        items = data.get("items") or data.get("priceList") or data.get("goods") or data.get("services") or data.get("menu") or []
        if isinstance(items, list):
            if len(items) < 10:
                raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
            if len(items) < 5:
                raw_scores["PROF-10.3"] = 0.0
            has_prices = any(bool(it.get("price") or it.get("cost")) for it in items if isinstance(it, dict))
            if not has_prices and not any(w in features_str for w in ["прайс", "цены", "руб"]):
                raw_scores["PROF-11.3"] = 0.0

        # 4. Рейтинг
        if rating < 4.8:
            raw_scores["REP-27.2"] = 0.0
        if rating < 4.5:
            raw_scores["REP-27.1"] = 0.0

        # 5. База отзывов
        rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(data.get("reviews", [])) or 0)
        if rev_count < 50:
            raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

        # 6. Фото и верификация
        p_count = int(data.get("photosCount", 0)) or len(data.get("photos", []))
        if p_count < 5:
            raw_scores["CONT-38.1"] = 0.5
        if not bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge")):
            raw_scores["PROF-12.1"] = 0.0

    calculated_score, top_fails = evaluate_audit_scores(raw_scores, niche, logger)

    if any(k in data for k in ["score", "totalScore", "readiness_score", "pin100_score"]):
        calculated_score = float(data.get("score") or data.get("totalScore") or data.get("readiness_score") or data.get("pin100_score"))

    comps = data.get("competitors") or []
    if not comps or not isinstance(comps, list):
        comps = ["соседние клиники локации", "сетевые клиники района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["DENTISTRY"])

    if logger:
        logger.log(f"Итоговый балл карточки: {calculated_score:.1f} / 100", "SUCCESS")

    return {
        "title": title,
        "org_id": org_id,
        "rating": rating,
        "score": calculated_score,
        "niche": niche,
        "canonical_url": data.get("canonical_url") or data.get("url") or "",
        "competitors": comps,
        "benchmark_leads": int(data.get("benchmark_leads") or n_def["benchmark_leads"]),
        "base_check": int(data.get("base_check") or n_def["base_check"]),
        "ltv_months": int(data.get("ltv_months") or n_def["ltv_months"]),
        "benchmark_source": n_def["benchmark_source"],
        "criteria_scores": raw_scores,
        "top_failures": top_fails,
        "date": data.get("date") or datetime.date.today().strftime("%d.%m.%Y"),
        "date_raw": data.get("date_raw") or datetime.date.today().strftime("%Y-%m-%d"),
    }

# ==========================================================
# 6. ТЕКСТЫ, ЮНИТ-ЭКОНОМИКА И КОМПИЛЯЦИЯ PDF
# ==========================================================

def format_currency(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def get_declension(number: int, word_type: str = "пациент") -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type in ["пациент", "клиент"]:
        if 11 <= n <= 19:
            return f"{word_type}ов"
        if n1 == 1:
            return word_type
        if 2 <= n1 <= 4:
            return f"{word_type}а"
        return f"{word_type}ов"
    return "обращений"


def get_score_color(score: float) -> str:
    if score >= 80:
        return "16a34a"
    if score >= 60:
        return "d97706"
    return "dc2626"


def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")
    return clean if clean else "clinic"


def generate_icebreaker(title: str, rating: float | str, competitors: List[str], lost_leads: int, niche_genitive: str = "стоматологий") -> str:
    has_real_comps = (
        competitors and 
        isinstance(competitors, list) and 
        len(competitors) >= 2 and 
        not any(w in competitors[0].lower() for w in ["конкурент", "клиник", "сосед"])
    )

    if has_real_comps:
        comp_str = f"«{competitors[0].strip('«»')}» и «{competitors[1].strip('«»')}»"
    else:
        comp_str = "соседние клиники локации"

    leads_range_str = f"{max(1, lost_leads - 2)}–{lost_leads + 3}"

    return (
        f"Добрый день!\n\n"
        f"Анализировали выдачу {niche_genitive} в вашем районе на Яндекс Картах "
        f"и обратили внимание на карточку «{title}». При сильной репутации ({rating}) "
        f"первичный поток прямо сейчас перехватывают {comp_str}.\n\n"
        f"На поверхности лежит отсутствие кнопки быстрой записи (пациенты вечером не хотят звонить "
        f"и уходят к соседям), но алгоритмы пессимизируют карточку еще по нескольким (иногда не очевидным) "
        f"параметрам. По емкости района это отток около {leads_range_str} пациентов в месяц.\n\n"
        f"Собрали наглядный разбор карточки и расчет потерь в короткий PDF на 4 страницы. "
        f"Скинуть файл сюда для ознакомления?"
    )


def calculate_report_metrics(audit_data: Dict[str, Any]) -> Dict[str, str]:
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_info = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])

    title = audit_data.get("title", "Организация")
    rating = audit_data.get("rating", 4.7)
    score = min(100.0, max(0.0, float(audit_data.get("score", 66.5))))

    leads_bench = audit_data.get("benchmark_leads", niche_info["benchmark_leads"])
    base_check = audit_data.get("base_check", niche_info["base_check"])
    ltv_months = audit_data.get("ltv_months", niche_info["ltv_months"])
    bench_source = audit_data.get("benchmark_source", niche_info["benchmark_source"])

    dev = max(0.0, round(100.0 - score, 1))
    lost_leads = int(round(leads_bench * (dev / 100.0)))
    rev_loss = lost_leads * base_check
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * ltv_months

    table_declension = get_declension(lost_leads, niche_info["client_word"])
    failures = audit_data.get("top_failures", [])

    return {
        "[[TITLE]]": title,
        "[[NICHE]]": niche_info["niche_name"],
        "[[DATE]]": audit_data.get("date", datetime.date.today().strftime("%d.%m.%Y")),
        "[[SCORE]]": f"{score:.1f}" if score % 1 != 0 else str(int(score)),
        "[[SCORE_COLOR]]": get_score_color(score),
        "[[REV_LOSS_FMT]]": format_currency(rev_loss),
        "[[CLIENT_LEADS]]": str(leads_bench),
        "[[DEV]]": f"{dev:.1f}" if dev % 1 != 0 else str(int(dev)),
        "[[LOST_LEADS]]": str(lost_leads),
        "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": format_currency(base_check),
        "[[CLIENT_LTV]]": str(ltv_months),
        "[[LTV_LOSS_FMT]]": format_currency(ltv_loss),
        "[[BENCHMARK_SOURCE]]": bench_source,
        "[[QUALITY_PHRASE]]": niche_info["quality_phrase"],
        "[[EXECUTIVE_SUMMARY]]": (
            f"Профиль «{title}» обладает высокой клинической репутацией ({rating}), однако из-за отсутствия "
            f"прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм "
            f"перенаправляет до {lost_leads} готовых обращений в месяц прямым конкурентам локации."
        ),
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери пациентов",
        "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": failures[0]["title"] if len(failures) > 0 else "Барьер конверсии",
        "[[FAIL_1_DESC]]": failures[0]["desc"] if len(failures) > 0 else "Требуется оптимизация карточки.",
        "[[FAIL_2_TITLE]]": failures[1]["title"] if len(failures) > 1 else "Барьер доверия",
        "[[FAIL_2_DESC]]": failures[1]["desc"] if len(failures) > 1 else "Требуется заполнение команды специалистов.",
        "[[FAIL_3_TITLE]]": failures[2]["title"] if len(failures) > 2 else "Барьер прейскуранта",
        "[[FAIL_3_DESC]]": failures[2]["desc"] if len(failures) > 2 else "Требуется открытие цен на услуги.",
        "[[WEEKLY_LOSS_FMT]]": format_currency(weekly_loss),
    }


def render_typst_template(template_path: Path, mapping: Dict[str, str]) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    for placeholder, val in mapping.items():
        content = content.replace(placeholder, str(val))
    return content


def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path, logger: Optional[TerminalLogger] = None) -> Tuple[bool, str]:
    temp_typ = work_dir / f"temp_{output_pdf_path.stem}.typ"
    try:
        if logger:
            logger.log("Подготовка исходного файла Typst...", "INFO")
        with open(temp_typ, "w", encoding="utf-8") as f:
            f.write(typst_content)

        if PY_TYPST_AVAILABLE:
            if logger:
                logger.log("Компиляция PDF через Python-модуль typst...", "STEP")
            try:
                typst.compile(str(temp_typ), output=str(output_pdf_path))
                if logger:
                    logger.log("PDF-отчет успешно собран через модуль typst!", "SUCCESS")
                return True, ""
            except Exception as ex_py:
                if logger:
                    logger.log(f"Сбой модуля typst: {ex_py}. Пробуем системный CLI...", "WARN")

        cmd = ["typst", "compile", str(temp_typ), str(output_pdf_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            if logger:
                logger.log("PDF-отчет успешно скомпилирован через Typst CLI!", "SUCCESS")
            return True, ""
        return False, f"Ошибка CLI Typst: {res.stderr}"

    except FileNotFoundError:
        return False, "Typst не найден в Python и не установлен в системе."
    except Exception as e:
        return False, f"Ошибка компиляции Typst: {e}"
    finally:
        if temp_typ.exists():
            try:
                temp_typ.unlink()
            except OSError:
                pass

# ==========================================================
# 7. GOOGLE DRIVE И GOOGLE SHEETS
# ==========================================================

def get_google_credentials() -> Optional[Any]:
    if not GOOGLE_LIBS_AVAILABLE:
        return None
    for path_str in ["credentials.json", "service_account.json"]:
        p = Path(path_str)
        if p.exists():
            return service_account.Credentials.from_service_account_file(str(p), scopes=GDRIVE_SCOPES)
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        return service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=GDRIVE_SCOPES)
    return None


def get_or_create_date_folder(drive_service: Any, parent_folder_id: str, date_str: str) -> str:
    query = f"'{parent_folder_id}' in parents and name = '{date_str}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {"name": date_str, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_folder_id]}
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_file_to_drive(drive_service: Any, local_path: Path, target_folder_id: str, mime_type: str) -> Dict[str, str]:
    metadata = {"name": local_path.name, "parents": [target_folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    uploaded = drive_service.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    return {"id": uploaded.get("id", ""), "link": uploaded.get("webViewLink", "")}


def sync_results_to_google(audit_data: Dict[str, Any], mapping: Dict[str, str], pdf_path: Path, txt_path: Path, json_path: Path, spreadsheet_id: Optional[str] = None, logger: Optional[TerminalLogger] = None) -> Dict[str, str]:
    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError("Пакеты google-api-python-client не установлены в окружении.")

    creds = get_google_credentials()
    if not creds:
        raise FileNotFoundError("Ключ credentials.json не найден в корне проекта.")

    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    if logger:
        logger.log(f"Синхронизация файлов с Google Диском в папку '{date_str}'...", "STEP")

    pdf_res = upload_file_to_drive(drive_service, pdf_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["PDF"], date_str), "application/pdf")
    txt_res = upload_file_to_drive(drive_service, txt_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["LETTERS"], date_str), "text/plain")
    json_res = upload_file_to_drive(drive_service, json_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["JSON"], date_str), "application/json")

    if logger:
        logger.log("Файлы (PDF, TXT, JSON) успешно загружены на Google Диск", "SUCCESS")

    links = {"pdf": pdf_res["link"], "txt": txt_res["link"], "json": json_res["link"]}

    if spreadsheet_id and spreadsheet_id.strip():
        if logger:
            logger.log("Добавление строки аудита в Google Таблицу...", "STEP")
        now_time = datetime.datetime.now().strftime("%H:%M:%S")
        row = [
            mapping["[[DATE]]"], now_time, audit_data.get("title", ""), audit_data.get("org_id", ""),
            audit_data.get("canonical_url", ""), mapping["[[NICHE]]"], audit_data.get("rating", ""),
            mapping["[[SCORE]]"], mapping["[[LOST_LEADS]]"], mapping["[[REV_LOSS_FMT]]"],
            links["pdf"], links["txt"], links["json"]
        ]
        try:
            sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id.strip(), range="Лист1!A:M", valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS", body={"values": [row]}
            ).execute()
            if logger:
                logger.log("Строка аудита успешно зафиксирована в Google Таблице!", "SUCCESS")
        except Exception as e:
            if logger:
                logger.log(f"Запись в Google Таблицу пропущена: {e}", "WARN")

    return links

# ==========================================================
# 8. СКВОЗНОЙ КОНВЕЙЕР ОБРАБОТКИ (PIPELINE RUNNER)
# ==========================================================

def execute_full_pipeline(raw_data: Any, logger: TerminalLogger):
    """Выполняет полный цикл аудита, сборки PDF и облачной синхронизации за один проход."""
    try:
        # 1. Парсинг и скоринг 41 критерия
        logger.log("ЭТАП 1/5: Анализ карточки и скоринг 41 критерия PIN100", "STEP")
        audit = parse_apify_or_raw_json(raw_data, logger)
        st.session_state.current_audit = audit

        # 2. Расчет финансовых метрик
        logger.log("ЭТАП 2/5: Расчет юнит-экономики и упущенной выручки", "STEP")
        mapping = calculate_report_metrics(audit)
        st.session_state.current_mapping = mapping
        logger.log(f"Упущенная выручка: {mapping['[[REV_LOSS_FMT]]']} ₽/мес, Потери: ~{mapping['[[LOST_LEADS]]']} чел/мес", "INFO")

        # 3. Формирование письма
        logger.log("ЭТАП 3/5: Генерация персонализированного письма для ЛПР (Icebreaker)", "STEP")
        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
        icebreaker_txt = generate_icebreaker(
            title=audit["title"],
            rating=audit["rating"],
            competitors=audit["competitors"],
            lost_leads=lost_leads_int,
            niche_genitive=n_def["niche_genitive"]
        )
        st.session_state.current_icebreaker = icebreaker_txt
        logger.log("Текст первого касания подготовлен без использования клише", "SUCCESS")

        # 4. Компиляция PDF-отчета
        logger.log("ЭТАП 4/5: Компиляция 4-страничного PDF-отчета (Typst)", "STEP")
        template_file = Path("report_template.typ")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        date_tag = datetime.date.today().strftime("%Y-%m-%d")
        file_prefix = f"{sanitize_filename(audit['title'])}_{audit['org_id']}_{date_tag}"
        pdf_path = output_dir / f"{file_prefix}_report.pdf"
        txt_path = output_dir / f"{file_prefix}_icebreaker.txt"
        json_path = output_dir / f"{file_prefix}_data.json"

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(icebreaker_txt)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)

        if not template_file.exists():
            err = "Шаблон report_template.typ не найден рядом с app.py"
            logger.log(err, "ERROR")
            send_telegram_error(err, "Компиляция PDF")
        else:
            rendered = render_typst_template(template_file, mapping)
            ok, err_typst = compile_typst_pdf(rendered, pdf_path, output_dir, logger)
            if ok:
                st.session_state.pdf_path = str(pdf_path)
            else:
                logger.log(f"Сбой компиляции Typst: {err_typst}", "ERROR")
                send_telegram_error(err_typst, f"Typst компиляция {audit['title']}")

        # 5. Синхронизация с Google
        logger.log("ЭТАП 5/5: Облачная синхронизация (Google Drive и Таблица)", "STEP")
        target_sheet = os.getenv("GOOGLE_SHEET_ID", "")
        if GOOGLE_LIBS_AVAILABLE and pdf_path.exists():
            try:
                links = sync_results_to_google(
                    audit_data=audit,
                    mapping=mapping,
                    pdf_path=pdf_path,
                    txt_path=txt_path,
                    json_path=json_path,
                    spreadsheet_id=target_sheet,
                    logger=logger
                )
                st.session_state.drive_links = links
            except Exception as ex_g:
                logger.log(f"Google Drive: {ex_g}", "WARN")
                send_telegram_error(str(ex_g), f"Синхронизация {audit['title']}")
        else:
            logger.log("Выгрузка в облако пропущена (пакеты Google не подключены или PDF не собран)", "WARN")

        logger.log("🏁 КОНВЕЙЕР УСПЕШНО ЗАВЕРШЕН!", "SUCCESS")

    except Exception as ex:
        err_msg = f"Критический сбой: {ex}"
        logger.log(err_msg, "ERROR")
        send_telegram_error(err_msg, "Выполнение конвейера PIN100")

# ==========================================================
# 9. ИНТЕРФЕЙС STREAMLIT
# ==========================================================

def run_streamlit_app() -> None:
    if "current_audit" not in st.session_state:
        st.session_state.current_audit = None
    if "current_mapping" not in st.session_state:
        st.session_state.current_mapping = None
    if "current_icebreaker" not in st.session_state:
        st.session_state.current_icebreaker = ""
    if "drive_links" not in st.session_state:
        st.session_state.drive_links = None
    if "pdf_path" not in st.session_state:
        st.session_state.pdf_path = ""

    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    st.caption("Прямой API-краулинг Яндекс Карт, персонализированное письмо для ЛПР и 4-страничный PDF-отчет.")

    tab_json, tab_url = st.tabs([
        "📋 Загрузить готовый JSON из Apify",
        "🔗 Ссылка на Яндекс Карты (Прямой API Apify)"
    ])

    # Вкладка 1: Загрузка готового JSON
    with tab_json:
        col_f1, col_f2 = st.columns([1.5, 2.5])
        with col_f1:
            uploaded_file = st.file_uploader("Перетащите файл .json из Apify:", type=["json"])
        with col_f2:
            json_text = st.text_area("Или вставьте код JSON из буфера:", height=100, placeholder='[{"title": "СпейсДент", ...}]')

        run_json_btn = st.button("🚀 Запустить полный конвейер по JSON", type="primary", use_container_width=True)

    # Вкладка 2: Ссылка через Apify
    with tab_url:
        with st.form("maps_url_form", clear_on_submit=False):
            target_url = st.text_input(
                "Ссылка на профиль в Яндекс Картах:",
                placeholder="https://yandex.ru/maps/org/... или короткая https://yandex.ru/maps/-/... "
            )
            run_url_btn = st.form_submit_button("🚀 Запустить краулинг и полный аудит", type="primary", use_container_width=True)

    # Терминал выполнения конвейера
    st.subheader("🖥️ Терминал выполнения конвейера (Live Diagnostics)")
    terminal_box = st.empty()
    logger = TerminalLogger(terminal_box)

    if run_json_btn:
        logger.log("Старт конвейера из источника JSON...", "INFO")
        raw_data = None
        if uploaded_file is not None:
            logger.log(f"Чтение загруженного файла '{uploaded_file.name}'...", "INFO")
            uploaded_file.seek(0)
            raw_data = json.load(uploaded_file)
        elif json_text.strip():
            logger.log("Чтение кода JSON из текстового поля...", "INFO")
            raw_data = json.loads(json_text)
        else:
            logger.log("Ошибка: файл не выбран и текстовое поле пусто!", "ERROR")

        if raw_data is not None:
            execute_full_pipeline(raw_data, logger)

    if run_url_btn:
        if not target_url.strip():
            logger.log("Ошибка: укажите ссылку на организацию!", "ERROR")
        else:
            logger.log(f"Старт конвейера по URL: {target_url}", "INFO")
            try:
                raw_data = fetch_profile_via_apify(target_url, logger)
                execute_full_pipeline(raw_data, logger)
            except Exception as ex_url:
                logger.log(f"Ошибка Apify: {ex_url}", "ERROR")
                send_telegram_error(str(ex_url), f"Apify URL: {target_url}")

    # ==========================================================
    # ВЫДАЧА РЕЗУЛЬТАТОВ (ОТОБРАЖАЕТСЯ АВТОМАТИЧЕСКИ ПОСЛЕ ЗАВЕРШЕНИЯ)
    # ==========================================================
    if st.session_state.current_audit and st.session_state.current_mapping:
        audit = st.session_state.current_audit
        mapping = st.session_state.current_mapping
        icebreaker_txt = st.session_state.current_icebreaker

        st.divider()
        col_left, col_right = st.columns([1.1, 0.9])

        with col_left:
            st.subheader("✉️ Первое сообщение руководителю (Icebreaker)")
            st.caption("Персонализированное обращение без формулировки «кассовый разрыв»:")
            st.text_area("Текст для WhatsApp / Telegram / Email:", value=icebreaker_txt, height=220)

            st.markdown("**Выявленные ключевые уязвимости профиля (Стр. 3 отчета):**")
            for idx, f in enumerate(audit.get("top_failures", []), 1):
                st.markdown(f"**{idx}. {f['title']}**")
                st.caption(f["desc"])

        with col_right:
            st.subheader(f"📊 Экономика потерь «{audit['title']}»")
            m1, m2 = st.columns(2)
            m1.metric("Оценка карточки", f"{mapping['[[SCORE]]']} / 100")
            m2.metric("Потери пациентов", f"~{mapping['[[LOST_LEADS]]']} чел/мес")

            m3, m4 = st.columns(2)
            m3.metric("Упущенная выручка", f"{mapping['[[REV_LOSS_FMT]]']} ₽/мес")
            m4.metric("Потери за неделю", f"~{mapping['[[WEEKLY_LOSS_FMT]]']} ₽/нед")

            st.caption(f"Источник бенчмарков ниши: **{mapping['[[BENCHMARK_SOURCE]]']}**")

            st.divider()

            st.subheader("📄 4-страничный PDF-отчет")
            if st.session_state.pdf_path and Path(st.session_state.pdf_path).exists():
                with open(st.session_state.pdf_path, "rb") as f:
                    st.download_button(
                        label="📥 Скачать готовый PDF-отчет",
                        data=f.read(),
                        file_name=Path(st.session_state.pdf_path).name,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
            else:
                st.warning("Файл PDF еще не собран. Проверьте сообщения в терминале выше.")

            if st.session_state.drive_links:
                st.success("✅ Все материалы сохранены на Google Диск!")
                l = st.session_state.drive_links
                st.markdown(f"📄 **PDF на Диске:** [Открыть файл]({l.get('pdf', '#')})")
                st.markdown(f"✉️ **Письмо на Диске:** [Открыть файл]({l.get('txt', '#')})")
                st.markdown(f"⚙️ **JSON на Диске:** [Открыть файл]({l.get('json', '#')})")


if __name__ == "__main__":
    run_streamlit_app()
