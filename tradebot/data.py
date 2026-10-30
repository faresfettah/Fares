import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def load_csv(path: str) -> pd.DataFrame:
    """CSV avec colonnes timestamp/date + open, high, low, close, volume."""
    df = pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    time_col = next((c for c in ("timestamp", "date", "datetime", "time") if c in df.columns), None)
    if time_col is None:
        raise ValueError("Le CSV doit contenir une colonne timestamp/date")
    col = df[time_col]
    df.index = pd.to_datetime(col, unit="ms") if np.issubdtype(col.dtype, np.number) else pd.to_datetime(col)
    missing = set(OHLCV) - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}")
    return df[OHLCV].astype(float).sort_index()


def ohlcv_to_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp"] + OHLCV)
    df.index = pd.to_datetime(df["timestamp"], unit="ms")
    return df[OHLCV].astype(float)


def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
    """Télécharge l'historique via ccxt, en paginant si nécessaire."""
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - limit * tf_ms
    rows = []
    while len(rows) < limit:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=min(1000, limit - len(rows)))
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + tf_ms
        if len(batch) < 2:
            break
    df = ohlcv_to_frame(rows)
    return df[~df.index.duplicated()]


def synthetic(n: int = 2000, seed: int = 42, start_price: float = 100.0, freq: str = "1h") -> pd.DataFrame:
    """Marché simulé (régimes de tendance + bruit) pour tester sans connexion."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.002, n // 200 + 1), 200)[:n]
    rets = drift + rng.normal(0, 0.01, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, 0.005, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.date_range("2024-01-01", periods=n, freq=freq)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 1000, n)},
        index=idx,
    )
