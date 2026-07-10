import streamlit as st
import requests
import time
import json
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И КЛЮЧЕЙ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-reviews-scraper"

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. КЭШИРОВАННЫЕ БАЗОВЫЕ ФУНКЦИИ
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        # Читаем сырой текст ключа и превращаем в JSON
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        return gc.open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка подключения к базе данных Google Sheets: {e}")
        st.stop()

# КЭШ НА 24 ЧАСА: Повторные проверки той же ссылки будут мгновенными
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
        status_req = requests.get(status_url).json()
        status = status_req['data']['status']

    if status != "SUCCEEDED":
        raise Exception("Ошибка при парсинге данных Apify.")

    dataset_url = f"https://api.apify.com/v2/datasets/{default_dataset_id}/items?token={APIFY_API_TOKEN}"
    dataset_req = requests.get(dataset_url).json()
    
    if not dataset_req:
        raise Exception("Парсер не нашел данных по этой ссылке.")
        
    return dataset_req[0]

# ==========================================
# 3. ФУНКЦИЯ ОЧИСТКИ (TRIMMER) ДЛЯ ЭКОНОМИИ ТОКЕНОВ
# ==========================================
def trim_for_ai(raw_data):
    """Удаляет 95% системного мусора из JSON, оставляя только нужную SEO-суть"""
    trimmed = {
        "name": raw_data.get("name", ""),
        "description": raw_data.get("description", ""),
        "rating": raw_data.get("rating", ""),
        "reviewsCount": raw_data.get("reviewsCount", ""),
        "categories": raw_data.get("categories", []),
        "website": raw_data.get("website", ""),
        "phones": raw_data.get("phones", []),
        "workingHours": raw_data.get("workingHours", []),
        "attributes": raw_data.get("attributes", []), 
        "is_verified": raw_data.get("is_verified", False),
        "photo_count": len(raw_data.get("photos", [])),
        "reviews": []
    }
    
    # Берем только 10 последних отзывов (Текст + Ответ владельца)
    raw_reviews = raw_data.get("reviews", [])
    for r in raw_reviews[:10]:
        trimmed_rev = {
            "text": r.get("text", ""),
            "rating": r.get("rating", ""),
            "owner_reply": r.get("ownerResponse", {}).get("text", "") if r.get("ownerResponse") else ""
        }
        if trimmed_rev["text"] or trimmed_rev["owner_reply"]:
            trimmed["reviews"].append(trimmed_rev)
            
    return trimmed

# ==========================================
# 4. ИНТЕРФЕЙС STREAMLIT И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Гибридный Аудит", page_icon="📍", layout="wide")

st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию. Повторные проверки осуществляются мгновенно из кэша.")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

# --- КНОПКА №1: ДЛЯ РАЗРАБОТЧИКА (БЕЗ ИСПОЛЬЗОВАНИЯ ИИ) ---
if st.button("🛠 Скачать сырой JSON (для разработки)", type="secondary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        with st.spinner("Забираем полные данные из Apify..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url) 
                json_string = json.dumps(raw_yandex_data, ensure_ascii=False, indent=4)
                
                st.success("✅ Данные получены! Нажмите кнопку ниже, чтобы скачать файл.")
                st.download_button(
                    label="📥 Скачать yandex_raw_data.json",
                    file_name="yandex_raw_data.json",
                    mime="application/json",
                    data=json_string,
                )
            except Exception as e:
                st.error(f"Ошибка получения данных: {e}")

