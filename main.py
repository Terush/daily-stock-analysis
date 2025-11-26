import yfinance as yf
import pandas as pd
import numpy as np
import os
from datetime import datetime

# --- ユーザーの計算ロジック (変更なし) ---
period_days = {
    "1mo": 20,
    "3mo": 60,
    "6mo": 120,
}
# 会社名辞書を CSV から読み込む
company_dict = {}
csv_path = "japan_stocks.csv"  # CSVファイル名（必要ならパスを変更）

if os.path.exists(csv_path):
    df_company = pd.read_csv(csv_path)
    # 必須カラムがあるか一応チェック
    if {"ticker", "company_name"} <= set(df_company.columns):
        company_dict = dict(zip(df_company["ticker"], df_company["company_name"]))
    else:
        print("WARN: japan_stocks.csv に 'ticker' または 'company_name' がありません")
else:
    print("WARN: japan_stocks.csv が見つかりません。ticker をそのまま表示します。")


def calc_sigma_signal(df, period_name):
    days = period_days.get(period_name, 20)

    # データが足りない場合は終了
    if len(df) < days + 1:
        return "-"

    df_subset = df.tail(days + 1).copy()

    # Adj Close が無ければ Close を使う
    if "Adj Close" in df_subset.columns:
        adj_series = df_subset["Adj Close"]
    else:
        adj_series = df_subset["Close"]

    close_series = df_subset["Close"]

    current_price = float(close_series.iloc[-1])
    last_close_ref = float(close_series.iloc[-2])

    # 直近の計算に当日を含めない
    calc_series_adj = adj_series.iloc[:-1]

    # 対数収益率 → ボラティリティ
    log_returns = np.log(calc_series_adj / calc_series_adj.shift(1)).dropna()
    if len(log_returns) < 5:
        return "-"

    daily_vol = float(log_returns.std())

    sigma1 = last_close_ref * daily_vol
    upper_2 = last_close_ref + 2 * sigma1
    lower_2 = last_close_ref - 2 * sigma1
    upper_1 = last_close_ref + sigma1
    lower_1 = last_close_ref - sigma1

    if current_price < lower_2:
        return "!! 強い買い (-2σ割れ)"
    elif current_price < lower_1:
        return "弱い買い (-1σ〜-2σ)"
    elif current_price > upper_2:
        return "!! 強い売り (+2σ超え)"
    elif current_price > upper_1:
        return "弱い売り (+1σ〜+2σ)"
    else:
        return "中立"

def calc_technical_status(df):
    if len(df) < 30:
        return "データ不足", 0.0
    adj_close = df["Adj Close"]
    current_price = float(adj_close.iloc[-1].item())
    sma_25 = adj_close.rolling(window=25).mean().iloc[-1].item()

    window = 14
    delta = adj_close.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/window, min_periods=window).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, min_periods=window).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1].item()

    
    trend_str = ""
    if current_price > sma_25:
        trend_str = "上昇トレンド"
    else:
        trend_str = "下落トレンド"
    return trend_str, rsi

