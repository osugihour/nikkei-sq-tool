import streamlit as st
import yfinance as yf
import pandas as pd
import json
import requests
import io
from datetime import date, datetime
from tickers import NIKKEI_225_TICKERS

st.set_page_config(page_title="日経225 SQ計算ツール", page_icon="📊", layout="wide")

st.title("📊 日経225 SQ計算ツール")
st.caption("ウィークリー・月次オプション対応 ｜ 構成銘柄の始値からSQ値をリアルタイム算出")

# ── 構成銘柄をWikipediaから自動取得（失敗時はローカルリストで代替）──
@st.cache_data(ttl=86400)
def get_nikkei225_tickers():
    try:
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NikkeiSQTool/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        for t in tables:
            for col in t.columns:
                if "code" in str(col).lower() or "ticker" in str(col).lower() or "symbol" in str(col).lower():
                    codes = t[col].dropna().astype(str).tolist()
                    tickers = [f"{c.zfill(4)}.T" for c in codes if c.isdigit() and len(c) <= 4]
                    if len(tickers) > 100:
                        return tickers, "Wikipedia"
    except Exception:
        pass
    return NIKKEI_225_TICKERS, "ローカルリスト（tickers.py）"

# ── 除数の読み込み ──────────────────────────────────────────────
def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"divisor": 27.769, "updated": "不明"}

config = load_config()
stored_divisor = config["divisor"]
divisor_updated = config.get("updated", "不明")

# ── 銘柄リスト取得 ────────────────────────────────────────────
with st.spinner("日経225構成銘柄リストを取得中..."):
    tickers, ticker_source = get_nikkei225_tickers()

if len(tickers) < 100:
    st.error(f"構成銘柄の取得に失敗しました（取得数: {len(tickers)}）。ページを再読み込みしてください。")
    st.stop()

st.success(f"✅ 構成銘柄 {len(tickers)} 銘柄を読み込みました（出所：{ticker_source}）")

# ── 除数入力UI ────────────────────────────────────────────────
st.subheader("① 除数（Divisor）の設定")
col1, col2 = st.columns([2, 3])

with col1:
    divisor_input = st.number_input(
        "現在の除数を入力してください",
        value=float(stored_divisor),
        min_value=1.0,
        max_value=100.0,
        step=0.001,
        format="%.3f",
        help="除数はBloombergまたは日経公式で確認できます。"
    )

with col2:
    st.info(f"📁 config.json の保存値：**{stored_divisor:.3f}**（最終更新：{divisor_updated}）")
    if abs(divisor_input - stored_divisor) > 0.0001:
        st.warning(
            f"⚠️ 入力された除数（{divisor_input:.3f}）が保存値（{stored_divisor:.3f}）と異なります。\n\n"
            "除数が変更された場合は、GitHubリポジトリの **config.json** を更新してください。"
        )

# ── 逆算機能（実SQから除数を確認）───────────────────────────────
with st.expander("🔧 実際のSQ値から除数を逆算する（除数確認用）"):
    st.caption("始値合計が分かっている場合に、正しい除数を確認できます")
    col_x, col_y, col_z = st.columns(3)
    real_sq = col_x.number_input("実際のSQ値（円）", value=0.0, step=100.0, format="%.2f")
    sum_input = col_y.number_input("始値合計（円）", value=0.0, step=1000.0, format="%.1f")
    if real_sq > 0 and sum_input > 0:
        implied_divisor = sum_input / real_sq
        col_z.metric("逆算された除数", f"{implied_divisor:.3f}")

# ── データ取得 ────────────────────────────────────────────────
st.subheader("② 始値データの取得")
today_str = date.today().strftime("%Y年%m月%d日")
st.write(f"対象日：**{today_str}**（SQ算出日に実行してください）")

if st.button("🔄 始値を取得してSQを計算する", type="primary"):

    with st.spinner(f"{len(tickers)}銘柄のデータを取得中...（約30秒かかります）"):
        try:
            tickers_str = " ".join(tickers)
            raw = yf.download(
                tickers_str,
                period="2d",
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            open_data = raw["Open"].iloc[-1]
        except Exception as e:
            st.error(f"データ取得エラー: {e}")
            st.stop()

    # ── 結果整理 ──────────────────────────────────────────────
    records = []
    for ticker in tickers:
        price = open_data.get(ticker, None)
        if pd.isna(price) or price is None or price == 0:
            records.append({"コード": ticker.replace(".T", ""), "ティッカー": ticker, "始値": None, "状態": "未取得"})
        else:
            records.append({"コード": ticker.replace(".T", ""), "ティッカー": ticker, "始値": round(float(price), 1), "状態": "取得済"})

    df = pd.DataFrame(records)
    fetched = df[df["状態"] == "取得済"]
    missing = df[df["状態"] == "未取得"]

    total_open = fetched["始値"].sum()
    sq_value = total_open / divisor_input

    # ── SQ表示 ───────────────────────────────────────────────
    st.subheader("③ SQ算出結果")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("推計SQ値", f"{sq_value:,.2f} 円")
    col_b.metric("取得済銘柄数", f"{len(fetched)} / {len(tickers)}")
    col_c.metric("始値合計", f"{total_open:,.1f} 円")
    col_d.metric("使用除数", f"{divisor_input:.3f}")

    if len(missing) > 0:
        st.warning(
            f"⚠️ **{len(missing)}銘柄**の始値が取得できていません。"
            "未取得銘柄が多い場合、SQ値は参考値となります。"
        )

    st.caption(f"算出時刻：{datetime.now().strftime('%H:%M:%S')} ｜ SQ = 始値合計（{total_open:,.1f}）÷ 除数（{divisor_input:.3f}）")

    # ── 詳細テーブル ──────────────────────────────────────────
    st.subheader("④ 銘柄別始値一覧")

    tab1, tab2 = st.tabs([f"取得済（{len(fetched)}銘柄）", f"未取得（{len(missing)}銘柄）"])

    with tab1:
        st.dataframe(
            fetched[["コード", "始値"]].reset_index(drop=True),
            use_container_width=True,
            height=400,
        )

    with tab2:
        if len(missing) > 0:
            st.dataframe(missing[["コード", "ティッカー"]].reset_index(drop=True), use_container_width=True)
        else:
            st.success("全銘柄の始値を取得できました！")

# ── フッター ──────────────────────────────────────────────────
st.divider()
st.
