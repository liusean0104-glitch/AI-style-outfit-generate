import streamlit as st
import os
import google.generativeai as genai
from dotenv import load_dotenv
import webbrowser
import json
import urllib.parse
import random
import requests
import asyncio
import time
from duckduckgo_search import DDGS

# 1. 載入與設定
load_dotenv(override=True)

# API Key & Supabase Logic (Prioritize st.secrets for Cloud deployment)
def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

# ── 多組 API Key 輪詢（Round-Robin + Quota-Aware Key Rotation）──
# 自動從環境變數讀取進來，存在的 key 才加入列表
ALL_API_KEYS = [
    k for k in [
        get_secret("GEMINI_API_KEY"),
        get_secret("GEMINI_API_KEY_2"),
        get_secret("GEMINI_API_KEY_3"),
        get_secret("GEMINI_API_KEY_4"),
    ] if k  # 過濾掉未設定的 None
]

# ── 使用模組層級變數（threading.Lock 保護），避免在背景執行緒存取 st.session_state ──
import threading as _threading
_key_lock = _threading.Lock()
_key_idx: int = 0
_key_cooldown: dict = {}  # {key_idx: unix_timestamp 直到不可用}

def _pick_api_key() -> str:
    """回傳目前可用的 API Key。若該 Key 在冷卻中，自動轉到下一個。
    執行緒安全：使用模組層級鎖，不依賴 st.session_state。"""
    global _key_idx
    n = len(ALL_API_KEYS)
    if n == 0:
        return ""
    now = time.time()
    with _key_lock:
        start = _key_idx
        for i in range(n):
            idx = (start + i) % n
            cooldown_until = _key_cooldown.get(idx, 0)
            if now >= cooldown_until:
                _key_idx = idx
                return ALL_API_KEYS[idx]
        # 全部在冷卻中，回傳冷卻時間最短的
        best = min(_key_cooldown, key=_key_cooldown.get)
        return ALL_API_KEYS[best]

def _mark_key_rate_limited(retry_seconds: int = 60):
    """將目前 Key 標記為冷卻中，並輪至下一個。
    執行緒安全：使用模組層級鎖，不依賴 st.session_state。"""
    global _key_idx
    with _key_lock:
        idx = _key_idx
        _key_cooldown[idx] = time.time() + retry_seconds
        next_idx = (idx + 1) % len(ALL_API_KEYS)
        _key_idx = next_idx
        print(f"[KeyRotation] Key #{idx} rate-limited, switching to Key #{next_idx}")

# 對外相容：舊程式碼使用單一 api_key 變數的地方仍可作用
api_key = ALL_API_KEYS[0] if ALL_API_KEYS else None
sb_url = get_secret("SUPABASE_URL")
sb_key = get_secret("SUPABASE_KEY")

st.set_page_config(page_title="AI Stylist", page_icon="👗", layout="centered")

import uuid

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "rec_id" not in st.session_state:
    st.session_state.rec_id = None

# 2. 注入自定義 CSS (Minimalist Luxury / ZARA Aesthetic)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,wght@0,400..900;1,400..900&family=Inter:wght@100..900&display=swap');

    .stApp {
        background-color: #FFFFFF;
    }
    
    /* Typography */
    .magazine-title {
        font-family: 'Bodoni Moda', serif;
        font-size: 3.5rem;
        font-weight: 800;
        text-align: center;
        letter-spacing: -1px;
        margin-bottom: 0.5rem;
        color: #000;
    }
    
    .magazine-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 0.8rem;
        text-transform: uppercase;
        text-align: center;
        letter-spacing: 5px;
        color: #666;
        margin-bottom: 3rem;
    }

    /* Standard Button Styling (ZARA style) */
    div.stButton > button:first-child {
        background-color: #000000;
        color: #ffffff;
        border-radius: 0px;
        border: none;
        font-family: 'Inter', sans-serif;
        text-transform: uppercase;
        font-weight: 500;
        letter-spacing: 2px;
        padding: 0.75rem 2rem;
        width: 100%;
        transition: opacity 0.3s ease;
    }
    
    div.stButton > button:first-child:hover {
        background-color: #000000;
        color: #ffffff;
        opacity: 0.8;
    }

    /* st.link_button Styling */
    div[data-testid="stLinkButton"] > a {
        background-color: #000000 !important;
        color: #ffffff !important;
        border-radius: 0px !important;
        border: none !important;
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase !important;
        font-weight: 500 !important;
        letter-spacing: 2px !important;
        padding: 0.5rem 1rem !important;
        display: flex !important;
        justify-content: center !important;
        white-space: nowrap !important;
    }

    /* Prevent button text wrapping */
    div.stButton > button {
        white-space: nowrap !important;
    }



    /* Expander Styling */
    .stExpander {
        border: none !important;
        border-top: 1px solid #eee !important;
        border-radius: 0px !important;
    }

    /* Image container — clean, no spinner */
    .img-container {
        width: 100%;
        aspect-ratio: 3/4;
        overflow: hidden;
        border: 1px solid #f0f0f0;
        background-color: #f9f9f9;
        position: relative;
    }
    .img-container img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }

    /* Luxury Loading Animation */
    .curating-container {
        padding: 4rem 1rem;
        text-align: center;
        background: #fff;
    }
    .curating-title {
        font-family: 'Bodoni Moda', serif;
        font-size: 1.5rem;
        letter-spacing: 4px;
        text-transform: uppercase;
        margin-bottom: 2rem;
        color: #000;
    }
    .scanning-line {
        width: 100%;
        height: 1px;
        background: #eee;
        position: relative;
        overflow: hidden;
        margin-bottom: 2rem;
    }
    .scanning-line::after {
        content: "";
        position: absolute;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, #000, transparent);
        animation: scan 2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }
    @keyframes scan {
        0% { left: -100%; }
        100% { left: 100%; }
    }
    
    /* Hide number input spinners (Standard) */
    input::-webkit-outer-spin-button,
    input::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
    }
    input[type=number] {
        -moz-appearance: textfield;
    }
    
    /* Hide number input spinners (Streamlit Specific) */
    button[data-testid="stNumberInputStepUp"],
    button[data-testid="stNumberInputStepDown"] {
        display: none !important;
    }

    .loading-tip {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: #888;
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }

    /* Decorative Floral Elements */
    .floral-decoration {
        position: fixed;
        z-index: 99; /* Higher z-index to be above the background */
        pointer-events: none;
        opacity: 0.4;
        width: 400px;
        filter: contrast(0.9) brightness(1.1);
    }
    .floral-tl {
        top: -100px;
        left: -120px;
        transform: rotate(-15deg);
    }
    .floral-br {
        bottom: -100px;
        right: -120px;
        transform: rotate(165deg);
    }

    @media (max-width: 768px) {
        .floral-decoration {
            display: none !important;
        }
        .magazine-title {
            font-size: 2.2rem !important;
            margin-top: 1rem;
        }
        .magazine-subtitle {
            letter-spacing: 2px !important;
            font-size: 0.6rem !important;
            margin-bottom: 1.5rem !important;
        }
        
        /* Force columns to stay side-by-side on mobile */
        [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 10px !important;
        }
        [data-testid="stHorizontalBlock"] > div {
            min-width: 0 !important;
            flex: 1 1 0% !important;
        }
    }

