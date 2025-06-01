"""
Streamlit‑GUI для FastAPI‑сервиса:
  • «Сформировать саммари»  → POST /summarize
  • «Извлечь атрибуты»      → POST /attributes
"""
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json; charset=utf-8",
}

import os
import requests
import streamlit as st
import pandas as pd



API_URL = os.getenv("API_URL", "http://127.0.0.1:8000") 
HEADERS = {"Content-Type": "application/json"}

st.set_page_config(page_title="Анализ отзывов", layout="wide")
st.title("📝 Анализ отзывов")

# Ввод текста
text = st.text_area(
    "Введите отзывы (каждый отзыв с новой строки):",
    height=300,
    placeholder="Купил арбуз, он был спелым, сочным…",
)
text = text.replace("\r\n", "\n")


# вспомогательная обертка post() 
def post(endpoint: str, payload: dict):
    """POST → dict|str,  None|err_msg"""
    url = f"{API_URL}/{endpoint}"
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=120)
        r.raise_for_status()
        # 1) пробуем JSON
        try:
            return r.json(), None
        except ValueError:
            # 2) не JSON → возвращаем как текст
            return r.text, None
    except requests.exceptions.RequestException as e:
        return None, str(e)

# Кнопки действий
col_sum, col_attr = st.columns(2)

# Саммари
if col_sum.button("📄 Сформировать саммари", use_container_width=True):
    if not text.strip():
        st.warning("Введите текст перед отправкой запроса.")
    else:
        with st.spinner("Генерируем саммари…"):
            data, error = post("summarize", {"text": text})

        if error:
            st.error(error)
        else:
            # берем summary вне зависимости от формата ответа 
            if isinstance(data, dict):
                summary = data.get("summary") or data
            else:
                summary = data

            st.subheader("Результат саммари:")
            if isinstance(summary, str):
                # переносы строк в Markdown: двойной пробел + \n
                st.markdown(summary.replace("\n", "  \n"))
            else:
                st.write(summary)   # на всякий случай (например, список)

# Атрибуты 
if col_attr.button("🔍 Извлечь атрибуты", use_container_width=True):
    if not text.strip():
        st.warning("Введите текст перед отправкой запроса.")
    else:
        with st.spinner("Извлекаем атрибуты…"):
            data, error = post("attributes", {"text": text})
        if error:
            st.error(error)
        else:
            st.subheader("Извлечённые атрибуты:")
            attrs = data.get("attributes", data)

            # сервер уже вернул список словарей
            if isinstance(attrs, list) and all(isinstance(x, dict) for x in attrs):
                st.dataframe(pd.DataFrame(attrs), use_container_width=True)

            # сервер вернул одну длинную строку "атрибут: …"
            elif isinstance(attrs, str):
                rows = []
                for line in attrs.strip().splitlines():
                    if ':' not in line:
                        continue
                    attr, vals = line.split(':', 1)
                    vals = [v.strip(' ;') for v in vals.split(';') if v.strip()]
                    rows.append({'attribute': attr.strip(),
                                 'values': ', '.join(vals)})
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
                else:
                    st.code(attrs)   # fallback — показать как есть

            # другой формат → просто выводим
            else:
                st.write(attrs)

