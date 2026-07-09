import streamlit as st
import requests
import time
import json
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ КЛЮЧЕЙ API И БАЗЫ ДАННЫХ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-reviews-scraper"

genai.configure(api_key=GEMINI_API_KEY)

# Подключение к Google Таблицам
@st.cache_resource
def init_google_sheets():
    try:
        # Читаем JSON-ключ из секретов
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        
        # Открываем таблицу по ссылке
        sheet_url = st.secrets["SPREADSHEET_URL"]
        doc = gc.open_by_url(sheet_url)
        return doc
    except Exception as e:
        st.error(f"❌ Ошибка подключения к базе данных Google Sheets: {e}")
        st.stop()

# ==========================================
# 2. ИНТЕРФЕЙС STREAMLIT
# ==========================================
st.set_page_config(page_title="MAP100 | Аудит Яндекс.Карт", page_icon="📍", layout="wide")

st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию в Яндекс.Картах, чтобы получить детальный разбор по всем 94 критериям.")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

if st.button("🚀 Запустить аудит", type="primary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        doc = init_google_sheets()
        
        # --- ЭТАП А: ПАРСИНГ ПРАВИЛ ---
        with st.spinner("Шаг 0: Загружаем актуальные правила из Google Таблиц..."):
            rules_sheet = doc.worksheet("Rules")
            rules_data = rules_sheet.get_all_records()
            
            # Формируем динамический текст правил для ИИ
            dynamic_rules = ""
            for row in rules_data:
                # Берем только заполненные строки
                if row.get('Код') and row.get('Критерий'):
                    dynamic_rules += f"- [{row['Код']}] {row['Критерий']} (Макс. балл {row['Балл']}): {row['Инструкция для ИИ']}\n"

        # --- ЭТАП Б: ПАРСИНГ APIFY ---
        with st.spinner("Шаг 1: Парсим данные из Яндекс.Карт (это может занять до 1-2 минут)..."):
            try:
                run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
                run_payload = {"startUrls": [{"url": yandex_url}], "maxItems": 1}
                run_req = requests.post(run_url, json=run_payload)
                run_data = run_req.json()

                if 'error' in run_data:
                    st.error(f"❌ Apify отказался запускаться: {run_data['error']}")
                    st.stop()

                run_id = run_data['data']['id']
                default_dataset_id = run_data['data']['defaultDatasetId']

                status = "RUNNING"
                while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
                    time.sleep(5)
                    status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}"
                    status_req = requests.get(status_url).json()
                    status = status_req['data']['status']

                if status != "SUCCEEDED":
                    st.error("Ошибка при парсинге данных Apify.")
                    st.stop()

                dataset_url = f"https://api.apify.com/v2/datasets/{default_dataset_id}/items?token={APIFY_API_TOKEN}"
                dataset_req = requests.get(dataset_url).json()
                
                if not dataset_req:
                    st.error("Парсер не нашел данных по этой ссылке.")
                    st.stop()
                    
                raw_yandex_data = dataset_req[0]
                st.success("✅ Данные Яндекс.Карт успешно собраны!")
                
            except Exception as e:
                st.error(f"Ошибка соединения с Apify: {e}")
                st.stop()

        # --- ЭТАП В: АНАЛИЗ GEMINI ---
        with st.spinner("Шаг 2: Gemini анализирует карточку по матрице MAP100..."):
            try:
                SYSTEM_INSTRUCTION = f"""
                Ты — ведущий эксперт по локальному SEO, гео-маркетингу и продвижению в Яндекс.Картах. 
                Твоя задача — проводить глубокий аудит карточек компаний на основе JSON-данных и выставлять баллы СТРОГО по методологии MAP100.
                
                ВОТ АКТУАЛЬНЫЕ ПРАВИЛА И КРИТЕРИИ ОЦЕНКИ (ИХ ВЕСА И АЛГОРИТМЫ):
                {dynamic_rules}
                
                Проанализируй полученные данные компании и начисли баллы по каждому пункту. Если данных для проверки критерия нет — ставь 0 баллов. Сложи все полученные баллы.
                Ты должен возвращать ответ СТРОГО в формате JSON без markdown разметки:
                {{
                    "company_name": "", 
                    "business_niche": "", 
                    "total_score": 0.0, 
                    "detailed_report": "Твой подробный аналитический вывод о состоянии карточки, главных ошибках и сильных сторонах.", 
                    "action_plan": ["шаг 1", "шаг 2", "шаг 3"]
                }}
                """
                
                model = genai.GenerativeModel(
                    model_name="gemini-2.0-flash", 
                    system_instruction=SYSTEM_INSTRUCTION,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )

                prompt = f"Проанализируй эти данные:\n{json.dumps(raw_yandex_data, ensure_ascii=False)}"
                response = model.generate_content(prompt)
                
                ai_report = json.loads(response.text)
                st.success("✅ Анализ завершен!")
                
                # --- ЭТАП Г: ВЫВОД ОТЧЕТА ---
                st.divider()
                
                # Заголовок и общий балл
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(f"🏢 {ai_report.get('company_name', 'Без названия')}")
                    st.caption(f"Ниша: {ai_report.get('business_niche', 'Не определена')}")
                with col2:
                    # Красивый вывод итогового балла
                    score = ai_report.get('total_score', 0)
                    if score >= 80: color = "normal"
                    elif score >= 50: color = "off"
                    else: color = "inverse"
                    st.metric("Общий балл MAP100", f"{score} / 100", delta_color=color)

                st.divider()
                
                # Вывод критики
                st.markdown("### 🔍 Общий аналитический отчет")
                st.write(ai_report.get('detailed_report', 'Отчет пуст'))
                    
                # Вывод плана действий
                st.markdown("### 🛠 Пошаговый план исправлений")
                for i, step in enumerate(ai_report.get('action_plan', [])):
                    st.info(f"**Шаг {i+1}:** {step}")

                # --- ЭТАП Д: ЗАПИСЬ В БАЗУ ДАННЫХ ---
                try:
                    results_sheet = doc.worksheet("Results")
                    new_row = [
                        time.strftime("%d.%m.%Y %H:%M:%S"), # Время
                        yandex_url,                         # Ссылка
                        ai_report.get('company_name', ''),  # Название
                        ai_report.get('business_niche', ''),# Ниша
                        ai_report.get('total_score', 0)     # Балл
                    ]
                    results_sheet.append_row(new_row)
                    st.toast('Сохранено в базу данных!', icon='💾')
                except Exception as e:
                    st.warning(f"Отчет готов, но не удалось записать в Google Sheets: {e}")

            except Exception as e:
                st.error(f"⚠️ Ошибка связи с ИИ: {e}")
