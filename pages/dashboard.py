import streamlit as st
import os
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from dotenv import load_dotenv

load_dotenv(override=True)

st.set_page_config(page_title="AI Stylist — Analytics", page_icon="📊", layout="wide")

# ── Secrets ──
def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass
    return os.getenv(key, default)

sb_url         = get_secret("SUPABASE_URL")
sb_key         = get_secret("SUPABASE_KEY")
ADMIN_PASSWORD = get_secret("DASHBOARD_PASSWORD", "aistyle2026")

# ── CSS ──
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,wght@0,400..900;1,400..900&family=DM+Mono:wght@400;500&family=Inter:wght@300;400;500;600&display=swap');

html, body, [data-testid="stApp"] { background:#fff; color:#111; }
#MainMenu, footer, header { visibility:hidden; }
[data-testid="stToolbar"] { display:none; }

.dash-header {
    font-family:'Bodoni Moda',serif;
    font-size:2.2rem; font-weight:400;
    letter-spacing:6px; text-transform:uppercase;
    border-bottom:1px solid #111;
    padding-bottom:1rem; margin-bottom:0.3rem;
}
.dash-sub {
    font-family:'DM Mono',monospace;
    font-size:0.65rem; letter-spacing:3px;
    color:#999; text-transform:uppercase; margin-bottom:0.5rem;
}
.section-label {
    font-family:'DM Mono',monospace;
    font-size:0.6rem; letter-spacing:4px;
    color:#aaa; text-transform:uppercase;
    margin-bottom:1rem; margin-top:2.5rem;
    border-top:1px solid #f0f0f0; padding-top:1.5rem;
}
.kpi-grid {
    display:grid; grid-template-columns:repeat(5,1fr);
    gap:1px; background:#111; border:1px solid #111; margin-bottom:2.5rem;
}
.kpi-card { background:#fff; padding:1.5rem 1.2rem 1.2rem; }
.kpi-label {
    font-family:'DM Mono',monospace; font-size:0.58rem;
    letter-spacing:3px; color:#999; text-transform:uppercase; margin-bottom:0.6rem;
}
.kpi-value {
    font-family:'Bodoni Moda',serif; font-size:2.4rem;
    font-weight:700; line-height:1; color:#111;
}
.kpi-delta { font-family:'DM Mono',monospace; font-size:0.6rem; letter-spacing:1px; margin-top:0.4rem; }
.kpi-delta.up   { color:#16a34a; }
.kpi-delta.down { color:#dc2626; }
.kpi-delta.neu  { color:#aaa; }

.funnel-row { display:flex; align-items:center; margin-bottom:0.6rem; gap:1rem; }
.funnel-label { font-family:'DM Mono',monospace; font-size:0.65rem; letter-spacing:2px; color:#555; width:180px; flex-shrink:0; }
.funnel-bar-wrap { flex:1; height:28px; background:#f5f5f5; position:relative; }
.funnel-bar { height:100%; }
.funnel-count { font-family:'DM Mono',monospace; font-size:0.7rem; color:#555; width:60px; text-align:right; }
.funnel-rate  { font-family:'DM Mono',monospace; font-size:0.65rem; color:#aaa; width:50px; text-align:right; }

.model-table { width:100%; border-collapse:collapse; }
.model-table th {
    font-family:'DM Mono',monospace; font-size:0.58rem;
    letter-spacing:3px; color:#999; text-transform:uppercase;
    border-bottom:1px solid #111; padding:0.6rem 0.8rem; text-align:left;
}
.model-table td {
    font-family:'Inter',sans-serif; font-size:0.82rem;
    padding:0.8rem; border-bottom:1px solid #f0f0f0; color:#333;
}
.model-table td:first-child { font-family:'DM Mono',monospace; font-size:0.75rem; color:#111; }
.model-tag {
    display:inline-block; font-family:'DM Mono',monospace;
    font-size:0.55rem; letter-spacing:2px; padding:2px 8px;
    border:1px solid #111; color:#111; text-transform:uppercase;
}
.model-tag.primary { background:#111; color:#fff; }

.insight-box {
    background:#f9f9f9; border-left:3px solid #111;
    padding:1rem 1.2rem; margin-bottom:0.8rem;
    font-family:'Inter',sans-serif; font-size:0.82rem; color:#333; line-height:1.7;
}
.insight-box b { color:#111; }

.dist-row { display:flex; align-items:center; gap:0.8rem; margin-bottom:0.5rem; }
.dist-key { font-family:'DM Mono',monospace; font-size:0.65rem; letter-spacing:1px; color:#555; width:120px; flex-shrink:0; }
.dist-bar-wrap { flex:1; height:18px; background:#f5f5f5; }
.dist-bar { height:100%; background:#111; }
.dist-pct { font-family:'DM Mono',monospace; font-size:0.65rem; color:#999; width:42px; text-align:right; }
</style>
""", unsafe_allow_html=True)

# ── 密碼保護 ──
if "dash_auth" not in st.session_state:
    st.session_state.dash_auth = False

if not st.session_state.dash_auth:
    st.markdown('<div class="dash-header">AI STYLIST</div>', unsafe_allow_html=True)
    st.markdown('<div class="dash-sub">Analytics Dashboard · Restricted Access</div>', unsafe_allow_html=True)
    pw = st.text_input("Password", type="password")
    if st.button("Enter"):
        if pw == ADMIN_PASSWORD:
            st.session_state.dash_auth = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

if not sb_url or not sb_key:
    st.warning("⚠️ 找不到 Supabase 連線設定")
    st.stop()

# ── Supabase helpers ──
def sb_get(table: str, params=None) -> list:
    url = f"{sb_url}/rest/v1/{table}"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Range": "0-4999"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.ok:
            return r.json()
        st.error(f"Supabase [{table}] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        st.error(f"連線失敗: {e}")
    return []

def sb_get_ranged(table: str, select: str, from_iso: str, to_iso: str, extra: list = None) -> list:
    """日期範圍查詢，用 list of tuples 避免 param 合併 bug。"""
    url = f"{sb_url}/rest/v1/{table}"
    headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Range": "0-4999"}
    params = [
        ("select", select),
        ("created_at", f"gte.{from_iso}"),
        ("created_at", f"lt.{to_iso}"),
    ]
    if extra:
        params.extend(extra)
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.ok:
            return r.json()
        st.error(f"Supabase [{table}] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        st.error(f"連線失敗: {e}")
    return []

# ── Header ──
st.markdown('<div class="dash-header">AI STYLIST</div>', unsafe_allow_html=True)
now_utc = datetime.now(timezone.utc)
ts_str  = now_utc.strftime("%Y·%m·%d  %H:%M UTC")
st.markdown(f'<div class="dash-sub">Analytics Dashboard · {ts_str}</div>', unsafe_allow_html=True)

# ── Date Filter（從舊版移植）──
col_f1, col_f2, col_f3 = st.columns([1, 1, 4])
with col_f1:
    date_from = st.date_input("From", value=datetime.today() - timedelta(days=30))
with col_f2:
    date_to = st.date_input("To", value=datetime.today())
with col_f3:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↺ Refresh Data"):
        st.cache_data.clear()
        st.rerun()

from_iso = date_from.isoformat() + "T00:00:00"
to_iso   = (date_to + timedelta(days=1)).isoformat() + "T00:00:00"

# ── 資料載入 ──
@st.cache_data(ttl=120)
def load_data(from_iso, to_iso):
    # 原始資料（日期篩選）
    events   = sb_get_ranged("events",   "event_type,item_name,session_id,rec_id,created_at", from_iso, to_iso)
    sessions = sb_get_ranged("sessions", "id,gender,season,occasion,language,has_photo_upload,styles,created_at", from_iso, to_iso)
    recs     = sb_get_ranged("recommendations", "id,session_id,model_used,latency_ms,zara_items,created_at", from_iso, to_iso)
    # Supabase views（全量，前端再篩日期）
    overview   = sb_get("analytics_overview")   # 每日聚合：day, generates, likes, dislikes, discover_clicks
    model_perf = sb_get("model_performance")    # model_used, uses, avg_latency_ms, likes, like_rate_pct
    return events, sessions, recs, overview, model_perf

with st.spinner("載入資料中..."):
    events, sessions, recs, overview, model_perf = load_data(from_iso, to_iso)

# ── 衍生計算 ──
import pandas as pd
import altair as alt

today = datetime.today().date()
yday  = today - timedelta(days=1)

def date_of(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except:
        return None

# 事件分類
like_sessions    = {e["session_id"] for e in events if e["event_type"] == "like"}
dislike_sessions = {e["session_id"] for e in events if e["event_type"] == "dislike"}
disc_events      = [e for e in events if e["event_type"] in ("discover_click","discover_view")]

total_sessions  = len(sessions)
total_recs      = len(recs)
total_likes     = len([e for e in events if e["event_type"] == "like"])
total_dislikes  = len([e for e in events if e["event_type"] == "dislike"])
total_discovers = len(disc_events)
total_feedback  = total_likes + total_dislikes

photo_count  = sum(1 for s in sessions if s.get("has_photo_upload"))
photo_rate   = round(photo_count / total_sessions * 100) if total_sessions else 0

session_rec_cnt = defaultdict(int)
for r in recs:
    session_rec_cnt[r["session_id"]] += 1
avg_gen = round(sum(session_rec_cnt.values()) / len(session_rec_cnt), 1) if session_rec_cnt else 0

engagement_rate = round(len(like_sessions | dislike_sessions) / total_sessions * 100) if total_sessions else 0
satisfaction    = round(total_likes / total_feedback * 100) if total_feedback else 0

# 7d 成長率（從 overview view 計算）
if overview:
    df_ov = pd.DataFrame(overview)
    df_ov["day"] = pd.to_datetime(df_ov["day"]).dt.date
    last7 = df_ov[df_ov["day"] >= today - timedelta(days=6)]["generates"].sum()
    prev7 = df_ov[(df_ov["day"] >= today - timedelta(days=13)) & (df_ov["day"] < today - timedelta(days=6))]["generates"].sum()
    growth = round((last7 - prev7) / prev7 * 100) if prev7 else None
else:
    growth = None

def delta_html(val, suffix="%"):
    if val is None:
        return '<span class="kpi-delta neu">— no prior data</span>'
    sign = "▲" if val >= 0 else "▼"
    cls  = "up" if val >= 0 else "down"
    return f'<span class="kpi-delta {cls}">{sign} {abs(val)}{suffix} vs prev 7d</span>'

# ── SECTION 1：North Star KPIs ──
st.markdown('<div class="section-label">North Star Metrics</div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-label">Total Sessions</div>
    <div class="kpi-value">{total_sessions}</div>
    {delta_html(growth)}
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Photo Upload Rate</div>
    <div class="kpi-value">{photo_rate}%</div>
    <span class="kpi-delta neu">深度使用指標</span>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Avg Gen / Session</div>
    <div class="kpi-value">{avg_gen}</div>
    <span class="kpi-delta neu">參與深度</span>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Engagement Rate</div>
    <div class="kpi-value">{engagement_rate}%</div>
    <span class="kpi-delta neu">留下 Like / Dislike</span>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Satisfaction</div>
    <div class="kpi-value">{satisfaction}%</div>
    <span class="kpi-delta neu">有回饋者中 Like 率</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── SECTION 2：成長曲線（從 analytics_overview view）──
st.markdown('<div class="section-label">Growth Trend</div>', unsafe_allow_html=True)

if overview:
    df_trend = pd.DataFrame(overview)
    df_trend["day"] = pd.to_datetime(df_trend["day"]).dt.date
    df_trend = df_trend[(df_trend["day"] >= date_from) & (df_trend["day"] <= date_to)].sort_values("day")

    # 累積 session（用篩選後的 sessions 資料計算）
    daily_sess = defaultdict(int)
    for s in sessions:
        d = date_of(s.get("created_at",""))
        if d:
            daily_sess[d] += 1

    if not df_trend.empty:
        col_l, col_r = st.columns(2)

        with col_l:
            st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:#aaa;text-transform:uppercase;margin-bottom:0.5rem;">每日生成次數趨勢</p>', unsafe_allow_html=True)
            df_m = df_trend.melt(
                id_vars="day",
                value_vars=["generates","likes","dislikes","discover_clicks"],
                var_name="event", value_name="count"
            )
            df_m["event"] = df_m["event"].map({
                "generates": "推薦", "likes": "Like",
                "dislikes": "Dislike", "discover_clicks": "Discover"
            })
            line = alt.Chart(df_m).mark_line(point=True).encode(
                x=alt.X("day:T", title="日期", axis=alt.Axis(format="%m/%d", labelFont="DM Mono", labelColor="#aaa", gridColor="#f5f5f5", domainColor="#eee")),
                y=alt.Y("count:Q", title="次數", axis=alt.Axis(labelFont="DM Mono", labelColor="#aaa", gridColor="#f5f5f5", domainColor="#eee")),
                color=alt.Color("event:N",
                    scale=alt.Scale(domain=["推薦","Like","Dislike","Discover"],
                                    range=["#111","#16a34a","#dc2626","#3b82f6"]),
                    legend=alt.Legend(title=None, orient="bottom", labelFont="DM Mono", labelFontSize=10)),
                tooltip=["day:T","event:N","count:Q"],
            ).properties(height=220).configure_view(strokeWidth=0)
            st.altair_chart(line, use_container_width=True)

        with col_r:
            st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:#aaa;text-transform:uppercase;margin-bottom:0.5rem;">累積生成次數（成長曲線）</p>', unsafe_allow_html=True)
            df_cum = df_trend[["day","generates"]].copy()
            df_cum["cumulative"] = df_cum["generates"].cumsum()
            area = alt.Chart(df_cum).mark_area(
                line={"color":"#111","strokeWidth":2},
                color=alt.Gradient(gradient="linear",
                    stops=[alt.GradientStop(color="#111",offset=0),
                           alt.GradientStop(color="#fff",offset=1)],
                    x1=1,x2=1,y1=1,y2=0)
            ).encode(
                x=alt.X("day:T", title="日期", axis=alt.Axis(format="%m/%d", labelFont="DM Mono", labelColor="#aaa", gridColor="#f5f5f5", domainColor="#eee")),
                y=alt.Y("cumulative:Q", title="累積次數", axis=alt.Axis(labelFont="DM Mono", labelColor="#aaa", gridColor="#f5f5f5", domainColor="#eee")),
                tooltip=["day:T","cumulative:Q"]
            ).properties(height=220).configure_view(strokeWidth=0)
            st.altair_chart(area, use_container_width=True)
    else:
        st.info("選定日期區間內無資料")
else:
    st.info("analytics_overview view 無資料")

# ── SECTION 3：用戶行為漏斗 ──
st.markdown('<div class="section-label">User Behaviour Funnel</div>', unsafe_allow_html=True)

sessions_with_rec      = len(set(r["session_id"] for r in recs))
sessions_with_discover = len(set(e["session_id"] for e in disc_events))
sessions_with_feedback = len(like_sessions | dislike_sessions)

funnel_steps = [
    ("SESSION STARTED",     total_sessions,           total_sessions, "#111"),
    ("GENERATED ≥1 OUTFIT", sessions_with_rec,         total_sessions, "#111"),
    ("CLICKED DISCOVER",    sessions_with_discover,    total_sessions, "#555"),
    ("LEFT FEEDBACK",       sessions_with_feedback,    total_sessions, "#888"),
    ("LIKED RESULT",        len(like_sessions),        total_sessions, "#bbb"),
]
funnel_html = ""
for label, count, base, color in funnel_steps:
    pct = round(count / base * 100) if base else 0
    funnel_html += f"""
    <div class="funnel-row">
      <div class="funnel-label">{label}</div>
      <div class="funnel-bar-wrap"><div class="funnel-bar" style="width:{pct}%;background:{color};"></div></div>
      <div class="funnel-count">{count}</div>
      <div class="funnel-rate">{pct}%</div>
    </div>"""
st.markdown(funnel_html, unsafe_allow_html=True)

col_i1, col_i2 = st.columns(2)
with col_i1:
    gen_rate  = round(sessions_with_rec / total_sessions * 100) if total_sessions else 0
    st.markdown(f'<div class="insight-box">生成轉換率 <b>{gen_rate}%</b>：每 100 個進入 App 的用戶中，有 {gen_rate} 個完成至少一次生成。</div>', unsafe_allow_html=True)
with col_i2:
    disc_rate = round(sessions_with_discover / sessions_with_rec * 100) if sessions_with_rec else 0
    st.markdown(f'<div class="insight-box">Discover 點擊率 <b>{disc_rate}%</b>：完成生成的用戶中，有 {disc_rate}% 點擊了 ZARA 商品連結，代表實際購物意圖。</div>', unsafe_allow_html=True)

# ── SECTION 4：AI Model 表現（從 model_performance Supabase view）──
st.markdown('<div class="section-label">AI Model Performance</div>', unsafe_allow_html=True)

CURRENT_MODELS = {"gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"}

if model_perf:
    model_rows = ""
    for row in sorted(model_perf, key=lambda x: -x.get("uses", 0)):
        name    = row.get("model_used", "—")
        uses    = row.get("uses", 0)
        avg_lat = row.get("avg_latency_ms")
        lat_str = f"{round(avg_lat/1000,1)}s" if avg_lat else "—"
        likes   = row.get("likes", 0)
        like_r  = row.get("like_rate_pct")
        like_str= f"{round(like_r)}%" if like_r is not None else "—"
        tag     = '<span class="model-tag primary">ACTIVE</span>' if name in CURRENT_MODELS else '<span class="model-tag">LEGACY</span>'
        model_rows += f"""
        <tr>
          <td>{name}</td><td>{tag}</td>
          <td style="font-family:'DM Mono',monospace;text-align:right;">{uses}</td>
          <td style="font-family:'DM Mono',monospace;text-align:right;">{lat_str}</td>
          <td style="font-family:'DM Mono',monospace;text-align:right;">{likes}</td>
          <td style="font-family:'DM Mono',monospace;text-align:right;">{like_str}</td>
        </tr>"""
    st.markdown(f"""
    <table class="model-table">
      <thead><tr>
        <th>Model</th><th>Status</th>
        <th style="text-align:right;">Uses</th>
        <th style="text-align:right;">Avg Latency</th>
        <th style="text-align:right;">Likes</th>
        <th style="text-align:right;">Like Rate</th>
      </tr></thead>
      <tbody>{model_rows}</tbody>
    </table>""", unsafe_allow_html=True)
else:
    st.info("暫無 model_performance 資料")

# ── SECTION 5：用戶 Profile 分佈 ──
st.markdown('<div class="section-label">User Profile Distribution</div>', unsafe_allow_html=True)

def dist_bars(count_dict, label):
    total = sum(count_dict.values()) or 1
    items = sorted(count_dict.items(), key=lambda x: -x[1])
    html  = f'<p style="font-family:\'DM Mono\',monospace;font-size:0.6rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.8rem;">{label}</p>'
    for k, v in items:
        pct = round(v / total * 100)
        html += f"""
        <div class="dist-row">
          <div class="dist-key">{k}</div>
          <div class="dist-bar-wrap"><div class="dist-bar" style="width:{pct}%"></div></div>
          <div class="dist-pct">{pct}%</div>
        </div>"""
    return html

gender_cnt = defaultdict(int)
season_cnt = defaultdict(int)
occ_cnt    = defaultdict(int)
lang_cnt   = defaultdict(int)
for s in sessions:
    gender_cnt[s.get("gender","Unknown")]   += 1
    season_cnt[s.get("season","Unknown")]   += 1
    occ_cnt[s.get("occasion","Unknown")]    += 1
    lang_cnt[s.get("language","Unknown")]   += 1

col_p1, col_p2, col_p3, col_p4 = st.columns(4)
with col_p1: st.markdown(dist_bars(gender_cnt, "Gender"),   unsafe_allow_html=True)
with col_p2: st.markdown(dist_bars(season_cnt, "Season"),   unsafe_allow_html=True)
with col_p3: st.markdown(dist_bars(occ_cnt,    "Occasion"), unsafe_allow_html=True)
with col_p4: st.markdown(dist_bars(lang_cnt,   "Language"), unsafe_allow_html=True)

# ── SECTION 6：Style & Product Intelligence ──
st.markdown('<div class="section-label">Style & Product Intelligence</div>', unsafe_allow_html=True)

style_cnt = defaultdict(int)
for s in sessions:
    for sty in (s.get("styles") or []):
        style_cnt[sty] += 1

item_cnt = defaultdict(int)
for r in recs:
    for item in (r.get("zara_items") or []):
        name = item.get("name","")
        if name:
            item_cnt[name] += 1
top_items = sorted(item_cnt.items(), key=lambda x: -x[1])[:8]

col_s1, col_s2 = st.columns(2)
with col_s1:
    st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.6rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.8rem;">Style Demand Ranking</p>', unsafe_allow_html=True)
    style_total = sum(style_cnt.values()) or 1
    for sty, cnt in sorted(style_cnt.items(), key=lambda x: -x[1])[:8]:
        pct = round(cnt / style_total * 100)
        st.markdown(f"""
        <div class="dist-row">
          <div class="dist-key" style="width:150px">{sty[:20]}</div>
          <div class="dist-bar-wrap"><div class="dist-bar" style="width:{pct}%"></div></div>
          <div class="dist-pct">{cnt}x</div>
        </div>""", unsafe_allow_html=True)

with col_s2:
    st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.6rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.8rem;">Top Recommended ZARA Items</p>', unsafe_allow_html=True)
    if top_items:
        max_cnt = top_items[0][1] or 1
        for name, cnt in top_items:
            pct = round(cnt / max_cnt * 100)
            st.markdown(f"""
            <div class="dist-row">
              <div class="dist-key" style="width:190px;font-size:0.6rem;">{name[:26]}</div>
              <div class="dist-bar-wrap"><div class="dist-bar" style="width:{pct}%"></div></div>
              <div class="dist-pct">{cnt}x</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.7rem;color:#aaa;">No item data yet</p>', unsafe_allow_html=True)

# ── SECTION 7：Competition Traction Summary ──
st.markdown('<div class="section-label">Competition Traction Summary</div>', unsafe_allow_html=True)

all_session_dates = sorted([date_of(s.get("created_at","")) for s in sessions if date_of(s.get("created_at",""))])
launch_date = str(all_session_dates[0]) if all_session_dates else "—"
rec_per_session = round(total_recs / total_sessions, 1) if total_sessions else 0

st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#111;border:1px solid #111;margin-bottom:1rem;">
  <div style="background:#fff;padding:1.2rem;">
    <div style="font-family:'DM Mono',monospace;font-size:0.58rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.5rem;">Prototype Live Since</div>
    <div style="font-family:'Bodoni Moda',serif;font-size:1.3rem;">{launch_date}</div>
  </div>
  <div style="background:#fff;padding:1.2rem;">
    <div style="font-family:'DM Mono',monospace;font-size:0.58rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.5rem;">Total Recommendations Generated</div>
    <div style="font-family:'Bodoni Moda',serif;font-size:1.3rem;">{total_recs}</div>
  </div>
  <div style="background:#fff;padding:1.2rem;">
    <div style="font-family:'DM Mono',monospace;font-size:0.58rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.5rem;">ZARA Discover Clicks</div>
    <div style="font-family:'Bodoni Moda',serif;font-size:1.3rem;">{total_discovers}</div>
  </div>
  <div style="background:#fff;padding:1.2rem;">
    <div style="font-family:'DM Mono',monospace;font-size:0.58rem;letter-spacing:3px;color:#999;text-transform:uppercase;margin-bottom:0.5rem;">Photo Upload Rate（深度使用）</div>
    <div style="font-family:'Bodoni Moda',serif;font-size:1.3rem;">{photo_rate}%</div>
  </div>
</div>
<div class="insight-box">
  <b>競賽報告 Key Numbers：</b>
  從 {launch_date} 上線至今，AI Stylist 累積 <b>{total_sessions} 個 Sessions</b>，
  共生成 <b>{total_recs} 次穿搭推薦</b>，平均每個 Session 生成 <b>{rec_per_session} 次</b>。
  用戶對推薦結果的 ZARA 商品點擊率達 <b>{disc_rate}%</b>，
  顯示產品具備驅動實際購物行為的能力。有 <b>{photo_rate}%</b> 的用戶主動上傳穿搭照片使用進階功能，
  代表核心功能的深度採用率。
</div>
""", unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)
