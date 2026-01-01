import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta

WINDOWS = {"1mo": 20, "3mo": 60, "6mo": 120}
WEIGHTS = {"1mo": 3.0, "3mo": 2.0, "6mo": 1.0}

def add_indicators_strict(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Close" not in df.columns:
        raise ValueError("Closeがありません")
    close = df["Close"].astype(float)
    adj = df["Adj Close"].astype(float) if "Adj Close" in df.columns else close

    df["_CLOSE"] = close
    df["_ADJ"] = adj
    df["_LOGRET"] = np.log(adj / adj.shift(1))

    for name, days in WINDOWS.items():
        vol_excl_today = df["_LOGRET"].shift(1).rolling(days).std()
        center = close.shift(1)
        sigma1 = center * vol_excl_today

        df[f"upper_1_{name}"] = center + sigma1
        df[f"upper_2_{name}"] = center + 2 * sigma1
        df[f"lower_1_{name}"] = center - sigma1
        df[f"lower_2_{name}"] = center - 2 * sigma1

    df["SMA25"] = adj.rolling(25).mean()

    window = 14
    delta = adj.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/window, min_periods=window).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/window, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    df["RSI"] = rsi.fillna(100.0)

    return df

def sigma_level_from_row(row, name: str) -> int:
    price = row["_CLOSE"]
    l2 = row.get(f"lower_2_{name}", np.nan)
    l1 = row.get(f"lower_1_{name}", np.nan)
    u1 = row.get(f"upper_1_{name}", np.nan)
    u2 = row.get(f"upper_2_{name}", np.nan)
    if np.isnan(price) or np.isnan(l2) or np.isnan(l1) or np.isnan(u1) or np.isnan(u2):
        return 0
    if price < l2: return 2
    if price < l1: return 1
    if price > u2: return -2
    if price > u1: return -1
    return 0

def judge_from_row(row) -> str:
    price = row["_ADJ"]
    sma25 = row["SMA25"]
    rsi = row["RSI"]
    if np.isnan(price) or np.isnan(sma25) or np.isnan(rsi):
        return "🤔 よくわからない（今はパス）"

    is_trend_up = price > sma25

    lvl = {}
    for name in WINDOWS.keys():
        lvl[name] = sigma_level_from_row(row, name)

    avg_sigma = (lvl["1mo"] * WEIGHTS["1mo"] + lvl["3mo"] * WEIGHTS["3mo"] + lvl["6mo"] * WEIGHTS["6mo"]) / sum(WEIGHTS.values())

    is_cheap = (avg_sigma >= 0.6)
    is_expensive = (avg_sigma <= -0.8)

    judge = "🤔 よくわからない（今はパス）"

    if is_trend_up:
        # 😍：ほんとに押し目で拾う
        if avg_sigma >= 0.7 and rsi < 45:
            judge = "😍 超チャンス！バーゲンセール中"
        # 🛒：割安だが過熱前の波に乗る
        elif avg_sigma >= 0.5 and rsi < 60:
            judge = "🛒 いい波きてる！買ってみる？"
        # 追加：上昇トレンド中でも過熱と割高なら利益確定
        elif rsi > 70 and avg_sigma <= -0.3:
            judge = "💰 勝ち逃げしよう（利益確定）"

        elif is_expensive and rsi <= 75:
            judge = "✋ 高すぎ！今はガマン（買うな）"

        else:
            judge = "✨ 順調だよ（持ってるならキープ）"
    else:
        if is_cheap:
            if rsi < 25:
                judge = "🎰 一か八かの賭け（リバウンド狙い）"
            else:
                judge = "💣 落ちてる最中（触るとケガするよ）"
        elif is_expensive:
            judge = "💨 今すぐ逃げて！（損切りチャンス）"
        else:
            judge = "🙅‍♂️ ダメそう（手を出さないで）"

    if rsi > 85:
        judge = "🚨 警報！バブル崩壊かも（すぐ売れ）"

    return judge

def action_from_judge(judge: str, treat_gamble_as_buy: bool = False) -> str:
    # ---- 修正箇所ここから ----
    # "🛒" (いい波) を削除し、"😍" (超チャンス) のみBUYにします
    if judge.startswith("😍") or judge.startswith("🛒"):
        return "BUY"
    # ---- 修正箇所ここまで ----

    if treat_gamble_as_buy and judge.startswith("🎰"):
        return "BUY"
    if judge.startswith("💰") or judge.startswith("💨") or judge.startswith("🚨"):
        return "SELL"
    return "HOLD"

