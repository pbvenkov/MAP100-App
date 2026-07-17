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

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-3.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден. AI отключен.")
    ai_model = None

# ==========================================
# 2. ПАРСЕР GOOGLE ТАБЛИЦЫ И APIFY
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception(f"Таймаут парсера. Логи: https://console.apify.com/actors/runs/{run_id}")
        time.sleep(5)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception(f"Парсер упал со статусом {status}.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or len(dataset) == 0: raise Exception(f"Парсер отработал, но Яндекс не отдал данные.")
    return dataset[0]

# ==========================================
# 3. СБОРКА И ИНТЕРФЕЙС (РЕЖИМ ДЕТЕКТИВА)
# ==========================================
st.set_page_config(page_title="MAP100 | Поиск конкурентов", layout="wide", page_icon="🕵️")

st.title("📍 MAP100: Режим поиска конкурентов (Версия 11.9)")
st.write("Этот режим временно останавливает аудит, чтобы показать структуру сырых данных от Яндекса.")

url = st.text_input("Ссылка на Яндекс.Бизнес")

if st.button("🚀 Найти структуру данных", type="primary"):
    if "yandex" not in url.lower(): 
        st.error("❌ Неверная ссылка.")
    else:
        with st.spinner("Сбор данных от Яндекса..."):
            try:
                data = fetch_apify_data(url)
                
                # === БЛОК ДЕТЕКТИВА ===
                st.success("✅ Данные успешно получены!")
                st.subheader("1. Главные ключи (папки) в ответе:")
                st.write(list(data.keys()))
                
                # Пробуем угадать, где могут быть конкуренты
                suspicious_keys = [k for k in data.keys() if any(word in k.lower() for word in ['similar', 'related', 'nearby', 'competitor', 'chain', 'recommend'])]
                
                if suspicious_keys:
                    st.warning(f"🚨 Подозрительные ключи, где могут прятаться конкуренты: {suspicious_keys}")
                    for key in suspicious_keys:
                        with st.expander(f"Содержимое ключа: {key}"):
                            st.json(data[key])
                else:
                    st.info("Очевидных ключей с конкурентами не найдено. Давайте заглянем внутрь всего ответа.")
                    
                st.subheader("2. Полный сырой ответ парсера (JSON):")
                with st.expander("Развернуть полный JSON", expanded=False):
                    st.json(data)
                
                st.stop() # Останавливаем выполнение кода здесь
                # =======================

            except Exception as e:
                st.error(f"Произошла ошибка: {e}")
