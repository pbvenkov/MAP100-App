import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

# ==========================================================
# 0. АВТОЗАГРУЗКА .ENV И БЕЗОПАСНЫЙ ИМПОРТ
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
# 1. КОНФИГУРАЦИЯ СИСТЕМЫ И БЕНЧМАРКИ
# ==========================================================

st.set_page_config(page_title="PIN100 Analytics", page_icon="📍", layout="wide")

GDRIVE_FOLDERS = {
    "JSON": "1efm3iHSVvUPp50in3tfOGxd0xOACio2E",
    "PDF": "15kzKEaS76HAhx22FR-BTvifbaecH_wx8",
    "LETTERS": "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6",
}
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии РФ») и РБК",
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК («Российский рынок эстетической медицины»)",
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat и НАФИ",
    }
}

# ==========================================================
# 2. МАТРИЦА 41 КРИТЕРИЯ PIN100
# ==========================================================
CRITERIA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "CONV-48.1": {"title": "Онлайн-запись на приём (МИС)", "group": "Конверсия", "complexity": 2, "weight": 6.0, "desc": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."},
    "CONV-48.2": {"title": "Витрина специалистов в профиле", "group": "Конверсия", "complexity": 2, "weight": 5.0, "desc": "Не оцифрованы врачи. Обезличенная карточка проигрывает конкурентам."},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "desc": "В описании клиники нет четкой структуры процедур."},
    "PROF-11.1": {"title": "Наполненность витрины услуг (10+)", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "desc": "Полупустой каталог пессимизируется алгоритмами поиска."},
    "CONV-49.1": {"title": "Уникальное торговое предложение (УТП)", "group": "Конверсия", "complexity": 2, "weight": 4.0, "desc": "Отсутствие твердого позиционирования размывает ценность."},
    "REP-34.1": {"title": "Авторитетность авторов (Знатоки)", "group": "Репутация", "complexity": 4, "weight": 4.0, "desc": "Мало отзывов от авторов со статусом «Знаток города»."},
    "PROF-11.3": {"title": "Цены у товаров и услуг («от...»)", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "desc": "«Слепой» прайс отпугивает пациентов страхом скрытых накруток."},
    "REP-32.2": {"title": "Культура диалога в отзывах", "group": "Репутация", "complexity": 4, "weight": 3.5, "desc": "Шаблонные или оборонительные ответы снижают лояльность."},
    "REP-29.1": {"title": "Свежие отзывы (<14 дней)", "group": "Репутация", "complexity": 4, "weight": 3.0, "desc": "Паузы в новых отзывах сигнализируют о спаде спроса."},
    "REP-30.1": {"title": "Охват отзывов ответами (>90%)", "group": "Репутация", "complexity": 4, "weight": 3.0, "desc": "Игнорирование обратной связи разрушает доверие."},
    "PROF-11.2": {"title": "Фото у позиций каталога", "group": "Базовое заполнение", "complexity": 1, "weight": 3.0, "desc": "Отсутствие визуализации услуг снижает вовлеченность."},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Рейтинг ниже 4.5 приводит к отсечению фильтрами Яндекса."},
    "REP-27.2": {"title": "Премиальный рейтинг (4.8+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Недостаточный рейтинг для автоматического снятия возражений."},
    "REP-30.2": {"title": "Скорость ответов (<=3 дней)", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Задержка в ответах демонстрирует слабый уровень сервиса."},
    "REP-30.4": {"title": "Развернутые ответы (>80 симв.)", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Короткие отписки не насыщают карточку SEO-запросами."},
    "REP-35.1": {"title": "Отзывы с реальными фото", "group": "Репутация", "complexity": 4, "weight": 2.5, "desc": "Отсутствие пользовательского визуала снижает доверие."},
    "SEO-19.2": {"title": "Упоминание услуг в отзывах", "group": "SEO и Трафик", "complexity": 4, "weight": 2.5, "desc": "Без процедур в тексте отзывов алгоритму сложнее ранжировать карточку."},
    "PROF-08.2": {"title": "Нишевые медицинские атрибуты", "group": "SEO и Трафик", "complexity": 1, "weight": 2.5, "desc": "Не заполнены специфические особенности (ДМС, рассрочка)."},
    "PROF-09.1": {"title": "Информативность описания", "group": "Базовое заполнение", "complexity": 1, "weight": 2.5, "desc": "Слишком короткое описание — потеря площади ранжирования."},
    "PROF-11.4": {"title": "Детальные карточки услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 2.5, "desc": "Сухие названия без описаний ведут к ценовому демпингу."},
    "CONT-42.1": {"title": "Видеоконтент (рилс/тур)", "group": "Контент", "complexity": 3, "weight": 2.0, "desc": "Отсутствие видео снижает время удержания в карточке."},
    "CONV-46.1": {"title": "Кастомная обложка профиля", "group": "Конверсия", "complexity": 3, "weight": 2.0, "desc": "Стандартная панорама Яндекса делает профиль безликим."},
    "CONV-50.1": {"title": "Чат с компанией", "group": "Конверсия", "complexity": 1, "weight": 2.0, "desc": "Отключенный чат отсекает интровертов и офисных сотрудников."},
    "CONV-53.1": {"title": "Бейджи (Акции/Скидки)", "group": "Конверсия", "complexity": 2, "weight": 2.0, "desc": "Без маркетинговых меток витрина выглядит монотонно."},
    "GEO-18.4": {"title": "Точный маркер входа", "group": "SEO и Трафик", "complexity": 5, "weight": 2.0, "desc": "Неточный маркер приводит к блужданию пациентов."},
    "PROF-04.1": {"title": "Рабочая ссылка на сайт", "group": "Базовое заполнение", "complexity": 2, "weight": 2.0, "desc": "Отсутствие сайта критически снижает статус организации."},
    "PROF-05.1": {"title": "Контактный телефон", "group": "Базовое заполнение", "complexity": 2, "weight": 2.0, "desc": "Отсутствует кликабельный номер телефона."},
    "PROF-07.1": {"title": "График работы (7 дней)", "group": "Базовое заполнение", "complexity": 2, "weight": 2.0, "desc": "Неполный график отсекает визиты с острой болью в выходные."},
    "PROF-13.1": {"title": "Прямые мессенджеры", "group": "Базовое заполнение", "complexity": 1, "weight": 2.0, "desc": "Нет WhatsApp/Telegram для быстрой отправки снимков."},
    "REP-28.1": {"title": "Объем базы отзывов (50+)", "group": "Репутация", "complexity": 4, "weight": 2.0, "desc": "Массив отзывов недостаточен для прочного социального доказательства."},
    "SEO-18.3": {"title": "Топонимы в тексте", "group": "SEO и Трафик", "complexity": 4, "weight": 2.0, "desc": "Без указания метро/района карточка проигрывает гео-поиск."},
    "CONT-38.1": {"title": "Профессиональные фото интерьера", "group": "Контент", "complexity": 3, "weight": 1.5, "desc": "Мало качественных фотографий кабинетов и зоны ожидания."},
    "CONV-52.1": {"title": "Блок FAQ (Вопрос-ответ)", "group": "Конверсия", "complexity": 2, "weight": 1.5, "desc": "Не закрыты базовые страхи пациентов прямо в профиле."},
    "PROF-03.2": {"title": "Смежные рубрики (3+)", "group": "SEO и Трафик", "complexity": 1.5, "weight": 1.5, "desc": "Указана только одна рубрика, срезается смежный трафик."},
    "PROF-08.1": {"title": "Атрибуты комфорта (Парковка, Wi-Fi)", "group": "SEO и Трафик", "complexity": 1, "weight": 1.5, "desc": "Незаполненные базовые удобства исключают клинику из фильтров."},
    "PROF-12.1": {"title": "Верификация «Синяя галочка»", "group": "Базовое заполнение", "complexity": 1.5, "weight": 1.5, "desc": "Профиль лишен траста и защиты от правок конкурентами."},
    "PROF-01.1": {"title": "Чистое название (Бренд)", "group": "SEO и Трафик", "complexity": 1, "weight": 1.0, "desc": "Некорректный формат названия снижает доверие алгоритмов."},
    "PROF-01.2": {"title": "Отсутствие SEO-спама в названии", "group": "SEO и Трафик", "complexity": 1, "weight": 1.0, "desc": "Переспам ключевиками грозит санкциями модерации."},
    "PROF-03.1": {"title": "Основная рубрика", "group": "SEO и Трафик", "complexity": 1, "weight": 1.0, "desc": "Некорректная базовая рубрика."},
    "PROF-04.2": {"title": "UTM-разметка ссылок", "group": "Базовое заполнение", "complexity": 1, "weight": 1.0, "desc": "Без меток невозможно отследить реальную окупаемость профиля."},
    "PROF-15.1": {"title": "Юридические данные (ИНН, ОГРН)", "group": "Базовое заполнение", "complexity": 2, "weight": 1.0, "desc": "Скрыты реквизиты, что вызывает подозрения у умной аудитории."}
}

# ==========================================================
# 3. ТЕРМИНАЛ И УВЕДОМЛЕНИЯ
# ==========================================================

class TerminalLogger:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.logs: List[str] = []

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "🔵 [INFO]", "SUCCESS": "🟢 [SUCCESS]", 
            "WARN": "🟠 [WARN]", "ERROR": "🔴 [ERROR]", "STEP": "⚙️ [STEP]"
        }.get(level, "🔵 [INFO]")
        
        self.logs.append(f"{ts} {prefix} {msg}")
        self.placeholder.code("\n".join(self.logs), language="bash")

def send_telegram_error(error_message: str, context: str = "") -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id: return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"🚨 <b>PIN100 Ошибка</b>\n<b>Контекст:</b> {context}\n<code>{error_message}</code>"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
        return True
    except: return False

# ==========================================================
# 4. ГЛУБОКИЙ ПАРСИНГ И СКОРИНГ
# ==========================================================

def perform_deep_scoring(data: Dict[str, Any], logger: TerminalLogger) -> Tuple[float, List[Dict[str, Any]], Dict[str, float]]:
    logger.log("Запуск глубокого эвристического анализа по 41 правилу PIN100...", "STEP")
    raw_scores = {}
    
    # Извлечение массивов данных из Apify
    features_str = str(data.get("features", [])).lower()
    site_str = str(data.get("website", "") or data.get("url", "")).lower()
    reviews = data.get("reviews", [])
    working_hours = data.get("workingHours", [])
    photos_count = int(data.get("photosCount", 0)) or len(data.get("photos", []))
    items = data.get("items") or data.get("priceList") or data.get("services") or data.get("goods") or []
    rating = float(data.get("rating") or data.get("reviewsRating") or 5.0)
    rev_count = int(data.get("reviewsCount") or data.get("ratingCount") or len(reviews))
    categories = data.get("categories", [])

    # Изначально выдаем всем критериям максимальный балл, затем штрафуем за отсутствие
    for c_code, c_meta in CRITERIA_REGISTRY.items():
        raw_scores[c_code] = float(c_meta["weight"])

    # --- БЛОК: КОНВЕРСИЯ ---
    has_booking = bool(data.get("bookingUrl") or data.get("booking") or "онлайн-запис" in features_str or any(w in site_str for w in ["yclients", "medflex", "infoclinica", "prodoctorov", "booking", "stoma"]))
    if not has_booking: raw_scores["CONV-48.1"] = 0.0

    has_staff = bool(data.get("specialists") or data.get("doctors") or data.get("staff") or "врач" in features_str or "специалист" in features_str)
    if not has_staff: raw_scores["CONV-48.2"] = 0.0
    
    if "акция" not in features_str and "скидк" not in features_str: raw_scores["CONV-53.1"] = 0.0

    # --- БЛОК: БАЗОВОЕ ЗАПОЛНЕНИЕ (УСЛУГИ) ---
    if isinstance(items, list):
        if len(items) < 10: raw_scores["PROF-11.1"] = 2.0 if len(items) >= 3 else 0.0
        if len(items) < 5:  raw_scores["PROF-10.3"] = 0.0
        
        has_prices = any(bool(it.get("price") or it.get("cost")) for it in items if isinstance(it, dict))
        if not has_prices and "прайс" not in features_str: raw_scores["PROF-11.3"] = 0.0

    if not bool(data.get("isVerified") or data.get("verified") or data.get("hasBlueBadge")):
        raw_scores["PROF-12.1"] = 0.0

    if not site_str: raw_scores["PROF-04.1"] = 0.0
    if not data.get("phones"): raw_scores["PROF-05.1"] = 0.0
    
    if len(working_hours) < 7: raw_scores["PROF-07.1"] = 1.0 if len(working_hours) > 0 else 0.0
    
    if "wa.me" not in site_str and "t.me" not in site_str and "whatsapp" not in features_str:
        raw_scores["PROF-13.1"] = 0.0
        
    if len(categories) < 3: raw_scores["PROF-03.2"] = 0.75 if len(categories) == 2 else 0.0

    # --- БЛОК: РЕПУТАЦИЯ ---
    if rating < 4.8: raw_scores["REP-27.2"] = 0.0
    if rating < 4.5: raw_scores["REP-27.1"] = 0.0
    
    if rev_count < 50: raw_scores["REP-28.1"] = 1.0 if rev_count >= 15 else 0.0

    # Высчитываем % ответов клиники на отзывы
    if reviews and isinstance(reviews, list):
        replied = sum(1 for r in reviews if isinstance(r, dict) and (r.get("reply") or r.get("comments")))
        reply_rate = replied / len(reviews)
        if reply_rate < 0.9: raw_scores["REP-30.1"] = 1.5 if reply_rate >= 0.5 else 0.0
    else:
        raw_scores["REP-30.1"] = 1.5 # Средний балл, если парсер не вытянул отзывы

    # --- БЛОК: КОНТЕНТ ---
    if photos_count < 10: raw_scores["CONT-38.1"] = 0.5 if photos_count >= 5 else 0.0

    # --- ПОДСЧЕТ И ЛОГИРОВАНИЕ ---
    total_score = 0.0
    gap_list = []

    for code, meta in CRITERIA_REGISTRY.items():
        max_w = meta["weight"]
        cur_w = raw_scores[code]
        total_score += cur_w
        lost = max_w - cur_w
        
        if lost > 0.1:
            impact = lost * (6.0 - meta["complexity"])
            gap_list.append({"code": code, "title": meta["title"], "desc": meta["desc"], "impact": impact})
            logger.log(f"[{code}] {meta['title']} -> Снят балл: -{lost:.1f}", "WARN")
        else:
            logger.log(f"[{code}] {meta['title']} -> Проверка пройдена ({max_w:.1f} б)", "SUCCESS")

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]
    while len(top_3) < 3:
        top_3.append({"title": "Техническая оптимизация", "desc": "Поддерживайте актуальность данных."})

    return round(total_score, 1), top_3, raw_scores


