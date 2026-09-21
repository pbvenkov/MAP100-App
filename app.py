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
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

st.set_page_config(page_title="PIN100 Analytics", page_icon="📍", layout="wide")

# ==========================================================
# 1. КОНФИГУРАЦИЯ СИСТЕМЫ И БЕНЧМАРКИ
# ==========================================================

GDRIVE_SCOPES = ["[https://www.googleapis.com/auth/spreadsheets](https://www.googleapis.com/auth/spreadsheets)"]
CRITERIA_SHEET_ID = "1NUuGhHn3H-GrgfLnnJoY1Paz8vvl_5E9AUu0QyxweVY"
CRITERIA_RANGE = "Rules!A:Z"

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "company_word": "клиники",
        "client_word": "пациент",
        "client_word_plural": "пациенты",
        "client_word_genitive_plural": "пациентов",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat («Анализ рынка стоматологии РФ») и РБК",
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "company_word": "клиники",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4800,
        "ltv_months": 10,
        "benchmark_source": "РБК («Российский рынок эстетической медицины»)",
    },
    "BEAUTY": {
        "niche_name": "Парикмахерская / Барбершоп",
        "niche_genitive": "салонов красоты",
        "company_word": "салона",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "мастерства стилистов и уровня сервиса",
        "benchmark_leads": 150,
        "base_check": 1800,
        "ltv_months": 6,
        "benchmark_source": "РБК («Российский рынок бьюти-услуг»)",
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "company_word": "медцентра",
        "client_word": "пациент",
        "client_word_plural": "пациенты",
        "client_word_genitive_plural": "пациентов",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3900,
        "ltv_months": 12,
        "benchmark_source": "BusinesStat и НАФИ",
    },
    "OTHER": {
        "niche_name": "Локальный бизнес",
        "niche_genitive": "конкурентов",
        "company_word": "организации",
        "client_word": "клиент",
        "client_word_plural": "клиенты",
        "client_word_genitive_plural": "клиентов",
        "quality_phrase": "качества услуг и клиентского сервиса",
        "benchmark_leads": 50,
        "base_check": 2000,
        "ltv_months": 3,
        "benchmark_source": "Усредненные данные локального поиска",
    }
}

FALLBACK_CRITERIA_REGISTRY = {
    "CONV-48.1": {"title": "Онлайн-запись на приём", "group": "Конверсия", "complexity": 2, "weight": 6.0, "descs": {"Обоснование_ОШИБКИ": "Отсутствие прямой онлайн-записи отсекает до 60% вечернего спроса."}},
    "PROF-10.3": {"title": "Структура услуг в описании", "group": "Базовое заполнение", "complexity": 1, "weight": 4.0, "descs": {"Обоснование_ОШИБКИ": "В описании нет четкой структуры процедур."}},
    "REP-27.1": {"title": "Базовый порог рейтинга (4.5+)", "group": "Репутация", "complexity": 4, "weight": 2.5, "descs": {"Обоснование_ОШИБКИ": "Рейтинг ниже 4.5 приводит к отсечению фильтрами."}},
    "PROF-11.3": {"title": "Цены у товаров и услуг", "group": "Базовое заполнение", "complexity": 1, "weight": 3.5, "descs": {"Обоснование_ОШИБКИ": "Слепой прайс отпугивает страхом скрытых накруток."}}
}

# ==========================================================
# 2. УНИВЕРСАЛЬНАЯ АВТОРИЗАЦИЯ GOOGLE
# ==========================================================

def get_google_credentials() -> Tuple[Any, str]:
    if not GOOGLE_LIBS_AVAILABLE:
        return None, "Библиотеки Google API не установлены."
    
    creds_data = st.secrets.get("GCP_CREDENTIALS") or st.secrets.get("GOOGLE_CREDENTIALS")
    if creds_data:
        try:
            creds_dict = json.loads(creds_data) if isinstance(creds_data, str) else dict(creds_data)
            creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка парсинга секретов Google: {e}"
            
    creds_file = Path("credentials.json")
    if creds_file.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(str(creds_file), scopes=GDRIVE_SCOPES)
            return creds, "OK"
        except Exception as e:
            return None, f"Ошибка чтения локального файла ключей: {e}"
            
    return None, "Ключи доступа не найдены ни в Secrets, ни в файле."

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_criteria_from_google() -> Tuple[Dict[str, Dict[str, Any]], str]:
    creds, status = get_google_credentials()
    if not creds:
        return FALLBACK_CRITERIA_REGISTRY, status

    try:
        sheets = build("sheets", "v4", credentials=creds)
        result = sheets.spreadsheets().values().get(spreadsheetId=CRITERIA_SHEET_ID, range=CRITERIA_RANGE).execute()
        rows = result.get('values', [])

        if not rows or len(rows) < 2:
            return FALLBACK_CRITERIA_REGISTRY, "Таблица пуста или не найден лист Rules."

        headers = [str(h).strip() for h in rows[0]]
        try:
            idx_code = headers.index("Код")
            idx_title = headers.index("Критерий")
            idx_group = headers.index("Группа метрик")
            idx_weight = headers.index("Балл")
        except ValueError as e:
            return FALLBACK_CRITERIA_REGISTRY, f"В таблице не найден обязательный столбец: {e}"

        desc_cols = {h: i for i, h in enumerate(headers) if h.startswith("Обоснование_ОШИБКИ")}
        registry = {}

        for row in rows[1:]:
            if
