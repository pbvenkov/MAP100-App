import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

st.set_page_config(page_title="Тест БД", layout="wide")
st.title("Тестирование подключения PIN100_Database")

@st.cache_resource
def init_test_db():
    creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(credentials).open_by_url(st.secrets["SPREADSHEET_URL"])

try:
    doc = init_test_db()
    st.success("✅ Успешная авторизация в Google Sheets API!")
    
    # Тест листа Rules
    rules_records = doc.worksheet("Rules").get_all_records()
    df_rules = pd.DataFrame(rules_records)
    st.write(f"📊 Лист Rules прочитан. Найдено метрик: **{len(df_rules)}**")
    st.dataframe(df_rules.head(3)) # Покажем первые 3 строки для проверки
    
    # Тест листа Prompts
    prompts_records = doc.worksheet("Prompts").get_all_records()
    st.write(f"🤖 Лист Prompts прочитан. Найдено промптов: **{len(prompts_records)}**")
    
    # Тест листа Leads
    leads_sheet = doc.worksheet("Leads")
    st.write(f"📝 Лист Leads доступен. Готов к записи заявок.")
    
except Exception as e:
    st.error(f"❌ Ошибка подключения: {e}")
    st.write("Проверьте email сервисного аккаунта в настройках доступа таблицы и SPREADSHEET_URL.")