def fetch_apify_data(target_url: str, logger: TerminalLogger) -> Dict[str, Any]:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    actor = os.getenv("APIFY_ACTOR_ID", "").strip()
    if not token or not actor:
        raise ValueError("В .env не настроены ключи APIFY_API_TOKEN и APIFY_ACTOR_ID.")

    run_url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items?token={token}&timeout=70"
    logger.log(f"Отправка URL в Apify Actor '{actor}'...", "STEP")
    
    resp = requests.post(run_url, json={"startUrls": [{"url": target_url.strip()}], "maxItems": 1, "includeReviews": True}, timeout=80)
    if resp.status_code != 201 and resp.status_code != 200:
        raise RuntimeError(f"Сбой Apify (HTTP {resp.status_code}): {resp.text[:200]}")
    
    items = resp.json()
    if not items: raise ValueError("Apify вернул пустой массив данных.")
    logger.log("Сырые данные успешно загружены из Apify.", "SUCCESS")
    return items[0]


def process_company_data(raw_input: Any, logger: TerminalLogger) -> Dict[str, Any]:
    data = raw_input[0] if isinstance(raw_input, list) and raw_input else raw_input
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        data = data["items"][0]

    title = data.get("title") or data.get("name") or "Организация"
    org_id = str(data.get("org_id") or data.get("id") or "0000000000")
    rating = float(data.get("rating") or data.get("reviewsRating") or 5.0)

    # Нормализация регистра для писем (Спейсдент -> СпейсДент сохраняем, если так в базе)
    logger.log(f"Найдена карточка: «{title}» (Рейтинг: {rating:.1f})", "INFO")

    niche = "DENTISTRY"
    low_txt = (str(title) + " " + str(data.get("categories", ""))).lower()
    if any(k in low_txt for k in ["космет", "beauty"]): niche = "COSMETOLOGY"
    elif any(k in low_txt for k in ["авто", "сервис"]): niche = "AUTOSERVICES"
    elif any(k in low_txt for k in ["медцентр"]): niche = "GENERAL_MEDICINE"

    score, top_fails, raw_scores = perform_deep_scoring(data, logger)
    
    # Принудительный оверрайд, если был готов в JSON
    if data.get("score"): score = float(data["score"])

    logger.log(f"Итоговый балл готовности: {score:.1f} / 100", "INFO")

    comps = data.get("competitors") or []
    if not isinstance(comps, list) or len(comps) < 2:
        comps = ["соседние клиники локации", "сетевые клиники района"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["DENTISTRY"])

    return {
        "title": title, "org_id": org_id, "rating": rating, "score": score, "niche": niche,
        "competitors": comps, "canonical_url": data.get("url", ""),
        "benchmark_leads": n_def["benchmark_leads"], "base_check": n_def["base_check"], 
        "ltv_months": n_def["ltv_months"], "benchmark_source": n_def["benchmark_source"],
        "top_failures": top_fails, "date": datetime.date.today().strftime("%d.%m.%Y")
    }

