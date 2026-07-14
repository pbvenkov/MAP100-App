import streamlit as st
import requests
import time
import json
import numpy as np
import pandas as pd
import re
import itertools
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Настройка ИИ 
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-3.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден. AI-функции отключены.")
    ai_model = None

def send_telegram_alert(message):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
        except Exception:
            pass

# ==========================================
# 2. ПАРСЕР GOOGLE ТАБЛИЦЫ И APIFY
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(credentials).open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка Google Sheets: {e}")
        st.stop()

def get_rules_from_sheets():
    doc = init_google_sheets()
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    for r in records:
        raw_val = r.get('Балл', 0.0)
        try:
            if isinstance(raw_val, (int, float)): r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError: r['Балл'] = 0.0
        r['Статус'] = str(r.get('Статус', 'Заглушка')).strip()
    return records

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: raise Exception(f"Ошибка Apify: {run_req['error']}")
    
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception("⏱ Таймаут парсера.")
        time.sleep(5)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
        status = status_req['data']['status']
        retries += 1
    if status != "SUCCEEDED": raise Exception("Парсер завершился с ошибкой.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or len(dataset) == 0: raise Exception("Нет данных (пустой ответ).")
    return dataset[0]

# ==========================================
# 3. ЛОГИКА АНАЛИЗА
# ==========================================
def get_safe_list(data, keys):
    result = []
    for k in keys:
        val = data.get(k)
        if isinstance(val, list): result.extend(val)
        elif isinstance(val, dict): result.append(val)
    return result

def calculate_ai_rules(data):
    scores, logs = {}, []
    if ai_model is None: return scores, logs, "Модель ИИ отключена."
    
    prompt = f"""
    Проанализируй данные: Название "{data.get('title')}", Описание "{data.get('description')}".
    Верни JSON с ключами:
    PROF-10.6, PROF-10.3, CONV-49.1, SEO-18.3, PROF-10.4, CONV-49.2, PROF-01.2, REP-31.2, CONV-52.2, PROF-02.1, PROF-03.2, SEO-17.1, SEO-17.2, SEO-17.3, CONV-49.4, SEO-19.1, SEO-19.2, SEO-21.2.
    Значения: true или false. Только JSON.
    """
    try:
        response = ai_model.generate_content(prompt)
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            ai_res = json.loads(json_match.group(0))
            mapping = {
                "PROF-10.6": "Призыв к действию", "PROF-10.3": "Конкретика услуг", 
                "CONV-49.1": "Сильное УТП", "SEO-18.3": "Топонимы в тексте", 
                "PROF-10.4": "Факты/преимущества", "CONV-49.2": "Цифры в описании",
                "PROF-01.2": "Чистый бренд", "REP-31.2": "Корпоративный ToV", 
                "CONV-52.2": "FAQ снимает страхи", "PROF-02.1": "Категория совпадает",
                "PROF-03.2": "Нет мусорных категорий", "SEO-17.1": "Целевые ключи",
                "SEO-17.2": "Текст читаем", "SEO-17.3": "LSI-семантика",
                "CONV-49.4": "Релевантность болям", "SEO-19.1": "Ключи в ответах",
                "SEO-19.2": "Услуги в отзывах", "SEO-21.2": "SEO в товарах"
            }
            for code, name in mapping.items():
                if ai_res.get(code):
                    scores[code] = True
                    logs.append(f"✅ [{code}] AI: {name}")
    except Exception as e:
        return {}, [], str(e)
    return scores, logs, None

def calculate_all_python_rules(data):
    scores, logs = {}, []
    ai_scores, ai_logs, ai_err = calculate_ai_rules(data)
    scores.update(ai_scores)
    logs.extend(ai_logs)
    return scores, logs, ai_err

# ==========================================
# 4. ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title="MAP100 | Нейро-Аудитор", layout="wide")
st.title("📍 MAP100: AI-Аудитор (Версия 10.1 - Исправлено)")

yandex_url = st.text_input("Ссылка на карточку Яндекс.Бизнеса")
if st.button("🚀 Запустить аудит"):
    try:
        data = fetch_apify_data(yandex_url)
        scores, logs, err = calculate_all_python_rules(data)
        if err: st.error(err)
        
        # Вывод результатов (сокращено для экономии места)
        st.write("Аудит завершен!")
        st.dataframe(pd.DataFrame({"Код": list(scores.keys()), "Статус": ["Выполнено"] * len(scores)}))
    except Exception as e:
        st.error(f"Ошибка: {e}")