def analyze_stock_combined(ticker):
    try:
        df = yf.download(ticker, period="1y", progress=False, auto_adjust=False)

        # データの有無チェック
        if df.empty or ("Close" not in df.columns and "Adj Close" not in df.columns):
            return {"ticker": ticker, "company_name": "取得失敗"}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ---------------------------------------------------
        # ▼ 【修正】画像生成を削除し、計算のみを行う
        # ---------------------------------------------------
        calc_col = "Adj Close" if "Adj Close" in df.columns else "Close"
        price_col = "Close" if "Close" in df.columns else "Adj Close"

        series_calc = df[calc_col]
        current_price = float(df[price_col].iloc[-1].item())

        # 対数収益率 (全期間)
        log_returns = np.log(series_calc / series_calc.shift(1)).dropna()

        # 年率ボラティリティ & 予測レンジ計算
        if len(log_returns) > 0:
            daily_vol = log_returns.std()
            # 年率換算 (営業日252日)
            annual_vol = daily_vol * np.sqrt(252)

            # 予測レンジ (±2σ, 対数正規分布近似)
            price_upper_2 = current_price * np.exp(2 * annual_vol)
            price_lower_2 = current_price * np.exp(-2 * annual_vol)

            hv_str = f"{annual_vol*100:.1f}%"
            range_str = f"{int(price_lower_2):,} ~ {int(price_upper_2):,}円"
        else:
            hv_str = "-"
            range_str = "-"
        # ---------------------------------------------------

        result = {"ticker": ticker}
        for p_name in period_days.keys():
            result[f"σ判定_{p_name}"] = calc_sigma_signal(df, p_name)

        trend, rsi_val = calc_technical_status(df)
        result["トレンド判定"] = trend
        result["RSI"] = f"{rsi_val:.1f}"

        # 結果辞書に追加
        result["年率HV"] = hv_str
        result["予測レンジ(1年後)"] = range_str
        # ▼【追加】現在価格を見やすくフォーマットして追加
        result["現在価格"] = f"{current_price:,.0f}円"

        # （以下、判定ロジックは変更なし）
        sig_1mo = result["σ判定_1mo"]
        sig_3mo = result["σ判定_3mo"]
        sig_6mo = result["σ判定_6mo"]

        def sigma_level(text):
            if "強い買い" in text: return 2
            elif "弱い買い" in text: return 1
            elif "中立" in text or "-" in text: return 0
            elif "弱い売り" in text: return -1
            elif "強い売り" in text: return -2
            return 0

        level_1 = sigma_level(sig_1mo)
        level_3 = sigma_level(sig_3mo)
        level_6 = sigma_level(sig_6mo)
        # --- 重みの設定 (ここをお好みで調整してください) ---
        w_1 = 3.0  # 1ヶ月の重み (一番重視)
        w_3 = 2.0  # 3ヶ月の重み
        w_6 = 1.0  # 6ヶ月の重み
        total_weight = w_1 + w_3 + w_6

        # 加重平均の計算
        avg_sigma = float((level_1 * w_1 + level_3 * w_3 + level_6 * w_6) / total_weight)

        # -----------------------------------------------------------
        # ▼ 総合判定ロジック（高校生でもわかる直感バージョン）
        # -----------------------------------------------------------
        judge = "🤔 よくわからない（今はパス）"
        
        # 判定用のフラグ
        is_trend_up = ("上昇" in trend)
        is_cheap    = (avg_sigma >= 0.8)   # 安くなってる
        is_expensive= (avg_sigma <= -0.8)  # 高くなってる
        
        # 1. 上昇トレンド（基本はイケイケ）
        if is_trend_up:
            if is_cheap:
                # 上がってる最中に一時的に安くなった＝チャンス
                if rsi_val < 40:
                    judge = "😍 超チャンス！バーゲンセール中"
                else:
                    judge = "🛒 いい波きてる！買ってみる？"
            
            elif is_expensive:
                # 上がりすぎてて怖い
                if rsi_val > 75:
                    judge = "💰 勝ち逃げしよう（利益確定）"
                else:
                    judge = "✋ 高すぎ！今はガマン（買うな）"
            
            else:
                # 順調
                judge = "✨ 順調だよ（持ってるならキープ）"

        # 2. 下落トレンド（基本はダメ）
        if not is_trend_up:
            if is_cheap:
                # 下がってる最中は、安く見えてもさらに下がる
                if rsi_val < 25:
                    judge = "🎰 一か八かの賭け（リバウンド狙い）"
                else:
                    judge = "💣 落ちてる最中（触るとケガするよ）"
            
            elif is_expensive:
                # 下落中にちょっと上がった＝ワナ
                judge = "💨 今すぐ逃げて！（損切りチャンス）"
            
            else:
                judge = "🙅‍♂️ ダメそう（手を出さないで）"

        # 3. 異常事態（最優先）
        if rsi_val > 85:
            judge = "🚨 警報！バブル崩壊かも（すぐ売れ）"
        
        # 結果を格納
        result["総合判断"] = judge
        # -----------------------------------------------------------

        result["company_name"] = get_company_name(ticker)
        return result
    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        return {"ticker": ticker, "総合判断": "エラー"}

def get_company_name(ticker):
    name = company_dict.get(ticker)
    if name:
        return name

    # フォールバックで yfinance を使うパターン
    try:
        info = yf.Ticker(ticker).info
        return info.get("shortName") or ticker
    except:
        return ticker