# ==========================================================
# 5. СИНХРОНИЗАЦИЯ, PDF И ЭКОНОМИКА
# ==========================================================

def build_metrics(audit: Dict[str, Any]) -> Dict[str, str]:
    n_info = NICHE_CONFIG[audit["niche"]]
    score = audit["score"]
    dev = max(0.0, round(100.0 - score, 1))
    
    lost_leads = int(round(audit["benchmark_leads"] * (dev / 100.0)))
    rev_loss = lost_leads * audit["base_check"]
    
    return {
        "[[TITLE]]": audit["title"], "[[NICHE]]": n_info["niche_name"], "[[DATE]]": audit["date"],
        "[[SCORE]]": f"{score:.1f}", "[[SCORE_COLOR]]": "16a34a" if score >= 80 else ("d97706" if score >= 60 else "dc2626"),
        "[[REV_LOSS_FMT]]": f"{int(rev_loss):,}".replace(",", " "),
        "[[CLIENT_LEADS]]": str(audit["benchmark_leads"]), "[[DEV]]": f"{dev:.1f}",
        "[[LOST_LEADS]]": str(lost_leads), "[[CLIENT_CHECK_FMT]]": f"{int(audit['base_check']):,}".replace(",", " "),
        "[[CLIENT_LTV]]": str(audit["ltv_months"]), "[[LTV_LOSS_FMT]]": f"{int(rev_loss * audit['ltv_months']):,}".replace(",", " "),
        "[[BENCHMARK_SOURCE]]": audit["benchmark_source"], "[[QUALITY_PHRASE]]": n_info["quality_phrase"],
        "[[WEEKLY_LOSS_FMT]]": f"{int(rev_loss / 4.33):,}".replace(",", " "),
        "[[FAIL_1_TITLE]]": audit["top_failures"][0]["title"], "[[FAIL_1_DESC]]": audit["top_failures"][0]["desc"],
        "[[FAIL_2_TITLE]]": audit["top_failures"][1]["title"], "[[FAIL_2_DESC]]": audit["top_failures"][1]["desc"],
        "[[FAIL_3_TITLE]]": audit["top_failures"][2]["title"], "[[FAIL_3_DESC]]": audit["top_failures"][2]["desc"],
    }