</style>
""", unsafe_allow_html=True)

def _sb_post(table: str, payload: dict, prefer: str = "return=minimal"):
    """共用寫入，失敗只印 console。"""
    if not sb_url or not sb_key:
        return None
    url = f"{sb_url}/rest/v1/{table}"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=3)
        if r.ok and prefer == "return=representation":
            data = r.json()
            return data[0] if data else None
        elif not r.ok:
            print(f"[Supabase] {table} error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[Supabase] {table} exception: {e}")
    return None


def log_session(gender, height, weight, season, occasion, weather, styles, language, has_photo):
    """Upsert 用戶 profile 到 sessions 表。"""
    if not sb_url or not sb_key:
        return
    url = f"{sb_url}/rest/v1/sessions"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {
        "id": st.session_state.session_id,
        "gender": gender,
        "height_cm": int(height),
        "weight_kg": int(weight),
        "season": season,
        "occasion": occasion,
        "weather": weather,
        "styles": styles,
        "language": language,
        "has_photo_upload": has_photo,
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=3)
    except Exception as e:
        print(f"[Supabase] sessions upsert exception: {e}")


def log_recommendation(result: dict):
    """寫入推薦結果到 recommendations 表，回傳 rec_id。"""
    payload = {
        "session_id": st.session_state.session_id,
        "model_used": result.get("model_used", "unknown"),
        "zara_items": result.get("zara_items", []),
        "other_brands": result.get("other_brands", []),
        "accessories": result.get("accessories", []),
        "latency_ms": result.get("latency_ms"),
    }
    row = _sb_post("recommendations", payload, prefer="return=representation")
    return row["id"] if row else None


def log_event(event_type: str, item_name: str = None):
    """寫入行為事件到 events 表。"""
    payload = {
        "session_id": st.session_state.session_id,
        "rec_id": st.session_state.rec_id,
        "event_type": event_type,
        "item_name": item_name,
    }
    _sb_post("events", payload)


def track_like():
    log_event("like")
    st.toast("Thank you! / 感謝您的回饋！")


def track_dislike():
    log_event("dislike")
    st.toast("We'll do better next time! / 我們會繼續改進！")

# 2. 核心 AI 函數
GEMMA_MODELS = [
    'gemini-2.5-flash',
    'gemma-4-31b-it',
    'gemma-4-26b-a4b-it',
    'gemma-3-27b-it',
]

def get_ai_recommendation(gender, height, weight, season, occ, wea, sty, lang, uploaded_image=None, custom_prompt=None):
    if not ALL_API_KEYS:
        return None, "Error: API Key missing"
    
    genai.configure(api_key=ALL_API_KEYS[0])
    
    sty_str = ', '.join(sty) if sty else "general"
    system_persona = (
        f"You are a pragmatic fashion stylist for college students and office workers. "
        f"Focus on high value-for-money, affordable brands (e.g. ZARA, Uniqlo, H&M, GU). "
        f"Analyze their physique ({height}cm, {weight}kg) to suggest cuts that flatter a budget-conscious but stylish wardrobe."
    )
    
    image_analysis_instruction = ""
    if uploaded_image:
        image_analysis_instruction = (
            "CRITICAL: The user has uploaded a photo of their current outfit. "
            "1. Analyze the colors, fit, and style of the items they are wearing. "
            "2. Evaluate how this outfit fits their physique. "
            "3. In your JSON, include a 'critique' field with a paragraph of your analysis and suggestions. "
            "4. Your recommendations should either improve or complement the current outfit."
        )

    currency_instruction = "Estimate price in NTD (TWD) for 繁體中文, or USD for English."
    
    specific_style_rule = ""
    if lang == "繁體中文":
        p_cc_name = "教士隊城市限定球衣"
        p_cc_reason = "這套穿搭的核心單品。"
        p_home_name = "教士隊主場球衣"
        p_home_reason = "這套穿搭的核心單品。"
        p_price = "球隊商店限定"
    else:
        p_cc_name = "Padres City Connect Jersey"
        p_cc_reason = "The center piece of this outfit."
        p_home_name = "Padres Home Jersey"
        p_home_reason = "The center piece of this outfit."
        p_price = "Team Store Exclusive"

    if "Padres City Connect Jersey" in sty:
        specific_style_rule = (
            f"SPECIAL STYLE RULE: The user IS wearing a '{p_cc_name}' as the main top. "
            f"In your JSON response, the first item in 'zara_items' MUST be exactly: "
            f"{{\"name\": \"{p_cc_name}\", \"reason\": \"{p_cc_reason}\", \"category\": \"top\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"Do NOT suggest any other main tops. Focus entirely on matching pants, shoes, and inner layers."
        )
    elif "Padres Home Jersey" in sty:
        specific_style_rule = (
            f"SPECIAL STYLE RULE: The user IS wearing a '{p_home_name}' as the main top. "
            f"In your JSON response, the first item in 'zara_items' MUST be exactly: "
            f"{{\"name\": \"{p_home_name}\", \"reason\": \"{p_home_reason}\", \"category\": \"top\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"Do NOT suggest any other main tops. Focus entirely on matching pants, shoes, and inner layers."
        )

    custom_prompt_rule = ""
    if custom_prompt:
        custom_prompt_rule = (
            f"SPECIAL USER REQUEST: The user has specified the following additional style instructions:\n"
            f"\"{custom_prompt}\"\n"
            f"Please prioritize and adapt your recommended outfits, other brands, and accessories to fulfill this request."
        )

    prompt = (
        f"{system_persona}\n"
        f"User Profile: Gender: {gender}, Height: {height}cm, Weight: {weight}kg.\n"
        f"Context: Season: {season}, Occasion: {occ}, Weather: {wea}, Style: {sty_str}.\n"
        f"{specific_style_rule}\n"
        f"{custom_prompt_rule}\n"
        f"LANGUAGE RULE: Respond in {lang}. Use Traditional Chinese if '繁體中文'.\n"
        f"CURRENCY RULE: {currency_instruction}\n"
        f"Provide response in valid JSON format ONLY:\n"
        f"{{\n"
        f"  \"critique\": \"(Optional) Analysis of uploaded outfit if provided, otherwise empty.\",\n"
        f"  \"zara_items\": [\n"
        f"    {{\n"
        f"      \"name\": \"ZARA [Item Name]\",\n"
        f"      \"reason\": \"Reason why this fits their physique.\",\n"
        f"      \"category\": \"top/pants/shoes\",\n"
        f"      \"price_range\": \"Estimated price range\",\n"
        f"      \"recommended_size\": \"Calculated size (e.g. S, M, L, XL, EU 42) based on user's height/weight\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"other_brands\": [\n"
        f"    {{\n"
        f"      \"name\": \"[Brand Name] [Item Name]\",\n"
        f"      \"reason\": \"Styling tip.\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"accessories\": [\n"
        f"    {{\n"
        f"      \"name\": \"[Item Name]\",\n"
        f"      \"reason\": \"How it completes the look.\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"description\": \"A paragraph on the overall look.\"\n"
        f"}}\n"
        f"CRITICAL: 3 'zara_items', 4-5 'other_brands', 2 'accessories'.\n"
    )
    
    last_error = None
    # 對所有模型依序嘗試
    for model_name in GEMMA_MODELS:
        max_retries = len(ALL_API_KEYS) * 2  # 每張 key 最多試 2 次
        for attempt in range(max_retries):
            current_key = _pick_api_key()
            if not current_key:
                return None, "Error: 所有 API Key 均不可用"
            try:
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name)
                
                content_list = [prompt]
                if uploaded_image:
                    import PIL.Image
                    img = PIL.Image.open(uploaded_image)
                    content_list.append(img)
                    
                response = model.generate_content(content_list)
                text = response.text
                
                import json
                clean_text = text.strip()
                start_idx = clean_text.find('{')
                end_idx = clean_text.rfind('}')
                
                if start_idx != -1 and end_idx != -1:
                    data = json.loads(clean_text[start_idx:end_idx+1])
                    return {
                        "critique": data.get("critique", ""),
                        "zara_items": data.get("zara_items", []),
                        "other_brands": data.get("other_brands", []),
                        "accessories": data.get("accessories", []),
                        "description": data.get("description", ""),
                        "model_used": model_name
                    }, None
            except Exception as e:
                last_error = str(e)
                if "429" in last_error or "quota" in last_error.lower() or "rate" in last_error.lower():
                    # 解析 retry-after 秒數（若 Google API 有提供）
                    retry_secs = 65  # 預設冷卻 65 秒
                    import re
                    m = re.search(r'retry_delay.*?seconds.*?(\d+)', last_error, re.DOTALL)
                    if m:
                        retry_secs = int(m.group(1)) + 2
                    _mark_key_rate_limited(retry_secs)
                    # 立刻再試（帶新 key）而不是 sleep
                    continue
                # 其他錯誤跨出儲存迴圈直接嘗試下一個模型
                break
                
    return None, f"All models exhausted. Last error: {last_error}"

# Helper for base64 images
def get_base64_image(path):
    import base64
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

# Static Header (Same for both languages)
st.markdown('<div class="magazine-title">VOGUE AI STYLIST</div>', unsafe_allow_html=True)
st.markdown('<div class="magazine-subtitle">INTELLIGENT FASHION CURATION</div>', unsafe_allow_html=True)

# ─── Language & Gender Row ───
col_lang, col_gen = st.columns(2)
with col_lang:
    lang_select = st.selectbox("Language / 語言", ["繁體中文", "English"], label_visibility="collapsed")
    # Update dictionary based on selection
    if lang_select == "繁體中文":
        t = {
            "title": "VOGUE AI STYLIST", 
            "subtitle": "INTELLIGENT FASHION CURATION",
            "btn": "Generate Collection", 
            "buy": "Discover", 
            "occ": "Occasion", 
            "wea": "Weather",
            "gender": "Gender",
            "height": "Height",
            "weight": "Weight",
            "season": "Season",
            "style": "Style Aesthetic",
            "genders": ["Male", "Female", "Other"],
            "seasons": ["Spring", "Summer", "Autumn", "Winter"],
            "occs": ["Casual", "Business", "Date", "Gala"],
            "weas": ["Hot", "Comfortable", "Rainy", "Cold"],
            "styles": ["Old Money", "Minimalist", "Streetwear", "Korean Style", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS",
            "custom_prompt_label": "特別穿搭需求（選填）",
            "custom_prompt_placeholder": "例如：我今天想搭配一件黑色皮衣，或是希望看起來像美式街頭風格..."
        }
    else:
        t = {
            "title": "VOGUE AI STYLIST", 
            "subtitle": "INTELLIGENT FASHION CURATION",
            "btn": "Generate Collection", 
            "buy": "Discover", 
            "occ": "Occasion", 
            "wea": "Weather",
            "gender": "Gender",
            "height": "Height",
            "weight": "Weight",
            "season": "Season",
            "style": "Style Aesthetic",
            "genders": ["Male", "Female", "Other"],
            "seasons": ["Spring", "Summer", "Autumn", "Winter"],
            "occs": ["Casual", "Business", "Date", "Gala"],
            "weas": ["Hot", "Comfortable", "Rainy", "Cold"],
            "styles": ["Old Money", "Minimalist", "Streetwear", "Korean Style", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS",
            "custom_prompt_label": "Custom Styling Demand (Optional)",
            "custom_prompt_placeholder": "e.g. I want to match a black leather jacket, or look like US streetwear style..."
        }

with col_gen:
    user_gender = st.selectbox(t["gender"], t["genders"], label_visibility="collapsed")

# ─── Decorative Floral Injection ───
floral_b64 = get_base64_image("floral_roses.png")
if floral_b64:
    st.markdown(f"""
        <img src="data:image/png;base64,{floral_b64}" class="floral-decoration floral-tl">
        <img src="data:image/png;base64,{floral_b64}" class="floral-decoration floral-br">
    """, unsafe_allow_html=True)

# ─── Height & Weight Row ───
col_h, col_w = st.columns(2)
with col_h:
    user_height = st.number_input(t["height"], min_value=100, max_value=250, value=175, step=1)
with col_w:
    user_weight = st.number_input(t["weight"], min_value=30, max_value=200, value=70, step=1)

# ─── Season, Occasion, Weather Row ───
col_s, col_o, col_w_env = st.columns(3)
with col_s:
    user_season = st.selectbox(t["season"], t["seasons"])
with col_o:
    user_occ = st.selectbox(t["occ"], t["occs"])
with col_w_env:
    user_wea = st.selectbox(t["wea"], t["weas"])

# Style Aesthetic (No default, fixed list)
user_sty = st.multiselect(t["style"], t["styles"], default=[])

# ─── Outfit Upload ───
uploaded_file = st.file_uploader(t["upload_label"], type=["jpg", "png", "jpeg"], help=t["upload_help"])
if uploaded_file:
    # Shrink preview using columns
    _, col_mid, _ = st.columns([1, 1, 1])
    with col_mid:
        st.image(uploaded_file, caption="Current Outfit Preview", use_container_width=True)

# ── Custom Prompt input ───
user_custom_prompt = st.text_area(t["custom_prompt_label"], placeholder=t["custom_prompt_placeholder"])

# 5. 執行按鈕
st.markdown("<br>", unsafe_allow_html=True)
if st.button(t["btn"]):
    # 清除舊的圖片與曝光 cache，避免重新生成時殘留
    for key in list(st.session_state.keys()):
        if key.startswith("img_") or key.startswith("imp_"):
            del st.session_state[key]

    # Luxury Curating UI Setup
    TIPS = {
        "繁體中文": [
            "正在分析您的身形比例...",
            "正在挑選 ZARA 季度單品...",
            "正在優化服裝剪裁平衡...",
            "正在注入法式簡約美學...",
            "您的專屬時尚提案即將呈現..."
        ],
        "English": [
            "Analyzing your body proportions...",
            "Selecting seasonal ZARA pieces...",
            "Optimizing garment cut balance...",
            "Injecting minimalist aesthetics...",
            "Your curated style is almost ready..."
        ]
    }
    tips = TIPS[lang_select]
    ui_placeholder = st.empty()
    
    import concurrent.futures
    import time

    # Show animated luxury loading UI while calling the API
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(
            get_ai_recommendation,
            user_gender, user_height, user_weight, user_season,
            user_occ, user_wea, user_sty, lang_select, uploaded_file,
            user_custom_prompt
        )
        tip_idx = 0
        start_time = time.time()
        expected_seconds = 25 # Increased for multi-modal analysis and image search
        
        while not future.done():
            elapsed = time.time() - start_time
            remaining = max(1, int(expected_seconds - elapsed))
            
            # If it takes longer than expected, keep it at 1s or show "Processing..."
            timer_text = f"ETA: {remaining}s" if remaining > 0 else "Finalizing..."
            
            with ui_placeholder.container():
                st.markdown(f"""
                <div class="curating-container">
                    <div class="curating-title">Curating Your Style</div>
                    <div class="scanning-line"></div>
                    <div class="loading-tip">{tips[tip_idx % len(tips)]}</div>
                    <div style="font-family: 'Inter', sans-serif; font-size: 0.7rem; letter-spacing: 3px; color: #000; margin-top: 1.5rem; font-weight: 600;">
                        {timer_text}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            tip_idx += 1
            time.sleep(1.5) # Reduced sleep for smoother timer updates
        ui_placeholder.empty()
        result, err = future.result()

    if err:
        st.error(f"STYLING SERVICE UNAVAILABLE: {err}")
    else:
        result["latency_ms"] = int((time.time() - start_time) * 1000)
        st.session_state.last_result = result

        # 依序寫入三張表
        log_session(
            gender=user_gender,
            height=user_height,
            weight=user_weight,
            season=user_season,
            occasion=user_occ,
            weather=user_wea,
            styles=user_sty,
            language=lang_select,
            has_photo=uploaded_file is not None,
        )
        rec_id = log_recommendation(result)
        st.session_state.rec_id = rec_id
        log_event("generate")