# --- КНОПКА №2: ГЛАВНЫЙ БОЕВОЙ АУДИТ ---
if st.button("🚀 Запустить аудит", type="primary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        doc = init_google_sheets()
        
        # ЧТЕНИЕ ПРАВИЛ
        with st.spinner("Шаг 0: Читаем правила MAP100 из Google Таблиц..."):
            rules_sheet = doc.worksheet("Rules")
            rules_data = rules_sheet.get_all_records()
            dynamic_rules = ""
            for row in rules_data:
                if row.get('Код') and row.get('Критерий'):
                    dynamic_rules += f"- [{row['Код']}] {row['Критерий']} (Макс. балл {row['Балл']}): {row['Инструкция для ИИ']}\n"

        # ПАРСИНГ И ОЧИСТКА
        with st.spinner("Шаг 1: Собираем данные (или берем из кэша)..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                clean_data = trim_for_ai(raw_yandex_data)
                
                # Показываем вес в байтах, чтобы избежать нулей
                original_size = len(json.dumps(raw_yandex_data))
                clean_size = len(json.dumps(clean_data))
                st.success(f"✅ Данные готовы! Оптимизировано с {original_size} байт до {clean_size} байт.")
                
            except Exception as e:
                st.error(f"Ошибка сбора данных: {e}")
                st.stop()

        # АНАЛИЗ GEMINI
        with st.spinner("Шаг 2: Gemini анализирует оптимизированные данные..."):
            try:
                SYSTEM_INSTRUCTION = f"""
                Ты — эксперт по локальному SEO. Проведи аудит карточки Яндекс.Бизнеса СТРОГО по правилам MAP100.
                
                ПРАВИЛА И ВЕСА БАЛЛОВ:
                {dynamic_rules}
                
                ИНСТРУКЦИЯ:
                Данные были предварительно очищены от мусора. Если информации для проверки конкретного критерия нет в JSON — смело ставь за него 0 баллов. Оцени только то, что видишь.
                Верни ответ СТРОГО в формате JSON без markdown разметки:
                {{
                    "company_name": "", 
                    "business_niche": "", 
                    "total_score": 0.0, 
                    "detailed_report": "Общий вывод по главным ошибкам.", 
                    "action_plan": ["шаг 1", "шаг 2"]
                }}
                """
                
                # Используем стабильную модель (лимиты сбросятся в 10:00 МСК)
                model = genai.GenerativeModel(
                    model_name="gemini-2.0-flash", 
                    system_instruction=SYSTEM_INSTRUCTION,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )

                prompt = f"Данные для аудита:\n{json.dumps(clean_data, ensure_ascii=False)}"
                response = model.generate_content(prompt)
                
                ai_report = json.loads(response.text)
                st.success("✅ Анализ завершен!")
                
                # ВЫВОД ОТЧЕТА НА ЭКРАН
                st.divider()
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(f"🏢 {ai_report.get('company_name', 'Без названия')}")
                    st.caption(f"Ниша: {ai_report.get('business_niche', 'Не определена')}")
                with col2:
                    score = ai_report.get('total_score', 0)
                    if score >= 80: color = "normal"
                    elif score >= 50: color = "off"
                    else: color = "inverse"
                    st.metric("Общий балл MAP100", f"{score} / 100", delta_color=color)

                st.divider()
                st.markdown("### 🔍 Общий аналитический отчет")
                st.write(ai_report.get('detailed_report', 'Отчет пуст'))
                    
                st.markdown("### 🛠 Пошаговый план исправлений")
                for i, step in enumerate(ai_report.get('action_plan', [])):
                    st.info(f"**Шаг {i+1}:** {step}")

                # ЗАПИСЬ В ТАБЛИЦУ
                try:
                    results_sheet = doc.worksheet("Results")
                    new_row = [
                        time.strftime("%d.%m.%Y %H:%M:%S"), 
                        yandex_url,                         
                        ai_report.get('company_name', ''),  
                        ai_report.get('business_niche', ''),
                        ai_report.get('total_score', 0)     
                    ]
                    results_sheet.append_row(new_row)
                    st.toast('Успешно сохранено в Google Таблицу!', icon='💾')
                except Exception as e:
                    st.warning(f"Ошибка записи в таблицу: {e}")

            except Exception as e:
                st.error(f"⚠️ Ошибка связи с ИИ: {e}")
