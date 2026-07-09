import streamlit as st
import requests
import time
import json
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# ==========================================
# 1. НАСТРОЙКИ КЛЮЧЕЙ API И БАЗЫ ДАННЫХ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-reviews-scraper"

# ВСТАВЬТЕ СЮДА ПОЛНУЮ ССЫЛКУ НА ВАШУ ГУГЛ ТАБЛИЦУ
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1eQIlPiXZLAeHBPRj6_imnJCho5FB3IijoQc7jVYhazQ/edit"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite", 
    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
)

# ==========================================
# 2. ФУНКЦИЯ ЗАГРУЗКИ ПРАВИЛ ИЗ GOOGLE SHEETS
# ==========================================
@st.cache_data(ttl=600) # Кэшируем на 10 минут, чтобы сайт работал быстро
def load_map100_rules():
    # Загружаем секретный ключ
    creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    # Подключаемся к Гугл Таблице
    gc = gspread.authorize(credentials)
    sh = gc.open_by_url(GOOGLE_SHEET_URL)
    worksheet = sh.worksheet("Rules") # Читаем лист Rules
    
    # Возвращаем все строки как список словарей
    return worksheet.get_all_records()

# ==========================================
# 3. ИНТЕРФЕЙС STREAMLIT
# ==========================================
st.set_page_config(page_title="MAP100 | Аудит Яндекс.Карт", page_icon="📍", layout="wide")

st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию в Яндекс.Картах, чтобы получить детальный разбор по 94 критериям.")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

if st.button("🚀 Запустить аудит", type="primary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        # --- ЭТАП А: ПАРСИНГ ---
        with st.spinner("Шаг 1: Парсим данные из Яндекс.Карт..."):
            try:
                run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
                run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1})
                run_data = run_req.json()
                
                if 'error' in run_data:
                    st.error(f"❌ Ошибка Apify: {run_data['error']}")
                    st.stop()
                    
                run_id = run_data['data']['id']
                
                status = "RUNNING"
                while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
                    time.sleep(5)
                    status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
                    status = status_req['data']['status']
                    
                dataset_id = status_req['data']['defaultDatasetId']
                dataset_req = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
                raw_yandex_data = dataset_req[0]
                st.success("✅ Данные собраны!")
            except Exception as e:
                st.error(f"Ошибка Apify: {e}")
                st.stop()

        # --- ЭТАП Б: СБОРКА ПРОМПТА И АНАЛИЗ ИИ ---
        with st.spinner("Шаг 2: ИИ анализирует карточку по базе MAP100..."):
            try:
                rules = load_map100_rules()
                
                # Формируем динамический системный промпт из Гугл Таблицы
                sys_prompt = "Ты — ведущий эксперт по локальному SEO. Твоя задача — аудит JSON-данных строго по методике MAP100.\n\nКРИТЕРИИ ОЦЕНКИ:\n"
                for r in rules:
                    if r.get('Код'): # Защита от пустых строк
                        sys_prompt += f"- [{r['Код']}] {r['Критерий']} (Макс. балл: {r['Балл']}): {r['Инструкция для ИИ']}\n"
                
                sys_prompt += """
                \nВЕРНИ ОТВЕТ СТРОГО В ФОРМАТЕ JSON:
                {
                  "company_name": "Название",
                  "business_niche": "Ниша",
                  "total_score": 0.0,
                  "critique": [
                    {"code": "PROF-02.1", "name": "Основная категория", "earned": 1.5, "max": 1.5, "comment": "Твой комментарий"}
                  ],
                  "action_plan": ["Шаг 1", "Шаг 2"]
                }
                Учти все применимые критерии из списка в массиве critique.
                """
                
                prompt = f"Системные инструкции:\n{sys_prompt}\n\nПроанализируй эти данные:\n{json.dumps(raw_yandex_data, ensure_ascii=False)}"
                response = model.generate_content(prompt)
                ai_report = json.loads(response.text)
                st.success("✅ Анализ завершен!")
                
                # --- ЭТАП В: ВЫВОД ОТЧЕТА ---
                st.divider()
                st.subheader(f"🏢 {ai_report.get('company_name
