import streamlit as st
import streamlit.components.v1 as components
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

# ── API Key 列表（KEY_3 優先，KEY_1 備援）──
ALL_API_KEYS = [
    k for k in [
        get_secret("GEMINI_API_KEY_3"),  # 主力 Key
        get_secret("GEMINI_API_KEY_4"),
        get_secret("GEMINI_API_KEY_2"),
        get_secret("GEMINI_API_KEY"),    # 原 Key 1 降為最後備援
    ] if k
]

# ── 模型優先序 + RPD Soft Limit（達到閾值主動換 Key，不等 429）──
MODEL_TIERS = [
    # 第一優先：Gemini 3.5 Flash（RPD=20，留 2 緩衝）
    {"name": "gemini-3.5-flash",      "rpd_soft_limit": 18},
    # 第二：Gemini 2.5 Flash（RPD=20，留 2 緩衝）
    {"name": "gemini-2.5-flash",      "rpd_soft_limit": 18},
    # 最終備援：Gemini 3.1 Flash Lite（RPD=500，留 20 緩衝）品質略低但額度充裕
    {"name": "gemini-3.1-flash-lite", "rpd_soft_limit": 480},
]

import threading as _threading
import datetime as _datetime

_key_lock = _threading.Lock()
_key_cooldown: dict = {}
_daily_count: dict = {}
_daily_date: dict = {}

def _today_pt() -> str:
    import datetime, zoneinfo
    try:
        pt = zoneinfo.ZoneInfo("America/Los_Angeles")
        return datetime.datetime.now(pt).strftime("%Y-%m-%d")
    except Exception:
        return _datetime.datetime.utcnow().strftime("%Y-%m-%d")

def _get_daily_count(key_idx: int, model_name: str) -> int:
    k = (key_idx, model_name)
    today = _today_pt()
    if _daily_date.get(k) != today:
        _daily_count[k] = 0
        _daily_date[k] = today
    return _daily_count.get(k, 0)

def _inc_daily_count(key_idx: int, model_name: str):
    k = (key_idx, model_name)
    today = _today_pt()
    if _daily_date.get(k) != today:
        _daily_count[k] = 0
        _daily_date[k] = today
    _daily_count[k] = _daily_count.get(k, 0) + 1
    print(f"[Quota] Key#{key_idx} {model_name} today={_daily_count[k]}")

def _pick_key_for_model(model_name: str, rpd_soft_limit: int):
    n = len(ALL_API_KEYS)
    if n == 0:
        return None, None
    now = time.time()
    with _key_lock:
        for idx in range(n):
            if now < _key_cooldown.get(idx, 0):
                continue
            if _get_daily_count(idx, model_name) >= rpd_soft_limit:
                continue
            return idx, ALL_API_KEYS[idx]
    return None, None

def _mark_key_rpm_limited(key_idx: int, retry_seconds: int = 65):
    with _key_lock:
        _key_cooldown[key_idx] = time.time() + retry_seconds
        print(f"[KeyRotation] Key#{key_idx} RPM-limited for {retry_seconds}s")

# 對外相容
api_key = ALL_API_KEYS[0] if ALL_API_KEYS else None

# ── Supabase Quota 持久化（啟動時還原今日計數，重啟不失憶）──
def _sb_quota_restore():
    """從 Supabase key_quota 表讀回今日計數，避免 Streamlit 重啟後歸零。"""
    if not sb_url or not sb_key:
        return
    today = _today_pt()
    url = f"{sb_url}/rest/v1/key_quota?date=eq.{today}"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.ok:
            for row in r.json():
                k = (row["key_idx"], row["model_name"])
                _daily_count[k] = row["count"]
                _daily_date[k] = today
            print(f"[Quota] Restored {len(r.json())} quota rows from Supabase")
    except Exception as e:
        print(f"[Quota] restore failed: {e}")

def _sb_quota_upsert(key_idx: int, model_name: str, count: int):
    """把最新計數寫回 Supabase key_quota 表（upsert）。"""
    if not sb_url or not sb_key:
        return
    today = _today_pt()
    url = f"{sb_url}/rest/v1/key_quota"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {"key_idx": key_idx, "model_name": model_name, "date": today, "count": count}
    try:
        requests.post(url, headers=headers, json=payload, timeout=2)
    except Exception as e:
        print(f"[Quota] upsert failed: {e}")

# ── 方案三：Response Cache（模組層級，跨 session 共享）──
# 只快取「無圖、無 custom prompt」的標準請求，key = 選單組合
import hashlib as _hashlib
_REC_CACHE: dict = {}       # { cache_key: result_dict }
_REC_CACHE_MAX = 200        # 最多快取幾筆（LRU 簡易版：超過就清最舊的）

def _make_cache_key(gender, height, weight, season, occ, wea, sty, lang) -> str:
    raw = f"{gender}|{height}|{weight}|{season}|{occ}|{wea}|{'_'.join(sorted(sty))}|{lang}"
    return _hashlib.md5(raw.encode()).hexdigest()

def _cache_get(key: str):
    return _REC_CACHE.get(key)

def _cache_set(key: str, value: dict):
    global _REC_CACHE
    if len(_REC_CACHE) >= _REC_CACHE_MAX:
        # 刪除最舊的 20 筆
        oldest = list(_REC_CACHE.keys())[:20]
        for k in oldest:
            del _REC_CACHE[k]
    _REC_CACHE[key] = value
sb_url = get_secret("SUPABASE_URL")
sb_key = get_secret("SUPABASE_KEY")
# ⚠️ 前端點擊追蹤會把這把 key 嵌進瀏覽器 HTML。
#    務必設定為 anon key（搭配 events 表 INSERT-only RLS policy），
#    絕對不要把 service_role key 放進 SUPABASE_ANON_KEY。
sb_anon_key = get_secret("SUPABASE_ANON_KEY", sb_key)
# 圖片穩定性：Supabase Storage public bucket 名稱
SB_IMAGE_BUCKET = get_secret("SB_IMAGE_BUCKET", "item-images")
# Pro 金流：Stripe Payment Link（在 Stripe Dashboard 建立，無需後端）
STRIPE_PAYMENT_LINK = get_secret("STRIPE_PAYMENT_LINK", "")
_sb_quota_restore()  # 啟動時從 Supabase 還原今日 Key×Model 計數

st.set_page_config(page_title="AI Stylist", page_icon="👗", layout="centered")

import uuid

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "rec_id" not in st.session_state:
    st.session_state.rec_id = None
# 方案三：Response Cache（模組層級，跨 session 共享）
if "_rec_cache" not in st.session_state:
    pass  # cache 放模組層級，不放 session_state（見下方）
# 方案四：前端節流 — 記錄每個 session 上次生成時間
if "_last_gen_time" not in st.session_state:
    st.session_state["_last_gen_time"] = 0.0
# 方案 E：Outfit Builder 狀態
if "builder_pool" not in st.session_state:
    st.session_state["builder_pool"] = {}   # {slot: [item, item, item]}
if "builder_idx" not in st.session_state:
    st.session_state["builder_idx"] = {"top":0,"pants":0,"shoes":0}
if "pro_intent_clicked" not in st.session_state:
    st.session_state["pro_intent_clicked"] = False
# ── Task 1：Conversational Memory ──
if "user_id" not in st.session_state:
    st.session_state["user_id"] = None      # 登入後 = md5(email)，未登入 = None
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None
if "user_profile" not in st.session_state:
    st.session_state["user_profile"] = None  # 從 user_profiles 表載入的偏好摘要