# ─── Image Engine ──────────────────────────────────────────────────────────

# ── RAW_DATA：服裝單品清單（URL + 屬性）────────────────────────────────────
# 格式：{"name": str, "url": str, "gender": str, "style": str,
#        "season": str, "occasion": str, "category": str}
# gender / style / season / occasion 皆可為 "all" 表示萬用
RAW_DATA = [
    # ── Padres Special ─────────────────────────────────────────
    {"name": "Padres Home Jersey",      "url": "https://i.postimg.cc/4xBkzZVC/home-jersey.avif",
     "gender": "all", "style": "padres home jersey", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "Padres Jeans",            "url": "https://i.postimg.cc/Sx1K04t3/niu-zi-ku.jpg",
     "gender": "all", "style": "padres home jersey", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "Padres Sneakers",         "url": "https://i.postimg.cc/qvD7fr50/bai-se-fan-bu-xie.jpg",
     "gender": "all", "style": "padres home jersey", "season": "all", "occasion": "all", "category": "shoes"},

    {"name": "Padres City Connect Jersey", "url": "https://i.postimg.cc/cLXyQZwy/city-connect.jpg",
     "gender": "all", "style": "padres city connect jersey", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "Padres CC Jeans",         "url": "https://i.postimg.cc/Sx1K04t3/niu-zi-ku.jpg",
     "gender": "all", "style": "padres city connect jersey", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "Padres CC Sneakers",      "url": "https://i.postimg.cc/qvD7fr50/bai-se-fan-bu-xie.jpg",
     "gender": "all", "style": "padres city connect jersey", "season": "all", "occasion": "all", "category": "shoes"},

    # ── Korean Style ───────────────────────────────────────────
    {"name": "亞麻混紡寬版襯衫",        "url": "https://static.zara.net/assets/public/929f/7db7/8b134105881c/93f90f300c43/04391202251-e1/04391202251-e1.jpg?ts=1776675963894&w=750",
     "gender": "all", "style": "korean style", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "西裝長褲",                "url": "https://i.postimg.cc/JzYhw827/xi-zhuang-zhang-ku.jpg",
     "gender": "all", "style": "korean style", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "西裝外套",                "url": "https://static.zara.net/assets/public/77a3/aae9/7cdb4a779845/6bd338dda377/03548117505-e1/03548117505-e1.jpg?ts=1771492805494&w=750",
     "gender": "all", "style": "korean style", "season": "all", "occasion": "all", "category": "others"},
    {"name": "大衣",                    "url": "https://static.zara.net/assets/public/335a/4ba1/7fa649178479/013a090cd3e9/09330896730-e1/09330896730-e1.jpg?ts=1763624004198&w=750",
     "gender": "all", "style": "korean style", "season": "all", "occasion": "all", "category": "others"},
    {"name": "毛衣",                    "url": "https://static.zara.net/assets/public/47a8/0b53/66174400aeed/bc0ec06d656d/03920490704-e1/03920490704-e1.jpg?ts=1769507794726&w=750",
     "gender": "all", "style": "korean style", "season": "all", "occasion": "all", "category": "others"},

    # ── Legacy / General items (preserved from old dict) ───────
    {"name": "linen blend oversize shirt", "url": "https://i.postimg.cc/Zq954QGz/kuan-song-chen-shan.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "man jeans",               "url": "https://i.postimg.cc/Sx1K04t3/niu-zi-ku.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "white t-shirt",           "url": "https://i.postimg.cc/vZ2mRyNR/bai-se-T-Shirt.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "canvas sneaker",          "url": "https://i.postimg.cc/qvD7fr50/bai-se-fan-bu-xie.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "shoes"},
    {"name": "wide leg trouser",        "url": "https://i.postimg.cc/x1pdrQ41/kuan-xi-zhuang-zhang-ku.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "loafer",                  "url": "https://i.postimg.cc/qvD7fr5p/pi-le-fu-xie.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "shoes"},
    {"name": "polo shirt",              "url": "https://i.postimg.cc/fRqb4sgr/polo-shan.jpg",
     "gender": "male", "style": "all", "season": "all", "occasion": "all", "category": "tops"},

    {"name": "wide leg pant",           "url": "https://i.postimg.cc/0y7qns1n/nu-kuan-ku.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "linen blend trouser",     "url": "https://i.postimg.cc/kG9nXsWG/Linen-Blend-Trousers.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "sleeveless satin blouse", "url": "https://i.postimg.cc/gjDGwhKn/Sleeveless-Satin-Blouse.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "midi skirt",              "url": "https://i.postimg.cc/4N6W95VN/Satin-Midi-Skirt.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "woman jean",              "url": "https://i.postimg.cc/d11XbMp6/nu-niu-zi-ku.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "pants"},
    {"name": "ribbed t-shirt",          "url": "https://i.postimg.cc/766cFvdV/nu-luo-wen-duan-xiu-T-shirt.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "crop t-shirt",            "url": "https://i.postimg.cc/GhwRy2Zy/duan-ban-Tshirt.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "strappy heeled sandal",   "url": "https://i.postimg.cc/X7J8DbyL/Strappy-Heeled-Sandals.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "shoes"},
    {"name": "cropped linen blend shirt", "url": "https://i.postimg.cc/Qxtbn3WS/women-Cropped-Linen-Blend-Shirt.jpg",
     "gender": "female", "style": "all", "season": "all", "occasion": "all", "category": "tops"},
    # ── 新增競賽用單品 ──
    {"name": "紋理針織POLO衫", "url": "https://static.zara.net/assets/public/ea9b/6ad1/1fe04f5294ee/4550e91b144a/06771409725-e1/06771409725-e1.jpg?ts=1775027129089&w=750",
     "gender": "male", "style": "korean style", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "亞麻混紡寬鬆短袖襯衫", "url": "https://static.zara.net/assets/public/ee77/3142/66474a22afe3/eedbef858c32/04344502802-e1/04344502802-e1.jpg?ts=1774946000301&w=750",
     "gender": "male", "style": "korean style", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "白色球鞋", "url": "https://static.zara.net/assets/public/8dd7/c670/40b047c68246/c739d76bde81/15037710002-e1/15037710002-e1.jpg?ts=1771515859118&w=1024",
     "gender": "male", "style": "korean style", "season": "all", "occasion": "all", "category": "shoes"},
    {"name": "印花短版上衣", "url": "https://static.zara.net/assets/public/6a57/85f0/b1de4a47998d/870944fff272/06224858016-e2/06224858016-e2.jpg?ts=1775747112321&w=750",
     "gender": "female", "style": "streetwear", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "府綢寬鬆襯衫", "url": "https://static.zara.net/assets/public/2445/941b/a21441cca03e/6ac162b87051/01096289251-e1/01096289251-e1.jpg?ts=1771926772874&w=750",
     "gender": "female", "style": "streetwear", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "亞麻混紡開襟短袖襯衫", "url": "https://static.zara.net/assets/public/ee77/3142/66474a22afe3/eedbef858c32/04344502802-e1/04344502802-e1.jpg?ts=1774946000301&w=750",
     "gender": "male", "style": "streetwear", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "寬鬆版印花T shirt", "url": "https://static.zara.net/assets/public/6a57/85f0/b1de4a47998d/870944fff272/06224858016-e2/06224858016-e2.jpg?ts=1775747112321&w=750",
     "gender": "male", "style": "streetwear", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "針織POLO衫", "url": "https://static.zara.net/assets/public/ea9b/6ad1/1fe04f5294ee/4550e91b144a/06771409725-e1/06771409725-e1.jpg?ts=1775027129089&w=750",
     "gender": "male", "style": "old money", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "亞麻混紡休閒襯衫", "url": "https://static.zara.net/assets/public/ee77/3142/66474a22afe3/eedbef858c32/04344502802-e1/04344502802-e1.jpg?ts=1774946000301&w=750",
     "gender": "male", "style": "old money", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "合身基本款棉質T shirt", "url": "https://static.zara.net/assets/public/919a/0d64/18ab4209ad1f/e0daff2808bf/02621413250-e1/02621413250-e1.jpg?ts=1774258002473&w=750",
     "gender": "male", "style": "minimalist", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "亞麻混紡襯衫", "url": "https://static.zara.net/assets/public/ee77/3142/66474a22afe3/eedbef858c32/04344502802-e1/04344502802-e1.jpg?ts=1774946000301&w=750",
     "gender": "male", "style": "minimalist", "season": "all", "occasion": "all", "category": "tops"},
    {"name": "亞麻混紡中長洋裝", "url": "https://static.zara.net/assets/public/98bb/0b0f/04fb4cf990bc/929e28113793/02103122104-e1/02103122104-e1.jpg?ts=1774347716612&w=750",
     "gender": "female", "style": "minimalist", "season": "all", "occasion": "all", "category": "others"},
    {"name": "亞麻混紡寬鬆襯衫", "url": "https://static.zara.net/assets/public/fa9e/1985/508e4ae9a96a/ca968a6a6bfa/08648023712-e1/08648023712-e1.jpg?ts=1770813038309&w=750",
     "gender": "female", "style": "minimalist", "season": "all", "occasion": "all", "category": "tops"},
]

# ── 別名表：將 AI 可能輸出的字詞對應到 RAW_DATA 的 name ─────────────────────
_NAME_ALIASES: dict[str, str] = {
    # 男 tops
    "linen oversize shirt": "linen blend oversize shirt",
    "亞麻寬鬆襯衫": "linen blend oversize shirt",
    "寬鬆亞麻襯衫": "linen blend oversize shirt",
    "亞麻混紡寬版襯衫": "亞麻混紡寬版襯衫",
    # 男 pants
    "男牛仔褲": "man jeans",
    "西裝長褲": "西裝長褲",
    "寬鬆西裝": "wide leg trouser",
    "oversized suit pant": "wide leg trouser",
    # 男 tops (white T)
    "white tee": "white t-shirt",
    "白色t": "white t-shirt",
    "白色t-shirt": "white t-shirt",
    "白t": "white t-shirt",
    # 男 shoes
    "白色帆布鞋": "canvas sneaker",
    "帆布鞋": "canvas sneaker",
    "樂福鞋": "loafer",
    "皮質樂福鞋": "loafer",
    # 男 tops (polo)
    "polo衫": "polo shirt",
    "polo 衫": "polo shirt",
    # 女 pants
    "女寬鬆長褲": "wide leg pant",
    "寬鬆長褲": "wide leg pant",
    "亞麻長褲": "linen blend trouser",
    "linen trouser": "linen blend trouser",
    "linen blend trousers": "linen blend trouser",
    "低腰牛仔褲": "woman jean",
    "低腰寬版牛仔褲": "woman jean",
    "wide leg jean": "woman jean",
    "low rise jean": "woman jean",
    "女牛仔褲": "woman jean",
    "中長裙": "midi skirt",
    "緞面裙": "midi skirt",
    "迷你裙": "midi skirt",
    "denim skirt": "midi skirt",
    "mini skirt": "midi skirt",
    "satin skirt": "midi skirt",
    "短裙": "midi skirt",
    "丹寧裙": "midi skirt",
    # 女 tops
    "無袖緞面上衣": "sleeveless satin blouse",
    "緞面無袖": "sleeveless satin blouse",
    "satin blouse": "sleeveless satin blouse",
    "螺紋t": "ribbed t-shirt",
    "螺紋上衣": "ribbed t-shirt",
    "ribbed tee": "ribbed t-shirt",
    "短版t": "crop t-shirt",
    "短版上衣": "crop t-shirt",
    "cropped tee": "crop t-shirt",
    "y2k t": "crop t-shirt",
    "女寬鬆襯衫": "cropped linen blend shirt",
    "女亞麻襯衫": "cropped linen blend shirt",
    "cropped linen shirt": "cropped linen blend shirt",
    # 女 shoes
    "平底鞋": "strappy heeled sandal",
    "涼鞋": "strappy heeled sandal",
    "strappy sandal": "strappy heeled sandal",
    "strappy heeled sandals": "strappy heeled sandal",
    # Korean style
    "西裝外套": "西裝外套",
    "大衣": "大衣",
    "毛衣": "毛衣",
    # Padres
    "padres home jersey": "Padres Home Jersey",
    "教士隊主場球衣": "Padres Home Jersey",
    "padres city connect jersey": "Padres City Connect Jersey",
    "教士隊城市限定球衣": "Padres City Connect Jersey",
    # 新增競賽用單品別名對應
    "紋理針織polo衫": "紋理針織POLO衫",
    "textured knit polo shirt": "紋理針織POLO衫",
    "亞麻混紡寬鬆短袖襯衫": "亞麻混紡寬鬆短袖襯衫",
    "loose fit linen blend short sleeve shirt": "亞麻混紡寬鬆短袖襯衫",
    "白色球鞋": "白色球鞋",
    "white sneakers": "白色球鞋",
    "印花短版上衣": "印花短版上衣",
    "printed crop top": "印花短版上衣",
    "府綢寬鬆襯衫": "府綢寬鬆襯衫",
    "poplin oversize shirt": "府綢寬鬆襯衫",
    "亞麻混紡開襟短袖襯衫": "亞麻混紡開襟短袖襯衫",
    "linen blend open collar short sleeve shirt": "亞麻混紡開襟短袖襯衫",
    "寬鬆版印花t shirt": "寬鬆版印花T shirt",
    "loose fit printed t-shirt": "寬鬆版印花T shirt",
    "針織polo衫": "針織POLO衫",
    "knit polo shirt": "針織POLO衫",
    "亞麻混紡休閒襯衫": "亞麻混紡休閒襯衫",
    "linen blend casual shirt": "亞麻混紡休閒襯衫",
    "合身基本款棉質t shirt": "合身基本款棉質T shirt",
    "slim fit basic cotton t-shirt": "合身基本款棉質T shirt",
    "亞麻混紡襯衫": "亞麻混紡襯衫",
    "linen blend shirt": "亞麻混紡襯衫",
    "亞麻混紡中長洋裝": "亞麻混紡中長洋裝",
    "linen blend midi dress": "亞麻混紡中長洋裝",
    "亞麻混紡寬鬆襯衫": "亞麻混紡寬鬆襯衫",
    "linen blend loose fit shirt": "亞麻混紡寬鬆襯衫",
}

# ── 以 name 為索引的快速查詢字典 ─────────────────────────────────────────────
_NAME_TO_URL: dict[str, str] = {item["name"].lower(): item["url"] for item in RAW_DATA}

# ── COMPOSITE_DICT：以 "gender_style_season_occasion_category" 為組合鍵 ──────
def _build_composite_dict() -> dict[str, str]:
    """將 RAW_DATA 預處理為組合鍵字典，O(n) 初始化，O(1) 查詢。"""
    d: dict[str, str] = {}
    for item in RAW_DATA:
        g  = item["gender"].lower()
        st = item["style"].lower()
        se = item["season"].lower()
        oc = item["occasion"].lower()
        ca = item["category"].lower()
        key = f"{g}_{st}_{se}_{oc}_{ca}"
        d[key] = item["url"]
    return d

COMPOSITE_DICT: dict[str, str] = _build_composite_dict()

# ── 輔助：將 UI gender 對應到資料中的 gender 值 ──────────────────────────────
def _normalize_gender(gender: str) -> str:
    return "female" if gender in ("Female", "女性") else "male"

def get_local_image_data_uri(filename: str) -> str:
    import base64
    filepath = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(filepath):
        ext = filename.split('.')[-1].lower()
        mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg") else "image/jpeg"
        if ext == "jpg":
            mime = "image/jpeg"
        try:
            with open(filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                return f"data:{mime};base64,{b64}"
        except Exception as e:
            print(f"Error reading local image {filename}: {e}")
    return ""


def get_item_image(item_name: str, gender: str, category: str = "others",
                   style: str = "all", season: str = "all", occasion: str = "all") -> str:
    """名稱比對優先，組合鍵僅在有明確 style 時作 fallback。"""
    n = item_name.lower().strip()

    # 1. Padres 特例優先（不論 season / gender）
    for padres_key in ("padres home jersey", "padres city connect jersey",
                       "教士隊主場球衣", "教士隊城市限定球衣"):
        if padres_key in n:
            return _NAME_TO_URL.get(padres_key, "")

    # 2. 名稱直接命中 _NAME_TO_URL
    direct = _NAME_TO_URL.get(n)
    if direct:
        return direct

    # 3. 別名表 → _NAME_TO_URL
    canonical = _NAME_ALIASES.get(n)
    if canonical:
        url = _NAME_TO_URL.get(canonical.lower(), "")
        if url:
            return url

    # 4. 子字串模糊比對（AI 輸出常帶品牌前綴，如 "ZARA 亞麻混紡寬版襯衫"）
    for key, url in _NAME_TO_URL.items():
        if key in n or n in key:
            return url

    # 5. 組合鍵（Composite Key）兜底比對
    g  = _normalize_gender(gender)
    st = style.lower()
    se = season.lower()
    oc = occasion.lower()
    ca = category.lower()

    # 優先順序：指定風格 -> all 風格
    st_opts = [st]
    if st != "all":
        st_opts.append("all")

    # 對於 gender, season, occasion，優先配對具體值，再配對 "all"
    g_opts = [g, "all"]
    se_opts = [se, "all"]
    oc_opts = [oc, "all"]

    for st_val in st_opts:
        for g_val in g_opts:
            for se_val in se_opts:
                for oc_val in oc_opts:
                    composite_key = f"{g_val}_{st_val}_{se_val}_{oc_val}_{ca}"
                    if composite_key in COMPOSITE_DICT:
                        return COMPOSITE_DICT[composite_key]

    # 6. 如果以上都失敗，使用本機預設圖檔 (base64 格式) 避免破圖
    fallback_filename = f"{ca}.jpg"
    if ca == "tops":
        fallback_filename = "tops.jpg"
    elif ca == "pants":
        fallback_filename = "pants.jpg"
    else:
        fallback_filename = "others.jpg"
    
    local_b64 = get_local_image_data_uri(fallback_filename)
    if local_b64:
        return local_b64

    return ""


# ─── Results Display ──────────────────────────────────────────────────────────
if st.session_state.last_result:
    res = st.session_state.last_result
    st.markdown("---")

    # AI Analysis of Uploaded Outfit
    if res.get("critique"):
        st.markdown(
            f'<div style="font-family:\'Bodoni Moda\',serif; font-size:1.4rem; '
            f'letter-spacing:3px; margin-bottom:1rem;">{t["analysis_title"]}</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div style="font-family:\'Inter\',sans-serif; background-color:#f9f9f9; '
            f'padding:1.5rem; border-left:3px solid #000; margin-bottom:2.5rem; '
            f'font-style:italic; color:#333;">{res["critique"]}</div>',
            unsafe_allow_html=True
        )

    # Styling Concept (overall description)
    if res.get("description"):
        st.markdown(
            f'<div style="font-family:\'Inter\',sans-serif; line-height:1.8; color:#444; '
            f'font-size:0.95rem; margin-bottom:2.5rem;">{res["description"]}</div>',
            unsafe_allow_html=True
        )

    # ZARA Collection — 1×3 strict vertical layout
    st.markdown(
        '<div style="font-family:\'Bodoni Moda\',serif; font-size:1.4rem; '
        'letter-spacing:3px; margin-bottom:1.5rem;">THE COLLECTION</div>',
        unsafe_allow_html=True
    )

    zara_items = res.get("zara_items", [])
    for idx, item in enumerate(zara_items):
        raw_name   = item.get("name", "")
        reason     = item.get("reason", "")
        category   = item.get("category", "others")
        
        # 清理名稱：移除括號中多餘的語言 (例如 "名稱 (English)" -> "名稱")
        import re
        match = re.search(r'(.+?)\s*\((.+?)\)', raw_name)
        if match:
            part1 = match.group(1).strip()
            part2 = match.group(2).strip()
            has_chinese_p1 = any('\u4e00' <= c <= '\u9fff' for c in part1)
            has_chinese_p2 = any('\u4e00' <= c <= '\u9fff' for c in part2)
            
            if lang_select == "繁體中文":
                name_brand = part1 if has_chinese_p1 else (part2 if has_chinese_p2 else raw_name)
            else:
                name_brand = part1 if not has_chinese_p1 else (part2 if not has_chinese_p2 else raw_name)
        else:
            name_brand = raw_name

        # 圖片 cache：避免每次按鈕 rerun 重新搜尋
        img_cache_key = f"img_{idx}"
        if img_cache_key not in st.session_state:
            # 傳入第一個已選風格供組合鍵 fallback 使用
            primary_style = user_sty[0] if user_sty else "all"
            st.session_state[img_cache_key] = get_item_image(
                raw_name, user_gender, category,
                style=primary_style, season=user_season, occasion=user_occ
            )
        img_url = st.session_state[img_cache_key]

        if img_url:
            col_img_area, col_txt = st.columns([1, 1.5])
            with col_img_area:
                st.markdown(
                    f'<div class="img-container"><img src="{img_url}"></div>',
                    unsafe_allow_html=True
                )
        else:
            col_txt = st.container()

        with col_txt:
            # Item name — bold, uppercase
            st.markdown(
                f'<div style="font-family:\'Inter\',sans-serif; font-weight:700; '
                f'font-size:1rem; text-transform:uppercase; letter-spacing:1px; '
                f'margin-bottom:0.2rem;">{name_brand}</div>',
                unsafe_allow_html=True
            )
            # Price Range — grey, smaller
            price_range = item.get("price_range", "")
            rec_size = item.get("recommended_size", "")
            
            if price_range or rec_size:
                size_html = f" | Size: {rec_size}" if rec_size else ""
                st.markdown(
                    f'<div style="font-family:\'Inter\',sans-serif; font-size:0.75rem; '
                    f'color:#888; letter-spacing:1px; margin-bottom:0.8rem;">{price_range}{size_html}</div>',
                    unsafe_allow_html=True
                )
            # Reason — language-matched by AI
            st.markdown(
                f'<div style="font-family:\'Inter\',sans-serif; font-size:0.85rem; '
                f'color:#555; line-height:1.7; margin-bottom:1.5rem;">{reason}</div>',
                unsafe_allow_html=True
            )
            # ZARA gender-aware Discover button (skip for Padres jerseys)
            if "Padres" not in name_brand and "教士隊" not in name_brand:
                search_query = urllib.parse.quote(name_brand)
                section  = "MAN" if user_gender in ["Male", "男性"] else "WOMAN"
                zara_url = f"https://www.zara.com/tw/zt/search?searchTerm={search_query}&section={section}"
                
                # link_button 直接跳 ZARA，不觸發 rerun，手機也正常
                st.link_button(t["buy"], zara_url)
                # 渲染時記錄 impression
                if f"imp_{idx}" not in st.session_state:
                    st.session_state[f"imp_{idx}"] = True
                    log_event("discover_view", item_name=name_brand)

        if idx < len(zara_items) - 1:
            st.divider()

    # Other Brands (Text Only)
    if res.get("other_brands"):
        st.markdown(
            '<div style="font-family:\'Bodoni Moda\',serif; font-size:1.1rem; '
            'letter-spacing:2px; margin-top:2.5rem; margin-bottom:1.5rem; '
            'border-top:1px solid #eee; padding-top:2rem;">OTHER BRANDS</div>',
            unsafe_allow_html=True
        )
        for idx, alt in enumerate(res.get("other_brands", [])):
            name = alt.get('name','')
            reason = alt.get('reason','')
            js_name = name.replace("'", "\\'")
            
            st.markdown(f"""
            <div style="border-left:2px solid #000; padding:0.5rem 1rem; margin-bottom:1.2rem;">
                <div style="font-family:'Inter',sans-serif; font-weight:600; font-size:0.9rem; margin-bottom:0.2rem;">{name}</div>
                <div style="font-family:'Inter',sans-serif; font-size:0.8rem; color:#666; line-height:1.5;">{reason}</div>
            </div>
            """, unsafe_allow_html=True)

    # Accessories Recommendations
    if res.get("accessories"):
        st.markdown(
            '<div style="font-family:\'Bodoni Moda\',serif; font-size:1.1rem; '
            'letter-spacing:2px; margin-top:2.5rem; margin-bottom:1.5rem;">ACCESSORIES</div>',
            unsafe_allow_html=True
        )
        for idx_acc, acc in enumerate(res.get("accessories", [])):
            name = acc.get('name','')
            reason = acc.get('reason','')
            js_name = name.replace("'", "\\'")
            
            st.markdown(f"""
            <div style="border-left:2px solid #ccc; padding:0.5rem 1rem; margin-bottom:1.2rem;">
                <div style="font-family:'Inter',sans-serif; font-weight:600; font-size:0.9rem; margin-bottom:0.2rem;">{name}</div>
                <div style="font-family:'Inter',sans-serif; font-size:0.8rem; color:#777; line-height:1.5;">{reason}</div>
            </div>
            """, unsafe_allow_html=True)

    # Feedback
    st.markdown("---")
    st.write("How do you like this outfit?" if lang_select == "English" else "您喜歡這套穿搭嗎？")
    f1, f2, f3 = st.columns([2, 2, 4])
    with f1:
        st.button("👍 Like", on_click=track_like)
    with f2:
        st.button("👎 Dislike", on_click=track_dislike)

st.markdown("<br><br><br>", unsafe_allow_html=True)
