import streamlit as st
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(override=True)

def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

sb_url = get_secret("SUPABASE_URL")
sb_key = get_secret("SUPABASE_KEY")

st.set_page_config(page_title="AI Stylist — Analytics", page_icon="📊", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,wght@0,400..900;1,400..900&family=Inter:wght@100..900&display=swap');
.stApp { background-color: #FFFFFF; }
h1,h2,h3 { font-family:'Bodoni Moda',serif !important; color:#111; }
.dash-title { font-family:'Bodoni Moda',serif; font-size:2.4rem; font-weight:800; letter-spacing:-1px; color:#111; margin-bottom:0; }
.dash-sub { font-family:'Inter',sans-serif; font-size:11px; letter-spacing:3px; text-transform:uppercase; color:#999; margin-bottom:2rem; }
.section-label { font-family:'Inter',sans-serif; font-size:10px; letter-spacing:3px; text-transform:uppercase; color:#AAAAAA; border-bottom:0.5px solid #EEE; padding-bottom:6px; margin-bottom:1rem; }
hr { border:none; border-top:0.5px solid #EEE; margin:2rem 0; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="dash-title">Analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="dash-sub">AI Stylist — Backend Dashboard</div>', unsafe_allow_html=True)

if not sb_url or not sb_key:
    st.warning("⚠️  找不到 Supabase 連線設定。")
    st.stop()

# ── Supabase helpers ─────────────────────────────────────────────

def sb_get(table: str, params=None) -> list:
    url = f"{sb_url}/rest/v1/{table}"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.ok:
            return r.json()
        st.error(f"Supabase [{table}] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        st.error(f"連線失敗: {e}")
    return []

def sb_get_events(from_iso: str, to_iso: str) -> list:
    """日期範圍查詢用 list of tuples 避免 param 合併 bug。"""
    url = f"{sb_url}/rest/v1/events"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    params = [
        ("select", "event_type,item_name,created_at"),
        ("created_at", f"gte.{from_iso}"),
        ("created_at", f"lt.{to_iso}"),
    ]
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.ok:
            return r.json()
        st.error(f"Supabase [events] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        st.error(f"連線失敗: {e}")
    return []

def sb_get_sessions(from_iso: str) -> list:
    url = f"{sb_url}/rest/v1/sessions"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
    params = [
        ("select", "gender,season,occasion,styles"),
        ("created_at", f"gte.{from_iso}"),
    ]
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.ok:
            return r.json()
    except Exception as e:
        st.error(f"連線失敗: {e}")
    return []

# ── Date filter ──────────────────────────────────────────────────
c1, c2, _ = st.columns([1, 1, 4])
with c1:
    date_from = st.date_input("From", value=datetime.today() - timedelta(days=30))
with c2:
    date_to = st.date_input("To", value=datetime.today())

from_iso = date_from.isoformat() + "T00:00:00"
to_iso   = (date_to + timedelta(days=1)).isoformat() + "T00:00:00"

st.markdown("<hr>", unsafe_allow_html=True)

# ── Load data ────────────────────────────────────────────────────
with st.spinner("載入資料中..."):
    events_all   = sb_get_events(from_iso, to_iso)
    sessions_all = sb_get_sessions(from_iso)
    overview     = sb_get("analytics_overview")
    top_styles   = sb_get("top_styles")
    model_perf   = sb_get("model_performance")

# ── KPIs ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Overview</div>', unsafe_allow_html=True)

generates = sum(1 for e in events_all if e.get("event_type") == "generate")
likes     = sum(1 for e in events_all if e.get("event_type") == "like")
dislikes  = sum(1 for e in events_all if e.get("event_type") == "dislike")
discovers = sum(1 for e in events_all if e.get("event_type") in ("discover_click", "discover_view"))
total_fb  = likes + dislikes
like_rate = round(likes / total_fb * 100, 1) if total_fb > 0 else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("推薦次數", f"{generates:,}")
k2.metric("👍 Like",  f"{likes:,}")
k3.metric("👎 Dislike", f"{dislikes:,}")
k4.metric("Like 率",  f"{like_rate}%")
k5.metric("Discover",  f"{discovers:,}")

st.markdown("<hr>", unsafe_allow_html=True)

# ── Charts ───────────────────────────────────────────────────────
try:
    import pandas as pd
    import altair as alt

    # Daily trend
    st.markdown('<div class="section-label">Daily Trend</div>', unsafe_allow_html=True)
    if overview:
        df_ov = pd.DataFrame(overview)
        df_ov["day"] = pd.to_datetime(df_ov["day"]).dt.date
        df_ov = df_ov[(df_ov["day"] >= date_from) & (df_ov["day"] <= date_to)].sort_values("day")
        df_m = df_ov.melt(id_vars="day", value_vars=["generates","likes","dislikes","discover_clicks"],
                          var_name="event", value_name="count")
        df_m["event"] = df_m["event"].map({"generates":"推薦","likes":"Like","dislikes":"Dislike","discover_clicks":"Discover"})
        chart = alt.Chart(df_m).mark_line(point=True).encode(
            x=alt.X("day:T", title="日期", axis=alt.Axis(format="%m/%d")),
            y=alt.Y("count:Q", title="次數"),
            color=alt.Color("event:N",
                scale=alt.Scale(domain=["推薦","Like","Dislike","Discover"],
                                range=["#111","#2ECC71","#E74C3C","#3498DB"]),
                legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["day:T","event:N","count:Q"],
        ).properties(height=260).configure_axis(
            labelFont="Inter", titleFont="Inter", labelColor="#888", titleColor="#888", gridColor="#F5F5F5"
        ).configure_view(strokeOpacity=0)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("還沒有資料，生成並 Like 幾次後這裡會出現趨勢圖。")

    st.markdown("<hr>", unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown('<div class="section-label">風格 Like 率</div>', unsafe_allow_html=True)
        if top_styles:
            df_s = pd.DataFrame(top_styles).head(10).sort_values("like_rate_pct", ascending=True)
            bar = alt.Chart(df_s).mark_bar(color="#111").encode(
                x=alt.X("like_rate_pct:Q", title="Like 率 %", scale=alt.Scale(domain=[0,100])),
                y=alt.Y("style:N", sort="-x", title=None),
                tooltip=["style:N","like_rate_pct:Q","likes:Q","dislikes:Q"],
            ).properties(height=280).configure_axis(
                labelFont="Inter", titleFont="Inter", labelColor="#888", titleColor="#888", gridColor="#F5F5F5"
            ).configure_view(strokeOpacity=0)
            st.altair_chart(bar, use_container_width=True)
        else:
            st.info("暫無風格資料")

    with col_r:
        st.markdown('<div class="section-label">Discover 熱門單品 Top 10</div>', unsafe_allow_html=True)
        disc = [e for e in events_all if e.get("event_type") in ("discover_click","discover_view") and e.get("item_name")]
        if disc:
            from collections import Counter
            top_items = Counter(e["item_name"] for e in disc).most_common(10)
            df_i = pd.DataFrame(top_items, columns=["item","clicks"]).sort_values("clicks", ascending=True)
            bar2 = alt.Chart(df_i).mark_bar(color="#111").encode(
                x=alt.X("clicks:Q", title="次數"),
                y=alt.Y("item:N", sort="-x", title=None),
                tooltip=["item:N","clicks:Q"],
            ).properties(height=280).configure_axis(
                labelFont="Inter", titleFont="Inter", labelColor="#888", titleColor="#888", gridColor="#F5F5F5"
            ).configure_view(strokeOpacity=0)
            st.altair_chart(bar2, use_container_width=True)
        else:
            st.info("暫無 Discover 資料")

    st.markdown("<hr>", unsafe_allow_html=True)

    # Model performance
    st.markdown('<div class="section-label">AI Model 表現</div>', unsafe_allow_html=True)
    if model_perf:
        df_mp = pd.DataFrame(model_perf).rename(columns={
            "model_used":"Model","uses":"使用次數",
            "avg_latency_ms":"平均回應(ms)","likes":"Like","like_rate_pct":"Like率%"
        })
        st.dataframe(df_mp, use_container_width=True, hide_index=True)
    else:
        st.info("暫無 Model 資料")

    st.markdown("<hr>", unsafe_allow_html=True)

    # User profile breakdown
    st.markdown('<div class="section-label">用戶 Profile 分佈</div>', unsafe_allow_html=True)
    if sessions_all:
        df_sess = pd.DataFrame(sessions_all)
        c1, c2, c3 = st.columns(3)
        def pie(df, col, title):
            counts = df[col].value_counts().reset_index()
            counts.columns = [col, "count"]
            return alt.Chart(counts).mark_arc(innerRadius=40).encode(
                theta="count:Q",
                color=alt.Color(f"{col}:N", legend=alt.Legend(title=None)),
                tooltip=[f"{col}:N","count:Q"],
            ).properties(height=180, title=title).configure_view(strokeOpacity=0)
        with c1:
            st.altair_chart(pie(df_sess, "gender", "性別"), use_container_width=True)
        with c2:
            st.altair_chart(pie(df_sess, "season", "季節"), use_container_width=True)
        with c3:
            st.altair_chart(pie(df_sess, "occasion", "場合"), use_container_width=True)
    else:
        st.info("暫無 Session 資料")

except ImportError:
    st.warning("請安裝 `pip install altair pandas`")

st.markdown("""
<div style="text-align:center;font-family:'Inter',sans-serif;font-size:10px;letter-spacing:2px;color:#CCC;margin-top:3rem;">
AI STYLIST — ANALYTICS DASHBOARD
</div>
""", unsafe_allow_html=True)
