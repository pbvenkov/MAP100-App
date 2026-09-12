import argparse
import datetime
import json
import os
import re
import subprocess
import sys
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

# Импорт Python-библиотеки Typst
try:
    import typst
    PY_TYPST_AVAILABLE = True
except ImportError:
    PY_TYPST_AVAILABLE = False

# Импорт библиотек Google
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

# Верифицированные экономические бенчмарки ниш с официальными источниками
NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,       # Медиана первичных обращений ТОП-3 клиник района
        "base_check": 5500,          # Средний чек первичного визита (диагностика + гигиена/лечение)
        "ltv_months": 12,            # Средний горизонт прикрепления семьи (2.4 визита в год)
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
# 3. УВЕДОМЛЕНИЯ В TELEGRAM
# ==========================================================

def send_telegram_error(error_message: str, context: str = "") -> bool:
    """Отправляет уведомление об ошибке в Telegram (таймаут 3с, не вешает UI)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = (
        f"🚨 <b>PIN100 Analytics: Ошибка конвейера</b>\n\n"
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
# 4. СЕТЕВОЙ ПАРСЕР ССЫЛОК И СКОРИНГ
# ==========================================================

def fetch_yandex_maps_profile(raw_url: str) -> Dict[str, Any]:
    """Распаковывает короткие ссылки и извлекает метаданные с сохранением регистра названия."""
    clean_url = raw_url.strip()
    if not clean_url:
        raise ValueError("URL ссылки пуст.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    session = requests.Session()
    session.headers.update(headers)

    resp = session.get(clean_url, allow_redirects=True, timeout=8)
    canonical_url = resp.url
    html_text = resp.text

    # 1. Извлечение ID
    org_id = "0000000000"
    m_id = re.search(r'/org/(?:[^/?#]+/)?(\d+)', canonical_url) or re.search(r'[?&]oid=(\d+)', canonical_url)
    if m_id:
        org_id = m_id.group(1)

    # 2. Извлечение названия (сохраняем оригинальный регистр)
    title = None
    m_og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html_text, re.IGNORECASE)
    if m_og:
        raw_t = m_og.group(1).replace("— Яндекс Карты", "").replace("- Яндекс Карты", "").strip()
        title = re.split(r'[,|•·—–]', raw_t)[0].strip()

    if not title:
        m_slug = re.search(r'/org/([^/?#]+)/\d+', canonical_url)
        if m_slug:
            raw_slug = urllib.parse.unquote(m_slug.group(1)).replace('_', ' ').replace('-', ' ')
            title = raw_slug[:1].upper() + raw_slug[1:]

    if not title or title.lower() in ["яндекс карты", "yandex maps"]:
        title = "Организация"

    # 3. Рейтинг
    rating = 5.0
    m_rate = re.search(r'itemprop=["\']ratingValue["\']\s+content=["\']([0-9.]+)["\']', html_text)
    if not m_rate:
        m_rate = re.search(r'class="business-rating-badge-view__rating">([0-9.]+)</span>', html_text)
    if m_rate:
        try:
            rating = float(m_rate.group(1))
        except ValueError:
            pass

    # 4. Объем отзывов
    reviews_count = 50
    m_rev = re.search(r'itemprop=["\']reviewCount["\']\s+content=["\'](\d+)["\']', html_text)
    if m_rev:
        try:
            reviews_count = int(m_rev.group(1))
        except ValueError:
            pass

    return {
        "title": title,
        "org_id": org_id,
        "rating": rating,
        "reviewsRating": rating,
        "reviewsCount": reviews_count,
        "canonical_url": canonical_url,
        "url": canonical_url,
        "features": ["онлайн-запись", "врачи", "прайс-лист"] if "онлайн" in html_text.lower() else []
    }


def evaluate_audit_scores(raw_scores: Dict[str, float], niche: str = "DENTISTRY") -> Tuple[float, List[Dict[str, Any]]]:
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


def parse_apify_or_raw_json(raw_input: Any) -> Dict[str, Any]:
    """Универсальный парсер JSON с корректной обработкой конкурентов и названий."""
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
            return parse_apify_or_raw_json(raw_input["data"])
        else:
            data = raw_input
    else:
        raise ValueError(f"Неподдерживаемый тип данных: {type(raw_input).__name__}.")

    if not isinstance(data, dict):
        raise ValueError(f"Корневой элемент карточки не является объектом: {type(data).__name__}.")

    title = data.get("title") or data.get("name") or data.get("companyName")
    if not title:
        raise ValueError("В переданном JSON отсутствует название организации.")

    org_id = str(data.get("org_id") or data.get("id") or data.get("companyId") or "0000000000")
    rating = float(data.get("rating") or data.get("reviewsRating") or data.get("totalScore") or 5.0)

    # Определение ниши
    low_txt = (str(title) + " " + str(data.get("categories", "")) + " " + str(data.get("rubrics", ""))).lower()
    if any(k in low_txt for k in ["космет", "beauty", "эстет"]):
        niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["авто", "сервис", "мотор", "ремонт авто"]):
        niche = "AUTOSERVICES"
    elif any(k in low_txt for k in ["многопрофильн", "медцентр", "поликлиник"]):
        niche = "GENERAL_MEDICINE"
    else:
        niche = "DENTISTRY"

    raw_scores: Dict[str, float] = {}

    if "criteria_scores" in data and isinstance(data["criteria_scores"], dict):
        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(data["criteria_scores"].get(c_code, c_meta["weight_dentistry"]))
    elif "checks" in data and isinstance(data["checks"], dict):
        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(data["checks"].get(c_code, c_meta["weight_dentistry"]))
    else:
        for c_code, c_meta in CRITERIA_REGISTRY.items():
            raw_scores[c_code] = float(c_meta["weight_dentistry"])

        features_str = str(data.get("features", [])).lower()
        site_str = str(data.get("website", "") or data.get("url", "")).lower()

        # Онлайн-запись
        has_booking = bool(
            data.get("bookingUrl") or data.get("isBookingAvailable") or data.get("booking") or
            "онлайн-запис" in features_str or "запись онлайн" in features_str or
            any(w in site_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "booking"])
        )
        if not has_booking:
            raw_scores["CONV-48.1"] = 0.0

        # Врачи / Специалисты
        has_staff = bool(
            data.get("specialists") or data.get("doctors") or data.get("staff") or
            "врач" in features_str or "специалист" in features_str or "команда" in features_str
        )
        if not has_staff:
            raw_scores["CONV-48.2"] = 0.0

        # Каталог услуг и цены
        items = data.get("items") or data.get("priceList") or data.get("goods") or data.get("services") or data.get("menu") or []
        if isinstance(items, list):
            if len(items) < 10:
                raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
            if len(items) < 5:
                raw_scores["PROF-10.3"] = 0.0
            has_prices = any(bool(it.get("price") or it.get("cost")) for it in items if isinstance(it, dict))
            if not has_prices and not any(w in features_str for w in ["прайс", "цены", "руб"]):
                raw_scores["PROF-11.3"] = 0.0

        # Рейтинг
        if rating < 4.8:
            raw_scores["REP-27.2"] = 0.0
        if rating < 4.5:
            raw_scores["REP-27.1"] = 0.0

        # База отзывов
        rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(data.get("reviews", [])) or 0)
        if rev_count < 50:
            raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

        # Фото и верификация
        p_count = int(data.get("photosCount", 0)) or len(data.get("photos", []))
        if p_count < 5:
            raw_scores["CONT-38.1"] = 0.5
        if not bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge")):
            raw_scores["PROF-12.1"] = 0.0

    calculated_score, top_fails = evaluate_audit_scores(raw_scores, niche)

    if any(k in data for k in ["score", "totalScore", "readiness_score", "pin100_score"]):
        calculated_score = float(data.get("score") or data.get("totalScore") or data.get("readiness_score") or data.get("pin100_score"))

    # Конкуренты: нейтральные формулировки без чужих городов
    comps = data.get("competitors") or []
    if not comps or not isinstance(comps, list):
        comps = ["соседние клиники локации", "сетевые клиники района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["DENTISTRY"])

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
# 5. СИНХРОНИЗАЦИЯ С GOOGLE DRIVE И GOOGLE SHEETS
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


def sync_results_to_google(audit_data: Dict[str, Any], mapping: Dict[str, str], pdf_path: Path, txt_path: Path, json_path: Path, spreadsheet_id: Optional[str] = None) -> Dict[str, str]:
    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError("Пакеты google-api-python-client не установлены в окружении.")

    creds = get_google_credentials()
    if not creds:
        raise FileNotFoundError("Файл ключа credentials.json не найден рядом с app.py.")

    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    pdf_res = upload_file_to_drive(drive_service, pdf_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["PDF"], date_str), "application/pdf")
    txt_res = upload_file_to_drive(drive_service, txt_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["LETTERS"], date_str), "text/plain")
    json_res = upload_file_to_drive(drive_service, json_path, get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["JSON"], date_str), "application/json")

    links = {"pdf": pdf_res["link"], "txt": txt_res["link"], "json": json_res["link"]}

    if spreadsheet_id and spreadsheet_id.strip():
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
        except Exception as e:
            st.warning(f"Запись в Google Таблицу пропущена: {e}")

    return links

# ==========================================================
# 6. РАСЧЕТ ЮНИТ-ЭКОНОМИКИ И ТЕКСТОВ
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
    # Проверяем, являются ли конкуренты реальными названиями
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


def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> Tuple[bool, str]:
    """Компилирует PDF через Python-модуль typst либо через системный CLI."""
    temp_typ = work_dir / f"temp_{output_pdf_path.stem}.typ"
    try:
        with open(temp_typ, "w", encoding="utf-8") as f:
            f.write(typst_content)

        # 1. Приоритет: библиотека typst из requirements.txt
        if PY_TYPST_AVAILABLE:
            try:
                typst.compile(str(temp_typ), output=str(output_pdf_path))
                return True, ""
            except Exception as ex_py:
                pass  # пробуем CLI как fallback

        # 2. Резерв: CLI typst
        cmd = ["typst", "compile", str(temp_typ), str(output_pdf_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True, ""
        return False, f"Ошибка CLI Typst: {res.stderr}"

    except FileNotFoundError:
        return False, "Библиотека Typst не установлена в Python и не найдена в PATH системы."
    except Exception as e:
        return False, f"Сбой компиляции Typst: {e}"
    finally:
        if temp_typ.exists():
            try:
                temp_typ.unlink()
            except OSError:
                pass

# ==========================================================
# 7. ЧИСТЫЙ ИНТЕРФЕЙС КОНВЕЙЕРА (STREAMLIT)
# ==========================================================

def run_streamlit_app() -> None:
    if "current_audit" not in st.session_state:
        st.session_state.current_audit = None
    if "drive_links" not in st.session_state:
        st.session_state.drive_links = None

    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    st.caption("Автоматический расчет потерь, персонализированное письмо для ЛПР и 4-страничный PDF-отчет.")

    tab_url, tab_json = st.tabs([
        "🔗 Ссылка на профиль в Яндекс Картах (Основной поток)",
        "📋 Загрузить JSON из Apify"
    ])

    # Вкладка 1: Ссылка на профиль в Яндекс Картах
    with tab_url:
        with st.form("maps_url_form", clear_on_submit=False):
            target_url = st.text_input(
                "Ссылка на организацию в Яндекс Картах:",
                placeholder="Вставьте ссылку любого формата: https://yandex.ru/maps/org/... или короткую https://yandex.ru/maps/-/... "
            )
            submit_url = st.form_submit_button("🚀 Запустить аудит по ссылке", type="primary", use_container_width=True)

        if submit_url:
            if not target_url.strip():
                st.warning("⚠️ Пожалуйста, вставьте ссылку на организацию в поле выше.")
            else:
                with st.spinner("⏳ Подключаемся к Яндекс Картам, считываем профиль и рассчитываем скоринг..."):
                    try:
                        raw_card = fetch_yandex_maps_profile(target_url)
                        st.session_state.current_audit = parse_apify_or_raw_json(raw_card)
                        st.session_state.drive_links = None
                        st.success(f"✅ Карточка «{st.session_state.current_audit['title']}» успешно определена! Оценка: {st.session_state.current_audit['score']}/100")
                        st.rerun()
                    except Exception as e:
                        err_msg = f"Ошибка обработки ссылки: {e}"
                        st.error(err_msg)
                        send_telegram_error(err_msg, f"URL: {target_url}")

    # Вкладка 2: Загрузка готового JSON
    with tab_json:
        col_f1, col_f2 = st.columns([1.5, 2.5])
        with col_f1:
            uploaded_file = st.file_uploader("Перетащите файл .json из Apify:", type=["json"])
        with col_f2:
            json_text = st.text_area("Или вставьте код JSON из буфера:", height=100, placeholder='[{"title": "СпейсДент", ...}]')

        calc_json_btn = st.button("⚡ Рассчитать аудит по JSON", type="primary", use_container_width=True)

        if calc_json_btn:
            with st.spinner("⏳ Анализируем карточку по 41 критерию..."):
                raw_data = None
                error_context = ""

                if uploaded_file is not None:
                    error_context = f"Файл: {uploaded_file.name}"
                    try:
                        uploaded_file.seek(0)
                        raw_data = json.load(uploaded_file)
                    except Exception as ex:
                        err_msg = f"Ошибка чтения JSON файла: {ex}"
                        st.error(err_msg)
                        send_telegram_error(err_msg, error_context)
                elif json_text.strip():
                    error_context = "Текстовый ввод JSON"
                    try:
                        raw_data = json.loads(json_text)
                    except Exception as ex:
                        err_msg = f"Невалидный синтаксис JSON: {ex}"
                        st.error(err_msg)
                        send_telegram_error(err_msg, error_context)
                else:
                    st.warning("⚠️ Пожалуйста, загрузите .json файл или вставьте текст в поле выше.")

                if raw_data is not None:
                    try:
                        st.session_state.current_audit = parse_apify_or_raw_json(raw_data)
                        st.session_state.drive_links = None
                        st.success(f"✅ Организация «{st.session_state.current_audit['title']}» успешно оцифрована! Балл: {st.session_state.current_audit['score']}/100")
                        st.rerun()
                    except Exception as ex:
                        err_msg = f"Ошибка структуры данных карточки: {ex}"
                        st.error(err_msg)
                        send_telegram_error(err_msg, error_context or "Парсинг JSON")

    # ------------------------------------------------------
    # ДАШБОРД РЕЗУЛЬТАТОВ: ПИСЬМО + ПОТЕРИ + PDF
    # ------------------------------------------------------
    if not st.session_state.current_audit:
        st.divider()
        st.info("👆 Вставьте ссылку на Яндекс Карты или загрузите JSON карточки для старта конвейера.")
        return

    audit = st.session_state.current_audit
    mapping = calculate_report_metrics(audit)
    st.divider()

    col_left, col_right = st.columns([1.1, 0.9])

    with col_left:
        st.subheader("✉️ Первое сообщение руководителю (Icebreaker)")
        st.caption("Персонализированное обращение без формулировки «кассовый разрыв»:")

        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
        icebreaker_txt = generate_icebreaker(
            title=audit["title"],
            rating=audit["rating"],
            competitors=audit["competitors"],
            lost_leads=lost_leads_int,
            niche_genitive=n_def["niche_genitive"]
        )
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
        template_file = Path("report_template.typ")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        date_tag = datetime.date.today().strftime("%Y-%m-%d")
        file_prefix = f"{sanitize_filename(audit['title'])}_{audit['org_id']}_{date_tag}"
        pdf_path = output_dir / f"{file_prefix}_report.pdf"
        txt_path = output_dir / f"{file_prefix}_icebreaker.txt"
        json_path = output_dir / f"{file_prefix}_data.json"

        if st.button("🚀 Скомпилировать PDF и отправить на Google Диск", type="primary", use_container_width=True):
            if not template_file.exists():
                err_msg = "Файл report_template.typ не найден рядом с app.py."
                st.error(err_msg)
                send_telegram_error(err_msg, "Компиляция PDF")
            else:
                with st.spinner("Компилируем PDF-отчет и сохраняем файлы на Google Диск..."):
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(icebreaker_txt)
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(audit, f, ensure_ascii=False, indent=2)

                    rendered = render_typst_template(template_file, mapping)
                    ok, err = compile_typst_pdf(rendered, pdf_path, output_dir)

                    if ok:
                        st.success("PDF-отчет успешно сгенерирован!")
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                label="📥 Скачать готовый PDF-отчет",
                                data=f.read(),
                                file_name=pdf_path.name,
                                mime="application/pdf",
                                use_container_width=True
                            )

                        target_sheet = os.getenv("GOOGLE_SHEET_ID", "")
                        if GOOGLE_LIBS_AVAILABLE:
                            try:
                                links = sync_results_to_google(
                                    audit_data=audit,
                                    mapping=mapping,
                                    pdf_path=pdf_path,
                                    txt_path=txt_path,
                                    json_path=json_path,
                                    spreadsheet_id=target_sheet
                                )
                                st.session_state.drive_links = links
                                st.balloons()
                            except Exception as ex:
                                err_msg = f"Ошибка выгрузки на Google Диск: {ex}"
                                st.warning(err_msg)
                                send_telegram_error(err_msg, f"Синхронизация Google Drive для {audit['title']}")
                        else:
                            st.info("Для синхронизации с Google Диском добавьте google-api-python-client в requirements.txt.")
                    else:
                        st.error(f"Ошибка компиляции Typst: {err}")
                        send_telegram_error(err, f"Typst компиляция для {audit['title']}")

        if st.session_state.drive_links:
            st.success("✅ Все материалы сохранены в целевые папки на Google Диске!")
            l = st.session_state.drive_links
            st.markdown(f"📄 **PDF на Диске:** [Открыть файл]({l.get('pdf', '#')})")
            st.markdown(f"✉️ **Письмо на Диске:** [Открыть файл]({l.get('txt', '#')})")
            st.markdown(f"⚙️ **JSON на Диске:** [Открыть файл]({l.get('json', '#')})")


if __name__ == "__main__":
    run_streamlit_app()
