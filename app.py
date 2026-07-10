import streamlit as st
import requests
import time
import json
import numpy as np
from datetime import datetime
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И КЛЮЧЕЙ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. КЭШИРОВАННЫЕ БАЗОВЫЕ ФУНКЦИИ
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        return gc.open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        st.stop()

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_payload = {"startUrls": [{"url": yandex_url}], "maxItems": 1}
    run_req = requests.post(run_url, json=run_payload)
    run_data = run_req.json()

    if 'error' in run_data:
        raise Exception(run_data['error'])

    run_id = run_data['data']['id']
    default_dataset_id = run_data['data']['defaultDatasetId']

    status = "RUNNING"
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        time.sleep(5)
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}"
        status = requests.get(status_url).json()['data']['status']

    if status != "SUCCEEDED":
        raise Exception("Ошибка при парсинге данных Apify.")

    dataset_url = f"https://api.apify.com/v2/datasets/{default_dataset_id}/items?token={APIFY_API_TOKEN}"
    dataset_req = requests.get(dataset_url).json()
    
    if not dataset_req:
        raise Exception("Парсер не нашел данных.")
        
    return dataset_req[0]

# ==========================================
# 3. ГИБРИДНАЯ АРХИТЕКТУРА: PYTHON
# ==========================================
def calculate_python_scores(data):
    """Считает баллы по объективным метрикам без ИИ."""
    scores = {}
    details = []

    if len(data.get('title', '')) > 2:
        scores['PROF-01.1'] = 0.5
        
    if len(data.get('phones', [])) > 0:
        scores['PROF-05.1'] = 1.0

    if len(data.get('schedule', [])) == 7:
        scores['PROF-07.1'] = 1.0

    if data.get('isVerifiedOwner') == True:
        scores['PROF-12.1'] = 3.0
        details.append("✅ [PROF-12.1] Аккаунт верифицирован (Синяя галочка) (+3.0)")
    else:
        scores['PROF-12.1'] = 0.0
        details.append("❌ [PROF-12.1] Отсутствует Синяя галочка (0.0)")

    photo_count = data.get('photoCount', 0)
    if photo_count >= 15:
        scores['CONT-36.1'] = 1.5
        if photo_count >= 30:
            scores['CONT-36.2'] = 1.0
        details.append(f"✅ [CONT-36] Хорошая галерея: {photo_count} фото.")
    else:
        details.append(f"❌ [CONT-36] Мало фото: {photo_count} (нужно от 15).")

    products = data.get('menu', {}).get('items', [])
    if not products:
        products = data.get('productCatalog', [])
        
    if len(products) >= 10:
        scores['PROF-11.1'] = 1.5
        details.append(f"✅ [PROF-11.1] Каталог заполнен: {len(products)} позиций (+1.5)")
    else:
        details.append(f"❌ [PROF-11.1] Мало товаров/услуг в каталоге: {len(products)} из 10.")

    rating = data.get('rating', 0)
    if rating >= 4.8:
        scores['REP-27.2'] = 2.0
        scores['REP-27.1'] = 2.0
    elif rating >= 4.5:
        scores['REP-27.1'] = 2.0

    reviews_count = data.get('ratingsCount', 0)
    if reviews_count >= 50:
        scores['REP-28.1'] = 2.0

    reviews_data = data.get('reviews', [])
    response_times = []
    
    for rev in reviews_data:
        if rev.get("businessComment") and rev.get("date") and rev.get("businessCommentDate"):
            try:
                r_date = datetime.strptime(rev["date"][:19], "%Y-%m-%dT%H:%M:%S")
                c_date = datetime.strptime(rev["businessCommentDate"][:19], "%Y-%m-%dT%H:%M:%S")
                response_times.append((c_date - r_date).days)
            except Exception:
                pass
                
    if response_times:
        median_speed = np.median(response_times)
        if median_speed <= 3:
            scores['REP-30.2'] = 2.0
            details.append(f"✅ [REP-30.2] Медиана ответов: {median_speed} дн. (+2.0)")
        else:
            details.append(f"❌ [REP-30.2] Медленные ответы: {median_speed} дн. (