# ── Task 3：session 內互動訊號（未登入也有 single-session memory）──
if "clicked_items" not in st.session_state:
    st.session_state["clicked_items"] = []   # 本 session 點過 Discover 的單品名稱
if "liked_signal" not in st.session_state:
    st.session_state["liked_signal"] = []    # [("like"/"dislike", combo_names)]
# ── Task 2：swap AI reasoning cache ──
if "swap_reasons" not in st.session_state:
    st.session_state["swap_reasons"] = {}    # {f"{slot}_{idx}": "一句話解釋"}
# ── Task 4：Pro funnel 狀態 ──
if "pro_paywall_viewed" not in st.session_state:
    st.session_state["pro_paywall_viewed"] = False

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
        "user_id": st.session_state.get("user_id"),  # Task 1：登入用戶跨 session 關聯鍵
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


def _current_combo_names() -> str:
    pool = st.session_state.get("builder_pool", {}) or {}
    bidx = st.session_state.get("builder_idx", {}) or {}
    parts = []
    for s in ("top", "pants", "shoes"):
        opts = pool.get(s, [])
        i = bidx.get(s, 0)
        if opts and i < len(opts):
            parts.append(opts[i].get("name", ""))
    return " + ".join(p for p in parts if p)


def track_like():
    log_event("like")
    combo = _current_combo_names()
    if combo:
        st.session_state["liked_signal"].append(("like", combo))  # Task 3：回饋進下次 prompt
    st.toast("Thank you! / 感謝您的回饋！")


def track_dislike():
    log_event("dislike")
    combo = _current_combo_names()
    if combo:
        st.session_state["liked_signal"].append(("dislike", combo))
    st.toast("We'll do better next time! / 我們會繼續改進！")


# ─── Task 1 + 3：Memory & Feedback Loop helpers ─────────────────────────────

def _sb_get(table: str, params: dict) -> list:
    """共用查詢（PostgREST GET），失敗回空 list。"""
    if not sb_url or not sb_key:
        return []
    url = f"{sb_url}/rest/v1/{table}"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=3)
        if r.ok:
            return r.json()
        print(f"[Supabase] GET {table} error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[Supabase] GET {table} exception: {e}")
    return []


def load_user_profile(user_id: str) -> dict | None:
    """登入時載入跨 session 偏好。"""
    rows = _sb_get("user_profiles", {"id": f"eq.{user_id}", "select": "*", "limit": 1})
    return rows[0] if rows else None


def upsert_user_profile(user_id: str, email: str, prefs: dict):
    """寫回偏好快照（merge-duplicates upsert）。"""
    if not sb_url or not sb_key:
        return
    url = f"{sb_url}/rest/v1/user_profiles"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = {"id": user_id, "email": email, "prefs": prefs,
               "updated_at": _datetime.datetime.utcnow().isoformat()}
    try:
        requests.post(url, headers=headers, json=payload, timeout=3)
    except Exception as e:
        print(f"[Supabase] user_profiles upsert exception: {e}")


def fetch_recent_clicks(session_id: str, user_id: str | None) -> list[str]:
    """
    Task 3 關鍵：Discover 點擊由前端 JS fetch 直寫 Supabase（見 Discover 按鈕），
    Python 端在下一次 Generate 前把它讀回來，餵進 prompt。
    登入用戶額外撈跨 session 的歷史點擊（靠 sessions.user_id 關聯）。
    """
    names: list[str] = list(st.session_state.get("clicked_items", []))
    # 本 session 的前端點擊
    rows = _sb_get("events", {
        "session_id": f"eq.{session_id}",
        "event_type": "eq.discover_click",
        "select": "item_name",
        "order": "created_at.desc",
        "limit": 20,
    })
    names += [r["item_name"] for r in rows if r.get("item_name")]
    # 登入用戶：跨 session 歷史（先查該 user 的 sessions，再查 events）
    if user_id:
        srows = _sb_get("sessions", {"user_id": f"eq.{user_id}", "select": "id",
                                     "order": "created_at.desc", "limit": 10})
        sids = [s["id"] for s in srows if s.get("id") and s["id"] != session_id]
        if sids:
            in_list = ",".join(f'"{s}"' for s in sids)
            erows = _sb_get("events", {
                "session_id": f"in.({in_list})",
                "event_type": "eq.discover_click",
                "select": "item_name",
                "order": "created_at.desc",
                "limit": 30,
            })
            names += [r["item_name"] for r in erows if r.get("item_name")]
    # 去重保序
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:10]


def build_personal_context() -> str:
    """
    組合個人化 context 注入 prompt：
    1. 登入用戶的跨 session 偏好快照（user_profiles.prefs）
    2. 本 session（+ 歷史）的 Discover 點擊 → 興趣訊號
    3. 本 session 的 like / dislike
    """
    parts = []
    profile = st.session_state.get("user_profile")
    if profile and profile.get("prefs"):
        p = profile["prefs"]
        fav_styles = p.get("fav_styles", [])
        if fav_styles:
            parts.append(f"Returning user. Historically preferred styles: {', '.join(fav_styles[:5])}.")
        past_clicks = p.get("clicked_items", [])
        if past_clicks:
            parts.append(f"Items they clicked to shop in past visits: {', '.join(past_clicks[:6])}.")
    clicks = fetch_recent_clicks(st.session_state.session_id,
                                 st.session_state.get("user_id"))
    if clicks:
        parts.append(
            f"THIS-SESSION SHOPPING SIGNAL (strongest signal — they clicked through to buy these): "
            f"{', '.join(clicks)}. Recommend items with similar cut/color/vibe, but NOT identical duplicates."
        )
    for verdict, combo in st.session_state.get("liked_signal", [])[-3:]:
        if verdict == "like":
            parts.append(f"They LIKED this combo: {combo}. Lean into this direction.")
        else:
            parts.append(f"They DISLIKED this combo: {combo}. Avoid this direction.")
    if not parts:
        return ""
    return "PERSONALIZATION CONTEXT (use to tailor, never mention explicitly):\n- " + "\n- ".join(parts)


# ─── Task 3：可追蹤的 Discover 按鈕 ─────────────────────────────────────────
def render_discover_button(label: str, zara_url: str, item_name: str):
    """
    取代 st.link_button：
    - <a target="_blank"> 由使用者手勢直接開 ZARA（不會被 popup blocker 擋）
    - onclick 同時用 fetch 將 discover_click 直寫 Supabase events 表
    ⚠️ 這段 HTML 會帶 sb_anon_key 到瀏覽器 → 必須是 anon key，
       且 events 表要設 INSERT-only RLS policy（見 schema_v2.sql）。
    """
    if not (sb_url and sb_anon_key):
        st.link_button(label, zara_url)  # 無 Supabase 時退回原行為
        return
    payload = json.dumps({
        "session_id": st.session_state.session_id,
        "rec_id": st.session_state.get("rec_id"),
        "event_type": "discover_click",
        "item_name": item_name,
    })
    html = f"""
    <a href="{zara_url}" target="_blank" rel="noopener"
       onclick='fetch("{sb_url}/rest/v1/events", {{
            method: "POST",
            headers: {{
                "apikey": "{sb_anon_key}",
                "Authorization": "Bearer {sb_anon_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }},
            body: JSON.stringify({payload}),
            keepalive: true
       }}).catch(function(e){{}});'
       style="display:inline-block; font-family:Inter,Helvetica,sans-serif; font-size:0.8rem;
              letter-spacing:2px; text-transform:uppercase; color:#fff; background:#111;
              padding:0.55rem 1.6rem; text-decoration:none; border:1px solid #111;">
        {label}
    </a>
    <style>a:hover {{ background:#fff !important; color:#111 !important; }}</style>
    """
    components.html(html, height=52)


