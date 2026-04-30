import streamlit as st
import requests
import os

def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

st.title("🔍 Google CSE 診斷")

google_api_key = get_secret("GOOGLE_API_KEY")
google_cx      = get_secret("GOOGLE_CX")

st.markdown("### Secret 狀態")
col1, col2 = st.columns(2)
col1.metric("GOOGLE_API_KEY", "✅ 有值" if google_api_key else "❌ 空值")
col2.metric("GOOGLE_CX",      "✅ 有值" if google_cx      else "❌ 空值")

if google_api_key:
    st.code(f"KEY 前10碼: {google_api_key[:10]}...")
if google_cx:
    st.code(f"CX: {google_cx}")

st.markdown("---")
st.markdown("### 直接測試搜尋")

query = st.text_input("搜尋詞", value="ZARA man white shirt white background product")

if st.button("測試 Google CSE"):
    with st.spinner("搜尋中..."):
        params = {
            "key": google_api_key,
            "cx":  google_cx,
            "q":   query,
            "searchType": "image",
            "imgType": "photo",
            "imgDominantColor": "white",
            "num": 5,
            "safe": "active",
        }
        try:
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=8,
            )
            st.markdown(f"**HTTP Status:** `{r.status_code}`")

            if r.ok:
                data = r.json()
                items = data.get("items", [])
                st.success(f"找到 {len(items)} 筆結果")
                for i, item in enumerate(items):
                    url = item.get("link", "")
                    title = item.get("title", "")
                    st.markdown(f"**{i+1}. {title}**")
                    st.code(url)
                    if url.startswith("http"):
                        try:
                            st.image(url, width=200)
                        except:
                            st.write("（圖片無法預覽）")
            else:
                st.error(f"API 回傳錯誤：")
                st.json(r.json())

        except Exception as e:
            st.error(f"Exception: {e}")
