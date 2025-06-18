import time, requests, csv, schedule
from datetime import datetime
import pandas as pd
import ta
from binance.client import Client
from config import BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Gagal kirim pesan: {e}")

def get_klines(symbol, interval, limit=100):
    raw = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return df

def get_all_symbols():
    info = client.futures_exchange_info()
    return [
        s['symbol'] for s in info['symbols']
        if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT'
    ]

def analisa(symbol):
    tfs = ['15m', '1h', '4h']
    arah = None
    score = 0

    for tf in tfs:
        df = get_klines(symbol, tf)
        close = df['close']
        ema9 = ta.trend.EMAIndicator(close, 9).ema_indicator()
        ema21 = ta.trend.EMAIndicator(close, 21).ema_indicator()
        rsi = ta.momentum.RSIIndicator(close).rsi()
        bb = ta.volatility.BollingerBands(close)
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()

        last = df.iloc[-1]

        trend = 'LONG' if ema9.iloc[-1] > ema21.iloc[-1] else 'SHORT'
        if arah is None:
            arah = trend
        elif arah != trend:
            return None

        rsi_val = rsi.iloc[-1]
        if arah == 'LONG' and rsi_val > 70:
            return None
        if arah == 'SHORT' and rsi_val < 30:
            return None

        bb_break = (last['close'] > bb.bollinger_hband().iloc[-1]) if arah == 'LONG' else (last['close'] < bb.bollinger_lband().iloc[-1])
        if bb_break:
            score += 1

    close = df['close'].iloc[-1]
    atr_val = atr.iloc[-1]

    tp1 = round(close + atr_val * 0.5, 6) if arah == 'LONG' else round(close - atr_val * 0.5, 6)
    tp2 = round(close + atr_val * 1.0, 6) if arah == 'LONG' else round(close - atr_val * 1.0, 6)
    tp3 = round(close + atr_val * 1.5, 6) if arah == 'LONG' else round(close - atr_val * 1.5, 6)
    sl = round(close - atr_val * 1.0, 6) if arah == 'LONG' else round(close + atr_val * 1.0, 6)

    leverage = "25x" if atr_val/close < 0.01 else "20x" if atr_val/close < 0.02 else "15x" if atr_val/close < 0.03 else "10x"

    acc = min(100, 70 + score * 10)

    return {
        "symbol": symbol,
        "arah": arah,
        "entry": f"{round(close, 6)} – {round(close, 6)}",
        "tp1": str(tp1),
        "tp2": str(tp2),
        "tp3": str(tp3),
        "sl": str(sl),
        "sr_support": str(min(df['low'])),
        "sr_resistance": str(max(df['high'])),
        "acc": f"{acc}%",
        "leverage": leverage
    }

def kirim_sinyal(data):
    msg = f"""
🔥 <b>NEW SIGNAL UPDATE</b> 🔥

#{data['symbol']} {'🔺' if data['arah']=='LONG' else '🔻'} <b>{data['arah']} {data['leverage']}</b>
📊 TF: 1H
🎯 ENTRY: {data['entry']}

🎯 TP1: {data['tp1']} (Cari Aman)
🎯 TP2: {data['tp2']} (Butuh Duit)
🎯 TP3: {data['tp3']} (Maruk)

🛑 SL: {data['sl']}
📉 S/R: {data['sr_support']} / {data['sr_resistance']}
📈 ACC: {data['acc']}
"""
    send_telegram(msg)
    log_sinyal(data)

def log_sinyal(data):
    with open("sinyal_log.csv", "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            data['symbol'], data['arah'], data['entry'],
            data['tp1'], data['tp2'], data['tp3'], data['sl'],
            data['acc'], data['leverage'], data['sr_support'],
            data['sr_resistance'], "PENDING"
        ])

def cek_hasil():
    df = pd.read_csv("sinyal_log.csv", header=None)
    df.columns = ['time', 'symbol', 'arah', 'entry', 'tp1', 'tp2', 'tp3', 'sl', 'acc', 'leverage', 'sr_support', 'sr_resistance', 'result']
    for i, row in df.iterrows():
        if row['result'] != 'PENDING':
            continue
        try:
            harga = get_klines(row['symbol'], '1m', 1)['close'].iloc[-1]
            harga = float(harga)
            arah = row['arah']
            tp = [float(row['tp1']), float(row['tp2']), float(row['tp3'])]
            sl = float(row['sl'])
            result = None
            if arah == 'LONG':
                if harga >= tp[2]: result = "TP3"
                elif harga >= tp[1]: result = "TP2"
                elif harga >= tp[0]: result = "TP1"
                elif harga <= sl: result = "SL"
            else:
                if harga <= tp[2]: result = "TP3"
                elif harga <= tp[1]: result = "TP2"
                elif harga <= tp[0]: result = "TP1"
                elif harga >= sl: result = "SL"
            if result:
                df.at[i, 'result'] = result
        except: pass
    df.to_csv("sinyal_log.csv", index=False, header=False)

def leaderboard():
    df = pd.read_csv("sinyal_log.csv", header=None)
    df.columns = ['time', 'symbol', 'arah', 'entry', 'tp1', 'tp2', 'tp3', 'sl', 'acc', 'leverage', 'sr_support', 'sr_resistance', 'result']
    df = df[df['result'] != 'PENDING']
    win = df[df['result'].str.contains("TP")]
    lose = df[df['result'] == 'SL']
    tops = win['symbol'].value_counts().head(5)
    msg = "🏆 <b>LEADERBOARD SINYAL</b>\n\n"
    for sym, count in tops.items():
        msg += f"✅ {sym}: {count}x TP\n"
    msg += f"\n❌ SL Total: {len(lose)} sinyal"
    send_telegram(msg)

def run():
    symbols = get_all_symbols()
    for sym in symbols:
        hasil = analisa(sym)
        if hasil and int(hasil['acc'].replace('%','')) >= 80:
            kirim_sinyal(hasil)

# ⏱️ Jadwal
schedule.every(1).hours.do(run)
schedule.every(2).hours.do(cek_hasil)
schedule.every().day.at("18:00").do(leaderboard)

while True:
    schedule.run_pending()
    time.sleep(1)