# ─── Task 2 helper：輕量單句生成（只用 flash-lite，保護主力 quota）──────────
def get_light_completion(prompt: str) -> str | None:
    """Swap reasoning 等微任務專用：固定走最便宜 tier，失敗就放棄不重試太久。"""
    lite_tier = MODEL_TIERS[-1]  # gemini-3.1-flash-lite, RPD 充裕
    for attempt in range(min(len(ALL_API_KEYS), 2)):
        key_idx, current_key = _pick_key_for_model(lite_tier["name"], lite_tier["rpd_soft_limit"])
        if key_idx is None:
            return None
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(lite_tier["name"])
            resp = model.generate_content([prompt])
            with _key_lock:
                _inc_daily_count(key_idx, lite_tier["name"])
                count = _daily_count.get((key_idx, lite_tier["name"]), 1)
            _sb_quota_upsert(key_idx, lite_tier["name"], count)
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e):
                _mark_key_rpm_limited(key_idx, 65)
                continue
            return None
    return None

# 2. 核心 AI 函數
# MODEL_TIERS 已定義於頂部 key rotation 區段

def get_ai_recommendation(gender, height, weight, season, occ, wea, sty, lang, uploaded_image=None, custom_prompt=None, personal_context=""):
    if not ALL_API_KEYS:
        return None, "Error: API Key missing"
    
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
            f"In your JSON response, the FIRST item in 'top_options' MUST be exactly: "
            f"{{\"name\": \"{p_cc_name}\", \"reason\": \"{p_cc_reason}\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"The other two top_options should be layering pieces that go OVER or UNDER the jersey. "
            f"Focus on matching pants, shoes, and inner layers."
        )
    elif "Padres Home Jersey" in sty:
        specific_style_rule = (
            f"SPECIAL STYLE RULE: The user IS wearing a '{p_home_name}' as the main top. "
            f"In your JSON response, the FIRST item in 'top_options' MUST be exactly: "
            f"{{\"name\": \"{p_home_name}\", \"reason\": \"{p_home_reason}\", \"price_range\": \"{p_price}\", \"recommended_size\": \"L\"}}. "
            f"The other two top_options should be layering pieces that go OVER or UNDER the jersey. "
            f"Focus on matching pants, shoes, and inner layers."
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
        f"{personal_context}\n"
        f"{specific_style_rule}\n"
        f"{custom_prompt_rule}\n"
        f"LANGUAGE RULE: Respond in {lang}. Use Traditional Chinese if '繁體中文'.\n"
        f"CURRENCY RULE: {currency_instruction}\n"
        f"Provide response in valid JSON format ONLY:\n"
        f"{{\n"
        f"  \"critique\": \"(Optional) Analysis of uploaded outfit if provided, otherwise empty.\",\n"
        f"  \"top_options\": [ {{...}}, {{...}}, {{...}} ],\n"
        f"  \"pants_options\": [ {{...}}, {{...}}, {{...}} ],\n"
        f"  \"shoes_options\": [ {{...}}, {{...}}, {{...}} ],\n"
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
        f"Each option object in top_options / pants_options / shoes_options MUST be:\n"
        f"{{\n"
        f"  \"name\": \"ZARA [Item Name]\",\n"
        f"  \"reason\": \"Reason why this fits their physique.\",\n"
        f"  \"price_range\": \"Estimated price range\",\n"
        f"  \"recommended_size\": \"Calculated size (e.g. S, M, L, XL, EU 42) based on user's height/weight\"\n"
        f"}}\n"
        f"CRITICAL: EXACTLY 3 options per category, ordered best-first. The three options within a "
        f"category must be meaningfully different (cut / color / fabric), yet EACH must coordinate "
        f"with the first option of the other two categories. Also 4-5 'other_brands', 2 'accessories'.\n"
    )
    
    last_error = None
    import re, json

    # ── Model Tier × Key 二維 Fallback 邏輯 ──
    # 優先序：gemini-3.5-flash → gemini-2.5-flash → gemini-3.1-flash-lite
    # 每個 Model Tier 內：主動偵測 RPD Soft Limit（不等 429），所有 Key 達標才降到下一 Tier
    # 429（RPM）仍即時換 Key 並標記冷卻
    for tier in MODEL_TIERS:
        model_name     = tier["name"]
        rpd_soft_limit = tier["rpd_soft_limit"]

        # 在此 Tier 內最多嘗試 key 數 × 2 次（防止單 key 偶發錯誤）
        max_attempts = len(ALL_API_KEYS) * 2
        for attempt in range(max_attempts):
            key_idx, current_key = _pick_key_for_model(model_name, rpd_soft_limit)
            if key_idx is None:
                # 此 Tier 所有 Key 的今日 RPD 均已達軟限 → 降到下一 Tier
                print(f"[Quota] All keys hit RPD soft limit for {model_name}, trying next tier")
                break

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

                clean_text = text.strip()
                start_idx = clean_text.find('{')
                end_idx   = clean_text.rfind('}')

                if start_idx != -1 and end_idx != -1:
                    data = json.loads(clean_text[start_idx:end_idx+1])
                    # 成功：遞增計數 + 寫回 Supabase
                    with _key_lock:
                        _inc_daily_count(key_idx, model_name)
                        count = _daily_count.get((key_idx, model_name), 1)
                    _sb_quota_upsert(key_idx, model_name, count)

                    # ── 解析候補池格式（top_options/pants_options/shoes_options）──
                    def _inject_cat(opts, cat):
                        for it in opts:
                            it["category"] = cat
                        return opts

                    top_opts   = _inject_cat(data.get("top_options",   []), "top")
                    pants_opts = _inject_cat(data.get("pants_options", []), "pants")
                    shoes_opts = _inject_cat(data.get("shoes_options", []), "shoes")

                    # 相容舊格式（zara_items）
                    if not top_opts and not pants_opts and not shoes_opts:
                        for it in data.get("zara_items", []):
                            cat = it.get("category","").lower()
                            slot = "top" if "top" in cat else ("pants" if "pant" in cat or "skirt" in cat else "shoes")
                            if slot == "top":    top_opts.append(it)
                            elif slot == "pants": pants_opts.append(it)
                            else:               shoes_opts.append(it)

                    # zara_items = 每個 category 的第一件，供主畫面顯示
                    zara_items_main = [o[0] for o in [top_opts, pants_opts, shoes_opts] if o]

                    return {
                        "critique":      data.get("critique", ""),
                        "zara_items":    zara_items_main,
                        "top_options":   top_opts,
                        "pants_options": pants_opts,
                        "shoes_options": shoes_opts,
                        "other_brands":  data.get("other_brands", []),
                        "accessories":   data.get("accessories", []),
                        "description":   data.get("description", ""),
                        "model_used":    model_name,
                        "key_used":      key_idx,
                    }, None

            except Exception as e:
                last_error = str(e)
                is_rate_limit = ("429" in last_error or
                                 "quota" in last_error.lower() or
                                 "rate" in last_error.lower())
                if is_rate_limit:
                    retry_secs = 65
                    m = re.search(r'retry_delay.*?seconds.*?(\d+)', last_error, re.DOTALL)
                    if m:
                        retry_secs = int(m.group(1)) + 2
                    _mark_key_rpm_limited(key_idx, retry_secs)
                    print(f"[KeyRotation] Key#{key_idx} {model_name} RPM 429, cooldown={retry_secs}s")
                    continue  # 同 Tier 換下一把 Key
                # 非限流錯誤（網路、JSON 解析失敗等）→ 直接中止，不浪費 quota
                return None, f"API Error: {last_error}"

    return None, f"所有 Model Tier 與 API Key 均已耗盡。Last error: {last_error}"