def run_strict_backtest_with_combined_judge(
    tickers,
    start_date,
    end_date,
    initial_capital=1_000_000,
    unit=100,
    fee_rate=0.0,
    slippage_rate=0.0,
    treat_gamble_as_buy=False,
):
    data_map = {}
    fetch_start = (pd.to_datetime(start_date) - timedelta(days=250)).strftime("%Y-%m-%d")

    for ticker in tickers:
        try:
            df = yf.download(ticker, start=fetch_start, end=end_date, progress=False, auto_adjust=False)
            if df.empty:
                continue
            df = add_indicators_strict(df)
            data_map[ticker] = df
        except Exception:
            continue

    if not data_map:
        return 0.0, initial_capital, pd.DataFrame()

    all_dates = sorted(list(set().union(*[df.index for df in data_map.values()])))
    sim_dates = [d for d in all_dates if d >= pd.to_datetime(start_date)]

    cash = float(initial_capital)
    portfolio = {t: {"shares": 0, "avg_price": 0.0} for t in data_map.keys()}
    trades = []

    for exec_date in sim_dates:
        i = all_dates.index(exec_date)
        if i == 0:
            continue
        prev_date = all_dates[i - 1]

        for ticker, df in data_map.items():
            if prev_date not in df.index or exec_date not in df.index:
                continue

            row_prev = df.loc[prev_date]
            judge = judge_from_row(row_prev)
            action = action_from_judge(judge, treat_gamble_as_buy=treat_gamble_as_buy)

            open_price = float(df.loc[exec_date, "Open"])
            if np.isnan(open_price):
                continue

            shares = portfolio[ticker]["shares"]
            buy_px = open_price * (1.0 + slippage_rate)
            sell_px = open_price * (1.0 - slippage_rate)

            if action == "BUY":
                cost = buy_px * unit
                fee = cost * fee_rate
                if cash >= cost + fee:
                    old_shares = portfolio[ticker]["shares"]
                    old_avg = portfolio[ticker]["avg_price"]
                    cash -= (cost + fee)
                    new_shares = old_shares + unit
                    new_avg = ((old_shares * old_avg) + cost) / new_shares
                    portfolio[ticker]["shares"] = new_shares
                    portfolio[ticker]["avg_price"] = new_avg
                    trades.append({
                        "date": exec_date, "ticker": ticker,
                        "judge": judge, "action": "BUY",
                        "shares": unit, "price": buy_px,
                        "fee": fee, "profit": 0.0,
                        "trigger": "PrevDayJudge",
                    })

            elif action == "SELL" and shares > 0:
                avg = portfolio[ticker]["avg_price"]
                proceeds = sell_px * shares
                fee = proceeds * fee_rate
                cash += (proceeds - fee)
                trade_profit = (sell_px - avg) * shares - fee
                portfolio[ticker]["shares"] = 0
                portfolio[ticker]["avg_price"] = 0.0
                trades.append({
                    "date": exec_date, "ticker": ticker,
                    "judge": judge, "action": "SELL",
                    "shares": shares, "price": sell_px,
                    "fee": fee, "profit": trade_profit,
                    "trigger": "PrevDayJudge",
                })

    last_date = sim_dates[-1]
    stock_value = 0.0
    for ticker, pos in portfolio.items():
        if pos["shares"] <= 0:
            continue
        df = data_map[ticker]
        px = float(df.loc[last_date, "Close"]) if last_date in df.index else float(df.iloc[-1]["Close"])
        stock_value += pos["shares"] * px

    final_total = cash + stock_value
    profit = final_total - initial_capital
    return profit, final_total, pd.DataFrame(trades)

# ---- 実行設定 ----

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

profit, final_value, trades = run_strict_backtest_with_combined_judge(
    tickers,
    start_date="2025-10-01",
    end_date="2025-11-01",
    initial_capital=1_000_000,
    unit=100,
    fee_rate=0.0,
    slippage_rate=0.0,
    treat_gamble_as_buy=False,
)

print(f"最終総資産: {final_value:,.0f}円 / 総損益: {profit:,.0f}円")
if not trades.empty:
    print(trades.tail(20).to_string(index=False))
else:
    print("取引はありませんでした。条件が厳しすぎる可能性があります。")
