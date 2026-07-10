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
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" # Комбайн: Профиль + Отзывы

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
# 3. ГИБРИДНАЯ АРХИТЕКТУРА: PYTHON (80% работы)
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
            details.append(f"❌ [REP-30.2] Медленные ответы: {median_speed} дн. (норма < 3).")

    return sum(scores.values()), details

def trim_for_ai(raw_data):
    """Сжимает профиль Яндекса до текстовой выжимки для Gemini."""
    trimmed = {
        "title": raw_data.get("title", ""),
        "description": raw_data.get("description", ""),
        "categories": raw_data.get("categories", []),
        "features": list(raw_data.get("features", {}).keys()),
        "products": [],
        "reviews": []
    }
    
    products = raw_data.get('menu', {}).get('items', [])
    if products:
        trimmed["products"] = [p.get("title", "") for p in products[:15]]
    
    for r in raw_data.get("reviews", [])[:10]:
        trimmed["reviews"].append({
            "text": r.get("text", ""),
            "rating": r.get("rating", ""),
            "owner_reply": r.get("businessComment", "")
        })
    return trimmed

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Гибридный Аудит", page_icon="📍", layout="wide")

st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию. Повторные проверки мгновенны (из кэша).")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

# Кнопка для разработчика
if st.button("🛠 Скачать сырой JSON (для разработки)", type="secondary"):
    if yandex_url:
        with st.spinner("Забираем данные..."):
            raw = fetch_apify_data(yandex_url) 
            st.download_button(
                label="📥 Скачать yandex_raw_data.json",
                file_name="yandex_raw_data.json",
                mime="application/json",
                data=json.dumps(raw, ensure_ascii=False, indent=4),
            )

# БОЕВОЙ АУДИТ
if st.button("🚀 Запустить аудит", type="primary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        doc = init_google_sheets()
        
        # ЧТЕНИЕ ПРАВИЛ
        with st.spinner("Шаг 0: Читаем правила MAP100 из Google Таблиц..."):
            rules_data = doc.worksheet("Rules").get_all_records()
            dynamic_rules = "".join([f"- [{r['Код']}] {r['Критерий']} (Макс {r['Балл']}): {r['Инструкция для ИИ']}\n" for r in rules_data if r.get('Код')])

        # СБОР ДАННЫХ И PYTHON-ОЦЕНКА
        with st.spinner("Шаг 1: Python анализирует объективные данные..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                
                # Математика Python
                python_score, python_details = calculate_python_scores(raw_yandex_data)
                
                # Подготовка к ИИ
                clean_data = trim_for_ai(raw_yandex_data)
                
            except Exception as e:
                st.error(f"Ошибка сбора данных: {e}")
                st.stop()

        # АНАЛИЗ GEMINI
        with st.spinner("Шаг 2: Gemini анализирует тексты, SEO и смыслы..."):
            try:
                SYSTEM_INSTRUCTION = f"""
                Ты — эксперт по локальному SEO. Мы проводим аудит карточки Яндекс.Бизнеса по 100-балльной системе MAP100.
                МЫ ИСПОЛЬЗУЕМ ГИБРИДНУЮ АРХИТЕКТУРУ. 
                
                Автоматический скрипт УЖЕ проверил объективные параметры (график, галочки, фото) и начислил {python_score} баллов.
                Вот лог его проверки:
                {chr(10).join(python_details)}
                
                Твоя задача — проверить карточку по оставшимся ПРАВИЛАМ (эмоции, SEO-ключи, смыслы УТП, ответы на отзывы):
                {dynamic_rules}
                
                Оцени предоставленный текстовый JSON. Если данных нет, ставь 0 за критерий.
                СЛОЖИ баллы скрипта ({python_score}) и свои заработанные баллы.
                ВЕРНИ ОТВЕТ СТРОГО В ФОРМАТЕ JSON без markdown разметки:
                {{
                    "company_name": "", 
                    "business_niche": "", 
                    "total_score": <ЗДЕСЬ СУММА БАЛЛОВ PYTHON + ТВОИ БАЛЛЫ>, 
                    "detailed_report": "Общий аналитический вывод. Упомяни и находки автоматического скрипта, и свой семантический анализ текстов.", 
                    "action_plan": ["шаг 1", "шаг 2", "шаг 3"]
                }}
                """
                
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
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