# ── 方案 E：換單品 API（輕量，只換一個 category）────────────────────────────
def get_single_item_swap(
    category: str,          # "top" / "pants" / "shoes"
    locked_items: list,     # 已鎖定的其他品項（不換）
    gender, height, weight, season, occ, wea, sty, lang
) -> dict | None:
    """
    只針對指定 category 重新生成一個 ZARA 單品，
    同時告知 AI 已有哪些品項被鎖定，確保搭配協調。
    消耗約 300-500 tokens，遠小於全套重生成。
    """
    if not ALL_API_KEYS:
        return None

    sty_str = ', '.join(sty) if sty else "general"
    cat_label = {"top": "上衣/Top", "pants": "下身/Pants or Skirt", "shoes": "鞋子/Shoes"}.get(category, category)
    locked_desc = ""
    if locked_items:
        locked_desc = "LOCKED ITEMS (already chosen, do NOT change these):\n"
        for item in locked_items:
            locked_desc += f"  - {item.get('name','')} ({item.get('category','')}): {item.get('reason','')}\n"

    currency_instruction = "Estimate price in NTD (TWD) for 繁體中文, or USD for English."

    prompt = (
        f"You are a pragmatic fashion stylist. "
        f"User: Gender={gender}, Height={height}cm, Weight={weight}kg. "
        f"Context: Season={season}, Occasion={occ}, Weather={wea}, Style={sty_str}.\n"
        f"{locked_desc}\n"
        f"TASK: Suggest ONE new ZARA item for category: {cat_label}.\n"
        f"It must coordinate with the locked items above. Different from any item already mentioned.\n"
        f"LANGUAGE: Respond in {lang}.\n"
        f"CURRENCY: {currency_instruction}\n"
        f"Return ONLY valid JSON (no markdown):\n"
        f"{{\n"
        f"  \"name\": \"ZARA [item name]\",\n"
        f"  \"reason\": \"Why this fits physique and coordinates with locked items.\",\n"
        f"  \"category\": \"{category}\",\n"
        f"  \"price_range\": \"estimated price\",\n"
        f"  \"recommended_size\": \"size based on height/weight\"\n"
        f"}}\n"
    )

    import re, json
    last_error = None
    for tier in MODEL_TIERS:
        model_name     = tier["name"]
        rpd_soft_limit = tier["rpd_soft_limit"]
        for attempt in range(len(ALL_API_KEYS) * 2):
            key_idx, current_key = _pick_key_for_model(model_name, rpd_soft_limit)
            if key_idx is None:
                break
            try:
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([prompt])
                text = response.text.strip()
                start = text.find('{')
                end   = text.rfind('}')
                if start != -1 and end != -1:
                    data = json.loads(text[start:end+1])
                    with _key_lock:
                        _inc_daily_count(key_idx, model_name)
                        count = _daily_count.get((key_idx, model_name), 1)
                    _sb_quota_upsert(key_idx, model_name, count)
                    return data
            except Exception as e:
                last_error = str(e)
                is_rate = "429" in last_error or "quota" in last_error.lower()
                if is_rate:
                    retry_secs = 65
                    m = re.search(r'retry_delay.*?seconds.*?(\d+)', last_error, re.DOTALL)
                    if m:
                        retry_secs = int(m.group(1)) + 2
                    _mark_key_rpm_limited(key_idx, retry_secs)
                    continue
                return None
    return None

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

# ─── Task 1：Optional Login（跨 session 記憶）─────────────────────────────
_login_title = ("👤 會員登入（選填）— 記住你的風格" if lang_select == "繁體中文"
                else "👤 Sign in (optional) — we'll remember your style")
with st.expander(_login_title, expanded=False):
    if st.session_state.get("user_id"):
        _msg = (f"已登入：{st.session_state['user_email']}　我們會記住你的風格偏好與選擇。"
                if lang_select == "繁體中文"
                else f"Signed in as {st.session_state['user_email']}. Your style memory is active.")
        st.markdown(f'<div style="font-family:Inter,sans-serif;font-size:0.8rem;color:#555;">✓ {_msg}</div>',
                    unsafe_allow_html=True)
        if st.button("登出 / Sign out", key="logout_btn"):
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            st.session_state["user_profile"] = None
            st.rerun()
    else:
        _email = st.text_input(
            "Email",
            placeholder="your@email.com",
            key="login_email_input",
            label_visibility="collapsed",
        )
        _hint = ("不需密碼。輸入 Email 即可在下次回訪時沿用你的風格記憶。"
                 if lang_select == "繁體中文"
                 else "No password needed — your email is just a key to your style memory.")
        st.caption(_hint)
        if _email and st.button("登入 / Sign in", key="login_btn"):
            _email_clean = _email.strip().lower()
            if "@" in _email_clean and "." in _email_clean:
                _uid = _hashlib.md5(_email_clean.encode()).hexdigest()
                st.session_state["user_id"] = _uid
                st.session_state["user_email"] = _email_clean
                st.session_state["user_profile"] = load_user_profile(_uid)
                if not st.session_state["user_profile"]:
                    upsert_user_profile(_uid, _email_clean, {})
                log_event("login")
                st.rerun()
            else:
                st.warning("請輸入有效的 Email / Please enter a valid email")

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

# ── 方案四：前端節流 ── 同一 session 兩次生成需間隔 THROTTLE_SECS 秒
THROTTLE_SECS = 15
_now = time.time()
_elapsed_since_last = _now - st.session_state["_last_gen_time"]
_throttled = _elapsed_since_last < THROTTLE_SECS and st.session_state["_last_gen_time"] > 0
_cooldown_remaining = max(0, int(THROTTLE_SECS - _elapsed_since_last))

if _throttled:
    st.button(
        f"{t['btn']} ({_cooldown_remaining}s)",
        disabled=True,
        help="請稍候再試 / Please wait before generating again"
    )