tickers = [
"4151.T","4502.T","4503.T","4506.T","4507.T","4519.T","4523.T","4568.T","4578.T",
"4062.T","6479.T","6501.T","6503.T","6504.T","6506.T","6526.T","6645.T","6674.T","6701.T",
"6702.T","6723.T","6724.T","6752.T","6753.T","6758.T","6762.T","6770.T","6841.T","6857.T",
"6861.T","6902.T","6920.T","6952.T","6954.T","6963.T","6971.T","6976.T","6981.T","7735.T",
"7751.T","7752.T","8035.T",
"7201.T","7202.T","7203.T","7205.T","7211.T","7261.T","7267.T","7269.T","7270.T","7272.T",
"4543.T","4902.T","6146.T","7731.T","7733.T","7741.T",
"9432.T","9433.T","9434.T","9984.T",
"5831.T","7186.T","8304.T","8306.T","8308.T","8309.T","8316.T","8331.T","8354.T","8411.T",
"8253.T","8591.T","8697.T",
"8601.T","8604.T",
"8630.T","8725.T","8750.T","8766.T","8795.T",
"1332.T",
"2002.T","2269.T","2282.T","2501.T","2502.T","2503.T","2801.T","2802.T","2871.T","2914.T",
"3086.T","3092.T","3099.T","3382.T","7453.T","8233.T","8252.T","8267.T","9843.T","9983.T",
"2413.T","2432.T","3659.T","3697.T","4307.T","4324.T","4385.T","4661.T","4689.T","4704.T",
"4751.T","4755.T","6098.T","6178.T","6532.T","7974.T","9602.T","9735.T","9766.T",
"1605.T",
"3401.T","3402.T",
"3861.T",
"3405.T","3407.T","4004.T","4005.T","4021.T","4042.T","4043.T","4061.T","4063.T","4183.T",
"4188.T","4208.T","4452.T","4901.T","4911.T","6988.T",
"5019.T","5020.T",
"5101.T","5108.T",
"5201.T","5214.T","5233.T","5301.T","5332.T","5333.T",
"5401.T","5406.T","5411.T",
"3436.T","5706.T","5711.T","5713.T","5714.T","5801.T","5802.T","5803.T",
"2768.T","8001.T","8002.T","8015.T","8031.T","8053.T","8058.T",
"1721.T","1801.T","1802.T","1803.T","1808.T","1812.T","1925.T","1928.T","1963.T",
"5631.T","6103.T","6113.T","6273.T","6301.T","6302.T",
"6305.T","6326.T","6361.T","6367.T","6471.T",
"6472.T","6473.T","7004.T","7011.T","7013.T",
"7012.T","7832.T","7911.T","7912.T","7951.T",
"3289.T","8801.T","8802.T","8804.T","8830.T",
"9001.T","9005.T","9007.T","9008.T","9009.T",
"9020.T","9021.T","9022.T","9064.T","9147.T",
"9101.T","9104.T","9107.T","9201.T","9202.T",
"9501.T","9502.T","9503.T","9531.T","9532.T",
"6594.T","7564.T","6240.T","7532.T","3116.T"
]


results = []
print("分析を開始します...")
for t in tickers:
    res = analyze_stock_combined(t)
    results.append(res)

df_results = pd.DataFrame(results)

# 出力用ディレクトリ作成
os.makedirs("public", exist_ok=True)

