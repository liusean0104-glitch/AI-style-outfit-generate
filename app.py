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
        # Check if secrets exist and the key is present
        if key in st.secrets:
            return st.secrets[key]
    except:
        # Fallback if st.secrets is not initialized or accessible (common in local dev)
        pass
    return os.getenv(key, default)

api_key = get_secret("GEMINI_API_KEY")
sb_url = get_secret("SUPABASE_URL")
sb_key = get_secret("SUPABASE_KEY")

st.set_page_config(page_title="AI Stylist", page_icon="👗", layout="centered")

import uuid

if "last_result" not in st.session_state:
    st.session_state.last_result = None

# 產生並持久化 session_id（不需登入，重新整理後保留）
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "rec_id" not in st.session_state:
    st.session_state.rec_id = None  # 最新一次推薦的 ID

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

def _supabase_post(table: str, payload: dict):
    """共用的 Supabase REST 寫入，失敗只印 console 不中斷 UI。"""
    if not sb_url or not sb_key:
        return None
    url = f"{sb_url}/rest/v1/{table}"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",  # 改成 representation 才能拿到回傳的 id
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=3)
        if r.ok:
            data = r.json()
            return data[0] if data else None
        else:
            print(f"[Supabase] {table} write failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[Supabase] {table} exception: {e}")
    return None


def log_session(gender, height, weight, season, occasion, weather, styles, language, has_photo):
    """
    在 sessions 表寫入這次的用戶 profile。
    用 UPSERT（on_conflict=session_id）避免重複 generate 時重複寫。
    """
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
        "height_cm": height,
        "weight_kg": weight,
        "season": season,
        "occasion": occasion,
        "weather": weather,
        "styles": styles,          # Supabase 支援 text[] → 傳 Python list 即可
        "language": language,
        "has_photo_upload": has_photo,
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=3)
    except Exception as e:
        print(f"[Supabase] sessions upsert exception: {e}")


def log_recommendation(result: dict) -> str | None:
    """
    把 AI 推薦結果寫入 recommendations 表，回傳新建的 rec_id。
    """
    payload = {
        "session_id": st.session_state.session_id,
        "model_used": result.get("model_used", "unknown"),
        "zara_items": result.get("zara_items", []),
        "other_brands": result.get("other_brands", []),
        "accessories": result.get("accessories", []),
        # latency_ms 在 generate 那邊計算後傳入，這裡預設 None
        "latency_ms": result.get("latency_ms"),
    }
    row = _supabase_post("recommendations", payload)
    return row["id"] if row else None


def log_event(event_type: str, item_name: str | None = None):
    """
    通用事件寫入：generate / like / dislike / discover_click
    """
    payload = {
        "session_id": st.session_state.session_id,
        "rec_id": st.session_state.rec_id,   # 可能是 None（generate 之前）
        "event_type": event_type,
        "item_name": item_name,
    }
    _supabase_post("events", payload)


def track_like():
    log_event("like")
    st.toast("Thank you! / 感謝您的回饋！")


def track_dislike():
    log_event("dislike")
    st.toast("We'll do better next time! / 我們會繼續改進！")

# 2. 核心 AI 函數
GEMMA_MODELS = [
    'gemini-2.0-flash', # Keep gemini as first priority just in case it works
    'gemma-4-31b-it',
    'gemma-4-26b-a4b-it',
    'gemma-3-27b-it',
    'gemma-3-12b-it',
    'gemma-3-4b-it',
    'gemma-3-1b-it',
    'gemma-3n-e4b-it',
    'gemma-3n-e2b-it'
]