elif st.button(t["btn"]):
    # 記錄本次生成時間（方案四節流）
    st.session_state["_last_gen_time"] = time.time()

    # 清除舊的圖片與曝光 cache，避免重新生成時殘留
    for key in list(st.session_state.keys()):
        if key.startswith("img_") or key.startswith("imp_") or key.startswith("bimg_"):
            del st.session_state[key]
    # 清除 Builder 舊狀態，避免換風格後殘留舊 pool
    st.session_state["builder_pool"] = {}
    st.session_state["builder_idx"]  = {"top":0,"pants":0,"shoes":0}
    st.session_state["swap_reasons"] = {}   # Task 2：清除舊的 swap 解釋

    # ── Task 1+3：組合個人化 context（登入記憶 + Discover 點擊回饋）──
    _personal_ctx = build_personal_context()

    # ── 方案三：Cache 命中檢查（僅限無圖、無 custom prompt）──
    # 個人化 context 的 hash 一併納入 cache key：
    # 同樣條件但點擊訊號不同 → 視為不同請求，推薦才會「越用越準」
    _cache_key = None
    _cached_result = None
    _is_cacheable = not uploaded_file and not user_custom_prompt.strip()
    if _is_cacheable:
        _ctx_hash = _hashlib.md5(_personal_ctx.encode()).hexdigest()[:8] if _personal_ctx else "none"
        _cache_key = _make_cache_key(
            user_gender, user_height, user_weight,
            user_season, user_occ, user_wea, user_sty, lang_select
        ) + f"_{_ctx_hash}"
        _cached_result = _cache_get(_cache_key)

    if _cached_result:
        # Cache 命中：直接顯示，不消耗任何 API quota
        print(f"[Cache] HIT key={_cache_key}")
        st.session_state.last_result = _cached_result
        st.rerun()
    else:
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

        # Show animated luxury loading UI while calling the API
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                get_ai_recommendation,
                user_gender, user_height, user_weight, user_season,
                user_occ, user_wea, user_sty, lang_select, uploaded_file,
                user_custom_prompt, _personal_ctx
            )
            tip_idx = 0
            start_time = time.time()
            expected_seconds = 25  # Increased for multi-modal analysis and image search

            while not future.done():
                elapsed = time.time() - start_time
                remaining = max(1, int(expected_seconds - elapsed))
                timer_text = f"ETA: {remaining}s" if elapsed < expected_seconds else "Finalizing..."

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
                time.sleep(1.5)
            ui_placeholder.empty()
            result, err = future.result()

        if err:
            st.error(f"STYLING SERVICE UNAVAILABLE: {err}")
        else:
            result["latency_ms"] = int((time.time() - start_time) * 1000)
            st.session_state.last_result = result

            # ── 方案 E：初始化 Outfit Builder（以 zara_items 為起點）──
            builder_init = {}
            for item in result.get("zara_items", []):
                cat = item.get("category", "others").lower()
                # 以 top/pants/shoes 三個 slot 為主
                slot = "top" if "top" in cat else ("pants" if "pant" in cat or "skirt" in cat else ("shoes" if "shoe" in cat else cat))
                if slot not in builder_init:
                    builder_init[slot] = item
            # builder_pool 初始化（換件候補池）
            builder_pool_new = {
                "top":   result.get("top_options",   []),
                "pants": result.get("pants_options", []),
                "shoes": result.get("shoes_options", []),
            }
            st.session_state["builder_pool"] = builder_pool_new
            st.session_state["builder_idx"]  = {"top":0,"pants":0,"shoes":0}

            # ── Image Engine v3：同步生成 3 件主要單品圖（並行，~5-10s）──
            # 候補池其他單品 lazy：swap 時才生成，省 quota
            _main_names = [it.get("name", "") for it in result.get("zara_items", [])]
            _gen_style = user_sty[0] if user_sty else "all"
            with st.spinner("正在生成商品圖..." if lang_select == "繁體中文"
                            else "Generating product visuals..."):
                ensure_item_images(_main_names, user_gender, _gen_style)

            # ── 方案三：成功後存入 cache（僅限可快取請求）──
            if _is_cacheable and _cache_key:
                _cache_set(_cache_key, result)
                print(f"[Cache] SET key={_cache_key}")

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

            # ── Task 1：登入用戶 → 更新跨 session 偏好快照 ──
            if st.session_state.get("user_id"):
                _old_prefs = (st.session_state.get("user_profile") or {}).get("prefs", {}) or {}
                _fav = list(dict.fromkeys((user_sty or []) + _old_prefs.get("fav_styles", [])))[:8]
                _clk = fetch_recent_clicks(st.session_state.session_id, st.session_state["user_id"])[:8]
                _new_prefs = {
                    "fav_styles": _fav,
                    "clicked_items": _clk,
                    "gender": user_gender,
                    "height": int(user_height),
                    "weight": int(user_weight),
                }
                upsert_user_profile(st.session_state["user_id"],
                                    st.session_state["user_email"], _new_prefs)
                st.session_state["user_profile"] = {"id": st.session_state["user_id"],
                                                    "email": st.session_state["user_email"],
                                                    "prefs": _new_prefs}

# ─── Image Engine v3：Imagen 4 Fast 生成式商品圖 ───────────────────────────
# 設計：外鏈 URL 與 RAW_DATA 比對全面退役。
#   每個單品名稱「全域只生成一次」→ 上傳 Supabase Storage → 寫 item_image_cache，
#   之後所有用戶、所有 session 都直接吃自家 CDN。
#   Quota：imagen-4.0-fast 每把 key 25 RPD × 4 keys ≈ 100 張/天，
#   目錄飽和後新生成需求趨近於零。
# 例外：Padres 球衣是真實特定商品，維持 pinned 圖（不交給生成模型）。

IMAGE_MODEL_NAME = "imagen-4.0-fast-generate-001"
IMAGE_RPD_SOFT_LIMIT = 23   # RPD=25，留 2 緩衝

# 新版 google-genai SDK（Imagen 不走舊 google.generativeai）
try:
    from google import genai as genai_new
    from google.genai import types as genai_types
    _IMAGEN_AVAILABLE = True
except ImportError:
    _IMAGEN_AVAILABLE = False
    print("[Imagen] google-genai 未安裝，圖片生成停用（pip install google-genai）")

# Padres pinned（真實商品，不生成）
PINNED_IMAGES = {
    "padres home jersey":         "https://i.postimg.cc/4xBkzZVC/home-jersey.avif",
    "教士隊主場球衣":              "https://i.postimg.cc/4xBkzZVC/home-jersey.avif",
    "padres city connect jersey": "https://i.postimg.cc/cLXyQZwy/city-connect.jpg",
    "教士隊城市限定球衣":          "https://i.postimg.cc/cLXyQZwy/city-connect.jpg",
}


def _build_imagen_prompt(item_name: str, gender: str, style: str) -> str:
    g = "men's" if gender not in ("Female", "女性") else "women's"
    style_hint = f", {style} aesthetic" if style and style != "all" else ""
    return (
        f"Professional e-commerce product photography of a single {g} fashion item: "
        f"{item_name}{style_hint}. The garment only, no model, no mannequin, "
        f"laid flat or hanging, centered, soft studio lighting, "
        f"clean light beige background, minimalist ZARA catalog style, photorealistic."
    )


def _generate_item_image(item_name: str, gender: str, style: str = "all") -> str | None:
    """同步生成一張商品圖 → Storage → cache 表。回傳 stored_url 或 None。"""
    if not _IMAGEN_AVAILABLE or not (sb_url and sb_key) or not ALL_API_KEYS:
        return None
    key = item_name.lower().strip()
    if key in _IMG_CACHE:               # double-check（並行時可能已被別的 thread 生成）
        return _IMG_CACHE[key]
    prompt = _build_imagen_prompt(item_name, gender, style)
    for attempt in range(len(ALL_API_KEYS)):
        key_idx, current_key = _pick_key_for_model(IMAGE_MODEL_NAME, IMAGE_RPD_SOFT_LIMIT)
        if key_idx is None:
            print("[Imagen] 所有 Key 今日圖片 RPD 已達軟限")
            return None
        try:
            client = genai_new.Client(api_key=current_key)
            resp = client.models.generate_images(
                model=IMAGE_MODEL_NAME,
                prompt=prompt,
                config=genai_types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="3:4",
                    output_mime_type="image/jpeg",
                ),
            )
            if not resp.generated_images:
                return None
            img_bytes = resp.generated_images[0].image.image_bytes
            with _key_lock:
                _inc_daily_count(key_idx, IMAGE_MODEL_NAME)
                count = _daily_count.get((key_idx, IMAGE_MODEL_NAME), 1)
            _sb_quota_upsert(key_idx, IMAGE_MODEL_NAME, count)

            # 上傳 Storage（沿用 Task 5 管線）
            path = f"gen_{_hashlib.md5(key.encode()).hexdigest()}.jpg"
            up = requests.post(
                f"{sb_url}/storage/v1/object/{SB_IMAGE_BUCKET}/{path}",
                headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                         "Content-Type": "image/jpeg", "x-upsert": "true"},
                data=img_bytes, timeout=15)
            if not up.ok:
                print(f"[Imagen] Storage 上傳失敗 {up.status_code}: {up.text[:120]}")
                return None
            stored_url = f"{sb_url}/storage/v1/object/public/{SB_IMAGE_BUCKET}/{path}"
            _sb_post("item_image_cache",
                     {"item_name": item_name, "source_url": f"imagen:{IMAGE_MODEL_NAME}",
                      "stored_url": stored_url})
            _IMG_CACHE[key] = stored_url
            print(f"[Imagen] generated: {item_name}")
            return stored_url
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                _mark_key_rpm_limited(key_idx, 65)
                print(f"[Imagen] Key#{key_idx} 429, 換 Key")
                continue
            print(f"[Imagen] 生成失敗: {item_name} — {err[:200]}")
            return None
    return None


