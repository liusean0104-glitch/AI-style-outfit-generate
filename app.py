import streamlit as st
import os
import google.generativeai as genai
from dotenv import load_dotenv
import json
import urllib.parse
import requests
import asyncio
import time
import uuid
import re
import threading

# 1. 載入與設定
load_dotenv(override=True)

def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

api_key = get_secret("GEMINI_API_KEY")
sb_url  = get_secret("SUPABASE_URL")
sb_key  = get_secret("SUPABASE_KEY")

st.set_page_config(page_title="AI Stylist", page_icon="👗", layout="centered")

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "rec_id" not in st.session_state:
    st.session_state.rec_id = None

# 2. CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,wght@0,400..900;1,400..900&family=Inter:wght@100..900&display=swap');
    .stApp { background-color: #FFFFFF; }
    .magazine-title {
        font-family: 'Bodoni Moda', serif;
        font-size: 3.5rem; font-weight: 800;
        text-align: center; letter-spacing: -1px;
        margin-bottom: 0.5rem; color: #000;
    }
    .magazine-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 0.8rem; text-transform: uppercase;
        text-align: center; letter-spacing: 5px;
        color: #666; margin-bottom: 3rem;
    }
    div.stButton > button:first-child {
        background-color: #000000; color: #ffffff;
        border-radius: 0px; border: none;
        font-family: 'Inter', sans-serif;
        text-transform: uppercase; font-weight: 500;
        letter-spacing: 2px; padding: 0.75rem 2rem;
        width: 100%; transition: opacity 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background-color: #000000; color: #ffffff; opacity: 0.8;
    }
    div[data-testid="stLinkButton"] > a {
        background-color: #000000 !important; color: #ffffff !important;
        border-radius: 0px !important; border: none !important;
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase !important; font-weight: 500 !important;
        letter-spacing: 2px !important; padding: 0.5rem 1rem !important;
        display: flex !important; justify-content: center !important;
        white-space: nowrap !important;
    }
    div.stButton > button { white-space: nowrap !important; }
    .stExpander { border: none !important; border-top: 1px solid #eee !important; border-radius: 0px !important; }
    .img-container {
        width: 100%; aspect-ratio: 3/4; overflow: hidden;
        border: 1px solid #f0f0f0; background-color: #f9f9f9; position: relative;
    }
    .img-container img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .curating-container { padding: 4rem 1rem; text-align: center; background: #fff; }
    .curating-title {
        font-family: 'Bodoni Moda', serif; font-size: 1.5rem;
        letter-spacing: 4px; text-transform: uppercase;
        margin-bottom: 2rem; color: #000;
    }
    .scanning-line {
        width: 100%; height: 1px; background: #eee;
        position: relative; overflow: hidden; margin-bottom: 2rem;
    }
    .scanning-line::after {
        content: ""; position: absolute; left: -100%; width: 100%; height: 100%;
        background: linear-gradient(90deg, transparent, #000, transparent);
        animation: scan 2s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }
    @keyframes scan { 0% { left: -100%; } 100% { left: 100%; } }
    input::-webkit-outer-spin-button, input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
    input[type=number] { -moz-appearance: textfield; }
    button[data-testid="stNumberInputStepUp"], button[data-testid="stNumberInputStepDown"] { display: none !important; }
    .loading-tip {
        font-family: 'Inter', sans-serif; font-size: 0.75rem;
        letter-spacing: 2px; text-transform: uppercase; color: #888;
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
    .floral-decoration {
        position: fixed; z-index: 99; pointer-events: none;
        opacity: 0.4; width: 400px; filter: contrast(0.9) brightness(1.1);
    }
    .floral-tl { top: -100px; left: -120px; transform: rotate(-15deg); }
    .floral-br { bottom: -100px; right: -120px; transform: rotate(165deg); }
    @media (max-width: 768px) {
        .floral-decoration { display: none !important; }
        .magazine-title { font-size: 2.2rem !important; margin-top: 1rem; }
        .magazine-subtitle { letter-spacing: 2px !important; font-size: 0.6rem !important; margin-bottom: 1.5rem !important; }
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; flex-wrap: nowrap !important; gap: 10px !important; }
        [data-testid="stHorizontalBlock"] > div { min-width: 0 !important; flex: 1 1 0% !important; }
    }
</style>
""", unsafe_allow_html=True)

# ── Supabase helpers ────────────────────────────────────────────

def _sb_post_bg(table: str, payload: dict, prefer: str = "return=minimal"):
    """Background thread write — never blocks UI."""
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
        r = requests.post(url, headers=headers, json=payload, timeout=5)
        if r.ok and prefer == "return=representation":
            data = r.json()
            return data[0] if data else None
        elif not r.ok:
            print(f"[Supabase] {table} error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[Supabase] {table} exception: {e}")
    return None


def log_session(gender, height, weight, season, occasion, weather, styles, language, has_photo):
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
        "styles": styles,       # list — Supabase accepts JSON array for text[]
        "language": language,
        "has_photo_upload": has_photo,
    }
    def _do():
        try:
            requests.post(url, headers=headers, json=payload, timeout=5)
        except Exception as e:
            print(f"[Supabase] sessions exception: {e}")
    threading.Thread(target=_do, daemon=True).start()


def log_recommendation(result: dict):
    """Synchronous — we need the rec_id back."""
    payload = {
        "session_id": st.session_state.session_id,
        "model_used": result.get("model_used", "unknown"),
        "zara_items":   result.get("zara_items", []),
        "other_brands": result.get("other_brands", []),
        "accessories":  result.get("accessories", []),
        "latency_ms":   result.get("latency_ms"),
    }
    row = _sb_post_bg("recommendations", payload, prefer="return=representation")
    return row["id"] if row else None


def log_event(event_type: str, item_name: str = None):
    payload = {
        "session_id": st.session_state.session_id,
        "rec_id":     st.session_state.rec_id,
        "event_type": event_type,
        "item_name":  item_name,
    }
    threading.Thread(target=_sb_post_bg, args=("events", payload), daemon=True).start()


def track_like():
    log_event("like")
    st.toast("Thank you! / 感謝您的回饋！")

def track_dislike():
    log_event("dislike")
    st.toast("We'll do better next time! / 我們會繼續改進！")

# ── AI ──────────────────────────────────────────────────────────

GEMMA_MODELS = [
    'gemini-2.0-flash',
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
        p_cc_name = "教士隊城市限定球衣"; p_cc_reason = "這套穿搭的核心單品。"
        p_home_name = "教士隊主場球衣";  p_home_reason = "這套穿搭的核心單品。"
        p_price = "球隊商店限定"
    else:
        p_cc_name = "Padres City Connect Jersey"; p_cc_reason = "The center piece of this outfit."
        p_home_name = "Padres Home Jersey";        p_home_reason = "The center piece of this outfit."
        p_price = "Team Store Exclusive"
    if "Padres City Connect Jersey" in sty:
        specific_style_rule = (
            f"SPECIAL STYLE RULE: The user IS wearing a '{p_cc_name}' as the main top. "
            f"In your JSON response, the first item in 'zara_items' MUST be exactly: "
            f"{{\"name\": \"{p_cc_name}\", \"reason\": \"{p_cc_reason}\", \"category\": \"top\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"Do NOT suggest any other main tops."
        )
    elif "Padres Home Jersey" in sty:
        specific_style_rule = (
            f"SPECIAL STYLE RULE: The user IS wearing a '{p_home_name}' as the main top. "
            f"In your JSON response, the first item in 'zara_items' MUST be exactly: "
            f"{{\"name\": \"{p_home_name}\", \"reason\": \"{p_home_reason}\", \"category\": \"top\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"Do NOT suggest any other main tops."
        )
    prompt = (
        f"{system_persona}\n{image_analysis_instruction}\n"
        f"User Profile: Gender: {gender}, Height: {height}cm, Weight: {weight}kg.\n"
        f"Context: Season: {season}, Occasion: {occ}, Weather: {wea}, Style: {sty_str}.\n"
        f"{specific_style_rule}\n"
        f"LANGUAGE RULE: Respond in {lang}. Use Traditional Chinese if '繁體中文'.\n"
        f"CURRENCY RULE: {currency_instruction}\n"
        f"Provide response in valid JSON format ONLY:\n"
        f"{{\n"
        f"  \"critique\": \"(Optional) Analysis of uploaded outfit if provided, otherwise empty.\",\n"
        f"  \"zara_items\": [\n"
        f"    {{\"name\": \"ZARA [Item Name]\", \"reason\": \"Reason why this fits their physique.\", "
        f"\"category\": \"top/pants/shoes\", \"price_range\": \"Estimated price range\", "
        f"\"recommended_size\": \"Calculated size\"}}\n"
        f"  ],\n"
        f"  \"other_brands\": [{{\"name\": \"[Brand] [Item]\", \"reason\": \"Styling tip.\"}}],\n"
        f"  \"accessories\": [{{\"name\": \"[Item]\", \"reason\": \"How it completes the look.\"}}],\n"
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
            clean_text = text.strip()
            start_idx = clean_text.find('{')
            end_idx = clean_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                data = json.loads(clean_text[start_idx:end_idx+1])
                return {
                    "critique":    data.get("critique", ""),
                    "zara_items":  data.get("zara_items", []),
                    "other_brands":data.get("other_brands", []),
                    "accessories": data.get("accessories", []),
                    "description": data.get("description", ""),
                    "model_used":  model_name
                }, None
        except Exception as e:
            last_error = str(e)
            continue
    return None, f"All models exhausted. Last error: {last_error}"

def get_base64_image(path):
    import base64
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

# ── Image Engine (single image, no carousel) ────────────────────

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
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower().split("?")[0]
    return any(url_lower.endswith(ext) for ext in VALID_EXTENSIONS)

def get_zara_image(item_name: str, gender: str, category: str = "others") -> str:
    """回傳單張圖片 URL（快速，不做多圖搜尋）。"""
    n = item_name.lower().strip()
    g = "man" if gender in ["Male", "男性"] else "woman"

    # 1. 精確比對靜態圖
    for key, url in SPECIFIC_ITEM_IMAGES.items():
        if key in n:
            return url

    # 2. 單次 DDG 搜尋（只取第一個結果）
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(
                keywords=f"zara {g} {item_name}",
                region="wt-wt",
                safesearch="moderate",
                max_results=5,
            ))
        for r in results:
            url = r.get("image", "")
            if _is_plausible_image_url(url):
                return url
    except Exception:
        pass

    # 3. Fallback
    top_kw   = ("shirt", "襯衫", "blouse", "top", "tee")
    pants_kw = ("pants", "褲", "trouser", "cargo", "jeans")
    if any(k in n for k in top_kw) or category == "top":
        return URL_FALLBACK_TOPS
    if any(k in n for k in pants_kw) or category == "pants":
        return URL_FALLBACK_PANTS
    return URL_FALLBACK_OTHERS

# ── Header ──────────────────────────────────────────────────────
st.markdown('<div class="magazine-title">VOGUE AI STYLIST</div>', unsafe_allow_html=True)
st.markdown('<div class="magazine-subtitle">INTELLIGENT FASHION CURATION</div>', unsafe_allow_html=True)

# ── Language & Gender ────────────────────────────────────────────
col_lang, col_gen = st.columns(2)
with col_lang:
    lang_select = st.selectbox("Language / 語言", ["繁體中文", "English"], label_visibility="collapsed")
    if lang_select == "繁體中文":
        t = {
            "btn": "Generate Collection", "buy": "Discover",
            "occ": "Occasion", "wea": "Weather", "gender": "Gender",
            "height": "Height", "weight": "Weight", "season": "Season",
            "style": "Style Aesthetic",
            "genders": ["Male", "Female", "Other"],
            "seasons": ["Spring", "Summer", "Autumn", "Winter"],
            "occs": ["Casual", "Business", "Date", "Gala"],
            "weas": ["Hot", "Comfortable", "Rainy", "Cold"],
            "styles": ["Old Money", "City Boy", "Minimalist", "Streetwear", "Korean Style", "Y2K",
                       "Workwear", "Japanese Casual", "Athleisure", "Vintage", "High Fashion",
                       "Goth/Dark", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS",
        }
    else:
        t = {
            "btn": "Generate Collection", "buy": "Discover",
            "occ": "Occasion", "wea": "Weather", "gender": "Gender",
            "height": "Height", "weight": "Weight", "season": "Season",
            "style": "Style Aesthetic",
            "genders": ["Male", "Female", "Other"],
            "seasons": ["Spring", "Summer", "Autumn", "Winter"],
            "occs": ["Casual", "Business", "Date", "Gala"],
            "weas": ["Hot", "Comfortable", "Rainy", "Cold"],
            "styles": ["Old Money", "City Boy", "Minimalist", "Streetwear", "Korean Style", "Y2K",
                       "Workwear", "Japanese Casual", "Athleisure", "Vintage", "High Fashion",
                       "Goth/Dark", "Padres City Connect Jersey", "Padres Home Jersey"],
            "upload_label": "Upload Your Outfit (Optional)",
            "upload_help": "We'll analyze your style and physique.",
            "analysis_title": "AI OUTFIT ANALYSIS",
        }

with col_gen:
    user_gender = st.selectbox(t["gender"], t["genders"], label_visibility="collapsed")

# Floral decoration
floral_b64 = get_base64_image("floral_roses.png")
if floral_b64:
    st.markdown(f"""
        <img src="data:image/png;base64,{floral_b64}" class="floral-decoration floral-tl">
        <img src="data:image/png;base64,{floral_b64}" class="floral-decoration floral-br">
    """, unsafe_allow_html=True)

# ── Inputs ───────────────────────────────────────────────────────
col_h, col_w = st.columns(2)
with col_h:
    user_height = st.number_input(t["height"], min_value=100, max_value=250, value=175, step=1)
with col_w:
    user_weight = st.number_input(t["weight"], min_value=30, max_value=200, value=70, step=1)

col_s, col_o, col_w_env = st.columns(3)
with col_s:
    user_season = st.selectbox(t["season"], t["seasons"])
with col_o:
    user_occ = st.selectbox(t["occ"], t["occs"])
with col_w_env:
    user_wea = st.selectbox(t["wea"], t["weas"])

user_sty = st.multiselect(t["style"], t["styles"], default=[])

uploaded_file = st.file_uploader(t["upload_label"], type=["jpg", "png", "jpeg"], help=t["upload_help"])
if uploaded_file:
    _, col_mid, _ = st.columns([1, 1, 1])
    with col_mid:
        st.image(uploaded_file, caption="Current Outfit Preview", use_container_width=True)

# ── Generate ─────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
if st.button(t["btn"]):
    TIPS = {
        "繁體中文": ["正在分析您的身形比例...","正在挑選 ZARA 季度單品...","正在優化服裝剪裁平衡...","正在注入法式簡約美學...","您的專屬時尚提案即將呈現..."],
        "English":  ["Analyzing your body proportions...","Selecting seasonal ZARA pieces...","Optimizing garment cut balance...","Injecting minimalist aesthetics...","Your curated style is almost ready..."],
    }
    tips = TIPS[lang_select]
    ui_placeholder = st.empty()

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(
            get_ai_recommendation,
            user_gender, user_height, user_weight, user_season,
            user_occ, user_wea, user_sty, lang_select, uploaded_file
        )
        tip_idx = 0
        start_time = time.time()
        expected_seconds = 55
        while not future.done():
            elapsed = time.time() - start_time
            remaining = max(1, int(expected_seconds - elapsed))
            timer_text = f"ETA: {remaining}s" if remaining > 0 else "Finalizing..."
            with ui_placeholder.container():
                st.markdown(f"""
                <div class="curating-container">
                    <div class="curating-title">Curating Your Style</div>
                    <div class="scanning-line"></div>
                    <div class="loading-tip">{tips[tip_idx % len(tips)]}</div>
                    <div style="font-family:'Inter',sans-serif;font-size:0.7rem;letter-spacing:3px;color:#000;margin-top:1.5rem;font-weight:600;">{timer_text}</div>
                </div>
                """, unsafe_allow_html=True)
            tip_idx += 1
            time.sleep(1.5)
        ui_placeholder.empty()
        result, err = future.result()

    if err:
        st.error(f"STYLING SERVICE UNAVAILABLE: {err}")
    else:
        result["latency_ms"] = int((time.time() - start_time) * 1000)
        st.session_state.last_result = result

        # 寫入 Supabase（背景執行，不卡 UI）
        log_session(
            gender=user_gender, height=user_height, weight=user_weight,
            season=user_season, occasion=user_occ, weather=user_wea,
            styles=user_sty, language=lang_select,
            has_photo=uploaded_file is not None,
        )
        rec_id = log_recommendation(result)
        st.session_state.rec_id = rec_id
        log_event("generate")

# ── Results ──────────────────────────────────────────────────────
if st.session_state.last_result:
    res = st.session_state.last_result
    st.markdown("---")

    if res.get("critique"):
        st.markdown(
            f'<div style="font-family:\'Bodoni Moda\',serif;font-size:1.4rem;letter-spacing:3px;margin-bottom:1rem;">{t["analysis_title"]}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-family:\'Inter\',sans-serif;background-color:#f9f9f9;padding:1.5rem;border-left:3px solid #000;margin-bottom:2.5rem;font-style:italic;color:#333;">{res["critique"]}</div>',
            unsafe_allow_html=True)

    if res.get("description"):
        st.markdown(
            f'<div style="font-family:\'Inter\',sans-serif;line-height:1.8;color:#444;font-size:0.95rem;margin-bottom:2.5rem;">{res["description"]}</div>',
            unsafe_allow_html=True)

    st.markdown(
        '<div style="font-family:\'Bodoni Moda\',serif;font-size:1.4rem;letter-spacing:3px;margin-bottom:1.5rem;">THE COLLECTION</div>',
        unsafe_allow_html=True)

    zara_items = res.get("zara_items", [])
    for idx, item in enumerate(zara_items):
        raw_name = item.get("name", "")
        reason   = item.get("reason", "")
        category = item.get("category", "others")

        # 清理雙語名稱
        match = re.search(r'(.+?)\s*\((.+?)\)', raw_name)
        if match:
            part1, part2 = match.group(1).strip(), match.group(2).strip()
            has_zh1 = any('\u4e00' <= c <= '\u9fff' for c in part1)
            has_zh2 = any('\u4e00' <= c <= '\u9fff' for c in part2)
            if lang_select == "繁體中文":
                name_brand = part1 if has_zh1 else (part2 if has_zh2 else raw_name)
            else:
                name_brand = part1 if not has_zh1 else (part2 if not has_zh2 else raw_name)
        else:
            name_brand = raw_name

        # 單張圖（從 session_state 快取，避免重複搜尋）
        img_cache_key = f"img_{idx}"
        if img_cache_key not in st.session_state:
            st.session_state[img_cache_key] = get_zara_image(raw_name, user_gender, category)
        img_url = st.session_state[img_cache_key]

        col_img_area, col_txt = st.columns([1, 1.5])

        with col_img_area:
            st.markdown(
                f'<div class="img-container"><img src="{img_url}"></div>',
                unsafe_allow_html=True)

        with col_txt:
            st.markdown(
                f'<div style="font-family:\'Inter\',sans-serif;font-weight:700;font-size:1rem;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.2rem;">{name_brand}</div>',
                unsafe_allow_html=True)

            price_range = item.get("price_range", "")
            rec_size    = item.get("recommended_size", "")
            if price_range or rec_size:
                size_html = f" | Size: {rec_size}" if rec_size else ""
                st.markdown(
                    f'<div style="font-family:\'Inter\',sans-serif;font-size:0.75rem;color:#888;letter-spacing:1px;margin-bottom:0.8rem;">{price_range}{size_html}</div>',
                    unsafe_allow_html=True)

            st.markdown(
                f'<div style="font-family:\'Inter\',sans-serif;font-size:0.85rem;color:#555;line-height:1.7;margin-bottom:1.5rem;">{reason}</div>',
                unsafe_allow_html=True)

            # Discover — link_button 直接跳 ZARA，on_click 記錄事件
            if "Padres" not in name_brand and "教士隊" not in name_brand:
                search_query = urllib.parse.quote(name_brand)
                section  = "MAN" if user_gender in ["Male", "男性"] else "WOMAN"
                zara_url = f"https://www.zara.com/tw/zt/search?searchTerm={search_query}&section={section}"

                st.link_button(
                    t["buy"],
                    zara_url,
                )
                # 在 link_button 旁邊加一個隱形 on_click 追蹤
                # 因為 link_button 不支援 on_click，用一個小 checkbox state 技巧：
                # 用 st.button 做追蹤，CSS 隱藏它（最簡單可行）
                # ↓ 實際上最乾淨的做法是接受 link_button 無法追蹤 click，
                #   但 log impression（頁面渲染時就記錄）：
                if f"logged_discover_{idx}" not in st.session_state:
                    st.session_state[f"logged_discover_{idx}"] = True
                    log_event("discover_view", item_name=name_brand)

        if idx < len(zara_items) - 1:
            st.divider()

    # Other Brands
    if res.get("other_brands"):
        st.markdown(
            '<div style="font-family:\'Bodoni Moda\',serif;font-size:1.1rem;letter-spacing:2px;margin-top:2.5rem;margin-bottom:1.5rem;border-top:1px solid #eee;padding-top:2rem;">OTHER BRANDS</div>',
            unsafe_allow_html=True)
        for alt in res.get("other_brands", []):
            st.markdown(f"""
            <div style="border-left:2px solid #000;padding:0.5rem 1rem;margin-bottom:1.2rem;">
                <div style="font-family:'Inter',sans-serif;font-weight:600;font-size:0.9rem;margin-bottom:0.2rem;">{alt.get('name','')}</div>
                <div style="font-family:'Inter',sans-serif;font-size:0.8rem;color:#666;line-height:1.5;">{alt.get('reason','')}</div>
            </div>
            """, unsafe_allow_html=True)

    # Accessories
    if res.get("accessories"):
        st.markdown(
            '<div style="font-family:\'Bodoni Moda\',serif;font-size:1.1rem;letter-spacing:2px;margin-top:2.5rem;margin-bottom:1.5rem;">ACCESSORIES</div>',
            unsafe_allow_html=True)
        for acc in res.get("accessories", []):
            st.markdown(f"""
            <div style="border-left:2px solid #ccc;padding:0.5rem 1rem;margin-bottom:1.2rem;">
                <div style="font-family:'Inter',sans-serif;font-weight:600;font-size:0.9rem;margin-bottom:0.2rem;">{acc.get('name','')}</div>
                <div style="font-family:'Inter',sans-serif;font-size:0.8rem;color:#777;line-height:1.5;">{acc.get('reason','')}</div>
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