def get_ai_recommendation(gender, height, weight, season, occ, wea, sty, lang, uploaded_image=None):
    if not api_key:
        return None, "Error: API Key missing"
    
    genai.configure(api_key=api_key)
    
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

    prompt = (
        f"{system_persona}\n"
        f"User Profile: Gender: {gender}, Height: {height}cm, Weight: {weight}kg.\n"
        f"Context: Season: {season}, Occasion: {occ}, Weather: {wea}, Style: {sty_str}.\n"
        f"{specific_style_rule}\n"
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
    for model_name in GEMMA_MODELS:
        try:
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
            continue
                
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
            "styles": ["Old Money", "City Boy", "Minimalist", "Streetwear", "Korean Style", "Y2K", "Workwear", "Japanese Casual", "Athleisure", "Vintage", "High Fashion", "Goth/Dark", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS"
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
            "styles": ["Old Money", "City Boy", "Minimalist", "Streetwear", "Korean Style", "Y2K", "Workwear", "Japanese Casual", "Athleisure", "Vintage", "High Fashion", "Goth/Dark", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS"
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

# 5. 執行按鈕
st.markdown("<br>", unsafe_allow_html=True)
if st.button(t["btn"]):
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
            user_occ, user_wea, user_sty, lang_select, uploaded_file
        )
        tip_idx = 0
        start_time = time.time()
        expected_seconds = 55 # Increased for multi-modal analysis and image search
        
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
        # 計算 latency（在 ThreadPoolExecutor 外面算，用 start_time）
        result["latency_ms"] = int((time.time() - start_time) * 1000)

        st.session_state.last_result = result

        # 1. 寫入 session（用戶 profile）
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

        # 2. 寫入推薦結果，拿到 rec_id
        rec_id = log_recommendation(result)
        st.session_state.rec_id = rec_id

        # 3. 寫入 generate 事件
        log_event("generate")

# ─── Image Engine ──────────────────────────────────────────────────────────
URL_FALLBACK_TOPS   = "https://i.postimg.cc/7Z4QNfN7/shirts.jpg"
URL_FALLBACK_PANTS  = "https://i.postimg.cc/j233g442/pants.jpg"
URL_FALLBACK_OTHERS = "https://i.postimg.cc/13K77sWH/loafers.jpg"

SPECIFIC_ITEM_IMAGES = {
    "strappy heeled sandals":    "https://i.postimg.cc/X7J8DbyL/Strappy-Heeled-Sandals.jpg",
    "wide leg cargo pant":       "https://i.postimg.cc/bNJTFh23/wide-leg-cargo-pant.jpg",
    "cropped linen blend shirt": "https://i.postimg.cc/Qxtbn3WS/women-Cropped-Linen-Blend-Shirt.jpg",
    "sleeveless satin blouse":   "https://i.postimg.cc/gjDGwhKn/Sleeveless-Satin-Blouse.jpg",
    "linen blend trousers":      "https://i.postimg.cc/kG9nXsWG/Linen-Blend-Trousers.jpg",
    "padres city connect jersey":"https://i.postimg.cc/cLXyQZwy/city-connect.jpg",
    "教士隊城市限定球衣":        "https://i.postimg.cc/cLXyQZwy/city-connect.jpg",
    "padres home jersey":        "https://i.postimg.cc/4xBkzZVC/home-jersey.avif",
    "教士隊主場球衣":            "https://i.postimg.cc/4xBkzZVC/home-jersey.avif"
}

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

def _is_plausible_image_url(url: str) -> bool:
    """不做網路請求，純靠 URL 格式快速過濾明顯壞連結。"""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower().split("?")[0]  # 去掉 query string 再判斷副檔名
    return any(url_lower.endswith(ext) for ext in VALID_EXTENSIONS)

def _ddg_search_one(query: str, max_results: int = 3) -> str | None:
    """單一 query 的 DDG 搜尋，回傳第一個格式合理的圖片 URL。"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(
                keywords=query,
                region="wt-wt",
                safesearch="moderate",
                max_results=max_results
            ))
        for r in results:
            url = r.get("image", "")
            if _is_plausible_image_url(url):
                return url
    except Exception:
        pass
    return None

async def _race_queries(queries: list[str]) -> list[str]:
    """並行跑所有 query，收集所有成功結果（去重）。"""
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _ddg_search_one, q) for q in queries]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 去重、過濾 None
    seen = set()
    unique = []
    for r in results:
        if r and isinstance(r, str) and r not in seen:
            seen.add(r)
            unique.append(r)
    return unique

def get_zara_images(item_name: str, gender: str, category: str = "others") -> list[str]:
    """回傳多張圖片 URL 的 list。"""
    n = item_name.lower().strip()
    g = "man" if gender in ["Male", "男性"] else "woman"

    # 1. 精確比對（只有一張，直接包成 list）
    for key, url in SPECIFIC_ITEM_IMAGES.items():
        if key in n:
            return [url]

    # 2. 並行搜尋，收集全部結果
    queries = [
        f"zara {g} {item_name} outfit",
        f"{g} {item_name} fashion product",
        f"{item_name} clothing lookbook",
    ]

    try:
        results = asyncio.run(_race_queries(queries))
        if results:
            return results
    except Exception:
        pass

    # 3. Fallback
    top_keywords   = ("shirt", "襯衫", "blouse", "top", "tee")
    pants_keywords = ("pants", "褲", "trouser", "cargo", "jeans")
    if any(k in n for k in top_keywords) or category == "top":
        return [URL_FALLBACK_TOPS]
    if any(k in n for k in pants_keywords) or category == "pants":
        return [URL_FALLBACK_PANTS]
    return [URL_FALLBACK_OTHERS]

def render_image_carousel(item_key: str, urls: list[str]):
    """
    處理 Streamlit 中的圖片左右切換。
    """
    if not urls:
        return

    idx_key = f"img_idx_{item_key.replace(' ', '_')}"

    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    idx = st.session_state[idx_key]
    total = len(urls)

    if total > 1:
        # 使用自定義容器保持 ZARA 比例，並加上導航按鈕
        col_prev, col_main, col_next = st.columns([1, 8, 1])
        
        with col_prev:
            st.markdown("<div style='height: 80px;'></div>", unsafe_allow_html=True)
            if st.button("‹", key=f"prev_{idx_key}", disabled=(idx == 0)):
                st.session_state[idx_key] -= 1
                st.rerun()

        with col_main:
            img_url = urls[idx]
            st.markdown(
                f"""
                <div class="img-container">
                    <img src="{img_url}">
                </div>
                <div style="text-align:center; font-family:'Inter',sans-serif; font-size:0.7rem; color:#888; margin-top:5px;">
                    {idx + 1} / {total}
                </div>
                """,
                unsafe_allow_html=True
            )

        with col_next:
            st.markdown("<div style='height: 80px;'></div>", unsafe_allow_html=True)
            if st.button("›", key=f"next_{idx_key}", disabled=(idx == total - 1)):
                st.session_state[idx_key] += 1
                st.rerun()
    else:
        # 只有一張就維持原樣
        img_url = urls[0]
        st.markdown(
            f"""
            <div class="img-container">
                <img src="{img_url}">
            </div>
            """,
            unsafe_allow_html=True
        )

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

        img_urls   = get_zara_images(raw_name, user_gender, category) # 爬圖用原始名稱更準確

        col_img_area, col_txt = st.columns([1, 1.5])

        with col_img_area:
            render_image_carousel(item_key=name_brand, urls=img_urls)

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
                
                # Cloud-compatible Discover Link
                st.link_button(t["buy"], zara_url)

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