def ensure_item_images(item_names: list[str], gender: str, style: str = "all"):
    """Generate 後同步補齊主要單品圖（並行，最多 3 張，每張各自挑 Key）。"""
    _load_image_cache_once()
    todo = [n for n in item_names
            if n and n.lower().strip() not in _IMG_CACHE
            and n.lower().strip() not in PINNED_IMAGES]
    if not todo:
        return
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(_generate_item_image, n, gender, style) for n in todo[:3]]
        for f in futures:
            try:
                f.result(timeout=30)
            except Exception as e:
                print(f"[Imagen] ensure exception: {e}")

# ─── Task 5：圖片穩定性層（Supabase Storage 暖存 + onerror fallback）─────────
# 問題：postimg / zara.net 外鏈常失效或被防盜鏈擋 → 破圖。
# 策略：第一次用到某張圖時，背景執行緒把它抓下來上傳到自家 Supabase Storage，
#       並寫入 item_image_cache 表；之後一律走自家 CDN URL。
#       前端 <img> 再加 onerror 換 SVG placeholder 作最後保險。

_FALLBACK_SVG_URI = "data:image/svg+xml;utf8," + urllib.parse.quote(
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="500">'
    '<rect width="100%" height="100%" fill="#f4f1ee"/>'
    '<text x="50%" y="46%" font-family="Helvetica" font-size="44" '
    'text-anchor="middle" fill="#c9bfb6">VOGUE</text>'
    '<text x="50%" y="56%" font-family="Helvetica" font-size="13" letter-spacing="4" '
    'text-anchor="middle" fill="#c9bfb6">IMAGE UNAVAILABLE</text></svg>'
)

_IMG_CACHE: dict[str, str] = {}        # {item_name_lower: storage_url}（模組層，跨 rerun 存活）
_IMG_CACHE_LOADED = False
_IMG_WARMING: set = set()              # 防止同名重複暖存


def _load_image_cache_once():
    """啟動後第一次需要圖片時，把 item_image_cache 表整批載入記憶體。"""
    global _IMG_CACHE_LOADED
    if _IMG_CACHE_LOADED or not (sb_url and sb_key):
        _IMG_CACHE_LOADED = True
        return
    rows = _sb_get("item_image_cache", {"select": "item_name,stored_url", "limit": "2000"})
    for r in rows:
        if r.get("item_name") and r.get("stored_url"):
            _IMG_CACHE[r["item_name"].lower()] = r["stored_url"]
    _IMG_CACHE_LOADED = True
    print(f"[ImageCache] loaded {len(_IMG_CACHE)} cached images")


def _warm_image_to_storage(item_name: str, source_url: str):
    """背景執行：抓圖 → 上傳 Storage（x-upsert）→ 寫 cache 表 → 更新記憶體 dict。"""
    key = item_name.lower()
    try:
        resp = requests.get(source_url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36",
            "Referer": "https://www.zara.com/",
        })
        if not resp.ok or len(resp.content) < 1000:
            return
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        ext = {"image/png": "png", "image/webp": "webp", "image/avif": "avif"}.get(content_type, "jpg")
        path = f"{_hashlib.md5(key.encode()).hexdigest()}.{ext}"
        up = requests.post(
            f"{sb_url}/storage/v1/object/{SB_IMAGE_BUCKET}/{path}",
            headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                     "Content-Type": content_type, "x-upsert": "true"},
            data=resp.content, timeout=10)
        if not up.ok:
            print(f"[ImageCache] upload failed {up.status_code}: {up.text[:120]}")
            return
        stored_url = f"{sb_url}/storage/v1/object/public/{SB_IMAGE_BUCKET}/{path}"
        _sb_post("item_image_cache",
                 {"item_name": item_name, "source_url": source_url, "stored_url": stored_url})
        _IMG_CACHE[key] = stored_url
        print(f"[ImageCache] warmed: {item_name}")
    except Exception as e:
        print(f"[ImageCache] warm exception for {item_name}: {e}")
    finally:
        _IMG_WARMING.discard(key)


def resolve_item_image(item_name: str, gender: str, category: str = "others",
                       style: str = "all", season: str = "all", occasion: str = "all",
                       generate: bool = False) -> str:
    """
    UI 唯一圖片入口（v3）：
    1. Padres pinned（真實商品）→ 直接回，並背景暖存進自家 Storage
    2. item_image_cache 命中 → 自家 Storage URL（最穩、零延遲）
    3. generate=True → 同步呼叫 Imagen 生成（5-10 秒，僅在 Generate 流程/Swap 時用）
    4. 都沒有 → SVG placeholder（generate=False 的 lazy 場景）
    """
    _load_image_cache_once()
    key = item_name.lower().strip()

    # 1. Pinned（含子字串比對：AI 輸出常帶前綴）
    for pk, purl in PINNED_IMAGES.items():
        if pk in key:
            cached = _IMG_CACHE.get(pk)
            if cached:
                return cached
            if sb_url and sb_key and pk not in _IMG_WARMING:
                _IMG_WARMING.add(pk)
                _threading.Thread(target=_warm_image_to_storage,
                                  args=(pk, purl), daemon=True).start()
            return purl

    # 2. Cache
    cached = _IMG_CACHE.get(key)
    if cached:
        return cached

    # 3. 同步生成
    if generate:
        url = _generate_item_image(item_name, gender, style)
        if url:
            return url

    # 4. Placeholder
    return _FALLBACK_SVG_URI