if not df_results.empty:
    # "トレンド判定", "RSI" をリストに追加して、画面に表示されるようにしました
    first_cols = ["ticker", "company_name", "総合判断", "現在価格", "予測レンジ(1年後)", "年率HV", "トレンド判定", "RSI"]
    valid_cols = first_cols  # σ判定の列カット
    df_results = df_results.reindex(columns=valid_cols, fill_value="-")

    # 存在しない列は無視してdf作成
    df_results = df_results.reindex(columns=valid_cols, fill_value="-")

    # フィルタリングとソート
    df_picks = df_results.copy()

    # フィルタリングとソート（オススメ順）
    df_picks = df_picks.sort_values(by="総合判断", ascending=False, key=lambda col: col.map({
        # --- 🟢 買うチャンス ---
        "😍 超チャンス！バーゲンセール中": 10,
        "🛒 いい波きてる！買ってみる？": 9,
        "✨ 順調だよ（持ってるならキープ）": 8,
        
        # --- 🟡 様子見（何もしない） ---
        "🤔 よくわからない（今はパス）": 5,
        "✋ 高すぎ！今はガマン（買うな）": 4,
        "🙅‍♂️ ダメそう（手を出さないで）": 3,
        "💣 落ちてる最中（触るとケガするよ）": 2,

        # --- 🔴 売る・逃げる（警告） ---
        "🎰 一か八かの賭け（リバウンド狙い）": 1,
        "💰 勝ち逃げしよう（利益確定）": 0,
        "💨 今すぐ逃げて！（損切りチャンス）": -1,
        "🚨 警報！バブル崩壊かも（すぐ売れ）": -2
        }).fillna(0))
    
    # --- 【変更点1】 Google Financeへのリンク生成関数 ---
    def make_clickable_ticker(ticker_str):
        # 9984.T -> 9984 (数字のみ抽出)
        code = ticker_str.replace(".T", "")
        # Google FinanceのURL形式を作成
        url = f"https://www.google.com/finance/quote/{code}:TYO?authuser=0"
        # HTMLの<a>タグを作成（target="_blank"で別タブで開くように設定）
        return f'<a href="{url}" target="_blank" class="ticker-link">{ticker_str}</a>'

    # --- 【変更点2】 ticker列にリンク生成関数を適用 ---
    # .copy() をつけてSettingWithCopyWarningを回避
    df_picks = df_picks.copy() 
    df_picks["ticker"] = df_picks["ticker"].apply(make_clickable_ticker)

    # 現在時刻 (JST)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # --- 【変更点3】 escape=False を追加してHTMLタグを有効化 ---
    html_table = df_picks.to_html(index=False, classes="table_style", border=0, escape=False)

    description = """
    <h2>📌 3秒でわかる用語解説</h2>
    <ul>
    <li><b>現在価格</b> ➔ このレポートを作成した時点（上の最終更新日時）の価格です。<br>
        <span style="font-size:0.85em; color:#d9534f;">※あなたが今見ている瞬間のリアルタイム株価ではありません。</span></li>
    <li><b>予測レンジ</b> ➔ 統計上の「これ以上は上がらない/下がらない」の目安ライン。</li>
    <li><b>年率HV</b> ➔ 銘柄の性格。数値が高いほどハイリスク・ハイリターン。</li>
    <li><b>トレンド判定</b> ➔ 今の流れが「上り坂（強気）」か「下り坂（弱気）」か。25日平均線が基準です。</li>
    <li><b>RSI</b> ➔ 30以下なら「バーゲンセール？」、70以上なら「バブル？」のサイン。</li>
    </ul>
    <p style="font-size:0.85em; color:#666;">※これらは過去の動きに基づいた計算結果であり、未来を保証するものではありません。</p>
    """

    disclaimer = """
    【ゆるい注意書き】
    
    この分析結果は、作者が「たぶん合ってる…はず…？」と願いながら育てたものです。
    大根のようにまっすぐでもなく、ほうれん草のように栄養満点でもなく、
    たぶん“かぶ”くらいの信頼度です。つまり、食べられるけど万能ではありません。
    
    計算式はマジメですが、作者の数学力・プログラミング力・投資センスは
    かぶの葉っぱくらいの頼りなさです。
    見た目は立派でも、油断するとベランダで萎れます。
    
    このツールは過去データを勝手に計算しているだけで、
    未来を当てるものではありません。
    株価は食べるかぶよりずっと気まぐれで、
    時々こちらを笑いながら地中深く潜ります。
    
    この情報を信じて大損しても、
    作者は画面の前で「えっ…ごめん…」と申し訳なさメンタルに漬かるだけで、
    損失を補填する能力はありません。
    
    投資判断は必ずあなた自身の頭（たぶんかぶより賢い）でお願いします。
    そして、このツールの無断転載・販売・「この人が推奨してました！」とSNSで晒す行為は
    ぬか漬けに生クリームを入れるくらいやめたほうがいい行為です。
    
    ほどよく使い、ほどよく疑い、ほどよく笑ってください。
    """
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>日本株シグナル分析</title>
        <link rel="icon" href="/daily-stock-analysis/favicon.png" type="image/png">
        <style>
            body {{ font-family: sans-serif; padding: 20px; background-color: #f4f4f9; }}
            h1 {{ color: #333; font-size: 1.5em; }}
            .update-time {{ color: #666; font-size: 0.8em; margin-bottom: 20px; }}
            .table_style {{
                width: 100%; border-collapse: collapse; margin-top: 20px;
                background-color: #fff; box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }}
            .table_style th {{ background-color: #007bff; color: #fff; padding: 10px; text-align: left; }}
            .table_style td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
            .table_style tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .table-container {{ overflow-x: auto; }}

            /* リンクの見栄えを良くするCSS追加 */
            .ticker-link {{
                color: #007bff;
                text-decoration: none;
                font-weight: bold;
            }}
            .ticker-link:hover {{
                text-decoration: underline;
                color: #0056b3;
            }}

            .description {{
                background: #eef5ff;
                border-left: 5px solid #3a78ff;
                padding: 15px;
                margin-bottom: 25px;
                line-height: 1.6;
                font-size: 0.9em;
            }}

    
            /* 注意書きのデザイン */
            .disclaimer {{
                margin-top: 40px;
                padding: 20px;
                background: #fff6dc;
                border-left: 6px solid #f0b400;
                white-space: pre-wrap;
                font-size: 0.85em;
                line-height: 1.6em;
            }}
        </style>
    </head>
    <body>
        <h1>📈 日本株 朝イチ分析レポート</h1>
        <div class="update-time">最終更新: {now_str} (JST)</div>
        <div class="description">
            {description}
        </div>
        <div class="table-container">
            {html_table}
        </div>
        <div class="disclaimer">{disclaimer}</div>
    </body>
    </html>
    """
    
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("HTMLファイルの生成が完了しました。")
else:
    print("データが取得できませんでした。")