def compile_pdf(typ_content: str, out_path: Path, work_dir: Path, logger: TerminalLogger) -> bool:
    temp_typ = work_dir / f"temp_{out_path.stem}.typ"
    try:
        with open(temp_typ, "w", encoding="utf-8") as f: f.write(typ_content)
        if PY_TYPST_AVAILABLE:
            typst.compile(str(temp_typ), output=str(out_path))
            return True
        subprocess.run(["typst", "compile", str(temp_typ), str(out_path)], check=True)
        return True
    except Exception as e:
        logger.log(f"Ошибка компиляции Typst: {e}", "ERROR")
        return False
    finally:
        if temp_typ.exists(): temp_typ.unlink()

def sync_to_google(audit: Dict, mapping: Dict, p_pdf: Path, p_txt: Path, p_json: Path, logger: TerminalLogger) -> Dict:
    if not GOOGLE_LIBS_AVAILABLE: return {}
    creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=GDRIVE_SCOPES) if Path("credentials.json").exists() else None
    if not creds: return {}
    
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    d_str = datetime.date.today().strftime("%Y-%m-%d")

    def upload(path: Path, folder_id: str, mime: str):
        q = f"'{folder_id}' in parents and name = '{d_str}' and trashed = false"
        res = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
        fid = res[0]["id"] if res else drive.files().create(body={"name": d_str, "mimeType": "application/vnd.google-apps.folder", "parents": [folder_id]}, fields="id").execute()["id"]
        return drive.files().create(body={"name": path.name, "parents": [fid]}, media_body=MediaFileUpload(str(path), mimetype=mime), fields="webViewLink").execute().get("webViewLink", "")

    links = {
        "pdf": upload(p_pdf, GDRIVE_FOLDERS["PDF"], "application/pdf"),
        "txt": upload(p_txt, GDRIVE_FOLDERS["LETTERS"], "text/plain"),
        "json": upload(p_json, GDRIVE_FOLDERS["JSON"], "application/json")
    }
    
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if sheet_id:
        row = [mapping["[[DATE]]"], datetime.datetime.now().strftime("%H:%M:%S"), audit["title"], audit["org_id"], audit["canonical_url"], audit["niche"], audit["rating"], mapping["[[SCORE]]"], mapping["[[LOST_LEADS]]"], mapping["[[REV_LOSS_FMT]]"], links["pdf"], links["txt"], links["json"]]
        sheets.spreadsheets().values().append(spreadsheetId=sheet_id, range="Лист1!A:M", valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
    return links

# ==========================================================
# 6. КОНВЕЙЕР И СТРИМЛИТ ИНТЕРФЕЙС
# ==========================================================

def run_pipeline(raw_data: Any, logger: TerminalLogger):
    try:
        # 1. Парсинг
        audit = process_company_data(raw_data, logger)
        st.session_state.current_audit = audit
        mapping = build_metrics(audit)
        st.session_state.current_mapping = mapping

        # 2. Письмо
        logger.log("Генерация письма Icebreaker...", "STEP")
        c_str = f"«{audit['competitors'][0]}» и «{audit['competitors'][1]}»" if "сосед" not in audit['competitors'][0].lower() else "соседние клиники локации"
        ll = int(mapping["[[LOST_LEADS]]"])
        ib_txt = f"Добрый день!\n\nАнализировали выдачу в вашем районе и обратили внимание на карточку «{audit['title']}». При сильной репутации ({audit['rating']:.1f}) первичный поток перехватывают {c_str}.\n\nНа поверхности лежат пара недочетов (например, пациенты вечером не могут записаться в 1 клик и уходят к соседям). По емкости района это отток около {max(1, ll-2)}–{ll+3} пациентов в месяц.\n\nСобрали наглядный разбор карточки и расчет потерь в PDF на 4 страницы. Скинуть файл для ознакомления?"
        st.session_state.current_icebreaker = ib_txt

        # 3. Файлы и компиляция
        logger.log("Компиляция PDF-отчета...", "STEP")
        out_dir = Path("output"); out_dir.mkdir(exist_ok=True)
        prefix = f"{re.sub(r'[^a-zA-Z0-9а-яА-Я]', '_', audit['title'])}_{audit['org_id']}"
        p_pdf, p_txt, p_json = out_dir / f"{prefix}.pdf", out_dir / f"{prefix}.txt", out_dir / f"{prefix}.json"
        
        with open(p_txt, "w", encoding="utf-8") as f: f.write(ib_txt)
        with open(p_json, "w", encoding="utf-8") as f: json.dump(audit, f, ensure_ascii=False)
        
        tpl = Path("report_template.typ")
        if tpl.exists():
            with open(tpl, "r", encoding="utf-8") as f: content = f.read()
            for k, v in mapping.items(): content = content.replace(k, str(v))
            if compile_pdf(content, p_pdf, out_dir, logger):
                st.session_state.pdf_path = str(p_pdf)
                logger.log("PDF успешно скомпилирован.", "SUCCESS")
        else:
            logger.log("Шаблон report_template.typ не найден!", "ERROR")

        # 4. Google Drive
        logger.log("Выгрузка результатов на Google Диск...", "STEP")
        st.session_state.drive_links = sync_to_google(audit, mapping, p_pdf, p_txt, p_json, logger)
        if st.session_state.drive_links: logger.log("Файлы успешно загружены в облако.", "SUCCESS")
        
        logger.log("КОНВЕЙЕР УСПЕШНО ЗАВЕРШЕН!", "SUCCESS")

    except Exception as ex:
        logger.log(f"Критическая ошибка: {ex}", "ERROR")
        send_telegram_error(str(ex), "Pipeline Run")

def app():
    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    tab_json, tab_url = st.tabs(["📋 Загрузить JSON", "🔗 Ссылка (Apify API)"])

    with tab_json:
        col1, col2 = st.columns([1, 2])
        file = col1.file_uploader("Файл .json из Apify:", type=["json"])
        txt = col2.text_area("Или код JSON:", height=100)
        btn_json = st.button("🚀 Запустить конвейер по JSON", type="primary", use_container_width=True)

    with tab_url:
        url = st.text_input("Ссылка на Яндекс Карты:")
        btn_url = st.button("🚀 Запустить краулинг и конвейер", type="primary", use_container_width=True)

    st.subheader("🖥️ Терминал выполнения конвейера (Live Diagnostics)")
    logger = TerminalLogger(st.empty())

    if btn_json:
        data = json.load(file) if file else (json.loads(txt) if txt.strip() else None)
        if data: run_pipeline(data, logger)
        else: logger.log("Нет данных для анализа.", "ERROR")
    
    if btn_url and url.strip():
        try:
            data = fetch_apify_data(url, logger)
            run_pipeline(data, logger)
        except Exception as e:
            logger.log(str(e), "ERROR")

    # ВЫДАЧА
    if st.session_state.get("current_audit"):
        st.divider()
        c1, c2 = st.columns([1.1, 0.9])
        map_d = st.session_state.current_mapping
        aud = st.session_state.current_audit

        with c1:
            st.subheader("✉️ Первое сообщение (Icebreaker)")
            st.text_area("Текст:", value=st.session_state.current_icebreaker, height=200)
            st.markdown("**Топ-3 уязвимости:**")
            for i, f in enumerate(aud["top_failures"], 1):
                st.markdown(f"**{i}. {f['title']}**\n<small>{f['desc']}</small>", unsafe_allow_html=True)

        with c2:
            st.subheader(f"📊 Экономика потерь «{aud['title']}»")
            m1, m2 = st.columns(2)
            m1.metric("Балл", f"{map_d['[[SCORE]]']} / 100")
            m2.metric("Потери", f"~{map_d['[[LOST_LEADS]]']} чел/мес")
            m3, m4 = st.columns(2)
            m3.metric("Упущенная выручка", f"{map_d['[[REV_LOSS_FMT]]']} ₽/мес")
            m4.metric("Потери за неделю", f"~{map_d['[[WEEKLY_LOSS_FMT]]']} ₽/нед")
            
            st.divider()
            st.subheader("📄 PDF-отчет")
            if st.session_state.get("pdf_path"):
                with open(st.session_state.pdf_path, "rb") as f:
                    st.download_button("📥 Скачать PDF", f, Path(st.session_state.pdf_path).name, "application/pdf", type="primary", use_container_width=True)
            
            dl = st.session_state.get("drive_links")
            if dl:
                st.success("✅ Сохранено на Google Drive!")
                st.markdown(f"[📄 PDF]({dl.get('pdf')}) | [✉️ Письмо]({dl.get('txt')}) | [⚙️ JSON]({dl.get('json')})")

if __name__ == "__main__":
    app()
