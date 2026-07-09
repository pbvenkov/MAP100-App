import streamlit as st
import requests
import time
import json
import google.generativeai as genai

# ==========================================
# 1. НАСТРОЙКИ КЛЮЧЕЙ API (ИЗ СЕКРЕТОВ STREAMLIT)
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-reviews-scraper"

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """
Ты — ведущий эксперт по локальному SEO, гео-маркетингу и продвижению в Яндекс.Картах. 
Твоя задача — проводить глубокий аудит карточек компаний на основе JSON-данных и выставлять баллы строго по методике MAP100.
Оценивай PROF-02.1, PROF-03.2, PROF-10.4, PROF-10.5, PROF-10.6, SEO-17.3, REP-31.2, REP-31.4, REP-31.7.
Обязательно учитывай Правило Динамической Ниши.
Ты должен возвращать ответ СТРОГО в формате JSON:
{"company_name": "", "business_niche": "", "scores": {"profile_score": 0.0, "reviews_score": 0.0, "total_map100_score": 0.0}, "detailed_report": {"profile_critique": "", "reviews_critique": ""}, "action_plan": [""]}
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite", 
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
)

# ==========================================
# 2. ИНТЕРФЕЙС STREAMLIT
# ==========================================
st.set_page_config(page_title="MAP100 | Аудит Яндекс.Карт", page_icon="📍", layout="wide")

st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию в Яндекс.Картах, чтобы получить детальный разбор.")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

if st.button("🚀 Запустить аудит", type="primary"):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        # --- ЭТАП А: ПАРСИНГ ---
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
                st.success("✅ Данные успешно собраны!")
                
            except Exception as e:
                st.error(f"Ошибка соединения с Apify: {e}")
                st.stop()

        # --- ЭТАП Б: АНАЛИЗ ---
        with st.spinner("Шаг 2: Gemini анализирует карточку по методике MAP100..."):
            try:
                prompt = f"Проанализируй эти данные:\n{json.dumps(raw_yandex_data, ensure_ascii=False)}"
                response = model.generate_content(prompt)
                
                ai_report = json.loads(response.text)
                st.success("✅ Анализ завершен!")
                
                # --- ЭТАП В: ВЫВОД ОТЧЕТА ---
                st.divider()
                st.subheader(f"🏢 {ai_report.get('company_name', 'Без названия')} | Ниша: {ai_report.get('business_niche', 'Не определена')}")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Общий балл MAP100", f"{ai_report['scores']['total_map100_score']} / 100")
                col2.metric("Упаковка профиля", f"{ai_report['scores']['profile_score']}")
                col3.metric("Работа с отзывами", f"{ai_report['scores']['reviews_score']}")
                
                st.divider()
                st.markdown("### 🔍 Подробный разбор")
                with st.expander("📝 Анализ текстов и упаковки", expanded=True):
                    st.write(ai_report['detailed_report']['profile_critique'])
                with st.expander("💬 Анализ работы с отзывами", expanded=True):
                    st.write(ai_report['detailed_report']['reviews_critique'])
                    
                st.markdown("### 🛠 План исправлений")
                for i, step in enumerate(ai_report.get('action_plan', [])):
                    st.info(f"**Шаг {i+1}:** {step}")

            except Exception as e:
                st.error(f"⚠️ Ошибка связи с ИИ: {e}")