# ─── Results Display ──────────────────────────────────────────────────────────
# 圖片預載：在 get_item_image 定義後執行，Builder 換件時 instant 切換
if st.session_state.get("builder_pool"):
    _primary_style = user_sty[0] if user_sty else "all"
    _is_padres_pre = any(s in (user_sty or []) for s in ["Padres City Connect Jersey","Padres Home Jersey"])
    for _slot, _opts in st.session_state["builder_pool"].items():
        for _i, _item in enumerate(_opts):
            _img_key = f"bimg_{_slot}_{_i}"
            if _img_key not in st.session_state:
                # Padres top 第一件：直接給 jersey URL，不走比對
                if _slot == "top" and _i == 0 and _is_padres_pre:
                    _name = _item.get("name","").lower()
                    if "city connect" in _name or "城市限定" in _name:
                        st.session_state[_img_key] = "https://i.postimg.cc/cLXyQZwy/city-connect.jpg"
                    else:
                        st.session_state[_img_key] = "https://i.postimg.cc/4xBkzZVC/home-jersey.avif"
                else:
                    st.session_state[_img_key] = resolve_item_image(
                        _item.get("name",""), user_gender, _slot,
                        style=_primary_style, season=user_season, occasion=user_occ,
                        generate=(_i == 0)   # 第一件=主圖（已生成）；候補 lazy，swap 時才生成
                    )

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
            # Padres 第一件：直接給 jersey URL，不走比對
            _is_padres_item = (idx == 0 and any(s in (user_sty or [])
                               for s in ["Padres City Connect Jersey","Padres Home Jersey"]))
            if _is_padres_item:
                _rn = raw_name.lower()
                if "city connect" in _rn or "城市限定" in _rn:
                    st.session_state[img_cache_key] = "https://i.postimg.cc/cLXyQZwy/city-connect.jpg"
                else:
                    st.session_state[img_cache_key] = "https://i.postimg.cc/4xBkzZVC/home-jersey.avif"
            else:
                primary_style = user_sty[0] if user_sty else "all"
                st.session_state[img_cache_key] = resolve_item_image(
                    raw_name, user_gender, category,
                    style=primary_style, season=user_season, occasion=user_occ,
                    generate=True   # 正常情況 ensure 已生成 → cache hit；此為保險網
                )
        img_url = st.session_state[img_cache_key]

        if img_url:
            col_img_area, col_txt = st.columns([1, 1.5])
            with col_img_area:
                st.markdown(
                    f'<div class="img-container"><img src="{img_url}" '
                    f'onerror="this.onerror=null;this.src=\'{_FALLBACK_SVG_URI}\'"></div>',
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

                # Task 3：tracked anchor — 開新分頁 + 前端 fetch 記錄 discover_click
                render_discover_button(t["buy"], zara_url, name_brand)
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

    # ─────────────────────────────────────────────────────────────────
    # 方案 E：OUTFIT BUILDER
    # ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        """<div style="font-family:Bodoni Moda,serif; font-size:1.4rem; """
        """letter-spacing:3px; margin-bottom:0.3rem;">BUILD YOUR LOOK</div>""",
        unsafe_allow_html=True
    )
    st.markdown(
        """<div style="font-family:Inter,sans-serif; font-size:0.75rem; """
        """letter-spacing:2px; color:#999; text-transform:uppercase; margin-bottom:1.5rem;">"""
        """Swap individual pieces · keep what you love</div>""",
        unsafe_allow_html=True
    )

    builder_pool = st.session_state.get("builder_pool", {})
    # builder_idx 直接操作 session_state，確保 swap 後狀態正確保存
    if "builder_idx" not in st.session_state:
        st.session_state["builder_idx"] = {"top":0,"pants":0,"shoes":0}
    builder_idx = st.session_state["builder_idx"]

    SLOT_LABELS = {"top":("上衣","Top"), "pants":("下身","Bottoms"), "shoes":("鞋子","Shoes")}
    SLOT_EMOJI  = {"top":"👕", "pants":"👖", "shoes":"👟"}

    # Padres 風格判斷
    _is_padres_style = any(s in (user_sty or []) for s in ["Padres City Connect Jersey", "Padres Home Jersey"])

    # ── 顯示三個 slot ──
    slot_cols = st.columns(3)
    for i, slot in enumerate(["top","pants","shoes"]):
        opts  = builder_pool.get(slot, [])
        idx   = builder_idx.get(slot, 0)
        item  = opts[idx] if opts else None
        total = len(opts)
        zh_label, en_label = SLOT_LABELS[slot]
        slot_label = zh_label if lang_select == "繁體中文" else en_label
        emoji = SLOT_EMOJI[slot]

        with slot_cols[i]:
            indicator = f" {idx+1}/{total}" if total > 1 else ""
            st.markdown(
                f'<div style="font-family:Inter,sans-serif; font-size:0.65rem; '
                f'letter-spacing:3px; color:#aaa; text-transform:uppercase; '
                f'margin-bottom:0.5rem;">{emoji} {slot_label}{indicator}</div>',
                unsafe_allow_html=True
            )
            if item:
                # 圖片：直接用 bimg_ cache（預載時已處理）
                img_url = st.session_state.get(f"bimg_{slot}_{idx}", "")
                # Padres top slot 第一件：強制用 jersey URL
                if slot == "top" and idx == 0 and _is_padres_style:
                    jersey_name = item.get("name","").lower()
                    if "city connect" in jersey_name or "城市限定" in jersey_name:
                        img_url = "https://i.postimg.cc/cLXyQZwy/city-connect.jpg"
                    else:
                        img_url = "https://i.postimg.cc/4xBkzZVC/home-jersey.avif"
                if img_url:
                    st.markdown(
                        f'<div class="img-container" style="margin-bottom:0.6rem;">'
                        f'<img src="{img_url}" onerror="this.onerror=null;this.src=\'{_FALLBACK_SVG_URI}\'"></div>',
                        unsafe_allow_html=True
                    )
                st.markdown(
                    f'<div style="font-family:Inter,sans-serif; font-weight:600; '
                    f'font-size:0.82rem; margin-bottom:0.2rem; line-height:1.3;">'
                    f'{item.get("name","")}</div>',
                    unsafe_allow_html=True
                )
                price = item.get("price_range","")
                size  = item.get("recommended_size","")
                if price or size:
                    size_txt = f" · {size}" if size else ""
                    st.markdown(
                        f'<div style="font-family:Inter,sans-serif; font-size:0.7rem; '
                        f'color:#aaa; margin-bottom:0.5rem;">{price}{size_txt}</div>',
                        unsafe_allow_html=True
                    )
                reason = item.get("reason","")
                if reason:
                    st.markdown(
                        f'<div style="font-family:Inter,sans-serif; font-size:0.72rem; '
                        f'color:#777; line-height:1.5; margin-bottom:0.6rem;">{reason}</div>',
                        unsafe_allow_html=True
                    )
                # ── Task 2：swap 後的 AI 一句話解釋 ──
                _swap_reason = st.session_state["swap_reasons"].get(f"{slot}_{idx}")
                if _swap_reason and idx > 0:
                    st.markdown(
                        f'<div style="font-family:Inter,sans-serif; font-size:0.7rem; '
                        f'color:#8a6d5c; line-height:1.5; margin-bottom:0.6rem; '
                        f'padding:0.5rem 0.7rem; background:#faf6f3; '
                        f'border-left:2px solid #c9a99a;">✦ AI：{_swap_reason}</div>',
                        unsafe_allow_html=True
                    )
                # 換件按鈕：Padres top 第一件鎖定
                _lock_top = (slot == "top" and idx == 0 and _is_padres_style)
                if _lock_top:
                    st.markdown(
                        '<div style="font-family:Inter,sans-serif;font-size:0.62rem;'
                        'letter-spacing:2px;color:#aaa;text-transform:uppercase;'
                        'margin-top:0.3rem;">⚾ FIXED · PADRES</div>',
                        unsafe_allow_html=True
                    )
                elif total > 1:
                    swap_label = f"↺ 換一件{zh_label}" if lang_select == "繁體中文" else f"↺ Swap {en_label}"
                    if st.button(swap_label, key=f"swap_{slot}"):
                        new_idx = (idx + 1) % total
                        st.session_state["builder_idx"][slot] = new_idx
                        log_event("builder_swap", item_name=opts[new_idx].get("name", ""))

                        # ── Image Engine v3：候補單品圖 lazy 生成（首次 swap 到才花 quota）──
                        _bimg_key = f"bimg_{slot}_{new_idx}"
                        _cur_img = st.session_state.get(_bimg_key, "")
                        if (not _cur_img) or _cur_img.startswith("data:image/svg"):
                            with st.spinner("正在生成商品圖..." if lang_select == "繁體中文"
                                            else "Generating product visual..."):
                                _gen_url = resolve_item_image(
                                    opts[new_idx].get("name", ""), user_gender, slot,
                                    style=(user_sty[0] if user_sty else "all"),
                                    generate=True
                                )
                            st.session_state[_bimg_key] = _gen_url

                        # ── Task 2：為換上的單品生成一句 AI 解釋（有 cache 就跳過）──
                        _reason_key = f"{slot}_{new_idx}"
                        if _reason_key not in st.session_state["swap_reasons"]:
                            _new_item = opts[new_idx]
                            _locked = []
                            for _s in ("top", "pants", "shoes"):
                                if _s == slot:
                                    continue
                                _o = builder_pool.get(_s, [])
                                _i = builder_idx.get(_s, 0)
                                if _o and _i < len(_o):
                                    _locked.append(_o[_i].get("name", ""))
                            if lang_select == "繁體中文":
                                _lang_rule = "用繁體中文回答，一句話、40 字以內，不要引號。"
                            else:
                                _lang_rule = "Answer in English, ONE sentence under 25 words, no quotes."
                            _swap_prompt = (
                                f"You are a fashion stylist. User: {user_gender}, {user_height}cm, {user_weight}kg. "
                                f"Outfit kept: {', '.join(_locked) if _locked else 'none'}. "
                                f"They just swapped their {slot} from '{item.get('name','')}' "
                                f"to '{_new_item.get('name','')}'. "
                                f"Explain why this new piece works better for their body and the rest of the outfit. "
                                f"{_lang_rule}"
                            )
                            with st.spinner("AI 正在分析這次換搭..." if lang_select == "繁體中文"
                                            else "Analyzing this swap..."):
                                _reason = get_light_completion(_swap_prompt)
                            if _reason:
                                st.session_state["swap_reasons"][_reason_key] = _reason
                        st.rerun()
            else:
                st.markdown(
                    f'<div style="font-family:Inter,sans-serif; font-size:0.78rem; '
                    f'color:#ccc; padding:2rem 0;">暫無候補 / No options</div>',
                    unsafe_allow_html=True
                )

    # ── 目前搭配摘要 ──
    if builder_pool:
        combo_parts = []
        for s in ["top","pants","shoes"]:
            opts = builder_pool.get(s,[])
            idx  = builder_idx.get(s,0)
            if opts and idx < len(opts):
                combo_parts.append(opts[idx].get("name","?"))
        if combo_parts:
            combo_names = " + ".join(combo_parts)
            st.markdown(
                f'<div style="font-family:Inter,sans-serif; font-size:0.78rem; '
                f'color:#555; margin-top:1rem; padding:0.8rem 1rem; '
                f'background:#f9f9f9; border-left:2px solid #111;">'
                f'✦ {combo_names}</div>',
                unsafe_allow_html=True
            )

    # ─────────────────────────────────────────────────────────────────
    # 方案 D：AI 穿搭圖生成（Pro 功能 · 付費意願追蹤）
    # ─────────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    pro_label = "✨ 生成完整穿搭圖（Pro 功能）" if lang_select == "繁體中文" else "✨ Generate Outfit Visual (Pro Feature)"
    pro_help  = "升級 Pro 版即可生成 AI 穿搭圖像" if lang_select == "繁體中文" else "Upgrade to Pro to generate AI outfit visuals"

    col_pro, col_spacer = st.columns([1.5, 2])
    with col_pro:
        if st.button(pro_label, help=pro_help, type="secondary"):
            st.session_state["pro_intent_clicked"] = True
            log_event("pro_intent_click")  # 記錄到 Supabase events 表
            st.rerun()

    if st.session_state.get("pro_intent_clicked"):
        # ── Task 4：funnel step 2 — paywall 曝光（只記一次）──
        if not st.session_state["pro_paywall_viewed"]:
            st.session_state["pro_paywall_viewed"] = True
            log_event("pro_paywall_view")

        st.markdown(
            '<div style="font-family:Inter,sans-serif; font-size:0.82rem; '
            'color:#555; padding:1rem; border:1px solid #eee; margin-top:0.5rem; '
            'background:#fafafa;">'
            '🔒 <b>Pro 版功能</b>：一鍵生成完整穿搭 AI 圖像，支援 flat lay 風格與模特展示圖。</div>'
            if lang_select == "繁體中文" else
            '<div style="font-family:Inter,sans-serif; font-size:0.82rem; '
            'color:#555; padding:1rem; border:1px solid #eee; margin-top:0.5rem; '
            'background:#fafafa;">'
            '🔒 <b>Pro Feature</b>: Generate a full AI outfit visual — flat lay or model shot — in one click.</div>',
            unsafe_allow_html=True
        )

        # ── 路徑 A：Stripe Payment Link（funnel step 3a — 真實付費意願）──
        if STRIPE_PAYMENT_LINK:
            _pay_label = "💳 NT$99 / 月 解鎖 Pro" if lang_select == "繁體中文" else "💳 Unlock Pro — $3.99/mo"
            col_pay, _ = st.columns([1.5, 2])
            with col_pay:
                if st.button(_pay_label, key="stripe_intent_btn", type="primary"):
                    log_event("stripe_checkout_click")
                    st.session_state["_show_stripe_link"] = True
            if st.session_state.get("_show_stripe_link"):
                st.link_button("→ 前往安全結帳 / Proceed to secure checkout", STRIPE_PAYMENT_LINK)

        # ── 路徑 B：Waitlist（funnel step 3b — 留 email + 價格意願）──
        _wl_title = "或先加入候補名單：" if lang_select == "繁體中文" else "Or join the waitlist first:"
        st.caption(_wl_title)
        waitlist_email = st.text_input(
            "Email（選填）" if lang_select == "繁體中文" else "Email (optional)",
            placeholder="your@email.com",
            key="waitlist_email_input"
        )
        _wtp_label = "你願意為這個功能付多少？" if lang_select == "繁體中文" else "What would you pay for this?"
        _wtp_opts = (["NT$0（免費才用）", "NT$49/月", "NT$99/月", "NT$199/月"]
                     if lang_select == "繁體中文"
                     else ["$0 (free only)", "$1.99/mo", "$3.99/mo", "$6.99/mo"])
        wtp_choice = st.radio(_wtp_label, _wtp_opts, horizontal=True, key="wtp_radio")

        if waitlist_email and st.button("加入候補名單" if lang_select == "繁體中文" else "Join Waitlist"):
            _email_c = waitlist_email.strip().lower()
            if "@" in _email_c and "." in _email_c:
                # 寫進專用 waitlist 表（去重 upsert）＋ events 雙保險
                if sb_url and sb_key:
                    try:
                        requests.post(
                            f"{sb_url}/rest/v1/waitlist",
                            headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                                     "Content-Type": "application/json",
                                     "Prefer": "resolution=merge-duplicates,return=minimal"},
                            json={"email": _email_c,
                                  "session_id": st.session_state.session_id,
                                  "user_id": st.session_state.get("user_id"),
                                  "willingness_to_pay": wtp_choice},
                            timeout=3)
                    except Exception as e:
                        print(f"[Supabase] waitlist exception: {e}")
                log_event("waitlist_signup", item_name=_email_c)
                st.success("✓ 已收到！我們會在 Pro 版上線時通知您。" if lang_select == "繁體中文"
                           else "✓ Got it! We'll notify you when Pro launches.")
            else:
                st.warning("請輸入有效的 Email / Please enter a valid email")

    # Feedback
    st.markdown("---")
    st.write("How do you like this outfit?" if lang_select == "English" else "您喜歡這套穿搭嗎？")
    f1, f2, f3 = st.columns([2, 2, 4])
    with f1:
        st.button("👍 Like", on_click=track_like)
    with f2:
        st.button("👎 Dislike", on_click=track_dislike)

st.markdown("<br><br><br>", unsafe_allow_html=True)
