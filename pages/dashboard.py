import streamlit as st
import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(override=True)

# ── 連線設定（與 app.py 相同）──────────────────────────────────
def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

sb_url = get_secret("SUPABASE_URL")
sb_key = get_secret("SUPABASE_KEY")

# ── 頁面設定 ────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Stylist — Analytics",
    page_icon="📊",
    layout="wide",
)

# ── 樣式（延續 ZARA 黑白美學）──────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,wght@0,400..900;1,400..900&family=Inter:wght@100..900&display=swap');

.stApp { background-color: #FFFFFF; }

h1, h2, h3 {
    font-family: 'Bodoni Moda', serif !important;
    color: #111111;
}
.stMetric label {
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #888888 !important;
}
.stMetric .metric-value {
    font-family: 'Bodoni Moda', serif !important;
    font-size: 2rem !important;
}
.dash-title {
    font-family: 'Bodoni Moda', serif;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -1px;
    color: #111;
    margin-bottom: 0;
}
.dash-sub {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #999;
    margin-bottom: 2rem;
}
.section-label {
    font-family: 'Inter', sans-serif;
    font-size: 10px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #AAAAAA;
    border-bottom: 0.5px solid #EEEEEE;
    padding-bottom: 6px;
    margin-bottom: 1rem;
}
hr { border: none; border-top: 0.5px solid #EEEEEE; margin: 2rem 0; }
</style>
""", unsafe_allow_html=True)

# ── Supabase 查詢工具 ────────────────────────────────────────────
def sb_query(sql: str) -> list[dict]:
    """用 Supabase SQL endpoint 執行查詢，回傳 list of dicts。"""
    if not sb_url or not sb_key:
        return []
    url = f"{sb_url}/rest/v1/rpc/execute_sql"
    # 改用 PostgREST 直接讀 VIEW
    return []

def sb_get(table_or_view: str, params: dict = None) -> list[dict]:
    """用 REST API 讀取 table 或 view。"""
    if not sb_url or not sb_key:
        return []
    url = f"{sb_url}/rest/v1/{table_or_view}"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=8)
        if r.ok:
            return r.json()
        else:
            st.error(f"Supabase error: {r.status_code} — {r.text[:200]}")
            return []
    except Exception as e:
        st.error(f"連線失敗：{e}")
        return []

def sb_get_events(date_from_str, date_to_str):
    url = f"{sb_url}/rest/v1/events"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    params = [
        ("select", "event_type,item_name,created_at"),
        ("created_at", f"gte.{date_from_str}"),
        ("created_at", f"lt.{date_to_str}"),
    ]
    r = requests.get(url, headers=headers, params=params, timeout=8)
    return r.json() if r.ok else []

def sb_rpc(func_name: str, payload: dict = None) -> list[dict]:
    """呼叫 Supabase RPC function。"""
    if not sb_url or not sb_key:
        return []
    url = f"{sb_url}/rest/v1/rpc/{func_name}"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json=payload or {}, timeout=8)
        if r.ok:
            return r.json()
        else:
            return []
    except:
        return []

# ── Header ───────────────────────────────────────────────────────
st.markdown('<div class="dash-title">Analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="dash-sub">AI Stylist — Backend Dashboard</div>', unsafe_allow_html=True)

# ── 無 Supabase 連線時的提示 ─────────────────────────────────────
if not sb_url or not sb_key:
    st.warning("⚠️  找不到 Supabase 連線設定。請確認 `.env` 或 `st.secrets` 裡有 `SUPABASE_URL` 和 `SUPABASE_KEY`。")
    st.stop()

# ── 日期篩選器 ───────────────────────────────────────────────────
col_date1, col_date2, _ = st.columns([1, 1, 4])
with col_date1:
    date_from = st.date_input("From", value=datetime.today() - timedelta(days=30))
with col_date2:
    date_to = st.date_input("To", value=datetime.today())

date_from_str = date_from.isoformat()
date_to_str = (date_to + timedelta(days=1)).isoformat()  # 包含當天

st.markdown("<hr>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# KPI 區塊
# ════════════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Overview</div>', unsafe_allow_html=True)

events_raw = sb_get("events", {
    "created_at": f"gte.{date_from_str}",
    "select": "event_type",
})
# PostgREST 支援 range filter
events_all = sb_get_events(date_from_str, date_to_str)

# 計算各指標
generates  = sum(1 for e in events_all if e.get("event_type") == "generate")
likes      = sum(1 for e in events_all if e.get("event_type") == "like")
dislikes   = sum(1 for e in events_all if e.get("event_type") == "dislike")
discovers  = sum(1 for e in events_all if e.get("event_type") == "discover_click")
total_fb   = likes + dislikes
like_rate  = round(likes / total_fb * 100, 1) if total_fb > 0 else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("推薦次數", f"{generates:,}")
k2.metric("Like 👍", f"{likes:,}")
k3.metric("Dislike 👎", f"{dislikes:,}")
k4.metric("Like 率", f"{like_rate}%")
k5.metric("Discover 點擊", f"{discovers:,}")

st.markdown("<hr>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# 每日趨勢
# ════════════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Daily Trend</div>', unsafe_allow_html=True)

try:
    import pandas as pd
    import altair as alt

    # 從 analytics_overview VIEW 拉資料
    overview = sb_get("analytics_overview")

    if overview:
        df_ov = pd.DataFrame(overview)
        df_ov["day"] = pd.to_datetime(df_ov["day"]).dt.date
        df_ov = df_ov[
            (df_ov["day"] >= date_from) & (df_ov["day"] <= date_to)
        ].sort_values("day")

        df_melted = df_ov.melt(
            id_vars="day",
            value_vars=["generates", "likes", "dislikes", "discover_clicks"],
            var_name="event",
            value_name="count",
        )
        event_labels = {
            "generates": "推薦",
            "likes": "Like",
            "dislikes": "Dislike",
            "discover_clicks": "Discover",
        }
        df_melted["event"] = df_melted["event"].map(event_labels)

        chart = alt.Chart(df_melted).mark_line(point=True).encode(
            x=alt.X("day:T", title="日期", axis=alt.Axis(format="%m/%d")),
            y=alt.Y("count:Q", title="次數"),
            color=alt.Color(
                "event:N",
                scale=alt.Scale(
                    domain=["推薦", "Like", "Dislike", "Discover"],
                    range=["#111111", "#2ECC71", "#E74C3C", "#3498DB"],
                ),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=["day:T", "event:N", "count:Q"],
        ).properties(height=280).configure_axis(
            labelFont="Inter", titleFont="Inter",
            labelColor="#888", titleColor="#888",
            gridColor="#F5F5F5",
        ).configure_view(strokeOpacity=0)

        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("還沒有資料，開始使用 app 之後這裡會出現趨勢圖。")

except ImportError:
    st.info("安裝 `altair` 和 `pandas` 以顯示圖表：`pip install altair pandas`")

st.markdown("<hr>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# 風格 Like 率 + 熱門單品
# ════════════════════════════════════════════════════════════════
col_left, col_right = st.columns(2)

with col_left:
    st.markdown('<div class="section-label">風格 Like 率</div>', unsafe_allow_html=True)
    styles_data = sb_get("top_styles")

    if styles_data:
        try:
            df_styles = pd.DataFrame(styles_data).head(10)
            df_styles = df_styles.sort_values("like_rate_pct", ascending=True)

            bar = alt.Chart(df_styles).mark_bar(color="#111111").encode(
                x=alt.X("like_rate_pct:Q", title="Like 率 %", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("style:N", sort="-x", title=None),
                tooltip=["style:N", "like_rate_pct:Q", "likes:Q", "dislikes:Q"],
            ).properties(height=300).configure_axis(
                labelFont="Inter", titleFont="Inter",
                labelColor="#888", titleColor="#888",
                gridColor="#F5F5F5",
            ).configure_view(strokeOpacity=0)

            st.altair_chart(bar, use_container_width=True)
        except:
            for row in styles_data[:8]:
                st.write(f"**{row.get('style')}** — {row.get('like_rate_pct')}% like rate")
    else:
        st.info("暫無資料")

with col_right:
    st.markdown('<div class="section-label">Discover 熱門單品 Top 10</div>', unsafe_allow_html=True)

    discover_events = [
        e for e in events_all
        if e.get("event_type") == "discover_click" and e.get("item_name")
    ]

    if discover_events:
        from collections import Counter
        counts = Counter(e["item_name"] for e in discover_events)
        top_items = counts.most_common(10)

        try:
            df_items = pd.DataFrame(top_items, columns=["item", "clicks"])
            df_items = df_items.sort_values("clicks", ascending=True)

            bar2 = alt.Chart(df_items).mark_bar(color="#111111").encode(
                x=alt.X("clicks:Q", title="點擊次數"),
                y=alt.Y("item:N", sort="-x", title=None),
                tooltip=["item:N", "clicks:Q"],
            ).properties(height=300).configure_axis(
                labelFont="Inter", titleFont="Inter",
                labelColor="#888", titleColor="#888",
                gridColor="#F5F5F5",
            ).configure_view(strokeOpacity=0)

            st.altair_chart(bar2, use_container_width=True)
        except:
            for item, cnt in top_items:
                st.write(f"**{item}** — {cnt} 次")
    else:
        st.info("暫無 Discover 點擊資料")

st.markdown("<hr>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# AI Model 表現
# ════════════════════════════════════════════════════════════════
st.markdown('<div class="section-label">AI Model 表現</div>', unsafe_allow_html=True)

model_data = sb_get("model_performance")

if model_data:
    try:
        df_model = pd.DataFrame(model_data)
        st.dataframe(
            df_model.rename(columns={
                "model_used": "Model",
                "uses": "使用次數",
                "avg_latency_ms": "平均回應 (ms)",
                "likes": "Like",
                "like_rate_pct": "Like 率 %",
            }),
            use_container_width=True,
            hide_index=True,
        )
    except:
        st.json(model_data)
else:
    st.info("暫無 Model 資料")

st.markdown("<hr>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# 用戶 Profile 分佈
# ════════════════════════════════════════════════════════════════
st.markdown('<div class="section-label">用戶 Profile 分佈</div>', unsafe_allow_html=True)

sessions_data = sb_get("sessions", {
    "select": "gender,season,occasion",
    "created_at": f"gte.{date_from_str}",
})

if sessions_data:
    try:
        df_sess = pd.DataFrame(sessions_data)
        c1, c2, c3 = st.columns(3)

        with c1:
            st.caption("性別分佈")
            gender_counts = df_sess["gender"].value_counts().reset_index()
            gender_counts.columns = ["gender", "count"]
            pie1 = alt.Chart(gender_counts).mark_arc(innerRadius=40).encode(
                theta="count:Q",
                color=alt.Color("gender:N", scale=alt.Scale(range=["#111","#888","#CCC"]), legend=alt.Legend(title=None)),
                tooltip=["gender:N", "count:Q"],
            ).properties(height=180).configure_view(strokeOpacity=0)
            st.altair_chart(pie1, use_container_width=True)

        with c2:
            st.caption("季節分佈")
            season_counts = df_sess["season"].value_counts().reset_index()
            season_counts.columns = ["season", "count"]
            pie2 = alt.Chart(season_counts).mark_arc(innerRadius=40).encode(
                theta="count:Q",
                color=alt.Color("season:N", scale=alt.Scale(range=["#111","#555","#999","#DDD"]), legend=alt.Legend(title=None)),
                tooltip=["season:N", "count:Q"],
            ).properties(height=180).configure_view(strokeOpacity=0)
            st.altair_chart(pie2, use_container_width=True)

        with c3:
            st.caption("場合分佈")
            occ_counts = df_sess["occasion"].value_counts().reset_index()
            occ_counts.columns = ["occasion", "count"]
            pie3 = alt.Chart(occ_counts).mark_arc(innerRadius=40).encode(
                theta="count:Q",
                color=alt.Color("occasion:N", legend=alt.Legend(title=None)),
                tooltip=["occasion:N", "count:Q"],
            ).properties(height=180).configure_view(strokeOpacity=0)
            st.altair_chart(pie3, use_container_width=True)

    except Exception as e:
        st.info(f"需要安裝 pandas + altair：{e}")
else:
    st.info("暫無 Session 資料")

# ── Footer ───────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; font-family:'Inter',sans-serif;
font-size:10px; letter-spacing:2px; color:#CCCCCC; margin-top:3rem;">
AI STYLIST — ANALYTICS DASHBOARD
</div>
""", unsafe_allow_html=True)
